#!/usr/bin/env python3
"""
Clock Jitter and PLL Lock Time Analyzer — Siglent SDS2000X Plus MSO

Captures digital signals via the MSO probe pod and measures:
  --mode jitter    : cycle-to-cycle period jitter histogram for a clock signal
  --mode pll-lock  : time from frequency-change write strobe to PLL LOCK_DETECT assertion

WARNING — MSO HARDWARE NOT TESTED:
  All MSO digital channel code is implemented from the Siglent SDS Series EN11F SCPI
  programming guide. The MSO probe pod hardware has NOT been physically tested. If
  digital captures return empty data: verify the MSO option is licensed, the pod is
  connected and powered, and the threshold is set correctly for the signal level.

Usage:
  # Jitter measurement — D0 = clock, 10 ms capture:
  python clock_jitter.py --mode jitter --clock-ch 0 --duration-s 0.01

  # Jitter with expected frequency validation:
  python clock_jitter.py --mode jitter --clock-ch 0 --expected-freq-hz 16e6

  # PLL lock time — D0 = LOCK_DETECT, D1 = LE write strobe, C1 = VCO tuning voltage:
  python clock_jitter.py --mode pll-lock --lock-ch 0 --write-ch 1 --vco-analog-ch 1

  # PLL lock time — digital only (no analog VCO channel):
  python clock_jitter.py --mode pll-lock --lock-ch 0 --write-ch 1 --vco-analog-ch -1
"""

import argparse
import csv as csv_module
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

from rf_bench.siglent import SDS2000X                                        # noqa: E402
from rf_bench.utils import format_freq                                        # noqa: E402

# scipy is optional — Gaussian fit is skipped if unavailable
try:
    from scipy.optimize import curve_fit as _scipy_curve_fit
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SCOPE_HOST         = "10.1.1.58"
DEFAULT_CLOCK_CH   = 0
DEFAULT_LOCK_CH    = 0
DEFAULT_WRITE_CH   = 1
DEFAULT_VCO_CH     = 1          # analog channel; -1 = skip
DEFAULT_VCO_VDIV   = 0.5        # V/div for VCO tuning voltage
DEFAULT_JITTER_DUR = 0.01       # 10 ms → ~10 000 cycles at 1 MHz
DEFAULT_PLL_DUR    = 0.001      # 1 ms window around lock event
DEFAULT_THRESHOLD  = "LVCMOS33"

THRESHOLD_CHOICES  = ("ttl", "cmos", "lvcmos33", "lvcmos25")


# ---------------------------------------------------------------------------
# Threshold helpers
# ---------------------------------------------------------------------------

def _resolve_threshold(threshold_str: str | None,
                       threshold_v: float | None) -> str | float:
    """Return the threshold value to pass to set_digital_threshold()."""
    if threshold_v is not None:
        return threshold_v
    return threshold_str.upper() if threshold_str else DEFAULT_THRESHOLD


def _pod_for_channel(ch: int) -> int:
    """Return pod number (1 or 2) for a digital channel (0–15)."""
    return 1 if ch < 8 else 2


# ---------------------------------------------------------------------------
# Gaussian fit helper
# ---------------------------------------------------------------------------

def _gaussian(x, mu, sigma, amplitude):
    return amplitude * np.exp(-0.5 * ((x - mu) / sigma) ** 2)


def _fit_gaussian(bin_centers, counts):
    """
    Fit a Gaussian to a histogram.  Returns (mu, sigma, amplitude) or None.
    Requires scipy.  Skips if fewer than 5 non-zero bins.
    """
    if not _SCIPY_OK:
        return None
    nonzero = counts > 0
    if np.sum(nonzero) < 5:
        return None
    try:
        p0 = [bin_centers[np.argmax(counts)], np.std(bin_centers), float(np.max(counts))]
        popt, _ = _scipy_curve_fit(_gaussian, bin_centers, counts, p0=p0, maxfev=5000)
        return popt   # (mu, sigma, amplitude)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Jitter mode
# ---------------------------------------------------------------------------

def run_jitter(scope: SDS2000X, args) -> None:
    """Capture a digital clock and measure cycle-to-cycle period jitter."""

    threshold = _resolve_threshold(args.threshold, args.threshold_v)
    pod       = _pod_for_channel(args.clock_ch)

    print(f"\n[JITTER] D{args.clock_ch}  threshold={threshold}  "
          f"duration={args.duration_s*1000:.1f} ms")

    # --- Configure scope ---
    print("  Configuring MSO digital channel ...", end=" ", flush=True)
    scope.digital_enable()
    scope.digital_channel_enable(args.clock_ch)
    scope.set_digital_threshold(pod, threshold)
    print("done")

    # Set timebase: duration_s / 10 s/div (10 divisions total)
    tdiv = args.duration_s / 10.0
    scope.stop()
    time.sleep(0.1)
    scope._cmd(f"TDIV {tdiv:.8f}S")
    scope._cmd("TRMD AUTO")

    print("  Acquiring ...", end=" ", flush=True)
    scope.run()
    time.sleep(args.duration_s + 0.5)
    scope.stop()
    time.sleep(0.2)
    print("done")

    # --- Read digital waveform ---
    print("  Reading digital waveform ...", end=" ", flush=True)
    samples, sr = scope.capture_digital(args.clock_ch)
    print(f"done  ({len(samples)} samples @ {sr/1e6:.1f} MHz sample rate)")

    if sr <= 0:
        raise RuntimeError("Sample rate is zero — scope did not return a valid acquisition")

    # --- Find rising edges ---
    edge_indices = np.where(np.diff(samples.astype(np.int8)) == 1)[0]

    if len(edge_indices) < 3:
        raise RuntimeError(
            f"Only {len(edge_indices)} rising edge(s) found — need ≥ 3 for jitter measurement. "
            f"Check: threshold correct? Clock signal present on D{args.clock_ch}? "
            f"Capture window long enough for expected frequency?"
        )

    # --- Jitter statistics ---
    intervals_s    = np.diff(edge_indices) / sr
    freq_hz        = 1.0 / np.mean(intervals_s)
    mean_period_s  = np.mean(intervals_s)
    sigma_jitter_s = np.std(intervals_s)
    pk_pk_jitter_s = float(np.ptp(intervals_s))
    jitter_ps      = (intervals_s - mean_period_s) * 1e12   # centered on 0

    # Frequency validation
    freq_warning = ""
    if args.expected_freq_hz is not None:
        error_pct = abs(freq_hz - args.expected_freq_hz) / args.expected_freq_hz * 100.0
        if error_pct > 2.0:
            freq_warning = (f"  WARNING: measured {format_freq(freq_hz)} vs expected "
                            f"{format_freq(args.expected_freq_hz)} — {error_pct:.1f}% error")

    # --- Terminal output ---
    print()
    print(f"  Measured frequency   : {format_freq(freq_hz)}")
    print(f"  Mean period          : {mean_period_s*1e9:.3f} ns")
    print(f"  RMS jitter (1σ)      : {sigma_jitter_s*1e12:.1f} ps")
    print(f"  Peak-to-peak jitter  : {pk_pk_jitter_s*1e12:.1f} ps")
    print(f"  Cycles measured      : {len(intervals_s)}")
    if freq_warning:
        print(freq_warning)

    # --- Save CSV ---
    csv_path = f"{args.output}_jitter.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["cycle_number", "period_ns", "jitter_ps"])
        for i, (period, jitter) in enumerate(zip(intervals_s * 1e9, jitter_ps)):
            w.writerow([i + 1, f"{period:.4f}", f"{jitter:.4f}"])
    print(f"\n  CSV    → {csv_path}")

    # --- Save summary text ---
    txt_path = f"{args.output}_jitter.txt"
    with open(txt_path, "w") as f:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sep = "=" * 60
        f.write(f"{sep}\n  CLOCK JITTER ANALYSIS\n  Generated : {ts}\n")
        f.write(f"  Scope     : {args.scope_host}\n")
        f.write(f"  Channel   : D{args.clock_ch}\n")
        f.write(f"  Threshold : {threshold}\n")
        f.write(f"  Duration  : {args.duration_s*1000:.1f} ms\n{sep}\n\n")
        f.write(f"  Measured frequency   : {format_freq(freq_hz)}\n")
        f.write(f"  Mean period          : {mean_period_s*1e9:.3f} ns\n")
        f.write(f"  RMS jitter (1σ)      : {sigma_jitter_s*1e12:.1f} ps\n")
        f.write(f"  Peak-to-peak jitter  : {pk_pk_jitter_s*1e12:.1f} ps\n")
        f.write(f"  Cycles measured      : {len(intervals_s)}\n")
        if args.expected_freq_hz is not None:
            f.write(f"  Expected frequency   : {format_freq(args.expected_freq_hz)}\n")
        if freq_warning:
            f.write(f"\n{freq_warning.strip()}\n")
        if not _SCIPY_OK:
            f.write("\nNOTE: scipy not available — Gaussian fit skipped.\n")
    print(f"  Report → {txt_path}")

    # --- Plot ---
    png_path = f"{args.output}_jitter.png"
    _plot_jitter(jitter_ps, intervals_s * 1e9, freq_hz, sigma_jitter_s * 1e12,
                 pk_pk_jitter_s * 1e12, len(intervals_s), args, png_path)
    print(f"  Plot   → {png_path}")


def _plot_jitter(jitter_ps: np.ndarray, periods_ns: np.ndarray,
                 freq_hz: float, rms_ps: float, pkpk_ps: float,
                 n_cycles: int, args, path: str) -> None:
    fig, (ax_hist, ax_time) = plt.subplots(2, 1, figsize=(10, 8))

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig.suptitle(
        f"Clock Jitter — D{args.clock_ch}  {format_freq(freq_hz)}\n"
        f"{ts}  |  Scope {args.scope_host}",
        fontsize=12,
    )

    # ---- Top: jitter histogram ----
    n_bins  = min(max(20, int(np.sqrt(len(jitter_ps)) * 2)), 150)
    counts, bin_edges = np.histogram(jitter_ps, bins=n_bins)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    ax_hist.bar(bin_centers, counts, width=bin_edges[1] - bin_edges[0],
                color="#1f77b4", alpha=0.75, label="Measured")

    # Gaussian fit overlay
    gfit = _fit_gaussian(bin_centers, counts)
    if gfit is not None:
        mu, sigma, amp = gfit
        x_fit = np.linspace(bin_edges[0], bin_edges[-1], 400)
        ax_hist.plot(x_fit, _gaussian(x_fit, mu, sigma, amp),
                     color="red", linewidth=2.0,
                     label=f"Gaussian fit  σ={abs(sigma):.1f} ps")
    else:
        ax_hist.axvline(0, color="gray", linewidth=0.8, linestyle="--")

    ax_hist.set_xlabel("Cycle-to-cycle jitter (ps)", fontsize=10)
    ax_hist.set_ylabel("Count", fontsize=10)
    ax_hist.set_title(
        f"Jitter histogram — RMS={rms_ps:.1f} ps  pk-pk={pkpk_ps:.1f} ps  "
        f"N={n_cycles} cycles",
        fontsize=10,
    )
    ax_hist.grid(True, alpha=0.35)
    ax_hist.legend(fontsize=9)

    # ---- Bottom: period vs. cycle number ----
    cycle_nums = np.arange(1, len(periods_ns) + 1)
    ax_time.plot(cycle_nums, periods_ns, color="#2ca02c", linewidth=0.8, alpha=0.85)
    ax_time.axhline(np.mean(periods_ns), color="red", linewidth=1.2,
                    linestyle="--", label=f"Mean {np.mean(periods_ns):.4f} ns")
    ax_time.set_xlabel("Cycle number", fontsize=10)
    ax_time.set_ylabel("Period (ns)", fontsize=10)
    ax_time.set_title("Period vs. cycle number", fontsize=10)
    ax_time.grid(True, alpha=0.35)
    ax_time.legend(fontsize=9)
    ax_time.set_xlim(1, len(periods_ns))

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# PLL lock mode
# ---------------------------------------------------------------------------

def run_pll_lock(scope: SDS2000X, args) -> None:
    """Measure PLL lock time from write strobe assertion to LOCK_DETECT rising edge."""

    threshold = _resolve_threshold(args.threshold, args.threshold_v)
    channels  = sorted(set([args.write_ch, args.lock_ch]))
    pod1_chs  = [c for c in channels if c < 8]
    pod2_chs  = [c for c in channels if c >= 8]

    print(f"\n[PLL LOCK]  LOCK_DETECT=D{args.lock_ch}  WRITE_STROBE=D{args.write_ch}  "
          f"threshold={threshold}  window={args.duration_s*1000:.1f} ms")
    if args.vco_analog_ch >= 1:
        print(f"  VCO tuning voltage : analog C{args.vco_analog_ch} "
              f"({args.vco_vdiv:.2f} V/div)")

    # --- Configure MSO ---
    print("  Configuring MSO ...", end=" ", flush=True)
    scope.digital_enable()
    for ch in channels:
        scope.digital_channel_enable(ch)
    if pod1_chs:
        scope.set_digital_threshold(1, threshold)
    if pod2_chs:
        scope.set_digital_threshold(2, threshold)
    print("done")

    # Set timebase
    tdiv = args.duration_s / 10.0
    scope.stop()
    time.sleep(0.1)
    scope._cmd(f"TDIV {tdiv:.8f}S")
    scope._cmd("TRMD AUTO")

    # Optional: configure analog VCO channel
    if args.vco_analog_ch >= 1:
        ch_str = f"C{args.vco_analog_ch}"
        scope._cmd(f"{ch_str}:CPL D1M")
        scope._cmd(f"{ch_str}:VDIV {args.vco_vdiv:.4f}V")

    print("  Acquiring ...", end=" ", flush=True)
    scope.run()
    time.sleep(args.duration_s + 0.5)
    scope.stop()
    time.sleep(0.2)
    print("done")

    # --- Read digital channels ---
    print("  Reading digital waveforms ...", end=" ", flush=True)
    traces, sr = scope.capture_all_digital(channels)
    print(f"done  (sr={sr/1e6:.1f} MHz)")

    if args.write_ch not in traces:
        raise RuntimeError(
            f"No data on write strobe D{args.write_ch} — check pod connection and enable"
        )
    if args.lock_ch not in traces:
        raise RuntimeError(
            f"No data on lock detect D{args.lock_ch} — check pod connection and enable"
        )

    write_signal = traces[args.write_ch]
    lock_signal  = traces[args.lock_ch]
    n_samples    = len(write_signal)
    t_axis_us    = np.arange(n_samples) / sr * 1e6   # microseconds

    # --- Find write strobe rising edge (LE pulse) ---
    write_diff   = np.diff(write_signal.astype(np.int8))
    write_edges  = np.where(write_diff > 0)[0]
    if len(write_edges) == 0:
        raise RuntimeError(
            f"No rising edge on write strobe D{args.write_ch} — "
            f"verify LE pulse is active-high and occurs within the capture window"
        )
    t_write_idx = int(write_edges[0])
    t_write_us  = t_write_idx / sr * 1e6

    # --- Find lock detect assertion after write ---
    post_write_lock = lock_signal[t_write_idx:]
    lock_asserted   = np.where(post_write_lock > 0)[0]

    if len(lock_asserted) == 0:
        lock_time_us  = float("nan")
        lock_occurred = False
        print("\n  WARNING: PLL did not assert LOCK_DETECT within the capture window.")
        print(f"           Consider increasing --duration-s (current: {args.duration_s*1000:.1f} ms)")
    else:
        lock_time_samples = int(lock_asserted[0])
        lock_time_us      = lock_time_samples / sr * 1e6
        lock_occurred     = True

    # --- Optional VCO analog capture ---
    vco_v   = None
    vco_sr  = None
    if args.vco_analog_ch >= 1:
        print("  Reading VCO tuning voltage ...", end=" ", flush=True)
        try:
            vco_v, vco_sr = scope.capture_audio(
                args.vco_analog_ch, duration_s=args.duration_s, vdiv=args.vco_vdiv
            )
            print(f"done  ({len(vco_v)} samples)")
        except Exception as exc:
            print(f"failed ({exc}) — analog trace skipped")

    # --- Terminal output ---
    print()
    if lock_occurred:
        print(f"  Write strobe at    : {t_write_us:.3f} µs (sample {t_write_idx})")
        print(f"  Lock asserted at   : {t_write_us + lock_time_us:.3f} µs after capture start")
        print(f"  PLL lock time      : {lock_time_us:.1f} µs")
    else:
        print(f"  Write strobe at    : {t_write_us:.3f} µs")
        print(f"  PLL lock time      : did not lock within window")

    # --- Save summary text ---
    txt_path = f"{args.output}_pll.txt"
    with open(txt_path, "w") as f:
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sep = "=" * 60
        f.write(f"{sep}\n  PLL LOCK TIME ANALYSIS\n  Generated : {ts}\n")
        f.write(f"  Scope     : {args.scope_host}\n")
        f.write(f"  Lock ch   : D{args.lock_ch}\n")
        f.write(f"  Write ch  : D{args.write_ch}\n")
        f.write(f"  Threshold : {threshold}\n")
        f.write(f"  Window    : {args.duration_s*1000:.1f} ms\n{sep}\n\n")
        f.write(f"  Write strobe (LE rising edge) : {t_write_us:.3f} µs from start\n")
        if lock_occurred:
            f.write(f"  Lock detect assertion        : {t_write_us + lock_time_us:.3f} µs\n")
            f.write(f"  PLL lock time                : {lock_time_us:.1f} µs\n")
        else:
            f.write(f"  PLL lock time                : did not lock within window\n")
        if vco_v is not None:
            vco_start = float(vco_v[0])
            vco_end   = float(vco_v[-1])
            f.write(f"\n  VCO tuning voltage (start)   : {vco_start:.3f} V\n")
            f.write(f"  VCO tuning voltage (settled) : {vco_end:.3f} V\n")
            f.write(f"  VCO tuning voltage swing     : {abs(vco_end - vco_start):.3f} V\n")
    print(f"  Report → {txt_path}")

    # --- Plot ---
    png_path = f"{args.output}_pll.png"
    _plot_pll(t_axis_us, write_signal, lock_signal, vco_v, vco_sr,
              t_write_us, lock_time_us, lock_occurred, args, png_path)
    print(f"  Plot   → {png_path}")


def _plot_pll(t_axis_us: np.ndarray,
              write_signal: np.ndarray,
              lock_signal: np.ndarray,
              vco_v,        # np.ndarray or None
              vco_sr,       # float or None
              t_write_us: float,
              lock_time_us: float,
              lock_occurred: bool,
              args, path: str) -> None:

    has_vco = vco_v is not None and vco_sr is not None
    nrows   = 2 if has_vco else 1
    fig, axes = plt.subplots(nrows, 1, figsize=(12, 4 * nrows + 1),
                             sharex=False)
    if nrows == 1:
        axes = [axes]

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig.suptitle(
        f"PLL Lock Time — LOCK=D{args.lock_ch}  WR=D{args.write_ch}\n"
        f"{ts}  |  Scope {args.scope_host}",
        fontsize=12,
    )

    # ---- VCO tuning voltage panel (top, if captured) ----
    if has_vco:
        ax_vco = axes[0]
        vco_t  = np.arange(len(vco_v)) / vco_sr * 1e6
        ax_vco.plot(vco_t, vco_v, color="#d62728", linewidth=1.0)
        ax_vco.axvline(t_write_us, color="blue", linewidth=1.5,
                       linestyle="--", label=f"Write strobe t={t_write_us:.2f} µs")
        if lock_occurred:
            ax_vco.axvline(t_write_us + lock_time_us, color="green", linewidth=1.5,
                           linestyle=":", label=f"Lock at +{lock_time_us:.1f} µs")
        ax_vco.set_ylabel("VCO tuning voltage (V)", fontsize=9)
        ax_vco.set_xlabel("Time (µs)", fontsize=9)
        ax_vco.set_title(f"VCO tuning voltage  C{args.vco_analog_ch}", fontsize=10)
        ax_vco.grid(True, alpha=0.35)
        ax_vco.legend(fontsize=8, loc="upper right")
        ax_vco_idx = 1
    else:
        ax_vco_idx = 0

    # ---- Digital channels panel ----
    ax_dig = axes[ax_vco_idx]

    # Plot write strobe (offset +2) and lock detect (offset 0)
    wr_offset   = 2.5
    lock_offset = 0.0
    ax_dig.step(t_axis_us, write_signal.astype(float) + wr_offset,
                where="post", color="#1f77b4", linewidth=1.2,
                label=f"D{args.write_ch} Write strobe (offset +{wr_offset:.0f})")
    ax_dig.step(t_axis_us, lock_signal.astype(float) + lock_offset,
                where="post", color="#2ca02c", linewidth=1.2,
                label=f"D{args.lock_ch} LOCK_DETECT")

    ax_dig.axvline(t_write_us, color="blue", linewidth=1.5, linestyle="--",
                   label=f"Write t={t_write_us:.2f} µs")
    if lock_occurred:
        ax_dig.axvline(t_write_us + lock_time_us, color="green", linewidth=1.5,
                       linestyle=":", label=f"Lock +{lock_time_us:.1f} µs")
        # Annotate lock time span
        yp = 1.8
        ax_dig.annotate(
            "", xy=(t_write_us + lock_time_us, yp), xytext=(t_write_us, yp),
            arrowprops=dict(arrowstyle="<->", color="darkorange", lw=1.5),
        )
        ax_dig.text(t_write_us + lock_time_us / 2, yp + 0.15,
                    f"{lock_time_us:.1f} µs", ha="center", va="bottom",
                    fontsize=9, color="darkorange")
    else:
        ax_dig.text(0.5, 0.5, "PLL did not lock in window",
                    transform=ax_dig.transAxes, ha="center", va="center",
                    fontsize=11, color="red", alpha=0.6)

    ax_dig.set_yticks([0, 0.5, 1, wr_offset, wr_offset + 0.5, wr_offset + 1])
    ax_dig.set_yticklabels(
        ["LO", "", f"D{args.lock_ch} HI", "LO", "", f"D{args.write_ch} HI"],
        fontsize=8,
    )
    ax_dig.set_xlabel("Time (µs)", fontsize=9)
    ax_dig.set_title("Digital channels (write strobe + lock detect)", fontsize=10)
    ax_dig.grid(True, alpha=0.35)
    ax_dig.legend(fontsize=8, loc="upper right")
    ax_dig.set_ylim(-0.3, wr_offset + 1.5)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Clock Jitter and PLL Lock Time Analyzer — Siglent SDS2000X Plus MSO",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
MSO HARDWARE WARNING:
  All MSO digital code is from the Siglent EN11F SCPI programming guide.
  This has NOT been tested with physical MSO hardware.  If captures return
  empty data: confirm MSO license, pod connection, and threshold voltage.

Mode: jitter
  Capture a digital clock, find rising edges, compute cycle-to-cycle
  period jitter, and generate a histogram with optional Gaussian fit.

  Example:
    python clock_jitter.py --mode jitter --clock-ch 0 --duration-s 0.01
    python clock_jitter.py --mode jitter --clock-ch 2 --threshold-v 1.65

Mode: pll-lock
  Measure time from a PLL write strobe (LE pulse) to LOCK_DETECT assertion.
  Optionally capture the VCO tuning voltage on an analog channel.

  Example:
    python clock_jitter.py --mode pll-lock --lock-ch 0 --write-ch 1
    python clock_jitter.py --mode pll-lock --lock-ch 0 --write-ch 1 --vco-analog-ch -1

Output files (jitter mode):
  <prefix>_jitter.csv   — cycle_number, period_ns, jitter_ps (per cycle)
  <prefix>_jitter.png   — histogram + Gaussian fit (top), period time series (bottom)
  <prefix>_jitter.txt   — summary statistics

Output files (pll-lock mode):
  <prefix>_pll.png      — VCO tuning voltage (if captured) + digital channels
  <prefix>_pll.txt      — lock time, VCO settling info
""",
    )

    parser.add_argument("--mode", required=True, choices=("jitter", "pll-lock"),
                        help="Measurement mode")
    parser.add_argument("--scope-host", default=SCOPE_HOST,
                        help=f"Oscilloscope IP address (default: {SCOPE_HOST})")
    parser.add_argument("--output", default=None,
                        help="Output filename prefix (default: timestamped)")

    # Threshold selection (shared)
    tgrp = parser.add_argument_group("threshold")
    tgrp.add_argument("--threshold", default=DEFAULT_THRESHOLD,
                      choices=THRESHOLD_CHOICES,
                      help=f"Logic threshold standard (default: {DEFAULT_THRESHOLD})")
    tgrp.add_argument("--threshold-v", type=float, default=None, metavar="V",
                      help="Custom threshold voltage in V (overrides --threshold)")

    # Jitter mode
    jgrp = parser.add_argument_group("jitter mode")
    jgrp.add_argument("--clock-ch", type=int, default=DEFAULT_CLOCK_CH, metavar="N",
                      help=f"Digital channel with clock signal (default: {DEFAULT_CLOCK_CH})")
    jgrp.add_argument("--duration-s", type=float, default=DEFAULT_JITTER_DUR, metavar="S",
                      help=f"Capture duration in seconds (default: {DEFAULT_JITTER_DUR}; "
                           f"10 ms → ~10 000 cycles at 1 MHz)")
    jgrp.add_argument("--expected-freq-hz", type=float, default=None, metavar="HZ",
                      help="Nominal clock frequency for validation (optional)")

    # PLL lock mode
    pgrp = parser.add_argument_group("pll-lock mode")
    pgrp.add_argument("--lock-ch", type=int, default=DEFAULT_LOCK_CH, metavar="N",
                      help=f"Digital channel: PLL LOCK_DETECT output (default: {DEFAULT_LOCK_CH})")
    pgrp.add_argument("--write-ch", type=int, default=DEFAULT_WRITE_CH, metavar="N",
                      help=f"Digital channel: PLL write strobe / LE pulse (default: {DEFAULT_WRITE_CH})")
    pgrp.add_argument("--vco-analog-ch", type=int, default=DEFAULT_VCO_CH, metavar="N",
                      help=f"Analog scope channel for VCO tuning voltage "
                           f"(default: {DEFAULT_VCO_CH}; -1 = skip)")
    pgrp.add_argument("--vco-vdiv", type=float, default=DEFAULT_VCO_VDIV, metavar="V",
                      help=f"V/div for VCO tuning voltage channel (default: {DEFAULT_VCO_VDIV})")
    pgrp.add_argument("--pll-duration-s", type=float, default=DEFAULT_PLL_DUR, metavar="S",
                      dest="duration_s",
                      help=f"Capture window in seconds for pll-lock mode (default: {DEFAULT_PLL_DUR}; "
                           f"1 ms — increase for slow-locking PLLs)")

    args = parser.parse_args()

    # jitter mode also uses duration_s, but must not conflict with pll default
    # Both modes share args.duration_s via the argparse dest above.
    # For jitter mode, re-parse the default separately if the user didn't supply it.
    # We handle this by adding --duration-s only for jitter mode; pll uses --pll-duration-s.
    # Since both write to args.duration_s, the last one wins. For jitter the user uses
    # --duration-s which is defined in the jitter group — it always overrides the pll default.

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"clock_{args.mode.replace('-', '_')}_{ts}"

    print(f"Clock Jitter / PLL Lock Analyzer")
    print(f"  Mode   : {args.mode}")
    print(f"  Scope  : {args.scope_host}")
    print(f"  Output : {args.output}_*")

    try:
        scope = SDS2000X(args.scope_host)
        idn   = scope.identify()
        print(f"  IDN    : {idn.strip()}")
        if "SDS" not in idn.upper() and "SIGLENT" not in idn.upper():
            print("  WARNING: IDN doesn't look like a Siglent oscilloscope — continuing.")

        if args.mode == "jitter":
            run_jitter(scope, args)
        elif args.mode == "pll-lock":
            run_pll_lock(scope, args)

        print("\nDone.")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError:
        print(f"\nCannot connect to {args.scope_host}:5025")
        print("Verify the oscilloscope is powered on and SCPI/LAN is enabled.")
        sys.exit(1)
    except OSError as exc:
        print(f"\nNetwork error: {exc}")
        sys.exit(1)
    except RuntimeError as exc:
        print(f"\nMeasurement error: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            scope.run()
            scope.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
