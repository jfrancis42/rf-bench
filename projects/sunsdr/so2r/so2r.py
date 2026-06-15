#!/usr/bin/env python3
"""
SO2R (Single Operator Two Radio) Coordinator.

IC-7300 as the primary operating radio on one band.
SunSDR2 Pro monitors a second frequency for incoming signals.
When SunSDR detects activity above threshold, IC-7300's PTT is inhibited
(or a warning is issued) to prevent transmitting over incoming traffic.

Use cases:
  - Monitor 2m SSB calling while operating on HF
  - Monitor a DX frequency while operating on another band
  - Protect receive: prevent IC-7300 TX while SunSDR hears a signal

The SunSDR operates in full-time receive mode on the monitoring frequency.
A threshold SNR above the noise floor triggers the PTT inhibit.

Usage:
    python so2r.py --radio-host localhost --sdr-host 192.168.1.100 \
        --monitor-freq 144200000 --inhibit-threshold 8
    python so2r.py --radio-host localhost --sdr-host 192.168.1.100 \
        --monitor-freq 14074000 --no-inhibit --alert-only
    python so2r.py --radio-host localhost --sdr-host 192.168.1.100 \
        --monitor-freq 144200000 --log so2r.db
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

from rf_bench.icom import IC7300
from rf_bench.sunsdr import SunSDR, SunSDRError
from rf_bench import connect


# ── ANSI colours ─────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"


# ── SQLite ────────────────────────────────────────────────────────────────────

def _open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY,
            ts_utc       TEXT NOT NULL,
            ts_unix      REAL NOT NULL,
            event_type   TEXT NOT NULL,  -- 'signal', 'inhibit', 'allow'
            monitor_freq INTEGER,
            snr_db       REAL,
            noise_dbfs   REAL,
            ic7300_freq  INTEGER,
            ic7300_mode  TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts    ON events (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_etype ON events (event_type)")
    conn.commit()
    return conn


def _log_event(conn: sqlite3.Connection, event_type: str,
               monitor_freq: int, snr_db: float, noise_dbfs: float,
               ic7300_freq: int | None, ic7300_mode: str | None) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO events "
        "(ts_utc, ts_unix, event_type, monitor_freq, snr_db, noise_dbfs, "
        " ic7300_freq, ic7300_mode) VALUES (?,?,?,?,?,?,?,?)",
        (now.isoformat(), now.timestamp(),
         event_type, monitor_freq,
         round(snr_db, 2) if not np.isnan(snr_db) else None,
         round(noise_dbfs, 2) if not np.isnan(noise_dbfs) else None,
         ic7300_freq, ic7300_mode),
    )
    conn.commit()


# ── Signal detection ──────────────────────────────────────────────────────────

def _measure_snr(sdr: SunSDR, center_hz: int, n_samples: int,
                 rate: int) -> tuple[float, float]:
    """
    Measure SNR at center_hz.  Returns (snr_db, noise_dbfs).
    """
    sdr.set_frequency(center_hz)
    iq = sdr.capture_iq(n_samples)

    n      = len(iq)
    window = np.hanning(n).astype(np.float32)
    fft_db = 10.0 * np.log10(
        np.maximum(
            np.abs(np.fft.fft(iq * window)) ** 2 / np.sum(window ** 2),
            1e-30
        )
    )
    noise  = float(np.median(fft_db))
    peak   = float(np.max(fft_db))
    return peak - noise, noise


# ── Display ───────────────────────────────────────────────────────────────────

def _print_status(use_color: bool, cycle: int,
                  monitor_hz: int, ic7300_hz: int | None,
                  snr_now: float, noise_now: float,
                  threshold: float, inhibited: bool,
                  recent_events: deque, total_signals: int,
                  total_inhibits: int) -> None:
    if use_color:
        os.system("clear")
    else:
        print("\033[H\033[J", end="")

    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hdr = f"{BOLD}SO2R Coordinator{RESET}" if use_color else "SO2R Coordinator"
    print(f"\n  {hdr}  —  {ts}  |  cycle #{cycle}")
    print(f"  Monitor:   {monitor_hz/1e6:.4f} MHz  |  threshold: +{threshold:.0f} dB SNR")
    if ic7300_hz:
        print(f"  IC-7300:   {ic7300_hz/1e6:.4f} MHz")
    print()

    # Current state
    snr_col   = GREEN if snr_now > threshold else DIM
    inh_str   = f"{RED}PTT INHIBITED{RESET}" if inhibited and use_color else ("PTT INHIBITED" if inhibited else "PTT OK")
    inh_col   = RED if inhibited and use_color else ""

    if use_color:
        print(f"  SNR:  {snr_col}{snr_now:+.1f} dB{RESET}  "
              f"|  Noise: {noise_now:+.1f} dBFS  "
              f"|  Status: {inh_str}")
    else:
        print(f"  SNR:  {snr_now:+.1f} dB  "
              f"|  Noise: {noise_now:+.1f} dBFS  "
              f"|  Status: {inh_str}")

    print(f"  Signals detected: {total_signals}  |  PTT inhibits: {total_inhibits}")
    print(f"  {'─'*72}")

    print(f"\n  Recent events:")
    if not recent_events:
        dim = DIM if use_color else ""
        rst = RESET if use_color else ""
        print(f"  {dim}No events yet.{rst}")
    else:
        for ev in recent_events:
            print(f"    {ev}")

    print(f"\n  Press Ctrl-C to stop.\n")


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    monitor_hz = args.monitor_freq
    threshold  = args.inhibit_threshold
    iq_rate    = 192_000
    dwell      = args.dwell

    conn = _open_db(args.log) if args.log else None

    print(f"\n  SO2R Coordinator")
    print(f"  Radio: {args.radio_host}:{args.radio_port}")
    print(f"  SDR:   {args.sdr_host}:{args.sdr_port}")
    print(f"  Monitor: {monitor_hz/1e6:.4f} MHz  |  threshold: +{threshold:.0f} dB")
    print(f"  Inhibit PTT: {'NO (alert only)' if args.alert_only else 'YES'}")
    if args.log:
        print(f"  SQLite: {args.log}")
    print()

    # Connect to IC-7300
    print(f"  Connecting to IC-7300 via rigctld...")
    try:
        rig = IC7300(host=args.radio_host, port=args.radio_port)
        print(f"  IC-7300 connected.")
    except Exception as e:
        print(f"  WARNING: rigctld connection failed ({e})")
        print(f"  Continuing in monitor-only mode.")
        rig = None

    # Connect to SunSDR
    print(f"  Connecting to SunSDR...")
    try:
        sdr = SunSDR(args.sdr_host, port=args.sdr_port, iq_rate=iq_rate)
    except SunSDRError as e:
        print(f"  ERROR: {e}")
        if rig:
            rig.close()
        sys.exit(1)

    print(f"  Connected: {sdr.identify()['device']}")
    sdr.set_frequency(monitor_hz)
    sdr.set_mode("USB")
    time.sleep(0.05)

    recent_events = deque(maxlen=15)
    total_signals = 0
    total_inhibits = 0
    cycle          = 0
    stop           = False
    was_inhibited  = False

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    try:
        while not stop:
            cycle += 1
            snr_db = float("nan")
            noise  = float("nan")
            ic7300_hz = None
            ic7300_mode = None

            # Get IC-7300 frequency
            if rig:
                try:
                    ic7300_hz = int(rig.get_frequency())
                    mode_str, _ = rig.get_mode()
                    ic7300_mode = mode_str
                except Exception:
                    pass

            # Measure monitor frequency
            try:
                snr_db, noise = _measure_snr(sdr, monitor_hz, dwell, iq_rate)
            except SunSDRError as e:
                print(f"  [SDR error: {e}]")
                time.sleep(1.0)
                continue

            signal_active = (not np.isnan(snr_db)) and (snr_db >= threshold)
            inhibited     = signal_active and not args.alert_only

            # PTT inhibit logic (via rigctld)
            if rig and not args.alert_only:
                try:
                    current_ptt = False   # we don't track PTT state here
                    if inhibited and not was_inhibited:
                        # Rising edge: signal appeared — force PTT off
                        rig._cmd("\\set_ptt 0")
                        was_inhibited = True
                    elif not inhibited and was_inhibited:
                        # Falling edge: signal gone — PTT allowed
                        was_inhibited = False
                except Exception:
                    pass

            # Log events
            if signal_active:
                total_signals += 1
                if conn:
                    _log_event(conn, "signal", monitor_hz, snr_db, noise,
                               ic7300_hz, ic7300_mode)
                ts_str = datetime.now().strftime("%H:%M:%S")
                ev_str = (f"{ts_str}  Signal: {monitor_hz/1e6:.4f}MHz  "
                          f"SNR {snr_db:+.1f}dB  "
                          f"{'PTT INHIBITED' if inhibited else 'alert'}")
                if use_color and inhibited:
                    ev_str = f"{RED}{ev_str}{RESET}"
                elif use_color:
                    ev_str = f"{YELLOW}{ev_str}{RESET}"
                recent_events.appendleft(ev_str)

                if inhibited:
                    total_inhibits += 1
                    if conn:
                        _log_event(conn, "inhibit", monitor_hz, snr_db, noise,
                                   ic7300_hz, ic7300_mode)

            _print_status(use_color, cycle, monitor_hz, ic7300_hz,
                          snr_db if not np.isnan(snr_db) else 0.0,
                          noise if not np.isnan(noise) else 0.0,
                          threshold, inhibited,
                          recent_events, total_signals, total_inhibits)

    except Exception as e:
        print(f"\n  ERROR: {e}")
        raise
    finally:
        if rig:
            try:
                rig._cmd("\\set_ptt 0")   # ensure PTT off
            except Exception:
                pass
            rig.close()
        sdr.close()
        if conn:
            conn.close()

    print(f"\n  Stopped after {cycle} cycles.")
    print(f"  Signals detected: {total_signals}  |  PTT inhibits: {total_inhibits}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="SO2R Coordinator — IC-7300 + SunSDR2 Pro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python so2r.py --sdr-host 192.168.1.100 --monitor-freq 144200000
  python so2r.py --sdr-host 192.168.1.100 --monitor-freq 14074000 --alert-only
  python so2r.py --sdr-host 192.168.1.100 --monitor-freq 144200000 --log so2r.db
        """,
    )
    p.add_argument("--radio-host",       default="localhost", dest="radio_host",
                   help="rigctld host for IC-7300 (default: localhost)")
    p.add_argument("--radio-port",       type=int, default=4532, dest="radio_port")
    p.add_argument("--sdr-host",         required=True, dest="sdr_host",
                   help="SunSDR host IP")
    p.add_argument("--sdr-port",         type=int, default=50001, dest="sdr_port")
    p.add_argument("--monitor-freq",     type=int, required=True, dest="monitor_freq",
                   help="SunSDR monitoring frequency in Hz")
    p.add_argument("--inhibit-threshold", type=float, default=8.0, dest="inhibit_threshold",
                   help="SNR threshold in dB to trigger inhibit (default: 8)")
    p.add_argument("--dwell",            type=int, default=48_000,
                   help="IQ samples per measurement (default: 48000 = 250ms @ 192kHz)")
    p.add_argument("--alert-only",       action="store_true", dest="alert_only",
                   help="Alert on signal but do not inhibit IC-7300 PTT")
    p.add_argument("--log",              default=None,
                   help="SQLite log file path (optional)")
    p.add_argument("--no-color",         action="store_true", dest="no_color")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
