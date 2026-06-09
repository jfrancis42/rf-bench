#!/usr/bin/env python3
"""
HF Monitor — KiwiSDR HF band activity scanner (log mode).

Sweeps configurable amateur HF bands using the KiwiSDR's scan_band() method,
logs detected signals to SQLite, and shows a rolling terminal display of recent
detections and most-active frequencies.  The HF analogue of bubba-detector's
log mode.

Coverage: 0–30 MHz (KiwiSDR hardware limit).  Amateur bands 160m–10m.

Usage:
    python hf_monitor.py                          # 40m/20m/15m/10m, default squelch
    python hf_monitor.py --bands 40m,20m,17m,15m  # specific bands
    python hf_monitor.py --all-amateur             # all 9 amateur HF bands
    python hf_monitor.py --host 10.1.0.5 --squelch 15
    python hf_monitor.py --step 5000 --dwell 4096  # finer step, longer dwell

Output:
    hf_monitor.db   — SQLite log of all detections (default path)
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


# ── HF amateur band definitions ───────────────────────────────────────────────

HF_BANDS = {
    "160m": (1_800_000,  2_000_000),
    "80m":  (3_500_000,  4_000_000),
    "60m":  (5_330_500,  5_403_500),
    "40m":  (7_000_000,  7_300_000),
    "30m":  (10_100_000, 10_150_000),
    "20m":  (14_000_000, 14_350_000),
    "17m":  (18_068_000, 18_168_000),
    "15m":  (21_000_000, 21_450_000),
    "12m":  (24_890_000, 24_990_000),
    "10m":  (28_000_000, 29_700_000),
}

ALL_AMATEUR_BANDS = list(HF_BANDS.keys())
DEFAULT_BANDS     = ["40m", "20m", "15m", "10m"]


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
    "160m": "\033[35m",   # magenta
    "80m":  "\033[33m",   # orange/brown
    "60m":  "\033[93m",   # yellow
    "40m":  "\033[92m",   # green
    "30m":  "\033[96m",   # cyan
    "20m":  "\033[97m",   # white
    "17m":  "\033[95m",   # bright magenta
    "15m":  "\033[94m",   # blue
    "12m":  "\033[91m",   # red
    "10m":  "\033[96m",   # cyan
}


def _bar(snr: float, lo: float = 0.0, hi: float = 40.0, width: int = 10) -> str:
    frac = max(0.0, min(1.0, (snr - lo) / (hi - lo)))
    filled = int(frac * width)
    return "█" * filled + "░" * (width - filled)


def _band_for_freq(freq_hz: int) -> str:
    for band, (lo, hi) in HF_BANDS.items():
        if lo <= freq_hz <= hi:
            return band
    return "?"


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
            noise_dbfs  REAL,
            snr_db      REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON detections (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_freq ON detections (freq_hz)")
    conn.commit()
    return conn


def _log_detection(conn: sqlite3.Connection, freq_hz: int, band: str,
                   power_dbfs: float, noise_dbfs: float, snr_db: float) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO detections "
        "(ts_utc, ts_unix, freq_hz, freq_mhz, band, power_dbfs, noise_dbfs, snr_db) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (now.isoformat(), now.timestamp(),
         freq_hz, round(freq_hz / 1e6, 6), band,
         round(power_dbfs, 2), round(noise_dbfs, 2), round(snr_db, 2)),
    )
    conn.commit()


# ── band sweep ────────────────────────────────────────────────────────────────

def _sweep_band(kiwi: KiwiSDR, band: str, start_hz: int, stop_hz: int,
                step_hz: int, dwell_samples: int,
                squelch_db: float) -> list[tuple[int, float, float, float]]:
    """
    Sweep one amateur band and return a list of (freq_hz, power, noise, snr) tuples
    for each step where a signal was detected above squelch_db.

    Uses scan_band() from the driver.  The driver's threshold_db is relative to
    the local noise floor; we pass squelch_db directly.
    """
    hits = []
    freq = start_hz
    while freq <= stop_hz:
        try:
            kiwi.set_center_freq(freq)
            time.sleep(0.04)   # ~40 ms settle for FPGA filter transient
            iq = kiwi.capture_iq(dwell_samples)
        except KiwiSDRError:
            freq += step_hz
            continue

        # Compute PSD and noise floor in-band
        n = len(iq)
        window  = np.hanning(n).astype(np.float32)
        fft_raw = np.fft.fftshift(np.fft.fft(iq * window))
        psd_db  = 10.0 * np.log10(
            np.maximum(np.abs(fft_raw) ** 2 / np.sum(window ** 2), 1e-30)
        )
        noise  = float(np.median(psd_db))
        peak   = float(np.max(psd_db))
        snr    = peak - noise

        if snr >= squelch_db:
            hits.append((freq, peak, noise, snr))

        freq += step_hz

    return hits


# ── display ───────────────────────────────────────────────────────────────────

def _format_detection(freq_hz: int, band: str, snr_db: float, power_dbfs: float,
                      ts_str: str, use_color: bool) -> str:
    mhz = freq_hz / 1e6
    bar = _bar(snr_db)
    if use_color:
        col = BAND_COLORS.get(band, "")
        return (f"{DIM}[{ts_str}]{RESET} "
                f"{col}{BOLD}{band:<4}{RESET}  "
                f"{mhz:10.4f} MHz  "
                f"SNR {snr_db:+5.1f} dB  pwr {power_dbfs:+6.1f} dBFS  "
                f"{col}{bar}{RESET}")
    return (f"[{ts_str}] {band:<4}  {mhz:10.4f} MHz  "
            f"SNR {snr_db:+5.1f} dB  pwr {power_dbfs:+6.1f} dBFS  {bar}")


def _print_status(cycle: int, elapsed: float, bands: list[str],
                  total: int, recent: deque, hits_by_freq: dict,
                  use_color: bool) -> None:
    if use_color:
        os.system("clear")
    else:
        print("\033[H\033[J", end="")

    bands_str = " ".join(bands)
    print(f"\n  {'HF Monitor' if not use_color else BOLD + 'HF Monitor' + RESET}  "
          f"cycle #{cycle}  |  bands: {bands_str}  |  "
          f"sweep: {elapsed:.1f}s  |  detections: {total}")
    print(f"  {'─'*74}")

    if recent:
        for line in recent:
            print(f"  {line}")
    else:
        print("  (no activity yet)")

    print(f"  {'─'*74}")

    if hits_by_freq:
        top = sorted(hits_by_freq.items(), key=lambda x: -x[1])[:5]
        top_strs = []
        for freq_hz, count in top:
            band = _band_for_freq(freq_hz)
            col  = BAND_COLORS.get(band, "") if use_color else ""
            rst  = RESET if use_color else ""
            top_strs.append(f"{col}{freq_hz/1e6:.4f} MHz{rst} ({count})")
        print(f"\n  Top: " + "  |  ".join(top_strs))

    print(f"\n  Press Ctrl-C to stop.\n")


# ── main loop ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    # Resolve band list
    if args.all_amateur:
        bands = ALL_AMATEUR_BANDS
    else:
        bands = [b.strip() for b in args.bands.split(",")]
        invalid = [b for b in bands if b not in HF_BANDS]
        if invalid:
            print(f"ERROR: unknown bands: {', '.join(invalid)}")
            print(f"  Valid: {', '.join(HF_BANDS.keys())}")
            sys.exit(1)

    conn = _open_db(args.log)
    print(f"\n  HF Monitor  —  bands: {' '.join(bands)}")
    print(f"  Host: {args.host}:{args.port}  |  squelch: +{args.squelch:.0f} dB")
    print(f"  Step: {args.step} Hz  |  dwell: {args.dwell} samples "
          f"({args.dwell / SAMPLE_RATE * 1000:.0f} ms)  |  tail: {args.tail}")
    print(f"  SQLite: {args.log}")
    print(f"  Connecting to KiwiSDR...")

    try:
        kiwi = KiwiSDR(args.host, port=args.port, password=args.password,
                       channel=0, passband_hz=5000)
    except KiwiSDRError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if args.gain != 0:
        kiwi.set_gain(args.gain)

    recent: deque[str]           = deque(maxlen=args.tail)
    hits_by_freq: dict[int, int] = {}
    total_detections             = 0
    cycle                        = 0
    stop                         = False

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    print(f"  Connected.  Starting sweep...\n  Press Ctrl-C to stop.\n")

    try:
        while not stop:
            t0 = time.monotonic()
            cycle += 1

            for band in bands:
                if stop:
                    break
                lo, hi = HF_BANDS[band]
                try:
                    hits = _sweep_band(kiwi, band, lo, hi,
                                       args.step, args.dwell, args.squelch)
                except KiwiSDRError as e:
                    print(f"  [sweep error on {band}: {e}]")
                    continue

                for freq_hz, power, noise, snr in hits:
                    ts_str = datetime.now().strftime("%H:%M:%S")
                    _log_detection(conn, freq_hz, band, power, noise, snr)
                    line = _format_detection(freq_hz, band, snr, power, ts_str, use_color)
                    recent.append(line)
                    hits_by_freq[freq_hz] = hits_by_freq.get(freq_hz, 0) + 1
                    total_detections += 1

            elapsed = time.monotonic() - t0
            _print_status(cycle, elapsed, bands, total_detections,
                          recent, hits_by_freq, use_color)

    except Exception as e:
        print(f"\n  Error: {e}")
    finally:
        kiwi.close()
        conn.close()

    print(f"\n  Stopped after {cycle} cycles, {total_detections} detections.")
    print(f"  Database: {args.log}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="HF Monitor — KiwiSDR HF band activity scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Bands: 160m 80m 60m 40m 30m 20m 17m 15m 12m 10m

Examples:
  python hf_monitor.py
  python hf_monitor.py --all-amateur
  python hf_monitor.py --bands 40m,20m,17m,15m --squelch 15
  python hf_monitor.py --host 10.1.0.5 --step 5000 --dwell 4096
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
    p.add_argument("--bands",       default=",".join(DEFAULT_BANDS),
                   help="Comma-separated band names (default: 40m,20m,15m,10m)")
    p.add_argument("--all-amateur", action="store_true", dest="all_amateur",
                   help="Sweep all 9 amateur HF bands (160m–10m)")

    # Sweep parameters
    p.add_argument("--step",    type=int,   default=10_000,
                   help="Frequency step in Hz (default: 10000)")
    p.add_argument("--dwell",   type=int,   default=2_048,
                   help="IQ samples per step (default: 2048 ≈ 171 ms at 12 kHz)")
    p.add_argument("--squelch", type=float, default=12.0,
                   help="dB above noise floor to trigger detection (default: 12)")
    p.add_argument("--gain",    type=float, default=0,
                   help="AGC threshold adjustment in dB (default: 0 = auto AGC)")

    # Output
    p.add_argument("--log",      default="hf_monitor.db",
                   help="SQLite output path (default: hf_monitor.db)")
    p.add_argument("--tail",     type=int, default=20,
                   help="Number of recent detections in rolling display (default: 20)")
    p.add_argument("--no-color", action="store_true", dest="no_color",
                   help="Disable ANSI colours")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
