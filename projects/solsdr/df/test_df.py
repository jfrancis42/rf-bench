#!/usr/bin/env python3
"""
Test suite for the DF pipeline — runs with NO hardware.

Covers: geometry math + ambiguity flags, the calibration / refuse-until-
calibrated gate, and the end-to-end recovery of a KNOWN simulated bearing
through cross-phase -> calibration -> geometry. This is the regression fixture
that lets us build the whole system before the antennas are up: feed a known
bearing in via simulate.py, confirm it comes back out.

Run:  python3 test_df.py
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry as geo
import simulate as sim
from bearing import BearingEngine, DualBaselineEngine, Calibration, _wrap180

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILS.append(name)


def _cross_phase_deg(a, b, nfft=8192):
    """Peak-bin cross-phase, mirroring df.py / rx2_coherence (Fa·conj(Fb))."""
    w = np.hanning(nfft)
    segs = min(len(a), len(b)) // nfft
    Sxy = np.zeros(nfft, dtype=complex); P = np.zeros(nfft)
    for k in range(segs):
        Fa = np.fft.fft(a[k*nfft:(k+1)*nfft]*w)
        Fb = np.fft.fft(b[k*nfft:(k+1)*nfft]*w)
        Sxy += Fa*np.conj(Fb); P += np.abs(Fa)**2 + np.abs(Fb)**2
    pk = int(np.argmax(P))
    return math.degrees(np.angle(Sxy[pk]))


# ── geometry ────────────────────────────────────────────────────────────────
def test_geometry_roundtrip():
    print("geometry forward/inverse round-trip:")
    d, f = 10.0, 14_074_000
    D = geo.electrical_spacing(d, f)
    # 10 m at 20 m band: D≈0.47 (<0.5) so it is NOT aliased. A 15 m baseline would be.
    check("D at 10m/20m computed (D=%.2f, unaliased)" % D, 0.4 < D < 0.5)
    check("15m/20m baseline IS aliased (D>0.5)", geo.electrical_spacing(15.0, f) > 0.5)
    # use a small baseline that is unambiguous to test clean inversion
    d2 = 8.0
    for theta in (30, 60, 90, 120, 150):
        dphi = geo.phase_for_angle_deg(theta, d2, f)
        sol = geo.angle_for_phase_deg(dphi, d2, f)
        ok = sol["ok"] and abs(sol["theta_deg"] - theta) < 0.01
        check(f"θ={theta}° -> Δφ={dphi:+.1f}° -> θ={sol.get('theta_deg', float('nan')):.2f}°", ok)


def test_geometry_broadside_and_range():
    print("geometry broadside + out-of-range:")
    d, f = 5.0, 14_074_000
    check("broadside θ=90° gives Δφ≈0", abs(geo.phase_for_angle_deg(90, d, f)) < 1e-9)
    # a Δφ implying |cosθ|>1 must be rejected
    big = geo.max_unambiguous_phase_deg(d, f) * 2
    sol = geo.angle_for_phase_deg(big, d, f)
    check("impossible Δφ rejected (|cosθ|>1)", not sol["ok"], sol.get("reason", ""))


def test_error_propagation():
    print("θ error propagation (endfire worse than broadside):")
    d, f = 10.0, 14_074_000
    e_broad = geo.theta_error_deg(0.2, 90, d, f)
    e_end = geo.theta_error_deg(0.2, 20, d, f)
    check(f"broadside err {e_broad:.3f}° < endfire err {e_end:.3f}°", e_broad < e_end)
    check("0.2° phase gives sub-degree broadside err", e_broad < 1.0, f"{e_broad:.3f}°")


# ── calibration gate ──────────────────────────────────────────────────────────
def test_refuse_until_calibrated():
    print("refuse-until-calibrated gate:")
    eng = BearingEngine(baseline_m=8.0, freq_hz=14_074_000)
    r = eng.bearing(30.0)
    check("uncalibrated engine refuses", (not r.ok) and "CALIBRATED" in r.reason)
    eng.calibrate(dphi_meas_deg=-32.77, known_geo_phase_deg=0.0)  # ref tone, θ known
    check("calibrated offset stored", eng.cal.valid and abs(eng.cal.phi0_x_deg + 32.77) < 1e-6)
    r2 = eng.bearing(-32.77)   # measured == offset -> geo phase 0 -> broadside
    check("after cal, ref phase -> broadside θ≈90°", r2.ok and abs(r2.theta_deg - 90) < 0.5,
          f"θ={r2.theta_deg:.2f}" if r2.ok else r2.reason)


# ── end-to-end via simulator ──────────────────────────────────────────────────
def test_single_baseline_end_to_end():
    print("END-TO-END single baseline (simulate known θ -> recover it):")
    f = 14_074_000; d = 8.0; phi0 = -32.77   # unambiguous baseline (D<0.5)
    D = geo.electrical_spacing(d, f)
    assert D < 0.5, D
    eng = BearingEngine(baseline_m=d, freq_hz=f)
    # calibrate: simulate a reference at broadside (θ=90 -> geo phase 0)
    a, b = sim.simulate_pair(theta_deg=90.0, baseline_m=d, freq_hz=f,
                             phi0_deg=phi0, snr_db=50, tone_hz=3000.0, n=8192*8)
    dphi_ref = _cross_phase_deg(a, b)
    eng.calibrate(dphi_meas_deg=dphi_ref, known_geo_phase_deg=0.0)
    check(f"recovered φ0={eng.cal.phi0_x_deg:+.2f}° ~ measured cross-phase of ref",
          abs(_wrap180(eng.cal.phi0_x_deg - (-phi0))) < 3.0,
          f"cal={eng.cal.phi0_x_deg:+.1f}, phi0 conv={-phi0:+.1f}")
    # now measure several true bearings and recover them
    for true_theta in (60.0, 75.0, 105.0, 120.0):
        a, b = sim.simulate_pair(theta_deg=true_theta, baseline_m=d, freq_hz=f,
                                 phi0_deg=phi0, snr_db=50, tone_hz=3000.0, n=8192*8)
        dphi = _cross_phase_deg(a, b)
        r = eng.bearing(dphi)
        # single baseline gives the cone angle; mirror (θ vs 180-θ ambiguity is
        # side, not the angle) — recovered θ should match true θ within tolerance
        err = abs(r.theta_deg - true_theta) if r.ok else 999
        check(f"true θ={true_theta}° -> recovered {r.theta_deg:.1f}° (err {err:.2f}°)",
              r.ok and err < 2.0)


def test_dual_baseline_azimuth():
    print("END-TO-END dual baseline (recover full 0..360° azimuth):")
    f = 14_074_000; d = 8.0; phi0 = -32.77
    eng = DualBaselineEngine(baseline_m=d, freq_hz=f)
    # calibrate both baselines against a broadside reference on each (geo phase 0)
    ax, bx, ay, by = sim.simulate_pair_azimuth(az_deg=90.0, baseline_m=d, freq_hz=f,
                                               phi0_deg=phi0, snr_db=50,
                                               tone_hz=3000.0, n=8192*8)
    # az=90 -> dphi_x geo = 0 (cos90), dphi_y geo = max; calibrate X at az=90
    # (its geo phase is 0) and Y at az=0 (its geo phase is 0). Do two ref shots:
    axc, bxc, _, _ = sim.simulate_pair_azimuth(az_deg=90.0, baseline_m=d, freq_hz=f,
                                               phi0_deg=phi0, snr_db=50,
                                               tone_hz=3000.0, n=8192*8)
    _, _, ayc, byc = sim.simulate_pair_azimuth(az_deg=0.0, baseline_m=d, freq_hz=f,
                                               phi0_deg=phi0, snr_db=50,
                                               tone_hz=3000.0, n=8192*8)
    eng.calibrate(_cross_phase_deg(axc, bxc), _cross_phase_deg(ayc, byc))
    for true_az in (0.0, 45.0, 135.0, 210.0, 300.0):
        ax, bx, ay, by = sim.simulate_pair_azimuth(az_deg=true_az, baseline_m=d,
                                                   freq_hz=f, phi0_deg=phi0,
                                                   snr_db=50, tone_hz=3000.0, n=8192*8)
        r = eng.bearing(_cross_phase_deg(ax, bx), _cross_phase_deg(ay, by))
        err = min(abs(r.azimuth_deg - true_az), 360 - abs(r.azimuth_deg - true_az))
        check(f"true az={true_az}° -> recovered {r.azimuth_deg:.1f}° (err {err:.2f}°)",
              r.ok and err < 3.0)


def test_noise_degrades_gracefully():
    print("noisy low-SNR still recovers bearing within a looser tol:")
    f = 14_074_000; d = 8.0; phi0 = -32.77
    eng = BearingEngine(baseline_m=d, freq_hz=f)
    a, b = sim.simulate_pair(theta_deg=90.0, baseline_m=d, freq_hz=f, phi0_deg=phi0,
                             snr_db=10, tone_hz=3000.0, n=8192*16)
    eng.calibrate(_cross_phase_deg(a, b))
    a, b = sim.simulate_pair(theta_deg=70.0, baseline_m=d, freq_hz=f, phi0_deg=phi0,
                             snr_db=10, tone_hz=3000.0, n=8192*16)
    r = eng.bearing(_cross_phase_deg(a, b))
    check(f"SNR=10dB θ=70° -> {r.theta_deg:.1f}°", r.ok and abs(r.theta_deg - 70) < 5.0)


if __name__ == "__main__":
    for t in (test_geometry_roundtrip, test_geometry_broadside_and_range,
              test_error_propagation, test_refuse_until_calibrated,
              test_single_baseline_end_to_end, test_dual_baseline_azimuth,
              test_noise_degrades_gracefully):
        t()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {FAILS}")
        sys.exit(1)
    print("ALL DF PIPELINE TESTS PASSED (no hardware)")
