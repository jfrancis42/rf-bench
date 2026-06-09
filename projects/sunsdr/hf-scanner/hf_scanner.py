#!/usr/bin/env python3
"""
HF Scanner — SunSDR2 Pro wideband HF band scanner.

Sweeps 0.1–55 MHz in configurable steps, using the SunSDR's 192 kHz IQ
bandwidth to capture ±96 kHz per step.  Detects signals above a squelch
threshold, logs detections to SQLite, and displays a rolling terminal
activity table.

At 192 kHz sample rate, a 192 kHz step provides complete coverage with
no gaps.  A full 0–55 MHz sweep takes ~290 steps ≈ 90–180 seconds depending
on dwell time.  Use --bands to restrict to amateur sub-bands for faster sweeps.

Usage:
    python hf_scanner.py --host 192.168.1.100
    python hf_scanner.py --host 192.168.1.100 --step 96000 --squelch 15
    python hf_scanner.py --host 192.168.1.100 --bands 40m,20m,15m,10m
    python hf_scanner.py --host 192.168.1.100 --db my_scan.db --no-color

Output:
    hf_scan.db  — SQLite log of all detections
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

from rf_bench.sunsdr import SunSDR, SunSDRError


# ── Amateur band definitions (Hz) ────────────────────────────────────────────

AMATEUR_BANDS: dict[str, tuple[int, int]] = {
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
    "6m":   (50_000_000, 54_000_000),
}

ALL_HF_START =    100_000   # 100 kHz (SunSDR lower limit)
ALL_HF_STOP  = 55_000_000   # 55 MHz (SunSDR upper limit)

# ── ANSI colours ─────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"
WHITE  = "\033[97m"


def _sig_color(snr: float) -> str:
    if snr >= 30:
        return GREEN
    if snr >= 15:
        return YELLOW
    if snr >= 8:
        return CYAN
    return DIM


def _bar(snr: float, lo: float = 0.0, hi: float = 40.0, width: int = 16) -> str:
    frac  = max(0.0, min(1.0, (snr - lo) / (hi - lo)))
    filled = int(frac * width)
    return "█" * filled + "░" * (width - filled)


def _band_label(freq_hz: int) -> str:
    """Return the amateur band name for a frequency, or the MHz string."""
    for name, (lo, hi) in AMATEUR_BANDS.items():
        if lo <= freq_hz <= hi:
            return name
    return f"{freq_hz/1e6:.3f} MHz"


# ── SQLite ────────────────────────────────────────────────────────────────────

def _open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT NOT NULL,
            ts_unix     REAL NOT NULL,
            freq_hz     INTEGER NOT NULL,
            freq_mhz    REAL NOT NULL,
            band        TEXT,
            power_dbfs  REAL,
            snr_db      REAL,
            noise_dbfs  REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_d_ts   ON detections (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_d_freq ON detections (freq_hz)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_d_band ON detections (band)")
    conn.commit()
    return conn


def _log_detection(conn: sqlite3.Connection, freq_hz: int, power_dbfs: float,
                   snr_db: float, noise_dbfs: float) -> None:
    now = datetime.now(timezone.utc)
    band = _band_label(freq_hz)
    # If band looks like "X.XXX MHz" it's not a named amateur band
    if "MHz" in band:
        band = None
    conn.execute(
        "INSERT INTO detections "
        "(ts_utc, ts_unix, freq_hz, freq_mhz, band, power_dbfs, snr_db, noise_dbfs) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (now.isoformat(), now.timestamp(),
         freq_hz, round(freq_hz / 1e6, 6),
         band,
         round(power_dbfs, 2), round(snr_db, 2), round(noise_dbfs, 2)),
    )
    conn.commit()


# ── Sweep helpers ─────────────────────────────────────────────────────────────

def _psd_snr(iq: np.ndarray, rate: int, rbw_hz: float = 500.0
             ) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Compute Hann-windowed PSD from IQ block.

    Returns (freq_relative_hz, power_db, noise_db) where power_db is
    unnormalised dBFS (not peak-normalised) for cross-step comparability.
    """
    n       = len(iq)
    nperseg = max(64, 1 << int(np.log2(max(int(rate / rbw_hz), 64))))
    nperseg = min(nperseg, n)

    window  = np.hanning(nperseg).astype(np.float32)
    wpow    = float(np.sum(window ** 2))
    step    = max(1, nperseg // 2)
    segs    = []
    pos     = 0
    while pos + nperseg <= n:
        seg = iq[pos: pos + nperseg] * window
        segs.append(np.abs(np.fft.fft(seg, n=nperseg)) ** 2)
        pos += step

    if not segs:
        # fallback: single window
        w   = np.hanning(n).astype(np.float32)
        segs = [np.abs(np.fft.fft(iq * w, n=n)) ** 2]
        wpow = float(np.sum(w ** 2))
        nperseg = n

    psd    = np.mean(segs, axis=0) / wpow
    freq_r = np.fft.fftfreq(nperseg, d=1.0 / rate)
    psd_db = (10.0 * np.log10(psd + 1e-30)).astype(np.float32)

    freq_r = np.fft.fftshift(freq_r).astype(np.float32)
    psd_db = np.fft.fftshift(psd_db)

    noise  = float(np.median(psd_db))
    return freq_r, psd_db, noise


def _detect_signals(freq_center: int, iq: np.ndarray, rate: int,
                    squelch_db: float) -> list[dict]:
    """Return list of {'freq_hz', 'power_dbfs', 'snr_db', 'noise_dbfs'} above squelch."""
    freq_r, psd_db, noise = _psd_snr(iq, rate)
    freq_abs = freq_r + freq_center

    above   = (psd_db - noise) >= squelch_db
    signals = []
    in_sig, start = False, 0
    for i, flag in enumerate(above):
        if flag and not in_sig:
            start, in_sig = i, True
        elif not flag and in_sig:
            mid = (start + i) // 2
            f   = int(freq_abs[mid])
            p   = float(psd_db[mid])
            snr = p - noise
            signals.append({
                "freq_hz":    f,
                "power_dbfs": round(p, 2),
                "snr_db":     round(snr, 2),
                "noise_dbfs": round(noise, 2),
            })
            in_sig = False
    if in_sig:
        mid = (start + len(above)) // 2
        f   = int(freq_abs[mid])
        p   = float(psd_db[mid])
        snr = p - noise
        signals.append({
            "freq_hz":    f,
            "power_dbfs": round(p, 2),
            "snr_db":     round(snr, 2),
            "noise_dbfs": round(noise, 2),
        })

    return sorted(signals, key=lambda x: x["snr_db"], reverse=True)


# ── Display ───────────────────────────────────────────────────────────────────

def _print_status(use_color: bool, cycle: int, step_hz: int, squelch_db: float,
                  current_freq: int, recent: deque, total_det: int,
                  sweep_start: float, sweep_ranges: list[tuple[int, int]]) -> None:
    if use_color:
        os.system("clear")
    else:
        print("\033[H\033[J", end="")

    ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed  = time.monotonic() - sweep_start
    n_ranges = len(sweep_ranges)
    total_span = sum(hi - lo for lo, hi in sweep_ranges)
    hdr = f"{BOLD}HF Scanner — SunSDR2 Pro{RESET}" if use_color else "HF Scanner — SunSDR2 Pro"
    print(f"\n  {hdr}  —  {ts}  |  cycle #{cycle}")
    print(f"  Step: {step_hz/1e3:.0f} kHz  |  squelch: +{squelch_db:.0f} dB  "
          f"|  sweep span: {total_span/1e6:.1f} MHz  |  total detections: {total_det}")
    print(f"  Current: {current_freq/1e6:.4f} MHz  |  "
          f"sweep time: {elapsed:.0f}s")
    print(f"  {'─'*72}")

    # Recent detections table
    print(f"  {'Time':^10}  {'Freq (MHz)':>11}  {'Band':>6}  "
          f"{'SNR':>7}  {'Power':>9}  {'Bar':<16}")
    print(f"  {'─'*72}")

    if not recent:
        dim = DIM if use_color else ""
        rst = RESET if use_color else ""
        print(f"  {dim}No detections yet.{rst}")
    else:
        for det in recent:
            snr  = det["snr_db"]
            col  = _sig_color(snr) if use_color else ""
            rst  = RESET if use_color else ""
            band = det.get("band") or f"{det['freq_hz']/1e6:.3f}"
            print(f"  {col}{det['ts']:>10}  "
                  f"{det['freq_hz']/1e6:>11.4f}  "
                  f"{band:>6}  "
                  f"{snr:>+7.1f} dB  "
                  f"{det['power_dbfs']:>+8.1f} dBFS  "
                  f"{_bar(snr)}{rst}")

    print(f"\n  Press Ctrl-C to stop.\n")


# ── Main sweep loop ───────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    # Build sweep ranges
    if args.bands:
        band_names = [b.strip().lower() for b in args.bands.split(",")]
        sweep_ranges: list[tuple[int, int]] = []
        for name in band_names:
            if name not in AMATEUR_BANDS:
                print(f"Unknown band: {name}  (valid: {', '.join(AMATEUR_BANDS)})")
                sys.exit(1)
            sweep_ranges.append(AMATEUR_BANDS[name])
    else:
        sweep_ranges = [(ALL_HF_START, ALL_HF_STOP)]

    iq_rate   = 192_000
    step_hz   = args.step
    dwell     = args.dwell
    squelch   = args.squelch
    settle_s  = 0.025   # 25 ms post-retune settle

    conn = _open_db(args.db)

    print(f"\n  HF Scanner")
    print(f"  Host: {args.host}:{args.port}")
    print(f"  Step: {step_hz/1e3:.0f} kHz  |  dwell: {dwell} samples  "
          f"|  squelch: +{squelch:.0f} dB SNR")
    print(f"  Bands: {args.bands or 'all HF (0.1–55 MHz)'}")
    print(f"  SQLite: {args.db}")
    print(f"  Connecting...")

    try:
        sdr = SunSDR(args.host, port=args.port, iq_rate=iq_rate)
    except SunSDRError as e:
        print(f"ERROR connecting to SunSDR: {e}")
        sys.exit(1)

    print(f"  Connected: {sdr.identify()['device']}")
    sdr.set_mode("USB")

    recent:    deque = deque(maxlen=30)
    total_det  = 0
    cycle      = 0
    stop       = False

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    try:
        while not stop:
            cycle      += 1
            sweep_start = time.monotonic()
            current_freq = sweep_ranges[0][0]

            for start_hz, stop_hz in sweep_ranges:
                freq = start_hz
                while freq <= stop_hz and not stop:
                    current_freq = freq
                    try:
                        sdr.set_frequency(freq)
                        time.sleep(settle_s)
                        iq   = sdr.capture_iq(dwell)
                        hits = _detect_signals(freq, iq, iq_rate, squelch)
                    except SunSDRError as e:
                        print(f"  [error at {freq/1e6:.3f} MHz: {e}]")
                        freq += step_hz
                        continue

                    for hit in hits:
                        f    = hit["freq_hz"]
                        band = _band_label(f)
                        if "MHz" in band:
                            band_for_db = None
                        else:
                            band_for_db = band
                        _log_detection(conn, f, hit["power_dbfs"],
                                       hit["snr_db"], hit["noise_dbfs"])
                        total_det += 1
                        ts = datetime.now().strftime("%H:%M:%S")
                        recent.appendleft({
                            "ts":         ts,
                            "freq_hz":    f,
                            "band":       band_for_db,
                            "snr_db":     hit["snr_db"],
                            "power_dbfs": hit["power_dbfs"],
                        })
                        _print_status(use_color, cycle, step_hz, squelch,
                                      current_freq, recent, total_det,
                                      sweep_start, sweep_ranges)

                    freq += step_hz

            # Show final status at end of each sweep
            _print_status(use_color, cycle, step_hz, squelch,
                          current_freq, recent, total_det,
                          sweep_start, sweep_ranges)

    except Exception as e:
        print(f"\n  Unhandled error: {e}")
        raise
    finally:
        sdr.close()
        conn.close()

    print(f"\n  Stopped after {cycle} sweep cycles.  Total detections: {total_det}")
    print(f"  Database: {args.db}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="HF Scanner — SunSDR2 Pro wideband HF band scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python hf_scanner.py --host 192.168.1.100
  python hf_scanner.py --host 192.168.1.100 --bands 40m,20m,15m,10m
  python hf_scanner.py --host 192.168.1.100 --step 96000 --squelch 12
  python hf_scanner.py --host 192.168.1.100 --db my_scan.db

Named bands: 160m 80m 60m 40m 30m 20m 17m 15m 12m 10m 6m
        """,
    )
    p.add_argument("--host",     default="sunsdr.local",
                   help="SunSDR / ExpertSDR3 host IP (default: sunsdr.local)")
    p.add_argument("--port",     type=int, default=50001,
                   help="TCI WebSocket port (default: 50001)")
    p.add_argument("--step",     type=int, default=192_000,
                   help="Frequency step in Hz (default: 192000 = no gap at 192kHz IQ)")
    p.add_argument("--squelch",  type=float, default=12.0,
                   help="SNR threshold in dB above noise floor (default: 12)")
    p.add_argument("--dwell",    type=int, default=48_000,
                   help="IQ samples per step at 192kHz (default: 48000 = 250ms)")
    p.add_argument("--bands",    default=None,
                   help="Comma-separated band names to restrict sweep, e.g. 40m,20m,10m")
    p.add_argument("--db",       default="hf_scan.db",
                   help="SQLite output path (default: hf_scan.db)")
    p.add_argument("--no-color", action="store_true", dest="no_color",
                   help="Disable ANSI colours")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
