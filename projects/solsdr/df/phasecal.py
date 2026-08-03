#!/usr/bin/env python3
"""
phasecal.py — characterize the inter-channel phase vs. FREQUENCY (Phase 1 prep).

On a SINGLE shared antenna both DDCs get identical RF, so the cross-spectrum
phase at each bin is the phase of the inter-channel transfer H1(f)·conj(H2(f)).
If the two channels differ only by a constant phase φ0 and a fixed sample/time
offset δ, then:

    Δφ(f) = φ0 + 2π·f·δ            (f = baseband offset from center, Hz)

So the shape of Δφ(f) tells us what Phase-1 calibration must store:
  * FLAT  (slope≈0)  -> a single SCALAR offset φ0 is enough.
  * RAMP  (slope≠0)  -> there's a time offset δ; calibration must be
                        frequency-dependent (store δ, or the whole curve).

Phase 0 saw a hint of this: FT8 (multi-tone across ~3 kHz) gave 38° Δφ spread
while a single carrier gave 0.1°. This tool measures the slope directly and
reports δ. Run on the radio host, single shared antenna, on a signal with energy
spread across frequency (busy FT8, an AM broadcast with sidebands, or — best —
a wide noisy/busy band captured at a high --rate).

Usage (radio host):
    python3 phasecal.py --freq 14074 --seconds 20 --rate 312500
"""
import argparse
import os
import sys
import time

import numpy as np

_DEF_SOLSDR = os.path.expanduser("~/Dropbox/build/solsdr")
for _p in (os.environ.get("SOLSDR_PATH"), _DEF_SOLSDR):
    if _p and os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


def cross_spectrum(a, b, nfft=8192):
    """Welch cross-spectrum + auto-spectra. Returns (Sxy, Sxx, Syy, segs)."""
    w = np.hanning(nfft)
    m = min(len(a), len(b))
    segs = m // nfft
    Sxy = np.zeros(nfft, dtype=complex)
    Sxx = np.zeros(nfft)
    Syy = np.zeros(nfft)
    for k in range(segs):
        Fa = np.fft.fft(a[k * nfft:(k + 1) * nfft] * w)
        Fb = np.fft.fft(b[k * nfft:(k + 1) * nfft] * w)
        Sxy += Fa * np.conj(Fb)
        Sxx += np.abs(Fa) ** 2
        Syy += np.abs(Fb) ** 2
    return Sxy, Sxx, Syy, segs


def fit_phase_vs_freq(Sxy, Sxx, Syy, rate, nfft, gamma_min=0.9):
    """At bins where coherence γ² >= gamma_min, extract Δφ(f) and fit a line
    Δφ = φ0 + 2π·f·δ (weighted least squares by coherence). Returns a dict."""
    gamma2 = (np.abs(Sxy) ** 2) / (Sxx * Syy + 1e-30)
    freqs = np.fft.fftfreq(nfft, d=1.0 / rate)          # signed baseband Hz
    sel = gamma2 >= gamma_min
    n_sel = int(np.sum(sel))
    if n_sel < 4:
        return {"ok": False, "n_bins": n_sel}
    f = freqs[sel]
    phi = np.angle(Sxy[sel])                            # radians, wrapped
    w = gamma2[sel]                                     # weight by coherence
    order = np.argsort(f)
    f, phi, w = f[order], phi[order], w[order]
    # Unwrap along frequency so a genuine ramp isn't chopped at ±π. (Requires
    # the selected bins to be reasonably dense in f; report the span so the
    # caller can judge trust.)
    phi_u = np.unwrap(phi)
    # weighted linear fit phi_u = a*f + b
    W = np.diag(w)
    A = np.vstack([f, np.ones_like(f)]).T
    ATA = A.T @ W @ A
    ATb = A.T @ W @ phi_u
    slope, intercept = np.linalg.solve(ATA, ATb)        # rad/Hz, rad
    resid = phi_u - (slope * f + intercept)
    resid_std = float(np.sqrt(np.average(resid ** 2, weights=w)))
    delta_s = slope / (2 * np.pi)                       # seconds
    return {
        "ok": True,
        "n_bins": n_sel,
        "f_min": float(f.min()), "f_max": float(f.max()),
        "span_hz": float(f.max() - f.min()),
        "phi0_deg": float(np.degrees(intercept)),
        "slope_deg_per_khz": float(np.degrees(slope) * 1000.0),
        "delta_ns": float(delta_s * 1e9),
        "delta_samples": float(delta_s * rate),
        "resid_std_deg": float(np.degrees(resid_std)),
    }


def capture(freq_hz, seconds, rate, radio_ip, local_ip):
    from solsdr.radio import Radio
    r = Radio(radio_ip=radio_ip, local_ip=local_ip, variant="PRO",
              rx2=True, verbose=False, sample_rate=rate)
    if not r.open(wake_timeout=20):
        raise RuntimeError("radio open failed")
    r.set_frequency(freq_hz)
    r.set_frequency(freq_hz, rx=1)
    time.sleep(0.5)
    buf = {0: [], 1: []}
    r.start_stream(lambda idx, iq: buf[idx].append(iq.copy()))
    time.sleep(seconds)
    r.close()
    n = min(len(buf[0]), len(buf[1]))
    a = np.concatenate(buf[0][:n]) if n else np.zeros(0, np.complex64)
    b = np.concatenate(buf[1][:n]) if n else np.zeros(0, np.complex64)
    m = min(len(a), len(b))
    return r.wire_rate, a[:m], b[:m]


def main():
    ap = argparse.ArgumentParser(
        description="Measure inter-channel phase vs frequency (scalar vs δ)")
    ap.add_argument("--freq", type=float, default=14074.0, help="center kHz")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--rate", type=float, default=None,
                    help="sample rate; a HIGHER rate spreads signal over more "
                         "frequency and gives a better slope estimate")
    ap.add_argument("--nfft", type=int, default=8192)
    ap.add_argument("--gamma-min", type=float, default=0.9,
                    help="only fit bins with coherence above this (default 0.9)")
    ap.add_argument("--radio-ip", default="10.1.2.3")
    ap.add_argument("--local-ip", default="10.1.2.185")
    args = ap.parse_args()

    try:
        rate, a, b = capture(int(args.freq * 1000), args.seconds, args.rate,
                             args.radio_ip, args.local_ip)
    except ImportError as e:
        sys.exit(f"cannot import solsdr ({e}); set SOLSDR_PATH.")
    if len(a) < args.nfft:
        sys.exit("not enough IQ captured")

    Sxy, Sxx, Syy, segs = cross_spectrum(a, b, args.nfft)
    fit = fit_phase_vs_freq(Sxy, Sxx, Syy, rate, args.nfft, args.gamma_min)
    print(f"phase-vs-frequency fit  (rate {rate:.0f} S/s, nfft {args.nfft}, "
          f"{segs} segs, γ²≥{args.gamma_min})")
    if not fit["ok"]:
        print(f"  only {fit['n_bins']} coherent bins — need a signal spread over "
              f"more frequency (try a busier band or higher --rate).")
        return
    print(f"  coherent bins: {fit['n_bins']} spanning "
          f"{fit['f_min']:+.0f}..{fit['f_max']:+.0f} Hz "
          f"({fit['span_hz']/1000:.1f} kHz)")
    print(f"  φ0 (offset at center) : {fit['phi0_deg']:+.2f}°")
    print(f"  slope                 : {fit['slope_deg_per_khz']:+.3f} °/kHz")
    print(f"  -> time offset δ       : {fit['delta_ns']:+.1f} ns "
          f"({fit['delta_samples']:+.4f} samples)")
    print(f"  fit residual (std)    : {fit['resid_std_deg']:.2f}°")
    # verdict: is the ramp significant across a realistic DF passband (say 3 kHz)?
    ramp_3k = abs(fit["slope_deg_per_khz"]) * 3.0
    if ramp_3k < 2.0:
        print(f"  VERDICT: essentially FLAT ({ramp_3k:.1f}° over 3 kHz) -> a "
              f"SCALAR offset calibration is sufficient.")
    else:
        print(f"  VERDICT: sloped ({ramp_3k:.1f}° over 3 kHz) -> calibration must "
              f"be FREQUENCY-DEPENDENT; store δ={fit['delta_ns']:+.1f} ns and "
              f"correct per-bin (or calibrate at the exact DF frequency).")
    print("\n  NOTE: single shared antenna, so this is the pure inter-channel "
          "term. With two antennas the antenna/feedline paths add to it — but "
          "this tells us the RECEIVER contribution and the calibration MODEL.")


if __name__ == "__main__":
    sys.exit(main())
