#!/usr/bin/env python3
"""
SWBC Scanner — KiwiSDR shortwave broadcast band scanner.

Scans international shortwave broadcast bands (120m–11m) looking for active AM
carriers.  Logs detected stations to SQLite and displays frequency, band, and
signal-to-noise ratio in the terminal.

Coverage: 14 SWBC bands from 2.3 MHz to 26.1 MHz.

Usage:
    python swbc_scanner.py                              # all bands, continuous loop
    python swbc_scanner.py --bands 49m,41m,31m,25m      # specific bands
    python swbc_scanner.py --once                        # single sweep and exit
    python swbc_scanner.py --host 10.1.0.5 --squelch 12
    python swbc_scanner.py --interval 600               # sweep every 10 minutes

Output:
    swbc.db   — SQLite log of all detections (default path)
"""

import argparse
import os
import signal
import sqlite3
import sys
import time
from collections import deque
from datetime import datetime, timezone

import numpy as np

from rf_bench.kiwisdr import KiwiSDR, KiwiSDRError, SAMPLE_RATE


# ── SWBC band definitions ─────────────────────────────────────────────────────

SWBC_BANDS = {
    "120m": (2_300_000,  2_495_000),
    "90m":  (3_200_000,  3_400_000),
    "75m":  (3_900_000,  4_000_000),
    "60m":  (4_750_000,  5_060_000),
    "49m":  (5_900_000,  6_200_000),
    "41m":  (7_200_000,  7_450_000),
    "31m":  (9_400_000,  9_900_000),
    "25m":  (11_600_000, 12_100_000),
    "22m":  (13_570_000, 13_870_000),
    "19m":  (15_100_000, 15_800_000),
    "16m":  (17_480_000, 17_900_000),
    "15m":  (18_900_000, 19_020_000),
    "13m":  (21_450_000, 21_850_000),
    "11m":  (25_600_000, 26_100_000),
}

DEFAULT_BANDS = list(SWBC_BANDS.keys())   # all bands by default

# International SWBC channel spacing is 5 kHz (ITU).
# Many broadcasters use 9 kHz spacing; some use 10 kHz.
# Default step of 9 kHz catches most carriers; use 5000 to be thorough (slow).
DEFAULT_STEP_HZ = 9_000


# ── well-known SWBC stations (for display annotation) ────────────────────────
# Keyed by exact frequency (Hz).  Only the most active / universally audible.
# This list will need periodic updates as broadcast schedules change.

KNOWN_STATIONS: dict[int, str] = {
    # WWV / WWVH (US time signals)
    2_500_000:  "WWV/WWVH 2.5 MHz",
    5_000_000:  "WWV/WWVH 5 MHz",
    10_000_000: "WWV/WWVH 10 MHz",
    15_000_000: "WWV/WWVH 15 MHz",
    20_000_000: "WWV 20 MHz",
    25_000_000: "WWV 25 MHz",
    # CHU Canada
    3_330_000:  "CHU 3.330 MHz",
    7_850_000:  "CHU 7.850 MHz",
    14_670_000: "CHU 14.670 MHz",
    # Radio New Zealand International
    9_765_000:  "RNZI 9.765 MHz",
    11_725_000: "RNZI 11.725 MHz",
    # Radio Habana Cuba
    6_000_000:  "RHC 6.000 MHz",
    6_165_000:  "RHC 6.165 MHz",
    9_535_000:  "RHC 9.535 MHz",
    11_760_000: "RHC 11.760 MHz",
    # China Radio International
    9_570_000:  "CRI 9.570 MHz",
    # Radio Exterior de Espana
    9_690_000:  "REE 9.690 MHz",
    # Voice of America
    17_895_000: "VOA 17.895 MHz",
    # Numbers stations (for when the SDR captures them by accident)
    4_625_000:  "UVB-76 (Russian beacon)",
}


# ── ANSI colours ──────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"
ORANGE = "\033[33m"
WHITE  = "\033[97m"

BAND_COLORS = {
    "120m": "\033[35m",
    "90m":  "\033[33m",
    "75m":  "\033[33m",
    "60m":  "\033[93m",
    "49m":  "\033[92m",
    "41m":  "\033[92m",
    "31m":  "\033[97m",
    "25m":  "\033[96m",
    "22m":  "\033[96m",
    "19m":  "\033[94m",
    "16m":  "\033[94m",
    "15m":  "\033[91m",
    "13m":  "\033[91m",
    "11m":  "\033[95m",
}


def _bar(snr: float, lo: float = 0.0, hi: float = 35.0, width: int = 10) -> str:
    frac = max(0.0, min(1.0, (snr - lo) / (hi - lo)))
    filled = int(frac * width)
    return "█" * filled + "░" * (width - filled)


def _band_for_freq(freq_hz: int) -> str:
    for band, (lo, hi) in SWBC_BANDS.items():
        if lo <= freq_hz <= hi:
            return band
    return "?"


def _nearest_known(freq_hz: int, tolerance_hz: int = 4_000) -> str | None:
    """Return the name of a known station near freq_hz, or None."""
    best = min(KNOWN_STATIONS.keys(), key=lambda f: abs(f - freq_hz), default=None)
    if best is not None and abs(best - freq_hz) <= tolerance_hz:
        return KNOWN_STATIONS[best]
    return None


# ── SQLite ────────────────────────────────────────────────────────────────────

def _open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT NOT NULL,
            ts_unix     REAL NOT NULL,
            freq_hz     INTEGER NOT NULL,
            freq_mhz    REAL,
            band        TEXT,
            power_dbfs  REAL,
            snr_db      REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts   ON detections (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_freq ON detections (freq_hz)")
    conn.commit()
    return conn


def _log_detection(conn: sqlite3.Connection, freq_hz: int, band: str,
                   power_dbfs: float, snr_db: float) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO detections "
        "(ts_utc, ts_unix, freq_hz, freq_mhz, band, power_dbfs, snr_db) "
        "VALUES (?,?,?,?,?,?,?)",
        (now.isoformat(), now.timestamp(),
         freq_hz, round(freq_hz / 1e6, 6), band,
         round(power_dbfs, 2), round(snr_db, 2)),
    )
    conn.commit()


# ── band sweep ────────────────────────────────────────────────────────────────

def _sweep_band(kiwi: KiwiSDR, band: str, start_hz: int, stop_hz: int,
                step_hz: int, dwell_samples: int,
                squelch_db: float) -> list[tuple[int, float, float]]:
    """
    Sweep one SWBC band.  Returns list of (freq_hz, power_dbfs, snr_db) tuples.

    Uses a simple peak-above-median detector.  SWBC signals are AM carriers,
    which produce a strong spectral line at the carrier frequency — ideal for
    this kind of FFT-peak detection.
    """
    hits: list[tuple[int, float, float]] = []
    freq = start_hz
    while freq <= stop_hz:
        try:
            kiwi.set_center_freq(freq)
            time.sleep(0.04)   # FPGA settle
            iq = kiwi.capture_iq(dwell_samples)
        except KiwiSDRError:
            freq += step_hz
            continue

        n = len(iq)
        window  = np.hanning(n).astype(np.float32)
        fft_raw = np.fft.fftshift(np.fft.fft(iq * window))
        psd_db  = 10.0 * np.log10(
            np.maximum(np.abs(fft_raw) ** 2 / np.sum(window ** 2), 1e-30)
        )
        noise = float(np.median(psd_db))
        peak  = float(np.max(psd_db))
        snr   = peak - noise

        if snr >= squelch_db:
            hits.append((freq, peak, snr))

        freq += step_hz

    return hits


# ── display ───────────────────────────────────────────────────────────────────

def _format_detection(freq_hz: int, band: str, snr_db: float,
                      power_dbfs: float, ts_str: str,
                      use_color: bool) -> str:
    mhz      = freq_hz / 1e6
    bar      = _bar(snr_db)
    known    = _nearest_known(freq_hz)
    note     = f"  {known}" if known else ""
    if use_color:
        col = BAND_COLORS.get(band, "")
        note_col = DIM + note + RESET if note else ""
        return (f"{DIM}[{ts_str}]{RESET} "
                f"{col}{BOLD}{band:<4}{RESET}  "
                f"{mhz:10.4f} MHz  "
                f"SNR {snr_db:+5.1f} dB  pwr {power_dbfs:+6.1f} dBFS  "
                f"{col}{bar}{RESET}"
                f"{note_col}")
    return (f"[{ts_str}] {band:<4}  {mhz:10.4f} MHz  "
            f"SNR {snr_db:+5.1f} dB  pwr {power_dbfs:+6.1f} dBFS  {bar}{note}")


def _print_sweep_header(bands: list[str], use_color: bool) -> None:
    bands_str = " ".join(bands)
    title = BOLD + "SWBC Scanner" + RESET if use_color else "SWBC Scanner"
    print(f"\n  {title}  —  sweeping: {bands_str}")
    print(f"  {'─'*74}")


def _print_status(sweep: int, elapsed: float, bands: list[str],
                  total: int, recent: deque, hits_by_freq: dict,
                  next_sweep_in: float, use_color: bool,
                  loop_mode: bool) -> None:
    if use_color:
        os.system("clear")
    else:
        print("\033[H\033[J", end="")

    bands_str = " ".join(bands)
    title = (BOLD + "SWBC Scanner" + RESET) if use_color else "SWBC Scanner"
    print(f"\n  {title}  sweep #{sweep}  |  bands: {bands_str}  |  "
          f"sweep: {elapsed:.1f}s  |  detections: {total}")

    if loop_mode and next_sweep_in > 0:
        m, s = divmod(int(next_sweep_in), 60)
        print(f"  Next sweep in: {m}m {s:02d}s")

    print(f"  {'─'*74}")

    if recent:
        for line in recent:
            print(f"  {line}")
    else:
        print("  (no activity this sweep)")

    print(f"  {'─'*74}")

    if hits_by_freq:
        top = sorted(hits_by_freq.items(), key=lambda x: -x[1])[:5]
        top_strs = []
        for freq_hz, count in top:
            band = _band_for_freq(freq_hz)
            col  = BAND_COLORS.get(band, "") if use_color else ""
            rst  = RESET if use_color else ""
            known = _nearest_known(freq_hz)
            label = known if known else f"{freq_hz/1e6:.4f} MHz"
            top_strs.append(f"{col}{label}{rst} ({count})")
        print(f"\n  Top: " + "  |  ".join(top_strs))

    print(f"\n  Press Ctrl-C to stop.\n")


# ── main loop ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    # Resolve band list
    bands = [b.strip() for b in args.bands.split(",")]
    invalid = [b for b in bands if b not in SWBC_BANDS]
    if invalid:
        print(f"ERROR: unknown bands: {', '.join(invalid)}")
        print(f"  Valid: {', '.join(SWBC_BANDS.keys())}")
        sys.exit(1)

    conn = _open_db(args.log)
    print(f"\n  SWBC Scanner  —  bands: {' '.join(bands)}")
    print(f"  Host: {args.host}:{args.port}  |  squelch: +{args.squelch:.0f} dB")
    print(f"  Step: {args.step} Hz  |  dwell: {args.dwell} samples "
          f"({args.dwell / SAMPLE_RATE * 1000:.0f} ms)")
    print(f"  Mode: {'single sweep' if args.once else f'loop, interval {args.interval}s'}")
    print(f"  SQLite: {args.log}")
    print(f"  Connecting to KiwiSDR...")

    try:
        kiwi = KiwiSDR(args.host, port=args.port, password=args.password,
                       channel=0, passband_hz=5000)
    except KiwiSDRError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    recent: deque[str]           = deque(maxlen=25)
    hits_by_freq: dict[int, int] = {}
    total_detections             = 0
    sweep_count                  = 0
    stop                         = False

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    print(f"  Connected.  Starting sweep...\n  Press Ctrl-C to stop.\n")

    try:
        while not stop:
            t0 = time.monotonic()
            sweep_count += 1
            sweep_hits: list[tuple[str, int, float, float]] = []  # (ts, freq_hz, power, snr)

            if use_color:
                os.system("clear")
            _print_sweep_header(bands, use_color)

            for band in bands:
                if stop:
                    break
                lo, hi = SWBC_BANDS[band]
                try:
                    hits = _sweep_band(kiwi, band, lo, hi,
                                       args.step, args.dwell, args.squelch)
                except KiwiSDRError as e:
                    print(f"  [sweep error on {band}: {e}]")
                    continue

                for freq_hz, power, snr in hits:
                    ts_str = datetime.now().strftime("%H:%M:%S")
                    _log_detection(conn, freq_hz, band, power, snr)
                    line = _format_detection(freq_hz, band, snr, power, ts_str, use_color)
                    recent.append(line)
                    hits_by_freq[freq_hz] = hits_by_freq.get(freq_hz, 0) + 1
                    total_detections += 1
                    sweep_hits.append((ts_str, freq_hz, power, snr))
                    print(f"  {line}")

            elapsed = time.monotonic() - t0

            if args.once:
                break

            # Wait for the next sweep interval
            wait_for = max(0.0, args.interval - elapsed)
            deadline = time.monotonic() + wait_for

            while not stop and time.monotonic() < deadline:
                _print_status(sweep_count, elapsed, bands, total_detections,
                              recent, hits_by_freq,
                              deadline - time.monotonic(), use_color, loop_mode=True)
                time.sleep(min(5.0, max(0.1, deadline - time.monotonic())))

    except Exception as e:
        print(f"\n  Error: {e}")
    finally:
        kiwi.close()
        conn.close()

    # Final summary
    print(f"\n  SWBC Scanner stopped.")
    print(f"  Sweeps: {sweep_count}  |  Total detections: {total_detections}")
    if hits_by_freq:
        top = sorted(hits_by_freq.items(), key=lambda x: -x[1])[:5]
        print(f"  Top frequencies:")
        for freq_hz, count in top:
            band  = _band_for_freq(freq_hz)
            known = _nearest_known(freq_hz)
            label = known if known else f"{freq_hz/1e6:.4f} MHz"
            print(f"    {freq_hz/1e6:10.4f} MHz  {band:<5}  {count:4d} detections"
                  + (f"  ({label})" if not known else ""))
    print(f"  Database: {args.log}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="SWBC Scanner — KiwiSDR shortwave broadcast band scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
SWBC bands: 120m 90m 75m 60m 49m 41m 31m 25m 22m 19m 16m 15m 13m 11m

Examples:
  python swbc_scanner.py
  python swbc_scanner.py --bands 49m,41m,31m,25m,19m
  python swbc_scanner.py --once
  python swbc_scanner.py --host 10.1.0.5 --squelch 12
  python swbc_scanner.py --step 5000 --dwell 4000 --squelch 8
  python swbc_scanner.py --interval 600   # sweep every 10 minutes
        """,
    )

    # Connection
    p.add_argument("--host",     default="kiwisdr.local",
                   help="KiwiSDR hostname or IP (default: kiwisdr.local)")
    p.add_argument("--port",     type=int, default=8073,
                   help="KiwiSDR WebSocket port (default: 8073)")
    p.add_argument("--password", default="",
                   help="KiwiSDR password (default: empty)")

    # Band selection
    p.add_argument("--bands",    default=",".join(DEFAULT_BANDS),
                   help="Comma-separated SWBC band names (default: all 14 bands)")

    # Sweep parameters
    p.add_argument("--step",    type=int,   default=DEFAULT_STEP_HZ,
                   help="Frequency step in Hz (default: 9000 = AM channel spacing)")
    p.add_argument("--dwell",   type=int,   default=3_000,
                   help="IQ samples per step (default: 3000 ≈ 250 ms at 12 kHz)")
    p.add_argument("--squelch", type=float, default=10.0,
                   help="dB above noise floor to trigger detection (default: 10)")

    # Loop control
    p.add_argument("--once",     action="store_true",
                   help="Sweep once and exit (default: loop continuously)")
    p.add_argument("--interval", type=int, default=300,
                   help="Seconds between sweeps in loop mode (default: 300)")

    # Output
    p.add_argument("--log",      default="swbc.db",
                   help="SQLite output path (default: swbc.db)")
    p.add_argument("--no-color", action="store_true", dest="no_color",
                   help="Disable ANSI colours")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
