#!/usr/bin/env python3
"""
df.py — HF direction-finding experiment on the SunSDR2 PRO's coherent receivers.

PHASE 0 (this file): live cross-phase readout. Both DDCs are tuned to the SAME
frequency; we measure the phase difference Δφ = angle(Sxy) between RX1 and RX2 at
the strongest signal bin, smoothed, with its stability (std-dev over a rolling
window). See df-proposal.md for the full plan.

Why this first: Δφ is the raw DF observable. On the current SINGLE SHARED antenna,
Δφ should sit at a CONSTANT (the per-session inter-DDC offset) with low variance.
This validates the observable + plumbing with zero new hardware, and — crucially —
measures the PHASE-NOISE FLOOR (the Δφ std-dev), which sets the best-case angular
resolution any later two-antenna DF can achieve. It does NOT yet produce a
bearing (that needs two spatially-separated antennas + calibration; Phases 1-3).

WHY THE DIRECT RADIO CALLBACK, NOT THE NETWORK IQ SERVERS
---------------------------------------------------------
DF lives or dies on SAMPLE ALIGNMENT between the two channels: a sample offset δ
injects a phase error 2π·f·δ/fs into Δφ. solsdr's two network IQ servers
(:5555 RX1, :5557 RX2) are independent TCP streams with independent buffering —
no alignment guarantee, and they could slip mid-session (silently invalidating a
calibration). So DF pulls BOTH receivers from the same index-tagged UDP stream
callback (Radio(rx2=True) -> cb(idx, iq)), which is inherently sample-aligned.
Consequence: this tool imports solsdr.radio and must run on the radio host (it
talks the raw UDP protocol directly), like tools/rx2_coherence.py in the solsdr
tree. It needs the solsdr project importable (see --solsdr-path / SOLSDR_PATH).

Usage (on the radio host):
    python3 df.py --freq 14074 --radio-ip 10.1.2.3 --local-ip 10.1.2.185
    python3 df.py --freq 14074 --seconds 60        # longer stability run
"""
import argparse
import os
import statistics
import sys
import time
from collections import deque

import numpy as np

# solsdr is a separate project; make it importable. Order: --solsdr-path (added
# in main before this matters), $SOLSDR_PATH, then the usual dev location.
_DEF_SOLSDR = os.path.expanduser("~/Dropbox/build/solsdr")
for _p in (os.environ.get("SOLSDR_PATH"), _DEF_SOLSDR):
    if _p and os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


def cross_spectrum(a, b, nfft=4096):
    """Welch-averaged cross-spectrum + auto-spectra over whole segments.

    Returns (gamma2, power, Sxy, segs):
      gamma2 = |Sxy|^2 / (Sxx*Syy)  per bin (magnitude-squared coherence)
      power  = Sxx + Syy            per bin (for picking the signal bin)
      Sxy    = cross-spectrum       per bin (its ANGLE is the DF observable)
    Mirrors solsdr tools/rx2_coherence.py:spectral_coherence so results are
    directly comparable.
    """
    w = np.hanning(nfft)
    m = min(len(a), len(b))
    segs = m // nfft
    if segs == 0:
        return None, None, None, 0
    Sxy = np.zeros(nfft, dtype=complex)
    Sxx = np.zeros(nfft)
    Syy = np.zeros(nfft)
    for k in range(segs):
        Fa = np.fft.fft(a[k * nfft:(k + 1) * nfft] * w)
        Fb = np.fft.fft(b[k * nfft:(k + 1) * nfft] * w)
        Sxy += Fa * np.conj(Fb)
        Sxx += np.abs(Fa) ** 2
        Syy += np.abs(Fb) ** 2
    gamma2 = (np.abs(Sxy) ** 2) / (Sxx * Syy + 1e-30)
    return gamma2, (Sxx + Syy), Sxy, segs


def _circ_stats(degs):
    """Circular mean + std (deg) — plain std is wrong near the ±180° wrap."""
    r = np.radians(np.asarray(degs))
    c, s = np.mean(np.cos(r)), np.mean(np.sin(r))
    mean = np.degrees(np.arctan2(s, c))
    R = np.hypot(c, s)                       # mean resultant length, 0..1
    std = np.degrees(np.sqrt(-2.0 * np.log(max(R, 1e-12))))  # circular std
    return mean, std


class PhaseMonitor:
    """Accumulates per-block Δφ measurements and reports live stats."""

    def __init__(self, nfft=4096, window=50, min_gamma=0.5, fixed_bin=None):
        self.nfft = nfft
        self.min_gamma = min_gamma
        # If set, always measure Δφ at THIS bin index instead of the strongest.
        # Phase 0 showed "strongest bin" fails on multi-tone/hopping signals
        # (FT8: 38° std) because the peak jumps between tones at different
        # offset frequencies and a residual inter-channel time offset makes
        # phase frequency-dependent. DF must pin a single fixed carrier bin.
        self.fixed_bin = fixed_bin
        self.phases = deque(maxlen=window)   # recent Δφ (deg) at the signal bin
        self.gammas = deque(maxlen=window)
        self.n_meas = 0
        self.n_reject = 0

    def add(self, a, b):
        """Process one IQ chunk from both receivers; returns a status dict."""
        gamma2, power, Sxy, segs = cross_spectrum(a, b, self.nfft)
        if segs == 0:
            return None
        pk = self.fixed_bin if self.fixed_bin is not None else int(np.argmax(power))
        g = float(gamma2[pk])
        dphi = float(np.degrees(np.angle(Sxy[pk])))
        rx1_db = 10 * np.log10(np.mean(np.abs(a) ** 2) + 1e-30)
        if g < self.min_gamma:
            # signal too weak / incoherent this block — don't pollute the stats
            self.n_reject += 1
            return {"ok": False, "gamma": g, "dphi": dphi, "rx1_db": rx1_db,
                    "bin": pk}
        self.phases.append(dphi)
        self.gammas.append(g)
        self.n_meas += 1
        mean, std = _circ_stats(self.phases)
        return {"ok": True, "gamma": g, "dphi": dphi, "rx1_db": rx1_db, "bin": pk,
                "mean": mean, "std": std, "n": len(self.phases)}


def resolution_note(std_deg, freq_hz, baseline_m):
    """Best-case angular resolution a two-element interferometer could get given
    the measured Δφ std, IF we had two antennas on `baseline_m`. Broadside
    (θ=90°): dφ/dθ = (2π d/λ)·sin(θ); at broadside sin=1, so dθ ≈ dφ·λ/(2π d).
    This is an optimistic floor (broadside, no skywave), for context only."""
    c = 299_792_458.0
    lam = c / freq_hz
    dphi_rad = np.radians(std_deg)
    dtheta = dphi_rad * lam / (2 * np.pi * baseline_m)
    return np.degrees(dtheta), lam


def main():
    ap = argparse.ArgumentParser(
        description="Phase 0 DF: live cross-phase readout on the coherent RX pair")
    ap.add_argument("--freq", type=float, default=14074.0,
                    help="kHz; BOTH receivers tuned here (DF needs same freq). "
                         "Use a strong steady signal (busy 20m FT8, a broadcast "
                         "carrier, or an injected tone).")
    ap.add_argument("--seconds", type=float, default=30.0,
                    help="run duration (default 30)")
    ap.add_argument("--nfft", type=int, default=4096, help="FFT size per segment")
    ap.add_argument("--min-gamma", type=float, default=0.5,
                    help="ignore blocks whose peak-bin coherence is below this "
                         "(signal too weak/incoherent to trust; default 0.5)")
    ap.add_argument("--block", type=float, default=0.25,
                    help="seconds of IQ per Δφ measurement (default 0.25)")
    ap.add_argument("--bin-freq", type=float, default=None, metavar="HZ",
                    help="measure Δφ at a FIXED baseband bin this many Hz from "
                         "the tuned center (0 = center/DC), instead of the "
                         "strongest bin. REQUIRED for a real DF/calibration "
                         "measurement: Phase 0 showed the strongest-bin default "
                         "fails on multi-tone/hopping signals (FT8 gave 38° std "
                         "vs 0.1° on a steady carrier). Pin a single CW carrier.")
    ap.add_argument("--baseline", type=float, default=10.0,
                    help="hypothetical antenna baseline (m) for the resolution "
                         "note only — Phase 0 has ONE antenna and no bearing")
    ap.add_argument("--rate", type=float, default=None,
                    help="IQ sample rate (default: radio default 39062.5)")
    ap.add_argument("--radio-ip", default="10.1.2.3")
    ap.add_argument("--local-ip", default="10.1.2.185")
    ap.add_argument("--solsdr-path", default=None,
                    help="path to the solsdr project (else $SOLSDR_PATH or "
                         "~/Dropbox/build/solsdr)")
    args = ap.parse_args()

    if args.solsdr_path and os.path.isdir(args.solsdr_path):
        sys.path.insert(0, args.solsdr_path)
    try:
        from solsdr.radio import Radio
    except ImportError as e:
        sys.exit(f"cannot import solsdr ({e}); pass --solsdr-path /path/to/solsdr "
                 f"or set SOLSDR_PATH. This tool runs on the radio host and talks "
                 f"the raw UDP protocol directly.")

    freq_hz = int(args.freq * 1000)
    print(f"Phase-0 DF cross-phase monitor")
    print(f"  freq {args.freq:.1f} kHz (both RX)  nfft {args.nfft}  "
          f"block {args.block:.2f}s  min-gamma {args.min_gamma}")
    print(f"  NOTE: single shared antenna -> Δφ should be a CONSTANT (the "
          f"per-session inter-DDC offset); its std is the phase-noise floor.\n")

    r = Radio(radio_ip=args.radio_ip, local_ip=args.local_ip, variant="PRO",
              rx2=True, verbose=False, sample_rate=args.rate)
    if not r.open(wake_timeout=20):
        sys.exit("radio open failed")
    r.set_frequency(freq_hz)
    r.set_frequency(freq_hz, rx=1)          # RX2 same freq for DF
    time.sleep(0.5)
    rate = r.wire_rate

    buf = {0: [], 1: []}

    def cb(idx, iq):
        buf[idx].append(iq.copy())
    r.start_stream(cb)

    fixed_bin = None
    if args.bin_freq is not None:
        # np.fft.fft bin k -> frequency k*rate/nfft for k<nfft/2, negative above.
        # Map a signed Hz offset to the nearest bin (wrap negatives to the top).
        fixed_bin = int(round(args.bin_freq / rate * args.nfft)) % args.nfft
        print(f"  measuring at FIXED bin {fixed_bin} "
              f"({args.bin_freq:+.0f} Hz from center)\n")
    mon = PhaseMonitor(nfft=args.nfft, min_gamma=args.min_gamma,
                       fixed_bin=fixed_bin)
    block_samples = int(rate * args.block)
    t0 = time.time()
    try:
        while time.time() - t0 < args.seconds:
            time.sleep(args.block)
            n = min(len(buf[0]), len(buf[1]))
            if n == 0:
                continue
            a = np.concatenate(buf[0][:n]); b = np.concatenate(buf[1][:n])
            buf[0] = buf[0][n:]; buf[1] = buf[1][n:]
            m = min(len(a), len(b))
            if m < args.nfft:
                # put back so we accumulate enough for at least one FFT segment
                buf[0].insert(0, a[:m]); buf[1].insert(0, b[:m])
                continue
            st = mon.add(a[:m], b[:m])
            if st is None:
                continue
            el = time.time() - t0
            if st["ok"]:
                print(f"  t={el:5.1f}s  Δφ={st['dphi']:+7.1f}°  "
                      f"γ²={st['gamma']:.3f}  RX1={st['rx1_db']:5.1f}dBFS  "
                      f"| mean {st['mean']:+7.1f}°  std {st['std']:5.2f}°  "
                      f"(n={st['n']})", flush=True)
            else:
                print(f"  t={el:5.1f}s  Δφ={st['dphi']:+7.1f}°  "
                      f"γ²={st['gamma']:.3f}  RX1={st['rx1_db']:5.1f}dBFS  "
                      f"| REJECTED (γ²<{args.min_gamma})", flush=True)
    finally:
        r.close()

    print()
    if mon.n_meas >= 2:
        mean, std = _circ_stats(mon.phases)
        gmean = statistics.mean(mon.gammas)
        print(f"SUMMARY  ({mon.n_meas} measurements, {mon.n_reject} rejected)")
        print(f"  cross-phase Δφ : {mean:+.1f}°  (circular std {std:.2f}°)")
        print(f"  coherence γ²   : {gmean:.3f}")
        dtheta, lam = resolution_note(std, freq_hz, args.baseline)
        print(f"  phase-noise floor -> best-case angular resolution "
              f"~{dtheta:.2f}° at broadside on a {args.baseline:.0f} m baseline "
              f"(λ={lam:.1f} m)")
        print(f"  [interpretation] a stable Δφ with small std confirms the DDCs "
              f"are phase-locked and quantifies the DF noise floor. This is the "
              f"per-session offset that Phase 1 will calibrate out.")
    else:
        print("Not enough coherent measurements. Point both RX at a stronger, "
              "steadier signal, raise --seconds, or lower --min-gamma.")


if __name__ == "__main__":
    sys.exit(main())
