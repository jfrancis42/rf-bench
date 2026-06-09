#!/usr/bin/env -S python3 -u
"""
CW Band Skimmer

Scans the CW sub-bands of HF amateur radio bands and detects active CW signals
by energy level.  Steps through each band in --step Hz increments, capturing a
short IQ block at each frequency and measuring power against the local noise
floor.  Active signals are logged to SQLite and displayed in a live terminal
summary.

Detection is energy-only — no decoding or WPM estimation.  Uses a narrow ±500 Hz
passband (default) to improve sensitivity for CW signals vs. wideband noise,
analogous to a very narrow IF filter.

CW sub-bands covered (configurable with --bands):
  160m  1.800–1.850 MHz
  80m   3.500–3.600 MHz
  40m   7.000–7.125 MHz
  30m   10.100–10.150 MHz
  20m   14.000–14.070 MHz
  17m   18.068–18.110 MHz
  15m   21.000–21.150 MHz
  12m   24.890–24.930 MHz
  10m   28.000–28.190 MHz

Usage:
    python cw_skimmer.py --host kiwisdr.local
    python cw_skimmer.py --host 192.168.1.100 --bands 40m,20m,15m,10m
    python cw_skimmer.py --host 192.168.1.100 --step 250 --squelch 12 --log cw.db
    python cw_skimmer.py --host 192.168.1.100 --interval 60  # 1-minute repeat sweeps
"""

import argparse
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone

import numpy as np

from rf_bench.kiwisdr import KiwiSDR, KiwiSDRError, KiwiSDRBusyError, SAMPLE_RATE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HOST      = "kiwisdr.local"
DEFAULT_PORT      = 8073
DEFAULT_STEP_HZ   = 500      # Hz — half the passband width
DEFAULT_DWELL     = 1024     # IQ samples (~85 ms at 12 kHz)
DEFAULT_SQUELCH   = 15       # dB above noise floor (CW peaks are narrow)
DEFAULT_PASSBAND  = 500      # Hz one-sided — narrow for CW detection
DEFAULT_INTERVAL  = 0        # 0 = continuous sweep; >0 = pause N seconds between passes
DEFAULT_DB        = "cw_skimmer.db"

# CW sub-band definitions (start_hz, stop_hz)
CW_BANDS: dict[str, tuple[int, int]] = {
    "160m": (1_800_000,  1_850_000),
    "80m":  (3_500_000,  3_600_000),
    "40m":  (7_000_000,  7_125_000),
    "30m":  (10_100_000, 10_150_000),
    "20m":  (14_000_000, 14_070_000),
    "17m":  (18_068_000, 18_110_000),
    "15m":  (21_000_000, 21_150_000),
    "12m":  (24_890_000, 24_930_000),
    "10m":  (28_000_000, 28_190_000),
}

# ANSI
_BOLD  = "\033[1m"
_RED   = "\033[31m"
_YELLOW= "\033[33m"
_GREEN = "\033[32m"
_CYAN  = "\033[36m"
_RESET = "\033[0m"
_CLEAR = "\033[H\033[J"

_running = True


def _sigint(_sig, _frame):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigint)

# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS spots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc      TEXT    NOT NULL,
    ts_unix     REAL    NOT NULL,
    freq_hz     INTEGER NOT NULL,
    freq_khz    REAL,
    band        TEXT,
    power_dbfs  REAL,
    snr_db      REAL
);

CREATE INDEX IF NOT EXISTS spots_freq ON spots(freq_hz);
CREATE INDEX IF NOT EXISTS spots_time ON spots(ts_unix);
CREATE INDEX IF NOT EXISTS spots_band ON spots(band);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(CREATE_SQL)
    conn.commit()
    return conn


def log_spot(conn: sqlite3.Connection,
             freq_hz: int, band: str,
             power_dbfs: float, snr_db: float) -> None:
    now = time.time()
    ts  = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO spots(ts_utc, ts_unix, freq_hz, freq_khz, band, power_dbfs, snr_db) "
        "VALUES(?,?,?,?,?,?,?)",
        (ts, now, freq_hz, freq_hz / 1000.0, band, power_dbfs, snr_db)
    )
    conn.commit()

# ---------------------------------------------------------------------------
# Frequency → band lookup
# ---------------------------------------------------------------------------

def freq_to_band(freq_hz: int, bands: dict[str, tuple[int, int]]) -> str:
    for name, (lo, hi) in bands.items():
        if lo <= freq_hz <= hi:
            return name
    return "?"


# ---------------------------------------------------------------------------
# Power measurement
# ---------------------------------------------------------------------------

def measure_power(iq: np.ndarray) -> tuple[float, float]:
    """
    Compute (power_dbfs, snr_db) from a short IQ block.

    For a narrow passband (±500 Hz, 1000 Hz total), the IQ is essentially
    a single channel.  Power is the mean squared magnitude in dBFS.
    SNR estimate: compare the peak to the median (noise proxy) of the
    power spectral density.

    Returns (power_dbfs, snr_db).
    """
    if len(iq) == 0:
        return -99.0, 0.0

    # Mean power in dBFS
    power_lin  = float(np.mean(np.abs(iq) ** 2))
    power_dbfs = 10.0 * np.log10(power_lin + 1e-30)

    # Quick PSD for SNR estimate (no need for Welch at very short dwells)
    nperseg = min(len(iq), 256)
    window  = np.hanning(nperseg).astype(np.float32)
    spec    = np.abs(np.fft.fft(iq[:nperseg] * window)) ** 2
    spec_db = 10.0 * np.log10(spec + 1e-30)

    peak_db  = float(np.max(spec_db))
    noise_db = float(np.median(spec_db))
    snr_db   = peak_db - noise_db

    return power_dbfs, snr_db

# ---------------------------------------------------------------------------
# Band scanning
# ---------------------------------------------------------------------------

def scan_band(kiwi: KiwiSDR, band_name: str,
              start_hz: int, stop_hz: int,
              step_hz: int, passband_hz: int,
              dwell_samples: int, squelch_db: float) -> list[dict]:
    """
    Step through a CW sub-band and return list of detected signals.

    Uses a narrow passband (±passband_hz) at each step to maximise
    CW sensitivity.  Restores the default passband after scanning.
    """
    spots = []
    freq  = start_hz

    kiwi.set_passband(-passband_hz, passband_hz)

    while freq <= stop_hz:
        if not _running:
            break
        try:
            kiwi.set_center_freq(freq)
            time.sleep(0.05)    # settle after retune
            iq = kiwi.capture_iq(dwell_samples)
        except KiwiSDRError:
            freq += step_hz
            continue

        power_dbfs, snr_db = measure_power(iq)

        if snr_db >= squelch_db:
            spots.append({
                "freq_hz":    freq,
                "freq_khz":   freq / 1000.0,
                "band":       band_name,
                "power_dbfs": power_dbfs,
                "snr_db":     snr_db,
            })

        freq += step_hz

    # Restore default passband
    kiwi.set_passband(-5000, 5000)
    return spots

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def render_summary(sweep_count: int, total_spots: int,
                   current_band: str, current_freq_hz: int,
                   recent_spots: list[dict]) -> None:
    lines = [_CLEAR]
    lines.append(f"{_BOLD}CW Band Skimmer{_RESET}  "
                 f"(sweeps: {sweep_count}  total spots: {total_spots}  Ctrl-C to stop)")
    lines.append(f"Scanning: {_CYAN}{current_band}{_RESET}  "
                 f"@ {current_freq_hz/1000.0:.1f} kHz")
    lines.append("")

    if recent_spots:
        hdr = f"{'Time (UTC)':<10}  {'Band':<6}  {'Freq (kHz)':>12}  {'S/N (dB)':>9}  {'Power (dBFS)':>13}"
        lines.append(_BOLD + hdr + _RESET)
        lines.append("-" * 60)
        for s in recent_spots[-25:]:   # last 25 spots
            ts  = datetime.fromtimestamp(s["ts_unix"], tz=timezone.utc).strftime("%H:%M:%S")
            snr = s["snr_db"]
            colour = _GREEN if snr >= 25 else (_YELLOW if snr >= 15 else _RED)
            lines.append(
                f"{ts:<10}  "
                f"{s['band']:<6}  "
                f"{s['freq_khz']:>12.1f}  "
                f"{colour}{snr:>+8.1f}{_RESET}  "
                f"{s['power_dbfs']:>+12.1f}"
            )
    else:
        lines.append("  (no CW activity detected yet)")

    print("\n".join(lines), end="", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_bands(band_str: str) -> dict[str, tuple[int, int]]:
    """Parse --bands argument into a sub-dict of CW_BANDS."""
    result = {}
    for name in band_str.split(","):
        name = name.strip().lower()
        if name in CW_BANDS:
            result[name] = CW_BANDS[name]
        else:
            print(f"WARNING: unknown band {name!r} (valid: {', '.join(CW_BANDS)})",
                  file=sys.stderr)
    return result


def main():
    ap = argparse.ArgumentParser(
        description="CW band energy scanner via KiwiSDR"
    )
    ap.add_argument("--host",     default=DEFAULT_HOST,
                    help="KiwiSDR hostname or IP (default: %(default)s)")
    ap.add_argument("--port",     type=int, default=DEFAULT_PORT,
                    help="KiwiSDR port (default: %(default)s)")
    ap.add_argument("--password", default="",
                    help="KiwiSDR password (default: empty)")
    ap.add_argument("--bands",    default=",".join(CW_BANDS.keys()),
                    help="Bands to scan, comma-separated (default: all CW bands)")
    ap.add_argument("--step",     type=int, default=DEFAULT_STEP_HZ,
                    help="Frequency step in Hz (default: %(default)s)")
    ap.add_argument("--dwell",    type=int, default=DEFAULT_DWELL,
                    help="IQ samples per step (default: %(default)s = ~85 ms)")
    ap.add_argument("--squelch",  type=float, default=DEFAULT_SQUELCH,
                    help="dB above noise floor to report a spot (default: %(default)s)")
    ap.add_argument("--log",      default=DEFAULT_DB, metavar="FILE",
                    help="SQLite log path (default: %(default)s)")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                    help="Seconds between sweeps (0 = continuous, default: %(default)s)")
    args = ap.parse_args()

    bands = parse_bands(args.bands)
    if not bands:
        print("No valid bands specified.", file=sys.stderr)
        sys.exit(1)

    conn          = open_db(args.log)
    sweep_count   = 0
    total_spots   = 0
    recent_spots  = []   # timestamped list of all spots this session

    # Count total steps for progress indication
    total_steps = sum(
        max(0, (hi - lo) // args.step + 1)
        for lo, hi in bands.values()
    )

    print(f"CW skimmer | {len(bands)} band(s) | {total_steps} steps/sweep | "
          f"step={args.step} Hz | squelch={args.squelch} dB")
    print(f"Bands: {', '.join(bands.keys())}")
    print(f"Log: {args.log}")
    print("Press Ctrl-C to stop.\n")

    try:
        kiwi = KiwiSDR(host=args.host, port=args.port, password=args.password,
                       passband_hz=DEFAULT_PASSBAND)
    except KiwiSDRBusyError as exc:
        print(f"KiwiSDR busy: {exc}", file=sys.stderr)
        sys.exit(1)
    except KiwiSDRError as exc:
        print(f"KiwiSDR connection failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        while _running:
            sweep_count += 1
            sweep_spots  = []

            for band_name, (start_hz, stop_hz) in bands.items():
                if not _running:
                    break

                # Update display at band boundary
                render_summary(sweep_count, total_spots, band_name,
                               start_hz, recent_spots)

                spots = scan_band(
                    kiwi, band_name, start_hz, stop_hz,
                    step_hz=args.step,
                    passband_hz=DEFAULT_PASSBAND,
                    dwell_samples=args.dwell,
                    squelch_db=args.squelch,
                )

                # Log and accumulate
                now = time.time()
                for s in spots:
                    s["ts_unix"] = now
                    log_spot(conn, s["freq_hz"], s["band"],
                             s["power_dbfs"], s["snr_db"])
                sweep_spots.extend(spots)
                recent_spots.extend(spots)
                if len(recent_spots) > 200:
                    recent_spots = recent_spots[-200:]

            total_spots += len(sweep_spots)
            render_summary(sweep_count, total_spots,
                           "done", 0, recent_spots)

            if sweep_spots:
                print(f"\n  Sweep {sweep_count}: {len(sweep_spots)} spots on "
                      f"{', '.join(sorted({s['band'] for s in sweep_spots}))}")

            if args.interval > 0 and _running:
                deadline = time.time() + args.interval
                while _running and time.time() < deadline:
                    time.sleep(0.5)

    except KiwiSDRError as exc:
        print(f"\nKiwiSDR error: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        pass
    finally:
        kiwi.close()
        conn.close()
        print(f"\nDone. {sweep_count} sweeps, {total_spots} spots logged to {args.log}")


if __name__ == "__main__":
    main()
