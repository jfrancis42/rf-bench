#!/usr/bin/env python3
"""
Band Opening Relay — SunSDR2 Pro 6m SSB activity detector + SMS alert.

Monitors 50.125 MHz (6m SSB calling frequency) using TRX 0 on the SunSDR.
When activity is detected above the threshold, writes a JSON alert file
that other tools (e.g. bubba-detector) can poll, and optionally sends an
SMS notification via the voipms proxy at https://voip.n0gq.org/sms.

The SunSDR's HF receiver port (TRX 0) covers 50 MHz directly — unlike the
KiwiSDR which is limited to 30 MHz, and unlike the RTL-SDR which would require
a separate 50 MHz antenna and coverage path.

Usage:
    python band_opening_relay.py --host 192.168.1.100
    python band_opening_relay.py --host 192.168.1.100 --threshold 8
    python band_opening_relay.py --host 192.168.1.100 --alert-file /tmp/6m_opening.json
    python band_opening_relay.py --host 192.168.1.100 --sms --sms-to 13035551234
"""

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone

import numpy as np

from rf_bench.sunsdr import SunSDR, SunSDRError


# ── Constants ─────────────────────────────────────────────────────────────────

# 6m SSB calling frequency
DEFAULT_FREQ_HZ = 50_125_000

# Path to the SMS sender script (relative to home directory)
SMS_SCRIPT = os.path.expanduser("~/Dropbox/build/money/sms.py")

# Alert file cooldown: don't resend SMS more often than this
SMS_COOLDOWN_S = 300   # 5 minutes

# ── ANSI colours ─────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"


def _bar(snr: float, lo: float = 0.0, hi: float = 30.0, width: int = 16) -> str:
    frac   = max(0.0, min(1.0, (snr - lo) / (hi - lo)))
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
            snr_db      REAL,
            noise_dbfs  REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS openings (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT NOT NULL,
            ts_unix     REAL NOT NULL,
            freq_hz     INTEGER NOT NULL,
            snr_db      REAL,
            sms_sent    INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_r_ts ON readings  (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_o_ts ON openings  (ts_unix)")
    conn.commit()
    return conn


def _log_reading(conn: sqlite3.Connection, freq_hz: int,
                 snr_db: float, noise_dbfs: float) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO readings (ts_utc, ts_unix, freq_hz, snr_db, noise_dbfs) "
        "VALUES (?,?,?,?,?)",
        (now.isoformat(), now.timestamp(),
         freq_hz, round(snr_db, 2), round(noise_dbfs, 2)),
    )
    conn.commit()


def _log_opening(conn: sqlite3.Connection, freq_hz: int,
                 snr_db: float, sms_sent: bool) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO openings (ts_utc, ts_unix, freq_hz, snr_db, sms_sent) "
        "VALUES (?,?,?,?,?)",
        (now.isoformat(), now.timestamp(),
         freq_hz, round(snr_db, 2), int(sms_sent)),
    )
    conn.commit()


# ── Alert file ────────────────────────────────────────────────────────────────

def _write_alert(path: str, freq_hz: int, snr_db: float) -> None:
    """Write JSON alert file atomically."""
    payload = {
        "ts_unix":  round(time.time(), 3),
        "ts_utc":   datetime.now(timezone.utc).isoformat(),
        "freq_hz":  freq_hz,
        "freq_mhz": round(freq_hz / 1e6, 4),
        "snr_db":   round(snr_db, 2),
        "band":     "6m",
        "opening":  True,
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def _clear_alert(path: str) -> None:
    """Overwrite alert file with no-opening state."""
    payload = {
        "ts_unix": round(time.time(), 3),
        "opening": False,
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


# ── SMS ───────────────────────────────────────────────────────────────────────

def _send_sms(to_number: str, freq_hz: int, snr_db: float) -> bool:
    """Send SMS via ~/money/sms.py.  Returns True on success."""
    if not os.path.exists(SMS_SCRIPT):
        print(f"  [SMS] Script not found: {SMS_SCRIPT}")
        return False
    msg = (f"6m band opening detected on {freq_hz/1e6:.3f} MHz  "
           f"SNR {snr_db:+.1f} dB  "
           f"{datetime.now().strftime('%H:%M UTC')}")
    try:
        result = subprocess.run(
            ["python3", SMS_SCRIPT, "--to", to_number, "--message", msg],
            timeout=15, capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  [SMS] Sent to {to_number}")
            return True
        else:
            print(f"  [SMS] Error: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"  [SMS] Failed: {e}")
        return False


# ── Signal measurement ────────────────────────────────────────────────────────

def _measure_snr(sdr: SunSDR, n_samples: int, rate: int) -> tuple[float, float]:
    """Return (peak_snr_db, noise_dbfs) from IQ capture."""
    iq     = sdr.capture_iq(n_samples)
    n      = len(iq)
    window = np.hanning(n).astype(np.float32)
    fft_db = 10.0 * np.log10(
        np.maximum(np.abs(np.fft.fft(iq * window)) ** 2 / np.sum(window ** 2), 1e-30)
    )
    noise  = float(np.median(fft_db))
    peak   = float(np.max(fft_db))
    return peak - noise, noise


# ── Display ───────────────────────────────────────────────────────────────────

def _print_status(use_color: bool, cycle: int, freq_hz: int,
                  snr_now: float, noise_now: float,
                  threshold: float, opening_active: bool,
                  recent_events: deque, total_openings: int) -> None:
    if use_color:
        os.system("clear")
    else:
        print("\033[H\033[J", end="")

    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hdr = f"{BOLD}6m Band Opening Relay{RESET}" if use_color else "6m Band Opening Relay"
    print(f"\n  {hdr}  —  {ts}  |  reading #{cycle}")
    print(f"  Monitor: {freq_hz/1e6:.4f} MHz  |  threshold: +{threshold:.0f} dB SNR")
    print()

    snr_col = GREEN if snr_now > threshold else (YELLOW if snr_now > threshold * 0.7 else DIM)
    open_str = ""
    if opening_active:
        open_str = f"  {GREEN if use_color else ''}*** BAND OPEN ***{RESET if use_color else ''}"
    rst = RESET if use_color else ""

    if use_color:
        print(f"  SNR:   {snr_col}{snr_now:+.1f} dB{rst}  "
              f"  Noise: {noise_now:+.1f} dBFS  "
              f"  Bar: {_bar(snr_now)}{open_str}")
    else:
        print(f"  SNR:   {snr_now:+.1f} dB  "
              f"  Noise: {noise_now:+.1f} dBFS  "
              f"  Bar: {_bar(snr_now)}{open_str}")

    print(f"  Total openings detected: {total_openings}")
    print(f"  {'─'*72}")

    if recent_events:
        print(f"\n  Recent openings:")
        for ev in recent_events:
            print(f"    {ev}")
    else:
        dim = DIM if use_color else ""
        print(f"\n  {dim}No openings detected yet.{rst}")

    print(f"\n  Press Ctrl-C to stop.\n")


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    freq_hz    = args.freq
    threshold  = args.threshold
    iq_rate    = 192_000
    dwell      = args.dwell

    conn = _open_db(args.db)

    print(f"\n  6m Band Opening Relay")
    print(f"  Host: {args.host}:{args.port}  |  freq: {freq_hz/1e6:.4f} MHz")
    print(f"  Threshold: +{threshold:.0f} dB SNR")
    if args.alert_file:
        print(f"  Alert file: {args.alert_file}")
    if args.sms:
        print(f"  SMS: enabled → {args.sms_to}")
    print(f"  SQLite: {args.db}")
    print(f"  Connecting...")

    try:
        sdr = SunSDR(args.host, port=args.port, iq_rate=iq_rate)
    except SunSDRError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    sdr.set_frequency(freq_hz)
    sdr.set_mode("USB")
    time.sleep(0.05)
    print(f"  Connected: {sdr.identify()['device']}")

    recent_events   = deque(maxlen=10)
    total_openings  = 0
    opening_active  = False
    last_sms_time   = 0.0
    cycle           = 0
    stop            = False

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    try:
        while not stop:
            cycle += 1
            try:
                snr_db, noise_dbfs = _measure_snr(sdr, dwell, iq_rate)
            except SunSDRError as e:
                print(f"  [SDR error: {e}]")
                time.sleep(1.0)
                continue

            _log_reading(conn, freq_hz, snr_db, noise_dbfs)

            new_opening = (snr_db >= threshold) and not opening_active
            was_open    = opening_active
            opening_active = snr_db >= threshold

            if new_opening:
                # First detection of this opening
                total_openings += 1
                ts_str   = datetime.now().strftime("%H:%M:%S")
                ev_str   = f"{ts_str}  SNR {snr_db:+.1f} dB  (new opening)"
                if use_color:
                    ev_str = f"{GREEN}{ev_str}{RESET}"
                recent_events.appendleft(ev_str)

                # Write alert file
                if args.alert_file:
                    try:
                        _write_alert(args.alert_file, freq_hz, snr_db)
                    except OSError as e:
                        print(f"  [alert file error: {e}]")

                # Send SMS (with cooldown)
                sms_sent = False
                if args.sms and (time.time() - last_sms_time) > SMS_COOLDOWN_S:
                    sms_sent      = _send_sms(args.sms_to, freq_hz, snr_db)
                    last_sms_time = time.time()

                _log_opening(conn, freq_hz, snr_db, sms_sent)

            elif was_open and not opening_active:
                # Closing edge
                if args.alert_file:
                    try:
                        _clear_alert(args.alert_file)
                    except OSError:
                        pass

            _print_status(use_color, cycle, freq_hz, snr_db, noise_dbfs,
                          threshold, opening_active, recent_events, total_openings)

    except Exception as e:
        print(f"\n  Unhandled error: {e}")
        raise
    finally:
        sdr.close()
        conn.close()

    print(f"\n  Stopped after {cycle} readings.  Total openings: {total_openings}")
    print(f"  Database: {args.db}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="6m Band Opening Relay — SunSDR2 Pro 50.125 MHz monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Monitors 50.125 MHz (6m SSB calling) for band openings.
Writes a JSON alert file and/or sends SMS when activity is detected.

Examples:
  python band_opening_relay.py --host 192.168.1.100
  python band_opening_relay.py --host 192.168.1.100 --threshold 8
  python band_opening_relay.py --host 192.168.1.100 --alert-file /tmp/6m.json
  python band_opening_relay.py --host 192.168.1.100 --sms --sms-to 13035551234
        """,
    )
    p.add_argument("--host",       required=True,
                   help="SunSDR host IP")
    p.add_argument("--port",       type=int, default=50001)
    p.add_argument("--freq",       type=int, default=DEFAULT_FREQ_HZ,
                   help=f"Monitor frequency Hz (default: {DEFAULT_FREQ_HZ} = 50.125 MHz)")
    p.add_argument("--threshold",  type=float, default=10.0,
                   help="SNR threshold in dB to declare opening (default: 10)")
    p.add_argument("--dwell",      type=int, default=192_000,
                   help="IQ samples per measurement (default: 192000 = 1s @ 192kHz)")
    p.add_argument("--alert-file", default=None, dest="alert_file",
                   help="JSON alert file path to write on opening")
    p.add_argument("--sms",        action="store_true",
                   help="Send SMS on first detection of each opening")
    p.add_argument("--sms-to",     default=None, dest="sms_to",
                   help="SMS destination phone number (E.164 format, e.g. 13035551234)")
    p.add_argument("--db",         default="band_opening.db",
                   help="SQLite log path (default: band_opening.db)")
    p.add_argument("--no-color",   action="store_true", dest="no_color")

    args = p.parse_args()

    if args.sms and not args.sms_to:
        print("ERROR: --sms requires --sms-to <phone_number>")
        sys.exit(1)

    run(args)


if __name__ == "__main__":
    main()
