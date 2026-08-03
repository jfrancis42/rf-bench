#!/usr/bin/env python3
"""
Eye Diagram Builder — SDS2000X scope

Captures N triggered waveforms of a serial signal, time-aligns each to the
first zero crossing, and overlays them all to produce an eye diagram.
Shows eye height, eye width, and crossing point statistics.

Usage:
  python scope_eye.py --baud 115200 --captures 200
  python scope_eye.py --baud 1000000 --channel 2 --captures 500 --plot eye.png
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))

from rf_bench.siglent import SDS2000X  # noqa: E402
from rf_bench import connect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SCOPE_HOST = None  # Now uses inventory
DEFAULT_CHANNEL    = 1
DEFAULT_CAPTURES   = 200
DEFAULT_THRESHOLD  = 0.0   # V — trigger and crossing level

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C — stopping capture, plotting what was captured ...]")


signal.signal(signal.SIGINT, _sigint_handler)

# ---------------------------------------------------------------------------
# Crossing detection
# ---------------------------------------------------------------------------

def find_first_crossing(t: np.ndarray, v: np.ndarray,
                        threshold: float = 0.0) -> float | None:
    """
    Find time of first upward-going zero crossing using linear interpolation.
    Returns time in seconds, or None if no crossing found.
    """
    for i in range(len(v) - 1):
        if v[i] < threshold <= v[i + 1]:
            # Linear interpolation
            frac = (threshold - v[i]) / (v[i + 1] - v[i])
            return float(t[i] + frac * (t[i + 1] - t[i]))
    return None


# ---------------------------------------------------------------------------
# Eye diagram construction
# ---------------------------------------------------------------------------

def build_eye(waveforms: list[np.ndarray], sample_rate: float,
              bit_period_s: float, threshold: float) -> dict:
    """
    Align waveforms to first crossing and stack two bit periods for the eye.

    Returns dict with aligned traces array and eye metrics.
    """
    eye_window = 2.0 * bit_period_s   # show 2 UI
    n_eye_pts  = max(256, int(eye_window * sample_rate))
    eye_time   = np.linspace(0, eye_window, n_eye_pts)

    aligned: list[np.ndarray] = []
    crossings: list[float]    = []

    for wave in waveforms:
        n = len(wave)
        t = np.arange(n) / sample_rate
        cross_t = find_first_crossing(t, wave, threshold)
        if cross_t is None:
            continue
        crossings.append(cross_t)
        # Interpolate waveform onto eye_time grid aligned at crossing
        t_shifted = t - cross_t
        # Wrap into eye_window using modulo — tile two periods
        aligned_wave = np.interp(eye_time % eye_window,
                                 (t_shifted % eye_window + eye_window) % eye_window,
                                 wave, left=np.nan, right=np.nan)
        aligned.append(aligned_wave)

    if not aligned:
        return {}

    stack = np.array(aligned)  # shape: (n_captures, n_eye_pts)

    # Eye metrics at UI=0.5 (mid-eye)
    mid_idx  = np.searchsorted(eye_time, bit_period_s)
    mid_col  = stack[:, mid_idx]
    mid_col  = mid_col[np.isfinite(mid_col)]

    eye_high = float(np.percentile(mid_col, 5))   # bottom of upper rail
    eye_low  = float(np.percentile(mid_col, 95))  # top of lower rail
    eye_height = eye_high - eye_low

    # Eye width: find time span where all traces are above threshold or below
    # (simple: fraction of time axis where 5th/95th percentile are on same side)
    col_5  = np.nanpercentile(stack, 5,  axis=0)
    col_95 = np.nanpercentile(stack, 95, axis=0)
    eye_open = (col_95 < threshold) | (col_5 > threshold)
    eye_width_frac = float(np.mean(eye_open))

    return {
        'eye_time': eye_time,
        'stack':    stack,
        'bit_period_s': bit_period_s,
        'eye_height_v': eye_height,
        'eye_width_frac': eye_width_frac,
        'n_captured': len(aligned),
        'crossing_t_mean': float(np.mean(crossings)) if crossings else 0.0,
    }


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def save_eye_plot(eye: dict, threshold: float, baud: int, output_path: str) -> None:
    """Render eye diagram with overlay of all aligned traces."""
    stack    = eye['stack']
    eye_time = eye['eye_time'] * 1e6  # → µs
    bit_us   = eye['bit_period_s'] * 1e6

    fig, ax = plt.subplots(figsize=(10, 6))

    for row in stack:
        ax.plot(eye_time, row, color='lime', alpha=0.05, linewidth=0.5)

    ax.axhline(threshold, color='cyan', linewidth=0.8, linestyle='--', label=f'Threshold {threshold:+.2f} V')
    ax.axvline(bit_us,    color='white', linewidth=0.5, linestyle=':')

    ax.set_facecolor('black')
    fig.patch.set_facecolor('#1a1a1a')
    ax.set_xlabel("Time (µs)", fontsize=10, color='white')
    ax.set_ylabel("Voltage (V)", fontsize=10, color='white')
    ax.tick_params(colors='white', labelsize=9)
    for spine in ax.spines.values():
        spine.set_color('gray')

    title = (f"Eye Diagram — {baud:,} baud   "
             f"N={eye['n_captured']} captures\n"
             f"Eye height: {eye['eye_height_v']*1000:.1f} mV   "
             f"Eye width: {eye['eye_width_frac']*100:.1f}% UI")
    ax.set_title(title, fontsize=10, color='white')
    ax.legend(fontsize=8, facecolor='#333333', labelcolor='white')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Eye diagram builder — SDS2000X scope",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scope_eye.py --baud 115200 --captures 200
  python scope_eye.py --baud 1000000 --channel 2 --captures 500 --plot eye.png
  python scope_eye.py --baud 9600 --threshold 1.65 --captures 100
""",
    )
    parser.add_argument("--scope",    default=DEFAULT_SCOPE_HOST, metavar="HOST",
                        help=f"SDS2000X IP address (default {DEFAULT_SCOPE_HOST})")
    parser.add_argument("--channel",  type=int, default=DEFAULT_CHANNEL, metavar="N",
                        help=f"Scope channel (default {DEFAULT_CHANNEL})")
    parser.add_argument("--captures", type=int, default=DEFAULT_CAPTURES, metavar="N",
                        help=f"Number of waveforms to capture (default {DEFAULT_CAPTURES})")
    parser.add_argument("--baud",     type=int, required=True, metavar="N",
                        help="Signal baud rate — sets timebase (required)")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, metavar="V",
                        help=f"Trigger/crossing threshold in V (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--plot",     default=None, metavar="FILE",
                        help="Output PNG path (default: timestamped)")

    args = parser.parse_args()

    bit_period_s = 1.0 / args.baud
    # Show 1.5 bit periods total; timebase = 1.5*bit_period / 10 divisions
    timebase_s   = (1.5 * bit_period_s) / 10.0

    if args.plot is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.plot = f"eye_{ts}_{args.baud}baud.png"

    print(f"Connecting to SDS2000X via inventory ...")
    scope = None
    try:
        scope = connect(args.scope or 'sds')
        print(f"  {scope.identify()}")

        # Configure scope
        print(f"  Timebase: {timebase_s*1e6:.3f} µs/div  "
              f"(1 bit = {bit_period_s*1e6:.3f} µs)")
        scope.set_timebase(timebase_s)
        scope.set_trigger_edge(f"C{args.channel}", args.threshold, slope='rising')

        waveforms:   list[np.ndarray] = []
        sample_rate: float = 1.0

        print(f"\n  Capturing {args.captures} waveforms on CH{args.channel} ...")
        for i in range(args.captures):
            if not _running:
                break
            try:
                scope.arm_trigger()
                wave, sr = scope.capture_waveform(args.channel)
                waveforms.append(wave)
                sample_rate = sr
                print(f"  [{i+1:4d}/{args.captures}]  {len(wave)} pts  "
                      f"SR={sr/1e6:.0f} MSa/s", end='\r', flush=True)
            except Exception as exc:
                print(f"\n  [capture error: {exc}]")
                time.sleep(0.1)

        print(f"\n  Captured {len(waveforms)} waveforms.")

        if len(waveforms) < 2:
            print("  Not enough waveforms for eye diagram.")
            sys.exit(1)

        print("  Building eye diagram ...")
        eye = build_eye(waveforms, sample_rate, bit_period_s, args.threshold)

        if not eye:
            print("  No crossing found in any waveform — check threshold and signal.")
            sys.exit(1)

        print(f"  Eye height : {eye['eye_height_v']*1000:.1f} mV")
        print(f"  Eye width  : {eye['eye_width_frac']*100:.1f}% UI")
        print(f"  Aligned    : {eye['n_captured']} / {len(waveforms)} captures")

        save_eye_plot(eye, args.threshold, args.baud, args.plot)
        print(f"\n  Plot saved → {args.plot}")

    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to scope: {exc}")
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
                scope.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
