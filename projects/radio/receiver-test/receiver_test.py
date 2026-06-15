#!/usr/bin/env python3
"""
receiver_test.py — Automated HF receiver test suite

Tests the Icom IC-7300 or Yaesu FT-891 using a Siglent SDG1000X function
generator as a calibrated signal source and (for IMD) a Siglent SDS2000X Plus
oscilloscope for audio analysis.

Usage:
    python receiver_test.py --test smeter-cal --freq 14200 --atten 110
    python receiver_test.py --test mds --freq 14200 --atten 110
    python receiver_test.py --test imd --freq 14200 --atten 110
    python receiver_test.py --test blocking --freq 14200 --atten 110
    python receiver_test.py --test selectivity --freq 14200 --mode cw --atten 110

    # FT-891 (pass --radio ft891):
    python receiver_test.py --radio ft891 --test smeter-cal --freq 14200 --atten 110

See README.md for full documentation.
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import windows as scipy_windows


from rf_bench.siglent import SDG1000X, SDS2000X, DBM_MIN as SDG_DBM_MIN, DBM_MAX as SDG_DBM_MAX  # noqa: E402
from rf_bench.icom    import IC7300                                                               # noqa: E402
from rf_bench.yaesu   import FT891                                                                # noqa: E402
from rf_bench.utils   import (                                                                    # noqa: E402
from rf_bench import connect
    noise_figure_from_mds, thermal_noise_floor, ip3_from_imd,
)

# ---------------------------------------------------------------------------
# Defaults — edit these to match your bench
# ---------------------------------------------------------------------------

SDG_HOST     = "10.1.1.55"   # SDG1062X
SCOPE_HOST   = "10.1.1.58"   # SDS2504X Plus
RIGCTLD_HOST = "localhost"
RIGCTLD_PORT = 4532

SMETER_CAL_FILE = os.path.expanduser("~/.ic7300_smeter_cal.json")  # overridden by main() based on --radio

# Combiner insertion loss (dB per input port) for the resistive 2-way combiner.
# A T-combiner with two 100Ω series resistors and 50Ω shunt loses 6 dB per port.
COMBINER_LOSS_DB = 6.0

# Receiver noise bandwidth by mode (Hz) — used for noise figure calculation.
# These are approximate; actual bandwidth depends on IC-7300 filter settings.
MODE_NOISE_BW = {
    "usb":  2400,
    "lsb":  2400,
    "cw":    500,
    "cwr":   500,
    "am":   6000,
    "fm":  15000,
}

# Default two-tone audio offsets from receiver center frequency (Hz)
# Chosen so both tones and both IMD products fall within the SSB passband (300–2800 Hz).
TONE1_AUDIO_HZ = 1000   # f1 = fc + 1.000 kHz
TONE2_AUDIO_HZ = 1500   # f2 = fc + 1.500 kHz
# IMD products: 2f1−f2 → 500 Hz, 2f2−f1 → 2000 Hz

# AGC settle time after SDG level change (seconds)
AGC_SETTLE_S = 0.6


# ---------------------------------------------------------------------------
# S-meter calibration helpers
# ---------------------------------------------------------------------------

def load_smeter_cal() -> dict | None:
    """Load the S-meter calibration file, or return None if not found."""
    if not os.path.exists(SMETER_CAL_FILE):
        return None
    with open(SMETER_CAL_FILE) as f:
        return json.load(f)


def save_smeter_cal(cal: dict) -> None:
    with open(SMETER_CAL_FILE, "w") as f:
        json.dump(cal, f, indent=2)
    print(f"Saved calibration to {SMETER_CAL_FILE}")


def strength_to_dbm(strength: float, cal: dict | None) -> float:
    """
    Convert a raw Hamlib STRENGTH value to dBm using the calibration table.

    If no calibration is available, returns the raw value with a warning.
    """
    if cal is None:
        return strength   # uncalibrated — use raw

    pts = cal["points"]   # list of [strength, dbm] pairs, sorted by strength
    if not pts:
        return strength

    strengths = [p[0] for p in pts]
    dbm_vals  = [p[1] for p in pts]

    # Linear interpolation / extrapolation
    return float(np.interp(strength, strengths, dbm_vals))


# noise_figure_from_mds, thermal_noise_floor, ip3_from_imd imported from rf_bench.utils


# ---------------------------------------------------------------------------
# Test: S-meter calibration
# ---------------------------------------------------------------------------

def run_smeter_cal(sdg: SDG1000X, rig: IC7300 | FT891, args) -> dict:
    """
    Sweep SDG output level from −20 dBm down toward the noise floor, recording
    Radio STRENGTH vs. input level. Saves calibration to ~/.{radio}_smeter_cal.json.

    Returns the calibration dict.
    """
    freq_hz   = args.freq * 1000
    total_atten = args.atten
    start_dbm   = -20.0    # SDG output at start of sweep
    stop_dbm    = SDG_DBM_MIN + 5   # leave a little headroom
    step_db     = 1.0

    print(f"\n=== S-meter calibration: {args.freq:.1f} kHz, {total_atten} dB attenuation ===")
    print(f"SDG sweep: {start_dbm:.0f} dBm → {stop_dbm:.0f} dBm in {step_db:.1f} dB steps")
    print(f"Input to receiver: {start_dbm - total_atten:.0f} → {stop_dbm - total_atten:.0f} dBm")

    if not args.yes:
        input("\nTune {} to {:.3f} MHz, set mode {}, then press Enter...".format(
            args.radio_name,
            freq_hz / 1e6, args.mode.upper()))

    rig.set_frequency(freq_hz)
    rig.set_mode(args.mode)
    rig.set_agc("slow")

    # Measure undriven noise floor
    sdg.output_off(1)
    time.sleep(AGC_SETTLE_S)
    noise_floor_strength = rig.get_strength_settled(settle_s=0.5, samples=5)
    print(f"\nNoise floor STRENGTH: {noise_floor_strength:.2f}")

    sdg.set_sine(1, freq_hz, start_dbm)
    sdg.output_on(1)

    levels_dbm   = []
    input_dbm    = []
    strengths    = []

    level = start_dbm
    while level >= stop_dbm:
        sdg.set_level(1, level)
        rx_dbm = level - total_atten

        strength = rig.get_strength_settled(settle_s=AGC_SETTLE_S, samples=3)
        print(f"  SDG {level:+6.1f} dBm → RX input {rx_dbm:+7.1f} dBm | STRENGTH {strength:6.2f}")

        levels_dbm.append(level)
        input_dbm.append(rx_dbm)
        strengths.append(strength)

        # Stop early if we've been at noise floor for several steps
        if len(strengths) >= 5 and all(abs(s - noise_floor_strength) < 0.5
                                        for s in strengths[-5:]):
            print("  (Reached noise floor — stopping sweep)")
            break

        level -= step_db

    sdg.output_off(1)

    cal = {
        "freq_khz":            args.freq,
        "mode":                args.mode,
        "atten_db":            total_atten,
        "noise_floor_strength": noise_floor_strength,
        "timestamp":           datetime.now().isoformat(),
        "points":              [[s, d] for s, d in zip(strengths, input_dbm)],
    }
    save_smeter_cal(cal)

    # Plot
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(input_dbm, strengths, "b-o", markersize=4, label="S-meter vs input")
    ax.axhline(noise_floor_strength, color="gray", linestyle="--", label="Noise floor")
    ax.set_xlabel("Input level (dBm)")
    ax.set_ylabel("Hamlib STRENGTH")
    ax.set_title(f"{args.radio_name} S-meter calibration — {args.freq:.1f} kHz {args.mode.upper()}")
    ax.legend()
    ax.grid(True, alpha=0.3)

    prefix   = _make_prefix(args, "smeter-cal")
    fig.savefig(prefix + ".png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    _write_text_report(prefix + ".txt", "S-METER CALIBRATION", [
        ("Frequency",     f"{args.freq:.1f} kHz"),
        ("Mode",          args.mode.upper()),
        ("Attenuation",   f"{total_atten} dB"),
        ("Noise floor",   f"STRENGTH = {noise_floor_strength:.2f}"),
        ("Points",        str(len(points := cal["points"]))),
        ("Min input",     f"{min(p[1] for p in points):.1f} dBm"),
        ("Max input",     f"{max(p[1] for p in points):.1f} dBm"),
    ])

    with open(prefix + ".json", "w") as f:
        json.dump({"test": "smeter-cal", "cal": cal,
                   "input_dbm": input_dbm, "strengths": strengths}, f, indent=2)

    print(f"\nOutputs: {prefix}.txt / .png / .json")
    return cal


# ---------------------------------------------------------------------------
# Test: MDS
# ---------------------------------------------------------------------------

def run_mds(sdg: SDG1000X, rig: IC7300 | FT891, args) -> dict:
    """
    Measure Minimum Discernible Signal and derive noise figure.
    """
    freq_hz     = args.freq * 1000
    total_atten = args.atten
    cal         = load_smeter_cal()
    if cal is None:
        print("WARNING: No S-meter calibration file found. Run --test smeter-cal first.")
        print(f"         (Looking for {SMETER_CAL_FILE})")

    print(f"\n=== MDS test: {args.freq:.1f} kHz {args.mode.upper()}, {total_atten} dB attenuation ===")

    if not args.yes:
        input("Tune {} to {:.3f} MHz, set mode {}, then press Enter...".format(
            args.radio_name, freq_hz / 1e6, args.mode.upper()))

    rig.set_frequency(freq_hz)
    rig.set_mode(args.mode)
    rig.set_agc("slow")

    # Baseline noise floor
    sdg.output_off(1)
    time.sleep(AGC_SETTLE_S)
    noise_strength = rig.get_strength_settled(settle_s=0.5, samples=5)
    noise_dbm      = strength_to_dbm(noise_strength, cal)
    print(f"Noise floor: STRENGTH = {noise_strength:.2f} ({noise_dbm:.1f} dBm equiv)")

    # Start at a level clearly above noise floor and step down
    start_dbm = -30.0
    sdg.set_sine(1, freq_hz, start_dbm)
    sdg.output_on(1)

    levels   = []
    s_raw    = []
    s_dbm    = []
    mds_dbm  = None

    for level in np.arange(start_dbm, SDG_DBM_MIN + 3, -1.0):
        rx_dbm = level - total_atten
        sdg.set_level(1, level)
        strength = rig.get_strength_settled(settle_s=AGC_SETTLE_S, samples=3)
        rx_equiv = strength_to_dbm(strength, cal)

        levels.append(rx_dbm)
        s_raw.append(strength)
        s_dbm.append(rx_equiv)
        print(f"  RX input {rx_dbm:+7.1f} dBm | STRENGTH {strength:6.2f} ({rx_equiv:.1f} dBm)")

        # MDS: first level where signal is within 3 dB of noise floor
        if mds_dbm is None and abs(strength - noise_strength) < 0.5:
            mds_dbm = rx_dbm
            print(f"  *** MDS reached at {mds_dbm:.1f} dBm ***")
            break

    sdg.output_off(1)

    bw_hz   = MODE_NOISE_BW.get(args.mode.lower(), 2400)
    nf_db   = noise_figure_from_mds(mds_dbm, bw_hz) if mds_dbm is not None else float("nan")
    ktb_dbm = thermal_noise_floor(bw_hz)

    print(f"\nResults:")
    print(f"  MDS:            {mds_dbm:.1f} dBm" if mds_dbm else "  MDS:            not reached (add more attenuation)")
    print(f"  Noise figure:   {nf_db:.1f} dB  (kTB = {ktb_dbm:.1f} dBm in {bw_hz} Hz)")

    # Plot
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(levels, s_dbm, "b-o", markersize=4, label="Signal level")
    ax.axhline(noise_dbm, color="gray", linestyle="--", label=f"Noise floor ({noise_dbm:.1f} dBm)")
    if mds_dbm:
        ax.axvline(mds_dbm, color="red", linestyle=":", label=f"MDS = {mds_dbm:.1f} dBm")
    ax.set_xlabel("Input level (dBm)")
    ax.set_ylabel("Receiver level (dBm, calibrated)")
    ax.set_title(f"{args.radio_name} MDS — {args.freq:.1f} kHz {args.mode.upper()}")
    ax.legend()
    ax.grid(True, alpha=0.3)

    prefix = _make_prefix(args, "mds")
    fig.savefig(prefix + ".png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    result = {
        "test":        "mds",
        "freq_khz":    args.freq,
        "mode":        args.mode,
        "atten_db":    total_atten,
        "mds_dbm":     mds_dbm,
        "noise_fig_db": nf_db,
        "bw_hz":       bw_hz,
        "ktb_dbm":     ktb_dbm,
        "noise_strength": noise_strength,
        "levels_dbm":  levels,
        "strengths":   s_raw,
        "timestamp":   datetime.now().isoformat(),
    }

    _write_text_report(prefix + ".txt", "MDS / NOISE FIGURE", [
        ("Frequency",      f"{args.freq:.1f} kHz"),
        ("Mode",           args.mode.upper()),
        ("Attenuation",    f"{total_atten} dB"),
        ("MDS",            f"{mds_dbm:.1f} dBm" if mds_dbm else "not reached"),
        ("Noise BW",       f"{bw_hz} Hz"),
        ("kTB",            f"{ktb_dbm:.1f} dBm"),
        ("Noise figure",   f"{nf_db:.1f} dB" if not math.isnan(nf_db) else "n/a"),
    ])

    with open(prefix + ".json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nOutputs: {prefix}.txt / .png / .json")
    return result


# ---------------------------------------------------------------------------
# Test: Two-tone IMD / IP3
# ---------------------------------------------------------------------------

def run_imd(sdg: SDG1000X, scope: SDS2000X | None, rig: IC7300 | FT891 | None, args) -> dict:
    """
    Two-tone IMD test. Injects dual-channel SDG tones through a resistive combiner,
    captures audio on the scope, FFTs it, and computes IP3.

    The resistive combiner adds COMBINER_LOSS_DB per port, so the effective input
    level at the receiver is: SDG_level − total_atten − COMBINER_LOSS_DB
    """
    if scope is None:
        print("ERROR: IMD test requires the scope (--scope). Use --no-scope to skip.")
        return {}

    freq_hz     = args.freq * 1000
    total_atten = args.atten
    # Effective attenuation includes combiner insertion loss
    eff_atten   = total_atten + COMBINER_LOSS_DB

    # Two input tones (RF frequencies)
    f1_hz = freq_hz + TONE1_AUDIO_HZ
    f2_hz = freq_hz + TONE2_AUDIO_HZ
    # Expected audio frequencies
    audio_f1   = TONE1_AUDIO_HZ
    audio_f2   = TONE2_AUDIO_HZ
    audio_imd1 = 2 * TONE1_AUDIO_HZ - TONE2_AUDIO_HZ   # 500 Hz
    audio_imd2 = 2 * TONE2_AUDIO_HZ - TONE1_AUDIO_HZ   # 2000 Hz

    print(f"\n=== Two-tone IMD / IP3: {args.freq:.1f} kHz {args.mode.upper()} ===")
    print(f"  Tone 1: {f1_hz/1000:.3f} kHz → audio {audio_f1} Hz")
    print(f"  Tone 2: {f2_hz/1000:.3f} kHz → audio {audio_f2} Hz")
    print(f"  Expected IMD: audio {audio_imd1} Hz and {audio_imd2} Hz")
    print(f"  Effective attenuation: {eff_atten} dB ({total_atten} fixed + {COMBINER_LOSS_DB} combiner)")

    if not args.yes:
        input(f"\nTune {args.radio_name} to {freq_hz/1e6:.3f} MHz USB, connect scope CH{args.scope_ch} "
              f"to {args.radio_name} audio output, then press Enter...")

    if rig:
        rig.set_frequency(freq_hz)
        rig.set_mode("usb")
        rig.set_agc("slow")

    # Set a fixed test level (SDG output)
    test_level_dbm = -10.0   # SDG output; adjust if IMD products are not visible
    rx_input_dbm   = test_level_dbm - eff_atten

    sdg.set_sine(1, f1_hz, test_level_dbm)
    sdg.set_sine(2, f2_hz, test_level_dbm)
    sdg.output_on(1)
    sdg.output_on(2)
    time.sleep(1.0)   # let AGC settle

    print(f"\nCapturing audio (SDG {test_level_dbm:+.0f} dBm, RX input ≈ {rx_input_dbm:.1f} dBm)...")
    voltages, fs = scope.capture_audio(
        channel=args.scope_ch,
        duration_s=args.audio_duration,
    )
    sdg.output_off_all()

    print(f"  Captured {len(voltages)} samples at {fs:.0f} Sa/s "
          f"({len(voltages)/fs:.2f} s)")

    if len(voltages) < 256:
        print("ERROR: Too few samples captured. Check scope connection and timebase.")
        return {}

    # FFT analysis
    fft_result = _audio_fft(voltages, fs)
    freqs      = fft_result["freqs"]
    magnitude  = fft_result["magnitude_db"]

    # Find peak amplitudes at the expected audio frequencies
    a_f1   = _peak_near(freqs, magnitude, audio_f1,   window_hz=50)
    a_f2   = _peak_near(freqs, magnitude, audio_f2,   window_hz=50)
    a_imd1 = _peak_near(freqs, magnitude, audio_imd1, window_hz=50)
    a_imd2 = _peak_near(freqs, magnitude, audio_imd2, window_hz=50)

    print(f"\nAudio FFT results (dBV rms):")
    print(f"  Tone 1  ({audio_f1:5d} Hz): {a_f1:+.1f} dBV")
    print(f"  Tone 2  ({audio_f2:5d} Hz): {a_f2:+.1f} dBV")
    print(f"  IMD low ({audio_imd1:5d} Hz): {a_imd1:+.1f} dBV")
    print(f"  IMD high({audio_imd2:5d} Hz): {a_imd2:+.1f} dBV")

    # IP3 from each IMD product (average)
    ip3_low  = ip3_from_imd(a_f1, a_imd1, p_in_dbm=rx_input_dbm)
    ip3_high = ip3_from_imd(a_f2, a_imd2, p_in_dbm=rx_input_dbm)
    ip3      = (ip3_low + ip3_high) / 2

    # IMD ratios (signal level − IMD product level in audio)
    imd_ratio_low  = a_f1  - a_imd1
    imd_ratio_high = a_f2  - a_imd2

    print(f"\nIMD ratios:  low {imd_ratio_low:.1f} dBc  |  high {imd_ratio_high:.1f} dBc")
    print(f"IIP3:        low {ip3_low:.1f}  |  high {ip3_high:.1f}  |  avg {ip3:.1f} dBm")

    # Plot
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(freqs / 1000, magnitude, "b-", linewidth=0.8, label="Audio spectrum")
    for f, label, col in [
        (audio_f1,   f"f₁ {a_f1:.0f} dBV",   "green"),
        (audio_f2,   f"f₂ {a_f2:.0f} dBV",   "blue"),
        (audio_imd1, f"IMD₋ {a_imd1:.0f} dBV", "red"),
        (audio_imd2, f"IMD₊ {a_imd2:.0f} dBV", "orange"),
    ]:
        ax.axvline(f / 1000, color=col, linestyle="--", alpha=0.7, label=label)
    ax.set_xlabel("Audio frequency (kHz)")
    ax.set_ylabel("Level (dBV rms)")
    ax.set_xlim(0, 5)
    ax.set_title(f"{args.radio_name} Two-tone IMD — {args.freq:.1f} kHz | IIP3 = {ip3:.1f} dBm")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    prefix = _make_prefix(args, "imd")
    fig.savefig(prefix + ".png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    result = {
        "test":              "imd",
        "freq_khz":          args.freq,
        "mode":              "usb",
        "atten_db":          total_atten,
        "combiner_loss_db":  COMBINER_LOSS_DB,
        "eff_atten_db":      eff_atten,
        "sdg_level_dbm":     test_level_dbm,
        "rx_input_dbm":      rx_input_dbm,
        "tone1_audio_hz":    audio_f1,
        "tone2_audio_hz":    audio_f2,
        "imd1_audio_hz":     audio_imd1,
        "imd2_audio_hz":     audio_imd2,
        "a_f1_dbv":          a_f1,
        "a_f2_dbv":          a_f2,
        "a_imd1_dbv":        a_imd1,
        "a_imd2_dbv":        a_imd2,
        "imd_ratio_low_dbc": imd_ratio_low,
        "imd_ratio_high_dbc": imd_ratio_high,
        "iip3_dbm":          ip3,
        "sample_rate_hz":    fs,
        "n_samples":         len(voltages),
        "timestamp":         datetime.now().isoformat(),
    }

    _write_text_report(prefix + ".txt", "TWO-TONE IMD / IP3", [
        ("Frequency",      f"{args.freq:.1f} kHz"),
        ("Tone 1",         f"{audio_f1} Hz audio → {a_f1:.1f} dBV"),
        ("Tone 2",         f"{audio_f2} Hz audio → {a_f2:.1f} dBV"),
        ("IMD low",        f"{audio_imd1} Hz audio → {a_imd1:.1f} dBV ({imd_ratio_low:.1f} dBc)"),
        ("IMD high",       f"{audio_imd2} Hz audio → {a_imd2:.1f} dBV ({imd_ratio_high:.1f} dBc)"),
        ("RX input level", f"{rx_input_dbm:.1f} dBm"),
        ("IIP3",           f"{ip3:.1f} dBm (avg of two products)"),
    ])

    with open(prefix + ".json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nOutputs: {prefix}.txt / .png / .json")
    return result


# ---------------------------------------------------------------------------
# Test: Blocking dynamic range
# ---------------------------------------------------------------------------

def run_blocking(sdg: SDG1000X, rig: IC7300 | FT891, args) -> dict:
    """
    Blocking dynamic range: step up an off-frequency interferer (CH1) while
    monitoring a weak wanted signal (CH2) on the S-meter. Find the interferer
    level that reduces the wanted signal by 1 dB.
    """
    freq_hz     = args.freq * 1000
    total_atten = args.atten
    eff_atten   = total_atten + COMBINER_LOSS_DB
    cal         = load_smeter_cal()

    # Wanted signal: 5 kHz offset from test frequency, fixed at a level ~20 dB above MDS
    wanted_offset_hz   = 5_000
    wanted_freq_hz     = freq_hz + wanted_offset_hz
    wanted_level_dbm   = -30.0   # SDG output; adjust if needed

    # Interferer: 20 kHz offset, stepped from low to high
    interferer_offset_hz = 20_000
    interferer_freq_hz   = freq_hz + interferer_offset_hz
    interferer_start_dbm = -40.0
    interferer_step_db   = 2.0

    print(f"\n=== Blocking dynamic range: {args.freq:.1f} kHz {args.mode.upper()} ===")
    print(f"  Wanted:     {wanted_freq_hz/1000:.3f} kHz, {wanted_level_dbm:+.0f} dBm SDG "
          f"(RX: {wanted_level_dbm - eff_atten:.0f} dBm)")
    print(f"  Interferer: {interferer_freq_hz/1000:.3f} kHz, swept {interferer_start_dbm:+.0f} upward")

    if not args.yes:
        input(f"Tune {args.radio_name} to {wanted_freq_hz/1e6:.3f} MHz {args.mode.upper()}, press Enter...")

    if rig:
        rig.set_frequency(wanted_freq_hz)
        rig.set_mode(args.mode)
        rig.set_agc("slow")

    # Baseline: wanted signal only
    sdg.set_sine(1, interferer_freq_hz, interferer_start_dbm - 20)  # interferer off effectively
    sdg.set_sine(2, wanted_freq_hz, wanted_level_dbm)
    sdg.output_on(2)
    time.sleep(AGC_SETTLE_S)
    baseline_strength = rig.get_strength_settled(settle_s=0.5, samples=5)
    baseline_dbm      = strength_to_dbm(baseline_strength, cal)
    print(f"\n  Baseline (wanted only): STRENGTH = {baseline_strength:.2f} ({baseline_dbm:.1f} dBm)")

    sdg.output_on(1)

    interferer_levels = []
    wanted_strengths  = []
    blocking_dbm      = None

    for level in np.arange(interferer_start_dbm, SDG_DBM_MAX - 1, interferer_step_db):
        rx_interferer = level - eff_atten
        sdg.set_level(1, level)
        strength = rig.get_strength_settled(settle_s=AGC_SETTLE_S, samples=3)
        wanted_rx = strength_to_dbm(strength, cal)
        delta     = wanted_rx - baseline_dbm

        print(f"  Interferer {rx_interferer:+7.1f} dBm RX | wanted STRENGTH {strength:.2f} "
              f"({wanted_rx:.1f} dBm, Δ{delta:+.1f} dB)")

        interferer_levels.append(rx_interferer)
        wanted_strengths.append(wanted_rx)

        if blocking_dbm is None and delta < -1.0:
            blocking_dbm = rx_interferer
            print(f"  *** 1 dB desensitization at interferer = {blocking_dbm:.1f} dBm ***")

    sdg.output_off_all()

    wanted_rx_dbm = wanted_level_dbm - eff_atten
    blocking_dr   = (blocking_dbm - wanted_rx_dbm) if blocking_dbm else float("nan")

    print(f"\nResults:")
    print(f"  Wanted signal:          {wanted_rx_dbm:.1f} dBm")
    print(f"  1 dB blocking point:    {blocking_dbm:.1f} dBm" if blocking_dbm else "  1 dB blocking point: not reached")
    print(f"  Blocking dynamic range: {blocking_dr:.0f} dB" if not math.isnan(blocking_dr) else "  Blocking DR: n/a")

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(interferer_levels, wanted_strengths, "b-o", markersize=4)
    ax.axhline(baseline_dbm,       color="green",  linestyle="--", label=f"Baseline ({baseline_dbm:.1f} dBm)")
    ax.axhline(baseline_dbm - 1.0, color="orange", linestyle="--", label="−1 dB threshold")
    if blocking_dbm:
        ax.axvline(blocking_dbm, color="red", linestyle=":", label=f"Blocking = {blocking_dbm:.1f} dBm")
    ax.set_xlabel("Interferer input level (dBm)")
    ax.set_ylabel("Wanted signal level (dBm, calibrated)")
    ax.set_title(f"{args.radio_name} Blocking — {args.freq:.1f} kHz | BDR = {blocking_dr:.0f} dB")
    ax.legend()
    ax.grid(True, alpha=0.3)

    prefix = _make_prefix(args, "blocking")
    fig.savefig(prefix + ".png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    result = {
        "test":              "blocking",
        "freq_khz":          args.freq,
        "mode":              args.mode,
        "atten_db":          total_atten,
        "eff_atten_db":      eff_atten,
        "wanted_rx_dbm":     wanted_rx_dbm,
        "blocking_dbm":      blocking_dbm,
        "blocking_dr_db":    blocking_dr,
        "interferer_levels": interferer_levels,
        "wanted_levels":     wanted_strengths,
        "timestamp":         datetime.now().isoformat(),
    }

    _write_text_report(prefix + ".txt", "BLOCKING DYNAMIC RANGE", [
        ("Frequency",         f"{args.freq:.1f} kHz"),
        ("Mode",              args.mode.upper()),
        ("Wanted signal",     f"{wanted_rx_dbm:.1f} dBm"),
        ("1 dB block point",  f"{blocking_dbm:.1f} dBm" if blocking_dbm else "not reached"),
        ("Blocking DR",       f"{blocking_dr:.0f} dB" if not math.isnan(blocking_dr) else "n/a"),
    ])

    with open(prefix + ".json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nOutputs: {prefix}.txt / .png / .json")
    return result


# ---------------------------------------------------------------------------
# Test: Selectivity / IF filter shape
# ---------------------------------------------------------------------------

def run_selectivity(sdg: SDG1000X, rig: IC7300 | FT891, args) -> dict:
    """
    Sweep SDG frequency across and beyond the receiver passband at constant
    level, recording S-meter vs. offset to map the IF filter shape.
    """
    freq_hz     = args.freq * 1000
    total_atten = args.atten
    cal         = load_smeter_cal()
    level_dbm   = -30.0

    # Sweep ±10 kHz around center in 100 Hz steps (for a 500 Hz CW filter)
    # For SSB use ±5 kHz; for CW ±2 kHz; auto-select based on mode
    half_span_hz = {"usb": 5000, "lsb": 5000, "cw": 2000, "cwr": 2000}.get(
        args.mode.lower(), 5000)
    step_hz = 50 if args.mode.lower() in ("cw", "cwr") else 100

    start_hz  = freq_hz - half_span_hz
    stop_hz   = freq_hz + half_span_hz

    print(f"\n=== Selectivity: {args.freq:.1f} kHz {args.mode.upper()}, "
          f"sweep ±{half_span_hz/1000:.1f} kHz in {step_hz} Hz steps ===")

    if not args.yes:
        input(f"Tune {args.radio_name} to {freq_hz/1e6:.3f} MHz {args.mode.upper()}, press Enter...")

    if rig:
        rig.set_mode(args.mode)
        rig.set_agc("slow")

    sdg.set_sine(1, freq_hz, level_dbm)
    sdg.output_on(1)

    offsets   = []
    strengths = []
    levels    = []

    for f in np.arange(start_hz, stop_hz + step_hz, step_hz):
        sdg.set_sine(1, float(f), level_dbm)
        offset_hz = f - freq_hz
        time.sleep(0.15)   # SDG settle; AGC settle handled by averaging
        strength = rig.get_strength_settled(settle_s=0.2, samples=2)
        rx_dbm   = strength_to_dbm(strength, cal)

        offsets.append(offset_hz)
        strengths.append(strength)
        levels.append(rx_dbm)

    sdg.output_off(1)

    # Find passband edges (−3 dB and −60 dB points relative to peak)
    peak_dbm  = max(levels)
    peak_idx  = levels.index(peak_dbm)
    peak_freq = offsets[peak_idx]

    def find_bw(threshold_db):
        threshold = peak_dbm - threshold_db
        lo = hi = None
        for i in range(peak_idx, 0, -1):
            if levels[i] <= threshold:
                lo = offsets[i]
                break
        for i in range(peak_idx, len(levels)):
            if levels[i] <= threshold:
                hi = offsets[i]
                break
        if lo is not None and hi is not None:
            return hi - lo
        return None

    bw3db  = find_bw(3)
    bw60db = find_bw(60)
    shape_factor = (bw60db / bw3db) if (bw3db and bw60db) else float("nan")

    print(f"\nResults:")
    print(f"  Peak offset:   {peak_freq:.0f} Hz")
    print(f"  3 dB BW:       {bw3db:.0f} Hz"  if bw3db  else "  3 dB BW:  not measurable")
    print(f"  60 dB BW:      {bw60db:.0f} Hz" if bw60db else "  60 dB BW: not measurable")
    print(f"  Shape factor:  {shape_factor:.2f}" if not math.isnan(shape_factor) else "  Shape factor: n/a")

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot([o / 1000 for o in offsets], [l - peak_dbm for l in levels],
            "b-", linewidth=1.2)
    ax.axhline(-3,  color="orange", linestyle="--", alpha=0.7, label="−3 dB")
    ax.axhline(-60, color="red",    linestyle="--", alpha=0.7, label="−60 dB")
    ax.set_xlabel("Frequency offset (kHz)")
    ax.set_ylabel("Relative level (dB)")
    ax.set_title(f"{args.radio_name} Selectivity — {args.freq:.1f} kHz {args.mode.upper()} "
                 f"| 3 dB BW = {bw3db:.0f} Hz" if bw3db else "")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_ylim(-80, 5)

    prefix = _make_prefix(args, "selectivity")
    fig.savefig(prefix + ".png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    result = {
        "test":          "selectivity",
        "freq_khz":      args.freq,
        "mode":          args.mode,
        "atten_db":      total_atten,
        "peak_offset_hz": peak_freq,
        "bw_3db_hz":     bw3db,
        "bw_60db_hz":    bw60db,
        "shape_factor":  shape_factor,
        "offsets_hz":    [float(o) for o in offsets],
        "levels_dbm":    levels,
        "timestamp":     datetime.now().isoformat(),
    }

    _write_text_report(prefix + ".txt", "IF SELECTIVITY", [
        ("Frequency",    f"{args.freq:.1f} kHz"),
        ("Mode",         args.mode.upper()),
        ("Peak offset",  f"{peak_freq:.0f} Hz"),
        ("3 dB BW",      f"{bw3db:.0f} Hz" if bw3db else "n/a"),
        ("60 dB BW",     f"{bw60db:.0f} Hz" if bw60db else "n/a"),
        ("Shape factor", f"{shape_factor:.2f}" if not math.isnan(shape_factor) else "n/a"),
    ])

    with open(prefix + ".json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nOutputs: {prefix}.txt / .png / .json")
    return result


# ---------------------------------------------------------------------------
# FFT helpers
# ---------------------------------------------------------------------------

def _audio_fft(voltages: np.ndarray, sample_rate: float) -> dict:
    """
    Compute a windowed FFT of a voltage waveform.

    Returns a dict with:
        freqs:        frequency array (Hz)
        magnitude_db: one-sided power spectrum in dBV rms
    """
    n = len(voltages)
    window = scipy_windows.hann(n)
    # Normalize window so amplitude is preserved
    windowed  = voltages * window
    fft_vals  = np.fft.rfft(windowed)
    freqs     = np.fft.rfftfreq(n, d=1.0 / sample_rate)

    # Convert to dBV rms (single-sided, corrected for window and two-sided → one-sided)
    # Factor of 2/n for single-sided, √2 cancels for rms, window correction = 1/mean(window)
    window_correction = n / np.sum(window)
    magnitude_rms = np.abs(fft_vals) * window_correction * (2.0 / n)
    magnitude_rms[0] /= 2   # DC bin not doubled
    magnitude_db = 20.0 * np.log10(np.maximum(magnitude_rms, 1e-12))

    return {"freqs": freqs, "magnitude_db": magnitude_db}


def _peak_near(freqs: np.ndarray, magnitude_db: np.ndarray,
               target_hz: float, window_hz: float = 50) -> float:
    """Return the maximum dBV value within ±window_hz of target_hz."""
    mask = np.abs(freqs - target_hz) <= window_hz
    if not np.any(mask):
        return float("-inf")
    return float(np.max(magnitude_db[mask]))


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _make_prefix(args, test_name: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = args.output or os.path.join(
        os.getcwd(),
        f"receiver_{test_name}_{int(args.freq)}kHz_{ts}"
    )
    return base


def _write_text_report(path: str, title: str, rows: list[tuple[str, str]]) -> None:
    width = 60
    lines = [
        "=" * width,
        f"  {title}",
        f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * width,
        "",
    ]
    for key, val in rows:
        lines.append(f"  {key:<22} {val}")
    lines += ["", "=" * width]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Argument parsing and main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Automated HF receiver test suite (IC-7300 / FT-891)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Tests:
  smeter-cal    S-meter calibration (run this first)
  mds           Minimum Discernible Signal + noise figure
  imd           Two-tone IMD / IP3 (requires scope on audio output)
  blocking      Blocking dynamic range
  selectivity   IF filter passband shape

Example:
  python receiver_test.py --test smeter-cal mds --freq 14200 --atten 110
        """
    )
    p.add_argument("--radio", choices=["ic7300", "ft891"], default="ic7300",
                   help="Radio model to use (default: ic7300)")
    p.add_argument("--test", nargs="+", required=True,
                   choices=["smeter-cal", "mds", "imd", "blocking", "selectivity"],
                   help="Test(s) to run")
    p.add_argument("--sdg",      default=SDG_HOST,
                   help=f"SDG1000X IP address [default: {SDG_HOST}]")
    p.add_argument("--scope",    default=SCOPE_HOST,
                   help=f"SDS2000X Plus IP address [default: {SCOPE_HOST}]")
    p.add_argument("--rigctld",  default=f"{RIGCTLD_HOST}:{RIGCTLD_PORT}",
                   help=f"rigctld host:port [default: {RIGCTLD_HOST}:{RIGCTLD_PORT}]")
    p.add_argument("--freq",     type=float, default=14200.0,
                   help="Test frequency in kHz [default: 14200]")
    p.add_argument("--mode",     default="usb",
                   choices=["usb", "lsb", "cw", "cwr", "am", "fm"],
                   help="Receiver mode [default: usb]")
    p.add_argument("--atten",    type=float, default=110.0,
                   help="Total fixed attenuation in dB [default: 110]")
    p.add_argument("--scope-ch", type=int, default=1, dest="scope_ch",
                   help="Scope channel for audio input [default: 1]")
    p.add_argument("--audio-duration", type=float, default=2.0, dest="audio_duration",
                   help="Audio capture duration for IMD FFT in seconds [default: 2.0]")
    p.add_argument("--no-rig",   action="store_true",
                   help="Skip CAT/Hamlib (only IMD test works without rig)")
    p.add_argument("--no-scope", action="store_true",
                   help="Skip scope connection (IMD test unavailable)")
    p.add_argument("--output",   default=None,
                   help="Output file prefix (default: auto-timestamped)")
    p.add_argument("--yes",      action="store_true",
                   help="Skip confirmation prompts")
    return p.parse_args()


def main():
    args = parse_args()

    # Set radio display name and calibration file path based on --radio
    global SMETER_CAL_FILE
    if args.radio == "ft891":
        args.radio_name = "FT-891"
        SMETER_CAL_FILE = os.path.expanduser("~/.ft891_smeter_cal.json")
    else:
        args.radio_name = "IC-7300"
        SMETER_CAL_FILE = os.path.expanduser("~/.ic7300_smeter_cal.json")

    # Parse rigctld address
    rig_addr = args.rigctld.split(":")
    rig_host = rig_addr[0]
    rig_port = int(rig_addr[1]) if len(rig_addr) > 1 else RIGCTLD_PORT

    # Connect to instruments
    print(f"Connecting to SDG1000X at {args.sdg}...", end=" ", flush=True)
    try:
        sdg = connect(args.sdg or 'sdg')
        print(f"OK  [{sdg.identify()[:40]}]")
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)

    scope = None
    if not args.no_scope and "imd" in args.test:
        print(f"Connecting to SDS2000X Plus at {args.scope}...", end=" ", flush=True)
        try:
            scope = connect(args.scope or 'sds')
            print(f"OK  [{scope.identify()[:40]}]")
        except Exception as e:
            print(f"FAILED: {e}")
            if "imd" in args.test:
                print("IMD test requires the scope. Use --no-scope to skip.")
                sdg.close()
                sys.exit(1)

    rig = None
    if not args.no_rig:
        print(f"Connecting to rigctld at {rig_host}:{rig_port}...", end=" ", flush=True)
        try:
            if args.radio == "ft891":
                rig = FT891(rig_host, rig_port)
            else:
                rig = IC7300(rig_host, rig_port)
            freq = rig.get_frequency()
            print(f"OK  [current freq: {freq/1000:.1f} kHz]")
        except Exception as e:
            print(f"FAILED: {e}")
            if args.radio == "ft891":
                print("Hint: start rigctld first:  rigctld -m 1036 -r /dev/ttyUSB0 -s 38400 &")
            else:
                print("Hint: start rigctld first:  rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 &")
            sdg.close()
            if scope:
                scope.close()
            sys.exit(1)

    # Run requested tests in order
    try:
        for test in args.test:
            if test == "smeter-cal":
                run_smeter_cal(sdg, rig, args)
            elif test == "mds":
                run_mds(sdg, rig, args)
            elif test == "imd":
                run_imd(sdg, scope, rig, args)
            elif test == "blocking":
                run_blocking(sdg, rig, args)
            elif test == "selectivity":
                run_selectivity(sdg, rig, args)
    finally:
        sdg.output_off_all()
        sdg.close()
        if scope:
            scope.close()
        if rig:
            rig.close()


if __name__ == "__main__":
    main()
