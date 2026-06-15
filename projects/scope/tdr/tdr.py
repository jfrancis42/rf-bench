#!/usr/bin/env python3
"""
tdr.py — Time-Domain Reflectometer

Locates impedance discontinuities in coaxial cables by launching a fast
step edge and measuring the round-trip delay to any echoes.

Physical setup:
    Source → SMA T-splitter ─┬── CH1 (monitors launch edge)
                              └── Coax cable under test ── open/short/load

Source selection:
    SDG1062X (--source sdg, default) — 60 MHz, ~3.5 ns rise time
    SDS2504X Plus built-in AWG (--source awg) — 25 MHz, ~14 ns rise time

    SDG is strongly preferred. The rise time determines TDR resolution:
        SDG  ~3.5 ns rise:  ~35 cm resolution at VF=0.66
        AWG  ~14 ns rise:  ~138 cm resolution at VF=0.66

Usage examples:
    python tdr.py                              # RG-58, SDG, 100 m max
    python tdr.py --cable-type lmr400          # LMR-400 preset (VF=0.85)
    python tdr.py --vf 0.82 --max-length-m 50 # custom VF, 50 m cable
    python tdr.py --source awg --averages 32   # AWG source, more averaging
"""

import argparse
import csv as csv_module
import math
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.siglent import SDG1000X, SDS2000X          # noqa: E402
from rf_bench.utils import format_freq_short              # noqa: E402
from rf_bench import connect

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_SDG_HOST    = None  # Now uses inventory
DEFAULT_SCOPE_HOST  = None  # Now uses inventory
DEFAULT_VF          = 0.66   # RG-58 / RG-8 / RG-213
DEFAULT_MAX_LENGTH  = 100.0  # metres
DEFAULT_FREQ_SDG    = 10_000_000   # 10 MHz
DEFAULT_FREQ_AWG    =  5_000_000   #  5 MHz
DEFAULT_AVERAGES    = 16
DEFAULT_AMPLITUDE   = 1.0    # Vpp — enough for clear edges; won't damage 50 Ω loads
SCOPE_CHANNEL       = 1      # CH1 monitors the launch edge

# Cable type presets: (velocity_factor, description)
CABLE_PRESETS = {
    "rg58":   (0.66, "RG-58 (VF=0.66)"),
    "rg8":    (0.66, "RG-8 (VF=0.66)"),
    "rg213":  (0.66, "RG-213 (VF=0.66)"),
    "lmr400": (0.85, "LMR-400 (VF=0.85)"),
    "lmr240": (0.84, "LMR-240 (VF=0.84)"),
    "custom": (None, "Custom — use --vf"),
}

# Reflection classifier thresholds (normalised to initial step height)
FAULT_THRESHOLD_FRACTION = 0.05   # secondary edges ≥ 5% of initial edge height


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolution_m(rise_time_ns: float, velocity_factor: float) -> float:
    """Spatial resolution in metres from rise time and velocity factor."""
    c = 3e8  # m/s
    return rise_time_ns * 1e-9 * velocity_factor * c / 2.0


def classify_reflection(delta: float, initial_step: float) -> str:
    """
    Classify a reflected edge as open, short, or partial.

    delta:         derivative value at the fault location
    initial_step:  derivative value at the launch edge (positive)
    """
    ratio = delta / abs(initial_step) if abs(initial_step) > 1e-12 else 0.0
    if ratio > 0.5:
        return "open circuit"
    elif ratio < -0.5:
        return "short circuit"
    elif ratio > 0:
        return f"partial (higher impedance, {ratio*100:.0f}% reflection)"
    else:
        return f"partial (lower impedance, {abs(ratio)*100:.0f}% reflection)"


def capture_averaged(scope: SDS2000X, channel: int, duration_s: float,
                     vdiv: float, averages: int) -> tuple[np.ndarray, float]:
    """
    Capture N waveforms and return the averaged result.

    For TDR, DC coupling is required — we must see the actual step transition,
    not an AC-coupled derivative.  We set DC coupling explicitly via SCPI.
    """
    ch_str = f"C{channel}"
    sum_wave = None
    sample_rate_hz = 0.0

    for i in range(averages):
        # Stop scope, configure DC coupling and V/div, then arm
        scope.stop()
        time.sleep(0.05)
        scope._cmd(f"{ch_str}:CPL D1M")    # DC coupling, 1 MΩ
        scope._cmd(f"{ch_str}:VDIV {vdiv:.4f}V")
        tdiv = duration_s / 10.0
        scope._cmd(f"TDIV {tdiv:.6f}S")
        scope._cmd("TRMD AUTO")
        scope.run()
        time.sleep(duration_s + 0.5)
        scope.stop()
        time.sleep(0.15)

        scope._cmd(f":WAVeform:SOURce {ch_str}")
        scope._cmd(":WAVeform:FORMat BYTE")
        scope._cmd(":WAVeform:POINt MAX")

        pre = scope._read_binary_block(":WAVeform:PREamble?")
        horiz_interval, vgain, voffset = scope._parse_wavedesc(pre)
        raw = scope._read_binary_block(":WAVeform:DATA?")
        if not raw:
            raise RuntimeError(f"Waveform data empty on capture {i+1}")

        counts  = np.frombuffer(raw, dtype=np.int8).astype(np.float64)
        wave    = counts * vgain - voffset
        sr      = 1.0 / horiz_interval if horiz_interval > 0 else 0.0

        if sum_wave is None:
            sum_wave = wave.copy()
            sample_rate_hz = sr
        else:
            if len(wave) != len(sum_wave):
                wave = np.interp(
                    np.linspace(0, 1, len(sum_wave)),
                    np.linspace(0, 1, len(wave)),
                    wave,
                )
            sum_wave += wave

    return sum_wave / averages, sample_rate_hz


def detect_faults(distances_m: np.ndarray, wave: np.ndarray,
                  velocity_factor: float) -> list[dict]:
    """
    Detect impedance discontinuities in the TDR trace.

    Returns list of dicts: distance_m, delta_v, type_str.
    The first edge (launch) is normalised to 0 m / excluded from fault list.
    """
    # Smoothed derivative — use a wide Savitzky-Golay-style difference kernel
    # to reduce noise hits.  We use np.gradient then a running average.
    deriv = np.gradient(wave, distances_m)
    kernel_len = max(3, len(deriv) // 500)    # ~0.2% of total length
    kernel = np.ones(kernel_len) / kernel_len
    smooth_deriv = np.convolve(deriv, kernel, mode='same')

    # Largest positive edge = launch step at distance ~0
    launch_idx  = int(np.argmax(smooth_deriv))
    launch_val  = smooth_deriv[launch_idx]

    threshold   = abs(launch_val) * FAULT_THRESHOLD_FRACTION

    # Suppress a window around the launch edge (2% of trace from launch)
    suppress_samples = max(5, len(distances_m) // 50)
    suppress_end = launch_idx + suppress_samples

    faults = []
    in_fault = False
    fault_start = 0

    for idx in range(suppress_end, len(smooth_deriv)):
        if not in_fault and abs(smooth_deriv[idx]) > threshold:
            in_fault = True
            fault_start = idx
        elif in_fault and abs(smooth_deriv[idx]) <= threshold:
            in_fault = False
            # Peak within the fault region
            seg   = smooth_deriv[fault_start:idx]
            peak_rel = int(np.argmax(np.abs(seg)))
            peak_idx = fault_start + peak_rel
            delta    = smooth_deriv[peak_idx]
            dist     = float(distances_m[peak_idx])
            faults.append({
                "distance_m": dist,
                "delta_v":    float(delta),
                "type_str":   classify_reflection(delta, launch_val),
            })

    return faults


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_csv(prefix: str, distances_m: np.ndarray, wave: np.ndarray) -> str:
    path = f"{prefix}_tdr.csv"
    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["distance_m", "voltage_v"])
        for d, v in zip(distances_m, wave):
            w.writerow([f"{d:.4f}", f"{v:.6f}"])
    return path


def write_text(prefix: str, faults: list[dict], velocity_factor: float,
               source: str, max_length_m: float,
               rise_time_ns: float) -> str:
    path = f"{prefix}_tdr.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    res  = resolution_m(rise_time_ns, velocity_factor)
    with open(path, "w") as f:
        f.write(f"TDR REPORT — {ts}\n")
        f.write("=" * 60 + "\n")
        f.write(f"  Source         : {source.upper()}\n")
        f.write(f"  Velocity factor: {velocity_factor:.3f}\n")
        f.write(f"  Max cable length: {max_length_m:.0f} m\n")
        f.write(f"  Rise time estimate: {rise_time_ns:.1f} ns\n")
        f.write(f"  Spatial resolution: ~{res*100:.1f} cm\n")
        f.write("\n")
        if faults:
            f.write(f"DETECTED FAULTS ({len(faults)}):\n")
            f.write("-" * 60 + "\n")
            for i, fa in enumerate(faults, 1):
                f.write(f"  Fault {i}: {fa['distance_m']:.2f} m  "
                        f"— {fa['type_str']}\n")
        else:
            f.write("No significant reflections detected.\n")
        f.write("\n")
    return path


def generate_plot(prefix: str, distances_m: np.ndarray, wave: np.ndarray,
                  faults: list[dict], velocity_factor: float,
                  source: str, max_length_m: float) -> str:
    fig, ax = plt.subplots(figsize=(12, 5))

    ax.plot(distances_m, wave, color="#1f77b4", linewidth=1.2, label="TDR trace")

    # Fault markers
    colors = ["red", "orange", "purple", "brown"]
    for i, fa in enumerate(faults):
        color = colors[i % len(colors)]
        ax.axvline(fa["distance_m"], color=color, linestyle="--",
                   linewidth=1.2, alpha=0.8,
                   label=f"{fa['distance_m']:.2f} m — {fa['type_str']}")
        ax.annotate(
            f"{fa['distance_m']:.2f} m\n{fa['type_str']}",
            xy=(fa["distance_m"], wave[np.argmin(np.abs(distances_m - fa["distance_m"]))]),
            xytext=(fa["distance_m"] + max_length_m * 0.02, ax.get_ylim()[1] * 0.5),
            fontsize=7, color=color,
            arrowprops=dict(arrowstyle="->", color=color, lw=0.8),
        )

    ax.set_xlabel("Distance (m)", fontsize=10)
    ax.set_ylabel("Voltage (V)", fontsize=10)
    ax.set_title(
        f"TDR Trace — Source: {source.upper()}  VF={velocity_factor:.3f}  "
        f"Max: {max_length_m:.0f} m\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=11,
    )
    ax.set_xlim(0, max_length_m)
    ax.grid(True, alpha=0.35)
    if faults:
        ax.legend(fontsize=8, loc="upper right")
    ax.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{prefix}_tdr.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Time-Domain Reflectometer — locate cable faults via step-edge reflection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Source selection:
  SDG  (default) — ~3.5 ns rise time → ~35 cm resolution at VF=0.66
  AWG             — ~14 ns rise time → ~138 cm resolution at VF=0.66
  SDG is strongly preferred for TDR work.

Cable type presets (set --cable-type or supply --vf manually):
  rg58 / rg8 / rg213  VF=0.66
  lmr400               VF=0.85
  lmr240               VF=0.84
  custom               Use --vf VALUE

Physical setup:
  Source → SMA T-splitter ─┬── CH1 (scope)
                            └── Coax cable under test ── open/short/load

Examples:
  python tdr.py
  python tdr.py --cable-type lmr400 --max-length-m 200
  python tdr.py --source awg --averages 32 --vf 0.82
""",
    )

    parser.add_argument("--source", choices=["sdg", "awg"], default="sdg",
                        help="Signal source (default: sdg — better rise time)")
    parser.add_argument("--vf", type=float, default=None,
                        help="Velocity factor (overrides --cable-type)")
    parser.add_argument("--cable-type",
                        choices=list(CABLE_PRESETS.keys()), default="rg58",
                        help="Cable type preset (default: rg58, VF=0.66)")
    parser.add_argument("--max-length-m", type=float, default=DEFAULT_MAX_LENGTH,
                        help=f"Maximum cable length to display in metres "
                             f"(default: {DEFAULT_MAX_LENGTH:.0f})")
    parser.add_argument("--freq-hz", type=float, default=None,
                        help="Square wave frequency in Hz "
                             "(default: 10 MHz for SDG, 5 MHz for AWG)")
    parser.add_argument("--sdg-host", default=DEFAULT_SDG_HOST,
                        help=f"SDG1062X IP address (default: {DEFAULT_SDG_HOST})")
    parser.add_argument("--scope-host", default=DEFAULT_SCOPE_HOST,
                        help=f"SDS2504X Plus IP address (default: {DEFAULT_SCOPE_HOST})")
    parser.add_argument("--output", default=None,
                        help="Output filename prefix (default: tdr_YYYYMMDD_HHMMSS)")
    parser.add_argument("--averages", type=int, default=DEFAULT_AVERAGES,
                        help=f"Number of captures to average (default: {DEFAULT_AVERAGES})")

    args = parser.parse_args()

    # Resolve velocity factor
    if args.vf is not None:
        velocity_factor = args.vf
        cable_desc      = f"custom (VF={args.vf:.3f})"
    elif args.cable_type == "custom":
        parser.error("--cable-type custom requires --vf VALUE")
    else:
        velocity_factor, cable_desc = CABLE_PRESETS[args.cable_type]

    # Resolve frequency
    if args.freq_hz is not None:
        freq_hz = args.freq_hz
    else:
        freq_hz = DEFAULT_FREQ_SDG if args.source == "sdg" else DEFAULT_FREQ_AWG

    # Output prefix
    if args.output is None:
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"tdr_{ts}"

    # Rise time estimate for resolution display
    rise_time_ns = 3.5 if args.source == "sdg" else 14.0

    # Capture duration = round trip for max length plus margin
    c = 3e8  # m/s
    rt_time_s   = 2.0 * args.max_length_m / (velocity_factor * c)
    duration_s  = rt_time_s + 200e-9   # 200 ns margin
    duration_s  = max(duration_s, 1e-6)

    print(f"TDR — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Cable type  : {cable_desc}")
    print(f"  Velocity factor: {velocity_factor:.3f}")
    print(f"  Max length  : {args.max_length_m:.0f} m")
    print(f"  Source      : {args.source.upper()}  f={format_freq_short(freq_hz)}")
    print(f"  Averages    : {args.averages}")
    print(f"  Capture window: {duration_s*1e6:.2f} µs")
    print(f"  Est. resolution: ~{resolution_m(rise_time_ns, velocity_factor)*100:.1f} cm\n")

    scope = None
    sdg   = None

    try:
        print(f"Connecting to scope via inventory'} ...", end=" ", flush=True)
        scope = connect(args.scope_host or 'sds')
        print(f"OK  [{scope.identify().split(',')[1].strip()}]")

        if args.source == "sdg":
            print(f"Connecting to SDG via inventory'} ...", end=" ", flush=True)
            sdg = connect(args.sdg_host or 'sdg')
            print(f"OK  [{sdg.identify().split(',')[1].strip()}]")
            sdg.set_sine(1, freq_hz, level_dbm=13.0)   # ~13 dBm ≈ 1 Vpp into 50 Ω
            # Reconfigure as square wave via BSWV
            vpp = DEFAULT_AMPLITUDE
            sdg._cmd(
                f"C1:BSWV WVTP,SQUARE,"
                f"FRQ,{freq_hz:.6f},"
                f"AMP,{vpp:.6f},"
                f"DUTY,50,"
                f"OFST,0,"
                f"PHSE,0"
            )
            sdg.output_on(1)
            time.sleep(0.2)
            print(f"  SDG output ON: {format_freq_short(freq_hz)} square, "
                  f"{vpp:.2f} Vpp")
        else:
            # Built-in AWG
            scope.set_awg_square(freq_hz, amplitude_vpp=DEFAULT_AMPLITUDE, duty_pct=50.0)
            scope.awg_output_on()
            time.sleep(0.2)
            print(f"  AWG output ON: {format_freq_short(freq_hz)} square, "
                  f"{DEFAULT_AMPLITUDE:.2f} Vpp")

        # Auto-estimate V/div from half the AWG amplitude (the trace sits at 0
        # or 1× amplitude level — one division slightly above the high level is fine)
        vdiv = DEFAULT_AMPLITUDE / 2.5

        print(f"\nCapturing ({args.averages} averages) ...", end=" ", flush=True)
        wave, sample_rate_hz = capture_averaged(
            scope, SCOPE_CHANNEL, duration_s, vdiv, args.averages,
        )
        print(f"done  ({len(wave)} samples, {sample_rate_hz/1e6:.0f} MHz SR)")

        # Build distance axis
        t_per_sample  = 1.0 / sample_rate_hz
        d_per_sample  = t_per_sample * velocity_factor * c / 2.0
        distances_m   = np.arange(len(wave)) * d_per_sample

        # Trim to max length
        mask        = distances_m <= args.max_length_m
        distances_m = distances_m[mask]
        wave        = wave[mask]

        # Detect faults
        print("Detecting faults ...", end=" ", flush=True)
        faults = detect_faults(distances_m, wave, velocity_factor)
        print(f"done  ({len(faults)} fault(s) detected)")

        # Report faults to terminal
        if faults:
            print("\nDetected faults:")
            for i, fa in enumerate(faults, 1):
                print(f"  {i}. {fa['distance_m']:.2f} m — {fa['type_str']}")
        else:
            print("\nNo significant reflections detected.")

        # Write outputs
        csv_path = write_csv(args.output, distances_m, wave)
        txt_path = write_text(args.output, faults, velocity_factor, args.source,
                              args.max_length_m, rise_time_ns)
        png_path = generate_plot(args.output, distances_m, wave, faults,
                                 velocity_factor, args.source, args.max_length_m)

        print(f"\nOutput:")
        print(f"  PNG  → {png_path}")
        print(f"  CSV  → {csv_path}")
        print(f"  TXT  → {txt_path}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nConnection refused: {exc}")
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
        if scope is not None:
            try:
                scope.awg_output_off()
                scope.run()
                scope.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
