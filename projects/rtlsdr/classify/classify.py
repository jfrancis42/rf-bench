#!/usr/bin/env -S python3 -u
"""
Protocol Hunter / Signal Classifier

Scans a frequency range for signal activity, captures burst IQ, and classifies
each signal by modulation type (AM/OOK, FM, FSK, PSK/QPSK, CW/pulsed).
Optionally commands the SSA to lock on a detected signal for precision
amplitude and harmonic measurement.

The RTL-SDR finds signals quickly across a wide range; the SSA measures them
accurately.  Together they extend the EMI finder (#16) workflow: RTL-SDR
classifies by modulation signature, SSA confirms level and harmonics.

Usage:
    python classify.py --freq 433.92e6 --bw 2.4e6
    python classify.py --freq 433.92e6 --bw 2.4e6 --ssa 10.1.1.60
    python classify.py --scan 300e6 1000e6 --step 2e6    # coarse survey
    python classify.py --freq 144.39e6 --bw 200e3 --threshold -30
"""

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from rf_bench.rtlsdr import RTLSDR, RTLSDRError

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE  = 2_400_000
DEFAULT_GAIN         = "auto"
DEFAULT_THRESHOLD_DB = -20.0   # dB above noise floor
DEFAULT_BLOCK_SIZE   = 65_536
SSA_HOST             = "10.1.1.60"
SSA_PORT             = 5025

_running = True

def _sigint(_sig, _frame):
    global _running
    _running = False

signal.signal(signal.SIGINT, _sigint)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _instantaneous(iq: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (amplitude, inst_freq, inst_phase) for a complex IQ block."""
    amp   = np.abs(iq)
    phase = np.unwrap(np.angle(iq))
    freq  = np.diff(phase) / (2 * np.pi)   # normalised: 1.0 = sample_rate
    return amp, freq, phase


def _variance_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """Ratio of variances.  > 1 means b has more variance than a."""
    va = float(np.var(a))
    vb = float(np.var(b))
    if va < 1e-20:
        return float("inf") if vb > 1e-20 else 1.0
    return vb / va


def classify_burst(iq: np.ndarray) -> dict:
    """
    Classify a burst of IQ samples.

    Returns dict with keys:
        modulation  — 'AM/OOK', 'FM', 'FSK', 'PSK', 'CW/carrier', 'pulsed', 'noise'
        confidence  — 0.0–1.0
        bw_hz       — estimated signal bandwidth at -20 dB (relative to sample_rate)
        symbol_rate — estimated symbol rate (Hz), or None
        duty_cycle  — fraction of time signal is 'on' (0.0–1.0)
        notes       — human-readable description
    """
    if len(iq) < 64:
        return {"modulation": "noise", "confidence": 0.0,
                "bw_hz": 0, "symbol_rate": None, "duty_cycle": 0.0, "notes": "too short"}

    amp, inst_freq, inst_phase = _instantaneous(iq)

    # Amplitude statistics
    amp_mean = float(np.mean(amp))
    amp_var  = float(np.var(amp / (amp_mean + 1e-10)))
    am_index = amp_var   # high = AM/OOK

    # Instantaneous frequency statistics
    freq_var  = float(np.var(inst_freq))
    freq_std  = float(np.std(inst_freq))

    # Phase statistics
    phase_diff = np.diff(inst_phase) % (2 * np.pi)
    phase_var  = float(np.var(phase_diff))

    # Duty cycle (envelope above 30% of peak)
    on_fraction = float(np.mean(amp > 0.3 * np.max(amp)))

    # Estimate bandwidth from FFT
    spec = np.abs(np.fft.fftshift(np.fft.fft(iq, n=2048))) ** 2
    spec_db = 10 * np.log10(spec / (np.max(spec) + 1e-30) + 1e-20)
    above_20db = np.sum(spec_db > -20)
    bw_fraction = above_20db / len(spec_db)   # fraction of total BW

    # Classification heuristics
    notes = []
    modulation = "unknown"
    confidence = 0.0

    # Pulsed / radar / transponder: low duty cycle, impulsive amplitude
    if on_fraction < 0.15 and am_index > 0.3:
        modulation  = "pulsed"
        confidence  = 0.7
        notes.append(f"duty={on_fraction:.2f} am_idx={am_index:.2f}")

    # AM / OOK: high amplitude variance, relatively low freq variance
    elif am_index > 0.15 and freq_std < 0.1:
        if on_fraction < 0.6:
            modulation = "AM/OOK"
        else:
            modulation = "AM"
        confidence = min(1.0, am_index * 3)
        notes.append(f"am_idx={am_index:.2f} freq_std={freq_std:.4f}")

    # FM / NFM: constant envelope (low AM), high freq variance
    elif am_index < 0.05 and freq_std > 0.005 and freq_std < 0.15:
        if freq_std < 0.02:
            modulation = "NFM"
            notes.append("narrowband FM")
        else:
            modulation = "FM"
        confidence = min(1.0, (0.1 - am_index) * 20)
        notes.append(f"freq_std={freq_std:.4f}")

    # FSK: constant envelope, discrete frequency jumps (multi-modal inst_freq)
    elif am_index < 0.08 and freq_std > 0.003:
        # Check for bimodal frequency distribution (2-FSK)
        hist, _ = np.histogram(inst_freq, bins=32)
        peaks_above = np.sum(hist > np.max(hist) * 0.3)
        if 2 <= peaks_above <= 4:
            modulation  = "FSK"
            confidence  = 0.75
            # Symbol rate estimate from autocorrelation zero-crossing
            ac = np.correlate(inst_freq - np.mean(inst_freq), inst_freq - np.mean(inst_freq), mode='full')
            ac = ac[len(ac)//2:]
            zeros = np.where(np.diff(np.sign(ac)))[0]
            if len(zeros) > 0:
                symbol_period = zeros[0]
            else:
                symbol_period = None
            notes.append(f"freq_modes={peaks_above}")
        else:
            modulation = "FSK"
            confidence = 0.5
            symbol_period = None
        notes.append(f"freq_std={freq_std:.4f}")

    # PSK / QPSK: constant envelope, discrete phase steps
    elif am_index < 0.05 and phase_var > 0.5 and freq_std < 0.05:
        modulation  = "PSK"
        confidence  = 0.65
        notes.append(f"phase_var={phase_var:.2f}")

    # CW carrier: very low amplitude and frequency variance
    elif am_index < 0.02 and freq_std < 0.002 and on_fraction > 0.8:
        modulation  = "CW/carrier"
        confidence  = 0.9
        notes.append("unmodulated carrier")

    else:
        modulation  = "unknown"
        confidence  = 0.2
        notes.append(f"am={am_index:.3f} freq_std={freq_std:.4f} phase_var={phase_var:.3f}")

    # Estimate symbol rate for digital modes
    symbol_rate = None
    if modulation in ("FSK", "PSK", "AM/OOK"):
        # BW-based estimate: symbol_rate ≈ bw at -20 dB for most digital modes
        symbol_rate = bw_fraction * DEFAULT_SAMPLE_RATE

    return {
        "modulation":  modulation,
        "confidence":  round(confidence, 2),
        "bw_hz":       round(bw_fraction * DEFAULT_SAMPLE_RATE),
        "symbol_rate": round(symbol_rate) if symbol_rate else None,
        "duty_cycle":  round(on_fraction, 2),
        "notes":       " | ".join(notes),
    }


# ---------------------------------------------------------------------------
# SSA handoff
# ---------------------------------------------------------------------------

def ssa_lock_on(freq_hz: float, ssa_host: str) -> None:
    """Command the SSA to narrow-span around a detected signal."""
    import socket
    span_hz = 2_000_000   # ±1 MHz span for initial lock
    try:
        with socket.create_connection((ssa_host, SSA_PORT), timeout=2) as s:
            cmds = [
                f":SENS:FREQ:CENT {freq_hz:.0f}",
                f":SENS:FREQ:SPAN {span_hz}",
                ":SENS:SWE:MODE SINGLE",
                ":INIT:IMM",
            ]
            for c in cmds:
                s.sendall(f"{c}\n".encode())
                time.sleep(0.05)
        print(f"  → SSA locked on {freq_hz/1e6:.3f} MHz  span={span_hz/1e6:.1f} MHz")
    except OSError as exc:
        print(f"  → SSA unreachable ({exc})")


# ---------------------------------------------------------------------------
# Peak detection
# ---------------------------------------------------------------------------

def find_peaks(freq_hz: np.ndarray, power_db: np.ndarray,
               threshold_db: float) -> list[dict]:
    """Find frequency peaks above noise_floor + threshold_db."""
    noise_floor = float(np.median(power_db))
    cutoff      = noise_floor + threshold_db
    above       = power_db > cutoff

    peaks = []
    in_pk = False
    start = 0
    for i in range(len(above)):
        if above[i] and not in_pk:
            start = i
            in_pk = True
        elif not above[i] and in_pk:
            mid = int(np.argmax(power_db[start:i]) + start)
            peaks.append({
                "freq_hz":  float(freq_hz[mid]),
                "power_db": float(power_db[mid]),
                "width_hz": float(freq_hz[i] - freq_hz[start]) if i > start else 0,
            })
            in_pk = False
    if in_pk:
        mid = int(np.argmax(power_db[start:]) + start)
        peaks.append({
            "freq_hz":  float(freq_hz[mid]),
            "power_db": float(power_db[mid]),
            "width_hz": 0.0,
        })

    return sorted(peaks, key=lambda p: p["power_db"], reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="RTL-SDR signal classifier")
    ap.add_argument("--freq",      type=float,
                    help="Center frequency in Hz (e.g. 433.92e6)")
    ap.add_argument("--bw",        type=float, default=DEFAULT_SAMPLE_RATE,
                    help="Sample rate in S/s (default: 2.4e6)")
    ap.add_argument("--gain",      default=DEFAULT_GAIN,
                    help="Gain in dB or 'auto' (default: auto)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_DB,
                    help="Signal threshold dB above noise floor (default: %(default)s)")
    ap.add_argument("--scan",      nargs=2, type=float, metavar=("START_HZ", "STOP_HZ"),
                    help="Scan a range (e.g. --scan 300e6 1000e6)")
    ap.add_argument("--step",      type=float, default=2_000_000,
                    help="Step size in scan mode in Hz (default: 2e6)")
    ap.add_argument("--ssa",       metavar="HOST",
                    help="SSA host IP; when given, lock on each detected signal")
    ap.add_argument("--dwell",     type=float, default=1.0,
                    help="Seconds to monitor each frequency (default: 1.0)")
    ap.add_argument("--serial",    help="RTL-SDR serial number")
    ap.add_argument("--json",      action="store_true",
                    help="Output results as JSON lines")
    args = ap.parse_args()

    if not args.freq and not args.scan:
        ap.error("Specify --freq for single-channel or --scan START STOP for range scan")

    gain = args.gain if args.gain == "auto" else float(args.gain)

    try:
        with RTLSDR(serial=args.serial) as sdr:
            sdr.set_sample_rate(int(args.bw))
            sdr.set_gain(gain)

            if args.freq:
                # Single-frequency continuous monitor
                sdr.set_center_freq(int(args.freq))
                print(f"Monitoring {args.freq/1e6:.3f} MHz  threshold=noise+{args.threshold:.0f} dB")
                print("Ctrl-C to stop.\n")

                while _running:
                    iq = sdr.capture_iq(DEFAULT_BLOCK_SIZE)
                    freq_ax, psd = sdr.power_spectrum(iq, rbw_hz=args.bw / 512)
                    peaks = find_peaks(freq_ax, psd, args.threshold)

                    for pk in peaks[:5]:
                        # Tune to the peak and capture a burst for classification
                        sdr.set_center_freq(int(pk["freq_hz"]))
                        burst = sdr.capture_iq(DEFAULT_BLOCK_SIZE * 2)
                        result = classify_burst(burst)
                        sdr.set_center_freq(int(args.freq))

                        ts = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
                        row = {
                            "time":        ts,
                            "freq_mhz":    round(pk["freq_hz"] / 1e6, 4),
                            "power_db":    round(pk["power_db"], 1),
                            **result,
                        }

                        if args.json:
                            print(json.dumps(row))
                        else:
                            print(f"[{ts}] {pk['freq_hz']/1e6:.4f} MHz  "
                                  f"{result['modulation']:12s}  "
                                  f"conf={result['confidence']:.2f}  "
                                  f"bw={result['bw_hz']/1e3:.0f} kHz  "
                                  f"{result['notes']}")

                        if args.ssa and result["confidence"] > 0.5:
                            ssa_lock_on(pk["freq_hz"], args.ssa)

                    time.sleep(args.dwell)

            else:
                # Range scan
                start_hz, stop_hz = args.scan
                freqs = np.arange(start_hz, stop_hz, args.step)
                print(f"Scanning {start_hz/1e6:.0f}–{stop_hz/1e6:.0f} MHz  "
                      f"step={args.step/1e6:.1f} MHz  ({len(freqs)} steps)")
                print("Ctrl-C to stop.\n")

                while _running:
                    scan_results = []
                    for freq in freqs:
                        if not _running:
                            break
                        sdr.set_center_freq(int(freq))
                        signals = sdr.scan_activity(threshold_db=args.threshold,
                                                    num_samples=DEFAULT_BLOCK_SIZE)
                        for sig in signals:
                            # Capture burst for classification
                            sdr.set_center_freq(int(sig["freq_hz"]))
                            burst  = sdr.capture_iq(DEFAULT_BLOCK_SIZE)
                            result = classify_burst(burst)
                            row    = {
                                "freq_mhz":  round(sig["freq_hz"] / 1e6, 3),
                                "power_db":  round(sig["power_db"], 1),
                                **result,
                            }
                            scan_results.append(row)

                            if args.json:
                                print(json.dumps(row))
                            else:
                                print(f"  {sig['freq_hz']/1e6:.3f} MHz  "
                                      f"{result['modulation']:12s}  "
                                      f"conf={result['confidence']:.2f}  "
                                      f"bw={result['bw_hz']/1e3:.0f} kHz")

                            if args.ssa and result["confidence"] > 0.5:
                                ssa_lock_on(sig["freq_hz"], args.ssa)

                    if scan_results:
                        print(f"\n--- Scan complete: {len(scan_results)} signal(s) found ---\n")
                    time.sleep(args.dwell)

    except RTLSDRError as exc:
        print(f"RTL-SDR error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
