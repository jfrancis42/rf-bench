#!/usr/bin/env python3
"""
choke_pdf.py — Common-mode choke |Z| PDF, NanoVNA or HP 8712B.

Common-mode-current chokes (the toroidal "ugly baluns" and ferrite-
sleeve types that hang off feedlines) are characterised by their
common-mode impedance |Zcm| across frequency. The accepted lab method
is the "series-through" fixture: put the choke as a SERIES element in
a 50-Ω THRU path, measure S21, and derive |Zdut| from the resulting
loss:

    Zdut(f) = 2 * Z0 * (1 - S21) / S21

Setup
-----
    VNA Port 1 ── series-through fixture (choke in line) ── VNA Port 2

    A "series-through" fixture is just two SMA jacks with the centre
    conductors broken into the DUT — the choke sits in series with the
    50 Ω signal path. The K6JCA / DX Engineering / Steve Hunt G3TXQ
    methodology is the same.

Plot
----
Single-page PDF, two panels:

  - |Z|  vs frequency (semilog Y, ohms)
  - R, X vs frequency (linear ohms; positive X = inductive)

Targets
-------
Hams commonly quote two thresholds:

  - **2000 Ω is "useful"** above ~3 MHz on HF
  - **5000 Ω is "excellent"** in the high-Q region

A horizontal target line can be drawn with `--target OHMS`.
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
Z0               = 50.0


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


def measure_s21(vna, start_hz, stop_hz, points, averaging):
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_parameter("S21")
    ok = vna.single_sweep()
    if not ok:
        print("  WARNING: single_sweep() returned False — trace may be stale")
    freqs = vna.get_frequencies()
    s21 = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    if len(freqs) != len(s21):
        raise RuntimeError(
            f"VNA returned mismatched array lengths "
            f"(freqs={len(freqs)}, s21={len(s21)})"
        )
    return freqs, s21


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_pdf(freqs_hz, z_complex, label, target_ohms, driver_name, idn,
             output_path):
    freqs_mhz = freqs_hz / 1e6
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    mag = np.abs(z_complex)
    r   = z_complex.real
    x   = z_complex.imag

    i_pk = int(np.argmax(mag))

    fig, axes = plt.subplots(2, 1, figsize=(11, 9), sharex=True)

    # ── Panel 1: |Z| (semilog Y) ─────────────────────────────────────────
    ax0 = axes[0]
    ax0.semilogy(freqs_mhz, mag, color="#1f77b4", linewidth=1.5, label="|Z|")
    if target_ohms is not None:
        ax0.axhline(target_ohms, color="#ff7f0e", linestyle="--", linewidth=1.0,
                    label=f"Target {target_ohms:g} Ω")
    # Common reference lines
    for ref, color in ((1000.0, "#bbbbbb"), (2000.0, "#888888"),
                       (5000.0, "#888888")):
        ax0.axhline(ref, color=color, linestyle=":", linewidth=0.8, alpha=0.6)

    # Peak annotation
    ax0.plot(freqs_mhz[i_pk], mag[i_pk], "o", color="purple", markersize=6,
             zorder=5)
    ax0.annotate(
        f"|Z| peak {mag[i_pk]:.0f} Ω @ {freqs_mhz[i_pk]:.3f} MHz",
        xy=(freqs_mhz[i_pk], mag[i_pk]),
        xytext=(10, 10), textcoords="offset points",
        fontsize=9, color="purple",
        arrowprops=dict(arrowstyle="->", color="purple", lw=0.8),
    )

    ax0.set_ylabel("|Z| (Ω)")
    ax0.grid(True, which="both", alpha=0.35)
    ax0.legend(loc="lower right", fontsize=8, framealpha=0.92)
    title_lines = [
        f"Common-mode Choke |Z| — {label}",
        f"{freqs_mhz[0]:.3f} – {freqs_mhz[-1]:.3f} MHz  •  {len(freqs_hz)} points  "
        f"•  {driver_name}  •  {ts}",
    ]
    if idn:
        title_lines.append(idn[:120])
    ax0.set_title("\n".join(title_lines), fontsize=10)

    # ── Panel 2: R, X ────────────────────────────────────────────────────
    ax1 = axes[1]
    ax1.plot(freqs_mhz, r, color="#d62728", linewidth=1.3, label="R (resistive)")
    ax1.plot(freqs_mhz, x, color="#2ca02c", linewidth=1.3,
             label="X (reactive: +ind / -cap)")
    ax1.axhline(0, color="#888888", linewidth=0.7)
    ax1.set_xlabel("Frequency (MHz)")
    ax1.set_ylabel("R, X (Ω)")
    ax1.grid(True, which="both", alpha=0.35)
    ax1.legend(loc="upper right", fontsize=8, framealpha=0.92)

    # Auto Y range that frames most of the data without being squashed by
    # one wild spike. Cap at the |Z| peak magnitude (the resistive peak is
    # always ≤ |Z| peak).
    cap = max(1000.0, mag[i_pk] * 1.2)
    ax1.set_ylim(-cap, cap)

    fig.tight_layout()
    fig.savefig(output_path, format="pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Common-mode choke |Z| PDF from series-through S21.",
    )
    p.add_argument("--vna",   choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port",  default=DEFAULT_PORT)
    p.add_argument("--host",  default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N")
    p.add_argument("--average", type=int, default=4, metavar="N",
                   help="Software-average N sweeps (default 4: |Z| benefits from averaging)")
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--target", type=float, default=None, metavar="OHMS",
                   help="Horizontal target line on |Z| panel (e.g. 2000)")
    p.add_argument("--label", default="choke")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= 0 or args.stop <= args.start:
        print("Error: --start and --stop must be positive with stop > start (MHz)")
        return 1
    if args.points < 2 or args.average < 1:
        print("Error: --points must be ≥ 2 and --average must be ≥ 1")
        return 1

    print(f"Choke PDF — {args.label}")
    print(f"  Driver       : {args.vna}")
    print(f"  Sweep        : {args.start:.3f} – {args.stop:.3f} MHz, "
          f"{args.points} points, average={args.average}")
    print(f"  Output       : {args.output}")

    vna = None
    try:
        vna, idn = open_vna(args)
        print(f"  IDN          : {idn[:120]}")
        maybe_set_power(vna, args.power, args.vna)

        freqs_hz, s21 = measure_s21(
            vna, args.start * 1e6, args.stop * 1e6, args.points, args.average,
        )
        # Series-through impedance derivation
        s21_safe = np.where(np.abs(s21) < 1e-9, 1e-9 + 0j, s21)
        z = 2.0 * Z0 * (1.0 - s21_safe) / s21_safe

        mag = np.abs(z)
        i_pk = int(np.argmax(mag))
        print(f"  |Z| peak     : {mag[i_pk]:.0f} Ω @ {freqs_hz[i_pk]/1e6:.3f} MHz")
        print(f"     R, X      : {z[i_pk].real:.0f} Ω, "
              f"{z[i_pk].imag:+.0f} Ω")
        # Useful summary thresholds
        for thresh in (2000.0, 5000.0):
            above = mag >= thresh
            if np.any(above):
                f_lo = freqs_hz[np.argmax(above)] / 1e6
                # last True (walk from end)
                f_hi = freqs_hz[len(above) - 1 - np.argmax(above[::-1])] / 1e6
                print(f"  ≥{thresh:>5.0f} Ω    : "
                      f"{f_lo:.3f} – {f_hi:.3f} MHz")
            else:
                print(f"  ≥{thresh:>5.0f} Ω    : never reached")

        plot_pdf(
            freqs_hz, z,
            label=args.label,
            target_ohms=args.target,
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
