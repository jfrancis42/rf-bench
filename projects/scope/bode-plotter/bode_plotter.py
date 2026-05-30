#!/usr/bin/env python3
"""
Bode Plotter — Siglent SDS2000X Plus (scope + AWG) or SDG1000X + SDS2000X Plus

Measures gain (dB) and phase (degrees) versus frequency for any linear DUT.
Classic Bode plot, two-panel (gain / phase), log-frequency X axis.

Cable setup:
  Source ──┬─── CH1 (reference, monitors the actual source voltage)
           └─── DUT input
                  DUT output ─── CH2 (measures the output)

Source options:
  --source awg   Scope's built-in AWG ("Gen Out" BNC). Phase-coherent with the
                 scope's timebase. No SDG required. Max 25 MHz. Best for audio
                 frequency work (filters, op-amps, crossovers). Default.

  --source sdg   External SDG1000X function generator. Sweeps up to 60 MHz.
                 Better amplitude stability; required for frequencies above 25 MHz.
                 Slight inter-instrument phase offset (negligible for most HF work).

Usage:
  python bode_plotter.py                            # AWG, 10 Hz–1 MHz, 100 points
  python bode_plotter.py --start 20 --stop 20000    # audio band
  python bode_plotter.py --source sdg --stop 10e6   # SDG, 10 MHz
  python bode_plotter.py --level -20 --points 200   # lower drive, more points
  python bode_plotter.py --output my_filter         # custom output prefix
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
# Shared drivers
# ---------------------------------------------------------------------------


from rf_bench.siglent import SDG1000X, SDS2000X                 # noqa: E402
from rf_bench.utils import (                                      # noqa: E402
    gain_phase_from_fft, dominant_frequency,
    format_freq, format_freq_short, dbm_to_vpp, vpp_to_dbm,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SDG_HOST         = "10.1.1.55"
SCOPE_HOST       = "10.1.1.58"
DEFAULT_POINTS   = 100
DEFAULT_LEVEL_DBM = -10.0
AWG_MAX_FREQ_HZ  = 25_000_000     # 25 MHz hard limit for scope AWG
SDG_MAX_FREQ_HZ  = 60_000_000     # 60 MHz for SDG1062X


# ---------------------------------------------------------------------------
# Frequency array helpers
# ---------------------------------------------------------------------------

def make_freq_array(start_hz: float, stop_hz: float,
                    n: int, log_spaced: bool) -> np.ndarray:
    """Return an array of n frequencies between start_hz and stop_hz."""
    if log_spaced:
        return np.logspace(np.log10(start_hz), np.log10(stop_hz), n)
    else:
        return np.linspace(start_hz, stop_hz, n)


# ---------------------------------------------------------------------------
# Capture duration heuristic
# ---------------------------------------------------------------------------

def capture_duration(freq_hz: float, min_cycles: int = 20,
                     max_s: float = 5.0) -> float:
    """
    Return a capture duration (seconds) that gives at least min_cycles at freq_hz.

    Floor: 0.02 s (so the scope can settle after arm)
    Ceiling: max_s (avoids multi-minute captures at very low frequencies)
    """
    t = max(0.02, min_cycles / freq_hz)
    return min(t, max_s)


# ---------------------------------------------------------------------------
# Core measurement loop
# ---------------------------------------------------------------------------

def run_sweep(
    scope: SDS2000X,
    sdg,                        # SDG1000X | None
    freqs_hz: np.ndarray,
    level_dbm: float,
    ch_ref: int,
    ch_dut: int,
    source: str,
    fixed_duration_s: "float | None" = None,
) -> tuple[list[float], list[float], list[float]]:
    """
    Sweep *freqs_hz*, measure gain and phase at each point.

    Returns (measured_freqs, gain_db_list, phase_deg_list).

    Skipped points (capture failure) are represented by NaN.
    """
    amplitude_vpp = dbm_to_vpp(level_dbm)

    measured_freqs = []
    gains_db       = []
    phases_deg     = []

    total = len(freqs_hz)
    for i, f in enumerate(freqs_hz):
        # Set source
        if source == "awg":
            scope.set_awg_sine(freq_hz=f, amplitude_vpp=amplitude_vpp)
        else:  # sdg
            sdg.set_sine(1, freq_hz=f, level_dbm=level_dbm)

        # Give source a moment to settle (especially important at low frequencies)
        settle_s = min(0.1, 2.0 / f)
        time.sleep(settle_s)

        # Capture both channels
        dur = fixed_duration_s if fixed_duration_s is not None else capture_duration(f)
        try:
            ch1_v, sr = scope.capture_audio(channel=ch_ref,  duration_s=dur)
            ch2_v, _  = scope.capture_audio(channel=ch_dut,  duration_s=dur)
        except RuntimeError as exc:
            print(f"  [{i+1:3d}/{total}] {format_freq_short(f):>10}  SKIP ({exc})")
            measured_freqs.append(f)
            gains_db.append(float("nan"))
            phases_deg.append(float("nan"))
            continue

        # FFT-based gain and phase
        gain_db, phase_deg = gain_phase_from_fft(ch1_v, ch2_v, sr, freq_hz=f)

        print(f"  [{i+1:3d}/{total}] {format_freq_short(f):>10}  "
              f"gain={gain_db:+7.2f} dB  phase={phase_deg:+7.1f}°")

        measured_freqs.append(f)
        gains_db.append(gain_db)
        phases_deg.append(phase_deg)

    return measured_freqs, gains_db, phases_deg


# ---------------------------------------------------------------------------
# –3 dB frequency finder
# ---------------------------------------------------------------------------

def find_minus3db(freqs: list[float],
                  gains_db: list[float]) -> tuple[float | None, float | None]:
    """
    Find the first frequency where gain drops 3 dB below the passband.

    The passband level is estimated as the median of the top-25% gain values
    (robust against roll-off at the edges of the sweep).

    Returns (f_3db, gain_at_3db) or (None, None) if not found.
    """
    g = np.array(gains_db, dtype=float)
    f = np.array(freqs, dtype=float)
    valid = ~np.isnan(g)
    if np.sum(valid) < 3:
        return None, None

    gv = g[valid]
    fv = f[valid]

    # Passband estimate: median of top-25%
    threshold = np.percentile(gv, 75)
    passband_level = np.median(gv[gv >= threshold])
    target = passband_level - 3.0

    # Walk forward; find first point below target
    for idx in range(len(gv)):
        if gv[idx] < target:
            # Linear interpolation between idx-1 and idx
            if idx > 0:
                f0, g0 = fv[idx - 1], gv[idx - 1]
                f1, g1 = fv[idx], gv[idx]
                if g1 != g0:
                    fmid = f0 + (f1 - f0) * (target - g0) / (g1 - g0)
                    return float(fmid), target
            return float(fv[idx]), float(gv[idx])

    return None, None


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_csv(freqs: list[float], gains_db: list[float],
              phases_deg: list[float], prefix: str) -> str:
    path = f"{prefix}_bode.csv"
    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["freq_hz", "gain_db", "phase_deg"])
        for freq, g, p in zip(freqs, gains_db, phases_deg):
            w.writerow([f"{freq:.6f}", f"{g:.4f}", f"{p:.3f}"])
    return path


def write_summary(freqs: list[float], gains_db: list[float],
                  phases_deg: list[float], source: str,
                  level_dbm: float, prefix: str) -> str:
    path = f"{prefix}_bode.txt"

    f3db, g3db = find_minus3db(freqs, gains_db)
    g = np.array(gains_db, dtype=float)
    valid = ~np.isnan(g)

    with open(path, "w") as fh:
        fh.write("=" * 72 + "\n")
        fh.write("  BODE PLOT SUMMARY\n")
        fh.write(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        fh.write(f"  Source    : {source.upper()}\n")
        fh.write(f"  Drive     : {level_dbm:+.1f} dBm"
                 f"  ({dbm_to_vpp(level_dbm)*1000:.1f} mVpp into 50 Ω)\n")
        fh.write(f"  Sweep     : {format_freq(freqs[0])} – {format_freq(freqs[-1])}\n")
        fh.write(f"  Points    : {len(freqs)} ({np.sum(valid)} valid)\n")
        fh.write("=" * 72 + "\n\n")

        if np.sum(valid) > 0:
            gv = g[valid]
            fh.write(f"  Passband gain (approx) : {np.percentile(gv, 75):+.2f} dB"
                     f"  (75th percentile)\n")
            fh.write(f"  Gain range             : {np.nanmin(g):+.2f} dB"
                     f" – {np.nanmax(g):+.2f} dB\n")

        if f3db is not None:
            # Phase at the –3 dB frequency (interpolated)
            fa = np.array(freqs, dtype=float)
            pa = np.array(phases_deg, dtype=float)
            valid_p = ~np.isnan(pa)
            phase_at_3db = float("nan")
            if np.sum(valid_p) > 1:
                phase_at_3db = float(np.interp(f3db, fa[valid_p], pa[valid_p]))
            fh.write(f"\n  –3 dB frequency        : {format_freq(f3db)}\n")
            if not np.isnan(phase_at_3db):
                fh.write(f"  Phase at –3 dB         : {phase_at_3db:+.1f}°\n")
        else:
            fh.write("\n  –3 dB frequency        : not found in sweep range\n")

    return path


# ---------------------------------------------------------------------------
# Plot generation
# ---------------------------------------------------------------------------

def generate_plot(freqs: list[float], gains_db: list[float],
                  phases_deg: list[float], source: str,
                  level_dbm: float, prefix: str) -> str:
    fa = np.array(freqs, dtype=float)
    ga = np.array(gains_db, dtype=float)
    pa = np.array(phases_deg, dtype=float)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    src_label = f"Source: {source.upper()}  Drive: {level_dbm:+.0f} dBm"
    fig.suptitle(
        f"Bode Plot — {ts}\n"
        f"{src_label}  |  "
        f"{format_freq_short(fa[0])} – {format_freq_short(fa[-1])}",
        fontsize=11,
    )

    # --- Gain panel ---
    ax1.semilogx(fa, ga, color="#1f77b4", linewidth=1.8, label="Gain")
    ax1.axhline(0.0, color="gray",       linestyle="--", linewidth=0.9,
                label="0 dB")
    ax1.axhline(-3.0, color="darkorange", linestyle=":",  linewidth=0.9,
                label="–3 dB")

    # Mark –3 dB crossover
    f3db, g3db = find_minus3db(freqs, gains_db)
    if f3db is not None:
        ax1.axvline(f3db, color="red", linestyle="--", linewidth=0.8, alpha=0.7)
        ax1.annotate(f"–3 dB: {format_freq_short(f3db)}",
                     xy=(f3db, g3db if g3db is not None else -3.0),
                     xytext=(f3db * 1.5, (g3db if g3db is not None else -3.0) + 2),
                     fontsize=8, color="red",
                     arrowprops=dict(arrowstyle="->", color="red", lw=0.8))

    ax1.set_ylabel("Gain (dB)", fontsize=10)
    ax1.grid(True, which="both", alpha=0.30)
    ax1.legend(fontsize=8, loc="best")
    ax1.tick_params(labelsize=9)

    # --- Phase panel ---
    ax2.semilogx(fa, pa, color="#d62728", linewidth=1.8, label="Phase")
    ax2.axhline(  0.0, color="gray",       linestyle="--", linewidth=0.9)
    ax2.axhline( 90.0, color="lightgray",  linestyle=":",  linewidth=0.7)
    ax2.axhline(-90.0, color="lightgray",  linestyle=":",  linewidth=0.7)

    if f3db is not None:
        ax2.axvline(f3db, color="red", linestyle="--", linewidth=0.8, alpha=0.7)

    ax2.set_ylabel("Phase (°)", fontsize=10)
    ax2.set_xlabel("Frequency (Hz)", fontsize=10)
    ax2.set_ylim(-180, 180)
    ax2.set_yticks([-180, -90, 0, 90, 180])
    ax2.grid(True, which="both", alpha=0.30)
    ax2.legend(fontsize=8, loc="best")
    ax2.tick_params(labelsize=9)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    path = f"{prefix}_bode.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Bode Plotter — gain and phase versus frequency",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Cable setup:
  Source ──┬─── CH1 (reference)
           └─── DUT input
                  DUT output ─── CH2

Source options:
  --source awg   Scope AWG (25 MHz max). Phase-coherent. Default.
  --source sdg   SDG1000X function generator (60 MHz max). Better for HF.

Examples:
  python bode_plotter.py                             # AWG, 10 Hz – 1 MHz
  python bode_plotter.py --start 20 --stop 20000     # audio band
  python bode_plotter.py --source sdg --stop 10e6    # SDG to 10 MHz
  python bode_plotter.py --lin-freq                  # linear frequency spacing
  python bode_plotter.py --level -20 --points 200    # 200-point sweep at −20 dBm
""",
    )

    src_grp = parser.add_argument_group("source")
    src_grp.add_argument("--source", choices=["awg", "sdg"], default="awg",
                         help="Signal source: awg (scope built-in, ≤25 MHz) or "
                              "sdg (SDG1000X, ≤60 MHz) [default: awg]")
    src_grp.add_argument("--sdg-host", default=SDG_HOST, metavar="HOST",
                         help=f"SDG1000X IP [default: {SDG_HOST}]")
    src_grp.add_argument("--scope-host", default=SCOPE_HOST, metavar="HOST",
                         help=f"SDS2000X IP [default: {SCOPE_HOST}]")

    sweep_grp = parser.add_argument_group("sweep")
    sweep_grp.add_argument("--start", type=float, default=10.0, metavar="HZ",
                           help="Start frequency in Hz [default: 10]")
    sweep_grp.add_argument("--stop",  type=float, default=None,  metavar="HZ",
                           help="Stop frequency in Hz "
                                "[default: 1 MHz for AWG, 10 MHz for SDG]")
    sweep_grp.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N",
                           help=f"Number of sweep points [default: {DEFAULT_POINTS}]")
    sweep_grp.add_argument("--level", type=float, default=DEFAULT_LEVEL_DBM,
                           metavar="DBM",
                           help=f"Source level in dBm [default: {DEFAULT_LEVEL_DBM}]")

    spacing_grp = parser.add_mutually_exclusive_group()
    spacing_grp.add_argument("--log-freq", action="store_true", default=False,
                              help="Log-spaced frequency points (default behaviour)")
    spacing_grp.add_argument("--lin-freq", action="store_true", default=False,
                              help="Linear-spaced frequency points instead")

    chan_grp = parser.add_argument_group("channels")
    chan_grp.add_argument("--ch-ref", type=int, default=1, metavar="N",
                          help="Scope channel for reference (CH1 default)")
    chan_grp.add_argument("--ch-dut", type=int, default=2, metavar="N",
                          help="Scope channel for DUT output (CH2 default)")

    out_grp = parser.add_argument_group("output")
    out_grp.add_argument("--output", default=None, metavar="PREFIX",
                         help="Output filename prefix [default: bode_YYYYMMDD_HHMMSS]")
    out_grp.add_argument("--duration-s", type=float, default=None, metavar="S",
                         help="Fixed capture duration per point (overrides auto). "
                              "More seconds → finer FFT bins.")

    args = parser.parse_args()

    # Resolve defaults
    if args.stop is None:
        args.stop = 1_000_000.0 if args.source == "awg" else 10_000_000.0

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"bode_{ts}"

    # Validate frequency limits
    max_freq = AWG_MAX_FREQ_HZ if args.source == "awg" else SDG_MAX_FREQ_HZ
    if args.stop > max_freq:
        print(f"Warning: --stop {args.stop/1e6:.1f} MHz exceeds {args.source.upper()} "
              f"limit of {max_freq/1e6:.0f} MHz. Clamping.")
        args.stop = float(max_freq)

    if args.start <= 0:
        print("Error: --start must be > 0 Hz")
        sys.exit(1)

    if args.start >= args.stop:
        print("Error: --start must be less than --stop")
        sys.exit(1)

    # Log-spaced unless --lin-freq explicitly given
    log_spaced = not args.lin_freq

    # Build frequency array
    freqs_hz = make_freq_array(args.start, args.stop, args.points, log_spaced)

    # Validate level
    if args.source == "awg":
        vpp = dbm_to_vpp(args.level)
        if vpp > 6.0:
            print(f"Warning: {args.level:.1f} dBm = {vpp:.3f} Vpp exceeds AWG max "
                  f"(6 Vpp into high-Z, less into 50 Ω). Continuing.")
    else:
        from rf_bench.siglent.sdg1000x import DBM_MIN, DBM_MAX
        if not (DBM_MIN <= args.level <= DBM_MAX):
            print(f"Error: --level {args.level:.1f} dBm outside SDG range "
                  f"[{DBM_MIN:.0f}, {DBM_MAX:.0f}] dBm")
            sys.exit(1)

    # Print setup summary
    spacing_label = "log-spaced" if log_spaced else "linear-spaced"
    print(f"\n[BODE PLOTTER]")
    print(f"  Source    : {args.source.upper()}")
    print(f"  Sweep     : {format_freq(args.start)} – {format_freq(args.stop)}  "
          f"({args.points} pts, {spacing_label})")
    print(f"  Drive     : {args.level:+.1f} dBm  "
          f"({dbm_to_vpp(args.level)*1000:.1f} mVpp into 50 Ω)")
    print(f"  CH ref    : CH{args.ch_ref}   CH DUT: CH{args.ch_dut}")
    print(f"  Output    : {args.output}_bode.{{png,csv,txt}}")
    print()

    # Connect instruments
    print("Connecting to scope ...", end=" ", flush=True)
    try:
        scope = SDS2000X(args.scope_host)
    except (ConnectionRefusedError, OSError) as exc:
        print(f"\nCannot connect to scope at {args.scope_host}: {exc}")
        sys.exit(1)
    print(f"OK  ({scope.identify().split(',')[1].strip()})")

    sdg = None
    if args.source == "sdg":
        print("Connecting to SDG ...", end=" ", flush=True)
        try:
            sdg = SDG1000X(args.sdg_host)
        except (ConnectionRefusedError, OSError) as exc:
            print(f"\nCannot connect to SDG at {args.sdg_host}: {exc}")
            scope.close()
            sys.exit(1)
        print(f"OK  ({sdg.identify().split(',')[1].strip()})")
        sdg.set_sine(1, freq_hz=args.start, level_dbm=args.level)
        sdg.output_on(1)
    else:
        scope.awg_output_on()

    print("\nSweeping:")

    freqs_out  = []
    gains_out  = []
    phases_out = []

    try:
        freqs_out, gains_out, phases_out = run_sweep(
            scope=scope,
            sdg=sdg,
            freqs_hz=freqs_hz,
            level_dbm=args.level,
            ch_ref=args.ch_ref,
            ch_dut=args.ch_dut,
            source=args.source,
            fixed_duration_s=args.duration_s,
        )
    except KeyboardInterrupt:
        print("\nInterrupted — saving partial results ...")
        # freqs_out / gains_out / phases_out may be partially populated;
        # run_sweep returns only on completion, so we save what we have
        # by catching the interrupt here and falling through to cleanup.

    # Restore safe state
    if args.source == "awg":
        scope.awg_output_off()
    else:
        if sdg is not None:
            try:
                sdg.output_off_all()
                sdg.close()
            except Exception:
                pass
    scope.run()
    scope.close()

    if not freqs_out:
        print("No data collected.")
        sys.exit(1)

    # Write outputs
    print("\n[RESULTS]")
    csv_path = write_csv(freqs_out, gains_out, phases_out, args.output)
    txt_path = write_summary(freqs_out, gains_out, phases_out,
                             args.source, args.level, args.output)

    try:
        png_path = generate_plot(freqs_out, gains_out, phases_out,
                                 args.source, args.level, args.output)
        print(f"  Plot    → {png_path}")
    except Exception as exc:
        print(f"  Plot generation failed: {exc}")

    print(f"  CSV     → {csv_path}")
    print(f"  Summary → {txt_path}")

    # Print summary
    print()
    with open(txt_path) as fh:
        print(fh.read())


if __name__ == "__main__":
    main()
