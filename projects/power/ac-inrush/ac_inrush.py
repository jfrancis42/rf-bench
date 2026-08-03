#!/usr/bin/env python3
"""
AC Inrush Current Capture — Fluke 80i-400 clamp + SDS2000X scope

Captures the turn-on inrush surge of a mains-powered device by clamping its
supply conductor with the Fluke 80i-400 and single-shot triggering the scope
on the current rise. Reports peak inrush current, the time the current stays
above 10 % of peak, and the I²t integral (A²·s) — the figure that sizes fuses
and inrush limiters.

This is the AC-mains, non-invasive complement to projects/power/inrush/, which
measures DC inrush across a sense resistor on a bench-PSU-fed DUT. Here nothing
is broken into: the clamp goes around the existing conductor.

Why current-only is valid here:
  Inrush is fully characterized by the current transient (peak A, duration,
  I²t). No voltage sensing needed → no mains-voltage contact. (Power/PF need
  voltage; see projects/power/ac-power/.)

Signal path:
  conductor → 80i-400 clamp → burden resistor → scope CH (1 Ω = 1 mV/A).

Procedure:
  1. Clamp the (de-energized) supply conductor, connect burden → scope.
  2. Start this script; it arms a single-shot capture.
  3. Energize the device. The script freezes on the surge and reports.

Usage:
  python ac_inrush.py                          # CH1, 1 Ω, 200 ms window
  python ac_inrush.py --window 0.5             # 500 ms capture window
  python ac_inrush.py --burden 1 --channel 2
  python ac_inrush.py --plot inrush.png

NOTE: this uses a free-run capture over --window seconds and expects you to
energize the DUT during that window; it then analyzes the captured transient.
For a hardware edge trigger, set the scope trigger manually and use --window to
size the record. Simpler and robust for one-shot bench use.

Author: Jeff Francis (N0GQ) <gjfrancis@protonmail.com>
License: GPL-3.0-or-later
"""

import argparse
import sys

import numpy as np

from rf_bench.siglent import SDS2000X
from rf_bench.fluke import Fluke80i400


def analyze_inrush(amps: np.ndarray, sample_rate: float):
    """Characterize an inrush transient.

    Returns dict: peak_a, peak_time_s, duration_above_10pct_s, i2t (A²·s),
    steady_a (RMS of the last quarter of the record, as a settle estimate).
    Works on the rectified/absolute current envelope (AC surge is bipolar).
    """
    if len(amps) < 4 or sample_rate <= 0:
        raise RuntimeError("Insufficient samples for inrush analysis")

    dt = 1.0 / sample_rate
    env = np.abs(amps)                      # envelope of the bipolar AC current
    peak_idx = int(np.argmax(env))
    peak_a = float(env[peak_idx])
    peak_time = peak_idx * dt

    thresh = 0.10 * peak_a
    above = env >= thresh
    duration_above = float(np.count_nonzero(above) * dt)

    # I²t over the whole record (A²·s) — instantaneous current squared, integrated.
    i2t = float(np.sum(amps ** 2) * dt)

    # Steady-state estimate: RMS of the final quarter of the record.
    tail = amps[int(0.75 * len(amps)):]
    steady = float(np.sqrt(np.mean(tail ** 2))) if len(tail) else 0.0

    return {
        "peak_a": peak_a,
        "peak_time_s": peak_time,
        "duration_above_10pct_s": duration_above,
        "i2t": i2t,
        "steady_a": steady,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="AC inrush current capture")
    p.add_argument("--scope", default=None, help="Scope IP (default: driver default)")
    p.add_argument("--channel", type=int, default=1, help="Scope channel (default 1)")
    p.add_argument("--burden", type=float, default=1.0,
                   help="Burden resistor ohms (default 1.0 → 1 mV/A)")
    p.add_argument("--window", type=float, default=0.2,
                   help="Capture window seconds (default 0.2)")
    p.add_argument("--vdiv", type=float, default=None,
                   help="Fix scope V/div (default: auto-range). Pin this if the "
                        "surge over-ranges auto — inrush can be 10× steady.")
    p.add_argument("--plot", default=None, help="Save current-vs-time PNG")
    args = p.parse_args()

    clamp = Fluke80i400()
    print(f"Burden {args.burden} Ω → {clamp.burden_mv_per_amp(args.burden):.1f} mV/A")
    print(f"Arming {args.window*1000:.0f} ms capture on CH{args.channel}. "
          f"Energize the device now...")

    scope = SDS2000X(args.scope) if args.scope else SDS2000X()
    try:
        v_burden, sr = scope.capture_audio(channel=args.channel,
                                           duration_s=args.window,
                                           vdiv=args.vdiv)
    finally:
        scope.close()

    amps = clamp.amps_from_burden_waveform(v_burden, args.burden)
    r = analyze_inrush(amps, sr)

    print(f"\nSample rate:            {sr/1e3:.1f} kS/s ({len(amps)} samples)")
    print(f"Peak inrush:            {r['peak_a']:.1f} A")
    print(f"Time to peak:           {r['peak_time_s']*1e3:.2f} ms")
    print(f"Duration >10% of peak:  {r['duration_above_10pct_s']*1e3:.2f} ms")
    print(f"I²t:                    {r['i2t']:.3f} A²·s")
    print(f"Steady-state (RMS tail):{r['steady_a']:.2f} A")
    if r["steady_a"] > 0:
        print(f"Inrush ratio:           {r['peak_a']/r['steady_a']:.1f}× steady")

    if args.plot:
        _save_plot(args.plot, amps, sr, r)
        print(f"\nSaved {args.plot}")
    return 0


def _save_plot(path, amps, sr, r):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = np.arange(len(amps)) / sr * 1e3   # ms
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(t, amps, color="#c8102e", lw=0.7)
    ax.axhline(r["peak_a"], color="#333", ls="--", lw=0.8,
               label=f"peak {r['peak_a']:.1f} A")
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("Current (A)")
    ax.set_title(f"AC inrush — peak {r['peak_a']:.1f} A, I²t {r['i2t']:.3f} A²·s")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
