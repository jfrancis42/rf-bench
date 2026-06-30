#!/usr/bin/env python3
"""
bandpass_tdr_pdf.py — Bandpass-mode TDR for sweeps that don't include DC.

The low-pass TDR (tdr-pdf) folds the swept spectrum to negative
frequencies as a Hermitian-conjugate mirror so DC sits at index 0.
That works when the sweep is REASONABLY close to DC — fine on a
NanoVNA-F starting at 50 kHz, OK on a HP 8712B at 300 kHz, NOT FINE
on a UHF-only sweep like 400–600 MHz where the missing DC region is
larger than the actual measurement.

The bandpass-mode TDR (this script) handles that case. The math
treats the swept S11 as the analytic signal of a complex sinusoid
modulated at the centre of the sweep — IFFT'ing gives the envelope
of the reflected signal in the time domain, free of the DC-extrapolation
artefact that plagues a low-pass TDR run on a high-frequency-only
sweep.

When to prefer this over the low-pass TDR in `../tdr-pdf/`:

  - You have a UHF/SHF-only sweep (band-restricted DUT or VNA)
  - You can't sweep down to DC because the cable/filter has a HPF
    response that kills S11 below some frequency
  - You're tracking a single reflection's *envelope* timing, not
    its true reflection coefficient

A low-pass TDR remains the right tool when the sweep extends close
to DC (start < 1 % of stop, typically).
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
C0               = 299_792_458.0


def open_vna(args):
    if args.vna == "nanovna":
        from rf_bench.nanovna import NanoVNA
        return NanoVNA(port=args.port)
    from rf_bench.hp import HP8712B
    return HP8712B(host=args.host)


def maybe_set_power(vna, dbm, kind):
    if dbm is None: return
    try: vna.set_power(float(dbm))
    except NotImplementedError:
        print(f"  --power ignored ({kind} has no dBm setpoint)")


def measure_s11(vna, start_hz, stop_hz, points, averaging):
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_parameter("S11")
    vna.single_sweep()
    f = vna.get_frequencies()
    g = vna.average_s_data(averaging) if averaging > 1 else vna.get_s_data()
    return f, g


def window(name, n):
    name = name.lower()
    if name in ("rect", "none"): return np.ones(n)
    if name == "hann":     return np.hanning(n)
    if name == "hamming":  return np.hamming(n)
    if name == "blackman": return np.blackman(n)
    if name == "kaiser":   return np.kaiser(n, 8.0)
    raise ValueError(f"unknown window {name!r}")


def compute_bandpass_tdr(freqs_hz, gamma, vf, window_name, interp_factor=8):
    """
    Bandpass-mode TDR. The swept gamma is treated as the complex
    envelope of an analytic signal centred at the sweep midpoint.
    Zero-pad the spectrum on both sides (low-frequency and high-
    frequency) before IFFT to get a clean time-domain envelope.

    Returns (distance_m, envelope_abs).
    """
    n = len(freqs_hz)
    if n < 4:
        raise ValueError("Bandpass TDR needs at least 4 sweep points")
    df = float(freqs_hz[1] - freqs_hz[0])
    if df <= 0:
        raise ValueError("Frequency spacing non-positive")

    w = window(window_name, n)
    s = gamma * w

    # Zero-pad both ends of the spectrum to push the effective FFT
    # length up by interp_factor.
    full_len = max(n, 1) * max(1, int(interp_factor))
    spectrum = np.zeros(full_len, dtype=np.complex128)
    # Place the swept band centered around 0 in the FFT input (which
    # in bandpass-mode TDR corresponds to centering on the analytic-
    # signal carrier).
    start_idx = (full_len - n) // 2
    spectrum[start_idx: start_idx + n] = s

    # IFFT → complex envelope of the impulse response. Take magnitude.
    h_complex = np.fft.ifft(np.fft.ifftshift(spectrum))
    envelope = np.abs(h_complex)

    # Time/distance axis. The "envelope time" is the relative delay
    # between reflections, not absolute distance from the port.
    dt = 1.0 / (df * full_len)
    t = np.arange(full_len) * dt
    distance_m = vf * C0 * t / 2.0  # round trip → one way
    return distance_m, envelope


def plot_pdf(distance_m, env, vf, units, label, driver, output, freqs_hz):
    if units == "ft":
        x = distance_m * 3.28084
        unit = "ft"
    else:
        x = distance_m
        unit = "m"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.plot(x, env, color="#d62728", linewidth=1.1, label="envelope")
    ax.set_xlabel(f"Distance one-way ({unit})")
    ax.set_ylabel("|envelope|")
    ax.grid(True, which="both", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8)
    sweep_lo_mhz = freqs_hz[0] / 1e6
    sweep_hi_mhz = freqs_hz[-1] / 1e6
    fig.suptitle(
        f"Bandpass-mode TDR — {label}\n"
        f"Sweep {sweep_lo_mhz:.3f} – {sweep_hi_mhz:.3f} MHz  •  "
        f"vf={vf:.3f}  •  {driver}  •  {ts}",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(output, format="pdf")
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bandpass-mode TDR PDF for sweeps that don't include DC.")
    p.add_argument("--vna", choices=("nanovna", "hp"), default=DEFAULT_VNA)
    p.add_argument("--port", default=DEFAULT_PORT)
    p.add_argument("--host", default=DEFAULT_HP_HOST)
    p.add_argument("--start", type=float, required=True, metavar="MHZ")
    p.add_argument("--stop",  type=float, required=True, metavar="MHZ")
    p.add_argument("--points", type=int, default=DEFAULT_POINTS)
    p.add_argument("--average", type=int, default=2)
    p.add_argument("--power", type=float, default=None, metavar="DBM")
    p.add_argument("--vf", type=float, default=0.66)
    p.add_argument("--feet", action="store_true",
                   help="Plot distance in feet (default metres)")
    p.add_argument("--window", default="hann",
                   choices=("rect","hann","hamming","blackman","kaiser"))
    p.add_argument("--interp", type=int, default=8)
    p.add_argument("--label", default="bandlimited DUT")
    p.add_argument("--output", required=True, metavar="FILE.pdf")
    args = p.parse_args()

    if args.start <= 0 or args.stop <= args.start or args.points < 4:
        print("Error: bad sweep args", file=sys.stderr); return 1

    vna = open_vna(args)
    try:
        print(f"Bandpass TDR — {args.label}")
        print(f"  Driver       : {args.vna}")
        print(f"  Sweep        : {args.start:.4f} – {args.stop:.4f} MHz, "
              f"{args.points} pts, average={args.average}")
        maybe_set_power(vna, args.power, args.vna)
        freqs_hz, g = measure_s11(vna, args.start*1e6, args.stop*1e6,
                                  args.points, args.average)
        d, env = compute_bandpass_tdr(freqs_hz, g, args.vf,
                                      args.window, args.interp)
        i = int(np.argmax(env))
        units = "ft" if args.feet else "m"
        peak_disp = d[i]*3.28084 if args.feet else d[i]
        print(f"  Peak @       : {peak_disp:.3f} {units}")
        plot_pdf(d, env, args.vf, units, args.label, args.vna.upper(),
                 args.output, freqs_hz)
        print(f"  Wrote PDF    → {args.output}")
        return 0
    finally:
        try: vna.close()
        except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
