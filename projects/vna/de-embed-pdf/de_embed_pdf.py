#!/usr/bin/env python3
"""
de_embed_pdf.py — Mathematically remove a known fixture from a measurement.

Pure post-processor. Takes two Touchstone .s2p files:

  measurement.s2p  — what the VNA actually saw (fixture + DUT cascaded)
  fixture.s2p      — fixture alone, captured separately (DUT replaced by THRU)

Computes the DUT's true S-parameters by inverting the fixture's T-matrix
(scattering-transfer / ABCD-like representation) on each side. Writes a
clean dut.s2p and a side-by-side before/after PDF.

This is the technique every commercial VNA's "fixture compensation" or
"port extension" feature reduces to. It moves the reference plane from
"at the SMA jack" to "at the chip pad" (or wherever the fixture ends
and the DUT begins).

Topology assumption
-------------------
The fixture sits as a SYMMETRIC cascade around the DUT:

    [Port1 ── Fixture_in ── DUT ── Fixture_out ── Port2]

The script supports two fixture models:

  --topology symmetric    (default)
      One fixture.s2p describes BOTH sides. The de-embed treats the
      measured s21 path as Fix_in → DUT → mirror(Fix_in). This is
      correct for symmetric jigs (the typical PCB-with-two-SMA-jacks
      fixture, when you can characterise one half by terminating
      the centre in 50 Ω).

  --topology asymmetric --fixture-out OUT.s2p
      Two fixture files, one per side. Use when the input-side and
      output-side launches genuinely differ (different connector,
      different trace length, etc.).

Math
----
S to T (scattering-transfer) matrix conversion:

    T = (1/S21) · [[S12·S21 - S11·S22,  S11],
                   [-S22,                1  ]]

Forward T-matrix cascade:

    T_meas = T_fix_in · T_dut · T_fix_out

De-embed:

    T_dut = inv(T_fix_in) · T_meas · inv(T_fix_out)

Then T → S:

    S = (1/T22) · [[T12,             T11·T22 - T12·T21],
                   [1,               -T21              ]]

Both VNAs return complex S-parameters of identical shape, so this
script doesn't care which VNA produced the inputs.
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
# Touchstone reader / writer
# ---------------------------------------------------------------------------

def read_s2p(path: str):
    """
    Parse a Touchstone v1 .s2p file. Returns (freqs_hz, S, z0, fmt_used).

    S is shape (N, 2, 2), complex128, indexed as S[i,row,col] where
    row=0/col=0 = S11, row=0/col=1 = S12, etc.

    Column ordering on disk is Touchstone v1: S11 S21 S12 S22.
    """
    freq_mult = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}
    freq_unit = "ghz"   # Touchstone default
    param_kind = "s"
    fmt = "ma"          # default in Touchstone v1
    z0 = 50.0
    rows: list[tuple[float, complex, complex, complex, complex]] = []

    with open(path) as fh:
        for raw in fh:
            line = raw.split("!", 1)[0].strip()
            if not line:
                continue
            if line.startswith("#"):
                tokens = line[1:].split()
                # # <freq-unit> <param-kind> <format> R <Z0>
                i = 0
                while i < len(tokens):
                    tok = tokens[i].lower()
                    if tok in freq_mult:
                        freq_unit = tok
                    elif tok in ("s",):
                        param_kind = tok
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
                def _ma(m, a_deg):
                    a = np.deg2rad(a_deg)
                    return m * (np.cos(a) + 1j * np.sin(a))
                s11 = _ma(vals[0], vals[1])
                s21 = _ma(vals[2], vals[3])
                s12 = _ma(vals[4], vals[5])
                s22 = _ma(vals[6], vals[7])
            elif fmt == "db":
                def _db(db_, a_deg):
                    m = 10.0 ** (db_ / 20.0)
                    a = np.deg2rad(a_deg)
                    return m * (np.cos(a) + 1j * np.sin(a))
                s11 = _db(vals[0], vals[1])
                s21 = _db(vals[2], vals[3])
                s12 = _db(vals[4], vals[5])
                s22 = _db(vals[6], vals[7])
            else:
                raise ValueError(f"Unsupported Touchstone format: {fmt}")
            rows.append((f, s11, s21, s12, s22))

    if not rows:
        raise ValueError(f"No data rows parsed from {path}")
    if param_kind != "s":
        raise ValueError(f"Only S-parameter Touchstone files are supported; "
                         f"got {param_kind}")

    n = len(rows)
    freqs = np.empty(n, dtype=np.float64)
    S = np.empty((n, 2, 2), dtype=np.complex128)
    for i, (f, s11, s21, s12, s22) in enumerate(rows):
        freqs[i] = f * freq_mult[freq_unit]
        S[i, 0, 0] = s11
        S[i, 0, 1] = s12
        S[i, 1, 0] = s21
        S[i, 1, 1] = s22
    return freqs, S, z0, fmt


def write_s2p(path: str, freqs_hz: np.ndarray, S: np.ndarray, z0: float,
              comment_lines: list[str] | None = None) -> None:
    """Write a Touchstone .s2p file in MA format at the given Z0."""
    with open(path, "w") as fh:
        fh.write("! Touchstone .s2p, generated by de_embed_pdf.py\n")
        fh.write(f"! Date: {datetime.now().isoformat(timespec='seconds')}\n")
        if comment_lines:
            for line in comment_lines:
                fh.write(f"! {line}\n")
        fh.write(f"# Hz S MA R {z0:g}\n")
        for i in range(len(freqs_hz)):
            s11 = S[i, 0, 0]
            s12 = S[i, 0, 1]
            s21 = S[i, 1, 0]
            s22 = S[i, 1, 1]
            row = [
                float(freqs_hz[i]),
                float(np.abs(s11)), float(np.degrees(np.angle(s11))),
                float(np.abs(s21)), float(np.degrees(np.angle(s21))),
                float(np.abs(s12)), float(np.degrees(np.angle(s12))),
                float(np.abs(s22)), float(np.degrees(np.angle(s22))),
            ]
            fh.write(" ".join(f"{v:.6e}" for v in row) + "\n")


# ---------------------------------------------------------------------------
# S ↔ T matrix conversion + de-embedding
# ---------------------------------------------------------------------------

def s_to_t(S: np.ndarray) -> np.ndarray:
    """
    Convert S to T (scattering-transfer) matrix.

    T = (1/S21) · [[S12·S21 - S11·S22,  S11],
                   [-S22,                1  ]]

    S, T both shape (N, 2, 2) complex.
    """
    s11 = S[:, 0, 0]
    s12 = S[:, 0, 1]
    s21 = S[:, 1, 0]
    s22 = S[:, 1, 1]
    s21_safe = np.where(np.abs(s21) < 1e-12, 1e-12 + 0j, s21)
    T = np.empty_like(S)
    T[:, 0, 0] = (s12 * s21 - s11 * s22) / s21_safe
    T[:, 0, 1] = s11 / s21_safe
    T[:, 1, 0] = -s22 / s21_safe
    T[:, 1, 1] = 1.0 / s21_safe
    return T


def t_to_s(T: np.ndarray) -> np.ndarray:
    """
    Convert T back to S.

    S = (1/T22) · [[T12,             T11·T22 - T12·T21],
                   [1,               -T21              ]]
    """
    t11 = T[:, 0, 0]
    t12 = T[:, 0, 1]
    t21 = T[:, 1, 0]
    t22 = T[:, 1, 1]
    t22_safe = np.where(np.abs(t22) < 1e-12, 1e-12 + 0j, t22)
    S = np.empty_like(T)
    S[:, 0, 0] = t12 / t22_safe
    S[:, 0, 1] = (t11 * t22 - t12 * t21) / t22_safe
    S[:, 1, 0] = 1.0 / t22_safe
    S[:, 1, 1] = -t21 / t22_safe
    return S


def mirror_two_port(S: np.ndarray) -> np.ndarray:
    """
    Return the port-reversed (mirrored) version of a 2-port S matrix.

    Swap S11 ↔ S22 and S12 ↔ S21. The new "port 1" sees what was port 2.
    For a symmetric fixture characterised as a half-jig (input side
    only), the output-side jig is the mirror of the input side.
    """
    out = np.empty_like(S)
    out[:, 0, 0] = S[:, 1, 1]
    out[:, 0, 1] = S[:, 1, 0]
    out[:, 1, 0] = S[:, 0, 1]
    out[:, 1, 1] = S[:, 0, 0]
    return out


def de_embed(T_meas: np.ndarray, T_fix_in: np.ndarray,
             T_fix_out: np.ndarray) -> np.ndarray:
    """
    Compute T_dut = inv(T_fix_in) · T_meas · inv(T_fix_out).

    Per-frequency 2x2 inversion via np.linalg.inv with a small ridge for
    near-singular fixture matrices (which shouldn't happen for any real
    physical fixture but does happen if you accidentally include the
    DUT in your fixture cal).
    """
    try:
        inv_in = np.linalg.inv(T_fix_in)
    except np.linalg.LinAlgError:
        eps = 1e-10
        inv_in = np.linalg.inv(T_fix_in + eps * np.eye(2)[None, :, :])
    try:
        inv_out = np.linalg.inv(T_fix_out)
    except np.linalg.LinAlgError:
        eps = 1e-10
        inv_out = np.linalg.inv(T_fix_out + eps * np.eye(2)[None, :, :])
    return inv_in @ T_meas @ inv_out


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, S_meas, S_dut, label, output_path):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fig, axes = plt.subplots(4, 2, figsize=(12, 14), sharex=True)
    panels = [
        ("S11", 0, 0, "#1f77b4"),
        ("S21", 1, 0, "#2ca02c"),
        ("S12", 0, 1, "#ff7f0e"),
        ("S22", 1, 1, "#d62728"),
    ]
    for i, (name, r, c, color) in enumerate(panels):
        meas = S_meas[:, r, c]
        dut  = S_dut[:, r, c]
        meas_db = 20 * np.log10(np.clip(np.abs(meas), 1e-12, None))
        dut_db  = 20 * np.log10(np.clip(np.abs(dut),  1e-12, None))
        meas_ph = np.degrees(np.unwrap(np.angle(meas)))
        dut_ph  = np.degrees(np.unwrap(np.angle(dut)))

        axes[i, 0].plot(freqs_mhz, meas_db, color="#888888", linewidth=1.0,
                        linestyle="--", label=f"|{name}| measured")
        axes[i, 0].plot(freqs_mhz, dut_db, color=color, linewidth=1.4,
                        label=f"|{name}| DUT (de-embedded)")
        axes[i, 0].set_ylabel(f"|{name}| (dB)")
        axes[i, 0].grid(True, which="both", alpha=0.35)
        axes[i, 0].legend(loc="upper right", fontsize=7, framealpha=0.92)

        axes[i, 1].plot(freqs_mhz, meas_ph, color="#888888", linewidth=1.0,
                        linestyle="--", label="measured")
        axes[i, 1].plot(freqs_mhz, dut_ph, color=color, linewidth=1.4,
                        label="DUT")
        axes[i, 1].set_ylabel(f"∠{name} (°)")
        axes[i, 1].grid(True, which="both", alpha=0.35)
        axes[i, 1].legend(loc="upper right", fontsize=7, framealpha=0.92)

    axes[3, 0].set_xlabel("Frequency (MHz)")
    axes[3, 1].set_xlabel("Frequency (MHz)")
    fig.suptitle(
        f"De-embedded S-parameters — {label}\n"
        f"{freqs_mhz[0]:.4f} – {freqs_mhz[-1]:.4f} MHz  •  "
        f"{len(freqs_hz)} points  •  {ts}\n"
        "Dashed grey = measured (fixture + DUT)  /  "
        "solid colour = DUT alone (de-embedded)",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="De-embed a fixture from a 2-port S-param measurement.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--measurement", required=True, metavar="MEAS.s2p",
                   help="Touchstone .s2p of the fixture + DUT cascade.")
    p.add_argument("--fixture", required=True, metavar="FIX.s2p",
                   help="Touchstone .s2p of the input-side fixture (or the "
                        "ONLY fixture file if --topology symmetric).")
    p.add_argument("--fixture-out", default=None, metavar="OUT.s2p",
                   help="Output-side fixture .s2p (required when "
                        "--topology asymmetric).")
    p.add_argument("--topology", choices=("symmetric", "asymmetric"),
                   default="symmetric",
                   help="Fixture model. symmetric: --fixture used for both "
                        "sides; output side is its port-reversed mirror. "
                        "asymmetric: --fixture-out also required.")
    p.add_argument("--label", default="DUT after de-embed",
                   help='Title text for the chart')
    p.add_argument("--output", required=True, metavar="DUT.pdf",
                   help="Output PDF path")
    p.add_argument("--touchstone", default=None, metavar="DUT.s2p",
                   help="Output Touchstone path for the DUT-alone S-params. "
                        "Defaults to --output with .s2p extension.")
    args = p.parse_args()

    if args.topology == "asymmetric" and not args.fixture_out:
        print("Error: --topology asymmetric requires --fixture-out",
              file=sys.stderr)
        return 1

    if args.touchstone is None:
        args.touchstone = (args.output[:-4] + ".s2p"
                           if args.output.lower().endswith(".pdf")
                           else args.output + ".s2p")

    print("De-embed PDF")
    print(f"  Measurement  : {args.measurement}")
    print(f"  Fixture (in) : {args.fixture}")
    if args.topology == "asymmetric":
        print(f"  Fixture (out): {args.fixture_out}")
    else:
        print(f"  Topology     : symmetric (output fixture = mirror of input)")
    print(f"  PDF          : {args.output}")
    print(f"  Touchstone   : {args.touchstone}")

    try:
        freqs_m, S_meas, z0_m, _ = read_s2p(args.measurement)
        freqs_f, S_fix_in, z0_f, _ = read_s2p(args.fixture)

        if not np.allclose(freqs_m, freqs_f, rtol=1e-6):
            print("Error: frequency arrays of measurement and fixture must "
                  "match exactly (same sweep params).", file=sys.stderr)
            return 1
        if abs(z0_m - z0_f) > 1e-6:
            print(f"  WARNING: Z0 mismatch (meas={z0_m}, fix={z0_f}); "
                  "treating both as 50 Ω.")

        if args.topology == "asymmetric":
            freqs_o, S_fix_out, _, _ = read_s2p(args.fixture_out)
            if not np.allclose(freqs_m, freqs_o, rtol=1e-6):
                print("Error: frequency arrays of measurement and "
                      "--fixture-out must match exactly.", file=sys.stderr)
                return 1
        else:
            S_fix_out = mirror_two_port(S_fix_in)

        T_meas    = s_to_t(S_meas)
        T_fix_in  = s_to_t(S_fix_in)
        T_fix_out = s_to_t(S_fix_out)
        T_dut     = de_embed(T_meas, T_fix_in, T_fix_out)
        S_dut     = t_to_s(T_dut)

        for name, r, c in (("S11", 0, 0), ("S21", 1, 0),
                           ("S12", 0, 1), ("S22", 1, 1)):
            i = int(np.argmin(np.abs(S_dut[:, r, c])))
            j = int(np.argmax(np.abs(S_dut[:, r, c])))
            print(f"  DUT {name}     : "
                  f"min {20*np.log10(max(abs(S_dut[i,r,c]),1e-12)):+.2f} dB "
                  f"@ {freqs_m[i]/1e6:.3f} MHz, "
                  f"max {20*np.log10(max(abs(S_dut[j,r,c]),1e-12)):+.2f} dB "
                  f"@ {freqs_m[j]/1e6:.3f} MHz")

        write_s2p(args.touchstone, freqs_m, S_dut, z0_m, comment_lines=[
            f"De-embedded DUT S-parameters",
            f"Source measurement: {args.measurement}",
            f"Fixture (in): {args.fixture}",
            f"Topology: {args.topology}"
            + (f"  fixture (out): {args.fixture_out}"
               if args.topology == "asymmetric" else ""),
        ])
        print(f"  Wrote .s2p   → {args.touchstone}")

        plot_pdf(freqs_m, S_meas, S_dut, args.label, args.output)
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
