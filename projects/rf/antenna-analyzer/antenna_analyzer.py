#!/usr/bin/env python3
"""
Antenna Analyzer — Siglent SSA + Reflection Bridge

Connects via SCPI/TCP, sweeps amateur and service bands, computes VSWR from
return loss, and generates text/JSON/CSV reports and PNG plots.

Calibration:
  Connect an OPEN circuit to the DUT port before calibrating.
  Open = 100% reflection = 0 dB RL reference.  --calibrate always sweeps
  all bands so the calibration file covers every possible measurement.

Usage:
  python antenna_analyzer.py                       # HF bands (default)
  python antenna_analyzer.py --hf --vhf            # HF + 6m/2m/1.25m
  python antenna_analyzer.py --bands 40m 20m       # specific bands
  python antenna_analyzer.py --watch --bands 40m   # live retune mode
  python antenna_analyzer.py --calibrate --yes     # unattended calibration
"""

import argparse
import csv as csv_module
import json
import math
import os
import socket
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Siglent shared drivers
# ---------------------------------------------------------------------------

from rf_bench.siglent import SSA3000X                                      # noqa: E402
from rf_bench.siglent.ssa3000x import DEFAULT_TG_LEVEL as DEFAULT_TG_LEVEL_DBM  # noqa: E402
from rf_bench.utils import (                                               # noqa: E402
    rl_to_vswr, rl_to_vswr_v, format_freq, nearest_rbw,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

INSTRUMENT_HOST      = "10.1.1.60"
INSTRUMENT_PORT      = 5025
DEFAULT_POINTS       = 1001
QUICK_POINTS         = 201
DEFAULT_CAL_FILE     = os.path.expanduser("~/.calibration.npz")
HISTORY_LOG          = os.path.expanduser("~/.antenna_log.csv")
# All supported bands in ascending frequency order: (start_hz, stop_hz, name)
ALL_BANDS = [
    (1_800_000,     2_000_000,    "160m"),
    (3_500_000,     4_000_000,    "80m"),
    (4_063_000,     4_438_000,    "marine4"),   # Marine HF 4 MHz (ITU)
    (5_330_500,     5_403_500,    "60m"),
    (6_200_000,     6_525_000,    "marine6"),   # Marine HF 6 MHz (ITU)
    (7_000_000,     7_300_000,    "40m"),
    (8_195_000,     8_815_000,    "marine8"),   # Marine HF 8 MHz (ITU)
    (10_100_000,    10_150_000,   "30m"),
    (12_230_000,    13_200_000,   "marine12"),  # Marine HF 12 MHz (ITU)
    (14_000_000,    14_350_000,   "20m"),
    (16_360_000,    17_410_000,   "marine16"),  # Marine HF 16 MHz (ITU)
    (18_068_000,    18_168_000,   "17m"),
    (18_780_000,    18_900_000,   "marine18"),  # Marine HF 18 MHz (ITU)
    (21_000_000,    21_450_000,   "15m"),
    (22_000_000,    22_855_000,   "marine22"),  # Marine HF 22 MHz (ITU)
    (24_890_000,    24_990_000,   "12m"),
    (25_070_000,    25_215_000,   "marine25"),  # Marine HF 25 MHz (ITU)
    (26_965_000,    27_405_000,   "11m"),       # CB (channels 1–40)
    (28_000_000,    29_700_000,   "10m"),
    (50_000_000,    54_000_000,   "6m"),
    (108_000_000,   137_000_000,  "aviation"),  # Aviation VHF (nav 108–118 + comms 118–137)
    (144_000_000,   148_000_000,  "2m"),
    (151_820_000,   154_600_000,  "murs"),      # MURS (5 channels)
    (156_000_000,   162_600_000,  "marine"),    # Marine VHF (ch 1–88 + WX1–WX7)
    (219_000_000,   225_000_000,  "1.25m"),     # 1.25 m amateur band
    (420_000_000,   450_000_000,  "70cm"),
    (462_500_000,   467_800_000,  "frs"),       # FRS/GMRS (462.550–467.7125 MHz)
    (902_000_000,   928_000_000,  "33cm"),      # 33 cm amateur / ISM 915 MHz
    (1_240_000_000, 1_300_000_000, "23cm"),     # 23 cm amateur band
    (2_300_000_000, 2_450_000_000, "13cm"),     # 13 cm amateur band
    (2_400_000_000, 2_484_000_000, "2.4ghz"),   # 2.4 GHz ISM: WiFi / Bluetooth
]

# Band group membership
HF_BAND_NAMES        = {"160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m"}
CB_BAND_NAMES        = {"11m"}
VHF_BAND_NAMES       = {"6m", "2m", "1.25m"}
UHF_BAND_NAMES       = {"70cm", "33cm", "23cm", "13cm", "2.4ghz"}
FRS_BAND_NAMES       = {"frs"}
GMRS_BAND_NAMES      = {"frs"}          # GMRS and FRS share 462.5–467.8 MHz; same sweep
MURS_BAND_NAMES      = {"murs"}
AVIATION_BAND_NAMES  = {"aviation"}
MARINE_BAND_NAMES    = {"marine"}
MARINE_HF_BAND_NAMES = {"marine4", "marine6", "marine8", "marine12",
                         "marine16", "marine18", "marine22", "marine25"}

BAND_MAP = {b[2].lower(): b for b in ALL_BANDS}

# Sub-band boundary markers for amateur bands (US allocations).
# Each entry: list of (freq_hz, label) pairs drawn as vertical lines on plots.
SUBBAND_MARKERS: dict[str, list[tuple[int, str]]] = {
    "160m": [(1_840_000,   "Phone")],
    "80m":  [(3_600_000,   "Phone")],
    "40m":  [(7_125_000,   "Phone")],
    "20m":  [(14_150_000,  "Phone")],
    "17m":  [(18_110_000,  "Phone")],
    "15m":  [(21_200_000,  "Phone")],
    "12m":  [(24_930_000,  "Phone")],
    "10m":  [(28_300_000,  "Phone"), (29_000_000, "FM")],
    "6m":   [(50_100_000,  "Phone"), (51_000_000, "FM")],
    "2m":   [(144_100_000, "SSB/CW"), (146_000_000, "FM")],
}

# ---------------------------------------------------------------------------
# Math / formatting helpers
# ---------------------------------------------------------------------------

def _assessment(vswr: float) -> str:
    if vswr <= 1.5:
        return "Excellent"
    if vswr <= 2.0:
        return "Good"
    if vswr <= 3.0:
        return "Fair"
    return "Poor"


# ---------------------------------------------------------------------------
# Calibration file I/O
# ---------------------------------------------------------------------------

def save_calibration(path: str, cal_data: dict[str, np.ndarray], host: str, points: int):
    """Save open-circuit calibration traces to a .npz file."""
    meta = json.dumps({
        "timestamp": datetime.now().isoformat(),
        "host":      host,
        "points":    points,
        "bands":     sorted(cal_data.keys()),
    })
    arrays = {f"cal_{name}": arr for name, arr in cal_data.items()}
    arrays["_meta"] = np.array([meta])
    np.savez(path, **arrays)
    print(f"Calibration saved → {path}")


def load_calibration(path: str) -> tuple[dict[str, np.ndarray], dict]:
    """Load calibration from a .npz file.

    Returns (cal_data, meta). Raises FileNotFoundError / ValueError on failure.
    """
    data = np.load(path, allow_pickle=False)
    meta: dict = {}
    if "_meta" in data.files:
        try:
            meta = json.loads(str(data["_meta"][0]))
        except (json.JSONDecodeError, IndexError):
            pass
    cal_data = {k[4:]: data[k] for k in data.files if k.startswith("cal_")}
    if not cal_data:
        raise ValueError(f"{path} contains no calibration data")
    return cal_data, meta


# ---------------------------------------------------------------------------
# Result I/O — save/load measurement data for comparison and history
# ---------------------------------------------------------------------------

def save_results_json(results: list[dict], output_prefix: str,
                      calibrated: bool, host: str) -> str:
    """Write <prefix>.json with per-band freq/VSWR arrays for later comparison."""
    path = f"{output_prefix}.json"
    data: dict = {
        "timestamp":  datetime.now().isoformat(),
        "instrument": host,
        "calibrated": calibrated,
        "bands":      [],
    }
    for r in results:
        entry: dict = {
            "name":       r["name"],
            "start_hz":   int(r["start_hz"]),
            "stop_hz":    int(r["stop_hz"]),
            "best_freq_hz": float(r["best_freq"]),
            "best_vswr":  float(r["best_vswr"]),
            "best_rl_db": float(r["best_rl"]),
            "bw_2to1_hz": float(r["bw_2to1_hz"]),
            "freqs_hz":   r["freqs"].tolist(),
            "vswr":       r["vswr"].tolist(),
            "rl_db":      r["rl_db"].tolist(),
        }
        if r.get("narrow_freq") is not None:
            entry["narrow_freq_hz"] = float(r["narrow_freq"])
            entry["narrow_vswr"]    = float(r["narrow_vswr"])
            entry["narrow_rl_db"]   = float(r["narrow_rl"])
        data["bands"].append(entry)
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def load_results_json(path: str) -> list[dict]:
    """Load a previous result JSON for comparison overlay."""
    with open(path) as f:
        data = json.load(f)
    out = []
    for b in data.get("bands", []):
        out.append({
            "name":  b["name"],
            "freqs": np.array(b["freqs_hz"]),
            "vswr":  np.array(b["vswr"]),
        })
    return out


def save_csv(results: list[dict], output_prefix: str) -> str:
    """Write per-frequency-point CSV: band, freq_hz, freq_mhz, vswr, return_loss_db."""
    path = f"{output_prefix}.csv"
    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["band", "freq_hz", "freq_mhz", "vswr", "return_loss_db"])
        for r in results:
            for freq, vswr, rl in zip(r["freqs"], r["vswr"], r["rl_db"]):
                w.writerow([r["name"], f"{freq:.0f}", f"{freq/1e6:.6f}",
                             f"{vswr:.4f}", f"{rl:.3f}"])
    return path


def append_history(results: list[dict], output_prefix: str):
    """Append one summary row per band to ~/.antenna_log.csv."""
    write_header = not os.path.exists(HISTORY_LOG)
    with open(HISTORY_LOG, "a", newline="") as f:
        w = csv_module.writer(f)
        if write_header:
            w.writerow(["timestamp", "prefix", "band",
                        "best_freq_mhz", "best_vswr", "best_rl_db",
                        "bw_2to1_khz", "narrow_freq_mhz", "narrow_vswr", "assessment"])
        ts = datetime.now().isoformat()
        for r in results:
            bw_khz = f"{r['bw_2to1_hz']/1000:.1f}" if r["bw_2to1_hz"] > 0 else ""
            nf = f"{r['narrow_freq']/1e6:.6f}" if r.get("narrow_freq") else ""
            nv = f"{r['narrow_vswr']:.4f}"      if r.get("narrow_vswr") else ""
            w.writerow([ts, output_prefix, r["name"],
                        f"{r['best_freq']/1e6:.6f}",
                        f"{r['best_vswr']:.4f}",
                        f"{r['best_rl']:.2f}",
                        bw_khz, nf, nv,
                        _assessment(r["best_vswr"])])


# ---------------------------------------------------------------------------
# Measurement logic
# ---------------------------------------------------------------------------

class AntennaAnalyzer:
    def __init__(self, ssa: SSA3000X, points: int = DEFAULT_POINTS):
        self.ssa    = ssa
        self.points = points
        self._cal: dict[str, np.ndarray] = {}

    def calibrate(self, bands: list[tuple[int, int, str]]):
        """Sweep all bands with open-circuit load to establish RL reference."""
        print("\n[CALIBRATION] Sweeping with open circuit:")
        for start_hz, stop_hz, name in bands:
            rbw = self.ssa.setup_band(start_hz, stop_hz, self.points)
            print(f"  {name:<8}  RBW={rbw/1000:.0f} kHz ...", end=" ", flush=True)
            ok    = self.ssa.single_sweep()
            trace = self.ssa.get_trace()
            self._cal[name] = trace
            peak  = np.max(trace)
            print(f"done ({len(trace)} pts, peak={peak:.1f} dBm)"
                  + (" [WARN: *OPC timeout]" if not ok else ""))

    def load_cal_data(self, cal_data: dict[str, np.ndarray]):
        self._cal.update(cal_data)

    def _averaged_sweep(self, n: int) -> tuple[bool, np.ndarray]:
        """Run n sweeps, return (all_opc_ok, mean_trace)."""
        traces = []
        ok     = True
        for _ in range(n):
            this_ok = self.ssa.single_sweep()
            ok      = ok and this_ok
            traces.append(self.ssa.get_trace())
        return ok, np.mean(np.stack(traces), axis=0)

    def _rl_and_vswr(self, name: str, start_hz: int, stop_hz: int,
                     trace: np.ndarray,
                     cal_override: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Compute return-loss and VSWR arrays from a raw trace.

        cal_override lets a narrow-sweep caller supply an interpolated cal slice.
        """
        cal_src = cal_override if cal_override is not None else self._cal.get(name)
        if cal_src is not None:
            cal = cal_src
            if len(cal) != len(trace):
                cal = np.interp(np.linspace(0, 1, len(trace)),
                                np.linspace(0, 1, len(cal)), cal)
            rl_db = cal - trace
        else:
            rl_db = -trace
        vswr = np.clip(rl_to_vswr_v(rl_db), 1.0, 99.9)
        return rl_db, vswr

    def measure_band(self, start_hz: int, stop_hz: int, name: str,
                     averages: int = 1, narrow: bool = True) -> dict:
        rbw       = self.ssa.setup_band(start_hz, stop_hz, self.points)
        avg_label = f" ×{averages}" if averages > 1 else ""
        print(f"  {name:<8}  RBW={rbw/1000:.0f} kHz{avg_label} ...", end=" ", flush=True)
        ok, trace = self._averaged_sweep(averages)

        freqs         = np.linspace(start_hz, stop_hz, len(trace))
        rl_db, vswr   = self._rl_and_vswr(name, start_hz, stop_hz, trace)
        best_idx      = int(np.argmin(vswr))

        result: dict = dict(
            name       = name,
            start_hz   = start_hz,
            stop_hz    = stop_hz,
            freqs      = freqs,
            trace_dbm  = trace,
            rl_db      = rl_db,
            vswr       = vswr,
            best_idx   = best_idx,
            best_freq  = freqs[best_idx],
            best_vswr  = float(vswr[best_idx]),
            best_rl    = float(rl_db[best_idx]),
            calibrated = (name in self._cal),
            rbw        = rbw,
            opc_ok     = ok,
            narrow_freq = None,
            narrow_vswr = None,
            narrow_rl   = None,
        )

        lo, hi = self._swr_bandwidth(freqs, vswr, best_idx, threshold=2.0)
        result["bw_2to1_lo"] = lo
        result["bw_2to1_hi"] = hi
        result["bw_2to1_hz"] = float(hi - lo) if lo is not None else 0.0

        print(f"done  VSWR_min={result['best_vswr']:.2f}:1 "
              f"@ {result['best_freq']/1e6:.4f} MHz"
              + (" [WARN: *OPC timeout]" if not ok else ""))

        # Precision narrowing sweep — zoom in around the resonant point
        if narrow and result["best_vswr"] < 3.0:
            span = stop_hz - start_hz
            if result["bw_2to1_hz"] > 0:
                margin  = result["bw_2to1_hz"] * 0.20
                n_start = max(start_hz, result["bw_2to1_lo"] - margin)
                n_stop  = min(stop_hz,  result["bw_2to1_hi"] + margin)
            else:
                margin  = span * 0.05
                n_start = max(start_hz, result["best_freq"] - margin)
                n_stop  = min(stop_hz,  result["best_freq"] + margin)

            # Only bother if we achieve at least 25% zoom (window < 75% of span)
            if (n_stop - n_start) < span * 0.75:
                self.ssa.setup_band(int(n_start), int(n_stop), self.points)
                self.ssa.single_sweep()
                n_trace  = self.ssa.get_trace()
                n_freqs  = np.linspace(n_start, n_stop, len(n_trace))

                # Interpolate cal from the original full-band trace
                n_cal = None
                if name in self._cal:
                    cal_src   = self._cal[name]
                    cal_freqs = np.linspace(start_hz, stop_hz, len(cal_src))
                    n_cal     = np.interp(n_freqs, cal_freqs, cal_src)

                n_rl, n_vswr = self._rl_and_vswr(name, int(n_start), int(n_stop),
                                                  n_trace, cal_override=n_cal)
                n_best = int(np.argmin(n_vswr))
                result["narrow_freq"] = float(n_freqs[n_best])
                result["narrow_vswr"] = float(n_vswr[n_best])
                result["narrow_rl"]   = float(n_rl[n_best])
                print(f"  {'':8}  narrow → VSWR {n_vswr[n_best]:.3f}:1 "
                      f"@ {n_freqs[n_best]/1e6:.6f} MHz")

        return result

    @staticmethod
    def _swr_bandwidth(freqs, vswr, center_idx, threshold=2.0):
        """Contiguous frequency range around center_idx where vswr < threshold."""
        if vswr[center_idx] >= threshold:
            return None, None
        lo = center_idx
        while lo > 0 and vswr[lo - 1] < threshold:
            lo -= 1
        hi = center_idx
        while hi < len(vswr) - 1 and vswr[hi + 1] < threshold:
            hi += 1
        return freqs[lo], freqs[hi]


# ---------------------------------------------------------------------------
# Watch / live-retune mode
# ---------------------------------------------------------------------------

def run_watch(analyzer: AntennaAnalyzer, band: tuple[int, int, str],
              max_vswr: float | None):
    start_hz, stop_hz, name = band
    print(f"\n[WATCH] {name}  {format_freq(start_hz)} – {format_freq(stop_hz)}")
    print("Ctrl-C to stop.\n")

    hdr = (f"{'Time':>8}  {'#':>4}  {'Band':<8}  {'VSWR':>8}  "
           f"{'Freq':>14}  {'RL':>7}  {'2:1 BW':>10}  Bar (1.0–5.0)        Status")
    print(hdr)
    print("-" * len(hdr))

    n = 0
    while True:
        n += 1
        r    = analyzer.measure_band(start_hz, stop_hz, name, averages=1, narrow=False)
        t    = datetime.now().strftime("%H:%M:%S")
        vswr = r["best_vswr"]

        bar_len = max(0, min(20, round((vswr - 1.0) / 4.0 * 20)))
        bar     = "█" * bar_len + "░" * (20 - bar_len)

        bw     = r["bw_2to1_hz"]
        bw_str = (f"{bw/1e3:.0f} kHz" if 0 < bw < 1e6 else
                  f"{bw/1e6:.2f} MHz"  if bw >= 1e6    else "N/A")

        status = _assessment(vswr)
        if max_vswr is not None:
            status += "  " + ("PASS" if vswr <= max_vswr else "FAIL")

        print(f"{t:>8}  {n:>4}  {name:<8}  {vswr:>6.2f}:1  "
              f"{r['best_freq']/1e6:>12.4f} MHz  "
              f"{r['best_rl']:>5.1f} dB  {bw_str:>10}  [{bar}]  {status}")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def generate_text_report(results: list[dict], calibrated: bool,
                         output_prefix: str,
                         max_vswr: float | None = None) -> str:
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "=" * 78

    lines = [
        sep,
        "  ANTENNA ANALYSIS REPORT",
        f"  Generated  : {ts}",
        f"  Instrument : Siglent SSA 3032X Plus @ {INSTRUMENT_HOST}",
        f"  Calibration: "
        f"{'Open-circuit reference (return loss)' if calibrated else 'None — raw reflected power'}",
    ]
    if max_vswr is not None:
        lines.append(f"  Pass/Fail  : VSWR ≤ {max_vswr:.1f}:1")
    lines += [sep, ""]

    # Summary table
    hdr = (f"{'Band':<8} {'Resonant Freq':>15} {'VSWR':>8} {'Ret.Loss':>10} "
           f"{'2:1 BW':>12}  {'Assessment':<11}")
    if max_vswr is not None:
        hdr += "  P/F"
    lines += [hdr, "-" * len(hdr)]

    for r in results:
        bw     = r["bw_2to1_hz"]
        bw_str = (f"{bw/1e3:.1f} kHz" if 0 < bw < 1e6 else
                  f"{bw/1e6:.2f} MHz"  if bw >= 1e6    else "N/A")
        line = (f"{r['name']:<8} {format_freq(r['best_freq']):>15} "
                f"{r['best_vswr']:>6.2f}:1 {r['best_rl']:>8.1f} dB "
                f"{bw_str:>12}  {_assessment(r['best_vswr']):<11}")
        if max_vswr is not None:
            line += "  " + ("PASS" if r["best_vswr"] <= max_vswr else "FAIL")
        lines.append(line)

    lines += ["", "BAND DETAIL", "-" * 78]

    for r in results:
        v = r["vswr"]
        lines += [
            "",
            f"{r['name']}  ({format_freq(r['start_hz'])} – {format_freq(r['stop_hz'])})",
            f"  Resonant frequency  : {format_freq(r['best_freq'])}",
            f"  VSWR at resonance   : {r['best_vswr']:.2f}:1",
            f"  Return loss         : {r['best_rl']:.1f} dB",
            f"  VSWR at band start  : {v[0]:.2f}:1",
            f"  VSWR at band center : {v[len(v)//2]:.2f}:1",
            f"  VSWR at band end    : {v[-1]:.2f}:1",
        ]
        bw = r["bw_2to1_hz"]
        if bw > 0:
            bw_str = f"{bw/1e3:.1f} kHz" if bw < 1e6 else f"{bw/1e6:.2f} MHz"
            lines.append(f"  2:1 SWR bandwidth   : {bw_str}"
                         f"  ({format_freq(r['bw_2to1_lo'])} – {format_freq(r['bw_2to1_hi'])})")
        else:
            lines.append("  2:1 SWR bandwidth   : N/A (VSWR never below 2:1)")
        if r.get("narrow_freq") is not None:
            lines.append(
                f"  Resonance (narrow)  : {format_freq(r['narrow_freq'])}"
                f"  VSWR {r['narrow_vswr']:.3f}:1  RL {r['narrow_rl']:.1f} dB")
        lines.append(f"  Assessment          : {_assessment(r['best_vswr'])}")
        if max_vswr is not None:
            lines.append(f"  Pass/Fail           : "
                         f"{'PASS' if r['best_vswr'] <= max_vswr else 'FAIL'}")
        if not r["calibrated"]:
            lines.append("  NOTE: no calibration — VSWR values are estimates only")

    text = "\n".join(lines) + "\n"
    path = f"{output_prefix}.txt"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# Plot generation
# ---------------------------------------------------------------------------

def generate_plot(results: list[dict], calibrated: bool, output_prefix: str,
                  compare_results: list[dict] | None = None,
                  max_vswr: float | None = None) -> str:
    n     = len(results)
    ncols = min(3, n)
    nrows = math.ceil(n / ncols)

    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 4 * nrows))
    cal_label = ("Calibrated (open-circuit reference)"
                 if calibrated else "Uncalibrated — raw power levels")
    fig.suptitle(
        f"Antenna Analysis — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{cal_label}",
        fontsize=12,
    )

    ax_list  = np.array(axes).flatten() if n > 1 else [axes]
    cmp_map  = {cr["name"]: cr for cr in (compare_results or [])}

    for i, r in enumerate(results):
        ax        = ax_list[i]
        freqs_mhz = r["freqs"] / 1e6
        ymax      = 5.0 if np.max(r["vswr"]) > 3.0 else 3.0
        vp        = np.clip(r["vswr"], 1.0, ymax)

        # Three-zone fill: green ≤1.5, gold 1.5–2.0
        ax.fill_between(freqs_mhz, 1.0, np.clip(vp, 1.0, 1.5),
                        alpha=0.30, color="green", label="_nolegend_")
        ax.fill_between(freqs_mhz, 1.5, np.clip(vp, 1.5, 2.0),
                        alpha=0.30, color="gold",  label="_nolegend_")

        # Comparison trace (gray dashed)
        if r["name"] in cmp_map:
            cr     = cmp_map[r["name"]]
            cf_mhz = np.array(cr["freqs"]) / 1e6
            cv     = np.clip(np.array(cr["vswr"]), 1.0, ymax)
            ax.plot(cf_mhz, cv, color="gray", linewidth=1.2,
                    linestyle="--", alpha=0.65, label="Reference")

        ax.plot(freqs_mhz, vp, color="#1f77b4", linewidth=1.5, label="Measured")
        ax.axhline(2.0, color="darkorange", linestyle="--", linewidth=1.0, label="2:1 SWR")
        ax.axhline(1.5, color="green",      linestyle=":",  linewidth=0.8, label="1.5:1 SWR")

        if max_vswr is not None and 1.0 < max_vswr < ymax:
            ax.axhline(max_vswr, color="red", linestyle="-.", linewidth=1.0,
                       label=f"Limit {max_vswr:.1f}:1")

        # Best-VSWR marker — use narrow result when available
        if r.get("narrow_freq") is not None:
            bv    = min(r["narrow_vswr"], ymax)
            bf    = r["narrow_freq"] / 1e6
            label = f"Min {r['narrow_vswr']:.3f}:1\n@ {bf:.6f} MHz"
        else:
            bv    = min(r["best_vswr"], ymax)
            bf    = r["best_freq"] / 1e6
            label = f"Min {r['best_vswr']:.2f}:1\n@ {bf:.4f} MHz"
        ax.plot(bf, bv, "r*", markersize=12, label=label)

        # Sub-band boundary markers
        for mfreq_hz, mlabel in SUBBAND_MARKERS.get(r["name"], []):
            if r["start_hz"] < mfreq_hz < r["stop_hz"]:
                ax.axvline(mfreq_hz / 1e6, color="purple", linestyle=":",
                           linewidth=0.9, alpha=0.7)
                ax.text(mfreq_hz / 1e6, ymax * 0.97, mlabel,
                        fontsize=6, rotation=90, va="top", ha="right",
                        color="purple", alpha=0.8)

        # Title with pass/fail annotation
        if max_vswr is not None:
            passed = r["best_vswr"] <= max_vswr
            pf_str = "✓ PASS" if passed else "✗ FAIL"
            tc     = "darkgreen" if passed else "red"
            ax.set_title(f"{r['name']}  [{pf_str}]", fontsize=11,
                         fontweight="bold", color=tc)
        else:
            ax.set_title(r["name"], fontsize=11, fontweight="bold")

        ax.set_xlabel("Frequency (MHz)", fontsize=9)
        ax.set_ylabel("VSWR", fontsize=9)
        ax.set_ylim(1.0, ymax)
        ax.set_xlim(freqs_mhz[0], freqs_mhz[-1])
        ax.grid(True, alpha=0.35)
        ax.legend(fontsize=7, loc="upper right")
        ax.tick_params(labelsize=8)

    for j in range(n, len(ax_list)):
        ax_list[j].set_visible(False)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    path = f"{output_prefix}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Antenna Analyzer — Siglent SSA + Reflection Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Calibration:
  By default the program looks for a saved calibration file
  ({DEFAULT_CAL_FILE}) and uses it if present.  If missing it prompts
  you to connect an open circuit, sweeps all bands, and saves the file.

  --calibrate       Force fresh calibration sweep of ALL bands, then measure.
  --calibrate --yes Calibrate only and exit — no measurement (for automation).
  --no-cal          Skip calibration entirely (raw reflected-power data only).
  --cal-file FILE   Use an alternate calibration file path.

Band selection (combinable; default: --hf):
  --hf          160m 80m 60m 40m 30m 20m 17m 15m 12m 10m  (default)
  --cb          11m  (CB: 26.965–27.405 MHz)
  --vhf         6m 2m 1.25m
  --uhf         70cm 33cm 23cm 13cm 2.4ghz
  --frs         FRS (462.5–467.8 MHz)
  --gmrs        GMRS (same sweep as --frs)
  --murs        MURS (151.820–154.600 MHz)
  --aviation    Aviation VHF (108–137 MHz)
  --marine-vhf  Marine VHF (156.0–162.6 MHz)
  --marine-hf   Marine HF (8 ITU bands: 4/6/8/12/16/18/22/25 MHz)
  --all         All bands
  --bands       Explicit list, e.g. --bands 40m 20m frs aviation

Measurement options:
  --watch       Live retune mode: continuously re-sweep (use with --bands BAND)
  --averages N  Average N sweeps per band for noise reduction (default: 1)
  --quick       Use {QUICK_POINTS} sweep points instead of {DEFAULT_POINTS} (faster, less resolution)
  --no-narrow   Skip the precision narrowing sweep around resonance
  --max-vswr X  Add PASS/FAIL column for VSWR ≤ X threshold
  --yes         Skip all interactive prompts (for automation)

Output:
  --output PREFIX   Filename prefix (default: timestamped)
  --csv             Also write per-point CSV (<prefix>.csv)
  --compare FILE    Overlay a previous result JSON on the plot

History is always appended to {HISTORY_LOG}.

Examples:
  python antenna_analyzer.py                        # HF (default)
  python antenna_analyzer.py --all                  # every band
  python antenna_analyzer.py --watch --bands 40m    # live retune on 40m
  python antenna_analyzer.py --calibrate --yes      # unattended calibration
  python antenna_analyzer.py --hf --averages 3      # noise-reduced HF scan
  python antenna_analyzer.py --compare prev.json    # compare to previous run
  python antenna_analyzer.py --max-vswr 2.0 --hf   # pass/fail check
  python antenna_analyzer.py --quick --all          # fast survey of every band
""",
    )

    parser.add_argument("--host",  default=INSTRUMENT_HOST, help="Instrument IP address")
    parser.add_argument("--port",  type=int, default=INSTRUMENT_PORT, help="SCPI TCP port")
    parser.add_argument("--points", type=int, default=DEFAULT_POINTS,
                        help=f"Sweep points per band (default {DEFAULT_POINTS}; overridden by --quick)")
    parser.add_argument("--calibrate", action="store_true",
                        help="Force new calibration sweep of ALL bands")
    parser.add_argument("--no-cal",    action="store_true",
                        help="Skip calibration entirely (overrides --calibrate)")
    parser.add_argument("--cal-file",  default=DEFAULT_CAL_FILE, metavar="FILE",
                        help=f"Calibration file (default: {DEFAULT_CAL_FILE})")

    grp = parser.add_argument_group("band selection (combinable; default: --hf)")
    grp.add_argument("--hf",         action="store_true", help="HF amateur: 160m–10m")
    grp.add_argument("--cb",         action="store_true", help="CB: 11m (26.965–27.405 MHz)")
    grp.add_argument("--vhf",        action="store_true", help="VHF amateur: 6m, 2m, 1.25m")
    grp.add_argument("--uhf",        action="store_true",
                     help="UHF/microwave: 70cm, 33cm, 23cm, 13cm, 2.4ghz")
    grp.add_argument("--frs",        action="store_true", help="FRS (462.5–467.8 MHz)")
    grp.add_argument("--gmrs",       action="store_true", help="GMRS (same sweep as --frs)")
    grp.add_argument("--murs",       action="store_true", help="MURS (151.820–154.600 MHz)")
    grp.add_argument("--aviation",   action="store_true", help="Aviation VHF (108–137 MHz)")
    grp.add_argument("--marine-vhf", action="store_true", help="Marine VHF (156.0–162.6 MHz)")
    grp.add_argument("--marine-hf",  action="store_true", help="Marine HF (8 ITU bands)")
    grp.add_argument("--all",        action="store_true", help="All bands")
    grp.add_argument("--bands", nargs="+", metavar="BAND",
                     help="Explicit band list (overrides group flags)")

    mgrp = parser.add_argument_group("measurement options")
    mgrp.add_argument("--watch",     action="store_true",
                      help="Live retune mode: continuously re-sweep the selected band")
    mgrp.add_argument("--averages",  type=int, default=1, metavar="N",
                      help="Average N sweeps per band (default: 1)")
    mgrp.add_argument("--quick",     action="store_true",
                      help=f"Use {QUICK_POINTS} sweep points for faster, lower-res scans")
    mgrp.add_argument("--no-narrow", action="store_true",
                      help="Skip precision narrowing sweep around resonance")
    mgrp.add_argument("--max-vswr",  type=float, default=None, metavar="X",
                      help="Pass/fail threshold: flag bands with VSWR > X in report and plot")
    mgrp.add_argument("--tg-level",  type=float, default=DEFAULT_TG_LEVEL_DBM, metavar="DBM",
                      help=f"TG output level in dBm (default: {DEFAULT_TG_LEVEL_DBM}; range −20 to 0)")
    mgrp.add_argument("--yes",       action="store_true",
                      help="Skip all interactive prompts (for scripting/automation)")

    ogrp = parser.add_argument_group("output")
    ogrp.add_argument("--output",  default=None,
                      help="Output filename prefix (default: antenna_analysis_YYYYMMDD_HHMMSS)")
    ogrp.add_argument("--csv",     action="store_true",
                      help="Also write per-frequency-point CSV (<prefix>.csv)")
    ogrp.add_argument("--compare", default=None, metavar="FILE",
                      help="Overlay a previous result JSON file on the plot")

    args = parser.parse_args()

    if args.quick:
        args.points = QUICK_POINTS

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"antenna_analysis_{ts}"

    # Resolve band list
    if args.bands:
        bands = []
        for b in args.bands:
            key = b.lower()
            if key not in BAND_MAP:
                print(f"Warning: unknown band '{b}' — skipping.")
                print(f"  Available: {' '.join(x[2] for x in ALL_BANDS)}")
            else:
                bands.append(BAND_MAP[key])
        if not bands:
            print("Error: no valid bands specified.")
            sys.exit(1)
    else:
        any_group = (args.hf or args.cb or args.vhf or args.uhf or args.frs or args.gmrs
                     or args.murs or args.aviation or args.marine_vhf or args.marine_hf
                     or args.all)
        selected: set[str] = set()
        if args.all:
            selected = {b[2] for b in ALL_BANDS}
        else:
            if args.hf       or not any_group: selected |= HF_BAND_NAMES
            if args.cb:                        selected |= CB_BAND_NAMES
            if args.vhf:                       selected |= VHF_BAND_NAMES
            if args.uhf:                       selected |= UHF_BAND_NAMES
            if args.frs or args.gmrs:          selected |= FRS_BAND_NAMES
            if args.murs:                      selected |= MURS_BAND_NAMES
            if args.aviation:                  selected |= AVIATION_BAND_NAMES
            if args.marine_vhf:                selected |= MARINE_BAND_NAMES
            if args.marine_hf:                 selected |= MARINE_HF_BAND_NAMES
        bands = [b for b in ALL_BANDS if b[2] in selected]

    if args.watch and len(bands) > 1:
        print(f"[WATCH] Multiple bands selected — using first: {bands[0][2]}")
        bands = [bands[0]]

    # Load comparison data
    compare_results = None
    if args.compare:
        try:
            compare_results = load_results_json(args.compare)
            print(f"Loaded comparison data: {args.compare} ({len(compare_results)} band(s))")
        except Exception as exc:
            print(f"Warning: could not load comparison file ({exc})")

    def prompt(msg: str):
        """Print msg; wait for Enter unless --yes."""
        print(msg)
        if not args.yes:
            input("Press Enter when ready...")

    ssa = SSA3000X(args.host, args.port)

    try:
        ssa.connect()
        idn = ssa.identify()
        print(f"Instrument: {idn}")
        if "SSA" not in idn.upper() and "SIGLENT" not in idn.upper():
            print("WARNING: IDN doesn't look like a Siglent SSA — continuing anyway.")

        print(f"Enabling reflection mode (TG ON, {args.tg_level:+.0f} dBm) ...")
        tg_ok = ssa.enable_tracking_generator(args.tg_level)
        if tg_ok:
            print(f"  TG confirmed ON (level {args.tg_level:+.0f} dBm)")
        else:
            print("  WARNING: TG state query returned unexpected value — check front panel.")

        analyzer = AntennaAnalyzer(ssa, args.points)

        # --- Calibration ---
        calibrated = False
        if args.no_cal:
            print("Calibration skipped (--no-cal).")
        elif args.calibrate:
            prompt("\nConnect an OPEN circuit to the DUT port of the reflection bridge.")
            analyzer.calibrate(ALL_BANDS)
            save_calibration(args.cal_file, analyzer._cal, args.host, args.points)
            calibrated = True
            if args.yes:
                print("Calibration complete (--yes mode: exiting without measurement).")
                sys.exit(0)
        else:
            try:
                cal_data, meta = load_calibration(args.cal_file)
                stored   = set(meta.get("bands", cal_data.keys()))
                requested = {name for _, _, name in bands}
                missing  = requested - stored
                print(f"Loaded calibration from {args.cal_file}")
                print(f"  Taken : {meta.get('timestamp', 'unknown')}  "
                      f"Host: {meta.get('host', 'unknown')}")
                print(f"  Bands : {', '.join(sorted(stored))}")
                if missing:
                    print(f"  WARNING: bands not in cal file: {', '.join(sorted(missing))}")
                    print("  Those bands will use raw power levels. Run --calibrate to update.")
                analyzer.load_cal_data(cal_data)
                calibrated = True
            except FileNotFoundError:
                print(f"No calibration file at {args.cal_file}.")
                prompt("Connect an OPEN circuit to the DUT port of the reflection bridge.")
                analyzer.calibrate(ALL_BANDS)
                save_calibration(args.cal_file, analyzer._cal, args.host, args.points)
                calibrated = True

        # --- Watch mode ---
        if args.watch:
            run_watch(analyzer, bands[0], args.max_vswr)
            return  # only exits via KeyboardInterrupt below

        # --- Measurement ---
        print("\n[MEASUREMENT]")
        prompt("Connect the ANTENNA to the DUT port of the reflection bridge.")

        do_narrow = not args.no_narrow and not args.quick
        desc_parts = [f"{len(bands)} band(s)"]
        if args.averages > 1:
            desc_parts.append(f"×{args.averages} averages")
        if do_narrow:
            desc_parts.append("narrow: on")
        print(f"Sweeping {', '.join(desc_parts)}:")

        results = []
        for start_hz, stop_hz, name in bands:
            r = analyzer.measure_band(start_hz, stop_hz, name,
                                      averages=args.averages,
                                      narrow=do_narrow)
            results.append(r)

        # --- Report & export ---
        print("\n[REPORT]")
        txt_path  = generate_text_report(results, calibrated, args.output, args.max_vswr)
        json_path = save_results_json(results, args.output, calibrated, args.host)
        append_history(results, args.output)

        if args.csv:
            csv_path = save_csv(results, args.output)
            print(f"CSV    → {csv_path}")

        try:
            png_path = generate_plot(results, calibrated, args.output,
                                     compare_results, args.max_vswr)
            print(f"Plot   → {png_path}")
        except Exception as exc:
            print(f"Plot generation failed ({exc}) — text report still saved.")

        print(f"Report → {txt_path}")
        print(f"JSON   → {json_path}")
        print(f"Log    → {HISTORY_LOG}")
        print()

        with open(txt_path) as fh:
            print(fh.read())

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError:
        print(f"\nCannot connect to {args.host}:{args.port}")
        print("Verify the instrument is powered on and SCPI/LAN is enabled.")
        sys.exit(1)
    except OSError as exc:
        print(f"\nNetwork error: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        ssa.disable_tracking_generator()
        ssa.disconnect()


if __name__ == "__main__":
    main()
