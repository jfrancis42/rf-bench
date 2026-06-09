#!/usr/bin/env python3
"""
Wideband Station Monitor — SunSDR2 Pro + RTL-SDR combined coverage.

SunSDR (TRX 0): covers 0.1–55 MHz + 100–150 MHz via TCI
RTL-SDR:        covers 55 MHz–1766 MHz

Together: near-complete coverage from 100 kHz to 1.7 GHz in a single unified
monitor.  Both receivers run in separate threads, logging detections to a shared
SQLite database.  A unified terminal display shows activity from both simultaneously.

The SunSDR's 192 kHz IQ bandwidth and RTL-SDR's 2.4 MHz IQ bandwidth complement
each other well: SunSDR provides high dynamic range on HF; RTL-SDR provides wide
instantaneous bandwidth on VHF/UHF.

Usage:
    python station_monitor.py --sdr-host 192.168.1.100
    python station_monitor.py --sdr-host 192.168.1.100 --rtlsdr-serial 00000001
    python station_monitor.py --sdr-host 192.168.1.100 --squelch 12 --no-color
    python station_monitor.py --sdr-host 192.168.1.100 --db monitor.db
"""

import argparse
import os
import queue
import signal
import sqlite3
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone

import numpy as np

from rf_bench.rtlsdr import RTLSDR, RTLSDRError
from rf_bench.sunsdr import SunSDR, SunSDRError


# ── Frequency coverage ────────────────────────────────────────────────────────

# SunSDR coverage: two ranges
SUNSDR_RANGES = [
    (100_000,    55_000_000),   # HF + 6m
    (100_000_000, 150_000_000), # VHF (2m)
]

# RTL-SDR coverage: starts where SunSDR HF ends, continues to max
RTLSDR_LO   =  55_000_000   # Hz
RTLSDR_HI   = 1_766_000_000 # Hz
RTLSDR_STEP =  2_400_000    # Hz (RTL-SDR instantaneous BW at 2.4 MS/s)
RTLSDR_RATE =  2_400_000    # S/s

SUNSDR_RATE = 192_000
SUNSDR_STEP = 192_000       # No overlap

# ── ANSI colours ─────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"


def _bar(snr: float, lo: float = 0.0, hi: float = 40.0, width: int = 10) -> str:
    frac   = max(0.0, min(1.0, (snr - lo) / (hi - lo)))
    filled = int(frac * width)
    return "█" * filled + "░" * (width - filled)


def _snr_col(snr: float, use_color: bool) -> str:
    if not use_color:
        return ""
    if snr >= 30:
        return GREEN
    if snr >= 15:
        return YELLOW
    return CYAN


# ── SQLite ────────────────────────────────────────────────────────────────────

_db_lock = threading.Lock()


def _open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT NOT NULL,
            ts_unix     REAL NOT NULL,
            source      TEXT NOT NULL,  -- 'sunsdr' or 'rtlsdr'
            freq_hz     INTEGER NOT NULL,
            freq_mhz    REAL NOT NULL,
            snr_db      REAL,
            noise_dbfs  REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts     ON detections (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON detections (source)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_freq   ON detections (freq_hz)")
    conn.commit()
    return conn


def _log(conn: sqlite3.Connection, source: str, freq_hz: int,
         snr_db: float, noise_dbfs: float) -> None:
    now = datetime.now(timezone.utc)
    with _db_lock:
        conn.execute(
            "INSERT INTO detections "
            "(ts_utc, ts_unix, source, freq_hz, freq_mhz, snr_db, noise_dbfs) "
            "VALUES (?,?,?,?,?,?,?)",
            (now.isoformat(), now.timestamp(),
             source, freq_hz, round(freq_hz / 1e6, 6),
             round(snr_db, 2), round(noise_dbfs, 2)),
        )
        conn.commit()


# ── IQ analysis ───────────────────────────────────────────────────────────────

def _detect(center_hz: int, iq: np.ndarray, rate: int,
            squelch_db: float) -> list[dict]:
    n      = len(iq)
    window = np.hanning(n).astype(np.float32)
    fft_db = 10.0 * np.log10(
        np.maximum(
            np.abs(np.fft.fftshift(np.fft.fft(iq * window))) ** 2
            / np.sum(window ** 2),
            1e-30
        )
    ).astype(np.float32)
    freq_r = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / rate)).astype(np.float32)
    noise  = float(np.median(fft_db))
    above  = (fft_db - noise) >= squelch_db
    freq_a = freq_r + center_hz

    signals = []
    in_sig, start = False, 0
    for i, flag in enumerate(above):
        if flag and not in_sig:
            start, in_sig = i, True
        elif not flag and in_sig:
            mid = (start + i) // 2
            signals.append({
                "freq_hz":  int(freq_a[mid]),
                "snr_db":   round(float(fft_db[mid]) - noise, 2),
                "noise_dbfs": round(noise, 2),
            })
            in_sig = False
    if in_sig:
        mid = (start + len(above)) // 2
        signals.append({
            "freq_hz":  int(freq_a[mid]),
            "snr_db":   round(float(fft_db[mid]) - noise, 2),
            "noise_dbfs": round(noise, 2),
        })
    return sorted(signals, key=lambda x: x["snr_db"], reverse=True)


# ── SunSDR sweep thread ───────────────────────────────────────────────────────

def _sunsdr_worker(host: str, port: int, squelch_db: float,
                   conn: sqlite3.Connection, event_q: queue.Queue,
                   stop_event: threading.Event) -> None:
    try:
        sdr = SunSDR(host, port=port, iq_rate=SUNSDR_RATE)
    except SunSDRError as e:
        event_q.put(("sunsdr_error", str(e)))
        return

    event_q.put(("sunsdr_ready", sdr.identify()["device"]))
    sdr.set_mode("USB")

    try:
        while not stop_event.is_set():
            for lo, hi in SUNSDR_RANGES:
                freq = lo
                while freq <= hi and not stop_event.is_set():
                    try:
                        sdr.set_frequency(freq)
                        time.sleep(0.02)
                        iq   = sdr.capture_iq(48_000)
                        hits = _detect(freq, iq, SUNSDR_RATE, squelch_db)
                    except SunSDRError as e:
                        event_q.put(("sunsdr_error", str(e)))
                        freq += SUNSDR_STEP
                        continue

                    for hit in hits:
                        _log(conn, "sunsdr", hit["freq_hz"],
                             hit["snr_db"], hit["noise_dbfs"])
                        event_q.put(("sunsdr_det", {
                            "ts":      datetime.now().strftime("%H:%M:%S"),
                            "freq_hz": hit["freq_hz"],
                            "snr_db":  hit["snr_db"],
                        }))

                    event_q.put(("sunsdr_step", freq))
                    freq += SUNSDR_STEP
    finally:
        sdr.close()


# ── RTL-SDR sweep thread ──────────────────────────────────────────────────────

def _rtlsdr_worker(serial: str | None, squelch_db: float,
                   conn: sqlite3.Connection, event_q: queue.Queue,
                   stop_event: threading.Event) -> None:
    try:
        rtl = RTLSDR(serial=serial)
        rtl.set_sample_rate(RTLSDR_RATE)
        rtl.set_gain("auto")
    except RTLSDRError as e:
        event_q.put(("rtlsdr_error", str(e)))
        return

    event_q.put(("rtlsdr_ready", rtl.identify()["device"]))

    try:
        while not stop_event.is_set():
            freq = RTLSDR_LO
            while freq <= RTLSDR_HI and not stop_event.is_set():
                try:
                    rtl.set_center_freq(freq)
                    time.sleep(0.02)
                    iq   = rtl.capture_iq(RTLSDR_RATE // 4)   # 250 ms
                    hits = _detect(freq, iq, RTLSDR_RATE, squelch_db)
                except RTLSDRError as e:
                    event_q.put(("rtlsdr_error", str(e)))
                    freq += RTLSDR_STEP
                    continue

                for hit in hits:
                    _log(conn, "rtlsdr", hit["freq_hz"],
                         hit["snr_db"], hit["noise_dbfs"])
                    event_q.put(("rtlsdr_det", {
                        "ts":      datetime.now().strftime("%H:%M:%S"),
                        "freq_hz": hit["freq_hz"],
                        "snr_db":  hit["snr_db"],
                    }))

                event_q.put(("rtlsdr_step", freq))
                freq += RTLSDR_STEP
    finally:
        rtl.close()


# ── Display ───────────────────────────────────────────────────────────────────

def _print_status(use_color: bool, cycle: int,
                  sunsdr_step: int, rtlsdr_step: int,
                  squelch_db: float,
                  sunsdr_recent: deque, rtlsdr_recent: deque,
                  sunsdr_total: int, rtlsdr_total: int) -> None:
    if use_color:
        os.system("clear")
    else:
        print("\033[H\033[J", end="")

    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hdr = f"{BOLD}Wideband Station Monitor{RESET}" if use_color else "Wideband Station Monitor"
    print(f"\n  {hdr}  —  {ts}  |  update #{cycle}")
    print(f"  SunSDR:  {sunsdr_step/1e6:>8.4f} MHz  det: {sunsdr_total}")
    print(f"  RTL-SDR: {rtlsdr_step/1e6:>8.4f} MHz  det: {rtlsdr_total}")
    print(f"  Squelch: +{squelch_db:.0f} dB SNR")
    print(f"  {'─'*72}")

    print(f"  {'── SunSDR (0.1–55 + 100–150 MHz) ──':<38}  RTL-SDR (55–1766 MHz)")
    print(f"  {'─'*72}")

    sdr_list = list(sunsdr_recent)[:14]
    rtl_list = list(rtlsdr_recent)[:14]
    rows     = max(len(sdr_list), len(rtl_list), 4)

    for i in range(rows):
        if i < len(sdr_list):
            d   = sdr_list[i]
            col = _snr_col(d["snr_db"], use_color)
            rst = RESET if use_color else ""
            sdr_col = f"{col}{d['ts']}  {d['freq_hz']/1e6:.4f}MHz  {d['snr_db']:+5.1f}dB{rst}"
        else:
            sdr_col = ""

        if i < len(rtl_list):
            d   = rtl_list[i]
            col = _snr_col(d["snr_db"], use_color)
            rst = RESET if use_color else ""
            rtl_col = f"{col}{d['ts']}  {d['freq_hz']/1e6:.4f}MHz  {d['snr_db']:+5.1f}dB{rst}"
        else:
            rtl_col = ""

        print(f"  {sdr_col:<38}  {rtl_col}")

    print(f"\n  Press Ctrl-C to stop.\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    conn       = _open_db(args.db)
    event_q: queue.Queue = queue.Queue()
    stop_event = threading.Event()

    sunsdr_recent = deque(maxlen=20)
    rtlsdr_recent = deque(maxlen=20)
    sunsdr_total  = 0
    rtlsdr_total  = 0
    sunsdr_step   = SUNSDR_RANGES[0][0]
    rtlsdr_step   = RTLSDR_LO
    cycle         = 0
    stop          = False

    print(f"\n  Wideband Station Monitor")
    print(f"  SunSDR: {args.sdr_host}:{args.sdr_port}")
    print(f"  RTL-SDR serial: {args.rtlsdr_serial or 'auto'}")
    print(f"  Squelch: +{args.squelch:.0f} dB  |  SQLite: {args.db}")
    print(f"  Starting threads...")

    sdr_thread = threading.Thread(
        target=_sunsdr_worker,
        args=(args.sdr_host, args.sdr_port, args.squelch, conn, event_q, stop_event),
        daemon=True, name="sunsdr-sweep",
    )
    rtl_thread = threading.Thread(
        target=_rtlsdr_worker,
        args=(args.rtlsdr_serial, args.squelch, conn, event_q, stop_event),
        daemon=True, name="rtlsdr-sweep",
    )

    sdr_thread.start()
    rtl_thread.start()

    def _sigint(*_):
        nonlocal stop
        stop = True
        stop_event.set()
    signal.signal(signal.SIGINT, _sigint)

    try:
        while not stop:
            cycle += 1
            for _ in range(500):
                try:
                    ev_type, ev_data = event_q.get_nowait()
                    if ev_type == "sunsdr_det":
                        sunsdr_recent.appendleft(ev_data)
                        sunsdr_total += 1
                    elif ev_type == "rtlsdr_det":
                        rtlsdr_recent.appendleft(ev_data)
                        rtlsdr_total += 1
                    elif ev_type == "sunsdr_step":
                        sunsdr_step = ev_data
                    elif ev_type == "rtlsdr_step":
                        rtlsdr_step = ev_data
                except queue.Empty:
                    break

            _print_status(use_color, cycle, sunsdr_step, rtlsdr_step,
                          args.squelch,
                          sunsdr_recent, rtlsdr_recent,
                          sunsdr_total, rtlsdr_total)

            if not sdr_thread.is_alive() and not rtl_thread.is_alive():
                break
            time.sleep(0.5)

    finally:
        stop_event.set()
        sdr_thread.join(timeout=5.0)
        rtl_thread.join(timeout=5.0)
        conn.close()

    print(f"\n  Stopped.  SunSDR: {sunsdr_total} det  RTL-SDR: {rtlsdr_total} det")
    print(f"  Database: {args.db}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Wideband Station Monitor — SunSDR2 Pro + RTL-SDR combined",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Coverage:
  SunSDR:  0.1–55 MHz + 100–150 MHz (HF + 6m + 2m)
  RTL-SDR: 55 MHz – 1766 MHz (VHF/UHF/SHF)

Examples:
  python station_monitor.py --sdr-host 192.168.1.100
  python station_monitor.py --sdr-host 192.168.1.100 --squelch 10
  python station_monitor.py --sdr-host 192.168.1.100 --rtlsdr-serial 00000001
        """,
    )
    p.add_argument("--sdr-host",       required=True, dest="sdr_host",
                   help="SunSDR host IP")
    p.add_argument("--sdr-port",       type=int, default=50001, dest="sdr_port")
    p.add_argument("--rtlsdr-serial",  default=None, dest="rtlsdr_serial",
                   help="RTL-SDR serial number (default: first device found)")
    p.add_argument("--squelch",        type=float, default=12.0,
                   help="SNR threshold in dB (default: 12)")
    p.add_argument("--db",             default="station_monitor.db",
                   help="SQLite output path (default: station_monitor.db)")
    p.add_argument("--no-color",       action="store_true", dest="no_color")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
