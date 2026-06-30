#!/usr/bin/env python3
"""
mixed_mode_pdf.py — Convert single-ended 4-port S-params to mixed-mode.

Pure post-processor. Takes a Touchstone .s4p file of a 4-port DUT (typical
example: a differential pair, a transformer, an LVDS link, a balun's
4 single-ended ports) and computes the mixed-mode S-parameter matrix:

    S_mm = [ S_dd  S_dc ]
           [ S_cd  S_cc ]

where each S_xx block is 2×2 in mode space (port-1 mode → port-2 mode).

  S_dd  : differential-to-differential — the "signal" path for a diff pair
  S_cc  : common-to-common              — common-mode propagation
  S_dc  : common-to-differential        — UNWANTED mode conversion
  S_cd  : differential-to-common        — UNWANTED mode conversion

For a well-balanced differential line (e.g. clean CAT5 / LVDS / USB
twisted pair), |S_dd21| should be near 0 dB, |S_cc21| should be high
(common-mode rejected as a passband would be), and S_dc / S_cd should
be near zero (no mode conversion). When mode conversion is *not* zero,
the geometric asymmetry between the two halves of the pair becomes a
radiation source (EMC problem) or a noise pickup point.

Port convention
---------------
The script defaults to the most common Touchstone convention for
differential pairs:

  Pair 1 (input):   ports 1 and 2
  Pair 2 (output):  ports 3 and 4

This is the order skim-readers see in S4P column listings. Many EDA
tools follow it; some use {1,3} / {2,4} instead. Pass --convention
to swap.

Math
----
Single-ended S in standard 4-port column order [1,2,3,4]:

    [ S11 S12 S13 S14 ]
    [ S21 S22 S23 S24 ]
    [ S31 S32 S33 S34 ]
    [ S41 S42 S43 S44 ]

Transform matrix M (for convention 1-2 / 3-4):

           1   [  1  -1   0   0 ]
    M  =  ───  [  0   0   1  -1 ]
          √2   [  1   1   0   0 ]
               [  0   0   1   1 ]

where rows are the new modes [d1, d2, c1, c2] and columns are the
old single-ended ports [1, 2, 3, 4].

    S_mm = M · S_se · M^T

The result rows / cols are [d1, d2, c1, c2]. We slice that into the
four 2×2 blocks Sdd, Sdc, Scd, Scc for plotting / reporting.

References
----------
  Bockelman & Eisenstadt, "Combined Differential and Common-Mode
  Scattering Parameters: Theory and Simulation", IEEE Trans MTT 1995.
"""

from __future__ import annotations

# Suppress mixed-install matplotlib Axes3D import warning (harmless;
# happens when system-package and pip-installed matplotlib are both present).
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")

import argparse
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


# ---------------------------------------------------------------------------
# Touchstone v1 .s4p reader / writer
# ---------------------------------------------------------------------------

def read_s4p(path: str):
    """
    Parse a Touchstone v1 .s4p. Returns (freqs_hz, S, z0).

    S is shape (N, 4, 4) complex128. Column ordering follows the
    Touchstone v1 convention for n > 2:

        Each frequency row contains 16 complex values arranged in
        16 (real, imag/mag, ang/db, ang) pairs across multiple lines.
        The row-major order is [S11 S12 S13 S14  S21 S22 S23 S24
                                S31 S32 S33 S34  S41 S42 S43 S44].

    Touchstone v1 for 3+ ports puts the data across multiple lines —
    16 complex values = 32 numeric fields per frequency, traditionally
    written as 4 lines of 8 numbers each. We just concatenate all
    numeric tokens between header / option lines until we have
    4 + 32 = 33 of them (freq + 16 complex), then parse.
    """
    freq_mult = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}
    freq_unit = "ghz"
    fmt = "ma"
    z0 = 50.0
    numeric: list[float] = []

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
            for tok in line.split():
                try:
                    numeric.append(float(tok))
                except ValueError:
                    pass

    # Each frequency row consumes 1 + 32 = 33 tokens
    if len(numeric) % 33 != 0:
        raise ValueError(
            f"{path}: parsed {len(numeric)} numeric tokens, "
            f"not divisible by 33 (= 1 freq + 16 complex per row).")
    n = len(numeric) // 33
    freqs = np.empty(n, dtype=np.float64)
    S = np.empty((n, 4, 4), dtype=np.complex128)

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
        raise ValueError(f"Unsupported Touchstone format: {fmt}")

    for k in range(n):
        base = k * 33
        freqs[k] = numeric[base] * freq_mult[freq_unit]
        # Row-major S[i,j] order in Touchstone v1
        idx = base + 1
        for i in range(4):
            for j in range(4):
                S[k, i, j] = _to_complex(numeric[idx], numeric[idx + 1])
                idx += 2
    return freqs, S, z0


def write_s4p(path: str, freqs_hz: np.ndarray, S: np.ndarray, z0: float,
              comment_lines: list[str] | None = None) -> None:
    """Write a Touchstone v1 .s4p in MA format."""
    with open(path, "w") as fh:
        fh.write("! Touchstone .s4p, generated by mixed_mode_pdf.py\n")
        fh.write(f"! Date: {datetime.now().isoformat(timespec='seconds')}\n")
        if comment_lines:
            for line in comment_lines:
                fh.write(f"! {line}\n")
        fh.write(f"# Hz S MA R {z0:g}\n")
        for k in range(len(freqs_hz)):
            fh.write(f"{freqs_hz[k]:.6e}")
            for i in range(4):
                fh.write(" ")
                for j in range(4):
                    fh.write(f" {abs(S[k,i,j]):.6e} "
                             f"{np.degrees(np.angle(S[k,i,j])):.4f}")
                if i < 3:
                    fh.write("\n           ")
            fh.write("\n")


# ---------------------------------------------------------------------------
# Mixed-mode transform
# ---------------------------------------------------------------------------

def build_transform(convention: str) -> np.ndarray:
    """
    Return the 4×4 mode transform M acting on column-ordered
    single-ended ports [1,2,3,4]. Rows of M are [d1, d2, c1, c2].

      convention "1-2/3-4" (default): pair 1 = ports 1,2; pair 2 = 3,4
          d1 = (V1 - V2)/√2
          d2 = (V3 - V4)/√2
          c1 = (V1 + V2)/√2
          c2 = (V3 + V4)/√2

      convention "1-3/2-4" (alternate): pair 1 = 1,3; pair 2 = 2,4
          d1 = (V1 - V3)/√2
          d2 = (V2 - V4)/√2
          c1 = (V1 + V3)/√2
          c2 = (V2 + V4)/√2
    """
    s = 1.0 / np.sqrt(2.0)
    if convention == "1-2/3-4":
        return s * np.array(
            [[1, -1, 0,  0],
             [0,  0, 1, -1],
             [1,  1, 0,  0],
             [0,  0, 1,  1]], dtype=np.float64)
    if convention == "1-3/2-4":
        return s * np.array(
            [[1, 0, -1,  0],
             [0, 1,  0, -1],
             [1, 0,  1,  0],
             [0, 1,  0,  1]], dtype=np.float64)
    raise ValueError(f"Unknown convention {convention!r}")


def to_mixed_mode(S_se: np.ndarray, M: np.ndarray) -> np.ndarray:
    """Compute S_mm = M · S_se · M^T per frequency point."""
    n = S_se.shape[0]
    Mt = M.T
    out = np.empty_like(S_se)
    for k in range(n):
        out[k] = M @ S_se[k] @ Mt
    return out


def split_mm_blocks(S_mm: np.ndarray):
    """
    Extract the four 2×2 mode blocks from the 4×4 mixed-mode matrix
    arranged as rows / cols [d1, d2, c1, c2].

    Returns (Sdd, Sdc, Scd, Scc), each shape (N, 2, 2).
    """
    Sdd = S_mm[:, 0:2, 0:2]
    Sdc = S_mm[:, 0:2, 2:4]
    Scd = S_mm[:, 2:4, 0:2]
    Scc = S_mm[:, 2:4, 2:4]
    return Sdd, Sdc, Scd, Scc


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, Sdd, Sdc, Scd, Scc, label, convention, output_path):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 4 rows × 2 cols. Each row shows |·| (dB) on the left, ∠· (°) on the right.
    # Row order: Sdd21 (diff insertion), Scc21 (CM "insertion"),
    #            Sdc21 (CM→diff conversion), Scd21 (diff→CM conversion).
    rows = [
        ("S_dd21 (differential through)",  Sdd[:, 1, 0], "#1f77b4"),
        ("S_cc21 (common-mode through)",   Scc[:, 1, 0], "#2ca02c"),
        ("S_dc21 (CM → diff conversion)",  Sdc[:, 1, 0], "#d62728"),
        ("S_cd21 (diff → CM conversion)",  Scd[:, 1, 0], "#ff7f0e"),
    ]
    fig, axes = plt.subplots(4, 2, figsize=(12, 13), sharex=True)
    for i, (name, s, color) in enumerate(rows):
        mag_db = 20.0 * np.log10(np.clip(np.abs(s), 1e-12, None))
        phase  = np.degrees(np.unwrap(np.angle(s)))
        axes[i, 0].plot(freqs_mhz, mag_db, color=color, linewidth=1.4)
        axes[i, 0].set_ylabel(f"|{name.split(' ')[0]}| (dB)")
        axes[i, 0].grid(True, which="both", alpha=0.35)
        axes[i, 0].set_title(name, fontsize=9, loc="left")
        axes[i, 1].plot(freqs_mhz, phase, color=color, linewidth=1.4)
        axes[i, 1].set_ylabel(f"∠{name.split(' ')[0]} (°)")
        axes[i, 1].grid(True, which="both", alpha=0.35)

    axes[3, 0].set_xlabel("Frequency (MHz)")
    axes[3, 1].set_xlabel("Frequency (MHz)")

    fig.suptitle(
        f"Mixed-mode S-parameters — {label}\n"
        f"{freqs_mhz[0]:.4f} – {freqs_mhz[-1]:.4f} MHz  •  "
        f"{len(freqs_hz)} points  •  port convention: {convention}  •  {ts}",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Single-ended .s4p → mixed-mode S-parameter PDF + .s4p.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input", required=True, metavar="DUT.s4p",
                   help="Single-ended 4-port Touchstone .s4p")
    p.add_argument("--convention", choices=("1-2/3-4", "1-3/2-4"),
                   default="1-2/3-4",
                   help="Port-to-pair mapping (default 1-2/3-4 = pair-1 is "
                        "ports 1+2, pair-2 is ports 3+4).")
    p.add_argument("--label", default="differential DUT")
    p.add_argument("--output", required=True, metavar="OUT.pdf")
    p.add_argument("--touchstone", default=None, metavar="OUT.s4p",
                   help="Optional explicit output .s4p path (defaults to "
                        "--output with .s4p extension).")
    args = p.parse_args()

    if args.touchstone is None:
        args.touchstone = (args.output[:-4] + ".s4p"
                           if args.output.lower().endswith(".pdf")
                           else args.output + ".s4p")

    print(f"Mixed-mode PDF — {args.label}")
    print(f"  Input        : {args.input}")
    print(f"  Convention   : {args.convention}")
    print(f"  PDF          : {args.output}")
    print(f"  Touchstone   : {args.touchstone}")

    try:
        freqs_hz, S_se, z0 = read_s4p(args.input)
        M = build_transform(args.convention)
        S_mm = to_mixed_mode(S_se, M)
        Sdd, Sdc, Scd, Scc = split_mm_blocks(S_mm)

        # Summary
        for name, s in (("Sdd21", Sdd[:, 1, 0]), ("Scc21", Scc[:, 1, 0]),
                        ("Sdc21", Sdc[:, 1, 0]), ("Scd21", Scd[:, 1, 0])):
            mag = np.abs(s)
            mag_db = 20.0 * np.log10(np.clip(mag, 1e-12, None))
            i_pk = int(np.argmax(mag))
            i_dp = int(np.argmin(mag))
            print(f"  {name}        : "
                  f"max {mag_db[i_pk]:+.2f} dB @ {freqs_hz[i_pk]/1e6:.4f} MHz, "
                  f"min {mag_db[i_dp]:+.2f} dB @ {freqs_hz[i_dp]/1e6:.4f} MHz")

        write_s4p(args.touchstone, freqs_hz, S_mm, z0, comment_lines=[
            f"Mixed-mode S-parameters",
            f"Source: {args.input}",
            f"Convention: {args.convention}",
            "Row / col order: [d1, d2, c1, c2]",
        ])
        print(f"  Wrote .s4p   → {args.touchstone}")

        plot_pdf(freqs_hz, Sdd, Sdc, Scd, Scc, args.label,
                 args.convention, args.output)
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
