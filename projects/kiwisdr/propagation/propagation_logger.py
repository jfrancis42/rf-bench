#!/usr/bin/env python3
"""
Propagation Logger — KiwiSDR periodic HF noise floor and signal strength logger.

Monitors a configurable list of HF frequencies at regular intervals and records
power, noise floor, and SNR to SQLite.  Designed for long-term propagation
tracking: WWV time signals, NCDXF/IBP beacons, and quiet noise-reference
frequencies.

Default frequencies:
    5 000 000 Hz  — WWV 5 MHz (day/night propagation indicator)
   10 000 000 Hz  — WWV 10 MHz
   15 000 000 Hz  — WWV 15 MHz
   14 100 000 Hz  — NCDXF/IBP beacon network (20m)
    3 330 000 Hz  — CHU Canada 3.330 MHz (night backup to WWV)

Usage:
    python propagation_logger.py                         # defaults
    python propagation_logger.py --host 10.1.0.5
    python propagation_logger.py --freqs 5000000,10000000,15000000
    python propagation_logger.py --interval 30 --samples 12000
    python propagation_logger.py --csv                   # also write CSV

Output:
    propagation.db    — SQLite log (default)
    propagation.csv   — CSV append (with --csv)
"""

import argparse
import csv
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from rf_bench.kiwisdr import KiwiSDR, KiwiSDRError, SAMPLE_RATE


# ── default frequency list ────────────────────────────────────────────────────

DEFAULT_FREQS = [
    5_000_000,
    10_000_000,
    15_000_000,
    14_100_000,
    3_330_000,
]

DEFAULT_LABELS = [
    "WWV 5 MHz",
    "WWV 10 MHz",
    "WWV 15 MHz",
    "NCDXF 20m",
    "CHU 3.330",
]


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


def _snr_color(snr: float, use_color: bool) -> str:
    if not use_color:
        return ""
    if snr >= 20.0:
        return GREEN
    if snr >= 10.0:
        return YELLOW
    if snr >= 3.0:
        return ORANGE
    return DIM


def _bar(snr: float, lo: float = 0.0, hi: float = 30.0, width: int = 8) -> str:
    frac = max(0.0, min(1.0, (snr - lo) / (hi - lo)))
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
            power_dbfs  REAL,
            noise_dbfs  REAL,
            snr_db      REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts    ON readings (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_freq  ON readings (freq_hz)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_label ON readings (label)")
    conn.commit()
    return conn


def _log_reading(conn: sqlite3.Connection, ts_utc: str, ts_unix: float,
                 freq_hz: int, label: str,
                 power_dbfs: float, noise_dbfs: float, snr_db: float) -> None:
    conn.execute(
        "INSERT INTO readings "
        "(ts_utc, ts_unix, freq_hz, label, power_dbfs, noise_dbfs, snr_db) "
        "VALUES (?,?,?,?,?,?,?)",
        (ts_utc, ts_unix, freq_hz, label,
         round(power_dbfs, 2), round(noise_dbfs, 2), round(snr_db, 2)),
    )
    conn.commit()


# ── CSV ───────────────────────────────────────────────────────────────────────

def _ensure_csv(path: str) -> None:
    """Write header row if the file is new."""
    if not Path(path).exists():
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ts_utc", "ts_unix", "freq_hz", "label",
                             "power_dbfs", "noise_dbfs", "snr_db"])


def _append_csv(path: str, ts_utc: str, ts_unix: float, freq_hz: int, label: str,
                power_dbfs: float, noise_dbfs: float, snr_db: float) -> None:
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([ts_utc, round(ts_unix, 3), freq_hz, label,
                         round(power_dbfs, 2), round(noise_dbfs, 2),
                         round(snr_db, 2)])


# ── measurement ───────────────────────────────────────────────────────────────

def _measure(kiwi: KiwiSDR, freq_hz: int, num_samples: int) -> tuple[float, float, float]:
    """
    Tune to freq_hz, capture IQ, return (power_dbfs, noise_dbfs, snr_db).

    power_dbfs = 10 * log10(mean(|iq|^2))
    noise_dbfs = median of Hann-FFT PSD bins (noise floor estimate)
    snr_db     = peak FFT bin - noise_dbfs  (how much the carrier stands above noise)

    For a pure carrier (e.g. WWV), snr_db will be strong (10–40 dB).
    For a noise reference, snr_db will be near 0.
    """
    kiwi.set_center_freq(freq_hz)
    time.sleep(0.05)   # settle for FPGA filter transient
    iq = kiwi.capture_iq(num_samples)

    # Overall power
    power_dbfs = float(10.0 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-30))

    # FFT-based noise floor and peak
    n = len(iq)
    window  = np.hanning(n).astype(np.float32)
    fft_raw = np.fft.fftshift(np.fft.fft(iq * window))
    psd_db  = 10.0 * np.log10(
        np.maximum(np.abs(fft_raw) ** 2 / np.sum(window ** 2), 1e-30)
    )
    noise_dbfs = float(np.median(psd_db))
    peak_dbfs  = float(np.max(psd_db))
    snr_db     = peak_dbfs - noise_dbfs

    return power_dbfs, noise_dbfs, snr_db


# ── display ───────────────────────────────────────────────────────────────────

def _print_table(freqs: list[int], labels: list[str],
                 readings: dict[int, tuple[float, float, float]],
                 ts_str: str, use_color: bool) -> None:
    if use_color:
        os.system("clear")
    else:
        print("\033[H\033[J", end="")

    header = (f"  {'Propagation Logger' if not use_color else BOLD + 'Propagation Logger' + RESET}"
              f"  —  {ts_str} UTC")
    print(f"\n{header}")
    print(f"  {'─'*68}")

    col_w = 14  # label column width
    print(f"  {'Label':<{col_w}}  {'Freq (MHz)':>11}  "
          f"{'Power dBFS':>10}  {'Noise dBFS':>10}  {'SNR dB':>7}  Bar")
    print(f"  {'─'*68}")

    for freq_hz, label in zip(freqs, labels):
        mhz = freq_hz / 1e6
        if freq_hz in readings:
            power, noise, snr = readings[freq_hz]
            col = _snr_color(snr, use_color)
            rst = RESET if use_color else ""
            bar = _bar(snr)
            print(f"  {label:<{col_w}}  {mhz:>11.4f}  "
                  f"{power:>+10.2f}  {noise:>+10.2f}  "
                  f"{col}{snr:>+7.1f}{rst}  {col}{bar}{rst}")
        else:
            print(f"  {label:<{col_w}}  {mhz:>11.4f}  {'—':>10}  {'—':>10}  {'—':>7}")

    print(f"  {'─'*68}")
    print(f"\n  Press Ctrl-C to stop.\n")


# ── main loop ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    # Parse frequency list and optional labels
    freqs = [int(f.strip()) for f in args.freqs.split(",")]
    if args.freq_names:
        labels = [l.strip() for l in args.freq_names.split(",")]
        if len(labels) != len(freqs):
            print(f"ERROR: --freq-names has {len(labels)} entries but "
                  f"--freqs has {len(freqs)} entries; they must match.")
            sys.exit(1)
    else:
        # Auto-label: use default labels for known frequencies, else "X.XXX MHz"
        freq_label_map = dict(zip(DEFAULT_FREQS, DEFAULT_LABELS))
        labels = [freq_label_map.get(f, f"{f/1e6:.4f} MHz") for f in freqs]

    # Validate range
    for f in freqs:
        if not (0 <= f <= 30_000_000):
            print(f"ERROR: frequency {f} Hz is outside KiwiSDR range (0–30 MHz)")
            sys.exit(1)

    conn = _open_db(args.log)

    csv_path: str | None = None
    if args.csv:
        csv_path = args.log.replace(".db", ".csv") if args.log.endswith(".db") \
                   else args.log + ".csv"
        _ensure_csv(csv_path)

    print(f"\n  Propagation Logger")
    print(f"  Host: {args.host}:{args.port}  |  interval: {args.interval}s  "
          f"|  samples: {args.samples} ({args.samples / SAMPLE_RATE * 1000:.0f} ms)")
    print(f"  Frequencies: {len(freqs)}")
    for f, l in zip(freqs, labels):
        print(f"    {l:<14}  {f/1e6:.4f} MHz")
    print(f"  SQLite: {args.log}")
    if csv_path:
        print(f"  CSV:    {csv_path}")
    print(f"  Connecting to KiwiSDR...")

    try:
        kiwi = KiwiSDR(args.host, port=args.port, password=args.password,
                       channel=0, passband_hz=5000)
    except KiwiSDRError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    stop      = False
    n_rounds  = 0

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    print(f"  Connected.  First measurement in {args.interval}s.\n"
          f"  Press Ctrl-C to stop.\n")

    try:
        while not stop:
            t_start   = time.monotonic()
            now       = datetime.now(timezone.utc)
            ts_utc    = now.isoformat()
            ts_unix   = now.timestamp()
            ts_str    = now.strftime("%Y-%m-%d %H:%M:%S")
            readings: dict[int, tuple[float, float, float]] = {}

            for freq_hz, label in zip(freqs, labels):
                if stop:
                    break
                try:
                    power, noise, snr = _measure(kiwi, freq_hz, args.samples)
                except KiwiSDRError as e:
                    print(f"  [measure error at {freq_hz/1e6:.3f} MHz: {e}]")
                    continue

                readings[freq_hz] = (power, noise, snr)
                _log_reading(conn, ts_utc, ts_unix, freq_hz, label, power, noise, snr)

                if csv_path:
                    _append_csv(csv_path, ts_utc, ts_unix,
                                freq_hz, label, power, noise, snr)

            n_rounds += 1
            _print_table(freqs, labels, readings, ts_str, use_color)

            # Wait for the remainder of the interval
            elapsed  = time.monotonic() - t_start
            wait_for = max(0.0, args.interval - elapsed)
            deadline = time.monotonic() + wait_for
            while not stop and time.monotonic() < deadline:
                time.sleep(0.2)

    except Exception as e:
        print(f"\n  Error: {e}")
    finally:
        kiwi.close()
        conn.close()

    print(f"\n  Stopped after {n_rounds} measurement rounds.")
    print(f"  Database: {args.log}")
    if csv_path:
        print(f"  CSV:      {csv_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Propagation Logger — KiwiSDR periodic HF power and noise floor logger",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Default frequencies: WWV 5/10/15 MHz, NCDXF 14.100 MHz, CHU 3.330 MHz

Examples:
  python propagation_logger.py
  python propagation_logger.py --host 10.1.0.5
  python propagation_logger.py --freqs 5000000,10000000,15000000
  python propagation_logger.py --freqs 5000000,10000000 --freq-names "WWV 5,WWV 10"
  python propagation_logger.py --interval 30 --samples 12000 --csv
        """,
    )

    # Connection
    p.add_argument("--host",     default="kiwisdr.local",
                   help="KiwiSDR hostname or IP (default: kiwisdr.local)")
    p.add_argument("--port",     type=int, default=8073,
                   help="KiwiSDR WebSocket port (default: 8073)")
    p.add_argument("--password", default="",
                   help="KiwiSDR password (default: empty)")

    # Frequencies
    p.add_argument("--freqs",
                   default=",".join(str(f) for f in DEFAULT_FREQS),
                   help="Comma-separated frequencies in Hz "
                        "(default: WWV 5/10/15 MHz, NCDXF 14.1 MHz, CHU 3.33 MHz)")
    p.add_argument("--freq-names", default="", dest="freq_names",
                   help="Optional comma-separated labels for each frequency "
                        "(must match count of --freqs)")

    # Measurement
    p.add_argument("--interval", type=int, default=60,
                   help="Measurement interval in seconds (default: 60)")
    p.add_argument("--samples",  type=int, default=6_000,
                   help="IQ samples per measurement (default: 6000 = 0.5s at 12 kHz)")

    # Output
    p.add_argument("--log",      default="propagation.db",
                   help="SQLite output path (default: propagation.db)")
    p.add_argument("--csv",      action="store_true",
                   help="Also write propagation.csv (appended)")
    p.add_argument("--no-color", action="store_true", dest="no_color",
                   help="Disable ANSI colours")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
