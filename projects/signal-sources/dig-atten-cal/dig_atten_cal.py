#!/usr/bin/env python3
"""
rf-bench-dig-atten-cal — Digital attenuator calibration tool

Programs a PE4302 or HMC624A digital step attenuator via Bus Pirate SPI and
measures actual attenuation at each step using the Siglent SSA3032X Plus.
Generates a correction table (JSON) and plots insertion loss vs. frequency.

Usage:
    python3 dig_atten_cal.py --chip pe4302 --bp /dev/ttyUSB1
    python3 dig_atten_cal.py --chip hmc624a --bp /dev/ttyUSB1 \
        --start 1e6 --stop 3e9 --steps-freq 30 --freqs 100e6,500e6,1e9
    python3 dig_atten_cal.py --plot dig_atten_cal_pe4302_20260527.json
"""

import argparse
import json
import sys
import os
import time
from datetime import datetime
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))

from rf_bench.buspirate import BusPirate
from rf_bench.siglent   import SSA3000X
from rf_bench.utils     import format_freq, format_freq_short, nearest_rbw

# ---------------------------------------------------------------------------
# Chip definitions
# ---------------------------------------------------------------------------

CHIPS = {
    "pe4302": {
        "description": "PE4302 6-bit 0–31.5 dB (0.5 dB steps)",
        "bits":        6,
        "step_db":     0.5,
        "max_db":      31.5,
        "spi_cpol":    0,
        "spi_cpha":    0,
        "spi_bytes":   2,          # 2-byte parallel or serial; use serial (D0 first)
        "freq_max_hz": 4e9,
    },
    "hmc624a": {
        "description": "HMC624A 6-bit 0–31.5 dB (0.5 dB steps)",
        "bits":        6,
        "step_db":     0.5,
        "max_db":      31.5,
        "spi_cpol":    0,
        "spi_cpha":    0,
        "spi_bytes":   1,          # 1 byte: bits [5:0] = attenuation code
        "freq_max_hz": 13e9,
    },
}

# Default calibration frequencies (Hz)
DEFAULT_CAL_FREQS = [
    10e6, 50e6, 100e6, 200e6, 500e6,
    1e9, 1.5e9, 2e9, 2.5e9, 3e9,
]

# ---------------------------------------------------------------------------
# Attenuator programming
# ---------------------------------------------------------------------------

def _pe4302_word(atten_db: float) -> list:
    """
    PE4302 serial interface: 7-bit word (LE = latch enable, D5:D0 = attenuation).
    Attenuation code = round(atten_db / 0.5) as 6-bit value.
    Sent as 2 bytes: [0x00, code] — first byte clocks in the data, second triggers latch.
    Actually the PE4302 latches on the rising edge of LE (CS rising edge).
    We send 1 byte: MSB first, bits 6:0 = (LE=0, D5:D0).
    For Bus Pirate SPI the CS high at end of transfer acts as LE rising edge.
    """
    code = int(round(atten_db / 0.5)) & 0x3F
    # 7-bit word: bit6=LE(0), bits5:0=code. Pad to full byte.
    return [code & 0x3F]


def _hmc624a_word(atten_db: float) -> list:
    """
    HMC624A: 1-byte SPI word. bits[5:0] = attenuation in 0.5 dB steps.
    Bit 5 = 16 dB, Bit 4 = 8 dB, Bit 3 = 4 dB,
    Bit 2 = 2 dB, Bit 1 = 1 dB, Bit 0 = 0.5 dB.
    """
    code = int(round(atten_db / 0.5)) & 0x3F
    return [code]


def set_attenuation(bp: BusPirate, chip: str, atten_db: float):
    """Program the digital attenuator to atten_db (rounded to nearest step)."""
    chip_info = CHIPS[chip]
    step = chip_info["step_db"]
    atten_db = round(round(atten_db / step) * step, 4)  # snap to grid

    if chip == "pe4302":
        data = _pe4302_word(atten_db)
    elif chip == "hmc624a":
        data = _hmc624a_word(atten_db)
    else:
        raise ValueError(f"Unknown chip: {chip}")

    bp.spi_transfer(data)


# ---------------------------------------------------------------------------
# SSA measurement
# ---------------------------------------------------------------------------

def ssa_measure_power(ssa: SSA3000X, freq_hz: float, ref_dbm: float = -10.0) -> float:
    """
    Measure carrier power at freq_hz with a narrow span.
    ref_dbm: expected input level for reference level setting.
    Returns power in dBm.
    """
    span = 1e6
    rbw = nearest_rbw(span / 200)
    ssa.set_span(freq_hz - span/2, freq_hz + span/2)
    ssa.set_rbw(rbw)
    ssa.set_ref_level(ref_dbm + 5)
    time.sleep(0.4)
    power, _ = ssa.peak_search()
    return power


def ssa_measure_thru(ssa: SSA3000X, freq_hz: float) -> float:
    """
    Measure through power with attenuator set to 0 dB.
    Returns power in dBm as the reference level.
    """
    return ssa_measure_power(ssa, freq_hz, ref_dbm=0.0)


# ---------------------------------------------------------------------------
# Calibration sweep
# ---------------------------------------------------------------------------

def calibrate(bp: BusPirate, ssa: SSA3000X, chip: str,
              cal_freqs: list, source_freq_hz: float | None = None,
              source_dbm: float = -10.0) -> dict:
    """
    Sweep all attenuator steps at each calibration frequency.

    If source_freq_hz is provided, the SDG (or fixed source) is assumed to
    track that single frequency and all cal_freqs should equal it.
    Otherwise, the SSA tracking generator is used.

    Returns dict:
        {
          "chip": ...,
          "freqs_hz": [...],
          "steps_db": [...],
          "measured": {   # measured_db[step_idx][freq_idx]
              "nominal": [[...], ...],
              "actual":  [[...], ...],
              "error":   [[...], ...],
          }
        }
    """
    chip_info = CHIPS[chip]
    step_db   = chip_info["step_db"]
    max_db    = chip_info["max_db"]
    steps     = [round(i * step_db, 4)
                 for i in range(int(max_db / step_db) + 1)]   # 0, 0.5, 1.0, ...

    print(f"Calibrating {chip.upper()} — {len(steps)} steps × {len(cal_freqs)} frequencies")

    # ---- configure SPI ----
    bp.spi_configure(
        speed_hz=100_000,
        cpol=chip_info["spi_cpol"],
        cpha=chip_info["spi_cpha"],
        output_pushpull=True,
    )

    nominal_matrix = []
    actual_matrix  = []
    error_matrix   = []

    # ---- reference pass at 0 dB ----
    print("  Measuring 0 dB reference...")
    set_attenuation(bp, chip, 0.0)
    time.sleep(0.05)
    ref_power = {}
    for freq in cal_freqs:
        ref_power[freq] = ssa_measure_thru(ssa, freq)
        print(f"    {format_freq_short(freq)}: {ref_power[freq]:.1f} dBm (ref)")

    # ---- sweep steps ----
    for step in steps:
        actual_row  = []
        nominal_row = []
        error_row   = []

        set_attenuation(bp, chip, step)
        time.sleep(0.08)   # settling time

        for freq in cal_freqs:
            pwr = ssa_measure_power(ssa, freq, ref_dbm=ref_power[freq] - step)
            actual_atten  = ref_power[freq] - pwr   # positive = more attenuation
            error         = actual_atten - step

            actual_row.append(round(actual_atten, 3))
            nominal_row.append(step)
            error_row.append(round(error, 3))

        print(f"  {step:5.1f} dB: errors {min(error_row):+.2f} to {max(error_row):+.2f} dB")
        nominal_matrix.append(nominal_row)
        actual_matrix.append(actual_row)
        error_matrix.append(error_row)

    return {
        "chip":       chip,
        "timestamp":  datetime.now().isoformat(),
        "freqs_hz":   cal_freqs,
        "steps_db":   steps,
        "ref_dbm":    {str(f): v for f, v in ref_power.items()},
        "nominal":    nominal_matrix,
        "actual":     actual_matrix,
        "error":      error_matrix,
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_results(data: dict, output_base: str):
    freqs   = np.array(data["freqs_hz"])
    steps   = np.array(data["steps_db"])
    actual  = np.array(data["actual"])    # [step_idx][freq_idx]
    error   = np.array(data["error"])
    chip    = data["chip"]

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"{chip.upper()} Digital Attenuator Calibration — {data['timestamp'][:10]}",
                 fontsize=14)

    freq_labels = [format_freq_short(f) for f in freqs]
    colors = plt.cm.viridis(np.linspace(0, 1, len(freqs)))

    # --- Panel 1: Actual attenuation vs. nominal ---
    ax = axes[0, 0]
    for i, (freq, color) in enumerate(zip(freqs, colors)):
        ax.plot(steps, actual[:, i], marker='.', markersize=4,
                label=format_freq_short(freq), color=color)
    ax.plot(steps, steps, 'k--', linewidth=1, label="Ideal", zorder=5)
    ax.set_xlabel("Nominal attenuation (dB)")
    ax.set_ylabel("Actual attenuation (dB)")
    ax.set_title("Actual vs. Nominal")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.4)

    # --- Panel 2: Error vs. attenuation step ---
    ax = axes[0, 1]
    for i, (freq, color) in enumerate(zip(freqs, colors)):
        ax.plot(steps, error[:, i], marker='.', markersize=4,
                label=format_freq_short(freq), color=color)
    ax.axhline(0, color='k', linestyle='--', linewidth=1)
    ax.set_xlabel("Nominal attenuation (dB)")
    ax.set_ylabel("Error (dB)")
    ax.set_title("Calibration Error vs. Step")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.4)

    # --- Panel 3: Error heatmap (step × frequency) ---
    ax = axes[1, 0]
    im = ax.imshow(error, aspect='auto', origin='lower',
                   extent=[0, len(freqs)-1, 0, len(steps)-1],
                   cmap='RdYlGn', vmin=-0.5, vmax=0.5)
    ax.set_xticks(range(len(freqs)))
    ax.set_xticklabels(freq_labels, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel("Step index")
    ax.set_title("Error heatmap (dB)")
    fig.colorbar(im, ax=ax, label="Error (dB)")

    # --- Panel 4: RMS error vs. frequency ---
    ax = axes[1, 1]
    rms_by_freq = np.sqrt(np.mean(error**2, axis=0))
    max_by_freq = np.max(np.abs(error), axis=0)
    ax.bar(range(len(freqs)), rms_by_freq, label="RMS error", alpha=0.7)
    ax.bar(range(len(freqs)), max_by_freq, label="Max |error|", alpha=0.4)
    ax.set_xticks(range(len(freqs)))
    ax.set_xticklabels(freq_labels, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel("Error (dB)")
    ax.set_title("Error vs. Frequency")
    ax.legend()
    ax.grid(True, alpha=0.4, axis='y')

    plt.tight_layout()
    png_path = output_base + ".png"
    plt.savefig(png_path, dpi=150)
    plt.close()
    print(f"Plot saved: {png_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Digital attenuator calibration via Bus Pirate + SSA3032X Plus"
    )
    parser.add_argument("--chip",   default="pe4302",
                        choices=list(CHIPS.keys()),
                        help="Attenuator chip (default: pe4302)")
    parser.add_argument("--bp",     default="/dev/ttyUSB1",
                        help="Bus Pirate serial port (default: /dev/ttyUSB1)")
    parser.add_argument("--ssa",    default="10.1.1.60",
                        help="SSA IP address (default: 10.1.1.60)")
    parser.add_argument("--freqs",  default=None,
                        help="Comma-separated list of calibration frequencies in Hz "
                             "(default: built-in 10-point list)")
    parser.add_argument("--output", default=None,
                        help="Output file base name (without extension)")
    parser.add_argument("--plot",   default=None,
                        help="Re-plot from a saved JSON file (no hardware needed)")
    args = parser.parse_args()

    # ---- Re-plot mode ----
    if args.plot:
        with open(args.plot) as f:
            data = json.load(f)
        base = os.path.splitext(args.plot)[0]
        plot_results(data, base)
        return

    # ---- Parse calibration frequencies ----
    if args.freqs:
        cal_freqs = [float(x.strip()) for x in args.freqs.split(",")]
    else:
        chip_info = CHIPS[args.chip]
        cal_freqs = [f for f in DEFAULT_CAL_FREQS if f <= chip_info["freq_max_hz"]]

    # ---- Output base ----
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = args.output or f"dig_atten_cal_{args.chip}_{ts}"

    print(f"Digital Attenuator Calibration")
    print(f"  Chip : {args.chip.upper()} — {CHIPS[args.chip]['description']}")
    print(f"  Port : {args.bp}")
    print(f"  SSA  : {args.ssa}")
    print(f"  Freqs: {', '.join(format_freq_short(f) for f in cal_freqs)}")
    print()

    with BusPirate(args.bp) as bp:
        with SSA3000X(args.ssa) as ssa:
            data = calibrate(bp, ssa, args.chip, cal_freqs)

    # ---- Save JSON ----
    json_path = output_base + ".json"
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Data saved: {json_path}")

    # ---- Plot ----
    plot_results(data, output_base)

    # ---- Summary ----
    error = np.array(data["error"])
    print()
    print("Summary:")
    print(f"  Overall RMS error : {np.sqrt(np.mean(error**2)):.3f} dB")
    print(f"  Max absolute error: {np.max(np.abs(error)):.3f} dB")
    print(f"  Worst step        : {data['steps_db'][int(np.argmax(np.max(np.abs(error), axis=1)))]} dB")


if __name__ == "__main__":
    main()
