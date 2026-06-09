#!/usr/bin/env python3
"""
Bubba Detector — RTL-SDR Multi-Band Handheld Radio Activity Scanner / Traditional Scanner

Two operating modes:

  log mode (default)
      Fast group-sweep across all channels (~1.1 s/cycle).  Detects signal
      energy above squelch, logs to SQLite, rolling terminal display.  No audio.

  scan mode  (--mode scan)
      Traditional sequential scanner.  Hops through each channel, stops when
      squelch opens, demodulates audio (NFM or AM) for real-time playback,
      records each transmission as a timestamped MP3, and runs WebRTC VAD on
      every recording to flag transmissions containing human voice — all in
      real time with no separate post-processing step.

Signal strength: uncalibrated dBFS.  ~/.rtlsdr_vhf_cal.json (from rx-crosscheck)
is loaded automatically for approximate dBm.

Usage:
    python bubba_detector.py                            # log mode, all bands
    python bubba_detector.py --mode scan                # full scanner
    python bubba_detector.py --mode scan --no-audio     # silent recording
    python bubba_detector.py --airband                  # aviation VHF AM only
    python bubba_detector.py --ham-vhf --ham-uhf        # 2m + 70cm amateur FM
    python bubba_detector.py --ham-220 --ham-900        # 1.25m + 33cm amateur FM
    python bubba_detector.py --vhf-ssb                  # 6m/2m/70cm USB calling (band openings)
    python bubba_detector.py --list-channels

Output:
    bubba_<ts>.db                  — SQLite (both modes)
    recordings/<ts>_<ch>.mp3      — per-transmission MP3 (scan mode)
"""

import argparse
import dataclasses
import json
import os
import queue
import signal
import sqlite3
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from rf_bench.rtlsdr import RTLSDR

# ── optional scanner-mode dependencies ────────────────────────────────────────

try:
    import sounddevice as _sd
    _SOUNDDEVICE_OK = True
except ImportError:
    _SOUNDDEVICE_OK = False

try:
    import lameenc as _lameenc
    _LAMEENC_OK = True
except ImportError:
    _LAMEENC_OK = False

try:
    from scipy.signal import butter as _butter, sosfilt as _sosfilt, sosfilt_zi as _sosfilt_zi
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False

try:
    import webrtcvad as _webrtcvad
    _VAD_OK = True
except ImportError:
    _VAD_OK = False


# ── audio / scanner constants ─────────────────────────────────────────────────

SCANNER_SDR_RATE  = 2_400_000
AUDIO_RATE        = 48_000
DECIMATE          = SCANNER_SDR_RATE // AUDIO_RATE   # = 50
IQ_BLOCK          = 32_768      # IQ samples per block (~13.6 ms)
AUDIO_BLOCK       = IQ_BLOCK // DECIMATE             # ~655 audio samples
MAX_RECORD_S      = 120
DEFAULT_BITRATE   = 32
DEFAULT_RESUME    = 2.0
DEFAULT_SKIP      = 0.15
DEFAULT_MAX_DWELL = 10.0
AUDIO_QUEUE_MAX   = 200

VAD_RATE          = 16_000      # webrtcvad preferred sample rate
VAD_FRAME_MS      = 30          # VAD frame length in ms
VAD_FRAME_SAMPLES = VAD_RATE * VAD_FRAME_MS // 1000   # 480 samples at 16 kHz
VAD_AGGRESSIVENESS = 2          # 0 (permissive) – 3 (aggressive)


# ── channel database ──────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class Channel:
    name:           str
    freq_hz:        int
    band:           str
    bw_hz:          int   = 12_500
    modulation:     str   = "NFM"   # "NFM", "AM", "USB", or "LSB"
    notes:          str   = ""
    priority_bonus: float = 0.0     # analyzer priority boost (dB-equiv); set on custom channels


def _ch(name, freq_mhz, band, bw=12_500, mod="NFM", notes="") -> Channel:
    return Channel(name=name, freq_hz=round(freq_mhz * 1e6), band=band,
                   bw_hz=bw, modulation=mod, notes=notes)

def _frs(ch, freq_mhz, gmrs_ch=None, bw=12_500) -> Channel:
    name = f"FRS CH {ch} / GMRS CH {gmrs_ch}" if gmrs_ch else f"FRS CH {ch}"
    return Channel(name=name, freq_hz=round(freq_mhz * 1e6), band="FRS/GMRS", bw_hz=bw)

def _gmrs(ch, freq_mhz, rpt=False) -> Channel:
    return Channel(name=f"GMRS RPT{ch}" if rpt else f"GMRS CH {ch}",
                   freq_hz=round(freq_mhz * 1e6), band="FRS/GMRS", bw_hz=20_000,
                   notes="repeater output" if rpt else "simplex")

def _murs(ch, freq_mhz, bw=11_250) -> Channel:
    return Channel(name=f"MURS CH {ch}", freq_hz=round(freq_mhz * 1e6),
                   band="MURS", bw_hz=bw)

def _marine(ch, freq_mhz, notes="") -> Channel:
    return Channel(name=f"Marine CH {ch}", freq_hz=round(freq_mhz * 1e6),
                   band="Marine", bw_hz=25_000, notes=notes)

def _noaa(ch, freq_mhz) -> Channel:
    return Channel(name=f"NOAA WX {ch}", freq_hz=round(freq_mhz * 1e6),
                   band="NOAA", bw_hz=25_000, notes="weather broadcast")

def _biz(name, freq_mhz, band, bw=11_250) -> Channel:
    return Channel(name=name, freq_hz=round(freq_mhz * 1e6), band=band, bw_hz=bw)

def _air(name, freq_mhz, notes="") -> Channel:
    return Channel(name=name, freq_hz=round(freq_mhz * 1e6), band="Aviation AM",
                   bw_hz=25_000, modulation="AM", notes=notes)

def _ham(name, freq_mhz, band, bw=16_000, notes="") -> Channel:
    return Channel(name=name, freq_hz=round(freq_mhz * 1e6), band=band, bw_hz=bw, notes=notes)

def _ssb(name, freq_mhz, band, bw=6_000, notes="") -> Channel:
    return Channel(name=name, freq_hz=round(freq_mhz * 1e6), band=band,
                   bw_hz=bw, modulation="USB", notes=notes)


ALL_CHANNELS: list[Channel] = [

    # ── FRS / GMRS ────────────────────────────────────────────────────────────
    _frs(1, 462.5625, gmrs_ch=1), _frs(2, 462.5875, gmrs_ch=2),
    _frs(3, 462.6125, gmrs_ch=3), _frs(4, 462.6375, gmrs_ch=4),
    _frs(5, 462.6625, gmrs_ch=5), _frs(6, 462.6875, gmrs_ch=6),
    _frs(7, 462.7125, gmrs_ch=7),
    _frs(8,  467.5625), _frs(9,  467.5875), _frs(10, 467.6125),
    _frs(11, 467.6375), _frs(12, 467.6625), _frs(13, 467.6875), _frs(14, 467.7125),
    _frs(15, 462.5500, gmrs_ch=15, bw=20_000), _frs(16, 462.5750, gmrs_ch=16, bw=20_000),
    _frs(17, 462.6000, gmrs_ch=17, bw=20_000), _frs(18, 462.6250, gmrs_ch=18, bw=20_000),
    _frs(19, 462.6500, gmrs_ch=19, bw=20_000), _frs(20, 462.6750, gmrs_ch=20, bw=20_000),
    _frs(21, 462.7000, gmrs_ch=21, bw=20_000), _frs(22, 462.7250, gmrs_ch=22, bw=20_000),
    _gmrs(15, 467.5500, rpt=True), _gmrs(16, 467.5750, rpt=True),
    _gmrs(17, 467.6000, rpt=True), _gmrs(18, 467.6250, rpt=True),
    _gmrs(19, 467.6500, rpt=True), _gmrs(20, 467.6750, rpt=True),
    _gmrs(21, 467.7000, rpt=True), _gmrs(22, 467.7250, rpt=True),

    # ── MURS ─────────────────────────────────────────────────────────────────
    _murs(1, 151.820), _murs(2, 151.880), _murs(3, 151.940),
    _murs(4, 154.570, bw=20_000), _murs(5, 154.600, bw=20_000),

    # ── Business VHF itinerant ────────────────────────────────────────────────
    _biz("Biz VHF 151.505", 151.505, "Business VHF"),
    _biz("Biz VHF 151.625", 151.625, "Business VHF"),
    _biz("Biz VHF 151.755", 151.755, "Business VHF"),
    _biz("Biz VHF 151.895", 151.895, "Business VHF"),
    _biz("Biz VHF 152.015", 152.015, "Business VHF"),
    _biz("Biz VHF 152.865", 152.865, "Business VHF"),
    _biz("Biz VHF 154.490", 154.490, "Business VHF"),
    _biz("Biz VHF 154.515", 154.515, "Business VHF"),
    _biz("Biz VHF 154.540", 154.540, "Business VHF"),
    _biz("Biz VHF 154.570", 154.570, "Business VHF"),

    # ── Marine VHF ───────────────────────────────────────────────────────────
    _marine("01A", 156.050),
    _marine("06",  156.300, "intership safety"),
    _marine("09",  156.450, "boater calling"),
    _marine("16",  156.800, "DISTRESS / HAILING — always monitored"),
    _marine("17",  156.850, "state control"),
    _marine("68",  156.425, "non-commercial"),
    _marine("69",  156.475),
    _marine("71",  156.575),
    _marine("72",  156.625, "non-commercial"),
    _marine("78A", 156.925),
    _marine("79A", 156.975),
    _marine("80A", 157.025),
    _marine("22A", 157.100, "USCG liaison"),
    _marine("24",  157.200),
    _marine("25",  157.250),
    _marine("26",  157.300),
    _marine("27",  157.350),
    _marine("28",  157.400),

    # ── NOAA Weather ─────────────────────────────────────────────────────────
    _noaa(1, 162.400), _noaa(2, 162.425), _noaa(3, 162.450), _noaa(4, 162.475),
    _noaa(5, 162.500), _noaa(6, 162.525), _noaa(7, 162.550),

    # ── Business UHF itinerant ────────────────────────────────────────────────
    _biz("Biz UHF 451.800",  451.800,  "Business UHF", bw=20_000),
    _biz("Biz UHF 456.800",  456.800,  "Business UHF", bw=20_000),
    _biz("Biz UHF 462.9375", 462.9375, "Business UHF", bw=12_500),
    _biz("Biz UHF 467.9375", 467.9375, "Business UHF", bw=12_500),

    # ── Aviation VHF AM  (118–136 MHz) ───────────────────────────────────────
    # These channels use AM, not FM.  All require --airband to be included.
    _air("Guard 121.500",    121.500, "Emergency / Guard — all aircraft monitor"),
    _air("Guard 121.600",    121.600, "Ground control (common)"),
    _air("Guard 121.700",    121.700, "Ground control"),
    _air("UNICOM 122.700",   122.700, "UNICOM (uncontrolled airports)"),
    _air("UNICOM 122.750",   122.750, "UNICOM"),
    _air("UNICOM 122.800",   122.800, "UNICOM (most common)"),
    _air("UNICOM 122.850",   122.850, "UNICOM"),
    _air("CTAF 122.900",     122.900, "CTAF / MULTICOM"),
    _air("CTAF 123.000",     123.000, "CTAF"),
    _air("SAR 123.025",      123.025, "Search and rescue primary"),
    _air("Helo 123.050",     123.050, "Helicopter operations"),
    _air("SAR 123.100",      123.100, "Search and rescue secondary"),
    _air("A-A 123.450",      123.450, "Air-to-air (general aviation)"),
    _air("FSS 122.200",      122.200, "Flight service stations"),
    _air("FSS 126.700",      126.700, "Flight service stations"),
    _air("Center 127.500",   127.500, "ARTCC en-route center (common)"),
    _air("ARINC 128.820",    128.820, "ARINC common"),
    # 243.000 MHz military UHF guard is rarely audible from civilian locations
    # and has no nearby channels to share a scan group with.  Add a dedicated
    # ScanGroup("Mil Guard", 243_000_000, "airband") to SCAN_GROUPS if needed.

    # ── Ham 2m FM  (144–148 MHz) ──────────────────────────────────────────────
    # Common national simplex.  Local repeater outputs vary — add yours below.
    # APRS (144.390 MHz) is intentionally excluded: it is always active and
    # carries digital data, not voice — use projects/rtlsdr/aprs/ for APRS.
    _ham("2m Simplex 146.400",   146.400, "Ham 2m"),
    _ham("2m Simplex 146.460",   146.460, "Ham 2m"),
    _ham("2m Simplex 146.490",   146.490, "Ham 2m"),
    _ham("2m Calling 146.520",   146.520, "Ham 2m", notes="national FM simplex calling"),
    _ham("2m Simplex 146.550",   146.550, "Ham 2m"),
    _ham("2m Simplex 146.580",   146.580, "Ham 2m"),
    _ham("2m Simplex 147.000",   147.000, "Ham 2m"),
    _ham("2m Simplex 147.510",   147.510, "Ham 2m"),
    _ham("2m Simplex 147.540",   147.540, "Ham 2m"),
    _ham("2m Simplex 147.555",   147.555, "Ham 2m"),

    # ── Ham 70cm FM  (420–450 MHz) ────────────────────────────────────────────
    _ham("70cm Calling 446.000", 446.000, "Ham 70cm", notes="national FM simplex calling"),
    _ham("70cm Simplex 446.025", 446.025, "Ham 70cm"),
    _ham("70cm Simplex 446.050", 446.050, "Ham 70cm"),
    _ham("70cm Simplex 446.100", 446.100, "Ham 70cm"),
    _ham("70cm Simplex 446.125", 446.125, "Ham 70cm"),
    _ham("70cm Simplex 446.200", 446.200, "Ham 70cm"),
    _ham("70cm Simplex 446.500", 446.500, "Ham 70cm"),
    _ham("70cm Simplex 445.925", 445.925, "Ham 70cm"),

    # ── Ham 1.25m FM  (222–225 MHz) ──────────────────────────────────────────
    _ham("1.25m Calling 223.500",   223.500, "Ham 1.25m", notes="national FM simplex calling"),
    _ham("1.25m Simplex 223.400",   223.400, "Ham 1.25m"),
    _ham("1.25m Simplex 223.440",   223.440, "Ham 1.25m"),
    _ham("1.25m Simplex 223.460",   223.460, "Ham 1.25m"),
    _ham("1.25m Simplex 223.480",   223.480, "Ham 1.25m"),
    _ham("1.25m Simplex 223.520",   223.520, "Ham 1.25m"),
    _ham("1.25m Simplex 223.540",   223.540, "Ham 1.25m"),

    # ── Ham 33cm FM  (902–928 MHz) ────────────────────────────────────────────
    _ham("33cm Calling 927.500",    927.500, "Ham 33cm", notes="national FM simplex calling"),
    _ham("33cm Simplex 927.000",    927.000, "Ham 33cm"),
    _ham("33cm Simplex 926.500",    926.500, "Ham 33cm"),

    # ── SSB VHF calling / band-opening detection ──────────────────────────────
    # Enabled with --vhf-ssb (off by default).  Uses USB demodulation + VAD.
    # 6m channels are at the low end of R820T2 sensitivity — reduce --gain if
    # you get noise triggering, or increase --squelch.
    _ssb("6m SSB Calling 50.125",     50.125, "Ham 6m SSB",
         notes="national 6m SSB calling"),
    _ssb("6m SSB DX 50.200",          50.200, "Ham 6m SSB",
         notes="6m SSB DX"),
    _ssb("2m SSB Calling 144.200",   144.200, "Ham 2m SSB",
         notes="national 2m SSB calling"),
    _ssb("70cm SSB Calling 432.100", 432.100, "Ham 70cm SSB",
         notes="national 70cm SSB calling"),
]


# ── scan groups ───────────────────────────────────────────────────────────────

SAMPLE_RATE = 2_400_000
FFT_SIZE    = 131_072

@dataclasses.dataclass
class ScanGroup:
    name:      str
    center_hz: int
    band_flag: str
    channels:  list[Channel] = dataclasses.field(default_factory=list)


def _build_groups(channels: list[Channel]) -> list[ScanGroup]:
    raw = [
        # Standard bands
        ScanGroup("MURS + Biz VHF low",  152_000_000, "murs"),
        ScanGroup("MURS hi + Biz VHF",   154_800_000, "biz"),
        ScanGroup("Marine low",           156_400_000, "marine"),
        ScanGroup("Marine high",          157_200_000, "marine"),
        ScanGroup("NOAA Weather",         162_475_000, "noaa"),
        ScanGroup("Biz UHF 451",         451_800_000, "biz"),
        ScanGroup("Biz UHF 456",         456_800_000, "biz"),
        ScanGroup("FRS/GMRS low",        463_100_000, "frs"),
        ScanGroup("FRS/GMRS hi + Biz",   467_700_000, "frs"),
        # Aviation (AM)
        ScanGroup("Aviation Guard/CTAF", 121_800_000, "airband"),
        ScanGroup("Aviation UNICOM",     122_800_000, "airband"),
        ScanGroup("Aviation SAR/A-A",    123_300_000, "airband"),
        ScanGroup("Aviation FSS/Center", 126_700_000, "airband"),
        ScanGroup("Aviation ARINC",      128_500_000, "airband"),
        # Ham 2m
        ScanGroup("Ham 2m simplex",      146_600_000, "ham-vhf"),
        ScanGroup("Ham 2m high",         147_500_000, "ham-vhf"),
        # Ham 70cm
        ScanGroup("Ham 70cm simplex",    446_100_000, "ham-uhf"),
        # Ham 1.25m
        ScanGroup("Ham 1.25m simplex",   223_470_000, "ham-220"),
        # Ham 33cm
        ScanGroup("Ham 33cm simplex",    927_000_000, "ham-900"),
        # SSB VHF calling (band-opening detection)
        ScanGroup("6m SSB calling",       50_163_000, "vhf-ssb"),
        ScanGroup("2m SSB calling",      144_200_000, "vhf-ssb"),
        ScanGroup("70cm SSB calling",    432_100_000, "vhf-ssb"),
    ]
    half_bw = SAMPLE_RATE // 2
    for ch in channels:
        best = min(raw, key=lambda g: abs(g.center_hz - ch.freq_hz))
        if abs(best.center_hz - ch.freq_hz) <= half_bw - ch.bw_hz // 2:
            best.channels.append(ch)
    return [g for g in raw if g.channels]


SCAN_GROUPS = _build_groups(ALL_CHANNELS)


# ═══════════════════════════════════════════════════════════════════════════════
# DUAL-SDR ANALYZER — constants, priority queue, novelty scoring, custom freqs
# ═══════════════════════════════════════════════════════════════════════════════

ANALYZER_CAPTURE_BLOCK = 32_768      # IQ samples per SDR read (streaming capture)
ANALYZER_CLASSIFY_N    = 131_072     # IQ samples used for classification (~55 ms)
DEFAULT_ANALYZER_DWELL = 5.0         # seconds to capture per signal
DEFAULT_NOVELTY_S      = 120.0       # min seconds before re-analyzing a channel
DEFAULT_ANALYZER_QUEUE = 50          # max pending jobs in priority queue

# Per-band priority bonus (dB-equivalent; higher jumps the queue).
ANALYZER_BAND_BONUS: dict[str, float] = {
    "Ham 6m SSB":   5.0,   # rare band openings — always time-sensitive
    "Ham 2m SSB":   5.0,
    "Ham 70cm SSB": 5.0,
    "Aviation AM":  3.0,
    "Marine":       2.0,
    "Ham 2m":       1.0,
    "Ham 70cm":     1.0,
    "Ham 1.25m":    1.0,
    "Ham 33cm":     1.0,
}


@dataclasses.dataclass(order=True)
class AnalyzerJob:
    neg_score:  float                            # negated score (min-heap → highest priority first)
    ts:         float   = dataclasses.field(compare=False)
    channel:    Channel = dataclasses.field(compare=False)
    power_dbfs: float   = dataclasses.field(compare=False)
    novelty:    float   = dataclasses.field(compare=False, default=0.0)


def _analyzer_score(power_dbfs: float, last_t: float,
                    band: str, novelty: float = 0.0) -> float:
    """Higher = more urgent.  Stored negated in min-heap."""
    age_bonus  = min((time.time() - last_t) / 60.0, 5.0)  # up to +5 for channels idle >5 min
    band_bonus = ANALYZER_BAND_BONUS.get(band, 0.0)
    return power_dbfs + age_bonus + band_bonus + novelty


def _maybe_enqueue(q: "queue.PriorityQueue[AnalyzerJob]",
                   ch: Channel, dbfs: float,
                   last_analyzed: dict, lock: "threading.Lock",
                   novelty_s: float, novelty_score: float = 0.0) -> bool:
    """Push a job only if the channel has not been analyzed recently."""
    now = time.time()
    with lock:
        last_t = last_analyzed.get(ch.freq_hz, 0.0)
        if now - last_t < novelty_s:
            return False
    # ch.priority_bonus is always applied; novelty_score adds on top when tracking is active
    score = _analyzer_score(dbfs, last_t, ch.band, novelty_score + ch.priority_bonus)
    job   = AnalyzerJob(neg_score=-score, ts=now, channel=ch,
                        power_dbfs=dbfs, novelty=novelty_score)
    try:
        q.put_nowait(job)
        return True
    except queue.Full:
        return False


# ── Interestingness / novelty scoring ────────────────────────────────────────

def _novelty_score(ch: Channel, dbfs: float, ch_stats: dict, now: float) -> float:
    """
    First-draft interestingness calculator.  Returns a bonus score (>0 = more interesting).

    Signals score higher when:
      - First time heard on this channel (count == 0  → +10)
      - Fewer than 5 prior detections (diminishing bonus)
      - Significantly stronger than the channel's running average (unusual propagation)
      - USB/LSB on VHF/UHF bands (band-opening indicator)
      - User-specified custom priority (Channel.priority_bonus)

    The score is added to raw signal power in the analyzer priority queue, so a
    novel weak signal can outrank a boring strong one.  Adjust constants to taste.
    """
    stats   = ch_stats.get(ch.freq_hz, {})
    count   = stats.get("count", 0)
    avg_pwr = stats.get("avg_power", dbfs)

    # ch.priority_bonus is applied unconditionally in _maybe_enqueue;
    # this function only returns the *additional* novelty component.
    score = 0.0

    if count == 0:
        score += 10.0           # never-before-heard channel
    elif count <= 4:
        score += 5.0 / (count + 1)

    excess = dbfs - avg_pwr
    if excess > 10.0:
        score += min(excess - 10.0, 6.0)   # unusually strong: up to +6

    if ch.modulation in ("USB", "LSB"):
        score += 6.0            # SSB on VHF/UHF is rare and time-sensitive

    return score


def _update_ch_stats(ch_stats: dict, freq_hz: int, dbfs: float, now: float) -> None:
    s = ch_stats.setdefault(freq_hz, {
        "count": 0, "avg_power": dbfs, "first_seen": now, "last_seen": now
    })
    s["count"]    += 1
    s["last_seen"] = now
    s["avg_power"] = 0.9 * s["avg_power"] + 0.1 * dbfs   # EMA α=0.1


# ── Custom frequency / range parsing ─────────────────────────────────────────

def _parse_custom_freq(spec: str) -> Optional[Channel]:
    """
    Parse  --custom-freq  FREQ[:PRIORITY[:MOD[:NAME]]]   (FREQ in MHz).

    Examples:
      146.520              → NFM, priority 0
      146.520:3            → NFM, priority +3
      50.125:5:USB         → USB calling, priority +5
      146.520:3:NFM:K0ABC  → named channel
    """
    parts = spec.strip().split(":")
    try:
        freq_mhz = float(parts[0])
    except ValueError:
        print(f"  [warning] --custom-freq: bad frequency '{spec}' — skipping")
        return None
    priority = float(parts[1]) if len(parts) > 1 and parts[1] else 0.0
    mod      = parts[2].upper() if len(parts) > 2 and parts[2] else "NFM"
    name     = parts[3] if len(parts) > 3 and parts[3] else f"Custom {freq_mhz:.4f}"
    bw       = 6_000 if mod in ("USB", "LSB") else 16_000
    return Channel(name=name, freq_hz=round(freq_mhz * 1e6), band="Custom",
                   bw_hz=bw, modulation=mod, notes="user-specified",
                   priority_bonus=priority)


def _parse_custom_range(spec: str) -> list[Channel]:
    """
    Parse  --custom-range  START-END[:STEP_KHZ[:PRIORITY[:MOD]]].

    START and END in MHz; STEP in kHz (default 25 kHz).

    Examples:
      144-148              → 25 kHz steps, NFM
      144-148:12.5         → 12.5 kHz steps
      462-468:25:2         → 25 kHz steps, priority +2
      50.0-50.5:25:5:USB   → USB, 25 kHz steps, priority +5
    """
    try:
        range_part, *rest = spec.strip().split(":")
        lo_mhz, hi_mhz   = (float(x) for x in range_part.split("-"))
    except (ValueError, TypeError):
        print(f"  [warning] --custom-range: bad range '{spec}' — skipping")
        return []
    step_khz = float(rest[0]) if len(rest) > 0 and rest[0] else 25.0
    priority = float(rest[1]) if len(rest) > 1 and rest[1] else 0.0
    mod      = rest[2].upper() if len(rest) > 2 and rest[2] else "NFM"
    bw       = 6_000 if mod in ("USB", "LSB") else 16_000
    step_hz  = max(1_000, round(step_khz * 1_000))
    channels: list[Channel] = []
    freq_hz  = round(lo_mhz * 1e6)
    hi_hz    = round(hi_mhz * 1e6)
    while freq_hz <= hi_hz:
        channels.append(Channel(
            name=f"Custom {freq_hz/1e6:.4f}", freq_hz=freq_hz, band="Custom",
            bw_hz=bw, modulation=mod, notes="range scan", priority_bonus=priority,
        ))
        freq_hz += step_hz
    return channels


def _build_custom_groups(channels: list[Channel]) -> list[ScanGroup]:
    """Cluster custom channels into ≤2.4 MHz scan windows."""
    sorted_chs = sorted(channels, key=lambda c: c.freq_hz)
    groups: list[ScanGroup] = []
    used: set[int] = set()
    for ch in sorted_chs:
        if id(ch) in used:
            continue
        cluster = [c for c in sorted_chs
                   if abs(c.freq_hz - ch.freq_hz) <= 1_100_000 and id(c) not in used]
        center = sum(c.freq_hz for c in cluster) // len(cluster)
        g = ScanGroup(f"Custom {center/1e6:.3f} MHz", center, "custom")
        g.channels = cluster
        groups.append(g)
        for c in cluster:
            used.add(id(c))
    return groups


# ── calibration ───────────────────────────────────────────────────────────────

_CAL_FILE = Path.home() / ".rtlsdr_vhf_cal.json"
_cal: Optional[dict] = None

def _load_cal():
    global _cal
    if _CAL_FILE.exists():
        try:
            _cal = json.loads(_CAL_FILE.read_text())
        except Exception:
            pass

def _dbfs_to_dbm(dbfs: float, freq_hz: int) -> Optional[float]:
    if not _cal:
        return None
    key = min(_cal.keys(), key=lambda k: abs(int(k) - freq_hz), default=None)
    if key is None:
        return None
    e = _cal[key]
    return e.get("slope", 1.0) * dbfs + e.get("offset", 0.0)


# ── SQLite ────────────────────────────────────────────────────────────────────

def _open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id             INTEGER PRIMARY KEY,
            ts_utc         TEXT NOT NULL,
            ts_unix        REAL NOT NULL,
            freq_hz        INTEGER NOT NULL,
            freq_mhz       REAL,
            channel_name   TEXT,
            band           TEXT,
            modulation     TEXT,
            bw_hz          INTEGER,
            notes          TEXT,
            signal_dbfs    REAL,
            signal_dbm     REAL,
            squelch_db     REAL,
            has_voice      INTEGER DEFAULT 0,
            recording_path TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON detections (ts_unix)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id             INTEGER PRIMARY KEY,
            ts_utc         TEXT NOT NULL,
            ts_unix        REAL NOT NULL,
            freq_hz        INTEGER NOT NULL,
            freq_mhz       REAL,
            channel_name   TEXT,
            band           TEXT,
            scan_dbfs      REAL,
            analyze_dbfs   REAL,
            classified_mod TEXT,
            classified_bw  INTEGER,
            confidence     REAL,
            novelty_score  REAL,
            has_voice      INTEGER DEFAULT 0,
            recording_path TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_ts ON analyses (ts_unix)")
    conn.commit()
    return conn


def _detection_record(ch: Channel, dbfs: float, squelch_db: float,
                      has_voice: bool, recording_path: Optional[str]) -> dict:
    """Build a complete detection record dict — used for both JSON and SQLite."""
    now    = datetime.now(timezone.utc)
    dbm    = _dbfs_to_dbm(dbfs, ch.freq_hz)
    return {
        "ts_utc":         now.isoformat(),
        "ts_unix":        now.timestamp(),
        "freq_hz":        ch.freq_hz,
        "freq_mhz":       round(ch.freq_hz / 1e6, 6),
        "channel_name":   ch.name,
        "band":           ch.band,
        "modulation":     ch.modulation,
        "bw_hz":          ch.bw_hz,
        "notes":          ch.notes or None,
        "signal_dbfs":    round(dbfs, 2),
        "signal_dbm":     round(dbm, 1) if dbm is not None else None,
        "squelch_db":     squelch_db,
        "has_voice":      has_voice,
        "recording_path": recording_path,
    }


def _log_detection(conn: sqlite3.Connection, ch: Channel, dbfs: float,
                   squelch_db: float, has_voice: bool = False,
                   recording_path: Optional[str] = None,
                   jsonl_path: Optional[str] = None):
    rec = _detection_record(ch, dbfs, squelch_db, has_voice, recording_path)
    conn.execute(
        "INSERT INTO detections "
        "(ts_utc, ts_unix, freq_hz, freq_mhz, channel_name, band, modulation, bw_hz, "
        " notes, signal_dbfs, signal_dbm, squelch_db, has_voice, recording_path) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rec["ts_utc"], rec["ts_unix"], rec["freq_hz"], rec["freq_mhz"],
         rec["channel_name"], rec["band"], rec["modulation"], rec["bw_hz"],
         rec["notes"], rec["signal_dbfs"], rec["signal_dbm"],
         rec["squelch_db"], int(rec["has_voice"]), rec["recording_path"]),
    )
    conn.commit()
    if jsonl_path:
        with open(jsonl_path, "a") as f:
            f.write(json.dumps(rec) + "\n")


def _log_analysis(conn: sqlite3.Connection, job: "AnalyzerJob",
                  analyze_dbfs: float, mod: str, bw_hz: int,
                  confidence: float, novelty: float,
                  has_voice: bool, recording_path: Optional[str]) -> None:
    now = datetime.now(timezone.utc)
    ch  = job.channel
    conn.execute(
        "INSERT INTO analyses "
        "(ts_utc, ts_unix, freq_hz, freq_mhz, channel_name, band, "
        " scan_dbfs, analyze_dbfs, classified_mod, classified_bw, "
        " confidence, novelty_score, has_voice, recording_path) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (now.isoformat(), now.timestamp(),
         ch.freq_hz, round(ch.freq_hz / 1e6, 6), ch.name, ch.band,
         round(job.power_dbfs, 2), round(analyze_dbfs, 2),
         mod, bw_hz, round(confidence, 3), round(novelty, 2),
         int(has_voice), recording_path),
    )
    conn.commit()


# ── display ───────────────────────────────────────────────────────────────────

ANSI_RESET  = "\033[0m"
ANSI_BOLD   = "\033[1m"
ANSI_CYAN   = "\033[96m"
ANSI_YELLOW = "\033[93m"
ANSI_GREEN  = "\033[92m"
ANSI_OFF    = "\033[91m"
ANSI_DIM    = "\033[2m"
ANSI_ORANGE = "\033[33m"

BAND_COLORS = {
    "FRS/GMRS":     ANSI_CYAN,
    "MURS":         ANSI_GREEN,
    "Marine":       ANSI_YELLOW,
    "NOAA":         ANSI_ORANGE,
    "Aviation AM":  "\033[97m",   # bright white
    "Ham 2m":       "\033[92m",   # green
    "Ham 70cm":     "\033[96m",   # cyan
    "Ham 1.25m":    "\033[35m",   # magenta
    "Ham 33cm":     "\033[95m",   # bright magenta
    "Ham 6m SSB":   "\033[93m",   # yellow
    "Ham 2m SSB":   "\033[92m",   # green
    "Ham 70cm SSB": "\033[96m",   # cyan
    "Business VHF": "\033[35m",
    "Business UHF": "\033[95m",
}

def _bar(dbfs: float, lo: float = -90.0, hi: float = -40.0, width: int = 10) -> str:
    frac = max(0.0, min(1.0, (dbfs - lo) / (hi - lo)))
    return "█" * int(frac * width) + "░" * (width - int(frac * width))

def _format_detection(ch: Channel, dbfs: float, ts: str, use_color: bool,
                      has_voice: bool = False, has_rec: bool = False) -> str:
    dbm     = _dbfs_to_dbm(dbfs, ch.freq_hz)
    dbm_str = f"  ~{dbm:+.0f} dBm" if dbm is not None else ""
    flags   = ("  🗣" if has_voice else "") + ("  ⏺" if has_rec else "")
    mod_tag = f" [{ch.modulation}]" if ch.modulation != "NFM" else ""
    mhz     = ch.freq_hz / 1e6
    bar     = _bar(dbfs)
    if use_color:
        col = BAND_COLORS.get(ch.band, "")
        return (f"{ANSI_DIM}[{ts}]{ANSI_RESET} "
                f"{col}{ANSI_BOLD}{ch.name:<30}{ANSI_RESET}{mod_tag}  "
                f"{mhz:9.4f} MHz  {dbfs:+6.1f} dBFS{dbm_str}  {col}{bar}{ANSI_RESET}{flags}")
    return (f"[{ts}] {ch.name:<30}{mod_tag}  {mhz:9.4f} MHz  "
            f"{dbfs:+6.1f} dBFS{dbm_str}  {bar}{flags}")


# ── SMS alert ─────────────────────────────────────────────────────────────────

def _send_sms(detections: list[tuple[Channel, float]]):
    try:
        import subprocess
        sms = Path.home() / "Dropbox/build/money/sms.py"
        chans = ", ".join(f"{c.name} ({c.freq_hz/1e6:.4f} MHz)" for c, _ in detections[:3])
        subprocess.run(["python3", str(sms), f"Bubba Detector: activity on {chans}"],
                       timeout=15)
    except Exception:
        pass


# ── Audio alert ding ──────────────────────────────────────────────────────────

def _play_ding():
    """
    Play a short two-tone ascending chime on the default audio output.

    Designed to be audible but not jarring: 880 Hz (A5) → 1108 Hz (C#6),
    each note with a rapid exponential-decay envelope to give a bell-like
    character.  Non-blocking — returns immediately.
    """
    if not _SOUNDDEVICE_OK:
        return
    try:
        sr  = 44_100
        dur = 0.10   # seconds per note
        t   = np.linspace(0, dur, int(sr * dur), endpoint=False)
        env = np.exp(-8.0 * t / dur)   # fast decay → bell timbre
        note_a  = np.sin(2 * np.pi *  880 * t) * env   # A5
        note_cs = np.sin(2 * np.pi * 1109 * t) * env   # C#6
        gap     = np.zeros(int(sr * 0.02), dtype=np.float32)  # 20 ms silence between notes
        ding    = np.concatenate([note_a, gap, note_cs]).astype(np.float32) * 0.35
        _sd.play(ding, sr, blocking=False)
    except Exception:
        pass


# ── log-mode detection ────────────────────────────────────────────────────────

def _scan_group(sdr: RTLSDR, group: ScanGroup, squelch_db: float) -> list[tuple[Channel, float]]:
    sdr.set_center_freq(group.center_hz)
    iq = sdr.capture_iq(FFT_SIZE)
    window  = np.blackman(len(iq))
    fft_raw = np.fft.fftshift(np.fft.fft(iq * window))
    psd_db  = 10.0 * np.log10(np.maximum(np.abs(fft_raw) ** 2 / np.sum(window**2), 1e-30))
    noise   = float(np.median(psd_db))
    bin_hz  = SAMPLE_RATE / FFT_SIZE
    active  = []
    for ch in group.channels:
        off  = ch.freq_hz - group.center_hz
        cbin = int(round(off / bin_hz)) + FFT_SIZE // 2
        half = max(1, int(ch.bw_hz / 2 / bin_hz))
        lo, hi = max(0, cbin - half), min(FFT_SIZE - 1, cbin + half)
        if lo >= hi:
            continue
        power = float(np.mean(psd_db[lo:hi + 1]))
        if power - noise >= squelch_db:
            active.append((ch, power))
    return active


# ═══════════════════════════════════════════════════════════════════════════════
# DUAL-SDR ANALYZER THREAD
# ═══════════════════════════════════════════════════════════════════════════════

def run_analyzer(args, stop_evt: "threading.Event",
                 q: "queue.PriorityQueue[AnalyzerJob]",
                 last_analyzed: dict, lock: "threading.Lock",
                 db_path: str, use_color: bool) -> None:
    """
    Analyzer thread for dual-SDR mode.

    Consumes AnalyzerJob items from the priority queue (highest-score first),
    tunes the analyzer SDR to each frequency, captures IQ, classifies
    modulation, demodulates, encodes an MP3, runs VAD, and logs to the
    `analyses` table in SQLite.

    Runs until stop_evt is set AND the queue is empty.
    """
    serial = args.analyzer_sdr if args.analyzer_sdr != "auto" else None
    try:
        sdr = RTLSDR(serial=serial,
                     ppm_correction=getattr(args, "analyzer_ppm", 0))
        sdr.set_sample_rate(SCANNER_SDR_RATE)
        sdr.set_gain(getattr(args, "analyzer_gain", 40.0))
    except Exception as e:
        print(f"\n  [analyzer] ERROR: cannot open SDR (serial={serial!r}): {e}")
        return

    conn    = _open_db(db_path)
    rec_dir = Path(getattr(args, "analyzer_rec_dir", "recordings_analyzed"))
    rec_dir.mkdir(parents=True, exist_ok=True)
    vad        = _make_vad()
    dwell_s    = getattr(args, "analyzer_dwell", DEFAULT_ANALYZER_DWELL)
    novelty_s  = getattr(args, "analyzer_novelty", DEFAULT_NOVELTY_S)
    capture_n  = int(dwell_s * SCANNER_SDR_RATE)
    mp3_kbps   = getattr(args, "mp3_bitrate", DEFAULT_BITRATE)

    print(f"\n  [analyzer] open  serial={serial or 'auto'}  "
          f"dwell={dwell_s:.1f}s  novelty={novelty_s:.0f}s  "
          f"rec→{rec_dir}/")

    try:
        while not (stop_evt.is_set() and q.empty()):
            try:
                job = q.get(timeout=1.0)
            except queue.Empty:
                continue

            ch = job.channel

            # Re-check novelty — scanner may have re-queued while we were busy
            with lock:
                last_t = last_analyzed.get(ch.freq_hz, 0.0)
                if time.time() - last_t < novelty_s:
                    q.task_done()
                    continue

            mod_tag = f" [{ch.modulation}]" if ch.modulation != "NFM" else ""
            print(f"\n  [analyzer] ▶ {ch.name}{mod_tag}  "
                  f"{ch.freq_hz/1e6:.4f} MHz  "
                  f"scan={job.power_dbfs:+.1f} dBFS  novelty={job.novelty:.1f}")

            # ── Tune, settle, capture ─────────────────────────────────────────
            try:
                sdr.set_center_freq(ch.freq_hz)
                time.sleep(0.06)   # settle after retune
                iq_blocks: list[np.ndarray] = []
                captured = 0
                while captured < capture_n:
                    n = min(ANALYZER_CAPTURE_BLOCK, capture_n - captured)
                    iq_blocks.append(sdr.capture_iq(n))
                    captured += n
                iq = np.concatenate(iq_blocks)
            except Exception as e:
                print(f"  [analyzer]   capture error: {e}")
                q.task_done()
                continue

            # ── Signal-still-present check ────────────────────────────────────
            fft_n   = 4096
            snap_db = 10.0 * np.log10(np.maximum(
                np.abs(np.fft.fftshift(np.fft.fft(iq[:fft_n]))) ** 2 / fft_n ** 2,
                1e-30))
            noise_db     = float(np.median(snap_db))
            analyze_dbfs = float(np.max(snap_db))
            if analyze_dbfs - noise_db < 4.0:
                print(f"  [analyzer]   signal gone  (floor={noise_db:+.1f} dBFS)")
                with lock:
                    last_analyzed[ch.freq_hz] = time.time()
                q.task_done()
                continue

            # ── Classify ─────────────────────────────────────────────────────
            classify_n = min(ANALYZER_CLASSIFY_N, len(iq))
            mod, bw_hz, conf = _classify_iq(iq[:classify_n], SCANNER_SDR_RATE)
            print(f"  [analyzer]   {mod}  BW≈{bw_hz//1000}kHz  "
                  f"conf={conf:.2f}  power={analyze_dbfs:+.1f} dBFS")

            # ── Demodulate, record, VAD ───────────────────────────────────────
            rec_path  = None
            has_voice = False

            if _SCIPY_OK and _LAMEENC_OK:
                # Prefer classifier output (if confident) over channel declaration
                use_mod = (mod if conf >= 0.55 and mod not in ("noise", "unknown", "digital")
                           else ch.modulation)
                try:
                    if use_mod in ("USB", "LSB"):
                        sos, zi = _make_ssb_bpf()
                        audio, _ = _ssb_demod(iq, sos, zi)
                    elif use_mod == "AM":
                        sos, zi = _make_lpf()
                        audio, _ = _am_demod(iq, sos, zi)
                    else:
                        sos, zi = _make_lpf()
                        audio, _ = _nfm_demod(iq, sos, zi)

                    if _VAD_OK and vad:
                        has_voice, _ = _vad_check(audio, vad, [])

                    mp3_data = _encode_mp3(audio, bitrate=mp3_kbps)
                    ts_safe  = datetime.now().strftime("%Y%m%d_%H%M%S")
                    ch_safe  = ch.name.replace("/", "-").replace(" ", "_")
                    fpath    = rec_dir / f"{ts_safe}_{ch_safe}.mp3"
                    fpath.write_bytes(mp3_data)
                    rec_path = str(fpath)
                except Exception as e:
                    print(f"  [analyzer]   demod/record error: {e}")

            # ── Log and update novelty cache ──────────────────────────────────
            _log_analysis(conn, job, analyze_dbfs, mod, bw_hz, conf,
                          job.novelty, has_voice, rec_path)
            with lock:
                last_analyzed[ch.freq_hz] = time.time()

            flags = ("  🗣" if has_voice else "") + ("  ⏺" if rec_path else "")
            print(f"  [analyzer]   logged{flags}"
                  + (f"  → {rec_path}" if rec_path else ""))

            q.task_done()

    finally:
        sdr.close()
        conn.close()
        print("\n  [analyzer] stopped.")


# ═══════════════════════════════════════════════════════════════════════════════
# SCANNER MODE
# ═══════════════════════════════════════════════════════════════════════════════

def _check_scanner_deps():
    missing = []
    if not _SOUNDDEVICE_OK: missing.append("sounddevice  (pip install sounddevice)")
    if not _LAMEENC_OK:     missing.append("lameenc      (pip install lameenc)")
    if not _SCIPY_OK:       missing.append("scipy        (pip install scipy)")
    if missing:
        print("Scanner mode requires:")
        for m in missing: print(f"  {m}")
        sys.exit(1)


def _make_lpf(cutoff_hz: float = 4_000.0, sample_rate: float = SCANNER_SDR_RATE):
    sos = _butter(4, cutoff_hz / (sample_rate / 2.0), btype="low", output="sos")
    zi  = _sosfilt_zi(sos) * 0.0
    return sos, zi


def _make_ssb_bpf(lo: float = 300.0, hi: float = 3_000.0,
                  sample_rate: float = SCANNER_SDR_RATE):
    nyq = sample_rate / 2.0
    sos = _butter(4, [lo / nyq, hi / nyq], btype="band", output="sos")
    zi  = _sosfilt_zi(sos) * 0.0
    return sos, zi


def _nfm_demod(iq: np.ndarray, sos, zi, gain: float = 0.8):
    """Narrowband FM discriminator → LPF → decimate."""
    diff     = np.angle(iq[1:] * np.conj(iq[:-1]))
    filt, zi = _sosfilt(sos, diff, zi=zi)
    audio    = (filt[::DECIMATE] * gain).astype(np.float32)
    return audio, zi


def _am_demod(iq: np.ndarray, sos, zi, gain: float = 1.2):
    """AM envelope detector → DC removal → LPF → decimate."""
    envelope = np.abs(iq).astype(np.float64)
    envelope -= np.mean(envelope)   # remove carrier DC
    filt, zi = _sosfilt(sos, envelope, zi=zi)
    audio    = (filt[::DECIMATE] * gain).astype(np.float32)
    return audio, zi


def _ssb_demod(iq: np.ndarray, sos, zi, gain: float = 2.0):
    """USB demodulator: bandpass-filter the I channel (real part of baseband IQ), decimate."""
    filt, zi = _sosfilt(sos, iq.real, zi=zi)
    audio    = (filt[::DECIMATE] * gain).astype(np.float32)
    return audio, zi


def _demod(iq: np.ndarray, ch: Channel, sos, zi):
    if ch.modulation == "AM":
        return _am_demod(iq, sos, zi)
    return _nfm_demod(iq, sos, zi)


def _classify_iq(iq: np.ndarray, fs: float = SCANNER_SDR_RATE) -> tuple[str, int, float]:
    """
    Estimate modulation type, occupied bandwidth (Hz), and confidence from IQ samples.

    Returns: (modulation_str, bandwidth_hz, confidence_0_to_1)
    Modulations: "NFM", "WFM", "AM", "USB", "LSB", "CW", "digital", "noise", "unknown"

    Pure numpy — no scipy.  Thresholds are heuristic; tune on real hardware.
    """
    N = len(iq)

    # ── PSD and SNR ───────────────────────────────────────────────────────────
    window  = np.blackman(N)
    fft_raw = np.fft.fftshift(np.fft.fft(iq * window))
    psd     = np.abs(fft_raw) ** 2 / np.sum(window ** 2)
    psd_db  = 10.0 * np.log10(np.maximum(psd, 1e-30))
    noise   = float(np.median(psd_db))
    peak    = float(np.max(psd_db))
    snr     = peak - noise

    if snr < 6.0:
        return "noise", 0, 0.0

    # ── Occupied bandwidth (bins within 10 dB of peak) ────────────────────────
    bw_bins = int(np.sum(psd_db >= peak - 10.0))
    bw_hz   = int(bw_bins * fs / N)

    # ── Spectral asymmetry — SSB indicator ───────────────────────────────────
    mid       = N // 2
    upper_pwr = float(np.sum(psd[mid:]))
    lower_pwr = float(np.sum(psd[:mid]))
    total_pwr = upper_pwr + lower_pwr + 1e-30
    asymmetry = abs(upper_pwr - lower_pwr) / total_pwr

    # ── Instantaneous frequency variance — FM indicator ───────────────────────
    freq_var = float(np.var(np.angle(iq[1:] * np.conj(iq[:-1]))))

    # ── Envelope coefficient of variation — AM indicator ─────────────────────
    env      = np.abs(iq)
    env_cv   = float(np.std(env)) / (float(np.mean(env)) + 1e-10)

    # ── Classification (ordered by specificity) ───────────────────────────────
    # Threshold derivation (at 2.4 MSPS):
    #   inst_freq angle = 2π·f_dev/fs per sample
    #   NFM ±5 kHz:  freq_var ≈ (2π·5000/2.4e6)²/2 ≈ 8.5e-5
    #   WFM ±75 kHz: freq_var ≈ (2π·75000/2.4e6)²/2 ≈ 0.019
    #   Noise:       freq_var ≈ π²/3 ≈ 3.3 (uniform phase jumps)
    # These are FIRST-DRAFT values — tune on real hardware.
    if bw_hz > 80_000 and freq_var > 0.005:
        return "WFM", bw_hz, 0.80

    if 0.00005 < freq_var < 0.005 and bw_hz < 40_000:
        return "NFM", bw_hz, 0.75

    if env_cv > 0.15 and freq_var < 0.001:
        return "AM", bw_hz, 0.70

    if bw_hz < 800:
        return "CW", bw_hz, 0.65

    if asymmetry > 0.35 and 800 < bw_hz < 8_000:
        return ("USB" if upper_pwr > lower_pwr else "LSB"), bw_hz, 0.65

    if env_cv < 0.08 and bw_hz < 30_000:
        return "digital", bw_hz, 0.55

    return "unknown", bw_hz, 0.30


# ── WebRTC Voice Activity Detection ──────────────────────────────────────────

def _make_vad() -> Optional[object]:
    if not _VAD_OK:
        return None
    try:
        return _webrtcvad.Vad(VAD_AGGRESSIVENESS)
    except Exception:
        return None


def _vad_check(audio_48k: np.ndarray, vad, buf: list) -> tuple[bool, list]:
    """
    Run VAD on one audio block.  Buffers samples into VAD_FRAME_MS frames,
    returns (any_voice_detected, remaining_buffer).

    Downsamples 48 kHz → 16 kHz (factor 3) internally.
    Voice flag is set True if any frame in the block is classified as speech.
    Accumulated across the full dwell period so even a brief voice segment
    within a longer transmission is captured.
    """
    if vad is None:
        return False, buf

    audio_16k = audio_48k[::3]   # 48k → 16k
    buf       = buf + audio_16k.tolist()
    voice     = False

    while len(buf) >= VAD_FRAME_SAMPLES:
        frame = np.array(buf[:VAD_FRAME_SAMPLES], dtype=np.float32)
        buf   = buf[VAD_FRAME_SAMPLES:]
        pcm   = np.clip(frame * 32767, -32768, 32767).astype(np.int16)
        try:
            if vad.is_speech(pcm.tobytes(), VAD_RATE):
                voice = True
        except Exception:
            pass

    return voice, buf


# ── MP3 encode / save ─────────────────────────────────────────────────────────

def _encode_mp3(audio: np.ndarray, sample_rate: int = AUDIO_RATE,
                bitrate: int = DEFAULT_BITRATE) -> bytes:
    pcm   = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm * 32767).astype(np.int16)
    enc   = _lameenc.Encoder()
    enc.set_bit_rate(bitrate)
    enc.set_in_sample_rate(sample_rate)
    enc.set_channels(1)
    enc.set_quality(5)
    data  = enc.encode(pcm16.tobytes())
    data += enc.flush()
    return data


def _save_recording(audio_frames: list, ch: Channel, ts: str,
                    rec_dir: Path, bitrate: int) -> Optional[str]:
    if not audio_frames:
        return None
    try:
        audio = np.concatenate(audio_frames)
        mp3   = _encode_mp3(audio, bitrate=bitrate)
        fname = f"{ts}_{ch.name.replace('/', '-').replace(' ', '_')}.mp3"
        path  = rec_dir / fname
        path.write_bytes(mp3)
        return str(path)
    except Exception as e:
        print(f"  [recording error: {e}]")
        return None


# ── audio player ─────────────────────────────────────────────────────────────

class _AudioPlayer:
    def __init__(self):
        self._q   = queue.Queue(maxsize=AUDIO_QUEUE_MAX)
        self._buf = np.zeros(0, dtype=np.float32)
        self._stream = _sd.OutputStream(
            samplerate=AUDIO_RATE, channels=1, dtype="float32",
            blocksize=2048, callback=self._callback)
        self._stream.start()

    def _callback(self, outdata, frames, time_info, status):
        out, pos = np.zeros(frames, dtype=np.float32), 0
        if len(self._buf):
            n = min(len(self._buf), frames)
            out[pos:pos+n] = self._buf[:n]
            self._buf = self._buf[n:]
            pos += n
        while pos < frames:
            try:
                chunk = self._q.get_nowait()
                n = min(len(chunk), frames - pos)
                out[pos:pos+n] = chunk[:n]
                if n < len(chunk):
                    self._buf = chunk[n:]
                pos += n
            except queue.Empty:
                break
        outdata[:, 0] = out

    def push(self, audio: np.ndarray):
        try:
            self._q.put_nowait(audio.copy())
        except queue.Full:
            try: self._q.get_nowait()
            except queue.Empty: pass
            try: self._q.put_nowait(audio.copy())
            except queue.Full: pass

    def close(self):
        self._stream.stop()
        self._stream.close()


# ── scanner state machine ─────────────────────────────────────────────────────

_STATE_SCAN  = "scanning"
_STATE_DWELL = "dwelt"


def run_scanner(args, conn: sqlite3.Connection, channels: list[Channel],
                use_color: bool, jsonl_path: Optional[str] = None):
    _check_scanner_deps()

    rec_dir = None
    if not args.no_record:
        rec_dir = Path(args.rec_dir)
        rec_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Recordings: {rec_dir}/")

    player = None
    if not args.no_audio:
        try:
            player = _AudioPlayer()
            print(f"  Audio: {_sd.query_devices(kind='output')['name']}")
        except Exception as e:
            print(f"  Audio unavailable ({e}); continuing without playback.")

    vad = _make_vad()
    if vad:
        print(f"  Voice detection: webrtcvad aggressiveness {VAD_AGGRESSIVENESS}")
    else:
        print("  Voice detection: unavailable (pip install webrtcvad)")

    sos_lpf, _zi_tmpl     = _make_lpf(cutoff_hz=4_000.0)
    zi_lpf                = _zi_tmpl.copy()
    sos_ssb, _zi_ssb_tmpl = _make_ssb_bpf()
    zi_ssb                = _zi_ssb_tmpl.copy()

    scan_list = sorted(channels, key=lambda c: c.freq_hz)
    if not scan_list:
        print("No channels to scan.")
        return

    try:
        sdr = RTLSDR(serial=args.serial, ppm_correction=args.ppm)
        sdr.set_sample_rate(SCANNER_SDR_RATE)
        sdr.set_gain(args.gain)
    except Exception as e:
        print(f"ERROR: Cannot open RTL-SDR: {e}")
        return

    max_dwell = getattr(args, "max_dwell", DEFAULT_MAX_DWELL)

    # ── adaptive squelch state ────────────────────────────────────────────────
    # ch_quiet[name] = exponential moving average of "excess dB when quiet".
    # Squelch opens only when current excess > ch_quiet + SQUELCH_HYSTERESIS.
    # This lets each channel learn its own interference level automatically.
    SQUELCH_HYSTERESIS = args.squelch   # dB above *learned* background (not raw noise floor)
    QUIET_ALPHA        = 0.25           # EMA weight — lower = slower adaptation
    CONFIRM_BLOCKS     = 4              # consecutive blocks required before declaring open
    ch_quiet: dict[str, float] = {}     # per-channel learned background excess dB
    confirm_count      = 0             # consecutive above-threshold block counter

    state          = _STATE_SCAN
    ch_idx         = 0
    current_ch     = scan_list[ch_idx]
    silence_since  = None
    dwell_start    = None
    hop_start      = time.monotonic()
    dwell_dbfs     = -999.0
    record_buf: list    = []
    record_start_ts     = None
    vad_buf: list       = []
    voice_detected      = False
    ding_played         = False   # ding fires at most once per dwell
    total_detections    = 0
    hits_by_channel: dict[str, int] = {}
    recent: deque[str]  = deque(maxlen=args.tail)
    stop = False

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    def _advance():
        nonlocal ch_idx, current_ch, state, silence_since, zi_lpf, zi_ssb, dwell_dbfs
        nonlocal hop_start, dwell_start, vad_buf, voice_detected, confirm_count, ding_played
        ch_idx        = (ch_idx + 1) % len(scan_list)
        current_ch    = scan_list[ch_idx]
        state         = _STATE_SCAN
        silence_since = None
        dwell_start   = None
        dwell_dbfs    = -999.0
        hop_start     = time.monotonic()
        zi_lpf        = _zi_tmpl.copy()
        zi_ssb        = _zi_ssb_tmpl.copy()
        vad_buf       = []
        voice_detected = False
        ding_played    = False
        confirm_count  = 0

    def _finish_and_log(now_str: str) -> str | None:
        nonlocal record_buf, record_start_ts, voice_detected
        rec_path = None
        if record_buf and rec_dir is not None:
            ts_safe  = record_start_ts or datetime.now().strftime("%Y%m%d_%H%M%S")
            rec_path = _save_recording(record_buf, current_ch, ts_safe,
                                       rec_dir, args.mp3_bitrate)
        _log_detection(conn, current_ch, dwell_dbfs, args.squelch,
                       voice_detected, rec_path, jsonl_path=jsonl_path)
        total_detections_up = total_detections + 1
        hits_by_channel[current_ch.name] = hits_by_channel.get(current_ch.name, 0) + 1
        has_rec = rec_path is not None
        line = _format_detection(current_ch, dwell_dbfs, now_str, use_color,
                                 voice_detected, has_rec)
        recent.append(line)
        if args.sms:
            _send_sms([(current_ch, dwell_dbfs)])
        record_buf       = []
        record_start_ts  = None
        return rec_path, total_detections_up

    print(f"\n  Scanner  —  {len(scan_list)} channels  |  "
          f"squelch +{args.squelch:.0f} dB  |  max-dwell {max_dwell:.0f}s")
    print(f"  Audio: {'off' if args.no_audio else 'on'}  |  "
          f"Recording: {'off' if args.no_record else 'on'}  |  "
          f"{args.mp3_bitrate} kbps\n  Press Ctrl-C to stop.\n")

    sdr.set_center_freq(current_ch.freq_hz)

    try:
        while not stop:
            try:
                iq = sdr.capture_iq(IQ_BLOCK)
            except Exception as e:
                print(f"  RTL-SDR error: {e} — retrying")
                time.sleep(0.2)
                continue

            # ── Squelch detection ─────────────────────────────────────────────
            # Stage 1: FFT peak vs. single-block noise floor (fast, per-block)
            fft_n  = 4096
            fft_db = 10.0 * np.log10(np.maximum(
                np.abs(np.fft.fftshift(np.fft.fft(iq[:fft_n]))) ** 2 / fft_n ** 2,
                1e-30))
            noise_db  = float(np.median(fft_db))
            half_bins = max(2, int(current_ch.bw_hz / 2 / (SCANNER_SDR_RATE / fft_n)))
            mid       = fft_n // 2
            peak_db   = float(np.max(fft_db[mid - half_bins : mid + half_bins + 1]))
            power_dbfs = peak_db
            raw_excess = peak_db - noise_db    # dB above this block's noise floor

            # Stage 2: Adaptive per-channel background learning.
            # When scanning (no signal), track how noisy each channel is.
            # Open squelch only when excess is significantly above the channel's
            # own learned background — this automatically rejects stable bleedthrough
            # from nearby strong stations (e.g. NOAA) without needing manual tuning.
            ch_name = current_ch.name
            if state == _STATE_SCAN:
                # Update learned quiet level during scanning
                prev = ch_quiet.get(ch_name)
                if prev is None:
                    ch_quiet[ch_name] = raw_excess       # first visit: seed with current level
                else:
                    ch_quiet[ch_name] = prev * (1 - QUIET_ALPHA) + raw_excess * QUIET_ALPHA

            learned_bg = ch_quiet.get(ch_name, 0.0)
            sq_above   = raw_excess > learned_bg + SQUELCH_HYSTERESIS

            # Stage 3: Carrier confirmation — require CONFIRM_BLOCKS consecutive
            # blocks above threshold before transitioning to dwell.  This rejects
            # transient noise bursts (which disappear within 1–2 blocks) while
            # letting real carriers (stable for 40+ ms) through.
            if sq_above:
                confirm_count = min(confirm_count + 1, CONFIRM_BLOCKS + 1)
            else:
                confirm_count = 0

            sq_open = (confirm_count >= CONFIRM_BLOCKS)

            now_str = datetime.now().strftime("%H:%M:%S")

            if sq_open:
                dwell_dbfs    = max(dwell_dbfs, power_dbfs)
                silence_since = None

                if state == _STATE_SCAN:
                    state = _STATE_DWELL
                    dwell_start     = time.monotonic()
                    record_start_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    mod_tag = f" [{current_ch.modulation}]" if current_ch.modulation != "NFM" else ""
                    print(f"\n  ▶ {current_ch.name}{mod_tag}  "
                          f"{current_ch.freq_hz/1e6:.4f} MHz  {power_dbfs:+.1f} dBFS  "
                          f"(+{raw_excess:.0f} dB above bg)")
                    # Ding immediately on squelch-open when VAD is not available.
                    # When VAD is available, we wait for confirmed voice (below).
                    if args.alert and not ding_played and not _VAD_OK:
                        _play_ding()
                        ding_played = True

                # Demodulate — NFM, AM, or USB/LSB depending on channel
                if current_ch.modulation in ("USB", "LSB"):
                    audio, zi_ssb = _ssb_demod(iq, sos_ssb, zi_ssb)
                else:
                    audio, zi_lpf = _demod(iq, current_ch, sos_lpf, zi_lpf)

                if player:
                    player.push(audio)
                if rec_dir is not None:
                    record_buf.append(audio)

                # VAD — runs on every demodulated block, result accumulates.
                # When --alert is set, ding the first time voice is confirmed.
                voice_now, vad_buf = _vad_check(audio, vad, vad_buf)
                if voice_now:
                    voice_detected = True
                    if args.alert and not ding_played:
                        _play_ding()
                        ding_played = True

                # Force advance: max-dwell timeout or recording size limit
                rec_s = len(record_buf) * AUDIO_BLOCK / AUDIO_RATE
                force = rec_s > MAX_RECORD_S or (
                    dwell_start and time.monotonic() - dwell_start >= max_dwell)
                if force:
                    _, new_total = _finish_and_log(now_str)
                    total_detections = new_total
                    if use_color: os.system("clear")
                    _print_scanner_status(scan_list, ch_idx, state,
                                          recent, hits_by_channel,
                                          total_detections, args)
                    _advance()
                    sdr.set_center_freq(current_ch.freq_hz)

            else:
                if state == _STATE_DWELL:
                    if silence_since is None:
                        silence_since = time.monotonic()

                    if time.monotonic() - silence_since >= args.resume_delay:
                        _, new_total = _finish_and_log(now_str)
                        total_detections = new_total
                        if use_color: os.system("clear")
                        _print_scanner_status(scan_list, ch_idx, state,
                                              recent, hits_by_channel,
                                              total_detections, args)
                        _advance()
                        sdr.set_center_freq(current_ch.freq_hz)

                elif state == _STATE_SCAN:
                    if time.monotonic() - hop_start >= args.skip_delay:
                        _advance()
                        sdr.set_center_freq(current_ch.freq_hz)

    finally:
        if record_buf:
            _finish_and_log(datetime.now().strftime("%H:%M:%S"))
        sdr.close()
        if player:
            player.close()

    print(f"\nScanner stopped.  {total_detections} detections.")


def _print_scanner_status(scan_list, ch_idx, state, recent, hits, total, args):
    print(f"\n  Scanner  |  ch {ch_idx+1}/{len(scan_list)}  |  "
          f"detections: {total}  |  squelch +{args.squelch:.0f} dB\n")
    if recent:
        print(f"  {'─'*72}")
        for line in recent:
            print(f"  {line}")
        print(f"  {'─'*72}")
    else:
        print("  (no activity yet)")
    if hits:
        top = sorted(hits.items(), key=lambda x: -x[1])[:5]
        print(f"\n  Top: " + "  |  ".join(f"{n} ({c})" for n, c in top))
    print(f"\n  Press Ctrl-C to stop.")


# ═══════════════════════════════════════════════════════════════════════════════
# LOG MODE
# ═══════════════════════════════════════════════════════════════════════════════

def run_log(args, conn: sqlite3.Connection, active_groups: list[ScanGroup],
            use_color: bool, jsonl_path: Optional[str] = None,
            analyzer_queue: Optional["queue.PriorityQueue"] = None,
            last_analyzed: Optional[dict] = None,
            analyzed_lock: Optional["threading.Lock"] = None,
            ch_stats: Optional[dict] = None):
    total_detections    = 0
    hits_by_channel: dict[str, int] = {}
    recent: deque[str]  = deque(maxlen=args.tail)
    cycle = 0
    stop  = False

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    try:
        sdr = RTLSDR(serial=args.serial, ppm_correction=args.ppm)
        sdr.set_sample_rate(SAMPLE_RATE)
        sdr.set_gain(args.gain)
    except Exception as e:
        print(f"ERROR: Cannot open RTL-SDR: {e}")
        return

    n_ch = sum(len(g.channels) for g in active_groups)
    analyzer_active = analyzer_queue is not None
    print(f"\n  Log mode  —  {n_ch} channels  |  {len(active_groups)} scan groups"
          + ("  |  analyzer active" if analyzer_active else ""))
    print(f"  Squelch: +{args.squelch:.0f} dB  |  Press Ctrl-C to stop.\n")

    try:
        while not stop:
            t0 = time.monotonic()
            cycle_hits: list[tuple[Channel, float]] = []

            for group in active_groups:
                if stop: break
                try:
                    hits = _scan_group(sdr, group, args.squelch)
                except Exception:
                    continue
                for ch, dbfs in hits:
                    now_ts  = time.time()
                    now_str = datetime.now().strftime("%H:%M:%S")

                    # Novelty scoring (if tracking is enabled)
                    novelty = 0.0
                    is_novel = False
                    if ch_stats is not None:
                        novelty  = _novelty_score(ch, dbfs, ch_stats, now_ts)
                        is_novel = novelty > 8.0
                        _update_ch_stats(ch_stats, ch.freq_hz, dbfs, now_ts)

                    # Push to analyzer queue (if active)
                    if (analyzer_queue is not None and last_analyzed is not None
                            and analyzed_lock is not None):
                        _maybe_enqueue(analyzer_queue, ch, dbfs,
                                       last_analyzed, analyzed_lock,
                                       getattr(args, "analyzer_novelty", DEFAULT_NOVELTY_S),
                                       novelty_score=novelty)

                    novel_flag = "  ★" if is_novel else ""
                    recent.append(_format_detection(ch, dbfs, now_str, use_color) + novel_flag)
                    _log_detection(conn, ch, dbfs, args.squelch, jsonl_path=jsonl_path)
                    hits_by_channel[ch.name] = hits_by_channel.get(ch.name, 0) + 1
                    total_detections += 1
                    cycle_hits.append((ch, dbfs))

            if use_color: os.system("clear")
            else: print("\033[H\033[J", end="")
            cycle += 1
            elapsed = time.monotonic() - t0
            print(f"\n  Bubba Detector  cycle #{cycle}  |  "
                  f"detections: {total_detections}  |  scan: {elapsed:.2f}s")
            if analyzer_active:
                print(f"  Analyzer queue: {analyzer_queue.qsize()} pending")
            print()
            if recent:
                print(f"  {'─'*72}")
                for line in recent:
                    print(f"  {line}")
                print(f"  {'─'*72}")
            else:
                print("  (no activity yet)")
            if hits_by_channel:
                top = sorted(hits_by_channel.items(), key=lambda x: -x[1])[:5]
                print(f"\n  Top: " + "  |  ".join(f"{n} ({c})" for n, c in top))
            print(f"\n  Press Ctrl-C to stop.\n")

            if args.sms and cycle_hits:
                _send_sms(cycle_hits)
            if args.alert and cycle_hits:
                _play_ding()

    finally:
        sdr.close()

    print(f"\nStopped after {cycle} cycles, {total_detections} detections.")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def list_channels():
    print(f"\n{'Mod':<4} {'Band':<14} {'Channel':<32} {'Freq (MHz)':>12}  {'BW (kHz)':>9}  Notes")
    print("─" * 90)
    by_band: dict[str, list[Channel]] = {}
    for ch in sorted(ALL_CHANNELS, key=lambda c: (c.band, c.freq_hz)):
        by_band.setdefault(ch.band, []).append(ch)
    for band, chs in sorted(by_band.items()):
        for ch in chs:
            print(f"{ch.modulation:<4} {band:<14} {ch.name:<32} "
                  f"{ch.freq_hz/1e6:>12.4f}  {ch.bw_hz/1000:>9.3f}  {ch.notes}")
    total = len(ALL_CHANNELS)
    print(f"\nTotal: {total} channels  |  Scan groups: {len(SCAN_GROUPS)}\n")


def main():
    p = argparse.ArgumentParser(
        description="Bubba Detector — RTL-SDR multi-band handheld radio scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Mode
    p.add_argument("--mode",       choices=["log","scan"], default="log")

    # Common
    p.add_argument("--squelch",   type=float, default=10.0,
                   help="[log] dB above single-block noise floor (default 10).  "
                        "[scan] dB above *learned per-channel background* (auto-adaptive; default 10)")
    p.add_argument("--gain",      type=float, default=40.0,
                   help="RTL-SDR gain dB (default 40)")
    p.add_argument("--ppm",       type=int,   default=0)
    p.add_argument("--serial",    default=None)
    p.add_argument("--log",       default=None,
                   help="SQLite path (default: bubba_<ts>.db)")
    p.add_argument("--sms",       action="store_true",
                   help="Send SMS via ~/money/sms.py on any activity (renamed from --alert)")
    p.add_argument("--alert",     action="store_true",
                   help="Play an audio ding when traffic is detected.  In scan mode with "
                        "voice detection active, dings only on confirmed human voice.")
    p.add_argument("--tail",      type=int, default=25)
    p.add_argument("--no-color",  action="store_true", dest="no_color")
    p.add_argument("--list-channels", action="store_true", dest="list_channels")

    # Band selection — standard bands
    p.add_argument("--no-frs",    action="store_true", dest="no_frs")
    p.add_argument("--no-murs",   action="store_true", dest="no_murs")
    p.add_argument("--no-marine", action="store_true", dest="no_marine")
    p.add_argument("--no-noaa",   action="store_true", dest="no_noaa",
                   help="Skip NOAA channels (default; kept for backwards compatibility)")
    p.add_argument("--noaa",      action="store_true", dest="include_noaa",
                   help="Include NOAA weather channels (always-on broadcast; excluded by default)")
    p.add_argument("--no-biz",    action="store_true", dest="no_biz")

    # Optional extra bands (off by default)
    p.add_argument("--airband",   action="store_true",
                   help="Add aviation VHF AM channels (118–136 MHz)")
    p.add_argument("--ham-vhf",   action="store_true", dest="ham_vhf",
                   help="Add amateur 2m FM simplex (144–148 MHz)")
    p.add_argument("--ham-uhf",   action="store_true", dest="ham_uhf",
                   help="Add amateur 70cm FM simplex (440–450 MHz)")
    p.add_argument("--ham-220",   action="store_true", dest="ham_220",
                   help="Add amateur 1.25m FM simplex (222–225 MHz)")
    p.add_argument("--ham-900",   action="store_true", dest="ham_900",
                   help="Add amateur 33cm FM simplex (902–928 MHz)")
    p.add_argument("--vhf-ssb",   action="store_true", dest="vhf_ssb",
                   help="Add 6m/2m/70cm USB calling frequencies for VHF band-opening "
                        "detection with VAD (50.125, 50.200, 144.200, 432.100 MHz; "
                        "note: 6m sensitivity is reduced on R820T2 dongles)")

    # Custom frequencies / ranges
    p.add_argument("--custom-freq",  action="append", dest="custom_freqs",
                   metavar="FREQ[:PRI[:MOD[:NAME]]]",
                   help="Add a specific frequency (MHz) with optional priority bonus, "
                        "modulation (NFM/AM/USB), and name.  "
                        "Example: 146.520:3  or  50.125:5:USB:6m-call.  "
                        "Repeatable.")
    p.add_argument("--custom-range", action="append", dest="custom_ranges",
                   metavar="START-END[:STEP_KHZ[:PRI[:MOD]]]",
                   help="Scan a frequency range (MHz) with optional step (kHz, default 25), "
                        "priority bonus, and modulation.  "
                        "Example: 144-148:12.5:2  Repeatable.")

    # Novelty / interestingness mode
    p.add_argument("--novelty",      action="store_true",
                   help="Track per-channel detection history and flag novel signals (★) "
                        "in the display.  Boosts analyzer queue priority for unusual signals.")

    # Dual-SDR analyzer (log mode only)
    p.add_argument("--analyzer-sdr",    default=None,  dest="analyzer_sdr",
                   metavar="SERIAL",
                   help="Enable dual-SDR analyzer mode (log mode only).  "
                        "Specify the serial number of the analyzer dongle "
                        "(run rtl_test -t to list serials).  "
                        "Use 'auto' to pick the second detected device.  "
                        "The scanner uses --serial; the analyzer uses this.")
    p.add_argument("--analyzer-ppm",    type=int,   default=0,
                   dest="analyzer_ppm",    metavar="PPM")
    p.add_argument("--analyzer-gain",   type=float, default=40.0,
                   dest="analyzer_gain",   metavar="DB")
    p.add_argument("--analyzer-dwell",  type=float, default=DEFAULT_ANALYZER_DWELL,
                   dest="analyzer_dwell",  metavar="SEC",
                   help=f"Seconds to capture per signal (default {DEFAULT_ANALYZER_DWELL})")
    p.add_argument("--analyzer-novelty", type=float, default=DEFAULT_NOVELTY_S,
                   dest="analyzer_novelty", metavar="SEC",
                   help=f"Min seconds before re-analyzing a channel "
                        f"(default {DEFAULT_NOVELTY_S:.0f})")
    p.add_argument("--analyzer-rec-dir", default="recordings_analyzed",
                   dest="analyzer_rec_dir",
                   help="Directory for analyzer MP3 recordings "
                        "(default: recordings_analyzed)")

    # Scan mode options
    p.add_argument("--no-audio",  action="store_true", dest="no_audio")
    p.add_argument("--no-record", action="store_true", dest="no_record")
    p.add_argument("--resume-delay", type=float, default=DEFAULT_RESUME,
                   dest="resume_delay")
    p.add_argument("--skip-delay",   type=float, default=DEFAULT_SKIP,
                   dest="skip_delay")
    p.add_argument("--max-dwell",    type=float, default=DEFAULT_MAX_DWELL,
                   dest="max_dwell")
    p.add_argument("--mp3-bitrate",  type=int,   default=DEFAULT_BITRATE,
                   dest="mp3_bitrate")
    p.add_argument("--rec-dir",      default="recordings", dest="rec_dir")

    args = p.parse_args()

    if args.list_channels:
        list_channels()
        return

    _load_cal()

    # ── Build skip-flags set ──────────────────────────────────────────────────
    skip_flags: set[str] = set()
    if args.no_frs:    skip_flags.add("frs")
    if args.no_murs:   skip_flags.add("murs")
    if args.no_marine: skip_flags.add("marine")
    if args.no_biz:    skip_flags.add("biz")

    # NOAA: excluded by default (always-on broadcast); opt in with --noaa
    if not args.include_noaa:
        skip_flags.add("noaa")

    # Optional bands are OFF by default; add only when flag is set
    if not args.airband:  skip_flags.add("airband")
    if not args.ham_vhf:  skip_flags.add("ham-vhf")
    if not args.ham_uhf:  skip_flags.add("ham-uhf")
    if not args.ham_220:  skip_flags.add("ham-220")
    if not args.ham_900:  skip_flags.add("ham-900")
    if not args.vhf_ssb:  skip_flags.add("vhf-ssb")

    # ── Filter channels / groups ──────────────────────────────────────────────
    BAND_TO_FLAG = {
        "FRS/GMRS":     "frs",
        "MURS":         "murs",
        "Marine":       "marine",
        "NOAA":         "noaa",
        "Business VHF": "biz",
        "Business UHF": "biz",
        "Aviation AM":  "airband",
        "Ham 2m":       "ham-vhf",
        "Ham 70cm":     "ham-uhf",
        "Ham 1.25m":    "ham-220",
        "Ham 33cm":     "ham-900",
        "Ham 6m SSB":   "vhf-ssb",
        "Ham 2m SSB":   "vhf-ssb",
        "Ham 70cm SSB": "vhf-ssb",
    }
    scan_channels = [ch for ch in ALL_CHANNELS
                     if BAND_TO_FLAG.get(ch.band, "") not in skip_flags]
    active_groups = [g for g in SCAN_GROUPS if g.band_flag not in skip_flags]

    # ── Custom frequencies and ranges ─────────────────────────────────────────
    custom_channels: list[Channel] = []
    for spec in (args.custom_freqs or []):
        ch = _parse_custom_freq(spec)
        if ch:
            custom_channels.append(ch)
    for spec in (args.custom_ranges or []):
        custom_channels.extend(_parse_custom_range(spec))
    if custom_channels:
        custom_groups = _build_custom_groups(custom_channels)
        scan_channels.extend(custom_channels)
        active_groups.extend(custom_groups)
        print(f"  Custom: {len(custom_channels)} frequencies  "
              f"({len(custom_groups)} scan groups)")

    if not scan_channels and args.mode == "scan":
        print("All bands disabled — nothing to scan.")
        return
    if not active_groups and args.mode == "log":
        print("All scan groups disabled — nothing to scan.")
        return

    # ── Open SQLite ───────────────────────────────────────────────────────────
    db_path    = args.log or "bubba.db"
    jsonl_path = db_path.replace(".db", ".jsonl") if db_path.endswith(".db") \
                 else db_path + ".jsonl"
    conn       = _open_db(db_path)

    use_color = not args.no_color and sys.stdout.isatty()

    # Header
    bands_on = sorted({BAND_TO_FLAG.get(ch.band,"?") for ch in scan_channels} -
                      {"?"})
    print(f"\n{'='*72}")
    print(f"  Bubba Detector  —  mode: {args.mode.upper()}")
    print(f"  SQLite: {db_path}")
    print(f"  JSON:   {jsonl_path}")
    print(f"  Bands: {', '.join(bands_on)}")
    if _cal:
        print(f"  Calibration: {_CAL_FILE} ({len(_cal)} entries)")
    else:
        print(f"  Signal strength: dBFS (uncalibrated)")
    if args.mode == "scan" and not _VAD_OK:
        print("  Voice detection: unavailable (pip install webrtcvad)")
    print(f"{'='*72}")

    # ── Dual-SDR analyzer setup (log mode only) ───────────────────────────────
    analyzer_thread = None
    analyzer_queue  = None
    last_analyzed: dict         = {}
    analyzed_lock               = threading.Lock()
    stop_evt                    = threading.Event()
    use_novelty = args.novelty or bool(args.analyzer_sdr)
    ch_stats: Optional[dict]    = {} if use_novelty else None

    if args.analyzer_sdr and args.mode == "log":
        analyzer_queue = queue.PriorityQueue(maxsize=DEFAULT_ANALYZER_QUEUE)
        analyzer_thread = threading.Thread(
            target=run_analyzer,
            args=(args, stop_evt, analyzer_queue,
                  last_analyzed, analyzed_lock, db_path, use_color),
            daemon=True,
            name="analyzer",
        )
    elif args.analyzer_sdr and args.mode == "scan":
        print("  Note: --analyzer-sdr is only supported in log mode; ignoring.")

    try:
        if analyzer_thread:
            analyzer_thread.start()

        if args.mode == "scan":
            run_scanner(args, conn, scan_channels, use_color, jsonl_path=jsonl_path)
        else:
            run_log(args, conn, active_groups, use_color, jsonl_path=jsonl_path,
                    analyzer_queue=analyzer_queue,
                    last_analyzed=last_analyzed if analyzer_queue else None,
                    analyzed_lock=analyzed_lock  if analyzer_queue else None,
                    ch_stats=ch_stats)
    finally:
        conn.close()
        if analyzer_thread and analyzer_thread.is_alive():
            stop_evt.set()
            if analyzer_queue:
                try:
                    analyzer_queue.join()
                except Exception:
                    pass
            analyzer_thread.join(timeout=15.0)


if __name__ == "__main__":
    main()
