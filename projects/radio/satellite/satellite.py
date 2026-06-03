#!/usr/bin/env python3
"""
Satellite Pass Planner and Doppler Tracker

Predicts upcoming passes for amateur satellites using TLE data fetched from
Celestrak, and during a pass applies real-time Doppler correction to an
IC-9700 (or IC-7300/FT-891) via Hamlib rigctld.

Ground station location comes from gpsd (--gps) or explicit coordinates
(--lat / --lon / --alt).  TLE data is cached in ~/.cache/rf-bench/tle/ and
refreshed every 6 hours by default.

Usage:
    # List upcoming passes (GPS for location, built-in AO-91 transponder config)
    python satellite.py --sat AO-91 --gps

    # List passes with explicit coordinates
    python satellite.py --sat AO-91 --lat 39.7392 --lon -104.9903 --alt 1609

    # Track next pass, apply Doppler to IC-9700 (dry run — no radio commands)
    python satellite.py --sat AO-91 --gps --track --dry-run

    # Full operation: configure IC-9700 for satellite mode, track Doppler live
    python satellite.py --sat AO-91 --gps --track

    # Linear transponder (inverted passband) with explicit frequencies
    python satellite.py --sat FO-29 --gps --track \\
        --dl 435.850e6 --dl-mode USB --ul 145.950e6 --ul-mode LSB --invert

    # Lookup by NORAD number with custom frequencies
    python satellite.py --norad 43017 --gps --track \\
        --dl 145.960e6 --ul 435.250e6 --dl-mode FM --ul-mode FM

    # Show built-in transponder database
    python satellite.py --list-sats

All frequencies are in Hz.  Use scientific notation: 145.960e6 = 145.960 MHz.
"""

import argparse
import math
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import requests
from skyfield.api import EarthSatellite, load, wgs84

# ── optional drivers ──────────────────────────────────────────────────────────

try:
    from rf_bench.gpsd import GPSD, GPSDNoFixError
    _HAS_GPSD = True
except ImportError:
    _HAS_GPSD = False

try:
    from rf_bench.icom import IC7300, IC9700
    from rf_bench.yaesu import FT891
    _HAS_RADIO = True
except ImportError:
    _HAS_RADIO = False


# ── physics constant ──────────────────────────────────────────────────────────

_C_KM_S = 299_792.458  # speed of light, km/s


# ── TLE and frequency cache ──────────────────────────────────────────────────

_TLE_CACHE = Path.home() / ".cache" / "rf-bench" / "tle"
_TLE_MAX_AGE_H = 6.0
_FREQ_CACHE_FILE = _TLE_CACHE / "frequencies.json"
_FREQ_CACHE_MAX_AGE_H = 168.0  # 7 days (frequencies change less often than TLEs)

# TLE group URLs.  Celestrak's legacy /pub/TLE/ and SATCAT API were retired in
# 2022.  AMSAT's nasabare.txt is the authoritative current source for amateur
# satellites and is updated daily; it also includes ISS via ARISS.
_TLE_URLS = {
    "amateur":  "https://www.amsat.org/tle/current/nasabare.txt",
    "stations": "https://www.amsat.org/tle/current/nasabare.txt",
}

# Per-NORAD fallback: SatNOGS database API
# Returns JSON: [{"tle0": "NAME", "tle1": "1 ...", "tle2": "2 ..."}]
_SATNOGS_NORAD_URL = (
    "https://db.satnogs.org/api/tle/?format=json&norad_cat_id={norad}"
)

# SatNOGS transmitters API — returns frequency/mode data for satellites
# Returns JSON: [{"downlink_low": freq_hz, "mode": "FM", "alive": true, ...}]
_SATNOGS_TRANSMITTERS_URL = (
    "https://db.satnogs.org/api/transmitters/?format=json&satellite__norad_cat_id={norad}"
)

_REQUEST_HEADERS = {
    "User-Agent": (
        "rf-bench/1.0 (amateur satellite tracker; "
        "+https://github.com/jfrancis42/rf-bench)"
    )
}


# ── built-in transponder database ─────────────────────────────────────────────
#
# Frequencies per AMSAT-NA documentation.  Verify against current AMSAT news
# before use — satellite configurations can change.
#
# dl/ul are center frequencies in Hz.  invert=True for linear transponders
# (passband is inverted: lower uplink → higher downlink).
#
# CTCSS note: AO-91, AO-92, and SO-50 require CTCSS tones on the uplink.
# Hamlib can set these via \set_ctcss_tone but the radio must support FM CTCSS.
# These are NOT set automatically — configure on the IC-9700 manually.

TRANSPONDERS = {
    "AO-91": {
        "norad": 43017, "tle_group": "amateur",
        "dl": 145_960_000, "ul": 435_250_000,
        "dl_mode": "FM", "ul_mode": "FM", "invert": False,
        "note": "Fox-1B FM. UL: 67.0 Hz CTCSS required.",
    },
    "AO-92": {
        "norad": 43137, "tle_group": "amateur",
        "dl": 145_880_000, "ul": 435_350_000,
        "dl_mode": "FM", "ul_mode": "FM", "invert": False,
        "note": "Fox-1D FM.",
    },
    "SO-50": {
        "norad": 27607, "tle_group": "amateur",
        "dl": 436_795_000, "ul": 145_850_000,
        "dl_mode": "FM", "ul_mode": "FM", "invert": False,
        "note": "SaudiSat-1C FM. UL: arm with 74.4 Hz CTCSS (5 s), then 67.0 Hz.",
    },
    "ISS": {
        "norad": 25544, "tle_group": "stations",
        "dl": 145_800_000, "ul": 144_490_000,
        "dl_mode": "FM", "ul_mode": "FM", "invert": False,
        "note": "ISS crossband repeater. Active during special operations only.",
    },
    "FO-29": {
        "norad": 24278, "tle_group": "amateur",
        "dl": 435_850_000, "ul": 145_950_000,
        "dl_mode": "USB", "ul_mode": "LSB", "invert": True,
        "note": "FujiOSCAR-29 linear transponder (inverted). USB/CW.",
    },
    "AO-7": {
        "norad": 7530, "tle_group": "amateur",
        "dl": 145_975_000, "ul": 432_150_000,
        "dl_mode": "USB", "ul_mode": "USB", "invert": True,
        "note": "Mode B linear. Battery-less; active only in sunlight.",
    },
}


# ── TLE fetching and caching ──────────────────────────────────────────────────

def _tle_cache_path(key: str) -> Path:
    return _TLE_CACHE / f"{key}.txt"


def _fetch_tle_group(group: str, max_age_h: float = _TLE_MAX_AGE_H) -> str:
    """
    Return TLE text for a Celestrak group, using a local cache.
    Fetches fresh data if the cache is absent or older than max_age_h.
    """
    _TLE_CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = _tle_cache_path(group)
    url = _TLE_URLS.get(group)
    if url is None:
        raise ValueError(f"Unknown TLE group {group!r}. Known: {list(_TLE_URLS)}")

    # Check cache age
    if cache_path.exists():
        age_h = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_h < max_age_h:
            return cache_path.read_text()

    try:
        resp = requests.get(url, headers=_REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
        text = resp.text
        cache_path.write_text(text)
        return text
    except requests.RequestException as exc:
        if cache_path.exists():
            print(f"  TLE fetch failed ({exc}); using cached data.", file=sys.stderr)
            return cache_path.read_text()
        raise RuntimeError(
            f"Could not fetch TLE data from {url}: {exc}"
        ) from exc


def _fetch_tle_by_norad(norad: int, max_age_h: float = _TLE_MAX_AGE_H) -> str:
    """
    Fetch TLE for a specific NORAD catalog number via SatNOGS and return
    as a 3-line TLE string (name, line1, line2).
    """
    import json as _json

    _TLE_CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = _tle_cache_path(f"norad_{norad}")

    if cache_path.exists():
        age_h = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_h < max_age_h:
            return cache_path.read_text()

    url = _SATNOGS_NORAD_URL.format(norad=norad)
    try:
        resp = requests.get(url, headers=_REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
        data = _json.loads(resp.text)
        if not data:
            raise RuntimeError(f"No TLE data returned for NORAD {norad}")
        entry = data[0]
        # SatNOGS returns tle0 (name with leading "0 "), tle1, tle2
        name = entry.get("tle0", f"NORAD {norad}").lstrip("0 ").strip()
        text = f"{name}\n{entry['tle1']}\n{entry['tle2']}\n"
        cache_path.write_text(text)
        return text
    except (requests.RequestException, KeyError, IndexError) as exc:
        if cache_path.exists():
            return cache_path.read_text()
        raise RuntimeError(f"Could not fetch TLE for NORAD {norad}: {exc}") from exc


def _parse_tle_text(text: str, name_or_norad) -> EarthSatellite:
    """
    Search TLE text (3-line format) for a satellite by name substring or
    NORAD catalog number.  Returns an EarthSatellite object.
    """
    ts = load.timescale(builtin=True)
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # Group into (name, line1, line2) triples
    triples = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            # Two-line without name
            triples.append(("", lines[i], lines[i + 1]))
            i += 2
        elif not lines[i].startswith("1 ") and not lines[i].startswith("2 "):
            # Name line
            if i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
                triples.append((lines[i], lines[i + 1], lines[i + 2]))
                i += 3
            else:
                i += 1
        else:
            i += 1

    search = str(name_or_norad).strip().upper()

    for name, l1, l2 in triples:
        # Match by NORAD number (field 2 of line 1, chars 2-7)
        try:
            norad_in_tle = int(l1[2:7].strip())
        except ValueError:
            norad_in_tle = None

        if (search.isdigit() and norad_in_tle == int(search)) or \
           (search in name.upper()):
            return EarthSatellite(l1, l2, name, ts)

    raise LookupError(
        f"Satellite {name_or_norad!r} not found in TLE data. "
        f"Try --norad <catalog_number> or check Celestrak for the correct name."
    )


def _fetch_transmitters(norad: int) -> list[dict]:
    """
    Fetch transmitter data (frequencies, modes) from SatNOGS database for a
    given NORAD catalog number. Returns list of transmitter dicts.
    """
    import json as _json
    url = _SATNOGS_TRANSMITTERS_URL.format(norad=norad)
    try:
        resp = requests.get(url, headers=_REQUEST_HEADERS, timeout=10)
        resp.raise_for_status()
        data = _json.loads(resp.text)
        return data if data else []
    except (requests.RequestException, KeyError) as exc:
        return []


def _load_frequency_cache() -> dict:
    """
    Load cached frequency data from disk. Returns dict mapping NORAD -> transponder config.
    """
    import json as _json
    if not _FREQ_CACHE_FILE.exists():
        return {}

    try:
        age_h = (time.time() - _FREQ_CACHE_FILE.stat().st_mtime) / 3600
        if age_h > _FREQ_CACHE_MAX_AGE_H:
            return {}  # Cache too old

        data = _json.loads(_FREQ_CACHE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_frequency_cache(cache: dict) -> None:
    """Save frequency cache to disk."""
    import json as _json
    _TLE_CACHE.mkdir(parents=True, exist_ok=True)
    _FREQ_CACHE_FILE.write_text(_json.dumps(cache, indent=2))


def _get_cache_age_str(cache_file: Path) -> str:
    """Return human-readable cache age string."""
    if not cache_file.exists():
        return "not cached"
    age_h = (time.time() - cache_file.stat().st_mtime) / 3600
    if age_h < 1:
        return f"{int(age_h * 60)} minutes"
    elif age_h < 24:
        return f"{int(age_h)} hours"
    else:
        return f"{int(age_h / 24)} days"


def _build_extended_transponders(refresh: bool = False) -> dict:
    """
    Build extended TRANSPONDERS dict by merging built-in database with cached
    SatNOGS frequency data. If cache is missing or stale, optionally refresh it.

    Returns: dict mapping satellite names to transponder configs
    """
    import json as _json

    # Start with built-in database
    extended = dict(TRANSPONDERS)

    # Load frequency cache
    freq_cache = _load_frequency_cache()

    # If cache is empty and refresh=True, fetch from SatNOGS
    if not freq_cache and refresh:
        try:
            # Fetch TLE to get all NORAD numbers
            text = _fetch_tle_group("amateur", max_age_h=_TLE_MAX_AGE_H)
            lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

            norad_list = []
            i = 0
            while i < len(lines):
                if lines[i].startswith("1 "):
                    try:
                        norad = int(lines[i][2:7].strip())
                        # Find name from previous line if exists
                        name = ""
                        if i > 0 and not lines[i-1].startswith("1 ") and not lines[i-1].startswith("2 "):
                            name = lines[i-1]
                        norad_list.append((name, norad))
                    except ValueError:
                        pass
                i += 1

            # Fetch transmitter data for each (with rate limiting)
            print(f"Refreshing frequency cache for {len(norad_list)} satellites...", end="", flush=True)
            for idx, (name, norad) in enumerate(norad_list):
                transmitters = _fetch_transmitters(norad)
                if transmitters:
                    # Find best downlink/uplink
                    downlinks = [t for t in transmitters if t.get("downlink_low") and t.get("alive")]
                    uplinks = [t for t in transmitters if t.get("uplink_low") and t.get("alive")]

                    if downlinks:
                        dl = downlinks[0]
                        freq_cache[str(norad)] = {
                            "name": name if name else f"NORAD {norad}",
                            "dl": int(dl["downlink_low"]),
                            "ul": int(uplinks[0]["uplink_low"]) if uplinks else None,
                            "dl_mode": dl.get("mode", "FM").upper(),
                            "ul_mode": uplinks[0].get("mode", "FM").upper() if uplinks else None,
                        }

                if (idx + 1) % 10 == 0:
                    print(f"\rRefreshing frequency cache: {idx+1}/{len(norad_list)}  ", end="", flush=True)
                time.sleep(0.2)  # Rate limit

            print(" Done.")
            _save_frequency_cache(freq_cache)
        except Exception as e:
            print(f"\nWarning: Could not refresh frequency cache: {e}", file=sys.stderr)

    # Merge cached frequencies into extended database
    # Skip satellites already in built-in database
    built_in_norads = {cfg["norad"] for cfg in TRANSPONDERS.values()}

    for norad_str, cfg in freq_cache.items():
        norad = int(norad_str)
        if norad in built_in_norads:
            continue  # Don't override built-in entries

        # Generate short name (remove spaces, truncate)
        name = cfg.get("name", f"NORAD-{norad}")
        safe_name = name.upper().replace(" ", "-").replace("(", "").replace(")", "")[:15]

        # Add to extended database
        extended[safe_name] = {
            "norad": norad,
            "tle_group": "amateur",
            "dl": cfg["dl"],
            "ul": cfg.get("ul"),
            "dl_mode": cfg.get("dl_mode", "FM"),
            "ul_mode": cfg.get("ul_mode", "FM"),
            "invert": False,  # Conservative default
            "note": f"{name} (auto-imported from SatNOGS)",
            "_auto_imported": True,  # Flag for debugging
        }

    return extended


def load_satellite(name: Optional[str], norad: Optional[int],
                   tle_group: str = "amateur",
                   max_age_h: float = _TLE_MAX_AGE_H) -> EarthSatellite:
    """Load a satellite from Celestrak, using cache."""
    if norad is not None:
        # Fetch directly by NORAD number
        text = _fetch_tle_by_norad(norad, max_age_h)
        try:
            return _parse_tle_text(text, norad)
        except LookupError:
            # Fall through to group search
            pass

    if name is not None:
        # Check the built-in database for the TLE group to use
        db_entry = TRANSPONDERS.get(name.upper()) or TRANSPONDERS.get(name)
        group = db_entry["tle_group"] if db_entry else tle_group
        # Try the specific NORAD fetch first for accuracy
        if db_entry and "norad" in db_entry:
            try:
                text = _fetch_tle_by_norad(db_entry["norad"], max_age_h)
                return _parse_tle_text(text, db_entry["norad"])
            except Exception:
                pass
        # Fall back to group search
        text = _fetch_tle_group(group, max_age_h)
        return _parse_tle_text(text, name)

    raise ValueError("Specify --sat NAME or --norad NUMBER")


# ── ground station ────────────────────────────────────────────────────────────

def get_observer(lat: Optional[float], lon: Optional[float],
                 alt_m: float, gps: Optional[object]):
    """
    Return a skyfield observer (wgs84 latlon) and a display string.
    Uses GPS if provided and has a fix; falls back to lat/lon args.
    """
    if gps is not None and _HAS_GPSD:
        fix = gps.get_fix()
        if fix.has_fix:
            lat = fix.latitude
            lon = fix.longitude
            alt_m = fix.altitude_m or alt_m
            src = "GPS"
        else:
            src = "GPS (no fix — using --lat/--lon)"
    else:
        src = "--lat/--lon"

    if lat is None or lon is None:
        raise ValueError(
            "Ground station location required. Use --gps or --lat/--lon."
        )

    observer = wgs84.latlon(lat, lon, elevation_m=alt_m)
    return observer, lat, lon, alt_m, src


# ── orbital mechanics ─────────────────────────────────────────────────────────

def range_rate_km_s(sat: EarthSatellite, observer, t) -> float:
    """
    Radial range rate of satellite relative to observer at time t.
    Positive = moving away; negative = approaching.
    """
    topocentric = (sat - observer).at(t)
    pos = topocentric.position.km           # position vector, observer→sat
    vel = topocentric.velocity.km_per_s     # relative velocity vector
    rng = float(np.linalg.norm(pos))
    if rng < 1e-6:
        return 0.0
    return float(np.dot(pos, vel) / rng)


def doppler_rx_hz(f_nominal_hz: float, rr: float) -> float:
    """
    Frequency received on the downlink given range rate rr (km/s).
    Approaching (rr < 0) → higher frequency.
    """
    return f_nominal_hz * (1.0 - rr / _C_KM_S)


def doppler_tx_hz(f_nominal_hz: float, rr: float) -> float:
    """
    Uplink transmit frequency required for the satellite to hear us at
    f_nominal_hz, given range rate rr (km/s).
    """
    return f_nominal_hz * (1.0 + rr / _C_KM_S)


# ── pass prediction ───────────────────────────────────────────────────────────

def find_passes(sat: EarthSatellite, observer, ts,
                hours: float = 24.0, min_elev: float = 5.0,
                n_passes: int = 10) -> list:
    """
    Return a list of upcoming passes, each a dict with:
    aos, culmination, los (skyfield Time objects), max_elev_deg (float).
    """
    t0 = ts.now()
    t1 = ts.tt_jd(t0.tt + hours / 24.0)

    times, events = sat.find_events(observer, t0, t1,
                                    altitude_degrees=min_elev)

    passes = []
    current = {}
    for t, event in zip(times, events):
        if event == 0:   # AOS
            current = {"aos": t}
        elif event == 1: # culmination
            if current:
                alt, _, _ = (sat - observer).at(t).altaz()
                current["culmination"] = t
                current["max_elev_deg"] = float(alt.degrees)
        elif event == 2: # LOS
            if current and "aos" in current:
                current["los"] = t
                passes.append(current)
                if len(passes) >= n_passes:
                    break
            current = {}

    return passes


# ── display helpers ───────────────────────────────────────────────────────────

_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _compass(deg: float) -> str:
    return _COMPASS[round(deg / 22.5) % 16]


def _bar(frac: float, width: int = 20, full: str = "█", empty: str = "░") -> str:
    filled = max(0, min(width, round(frac * width)))
    return full * filled + empty * (width - filled)


def _utc_str(t) -> str:
    dt = t.utc_datetime()
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _hms(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _freq_mhz(hz: float) -> str:
    return f"{hz / 1e6:.6f} MHz"


def _doppler_str(delta_hz: float) -> str:
    if abs(delta_hz) >= 1000:
        return f"{delta_hz/1000:+.2f} kHz"
    return f"{delta_hz:+.0f} Hz"


# ── pass listing ──────────────────────────────────────────────────────────────

def list_passes(sat: EarthSatellite, observer, lat: float, lon: float,
                alt_m: float, hours: float, min_elev: float,
                n_passes: int, dl_hz: float, ul_hz: Optional[float]) -> None:
    ts = load.timescale(builtin=True)
    passes = find_passes(sat, observer, ts, hours=hours,
                         min_elev=min_elev, n_passes=n_passes)

    if not passes:
        print(f"No passes above {min_elev:.0f}° in the next {hours:.0f} hours.")
        return

    print(f"\n  Satellite : {sat.name}")
    print(f"  Location  : {lat:.5f}°, {lon:.5f}°  alt {alt_m:.0f} m")
    print(f"  Look-ahead: {hours:.0f} h  Min elev: {min_elev:.0f}°")
    if dl_hz:
        print(f"  Downlink  : {_freq_mhz(dl_hz)}")
    if ul_hz:
        print(f"  Uplink    : {_freq_mhz(ul_hz)}")
    print()
    print(f"  {'#':>2}  {'AOS (UTC)':>22}  {'LOS (UTC)':>22}  "
          f"{'Duration':>8}  {'Max El':>6}  {'Max Dop':>10}")
    print(f"  {'─'*2}  {'─'*22}  {'─'*22}  {'─'*8}  {'─'*6}  {'─'*10}")

    now_tt = ts.now().tt
    for i, p in enumerate(passes, 1):
        aos_str = _utc_str(p["aos"])
        los_str = _utc_str(p["los"])
        duration_s = (p["los"].tt - p["aos"].tt) * 86400
        max_el = p.get("max_elev_deg", 0.0)

        # Doppler at culmination
        t_peak = p["culmination"] if p.get("culmination") is not None else p["aos"]
        rr = range_rate_km_s(sat, observer, t_peak)
        dop_str = ""
        if dl_hz:
            delta = doppler_rx_hz(dl_hz, rr) - dl_hz
            dop_str = _doppler_str(delta)

        future = p["aos"].tt > now_tt
        marker = "→" if i == 1 and future else " "
        print(f"  {marker}{i:>2}  {aos_str}  {los_str}  "
              f"{_hms(duration_s):>8}  {max_el:>5.1f}°  {dop_str:>10}")

    print()


# ── live tracking display ─────────────────────────────────────────────────────

def render_tracking(sat_name: str, t, sat: EarthSatellite, observer,
                    dl_hz: float, ul_hz: Optional[float],
                    dl_mode: str, ul_mode: str, invert: bool,
                    pass_info: dict, radio_label: str,
                    dry_run: bool) -> None:

    topocentric = (sat - observer).at(t)
    alt, az, dist = topocentric.altaz()
    elev_deg = float(alt.degrees)
    az_deg = float(az.degrees)
    dist_km = float(dist.km)

    rr = range_rate_km_s(sat, observer, t)
    approaching = rr < 0

    f_rx = doppler_rx_hz(dl_hz, rr)
    f_tx = doppler_tx_hz(ul_hz, rr) if ul_hz else None

    delta_dl = f_rx - dl_hz
    delta_ul = (f_tx - ul_hz) if f_tx else None

    now_tt = t.tt
    aos_tt = pass_info["aos"].tt
    los_tt = pass_info["los"].tt
    pass_duration_s = (los_tt - aos_tt) * 86400
    elapsed_s = (now_tt - aos_tt) * 86400
    remaining_s = (los_tt - now_tt) * 86400
    pass_frac = max(0.0, min(1.0, elapsed_s / pass_duration_s)) if pass_duration_s > 0 else 0
    max_el = pass_info.get("max_elev_deg", 0.0)

    print("\033[2J\033[H", end="")  # clear screen

    W = 58
    print(f"  {'═'*W}")
    print(f"  TRACKING: {sat.name}")
    print(f"  AOS {_utc_str(pass_info['aos'])}   MAX EL {max_el:.1f}°")
    print(f"  LOS {_utc_str(pass_info['los'])}")
    print(f"  {'═'*W}")
    print()

    el_frac = max(0.0, min(1.0, elev_deg / 90.0))
    print(f"  Elevation  {_bar(el_frac, 22)}  {elev_deg:5.1f}°")
    print(f"  Azimuth    {az_deg:5.1f}°  ({_compass(az_deg)})")
    print(f"  Range      {dist_km:,.0f} km")
    rr_dir = "APPROACHING" if approaching else "RECEDING   "
    print(f"  Range rate {rr:+.3f} km/s  ({rr_dir})")
    print()

    print(f"  Doppler (DL)  {_doppler_str(delta_dl)}")
    if delta_ul is not None:
        print(f"  Doppler (UL)  {_doppler_str(delta_ul)}")
    print()

    print(f"  RX (downlink) {_freq_mhz(f_rx)}  {dl_mode}")
    if f_tx is not None:
        print(f"  TX (uplink)   {_freq_mhz(f_tx)}  {ul_mode}")
    if invert:
        print(f"  Transponder   INVERTED (LSB↔USB)")
    print()

    print(f"  Time to LOS  {_hms(remaining_s)}  {_bar(pass_frac, 20)}  {pass_frac*100:.0f}%")
    print()

    mode_str = "DRY RUN" if dry_run else "LIVE"
    print(f"  Radio  {radio_label}  [{mode_str}]")
    print(f"  {'─'*W}")
    print(f"  Ctrl-C to stop early (frequencies will be restored)")


# ── main tracking loop ────────────────────────────────────────────────────────

_running = True


def _sigint(*_):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigint)


def track_pass(sat: EarthSatellite, observer, pass_info: dict,
               dl_hz: float, ul_hz: Optional[float],
               dl_mode: str, ul_mode: str, invert: bool,
               radio, radio_label: str, dry_run: bool,
               update_interval: float = 1.0) -> None:
    """
    Wait for AOS, configure the radio, then Doppler-track the satellite
    until LOS or Ctrl-C.
    """
    ts = load.timescale(builtin=True)
    aos_tt = pass_info["aos"].tt
    los_tt = pass_info["los"].tt

    # Wait for AOS
    now = ts.now()
    wait_s = (aos_tt - now.tt) * 86400
    if wait_s > 0:
        print(f"\n  Waiting {_hms(wait_s)} for AOS at {_utc_str(pass_info['aos'])} …")
        deadline = time.monotonic() + wait_s
        while _running and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            # During wait, show a countdown and live satellite position
            t = ts.now()
            topocentric = (sat - observer).at(t)
            alt, az, dist = topocentric.altaz()
            rr = range_rate_km_s(sat, observer, t)
            print(
                f"\r  AOS in {_hms(remaining)}   "
                f"el={float(alt.degrees):+5.1f}°  "
                f"az={float(az.degrees):5.1f}°  "
                f"rr={rr:+.2f} km/s   ",
                end="", flush=True,
            )
            time.sleep(min(remaining, 5.0))
        print()
        if not _running:
            return

    # Configure radio
    if radio and not dry_run:
        print(f"  Configuring radio for satellite mode …")
        if hasattr(radio, "set_satellite_mode") and ul_hz:
            radio.set_satellite_mode(
                rx_freq_hz=dl_hz, rx_mode=dl_mode,
                tx_freq_hz=ul_hz, tx_mode=ul_mode,
            )
        else:
            radio.set_frequency(dl_hz)
            radio.set_mode(dl_mode)
            if ul_hz and hasattr(radio, "set_split"):
                radio.set_split(True)
                radio.set_tx_frequency(ul_hz)
                radio.set_tx_mode(ul_mode)

    # Tracking loop
    last_update = 0.0
    try:
        while _running:
            t = ts.now()
            if t.tt >= los_tt:
                break

            now_mono = time.monotonic()
            if now_mono - last_update >= update_interval:
                rr = range_rate_km_s(sat, observer, t)
                f_rx = doppler_rx_hz(dl_hz, rr)
                f_tx = doppler_tx_hz(ul_hz, rr) if ul_hz else None

                if radio and not dry_run:
                    if hasattr(radio, "update_doppler") and f_tx is not None:
                        radio.update_doppler(f_rx, f_tx)
                    else:
                        radio.set_frequency(f_rx)
                        if f_tx and hasattr(radio, "set_tx_frequency"):
                            radio.set_tx_frequency(f_tx)

                render_tracking(
                    sat.name, t, sat, observer,
                    dl_hz, ul_hz, dl_mode, ul_mode, invert,
                    pass_info, radio_label, dry_run,
                )
                last_update = now_mono

            time.sleep(0.1)

    finally:
        print("\033[2J\033[H", end="")
        # Restore nominal frequencies
        if radio and not dry_run:
            print("  Pass ended — restoring nominal frequencies …")
            if hasattr(radio, "clear_satellite_mode"):
                radio.clear_satellite_mode()
            else:
                radio.set_frequency(dl_hz)
                if hasattr(radio, "set_split"):
                    radio.set_split(False)

    if _running:
        print(f"\n  Pass complete.  LOS at {_utc_str(pass_info['los'])}")
    else:
        print(f"\n  Pass aborted by user.")


# ── radio factory ─────────────────────────────────────────────────────────────

def make_radio(radio_name: str, host: str, port: int):
    if not _HAS_RADIO:
        raise RuntimeError("rf-bench radio drivers not installed.")
    if radio_name == "ic9700":
        return IC9700(host, port)
    if radio_name == "ft891":
        return FT891(host, port)
    return IC7300(host, port)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Amateur satellite pass planner and Doppler tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage:")[1] if "Usage:" in __doc__ else "",
    )

    # Satellite identification
    sat_grp = ap.add_mutually_exclusive_group()
    sat_grp.add_argument("--sat", metavar="NAME",
                         help="Satellite name (e.g. AO-91, FO-29, ISS)")
    sat_grp.add_argument("--norad", type=int, metavar="CATNUM",
                         help="NORAD catalog number (e.g. 43017)")
    ap.add_argument("--list-sats", action="store_true",
                    help="Print built-in transponder database and exit")
    ap.add_argument("--list-all-tle", action="store_true",
                    help="Download and list all satellites from AMSAT TLE file (nasabare.txt)")
    ap.add_argument("--fetch-frequencies", action="store_true",
                    help="Fetch transmitter frequencies from SatNOGS for all satellites in TLE file")
    ap.add_argument("--generate-db", action="store_true",
                    help="Generate Python code for TRANSPONDERS dict (use with --fetch-frequencies)")

    # Ground station location
    loc_grp = ap.add_argument_group("location")
    loc_grp.add_argument("--gps", action="store_true",
                         help="Use gpsd for ground station location")
    loc_grp.add_argument("--gps-host", default="localhost")
    loc_grp.add_argument("--gps-port", type=int, default=2947)
    loc_grp.add_argument("--lat", type=float, metavar="DEG",
                         help="Ground station latitude in decimal degrees (+N)")
    loc_grp.add_argument("--lon", type=float, metavar="DEG",
                         help="Ground station longitude in decimal degrees (+E)")
    loc_grp.add_argument("--alt", type=float, default=0.0, metavar="M",
                         help="Ground station altitude in metres (default: 0)")

    # Pass prediction options
    pred_grp = ap.add_argument_group("pass prediction")
    pred_grp.add_argument("--passes", type=int, default=5,
                          help="Number of upcoming passes to list (default: 5)")
    pred_grp.add_argument("--hours", type=float, default=24.0,
                          help="Look-ahead window in hours (default: 24)")
    pred_grp.add_argument("--min-elev", type=float, default=5.0,
                          help="Minimum elevation in degrees (default: 5)")

    # Transponder frequencies
    freq_grp = ap.add_argument_group("transponder frequencies")
    freq_grp.add_argument("--dl", type=float, metavar="HZ",
                          help="Downlink (RX) center frequency in Hz")
    freq_grp.add_argument("--ul", type=float, metavar="HZ",
                          help="Uplink (TX) center frequency in Hz (omit for RX-only)")
    freq_grp.add_argument("--dl-mode", default="FM",
                          help="Downlink mode: FM, USB, LSB, CW (default: FM)")
    freq_grp.add_argument("--ul-mode", default="FM",
                          help="Uplink mode (default: FM)")
    freq_grp.add_argument("--invert", action="store_true",
                          help="Linear transponder: passband is inverted (uplink + downlink "
                               "Doppler corrections have opposite signs)")

    # Radio control
    radio_grp = ap.add_argument_group("radio control")
    radio_grp.add_argument("--track", action="store_true",
                           help="Wait for the next pass and apply live Doppler correction")
    radio_grp.add_argument("--pass-num", type=int, default=1,
                           help="Which upcoming pass to track (1 = next, default: 1)")
    radio_grp.add_argument("--radio", choices=["ic9700", "ic7300", "ft891"],
                           default="ic9700",
                           help="Radio model (default: ic9700)")
    radio_grp.add_argument("--rigctld-host", default="localhost")
    radio_grp.add_argument("--rigctld-port", type=int, default=4532)
    radio_grp.add_argument("--dry-run", action="store_true",
                           help="Compute and display Doppler but do not command the radio")
    radio_grp.add_argument("--interval", type=float, default=1.0,
                           help="Doppler update interval in seconds (default: 1)")

    # TLE options
    tle_grp = ap.add_argument_group("TLE data")
    tle_grp.add_argument("--tle-group", default="amateur",
                         choices=list(_TLE_URLS),
                         help="Celestrak TLE group for group searches (default: amateur)")
    tle_grp.add_argument("--tle-max-age", type=float, default=_TLE_MAX_AGE_H,
                         metavar="H",
                         help=f"Max TLE cache age in hours (default: {_TLE_MAX_AGE_H})")
    tle_grp.add_argument("--refresh-tle", action="store_true",
                         help="Force refresh TLE data from Celestrak")
    tle_grp.add_argument("--refresh-frequencies", action="store_true",
                         help="Force refresh frequency data from SatNOGS (rebuilds cache)")

    args = ap.parse_args()

    # ── Build extended transponders database ──────────────────────────────────
    # Load built-in + auto-imported SatNOGS frequencies
    global TRANSPONDERS
    TRANSPONDERS = _build_extended_transponders(refresh=args.refresh_frequencies)

    # ── list-sats mode ────────────────────────────────────────────────────────
    if args.list_sats:
        # Separate built-in from auto-imported
        built_in = {name: cfg for name, cfg in TRANSPONDERS.items() if not cfg.get("_auto_imported")}
        auto_imported = {name: cfg for name, cfg in TRANSPONDERS.items() if cfg.get("_auto_imported")}

        print(f"\n  Satellite transponder database ({len(TRANSPONDERS)} total):")
        print(f"\n  Built-in satellites ({len(built_in)}):")
        print(f"  {'Name':15}  {'NORAD':>6}  {'Downlink':>14}  {'Uplink':>14}  "
              f"{'DL':5}  {'UL':5}  {'Inv':3}")
        print(f"  {'─'*15}  {'─'*6}  {'─'*14}  {'─'*14}  {'─'*5}  {'─'*5}  {'─'*3}")
        for name, cfg in sorted(built_in.items()):
            ul_str = _freq_mhz(cfg["ul"]) if cfg.get("ul") else "—"
            print(f"  {name:15}  {cfg['norad']:>6}  "
                  f"{_freq_mhz(cfg['dl']):>14}  {ul_str:>14}  "
                  f"{cfg['dl_mode']:5}  {cfg.get('ul_mode',''):5}  "
                  f"{'yes' if cfg['invert'] else 'no ':3}")
            if not cfg['note'].startswith(name):  # Don't duplicate name in note
                print(f"                 {cfg['note']}")

        if auto_imported:
            print(f"\n  Auto-imported from SatNOGS ({len(auto_imported)}):")
            print(f"  {'Name':15}  {'NORAD':>6}  {'Downlink':>14}  {'Uplink':>14}  {'Mode':5}")
            print(f"  {'─'*15}  {'─'*6}  {'─'*14}  {'─'*14}  {'─'*5}")
            for name, cfg in sorted(auto_imported.items()):
                ul_str = _freq_mhz(cfg["ul"]) if cfg.get("ul") else "—"
                print(f"  {name:15}  {cfg['norad']:>6}  "
                      f"{_freq_mhz(cfg['dl']):>14}  {ul_str:>14}  {cfg['dl_mode']:5}")

            print(f"\n  Auto-imported satellites use SatNOGS data. Verify frequencies before use.")
            print(f"  Cache age: {_get_cache_age_str(_FREQ_CACHE_FILE)}")
            print(f"  Run with --refresh-frequencies to update from SatNOGS.")
        else:
            print(f"\n  No auto-imported satellites. Run with --refresh-frequencies to fetch from SatNOGS.")

        print()
        return

    # ── list-all-tle mode ─────────────────────────────────────────────────────
    if args.list_all_tle:
        print("\nFetching AMSAT TLE data (nasabare.txt)...", end="", flush=True)
        try:
            text = _fetch_tle_group("amateur", max_age_h=args.tle_max_age)
            print(" OK\n")

            # Parse TLE file into (name, norad, line1, line2) tuples
            lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
            satellites = []
            i = 0
            while i < len(lines):
                if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
                    # Two-line TLE without name
                    try:
                        norad = int(lines[i][2:7].strip())
                        satellites.append(("", norad, lines[i], lines[i + 1]))
                    except ValueError:
                        pass
                    i += 2
                elif not lines[i].startswith("1 ") and not lines[i].startswith("2 "):
                    # Name line
                    if i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
                        try:
                            norad = int(lines[i + 1][2:7].strip())
                            satellites.append((lines[i], norad, lines[i + 1], lines[i + 2]))
                        except ValueError:
                            pass
                        i += 3
                    else:
                        i += 1
                else:
                    i += 1

            # Sort by NORAD number
            satellites.sort(key=lambda x: x[1])

            # Display
            print(f"  Found {len(satellites)} satellites in AMSAT TLE file:\n")
            print(f"  {'NORAD':>8}  {'Name':<40}  {'In DB':<6}")
            print(f"  {'─'*8}  {'─'*40}  {'─'*6}")

            for name, norad, l1, l2 in satellites:
                # Check if this satellite is in the built-in database
                in_db = "yes" if any(cfg["norad"] == norad for cfg in TRANSPONDERS.values()) else ""
                display_name = name[:40] if name else f"NORAD {norad}"
                print(f"  {norad:>8}  {display_name:<40}  {in_db:<6}")

            print(f"\n  To track a satellite by NORAD number:")
            print(f"    python satellite.py --norad <NORAD> --dl <freq_hz> --gps")
            print(f"\n  Example (AO-73, NORAD 39444):")
            print(f"    python satellite.py --norad 39444 --dl 145.960e6 --ul 435.150e6 --gps")
            print()
        except Exception as e:
            print(f" FAILED\n  Error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # ── fetch-frequencies mode ────────────────────────────────────────────────
    if args.fetch_frequencies:
        print("\nFetching AMSAT TLE data (nasabare.txt)...", end="", flush=True)
        try:
            text = _fetch_tle_group("amateur", max_age_h=args.tle_max_age)
            print(" OK\n")

            # Parse TLE file
            lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
            satellites = []
            i = 0
            while i < len(lines):
                if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
                    try:
                        norad = int(lines[i][2:7].strip())
                        satellites.append(("", norad))
                    except ValueError:
                        pass
                    i += 2
                elif not lines[i].startswith("1 ") and not lines[i].startswith("2 "):
                    if i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
                        try:
                            norad = int(lines[i + 1][2:7].strip())
                            satellites.append((lines[i], norad))
                        except ValueError:
                            pass
                        i += 3
                    else:
                        i += 1
                else:
                    i += 1

            satellites.sort(key=lambda x: x[1])

            print(f"Found {len(satellites)} satellites. Fetching transmitter data from SatNOGS...\n")

            # Fetch transmitter data for each satellite
            results = []
            for idx, (name, norad) in enumerate(satellites, 1):
                print(f"\r  [{idx}/{len(satellites)}] {norad:>6} {name[:30]:<30}  ", end="", flush=True)
                transmitters = _fetch_transmitters(norad)
                if transmitters:
                    results.append((name, norad, transmitters))
                time.sleep(0.2)  # Rate limit: don't hammer SatNOGS API

            print("\n")

            # Display results
            if args.generate_db:
                # Generate Python code for TRANSPONDERS dict
                print("# Generated TRANSPONDERS entries (paste into satellite.py):\n")
                print("TRANSPONDERS = {")

                for name, norad, transmitters in results:
                    # Find best downlink and uplink
                    downlinks = [t for t in transmitters if t.get("downlink_low") and t.get("alive")]
                    uplinks = [t for t in transmitters if t.get("uplink_low") and t.get("alive")]

                    if not downlinks:
                        continue

                    # Use first alive downlink
                    dl = downlinks[0]
                    dl_freq = int(dl["downlink_low"])
                    dl_mode = dl.get("mode", "FM").upper()

                    # Find matching uplink (if any)
                    ul_freq = None
                    ul_mode = None
                    if uplinks:
                        ul = uplinks[0]
                        ul_freq = int(ul["uplink_low"])
                        ul_mode = ul.get("mode", "FM").upper()

                    # Generate entry
                    sat_name = name if name else f"NORAD-{norad}"
                    safe_name = sat_name.upper().replace(" ", "-").replace("(", "").replace(")", "")[:10]

                    print(f'    "{safe_name}": {{')
                    print(f'        "norad": {norad}, "tle_group": "amateur",')
                    print(f'        "dl": {dl_freq}, ', end="")
                    if ul_freq:
                        print(f'"ul": {ul_freq},')
                    else:
                        print()
                    print(f'        "dl_mode": "{dl_mode}", ', end="")
                    if ul_mode:
                        print(f'"ul_mode": "{ul_mode}", ', end="")
                    print('"invert": False,')
                    print(f'        "note": "{sat_name}",')
                    print('    },')

                print("}\n")
            else:
                # Display frequency table
                print(f"  {'NORAD':>8}  {'Name':<30}  {'Downlink (MHz)':<16}  {'Uplink (MHz)':<16}  {'Mode':<8}  {'Status':<8}")
                print(f"  {'─'*8}  {'─'*30}  {'─'*16}  {'─'*16}  {'─'*8}  {'─'*8}")

                for name, norad, transmitters in results:
                    # Find best downlink and uplink
                    downlinks = [t for t in transmitters if t.get("downlink_low")]
                    uplinks = [t for t in transmitters if t.get("uplink_low")]

                    if not downlinks:
                        continue

                    for dl in downlinks[:1]:  # Show first downlink only
                        dl_freq = dl.get("downlink_low", 0) / 1e6
                        ul_freq = uplinks[0].get("uplink_low", 0) / 1e6 if uplinks else 0
                        mode = dl.get("mode", "?").upper()
                        status = "alive" if dl.get("alive") else "dead"

                        ul_str = f"{ul_freq:.3f}" if ul_freq > 0 else "—"
                        display_name = (name[:30] if name else f"NORAD {norad}")

                        print(f"  {norad:>8}  {display_name:<30}  "
                              f"{dl_freq:>16.3f}  {ul_str:>16}  {mode:<8}  {status:<8}")

                print(f"\n  Run with --generate-db to output Python code for TRANSPONDERS dict.")

            # Save to cache (so next run of --list-sats will show these satellites)
            print(f"\nSaving frequency cache to {_FREQ_CACHE_FILE}...", end="", flush=True)
            freq_cache = {}
            for name, norad, transmitters in results:
                downlinks = [t for t in transmitters if t.get("downlink_low") and t.get("alive")]
                uplinks = [t for t in transmitters if t.get("uplink_low") and t.get("alive")]

                if downlinks:
                    dl = downlinks[0]
                    freq_cache[str(norad)] = {
                        "name": name if name else f"NORAD {norad}",
                        "dl": int(dl["downlink_low"]),
                        "ul": int(uplinks[0]["uplink_low"]) if uplinks else None,
                        "dl_mode": dl.get("mode", "FM").upper(),
                        "ul_mode": uplinks[0].get("mode", "FM").upper() if uplinks else None,
                    }

            _save_frequency_cache(freq_cache)
            print(f" Saved {len(freq_cache)} satellites.")
            print(f"\nRun './satellite.py --list-sats' to see all available satellites.")

        except Exception as e:
            print(f" FAILED\n  Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)
        return

    # ── require satellite identification ──────────────────────────────────────
    if args.sat is None and args.norad is None:
        ap.error("specify --sat NAME, --norad CATNUM, --list-sats, --list-all-tle, or --fetch-frequencies")

    # ── resolve transponder config ────────────────────────────────────────────
    db = None
    if args.sat:
        db = TRANSPONDERS.get(args.sat.upper()) or TRANSPONDERS.get(args.sat)

    dl_hz    = args.dl    or (db["dl"]      if db else None)
    ul_hz    = args.ul    or (db.get("ul")  if db else None)
    dl_mode  = args.dl_mode if args.dl else (db["dl_mode"]  if db else args.dl_mode)
    ul_mode  = args.ul_mode if args.ul else (db.get("ul_mode", args.ul_mode) if db else args.ul_mode)
    invert   = args.invert or (db.get("invert", False) if db else False)
    norad    = args.norad or (db["norad"] if db else None)
    tle_grp  = db["tle_group"] if db else args.tle_group

    if dl_hz is None:
        ap.error("downlink frequency required. Use --dl HZ or choose a satellite "
                 "from the built-in database (--list-sats).")

    # Force refresh
    if args.refresh_tle:
        for path in _TLE_CACHE.glob("*.txt"):
            path.unlink(missing_ok=True)

    # ── load TLE ──────────────────────────────────────────────────────────────
    name_or_id = args.sat or norad
    print(f"Loading TLE for {name_or_id} …", end="", flush=True)
    try:
        sat = load_satellite(
            args.sat, norad,
            tle_group=tle_grp,
            max_age_h=args.tle_max_age,
        )
        print(f" OK  ({sat.name})")
    except Exception as exc:
        print(f"\n  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # TLE age warning
    ts_local = load.timescale(builtin=True)
    t_now = ts_local.now()
    tle_age_d = float(t_now.tt - sat.model.jdsatepoch)
    if tle_age_d > 7:
        print(f"  Warning: TLE is {tle_age_d:.1f} days old. "
              f"Pass times may be inaccurate. Use --refresh-tle.")

    # ── ground station ────────────────────────────────────────────────────────
    gps = None
    if args.gps:
        if not _HAS_GPSD:
            print("Warning: rf-bench-drivers-gpsd not installed; --gps ignored.",
                  file=sys.stderr)
        else:
            gps = GPSD(host=args.gps_host, port=args.gps_port)
            print("Waiting for GPS fix …", end="", flush=True)
            try:
                gps.wait_for_fix(timeout=30)
                print(" OK")
            except GPSDNoFixError:
                print(" (no fix — use --lat/--lon as fallback)")

    try:
        observer, lat, lon, alt_m, loc_src = get_observer(
            args.lat, args.lon, args.alt, gps
        )
    except ValueError as exc:
        print(f"\n  {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Observer: {lat:.5f}°, {lon:.5f}°  alt {alt_m:.0f} m  [{loc_src}]")

    # ── find passes ───────────────────────────────────────────────────────────
    ts_obj = load.timescale(builtin=True)
    passes = find_passes(sat, observer, ts_obj,
                         hours=args.hours,
                         min_elev=args.min_elev,
                         n_passes=max(args.passes, args.pass_num))

    if not passes:
        print(f"\nNo passes above {args.min_elev:.0f}° in the next {args.hours:.0f} hours.")
        if gps:
            gps.close()
        return

    # ── list mode (default) ───────────────────────────────────────────────────
    list_passes(sat, observer, lat, lon, alt_m,
                args.hours, args.min_elev, args.passes,
                dl_hz, ul_hz)

    if not args.track:
        if gps:
            gps.close()
        return

    # ── track mode ────────────────────────────────────────────────────────────
    pass_idx = args.pass_num - 1
    if pass_idx >= len(passes):
        print(f"  Pass #{args.pass_num} not found in the next {args.hours:.0f} h.",
              file=sys.stderr)
        if gps:
            gps.close()
        sys.exit(1)

    target_pass = passes[pass_idx]

    # Connect to radio
    radio = None
    radio_label = "(no radio)"
    if not args.dry_run:
        print(f"Connecting to {args.radio} via rigctld "
              f"{args.rigctld_host}:{args.rigctld_port} …",
              end="", flush=True)
        try:
            radio = make_radio(args.radio,
                               args.rigctld_host, args.rigctld_port)
            radio_label = (f"{args.radio.upper()} @ "
                           f"{args.rigctld_host}:{args.rigctld_port}")
            print(" OK")
        except Exception as exc:
            print(f"\n  Failed: {exc}  (continuing in dry-run mode)",
                  file=sys.stderr)
            radio = None
            args.dry_run = True
            radio_label = "(radio unavailable)"
    else:
        radio_label = f"{args.radio.upper()} [dry run]"

    # During tracking, keep GPS fix updated if available
    try:
        track_pass(
            sat, observer, target_pass,
            dl_hz=dl_hz, ul_hz=ul_hz,
            dl_mode=dl_mode, ul_mode=ul_mode,
            invert=invert,
            radio=radio, radio_label=radio_label,
            dry_run=args.dry_run,
            update_interval=args.interval,
        )
    finally:
        if radio:
            try:
                radio.close()
            except Exception:
                pass
        if gps:
            gps.close()


if __name__ == "__main__":
    main()
