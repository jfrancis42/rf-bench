#!/usr/bin/env python3
"""
crystal_bvd_pdf.py — Extract Butterworth-Van Dyke parameters from a crystal.

Fits the standard 4-parameter motional model to a measured S21 sweep
across a crystal's series resonance.

The Butterworth-Van Dyke (BVD) model:

                    Lm   Cm   Rm
              o───┬──[||||]─[||]─[/\\]──┬───o
                  │                     │
                 ─┴─  C0               ─┴─
                  ─                     ─
                  │                     │
              o───┴────────────────────┴───o

A motional branch (Lm series, Cm series, Rm series) in parallel with
a static / electrode capacitance C0. The motional branch resonates
at:

    fs = 1 / (2π · √(Lm · Cm))                series resonance

A second, anti-resonance ("parallel-resonance") appears just above:

    fp = fs · √(1 + Cm/C0)                    parallel resonance

The motional Q and ratios that ham filter designers care about:

    Qm  = (2π · fs · Lm) / Rm                  motional Q
    r   = C0 / Cm                              capacitance ratio
    BW  = fp - fs                              series–parallel spread

Capture options
---------------
**Live (default):** the script will sweep a configured VNA across
a narrow window centred on the user's --estimate frequency and
extract BVD from the captured S21.

**Offline:** pass --from-s2p FILE.s2p to skip the VNA and fit a
previously-saved capture.

Fixture
-------
The standard crystal-test fixture is a low-impedance shunt:

  Port 1 ──┬─ small R ─[crystal]─ small R ─┬── Port 2
           │                                │
           ↓ ground                          ↓ ground

The series-R values (typically 12.5 Ω) approximately match the
crystal's motional resistance to 50 Ω; "approximately" because the
math we do is exact in the small-signal limit and doesn't actually
need the fixture R to be tuned.

The BVD extraction assumes the fixture is symmetric and small-loss
relative to the crystal. For lab-grade Qm measurement, characterise
the empty fixture and de-embed it (see `../de-embed-pdf/`).

Math used to fit
-----------------
At series resonance the impedance Z(f) of the crystal drops to a
minimum (≈ Rm) and the phase passes through zero. Just above, at
parallel resonance, |Z| peaks and the phase passes back through zero.
From the S21 trace:

  Z(f) = 2·Z0 · (1 - S21) / S21   (series-through topology)

We locate fs (Re Z = 0, dZ/df > 0), fp (Re Z = 0, dZ/df < 0 just
above), and Rm = Re Z at fs.

Then Lm and Cm follow from the standard BVD relations:

  ωs = 2π · fs
  C0 = (parsed from off-resonance |Z|, where Z ≈ 1/(jωC0))
  Cm = C0 / ((fp/fs)² − 1)
  Lm = 1 / (Cm · ωs²)
  Qm = ωs · Lm / Rm
"""

from __future__ import annotations

# Suppress mixed-install matplotlib Axes3D import warning (harmless;
# happens when system-package and pip-installed matplotlib are both present).
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")

import argparse
import sys
from datetime import datetime
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


DEFAULT_VNA      = "nanovna"
DEFAULT_PORT     = "/dev/ttyACM1"
DEFAULT_HP_HOST  = "10.1.1.70"
DEFAULT_POINTS   = 401
Z0               = 50.0


# ---------------------------------------------------------------------------
# Touchstone .s2p reader (subset)
# ---------------------------------------------------------------------------

def read_s2p(path: str):
    """Parse a Touchstone v1 .s2p. Returns (freqs_hz, S, z0)."""
    freq_mult = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}
    freq_unit = "ghz"
    fmt = "ma"
    z0 = 50.0
    rows = []
    with open(path) as fh:
        for raw in fh:
            line = raw.split("!", 1)[0].strip()
            if not line:
                continue
            if line.startswith("#"):
                tokens = line[1:].split()
                i = 0
                while i < len(tokens):
                    tok = tokens[i].lower()
                    if tok in freq_mult:
                        freq_unit = tok
                    elif tok in ("ma", "db", "ri"):
                        fmt = tok
                    elif tok == "r" and i + 1 < len(tokens):
                        z0 = float(tokens[i + 1])
                        i += 1
                    i += 1
                continue
            parts = line.split()
            if len(parts) < 9:
                continue
            f = float(parts[0])
            vals = [float(x) for x in parts[1:9]]
            if fmt == "ri":
                s11 = complex(vals[0], vals[1])
                s21 = complex(vals[2], vals[3])
                s12 = complex(vals[4], vals[5])
                s22 = complex(vals[6], vals[7])
            elif fmt == "ma":
                def _ma(m, a):
                    a = np.deg2rad(a); return m * (np.cos(a) + 1j*np.sin(a))
                s11 = _ma(vals[0], vals[1]); s21 = _ma(vals[2], vals[3])
                s12 = _ma(vals[4], vals[5]); s22 = _ma(vals[6], vals[7])
            elif fmt == "db":
                def _db(d, a):
                    m = 10.0 ** (d / 20.0); a = np.deg2rad(a)
                    return m * (np.cos(a) + 1j*np.sin(a))
                s11 = _db(vals[0], vals[1]); s21 = _db(vals[2], vals[3])
                s12 = _db(vals[4], vals[5]); s22 = _db(vals[6], vals[7])
            rows.append((f, s11, s12, s21, s22))
    if not rows:
        raise ValueError(f"No data rows parsed from {path}")
    n = len(rows)
    freqs = np.array([r[0] * freq_mult[freq_unit] for r in rows])
    s21 = np.array([r[3] for r in rows], dtype=np.complex128)
    return freqs, s21, z0


# ---------------------------------------------------------------------------
# Live VNA capture
# ---------------------------------------------------------------------------

def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port), "nanovna"
    elif args.vna == "hp":
        from rf_bench.hp import HP8712B
        return HP8712B(host=args.host), "hp"
    raise ValueError(f"--vna must be 'nanovna' or 'hp', got {args.vna!r}")


def maybe_set_power(vna, dbm, vna_kind):
    if dbm is None:
        return
    try:
        vna.set_power(float(dbm))
        print(f"  Source power : {dbm:+.1f} dBm")
    except NotImplementedError:
        print(f"  Source power : --power ignored ({vna_kind} has no dBm setpoint)")


def capture_s21(vna, start_hz, stop_hz, points, averaging):
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_parameter("S21")
    vna.single_sweep()
    freqs = vna.get_frequencies()
    s21 = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    return freqs, s21


# ---------------------------------------------------------------------------
# BVD extraction
# ---------------------------------------------------------------------------

def s21_to_z_series(s21: np.ndarray) -> np.ndarray:
    """Series-through impedance: Z = 2·Z0·(1 - S21)/S21."""
    safe = np.where(np.abs(s21) < 1e-12, 1e-12 + 0j, s21)
    return 2.0 * Z0 * (1.0 - safe) / safe


def find_zero_crossings(y: np.ndarray):
    """Return indices i where y[i] and y[i+1] straddle 0."""
    out = []
    for i in range(len(y) - 1):
        if y[i] == 0.0:
            out.append(i)
        elif y[i] * y[i + 1] < 0.0:
            out.append(i)
    return out


def interp_zero(freqs_hz, y, i):
    """Linearly interpolate the zero crossing between sample i and i+1."""
    f0, f1 = freqs_hz[i], freqs_hz[i + 1]
    y0, y1 = y[i], y[i + 1]
    if y1 == y0:
        return float(f0)
    return float(f0 + (-y0) * (f1 - f0) / (y1 - y0))


def fit_bvd(freqs_hz: np.ndarray, s21: np.ndarray) -> dict:
    """
    Extract BVD parameters from the S21 trace.

    Returns dict with: fs_hz, fp_hz, Rm_ohm, Cm_F, Lm_H, C0_F, Qm.
    Returns None values if a feature couldn't be located.
    """
    Z = s21_to_z_series(s21)
    R = Z.real
    X = Z.imag
    crossings = find_zero_crossings(X)

    if len(crossings) < 2:
        raise RuntimeError(
            "Couldn't locate two X=0 crossings (need both series and parallel "
            "resonance). Either the sweep is too narrow, the crystal isn't "
            "actually resonating in this band, or fixture loss has obscured "
            "the response. Try a wider sweep or more averaging.")

    # Order the two crossings by frequency. The lower-f one is series
    # resonance (X going from negative to positive); the higher-f one
    # is parallel resonance (X going from positive to negative).
    # In practice both BVD resonances always come paired: series first.
    fs_hz = interp_zero(freqs_hz, X, crossings[0])
    fp_hz = interp_zero(freqs_hz, X, crossings[1])
    if fp_hz <= fs_hz:
        # Defensive: swap if needed
        fs_hz, fp_hz = sorted((fs_hz, fp_hz))

    # Rm = Re Z at fs
    Rm = float(np.interp(fs_hz, freqs_hz, R))

    # C0 from off-resonance admittance, with motional-branch back-out.
    #
    # At any off-resonance frequency, total admittance Y = Y_motional + jωC0.
    # The motional branch, in the small-loss limit, is jωCm in series
    # with 1/(jωLm), giving Y_m(ω) = jωCm / (1 - (ω/ωs)²) where
    # ωs² = 1/(Lm·Cm). Below fs this is small and capacitive; above fp
    # this is small and inductive.
    #
    # We do a 2-pass fit:
    #   Pass 1: assume Y_m ≈ 0 at the sweep extremes, take median Im(Y)/ω
    #           as a first C0 estimate.
    #   Pass 2: from C0 and the (fp/fs) ratio compute Cm and Lm. Back out
    #           Y_m from the off-resonance samples; re-take the median.
    #   Iterate Pass 2 once more for convergence.
    n_band = max(2, len(freqs_hz) // 10)
    # Sample the BOTTOM 10% (always available, even when sweep is asymmetric).
    Y_low  = 1.0 / (R[:n_band] + 1j * X[:n_band])
    omega_low = 2 * np.pi * freqs_hz[:n_band]
    if not Y_low.size:
        C0 = float("nan")
    else:
        # Pass 1 — raw estimate
        C0 = float(abs(np.median(Y_low.imag / omega_low)))
        # Pass 2 — refine by removing motional contribution
        for _ in range(3):
            ratio = (fp_hz / fs_hz) ** 2 - 1.0
            if ratio <= 0:
                break
            Cm_est = C0 * ratio
            omega_s = 2 * np.pi * fs_hz
            Lm_est = 1.0 / (Cm_est * omega_s ** 2)
            # Motional admittance at the off-resonance band:
            #   Y_m(ω) = 1 / (jωLm + 1/(jωCm))
            #         = 1 / (j(ωLm − 1/(ωCm)))
            Xm = omega_low * Lm_est - 1.0 / (omega_low * Cm_est)
            # |Y_m| ≪ |Y_total| in the band; ignore Rm contribution
            Y_motional = 1.0 / (1j * Xm)
            Y_C0 = Y_low - Y_motional
            new_C0 = float(abs(np.median(Y_C0.imag / omega_low)))
            if abs(new_C0 - C0) / C0 < 1e-4:
                C0 = new_C0
                break
            C0 = new_C0

    # Cm from the series/parallel ratio:
    #   (fp/fs)^2 = 1 + Cm/C0   →   Cm = C0 * ((fp/fs)^2 - 1)
    if not np.isnan(C0):
        ratio = (fp_hz / fs_hz) ** 2 - 1.0
        if ratio > 0:
            Cm = C0 * ratio
        else:
            Cm = float("nan")
    else:
        Cm = float("nan")

    # Lm from fs and Cm
    if not np.isnan(Cm) and Cm > 0:
        omega_s = 2 * np.pi * fs_hz
        Lm = 1.0 / (Cm * omega_s ** 2)
    else:
        Lm = float("nan")

    # Motional Q
    if not np.isnan(Lm) and Rm > 0:
        Qm = (2 * np.pi * fs_hz * Lm) / Rm
    else:
        Qm = float("nan")

    return dict(
        fs_hz=fs_hz, fp_hz=fp_hz, Rm_ohm=Rm,
        Cm_F=Cm, Lm_H=Lm, C0_F=C0, Qm=Qm,
        bw_hz=fp_hz - fs_hz,
        cap_ratio=(C0 / Cm) if (not np.isnan(Cm) and Cm > 0) else float("nan"),
    )


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, s21, bvd, label, driver_name, output_path):
    freqs_khz = freqs_hz / 1e3
    Z = s21_to_z_series(s21)
    R = Z.real
    X = Z.imag
    mag_db = 20 * np.log10(np.clip(np.abs(s21), 1e-12, None))
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)

    # Panel 1: |S21| dB (the chart everyone recognises)
    ax = axes[0]
    ax.plot(freqs_khz, mag_db, color="#1f77b4", linewidth=1.2)
    ax.axvline(bvd["fs_hz"] / 1e3, color="green", linestyle="--",
               linewidth=0.9, label=f"fs = {bvd['fs_hz']/1e3:.3f} kHz")
    ax.axvline(bvd["fp_hz"] / 1e3, color="red", linestyle="--",
               linewidth=0.9, label=f"fp = {bvd['fp_hz']/1e3:.3f} kHz")
    ax.set_ylabel("|S21| (dB)")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.92)

    # Panel 2: R and X
    ax = axes[1]
    ax.plot(freqs_khz, R, color="#d62728", linewidth=1.2, label="R")
    ax.plot(freqs_khz, X, color="#2ca02c", linewidth=1.2, label="X")
    ax.axhline(0, color="#888888", linewidth=0.6)
    ax.axvline(bvd["fs_hz"] / 1e3, color="green", linestyle="--",
               linewidth=0.8, alpha=0.7)
    ax.axvline(bvd["fp_hz"] / 1e3, color="red", linestyle="--",
               linewidth=0.8, alpha=0.7)
    ax.set_ylabel("R, X (Ω)")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.92)

    # Panel 3: log |Z| with annotations
    ax = axes[2]
    ax.semilogy(freqs_khz, np.abs(Z), color="#1f77b4", linewidth=1.3)
    ax.axvline(bvd["fs_hz"] / 1e3, color="green", linestyle="--",
               linewidth=0.9)
    ax.axvline(bvd["fp_hz"] / 1e3, color="red", linestyle="--",
               linewidth=0.9)
    ax.set_xlabel("Frequency (kHz)")
    ax.set_ylabel("|Z| (Ω, log)")
    ax.grid(True, which="both", alpha=0.35)

    # BVD parameter block
    def fmt_si(x, unit):
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return "n/a"
        # Engineering notation, 3 sig figs
        from math import floor, log10
        if x == 0:
            return f"0 {unit}"
        e = int(floor(log10(abs(x))))
        prefixes = {-15: "f", -12: "p", -9: "n", -6: "µ", -3: "m",
                    0: "", 3: "k", 6: "M", 9: "G"}
        # Round e down to nearest multiple of 3
        e3 = (e // 3) * 3
        if e3 not in prefixes:
            e3 = max(min(e3, 9), -15)
        m = x / (10.0 ** e3)
        return f"{m:.4g} {prefixes[e3]}{unit}"

    lines = [
        "BVD model parameters",
        f"  fs  = {bvd['fs_hz']/1e3:.4f} kHz",
        f"  fp  = {bvd['fp_hz']/1e3:.4f} kHz   (BW = {bvd['bw_hz']:.1f} Hz)",
        f"  Rm  = {bvd['Rm_ohm']:.2f} Ω",
        f"  Lm  = {fmt_si(bvd['Lm_H'],  'H')}",
        f"  Cm  = {fmt_si(bvd['Cm_F'],  'F')}",
        f"  C0  = {fmt_si(bvd['C0_F'],  'F')}",
        f"  Qm  = {'n/a' if np.isnan(bvd['Qm']) else f'{bvd['Qm']:.0f}'}",
        f"  C0/Cm = {bvd['cap_ratio']:.1f}",
    ]
    axes[0].text(
        0.005, 0.005, "\n".join(lines),
        transform=axes[0].transAxes, fontsize=8, family="monospace",
        va="bottom", ha="left",
        bbox=dict(facecolor="white", edgecolor="#cccccc", alpha=0.92, pad=4),
    )

    title_lines = [
        f"Crystal BVD Extraction — {label}",
        f"{freqs_khz[0]:.4f} – {freqs_khz[-1]:.4f} kHz  •  "
        f"{len(freqs_hz)} points  •  {driver_name}  •  {ts}",
    ]
    fig.suptitle("\n".join(title_lines), fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


def write_spice_netlist(path: str, bvd: dict, label: str) -> None:
    """Dump a SPICE-paste-ready BVD subcircuit."""
    with open(path, "w") as fh:
        fh.write(f"* Butterworth-Van Dyke model for: {label}\n")
        fh.write(f"* Generated: {datetime.now().isoformat(timespec='seconds')}\n")
        fh.write(f"* fs = {bvd['fs_hz']:.6e} Hz   fp = {bvd['fp_hz']:.6e} Hz\n")
        fh.write(f"* Qm = "
                 f"{'n/a' if np.isnan(bvd['Qm']) else f'{bvd['Qm']:.0f}'}\n")
        fh.write(".subckt XTAL_BVD a b\n")
        fh.write(f"Lm a x  {bvd['Lm_H']:.6e}\n")
        fh.write(f"Cm x y  {bvd['Cm_F']:.6e}\n")
        fh.write(f"Rm y b  {bvd['Rm_ohm']:.6e}\n")
        fh.write(f"C0 a b  {bvd['C0_F']:.6e}\n")
        fh.write(".ends\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Extract Butterworth-Van Dyke parameters from a crystal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--estimate", type=float, metavar="MHZ",
                     help="Estimated series-resonance frequency in MHz. The "
                          "script sweeps ±0.1%% around this value via the VNA. "
                          "Use this for a live capture.")
    src.add_argument("--from-s2p", default=None, metavar="FILE.s2p",
                     help="Skip VNA capture; fit a pre-saved .s2p instead.")
    # VNA-related options (live capture only)
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--span-ppm", type=float, default=20000.0,
                   help="Sweep span in PPM around --estimate (default 20000 "
                        "= ±1%%; ~ ±100 kHz at 10 MHz). Wide enough that "
                        "the band BELOW fs is well off-resonance, which is "
                        "needed for the C0 fit. Narrower spans give noisier "
                        "C0 and therefore noisier Cm/Lm.")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=4, metavar="N")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--label", default="crystal")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    p.add_argument("--spice", default=None, metavar="FILE.sub",
                   help="Optional path to write a SPICE BVD subcircuit "
                        "(default: same basename as --output with .sub)")
    args = p.parse_args()

    if args.spice is None:
        args.spice = (args.output[:-4] + ".sub"
                      if args.output.lower().endswith(".pdf")
                      else args.output + ".sub")

    print(f"Crystal BVD — {args.label}")
    print(f"  PDF          : {args.output}")
    print(f"  SPICE netlist: {args.spice}")

    try:
        if args.from_s2p:
            print(f"  Source       : .s2p file {args.from_s2p}")
            freqs_hz, s21, _ = read_s2p(args.from_s2p)
            driver_name = "from-s2p"
        else:
            fs_est_hz = args.estimate * 1e6
            half_span = fs_est_hz * (args.span_ppm * 1e-6) / 2.0
            start_hz = fs_est_hz - half_span
            stop_hz  = fs_est_hz + half_span
            print(f"  Estimate fs  : {args.estimate:.4f} MHz "
                  f"(span ±{args.span_ppm/2:.1f} ppm)")
            print(f"  Sweep        : {start_hz/1e3:.3f} – {stop_hz/1e3:.3f} kHz, "
                  f"{args.points} points, average={args.average}")
            vna, vna_kind = open_vna(args)
            try:
                idn = vna.identify()
                print(f"  IDN          : {idn[:120]}")
                maybe_set_power(vna, args.power, vna_kind)
                freqs_hz, s21 = capture_s21(
                    vna, start_hz, stop_hz, args.points, args.average,
                )
            finally:
                vna.close()
            driver_name = args.vna.upper()

        bvd = fit_bvd(freqs_hz, s21)

        print()
        print(f"  fs           : {bvd['fs_hz']/1e3:.4f} kHz")
        print(f"  fp           : {bvd['fp_hz']/1e3:.4f} kHz  "
              f"(spread {bvd['bw_hz']:.1f} Hz)")
        print(f"  Rm           : {bvd['Rm_ohm']:.2f} Ω")
        print(f"  Cm           : {bvd['Cm_F']:.3e} F  "
              f"({bvd['Cm_F']*1e15:.2f} fF)")
        print(f"  Lm           : {bvd['Lm_H']:.3e} H  "
              f"({bvd['Lm_H']*1e3:.3f} mH)")
        print(f"  C0           : {bvd['C0_F']:.3e} F  "
              f"({bvd['C0_F']*1e12:.2f} pF)")
        print(f"  Qm           : "
              f"{'n/a' if np.isnan(bvd['Qm']) else f'{bvd['Qm']:.0f}'}")
        print(f"  C0/Cm        : {bvd['cap_ratio']:.1f}")

        plot_pdf(freqs_hz, s21, bvd, args.label, driver_name, args.output)
        write_spice_netlist(args.spice, bvd, args.label)
        print(f"  Wrote PDF    → {args.output}")
        print(f"  Wrote SPICE  → {args.spice}")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        print(f"\nFailed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
