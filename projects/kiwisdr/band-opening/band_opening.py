#!/usr/bin/env python3
"""
Band Opening Monitor — KiwiSDR NCDXF/IARU beacon network propagation detector.

Monitors the five NCDXF/IARU international beacon network frequencies
(14.100, 18.110, 21.150, 24.930, 28.200 MHz) to detect HF band openings.
Measures S/N at each beacon frequency on a configurable interval, computes a
rolling baseline, and declares an "opening" when S/N exceeds baseline + threshold.
Logs all readings and openings to SQLite.  Optionally writes a JSON alert file
that other tools (e.g. bubba-detector) can poll.

Usage:
    python band_opening.py
    python band_opening.py --host kiwi.example.com --threshold 12
    python band_opening.py --interval 60 --window 30 --alert-file /tmp/band_opening.json
    python band_opening.py --freqs 28200000,28300000 --interval 30

Output:
    band_opening.db   — SQLite log of all readings and detected openings
"""

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
from collections import deque
from datetime import datetime, timezone

import numpy as np

from rf_bench.kiwisdr import KiwiSDR, KiwiSDRError, SAMPLE_RATE


# ── Beacon network frequencies ────────────────────────────────────────────────

BEACON_FREQS: dict[str, int] = {
    "14.100 MHz (20m)": 14_100_000,
    "18.110 MHz (17m)": 18_110_000,
    "21.150 MHz (15m)": 21_150_000,
    "24.930 MHz (12m)": 24_930_000,
    "28.200 MHz (10m)": 28_200_000,
}

# Maximum frequency the KiwiSDR can receive
KIWI_MAX_HZ = 30_000_000

# Percentile used for rolling baseline (low percentile = ignores signal peaks,
# tracks true noise floor)
BASELINE_PERCENTILE = 20


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


def _snr_color(snr: float, above_baseline: float) -> str:
    """Color based on SNR above baseline (used to flag openings)."""
    if above_baseline >= 10:
        return GREEN
    if above_baseline >= 5:
        return YELLOW
    return ""


def _bar(value: float, lo: float = 0.0, hi: float = 40.0, width: int = 12) -> str:
    frac = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    filled = int(frac * width)
    return "█" * filled + "░" * (width - filled)


# ── SQLite ────────────────────────────────────────────────────────────────────

def _open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT NOT NULL,
            ts_unix     REAL NOT NULL,
            freq_hz     INTEGER NOT NULL,
            label       TEXT,
            snr_db      REAL,
            power_dbfs  REAL,
            baseline_db REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS openings (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT NOT NULL,
            ts_unix     REAL NOT NULL,
            freq_hz     INTEGER NOT NULL,
            label       TEXT,
            snr_db      REAL,
            peak_snr_db REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_r_ts   ON readings (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_r_freq ON readings (freq_hz)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_o_ts   ON openings (ts_unix)")
    conn.commit()
    return conn


def _log_reading(conn: sqlite3.Connection, freq_hz: int, label: str,
                 snr_db: float, power_dbfs: float, baseline_db: float) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO readings (ts_utc, ts_unix, freq_hz, label, snr_db, power_dbfs, baseline_db) "
        "VALUES (?,?,?,?,?,?,?)",
        (now.isoformat(), now.timestamp(),
         freq_hz, label,
         round(snr_db, 2), round(power_dbfs, 2), round(baseline_db, 2)),
    )
    conn.commit()


def _log_opening(conn: sqlite3.Connection, freq_hz: int, label: str,
                 snr_db: float, peak_snr_db: float) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO openings (ts_utc, ts_unix, freq_hz, label, snr_db, peak_snr_db) "
        "VALUES (?,?,?,?,?,?)",
        (now.isoformat(), now.timestamp(),
         freq_hz, label,
         round(snr_db, 2), round(peak_snr_db, 2)),
    )
    conn.commit()


# ── Measurement ───────────────────────────────────────────────────────────────

def _measure_snr(kiwi: KiwiSDR, freq_hz: int, n_samples: int) -> tuple[float, float]:
    """
    Tune to freq_hz and return (snr_db, peak_power_dbfs).

    snr_db is peak_power_dbfs minus the median of the PSD (noise floor estimate).
    """
    kiwi.set_center_freq(freq_hz)
    time.sleep(0.05)   # filter settle
    iq = kiwi.capture_iq(n_samples)

    n = len(iq)
    window  = np.hanning(n).astype(np.float32)
    fft_raw = np.fft.fftshift(np.fft.fft(iq * window))
    psd_db  = 10.0 * np.log10(
        np.maximum(np.abs(fft_raw) ** 2 / np.sum(window ** 2), 1e-30)
    )
    noise  = float(np.median(psd_db))
    peak   = float(np.max(psd_db))
    return peak - noise, peak


# ── Alert file ────────────────────────────────────────────────────────────────

def _write_alert(path: str,
                 openings: list[dict],
                 ts_unix: float) -> None:
    """Write JSON alert file consumed by other tools (e.g. bubba-detector)."""
    payload = {"ts_unix": round(ts_unix, 3), "openings": openings}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, path)   # atomic replace


# ── Display ───────────────────────────────────────────────────────────────────

def _print_status(use_color: bool, cycle: int,
                  freq_table: dict[str, int],
                  snr_now: dict[str, float],
                  baseline: dict[str, float],
                  recent_events: deque,
                  total_openings: int,
                  interval: int,
                  threshold: float) -> None:
    if use_color:
        os.system("clear")
    else:
        print("\033[H\033[J", end="")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hdr = f"Band Opening Monitor" if not use_color else f"{BOLD}Band Opening Monitor{RESET}"
    print(f"\n  {hdr}  —  {ts}  |  cycle #{cycle}  |  interval: {interval}s")
    print(f"  Threshold: +{threshold:.0f} dB above baseline  |  openings: {total_openings}")
    print(f"  {'─'*72}")

    # Per-frequency table
    print(f"  {'Frequency':<26} {'S/N':>7}  {'Baseline':>9}  {'Above':>6}  {'Bar':<14}  Status")
    print(f"  {'─'*72}")
    for label, freq_hz in freq_table.items():
        snr  = snr_now.get(label, float("nan"))
        base = baseline.get(label, float("nan"))
        above = snr - base if not (np.isnan(snr) or np.isnan(base)) else float("nan")
        bar  = _bar(snr) if not np.isnan(snr) else " " * 12

        if np.isnan(snr):
            snr_str = f"{'---':>7}"
            status  = f"{DIM}no data{RESET}" if use_color else "no data"
            col = ""
        else:
            snr_str = f"{snr:+7.1f}"
            if not np.isnan(above) and above >= threshold:
                status = f"{GREEN}OPENING{RESET}" if use_color else "OPENING"
                col = GREEN if use_color else ""
            elif not np.isnan(above) and above >= threshold / 2:
                status = f"{YELLOW}elevated{RESET}" if use_color else "elevated"
                col = YELLOW if use_color else ""
            else:
                status = "quiet"
                col = DIM if use_color else ""

        base_str  = f"{base:+8.1f}" if not np.isnan(base) else "    ---"
        above_str = f"{above:+6.1f}" if not np.isnan(above) else "   ---"
        rst = RESET if use_color else ""
        bcol = col if use_color else ""
        print(f"  {bcol}{label:<26}{rst}  "
              f"{bcol}{snr_str}{rst} dB  "
              f"{DIM if use_color else ''}{base_str}{rst} dB  "
              f"{above_str} dB  "
              f"{bcol}{bar}{rst}  {status}")

    print(f"  {'─'*72}")

    # Recent events
    if recent_events:
        print(f"\n  Recent openings:")
        for ev in recent_events:
            print(f"    {ev}")
    else:
        print(f"\n  {DIM}No openings detected yet.{RESET}" if use_color
              else "\n  No openings detected yet.")

    print(f"\n  Press Ctrl-C to stop.\n")


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    # Build frequency table
    if args.freqs:
        try:
            extra_hz = [int(f.strip()) for f in args.freqs.split(",")]
        except ValueError:
            print("ERROR: --freqs must be comma-separated integers in Hz")
            sys.exit(1)
        freq_table: dict[str, int] = {}
        for hz in extra_hz:
            label = f"{hz / 1e6:.3f} MHz"
            freq_table[label] = hz
    else:
        freq_table = dict(BEACON_FREQS)

    # Validate all frequencies are within KiwiSDR range
    bad = [(lbl, hz) for lbl, hz in freq_table.items() if hz > KIWI_MAX_HZ]
    if bad:
        for lbl, hz in bad:
            print(f"WARNING: {lbl} ({hz} Hz) exceeds KiwiSDR 30 MHz limit — skipping")
        freq_table = {lbl: hz for lbl, hz in freq_table.items() if hz <= KIWI_MAX_HZ}
    if not freq_table:
        print("ERROR: no valid frequencies to monitor")
        sys.exit(1)

    conn = _open_db(args.log)

    print(f"\n  Band Opening Monitor")
    print(f"  Host: {args.host}:{args.port}  |  interval: {args.interval}s  "
          f"|  threshold: +{args.threshold} dB  |  window: {args.window}")
    print(f"  Samples: {args.samples} ({args.samples / SAMPLE_RATE:.1f}s)  |  SQLite: {args.log}")
    if args.alert_file:
        print(f"  Alert file: {args.alert_file}")
    print(f"  Frequencies: {', '.join(freq_table.keys())}")
    print(f"  Connecting to KiwiSDR at {args.host}:{args.port}...")

    try:
        kiwi = KiwiSDR(args.host, port=args.port, password=args.password,
                       channel=0, passband_hz=5000)
    except KiwiSDRError as e:
        print(f"ERROR connecting: {e}")
        sys.exit(1)

    print(f"  Connected.  Press Ctrl-C to stop.\n")

    # Per-frequency rolling S/N history for baseline calculation
    history: dict[str, deque] = {lbl: deque(maxlen=args.window) for lbl in freq_table}

    snr_now: dict[str, float]  = {}
    baseline: dict[str, float] = {}
    peak_snr: dict[str, float] = {}   # session peak per freq

    recent_events: deque = deque(maxlen=10)
    total_openings = 0
    cycle = 0
    stop  = False

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    try:
        while not stop:
            t0 = time.monotonic()
            cycle += 1
            cycle_openings: list[dict] = []

            for label, freq_hz in freq_table.items():
                if stop:
                    break
                try:
                    snr_db, power_dbfs = _measure_snr(kiwi, freq_hz, args.samples)
                except KiwiSDRError as e:
                    print(f"  [error measuring {label}: {e}]")
                    continue

                snr_now[label] = snr_db
                peak_snr[label] = max(peak_snr.get(label, snr_db), snr_db)

                # Rolling baseline: percentile-20 of recent S/N readings
                history[label].append(snr_db)
                if len(history[label]) >= 2:
                    base = float(np.percentile(list(history[label]), BASELINE_PERCENTILE))
                    baseline[label] = base
                else:
                    base = snr_db
                    baseline[label] = base

                above = snr_db - base
                _log_reading(conn, freq_hz, label, snr_db, power_dbfs, base)

                # Opening detection
                if above >= args.threshold and len(history[label]) >= 3:
                    _log_opening(conn, freq_hz, label, snr_db, peak_snr[label])
                    total_openings += 1
                    ts_str = datetime.now().strftime("%H:%M:%S")
                    event_line = (
                        f"{ts_str}  {label}  "
                        f"S/N {snr_db:+.1f} dB  "
                        f"(+{above:.1f} dB above baseline)"
                    )
                    if use_color:
                        event_line = f"{GREEN}{event_line}{RESET}"
                    recent_events.append(event_line)
                    cycle_openings.append({
                        "freq_hz": freq_hz,
                        "snr_db": round(snr_db, 2),
                        "label": label,
                    })

            # Write alert file if any openings this cycle
            if args.alert_file and cycle_openings:
                try:
                    _write_alert(args.alert_file, cycle_openings, time.time())
                except OSError as e:
                    print(f"  [alert file write error: {e}]")

            _print_status(use_color, cycle, freq_table, snr_now, baseline,
                          recent_events, total_openings, args.interval, args.threshold)

            # Wait for next interval
            elapsed = time.monotonic() - t0
            remaining = args.interval - elapsed
            if remaining > 0 and not stop:
                # Sleep in small chunks to remain Ctrl-C responsive
                deadline = time.monotonic() + remaining
                while time.monotonic() < deadline and not stop:
                    time.sleep(min(0.25, deadline - time.monotonic()))

    except Exception as e:
        print(f"\n  Unhandled error: {e}")
        raise
    finally:
        kiwi.close()
        conn.close()

    print(f"\n  Stopped after {cycle} cycles.  Total openings detected: {total_openings}")
    print(f"  Database: {args.log}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Band Opening Monitor — KiwiSDR NCDXF beacon propagation detector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Default beacon frequencies (NCDXF/IARU network):
  14.100 MHz (20m)   18.110 MHz (17m)   21.150 MHz (15m)
  24.930 MHz (12m)   28.200 MHz (10m)

Examples:
  python band_opening.py
  python band_opening.py --host 10.1.0.5 --threshold 12 --interval 60
  python band_opening.py --alert-file /tmp/band_opening.json
  python band_opening.py --freqs 28200000,28300000,28400000 --interval 30
        """,
    )

    # Connection
    p.add_argument("--host",     default="kiwisdr.local",
                   help="KiwiSDR hostname or IP (default: kiwisdr.local)")
    p.add_argument("--port",     type=int, default=8073,
                   help="KiwiSDR port (default: 8073)")
    p.add_argument("--password", default="",
                   help="KiwiSDR password (default: empty)")

    # Frequency selection
    p.add_argument("--freqs", default=None,
                   help="Override beacon freqs: comma-separated Hz values "
                        "(default: NCDXF 5-band set)")

    # Measurement parameters
    p.add_argument("--interval", type=int, default=120,
                   help="Measurement interval in seconds (default: 120)")
    p.add_argument("--samples",  type=int, default=12_000,
                   help="IQ samples per measurement (~1 s at 12 kHz, default: 12000)")
    p.add_argument("--threshold", type=float, default=10.0,
                   help="dB above rolling baseline to declare opening (default: 10)")
    p.add_argument("--window",   type=int, default=20,
                   help="Rolling window size for baseline calculation (default: 20)")

    # Output
    p.add_argument("--alert-file", default=None, dest="alert_file",
                   help="Path to write JSON alert file on opening (optional)")
    p.add_argument("--log",      default="band_opening.db",
                   help="SQLite output path (default: band_opening.db)")
    p.add_argument("--no-color", action="store_true", dest="no_color",
                   help="Disable ANSI colours")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
