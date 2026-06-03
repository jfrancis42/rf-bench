#!/usr/bin/env -S python3 -u
"""
APRS Direct Receive

Receives APRS 1200-baud AFSK packets directly from 144.390 MHz, decodes
them with direwolf, and cross-references each callsign with the govt-data
/callsigns API and the aprs-server PostgreSQL database.

Produces three outputs:
  1. Live console: decoded packets with FCC callsign enrichment
  2. SQLite log: all heard packets with rssi_db and heard_locally flag
  3. Cross-reference report: compare heard-locally vs. APRS-IS (--compare)

Requirements:
  - direwolf installed (pacman -S direwolf)
  - RTL-SDR mode: rtl-sdr package + 144 MHz antenna
  - IC-9700 USB mode: IC-9700 via USB, hamlib/rigctld (pacman -S hamlib)
  - IC-9700 LAN mode: IC-9700 on LAN, hamlib/rigctld, wfview

Usage:
    python aprs.py
    python aprs.py --radio ic9700-usb
    python aprs.py --radio ic9700-lan --ic9700-host 192.168.1.10
    python aprs.py --radio ic9700-lan --ic9700-host 192.168.1.10 --wfview-existing
    python aprs.py --gain 40 --freq 144390
    python aprs.py --compare
    python aprs.py --no-enrich
"""

import argparse
import json
import os
import re
import shlex
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

from rf_bench.rtlsdr import RTLSDR, RTLSDRError

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_FREQ_KHZ      = 144_390
DEFAULT_SAMPLE_RATE   = 24_000    # rtl_fm audio output rate for direwolf stdin
DEFAULT_GAIN          = 40
DEFAULT_DB_PATH       = "aprs_local.db"
GOVTDATA_HOST         = "10.1.0.20"
GOVTDATA_PORT         = 8091
APRSDB_HOST           = "10.1.0.20"
APRSDB_NAME           = "aprs"
IC9700_SAMPLE_RATE    = 48_000
IC9700_USB_DEVICE     = "/dev/ttyUSB0"
DEFAULT_RIGCTLD_PORT  = 4532
PA_SINK_NAME          = "rfbench_aprs"
WFVIEW_STREAM_TIMEOUT = 15.0

_running = True

def _sigint(_sig, _frame):
    global _running
    _running = False

signal.signal(signal.SIGINT, _sigint)


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS callsign_info (
    callsign    TEXT PRIMARY KEY,
    name        TEXT,
    address     TEXT,
    license     TEXT,
    enriched_at REAL
);

CREATE TABLE IF NOT EXISTS packets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    callsign    TEXT NOT NULL,
    path        TEXT,
    packet_type TEXT,
    data        TEXT,
    rssi_db     REAL,
    raw         TEXT
);

CREATE INDEX IF NOT EXISTS pkt_time     ON packets(timestamp);
CREATE INDEX IF NOT EXISTS pkt_callsign ON packets(callsign);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(CREATE_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Callsign enrichment from govt-data
# ---------------------------------------------------------------------------

_enrich_cache: dict = {}
_enrich_lock  = threading.Lock()
ENRICH_TTL    = 3600


def enrich_callsign(callsign: str, conn: sqlite3.Connection) -> dict:
    """Look up an amateur callsign via govt-data /callsigns API."""
    base = callsign.split("-")[0].upper()
    now  = time.time()

    with _enrich_lock:
        if base in _enrich_cache:
            ts, data = _enrich_cache[base]
            if now - ts < ENRICH_TTL:
                return data

    row = conn.execute(
        "SELECT name, address, license, enriched_at FROM callsign_info WHERE callsign=?",
        (base,)
    ).fetchone()
    if row and row[3] and (now - row[3] < ENRICH_TTL):
        data = {"name": row[0], "address": row[1], "license": row[2]}
        with _enrich_lock:
            _enrich_cache[base] = (now, data)
        return data

    try:
        url = f"http://{GOVTDATA_HOST}:{GOVTDATA_PORT}/callsigns?callsign={base}"
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=2.0) as resp:
            payload = json.loads(resp.read())
        if isinstance(payload, list) and payload:
            r = payload[0]
        elif isinstance(payload, dict):
            r = payload
        else:
            raise ValueError("empty")
        data = {
            "name":    r.get("entity_name") or r.get("name"),
            "address": f"{r.get('po_box') or r.get('city')}, {r.get('state')}".strip(", "),
            "license": r.get("license_class") or r.get("operator_class"),
        }
    except Exception:
        data = {"name": None, "address": None, "license": None}

    with _enrich_lock:
        _enrich_cache[base] = (now, data)

    conn.execute(
        """INSERT INTO callsign_info(callsign, name, address, license, enriched_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(callsign) DO UPDATE SET
             name=excluded.name,
             address=excluded.address,
             license=excluded.license,
             enriched_at=excluded.enriched_at""",
        (base, data["name"], data["address"], data["license"], now)
    )
    conn.commit()
    return data


# ---------------------------------------------------------------------------
# Packet parser (direwolf output format)
# ---------------------------------------------------------------------------

_DECODED_RE = re.compile(
    r'(?:Decoded\[\d+\]\s+[\d:]+\s+|^\[\S+\]\s*)'
    r'(?P<from>[A-Z0-9-]+)>(?P<to>[A-Z0-9-]+)(?:,(?P<path>[^:]+))?:(?P<data>.*)',
    re.IGNORECASE
)


def parse_direwolf_line(line: str) -> dict | None:
    """Parse a single direwolf output line into a packet dict."""
    m = _DECODED_RE.match(line.strip())
    if not m:
        return None
    from_call = m.group("from").upper()
    to_addr   = m.group("to").upper()
    path      = m.group("path") or ""
    data      = m.group("data") or ""

    pkt_type = "unknown"
    if data.startswith("!") or data.startswith("="):
        pkt_type = "position"
    elif data.startswith(">"):
        pkt_type = "status"
    elif data.startswith(":"):
        pkt_type = "message"
    elif data.startswith("`") or data.startswith("'"):
        pkt_type = "mic-e"
    elif data.startswith("T#"):
        pkt_type = "telemetry"
    elif data.startswith("_"):
        pkt_type = "weather"

    return {
        "callsign": from_call,
        "to":       to_addr,
        "path":     path,
        "type":     pkt_type,
        "data":     data[:200],
        "raw":      line.strip(),
    }


# ---------------------------------------------------------------------------
# APRS-IS database comparison
# ---------------------------------------------------------------------------

def compare_aprs_is(conn: sqlite3.Connection, lookback_s: float = 3600.0) -> None:
    """
    Compare locally heard callsigns against the APRS-IS-sourced aprs-server DB.
    """
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 not installed; install it to enable APRS-IS comparison.")
        return

    cutoff = time.time() - lookback_s

    local_rows = conn.execute(
        "SELECT DISTINCT callsign FROM packets WHERE timestamp > ?",
        (cutoff,)
    ).fetchall()
    local_calls = {r[0].split("-")[0] for r in local_rows}

    try:
        pg = psycopg2.connect(host=APRSDB_HOST, dbname=APRSDB_NAME,
                              connect_timeout=5)
        cur = pg.cursor()
        cur.execute(
            "SELECT DISTINCT callsign FROM aprs_packets "
            "WHERE received_at > NOW() - INTERVAL %s",
            (f"{int(lookback_s)} seconds",)
        )
        is_calls = {r[0].split("-")[0] for r in cur.fetchall()}
        pg.close()
    except Exception as exc:
        print(f"Could not connect to aprs-server DB: {exc}")
        return

    gated      = sorted(local_calls & is_calls)
    local_only = sorted(local_calls - is_calls)
    is_only    = sorted(is_calls    - local_calls)

    print(f"\n=== APRS Coverage Comparison (last {int(lookback_s/60)} min) ===")
    print(f"Heard locally:     {len(local_calls)}")
    print(f"On APRS-IS:        {len(is_calls)}")
    print(f"\nGated (both):      {len(gated)}")
    if gated:
        print("  " + "  ".join(gated[:20]) + ("..." if len(gated) > 20 else ""))
    print(f"\nLocal only (un-gated): {len(local_only)}")
    for cs in local_only[:10]:
        print(f"  {cs}")
    if len(local_only) > 10:
        print(f"  ... ({len(local_only)-10} more)")
    print(f"\nAPRS-IS only (out of range): {len(is_only)}")
    print()


# ---------------------------------------------------------------------------
# IC-9700 helpers
# ---------------------------------------------------------------------------

def find_ic9700_usb_audio() -> str | None:
    """Scan arecord -L for an IC-9700 capture device name."""
    try:
        out = subprocess.run(["arecord", "-L"], capture_output=True, text=True).stdout
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if not line.startswith(' ') and i + 1 < len(lines):
                if re.search(r'ic.?9700', lines[i + 1], re.IGNORECASE):
                    return line.strip()
    except FileNotFoundError:
        pass
    return None


def start_rigctld(device_or_ip: str, port: int) -> subprocess.Popen:
    """Start rigctld for the IC-9700 and return the process."""
    from rf_bench.icom import IC9700
    cmd = shlex.split(IC9700.rigctld_cmd(device_or_ip, rigctld_port=port))
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def configure_ic9700(freq_hz: int, rigctld_port: int) -> None:
    """Connect to rigctld and set IC-9700 to FM on the given frequency."""
    from rf_bench.icom import IC9700
    with IC9700(port=rigctld_port) as rig:
        rig.set_frequency(freq_hz)
        rig.set_mode("fm")


def setup_pa_null_sink(name: str) -> int:
    """Load a PulseAudio null sink. Returns the module ID for later cleanup."""
    out = subprocess.run(
        ["pactl", "load-module", "module-null-sink",
         f"sink_name={name}",
         f"sink_properties=device.description={name}"],
        capture_output=True, text=True, check=True
    ).stdout.strip()
    return int(out)


def teardown_pa_null_sink(module_id: int) -> None:
    subprocess.run(["pactl", "unload-module", str(module_id)], capture_output=True)


def start_wfview(extra_args: list) -> subprocess.Popen:
    cmd = ["wfview"] + extra_args
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_wfview_sink_input(timeout_s: float = WFVIEW_STREAM_TIMEOUT) -> int | None:
    """
    Poll pactl until a wfview sink-input appears in PulseAudio.
    Returns the sink-input index or None if timed out.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        out = subprocess.run(
            ["pactl", "list", "sink-inputs"],
            capture_output=True, text=True
        ).stdout
        current_id = None
        for line in out.splitlines():
            m = re.match(r'Sink Input #(\d+)', line)
            if m:
                current_id = int(m.group(1))
            if current_id is not None and 'wfview' in line.lower():
                return current_id
        time.sleep(1.0)
    return None


def move_sink_input(sink_input_id: int, sink_name: str) -> None:
    subprocess.run(
        ["pactl", "move-sink-input", str(sink_input_id), sink_name],
        capture_output=True
    )


# ---------------------------------------------------------------------------
# Main receive loop
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="APRS direct-RF receive")
    ap.add_argument("--freq",      type=float, default=DEFAULT_FREQ_KHZ,
                    help="Receive frequency in kHz (default: %(default)s)")
    ap.add_argument("--gain",      type=float, default=DEFAULT_GAIN,
                    help="RTL-SDR gain in dB (default: %(default)s)")
    ap.add_argument("--db",        default=DEFAULT_DB_PATH,
                    help="SQLite log path (default: %(default)s)")
    ap.add_argument("--no-enrich", action="store_true",
                    help="Disable FCC callsign lookup")
    ap.add_argument("--compare",   action="store_true",
                    help="Print APRS-IS coverage comparison after receiving")
    ap.add_argument("--duration",  type=float, default=0,
                    help="Stop after N seconds (0 = run forever)")
    ap.add_argument("--serial",    help="RTL-SDR serial number")

    ap.add_argument("--radio", choices=["rtlsdr", "ic9700-usb", "ic9700-lan"],
                    default="rtlsdr",
                    help="Audio source: rtlsdr (default), ic9700-usb, ic9700-lan")
    ap.add_argument("--ic9700-device", default=IC9700_USB_DEVICE,
                    metavar="DEV",
                    help="IC-9700 serial port for USB CAT (default: %(default)s)")
    ap.add_argument("--ic9700-host", default=None,
                    metavar="IP",
                    help="IC-9700 IP address for LAN mode (required for ic9700-lan)")
    ap.add_argument("--ic9700-audio", default=None,
                    metavar="DEVICE",
                    help="Override ALSA/PA audio device name (default: auto-detect)")
    ap.add_argument("--rigctld-port", type=int, default=DEFAULT_RIGCTLD_PORT,
                    help="rigctld listen port (default: %(default)s)")
    ap.add_argument("--wfview-existing", action="store_true",
                    help="Connect to already-running wfview instead of starting one")
    ap.add_argument("--wfview-args", default="",
                    metavar="ARGS",
                    help="Extra arguments passed to wfview subprocess (quoted string)")
    args = ap.parse_args()

    if args.radio == "ic9700-lan" and not args.ic9700_host and not args.wfview_existing:
        ap.error("--ic9700-host is required for --radio ic9700-lan")

    conn = open_db(args.db)

    freq_hz = int(args.freq * 1000)

    rigctld_proc = None
    wfview_proc  = None
    pa_module_id = None
    rtlfm        = None
    dw           = None
    dw_conf_path = None

    try:
        dw_conf = tempfile.NamedTemporaryFile(
            mode="w", suffix=".conf", prefix="rfbench_dw_", delete=False
        )
        dw_conf_path = dw_conf.name

        if args.radio == "rtlsdr":
            print(f"APRS receive on {args.freq:.3f} kHz via RTL-SDR  gain={args.gain} dB")
            print("Decoding via rtl_fm | direwolf.  Ctrl-C to stop.")

            dw_conf.write(
                f"ADEVICE stdin null\n"
                f"CHANNEL 0\n"
                f"MYCALL N0CALL\n"
                f"MODEM 1200\n"
                f"AGWPORT 0\n"
                f"KISSPORT 0\n"
            )
            dw_conf.flush()

            serial_args = ["-d", args.serial] if args.serial else []
            rtl_cmd = [
                "rtl_fm",
                "-f", str(freq_hz),
                "-M", "fm",
                "-s", str(DEFAULT_SAMPLE_RATE),
                "-r", str(DEFAULT_SAMPLE_RATE),
                "-g", str(args.gain),
                *serial_args,
                "-",
            ]
            dw_cmd = [
                "direwolf",
                "-c", dw_conf_path,
                "-r", str(DEFAULT_SAMPLE_RATE),
                "-b", "16",
                "-n", "1",
                "-t", "0",
            ]

            try:
                rtlfm = subprocess.Popen(
                    rtl_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                dw = subprocess.Popen(
                    dw_cmd,
                    stdin=rtlfm.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except FileNotFoundError as exc:
                print(f"Error: {exc}. Install rtl-sdr and direwolf (pacman -S rtl-sdr direwolf).",
                      file=sys.stderr)
                sys.exit(1)

        else:
            # IC-9700 path (USB or LAN)
            device_or_ip = args.ic9700_host if args.radio == "ic9700-lan" else args.ic9700_device
            print(f"APRS receive on {args.freq:.3f} kHz via IC-9700 ({args.radio})")

            print(f"Starting rigctld ({device_or_ip})...")
            rigctld_proc = start_rigctld(device_or_ip, args.rigctld_port)
            time.sleep(1.5)

            print(f"Setting IC-9700 to FM {args.freq:.3f} kHz...")
            try:
                configure_ic9700(freq_hz, args.rigctld_port)
            except Exception as exc:
                print(f"Warning: CAT control failed ({exc}); ensure radio is on {args.freq:.3f} kHz FM",
                      file=sys.stderr)

            if args.radio == "ic9700-usb":
                audio_dev = args.ic9700_audio
                if not audio_dev:
                    audio_dev = find_ic9700_usb_audio()
                    if audio_dev:
                        print(f"Detected IC-9700 USB audio: {audio_dev}")
                    else:
                        audio_dev = "plughw:IC-9700,0"
                        print(f"IC-9700 USB audio not detected; using default: {audio_dev}")

            else:  # ic9700-lan
                print(f"Creating PulseAudio null sink '{PA_SINK_NAME}'...")
                pa_module_id = setup_pa_null_sink(PA_SINK_NAME)

                if args.wfview_existing:
                    print("Connecting to existing wfview instance...")
                else:
                    extra = shlex.split(args.wfview_args or "")
                    print(f"Starting wfview {' '.join(extra)}...")
                    wfview_proc = start_wfview(extra)

                print(f"Waiting for wfview audio stream (up to {WFVIEW_STREAM_TIMEOUT:.0f}s)...")
                sid = wait_for_wfview_sink_input()
                if sid is not None:
                    print(f"Moving wfview sink-input #{sid} to {PA_SINK_NAME}...")
                    move_sink_input(sid, PA_SINK_NAME)
                else:
                    print("Warning: wfview audio stream not detected; check wfview is connected to the radio",
                          file=sys.stderr)

                audio_dev = args.ic9700_audio or f"{PA_SINK_NAME}.monitor"

            print(f"Direwolf audio device: {audio_dev}")
            print("Decoding via direwolf.  Ctrl-C to stop.")

            dw_conf.write(
                f"ADEVICE {audio_dev} null\n"
                f"ARATE {IC9700_SAMPLE_RATE}\n"
                f"CHANNEL 0\n"
                f"MYCALL N0CALL\n"
                f"MODEM 1200\n"
                f"AGWPORT 0\n"
                f"KISSPORT 0\n"
            )
            dw_conf.flush()

            dw_cmd = ["direwolf", "-c", dw_conf_path, "-t", "0"]
            try:
                dw = subprocess.Popen(
                    dw_cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except FileNotFoundError as exc:
                print(f"Error: {exc}. Install direwolf (pacman -S direwolf).", file=sys.stderr)
                sys.exit(1)

        # -------------------------------------------------------------------
        # Decode loop
        # -------------------------------------------------------------------

        start_time = time.time()
        total_pkts = 0

        while _running:
            if args.duration > 0 and (time.time() - start_time) > args.duration:
                break
            if dw.poll() is not None:
                remaining = dw.stdout.read()
                if remaining:
                    print("direwolf output:", file=sys.stderr)
                    for l in remaining.splitlines()[-10:]:
                        print(f"  {l}", file=sys.stderr)
                print(f"direwolf exited (code {dw.returncode}).", file=sys.stderr)
                break

            line = dw.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue

            pkt = parse_direwolf_line(line)
            if not pkt:
                continue

            total_pkts += 1
            now = time.time()

            conn.execute(
                "INSERT INTO packets(timestamp,callsign,path,packet_type,data,rssi_db,raw)"
                " VALUES(?,?,?,?,?,?,?)",
                (now, pkt["callsign"], pkt["path"], pkt["type"], pkt["data"], None, pkt["raw"])
            )
            conn.commit()

            ts  = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%H:%M:%S")
            msg = f"[{ts}] {pkt['callsign']:10s} {pkt['type']:10s} {pkt['data'][:60]}"

            if not args.no_enrich:
                def _print_enriched(cs=pkt["callsign"], m=msg):
                    info = enrich_callsign(cs, conn)
                    name = info.get("name") or ""
                    if name:
                        print(f"{m}  ({name})")
                    else:
                        print(m)
                threading.Thread(target=_print_enriched, daemon=True).start()
            else:
                print(msg)

    finally:
        for proc in (rtlfm, dw, wfview_proc, rigctld_proc):
            if proc:
                proc.terminate()
        if pa_module_id is not None:
            teardown_pa_null_sink(pa_module_id)
        try:
            for proc in (rtlfm, dw, wfview_proc, rigctld_proc):
                if proc:
                    proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            for proc in (rtlfm, dw, wfview_proc, rigctld_proc):
                if proc:
                    proc.kill()
        if dw_conf_path:
            try:
                os.unlink(dw_conf_path)
            except OSError:
                pass

    print(f"\nDone. {total_pkts} packets decoded.")

    if args.compare:
        compare_aprs_is(conn)


if __name__ == "__main__":
    main()
