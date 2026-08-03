#!/usr/bin/env python3
"""
df_offline.py — run the full DF pipeline on SIMULATED data (no radio).

Demonstrates the calibrate -> measure -> bearing flow end to end using
simulate.py, so you can see the whole system work before the antennas are up.
Prints recovered bearings for a sweep of true arrival angles.

    python3 df_offline.py                          # single baseline sweep
    python3 df_offline.py --dual                   # two-baseline azimuth sweep
    python3 df_offline.py --baseline 8 --freq 14074 --snr 20
"""
import argparse
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry as geo
import simulate as sim
from bearing import BearingEngine, DualBaselineEngine


def cross_phase_deg(a, b, nfft=8192):
    w = np.hanning(nfft)
    segs = min(len(a), len(b)) // nfft
    Sxy = np.zeros(nfft, dtype=complex); P = np.zeros(nfft)
    for k in range(segs):
        Fa = np.fft.fft(a[k * nfft:(k + 1) * nfft] * w)
        Fb = np.fft.fft(b[k * nfft:(k + 1) * nfft] * w)
        Sxy += Fa * np.conj(Fb); P += np.abs(Fa) ** 2 + np.abs(Fb) ** 2
    return math.degrees(np.angle(Sxy[int(np.argmax(P))]))


def main():
    ap = argparse.ArgumentParser(description="offline DF pipeline demo (simulated)")
    ap.add_argument("--freq", type=float, default=14074.0, help="kHz")
    ap.add_argument("--baseline", type=float, default=8.0, help="metres")
    ap.add_argument("--snr", type=float, default=30.0, help="dB")
    ap.add_argument("--phi0", type=float, default=-32.77,
                    help="simulated inter-channel offset (measured ~-33°)")
    ap.add_argument("--dual", action="store_true", help="two-baseline azimuth")
    args = ap.parse_args()
    f = int(args.freq * 1000)
    d = args.baseline
    D = geo.electrical_spacing(d, f)
    kw = dict(baseline_m=d, freq_hz=f, phi0_deg=args.phi0, snr_db=args.snr,
              tone_hz=3000.0, n=8192 * 8)

    print(f"Offline DF demo — {args.freq:.0f} kHz, baseline {d} m "
          f"(D={D:.2f}{', ALIASED >0.5' if D > 0.5 else ', unambiguous'}), "
          f"SNR {args.snr:.0f} dB, sim φ0={args.phi0:+.1f}°\n")

    if not args.dual:
        eng = BearingEngine(baseline_m=d, freq_hz=f)
        a, b = sim.simulate_pair(theta_deg=90.0, **kw)     # broadside reference
        eng.calibrate(cross_phase_deg(a, b))
        print(f"  calibrated: φ0 = {eng.cal.phi0_x_deg:+.2f}° (from broadside ref)\n")
        print(f"  {'true θ':>8}  {'meas Δφ':>9}  {'θ (cone)':>9}  {'±err':>6}")
        for true_theta in (40, 60, 75, 90, 105, 120, 140):
            a, b = sim.simulate_pair(theta_deg=float(true_theta), **kw)
            dphi = cross_phase_deg(a, b)
            r = eng.bearing(dphi, dphi_std_deg=0.2)
            if r.ok:
                print(f"  {true_theta:8.0f}  {dphi:+9.1f}  {r.theta_deg:9.1f}  "
                      f"{(r.theta_err_deg or 0):6.2f}")
            else:
                print(f"  {true_theta:8.0f}  {dphi:+9.1f}  --  {r.reason}")
        print("\n  (single baseline -> cone angle from the baseline axis; the "
              "left/right mirror is unresolved. Two baselines give full azimuth.)")
    else:
        eng = DualBaselineEngine(baseline_m=d, freq_hz=f)
        axc, bxc, _, _ = sim.simulate_pair_azimuth(az_deg=90.0, **kw)
        _, _, ayc, byc = sim.simulate_pair_azimuth(az_deg=0.0, **kw)
        eng.calibrate(cross_phase_deg(axc, bxc), cross_phase_deg(ayc, byc))
        print(f"  calibrated: φ0_x={eng.cal.phi0_x_deg:+.1f}° "
              f"φ0_y={eng.cal.phi0_y_deg:+.1f}°\n")
        print(f"  {'true az':>8}  {'azimuth':>9}  {'±err':>6}")
        for true_az in (0, 45, 90, 135, 180, 225, 270, 315):
            ax, bx, ay, by = sim.simulate_pair_azimuth(az_deg=float(true_az), **kw)
            r = eng.bearing(cross_phase_deg(ax, bx), cross_phase_deg(ay, by))
            err = min(abs(r.azimuth_deg - true_az), 360 - abs(r.azimuth_deg - true_az))
            print(f"  {true_az:8.0f}  {r.azimuth_deg:9.1f}  {err:6.2f}")


if __name__ == "__main__":
    main()
