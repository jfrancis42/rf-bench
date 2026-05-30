#!/usr/bin/env python3
"""
Power Integrity Analyzer — Siglent SDS2000X Plus MSO + Analog Channels

Captures MSO digital switching activity and analog power rail voltage
simultaneously on a shared timebase.  Correlates digital transitions with
supply noise.

Usage:
  python power_integrity.py
  python power_integrity.py --digital-channels 0,1,2,3 --analog-channel 1
  python power_integrity.py --digital-channels 4,5 --vdiv 0.05 --duration-s 0.02
  python power_integrity.py --stats --continuous
  python power_integrity.py --trigger-on-edge 0
"""

import argparse
import csv as csv_module
import json
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

# ---------------------------------------------------------------------------
# Siglent shared drivers
# ---------------------------------------------------------------------------

from rf_bench.siglent import SDS2000X                                         # noqa: E402

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SCOPE_HOST       = "10.1.1.58"
DEFAULT_DURATION = 0.01    # 10 ms — keep short for high sample-rate captures
DEFAULT_CHANNELS = "0,1,2,3"
CONTINUOUS_INTERVAL = 2.0  # seconds between continuous captures

# Pod assignment
_POD1_CHANNELS = range(0, 8)
_POD2_CHANNELS = range(8, 16)


def _pod_for_channel(ch: int) -> int:
    return 1 if ch < 8 else 2


# ---------------------------------------------------------------------------
# Threshold helpers
# ---------------------------------------------------------------------------

def _apply_thresholds(scope: SDS2000X,
                      threshold_pod0: str, threshold_pod1: str,
                      channels: list[int]) -> None:
    """Apply per-pod thresholds for the pods used by the given channels."""
    pods_needed = set(_pod_for_channel(ch) for ch in channels)
    if 1 in pods_needed:
        _set_threshold(scope, 1, threshold_pod0)
    if 2 in pods_needed:
        _set_threshold(scope, 2, threshold_pod1)


def _set_threshold(scope: SDS2000X, pod: int, threshold: str) -> None:
    """Set a threshold — accepts preset name or numeric string."""
    try:
        v = float(threshold)
        scope.set_digital_threshold(pod, v)
    except ValueError:
        scope.set_digital_threshold(pod, threshold.upper())


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def capture_mixed_signal(
    scope: SDS2000X,
    analog_channel: int,
    digital_channels: list[int],
    duration_s: float,
    vdiv: float | None,
) -> tuple[np.ndarray, float, dict[int, np.ndarray], float]:
    """
    Capture analog + digital channels in a single acquisition.

    Procedure:
      1. Stop the scope.
      2. Configure analog channel.
      3. Acquire (run + wait + stop).
      4. Read analog waveform.
      5. Read digital channels.

    Returns:
        (analog_wave, sr_analog, digital_traces, sr_digital)
        analog_wave    — np.ndarray of voltages (V)
        sr_analog      — analog sample rate (Hz)
        digital_traces — dict ch → bool np.ndarray
        sr_digital     — digital sample rate (Hz)
    """
    analog_wave, sr_analog = scope.capture_audio(
        channel=analog_channel,
        duration_s=duration_s,
        vdiv=vdiv,
    )

    # Scope is stopped after capture_audio — read digital data immediately
    digital_traces, sr_digital = scope.capture_all_digital(digital_channels)

    scope.run()
    return analog_wave, sr_analog, digital_traces, sr_digital


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def compute_supply_stats(wave: np.ndarray) -> dict:
    """Compute supply rail statistics from a voltage waveform."""
    mean_v    = float(np.mean(wave))
    ac_vrms   = float(np.std(wave))               # std = AC RMS (DC removed)
    total_rms = float(np.sqrt(np.mean(wave**2)))  # includes DC
    vpp       = float(np.ptp(wave))
    vmin      = float(np.min(wave))
    vmax      = float(np.max(wave))

    # Worst-case deviation from mean
    worst_glitch_v = float(np.max(np.abs(wave - mean_v)))

    return {
        "mean_v":         mean_v,
        "ac_vrms":        ac_vrms,
        "total_rms":      total_rms,
        "vpp":            vpp,
        "vmin":           vmin,
        "vmax":           vmax,
        "worst_glitch_v": worst_glitch_v,
    }


def compute_digital_stats(traces: dict[int, np.ndarray],
                          sr_digital: float) -> dict[int, dict]:
    """Compute switching statistics per digital channel."""
    stats = {}
    for ch, samples in traces.items():
        edges = int(np.sum(np.abs(np.diff(samples.astype(np.int8)))))
        duration_s = len(samples) / sr_digital if sr_digital > 0 else 1.0
        # switching rate: edges / 2 = half-cycles per second = frequency
        rate_hz = (edges / 2.0) / duration_s if duration_s > 0 else 0.0

        stats[ch] = {
            "edges":          edges,
            "switching_hz":   rate_hz,
            "duration_s":     duration_s,
            "n_samples":      len(samples),
            "duty_cycle_pct": float(np.mean(samples) * 100.0),
        }
    return stats


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_stats(supply_stats: dict, digital_stats: dict[int, dict],
                analog_channel: int, timestamp: str | None = None) -> None:
    """Print one-line continuous status or full stats block."""
    ts = timestamp or datetime.now().strftime("%H:%M:%S")
    mean_v = supply_stats["mean_v"]
    vpp_mv = supply_stats["vpp"] * 1000.0
    ac_mv  = supply_stats["ac_vrms"] * 1000.0

    digital_parts = []
    for ch in sorted(digital_stats.keys()):
        rate = digital_stats[ch]["switching_hz"]
        if rate >= 1e6:
            rate_str = f"{rate/1e6:.2f} MHz"
        elif rate >= 1e3:
            rate_str = f"{rate/1e3:.1f} kHz"
        elif rate > 0:
            rate_str = f"{rate:.1f} Hz"
        else:
            rate_str = "0 Hz (idle)"
        digital_parts.append(f"D{ch}: {rate_str}")

    dig_str = " | ".join(digital_parts)
    print(f"[{ts}] CH{analog_channel}: {mean_v:.3f}V avg, {vpp_mv:.1f}mVpp, "
          f"{ac_mv:.2f}mV AC-RMS | {dig_str}")


def save_summary_txt(supply_stats: dict, supply_stats2: dict | None,
                     digital_stats: dict[int, dict],
                     analog_channel: int, analog_channel2: int,
                     duration_s: float, output_prefix: str) -> str:
    """Write a text summary file."""
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 70
    path = f"{output_prefix}_pi.txt"

    lines = [
        sep,
        "  POWER INTEGRITY ANALYSIS REPORT",
        f"  Generated  : {ts}",
        f"  Oscilloscope: Siglent SDS2000X Plus @ {SCOPE_HOST}",
        f"  Capture duration: {duration_s*1000:.1f} ms",
        sep,
        "",
        f"ANALOG CHANNEL CH{analog_channel} — Supply Rail",
        "-" * 40,
        f"  Mean voltage   : {supply_stats['mean_v']:.4f} V",
        f"  Vpp (pk-pk)    : {supply_stats['vpp']*1000:.3f} mV",
        f"  AC RMS noise   : {supply_stats['ac_vrms']*1000:.3f} mV",
        f"  Total RMS      : {supply_stats['total_rms']:.4f} V",
        f"  Vmin / Vmax    : {supply_stats['vmin']:.4f} V / {supply_stats['vmax']:.4f} V",
        f"  Worst glitch   : ±{supply_stats['worst_glitch_v']*1000:.3f} mV from mean",
    ]

    if supply_stats2 is not None:
        lines += [
            "",
            f"ANALOG CHANNEL CH{analog_channel2} — Supply Rail 2",
            "-" * 40,
            f"  Mean voltage   : {supply_stats2['mean_v']:.4f} V",
            f"  Vpp (pk-pk)    : {supply_stats2['vpp']*1000:.3f} mV",
            f"  AC RMS noise   : {supply_stats2['ac_vrms']*1000:.3f} mV",
            f"  Total RMS      : {supply_stats2['total_rms']:.4f} V",
            f"  Vmin / Vmax    : {supply_stats2['vmin']:.4f} V / {supply_stats2['vmax']:.4f} V",
            f"  Worst glitch   : ±{supply_stats2['worst_glitch_v']*1000:.3f} mV from mean",
        ]

    lines += ["", "DIGITAL CHANNEL SWITCHING", "-" * 40]

    for ch in sorted(digital_stats.keys()):
        st = digital_stats[ch]
        rate = st["switching_hz"]
        if rate >= 1e6:
            rate_str = f"{rate/1e6:.3f} MHz"
        elif rate >= 1e3:
            rate_str = f"{rate/1e3:.2f} kHz"
        else:
            rate_str = f"{rate:.1f} Hz"

        lines.append(
            f"  D{ch:<2}  edges: {st['edges']:6d}  "
            f"rate: {rate_str:>12}  "
            f"duty: {st['duty_cycle_pct']:.1f}%"
        )

    lines += ["", sep, ""]
    text = "\n".join(lines)

    with open(path, "w") as f:
        f.write(text)
    return path


def save_csv(analog_wave: np.ndarray, sr_analog: float,
             analog_wave2: np.ndarray | None, sr_analog2: float,
             digital_traces: dict[int, np.ndarray], sr_digital: float,
             analog_channel: int, analog_channel2: int,
             output_prefix: str) -> str:
    """Write aligned time + analog_v + digital columns to CSV."""
    path = f"{output_prefix}_pi.csv"

    n_analog  = len(analog_wave)
    t_analog  = np.arange(n_analog) / sr_analog

    # Digital: resample to analog time grid via nearest-neighbor
    digital_cols: dict[str, np.ndarray] = {}
    for ch, samples in digital_traces.items():
        t_digital = np.arange(len(samples)) / sr_digital
        # Nearest-neighbor resample: find closest digital sample for each analog time point
        interp_idx = np.searchsorted(t_digital, t_analog)
        interp_idx = np.clip(interp_idx, 0, len(samples) - 1)
        digital_cols[f"D{ch}"] = samples[interp_idx].astype(np.uint8)

    # Optional second analog channel (resample to same time base)
    analog2_resampled = None
    if analog_wave2 is not None:
        t_analog2 = np.arange(len(analog_wave2)) / sr_analog2
        interp_idx2 = np.searchsorted(t_analog2, t_analog)
        interp_idx2 = np.clip(interp_idx2, 0, len(analog_wave2) - 1)
        analog2_resampled = analog_wave2[interp_idx2]

    headers = ["time_s", f"CH{analog_channel}_v"]
    if analog2_resampled is not None:
        headers.append(f"CH{analog_channel2}_v")
    headers.extend(sorted(digital_cols.keys()))

    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(headers)
        for i, t in enumerate(t_analog):
            row = [f"{t:.9f}", f"{analog_wave[i]:.6f}"]
            if analog2_resampled is not None:
                row.append(f"{analog2_resampled[i]:.6f}")
            for col_name in sorted(digital_cols.keys()):
                row.append(str(int(digital_cols[col_name][i])))
            w.writerow(row)

    return path


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def generate_plot(
    analog_wave: np.ndarray, sr_analog: float,
    analog_wave2: np.ndarray | None, sr_analog2: float,
    digital_traces: dict[int, np.ndarray], sr_digital: float,
    supply_stats: dict, supply_stats2: dict | None,
    digital_stats: dict[int, dict],
    analog_channel: int, analog_channel2: int,
    output_prefix: str,
) -> str:
    """
    Generate multi-panel power integrity figure:
      - Top panel (taller): analog supply voltage, DC-centered (mV deviation)
      - Optional second panel: second analog rail (if enabled)
      - One panel per digital channel: logic lane
    All panels share the x-axis (time in ms or µs).
    """
    t_analog_ms = np.arange(len(analog_wave)) / sr_analog * 1e3  # milliseconds

    n_digital = len(digital_traces)
    n_analog_panels = 2 if analog_wave2 is not None else 1
    total_panels = n_analog_panels + n_digital

    if total_panels == 0:
        return ""

    # Panel height ratios: analog panels get 3x height of digital
    analog_height  = 3
    digital_height = 1
    height_ratios  = [analog_height] * n_analog_panels + [digital_height] * n_digital

    fig_height = max(4, 1.2 * n_analog_panels * analog_height +
                        0.8 * n_digital * digital_height)
    fig = plt.figure(figsize=(14, fig_height))

    gs = gridspec.GridSpec(total_panels, 1,
                           height_ratios=height_ratios,
                           hspace=0.12)

    # Colors for digital channels
    DIG_COLORS = [
        "#e74c3c", "#3498db", "#2ecc71", "#f39c12",
        "#9b59b6", "#1abc9c", "#e67e22", "#34495e",
        "#d35400", "#27ae60", "#8e44ad", "#16a085",
    ]

    # Panel 0: primary analog supply (DC-centered in mV)
    ax0 = fig.add_subplot(gs[0])
    mean_v   = supply_stats["mean_v"]
    wave_mv  = (analog_wave - mean_v) * 1000.0   # mV deviation from mean

    ax0.plot(t_analog_ms, wave_mv, color="#2c3e50", linewidth=0.6, alpha=0.85)
    ax0.axhline(0, color="gray", linewidth=0.5, linestyle="--", alpha=0.6)

    vpp_mv = supply_stats["vpp"] * 1000.0
    ax0.fill_between(t_analog_ms, wave_mv, 0,
                     where=(wave_mv > 0), color="#e74c3c", alpha=0.18, label="+noise")
    ax0.fill_between(t_analog_ms, wave_mv, 0,
                     where=(wave_mv < 0), color="#3498db", alpha=0.18, label="-noise")

    ax0.set_ylabel("Deviation (mV)", fontsize=8)
    ax0.set_title(
        f"Power Integrity Analysis — "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"CH{analog_channel}: {mean_v:.3f} V mean, {vpp_mv:.2f} mVpp",
        fontsize=10,
    )
    ax0.grid(True, alpha=0.3, axis='both')
    ax0.legend(fontsize=7, loc='upper right')
    ax0.tick_params(labelbottom=False)

    # Panel 1 (optional): second analog supply
    panel_offset = 1
    if analog_wave2 is not None and supply_stats2 is not None:
        t_a2_ms  = np.arange(len(analog_wave2)) / sr_analog2 * 1e3
        mean2_v  = supply_stats2["mean_v"]
        wave2_mv = (analog_wave2 - mean2_v) * 1000.0
        vpp2_mv  = supply_stats2["vpp"] * 1000.0

        ax1 = fig.add_subplot(gs[1], sharex=ax0)
        ax1.plot(t_a2_ms, wave2_mv, color="#27ae60", linewidth=0.6, alpha=0.85)
        ax1.axhline(0, color="gray", linewidth=0.5, linestyle="--", alpha=0.6)
        ax1.set_ylabel("Deviation (mV)", fontsize=8)
        ax1.set_title(f"CH{analog_channel2}: {mean2_v:.3f} V mean, {vpp2_mv:.2f} mVpp",
                      fontsize=9)
        ax1.grid(True, alpha=0.3, axis='both')
        ax1.tick_params(labelbottom=False)
        panel_offset = 2

    # Digital panels
    digital_sorted = sorted(digital_traces.keys())
    for di, ch in enumerate(digital_sorted):
        samples  = digital_traces[ch]
        t_dig_ms = np.arange(len(samples)) / sr_digital * 1e3

        ax = fig.add_subplot(gs[panel_offset + di], sharex=ax0)
        color = DIG_COLORS[di % len(DIG_COLORS)]

        ax.step(t_dig_ms, samples.astype(float), where='post',
                color=color, linewidth=0.8)
        ax.fill_between(t_dig_ms, 0, samples.astype(float),
                        step='post', color=color, alpha=0.25)

        rate   = digital_stats[ch]["switching_hz"]
        if rate >= 1e6:
            rate_str = f"{rate/1e6:.2f} MHz"
        elif rate >= 1e3:
            rate_str = f"{rate/1e3:.1f} kHz"
        elif rate > 0:
            rate_str = f"{rate:.0f} Hz"
        else:
            rate_str = "idle"

        ax.set_ylabel(f"D{ch}\n{rate_str}", fontsize=7, rotation=0,
                      ha='right', va='center', labelpad=28)
        ax.set_ylim(-0.15, 1.35)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["L", "H"], fontsize=6)
        ax.grid(True, alpha=0.3, axis='x')

        is_last = (di == len(digital_sorted) - 1)
        ax.tick_params(labelbottom=is_last)
        if is_last:
            ax.set_xlabel("Time (ms)", fontsize=8)

    # If no digital panels, label x-axis on last analog panel
    if n_digital == 0:
        last_ax = ax0 if analog_wave2 is None else ax1
        last_ax.set_xlabel("Time (ms)", fontsize=8)
        last_ax.tick_params(labelbottom=True)

    path = f"{output_prefix}_pi.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_once(scope: SDS2000X, args: argparse.Namespace,
             capture_num: int) -> tuple[str, str, str]:
    """
    Perform one power integrity capture + analysis cycle.

    Returns: (png_path, csv_path, txt_path)
    """
    digital_channels = [int(c.strip()) for c in args.digital_channels.split(",")]

    # Configure MSO
    scope.digital_enable()
    scope.enable_digital_channels(digital_channels)
    _apply_thresholds(scope, args.threshold_pod0, args.threshold_pod1, digital_channels)

    # Label digital channels on scope display
    for ch in digital_channels:
        scope.set_digital_label(ch, f"D{ch}")

    print(f"  Configuring CH{args.analog_channel} analog, "
          f"digital: {digital_channels} ...", end=" ", flush=True)

    # Capture
    analog_wave, sr_analog, digital_traces, sr_digital = capture_mixed_signal(
        scope,
        analog_channel=args.analog_channel,
        digital_channels=digital_channels,
        duration_s=args.duration_s,
        vdiv=args.vdiv,
    )

    print(f"done  "
          f"(analog: {sr_analog/1e6:.1f} MHz, {len(analog_wave)} pts; "
          f"digital: {sr_digital/1e6:.0f} MHz, "
          f"{len(next(iter(digital_traces.values()))) if digital_traces else 0} pts)")

    # Optional second analog channel
    analog_wave2  = None
    sr_analog2    = sr_analog
    supply_stats2 = None

    if args.analog_channel2 >= 0:
        print(f"  Capturing CH{args.analog_channel2} (second supply) ...",
              end=" ", flush=True)
        # Scope is running again after capture_mixed_signal; read second channel
        try:
            analog_wave2, sr_analog2 = scope.capture_audio(
                channel=args.analog_channel2,
                duration_s=args.duration_s,
                vdiv=args.vdiv,
            )
            print(f"done  ({sr_analog2/1e6:.1f} MHz, {len(analog_wave2)} pts)")
            supply_stats2 = compute_supply_stats(analog_wave2)
        except Exception as exc:
            print(f"warning: {exc}")
            analog_wave2 = None

    # Compute statistics
    supply_stats  = compute_supply_stats(analog_wave)
    digital_stats = compute_digital_stats(digital_traces, sr_digital)

    # Print stats
    if args.stats or not args.continuous:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n  Supply CH{args.analog_channel}:")
        print(f"    Mean    : {supply_stats['mean_v']:.4f} V")
        print(f"    Vpp     : {supply_stats['vpp']*1000:.3f} mVpp")
        print(f"    AC RMS  : {supply_stats['ac_vrms']*1000:.3f} mV")
        print(f"    Glitch  : ±{supply_stats['worst_glitch_v']*1000:.3f} mV")

        if supply_stats2 is not None:
            print(f"  Supply CH{args.analog_channel2}:")
            print(f"    Mean    : {supply_stats2['mean_v']:.4f} V")
            print(f"    Vpp     : {supply_stats2['vpp']*1000:.3f} mVpp")
            print(f"    AC RMS  : {supply_stats2['ac_vrms']*1000:.3f} mV")

        print(f"  Digital switching rates:")
        for ch in sorted(digital_stats.keys()):
            st   = digital_stats[ch]
            rate = st["switching_hz"]
            if rate >= 1e6:
                rate_str = f"{rate/1e6:.3f} MHz"
            elif rate >= 1e3:
                rate_str = f"{rate/1e3:.2f} kHz"
            else:
                rate_str = f"{rate:.1f} Hz"
            print(f"    D{ch}: {st['edges']:5d} edges  {rate_str:>12}  "
                  f"duty {st['duty_cycle_pct']:.1f}%")
        print()

    if args.continuous:
        print_stats(supply_stats, digital_stats, args.analog_channel)

    # Generate output prefix
    if args.output:
        pfx = args.output
    else:
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        pfx = f"pi_{ts}"
    if capture_num > 1:
        pfx = f"{pfx}_{capture_num:04d}"

    # Save outputs
    png_path = ""
    try:
        png_path = generate_plot(
            analog_wave, sr_analog,
            analog_wave2, sr_analog2,
            digital_traces, sr_digital,
            supply_stats, supply_stats2,
            digital_stats,
            args.analog_channel, args.analog_channel2,
            pfx,
        )
    except Exception as exc:
        print(f"  WARNING: plot generation failed ({exc})")

    csv_path = save_csv(
        analog_wave, sr_analog,
        analog_wave2, sr_analog2,
        digital_traces, sr_digital,
        args.analog_channel, args.analog_channel2,
        pfx,
    )

    txt_path = save_summary_txt(
        supply_stats, supply_stats2,
        digital_stats,
        args.analog_channel, args.analog_channel2,
        args.duration_s, pfx,
    )

    return png_path, csv_path, txt_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Power Integrity Analyzer — Siglent SDS2000X Plus MSO + Analog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Captures MSO digital channels simultaneously with an analog supply rail.
The analog and digital captures share the same trigger event, so switching
events on the digital channels are time-aligned with supply voltage glitches.

Examples:
  python power_integrity.py
  python power_integrity.py --digital-channels 0,1,2,3 --analog-channel 1
  python power_integrity.py --digital-channels 0,1 --analog-channel2 2
  python power_integrity.py --vdiv 0.05 --duration-s 0.02 --stats
  python power_integrity.py --threshold-pod0 lvcmos33 --threshold-pod1 ttl
  python power_integrity.py --continuous
  python power_integrity.py --stats --continuous
""",
    )

    parser.add_argument("--scope-host", default=SCOPE_HOST, metavar="HOST",
                        help=f"Oscilloscope IP address (default: {SCOPE_HOST})")
    parser.add_argument("--digital-channels", default=DEFAULT_CHANNELS, metavar="LIST",
                        help=f"Comma-separated digital channels (default: {DEFAULT_CHANNELS})")
    parser.add_argument("--analog-channel", type=int, default=1, metavar="N",
                        help="Analog channel for primary supply rail (default: 1)")
    parser.add_argument("--analog-channel2", type=int, default=-1, metavar="N",
                        help="Analog channel for optional second supply rail (default: -1 = disabled)")
    parser.add_argument("--duration-s", type=float, default=DEFAULT_DURATION, metavar="S",
                        help=f"Capture duration in seconds (default: {DEFAULT_DURATION})")
    parser.add_argument("--vdiv", type=float, default=None, metavar="VOLTS",
                        help="Vertical scale V/div (default: auto-range)")
    parser.add_argument("--threshold", default="lvcmos33",
                        choices=["ttl", "cmos", "lvcmos33", "lvcmos25"],
                        help="Default logic threshold for both pods (default: lvcmos33)")
    parser.add_argument("--threshold-pod0", default=None, metavar="THRESHOLD",
                        help="Threshold for D0-D7 pod (overrides --threshold; name or voltage)")
    parser.add_argument("--threshold-pod1", default=None, metavar="THRESHOLD",
                        help="Threshold for D8-D15 pod (overrides --threshold; name or voltage)")
    parser.add_argument("--trigger-on-edge", type=int, default=None, metavar="CH",
                        help="Digital channel to use as trigger source (not yet implemented — note only)")
    parser.add_argument("--output", default=None, metavar="PREFIX",
                        help="Output filename prefix (default: timestamped)")
    parser.add_argument("--stats", action="store_true",
                        help="Print detailed statistics after capture")
    parser.add_argument("--continuous", action="store_true",
                        help="Keep capturing and printing statistics until Ctrl+C")

    args = parser.parse_args()

    # Resolve per-pod thresholds: explicit override > global threshold
    if args.threshold_pod0 is None:
        args.threshold_pod0 = args.threshold
    if args.threshold_pod1 is None:
        args.threshold_pod1 = args.threshold

    if args.trigger_on_edge is not None:
        print(f"NOTE: --trigger-on-edge D{args.trigger_on_edge} noted — "
              f"digital trigger source is not yet implemented in this script; "
              f"using free-run trigger.")

    scope = None
    try:
        print(f"Connecting to oscilloscope at {args.scope_host} ...")
        scope = SDS2000X(args.scope_host)
        idn   = scope.identify()
        print(f"Instrument: {idn}")

        digital_channels = [int(c.strip()) for c in args.digital_channels.split(",")]
        print(f"Analog channel  : CH{args.analog_channel}"
              + (f" + CH{args.analog_channel2}" if args.analog_channel2 >= 0 else ""))
        print(f"Digital channels: {digital_channels}")
        print(f"Thresholds      : pod0={args.threshold_pod0}, pod1={args.threshold_pod1}")
        print(f"Duration        : {args.duration_s*1000:.1f} ms")
        print()

        if args.continuous:
            print("Continuous mode — press Ctrl+C to stop.\n")
            n = 0
            while True:
                n += 1
                png_path, csv_path, txt_path = run_once(scope, args, n)
                if not args.continuous or args.stats:
                    if png_path:
                        print(f"  PNG → {png_path}")
                    if csv_path:
                        print(f"  CSV → {csv_path}")
                    if txt_path:
                        print(f"  TXT → {txt_path}")
                time.sleep(CONTINUOUS_INTERVAL)
        else:
            print("[Capture]")
            png_path, csv_path, txt_path = run_once(scope, args, 1)
            if png_path:
                print(f"\nPNG → {png_path}")
            if csv_path:
                print(f"CSV → {csv_path}")
            if txt_path:
                print(f"TXT → {txt_path}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
    except ConnectionRefusedError:
        print(f"\nCannot connect to {args.scope_host}:5025")
        print("Verify the oscilloscope is powered on and SCPI/LAN is enabled.")
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
        if scope is not None:
            try:
                scope.digital_disable()
                scope.run()
            except Exception:
                pass
            scope.close()


if __name__ == "__main__":
    main()
