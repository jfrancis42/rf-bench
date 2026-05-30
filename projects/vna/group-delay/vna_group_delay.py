#!/usr/bin/env python3
"""
vna_group_delay.py — HP 8712B Group Delay Measurement

Requires HP 8712B VNA and rf-bench-drivers-hp. The HP 8712B is not currently
connected — requires KISS-488 Ethernet-GPIB adapter.

Measures S21 magnitude and phase, then computes group delay:
    τ(f) = -dφ/dω = -Δφ / (2π · Δf)   [nanoseconds]

Uses numpy.gradient for numerical differentiation of the unwrapped phase.

Note: The HP 8712B can compute group delay directly via set_format("GDEL"),
which returns the hardware-computed group delay trace.  This script
demonstrates both approaches: the manual computation from phase data
(--no-gdel) and the direct hardware GDEL readout (default).  The hardware
GDEL uses an aperture setting that is instrument-configured; the manual
computation here uses a two-point central difference (numpy.gradient).

Outputs:
  {prefix}.png    — 3-panel: S21 magnitude, S21 phase (unwrapped), group delay
  {prefix}.txt    — tabulated frequency / mag / phase / group_delay
  {prefix}.json   — all data in JSON

Usage:
  python vna_group_delay.py
  python vna_group_delay.py --start 1000 --stop 100000 --smooth
  python vna_group_delay.py --no-gdel        # use manual phase differentiation
  python vna_group_delay.py --output filter_delay
"""

import argparse
import json
import sys
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.hp import HP8712B

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_HOST      = "10.1.1.70"
DEFAULT_START_KHZ = 300
DEFAULT_STOP_KHZ  = 1_300_000
DEFAULT_POINTS    = 401
DEFAULT_POWER_DBM = -10.0

SAVGOL_WINDOW     = 5    # Savitzky-Golay smoothing window (must be odd)
SAVGOL_POLY       = 2    # polynomial order

# ---------------------------------------------------------------------------
# Group delay computation
# ---------------------------------------------------------------------------

def compute_group_delay_ns(freqs_hz: np.ndarray, phase_deg: np.ndarray) -> np.ndarray:
    """
    Compute group delay in nanoseconds from phase (degrees) vs. frequency (Hz).

    Method: unwrap phase, then apply central-difference numerical derivative.
        τ(f) = -dφ/dω = -Δφ_rad / (2π · Δf)
    Converts to nanoseconds (× 1e9).
    """
    phase_rad = np.deg2rad(phase_deg)
    phase_unwrapped = np.unwrap(phase_rad)
    # Central-difference derivative (numpy.gradient handles edges with one-sided diff)
    dphi_df = np.gradient(phase_unwrapped, freqs_hz)
    group_delay_s = -dphi_df / (2.0 * np.pi)
    return group_delay_s * 1e9   # → nanoseconds


def savitzky_golay_smooth(y: np.ndarray, window: int = SAVGOL_WINDOW,
                          poly: int = SAVGOL_POLY) -> np.ndarray:
    """
    Apply Savitzky-Golay smoothing.  Falls back to plain if scipy unavailable.
    """
    try:
        from scipy.signal import savgol_filter
        return savgol_filter(y, window_length=window, polyorder=poly)
    except ImportError:
        # Fall back to simple moving average
        kernel = np.ones(window) / window
        return np.convolve(y, kernel, mode="same")


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def measure_s21(vna: HP8712B, start_hz: float, stop_hz: float,
                points: int, power_dbm: float,
                use_gdel: bool) -> dict:
    """
    Measure S21 magnitude, phase, and group delay.

    If use_gdel is True, also reads the hardware GDEL trace in addition to
    the manually computed group delay.

    Returns dict with freqs_hz, mag_db, phase_deg, gd_manual_ns, gd_hw_ns.
    """
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_power(power_dbm)
    vna.set_parameter("S21")

    # Magnitude
    print("  S21 magnitude ...", end="", flush=True)
    vna.set_format("MLOG")
    ok = vna.single_sweep()
    if not ok:
        print(" WARN: sweep timeout")
    freqs_hz = vna.get_frequencies()
    mag_db   = vna.get_trace_db()
    print(f" done  (peak {np.max(mag_db):+.1f} dB)")

    # Phase
    print("  S21 phase ...", end="", flush=True)
    vna.set_format("PHAS")
    ok = vna.single_sweep()
    if not ok:
        print(" WARN: sweep timeout")
    phase_deg = vna.get_trace_phase()
    print(" done")

    # Manual group delay from phase
    gd_manual_ns = compute_group_delay_ns(freqs_hz, phase_deg)

    # Hardware group delay (GDEL format)
    gd_hw_ns = None
    if use_gdel:
        print("  S21 group delay (hardware GDEL) ...", end="", flush=True)
        vna.set_format("GDEL")
        ok = vna.single_sweep()
        if not ok:
            print(" WARN: sweep timeout")
        raw_gdel = vna.get_trace_db()   # GDEL returns seconds via FDAT; scaling TBD
        # HP 8712B GDEL returns seconds in FDAT — convert to nanoseconds.
        # Note: verify the GDEL unit (seconds vs nanoseconds) against HP 8712B manual.
        gd_hw_ns = raw_gdel * 1e9
        print(f" done  (mean {np.mean(gd_hw_ns):.2f} ns)")

    return {
        "freqs_hz":    freqs_hz,
        "mag_db":      mag_db,
        "phase_deg":   phase_deg,
        "gd_manual_ns": gd_manual_ns,
        "gd_hw_ns":    gd_hw_ns,
    }


# ---------------------------------------------------------------------------
# Text output
# ---------------------------------------------------------------------------

def save_txt(result: dict, prefix: str, start_hz: float, stop_hz: float,
             points: int, power_dbm: float, host: str,
             smooth: bool, use_gdel: bool) -> str:
    path = f"{prefix}.txt"
    freqs = result["freqs_hz"]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    gd_ns = result.get("gd_smooth_ns", result["gd_manual_ns"])

    with open(path, "w") as f:
        f.write("HP 8712B Group Delay Measurement\n")
        f.write("=" * 60 + "\n")
        f.write(f"Date/time  : {ts}\n")
        f.write(f"Instrument : {host}\n")
        f.write(f"Start      : {start_hz/1e6:.6f} MHz\n")
        f.write(f"Stop       : {stop_hz/1e6:.6f} MHz\n")
        f.write(f"Points     : {points}\n")
        f.write(f"Power      : {power_dbm:.1f} dBm\n")
        f.write(f"Smooth     : {'yes (Savitzky-Golay)' if smooth else 'no'}\n")
        f.write(f"GDEL hw    : {'yes' if use_gdel else 'no (manual only)'}\n\n")

        gd_valid = gd_ns[np.isfinite(gd_ns)]
        if len(gd_valid):
            f.write(f"Group delay: min {np.min(gd_valid):.3f} ns, "
                    f"max {np.max(gd_valid):.3f} ns, "
                    f"variation {np.max(gd_valid)-np.min(gd_valid):.3f} ns\n\n")

        hdr = (f"{'Freq (MHz)':>14}  {'S21 (dB)':>12}  "
               f"{'Phase (°)':>12}  {'GD (ns)':>12}")
        if result["gd_hw_ns"] is not None:
            hdr += f"  {'GD-hw (ns)':>12}"
        f.write(hdr + "\n")
        f.write("-" * len(hdr) + "\n")

        for i in range(len(freqs)):
            row = (f"{freqs[i]/1e6:>14.6f}  "
                   f"{result['mag_db'][i]:>12.4f}  "
                   f"{result['phase_deg'][i]:>12.4f}  "
                   f"{gd_ns[i]:>12.4f}")
            if result["gd_hw_ns"] is not None:
                row += f"  {result['gd_hw_ns'][i]:>12.4f}"
            f.write(row + "\n")
    return path


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_results(result: dict, prefix: str, start_hz: float,
                 stop_hz: float, smooth: bool) -> str:
    freqs_mhz = result["freqs_hz"] / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    gd_ns = result.get("gd_smooth_ns", result["gd_manual_ns"])

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    fig.suptitle(f"HP 8712B — S21 Group Delay\n"
                 f"{start_hz/1e6:.4f} – {stop_hz/1e6:.0f} MHz  |  {ts}",
                 fontsize=11)

    # Panel 1: S21 magnitude
    ax1.plot(freqs_mhz, result["mag_db"], color="steelblue", linewidth=0.8)
    ax1.set_ylabel("S21 Magnitude (dB)", fontsize=9)
    ax1.grid(True, alpha=0.4)
    ax1.tick_params(labelsize=8)

    # Panel 2: Phase (unwrapped)
    phase_unwrapped = np.rad2deg(np.unwrap(np.deg2rad(result["phase_deg"])))
    ax2.plot(freqs_mhz, phase_unwrapped, color="darkorange", linewidth=0.8,
             label="Unwrapped phase")
    ax2.plot(freqs_mhz, result["phase_deg"], color="goldenrod", linewidth=0.5,
             alpha=0.5, label="Wrapped phase")
    ax2.set_ylabel("S21 Phase (degrees)", fontsize=9)
    ax2.legend(fontsize=7, loc="upper right")
    ax2.grid(True, alpha=0.4)
    ax2.tick_params(labelsize=8)

    # Panel 3: Group delay
    label_manual = "Group delay (manual)" + (" + SG smooth" if smooth else "")
    ax3.plot(freqs_mhz, gd_ns, color="forestgreen", linewidth=0.9,
             label=label_manual)
    if result["gd_hw_ns"] is not None:
        ax3.plot(freqs_mhz, result["gd_hw_ns"], color="purple", linewidth=0.7,
                 alpha=0.7, linestyle="--", label="Group delay (HW GDEL)")
    ax3.set_xlabel("Frequency (MHz)", fontsize=9)
    ax3.set_ylabel("Group Delay (ns)", fontsize=9)
    ax3.legend(fontsize=7, loc="upper right")
    ax3.grid(True, alpha=0.4)
    ax3.tick_params(labelsize=8)

    # Annotate min/max group delay
    gd_valid = gd_ns[np.isfinite(gd_ns)]
    if len(gd_valid):
        gd_min = np.min(gd_valid)
        gd_max = np.max(gd_valid)
        gd_variation = gd_max - gd_min
        ax3.axhline(gd_min, color="forestgreen", linestyle=":", linewidth=0.6, alpha=0.7)
        ax3.axhline(gd_max, color="forestgreen", linestyle=":", linewidth=0.6, alpha=0.7)
        ax3.text(freqs_mhz[-1], gd_min, f" {gd_min:.2f} ns",
                 fontsize=7, va="center", color="forestgreen")
        ax3.text(freqs_mhz[-1], gd_max, f" {gd_max:.2f} ns",
                 fontsize=7, va="center", color="forestgreen")
        ax3.text(0.02, 0.92,
                 f"Variation: {gd_variation:.3f} ns  |  "
                 f"Mean: {np.mean(gd_valid):.3f} ns",
                 transform=ax3.transAxes, fontsize=8,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow",
                           edgecolor="gray", alpha=0.8))

    fig.tight_layout()
    path = f"{prefix}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="HP 8712B Group Delay Measurement (S21 phase differentiation)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup:
  DUT connected between PORT 1 (stimulus) and PORT 2 (receiver).
  For an unloaded thru measurement, connect PORT 1 → PORT 2 directly.

Examples:
  python vna_group_delay.py                         # full band, hardware GDEL
  python vna_group_delay.py --start 10000 --stop 100000 --smooth
  python vna_group_delay.py --no-gdel               # manual phase diff only
  python vna_group_delay.py --points 801 --output delay_filter
""",
    )

    parser.add_argument("--start",    type=float, default=DEFAULT_START_KHZ,
                        metavar="KHZ",
                        help=f"Start frequency in kHz (default {DEFAULT_START_KHZ})")
    parser.add_argument("--stop",     type=float, default=DEFAULT_STOP_KHZ,
                        metavar="KHZ",
                        help=f"Stop frequency in kHz (default {DEFAULT_STOP_KHZ})")
    parser.add_argument("--points",   type=int,   default=DEFAULT_POINTS,
                        metavar="N",
                        help=f"Sweep points, 1–801 (default {DEFAULT_POINTS})")
    parser.add_argument("--power",    type=float, default=DEFAULT_POWER_DBM,
                        metavar="DBM",
                        help=f"Stimulus power in dBm (default {DEFAULT_POWER_DBM})")
    parser.add_argument("--smooth",   action="store_true",
                        help="Apply Savitzky-Golay smoothing to manual group delay")
    parser.add_argument("--no-gdel",  action="store_true",
                        help="Skip hardware GDEL trace; use manual computation only")
    parser.add_argument("--host",     default=DEFAULT_HOST, metavar="HOST",
                        help=f"KISS-488 IP address (default {DEFAULT_HOST})")
    parser.add_argument("--prefix",   default=None, metavar="TEXT",
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()

    if args.prefix is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.prefix = f"vna_group_delay_{ts}"

    start_hz = args.start * 1_000.0
    stop_hz  = args.stop  * 1_000.0
    if start_hz >= stop_hz:
        print("Error: --start must be less than --stop")
        sys.exit(1)
    if args.points > 801:
        print("Warning: clamping points to 801")
        args.points = 801

    use_gdel = not args.no_gdel

    print("HP 8712B Group Delay Measurement")
    print(f"  Host       : {args.host}")
    print(f"  Sweep      : {start_hz/1e6:.4f} – {stop_hz/1e6:.0f} MHz, {args.points} pts")
    print(f"  Power      : {args.power:.1f} dBm")
    print(f"  Smooth     : {'yes (Savitzky-Golay)' if args.smooth else 'no'}")
    print(f"  HW GDEL    : {'yes' if use_gdel else 'no'}")
    print(f"  Prefix     : {args.prefix}")
    print()

    vna = None
    try:
        print(f"Connecting to HP 8712B @ {args.host} ...")
        vna = HP8712B(host=args.host)
        print(f"  {vna.identify()}")

        print("\n[MEASURING]")
        result = measure_s21(vna, start_hz, stop_hz, args.points,
                              args.power, use_gdel)

        # Optionally smooth the manual group delay
        if args.smooth:
            result["gd_smooth_ns"] = savitzky_golay_smooth(
                result["gd_manual_ns"], window=SAVGOL_WINDOW, poly=SAVGOL_POLY)

        # ---- Save outputs ----
        print("\n[SAVING RESULTS]")

        txt_path = save_txt(result, args.prefix, start_hz, stop_hz,
                            args.points, args.power, args.host,
                            args.smooth, use_gdel)
        print(f"Text   → {txt_path}")

        gd_ns = result.get("gd_smooth_ns", result["gd_manual_ns"])
        json_path = f"{args.prefix}.json"
        json_data = {
            "timestamp":    datetime.now().isoformat(),
            "host":         args.host,
            "start_hz":     start_hz,
            "stop_hz":      stop_hz,
            "points":       args.points,
            "power_dbm":    args.power,
            "smooth":       args.smooth,
            "hw_gdel_used": use_gdel,
            "freqs_hz":     result["freqs_hz"].tolist(),
            "mag_db":       result["mag_db"].tolist(),
            "phase_deg":    result["phase_deg"].tolist(),
            "gd_manual_ns": result["gd_manual_ns"].tolist(),
            "gd_smooth_ns": result["gd_smooth_ns"].tolist() if args.smooth else None,
            "gd_hw_ns":     result["gd_hw_ns"].tolist() if use_gdel else None,
        }
        with open(json_path, "w") as jf:
            json.dump(json_data, jf, indent=2)
        print(f"JSON   → {json_path}")

        try:
            png_path = plot_results(result, args.prefix, start_hz, stop_hz, args.smooth)
            print(f"Plot   → {png_path}")
        except Exception as exc:
            print(f"Plot failed: {exc}")

        # Summary
        gd_valid = gd_ns[np.isfinite(gd_ns)]
        print("\n[SUMMARY]")
        print(f"  S21 gain   : {np.min(result['mag_db']):+.1f} to "
              f"{np.max(result['mag_db']):+.1f} dB")
        if len(gd_valid):
            print(f"  Group delay: {np.min(gd_valid):.3f} ns min, "
                  f"{np.max(gd_valid):.3f} ns max, "
                  f"variation {np.max(gd_valid)-np.min(gd_valid):.3f} ns")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to HP 8712B: {exc}")
        print("Verify KISS-488 adapter is powered and at the correct IP.")
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
        if vna is not None:
            try:
                vna.marker_off()
                vna.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
