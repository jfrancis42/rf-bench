#!/usr/bin/env python3
"""
Satellite Downlink Wideband Monitor

While the IC-9700 handles the satellite duplex uplink, use the RTL-SDR as a
wideband receiver to monitor the 70cm downlink passband. Captures the full
transponder bandwidth as IQ (up to 2.4 MHz wide), letting you see your own
signal plus other stations in the passband simultaneously — useful for linear
transponders.

This is complementary to the radio/satellite Doppler tracker — that script
commands the IC-9700 for TX/RX Doppler correction; this script provides a
real-time wideband waterfall view of the downlink transponder showing all
active stations at once.

Usage:
    # Monitor AO-91 downlink (FM, narrow)
    python satellite_monitor.py --sat AO-91 --gps

    # Monitor FO-29 linear transponder (USB, 50 kHz passband)
    python satellite_monitor.py --sat FO-29 --gps --bw 200e3

    # Custom frequency with Doppler tracking
    python satellite_monitor.py --freq 145.96e6 --bw 200e3 --gps --doppler --norad 43017

    # Record IQ to SigMF file during pass
    python satellite_monitor.py --sat AO-91 --gps --record ao91_pass.sigmf

    # Waterfall-only mode (no IQ recording)
    python satellite_monitor.py --sat FO-29 --gps --waterfall-only

All frequencies are in Hz. Use scientific notation: 145.960e6 = 145.960 MHz.
"""

import argparse
import math
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.colors import Normalize

try:
    import sigmf
    from sigmf import SigMFFile
    HAS_SIGMF = True
except ImportError:
    HAS_SIGMF = False

try:
    from skyfield.api import EarthSatellite, load, wgs84
    HAS_SKYFIELD = True
except ImportError:
    HAS_SKYFIELD = False

try:
    from rf_bench.gpsd import GPSD, GPSDNoFixError
    HAS_GPSD = True
except ImportError:
    HAS_GPSD = False

from rf_bench.rtlsdr import RTLSDR, RTLSDRError

# ── physics constants ─────────────────────────────────────────────────────────

_C_KM_S = 299_792.458  # speed of light, km/s

# ── Built-in satellite transponder database ──────────────────────────────────

TRANSPONDERS = {
    "AO-91": {
        "norad": 43017,
        "dl": 145_960_000,
        "mode": "FM",
        "bw": 30_000,  # FM voice channel
        "note": "Fox-1B downlink"
    },
    "AO-92": {
        "norad": 43137,
        "dl": 145_880_000,
        "mode": "FM",
        "bw": 30_000,
        "note": "Fox-1D downlink"
    },
    "SO-50": {
        "norad": 27607,
        "dl": 436_795_000,
        "mode": "FM",
        "bw": 30_000,
        "note": "SaudiSat-1C downlink"
    },
    "ISS": {
        "norad": 25544,
        "dl": 145_800_000,
        "mode": "FM",
        "bw": 30_000,
        "note": "ISS crossband repeater downlink"
    },
    "FO-29": {
        "norad": 24278,
        "dl": 435_850_000,
        "mode": "USB",
        "bw": 50_000,  # Linear transponder passband
        "note": "FujiOscar-29 linear transponder"
    },
    "AO-7": {
        "norad": 7530,
        "dl": 145_975_000,
        "mode": "USB",
        "bw": 50_000,
        "note": "AMSAT-OSCAR 7 Mode B downlink"
    },
}

# ── TLE fetch (simplified from satellite.py) ─────────────────────────────────

_TLE_CACHE = Path.home() / ".cache" / "rf-bench" / "tle"
_AMSAT_TLE_URL = "https://www.amsat.org/tle/current/nasabare.txt"
_SATNOGS_TLE_URL = "https://db.satnogs.org/api/tle/?format=json&norad_cat_id={norad}"

_REQUEST_HEADERS = {
    "User-Agent": "rf-bench/1.0 (satellite monitor; +https://github.com/jfrancis42/rf-bench)"
}


def _fetch_tle(norad: int) -> tuple[str, str, str]:
    """Fetch TLE for a NORAD catalog number. Returns (name, line1, line2)."""
    import requests

    # Try AMSAT group file first
    _TLE_CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = _TLE_CACHE / "nasabare.txt"

    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < 21600:
        # Use cached file if < 6 hours old
        lines = cache_file.read_text().strip().split("\n")
    else:
        # Fetch fresh
        resp = requests.get(_AMSAT_TLE_URL, headers=_REQUEST_HEADERS, timeout=10)
        resp.raise_for_status()
        cache_file.write_text(resp.text)
        lines = resp.text.strip().split("\n")

    # Parse TLE file (3-line groups)
    for i in range(0, len(lines) - 2, 3):
        name = lines[i].strip()
        line1 = lines[i + 1].strip()
        line2 = lines[i + 2].strip()

        if line1.startswith("1 ") and line2.startswith("2 "):
            # Extract NORAD from line1: "1 NNNNN"
            try:
                tle_norad = int(line1.split()[1].rstrip("U"))
                if tle_norad == norad:
                    return (name, line1, line2)
            except (IndexError, ValueError):
                continue

    # Fallback: SatNOGS API
    url = _SATNOGS_TLE_URL.format(norad=norad)
    resp = requests.get(url, headers=_REQUEST_HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data:
        tle = data[0]
        return (tle["tle0"], tle["tle1"], tle["tle2"])

    raise ValueError(f"No TLE found for NORAD {norad}")


def _doppler_rx_hz(f_nominal: float, range_rate_km_s: float) -> float:
    """Downlink Doppler shift: f_rx = f_nominal × (1 − range_rate / c)"""
    return f_nominal * (1.0 - range_rate_km_s / _C_KM_S)


def _range_rate_km_s(sat, observer, t) -> float:
    """Compute radial velocity (km/s) from satellite to observer at time t."""
    diff = sat - observer
    topo = diff.at(t)
    pos = topo.position.km
    vel = topo.velocity.km_per_s
    r_mag = np.linalg.norm(pos)
    if r_mag < 1e-6:
        return 0.0
    return np.dot(pos, vel) / r_mag


# ── Waterfall display ─────────────────────────────────────────────────────────

class WaterfallDisplay:
    """Real-time waterfall plot using matplotlib animation."""

    def __init__(self, center_freq: float, sample_rate: float,
                 history_lines: int = 200):
        self.center_freq = center_freq
        self.sample_rate = sample_rate
        self.history_lines = history_lines

        # Waterfall data buffer (rows × FFT bins)
        self.waterfall_data = None
        self.current_row = 0

        # Set up plot
        self.fig, (self.ax_spectrum, self.ax_waterfall) = plt.subplots(
            2, 1, figsize=(12, 8),
            gridspec_kw={'height_ratios': [1, 3]}
        )
        self.fig.suptitle(
            f"Satellite Downlink Monitor — {center_freq/1e6:.3f} MHz",
            fontsize=14, fontweight='bold'
        )

        # Spectrum plot (top)
        self.line_spectrum, = self.ax_spectrum.plot([], [], 'cyan', linewidth=0.8)
        self.ax_spectrum.set_ylabel("Power (dB)", fontsize=10)
        self.ax_spectrum.set_xlim(-sample_rate/2e3, sample_rate/2e3)
        self.ax_spectrum.set_ylim(-80, 0)
        self.ax_spectrum.grid(True, alpha=0.3)
        self.ax_spectrum.set_title("Instantaneous Spectrum", fontsize=11)

        # Waterfall plot (bottom)
        self.im_waterfall = None
        self.ax_waterfall.set_xlabel("Frequency Offset (kHz)", fontsize=10)
        self.ax_waterfall.set_ylabel("Time →", fontsize=10)
        self.ax_waterfall.set_title("Waterfall (newest at top)", fontsize=11)

        plt.tight_layout()

    def init_waterfall(self, fft_size: int):
        """Initialize waterfall buffer once FFT size is known."""
        if self.waterfall_data is None:
            self.waterfall_data = np.full(
                (self.history_lines, fft_size),
                -100.0,
                dtype=np.float32
            )

            extent = [
                -self.sample_rate / 2e3,
                self.sample_rate / 2e3,
                0,
                self.history_lines
            ]
            self.im_waterfall = self.ax_waterfall.imshow(
                self.waterfall_data,
                aspect='auto',
                extent=extent,
                origin='lower',
                cmap='viridis',
                vmin=-80,
                vmax=0,
                interpolation='none'
            )
            cbar = self.fig.colorbar(self.im_waterfall, ax=self.ax_waterfall)
            cbar.set_label('Power (dB)', fontsize=9)

    def update(self, freq_offset_khz: np.ndarray, power_db: np.ndarray):
        """Update both spectrum and waterfall with new FFT data."""
        # Update instantaneous spectrum
        self.line_spectrum.set_data(freq_offset_khz, power_db)

        # Update waterfall (roll buffer and insert new line at top)
        if self.waterfall_data is not None:
            self.waterfall_data = np.roll(self.waterfall_data, 1, axis=0)
            self.waterfall_data[0, :] = power_db
            self.im_waterfall.set_data(self.waterfall_data)

    def show_nonblocking(self):
        """Display the window without blocking."""
        plt.ion()
        plt.show(block=False)
        plt.pause(0.001)


# ── Main monitor loop ─────────────────────────────────────────────────────────

_running = True

def _sigint(_sig, _frame):
    global _running
    _running = False

signal.signal(signal.SIGINT, _sigint)


def monitor_satellite(
    sdr: RTLSDR,
    center_freq: float,
    sat_config: Optional[dict] = None,
    observer = None,
    satellite = None,
    ts = None,
    doppler_enabled: bool = False,
    record_path: Optional[Path] = None,
    waterfall_only: bool = False,
    fft_size: int = 2048,
    update_interval: float = 0.1
):
    """
    Monitor satellite downlink with optional Doppler tracking and recording.

    Args:
        sdr: RTLSDR instance
        center_freq: Nominal center frequency (Hz)
        sat_config: Satellite transponder config dict (optional)
        observer: Skyfield observer (for Doppler)
        satellite: Skyfield EarthSatellite (for Doppler)
        ts: Skyfield timescale (for Doppler)
        doppler_enabled: Apply Doppler correction to SDR center freq
        record_path: SigMF file stem for recording (optional)
        waterfall_only: Display only (no recording)
        fft_size: FFT size for waterfall
        update_interval: Display update period (seconds)
    """

    # Set up waterfall display
    display = WaterfallDisplay(center_freq, sdr._sample_rate)
    display.show_nonblocking()

    # Set up recording if requested
    rec_fh = None
    rec_samples = 0
    if record_path and not waterfall_only:
        data_path = record_path.with_suffix(".sigmf-data")
        rec_fh = open(data_path, "wb")
        print(f"Recording to {data_path.name}")

    # Main loop
    last_update = 0.0
    last_doppler_update = 0.0
    block_count = 0

    print(f"Monitoring {center_freq/1e6:.3f} MHz  (Ctrl-C to stop)")
    if doppler_enabled and satellite and observer and ts:
        print("Doppler tracking: ENABLED")

    try:
        for block in sdr.stream_iq(block_size=fft_size * 4):
            if not _running:
                break

            block_count += 1

            # Record IQ if requested
            if rec_fh:
                rec_fh.write(block.astype(np.complex64).tobytes())
                rec_samples += len(block)

            # Apply Doppler correction (every 1 second)
            if doppler_enabled and satellite and observer and ts:
                now = time.time()
                if now - last_doppler_update >= 1.0:
                    t = ts.now()
                    rr = _range_rate_km_s(satellite, observer, t)
                    corrected_freq = _doppler_rx_hz(center_freq, rr)

                    # Update SDR center frequency
                    sdr.set_center_freq(int(corrected_freq))

                    # Update display title
                    doppler_shift_khz = (corrected_freq - center_freq) / 1e3
                    display.fig.suptitle(
                        f"Satellite Downlink Monitor — "
                        f"{corrected_freq/1e6:.4f} MHz "
                        f"(Doppler: {doppler_shift_khz:+.1f} kHz)",
                        fontsize=14, fontweight='bold'
                    )

                    last_doppler_update = now

            # Update waterfall display
            now = time.time()
            if now - last_update >= update_interval:
                # Compute power spectrum
                fft = np.fft.fftshift(np.fft.fft(block[:fft_size]))
                power_db = 20 * np.log10(np.abs(fft) + 1e-10)
                freq_offset_khz = np.fft.fftshift(
                    np.fft.fftfreq(fft_size, 1.0 / sdr._sample_rate)
                ) / 1e3

                # Initialize waterfall on first update
                if display.waterfall_data is None:
                    display.init_waterfall(fft_size)

                # Update display
                display.update(freq_offset_khz, power_db)
                plt.pause(0.001)

                last_update = now

                # Print status
                elapsed = rec_samples / sdr._sample_rate if rec_samples > 0 else 0
                status = f"\r  Blocks: {block_count}  "
                if rec_fh:
                    status += f"Recorded: {elapsed:.1f}s  "
                print(status, end="", flush=True)

    finally:
        sdr.stop_stream()

        if rec_fh:
            rec_fh.close()
            print(f"\n\nRecorded {rec_samples:,} samples ({rec_samples/sdr._sample_rate:.1f}s)")

            # Write SigMF metadata
            if HAS_SIGMF:
                meta_path = record_path.with_suffix(".sigmf-meta")
                sigmf_meta = SigMFFile(
                    data_file=str(record_path.with_suffix(".sigmf-data")),
                    global_info={
                        sigmf.SigMFFile.DATATYPE_KEY: "cf32_le",
                        sigmf.SigMFFile.SAMPLE_RATE_KEY: sdr._sample_rate,
                        sigmf.SigMFFile.HW_KEY: f"RTL-SDR ({sdr.identify()['tuner_type']})",
                        sigmf.SigMFFile.AUTHOR_KEY: "rf-bench-satellite-monitor",
                        sigmf.SigMFFile.VERSION_KEY: "1.0.0",
                    }
                )
                sigmf_meta.add_capture(
                    0,
                    metadata={
                        sigmf.SigMFFile.FREQUENCY_KEY: center_freq,
                        sigmf.SigMFFile.DATETIME_KEY: datetime.now(timezone.utc).isoformat(),
                    }
                )
                if sat_config:
                    sigmf_meta.set_global_field("core:description",
                                               f"{sat_config.get('note', 'Satellite downlink')}")

                sigmf_meta.tofile(str(meta_path))
                print(f"Metadata: {meta_path.name}")

        print("\nMonitoring stopped.")
        print("Close matplotlib window to exit.")
        plt.ioff()
        plt.show()  # Keep window open until user closes


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Satellite downlink wideband monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Satellite selection
    sat_group = ap.add_mutually_exclusive_group()
    sat_group.add_argument("--sat", choices=list(TRANSPONDERS.keys()),
                          help="Built-in satellite name")
    sat_group.add_argument("--freq", type=float,
                          help="Custom downlink frequency in Hz")

    ap.add_argument("--norad", type=int,
                   help="NORAD catalog number (required if --freq and --doppler)")
    ap.add_argument("--bw", type=float, default=None,
                   help="Sample rate / bandwidth in Hz (default: auto from satellite)")

    # Location (for Doppler)
    loc_group = ap.add_mutually_exclusive_group()
    loc_group.add_argument("--gps", action="store_true",
                          help="Use gpsd for location (required for Doppler)")
    loc_group.add_argument("--lat", type=float,
                          help="Latitude in decimal degrees")
    ap.add_argument("--lon", type=float,
                  help="Longitude (required if --lat)")
    ap.add_argument("--alt", type=float, default=0.0,
                  help="Altitude in metres (default: 0)")

    # Doppler tracking
    ap.add_argument("--doppler", action="store_true",
                   help="Enable Doppler correction (requires location)")

    # Recording
    ap.add_argument("--record", type=str, metavar="STEM",
                   help="Record IQ to SigMF file (e.g., pass.sigmf)")
    ap.add_argument("--waterfall-only", action="store_true",
                   help="Display waterfall without recording")

    # RTL-SDR settings
    ap.add_argument("--gain", default="auto",
                   help="RTL-SDR gain in dB or 'auto' (default: auto)")
    ap.add_argument("--bias-tee", action="store_true",
                   help="Enable RTL-SDR bias tee for LNA power")
    ap.add_argument("--serial", help="RTL-SDR serial number")

    # Display
    ap.add_argument("--fft-size", type=int, default=2048,
                   help="FFT size for waterfall (default: 2048)")
    ap.add_argument("--update", type=float, default=0.1,
                   help="Display update interval in seconds (default: 0.1)")

    # Utilities
    ap.add_argument("--list-sats", action="store_true",
                   help="List built-in satellites and exit")

    args = ap.parse_args()

    # List satellites mode
    if args.list_sats:
        print("\nBuilt-in Satellites:")
        print(f"{'Name':<10} {'NORAD':<8} {'Downlink (MHz)':<16} {'Mode':<6} {'BW (kHz)':<10} Note")
        print("-" * 90)
        for name, cfg in TRANSPONDERS.items():
            print(f"{name:<10} {cfg['norad']:<8} {cfg['dl']/1e6:<16.3f} "
                  f"{cfg['mode']:<6} {cfg['bw']/1e3:<10.0f} {cfg['note']}")
        return

    # Validate arguments
    if not args.sat and not args.freq:
        ap.error("Must specify either --sat or --freq")

    if args.lat is not None and args.lon is None:
        ap.error("--lon required when --lat is specified")

    if args.doppler and not (args.gps or args.lat):
        ap.error("--doppler requires location (--gps or --lat/--lon)")

    if args.doppler and not HAS_SKYFIELD:
        ap.error("--doppler requires skyfield library (pip install skyfield)")

    if args.doppler and args.freq and not args.norad:
        ap.error("--doppler with --freq requires --norad")

    # Determine satellite config
    sat_config = None
    center_freq = None
    sample_rate = args.bw
    norad = args.norad

    if args.sat:
        sat_config = TRANSPONDERS[args.sat]
        center_freq = sat_config["dl"]
        norad = sat_config["norad"]
        if sample_rate is None:
            # Auto-select bandwidth: 200 kHz for linear, 50 kHz for FM
            sample_rate = 200_000 if sat_config["bw"] >= 40_000 else 50_000
    else:
        center_freq = args.freq
        if sample_rate is None:
            sample_rate = 200_000  # Default for custom frequency

    gain = args.gain if args.gain == "auto" else float(args.gain)

    # Set up location and Doppler tracking
    observer = None
    satellite = None
    ts = None

    if args.doppler:
        import requests
        from skyfield.api import load, wgs84

        ts = load.timescale(builtin=True)

        # Get observer location
        if args.gps:
            if not HAS_GPSD:
                print("Error: --gps requires rf-bench-drivers-gpsd", file=sys.stderr)
                sys.exit(1)

            gps = GPSD()
            print("Waiting for GPS fix...", end="", flush=True)
            try:
                gps.wait_for_fix(timeout=30)
                fix = gps.get_fix()
                observer = wgs84.latlon(
                    fix.latitude,
                    fix.longitude,
                    elevation_m=fix.altitude_m or 0.0
                )
                print(f" OK ({fix.latitude:.4f}, {fix.longitude:.4f})")
                gps.close()
            except GPSDNoFixError:
                print(" FAILED", file=sys.stderr)
                sys.exit(1)
        else:
            observer = wgs84.latlon(args.lat, args.lon, elevation_m=args.alt)

        # Fetch TLE and create satellite object
        try:
            name, line1, line2 = _fetch_tle(norad)
            satellite = EarthSatellite(line1, line2, name, ts)
            print(f"Loaded TLE for {name} (NORAD {norad})")
        except Exception as e:
            print(f"Error loading TLE for NORAD {norad}: {e}", file=sys.stderr)
            sys.exit(1)

    # Set up recording path
    record_path = None
    if args.record and not args.waterfall_only:
        record_path = Path(args.record)
        if not record_path.suffix:
            record_path = record_path.with_suffix(".sigmf")
        record_path = record_path.with_suffix("")  # Remove extension (will add .sigmf-data/.sigmf-meta)

    # Open RTL-SDR and start monitoring
    try:
        with RTLSDR(serial=args.serial) as sdr:
            sdr.set_center_freq(int(center_freq))
            sdr.set_sample_rate(int(sample_rate))
            sdr.set_gain(gain)
            if args.bias_tee:
                sdr.set_bias_tee(True)

            info = sdr.identify()
            print(f"\nRTL-SDR: {info['tuner_type']}")
            print(f"  Frequency: {info['center_freq']/1e6:.3f} MHz")
            print(f"  Sample rate: {info['sample_rate']/1e6:.2f} MS/s")
            print(f"  Gain: {info['gain']} dB")
            print()

            monitor_satellite(
                sdr=sdr,
                center_freq=center_freq,
                sat_config=sat_config,
                observer=observer,
                satellite=satellite,
                ts=ts,
                doppler_enabled=args.doppler,
                record_path=record_path,
                waterfall_only=args.waterfall_only,
                fft_size=args.fft_size,
                update_interval=args.update
            )

            if args.bias_tee:
                sdr.set_bias_tee(False)

    except RTLSDRError as e:
        print(f"RTL-SDR error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
