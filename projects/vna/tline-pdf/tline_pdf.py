#!/usr/bin/env python3
"""
tline_pdf.py — Transmission-line characterisation PDF.

For a known-length sample of transmission line, extract velocity
factor (VF), characteristic impedance Z₀, and matched-line loss per
unit length, then write a single-page PDF.

Two methods supported, picked with --method:

  --method s21      (default; needs both VNA ports)
      VNA Port 1 ── tline ── VNA Port 2
      VF        = ω · L / -d(unwrap(∠S21))/dω      (electrical length)
      α (Np/m) = -ln(|S21|) / L                    (matched-line loss)
      Z₀ assumed = 50 Ω; reported as "assumed". Cannot be derived from
      S21 alone.

  --method osl-s11  (only one port needed)
      VNA Port 1 ── tline, far end OPEN
      VNA Port 1 ── tline, far end SHORT
      Two captures (script prompts).
      Z₀(f)     = Z₀_ref · sqrt(Γ_open · Γ_short)   classical method
      VF(f)     from -d(∠(γ·L))/dω                   where γ = atanh(...)
      α (Np/m) = Re(γ) (matched-line loss)
      Reports Z₀(f) too — the property the S21 method can't get.

In both methods the LINE LENGTH must be passed (--length-m or
--length-ft) — the measurement reduces L from observed phase/delay to
the per-unit-length numbers.

Setup considerations
--------------------

The "tline" sample is the line ALONE, not a connectorised patch lead
with two PL-259s on it. Connector reactance dominates the result on
short samples. Use samples ≥ 5 wavelengths long at the highest swept
frequency for sensible results.

For 50-Ω lines (RG-58, RG-213, LMR-400, etc.) the S21 method is
fine and faster. For unknown-Z lines (open-wire, twinlead, PCB
microstrip), use osl-s11 to actually measure Z₀.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Optional

# Suppress mixed-install matplotlib Axes3D import warning (harmless;
# happens when system-package and pip-installed matplotlib are both present).
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


DEFAULT_VNA      = "nanovna"
DEFAULT_PORT     = "/dev/ttyACM1"
DEFAULT_HP_HOST  = "10.1.1.70"
DEFAULT_POINTS   = 401
Z0_REF           = 50.0
C0_M_PER_S       = 299_792_458.0


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


def maybe_set_power(vna, dbm, vna_kind):
    if dbm is None:
        return
    try:
        vna.set_power(float(dbm))
        print(f"  Source power : {dbm:+.1f} dBm")
    except NotImplementedError:
        print(f"  Source power : --power ignored ({vna_kind} has no dBm setpoint)")


def measure_param(vna, param, start_hz, stop_hz, points, averaging):
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_parameter(param)
    vna.single_sweep()
    freqs = vna.get_frequencies()
    data = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    if len(freqs) != len(data):
        raise RuntimeError(f"VNA returned mismatched array lengths "
                           f"(freqs={len(freqs)}, {param}={len(data)})")
    return freqs, data


def prompt(message: str, no_prompt: bool):
    if no_prompt:
        print(f"  [no-prompt] skipping: {message}")
        return
    try:
        input(f"  {message} (press Enter to continue) ")
    except EOFError:
        print(f"  [no stdin] continuing: {message}")


# ---------------------------------------------------------------------------
# S21 method (50-Ω lines, fast)
# ---------------------------------------------------------------------------

def extract_s21(freqs_hz, s21, length_m):
    """Return dict(vf_array, alpha_np_per_m, loss_db_per_m, ...)."""
    omega = 2.0 * np.pi * freqs_hz
    phase = np.unwrap(np.angle(s21))
    # phase of a forward-only-loss line: φ = -β·L  →  β = -dφ/dL = -dφ/(vp·dt)
    # vp = ω·L / -d(phase)/dω → group velocity, not phase velocity.
    # For low loss this matches phase velocity to ~0.1 %. Honest enough.
    d_phase = np.gradient(phase, omega)        # = -L / vp
    vp_array = -length_m / d_phase             # m/s
    # Clamp implausible values that come from edge / wrap noise
    vp_array = np.where((vp_array <= 0) | (vp_array > C0_M_PER_S),
                        np.nan, vp_array)
    vf_array = vp_array / C0_M_PER_S
    alpha = -np.log(np.clip(np.abs(s21), 1e-12, None)) / length_m  # Np/m
    loss_db_per_m = 20.0 / np.log(10.0) * alpha
    return dict(
        vf_array=vf_array,
        alpha_np_per_m=alpha,
        loss_db_per_m=loss_db_per_m,
        z0_known=False,
    )


# ---------------------------------------------------------------------------
# OSL-S11 method (any-Z lines)
# ---------------------------------------------------------------------------

def extract_osl_s11(freqs_hz, g_open, g_short, length_m):
    """
    Classical Z0 and γ extraction from open-then-shorted S11 captures.

    Z_open  = Z0_ref · (1 + g_open ) / (1 - g_open )
    Z_short = Z0_ref · (1 + g_short) / (1 - g_short)
    Z₀(f)   = sqrt(Z_open · Z_short)
    γ·L     = atanh(sqrt(Z_short / Z_open))        (principal branch)
    α       = Re(γ)        Np/m  →  ÷L
    β       = Im(γ)        rad/m →  ÷L
    VF      = ω / (β · c0)
    """
    omega = 2.0 * np.pi * freqs_hz
    # Z_open / Z_short
    eps = 1e-12
    g_o = np.where(np.abs(1 - g_open) < eps,  1 - eps + 0j, g_open)
    g_s = np.where(np.abs(1 - g_short) < eps, 1 - eps + 0j, g_short)
    z_open  = Z0_REF * (1 + g_o) / (1 - g_o)
    z_short = Z0_REF * (1 + g_s) / (1 - g_s)
    z0 = np.sqrt(z_open * z_short)
    # γ·L = atanh(sqrt(Zs/Zo))
    gamma_l = np.arctanh(np.sqrt(z_short / z_open))
    # Pick the branch that makes Im(gamma·L) monotonically growing with f.
    # atanh's principal branch can fold above quarter-wave; unwrap by adding
    # jπ·k where needed.
    beta_l = gamma_l.imag
    # Unwrap β·L: add π when the trace jumps down by >π/2
    diffs = np.diff(beta_l)
    folds = np.where(diffs < -np.pi / 2.0)[0]
    correction = np.zeros_like(beta_l)
    for idx in folds:
        correction[idx + 1:] += np.pi
    beta_l = beta_l + correction
    alpha = gamma_l.real / length_m
    beta  = beta_l       / length_m   # rad/m
    vp = np.where(beta > 0, omega / beta, np.nan)
    vp = np.where((vp <= 0) | (vp > C0_M_PER_S * 1.01), np.nan, vp)
    vf_array = vp / C0_M_PER_S
    loss_db_per_m = 20.0 / np.log(10.0) * alpha
    return dict(
        z0_array=z0,
        vf_array=vf_array,
        alpha_np_per_m=alpha,
        loss_db_per_m=loss_db_per_m,
        z0_known=True,
    )


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, result, method, length_m, units,
             label, driver_name, idn, output_path):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    have_z0 = result["z0_known"]
    n_panels = 3 if have_z0 else 2
    fig, axes = plt.subplots(n_panels, 1, figsize=(11, 4.0 * n_panels + 1.5),
                             sharex=True)
    if n_panels == 1:
        axes = [axes]

    # ── Panel: VF ────────────────────────────────────────────────────────
    ax = axes[0]
    ax.plot(freqs_mhz, result["vf_array"], color="#1f77b4", linewidth=1.2)
    valid = ~np.isnan(result["vf_array"])
    if np.any(valid):
        vf_med = float(np.nanmedian(result["vf_array"]))
        ax.axhline(vf_med, color="#888888", linestyle=":", linewidth=1.0,
                   label=f"median VF = {vf_med:.4f}")
    ax.set_ylabel("Velocity factor")
    ax.set_ylim(0.4, 1.0)
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.92)

    title_lines = [
        f"Transmission Line — {label}  ({length_m:.4f} m / "
        f"{length_m * 3.28084:.3f} ft)",
        f"{freqs_mhz[0]:.4f} – {freqs_mhz[-1]:.4f} MHz  •  {len(freqs_hz)} points"
        f"  •  method: {method}  •  {driver_name}  •  {ts}",
    ]
    if idn:
        title_lines.append(idn[:120])
    ax.set_title("\n".join(title_lines), fontsize=10)

    # ── Panel: Loss ──────────────────────────────────────────────────────
    if units == "ft":
        loss_unit = result["loss_db_per_m"] / 3.28084 * 100.0
        ylabel = "Matched-line loss (dB / 100 ft)"
    else:
        loss_unit = result["loss_db_per_m"] * 100.0
        ylabel = "Matched-line loss (dB / 100 m)"
    ax = axes[1]
    ax.plot(freqs_mhz, loss_unit, color="#d62728", linewidth=1.3)
    ax.set_ylabel(ylabel)
    ax.grid(True, which="both", alpha=0.35)
    # Endpoint annotations
    i_lo, i_hi = 0, len(freqs_mhz) - 1
    ax.annotate(f"{loss_unit[i_lo]:.2f} @ {freqs_mhz[i_lo]:.3f} MHz",
                xy=(freqs_mhz[i_lo], loss_unit[i_lo]),
                xytext=(8, 8), textcoords="offset points",
                fontsize=8, color="#a02020")
    ax.annotate(f"{loss_unit[i_hi]:.2f} @ {freqs_mhz[i_hi]:.3f} MHz",
                xy=(freqs_mhz[i_hi], loss_unit[i_hi]),
                xytext=(-8, 8), textcoords="offset points",
                fontsize=8, color="#a02020", ha="right")
    if not have_z0:
        ax.set_xlabel("Frequency (MHz)")

    # ── Panel: Z₀ ────────────────────────────────────────────────────────
    if have_z0:
        ax = axes[2]
        z0 = result["z0_array"]
        ax.plot(freqs_mhz, np.abs(z0), color="#2ca02c", linewidth=1.3,
                label="|Z₀|")
        ax.plot(freqs_mhz, z0.real,    color="#1f77b4", linewidth=1.0,
                linestyle="--", alpha=0.85, label="Re Z₀")
        ax.plot(freqs_mhz, z0.imag,    color="#ff7f0e", linewidth=1.0,
                linestyle="--", alpha=0.85, label="Im Z₀")
        ax.axhline(50, color="#888888", linewidth=0.6, linestyle=":")
        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("Z₀ (Ω)")
        ax.grid(True, which="both", alpha=0.35)
        ax.legend(loc="upper right", fontsize=8, framealpha=0.92)

    fig.tight_layout()
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Transmission-line characterisation (VF, Z₀, loss) → PDF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=2, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--method", choices=("s21", "osl-s11"), default="s21",
                   help="s21 = port1→tline→port2 (default; needs Z₀ assumed = 50). "
                        "osl-s11 = port1→tline, two passes (OPEN, then SHORT) — "
                        "yields Z₀(f) too.")
    p.add_argument("--length-m", type=float, default=None, metavar="M")
    p.add_argument("--length-ft", type=float, default=None, metavar="FT")
    p.add_argument("--feet", action="store_true",
                   help="Report loss in dB/100 ft (default dB/100 m)")
    p.add_argument("--no-prompt", action="store_true",
                   help="Skip the OPEN/SHORT prompts in osl-s11 mode")
    p.add_argument("--label", default="line under test")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start")
        return 1
    if args.points < 4 or args.average < 1:
        print("Error: --points must be ≥ 4 and --average must be ≥ 1")
        return 1
    if args.length_m is None and args.length_ft is None:
        print("Error: pass either --length-m or --length-ft")
        return 1
    if args.length_m is not None and args.length_ft is not None:
        print("Error: pass either --length-m or --length-ft, not both")
        return 1
    length_m = args.length_m if args.length_m is not None \
        else args.length_ft / 3.28084
    if length_m <= 0:
        print("Error: length must be > 0")
        return 1
    units = "ft" if args.feet else "m"

    print(f"Tline PDF — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.4f} – {args.stop:.4f} MHz, "
          f"{args.points} points, average={args.average}")
    print(f"  Method       : {args.method}")
    print(f"  Length       : {length_m:.4f} m ({length_m * 3.28084:.3f} ft)")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        if args.method == "s21":
            prompt("Connect Port 1 → tline → Port 2 (THRU). "
                   "Capture about to begin.", no_prompt=args.no_prompt)
            freqs_hz, s21 = measure_param(
                vna, "S21",
                args.start * 1e6, args.stop * 1e6,
                args.points, args.average,
            )
            result = extract_s21(freqs_hz, s21, length_m)
            print("  Z₀ assumed   : 50 Ω (S21 method cannot derive Z₀)")
        else:
            prompt("Connect Port 1 → tline, far end OPEN. "
                   "OPEN capture about to begin.", no_prompt=args.no_prompt)
            freqs_hz, g_open = measure_param(
                vna, "S11",
                args.start * 1e6, args.stop * 1e6,
                args.points, args.average,
            )
            prompt("Now SHORT the far end of the tline. "
                   "SHORT capture about to begin.", no_prompt=args.no_prompt)
            freqs_hz2, g_short = measure_param(
                vna, "S11",
                args.start * 1e6, args.stop * 1e6,
                args.points, args.average,
            )
            if not np.allclose(freqs_hz, freqs_hz2):
                print("  WARNING: frequency arrays differ between OPEN and "
                      "SHORT passes; results may be inconsistent.")
            result = extract_osl_s11(freqs_hz, g_open, g_short, length_m)

        valid = ~np.isnan(result["vf_array"])
        if np.any(valid):
            vf_med = float(np.nanmedian(result["vf_array"]))
            print(f"  VF (median)  : {vf_med:.4f}")
        loss_per_100m = float(np.median(result["loss_db_per_m"]) * 100.0)
        print(f"  Loss (median): {loss_per_100m:.2f} dB / 100 m  "
              f"({loss_per_100m / 3.28084:.2f} dB / 100 ft)")
        if result["z0_known"]:
            z0_med_re = float(np.nanmedian(np.abs(result["z0_array"])))
            print(f"  |Z₀| (median): {z0_med_re:.2f} Ω")

        plot_pdf(
            freqs_hz, result, args.method, length_m, units,
            label=args.label,
            driver_name=args.vna.upper(),
            idn=idn,
            output_path=args.output,
        )
        print(f"  Wrote PDF    → {args.output}")
        return 0

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
