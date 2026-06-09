#!/usr/bin/env python3
"""
Diversity Reception — KiwiSDR + SunSDR2 Pro dual-antenna equal-gain combining.

Two antennas feed two receivers: the KiwiSDR (or a second SunSDR) and the SunSDR2 Pro,
both tuned to the same HF frequency.  This script aligns the IQ phases between
the two receivers (via cross-correlation), then combines them using equal-gain
combining (EGC) to improve SNR on weak signals.

Combining methods implemented:
  egc     — Equal-Gain Combining: align phases, sum, compare SNR
  mrc     — Maximal-Ratio Combining: weight by estimated SNR per branch
  switch  — Switched diversity: use the better branch at each snapshot

Usage:
    python diversity.py --sdr-host 192.168.1.100 --kiwi-host kiwisdr.local \
        --freq 14074000
    python diversity.py --sdr-host 192.168.1.100 --kiwi-host kiwisdr.local \
        --freq 7074000 --method mrc --duration 30
    python diversity.py --sdr-host 192.168.1.100 --kiwi-host kiwisdr.local \
        --freq 14074000 --loop
"""

import argparse
import sys
import time

import numpy as np

from rf_bench.kiwisdr import KiwiSDR, KiwiSDRError
from rf_bench.sunsdr import SunSDR, SunSDRError


# ── Constants ─────────────────────────────────────────────────────────────────

# KiwiSDR sample rate (fixed at 12 kHz)
KIWI_RATE = 12_000
# SunSDR IQ rate to match effective bandwidth with KiwiSDR
# Use 48 kHz and downsample to 12 kHz for alignment
SUNSDR_RATE = 48_000

# Number of KiwiSDR samples to capture per measurement
KIWI_SAMPLES = 12_000   # 1 second at 12 kHz


# ── IQ utility functions ──────────────────────────────────────────────────────

def _snr_db(iq: np.ndarray) -> float:
    """Estimate SNR: peak FFT bin power minus noise floor (median)."""
    n      = len(iq)
    window = np.hanning(n).astype(np.float32)
    fft_db = 10.0 * np.log10(
        np.maximum(np.abs(np.fft.fft(iq * window)) ** 2 / np.sum(window ** 2), 1e-30)
    )
    noise  = float(np.median(fft_db))
    peak   = float(np.max(fft_db))
    return peak - noise


def _rms_dbfs(iq: np.ndarray) -> float:
    return float(10.0 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-60))


def _cross_correlate_phase(iq_ref: np.ndarray, iq_b: np.ndarray) -> float:
    """
    Find the phase rotation to align iq_b to iq_ref.

    Uses the mean phase of the cross-spectrum:
        phase = angle(sum(iq_ref * conj(iq_b)))

    Returns phase offset in radians.  Apply: iq_b_aligned = iq_b * exp(j*phase)
    """
    if len(iq_ref) != len(iq_b):
        n = min(len(iq_ref), len(iq_b))
        iq_ref = iq_ref[:n]
        iq_b   = iq_b[:n]
    cross = np.sum(iq_ref * np.conj(iq_b))
    return float(np.angle(cross))


def _align_resample(iq_sunsdr: np.ndarray, sunsdr_rate: int,
                    target_len: int) -> np.ndarray:
    """
    Downsample SunSDR IQ from sunsdr_rate to match the KiwiSDR length.

    Uses a simple decimation (no anti-alias filter here; adequate for
    narrowband signals within the ±5 kHz KiwiSDR passband).
    """
    ratio   = sunsdr_rate // KIWI_RATE
    if ratio <= 1:
        return iq_sunsdr[:target_len]
    # Decimate
    decimated = iq_sunsdr[::ratio]
    if len(decimated) > target_len:
        decimated = decimated[:target_len]
    elif len(decimated) < target_len:
        # Pad with zeros (shouldn't happen in normal operation)
        pad = np.zeros(target_len - len(decimated), dtype=np.complex64)
        decimated = np.concatenate([decimated, pad])
    return decimated.astype(np.complex64)


# ── Combining methods ─────────────────────────────────────────────────────────

def _combine_egc(iq_a: np.ndarray, iq_b: np.ndarray
                 ) -> tuple[np.ndarray, float]:
    """Equal-Gain Combining: align phase, sum, normalise by 2."""
    phase = _cross_correlate_phase(iq_a, iq_b)
    iq_b_aligned = iq_b * np.exp(1j * phase).astype(np.complex64)
    combined = (iq_a + iq_b_aligned) / 2.0
    return combined.astype(np.complex64), phase


def _combine_mrc(iq_a: np.ndarray, iq_b: np.ndarray
                 ) -> tuple[np.ndarray, float]:
    """
    Maximal-Ratio Combining: weight each branch by its estimated amplitude.

    w_i = conj(h_i) / sum(|h_i|^2)
    where h_i is estimated as the RMS amplitude of branch i.
    """
    amp_a = float(np.sqrt(np.mean(np.abs(iq_a) ** 2)) + 1e-30)
    amp_b = float(np.sqrt(np.mean(np.abs(iq_b) ** 2)) + 1e-30)
    w_a   = amp_a / (amp_a ** 2 + amp_b ** 2)
    w_b   = amp_b / (amp_a ** 2 + amp_b ** 2)

    phase = _cross_correlate_phase(iq_a, iq_b)
    iq_b_aligned = iq_b * np.exp(1j * phase).astype(np.complex64)
    combined = (w_a * iq_a + w_b * iq_b_aligned).astype(np.complex64)
    return combined, phase


def _combine_switch(iq_a: np.ndarray, iq_b: np.ndarray
                    ) -> tuple[np.ndarray, float]:
    """Switched diversity: return the higher-SNR branch, no combination."""
    snr_a = _snr_db(iq_a)
    snr_b = _snr_db(iq_b)
    if snr_a >= snr_b:
        return iq_a.copy(), 0.0
    return iq_b.copy(), 0.0


_COMBINERS = {
    "egc":    _combine_egc,
    "mrc":    _combine_mrc,
    "switch": _combine_switch,
}


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    freq_hz = args.freq
    method  = args.method
    combine = _COMBINERS[method]

    print(f"\n  Diversity Reception  —  {method.upper()}")
    print(f"  KiwiSDR: {args.kiwi_host}:{args.kiwi_port}")
    print(f"  SunSDR:  {args.sdr_host}:{args.sdr_port}")
    print(f"  Frequency: {freq_hz/1e6:.4f} MHz")
    print()

    print(f"  Connecting to KiwiSDR...")
    try:
        kiwi = KiwiSDR(args.kiwi_host, port=args.kiwi_port, channel=0,
                       passband_hz=10_000)
        kiwi.set_center_freq(freq_hz)
        print(f"  KiwiSDR connected.")
    except KiwiSDRError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    print(f"  Connecting to SunSDR...")
    try:
        sdr = SunSDR(args.sdr_host, port=args.sdr_port, iq_rate=SUNSDR_RATE)
        sdr.set_frequency(freq_hz)
        sdr.set_mode("USB")
        print(f"  SunSDR connected: {sdr.identify()['device']}")
    except SunSDRError as e:
        print(f"  ERROR: {e}")
        kiwi.close()
        sys.exit(1)

    time.sleep(0.1)

    duration_s = args.duration
    n_reps     = args.reps
    cycle      = 0
    all_snr    = {"kiwi": [], "sdr": [], "combined": []}

    try:
        while True:
            cycle += 1
            if n_reps and cycle > n_reps:
                break

            # Capture IQ from both receivers simultaneously (close enough in time)
            try:
                n_kiwi = KIWI_SAMPLES
                n_sdr  = SUNSDR_RATE   # 1 second at SunSDR rate

                iq_kiwi  = kiwi.capture_iq(n_kiwi)
                iq_sdr   = sdr.capture_iq(n_sdr)
            except (KiwiSDRError, SunSDRError) as e:
                print(f"  [capture error: {e}]")
                time.sleep(1.0)
                continue

            # Resample SunSDR to match KiwiSDR length
            iq_sdr_resampled = _align_resample(iq_sdr, SUNSDR_RATE, len(iq_kiwi))

            # Measure individual SNR
            snr_kiwi = _snr_db(iq_kiwi)
            snr_sdr  = _snr_db(iq_sdr_resampled)

            # Combine
            iq_combined, phase_offset = combine(iq_kiwi, iq_sdr_resampled)
            snr_combined = _snr_db(iq_combined)

            all_snr["kiwi"].append(snr_kiwi)
            all_snr["sdr"].append(snr_sdr)
            all_snr["combined"].append(snr_combined)

            improvement = snr_combined - max(snr_kiwi, snr_sdr)

            print(f"  Cycle {cycle:4d}  |  "
                  f"KiwiSDR: {snr_kiwi:+6.1f} dB  "
                  f"SunSDR: {snr_sdr:+6.1f} dB  "
                  f"{method.upper()}: {snr_combined:+6.1f} dB  "
                  f"improvement: {improvement:+5.1f} dB  "
                  f"phase: {np.degrees(phase_offset):+6.1f}°")

            if args.duration:
                time.sleep(max(0.0, args.duration - 1.0))

            if not args.loop and (not n_reps or cycle >= n_reps):
                break

    except KeyboardInterrupt:
        pass
    finally:
        kiwi.close()
        sdr.close()

    # Summary
    if all_snr["kiwi"]:
        print(f"\n  === Summary ({cycle} measurements) ===")
        for name in ("kiwi", "sdr", "combined"):
            vals = np.array(all_snr[name])
            print(f"  {name.upper() if name != 'combined' else method.upper():<12}  "
                  f"mean: {np.mean(vals):+6.1f} dB  "
                  f"min: {np.min(vals):+6.1f} dB  "
                  f"max: {np.max(vals):+6.1f} dB")

        combined = np.array(all_snr["combined"])
        best_single = np.maximum(np.array(all_snr["kiwi"]), np.array(all_snr["sdr"]))
        avg_improvement = float(np.mean(combined - best_single))
        print(f"\n  Average improvement over best single branch: {avg_improvement:+.1f} dB")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Diversity Reception — KiwiSDR + SunSDR2 Pro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Requires two antennas: one connected to the KiwiSDR, one to the SunSDR.
The two signals are combined in software to improve SNR on weak HF signals.

Combining methods:
  egc     Equal-Gain Combining (phase-align and sum)
  mrc     Maximal-Ratio Combining (weight by estimated branch SNR)
  switch  Switched diversity (use the better branch)

Theory predicts EGC gives +3 dB over a single branch when SNR is equal on both.
MRC gives +3 dB when one branch is much better than the other.

Examples:
  python diversity.py --sdr-host 192.168.1.100 --kiwi-host kiwisdr.local --freq 14074000
  python diversity.py --sdr-host 192.168.1.100 --kiwi-host 10.1.0.5 --freq 7074000 --method mrc
  python diversity.py --sdr-host 192.168.1.100 --kiwi-host 10.1.0.5 --freq 14100000 --loop
        """,
    )
    p.add_argument("--sdr-host",   required=True, dest="sdr_host")
    p.add_argument("--sdr-port",   type=int, default=50001, dest="sdr_port")
    p.add_argument("--kiwi-host",  required=True, dest="kiwi_host")
    p.add_argument("--kiwi-port",  type=int, default=8073, dest="kiwi_port")
    p.add_argument("--kiwi-pass",  default="", dest="kiwi_pass",
                   help="KiwiSDR password (default: empty)")
    p.add_argument("--freq",       type=int, required=True,
                   help="Center frequency in Hz")
    p.add_argument("--method",     choices=["egc", "mrc", "switch"], default="egc",
                   help="Diversity combining method (default: egc)")
    p.add_argument("--reps",       type=int, default=10,
                   help="Number of measurement cycles (default: 10; 0 = infinite)")
    p.add_argument("--duration",   type=float, default=2.0,
                   help="Pause between captures in seconds (default: 2)")
    p.add_argument("--loop",       action="store_true",
                   help="Run continuously until Ctrl-C")

    args = p.parse_args()
    if args.loop:
        args.reps = 0
    run(args)


if __name__ == "__main__":
    main()
