#!/usr/bin/env python3
"""
tdr_pdf.py — Time-Domain Reflectometry from S11, NanoVNA or HP 8712B.

A frequency-domain VNA does TDR by inverse-FFT'ing the S11 sweep into
the time domain. The math is host-side; the NanoVNA's on-device TDR
display does exactly the same operation. This script runs the
calculation in Python so it works on any VNA that returns complex
S11 — including the NanoVNA-F and HP 8712B — and produces an
annotated single-page PDF.

What you get
------------
Two stacked panels, X-axis in metres (or feet with --feet):

  - Step response  Γ(d): smooth integral of the impulse response. A
    flat trace at Γ=0 is a matched line. A step UP at d means an
    *open-like* fault. A step DOWN means a *short-like* fault. The
    asymptotic Γ → ±1 is a true open / true short at d.

  - Impulse response |h(d)|: sharper peaks at every reflection.
    Useful for locating multiple discontinuities in one cable.

Cable length / fault distance
-----------------------------
    d = v · τ / 2          (round-trip → one-way)
    v = vf · c              (vf = velocity factor of the cable)

The script auto-finds the largest reflection past a small dead zone
(2 m default to suppress the port-1 connector echo) and prints

    Distance to dominant fault: 23.4 m  (74.7 ft)   Γ = +0.85  (open)

Common velocity factors:
  - RG-58, RG-8X, RG-213 solid PE              vf ≈ 0.66
  - LMR-400, 9913 (foam dielectric)            vf ≈ 0.85
  - Belden 9258 / RG-58U foam                  vf ≈ 0.79
  - Heliax 1/2" foam                           vf ≈ 0.88
  - PTFE-dielectric SMA jumper                 vf ≈ 0.69

Math details
------------
Low-pass step TDR (the kind a sampling-scope TDR does): we treat the
swept S11(f) as a one-sided spectrum, mirror-conjugate to negative
frequencies, apply a window (default Hann), inverse-FFT, and
integrate (cumsum) to get the step response. With a wide sweep that
starts close to DC (50 kHz on the NanoVNA-F) the result is a near-
textbook step TDR. With a sweep that excludes DC (HF VNAs that
start at 300 kHz, 1 MHz, etc.), the script still works but the step
response has a small DC ambiguity — use the impulse panel for fault
location in that case.
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
DEFAULT_VF       = 0.66
DEFAULT_WINDOW   = "hann"
C0_M_PER_S       = 299_792_458.0
DEFAULT_DEAD_M   = 2.0


# Cable types with published velocity factors. Pass --cable to fill VF
# without remembering the number.
CABLE_VF = {
    "RG-58":         0.66,
    "RG-8X":         0.84,    # foam dielectric, modern run
    "RG-58A":        0.66,
    "RG-213":        0.66,
    "RG-214":        0.66,
    "LMR-240":       0.84,
    "LMR-400":       0.85,
    "LMR-600":       0.87,
    "9913":          0.84,
    "Heliax-1/2":    0.88,
    "Heliax-7/8":    0.89,
    "Belden-9258":   0.78,
    "PTFE-jumper":   0.69,
    "twinlead-300":  0.82,
    "ladder-line":   0.91,
}


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


def maybe_set_power(vna, dbm: Optional[float], vna_kind: str) -> None:
    if dbm is None:
        return
    try:
        vna.set_power(float(dbm))
        print(f"  Source power : {dbm:+.1f} dBm")
    except NotImplementedError:
        print(f"  Source power : --power ignored ({vna_kind} has no dBm setpoint)")


def measure_s11(vna, start_hz, stop_hz, points, averaging):
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_parameter("S11")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: single_sweep() returned False — trace may be stale")
    freqs = vna.get_frequencies()
    gamma = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    if len(freqs) != len(gamma):
        raise RuntimeError(
            f"VNA returned mismatched array lengths "
            f"(freqs={len(freqs)}, gamma={len(gamma)})"
        )
    return freqs, gamma


# ---------------------------------------------------------------------------
# TDR math
# ---------------------------------------------------------------------------

def make_window(name: str, n: int) -> np.ndarray:
    """Return a length-n window for the frequency-domain trace."""
    name = name.lower()
    if name == "rect" or name == "none":
        return np.ones(n)
    if name == "hann":
        return np.hanning(n)
    if name == "hamming":
        return np.hamming(n)
    if name == "blackman":
        return np.blackman(n)
    if name == "kaiser":
        return np.kaiser(n, 8.0)
    raise ValueError(f"Unknown window {name!r}; "
                     "choose rect|hann|hamming|blackman|kaiser")


def compute_tdr(freqs_hz: np.ndarray, gamma: np.ndarray,
                vf: float, window_name: str,
                interp_factor: int = 8,
                ) -> dict:
    """
    Run low-pass TDR with optional zero-padding for interpolation in time.

    Returns a dict with:
        distance_m       : (half_len,) one-way distance axis
        step             : (half_len,) cumulative-sum step response
        impulse          : (full_len,) real impulse response — full (both
                           positive and negative-time halves) so gating
                           can FFT it back cleanly
        impulse_abs_pos  : (half_len,) |impulse| over positive-time half
                           (the chart-friendly view)
        n_input          : original sweep length (used to fold the gated
                           spectrum back to the input frequency grid)
        full_len         : zero-padded spectrum length
        dt               : time step in seconds
    """
    n = len(freqs_hz)
    if n < 4:
        raise ValueError("TDR needs at least 4 sweep points")

    df = float(freqs_hz[1] - freqs_hz[0])
    if df <= 0:
        raise ValueError("Frequency spacing is non-positive")

    # Window the frequency-domain trace to suppress sidelobes.
    w = make_window(window_name, n)
    s = gamma * w

    # Low-pass formulation: treat S11(f) as the positive-frequency half of
    # a Hermitian-symmetric spectrum, with f[0] approximated as the DC term.
    # Build the full spectrum: DC, positive freqs, conjugate-mirror negatives.
    # Zero-pad in frequency for finer time-domain interpolation.
    half_len = max(n, 1) * max(1, int(interp_factor))
    full_len = 2 * half_len

    spectrum = np.zeros(full_len, dtype=np.complex128)
    spectrum[0]      = s[0]          # DC ≈ S11 at the lowest swept frequency
    spectrum[1:n]    = s[1:]
    spectrum[full_len - n + 1 : full_len] = np.conj(s[1:][::-1])

    # IFFT → real impulse response sampled at dt = 1 / (df · full_len)
    h = np.fft.ifft(spectrum).real
    dt = 1.0 / (df * full_len)

    # The first half is the causal response we care about (positive time).
    h_pos = h[:half_len]
    t = np.arange(half_len) * dt

    # One-way distance d = vf · c · t / 2
    distance_m = vf * C0_M_PER_S * t / 2.0

    # Step response is the cumulative integral of the impulse response.
    step = np.cumsum(h_pos)

    return dict(
        distance_m=distance_m,
        step=step,
        impulse=h,                          # FULL real impulse response
        impulse_abs_pos=np.abs(h_pos),
        n_input=n,
        full_len=full_len,
        dt=dt,
    )


def compute_gated_response(tdr_result: dict, vf: float,
                           gate_start_m: float, gate_end_m: float,
                           gate_taper_m: float = 0.05,
                           ) -> tuple[np.ndarray, np.ndarray]:
    """
    Zero the impulse response outside the user's spatial gate, FFT back to
    the frequency domain, and return (gated_freqs_hz, gated_gamma).

    A cosine-taper "edge ramp" of width gate_taper_m on each side avoids
    spectral leakage from the sharp gate edges. Taper defaults to 5 cm,
    which is invisibly small at HF and meaningful at 1+ GHz.

    The returned frequency grid is the SAME grid the original sweep
    used (the script trims the inverse-FFT back to the input length).
    """
    impulse  = tdr_result["impulse"]
    full_len = tdr_result["full_len"]
    dt       = tdr_result["dt"]
    n_in     = tdr_result["n_input"]

    # Per-sample one-way distance for the FULL impulse-response axis.
    t_full = np.arange(full_len) * dt
    dist_full = vf * C0_M_PER_S * t_full / 2.0

    # Build the gating window. In the gate band, value = 1; at the edges,
    # cosine ramp from 0 to 1 over `gate_taper_m`. Outside, value = 0.
    gate = np.zeros(full_len, dtype=np.float64)
    in_band = (dist_full >= gate_start_m) & (dist_full <= gate_end_m)
    gate[in_band] = 1.0

    if gate_taper_m > 0:
        rise = (dist_full >= gate_start_m - gate_taper_m) & \
               (dist_full < gate_start_m)
        if np.any(rise):
            x = (dist_full[rise] - (gate_start_m - gate_taper_m)) / gate_taper_m
            gate[rise] = 0.5 * (1.0 - np.cos(np.pi * x))
        fall = (dist_full > gate_end_m) & \
               (dist_full <= gate_end_m + gate_taper_m)
        if np.any(fall):
            x = (dist_full[fall] - gate_end_m) / gate_taper_m
            gate[fall] = 0.5 * (1.0 + np.cos(np.pi * x))

    # Apply gate symmetrically about t = 0 (causal + anti-causal halves)
    # to keep the impulse response real.
    impulse_gated = impulse.copy()
    half = full_len // 2
    # Positive-time half
    impulse_gated[:half] *= gate[:half]
    # Negative-time half (mirror)
    impulse_gated[half:] *= gate[:half][::-1]

    # FFT back to spectrum, take the positive-frequency bins, trim to the
    # input grid length n_in.
    spectrum_gated = np.fft.fft(impulse_gated)
    gated_gamma = spectrum_gated[:n_in]

    return gated_gamma, gate


def find_dominant_fault(distance_m, step, impulse_abs, dead_zone_m: float):
    """
    Identify the largest fault past the dead zone.

    Returns (distance_m, gamma_at_fault, fault_type_text) or None.
    """
    mask = distance_m >= dead_zone_m
    if not np.any(mask):
        return None
    seg_d = distance_m[mask]
    seg_imp = impulse_abs[mask]
    seg_step = step[mask]
    i = int(np.argmax(seg_imp))
    d = float(seg_d[i])
    # Use the post-fault asymptotic value of the step response to characterise
    # the fault sign. Look 1 m past the impulse peak (one wavelength of
    # smoothing) to avoid the impulse-ringing region.
    d_post = d + 1.0
    look = np.where(distance_m >= d_post)[0]
    if look.size:
        g = float(step[look[0]])
    else:
        g = float(seg_step[i])
    if g > 0.05:
        kind = "open-like"
    elif g < -0.05:
        kind = "short-like"
    else:
        kind = "small mismatch"
    return d, g, kind


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(distance_axis, step, impulse_abs, vf, units, fault_info,
             dead_zone, label, driver_name, idn, freqs_hz, output_path,
             gated_gamma=None, gate_band=None):
    sweep_lo_mhz = float(freqs_hz[0] / 1e6)
    sweep_hi_mhz = float(freqs_hz[-1] / 1e6)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Convert distance axis if --feet
    if units == "ft":
        x = distance_axis * 3.28084
        unit_label = "ft"
        dead_zone_disp = dead_zone * 3.28084
    else:
        x = distance_axis
        unit_label = "m"
        dead_zone_disp = dead_zone

    show_gated = gated_gamma is not None
    n_panels = 3 if show_gated else 2
    fig = plt.figure(figsize=(11, 4.5 * n_panels))
    # First two panels share a distance X axis; third (gated) is independent
    if show_gated:
        gs = fig.add_gridspec(3, 1, hspace=0.32)
        ax_step    = fig.add_subplot(gs[0, 0])
        ax_impulse = fig.add_subplot(gs[1, 0], sharex=ax_step)
        ax_gated   = fig.add_subplot(gs[2, 0])
        axes = [ax_step, ax_impulse, ax_gated]
    else:
        gs = fig.add_gridspec(2, 1, hspace=0.05)
        ax_step    = fig.add_subplot(gs[0, 0])
        ax_impulse = fig.add_subplot(gs[1, 0], sharex=ax_step)
        axes = [ax_step, ax_impulse]

    # ── Panel 1: step response ───────────────────────────────────────
    ax = axes[0]
    ax.plot(x, step, color="#1f77b4", linewidth=1.4, label="Step response Γ(d)")
    ax.axhline(0,  color="#888888", linewidth=0.6)
    ax.axhline(1,  color="#cccccc", linewidth=0.6, linestyle="--")
    ax.axhline(-1, color="#cccccc", linewidth=0.6, linestyle="--")
    ax.axvspan(0, dead_zone_disp, color="#888888", alpha=0.10,
               label=f"Dead zone (port connector, {dead_zone_disp:.1f} {unit_label})")
    if fault_info is not None:
        fd, fg, fkind = fault_info
        if units == "ft":
            fd_disp = fd * 3.28084
        else:
            fd_disp = fd
        ax.axvline(fd_disp, color="red", linestyle="--", linewidth=1.0,
                   alpha=0.7)
        ax.annotate(
            f"dominant fault @ {fd_disp:.2f} {unit_label}\n"
            f"Γ = {fg:+.2f}  ({fkind})",
            xy=(fd_disp, fg),
            xytext=(10, -20), textcoords="offset points",
            fontsize=9, color="red",
            arrowprops=dict(arrowstyle="->", color="red", lw=0.8),
            bbox=dict(facecolor="white", edgecolor="red", alpha=0.9, pad=2),
        )
    ax.set_ylabel("Γ (step response)")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.92)
    ax.set_ylim(-1.1, 1.1)

    title_lines = [
        f"TDR — {label}",
        f"Sweep {sweep_lo_mhz:.3f} – {sweep_hi_mhz:.3f} MHz  •  "
        f"vf = {vf:.3f}  •  {driver_name}  •  {ts}",
    ]
    if idn:
        title_lines.append(idn[:120])
    ax.set_title("\n".join(title_lines), fontsize=10)

    # ── Panel 2: impulse response ────────────────────────────────────
    ax = axes[1]
    ax.plot(x, impulse_abs, color="#d62728", linewidth=1.1,
            label="|impulse response|")
    ax.axvspan(0, dead_zone_disp, color="#888888", alpha=0.10)
    if fault_info is not None:
        fd = fault_info[0]
        fd_disp = fd * 3.28084 if units == "ft" else fd
        ax.axvline(fd_disp, color="red", linestyle="--", linewidth=1.0,
                   alpha=0.7)
    # Overlay the gate window on the first two panels
    if gate_band is not None and gate_band[0] is not None:
        g_lo_disp = gate_band[0] * 3.28084 if units == "ft" else gate_band[0]
        g_hi_disp = gate_band[1] * 3.28084 if units == "ft" else gate_band[1]
        for a in (axes[0], axes[1]):
            a.axvspan(g_lo_disp, g_hi_disp, color="#2ca02c", alpha=0.15,
                      label=f"Time gate ({g_lo_disp:.2f}–{g_hi_disp:.2f} "
                            f"{unit_label})")
        # Refresh legends so the gate entry appears
        axes[0].legend(loc="upper right", fontsize=8, framealpha=0.92)
        axes[1].legend(loc="upper right", fontsize=8, framealpha=0.92)
    ax.set_xlabel(f"Distance one-way ({unit_label})")
    ax.set_ylabel("|h(d)|")
    ax.grid(True, which="both", alpha=0.35)
    if gate_band is None or gate_band[0] is None:
        ax.legend(loc="upper right", fontsize=8, framealpha=0.92)

    # ── Optional Panel 3: gated frequency response ───────────────────
    if gated_gamma is not None:
        ax = axes[2]
        freqs_mhz = freqs_hz / 1e6
        rl_db = -20.0 * np.log10(np.clip(np.abs(gated_gamma), 1e-12, None))
        ax.plot(freqs_mhz, rl_db, color="#2ca02c", linewidth=1.4,
                label="Gated return loss")
        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("Return loss of\ngated reflection (dB)")
        ax.set_xlim(float(freqs_mhz[0]), float(freqs_mhz[-1]))
        ax.grid(True, which="both", alpha=0.35)
        ax.legend(loc="upper right", fontsize=8, framealpha=0.92)
        # Reference lines at common RL thresholds
        for db_val, color in ((9.5, "red"), (14.0, "orange"),
                              (20.0, "green"), (26.0, "blue")):
            ax.axhline(db_val, color=color, linestyle="--", linewidth=0.8,
                       alpha=0.5)
        g_lo_disp = gate_band[0] * 3.28084 if units == "ft" else gate_band[0]
        g_hi_disp = gate_band[1] * 3.28084 if units == "ft" else gate_band[1]
        ax.set_title(
            f"Frequency response of just the reflection in "
            f"{g_lo_disp:.2f}–{g_hi_disp:.2f} {unit_label}",
            fontsize=9,
        )

    fig.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Time-Domain Reflectometer from S11 (host-side IFFT).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, default=0.05, metavar="MHZ",
                   help="Sweep start in MHz (default 0.05; NanoVNA-F can do this, "
                        "HP 8712B can only do 0.3 MHz)")
    p.add_argument("--stop",  type=float, default=900.0, metavar="MHZ",
                   help="Sweep stop in MHz (default 900). Wider sweep → "
                        "finer resolution in distance.")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=2, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--vf", type=float, default=None, metavar="VF",
                   help=f"Velocity factor (default 0.66 for solid-PE coax). "
                        "Overridden by --cable.")
    p.add_argument("--cable", default=None, metavar="TYPE",
                   help=f"Pick velocity factor by cable type. Known: "
                        f"{', '.join(sorted(CABLE_VF))}")
    p.add_argument("--max-dist", type=float, default=None, metavar="M_OR_FT",
                   help="Truncate the distance axis at this value")
    p.add_argument("--dead-zone", type=float, default=DEFAULT_DEAD_M, metavar="M",
                   help=f"Dead zone in metres to ignore when finding the "
                        f"dominant fault (default {DEFAULT_DEAD_M:.1f}). "
                        "Suppresses the port-connector ring.")
    p.add_argument("--feet", action="store_true",
                   help="Plot distance in feet instead of metres")
    p.add_argument("--window", default=DEFAULT_WINDOW,
                   choices=("rect", "hann", "hamming", "blackman", "kaiser"))
    p.add_argument("--interp", type=int, default=8, metavar="N",
                   help="Frequency-domain zero-pad factor for time-domain "
                        "interpolation (default 8). Higher = smoother trace, "
                        "no real resolution gain.")
    p.add_argument("--gate-start-m", type=float, default=None, metavar="M",
                   help="Time-gate START distance in metres. Together with "
                        "--gate-end-m, defines a window in the impulse "
                        "response that gets FFT'd back to the frequency "
                        "domain so you can see what just THAT reflection "
                        "contributes to S11. Skip the rest of the cable.")
    p.add_argument("--gate-end-m", type=float, default=None, metavar="M",
                   help="Time-gate END distance in metres.")
    p.add_argument("--gate-start-ft", type=float, default=None, metavar="FT",
                   help="Same as --gate-start-m but in feet.")
    p.add_argument("--gate-end-ft", type=float, default=None, metavar="FT",
                   help="Same as --gate-end-m but in feet.")
    p.add_argument("--gate-taper-m", type=float, default=0.05, metavar="M",
                   help="Width of the cosine edge taper on the gate (default "
                        "0.05 m = 5 cm). Tapers reduce spectral leakage from "
                        "sharp gate edges. Set to 0 for a hard gate.")
    p.add_argument("--label", default="cable")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    # Resolve gate flags (m / ft) into single metres values
    if args.gate_start_ft is not None:
        args.gate_start_m = args.gate_start_ft / 3.28084
    if args.gate_end_ft is not None:
        args.gate_end_m = args.gate_end_ft / 3.28084
    if (args.gate_start_m is None) ^ (args.gate_end_m is None):
        print("Error: pass BOTH --gate-start and --gate-end (or neither)",
              file=sys.stderr)
        return 1

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start")
        return 1
    if args.points < 4 or args.average < 1:
        print("Error: --points must be ≥ 4 and --average must be ≥ 1")
        return 1
    if args.interp < 1:
        print("Error: --interp must be ≥ 1")
        return 1

    # Resolve VF
    if args.cable:
        if args.cable not in CABLE_VF:
            print(f"Error: unknown cable {args.cable!r}. Known: "
                  f"{', '.join(sorted(CABLE_VF))}")
            return 1
        vf = CABLE_VF[args.cable]
    elif args.vf is not None:
        vf = args.vf
    else:
        vf = DEFAULT_VF
    if not (0.0 < vf <= 1.0):
        print(f"Error: vf must be in (0, 1]; got {vf}")
        return 1

    units = "ft" if args.feet else "m"

    print(f"TDR PDF — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.3f} – {args.stop:.3f} MHz, "
          f"{args.points} points, average={args.average}")
    print(f"  Window       : {args.window}")
    print(f"  Velocity fct : {vf:.3f}" +
          (f"  (from cable {args.cable})" if args.cable else ""))
    print(f"  Dead zone    : {args.dead_zone:.2f} m")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        freqs_hz, gamma = measure_s11(
            vna, args.start * 1e6, args.stop * 1e6,
            args.points, args.average,
        )

        # Theoretical resolution and unambiguous range:
        span = float(freqs_hz[-1] - freqs_hz[0])
        df   = float(freqs_hz[1]  - freqs_hz[0])
        resolution_m = vf * C0_M_PER_S / (2.0 * span)
        unambig_m    = vf * C0_M_PER_S / (2.0 * df)
        print(f"  Resolution   : {resolution_m:.3f} m  ({resolution_m * 3.28084:.3f} ft)")
        print(f"  Unambiguous  : {unambig_m:.1f} m  ({unambig_m * 3.28084:.1f} ft)")

        tdr_full = compute_tdr(
            freqs_hz, gamma, vf=vf,
            window_name=args.window,
            interp_factor=args.interp,
        )
        distance_m = tdr_full["distance_m"]
        step = tdr_full["step"]
        impulse_abs = tdr_full["impulse_abs_pos"]

        # Optional time-gating: zero impulse outside [gate_start_m, gate_end_m],
        # FFT back to get the gated frequency response (= what S11 would look
        # like if ONLY the reflections in that distance band were present).
        gated_gamma = None
        gate_window = None
        if args.gate_start_m is not None and args.gate_end_m is not None:
            g_lo = args.gate_start_m
            g_hi = args.gate_end_m
            if units == "ft":
                # Flags were passed in feet via --gate-start-ft / --gate-end-ft
                # so the conversion has already happened upstream.
                pass
            if g_hi <= g_lo:
                print("Error: --gate-end must exceed --gate-start", file=sys.stderr)
                return 1
            gated_gamma, gate_window = compute_gated_response(
                tdr_full, vf=vf,
                gate_start_m=g_lo, gate_end_m=g_hi,
                gate_taper_m=args.gate_taper_m,
            )
            print(f"  Gate         : {g_lo:.3f} – {g_hi:.3f} m  "
                  f"({g_lo*3.28084:.3f} – {g_hi*3.28084:.3f} ft), "
                  f"taper {args.gate_taper_m*100:.1f} cm")
            mag = np.abs(gated_gamma)
            print(f"  Gated |Γ|    : min {mag.min():.4f}, max {mag.max():.4f}, "
                  f"median {np.median(mag):.4f}")

        if args.max_dist is not None:
            max_m = args.max_dist / 3.28084 if args.feet else args.max_dist
            mask = distance_m <= max_m
            distance_m = distance_m[mask]
            step = step[mask]
            impulse_abs = impulse_abs[mask]

        fault_info = find_dominant_fault(distance_m, step, impulse_abs,
                                         dead_zone_m=args.dead_zone)
        if fault_info is None:
            print("  No fault candidates past the dead zone.")
        else:
            fd, fg, fkind = fault_info
            if units == "ft":
                print(f"  Fault @      : {fd:.3f} m  ({fd * 3.28084:.3f} ft)")
            else:
                print(f"  Fault @      : {fd:.3f} m  ({fd * 3.28084:.3f} ft)")
            print(f"  Γ at fault   : {fg:+.3f}  ({fkind})")

        plot_pdf(
            distance_m, step, impulse_abs, vf,
            units=units, fault_info=fault_info,
            dead_zone=args.dead_zone,
            label=args.label,
            driver_name=args.vna.upper(),
            idn=idn,
            freqs_hz=freqs_hz,
            output_path=args.output,
            gated_gamma=gated_gamma,
            gate_band=(args.gate_start_m, args.gate_end_m)
                if args.gate_start_m is not None else None,
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
