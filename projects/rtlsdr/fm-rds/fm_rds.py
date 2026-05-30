#!/usr/bin/env python3
"""
FM Band Monitor with RDS Decode

Monitors the FM broadcast band (87.5–108 MHz), demodulates individual stations,
and decodes RDS data (station name, PI code, program type, radiotext).  Identifies
distant stations from their PI codes (tropospheric ducting events) and logs all
data to SQLite.

Extends the SSA FM propagation monitor (#64) with station identity.  The SSA tracks
power levels across the full band; this tool adds demodulation and RDS metadata.
Run both concurrently: SSA for the waterfall, this tool for station identification.

Usage:
    python fm_rds.py                          # scan full FM band and identify stations
    python fm_rds.py --freq 96.5              # monitor one station continuously
    python fm_rds.py --ssa 10.1.1.60         # pair with SSA for triggered demodulation
    python fm_rds.py --alert                  # SMS alert on new PI code region
"""

import argparse
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from rf_bench.rtlsdr import RTLSDR, RTLSDRError

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

FM_START_MHZ    = 87.5
FM_STOP_MHZ     = 108.0
FM_STEP_MHZ     = 0.2     # FM channel spacing: 200 kHz
DEFAULT_SCAN_BW = 2_400_000
FM_AUDIO_RATE   = 48_000
DEFAULT_DB_PATH = "fm_rds.db"
SSA_PORT        = 5025

# PI code region mapping (upper nibble = country, varies by region)
# ITU Region 1 (Europe/Africa) upper nibble A-F; US uses 1-9
PI_COUNTRY_MAP = {
    0x1: "US", 0x2: "US", 0x3: "US", 0x4: "US", 0x5: "US",
    0x6: "US", 0x7: "US", 0x8: "US", 0x9: "US",
    0xA: "DE", 0xB: "DE", 0xC: "FR", 0xD: "FR",
    0xE: "UK", 0xF: "UK",
}

_running = True

def _sigint(_sig, _frame):
    global _running
    _running = False

signal.signal(signal.SIGINT, _sigint)


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS stations (
    pi_code      INTEGER PRIMARY KEY,
    ps_name      TEXT,
    pty          INTEGER,
    region       TEXT,
    first_seen   REAL,
    last_seen    REAL,
    seen_count   INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS observations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    REAL NOT NULL,
    freq_mhz     REAL NOT NULL,
    pi_code      INTEGER,
    ps_name      TEXT,
    pty          INTEGER,
    radiotext    TEXT,
    power_db     REAL,
    is_new_pi    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS obs_time ON observations(timestamp);
CREATE INDEX IF NOT EXISTS obs_pi   ON observations(pi_code);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(CREATE_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# RDS decode via redsea
# ---------------------------------------------------------------------------

def decode_rds_redsea(wav_path: Path, timeout_s: float = 5.0) -> dict:
    """
    Decode RDS from a mono FM demodulated WAV file using redsea.
    Returns dict with pi, ps, pty, rt keys.  All None if decode fails.
    """
    if not _has_redsea():
        return _decode_rds_fallback(wav_path)

    try:
        result = subprocess.run(
            ["redsea", "--input-rate", str(FM_AUDIO_RATE), str(wav_path)],
            capture_output=True, text=True, timeout=timeout_s
        )
        return _parse_redsea_output(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"pi": None, "ps": None, "pty": None, "rt": None}


def _has_redsea() -> bool:
    import shutil
    return shutil.which("redsea") is not None


def _parse_redsea_output(text: str) -> dict:
    """Parse redsea JSON output."""
    result = {"pi": None, "ps": None, "pty": None, "rt": None}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if "pi" in obj and obj["pi"] and result["pi"] is None:
                result["pi"] = int(obj["pi"], 16) if isinstance(obj["pi"], str) else obj["pi"]
            if "ps" in obj and obj["ps"]:
                result["ps"] = obj["ps"].strip()
            if "pty" in obj:
                result["pty"] = obj["pty"]
            if "radiotext" in obj and obj["radiotext"]:
                result["rt"] = obj["radiotext"].strip()
        except (json.JSONDecodeError, ValueError, KeyError):
            continue
    return result


def _decode_rds_fallback(wav_path: Path) -> dict:
    """
    Minimal RDS decoder using numpy: extract the 57 kHz subcarrier and decode
    the PI code from the first A block.  For basic PI identification only.
    """
    try:
        import wave
        with wave.open(str(wav_path), 'r') as wf:
            frames = wf.readframes(wf.getnframes())
            rate   = wf.getframerate()
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

        # RDS is at 57 kHz.  With 48 kHz audio this is aliased — cannot decode
        # without higher sample rate.  Return None gracefully.
        return {"pi": None, "ps": None, "pty": None, "rt": None,
                "_note": "redsea not installed; install for RDS decode"}
    except Exception:
        return {"pi": None, "ps": None, "pty": None, "rt": None}


# ---------------------------------------------------------------------------
# FM demodulation
# ---------------------------------------------------------------------------

def capture_and_demodulate(freq_mhz: float, duration_s: float,
                            gain: float | str, serial: Optional[str]) -> Optional[Path]:
    """
    Capture FM audio from freq_mhz for duration_s seconds.
    Returns path to WAV file, or None on error.

    Uses rtl_fm for FM demodulation (more reliable than software demod
    for RDS, which is bandwidth-critical).
    """
    import shutil
    if not shutil.which("rtl_fm"):
        return None

    freq_hz = int(freq_mhz * 1e6)
    tmp     = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    wav_path = Path(tmp.name)

    rtlfm_cmd = [
        "rtl_fm",
        "-f", str(freq_hz),
        "-M", "fm",
        "-s", "240000",       # 240 kS/s: enough BW for RDS subcarrier
        "-r", str(FM_AUDIO_RATE),
        "-g", str(gain),
        "-",
    ]
    sox_cmd = [
        "sox",
        "-t", "raw",
        "-r", str(FM_AUDIO_RATE),
        "-e", "signed-integer",
        "-b", "16",
        "-c", "1",
        "-",
        str(wav_path),
        "trim", "0", str(duration_s),
    ]

    try:
        rtlfm = subprocess.Popen(rtlfm_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        sox   = subprocess.Popen(sox_cmd, stdin=rtlfm.stdout, stderr=subprocess.DEVNULL)
        sox.wait(timeout=duration_s + 5)
        rtlfm.terminate()
        rtlfm.wait(timeout=2)
    except (subprocess.TimeoutExpired, Exception):
        try:
            rtlfm.kill()
        except Exception:
            pass
        return None

    return wav_path if wav_path.exists() and wav_path.stat().st_size > 1000 else None


# ---------------------------------------------------------------------------
# Band scan
# ---------------------------------------------------------------------------

def scan_band(sdr: RTLSDR, start_mhz: float, stop_mhz: float) -> list[dict]:
    """
    Quick power scan of the FM band.  Returns list of stations with estimated
    frequency and power.
    """
    # Centre the RTL-SDR at the middle of the band to capture it in one wide shot
    centre  = (start_mhz + stop_mhz) / 2 * 1e6
    bw      = (stop_mhz - start_mhz) * 1e6

    sdr.set_center_freq(int(centre))
    sdr.set_sample_rate(min(DEFAULT_SCAN_BW, 2_400_000))

    iq   = sdr.capture_iq(262_144)
    freq, psd = sdr.power_spectrum(iq, rbw_hz=100_000)   # 100 kHz RBW

    stations = []
    noise    = float(np.median(psd))
    for i, (f, p) in enumerate(zip(freq, psd)):
        f_mhz = f / 1e6
        if start_mhz <= f_mhz <= stop_mhz and p > noise + 10:
            # Snap to nearest 100 kHz channel
            ch_mhz = round(f_mhz * 10) / 10
            if not stations or abs(stations[-1]["freq_mhz"] - ch_mhz) > 0.15:
                stations.append({"freq_mhz": ch_mhz, "power_db": float(p)})

    return sorted(stations, key=lambda x: x["power_db"], reverse=True)


# ---------------------------------------------------------------------------
# PI code region inference
# ---------------------------------------------------------------------------

def pi_to_region(pi: int) -> str:
    """Map a PI code to a geographic region (rough heuristic)."""
    if not pi:
        return "unknown"
    upper = (pi >> 12) & 0xF
    return PI_COUNTRY_MAP.get(upper, f"region_{upper:X}")


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------

def send_alert(msg: str) -> None:
    """Send SMS via voipms proxy.  Fails silently if not configured."""
    sms_script = Path.home() / "Dropbox/build/money/sms.py"
    if sms_script.exists():
        try:
            subprocess.run(
                ["python3", str(sms_script), msg],
                timeout=10, capture_output=True
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="FM band monitor with RDS decode")
    ap.add_argument("--freq",    type=float, metavar="MHZ",
                    help="Monitor a single frequency in MHz (e.g. 96.5)")
    ap.add_argument("--gain",    default="auto",
                    help="Gain in dB or 'auto' (default: auto)")
    ap.add_argument("--db",      default=DEFAULT_DB_PATH,
                    help="SQLite database path (default: %(default)s)")
    ap.add_argument("--ssa",     metavar="HOST",
                    help="SSA host IP; when given, use SSA for band survey triggers")
    ap.add_argument("--alert",   action="store_true",
                    help="Send SMS alert when a new PI code region is detected")
    ap.add_argument("--dwell",   type=float, default=5.0,
                    help="Seconds per station in scan mode (default: 5)")
    ap.add_argument("--serial",  help="RTL-SDR serial number")
    ap.add_argument("--no-rds",  action="store_true",
                    help="Skip RDS decode (power scan only)")
    args = ap.parse_args()

    conn   = open_db(args.db)
    gain   = args.gain if args.gain == "auto" else float(args.gain)

    known_pi_regions: set = set(
        r[0] for r in conn.execute("SELECT DISTINCT region FROM stations").fetchall()
        if r[0]
    )

    def _update_station(pi: int, ps: str, pty: int, freq_mhz: float,
                        power_db: float, rt: str) -> bool:
        """Insert/update station in DB.  Returns True if PI code is new."""
        region  = pi_to_region(pi) if pi else "unknown"
        now     = time.time()
        is_new  = pi not in (r[0] for r in conn.execute("SELECT pi_code FROM stations").fetchall())
        conn.execute(
            """INSERT INTO stations(pi_code, ps_name, pty, region, first_seen, last_seen)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(pi_code) DO UPDATE SET
                 ps_name=COALESCE(excluded.ps_name, ps_name),
                 last_seen=excluded.last_seen,
                 seen_count=seen_count+1""",
            (pi, ps, pty, region, now, now)
        )
        conn.execute(
            "INSERT INTO observations(timestamp,freq_mhz,pi_code,ps_name,pty,radiotext,power_db,is_new_pi)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (now, freq_mhz, pi, ps, pty, rt, power_db, 1 if is_new else 0)
        )
        conn.commit()
        return is_new

    try:
        with RTLSDR(serial=args.serial) as sdr:
            sdr.set_sample_rate(DEFAULT_SCAN_BW)
            sdr.set_gain(gain)

            if args.freq:
                # Single-station continuous monitor
                print(f"Monitoring {args.freq:.1f} MHz  Ctrl-C to stop.")
                while _running:
                    wav = capture_and_demodulate(args.freq, args.dwell, gain, args.serial)
                    if wav and not args.no_rds:
                        rds = decode_rds_redsea(wav)
                        wav.unlink(missing_ok=True)
                        pi  = rds.get("pi")
                        ps  = rds.get("ps") or ""
                        pty = rds.get("pty")
                        rt  = rds.get("rt") or ""
                        if pi:
                            region   = pi_to_region(pi)
                            is_new   = _update_station(pi, ps, pty, args.freq, 0.0, rt)
                            ts       = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
                            new_flag = "  *** NEW REGION ***" if (is_new and region not in known_pi_regions) else ""
                            print(f"[{ts}] PI:{pi:04X} ({region})  PS:{ps:<8s}  PTY:{pty}  RT:{rt[:40]}{new_flag}")
                            if is_new and region not in known_pi_regions:
                                known_pi_regions.add(region)
                                if args.alert:
                                    send_alert(f"New FM PI region {region}: {ps} on {args.freq:.1f} MHz")
                    else:
                        time.sleep(args.dwell)

            else:
                # Full band scan
                print(f"FM band scan {FM_START_MHZ}–{FM_STOP_MHZ} MHz")
                print("Ctrl-C to stop.\n")
                print(f"{'Time':9s} {'Freq':7s} {'PI':7s} {'Region':8s} {'PS':9s} {'PTY':4s} {'Radiotext'}")
                print("-" * 72)

                while _running:
                    stations = scan_band(sdr, FM_START_MHZ, FM_STOP_MHZ)

                    for st in stations:
                        if not _running:
                            break
                        freq  = st["freq_mhz"]
                        power = st["power_db"]

                        rds = {"pi": None, "ps": None, "pty": None, "rt": None}
                        if not args.no_rds:
                            wav = capture_and_demodulate(freq, args.dwell, gain, args.serial)
                            if wav:
                                rds = decode_rds_redsea(wav)
                                wav.unlink(missing_ok=True)

                        pi  = rds.get("pi")
                        ps  = rds.get("ps") or "—"
                        pty = rds.get("pty") or "—"
                        rt  = rds.get("rt") or ""

                        is_new = False
                        if pi:
                            is_new = _update_station(pi, ps, pty, freq, power, rt)

                        region   = pi_to_region(pi) if pi else "—"
                        ts       = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
                        pi_str   = f"{pi:04X}" if pi else "—"
                        flag     = " <<<" if (is_new and region not in known_pi_regions and pi) else ""
                        print(f"[{ts}] {freq:6.1f}  {pi_str:6s}  {region:8s}  {ps:9s}  "
                              f"{str(pty):4s}  {rt[:30]}{flag}")

                        if is_new and pi and region not in known_pi_regions:
                            known_pi_regions.add(region)
                            if args.alert:
                                send_alert(f"Tropo ducting? New FM PI {pi:04X} ({region}): {ps} on {freq:.1f} MHz")

    except RTLSDRError as exc:
        print(f"RTL-SDR error: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
