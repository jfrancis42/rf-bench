#!/usr/bin/env python3
"""
Crystal Extractor — Siglent SDS2000X Plus (scope + AWG) or SDG1000X + SDS2000X Plus

Extracts the Butterworth-Van Dyke (BVD) equivalent circuit parameters of a quartz
crystal:
  Rs  — motional (series) resistance — ESR of the crystal at resonance
  Ls  — motional inductance
  Cs  — motional capacitance
  Cp  — parallel plate capacitance (static)
  fs  — series resonance frequency (|Z| minimum)
  fp  — parallel resonance frequency (|Z| maximum)
  Q   — Q factor at series resonance

Circuit (series injection topology):
  Source ──── R_ref (50 Ω) ──── Crystal ──── GND
        CH1 ↑             CH2 ↑

CH1 measures the voltage on the source side of R_ref.
CH2 measures the voltage on the crystal terminal (= V across crystal).
Z = R_ref × V_CH2 / (V_CH1 − V_CH2)   (complex, at each frequency)

Source options:
  --source awg   Scope built-in AWG. Phase-coherent. Max 25 MHz.
                 Default — covers all HF ham band crystals (1.8–21 MHz).
  --source sdg   SDG1000X. Up to 60 MHz. Needed for:
                   - 10 m crystals (~28 MHz)
                   - 40 MHz IF filter crystals
                   - 45 MHz IF crystals

Usage:
  python crystal_extractor.py --freq-khz 7000         # 40 m crystal
  python crystal_extractor.py --freq-khz 14318 --span-khz 30
  python crystal_extractor.py --freq-khz 28000 --source sdg
  python crystal_extractor.py --freq-khz 7000 --batch  # measure a batch
"""

import argparse
import cmath
import json
import math
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Shared drivers
# ---------------------------------------------------------------------------


from rf_bench.siglent import SDG1000X, SDS2000X                 # noqa: E402
from rf_bench.utils import (                                      # noqa: E402
    complex_impedance_series,
    format_freq, format_freq_short, dbm_to_vpp, vpp_to_dbm,
)
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SDG_HOST          = "10.1.1.55"
SCOPE_HOST        = "10.1.1.58"
DEFAULT_POINTS    = 200
DEFAULT_LEVEL_VPP = 0.1          # 100 mVpp — keep crystal excitation small
DEFAULT_SPAN_KHZ  = 20.0
DEFAULT_ZREF_OHM  = 50.0
AWG_MAX_FREQ_HZ   = 25_000_000
SDG_MAX_FREQ_HZ   = 60_000_000


# ---------------------------------------------------------------------------
# Capture duration
# ---------------------------------------------------------------------------

def capture_duration(freq_hz: float, min_cycles: int = 5,
                     max_s: float = 0.5) -> float:
    """Return a capture duration that gives at least min_cycles at freq_hz."""
    t = max(0.005, min_cycles / freq_hz)
    return min(t, max_s)


# ---------------------------------------------------------------------------
# Impedance sweep
# ---------------------------------------------------------------------------

def run_impedance_sweep(
    scope: SDS2000X,
    sdg,                    # SDG1000X | None
    freqs_hz: np.ndarray,
    level_vpp: float,
    z_ref_ohm: float,
    source: str,
) -> np.ndarray:
    """
    Sweep freqs_hz, return an array of complex Z values (ohms).

    Skipped points are represented by NaN (as complex(nan, nan)).
    """
    z_arr = np.full(len(freqs_hz), complex(float("nan"), float("nan")))
    total = len(freqs_hz)

    for i, f in enumerate(freqs_hz):
        # Set source
        if source == "awg":
            scope.set_awg_sine(freq_hz=f, amplitude_vpp=level_vpp)
        else:
            level_dbm = vpp_to_dbm(level_vpp)
            sdg.set_sine(1, freq_hz=f, level_dbm=level_dbm)

        # Let source settle (short — crystal measurements are fast)
        time.sleep(0.02)

        dur = capture_duration(f)
        try:
            ch1_v, sr = scope.capture_audio(channel=1, duration_s=dur)
            ch2_v, _  = scope.capture_audio(channel=2, duration_s=dur)
        except RuntimeError as exc:
            print(f"  [{i+1:3d}/{total}] {format_freq_short(f):>10}  SKIP ({exc})")
            continue

        Z = complex_impedance_series(ch1_v, ch2_v, sr,
                                     z_ref_ohm=z_ref_ohm, freq_hz=f)
        z_mag = abs(Z)
        z_phase = math.degrees(cmath.phase(Z))

        print(f"  [{i+1:3d}/{total}] {format_freq_short(f):>10}  "
              f"|Z|={z_mag:8.1f} Ω  ∠={z_phase:+7.1f}°")

        z_arr[i] = Z

    return z_arr


# ---------------------------------------------------------------------------
# BVD parameter extraction
# ---------------------------------------------------------------------------

def extract_bvd(freqs_hz: np.ndarray,
                z_arr: np.ndarray) -> dict | None:
    """
    Extract Butterworth-Van Dyke parameters from an impedance sweep.

    Assumes ideal BVD model:  Ls + Cs + Rs in series, all in parallel with Cp.

    Returns a dict with keys:
      fs_hz, fp_hz, Rs_ohm, Ls_h, Cs_f, Cp_f, Q
    or None if extraction fails.

    Method:
      fs = frequency of |Z| minimum  (series resonance → Z = Rs)
      fp = frequency of |Z| maximum  (parallel resonance)
      Rs = Re(Z) at fs  (or |Z_min| as fallback)
      Q  = fs / (2 × bandwidth at Rs√2)   (from 3 dB bandwidth of |Z| near fs)
      Ls = Rs / (2π·fs / Q)
      Cs = 1 / ((2π·fs)² · Ls)
      Cp ≈ Cs·(fs/fp)² / (1 − (fs/fp)²)   (first-order approximation)
    """
    # Strip NaN
    valid = ~np.isnan(z_arr.real)
    if np.sum(valid) < 5:
        return None

    fv = freqs_hz[valid]
    zv = z_arr[valid]
    mag = np.abs(zv)

    # Series resonance: |Z| minimum
    idx_s = int(np.argmin(mag))
    fs_hz = float(fv[idx_s])
    Rs    = float(np.real(zv[idx_s]))
    if Rs <= 0:
        Rs = float(mag[idx_s])   # fallback: use |Z_min|

    # Parallel resonance: |Z| maximum
    idx_p = int(np.argmax(mag))
    fp_hz = float(fv[idx_p])

    # Q from 3 dB bandwidth around series resonance
    # 3 dB level: |Z| = Rs * sqrt(2)
    z3db = Rs * math.sqrt(2.0)
    # Find lower and upper crossing of z3db around idx_s
    lo_hz = None
    hi_hz = None
    for j in range(idx_s, 0, -1):
        if mag[j - 1] > z3db:
            # Linear interpolation
            lo_hz = float(fv[j - 1]) + (float(fv[j]) - float(fv[j - 1])) * \
                    (z3db - mag[j - 1]) / (mag[j] - mag[j - 1])
            break
    for j in range(idx_s, len(mag) - 1):
        if mag[j + 1] > z3db:
            hi_hz = float(fv[j]) + (float(fv[j + 1]) - float(fv[j])) * \
                    (z3db - mag[j]) / (mag[j + 1] - mag[j])
            break

    if lo_hz is not None and hi_hz is not None and hi_hz > lo_hz:
        Q = fs_hz / (hi_hz - lo_hz)
    else:
        # Fallback Q estimate from crystal series / parallel resonance spacing
        # For a typical crystal: Q ≈ fs / (2*(fp-fs)) is reasonable order of magnitude
        if fp_hz > fs_hz:
            Q = fs_hz / (2.0 * (fp_hz - fs_hz))
        else:
            Q = 10_000.0   # safe placeholder

    # Derived BVD parameters
    omega_s = 2.0 * math.pi * fs_hz
    Ls = Rs * Q / omega_s           # Ls = Q / (ω_s / Rs) = Rs·Q / ω_s
    Cs = 1.0 / (omega_s ** 2 * Ls)

    # Cp from series/parallel resonance relationship: fp ≈ fs·√(1 + Cs/Cp)
    # → Cp ≈ Cs / ((fp/fs)² − 1)
    if fp_hz > fs_hz:
        ratio = (fp_hz / fs_hz) ** 2
        Cp = Cs / (ratio - 1.0)
    else:
        Cp = Cs * 0.01   # pathological case: fp not found or below fs

    return {
        "fs_hz":  fs_hz,
        "fp_hz":  fp_hz,
        "Rs_ohm": Rs,
        "Ls_h":   Ls,
        "Cs_f":   Cs,
        "Cp_f":   Cp,
        "Q":      Q,
    }


# ---------------------------------------------------------------------------
# Terminal display
# ---------------------------------------------------------------------------

def print_bvd(params: dict, label: str = "") -> None:
    hdr = f"  BVD Parameters{' — ' + label if label else ''}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    print(f"  fs  (series resonance)   : {format_freq(params['fs_hz'])}"
          f"  ({params['fs_hz']:.1f} Hz)")
    print(f"  fp  (parallel resonance) : {format_freq(params['fp_hz'])}"
          f"  ({params['fp_hz']:.1f} Hz)")
    print(f"  Rs  (ESR)                : {params['Rs_ohm']:.2f} Ω")
    print(f"  Ls  (motional L)         : {params['Ls_h']*1e6:.4f} µH")
    print(f"  Cs  (motional C)         : {params['Cs_f']*1e15:.4f} fF")
    print(f"  Cp  (parallel C)         : {params['Cp_f']*1e12:.4f} pF")
    print(f"  Q                        : {params['Q']:.0f}")
    print()


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_json(params: dict | None, freqs_hz: np.ndarray,
               z_arr: np.ndarray, level_vpp: float,
               z_ref_ohm: float, source: str, prefix: str) -> str:
    path = f"{prefix}_crystal.json"
    data = {
        "timestamp":  datetime.now().isoformat(),
        "source":     source.upper(),
        "level_vpp":  level_vpp,
        "z_ref_ohm":  z_ref_ohm,
        "bvd":        params,
        "sweep": {
            "freq_hz":    freqs_hz.tolist(),
            "z_real_ohm": z_arr.real.tolist(),
            "z_imag_ohm": z_arr.imag.tolist(),
            "z_mag_ohm":  np.abs(z_arr).tolist(),
            "z_phase_deg": [math.degrees(cmath.phase(z)) if not math.isnan(z.real)
                            else float("nan") for z in z_arr],
        },
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def generate_plot(freqs_hz: np.ndarray, z_arr: np.ndarray,
                  params: dict | None, freq_khz: float,
                  prefix: str) -> str:
    valid = ~np.isnan(z_arr.real)
    fv    = freqs_hz[valid]
    zv    = z_arr[valid]
    mag   = np.abs(zv)
    phase = np.array([math.degrees(cmath.phase(z)) for z in zv])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig.suptitle(
        f"Crystal Impedance — {ts}\n"
        f"Nominal {format_freq_short(freq_khz * 1000)}  |  "
        f"{format_freq_short(float(freqs_hz[0]))} – {format_freq_short(float(freqs_hz[-1]))}",
        fontsize=11,
    )

    # Impedance magnitude panel (log Y)
    ax1.semilogy(fv / 1e3, mag, color="#1f77b4", linewidth=1.8)
    if params is not None:
        ax1.axvline(params["fs_hz"] / 1e3, color="green", linestyle="--",
                    linewidth=1.0, label=f"fs = {format_freq_short(params['fs_hz'])}")
        ax1.axvline(params["fp_hz"] / 1e3, color="red", linestyle="--",
                    linewidth=1.0, label=f"fp = {format_freq_short(params['fp_hz'])}")
        ax1.axhline(params["Rs_ohm"], color="orange", linestyle=":",
                    linewidth=0.9, label=f"Rs = {params['Rs_ohm']:.1f} Ω")

    ax1.set_ylabel("|Z| (Ω)", fontsize=10)
    ax1.grid(True, which="both", alpha=0.30)
    ax1.legend(fontsize=8, loc="best")
    ax1.tick_params(labelsize=9)

    # Phase panel
    ax2.plot(fv / 1e3, phase, color="#d62728", linewidth=1.8)
    ax2.axhline(0.0, color="gray", linestyle="--", linewidth=0.8)
    if params is not None:
        ax2.axvline(params["fs_hz"] / 1e3, color="green", linestyle="--",
                    linewidth=1.0)
        ax2.axvline(params["fp_hz"] / 1e3, color="red", linestyle="--",
                    linewidth=1.0)

    ax2.set_ylabel("Phase (°)", fontsize=10)
    ax2.set_xlabel("Frequency (kHz)", fontsize=10)
    ax2.set_ylim(-90, 90)
    ax2.set_yticks([-90, -45, 0, 45, 90])
    ax2.grid(True, which="both", alpha=0.30)
    ax2.tick_params(labelsize=9)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    path = f"{prefix}_crystal.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Single-crystal measurement
# ---------------------------------------------------------------------------

def measure_crystal(
    scope: SDS2000X,
    sdg,
    freq_khz: float,
    span_khz: float,
    points: int,
    level_vpp: float,
    z_ref_ohm: float,
    source: str,
    prefix: str,
) -> dict | None:
    """
    Measure one crystal. Returns the BVD params dict or None on failure.
    Writes <prefix>_crystal.{png,json}.
    """
    f_center = freq_khz * 1000.0
    f_start  = f_center - (span_khz / 2.0) * 1000.0
    f_stop   = f_center + (span_khz / 2.0) * 1000.0
    freqs_hz = np.linspace(f_start, f_stop, points)

    print(f"\n  Sweep: {format_freq(f_start)} – {format_freq(f_stop)}  "
          f"({points} pts, {span_khz:.1f} kHz span)")
    print(f"  Drive: {level_vpp * 1000:.0f} mVpp  |  "
          f"Z_ref: {z_ref_ohm:.0f} Ω\n")

    z_arr = run_impedance_sweep(scope, sdg, freqs_hz, level_vpp,
                                z_ref_ohm, source)

    params = extract_bvd(freqs_hz, z_arr)

    print()
    if params is not None:
        print_bvd(params)
    else:
        print("  WARNING: BVD extraction failed — no valid data points.")

    json_path = write_json(params, freqs_hz, z_arr, level_vpp,
                           z_ref_ohm, source, prefix)
    print(f"  JSON → {json_path}")

    try:
        png_path = generate_plot(freqs_hz, z_arr, params, freq_khz, prefix)
        print(f"  Plot → {png_path}")
    except Exception as exc:
        print(f"  Plot generation failed: {exc}")

    return params


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def run_batch(
    scope: SDS2000X,
    sdg,
    freq_khz: float,
    span_khz: float,
    points: int,
    level_vpp: float,
    z_ref_ohm: float,
    source: str,
    batch_dir: str,
) -> None:
    os.makedirs(batch_dir, exist_ok=True)
    crystal_num = 0
    results     = []   # list of (num, params)

    print(f"\n[BATCH MODE]  Results → {batch_dir}/")
    print("Press Ctrl-C to finish and print summary.\n")

    while True:
        crystal_num += 1
        label  = f"crystal_{crystal_num:03d}"
        prefix = os.path.join(batch_dir, label)

        print(f"─── Crystal #{crystal_num} ──────────────────────────────────────")
        try:
            input("  Insert crystal and press Enter to measure "
                  "(Ctrl-C to finish batch) ...")
        except KeyboardInterrupt:
            print("\n\nBatch complete.")
            crystal_num -= 1  # last crystal wasn't measured
            break

        params = measure_crystal(
            scope=scope, sdg=sdg, freq_khz=freq_khz, span_khz=span_khz,
            points=points, level_vpp=level_vpp, z_ref_ohm=z_ref_ohm,
            source=source, prefix=prefix,
        )

        if params is not None:
            results.append((crystal_num, params))

    if not results:
        print("No crystals measured.")
        return

    # Write batch summary JSON
    summary_path = os.path.join(batch_dir, "batch_summary.json")
    sorted_results = sorted(results, key=lambda x: x[1]["fs_hz"])
    summary = {
        "timestamp":    datetime.now().isoformat(),
        "freq_khz":     freq_khz,
        "count":        len(results),
        "crystals":     [{"number": n, "bvd": p} for n, p in sorted_results],
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Print sorted table
    print("\n" + "=" * 72)
    print("  BATCH SUMMARY — sorted by fs")
    print("=" * 72)
    hdr = (f"  {'#':>3}  {'Crystal':>10}  {'fs (Hz)':>14}  {'fp (Hz)':>14}  "
           f"{'Q':>7}  {'Rs (Ω)':>8}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    for n, p in sorted_results:
        print(f"  {n:>3}  crystal_{n:03d}  "
              f"{p['fs_hz']:>14.1f}  {p['fp_hz']:>14.1f}  "
              f"{p['Q']:>7.0f}  {p['Rs_ohm']:>8.2f}")

    # Spread statistics
    fs_values = [p["fs_hz"] for _, p in sorted_results]
    if len(fs_values) > 1:
        spread_hz = max(fs_values) - min(fs_values)
        print(f"\n  fs spread: {spread_hz:.1f} Hz  "
              f"(min {min(fs_values):.1f}  max {max(fs_values):.1f})")
        # Matched sets: within ±5 Hz
        ref = fs_values[0]
        matched = [(n, p) for n, p in sorted_results
                   if abs(p["fs_hz"] - ref) <= 5.0]
        if len(matched) > 1:
            print(f"  Crystals within ±5 Hz of lowest: "
                  + ", ".join(f"#{n}" for n, _ in matched))

    print(f"\n  Batch summary → {summary_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Crystal Extractor — Butterworth-Van Dyke parameter measurement",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Circuit:
  Source ──── R_ref (50 Ω) ──── Crystal ──── GND
        CH1 ↑             CH2 ↑

You must physically install R_ref (default 50 Ω) in series with the crystal.
CH1 and CH2 connect on either side of R_ref.

Examples:
  python crystal_extractor.py --freq-khz 7000              # 40 m crystal, AWG
  python crystal_extractor.py --freq-khz 14318 --span-khz 30
  python crystal_extractor.py --freq-khz 28000 --source sdg
  python crystal_extractor.py --freq-khz 7000 --batch      # batch mode
  python crystal_extractor.py --freq-khz 4000 --batch --batch-output 4mhz_batch
""",
    )

    parser.add_argument("--freq-khz", type=float, required=True, metavar="KHZ",
                        help="Nominal crystal frequency in kHz (required)")

    src_grp = parser.add_argument_group("source")
    src_grp.add_argument("--source", choices=["awg", "sdg"], default="awg",
                         help="Signal source: awg (≤25 MHz) or sdg (≤60 MHz) "
                              "[default: awg]")
    src_grp.add_argument("--sdg-host", default=SDG_HOST, metavar="HOST",
                         help=f"SDG1000X IP [default: {SDG_HOST}]")
    src_grp.add_argument("--scope-host", default=SCOPE_HOST, metavar="HOST",
                         help=f"SDS2000X IP [default: {SCOPE_HOST}]")

    meas_grp = parser.add_argument_group("measurement")
    meas_grp.add_argument("--span-khz", type=float, default=DEFAULT_SPAN_KHZ,
                          metavar="KHZ",
                          help=f"Sweep ±span/2 around nominal freq in kHz "
                               f"[default: {DEFAULT_SPAN_KHZ}]")
    meas_grp.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N",
                          help=f"Sweep points [default: {DEFAULT_POINTS}]")
    meas_grp.add_argument("--zref", type=float, default=DEFAULT_ZREF_OHM,
                          metavar="OHMS",
                          help=f"Reference resistor value in Ω [default: {DEFAULT_ZREF_OHM}]")
    meas_grp.add_argument("--level-vpp", type=float, default=DEFAULT_LEVEL_VPP,
                          metavar="VPP",
                          help=f"Excitation level in Vpp [default: {DEFAULT_LEVEL_VPP}]  "
                               "Keep ≤ 100 mVpp to avoid crystal heating")

    batch_grp = parser.add_argument_group("batch mode")
    batch_grp.add_argument("--batch", action="store_true",
                           help="Batch mode: measure multiple crystals, prompt between each")
    batch_grp.add_argument("--batch-output", default=None, metavar="DIR",
                           help="Directory for batch output files [default: crystal_batch_YYYYMMDD]")

    out_grp = parser.add_argument_group("output")
    out_grp.add_argument("--output", default=None, metavar="PREFIX",
                         help="Output prefix [default: crystal_YYYYMMDD_HHMMSS]")

    args = parser.parse_args()

    # Resolve defaults
    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"crystal_{ts}"

    if args.batch and args.batch_output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.batch_output = f"crystal_batch_{ts}"

    # Validate frequency / source
    f_hz = args.freq_khz * 1000.0
    max_freq = AWG_MAX_FREQ_HZ if args.source == "awg" else SDG_MAX_FREQ_HZ
    if f_hz > max_freq:
        print(f"Error: {format_freq(f_hz)} exceeds {args.source.upper()} "
              f"limit of {max_freq/1e6:.0f} MHz.  Use --source sdg for this crystal.")
        sys.exit(1)

    if args.level_vpp > 0.5:
        print(f"Warning: --level-vpp {args.level_vpp:.3f} Vpp is high. "
              f"Keep ≤ 100 mVpp (0.1 Vpp) to avoid heating the crystal.")

    if args.level_vpp <= 0:
        print("Error: --level-vpp must be positive.")
        sys.exit(1)

    if args.zref <= 0:
        print("Error: --zref must be positive.")
        sys.exit(1)

    # Print setup
    print(f"\n[CRYSTAL EXTRACTOR]")
    print(f"  Crystal   : {format_freq(f_hz)}")
    print(f"  Span      : ±{args.span_khz/2:.1f} kHz  "
          f"({args.span_khz:.1f} kHz total,  {args.points} pts)")
    print(f"  Source    : {args.source.upper()}  "
          f"Drive: {args.level_vpp * 1000:.0f} mVpp")
    print(f"  Z_ref     : {args.zref:.0f} Ω")
    if args.batch:
        print(f"  Mode      : BATCH → {args.batch_output}/")
    else:
        print(f"  Output    : {args.output}_crystal.{{png,json}}")
    print()

    # Connect scope
    print("Connecting to scope ...", end=" ", flush=True)
    try:
        scope = connect(args.scope_host or 'sds')
    except (ConnectionRefusedError, OSError) as exc:
        print(f"\nCannot connect to scope at {args.scope_host}: {exc}")
        sys.exit(1)
    print(f"OK  ({scope.identify().split(',')[1].strip()})")

    sdg = None
    if args.source == "sdg":
        print("Connecting to SDG ...", end=" ", flush=True)
        try:
            sdg = connect(args.sdg_host or 'sdg')
        except (ConnectionRefusedError, OSError) as exc:
            print(f"\nCannot connect to SDG at {args.sdg_host}: {exc}")
            scope.close()
            sys.exit(1)
        print(f"OK  ({sdg.identify().split(',')[1].strip()})")
        sdg.set_sine(1, freq_hz=f_hz, level_dbm=vpp_to_dbm(args.level_vpp))
        sdg.output_on(1)
    else:
        scope.awg_output_on()

    try:
        if args.batch:
            run_batch(
                scope=scope, sdg=sdg,
                freq_khz=args.freq_khz, span_khz=args.span_khz,
                points=args.points, level_vpp=args.level_vpp,
                z_ref_ohm=args.zref, source=args.source,
                batch_dir=args.batch_output,
            )
        else:
            measure_crystal(
                scope=scope, sdg=sdg,
                freq_khz=args.freq_khz, span_khz=args.span_khz,
                points=args.points, level_vpp=args.level_vpp,
                z_ref_ohm=args.zref, source=args.source,
                prefix=args.output,
            )

    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
    finally:
        # Restore safe state
        if args.source == "awg":
            try:
                scope.awg_output_off()
            except Exception:
                pass
        else:
            if sdg is not None:
                try:
                    sdg.output_off_all()
                    sdg.close()
                except Exception:
                    pass
        try:
            scope.run()
            scope.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
