#!/usr/bin/env python3
"""
connector_check.py — Pass/fail return-loss check for a single connector.

Quick sanity-check workflow after every PL-259 crimp, every BNC barrel
purchase, every "wait, is this patch lead actually any good?" Plug it
into VNA port 1, run this script with `--bands hf vhf uhf`, and get
back a one-line PASS / FAIL per ham band plus a short PDF.

Setup
-----
    VNA Port 1 ── [connector / adapter / patch under test] ── 50-Ω LOAD

If the DUT is a single connector (PL-259, BNC, N), a precision 50-Ω
load on the back side gives the connector's reflection. If the DUT is
a complete patch lead, both ends are exercised in the return-loss
result.

OSL-calibrate over the whole sweep range before measuring; otherwise
the readout includes the loss of the cable between port 1 and the DUT.

Threshold
---------
The default pass threshold is **20 dB** (VSWR 1.22:1) — generous for
PL-259 crimps, tight enough to flag a damaged or filthy connector. You
can override per-band: `--threshold 26` for a 1.10:1 spec, or relax to
14 dB on the high VHF/UHF bands where most PL-259 specs allow it.

Output
------
  - Console table: best/worst RL per band, PASS/FAIL
  - JSON file: machine-readable per-band stats
  - PDF chart: |S11| trace with shaded amateur bands and threshold line
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


DEFAULT_VNA      = "nanovna"
DEFAULT_PORT     = "/dev/ttyACM1"
DEFAULT_HP_HOST  = "10.1.1.70"
DEFAULT_POINTS   = 401
DEFAULT_THRESHOLD_DB = 20.0


# Frequency ranges used when --bands is selected. Each entry is
# (key, start_mhz, stop_mhz, label).
BAND_SETS = {
    "hf":    [
        (1.8, 2.0,   "160m"), (3.5, 4.0,   "80m"),  (5.33, 5.41,  "60m"),
        (7.0, 7.3,   "40m"),  (10.10, 10.15, "30m"), (14.0, 14.35, "20m"),
        (18.07, 18.17, "17m"),(21.0, 21.45, "15m"), (24.89, 24.99, "12m"),
        (28.0, 29.7,  "10m"),
    ],
    "6m":    [(50.0,  54.0,  "6m")],
    "vhf":   [(144.0, 148.0, "2m"), (222.0, 225.0, "1.25m")],
    "uhf":   [(420.0, 450.0, "70cm")],
    "23cm":  [(1240.0, 1300.0, "23cm")],
}


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        vna = NanoVNA(port=args.port)
    elif args.vna == "hp":
        from rf_bench.hp import HP8712B
        vna = HP8712B(host=args.host)
    else:
        raise ValueError(f"--vna must be 'nanovna' or 'hp', got {args.vna!r}")
    return vna, vna.identify()


def maybe_set_power(vna, dbm: Optional[float], vna_kind: str) -> None:
    if dbm is None:
        return
    try:
        vna.set_power(float(dbm))
        print(f"  Source power : {dbm:+.1f} dBm")
    except NotImplementedError:
        print(f"  Source power : --power ignored ({vna_kind} has no dBm setpoint)")


def measure_s11(vna, start_hz, stop_hz, points, averaging):
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_parameter("S11")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: single_sweep() returned False — trace may be stale")
    freqs = vna.get_frequencies()
    gamma = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    if len(freqs) != len(gamma):
        raise RuntimeError(
            f"VNA returned mismatched array lengths "
            f"(freqs={len(freqs)}, gamma={len(gamma)})"
        )
    rl_db = -20.0 * np.log10(np.clip(np.abs(gamma), 1e-12, None))
    return freqs, gamma, rl_db


def evaluate_bands(freqs_hz: np.ndarray, rl_db: np.ndarray,
                   bands: list[tuple[float, float, str]],
                   threshold_db: float) -> list[dict]:
    freqs_mhz = freqs_hz / 1e6
    results = []
    for lo, hi, name in bands:
        in_band = (freqs_mhz >= lo) & (freqs_mhz <= hi)
        if not np.any(in_band):
            results.append({
                "band": name, "lo_mhz": lo, "hi_mhz": hi,
                "in_sweep": False, "pass": None,
                "worst_rl_db": None, "best_rl_db": None,
            })
            continue
        seg_rl = rl_db[in_band]
        seg_f = freqs_mhz[in_band]
        i_worst = int(np.argmin(seg_rl))
        i_best  = int(np.argmax(seg_rl))
        worst = float(seg_rl[i_worst])
        best  = float(seg_rl[i_best])
        results.append({
            "band": name, "lo_mhz": lo, "hi_mhz": hi,
            "in_sweep": True,
            "pass": bool(worst >= threshold_db),
            "worst_rl_db": worst,
            "worst_at_mhz": float(seg_f[i_worst]),
            "best_rl_db": best,
            "best_at_mhz": float(seg_f[i_best]),
        })
    return results


def plot_pdf(freqs_hz, rl_db, band_results, threshold_db,
             label, driver_name, idn, output_path):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, ax = plt.subplots(figsize=(11, 7.5))
    ax.plot(freqs_mhz, rl_db, color="#1f77b4", linewidth=1.4,
            label="Return loss")
    ax.axhline(threshold_db, color="red", linestyle="--", linewidth=1.0,
               label=f"Threshold {threshold_db:.0f} dB")

    for r in band_results:
        if not r["in_sweep"]:
            continue
        color = "#2ca02c" if r["pass"] else "#d62728"
        ax.axvspan(r["lo_mhz"], r["hi_mhz"], color=color, alpha=0.12, zorder=0)
        ax.text(
            (r["lo_mhz"] + r["hi_mhz"]) / 2.0, 0.97,
            f"{r['band']}\n{'PASS' if r['pass'] else 'FAIL'}",
            transform=ax.get_xaxis_transform(),
            ha="center", va="top", fontsize=8, color=color,
            fontweight="bold",
        )

    ax.set_xlim(float(freqs_mhz[0]), float(freqs_mhz[-1]))
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Return loss (dB)")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.92)

    title_lines = [
        f"Connector Check — {label}",
        f"{freqs_mhz[0]:.3f} – {freqs_mhz[-1]:.3f} MHz  •  "
        f"{len(freqs_hz)} points  •  threshold {threshold_db:.0f} dB  •  "
        f"{driver_name}  •  {ts}",
    ]
    if idn:
        title_lines.append(idn[:120])
    ax.set_title("\n".join(title_lines), fontsize=10)

    fig.tight_layout()
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Pass/fail return-loss check for a connector or patch lead.",
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, default=None, metavar="MHZ")
    p.add_argument("--stop",  type=float, default=None, metavar="MHZ")
    p.add_argument("--bands", nargs="+", default=None, metavar="SET",
                   choices=sorted(BAND_SETS.keys()),
                   help=f"Pick one or more band sets: "
                        f"{', '.join(sorted(BAND_SETS))}. "
                        "Overrides --start/--stop with the union of the picked "
                        "ranges (padded by 10 percent on each side).")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=2, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_DB,
                   metavar="DB",
                   help=f"Pass threshold in dB return loss "
                        f"(default {DEFAULT_THRESHOLD_DB:g})")
    p.add_argument("--label", default="connector")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    p.add_argument("--json", default=None, metavar="FILE.json",
                   help="Write per-band results to JSON")
    args = p.parse_args()

    # Resolve sweep range from --bands or --start/--stop
    bands_to_check = []
    if args.bands:
        for k in args.bands:
            bands_to_check.extend(BAND_SETS[k])
        lo = min(b[0] for b in bands_to_check)
        hi = max(b[1] for b in bands_to_check)
        # Pad ±10 % so the trace doesn't end abruptly at the band edge
        span = hi - lo
        start_mhz = max(0.05, lo - 0.10 * span)
        stop_mhz  = hi + 0.10 * span
    else:
        if args.start is None or args.stop is None:
            print("Error: either pass --bands or both --start and --stop")
            return 1
        start_mhz = args.start
        stop_mhz  = args.stop
        # Score against every band that falls inside the sweep
        for entries in BAND_SETS.values():
            for lo, hi, name in entries:
                if hi >= start_mhz and lo <= stop_mhz:
                    bands_to_check.append((lo, hi, name))

    if not bands_to_check:
        print("Error: no amateur bands fall inside the sweep range; "
              "use --bands to pick one explicitly.")
        return 1

    if start_mhz <= 0 or stop_mhz <= start_mhz:
        print("Error: bad sweep range")
        return 1
    if args.points < 2 or args.average < 1:
        print("Error: --points must be ≥ 2 and --average must be ≥ 1")
        return 1

    print(f"Connector Check — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {start_mhz:.3f} – {stop_mhz:.3f} MHz, "
          f"{args.points} points, average={args.average}")
    print(f"  Threshold    : {args.threshold:.1f} dB (RL)")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        freqs_hz, gamma, rl_db = measure_s11(
            vna, start_mhz * 1e6, stop_mhz * 1e6,
            args.points, args.average,
        )
        results = evaluate_bands(freqs_hz, rl_db, bands_to_check, args.threshold)

        print()
        print(f"  {'Band':>6}   {'Range (MHz)':>17}   {'Worst RL':>10}   "
              f"{'Best RL':>10}   Verdict")
        print(f"  {'-'*6}   {'-'*17}   {'-'*10}   {'-'*10}   -------")
        any_fail = False
        for r in results:
            if not r["in_sweep"]:
                print(f"  {r['band']:>6}   {r['lo_mhz']:>7.3f}–{r['hi_mhz']:<7.3f}   "
                      f"{'n/a':>10}   {'n/a':>10}   not in sweep")
                continue
            verdict = "PASS" if r["pass"] else "FAIL"
            if not r["pass"]:
                any_fail = True
            print(f"  {r['band']:>6}   "
                  f"{r['lo_mhz']:>7.3f}–{r['hi_mhz']:<7.3f}   "
                  f"{r['worst_rl_db']:>7.1f} dB   "
                  f"{r['best_rl_db']:>7.1f} dB   {verdict}")
        print()
        print(f"  Overall      : {'FAIL' if any_fail else 'PASS'}")

        if args.json:
            payload = {
                "label": args.label,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "threshold_db": args.threshold,
                "sweep_start_mhz": start_mhz,
                "sweep_stop_mhz": stop_mhz,
                "points": args.points,
                "average": args.average,
                "driver": args.vna,
                "idn": idn,
                "bands": results,
                "overall_pass": not any_fail,
            }
            with open(args.json, "w") as fh:
                json.dump(payload, fh, indent=2)
            print(f"  Wrote JSON   → {args.json}")

        plot_pdf(
            freqs_hz, rl_db, results, args.threshold,
            label=args.label,
            driver_name=args.vna.upper(),
            idn=idn,
            output_path=args.output,
        )
        print(f"  Wrote PDF    → {args.output}")
        return 0 if not any_fail else 2

    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        print(f"\nFailed: {exc}", file=sys.stderr)
        return 1
    finally:
        if vna is not None:
            try:
                vna.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
