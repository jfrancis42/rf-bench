#!/usr/bin/env python3
"""
vector_fit_spice.py — Rational fit of measured S-params → SPICE subckt.

Fits one S-parameter (default S21) from a Touchstone .s2p with a
rational function (sum of poles + residues, Gustavsen 1999 "Vector
Fitting" algorithm), then exports a SPICE subcircuit you can drop
straight into LTspice / ngspice.

Pipeline
--------

  1. Read .s2p
  2. Vector Fitting → poles p_k, residues r_k, constant d, optional
     proportional term h
  3. Compose H(s) = Σ r_k/(s - p_k) + d + h·s
  4. Convert to rational H(s) = N(s)/D(s) (polynomial numerator and
     denominator)
  5. Emit a Laplace-source subcircuit:
         .subckt FIT_S21 in out
         B1 out 0 V = laplace{V(in)} = { N(s) / D(s) }
         .ends
     (LTspice / ngspice both accept this with slight syntax variation —
     the script emits LTspice-flavoured by default; pass --spice-flavor
     to switch.)

Fit quality
-----------

A side-by-side PDF compares measured |S21| / ∠S21 against the rational
fit, with RMS / max error reported.

Algorithm references
--------------------

  - B. Gustavsen and A. Semlyen, "Rational approximation of frequency
    domain responses by Vector Fitting," IEEE Trans. Power Delivery,
    1999.
  - B. Gustavsen, "Improving the pole relocating properties of
    vector fitting," IEEE Trans. Power Delivery, 2006.

This implementation uses the original 1999 algorithm with the standard
real-pole-pair / complex-conjugate-pair handling. It is intentionally
**simple** (~200 lines), not the modern relaxed VF variant from 2006.
For very ill-conditioned data (wideband with many resonances) consider
the python-vectfit package instead.
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


# ---------------------------------------------------------------------------
# Touchstone reader (subset of s2p / s1p)
# ---------------------------------------------------------------------------

def read_touchstone(path: str, parameter: str):
    """
    Parse a Touchstone .s2p (or .s1p). Returns (freqs_hz, H, n_ports).
    H is shape (N,) complex — the selected S-parameter trace.

    parameter ∈ {"S11", "S12", "S21", "S22"}.
    """
    p = parameter.upper()
    if p not in ("S11", "S12", "S21", "S22"):
        raise ValueError(f"parameter must be S11/S12/S21/S22; got {p}")
    freq_mult = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}
    freq_unit = "ghz"
    fmt = "ma"
    z0 = 50.0
    rows = []
    n_ports = None
    is_s2p = path.lower().endswith(".s2p")
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
            if not parts:
                continue
            if is_s2p:
                if len(parts) < 9:
                    continue
                f = float(parts[0])
                vals = [float(x) for x in parts[1:9]]
                rows.append((f, vals))
            else:
                if len(parts) < 3:
                    continue
                f = float(parts[0])
                vals = [float(x) for x in parts[1:3]]
                rows.append((f, vals))

    n = len(rows)
    if not n:
        raise ValueError(f"No data rows in {path}")
    freqs = np.array([r[0] * freq_mult[freq_unit] for r in rows])

    def _to_complex(a, b):
        if fmt == "ri":
            return complex(a, b)
        if fmt == "ma":
            ang = np.deg2rad(b)
            return a * (np.cos(ang) + 1j * np.sin(ang))
        if fmt == "db":
            mag = 10.0 ** (a / 20.0)
            ang = np.deg2rad(b)
            return mag * (np.cos(ang) + 1j * np.sin(ang))
        raise ValueError(f"Unsupported format: {fmt}")

    if is_s2p:
        # Touchstone v1 .s2p columns: S11 S21 S12 S22
        idx_for_param = {"S11": (0, 1), "S21": (2, 3),
                         "S12": (4, 5), "S22": (6, 7)}
        ia, ib = idx_for_param[p]
        H = np.array(
            [_to_complex(rows[i][1][ia], rows[i][1][ib]) for i in range(n)],
            dtype=np.complex128,
        )
        return freqs, H, 2
    else:
        H = np.array(
            [_to_complex(rows[i][1][0], rows[i][1][1]) for i in range(n)],
            dtype=np.complex128,
        )
        return freqs, H, 1


# ---------------------------------------------------------------------------
# Vector Fitting (Gustavsen 1999 — basic real-pole-pair formulation)
# ---------------------------------------------------------------------------

def vector_fit(s_omega: np.ndarray, h: np.ndarray, n_poles: int,
               n_iters: int = 5, with_d: bool = True,
               with_h: bool = False) -> tuple:
    """
    Fit H(s) ≈ Σ_k r_k / (s - p_k)  + d  + h*s   to the data h(jω).

    Input:
        s_omega : array of jω values (purely imaginary, shape (N,))
        h       : measured frequency-domain response (shape (N,) complex)
        n_poles : number of poles to fit
        n_iters : number of pole-relocation iterations (Gustavsen 1999)
        with_d  : include a constant term d
        with_h  : include a proportional term h*s (rarely needed for S-params)

    Returns:
        poles    : (n_poles,) complex array
        residues : (n_poles,) complex array
        d        : float (zero if with_d=False)
        h_prop   : float (zero if with_h=False)
    """
    n = len(s_omega)
    assert len(h) == n

    # Initial pole guess: complex-conjugate pairs spanning the frequency
    # range (Gustavsen's recommended starting set).
    omega_min = np.imag(s_omega).min()
    omega_max = np.imag(s_omega).max()
    omega_min = max(omega_min, omega_max * 1e-3)  # avoid zero
    if n_poles % 2 != 0:
        # Odd number: one real pole + (n_poles-1)/2 conjugate pairs
        n_pair = (n_poles - 1) // 2
    else:
        n_pair = n_poles // 2
    poles = []
    if n_poles % 2 == 1:
        poles.append(-(omega_min + omega_max) / 2.0)
    if n_pair > 0:
        omega_init = np.linspace(omega_min, omega_max, n_pair)
        # Lossy starting poles: real part = -1% of imag, complex-conjugate
        for w in omega_init:
            poles.append(complex(-w * 0.01, w))
            poles.append(complex(-w * 0.01, -w))
    poles = np.array(poles[:n_poles], dtype=np.complex128)

    for it in range(n_iters):
        # === Pole-relocation step ===
        # Build the LS system [A; B] [c; sigma_c] = [h; 0]
        # where the model is:
        #   (sigma(s) * h(s)) ≈ Σ c_k / (s - p_k) + d_h + s*h_h
        #   sigma(s)          ≈ Σ sigma_c_k / (s - p_k) + 1
        # New poles are the zeros of sigma.
        cols = []
        # Phi_k = 1 / (s - p_k), enforce conjugate-pair real-coefficient
        # constraints by replacing pairs (Phi_k, Phi_{k+1}) where
        # p_{k+1} = conj(p_k) with (Re Phi_k + Re Phi_{k+1},
        #                            Im Phi_k - Im Phi_{k+1}).
        # For simplicity here, fit complex coefficients and clean up at end.
        Phi = 1.0 / (s_omega[:, None] - poles[None, :])

        # Columns for c_k
        cols.append(Phi)
        # Optional constant
        if with_d:
            cols.append(np.ones((n, 1), dtype=np.complex128))
        if with_h:
            cols.append(s_omega[:, None])
        # Columns for sigma_c_k: -Phi_k * h
        cols.append(-Phi * h[:, None])

        A = np.hstack(cols)
        # Real-valued LS: stack real and imag rows to force real coefficients
        Areal = np.vstack([A.real, A.imag])
        breal = np.hstack([h.real, h.imag])
        x, *_ = np.linalg.lstsq(Areal, breal, rcond=None)

        offset = n_poles
        c = x[:n_poles].astype(np.complex128)
        if with_d:
            d_h = x[offset]
            offset += 1
        else:
            d_h = 0.0
        if with_h:
            h_prop = x[offset]
            offset += 1
        else:
            h_prop = 0.0
        sigma_c = x[offset:offset + n_poles].astype(np.complex128)

        # New poles = zeros of sigma(s) = 1 + Σ sigma_c_k / (s - p_k)
        # = eigenvalues of A - b * c' where A = diag(p_k), b = ones, c' = sigma_c
        A_diag = np.diag(poles)
        b_col = np.ones(n_poles)
        new_poles = np.linalg.eigvals(A_diag - np.outer(b_col, sigma_c))

        # Stability fix: flip RHP poles into LHP
        real_parts = new_poles.real
        new_poles = np.where(real_parts > 0,
                             new_poles - 2 * real_parts, new_poles)
        poles = new_poles

    # === Residue-fitting step (final) — with the converged poles ===
    Phi = 1.0 / (s_omega[:, None] - poles[None, :])
    cols = [Phi]
    if with_d:
        cols.append(np.ones((n, 1), dtype=np.complex128))
    if with_h:
        cols.append(s_omega[:, None])
    A = np.hstack(cols)
    Areal = np.vstack([A.real, A.imag])
    breal = np.hstack([h.real, h.imag])
    x, *_ = np.linalg.lstsq(Areal, breal, rcond=None)
    residues = x[:n_poles].astype(np.complex128)
    offset = n_poles
    d = x[offset] if with_d else 0.0
    offset += 1 if with_d else 0
    h_prop_final = x[offset] if with_h else 0.0

    return poles, residues, float(d), float(h_prop_final)


def evaluate_fit(s_omega: np.ndarray, poles: np.ndarray,
                 residues: np.ndarray, d: float, h_prop: float) -> np.ndarray:
    """H_fit(s) = Σ r_k / (s - p_k) + d + h_prop * s."""
    out = np.full_like(s_omega, d, dtype=np.complex128)
    for p, r in zip(poles, residues):
        out += r / (s_omega - p)
    if h_prop:
        out += h_prop * s_omega
    return out


# ---------------------------------------------------------------------------
# Rational-form polynomial conversion + SPICE export
# ---------------------------------------------------------------------------

def poles_residues_to_polynomial(poles: np.ndarray, residues: np.ndarray,
                                 d: float, h_prop: float
                                 ) -> tuple[np.ndarray, np.ndarray]:
    """
    Convert the partial-fraction sum to a rational numerator / denominator.

    H(s) = N(s) / D(s)
    where D(s) = Π (s - p_k), and N(s) is obtained by partial-fraction
    inversion + d * D(s) + h_prop * s * D(s).

    Returns (num_coeffs, den_coeffs), each in DESCENDING order of s
    (numpy.poly convention).
    """
    # Denominator: polynomial with roots at the poles
    den = np.poly(poles)
    den = np.real_if_close(den, tol=1e6).astype(np.float64)

    # Numerator: sum over k of r_k · Π_{j≠k} (s - p_j),  plus d · D(s),
    # plus h_prop · s · D(s).
    num = np.zeros(len(den), dtype=np.complex128)
    for k in range(len(poles)):
        other_poles = np.delete(poles, k)
        contrib = np.poly(other_poles) * residues[k]
        # contrib has degree len(poles)-1, pad to match den length
        pad = len(den) - len(contrib)
        contrib = np.concatenate([np.zeros(pad), contrib])
        num += contrib
    if d != 0.0:
        num += d * den
    if h_prop != 0.0:
        # h_prop · s · D(s): shift coefficients up one degree
        shifted = np.concatenate([h_prop * den, [0.0]])
        # Now num has len(den), shifted has len(den)+1: extend num
        num = np.concatenate([[0.0], num])
        den_padded = np.concatenate([[0.0], den])
        num = num + shifted
        den = den_padded

    num = np.real_if_close(num, tol=1e6).astype(np.float64)
    return num, den


def write_spice_subckt(path: str, num: np.ndarray, den: np.ndarray,
                       label: str, parameter: str, flavor: str) -> None:
    """
    Emit a Laplace-source SPICE subcircuit modelling the fit.

    LTspice flavor (default):
        .subckt FIT in out
        B1 out 0 V = laplace { V(in) } = { (num...) / (den...) }
        .ends

    ngspice flavor:
        .subckt FIT in out
        Erational out 0 LAPLACE { V(in) } { (num...) / (den...) }
        .ends
    """
    def _poly_str(coeffs: np.ndarray) -> str:
        """Polynomial in s, highest-degree first, with explicit coefficients."""
        n = len(coeffs)
        terms = []
        for i, c in enumerate(coeffs):
            power = n - 1 - i
            if power == 0:
                terms.append(f"({c:.6e})")
            elif power == 1:
                terms.append(f"({c:.6e})*s")
            else:
                terms.append(f"({c:.6e})*s**{power}")
        return " + ".join(terms)

    num_str = _poly_str(num)
    den_str = _poly_str(den)

    with open(path, "w") as fh:
        fh.write(f"* Vector-fit rational model — {label}\n")
        fh.write(f"* Parameter: {parameter}\n")
        fh.write(f"* Generated: {datetime.now().isoformat(timespec='seconds')}\n")
        fh.write(f"* Numerator degree: {len(num) - 1}\n")
        fh.write(f"* Denominator degree: {len(den) - 1}\n")
        fh.write("*\n")
        fh.write(".subckt FIT_RATIONAL in out\n")
        if flavor == "ltspice":
            fh.write(f"B1 out 0 V=laplace V(in) "
                     f"= ({num_str}) / ({den_str})\n")
        elif flavor == "ngspice":
            fh.write(f"Erational out 0 LAPLACE {{V(in)}} "
                     f"{{({num_str}) / ({den_str})}}\n")
        else:
            raise ValueError(f"unknown SPICE flavor {flavor!r}")
        fh.write(".ends FIT_RATIONAL\n")


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, h_meas, h_fit, parameter, label, n_poles,
             rms_err_db, max_err_db, output_path):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)

    # Magnitude
    mag_meas = 20 * np.log10(np.clip(np.abs(h_meas), 1e-12, None))
    mag_fit  = 20 * np.log10(np.clip(np.abs(h_fit), 1e-12, None))
    axes[0].plot(freqs_mhz, mag_meas, color="#888888", linewidth=1.0,
                 linestyle="--", label="measured")
    axes[0].plot(freqs_mhz, mag_fit, color="#1f77b4", linewidth=1.4,
                 label="fit")
    axes[0].set_ylabel(f"|{parameter}| (dB)")
    axes[0].grid(True, which="both", alpha=0.35)
    axes[0].legend(loc="upper right", fontsize=8, framealpha=0.92)

    # Phase
    ph_meas = np.degrees(np.unwrap(np.angle(h_meas)))
    ph_fit  = np.degrees(np.unwrap(np.angle(h_fit)))
    axes[1].plot(freqs_mhz, ph_meas, color="#888888", linewidth=1.0,
                 linestyle="--", label="measured")
    axes[1].plot(freqs_mhz, ph_fit, color="#9467bd", linewidth=1.4,
                 label="fit")
    axes[1].set_ylabel(f"∠{parameter} (°)")
    axes[1].grid(True, which="both", alpha=0.35)
    axes[1].legend(loc="upper right", fontsize=8, framealpha=0.92)

    # Error
    err_db = mag_fit - mag_meas
    axes[2].plot(freqs_mhz, err_db, color="#d62728", linewidth=1.0,
                 label=f"fit − meas  (RMS {rms_err_db:.2f} dB, "
                       f"max {max_err_db:.2f} dB)")
    axes[2].axhline(0, color="#888888", linewidth=0.6)
    axes[2].set_xlabel("Frequency (MHz)")
    axes[2].set_ylabel("Mag error (dB)")
    axes[2].grid(True, which="both", alpha=0.35)
    axes[2].legend(loc="upper right", fontsize=8, framealpha=0.92)

    title_lines = [
        f"Vector-fit {parameter} → SPICE rational model — {label}",
        f"{freqs_mhz[0]:.4f} – {freqs_mhz[-1]:.4f} MHz  •  "
        f"{len(freqs_hz)} points  •  {n_poles} poles  •  {ts}",
    ]
    fig.suptitle("\n".join(title_lines), fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Fit measured S-params with poles/residues, export SPICE.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input", required=True, metavar="DUT.s2p",
                   help="Touchstone .s2p (or .s1p)")
    p.add_argument("--parameter", default="S21",
                   choices=("S11", "S12", "S21", "S22"),
                   help="Which S-parameter to fit (default S21)")
    p.add_argument("--poles", type=int, default=6, metavar="N",
                   help="Number of poles in the rational fit (default 6). "
                        "More poles = better fit but riskier extrapolation. "
                        "Tip: pick 2 per resonance you can see.")
    p.add_argument("--iters", type=int, default=8, metavar="N",
                   help="Pole-relocation iterations (default 8).")
    p.add_argument("--no-d", action="store_true",
                   help="Drop the constant term from the model (rare; default "
                        "includes it).")
    p.add_argument("--with-h", action="store_true",
                   help="Add a proportional term h*s to the model (use if "
                        "the response rises linearly at high frequency).")
    p.add_argument("--spice-flavor", choices=("ltspice", "ngspice"),
                   default="ltspice",
                   help="Output SPICE syntax flavor (default ltspice)")
    p.add_argument("--label", default="DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    p.add_argument("--spice", default=None, metavar="FILE.sub",
                   help="Output SPICE subcircuit path (default: "
                        "same basename as --output with .sub)")
    args = p.parse_args()

    if args.spice is None:
        args.spice = (args.output[:-4] + ".sub"
                      if args.output.lower().endswith(".pdf")
                      else args.output + ".sub")

    print(f"Vector-fit SPICE — {args.label}")
    print(f"  Input        : {args.input}")
    print(f"  Parameter    : {args.parameter}")
    print(f"  Poles        : {args.poles}")
    print(f"  Iterations   : {args.iters}")
    print(f"  PDF          : {args.output}")
    print(f"  SPICE ({args.spice_flavor}): {args.spice}")

    try:
        freqs_hz, h_meas, n_ports = read_touchstone(args.input, args.parameter)
        s_omega = 1j * 2 * np.pi * freqs_hz

        poles, residues, d, h_prop = vector_fit(
            s_omega, h_meas, n_poles=args.poles,
            n_iters=args.iters,
            with_d=not args.no_d, with_h=args.with_h,
        )
        h_fit = evaluate_fit(s_omega, poles, residues, d, h_prop)

        # Fit-quality stats in dB
        mag_meas_db = 20 * np.log10(np.clip(np.abs(h_meas), 1e-12, None))
        mag_fit_db  = 20 * np.log10(np.clip(np.abs(h_fit),  1e-12, None))
        err = mag_fit_db - mag_meas_db
        rms_err = float(np.sqrt(np.mean(err ** 2)))
        max_err = float(np.max(np.abs(err)))
        print(f"  RMS error    : {rms_err:.3f} dB")
        print(f"  Max error    : {max_err:.3f} dB")

        # Convert to polynomial form & write SPICE
        num, den = poles_residues_to_polynomial(poles, residues, d, h_prop)
        write_spice_subckt(args.spice, num, den, args.label,
                           args.parameter, args.spice_flavor)
        print(f"  Wrote SPICE  → {args.spice}")

        plot_pdf(freqs_hz, h_meas, h_fit, args.parameter, args.label,
                 args.poles, rms_err, max_err, args.output)
        print(f"  Wrote PDF    → {args.output}")
        return 0

    except FileNotFoundError as exc:
        print(f"\nFile not found: {exc.filename}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nFailed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
