#!/usr/bin/env python3
"""
Oscillator Stability Analyzer — Siglent SSA3000X (+ optional SDG1000X)

Measures frequency vs. time of any signal source using SSA narrow-span
peak/centroid tracking, then computes the Allan deviation (ADEV) σ_y(τ)
at multiple tau values.  Identifies oscillator noise types from the ADEV
slope.

Source modes:
  --source sdg  (default)  SDG CH1 → SSA RF In (SDG configured at --freq)
  --source ext             External source → SSA RF In (SDG not used)

Usage:
  python osc_stability.py --freq 14000
  python osc_stability.py --freq 10000 --duration 3600 --interval 1.0
  python osc_stability.py --freq 100 --duration 300 --source sdg
  python osc_stability.py --plot stability_20260527_120000.npz
"""

import argparse
import json
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

from rf_bench.siglent import SSA3000X, SDG1000X          # noqa: E402
from rf_bench.utils import (                              # noqa: E402
    format_freq, format_freq_short, nearest_rbw, adev_multi_tau,
)
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SSA_HOST         = None  # Now uses inventory
DEFAULT_SDG_HOST         = None  # Now uses inventory
DEFAULT_FREQ_KHZ         = 10_000      # 10 MHz
DEFAULT_DURATION_S       = 300         # 5 minutes
DEFAULT_INTERVAL_S       = 1.0         # 1 sample per second
DEFAULT_CARRIER_LEVEL_DBM = -10.0      # SDG output level
SSA_MIN_FREQ_HZ          = 9_000       # SSA3032X Plus minimum
SSA_POINTS               = 201         # trace points for narrow span


# ---------------------------------------------------------------------------
# SSA narrow-span centroid frequency measurement
# ---------------------------------------------------------------------------

def measure_carrier_freq(ssa: SSA3000X,
                         freq_hz: float,
                         span_hz: float) -> float:
    """
    Measure the carrier frequency using weighted centroid on the SSA trace.

    Configures a narrow span centered on freq_hz, triggers a single sweep,
    and returns the power-weighted mean frequency (sub-bin resolution).
    """
    start_hz = max(SSA_MIN_FREQ_HZ, int(freq_hz - span_hz / 2))
    stop_hz  = int(freq_hz + span_hz / 2)
    ssa.setup_band(start_hz, stop_hz, SSA_POINTS)
    ssa.single_sweep()
    trace    = ssa.get_trace()
    n        = len(trace)
    freqs    = np.linspace(start_hz, stop_hz, n)
    # Weighted centroid — gives sub-bin resolution when SNR is high
    power_lin = 10.0 ** (trace / 10.0)
    f_centroid = float(np.average(freqs, weights=power_lin))
    return f_centroid


# ---------------------------------------------------------------------------
# Measurement loop
# ---------------------------------------------------------------------------

def run_measurement(ssa: SSA3000X,
                    freq_hz: float,
                    span_hz: float,
                    duration_s: float,
                    interval_s: float) -> tuple[list[float], list[float]]:
    """
    Sample the carrier frequency until duration_s is reached.

    Returns (timestamps, freq_readings) with timestamps in absolute
    epoch seconds.
    """
    timestamps    = []
    freq_readings = []

    print(f"\n[FREQUENCY TRACKING]")
    print(f"  Carrier   : {format_freq_short(freq_hz)}")
    print(f"  Span      : {span_hz:.0f} Hz")
    print(f"  Duration  : {duration_s:.0f} s")
    print(f"  Interval  : {interval_s:.2f} s")
    print(f"  Max samples: {int(duration_s / interval_s) + 1}")
    print()

    t_start = time.time()
    while True:
        t0 = time.time()
        if t0 - t_start >= duration_s:
            break

        try:
            f_meas = measure_carrier_freq(ssa, freq_hz, span_hz)
        except Exception as exc:
            print(f"\n  WARNING: measurement failed: {exc}")
            time.sleep(interval_s)
            continue

        timestamps.append(time.time())
        freq_readings.append(f_meas)

        elapsed = timestamps[-1] - t_start
        dev_hz  = f_meas - freq_hz
        n       = len(freq_readings)
        print(f"\r  [{elapsed:6.0f}s]  samples={n:5d}  "
              f"f={f_meas:.3f} Hz  dev={dev_hz:+.3f} Hz    ",
              end='', flush=True)

        dt = time.time() - t0
        sleep_time = max(0.0, interval_s - dt)
        if sleep_time > 0:
            time.sleep(sleep_time)

    print()  # newline after carriage-return progress
    return timestamps, freq_readings


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def generate_plot(timestamps: list[float],
                  freq_readings: list[float],
                  f_nominal_hz: float,
                  taus: np.ndarray,
                  adevs: np.ndarray,
                  output_prefix: str) -> str:
    """Generate two-panel stability plot.  Returns saved file path."""
    t_arr  = np.array(timestamps)
    f_arr  = np.array(freq_readings)
    t_zero = t_arr - t_arr[0]           # elapsed seconds
    dev_hz = f_arr - f_nominal_hz

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 9))
    ts_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    fig.suptitle(
        f"Oscillator Stability  —  {ts_str}\n"
        f"Nominal: {format_freq_short(f_nominal_hz)}   "
        f"Samples: {len(freq_readings)}   "
        f"Duration: {t_zero[-1]:.0f} s",
        fontsize=11,
    )

    # --- Panel 1: frequency deviation vs time ---
    ax1.plot(t_zero, dev_hz, color='#1f77b4', linewidth=1.0, alpha=0.85)
    ax1.axhline(0.0, color='gray', linestyle='--', linewidth=0.8)

    mean_dev = float(np.mean(dev_hz))
    std_dev  = float(np.std(dev_hz))
    ax1.axhline(mean_dev, color='darkorange', linestyle='--', linewidth=0.9,
                label=f'Mean offset {mean_dev:+.3f} Hz')

    textstr = (f"Mean dev: {mean_dev:+.3f} Hz\n"
               f"Std dev:  {std_dev:.3f} Hz\n"
               f"Peak-peak: {float(np.max(dev_hz) - np.min(dev_hz)):.3f} Hz")
    ax1.text(0.02, 0.97, textstr, transform=ax1.transAxes,
             fontsize=8, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    ax1.set_xlabel("Elapsed time (s)", fontsize=10)
    ax1.set_ylabel("Frequency deviation (Hz)", fontsize=10)
    ax1.set_title("Carrier Frequency Deviation vs. Time", fontsize=10)
    ax1.legend(fontsize=8, loc='upper right')
    ax1.grid(True, alpha=0.35)
    ax1.tick_params(labelsize=9)

    # --- Panel 2: Allan deviation log-log ---
    if len(taus) >= 2:
        ax2.loglog(taus, adevs, 'o-', color='#d62728', linewidth=1.5,
                   markersize=5, label='ADEV σ_y(τ)')

        # Reference slope lines: -1 (white PM noise) and +0.5 (random walk FM)
        tau_ref = taus[len(taus) // 2]
        adev_ref = float(np.interp(tau_ref, taus, adevs))
        # slope -1 guide: sigma = A / tau
        tau_slope = np.array([taus[0], taus[-1]])
        ax2.loglog(tau_slope,
                   adev_ref * (tau_ref / tau_slope),
                   'k--', linewidth=0.7, alpha=0.4, label='slope −1 (white PM)')
        # slope +0.5 guide: sigma = B * sqrt(tau)
        ax2.loglog(tau_slope,
                   adev_ref * np.sqrt(tau_slope / tau_ref),
                   'k:', linewidth=0.7, alpha=0.4, label='slope +½ (RW FM)')

        # Annotate ADEV floor
        idx_min = int(np.argmin(adevs))
        tau_floor  = float(taus[idx_min])
        adev_floor = float(adevs[idx_min])
        ax2.plot(tau_floor, adev_floor, 'r*', markersize=14, zorder=5)
        ax2.annotate(
            f"floor σ_y = {adev_floor:.2e}\n@ τ = {tau_floor:.1f} s",
            xy=(tau_floor, adev_floor),
            xytext=(tau_floor * 2.0, adev_floor * 2.0),
            fontsize=8, color='red',
            arrowprops=dict(arrowstyle='->', color='red', lw=0.8),
        )

        ax2.set_xlabel("Averaging time τ (s)", fontsize=10)
        ax2.set_ylabel("Allan deviation σ_y(τ)", fontsize=10)
        ax2.set_title("Allan Deviation (ADEV)", fontsize=10)
        ax2.legend(fontsize=8, loc='best')
        ax2.grid(True, which='both', alpha=0.30)
        ax2.tick_params(labelsize=9)
    else:
        ax2.text(0.5, 0.5, 'Insufficient data for ADEV\n(need ≥ 4 samples)',
                 transform=ax2.transAxes, ha='center', va='center', fontsize=12,
                 color='gray')
        ax2.set_title("Allan Deviation (ADEV)", fontsize=10)

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    path = f"{output_prefix}.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def generate_plot_from_npz(npz_path: str, output_prefix: str) -> str:
    """Load saved .npz and regenerate plots."""
    data = np.load(npz_path)
    timestamps    = data['timestamps'].tolist()
    freq_readings = data['freq_readings'].tolist()
    f_nominal_hz  = float(data['f_nominal_hz'])
    sample_interval_s = float(data['sample_interval_s'])

    taus, adevs = adev_multi_tau(freq_readings, f_nominal_hz, sample_interval_s)
    return generate_plot(timestamps, freq_readings, f_nominal_hz,
                         taus, adevs, output_prefix)


# ---------------------------------------------------------------------------
# Text summary
# ---------------------------------------------------------------------------

def save_txt(timestamps: list[float],
             freq_readings: list[float],
             f_nominal_hz: float,
             taus: np.ndarray,
             adevs: np.ndarray,
             sample_interval_s: float,
             output_prefix: str) -> str:
    """Write a plain-text summary.  Returns path."""
    path = f"{output_prefix}.txt"
    f_arr  = np.array(freq_readings)
    dev_hz = f_arr - f_nominal_hz

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sep = '=' * 72

    lines = [
        sep,
        '  OSCILLATOR STABILITY ANALYSIS',
        f'  Generated     : {now}',
        f'  Nominal freq  : {format_freq(f_nominal_hz)}',
        f'  Total samples : {len(freq_readings)}',
        f'  Duration      : {timestamps[-1] - timestamps[0]:.1f} s',
        f'  Sample interval: {sample_interval_s:.3f} s',
        sep,
        '',
        f'  Mean frequency   : {float(np.mean(f_arr)):.6f} Hz',
        f'  Mean offset      : {float(np.mean(dev_hz)):+.6f} Hz',
        f'  Std deviation    : {float(np.std(dev_hz)):.6f} Hz',
        f'  Peak-peak dev    : {float(np.max(dev_hz) - np.min(dev_hz)):.6f} Hz',
        f'  Fractional freq  : {float(np.std(dev_hz)) / f_nominal_hz:.3e}',
        '',
    ]

    if len(taus) >= 2:
        idx_min    = int(np.argmin(adevs))
        tau_floor  = float(taus[idx_min])
        adev_floor = float(adevs[idx_min])
        lines += [
            f'  ADEV floor       : σ_y = {adev_floor:.3e}  @ τ = {tau_floor:.2f} s',
            '',
            f'  {"τ (s)":>10}  {"σ_y":>12}',
            '  ' + '-' * 26,
        ]
        for tau, adev in zip(taus, adevs):
            lines.append(f'  {tau:>10.2f}  {adev:>12.3e}')
    else:
        lines.append('  ADEV: insufficient data (need ≥ 4 samples)')

    text = '\n'.join(lines) + '\n'
    with open(path, 'w') as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Oscillator Stability Analyzer — ADEV via SSA narrow-span tracking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup:
  SDG mode (default): SDG CH1 OUT → SSA RF In
  Ext mode:           Any source → SSA RF In

The SSA tracks the carrier frequency using a power-weighted centroid over a
narrow span (~1 kHz or 0.01 %% of carrier frequency).  Allan deviation is
computed at all valid tau values up to duration/4.

Examples:
  python osc_stability.py --freq 14000                       # 14 MHz, 5 min
  python osc_stability.py --freq 10000 --duration 3600       # 10 MHz, 1 hour
  python osc_stability.py --freq 100 --source ext            # 100 kHz, external
  python osc_stability.py --plot stability_20260527.npz      # replot saved data
""",
    )

    parser.add_argument('--freq', type=float, default=DEFAULT_FREQ_KHZ,
                        metavar='KHZ',
                        help=f'Nominal carrier frequency in kHz (default {DEFAULT_FREQ_KHZ})')
    parser.add_argument('--ssa', default=DEFAULT_SSA_HOST, metavar='HOST',
                        help=f'SSA IP address (default {DEFAULT_SSA_HOST})')
    parser.add_argument('--sdg', default=DEFAULT_SDG_HOST, metavar='HOST',
                        help=f'SDG IP address (default {DEFAULT_SDG_HOST})')
    parser.add_argument('--source', choices=['sdg', 'ext'], default='sdg',
                        help='Signal source: sdg (configure SDG CH1) or ext (external)')
    parser.add_argument('--carrier-level', type=float,
                        default=DEFAULT_CARRIER_LEVEL_DBM, metavar='DBM',
                        help=f'SDG output level in dBm (default {DEFAULT_CARRIER_LEVEL_DBM})')
    parser.add_argument('--duration', type=float, default=DEFAULT_DURATION_S,
                        metavar='S',
                        help=f'Measurement duration in seconds (default {DEFAULT_DURATION_S})')
    parser.add_argument('--interval', type=float, default=DEFAULT_INTERVAL_S,
                        metavar='S',
                        help=f'Target measurement interval in seconds (default {DEFAULT_INTERVAL_S})')
    parser.add_argument('--span', type=float, default=None, metavar='HZ',
                        help='SSA span around carrier in Hz (default: auto)')
    parser.add_argument('--output', default=None, metavar='PREFIX',
                        help='Output filename prefix (default: timestamped)')
    parser.add_argument('--plot', default=None, metavar='FILE',
                        help='Load a saved .npz file and regenerate plots')

    args = parser.parse_args()

    # --- Re-plot mode ---
    if args.plot is not None:
        if args.output is None:
            base = os.path.splitext(args.plot)[0]
            args.output = base + '_replot'
        print(f"Loading {args.plot} ...")
        try:
            png_path = generate_plot_from_npz(args.plot, args.output)
            print(f"Plot  → {png_path}")
        except Exception as exc:
            print(f"Error: {exc}")
            sys.exit(1)
        return

    # --- Normal measurement mode ---
    freq_hz = args.freq * 1_000.0

    if freq_hz < SSA_MIN_FREQ_HZ:
        print(f"Error: --freq {args.freq} kHz is below SSA minimum "
              f"({SSA_MIN_FREQ_HZ / 1000:.0f} kHz)")
        sys.exit(1)

    # Auto-select span: 1 kHz minimum, or 0.01% of carrier, whichever is larger
    if args.span is not None:
        span_hz = args.span
    else:
        span_hz = max(1_000.0, freq_hz * 0.0001)

    if args.output is None:
        ts_str    = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.output = f"osc_stability_{ts_str}"

    print(f"\n[OSCILLATOR STABILITY ANALYZER]")
    print(f"  Carrier   : {format_freq_short(freq_hz)}")
    print(f"  Span      : {span_hz:.0f} Hz  (auto)")
    print(f"  Source    : {args.source.upper()}")
    print(f"  Duration  : {args.duration:.0f} s")
    print(f"  Interval  : {args.interval:.2f} s")
    print(f"  Output    : {args.output}.{{npz,png,txt}}")

    ssa = sdg = None
    try:
        print(f"\nConnecting to SSA via inventory ...")
        ssa = connect(args.ssa or 'ssa')
        print(f"  {ssa.identify()}")

        if args.source == 'sdg':
            print(f"Connecting to SDG via inventory ...")
            sdg = connect(args.sdg or 'sdg')
            print(f"  {sdg.identify()}")
            sdg.set_sine(1, freq_hz, args.carrier_level)
            sdg.output_on(1)
            print(f"  SDG CH1: {format_freq_short(freq_hz)} "
                  f"@ {args.carrier_level:+.1f} dBm  [ON]")
            time.sleep(0.3)  # let SDG stabilise

        # Disable TG — we don't want it interfering
        ssa.disable_tracking_generator()

        # Run the measurement
        timestamps, freq_readings = run_measurement(
            ssa, freq_hz, span_hz, args.duration, args.interval
        )

        if len(freq_readings) < 2:
            print("Error: fewer than 2 samples collected — cannot compute ADEV.")
            sys.exit(1)

        # Actual sample interval from timing data
        n_samp            = len(timestamps)
        sample_interval_s = (timestamps[-1] - timestamps[0]) / (n_samp - 1)

        print(f"\n  Collected {n_samp} samples  "
              f"(actual interval {sample_interval_s:.3f} s)")

        # Compute ADEV
        taus, adevs = adev_multi_tau(freq_readings, freq_hz, sample_interval_s)
        if len(taus) >= 2:
            idx_floor  = int(np.argmin(adevs))
            print(f"  ADEV floor: {float(adevs[idx_floor]):.3e}  "
                  f"@ τ = {float(taus[idx_floor]):.1f} s")

        # Save outputs
        print("\n[SAVING RESULTS]")

        npz_path = f"{args.output}.npz"
        np.savez(npz_path,
                 timestamps=np.array(timestamps),
                 freq_readings=np.array(freq_readings),
                 f_nominal_hz=np.float64(freq_hz),
                 sample_interval_s=np.float64(sample_interval_s))
        print(f"Data  → {npz_path}")

        txt_path = save_txt(timestamps, freq_readings, freq_hz,
                            taus, adevs, sample_interval_s, args.output)
        print(f"Text  → {txt_path}")

        try:
            png_path = generate_plot(timestamps, freq_readings, freq_hz,
                                     taus, adevs, args.output)
            print(f"Plot  → {png_path}")
        except Exception as exc:
            print(f"Plot failed: {exc}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        # Try to save partial data if we have any
        if 'timestamps' in dir() and len(timestamps) >= 2:
            print("Saving partial data ...")
            try:
                n_samp            = len(timestamps)
                sample_interval_s = (timestamps[-1] - timestamps[0]) / (n_samp - 1)
                taus, adevs       = adev_multi_tau(freq_readings, freq_hz,
                                                    sample_interval_s)
                npz_path = f"{args.output}_partial.npz"
                np.savez(npz_path,
                         timestamps=np.array(timestamps),
                         freq_readings=np.array(freq_readings),
                         f_nominal_hz=np.float64(freq_hz),
                         sample_interval_s=np.float64(sample_interval_s))
                print(f"Partial data → {npz_path}")
            except Exception:
                pass
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to instrument: {exc}")
        print("Verify instruments are powered on and SCPI/LAN is enabled.")
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
        if sdg is not None:
            try:
                sdg.output_off_all()
                sdg.close()
            except Exception:
                pass
        if ssa is not None:
            try:
                ssa.disconnect()
            except Exception:
                pass


if __name__ == '__main__':
    main()
