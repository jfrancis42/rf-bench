#!/usr/bin/env -S python3 -u
"""
Flipper Zero Sub-GHz Packet Decoder and Logger

Receives ISM packets via the Flipper CC1101, logs protocol name and decoded
data to a SQLite database. Optionally commands the SSA to do a narrow-span
sweep after each decode to characterize the transmission (bandwidth, frequency
error in ppm).

Usage:
  python subghz_decode.py --freq 433.92 --duration 300
  python subghz_decode.py --freq 433.92 --ssa 10.1.1.60 --db packets.db
  python subghz_decode.py --freq 315 --duration 0
"""

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero
try:
    from rf_bench.siglent import SSA3000X
from rf_bench import connect
    _SSA_AVAILABLE = True
except ImportError:
    _SSA_AVAILABLE = False

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_FREQ_MHZ  = 433.92
DEFAULT_DURATION  = 300      # seconds; 0 = forever
DEFAULT_DB        = "subghz_packets.db"
DEFAULT_SERIAL    = "/dev/ttyACM0"
DEFAULT_SSA_HOST  = None  # Now uses inventory
SSA_SPAN_HZ       = 500_000  # narrow span around carrier for RF characterization

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C — stopping receive loop]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS packets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            freq_hz     REAL    NOT NULL,
            protocol    TEXT,
            code        TEXT,
            raw_data    TEXT,
            bw_hz       REAL,
            freq_err_ppm REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON packets(ts)")
    conn.commit()
    return conn


def log_packet(conn: sqlite3.Connection, freq_hz: float, protocol: str,
               code: str, raw_data: str, bw_hz: float = None,
               freq_err_ppm: float = None) -> None:
    ts = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO packets(ts,freq_hz,protocol,code,raw_data,bw_hz,freq_err_ppm) "
        "VALUES (?,?,?,?,?,?,?)",
        (ts, freq_hz, protocol, code, raw_data, bw_hz, freq_err_ppm),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# SSA characterization
# ---------------------------------------------------------------------------

def ssa_characterize(ssa, freq_hz: float) -> tuple:
    """
    Do a narrow-span sweep around freq_hz.
    Returns (bandwidth_hz, freq_error_ppm).
    """
    start = freq_hz - SSA_SPAN_HZ / 2
    stop  = freq_hz + SSA_SPAN_HZ / 2
    ssa.setup_band(int(start), int(stop))
    ssa.single_sweep()
    trace = ssa.get_trace()
    freqs = np.linspace(start, stop, len(trace))

    peak_idx = int(np.argmax(trace))
    peak_dbm = float(trace[peak_idx])
    peak_hz  = float(freqs[peak_idx])
    ppm      = (peak_hz - freq_hz) / freq_hz * 1e6

    # 3 dB bandwidth: find crossings at peak - 3
    threshold = peak_dbm - 3.0
    above = trace >= threshold
    indices = np.where(above)[0]
    if len(indices) >= 2:
        bw_hz = float(freqs[indices[-1]] - freqs[indices[0]])
    else:
        bw_hz = 0.0

    return bw_hz, ppm


# ---------------------------------------------------------------------------
# Decode loop
# ---------------------------------------------------------------------------

def decode_loop(fz: FlipperZero, conn: sqlite3.Connection, freq_hz: float,
                duration_s: float, ssa=None) -> int:
    """
    Main receive loop. Returns total packets logged.
    """
    total = 0
    t_start = time.time()
    print(f"\n[LISTENING @ {freq_hz/1e6:.4f} MHz]  "
          f"duration={'forever' if duration_s == 0 else f'{duration_s:.0f} s'}"
          f"{'  +SSA' if ssa else ''}")
    print(f"  {'Time':>10}  {'Protocol':>16}  {'Code':>24}  {'BW (kHz)':>10}  {'ppm':>8}")
    print("  " + "-" * 76)

    while _running:
        elapsed = time.time() - t_start
        if duration_s > 0 and elapsed >= duration_s:
            break

        # Flipper raw capture (2 s window)
        raw = fz.subghz_get_raw(int(freq_hz), duration_s=2.0)
        if not raw:
            continue

        # Parse: Flipper returns lines with Protocol: / Code: fields
        protocol = "Unknown"
        code     = ""
        for line in raw.splitlines():
            if line.startswith("Protocol:"):
                protocol = line.split(":", 1)[1].strip()
            elif line.startswith("Code:"):
                code = line.split(":", 1)[1].strip()

        if not code and not protocol:
            continue

        bw_hz    = None
        freq_ppm = None

        if ssa is not None:
            try:
                bw_hz, freq_ppm = ssa_characterize(ssa, freq_hz)
            except Exception:
                pass

        log_packet(conn, freq_hz, protocol, code, raw, bw_hz, freq_ppm)
        total += 1
        ts_short = datetime.now().strftime("%H:%M:%S")
        bw_str   = f"{bw_hz/1e3:.1f}" if bw_hz else "  —"
        ppm_str  = f"{freq_ppm:+.1f}" if freq_ppm is not None else "  —"
        print(f"  {ts_short:>10}  {protocol:>16}  {code[:24]:>24}  {bw_str:>10}  {ppm_str:>8}")

    return total


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Flipper Zero Sub-GHz packet decoder and SQLite logger",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python subghz_decode.py --freq 433.92 --duration 300
  python subghz_decode.py --freq 315 --ssa 10.1.1.60 --db garage.db
  python subghz_decode.py --freq 433.92 --duration 0
""",
    )
    parser.add_argument("--freq",     type=float, default=DEFAULT_FREQ_MHZ, metavar="MHZ",
                        help=f"Receive frequency in MHz (default {DEFAULT_FREQ_MHZ})")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION, metavar="S",
                        help=f"Run duration in seconds, 0=forever (default {DEFAULT_DURATION})")
    parser.add_argument("--db",       default=DEFAULT_DB, metavar="FILE",
                        help=f"SQLite database file (default {DEFAULT_DB})")
    parser.add_argument("--ssa",      default=None, metavar="HOST",
                        help="SSA IP for RF characterization (optional)")
    parser.add_argument("--serial",   default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")

    args = parser.parse_args()
    freq_hz = args.freq * 1e6

    ssa = None
    if args.ssa:
        if not _SSA_AVAILABLE:
            print("Warning: rf-bench-drivers-siglent not installed, --ssa ignored")
        else:
            try:
                ssa = connect(args.ssa or 'ssa')
                print(f"SSA: {ssa.identify()}")
            except Exception as exc:
                print(f"Warning: cannot connect to SSA ({exc}), continuing without it")
                ssa = None

    conn = open_db(args.db)
    print(f"Database: {args.db}")

    try:
        print(f"Connecting to Flipper via inventory'} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")

        total = decode_loop(fz, conn, freq_hz, args.duration, ssa)
        print(f"\n  Total packets logged: {total}")

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
