#!/usr/bin/env -S python3 -u
"""
HF Digital Mode Activity Monitor

Monitors standard HF digital mode frequencies (FT8, FT4, JS8, WSPR) for activity.
When energy is detected above a configurable threshold, records IQ to SigMF format
files for external decoding by WSJT-X, JTDX, or other software.

Cycles through configured frequencies, checks for activity with a short IQ dwell,
and if active captures a full --record-s second block.  FT8 uses 15-second periods;
set --record-s 15 to capture a complete period.

SigMF output: a .sigmf-meta JSON metadata file and .sigmf-data binary IQ file
(raw complex64, little-endian) for each recording.

Digital mode frequencies monitored (select with --freqs or --all):
  FT8: 160m–10m  (1.840–28.074 MHz)
  FT4: 40m, 20m  (7.0475, 14.080 MHz)
  JS8: 40m, 20m  (7.078, 14.078 MHz)
  WSPR: 40m, 20m (7.0386, 14.0956 MHz)

Usage:
    python digital_monitor.py --host kiwisdr.local
    python digital_monitor.py --host 192.168.1.100 --all --rec-dir recordings/
    python digital_monitor.py --host 192.168.1.100 --freqs FT8_40m,FT8_20m,FT8_15m
    python digital_monitor.py --host 192.168.1.100 --squelch 8 --record-s 15
"""

import argparse
import json
import os
import signal
import sqlite3
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from rf_bench.kiwisdr import KiwiSDR, KiwiSDRError, KiwiSDRBusyError, SAMPLE_RATE

# ---------------------------------------------------------------------------
# Digital mode frequency table
# ---------------------------------------------------------------------------

DIGITAL_FREQS: dict[str, int] = {
    "FT8_160m":   1_840_000,
    "FT8_80m":    3_573_000,
    "FT8_60m":    5_357_000,
    "FT8_40m":    7_074_000,
    "FT8_30m":   10_136_000,
    "FT8_20m":   14_074_000,
    "FT8_17m":   18_100_000,
    "FT8_15m":   21_074_000,
    "FT8_12m":   24_915_000,
    "FT8_10m":   28_074_000,
    "FT4_40m":    7_047_500,
    "FT4_20m":   14_080_000,
    "JS8_40m":    7_078_000,
    "JS8_20m":   14_078_000,
    "WSPR_40m":   7_038_600,
    "WSPR_20m":  14_095_600,
}

DEFAULT_FREQS   = "FT8_40m,FT8_20m,FT8_15m,FT8_10m"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_HOST      = "kiwisdr.local"
DEFAULT_PORT      = 8073
DEFAULT_SQUELCH   = 10.0   # dB above noise
DEFAULT_RECORD_S  = 15     # seconds to record (FT8 period = 15 s)
DEFAULT_DWELL     = 3_000  # IQ samples for activity check (~250 ms)
DEFAULT_REC_DIR   = "recordings"
DEFAULT_DB        = "digital_monitor.db"
DEFAULT_PASSBAND  = 5_000  # ±5 kHz — FT8 signals span ~2.5 kHz within the band

# ANSI
_BOLD  = "\033[1m"
_RED   = "\033[31m"
_YELLOW= "\033[33m"
_GREEN = "\033[32m"
_CYAN  = "\033[36m"
_DIM   = "\033[2m"
_RESET = "\033[0m"
_CLEAR = "\033[H\033[J"

_running = True


def _sigint(_sig, _frame):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigint)

# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc      TEXT    NOT NULL,
    ts_unix     REAL    NOT NULL,
    freq_hz     INTEGER NOT NULL,
    label       TEXT,
    snr_db      REAL,
    recorded    INTEGER DEFAULT 0,
    sigmf_path  TEXT
);

CREATE INDEX IF NOT EXISTS activity_freq ON activity(freq_hz);
CREATE INDEX IF NOT EXISTS activity_time ON activity(ts_unix);
CREATE INDEX IF NOT EXISTS activity_label ON activity(label);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(CREATE_SQL)
    conn.commit()
    return conn


def log_activity(conn: sqlite3.Connection,
                 freq_hz: int, label: str,
                 snr_db: float,
                 recorded: bool = False,
                 sigmf_path: str = "") -> int:
    now = time.time()
    ts  = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute(
        "INSERT INTO activity(ts_utc, ts_unix, freq_hz, label, snr_db, recorded, sigmf_path) "
        "VALUES(?,?,?,?,?,?,?)",
        (ts, now, freq_hz, label, snr_db,
         1 if recorded else 0, sigmf_path)
    )
    conn.commit()
    return cur.lastrowid

# ---------------------------------------------------------------------------
# SigMF writer
# ---------------------------------------------------------------------------

def sigmf_basename(label: str, freq_hz: int) -> str:
    """Generate a SigMF file basename: e.g. FT8_20m_14074000_20260603T142301Z"""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{label}_{freq_hz}_{ts}"


def write_sigmf(rec_dir: str, label: str, freq_hz: int,
                iq: np.ndarray) -> tuple[str, str]:
    """
    Write IQ data to a SigMF file pair.

    Creates:
        <rec_dir>/<label>_<freq>_<ts>.sigmf-meta   JSON metadata
        <rec_dir>/<label>_<freq>_<ts>.sigmf-data   raw complex64 little-endian

    Returns (meta_path, data_path).
    """
    Path(rec_dir).mkdir(parents=True, exist_ok=True)

    base    = sigmf_basename(label, freq_hz)
    ts_utc  = datetime.now(tz=timezone.utc).isoformat()

    data_path = os.path.join(rec_dir, base + ".sigmf-data")
    meta_path = os.path.join(rec_dir, base + ".sigmf-meta")

    # Write binary IQ: complex64 (two float32) little-endian
    iq_c64 = iq.astype(np.complex64)
    with open(data_path, "wb") as fh:
        fh.write(iq_c64.tobytes())

    # SigMF metadata (core namespace)
    meta = {
        "global": {
            "core:version":          "1.0.0",
            "core:datatype":         "cf32_le",
            "core:sample_rate":      SAMPLE_RATE,
            "core:hw":               "KiwiSDR",
            "core:description":      f"HF digital monitor recording: {label}",
            "core:author":           "rf-bench digital-monitor",
        },
        "captures": [
            {
                "core:sample_start":      0,
                "core:frequency":         freq_hz,
                "core:datetime":          ts_utc,
            }
        ],
        "annotations": []
    }

    with open(meta_path, "w") as fh:
        json.dump(meta, fh, indent=2)

    return meta_path, data_path

# ---------------------------------------------------------------------------
# Activity detection
# ---------------------------------------------------------------------------

def check_activity(iq: np.ndarray) -> tuple[float, float]:
    """
    Return (snr_db, power_dbfs) for a short IQ block.

    S/N proxy: peak PSD bin vs. median PSD across the passband.
    """
    if len(iq) == 0:
        return 0.0, -99.0

    power_lin  = float(np.mean(np.abs(iq) ** 2))
    power_dbfs = 10.0 * np.log10(power_lin + 1e-30)

    nperseg = min(len(iq), 512)
    window  = np.hanning(nperseg).astype(np.float32)
    spec    = np.abs(np.fft.fft(iq[:nperseg] * window)) ** 2
    spec_db = 10.0 * np.log10(spec + 1e-30)

    peak_db  = float(np.max(spec_db))
    noise_db = float(np.median(spec_db))
    snr_db   = peak_db - noise_db

    return snr_db, power_dbfs

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

class ActivityRecord:
    """Holds display state for one monitored frequency."""
    __slots__ = ("label", "freq_hz", "snr_db", "power_dbfs",
                 "last_active", "recordings", "recording_path", "ts")

    def __init__(self, label: str, freq_hz: int):
        self.label         = label
        self.freq_hz       = freq_hz
        self.snr_db        = None
        self.power_dbfs    = None
        self.last_active   = None
        self.recordings    = 0
        self.recording_path = ""
        self.ts            = None


def render_display(records: list[ActivityRecord],
                   cycle_count: int, current_label: str,
                   total_recordings: int) -> None:
    lines = [_CLEAR]
    lines.append(f"{_BOLD}HF Digital Mode Activity Monitor{_RESET}  "
                 f"(cycles: {cycle_count}  recordings: {total_recordings}  Ctrl-C to stop)")
    lines.append(f"Current: {_CYAN}{current_label}{_RESET}")
    lines.append("")
    hdr = (f"{'Mode/Band':<14}  {'Freq (kHz)':>12}  {'S/N (dB)':>9}  "
           f"{'Activity':>10}  {'Recs':>5}  {'Last recording':<30}")
    lines.append(_BOLD + hdr + _RESET)
    lines.append("-" * 85)

    now = time.time()
    for rec in records:
        snr_str    = f"{rec.snr_db:+7.1f}" if rec.snr_db is not None else "  -----"
        age        = int(now - rec.last_active) if rec.last_active else 9999
        active_str = f"{age}s ago" if rec.last_active else "not seen"
        colour     = _GREEN if (rec.snr_db or 0) >= 20 else (
                     _YELLOW if (rec.snr_db or 0) >= 10 else _RED)
        rec_str    = os.path.basename(rec.recording_path) if rec.recording_path else ""

        lines.append(
            f"{rec.label:<14}  "
            f"{rec.freq_hz/1000.0:>12.3f}  "
            f"{colour}{snr_str}{_RESET}  "
            f"{active_str:>10}  "
            f"{rec.recordings:>5}  "
            f"{_DIM}{rec_str:<30}{_RESET}"
        )

    print("\n".join(lines), end="", flush=True)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_freqs(freqs_arg: str, all_freqs: bool) -> dict[str, int]:
    """Return {label: freq_hz} based on --freqs / --all args."""
    if all_freqs:
        return dict(DIGITAL_FREQS)

    result = {}
    for key in freqs_arg.split(","):
        key = key.strip()
        if key in DIGITAL_FREQS:
            result[key] = DIGITAL_FREQS[key]
        else:
            # Accept comma-separated Hz values as fallback
            try:
                hz = int(key)
                result[f"{hz/1000.0:.1f}kHz"] = hz
            except ValueError:
                print(f"WARNING: unknown mode key {key!r} (valid: {', '.join(DIGITAL_FREQS)})",
                      file=sys.stderr)
    return result


def main():
    ap = argparse.ArgumentParser(
        description="HF digital mode activity monitor and IQ recorder via KiwiSDR"
    )
    ap.add_argument("--host",      default=DEFAULT_HOST,
                    help="KiwiSDR hostname or IP (default: %(default)s)")
    ap.add_argument("--port",      type=int, default=DEFAULT_PORT,
                    help="KiwiSDR port (default: %(default)s)")
    ap.add_argument("--password",  default="",
                    help="KiwiSDR password (default: empty)")
    ap.add_argument("--freqs",     default=DEFAULT_FREQS,
                    help=f"Comma-separated mode keys to monitor (default: {DEFAULT_FREQS})")
    ap.add_argument("--all",       action="store_true",
                    help="Monitor all defined frequencies (overrides --freqs)")
    ap.add_argument("--squelch",   type=float, default=DEFAULT_SQUELCH,
                    help="dB above noise to trigger recording (default: %(default)s)")
    ap.add_argument("--record-s",  type=float, default=DEFAULT_RECORD_S,
                    help="Seconds to record when active (default: %(default)s)")
    ap.add_argument("--rec-dir",   default=DEFAULT_REC_DIR, metavar="DIR",
                    help="Directory for SigMF recordings (default: %(default)s)")
    ap.add_argument("--log",       default=DEFAULT_DB, metavar="FILE",
                    help="SQLite log path (default: %(default)s)")
    ap.add_argument("--dwell",     type=int, default=DEFAULT_DWELL,
                    help="IQ samples for activity check (default: %(default)s = ~250 ms)")
    args = ap.parse_args()

    freq_map = parse_freqs(args.freqs, args.all)
    if not freq_map:
        print("No frequencies to monitor.", file=sys.stderr)
        sys.exit(1)

    conn              = open_db(args.log)
    total_recordings  = 0
    cycle_count       = 0

    # Build display records ordered by frequency
    records_by_label: dict[str, ActivityRecord] = {}
    ordered_records:  list[ActivityRecord]      = []
    for label, hz in sorted(freq_map.items(), key=lambda kv: kv[1]):
        r = ActivityRecord(label, hz)
        records_by_label[label] = r
        ordered_records.append(r)

    record_samples = int(args.record_s * SAMPLE_RATE)

    print(f"Digital monitor | {len(freq_map)} frequencies | "
          f"squelch={args.squelch} dB | record={args.record_s}s")
    print(f"Frequencies: {', '.join(sorted(freq_map.keys()))}")
    print(f"Recordings → {args.rec_dir}/")
    print(f"Log: {args.log}")
    print("Press Ctrl-C to stop.\n")

    try:
        kiwi = KiwiSDR(host=args.host, port=args.port, password=args.password,
                       passband_hz=DEFAULT_PASSBAND)
    except KiwiSDRBusyError as exc:
        print(f"KiwiSDR busy: {exc}", file=sys.stderr)
        sys.exit(1)
    except KiwiSDRError as exc:
        print(f"KiwiSDR connection failed: {exc}", file=sys.stderr)
        sys.exit(1)

    freq_items = list(freq_map.items())   # [(label, hz), ...]

    try:
        while _running:
            cycle_count += 1

            for label, freq_hz in freq_items:
                if not _running:
                    break

                rec = records_by_label[label]
                render_display(ordered_records, cycle_count, label, total_recordings)

                # Tune and settle
                try:
                    kiwi.set_center_freq(freq_hz)
                    time.sleep(0.05)

                    # Activity check dwell
                    dwell_iq = kiwi.capture_iq(args.dwell)
                except KiwiSDRError as exc:
                    print(f"\nKiwiSDR error on {label}: {exc}", file=sys.stderr)
                    continue

                snr_db, power_dbfs = check_activity(dwell_iq)

                rec.snr_db    = snr_db
                rec.power_dbfs = power_dbfs
                rec.ts        = time.time()

                if snr_db >= args.squelch:
                    # Active — record a full block
                    rec.last_active = time.time()

                    try:
                        record_iq = kiwi.capture_iq(record_samples)
                    except KiwiSDRError as exc:
                        print(f"\nCapture error on {label}: {exc}", file=sys.stderr)
                        log_activity(conn, freq_hz, label, snr_db,
                                     recorded=False)
                        continue

                    meta_path, data_path = write_sigmf(
                        args.rec_dir, label, freq_hz, record_iq
                    )

                    rec.recordings     += 1
                    rec.recording_path  = data_path
                    total_recordings   += 1

                    log_activity(conn, freq_hz, label, snr_db,
                                 recorded=True, sigmf_path=data_path)

                    render_display(ordered_records, cycle_count, label, total_recordings)
                    print(f"\n  RECORDED {label} @ {freq_hz/1000.0:.3f} kHz  "
                          f"S/N={snr_db:+.1f} dB  → {os.path.basename(data_path)}")
                else:
                    log_activity(conn, freq_hz, label, snr_db,
                                 recorded=False)

    except KiwiSDRError as exc:
        print(f"\nKiwiSDR error: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        pass
    finally:
        kiwi.close()
        conn.close()
        print(f"\nDone. {cycle_count} cycles, {total_recordings} recordings → {args.rec_dir}/")


if __name__ == "__main__":
    main()
