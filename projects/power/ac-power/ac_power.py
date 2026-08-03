#!/usr/bin/env python3
"""
AC Power / Power-Factor Analyzer — Fluke 80i-400 clamp + voltage sense + scope

Measures TRUE power (W), apparent power (VA), and power factor of a mains load
by capturing the voltage and current waveforms simultaneously on two scope
channels and integrating the instantaneous product p(t) = v(t)·i(t).

    P_real   = mean( v(t) · i(t) )                 [W]
    V_rms, I_rms = rms(v), rms(i)
    S_apparent = V_rms · I_rms                      [VA]
    PF       = P_real / S_apparent                  (=cosφ for sinusoids)

This is the only clamp project that needs to sense the mains VOLTAGE, and that
makes it fundamentally more dangerous than the current-only projects.

  ┌─────────────────────────── SAFETY ───────────────────────────┐
  │ Sensing a live mains conductor on a bench scope is a shock and │
  │ ground-loop hazard. The scope's CH ground is tied to earth via │
  │ its mains plug; connecting a probe ground to a mains conductor │
  │ can short line-to-earth violently.                             │
  │                                                                │
  │ You MUST use ONE of:                                           │
  │   • a differential probe (e.g. 1400 V CAT III), OR             │
  │   • a mains isolation transformer on the DUT.                  │
  │                                                                │
  │ This script REFUSES to run without --i-have-isolation to make  │
  │ that choice explicit and deliberate.                           │
  └────────────────────────────────────────────────────────────────┘

Signal path:
  Voltage: mains → differential probe / isolation xfmr → scope CH_V, scaled by
           --volt-scale (V per scope-volt; a 1400 V diff probe at ×200 → 200).
  Current: conductor → 80i-400 clamp → burden resistor → scope CH_I (1 Ω=1 mV/A).
  Both channels captured in ONE acquisition (SDS2000X.capture_two_channels) so
  V and I are phase-aligned — essential for a correct power factor.

Usage (only after reading the safety block):
  python ac_power.py --i-have-isolation --volt-scale 200
  python ac_power.py --i-have-isolation --volt-scale 200 --burden 1 \
                     --ch-v 1 --ch-i 2 --mains 60 --plot power.png

Author: Jeff Francis (N0GQ) <gjfrancis@protonmail.com>
License: GPL-3.0-or-later
"""

import argparse
import sys

import numpy as np

from rf_bench.siglent import SDS2000X
from rf_bench.fluke import Fluke80i400


def compute_power(volts: np.ndarray, amps: np.ndarray):
    """Return dict of real/apparent/reactive power, PF, and RMS values.

    volts, amps must be simultaneous samples (same acquisition, same length).
    """
    n = min(len(volts), len(amps))
    volts, amps = volts[:n], amps[:n]

    v_rms = float(np.sqrt(np.mean(volts ** 2)))
    i_rms = float(np.sqrt(np.mean(amps ** 2)))
    p_real = float(np.mean(volts * amps))          # W (sign = direction)
    s_app = v_rms * i_rms                            # VA
    pf = (p_real / s_app) if s_app > 0 else 0.0
    # Reactive power magnitude (distortion-inclusive): Q = sqrt(S² − P²).
    q = float(np.sqrt(max(0.0, s_app ** 2 - p_real ** 2)))
    return {
        "v_rms": v_rms, "i_rms": i_rms,
        "p_real_w": p_real, "s_apparent_va": s_app,
        "q_reactive_var": q, "power_factor": pf,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="AC power / power-factor analyzer (REQUIRES voltage isolation)")
    p.add_argument("--i-have-isolation", action="store_true",
                   help="REQUIRED. Confirms you are sensing mains voltage via a "
                        "differential probe OR isolation transformer. Without "
                        "this the script refuses to run.")
    p.add_argument("--volt-scale", type=float, default=None,
                   help="Volts of mains per scope-volt on the voltage channel "
                        "(e.g. differential probe attenuation). REQUIRED.")
    p.add_argument("--scope", default=None, help="Scope IP (default: driver default)")
    p.add_argument("--ch-v", type=int, default=1, help="Voltage-sense channel (default 1)")
    p.add_argument("--ch-i", type=int, default=2, help="Current (clamp) channel (default 2)")
    p.add_argument("--burden", type=float, default=1.0,
                   help="Burden resistor ohms on current channel (default 1.0)")
    p.add_argument("--mains", type=float, default=60.0, help="Mains Hz (default 60)")
    p.add_argument("--cycles", type=float, default=6.0,
                   help="Mains cycles to capture (default 6)")
    p.add_argument("--plot", default=None, help="Save v/i/p waveform PNG")
    args = p.parse_args()

    if not args.i_have_isolation:
        print(__doc__.split("Usage")[0])   # print the safety block
        print("REFUSING TO RUN: pass --i-have-isolation once you are using a "
              "differential probe or isolation transformer for voltage sensing.")
        return 2
    if args.volt_scale is None:
        print("ERROR: --volt-scale is required (mains volts per scope-volt on "
              "the voltage channel).")
        return 2

    clamp = Fluke80i400()
    duration = args.cycles / args.mains
    print(f"Voltage ch C{args.ch_v} × {args.volt_scale} V/V, "
          f"current ch C{args.ch_i} via {args.burden} Ω burden "
          f"({clamp.burden_mv_per_amp(args.burden):.1f} mV/A)")
    print(f"Capturing {args.cycles:.0f} cycles ({duration*1e3:.0f} ms), "
          f"phase-locked...")

    scope = SDS2000X(args.scope) if args.scope else SDS2000X()
    try:
        cap = scope.capture_two_channels(ch_a=args.ch_v, ch_b=args.ch_i,
                                         duration_s=duration)
    finally:
        scope.close()

    volts = cap["a"] * args.volt_scale
    amps = clamp.amps_from_burden_waveform(cap["b"], args.burden)
    r = compute_power(volts, amps)

    print(f"\nSample rate:   {cap['sample_rate']/1e3:.1f} kS/s "
          f"({len(cap['a'])} samples/ch)")
    print(f"V rms:         {r['v_rms']:.1f} V")
    print(f"I rms:         {r['i_rms']:.2f} A")
    print(f"Real power:    {r['p_real_w']:.1f} W")
    print(f"Apparent:      {r['s_apparent_va']:.1f} VA")
    print(f"Reactive:      {r['q_reactive_var']:.1f} var")
    print(f"Power factor:  {r['power_factor']:.3f}")

    if args.plot:
        _save_plot(args.plot, cap["t"], volts, amps, r)
        print(f"\nSaved {args.plot}")
    return 0


def _save_plot(path, t, volts, amps, r):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tms = t * 1e3
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    ax1.plot(tms, volts, color="#1f77b4", lw=0.8, label="v(t)")
    ax1b = ax1.twinx()
    ax1b.plot(tms, amps, color="#c8102e", lw=0.8, label="i(t)")
    ax1.set_ylabel("Voltage (V)", color="#1f77b4")
    ax1b.set_ylabel("Current (A)", color="#c8102e")
    ax1.set_title(f"AC power — P={r['p_real_w']:.0f} W, "
                  f"S={r['s_apparent_va']:.0f} VA, PF={r['power_factor']:.3f}")
    ax1.grid(True, alpha=0.3)

    ax2.plot(tms, volts * amps, color="#2ca02c", lw=0.8)
    ax2.axhline(r["p_real_w"], color="#333", ls="--", lw=0.8,
                label=f"mean P={r['p_real_w']:.0f} W")
    ax2.set_ylabel("p(t)=v·i (W)")
    ax2.set_xlabel("Time (ms)")
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
