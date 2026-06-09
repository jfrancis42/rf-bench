#!/usr/bin/env python3
"""
VHF Monitor — SunSDR2 Pro 2m band activity monitor (TRX 1).

Uses TRX 1 on the SunSDR's VHF port (100–150 MHz RX) to continuously
monitor the 2m band.  Captures IQ blocks, detects signals above the squelch
threshold, logs detections to SQLite, and displays a rolling terminal activity
table.

The SunSDR's VHF receiver (TRX 1) has better dynamic range than the RTL-SDR
and avoids the need for a separate hardware device.  At 192 kHz rate it covers
±96 kHz of the 2m band per capture — from 143.9 to 144.3 MHz in a single shot
when centered at 144.1 MHz.

Usage:
    python vhf_monitor.py --host 192.168.1.100
    python vhf_monitor.py --host 192.168.1.100 --freq 144200000
    python vhf_monitor.py --host 192.168.1.100 --squelch 10 --no-color
    python vhf_monitor.py --host 192.168.1.100 --db 2m_monitor.db

Output:
    vhf_monitor.db  — SQLite log of all detections
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


# ── 2m sub-band definitions ───────────────────────────────────────────────────

# Key 2m frequencies for labelling detected signals
TWO_METER_FREQS: dict[str, int] = {
    "144.100 SSB calling": 144_100_000,
    "144.200 SSB calling": 144_200_000,
    "144.300 SSB":         144_300_000,
    "144.390 APRS":        144_390_000,
    "145.800 ISS uplink":  145_800_000,
    "146.520 FM calling":  146_520_000,
}

TWO_METER_LO  = 144_000_000
TWO_METER_HI  = 148_000_000
DEFAULT_CENTER = 144_200_000  # SSB calling frequency

VHF_LO = 100_000_000   # SunSDR TRX 1 lower limit
VHF_HI = 150_000_000   # SunSDR TRX 1 upper limit

# ── ANSI colours ─────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"


def _sig_color(snr: float) -> str:
    if snr >= 30:
        return GREEN
    if snr >= 15:
        return YELLOW
    if snr >= 8:
        return CYAN
    return DIM


def _bar(snr: float, lo: float = 0.0, hi: float = 40.0, width: int = 16) -> str:
    frac   = max(0.0, min(1.0, (snr - lo) / (hi - lo)))
    filled = int(frac * width)
    return "█" * filled + "░" * (width - filled)


def _freq_label(freq_hz: int, tol_hz: int = 20_000) -> str:
    """Return the well-known name for a 2m frequency if within tolerance."""
    for name, ref in TWO_METER_FREQS.items():
        if abs(freq_hz - ref) <= tol_hz:
            return name
    return f"{freq_hz / 1e6:.4f} MHz"


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
            label       TEXT,
            power_dbfs  REAL,
            snr_db      REAL,
            noise_dbfs  REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts   ON detections (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_freq ON detections (freq_hz)")
    conn.commit()
    return conn


def _log_detection(conn: sqlite3.Connection, freq_hz: int, label: str,
                   power_dbfs: float, snr_db: float, noise_dbfs: float) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO detections "
        "(ts_utc, ts_unix, freq_hz, freq_mhz, label, power_dbfs, snr_db, noise_dbfs) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (now.isoformat(), now.timestamp(),
         freq_hz, round(freq_hz / 1e6, 6),
         label,
         round(power_dbfs, 2), round(snr_db, 2), round(noise_dbfs, 2)),
    )
    conn.commit()


# ── IQ analysis ───────────────────────────────────────────────────────────────

def _detect_signals(center_hz: int, iq: np.ndarray, rate: int,
                    squelch_db: float) -> list[dict]:
    """Detect signals above squelch in the IQ capture."""
    n       = len(iq)
    window  = np.hanning(n).astype(np.float32)
    fft_raw = np.fft.fftshift(np.fft.fft(iq * window))
    psd_db  = 10.0 * np.log10(
        np.maximum(np.abs(fft_raw) ** 2 / np.sum(window ** 2), 1e-30)
    ).astype(np.float32)

    freq_r  = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / rate))
    freq_abs = freq_r + center_hz
    noise   = float(np.median(psd_db))
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
            signals.append({
                "freq_hz":    f,
                "power_dbfs": round(p, 2),
                "snr_db":     round(p - noise, 2),
                "noise_dbfs": round(noise, 2),
            })
            in_sig = False
    if in_sig:
        mid = (start + len(above)) // 2
        f   = int(freq_abs[mid])
        p   = float(psd_db[mid])
        signals.append({
            "freq_hz":    f,
            "power_dbfs": round(p, 2),
            "snr_db":     round(p - noise, 2),
            "noise_dbfs": round(noise, 2),
        })

    return sorted(signals, key=lambda x: x["snr_db"], reverse=True)


# ── Display ───────────────────────────────────────────────────────────────────

def _print_status(use_color: bool, cycle: int, center_hz: int,
                  iq_rate: int, squelch_db: float,
                  recent: deque, total_det: int) -> None:
    if use_color:
        os.system("clear")
    else:
        print("\033[H\033[J", end="")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bw_lo = (center_hz - iq_rate // 2) / 1e6
    bw_hi = (center_hz + iq_rate // 2) / 1e6
    hdr = f"{BOLD}VHF Monitor — SunSDR2 Pro TRX 1{RESET}" if use_color else "VHF Monitor — SunSDR2 Pro TRX 1"
    print(f"\n  {hdr}  —  {ts}  |  capture #{cycle}")
    print(f"  Center: {center_hz/1e6:.4f} MHz  |  "
          f"passband: {bw_lo:.3f}–{bw_hi:.3f} MHz  |  "
          f"squelch: +{squelch_db:.0f} dB  |  "
          f"total detections: {total_det}")
    print(f"  {'─'*72}")

    print(f"  {'Time':^10}  {'Freq (MHz)':>11}  {'Label':<26}  "
          f"{'SNR':>7}  {'Bar':<16}")
    print(f"  {'─'*72}")

    if not recent:
        dim = DIM if use_color else ""
        rst = RESET if use_color else ""
        print(f"  {dim}No detections yet.{rst}")
    else:
        for det in recent:
            snr = det["snr_db"]
            col = _sig_color(snr) if use_color else ""
            rst = RESET if use_color else ""
            print(f"  {col}{det['ts']:>10}  "
                  f"{det['freq_hz']/1e6:>11.4f}  "
                  f"{det['label']:<26}  "
                  f"{snr:>+7.1f} dB  "
                  f"{_bar(snr)}{rst}")

    print(f"\n  Press Ctrl-C to stop.\n")


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    center_hz = args.freq
    if not (VHF_LO <= center_hz <= VHF_HI):
        print(f"ERROR: --freq {center_hz} is outside TRX 1 range "
              f"({VHF_LO/1e6:.0f}–{VHF_HI/1e6:.0f} MHz)")
        sys.exit(1)

    iq_rate  = 192_000
    squelch  = args.squelch
    dwell    = args.dwell
    conn     = _open_db(args.db)

    print(f"\n  VHF Monitor")
    print(f"  Host: {args.host}:{args.port}  |  TRX: 1 (VHF)")
    print(f"  Center: {center_hz/1e6:.4f} MHz  |  passband: ±{iq_rate//2000:.0f} kHz")
    print(f"  Squelch: +{squelch:.0f} dB  |  dwell: {dwell} samples")
    print(f"  SQLite: {args.db}")
    print(f"  Connecting...")

    try:
        sdr = SunSDR(args.host, port=args.port, trx=1, iq_rate=iq_rate)
    except SunSDRError as e:
        print(f"ERROR connecting to SunSDR TRX 1: {e}")
        print("  Note: TRX 1 requires ExpertSDR3 to have a second receiver enabled.")
        print("  Enable via Settings → RX → Add receiver")
        sys.exit(1)

    print(f"  Connected: {sdr.identify()['device']}")
    sdr.set_frequency(center_hz)
    sdr.set_mode("USB")
    time.sleep(0.05)   # settle

    recent     = deque(maxlen=30)
    total_det  = 0
    cycle      = 0
    stop       = False

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    try:
        while not stop:
            cycle += 1
            try:
                iq   = sdr.capture_iq(dwell)
                hits = _detect_signals(center_hz, iq, iq_rate, squelch)
            except SunSDRError as e:
                print(f"  [IQ error: {e}]")
                time.sleep(1.0)
                continue

            for hit in hits:
                label = _freq_label(hit["freq_hz"])
                _log_detection(conn, hit["freq_hz"], label,
                               hit["power_dbfs"], hit["snr_db"], hit["noise_dbfs"])
                total_det += 1
                ts = datetime.now().strftime("%H:%M:%S")
                recent.appendleft({
                    "ts":         ts,
                    "freq_hz":    hit["freq_hz"],
                    "label":      label,
                    "snr_db":     hit["snr_db"],
                    "power_dbfs": hit["power_dbfs"],
                })

            _print_status(use_color, cycle, center_hz, iq_rate, squelch,
                          recent, total_det)

    except Exception as e:
        print(f"\n  Unhandled error: {e}")
        raise
    finally:
        sdr.close()
        conn.close()

    print(f"\n  Stopped after {cycle} captures.  Total detections: {total_det}")
    print(f"  Database: {args.db}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="VHF Monitor — SunSDR2 Pro TRX 1 2m band activity monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python vhf_monitor.py --host 192.168.1.100
  python vhf_monitor.py --host 192.168.1.100 --freq 144390000  # APRS
  python vhf_monitor.py --host 192.168.1.100 --freq 146520000  # FM calling
  python vhf_monitor.py --host 192.168.1.100 --squelch 8 --dwell 96000

TRX 1 covers 100–150 MHz (RX only).  TX is not available on TRX 1.
        """,
    )
    p.add_argument("--host",     default="sunsdr.local",
                   help="SunSDR / ExpertSDR3 host IP (default: sunsdr.local)")
    p.add_argument("--port",     type=int, default=50001,
                   help="TCI WebSocket port (default: 50001)")
    p.add_argument("--freq",     type=int, default=DEFAULT_CENTER,
                   help=f"Center frequency in Hz (default: {DEFAULT_CENTER} = 144.200 MHz)")
    p.add_argument("--squelch",  type=float, default=10.0,
                   help="SNR threshold in dB above noise floor (default: 10)")
    p.add_argument("--dwell",    type=int, default=192_000,
                   help="IQ samples per capture at 192kHz (default: 192000 = 1 s)")
    p.add_argument("--db",       default="vhf_monitor.db",
                   help="SQLite output path (default: vhf_monitor.db)")
    p.add_argument("--no-color", action="store_true", dest="no_color",
                   help="Disable ANSI colours")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
