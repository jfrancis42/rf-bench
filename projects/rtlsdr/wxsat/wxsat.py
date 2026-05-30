#!/usr/bin/env python3
"""
Weather Satellite APT / LRPT Decoder

Receives NOAA APT and Meteor-M LRPT weather satellite transmissions via RTL-SDR,
decodes them to PNG images.  Pass predictions are computed from current TLE data;
captures can be scheduled automatically or triggered manually.

Satellites:
    NOAA 15  — 137.620 MHz  APT (analog FM)
    NOAA 18  — 137.9125 MHz APT (analog FM)
    NOAA 19  — 137.100 MHz  APT (analog FM)
    Meteor-M N2-4 — 137.100 MHz  LRPT (digital QPSK)

Hardware:
    RTL-SDR + LNA (bias tee recommended) + V-dipole antenna
    V-dipole: two ~54 cm elements at 120° spread, mounted horizontally

Usage:
    python wxsat.py passes                       # list upcoming passes
    python wxsat.py capture --sat NOAA19         # capture next pass for NOAA 19
    python wxsat.py decode wxsat_20260528.wav    # decode saved WAV offline
    python wxsat.py schedule                     # auto-schedule all passes > 20°
"""

import argparse
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from pyorbital.orbital import Orbital
    from pyorbital import astronomy
    HAS_PYORBITAL = True
except ImportError:
    HAS_PYORBITAL = False

from rf_bench.rtlsdr import RTLSDR, RTLSDRError

# ---------------------------------------------------------------------------
# Observer location — set to your coordinates
# ---------------------------------------------------------------------------

OBSERVER_LAT  =  39.7392   # Denver, CO — change to your location
OBSERVER_LON  = -104.9903
OBSERVER_ALT  = 1609       # metres above sea level

# ---------------------------------------------------------------------------
# Satellite definitions
# ---------------------------------------------------------------------------

SATELLITES = {
    "NOAA15": {
        "tle_name":  "NOAA 15",
        "freq_hz":   137_620_000,
        "mode":      "APT",
        "sample_rate": 2_400_000,
        "fm_rate":   48_000,
    },
    "NOAA18": {
        "tle_name":  "NOAA 18",
        "freq_hz":   137_912_500,
        "mode":      "APT",
        "sample_rate": 2_400_000,
        "fm_rate":   48_000,
    },
    "NOAA19": {
        "tle_name":  "NOAA 19",
        "freq_hz":   137_100_000,
        "mode":      "APT",
        "sample_rate": 2_400_000,
        "fm_rate":   48_000,
    },
    "METEOR": {
        "tle_name":  "METEOR-M 2 4",
        "freq_hz":   137_100_000,
        "mode":      "LRPT",
        "sample_rate": 2_400_000,
        "fm_rate":   None,
    },
}

MIN_ELEVATION = 20.0     # degrees — skip passes below this
PRE_CAPTURE   = 60       # seconds before AOS to start recording
TLE_CACHE     = Path("tle_cache.json")
TLE_TTL       = 86_400   # 24 h before refreshing TLE data

_running = True

def _sigint(_sig, _frame):
    global _running
    _running = False

signal.signal(signal.SIGINT, _sigint)


# ---------------------------------------------------------------------------
# TLE management
# ---------------------------------------------------------------------------

CELESTRAK_WEATHER = "https://celestrak.org/NOAA/elements/gp.php?GROUP=weather&FORMAT=tle"
CELESTRAK_AMATEUR = "https://celestrak.org/NOAA/elements/gp.php?GROUP=amateur&FORMAT=tle"

def _fetch_tle_text() -> str:
    """Fetch TLE data from CelesTrak for weather + amateur satellites."""
    from urllib.request import urlopen
    from urllib.error import URLError
    try:
        with urlopen(CELESTRAK_WEATHER, timeout=10) as r:
            return r.read().decode()
    except URLError as exc:
        raise RuntimeError(f"Cannot fetch TLE data: {exc}") from exc


def load_tle(sat_name: str) -> tuple[str, str]:
    """Return (tle_line1, tle_line2) for a satellite by name."""
    now = time.time()
    if TLE_CACHE.exists():
        try:
            cache = json.loads(TLE_CACHE.read_text())
            if now - cache.get("fetched_at", 0) < TLE_TTL:
                tle = cache["satellites"].get(sat_name.upper())
                if tle:
                    return tle[0], tle[1]
        except (json.JSONDecodeError, KeyError):
            pass

    print("Fetching TLE data from CelesTrak...")
    raw = _fetch_tle_text()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    satellites = {}
    for i in range(0, len(lines) - 2, 3):
        name = lines[i].upper().strip()
        l1, l2 = lines[i+1], lines[i+2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            satellites[name] = (l1, l2)

    TLE_CACHE.write_text(json.dumps(
        {"fetched_at": now, "satellites": satellites}, indent=2
    ))

    tle = satellites.get(sat_name.upper())
    if not tle:
        raise RuntimeError(f"Satellite '{sat_name}' not found in TLE data. "
                           f"Available: {sorted(satellites.keys())[:10]}")
    return tle


# ---------------------------------------------------------------------------
# Pass prediction
# ---------------------------------------------------------------------------

def upcoming_passes(sat_key: str, hours_ahead: float = 24.0) -> list[dict]:
    """Return list of upcoming passes with AOS, LOS, max elevation."""
    if not HAS_PYORBITAL:
        raise RuntimeError("pyorbital not installed: pip install pyorbital")

    sat = SATELLITES[sat_key.upper()]
    tle_name = sat["tle_name"]

    try:
        l1, l2 = load_tle(tle_name)
    except RuntimeError as exc:
        print(f"Warning: {exc}")
        return []

    orb = Orbital(tle_name, line1=l1, line2=l2)

    start = datetime.now(tz=timezone.utc)
    passes = []

    try:
        raw = orb.get_next_passes(start, hours_ahead, OBSERVER_LON, OBSERVER_LAT, OBSERVER_ALT)
        for aos, los, max_el in raw:
            if max_el >= MIN_ELEVATION:
                passes.append({
                    "satellite": sat_key,
                    "aos":       aos,
                    "los":       los,
                    "max_el":    round(max_el, 1),
                    "duration":  int((los - aos).total_seconds()),
                })
    except Exception as exc:
        print(f"Pass prediction error: {exc}")

    return passes


def print_passes(passes: list[dict]) -> None:
    if not passes:
        print("No passes above minimum elevation found.")
        return
    print(f"\n{'Satellite':10s} {'AOS (UTC)':22s} {'LOS (UTC)':22s} {'MaxEl':6s} {'Duration':8s}")
    print("-" * 75)
    for p in passes:
        print(f"{p['satellite']:10s} {str(p['aos'])[:19]:22s} {str(p['los'])[:19]:22s} "
              f"{p['max_el']:5.1f}° {p['duration']:5d}s")
    print()


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def capture_pass(sat_key: str, duration_s: int, output_path: Path,
                 gain: float = 40, serial: str | None = None) -> Path:
    """
    Capture a satellite pass using rtl_fm and save as WAV (APT) or raw IQ (LRPT).

    Returns the path to the saved file.
    """
    sat = SATELLITES[sat_key.upper()]

    if sat["mode"] == "APT":
        wav_path = output_path.with_suffix(".wav")
        print(f"Capturing {sat_key} APT for {duration_s}s → {wav_path}")

        cmd = [
            "rtl_fm",
            "-f", str(sat["freq_hz"]),
            "-M", "fm",
            "-s", str(sat["sample_rate"]),
            "-r", str(sat["fm_rate"]),
            "-g", str(gain),
            "-",
        ]
        sox_cmd = [
            "sox",
            "-t", "raw",
            "-r", str(sat["fm_rate"]),
            "-e", "signed-integer",
            "-b", "16",
            "-c", "1",
            "-",
            str(wav_path),
        ]
        try:
            rtlfm = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            sox   = subprocess.Popen(sox_cmd, stdin=rtlfm.stdout, stderr=subprocess.DEVNULL)
            time.sleep(duration_s)
        finally:
            rtlfm.terminate()
            sox.terminate()
            try:
                rtlfm.wait(timeout=3)
                sox.wait(timeout=3)
            except subprocess.TimeoutExpired:
                rtlfm.kill()
                sox.kill()
        return wav_path

    else:
        # LRPT — save raw IQ
        iq_path = output_path.with_suffix(".iq")
        print(f"Capturing {sat_key} LRPT for {duration_s}s → {iq_path}")
        cmd = [
            "rtl_sdr",
            "-f", str(sat["freq_hz"]),
            "-s", str(sat["sample_rate"]),
            "-g", str(gain),
            "-n", str(sat["sample_rate"] * duration_s),
            str(iq_path),
        ]
        try:
            proc = subprocess.run(cmd, timeout=duration_s + 10)
        except subprocess.TimeoutExpired:
            pass
        return iq_path


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------

def decode_apt(wav_path: Path, output_dir: Path) -> Path | None:
    """
    Decode an APT WAV file to PNG using noaa-apt.
    Returns the output PNG path, or None if noaa-apt is not installed.
    """
    if not shutil.which("noaa-apt"):
        print("noaa-apt not found; install from AUR or https://noaa-apt.mbernardi.com.ar/")
        print(f"WAV saved at: {wav_path}")
        return None

    png_path = output_dir / (wav_path.stem + ".png")
    cmd = ["noaa-apt", str(wav_path), "-o", str(png_path)]
    print(f"Decoding APT: {wav_path.name} → {png_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"noaa-apt error: {result.stderr[:200]}")
        return None
    print(f"Image saved: {png_path}")
    return png_path


def decode_lrpt(iq_path: Path, output_dir: Path) -> Path | None:
    """
    Decode a Meteor-M LRPT IQ file to PNG using SatDump.
    Returns output directory path, or None if SatDump is not installed.
    """
    if not shutil.which("satdump"):
        print("satdump not found; install from https://github.com/SatDump/SatDump")
        print(f"IQ saved at: {iq_path}")
        return None

    out_dir = output_dir / iq_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "satdump", "offline_processing",
        "meteor_m2-x_lrpt",
        "--input_format", "raw_s8",
        "--source_file", str(iq_path),
        "--samplerate", "2400000",
        str(out_dir),
    ]
    print(f"Decoding LRPT: {iq_path.name} → {out_dir}/")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"SatDump error: {result.stderr[:200]}")
        return None
    print(f"LRPT images saved in: {out_dir}/")
    return out_dir


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Weather satellite APT/LRPT decoder via RTL-SDR")
    sub = ap.add_subparsers(dest="cmd")

    # passes
    p_passes = sub.add_parser("passes", help="List upcoming satellite passes")
    p_passes.add_argument("--sat",   default="all",
                          help="Satellite key or 'all' (default: all)")
    p_passes.add_argument("--hours", type=float, default=24.0,
                          help="Look-ahead window in hours (default: 24)")

    # capture
    p_cap = sub.add_parser("capture", help="Capture next pass and decode")
    p_cap.add_argument("--sat",    required=True, help="NOAA15 / NOAA18 / NOAA19 / METEOR")
    p_cap.add_argument("--gain",   type=float, default=40, help="Gain in dB")
    p_cap.add_argument("--outdir", default=".", help="Output directory")
    p_cap.add_argument("--serial", help="RTL-SDR serial number")
    p_cap.add_argument("--no-decode", action="store_true",
                       help="Save recording without decoding")

    # decode
    p_dec = sub.add_parser("decode", help="Decode a saved WAV/IQ file")
    p_dec.add_argument("file", help="WAV (APT) or IQ (LRPT) file to decode")
    p_dec.add_argument("--outdir", default=".", help="Output directory")

    # schedule
    p_sch = sub.add_parser("schedule", help="Auto-schedule and capture all passes")
    p_sch.add_argument("--gain",   type=float, default=40, help="Gain in dB")
    p_sch.add_argument("--outdir", default=".", help="Output directory")
    p_sch.add_argument("--serial", help="RTL-SDR serial number")

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        sys.exit(0)

    if not HAS_PYORBITAL and args.cmd in ("passes", "capture", "schedule"):
        print("pyorbital not installed: pip install pyorbital", file=sys.stderr)
        if args.cmd != "decode":
            sys.exit(1)

    if args.cmd == "passes":
        sats = list(SATELLITES.keys()) if args.sat == "all" else [args.sat.upper()]
        all_passes = []
        for s in sats:
            all_passes.extend(upcoming_passes(s, hours_ahead=args.hours))
        all_passes.sort(key=lambda p: p["aos"])
        print_passes(all_passes)

    elif args.cmd == "capture":
        sat_key = args.sat.upper()
        if sat_key not in SATELLITES:
            print(f"Unknown satellite '{args.sat}'. Choose: {', '.join(SATELLITES)}")
            sys.exit(1)

        passes = upcoming_passes(sat_key)
        if not passes:
            print("No passes above minimum elevation found.")
            sys.exit(0)

        p = passes[0]
        wait = (p["aos"] - datetime.now(tz=timezone.utc)).total_seconds() - PRE_CAPTURE
        if wait > 0:
            print(f"Next {sat_key} pass: AOS {p['aos'].strftime('%H:%M:%S UTC')}  "
                  f"max {p['max_el']}°  duration {p['duration']}s")
            print(f"Waiting {int(wait)}s...")
            time.sleep(max(0, wait))

        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = outdir / f"wxsat_{sat_key}_{ts}"

        cap = capture_pass(sat_key, p["duration"] + PRE_CAPTURE,
                           out_path, gain=args.gain, serial=args.serial)

        if not args.no_decode:
            if SATELLITES[sat_key]["mode"] == "APT":
                decode_apt(cap, outdir)
            else:
                decode_lrpt(cap, outdir)

    elif args.cmd == "decode":
        f = Path(args.file)
        outdir = Path(args.outdir)
        if not f.exists():
            print(f"File not found: {f}", file=sys.stderr)
            sys.exit(1)
        if f.suffix.lower() == ".wav":
            decode_apt(f, outdir)
        elif f.suffix.lower() in (".iq", ".bin", ".raw"):
            decode_lrpt(f, outdir)
        else:
            print(f"Unknown file type: {f.suffix}. Expected .wav (APT) or .iq/.bin (LRPT)")
            sys.exit(1)

    elif args.cmd == "schedule":
        print("Auto-schedule mode. Capturing all passes. Ctrl-C to stop.")
        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)

        while _running:
            all_passes = []
            for s in SATELLITES:
                all_passes.extend(upcoming_passes(s, hours_ahead=6))
            all_passes.sort(key=lambda p: p["aos"])

            if not all_passes:
                print("No passes found in next 6 hours. Sleeping 30 min.")
                time.sleep(1800)
                continue

            p   = all_passes[0]
            now = datetime.now(tz=timezone.utc)
            wait = (p["aos"] - now).total_seconds() - PRE_CAPTURE

            print(f"Next: {p['satellite']} AOS {p['aos'].strftime('%H:%M:%S UTC')}  "
                  f"max {p['max_el']}°  ({int(wait)}s away)")

            if wait > 60:
                time.sleep(min(wait - 30, 300))
                continue

            if wait > 0:
                time.sleep(wait)

            ts       = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
            out_path = outdir / f"wxsat_{p['satellite']}_{ts}"
            sat      = p["satellite"].upper()

            cap = capture_pass(sat, p["duration"] + PRE_CAPTURE,
                               out_path, gain=args.gain, serial=args.serial)

            if SATELLITES[sat]["mode"] == "APT":
                decode_apt(cap, outdir)
            else:
                decode_lrpt(cap, outdir)

            # Brief pause before checking for next pass
            time.sleep(60)


if __name__ == "__main__":
    main()
