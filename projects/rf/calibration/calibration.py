#!/usr/bin/env python3
"""
Cross-Instrument Amplitude Calibration — Siglent SDG / SSA / SDS / SDM

Measures each instrument's reading of a known SDG sine signal, builds a
correction table, and maps amplitude flatness vs frequency.

IMPORTANT — RELATIVE CALIBRATION ONLY:
  The SDG1062X is used as the reference source. This script tells you how
  each instrument reads *relative to the SDG's reported level*. It cannot
  tell you whether the SDG itself is accurate in absolute terms. For
  traceable absolute calibration you need an external calibrated reference
  (power meter, calibrated attenuator pad, etc.).

Physical setup:
  SDG CH1 ─── T-splitter ─┬─── scope CH1
                            ├─── SSA RF In
                            └─── DMM Hi (via BNC-banana adapter)

  All instruments see the same signal simultaneously via T-junctions.
  Loading: three 50 Ω loads in parallel = 16.7 Ω effective — the SDG sees
  a ~10 dB loss vs open circuit. The SDG CH1 output level reported by the
  driver (and set via `--level`) is the OPEN-CIRCUIT Vpp. With three 50 Ω
  loads, actual power to each is reduced. Correction offsets in the output
  table account for this implicitly because they compare instrument readings
  to the SDG's nominal set level.

Usage:
  python calibration.py                     # default 10-point log sweep
  python calibration.py --freq-list "1000,10000,100000,1000000"
  python calibration.py --skip-dmm          # skip DMM for RF frequencies
  python calibration.py --level -20
"""

import argparse
import csv
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
# Siglent shared drivers
# ---------------------------------------------------------------------------

from rf_bench.siglent import SSA3000X, SDG1000X, SDS2000X, SDM3000X        # noqa: E402
from rf_bench.utils import (                                                  # noqa: E402
    format_freq, format_freq_short, dbm_to_vpp, vpp_to_dbm, vrms_to_dbm,
    nearest_rbw,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SDG_HOST   = "10.1.1.55"
DEFAULT_SSA_HOST   = "10.1.1.60"
DEFAULT_SCOPE_HOST = "10.1.1.58"
DEFAULT_DMM_HOST   = "10.1.1.63"

DEFAULT_LEVEL_DBM  = -10.0        # dBm
DEFAULT_AVERAGES   = 3
DEFAULT_SCOPE_CH   = 1

# Default frequency list: 10 points log-spaced from 100 Hz to 10 MHz
_LOG_FREQS = [int(round(10 ** x))
              for x in np.linspace(math.log10(100), math.log10(10_000_000), 10)]

# SSA span for single-tone measurement: ±1% of center frequency,
# minimum ±50 kHz
SSA_SPAN_FRAC    = 0.02       # total span = freq * SSA_SPAN_FRAC
SSA_SPAN_MIN_HZ  = 100_000   # minimum total span

# DMM frequency limit: SDM3045X AC voltage accuracy is specified to 100 kHz
# Above this the reading becomes unreliable; warn the user.
DMM_FREQ_LIMIT_HZ = 100_000


# ---------------------------------------------------------------------------
# Single-instrument measurement functions
# ---------------------------------------------------------------------------

def measure_scope_dbm(
    scope: SDS2000X,
    channel: int,
    freq_hz: float,
    duration_s: float = 0.2,
) -> float:
    """
    Measure the RMS voltage of the signal on the scope channel and convert
    to dBm (into 50 Ω).

    Uses capture_audio() for the raw waveform, then computes Vrms from the
    waveform array. This avoids the PAVA firmware inconsistencies at extreme
    V/div settings.

    Args:
        scope:      SDS2000X driver instance
        channel:    Scope channel number (1–4)
        freq_hz:    Signal frequency (Hz) — used to set timebase
        duration_s: Capture duration in seconds (captures ~freq_hz * duration_s
                    cycles). Auto-selected to capture at least 10 cycles.

    Returns:
        Power in dBm (50 Ω).  Returns NaN on failure.
    """
    # Set timebase to capture at least 10 cycles
    min_duration = max(10.0 / freq_hz, 0.05)
    cap_dur      = max(duration_s, min_duration)

    try:
        wave, sr = scope.capture_audio(channel=channel, duration_s=cap_dur)
    except RuntimeError as exc:
        print(f" [scope error: {exc}]", end="")
        return float("nan")

    if len(wave) < 10:
        return float("nan")

    vrms    = float(np.sqrt(np.mean(wave ** 2)))
    if vrms <= 0:
        return float("nan")
    return vrms_to_dbm(vrms)


def measure_ssa_dbm(ssa: SSA3000X, freq_hz: float) -> float:
    """
    Measure peak power at freq_hz on the SSA using a narrow span.

    Sets a span of SSA_SPAN_FRAC × freq_hz (min SSA_SPAN_MIN_HZ),
    triggers a single sweep, and returns the peak of the trace.

    Returns:
        Peak power in dBm. Returns NaN on empty trace.
    """
    span_hz   = max(freq_hz * SSA_SPAN_FRAC, SSA_SPAN_MIN_HZ)
    half_span = span_hz / 2
    start_hz  = max(9_000, int(freq_hz - half_span))
    stop_hz   = int(freq_hz + half_span)

    rbw = ssa.setup_band(start_hz, stop_hz, 201)
    ssa.single_sweep()
    trace = ssa.get_trace()
    if len(trace) == 0:
        return float("nan")
    return float(np.max(trace))


def measure_dmm_dbm(dmm: SDM3000X) -> float:
    """
    Read AC Vrms from the DMM and convert to dBm (50 Ω).

    The SDM3045X measure_vac() returns volts RMS.

    Returns:
        Power in dBm. Returns NaN on measurement error.
    """
    try:
        vrms = dmm.measure_vac()
        if vrms is None or math.isnan(vrms) or vrms <= 0:
            return float("nan")
        return vrms_to_dbm(vrms)
    except Exception as exc:
        print(f" [dmm error: {exc}]", end="")
        return float("nan")


def averaged_measurement(
    measure_fn,
    n: int,
    settle_s: float = 0.1,
) -> float:
    """
    Call measure_fn() n times, pause settle_s between calls, and return the mean.

    NaN readings are excluded from the average. If all readings are NaN,
    returns NaN.
    """
    readings = []
    for _ in range(n):
        val = measure_fn()
        if not math.isnan(val):
            readings.append(val)
        if _ < n - 1:
            time.sleep(settle_s)
    if not readings:
        return float("nan")
    return float(np.mean(readings))


# ---------------------------------------------------------------------------
# Main calibration sweep
# ---------------------------------------------------------------------------

def run_calibration(
    sdg:         SDG1000X,
    ssa:         SSA3000X,
    scope:       SDS2000X,
    dmm:         SDM3000X | None,
    freq_list:   list[int],
    level_dbm:   float,
    averages:    int,
    scope_ch:    int,
    skip_dmm:    bool,
) -> list[dict]:
    """
    For each frequency in freq_list, set the SDG to a sine at that frequency
    and level_dbm, then read all three (or two) measurement instruments.

    Returns a list of dicts, one per frequency point:
        freq_hz, sdg_dbm,
        scope_dbm, ssa_dbm, dmm_dbm,
        scope_offset, ssa_offset, dmm_offset
    """
    print(f"\n[CALIBRATION SWEEP]  Level = {level_dbm:+.1f} dBm  Averages = {averages}")
    print(f"  {len(freq_list)} frequencies: "
          f"{format_freq_short(freq_list[0])} – {format_freq_short(freq_list[-1])}")
    print()

    hdr = (f"  {'Frequency':>12}  {'SDG':>8}  {'Scope':>8}  "
           f"{'SSA':>8}  {'DMM':>8}  "
           f"{'Δscope':>8}  {'ΔSSA':>8}  {'ΔDMM':>8}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    # Configure SDG CH1 for the first frequency; subsequent calls just
    # update frequency/level as needed
    sdg.set_sine(1, freq_list[0], level_dbm)
    sdg.output_on(1)
    time.sleep(0.2)

    results = []
    for freq_hz in freq_list:
        sdg.set_sine(1, freq_hz, level_dbm)
        time.sleep(0.15)   # let SDG settle

        # --- Scope ---
        scope_dbm = averaged_measurement(
            lambda: measure_scope_dbm(scope, scope_ch, freq_hz),
            n         = averages,
            settle_s  = 0.05,
        )

        # --- SSA ---
        ssa_dbm = averaged_measurement(
            lambda: measure_ssa_dbm(ssa, freq_hz),
            n        = averages,
            settle_s = 0.1,
        )

        # --- DMM ---
        if skip_dmm or dmm is None:
            dmm_dbm = float("nan")
        elif freq_hz > DMM_FREQ_LIMIT_HZ:
            # Still measure but flag
            dmm_dbm = averaged_measurement(
                lambda: measure_dmm_dbm(dmm),
                n        = averages,
                settle_s = 0.2,
            )
        else:
            dmm_dbm = averaged_measurement(
                lambda: measure_dmm_dbm(dmm),
                n        = averages,
                settle_s = 0.2,
            )

        scope_off = scope_dbm - level_dbm if not math.isnan(scope_dbm) else float("nan")
        ssa_off   = ssa_dbm   - level_dbm if not math.isnan(ssa_dbm)   else float("nan")
        dmm_off   = dmm_dbm   - level_dbm if not math.isnan(dmm_dbm)   else float("nan")

        dmm_flag  = ""
        if not skip_dmm and freq_hz > DMM_FREQ_LIMIT_HZ:
            dmm_flag = "*"    # above reliable DMM range

        def _fmt(v):
            return f"{v:+7.2f}" if not math.isnan(v) else "    N/A"

        print(
            f"  {format_freq_short(freq_hz):>12}  "
            f"{level_dbm:>+6.1f}    "
            f"{_fmt(scope_dbm)}  "
            f"{_fmt(ssa_dbm)}  "
            f"{_fmt(dmm_dbm)}{dmm_flag}  "
            f"{_fmt(scope_off)}  "
            f"{_fmt(ssa_off)}  "
            f"{_fmt(dmm_off)}"
        )

        results.append({
            "freq_hz":      freq_hz,
            "sdg_dbm":      level_dbm,
            "scope_dbm":    scope_dbm,
            "ssa_dbm":      ssa_dbm,
            "dmm_dbm":      dmm_dbm,
            "scope_offset": scope_off,
            "ssa_offset":   ssa_off,
            "dmm_offset":   dmm_off,
            "dmm_above_limit": freq_hz > DMM_FREQ_LIMIT_HZ,
        })

    return results


# ---------------------------------------------------------------------------
# Output: CSV, plot, text report
# ---------------------------------------------------------------------------

def save_csv(results: list[dict], output_prefix: str) -> str:
    """Write per-frequency data to CSV."""
    path = f"{output_prefix}_cal_table.csv"
    fieldnames = [
        "freq_hz", "sdg_dbm", "scope_dbm", "ssa_dbm", "dmm_dbm",
        "scope_offset", "ssa_offset", "dmm_offset",
    ]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in results:
            row = {k: (f"{r[k]:.4f}" if not math.isnan(r[k]) else "")
                   if isinstance(r[k], float) else r[k]
                   for k in fieldnames}
            w.writerow(row)
    return path


def save_flatness_plot(
    results:       list[dict],
    output_prefix: str,
    level_dbm:     float,
    skip_dmm:      bool,
) -> str:
    """
    Three-panel flatness plot: scope, SSA, and (optionally) DMM offset vs frequency.
    """
    freqs_hz = np.array([r["freq_hz"] for r in results])
    freqs_mhz = freqs_hz / 1e6

    scope_off = np.array([r["scope_offset"] for r in results], dtype=float)
    ssa_off   = np.array([r["ssa_offset"]   for r in results], dtype=float)
    dmm_off   = np.array([r["dmm_offset"]   for r in results], dtype=float)

    n_panels = 2 if skip_dmm else 3
    fig, axes = plt.subplots(n_panels, 1, figsize=(10, 3.5 * n_panels), sharex=True)

    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig.suptitle(
        f"Cross-Instrument Amplitude Calibration — {ts_str}\n"
        f"SDG reference level = {level_dbm:+.1f} dBm  "
        f"(offsets = instrument − SDG nominal)",
        fontsize=11,
    )

    def _plot_panel(ax, offsets, label, color):
        valid = ~np.isnan(offsets)
        if valid.any():
            ax.semilogx(freqs_hz[valid] / 1e6, offsets[valid],
                        color=color, linewidth=1.5, marker="o", markersize=5,
                        label=label)
            mean_off = float(np.nanmean(offsets[valid]))
            ax.axhline(mean_off, color=color, linestyle="--", linewidth=0.9, alpha=0.6,
                       label=f"Mean {mean_off:+.2f} dB")
        ax.axhline(0.0, color="black", linestyle=":", linewidth=0.8, alpha=0.5)
        ax.set_ylabel("Offset (dB)")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8, loc="upper right")
        ax.set_ylim(-10, 10)

    panel_idx = 0
    _plot_panel(axes[panel_idx], scope_off, "Scope offset", "#1f77b4")
    axes[panel_idx].set_title("Oscilloscope (SDS2000X)", fontsize=10)
    panel_idx += 1

    _plot_panel(axes[panel_idx], ssa_off, "SSA offset", "#d62728")
    axes[panel_idx].set_title("Spectrum Analyzer (SSA3000X)", fontsize=10)
    panel_idx += 1

    if not skip_dmm:
        _plot_panel(axes[panel_idx], dmm_off, "DMM offset", "#2ca02c")
        axes[panel_idx].set_title(
            f"Multimeter (SDM3000X)  "
            f"[* = above {format_freq_short(DMM_FREQ_LIMIT_HZ)} spec limit]",
            fontsize=10,
        )
        # Mark above-limit DMM points with a different marker
        above = np.array([r["dmm_above_limit"] for r in results])
        if above.any():
            axes[panel_idx].scatter(
                freqs_hz[above] / 1e6, dmm_off[above],
                color="red", marker="x", s=60, zorder=5,
                label=f"Above {format_freq_short(DMM_FREQ_LIMIT_HZ)}"
            )
            axes[panel_idx].legend(fontsize=8, loc="upper right")
        panel_idx += 1

    axes[-1].set_xlabel("Frequency (MHz)")

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    path = f"{output_prefix}_cal_flatness.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def save_text_report(
    results:       list[dict],
    level_dbm:     float,
    averages:      int,
    skip_dmm:      bool,
    output_prefix: str,
) -> str:
    """Write summary text report with average offsets per instrument."""
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "=" * 74

    scope_offsets = [r["scope_offset"] for r in results
                     if not math.isnan(r["scope_offset"])]
    ssa_offsets   = [r["ssa_offset"]   for r in results
                     if not math.isnan(r["ssa_offset"])]
    dmm_offsets   = [r["dmm_offset"]   for r in results
                     if not math.isnan(r["dmm_offset"])
                     and not r["dmm_above_limit"]]

    def _stats(vals):
        if not vals:
            return "N/A"
        return (f"mean {np.mean(vals):+.2f} dB  "
                f"min {np.min(vals):+.2f}  "
                f"max {np.max(vals):+.2f}  "
                f"pk-pk {np.max(vals) - np.min(vals):.2f} dB  "
                f"({len(vals)} pts)")

    lines = [
        sep,
        "  CROSS-INSTRUMENT AMPLITUDE CALIBRATION REPORT",
        f"  Generated  : {ts}",
        f"  Reference  : SDG1062X @ {level_dbm:+.1f} dBm (nominal, open circuit)",
        f"  Averages   : {averages} readings per point",
        f"  Note       : RELATIVE CALIBRATION ONLY — SDG accuracy not traceable",
        sep, "",
        "SUMMARY — average offset = (instrument − SDG nominal)",
        "-" * 74,
        f"  Scope  (SDS2000X) : {_stats(scope_offsets)}",
        f"  SSA    (SSA3000X) : {_stats(ssa_offsets)}",
    ]
    if not skip_dmm:
        lines.append(
            f"  DMM    (SDM3000X) : {_stats(dmm_offsets)}"
            + (f"  [values above {format_freq_short(DMM_FREQ_LIMIT_HZ)} excluded]"
               if any(r["dmm_above_limit"] for r in results) else "")
        )
    lines += [
        "",
        "INTERPRETATION",
        "-" * 74,
        "  A positive offset means the instrument reads HIGH vs. the SDG level.",
        "  A negative offset means the instrument reads LOW.",
        "  To correct a measurement: corrected_dBm = measured_dBm − offset",
        "",
    ]

    lines += [
        "FREQUENCY TABLE",
        "-" * 74,
        f"  {'Frequency':>12}  {'SDG':>8}  {'Scope':>8}  {'SSA':>8}  "
        f"{'DMM':>8}  {'Δscope':>8}  {'ΔSSA':>8}  {'ΔDMM':>8}",
        f"  {'-'*12}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}",
    ]

    def _f(v):
        return f"{v:+7.2f}" if not math.isnan(v) else "    N/A"

    for r in results:
        flag = "*" if r["dmm_above_limit"] else " "
        lines.append(
            f"  {format_freq_short(r['freq_hz']):>12}  "
            f"{r['sdg_dbm']:>+6.1f}    "
            f"{_f(r['scope_dbm'])}  "
            f"{_f(r['ssa_dbm'])}  "
            f"{_f(r['dmm_dbm'])}{flag} "
            f"{_f(r['scope_offset'])}  "
            f"{_f(r['ssa_offset'])}  "
            f"{_f(r['dmm_offset'])}"
        )
    if any(r["dmm_above_limit"] for r in results):
        lines.append(f"  * DMM reading above {format_freq_short(DMM_FREQ_LIMIT_HZ)} — outside spec")

    lines += ["", sep]
    text = "\n".join(lines) + "\n"
    path = f"{output_prefix}_cal.txt"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Cross-instrument amplitude calibration — SDG/SSA/Scope/DMM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Physical setup:
  SDG CH1 ─── T-splitter ─┬─── scope CH1
                            ├─── SSA RF In
                            └─── DMM Hi (BNC-banana)

IMPORTANT: This is RELATIVE calibration. The SDG is the reference —
accuracy is SDG output accuracy, not traceable to a calibration standard.

Examples:
  python calibration.py
  python calibration.py --freq-list "100,1000,10000,100000,1000000"
  python calibration.py --level -20 --averages 5
  python calibration.py --skip-dmm      # skip DMM for RF-range signals
""",
    )

    parser.add_argument(
        "--freq-list", default=None, metavar="HZ,HZ,...",
        help="Comma-separated list of frequencies in Hz "
             "(default: 10 log-spaced points from 100 Hz to 10 MHz)"
    )
    parser.add_argument(
        "--level", type=float, default=DEFAULT_LEVEL_DBM, metavar="DBM",
        help=f"SDG output level in dBm (default {DEFAULT_LEVEL_DBM})"
    )
    parser.add_argument(
        "--averages", type=int, default=DEFAULT_AVERAGES, metavar="N",
        help=f"Readings to average per instrument per frequency (default {DEFAULT_AVERAGES})"
    )
    parser.add_argument(
        "--scope-channel", type=int, default=DEFAULT_SCOPE_CH, metavar="N",
        help=f"Oscilloscope channel (default {DEFAULT_SCOPE_CH})"
    )
    parser.add_argument(
        "--sdg-host",   default=DEFAULT_SDG_HOST,   metavar="HOST",
        help=f"SDG1000X IP (default {DEFAULT_SDG_HOST})"
    )
    parser.add_argument(
        "--ssa-host",   default=DEFAULT_SSA_HOST,   metavar="HOST",
        help=f"SSA3000X IP (default {DEFAULT_SSA_HOST})"
    )
    parser.add_argument(
        "--scope-host", default=DEFAULT_SCOPE_HOST, metavar="HOST",
        help=f"SDS2000X IP (default {DEFAULT_SCOPE_HOST})"
    )
    parser.add_argument(
        "--dmm-host",   default=DEFAULT_DMM_HOST,   metavar="HOST",
        help=f"SDM3000X IP (default {DEFAULT_DMM_HOST})"
    )
    parser.add_argument(
        "--skip-dmm", action="store_true",
        help="Skip DMM measurements entirely (use for RF frequencies > 100 kHz)"
    )
    parser.add_argument(
        "--output", default=None, metavar="PREFIX",
        help="Output file prefix (default: timestamped)"
    )

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"cal_{ts}"

    # Parse frequency list
    if args.freq_list:
        try:
            freq_list = [int(float(x.strip())) for x in args.freq_list.split(",")]
        except ValueError as exc:
            print(f"Error: invalid --freq-list: {exc}")
            sys.exit(1)
    else:
        freq_list = _LOG_FREQS

    freq_list = sorted(set(freq_list))   # deduplicate and sort
    if not freq_list:
        print("Error: empty frequency list.")
        sys.exit(1)

    print(f"Calibration sweep: {len(freq_list)} frequencies, "
          f"{format_freq_short(freq_list[0])} – {format_freq_short(freq_list[-1])}")
    if any(f > DMM_FREQ_LIMIT_HZ for f in freq_list) and not args.skip_dmm:
        print(f"WARNING: some frequencies exceed DMM accuracy limit "
              f"({format_freq_short(DMM_FREQ_LIMIT_HZ)}). "
              "Consider --skip-dmm or restrict to lower frequencies.")
    print()

    # Connect to instruments
    print(f"Connecting to SDG   @ {args.sdg_host}   ...", end=" ", flush=True)
    sdg = SDG1000X(args.sdg_host)
    print("OK")

    print(f"Connecting to SSA   @ {args.ssa_host}   ...", end=" ", flush=True)
    ssa = SSA3000X(args.ssa_host)
    print("OK")

    print(f"Connecting to scope @ {args.scope_host} ...", end=" ", flush=True)
    scope = SDS2000X(args.scope_host)
    print("OK")

    dmm = None
    if not args.skip_dmm:
        print(f"Connecting to DMM   @ {args.dmm_host}   ...", end=" ", flush=True)
        dmm = SDM3000X(args.dmm_host)
        print("OK")
    else:
        print("DMM: skipped (--skip-dmm)")

    results = []
    try:
        results = run_calibration(
            sdg         = sdg,
            ssa         = ssa,
            scope       = scope,
            dmm         = dmm,
            freq_list   = freq_list,
            level_dbm   = args.level,
            averages    = args.averages,
            scope_ch    = args.scope_channel,
            skip_dmm    = args.skip_dmm,
        )
    except KeyboardInterrupt:
        print("\nInterrupted — saving partial results.")
    finally:
        try:
            sdg.output_off(1)
            sdg.close()
        except Exception:
            pass
        try:
            ssa.disconnect()
        except Exception:
            pass
        try:
            scope.close()
        except Exception:
            pass
        if dmm is not None:
            try:
                dmm.close()
            except Exception:
                pass

    if not results:
        print("No data collected.")
        sys.exit(1)

    # --- Save outputs ---
    print("\n[SAVING RESULTS]")

    csv_path = save_csv(results, args.output)
    print(f"  CSV          → {csv_path}")

    try:
        plot_path = save_flatness_plot(results, args.output, args.level, args.skip_dmm)
        print(f"  Flatness plot → {plot_path}")
    except Exception as exc:
        print(f"  Plot failed: {exc}")

    txt_path = save_text_report(results, args.level, args.averages,
                                args.skip_dmm, args.output)
    print(f"  Text report   → {txt_path}")
    print()

    with open(txt_path) as fh:
        print(fh.read())


if __name__ == "__main__":
    try:
        main()
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to instrument: {exc}")
        print("Check that instruments are powered on and SCPI/LAN is enabled.")
        sys.exit(1)
    except OSError as exc:
        print(f"\nNetwork error: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
        sys.exit(1)
