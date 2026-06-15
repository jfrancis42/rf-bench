#!/usr/bin/env python3
"""
FM Deviation Measurement — IC-9700 + SSA3032X

Injects a calibrated audio tone into the IC-9700 microphone input and
measures the resulting FM deviation at the transmitter output.

Method: Carson's rule bandwidth from the SSA spectrum trace.
  The SSA3032X firmware does NOT support FM demodulation SCPI commands.
  Instead, this script captures the FM spectrum trace, measures the -26 dB
  bandwidth (which equals 2(Δf + fa) by Carson's rule), and solves for Δf:

      BW_-26dB ≈ 2 × (deviation + audio_freq)
      deviation ≈ BW_-26dB / 2 - audio_freq

This is accurate when the modulation index β = Δf/fa >> 1 (moderate to high
deviation) and the audio tone is a pure sine wave.  For β << 1 (very low
deviation), the -26 dB point may include noise; use a narrow span and slow
sweep in that case.

Connection:
    Audio source → BNC-to-3.5 mm adapter → IC-9700 MIC input
    IC-9700 ANT → [attenuator ≥ 30 dB] → SSA RF In

    WARNING: Always use an attenuator (≥30 dB) between the IC-9700 TX output
    and the SSA input.  IC-9700 may output up to 75 W.

Usage:
    # Basic deviation measurement at 144.200 MHz, 1 kHz tone:
    python fm_deviation.py --freq 144200 --audio-hz 1000

    # Sweep audio level from -40 to 0 dBm:
    python fm_deviation.py --freq 146520 --sweep

    # 70cm:
    python fm_deviation.py --freq 432100

Output:
    fm_dev_<freq>_<timestamp>.json + .png
"""

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.siglent import SSA3000X
from rf_bench.icom    import IC9700
from rf_bench.utils   import format_freq

DEFAULT_SSA_HOST  = None  # Now uses inventory
DEFAULT_RIG_HOST  = "localhost"
DEFAULT_RIG_PORT  = 4532
DEFAULT_ATTEN     = 30.0
DEFAULT_FREQ_KHZ  = 144_200.0
DEFAULT_AUDIO_HZ  = 1_000.0
DEFAULT_AUDIO_DBM = -20.0

NARROW_FM_DEV_KHZ = 5.0
WIDE_FM_DEV_KHZ   = 15.0

# SSA3032X firmware 3.2.2.6.3R2 does not support :CALC:DMOD:FM?
# All measurement uses trace-based Carson's rule method.
_SSA_FM_DEMOD_UNSUPPORTED = True


# ── Carson's rule bandwidth from trace ────────────────────────────────────────

def measure_deviation_from_trace(ssa: SSA3000X, freq_hz: float,
                                  audio_hz: float, span_hz: float = 200_000
                                  ) -> tuple:
    """
    Measure FM deviation using Carson's rule from the SSA spectrum trace.

    Returns (deviation_khz, bw_26db_khz, carrier_dbm).

    Sets up a narrow span around the carrier, captures the trace, finds the
    peak, measures the -26 dB bandwidth, and solves for deviation.
    """
    ssa.setup_band(
        start_hz=int(freq_hz - span_hz / 2),
        stop_hz=int(freq_hz + span_hz / 2),
        rbw_hz=1_000,    # 1 kHz RBW for narrow FM
    )
    ssa.single_sweep()
    trace = ssa.get_trace()
    freqs = ssa.get_frequencies()

    if trace is None or len(trace) == 0:
        return float("nan"), float("nan"), float("nan")

    # Find carrier peak
    peak_idx = int(np.argmax(trace))
    carrier_dbm = float(trace[peak_idx])
    threshold = carrier_dbm - 26.0

    # Find -26 dB crossing on each side of the peak
    left_idx = peak_idx
    while left_idx > 0 and trace[left_idx] > threshold:
        left_idx -= 1

    right_idx = peak_idx
    while right_idx < len(trace) - 1 and trace[right_idx] > threshold:
        right_idx += 1

    if left_idx == 0 or right_idx == len(trace) - 1:
        # -26 dB boundary hit the edge — span is too narrow
        return float("nan"), float("nan"), carrier_dbm

    # Interpolate crossing frequencies
    def interp_cross(i, side):
        if side == "left":
            f1, f2 = freqs[i + 1], freqs[i]
            p1, p2 = trace[i + 1], trace[i]
        else:
            f1, f2 = freqs[i - 1], freqs[i]
            p1, p2 = trace[i - 1], trace[i]
        if p2 == p1:
            return f1
        t = (threshold - p1) / (p2 - p1)
        return f1 + t * (f2 - f1)

    f_left  = interp_cross(left_idx, "left")
    f_right = interp_cross(right_idx, "right")
    bw_hz   = f_right - f_left

    # Carson's rule: BW_-26dB = 2(dev + audio)  →  dev = BW/2 - audio
    dev_hz = bw_hz / 2.0 - audio_hz
    return dev_hz / 1000.0, bw_hz / 1000.0, carrier_dbm


# ── single measurement ────────────────────────────────────────────────────────

def single_point(radio: IC9700, ssa: SSA3000X, freq_hz: float,
                 audio_hz: float, atten_db: float) -> dict:
    radio.set_frequency(freq_hz)
    radio.set_mode("fm")
    radio.set_ptt(True)
    time.sleep(0.5)

    dev_khz, bw_khz, carrier_dbm = measure_deviation_from_trace(
        ssa, freq_hz, audio_hz)

    radio.set_ptt(False)
    time.sleep(0.2)

    spec  = NARROW_FM_DEV_KHZ
    if not math.isnan(dev_khz):
        status = "PASS" if abs(dev_khz) <= spec else "FAIL"
        print(f"   dev={dev_khz:.2f} kHz  BW(-26dB)={bw_khz:.2f} kHz  "
              f"carrier={carrier_dbm:.1f} dBm  [{status} spec ±{spec:.0f} kHz]")
    else:
        print(f"   dev=NaN  (span too narrow? carrier={carrier_dbm:.1f} dBm)")

    return {
        "deviation_khz":  dev_khz,
        "bw_26db_khz":    bw_khz,
        "carrier_dbm":    carrier_dbm,
        "audio_hz":       audio_hz,
        "method":         "carson_26db",
    }


# ── level sweep ───────────────────────────────────────────────────────────────

def sweep(radio: IC9700, ssa: SSA3000X, freq_hz: float,
          audio_hz: float, atten_db: float) -> list:
    """
    Sweep audio input level and measure deviation at each step.
    Requires an SDG1062X connected to the IC-9700 MIC input.
    Without SDG, adjust audio level manually and use --no-sweep.
    """
    # If SDG is available, use it; otherwise just do repeated measurements
    try:
        from rf_bench.siglent import SDG1000X
from rf_bench import connect
        sdg = connect('sdg')
        sdg.set_waveform(1, "SINE")
        sdg.set_frequency(1, audio_hz)
        sdg.set_output(1, True)
        use_sdg = True
    except Exception:
        sdg = None
        use_sdg = False
        print("   (SDG not available — measuring at current audio level)")

    levels  = list(range(-40, 5, 5)) if use_sdg else [DEFAULT_AUDIO_DBM]
    results = []

    for lvl in levels:
        if use_sdg:
            sdg.set_level_dbm(1, lvl)
            time.sleep(0.3)
        row = single_point(radio, ssa, freq_hz, audio_hz, atten_db)
        row["audio_dbm"] = lvl
        results.append(row)

    if use_sdg:
        sdg.set_output(1, False)
        sdg.close()

    return results


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="IC-9700 FM deviation measurement (Carson's rule from SSA trace)")
    p.add_argument("--freq",     type=float, default=DEFAULT_FREQ_KHZ,
                   help="TX frequency in kHz (default %(default)s)")
    p.add_argument("--audio-hz", type=float, default=DEFAULT_AUDIO_HZ, dest="audio_hz",
                   help="Test tone frequency in Hz (default %(default)s)")
    p.add_argument("--atten",    type=float, default=DEFAULT_ATTEN,
                   help="Path attenuation IC-9700 TX → SSA, dB (default %(default)s)")
    p.add_argument("--sweep",    action="store_true",
                   help="Sweep audio input level via SDG1062X")
    p.add_argument("--span-khz", type=float, default=200.0, dest="span_khz",
                   help="SSA span in kHz around carrier (default 200)")
    p.add_argument("--ssa-host", default=DEFAULT_SSA_HOST, dest="ssa_host")
    p.add_argument("--rig-host", default=DEFAULT_RIG_HOST, dest="rig_host")
    p.add_argument("--rig-port", type=int, default=DEFAULT_RIG_PORT, dest="rig_port")
    p.add_argument("--out",      default=None)
    args = p.parse_args()

    freq_hz = args.freq * 1000.0
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem    = args.out or f"fm_dev_{args.freq:.0f}_{ts}"

    print(f"FM Deviation Measurement — {format_freq(freq_hz)}")
    print(f"Method: Carson's rule from SSA -26 dB bandwidth")
    print(f"Audio tone: {args.audio_hz:.0f} Hz  Path atten: {args.atten:.1f} dB")
    print()
    print("⚠  Ensure attenuator is connected between IC-9700 TX and SSA!")
    print()

    radio = IC9700(host=args.rig_host, port=args.rig_port)
    ssa   = connect(args.ssa_host or 'ssa')

    if args.sweep:
        print("── Level Sweep ──")
        rows = sweep(radio, ssa, freq_hz, args.audio_hz, args.atten)
    else:
        print("── Single Measurement ──")
        rows = [single_point(radio, ssa, freq_hz, args.audio_hz, args.atten)]
        rows[0]["audio_dbm"] = DEFAULT_AUDIO_DBM

    radio.close()

    # Plot if sweep
    valid = [r for r in rows if not math.isnan(r["deviation_khz"])]
    if len(valid) > 1:
        fig, ax = plt.subplots(figsize=(8, 5))
        x = [r["audio_dbm"] for r in valid]
        y = [r["deviation_khz"] for r in valid]
        ax.plot(x, y, "o-", color="steelblue")
        ax.axhline(NARROW_FM_DEV_KHZ, color="red", linestyle="--",
                   label=f"Narrow FM limit ±{NARROW_FM_DEV_KHZ:.0f} kHz")
        ax.axhline(-NARROW_FM_DEV_KHZ, color="red", linestyle="--")
        ax.set_xlabel("Audio input level (dBm)")
        ax.set_ylabel("FM deviation (kHz)")
        ax.set_title(f"IC-9700 FM Deviation  {format_freq(freq_hz)}  "
                     f"{args.audio_hz:.0f} Hz")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        png = f"{stem}.png"
        fig.savefig(png, dpi=150)
        plt.close(fig)
        print(f"\nPlot saved: {png}")

    result = {
        "test":        "fm-deviation",
        "freq_hz":     freq_hz,
        "audio_hz":    args.audio_hz,
        "atten_db":    args.atten,
        "method":      "carson_26db",
        "ssa_note":    "SSA3032X fw 3.2.2.6.3R2 has no FM demod SCPI; using trace BW",
        "data":        rows,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }
    jpath = f"{stem}.json"
    with open(jpath, "w") as f:
        json.dump(result, f, indent=2)
    print(f"JSON saved: {jpath}")


if __name__ == "__main__":
    main()
