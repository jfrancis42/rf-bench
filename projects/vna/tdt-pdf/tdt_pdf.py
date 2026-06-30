#!/usr/bin/env python3
"""
tdt_pdf.py — Time-Domain Transmission, S21 → time, NanoVNA or HP 8712B.

TDR (tdr-pdf) uses S11 to find reflections — distances to faults on
a feedline. TDT does the same math on S21 to find lumped reflections
*inside* a 2-port DUT. Useful for:

  - Bonding-wire mismatches inside an amplifier (peak at "0" delay,
    inside the package)
  - Internal element parasitics in a filter (peaks at non-zero delay
    matched to element spacing)
  - PCB-trace discontinuities inside a multi-board chain
  - "Is the signal coming out where I think it is?" sanity check

The math is identical to TDR (IFFT of the windowed swept spectrum to
get the impulse response, optional cumulative integral for a step
response), only the input parameter changes.

The HP 8712B has this natively as `:CALC:TRAN:STATE ON`; NanoVNA does
it host-side. Either way, this script produces a single-page PDF.
"""

from __future__ import annotations

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
C0_M_PER_S       = 299_792_458.0


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port)
    from rf_bench.hp import HP8712B
    return HP8712B(host=args.host)


def maybe_set_power(vna, dbm, kind):
    if dbm is None:
        return
    try:
        vna.set_power(float(dbm))
    except NotImplementedError:
        print(f"  --power ignored ({kind} has no dBm setpoint)")


def measure_s21(vna, start_hz, stop_hz, points, averaging):
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_parameter("S21")
    vna.single_sweep()
    freqs = vna.get_frequencies()
    s21 = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    return freqs, s21


def window(name: str, n: int) -> np.ndarray:
    name = name.lower()
    if name in ("rect", "none"): return np.ones(n)
    if name == "hann":     return np.hanning(n)
    if name == "hamming":  return np.hamming(n)
    if name == "blackman": return np.blackman(n)
    if name == "kaiser":   return np.kaiser(n, 8.0)
    raise ValueError(f"unknown window {name!r}")


def compute_tdt(freqs_hz, s21, vf, window_name, interp_factor=8):
    """
    Low-pass TDT: windowed S21 → Hermitian-symmetric spectrum → IFFT →
    impulse response. Returns (time_s, impulse_abs, step).

    Time axis here is ONE-WAY through the DUT — the same physical
    delay you'd see on a sampling-scope TDT.
    """
    n = len(freqs_hz)
    if n < 4:
        raise ValueError("TDT needs at least 4 sweep points")
    df = float(freqs_hz[1] - freqs_hz[0])
    if df <= 0:
        raise ValueError("Frequency spacing non-positive")
    w = window(window_name, n)
    s = s21 * w
    half_len = max(n, 1) * max(1, int(interp_factor))
    full_len = 2 * half_len
    spectrum = np.zeros(full_len, dtype=np.complex128)
    spectrum[0] = s[0]
    spectrum[1:n] = s[1:]
    spectrum[full_len - n + 1: full_len] = np.conj(s[1:][::-1])
    h = np.fft.ifft(spectrum).real
    dt = 1.0 / (df * full_len)
    h_pos = h[:half_len]
    t = np.arange(half_len) * dt
    step = np.cumsum(h_pos)
    return t, np.abs(h_pos), step


def plot_pdf(t, impulse_abs, step, vf, units, label, driver, output):
    if units == "ft":
        x = t * vf * C0_M_PER_S * 3.28084     # 1-way distance in ft
        unit = "ft"
    elif units == "m":
        x = t * vf * C0_M_PER_S               # 1-way distance in m
        unit = "m"
    else:  # ns
        x = t * 1e9
        unit = "ns"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig, (ax_s, ax_i) = plt.subplots(2, 1, figsize=(11, 9), sharex=True)
    ax_s.plot(x, step, color="#1f77b4", linewidth=1.4, label="Step (cumulative)")
    ax_s.set_ylabel("S21 step response")
    ax_s.grid(True, which="both", alpha=0.35)
    ax_s.legend(loc="upper right", fontsize=8)
    ax_s.set_title(f"TDT — {label}    •  {driver}  •  {ts}", fontsize=10)

    ax_i.plot(x, impulse_abs, color="#d62728", linewidth=1.1, label="|impulse|")
    ax_i.set_xlabel(f"Through delay  ({unit})")
    ax_i.set_ylabel("|h(t)|")
    ax_i.grid(True, which="both", alpha=0.35)
    ax_i.legend(loc="upper right", fontsize=8)

    # Find the largest peak in the impulse
    i = int(np.argmax(impulse_abs))
    ax_i.plot(x[i], impulse_abs[i], "ro", markersize=6)
    ax_i.annotate(f"peak @ {x[i]:.3f} {unit}", (x[i], impulse_abs[i]),
                  xytext=(10, 10), textcoords="offset points", color="red")

    fig.tight_layout()
    fig.savefig(output, format="pdf")
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description="S21 → Time-Domain Transmission PDF (inside-the-DUT delay).")
    p.add_argument("--vna", choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port", default=DEFAULT_PORT)
    p.add_argument("--host", default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS)
    p.add_argument("--average", type=int, default=2)
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--vf", type=float, default=0.66,
                   help="Velocity factor for distance axis (default 0.66 = "
                        "solid PE coax). Only used when --units is m or ft.")
    p.add_argument("--units", choices=("ns", "m", "ft"), default="ns",
                   help="X axis units: ns (raw delay), m, or ft.")
    p.add_argument("--window", default="hann",
                   choices=("rect", "hann", "hamming", "blackman", "kaiser"))
    p.add_argument("--interp", type=int, default=8)
    p.add_argument("--label", default="DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= args.start or args.points < 4:
        print("Error: bad sweep args", file=sys.stderr); return 1

    vna = open_vna(args)
    try:
        print(f"TDT — {args.label}")
        print(f"  Driver       : {args.vna}")
        print(f"  Sweep        : {args.start:.4f} – {args.stop:.4f} MHz, "
              f"{args.points} pts, average={args.average}")
        maybe_set_power(vna, args.power, args.vna)
        freqs_hz, s21 = measure_s21(vna, args.start*1e6, args.stop*1e6,
                                    args.points, args.average)
        t, imp_abs, step = compute_tdt(freqs_hz, s21, args.vf,
                                       args.window, args.interp)
        i = int(np.argmax(imp_abs))
        if args.units == "ns":
            print(f"  Peak delay   : {t[i]*1e9:.3f} ns")
        elif args.units == "m":
            d = t[i] * args.vf * C0_M_PER_S
            print(f"  Peak delay   : {t[i]*1e9:.3f} ns "
                  f"(= {d:.4f} m of vf={args.vf})")
        else:
            d_ft = t[i] * args.vf * C0_M_PER_S * 3.28084
            print(f"  Peak delay   : {t[i]*1e9:.3f} ns "
                  f"(= {d_ft:.4f} ft of vf={args.vf})")
        plot_pdf(t, imp_abs, step, args.vf, args.units,
                 args.label, args.vna.upper(), args.output)
        print(f"  Wrote PDF    → {args.output}")
        return 0
    finally:
        try: vna.close()
        except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
