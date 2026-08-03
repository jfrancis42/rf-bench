#!/usr/bin/env python3
"""
iq_balance_trim.py — auto-null the opposite-sideband image of the AD831
phasing upconverter by correcting soundcard I/Q gain + phase imbalance.

The phasing (Hartley) upconverter cancels the unwanted sideband only as well
as the I and Q paths are matched in amplitude and quadrature. Real hardware
(soundcard DAC channels + analog stage + the AD831 itself) has a few percent
gain mismatch and a few degrees of phase error, which leaks an image at the
mirror frequency (LO - audio) instead of (LO + audio) for USB.

This tool pre-distorts the complex IQ before it reaches the soundcard so the
downstream imbalance is cancelled:

    I' = I
    Q' = g * Q + p * I

`g` (gain, ~1) trims amplitude imbalance; `p` (cross-term, ~0) trims phase /
quadrature skew. Two real parameters null one complex image tone.

It streams a steady 1 kHz test tone as USB IQ (I->left, Q->right) with a
live-adjustable (g, p), reads the image line off the SSA3032X, and runs a
Nelder-Mead search to minimize it. Drive (output scale) is held constant so the
image level in dBm is directly comparable across candidates.

Runs on the box with the soundcard (10.1.0.11); reaches the SSA over the LAN.

Frequencies assume LO = 7200 kHz, tone = 1 kHz:
    signal (USB) = 7201 kHz    carrier = 7200 kHz    image (LSB) = 7199 kHz
Override with --lo / --tone if your setup differs.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

import numpy as np


# ----------------------------------------------------------------------------
# Tone / IQ generation
# ----------------------------------------------------------------------------

def make_base_tone(rate: int, tone_hz: float) -> tuple[np.ndarray, np.ndarray]:
    """Return one seamlessly-loopable period-block of USB tone IQ (I0, Q0).

    USB tone = analytic signal of a cosine = e^{+j 2pi f t}, i.e.
        I0 = cos(2 pi f t),  Q0 = sin(2 pi f t)
    which is a pure positive-frequency (upper-sideband) tone. We build an
    integer number of cycles so the buffer loops with no discontinuity.
    """
    # Choose a length that is an integer number of both tone cycles and is a
    # round fraction of a second. rate/gcd(rate,tone) samples = 1 full lowest-
    # common period; multiply up to ~1 s for a comfortable buffer.
    from math import gcd
    base = rate // gcd(rate, int(tone_hz))      # samples in one exact period set
    reps = max(1, int(round(rate / base)))      # ~1 s worth, still integer cycles
    n = base * reps
    t = np.arange(n) / rate
    i0 = np.cos(2 * np.pi * tone_hz * t).astype(np.float32)
    q0 = np.sin(2 * np.pi * tone_hz * t).astype(np.float32)
    return i0, q0


# ----------------------------------------------------------------------------
# Live IQ player with atomic (g, p) update
# ----------------------------------------------------------------------------

class BalancedPlayer:
    """Continuously streams corrected USB tone IQ; (g, p) settable live."""

    def __init__(self, rate: int, tone_hz: float, scale: float, device):
        self.rate = rate
        self.scale = scale
        self.device = device
        self.i0, self.q0 = make_base_tone(rate, tone_hz)
        self.n = len(self.i0)
        self._pos = 0
        self._lock = threading.Lock()
        self._g = 1.0
        self._p = 0.0
        self.clipped = False
        self._stream = None

    def set_gp(self, g: float, p: float) -> None:
        with self._lock:
            self._g = g
            self._p = p

    def _callback(self, outdata, frames, time_info, status):
        with self._lock:
            g, p = self._g, self._p
        pos = self._pos
        idx = (pos + np.arange(frames)) % self.n
        i = self.i0[idx]
        q = self.q0[idx]
        ic = self.scale * i
        qc = self.scale * (g * q + p * i)
        peak = max(float(np.max(np.abs(ic))), float(np.max(np.abs(qc))))
        if peak > 0.999:
            self.clipped = True
        outdata[:, 0] = ic
        outdata[:, 1] = qc
        self._pos = (pos + frames) % self.n

    def start(self):
        import sounddevice as sd
        self._stream = sd.OutputStream(
            samplerate=self.rate, channels=2, dtype="float32",
            device=self.device, blocksize=1024, callback=self._callback)
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


# ----------------------------------------------------------------------------
# SSA measurement
# ----------------------------------------------------------------------------

class Analyzer:
    """Thin wrapper: narrow span around the LO, read the three lines."""

    def __init__(self, host: str, lo_hz: float, tone_hz: float,
                 rbw_hz: int, ref_dbm: float):
        from rf_bench.siglent import SSA3000X
        self.ssa = SSA3000X(host)
        self.ssa.connect()
        self.lo = lo_hz
        self.tone = tone_hz
        self.f_sig = lo_hz + tone_hz     # wanted (USB)
        self.f_car = lo_hz               # carrier
        self.f_img = lo_hz - tone_hz     # image (LSB)
        # Span brackets image..signal with margin; force a narrow RBW so the
        # three lines (tone_hz apart) resolve cleanly.
        margin = tone_hz * 0.6
        self.start = self.f_img - margin
        self.stop = self.f_sig + margin
        self.ssa.write(f":FREQ:STAR {int(self.start)}")
        self.ssa.write(f":FREQ:STOP {int(self.stop)}")
        self.ssa.write(f":SENS:BAND:RES {int(rbw_hz)}")
        self.ssa.write(f":SENS:BAND:VID {int(rbw_hz)}")
        self.ssa.set_ref_level(ref_dbm)
        self.ssa.set_input_attenuation(0)
        self._freqs = None

    def _freq_axis(self, n: int) -> np.ndarray:
        if self._freqs is None or len(self._freqs) != n:
            self._freqs = np.linspace(self.start, self.stop, n)
        return self._freqs

    def _level_at(self, trace, freqs, f0, win_hz):
        m = np.abs(freqs - f0) <= win_hz
        if not np.any(m):
            return float("nan")
        return float(np.max(trace[m]))

    def measure(self) -> dict:
        self.ssa.single_sweep()
        trace = self.ssa.get_trace()
        freqs = self._freq_axis(len(trace))
        win = self.tone * 0.35
        return {
            "signal": self._level_at(trace, freqs, self.f_sig, win),
            "carrier": self._level_at(trace, freqs, self.f_car, win),
            "image": self._level_at(trace, freqs, self.f_img, win),
        }

    def close(self):
        try:
            self.ssa.continuous_sweep()
        finally:
            self.ssa.close()


# ----------------------------------------------------------------------------
# Main: measure baseline, optimize (g, p), report
# ----------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ssa", default="10.1.1.60", help="SSA host (default 10.1.1.60)")
    p.add_argument("--lo", type=float, default=7_200_000, help="LO freq Hz (default 7200 kHz)")
    p.add_argument("--tone", type=float, default=1000.0, help="audio tone Hz (default 1000)")
    p.add_argument("--rate", type=int, default=8000, help="IQ sample rate (default 8000)")
    p.add_argument("--scale", type=float, default=0.85, help="output peak scale (default 0.85)")
    p.add_argument("--rbw", type=int, default=100, help="SSA RBW Hz (default 100)")
    p.add_argument("--ref", type=float, default=-20.0, help="SSA ref level dBm (default -20)")
    p.add_argument("--device", default=None, help="output device (index/name; default system default)")
    p.add_argument("--settle", type=float, default=0.4, help="settle seconds before each sweep")
    p.add_argument("--maxiter", type=int, default=80, help="Nelder-Mead max iterations")
    args = p.parse_args()

    device = args.device
    if device is not None:
        try:
            device = int(device)
        except ValueError:
            pass

    print(f"LO={args.lo/1e3:.1f} kHz  tone={args.tone:.0f} Hz  "
          f"signal={args.lo/1e3+args.tone/1e3:.1f}  carrier={args.lo/1e3:.1f}  "
          f"image={args.lo/1e3-args.tone/1e3:.1f} kHz", file=sys.stderr)

    player = BalancedPlayer(args.rate, args.tone, args.scale, device)
    analyzer = Analyzer(args.ssa, args.lo, args.tone, args.rbw, args.ref)

    # Give the SSA one throwaway sweep to apply the new span/RBW.
    player.set_gp(1.0, 0.0)
    player.start()
    time.sleep(0.8)
    analyzer.measure()

    def report(tag, g, p, m):
        supp_img = m["signal"] - m["image"]
        supp_car = m["signal"] - m["carrier"]
        print(f"[{tag}] g={g:+.5f} p={p:+.5f}  "
              f"sig={m['signal']:6.1f}  car={m['carrier']:6.1f}  "
              f"img={m['image']:6.1f} dBm  |  "
              f"image_supp={supp_img:5.1f} dB  carrier_supp={supp_car:5.1f} dB",
              file=sys.stderr)

    base = analyzer.measure()
    report("baseline", 1.0, 0.0, base)

    evals = {"n": 0}

    def objective(x):
        g, pp = float(x[0]), float(x[1])
        player.set_gp(g, pp)
        time.sleep(args.settle)
        m = analyzer.measure()
        evals["n"] += 1
        report(f"eval{evals['n']:02d}", g, pp, m)
        return m["image"]

    from scipy.optimize import minimize
    res = minimize(
        objective,
        x0=np.array([1.0, 0.0]),
        method="Nelder-Mead",
        options={
            "xatol": 1e-4, "fatol": 0.3,
            "initial_simplex": np.array([[1.0, 0.0], [1.05, 0.0], [1.0, 0.05]]),
            "maxiter": args.maxiter,
        },
    )

    g_best, p_best = float(res.x[0]), float(res.x[1])
    player.set_gp(g_best, p_best)
    time.sleep(args.settle)
    final = analyzer.measure()

    print("\n================ RESULT ================", file=sys.stderr)
    report("baseline", 1.0, 0.0, base)
    report("optimized", g_best, p_best, final)
    d_img = (final["signal"] - final["image"]) - (base["signal"] - base["image"])
    print(f"\nBest correction:  g = {g_best:.5f}   p = {p_best:.5f}", file=sys.stderr)
    print(f"Image suppression improved by {d_img:+.1f} dB "
          f"({base['signal']-base['image']:.1f} -> {final['signal']-final['image']:.1f} dB below signal)",
          file=sys.stderr)
    if player.clipped:
        print("WARNING: output clipped at some point — lower --scale and rerun.",
              file=sys.stderr)
    print("\nApply these in the modulator:  Q' = g*Q + p*I", file=sys.stderr)
    print("Holding optimized tone. Ctrl-C to stop.", file=sys.stderr)

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        player.stop()
        analyzer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
