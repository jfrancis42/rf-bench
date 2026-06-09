#!/usr/bin/env python3
"""
Dual-Band Scanner — SunSDR2 Pro simultaneous HF sweep + VHF monitor.

TRX 0 sweeps one or more HF amateur bands; TRX 1 continuously monitors
a VHF frequency (default: 144.200 MHz SSB calling).  Both receivers run
simultaneously in separate threads, writing to a shared SQLite database.
The terminal displays a unified view: HF sweep progress on one side,
recent VHF detections on the other.

This is the first rf-bench project to exploit true dual-receiver operation
on a single device.  Each SunSDR() instance opens its own WebSocket
connection to ExpertSDR3 (one per TRX index).

Usage:
    python dual_scan.py --host 192.168.1.100
    python dual_scan.py --host 192.168.1.100 --hf-bands 40m,20m,10m
    python dual_scan.py --host 192.168.1.100 --vhf-freq 144390000
    python dual_scan.py --host 192.168.1.100 --hf-squelch 12 --vhf-squelch 8

Output:
    dual_scan.db  — SQLite log with source='hf' or source='vhf' column
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

from rf_bench.sunsdr import SunSDR, SunSDRError


# ── Band definitions ──────────────────────────────────────────────────────────

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

DEFAULT_HF_BANDS  = "40m,20m,15m,10m"
DEFAULT_VHF_FREQ  = 144_200_000
DEFAULT_IQ_RATE   = 192_000

# ── ANSI colours ─────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"


def _bar(snr: float, lo: float = 0.0, hi: float = 40.0, width: int = 12) -> str:
    frac   = max(0.0, min(1.0, (snr - lo) / (hi - lo)))
    filled = int(frac * width)
    return "█" * filled + "░" * (width - filled)


def _sig_color(snr: float) -> str:
    if snr >= 30:
        return GREEN
    if snr >= 15:
        return YELLOW
    if snr >= 8:
        return CYAN
    return DIM


# ── SQLite ────────────────────────────────────────────────────────────────────

_db_lock = threading.Lock()


def _open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT NOT NULL,
            ts_unix     REAL NOT NULL,
            source      TEXT NOT NULL,  -- 'hf' or 'vhf'
            freq_hz     INTEGER NOT NULL,
            freq_mhz    REAL NOT NULL,
            band        TEXT,
            power_dbfs  REAL,
            snr_db      REAL,
            noise_dbfs  REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts     ON detections (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON detections (source)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_freq   ON detections (freq_hz)")
    conn.commit()
    return conn


def _log(conn: sqlite3.Connection, source: str, freq_hz: int, band: str | None,
         power_dbfs: float, snr_db: float, noise_dbfs: float) -> None:
    now = datetime.now(timezone.utc)
    with _db_lock:
        conn.execute(
            "INSERT INTO detections "
            "(ts_utc, ts_unix, source, freq_hz, freq_mhz, band, power_dbfs, snr_db, noise_dbfs) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (now.isoformat(), now.timestamp(),
             source, freq_hz, round(freq_hz / 1e6, 6),
             band,
             round(power_dbfs, 2), round(snr_db, 2), round(noise_dbfs, 2)),
        )
        conn.commit()


# ── IQ analysis (shared) ──────────────────────────────────────────────────────

def _detect_signals(center_hz: int, iq: np.ndarray, rate: int,
                    squelch_db: float) -> list[dict]:
    n       = len(iq)
    window  = np.hanning(n).astype(np.float32)
    fft_raw = np.fft.fftshift(np.fft.fft(iq * window))
    psd_db  = 10.0 * np.log10(
        np.maximum(np.abs(fft_raw) ** 2 / np.sum(window ** 2), 1e-30)
    ).astype(np.float32)

    freq_r   = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / rate))
    freq_abs = freq_r + center_hz
    noise    = float(np.median(psd_db))
    above    = (psd_db - noise) >= squelch_db

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
        signals.append({
            "freq_hz":    int(freq_abs[mid]),
            "power_dbfs": round(float(psd_db[mid]), 2),
            "snr_db":     round(float(psd_db[mid]) - noise, 2),
            "noise_dbfs": round(noise, 2),
        })

    return sorted(signals, key=lambda x: x["snr_db"], reverse=True)


def _band_label(freq_hz: int) -> str | None:
    for name, (lo, hi) in AMATEUR_BANDS.items():
        if lo <= freq_hz <= hi:
            return name
    return None


# ── HF sweep thread ───────────────────────────────────────────────────────────

def _hf_worker(host: str, port: int, sweep_ranges: list[tuple[int, int]],
               squelch_db: float, dwell_samples: int, step_hz: int,
               conn: sqlite3.Connection, event_q: queue.Queue,
               stop_event: threading.Event) -> None:
    try:
        sdr = SunSDR(host, port=port, trx=0, iq_rate=DEFAULT_IQ_RATE)
    except SunSDRError as e:
        event_q.put(("hf_error", f"TRX 0 connect failed: {e}"))
        return

    event_q.put(("hf_ready", sdr.identify()["device"]))
    sdr.set_mode("USB")

    try:
        while not stop_event.is_set():
            for start_hz, stop_hz in sweep_ranges:
                freq = start_hz
                while freq <= stop_hz and not stop_event.is_set():
                    try:
                        sdr.set_frequency(freq)
                        time.sleep(0.025)
                        iq   = sdr.capture_iq(dwell_samples)
                        hits = _detect_signals(freq, iq, DEFAULT_IQ_RATE, squelch_db)
                    except SunSDRError as e:
                        event_q.put(("hf_error", f"at {freq/1e6:.3f}MHz: {e}"))
                        freq += step_hz
                        continue

                    for hit in hits:
                        band = _band_label(hit["freq_hz"])
                        _log(conn, "hf", hit["freq_hz"], band,
                             hit["power_dbfs"], hit["snr_db"], hit["noise_dbfs"])
                        event_q.put(("hf_det", {
                            "ts":         datetime.now().strftime("%H:%M:%S"),
                            "freq_hz":    hit["freq_hz"],
                            "band":       band,
                            "snr_db":     hit["snr_db"],
                            "power_dbfs": hit["power_dbfs"],
                        }))

                    event_q.put(("hf_step", freq))
                    freq += step_hz
    finally:
        sdr.close()


# ── VHF monitor thread ────────────────────────────────────────────────────────

def _vhf_worker(host: str, port: int, center_hz: int,
                squelch_db: float, dwell_samples: int,
                conn: sqlite3.Connection, event_q: queue.Queue,
                stop_event: threading.Event) -> None:
    try:
        sdr = SunSDR(host, port=port, trx=1, iq_rate=DEFAULT_IQ_RATE)
    except SunSDRError as e:
        event_q.put(("vhf_error", f"TRX 1 connect failed: {e}"))
        return

    event_q.put(("vhf_ready", sdr.identify()["device"]))
    sdr.set_frequency(center_hz)
    sdr.set_mode("USB")
    time.sleep(0.05)

    try:
        while not stop_event.is_set():
            try:
                iq   = sdr.capture_iq(dwell_samples)
                hits = _detect_signals(center_hz, iq, DEFAULT_IQ_RATE, squelch_db)
            except SunSDRError as e:
                event_q.put(("vhf_error", f"IQ error: {e}"))
                time.sleep(1.0)
                continue

            for hit in hits:
                _log(conn, "vhf", hit["freq_hz"], None,
                     hit["power_dbfs"], hit["snr_db"], hit["noise_dbfs"])
                event_q.put(("vhf_det", {
                    "ts":         datetime.now().strftime("%H:%M:%S"),
                    "freq_hz":    hit["freq_hz"],
                    "snr_db":     hit["snr_db"],
                    "power_dbfs": hit["power_dbfs"],
                }))
    finally:
        sdr.close()


# ── Display ───────────────────────────────────────────────────────────────────

def _print_status(use_color: bool, cycle: int, hf_step: int,
                  vhf_center: int, hf_squelch: float, vhf_squelch: float,
                  hf_recent: deque, vhf_recent: deque,
                  hf_total: int, vhf_total: int) -> None:
    if use_color:
        os.system("clear")
    else:
        print("\033[H\033[J", end="")

    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hdr = f"{BOLD}Dual-Band Scanner — SunSDR2 Pro{RESET}" if use_color else "Dual-Band Scanner — SunSDR2 Pro"
    print(f"\n  {hdr}  —  {ts}  |  update #{cycle}")
    print(f"  TRX 0 (HF): {hf_step/1e6:.4f} MHz  squelch +{hf_squelch:.0f} dB  "
          f"detections: {hf_total}")
    print(f"  TRX 1 (VHF): center {vhf_center/1e6:.4f} MHz  "
          f"squelch +{vhf_squelch:.0f} dB  detections: {vhf_total}")
    print(f"  {'─'*72}")

    # Side-by-side or stacked layout
    print(f"\n  {'── HF Detections (TRX 0) ──':<38}  VHF Detections (TRX 1)")
    print(f"  {'─'*72}")

    hf_list  = list(hf_recent)[:12]
    vhf_list = list(vhf_recent)[:12]
    rows     = max(len(hf_list), len(vhf_list), 5)

    for i in range(rows):
        # HF column
        if i < len(hf_list):
            d   = hf_list[i]
            snr = d["snr_db"]
            col = _sig_color(snr) if use_color else ""
            rst = RESET if use_color else ""
            band = d.get("band") or f"{d['freq_hz']/1e6:.3f}"
            hf_col = f"{col}{d['ts']}  {d['freq_hz']/1e6:.4f}MHz  {band:<5}  {snr:+5.1f}dB{rst}"
        else:
            hf_col = ""

        # VHF column
        if i < len(vhf_list):
            d   = vhf_list[i]
            snr = d["snr_db"]
            col = _sig_color(snr) if use_color else ""
            rst = RESET if use_color else ""
            vhf_col = f"{col}{d['ts']}  {d['freq_hz']/1e6:.4f}MHz  {snr:+5.1f}dB{rst}"
        else:
            vhf_col = ""

        print(f"  {hf_col:<38}  {vhf_col}")

    print(f"\n  Press Ctrl-C to stop.\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    # Build HF sweep ranges
    band_names = [b.strip().lower() for b in args.hf_bands.split(",")]
    sweep_ranges: list[tuple[int, int]] = []
    for name in band_names:
        if name not in AMATEUR_BANDS:
            print(f"Unknown HF band: {name}  (valid: {', '.join(AMATEUR_BANDS)})")
            sys.exit(1)
        sweep_ranges.append(AMATEUR_BANDS[name])

    conn       = _open_db(args.db)
    event_q: queue.Queue = queue.Queue()
    stop_event = threading.Event()

    hf_recent  = deque(maxlen=20)
    vhf_recent = deque(maxlen=20)
    hf_total   = 0
    vhf_total  = 0
    hf_step    = sweep_ranges[0][0]
    cycle      = 0
    stop       = False

    print(f"\n  Dual-Band Scanner")
    print(f"  Host: {args.host}:{args.port}")
    print(f"  HF bands: {args.hf_bands}  squelch +{args.hf_squelch:.0f} dB")
    print(f"  VHF center: {args.vhf_freq/1e6:.4f} MHz  squelch +{args.vhf_squelch:.0f} dB")
    print(f"  SQLite: {args.db}")
    print(f"  Starting TRX 0 (HF) and TRX 1 (VHF) threads...")

    hf_thread = threading.Thread(
        target=_hf_worker,
        args=(args.host, args.port, sweep_ranges,
              args.hf_squelch, args.hf_dwell, args.step,
              conn, event_q, stop_event),
        daemon=True, name="hf-sweep",
    )
    vhf_thread = threading.Thread(
        target=_vhf_worker,
        args=(args.host, args.port, args.vhf_freq,
              args.vhf_squelch, args.vhf_dwell,
              conn, event_q, stop_event),
        daemon=True, name="vhf-monitor",
    )

    hf_thread.start()
    vhf_thread.start()

    def _sigint(*_):
        nonlocal stop
        stop = True
        stop_event.set()
    signal.signal(signal.SIGINT, _sigint)

    try:
        while not stop:
            cycle += 1
            # Drain the event queue
            for _ in range(200):
                try:
                    ev_type, ev_data = event_q.get_nowait()
                    if ev_type == "hf_det":
                        hf_recent.appendleft(ev_data)
                        hf_total += 1
                    elif ev_type == "vhf_det":
                        vhf_recent.appendleft(ev_data)
                        vhf_total += 1
                    elif ev_type == "hf_step":
                        hf_step = ev_data
                    elif ev_type in ("hf_error", "vhf_error"):
                        pass   # errors appear in the thread's own print
                except queue.Empty:
                    break

            _print_status(use_color, cycle, hf_step, args.vhf_freq,
                          args.hf_squelch, args.vhf_squelch,
                          hf_recent, vhf_recent, hf_total, vhf_total)

            if not hf_thread.is_alive() and not vhf_thread.is_alive():
                break

            time.sleep(0.5)

    finally:
        stop_event.set()
        hf_thread.join(timeout=5.0)
        vhf_thread.join(timeout=5.0)
        conn.close()

    print(f"\n  Stopped.  HF detections: {hf_total}  VHF detections: {vhf_total}")
    print(f"  Database: {args.db}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Dual-Band Scanner — SunSDR2 Pro TRX 0 (HF) + TRX 1 (VHF)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dual_scan.py --host 192.168.1.100
  python dual_scan.py --host 192.168.1.100 --hf-bands 40m,20m --vhf-freq 144390000
  python dual_scan.py --host 192.168.1.100 --hf-squelch 12 --vhf-squelch 8
        """,
    )
    p.add_argument("--host",        default="sunsdr.local",
                   help="SunSDR / ExpertSDR3 host IP")
    p.add_argument("--port",        type=int, default=50001)
    p.add_argument("--hf-bands",    default=DEFAULT_HF_BANDS, dest="hf_bands",
                   help=f"HF bands to sweep (default: {DEFAULT_HF_BANDS})")
    p.add_argument("--vhf-freq",    type=int, default=DEFAULT_VHF_FREQ, dest="vhf_freq",
                   help=f"VHF center frequency Hz (default: {DEFAULT_VHF_FREQ})")
    p.add_argument("--step",        type=int, default=192_000,
                   help="HF frequency step in Hz (default: 192000)")
    p.add_argument("--hf-squelch",  type=float, default=12.0, dest="hf_squelch",
                   help="HF SNR threshold dB (default: 12)")
    p.add_argument("--vhf-squelch", type=float, default=10.0, dest="vhf_squelch",
                   help="VHF SNR threshold dB (default: 10)")
    p.add_argument("--hf-dwell",    type=int, default=48_000, dest="hf_dwell",
                   help="HF IQ samples per step (default: 48000 = 250ms @ 192kHz)")
    p.add_argument("--vhf-dwell",   type=int, default=192_000, dest="vhf_dwell",
                   help="VHF IQ samples per capture (default: 192000 = 1s)")
    p.add_argument("--db",          default="dual_scan.db",
                   help="SQLite output path (default: dual_scan.db)")
    p.add_argument("--no-color",    action="store_true", dest="no_color")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
