#!/usr/bin/env python3
"""
Mixer Characterizer — Siglent SDG + SSA

Characterizes RF mixers: conversion loss, LO/RF port isolation,
1 dB compression point, and spurious products.

Physical setup:
  SDG CH1 (LO) ──────────────────────── LO port of mixer
  SDG CH2 (RF) ──[external attenuator]── RF port of mixer
                                          IF port of mixer ─── SSA RF In

Usage:
  python mixer_characterizer.py                          # default sweep
  python mixer_characterizer.py --p1db                   # 1 dB compression sweep
  python mixer_characterizer.py --isolation              # port isolation measurements
  python mixer_characterizer.py --lo-freq 100000 --lo-level 7
"""

import argparse
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Siglent shared drivers
# ---------------------------------------------------------------------------

from rf_bench.siglent import SSA3000X, SDG1000X                             # noqa: E402
from rf_bench.utils import (                                                  # noqa: E402
    format_freq, format_freq_short, dbm_to_vpp, vpp_to_dbm,
    nearest_rbw, intermod_products,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SDG_HOST    = "10.1.1.55"
DEFAULT_SSA_HOST    = "10.1.1.60"

DEFAULT_LO_FREQ_KHZ = 10_000      # 10 MHz
DEFAULT_LO_LEVEL    = 7.0         # dBm — typical double-balanced mixer drive
DEFAULT_RF_START_KHZ = 1_000      # 1 MHz
DEFAULT_RF_STOP_KHZ  = 20_000     # 20 MHz
DEFAULT_RF_POINTS   = 51
DEFAULT_RF_LEVEL    = -20.0       # dBm — small-signal RF
DEFAULT_IF_BW_KHZ   = 10         # kHz span around IF to search for peak
DEFAULT_P1DB_FREQ_KHZ = 1_000
DEFAULT_P1DB_START  = -30.0      # dBm sweep start for 1 dB compression
DEFAULT_P1DB_STOP   = 5.0        # dBm sweep stop
DEFAULT_P1DB_STEPS  = 36

# SDG CH1 = LO, CH2 = RF
CH_LO = 1
CH_RF = 2

# SSA sweep points for IF peak measurement
IF_SWEEP_POINTS = 201

# How many dB around the IF peak to set as SSA span
IF_PEAK_SPAN_FACTOR = 0.02       # ±1% of IF frequency


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------

def setup_if_measurement(ssa: SSA3000X, if_hz: float, bw_hz: float) -> int:
    """
    Configure SSA for a narrow-span IF peak measurement.

    Sets span to ±bw_hz/2 around if_hz (minimum 10 kHz each side).
    Returns the RBW set (Hz).
    """
    half_span = max(bw_hz / 2.0, 10_000)
    start_hz  = max(9_000, int(if_hz - half_span))
    stop_hz   = int(if_hz + half_span)
    rbw = ssa.setup_band(start_hz, stop_hz, IF_SWEEP_POINTS)
    return rbw


def measure_if_peak(ssa: SSA3000X, if_hz: float, bw_hz: float) -> float:
    """
    Measure peak power (dBm) at the IF output in a narrow window around if_hz.

    Returns the peak dBm value from the trace.
    """
    setup_if_measurement(ssa, if_hz, bw_hz)
    ssa.single_sweep()
    trace = ssa.get_trace()
    if len(trace) == 0:
        return -999.0
    return float(np.max(trace))


def measure_peak_wide(ssa: SSA3000X, center_hz: float, span_hz: float) -> float:
    """Measure peak power in a wide span centered at center_hz."""
    half_span = span_hz / 2
    start_hz  = max(9_000, int(center_hz - half_span))
    stop_hz   = int(center_hz + half_span)
    ssa.setup_band(start_hz, stop_hz, IF_SWEEP_POINTS)
    ssa.single_sweep()
    trace = ssa.get_trace()
    if len(trace) == 0:
        return -999.0
    return float(np.max(trace))


# ---------------------------------------------------------------------------
# Conversion loss sweep
# ---------------------------------------------------------------------------

def run_conversion_sweep(
    ssa: SSA3000X,
    sdg: SDG1000X,
    lo_hz: float,
    rf_freqs_hz: np.ndarray,
    rf_level_dbm: float,
    lo_level_dbm: float,
    if_bw_hz: float,
) -> list[dict]:
    """
    Sweep RF frequency; measure IF output power at each point.

    Returns list of dicts with keys:
        rf_hz, if_hz, if_dbm, conversion_loss_db
    """
    print(f"\n[CONVERSION SWEEP]  LO={format_freq_short(lo_hz)} @ {lo_level_dbm:+.1f} dBm  "
          f"RF level={rf_level_dbm:+.1f} dBm  ({len(rf_freqs_hz)} points)")
    print(f"  {'RF Freq':>14}  {'IF Freq':>14}  {'IF Power':>10}  {'Conv Loss':>10}")
    print(f"  {'-'*14}  {'-'*14}  {'-'*10}  {'-'*10}")

    # LO on CH1 — stays fixed throughout
    sdg.set_sine(CH_LO, lo_hz, lo_level_dbm)
    sdg.output_on(CH_LO)
    time.sleep(0.1)

    # RF on CH2
    sdg.set_sine(CH_RF, rf_freqs_hz[0], rf_level_dbm)
    sdg.output_on(CH_RF)
    time.sleep(0.1)

    results = []
    for rf_hz in rf_freqs_hz:
        if_hz = abs(lo_hz - rf_hz)

        # Skip IF < 9 kHz (below SSA range) or IF = LO (RF = 0)
        if if_hz < 9_000:
            print(f"  {format_freq_short(rf_hz):>14}  {format_freq_short(if_hz):>14}  "
                  f"  [SKIP — IF below SSA min]")
            continue

        sdg.set_frequency(CH_RF, rf_hz)
        time.sleep(0.05)

        if_dbm = measure_if_peak(ssa, if_hz, if_bw_hz)
        conv_loss = rf_level_dbm - if_dbm   # positive = loss

        results.append({
            "rf_hz":           rf_hz,
            "if_hz":           if_hz,
            "if_dbm":          if_dbm,
            "conversion_loss_db": conv_loss,
        })

        print(f"  {format_freq_short(rf_hz):>14}  {format_freq_short(if_hz):>14}  "
              f"  {if_dbm:>8.1f} dBm  {conv_loss:>8.2f} dB")

    return results


# ---------------------------------------------------------------------------
# 1 dB compression sweep
# ---------------------------------------------------------------------------

def run_p1db(
    ssa: SSA3000X,
    sdg: SDG1000X,
    lo_hz: float,
    rf_hz: float,
    lo_level_dbm: float,
    if_bw_hz: float,
    rf_start_dbm: float = DEFAULT_P1DB_START,
    rf_stop_dbm: float  = DEFAULT_P1DB_STOP,
    rf_steps: int       = DEFAULT_P1DB_STEPS,
) -> dict:
    """
    Sweep RF input power at a fixed frequency to find the IF 1 dB
    compression point.

    Returns a dict with keys:
        rf_powers, if_powers, p1db_in, p1db_out, p1db_found
    """
    if_hz = abs(lo_hz - rf_hz)
    print(f"\n[P1dB SWEEP]  RF={format_freq_short(rf_hz)}  LO={format_freq_short(lo_hz)}  "
          f"IF={format_freq_short(if_hz)}")
    print(f"  RF sweep: {rf_start_dbm:+.1f} to {rf_stop_dbm:+.1f} dBm  ({rf_steps} steps)")
    print(f"  {'RF In':>10}  {'IF Out':>10}  {'Conv Loss':>10}")
    print(f"  {'-'*10}  {'-'*10}  {'-'*10}")

    sdg.set_sine(CH_LO, lo_hz, lo_level_dbm)
    sdg.output_on(CH_LO)
    sdg.set_sine(CH_RF, rf_hz, rf_start_dbm)
    sdg.output_on(CH_RF)
    time.sleep(0.2)

    rf_powers  = np.linspace(rf_start_dbm, rf_stop_dbm, rf_steps)
    if_powers  = []

    for rf_dbm in rf_powers:
        sdg.set_level(CH_RF, rf_dbm)
        time.sleep(0.05)
        if_dbm = measure_if_peak(ssa, if_hz, if_bw_hz)
        if_powers.append(if_dbm)
        conv_loss = rf_dbm - if_dbm
        print(f"  {rf_dbm:>+8.1f} dBm  {if_dbm:>+8.1f} dBm  {conv_loss:>8.2f} dB")

    if_powers = np.array(if_powers)

    # Fit linear response to the lowest 1/3 of sweep points for the
    # "ideal" conversion loss reference line
    n_linear    = max(3, len(rf_powers) // 3)
    coeffs      = np.polyfit(rf_powers[:n_linear], if_powers[:n_linear], 1)
    ideal_slope = coeffs[0]
    ideal_line  = np.polyval(coeffs, rf_powers)

    # 1 dB compression: first point where if_powers < ideal_line - 1 dB
    p1db_in  = None
    p1db_out = None
    p1db_found = False
    for i, (rf_p, if_p, ideal) in enumerate(zip(rf_powers, if_powers, ideal_line)):
        if if_p < ideal - 1.0:
            # Interpolate more precisely between i-1 and i
            if i > 0:
                frac = (1.0 - (if_powers[i-1] - ideal_line[i-1])) / (
                    (if_powers[i-1] - ideal_line[i-1]) - (if_p - ideal)
                )
                p1db_in  = rf_powers[i-1] + frac * (rf_p - rf_powers[i-1])
                p1db_out = np.interp(p1db_in, rf_powers, if_powers)
            else:
                p1db_in  = rf_p
                p1db_out = if_p
            p1db_found = True
            break

    if p1db_found:
        print(f"\n  1 dB compression: RF_in = {p1db_in:+.2f} dBm,  IF_out = {p1db_out:+.2f} dBm")
    else:
        print(f"\n  1 dB compression: NOT FOUND in sweep range "
              f"({rf_start_dbm:+.1f} to {rf_stop_dbm:+.1f} dBm)")

    return {
        "rf_hz":       rf_hz,
        "if_hz":       if_hz,
        "rf_powers":   rf_powers,
        "if_powers":   if_powers,
        "ideal_line":  ideal_line,
        "p1db_in":     p1db_in,
        "p1db_out":    p1db_out,
        "p1db_found":  p1db_found,
    }


# ---------------------------------------------------------------------------
# Port isolation measurements
# ---------------------------------------------------------------------------

def run_isolation(
    ssa: SSA3000X,
    sdg: SDG1000X,
    lo_hz: float,
    rf_hz: float,
    lo_level_dbm: float,
    rf_level_dbm: float,
    if_bw_hz: float,
) -> dict:
    """
    Measure LO→IF and RF→IF isolation.

    LO→IF isolation: LO on, RF off → measure LO leakage at IF port at LO freq
    RF→IF isolation: RF on, LO off → measure RF leakage at IF port at RF freq

    Returns dict with lo_isolation_db, rf_isolation_db.
    """
    if_hz = abs(lo_hz - rf_hz)
    print(f"\n[ISOLATION]  LO={format_freq_short(lo_hz)} @ {lo_level_dbm:+.1f} dBm  "
          f"RF={format_freq_short(rf_hz)} @ {rf_level_dbm:+.1f} dBm")

    # --- LO to IF isolation ---
    print("  Measuring LO→IF isolation (LO on, RF off) ...", end=" ", flush=True)
    sdg.set_sine(CH_LO, lo_hz, lo_level_dbm)
    sdg.output_on(CH_LO)
    sdg.output_off(CH_RF)
    time.sleep(0.2)

    lo_at_if = measure_peak_wide(ssa, lo_hz, max(if_bw_hz, 100_000))
    lo_isolation = lo_level_dbm - lo_at_if   # positive = good isolation
    print(f"LO at IF port = {lo_at_if:.1f} dBm  (isolation = {lo_isolation:.1f} dB)")

    # --- RF to IF isolation ---
    print("  Measuring RF→IF isolation (RF on, LO off) ...", end=" ", flush=True)
    sdg.set_sine(CH_RF, rf_hz, rf_level_dbm)
    sdg.output_on(CH_RF)
    sdg.output_off(CH_LO)
    time.sleep(0.2)

    rf_at_if = measure_peak_wide(ssa, rf_hz, max(if_bw_hz, 100_000))
    rf_isolation = rf_level_dbm - rf_at_if
    print(f"RF at IF port = {rf_at_if:.1f} dBm  (isolation = {rf_isolation:.1f} dB)")

    return {
        "lo_hz":          lo_hz,
        "rf_hz":          rf_hz,
        "if_hz":          if_hz,
        "lo_level_dbm":   lo_level_dbm,
        "rf_level_dbm":   rf_level_dbm,
        "lo_at_if_dbm":   lo_at_if,
        "rf_at_if_dbm":   rf_at_if,
        "lo_isolation_db": lo_isolation,
        "rf_isolation_db": rf_isolation,
    }


# ---------------------------------------------------------------------------
# Spurious products measurement
# ---------------------------------------------------------------------------

def run_spurious(
    ssa: SSA3000X,
    sdg: SDG1000X,
    lo_hz: float,
    rf_hz: float,
    lo_level_dbm: float,
    rf_level_dbm: float,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """
    Capture a wide-span SSA trace with both LO and RF active.
    Compute and mark expected IM products.

    Returns: (freqs_hz, trace_dbm, annotated_products)
    """
    print(f"\n[SPURIOUS]  LO={format_freq_short(lo_hz)}  RF={format_freq_short(rf_hz)}")
    if_hz = abs(lo_hz - rf_hz)

    sdg.set_sine(CH_LO, lo_hz, lo_level_dbm)
    sdg.output_on(CH_LO)
    sdg.set_sine(CH_RF, rf_hz, rf_level_dbm)
    sdg.output_on(CH_RF)
    time.sleep(0.2)

    # Wide span: 9 kHz to 3× the LO or 5× the IF, whichever is greater
    span_stop = max(lo_hz * 3.0, if_hz * 5.0, rf_hz * 3.0)
    span_stop = min(span_stop, 3_200_000_000)   # SSA max
    start_hz  = 9_000

    print(f"  Wide sweep: {format_freq_short(start_hz)} – {format_freq_short(span_stop)}")
    rbw = ssa.setup_band(int(start_hz), int(span_stop), 1001)
    print(f"  RBW = {rbw/1000:.0f} kHz ...", end=" ", flush=True)
    ssa.single_sweep()
    trace = ssa.get_trace()
    print("done")

    freqs_hz = np.linspace(start_hz, span_stop, len(trace))

    # Build list of expected products
    # intermod_products gives close-in IM products; we want mixing products too
    products = []

    def add_product(freq_hz: float, label: str, level_dbm: float | None = None):
        if freq_hz < 9_000 or freq_hz > span_stop:
            return
        # Find measured level near this frequency
        idx = int(np.argmin(np.abs(freqs_hz - freq_hz)))
        measured = float(trace[idx])
        products.append({
            "freq_hz":   freq_hz,
            "label":     label,
            "measured":  measured,
        })

    # Fundamental products
    add_product(if_hz,       f"IF  |LO−RF|")
    add_product(lo_hz + rf_hz, "LO+RF")
    add_product(lo_hz,       "LO  leakage")
    add_product(rf_hz,       "RF  leakage")

    # Harmonics and mixing products up to order 5
    for k in range(2, 6):
        add_product(k * lo_hz,          f"{k}×LO")
        add_product(k * rf_hz,          f"{k}×RF")
        add_product(k * lo_hz - rf_hz,  f"{k}LO−RF")
        add_product(k * lo_hz + rf_hz,  f"{k}LO+RF")
        add_product(lo_hz - k * rf_hz,  f"LO−{k}RF")  if lo_hz > k * rf_hz else None
        add_product(lo_hz + k * rf_hz,  f"LO+{k}RF")
        add_product(k * lo_hz - (k-1) * rf_hz,  f"{k}LO−{k-1}RF")
        add_product((k-1) * lo_hz - k * rf_hz,  f"{k-1}LO−{k}RF") if (k-1)*lo_hz > k*rf_hz else None

    # Near-IF intermod products via intermod_products()
    im_list = intermod_products(lo_hz, rf_hz)
    for im in im_list:
        add_product(im["freq_hz"], im["label"])

    print(f"  Found {len(products)} annotated product locations")
    return freqs_hz, trace, products


# ---------------------------------------------------------------------------
# Output: plots and text report
# ---------------------------------------------------------------------------

def save_conversion_plot(
    results: list[dict],
    lo_hz: float,
    lo_level_dbm: float,
    rf_level_dbm: float,
    output_prefix: str,
) -> str:
    """Save conversion loss vs RF frequency plot."""
    if not results:
        return ""

    rf_mhz   = np.array([r["rf_hz"] / 1e6 for r in results])
    conv_loss = np.array([r["conversion_loss_db"] for r in results])

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(rf_mhz, conv_loss, color="#1f77b4", linewidth=1.5, marker="o",
            markersize=4, label="Conversion Loss")

    mean_loss = float(np.mean(conv_loss))
    ax.axhline(mean_loss, color="darkorange", linestyle="--", linewidth=1.0,
               label=f"Mean {mean_loss:.1f} dB")

    ax.set_title(
        f"Mixer Conversion Loss — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"LO = {format_freq_short(lo_hz)} @ {lo_level_dbm:+.1f} dBm  |  "
        f"RF level = {rf_level_dbm:+.1f} dBm",
        fontsize=11,
    )
    ax.set_xlabel("RF Frequency (MHz)")
    ax.set_ylabel("Conversion Loss (dB)")
    ax.invert_yaxis()   # higher loss = more negative = shown lower
    ax.grid(True, alpha=0.35)
    ax.legend(fontsize=9)

    path = f"{output_prefix}_conversion.png"
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def save_p1db_plot(p1db_result: dict, lo_hz: float, output_prefix: str) -> str:
    """Save 1 dB compression point plot."""
    rf_powers  = p1db_result["rf_powers"]
    if_powers  = p1db_result["if_powers"]
    ideal_line = p1db_result["ideal_line"]
    rf_hz      = p1db_result["rf_hz"]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(rf_powers, if_powers, color="#1f77b4", linewidth=1.5,
            marker="o", markersize=4, label="IF output (measured)")
    ax.plot(rf_powers, ideal_line, color="green", linestyle="--",
            linewidth=1.0, label="Linear fit (small-signal)")
    ax.plot(rf_powers, ideal_line - 1.0, color="darkorange", linestyle=":",
            linewidth=1.0, label="−1 dB from linear")

    if p1db_result["p1db_found"]:
        p1in  = p1db_result["p1db_in"]
        p1out = p1db_result["p1db_out"]
        ax.axvline(p1in, color="red", linestyle="-.", linewidth=1.0)
        ax.plot(p1in, p1out, "r*", markersize=14,
                label=f"P1dB_in = {p1in:+.2f} dBm\nP1dB_out = {p1out:+.2f} dBm")

    ax.set_title(
        f"Mixer 1 dB Compression — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"RF = {format_freq_short(rf_hz)}  |  LO = {format_freq_short(lo_hz)}",
        fontsize=11,
    )
    ax.set_xlabel("RF Input Power (dBm)")
    ax.set_ylabel("IF Output Power (dBm)")
    ax.grid(True, alpha=0.35)
    ax.legend(fontsize=8)

    path = f"{output_prefix}_p1db.png"
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def save_spurs_plot(
    freqs_hz: np.ndarray,
    trace_dbm: np.ndarray,
    products: list[dict],
    lo_hz: float,
    rf_hz: float,
    lo_level_dbm: float,
    rf_level_dbm: float,
    output_prefix: str,
) -> str:
    """Save wide-span SSA trace with annotated IM product markers."""
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(freqs_hz / 1e6, trace_dbm, color="#1f77b4", linewidth=0.8,
            label="SSA trace")

    noise_floor = float(np.percentile(trace_dbm, 10))

    # Annotate products that are significantly above noise
    labeled_freqs: list[float] = []
    for p in sorted(products, key=lambda x: x["measured"], reverse=True):
        if p["measured"] < noise_floor + 6:
            continue
        # Avoid overlapping labels: skip if another label is within 1% of the span
        too_close = any(
            abs(p["freq_hz"] - lf) < (freqs_hz[-1] - freqs_hz[0]) * 0.01
            for lf in labeled_freqs
        )
        if too_close:
            continue
        ax.axvline(p["freq_hz"] / 1e6, color="red", linestyle=":",
                   linewidth=0.7, alpha=0.6)
        ax.text(
            p["freq_hz"] / 1e6, p["measured"] + 2,
            p["label"], fontsize=6, rotation=90, va="bottom", ha="center",
            color="darkred",
        )
        labeled_freqs.append(p["freq_hz"])

    ax.set_title(
        f"Mixer Spurious Products — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"LO = {format_freq_short(lo_hz)} @ {lo_level_dbm:+.1f} dBm  |  "
        f"RF = {format_freq_short(rf_hz)} @ {rf_level_dbm:+.1f} dBm",
        fontsize=11,
    )
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Power (dBm)")
    ax.grid(True, alpha=0.35)
    ax.legend(fontsize=8)

    path = f"{output_prefix}_spurs.png"
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def save_text_report(
    conversion_results: list[dict],
    p1db_result: dict | None,
    isolation_result: dict | None,
    spur_products: list[dict] | None,
    lo_hz: float,
    lo_level_dbm: float,
    rf_level_dbm: float,
    output_prefix: str,
) -> str:
    """Write summary text report."""
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "=" * 72
    lines = [
        sep,
        "  MIXER CHARACTERIZATION REPORT",
        f"  Generated  : {ts}",
        f"  LO         : {format_freq_short(lo_hz)} @ {lo_level_dbm:+.1f} dBm  (SDG CH1)",
        f"  RF level   : {rf_level_dbm:+.1f} dBm  (SDG CH2)",
        sep, "",
    ]

    # Conversion loss summary
    if conversion_results:
        conv_losses = [r["conversion_loss_db"] for r in conversion_results]
        lines += [
            "CONVERSION LOSS",
            "-" * 72,
            f"  Points       : {len(conversion_results)}",
            f"  Mean loss    : {np.mean(conv_losses):.2f} dB",
            f"  Min loss     : {np.min(conv_losses):.2f} dB  @ {format_freq_short(conversion_results[int(np.argmin(conv_losses))]['rf_hz'])}",
            f"  Max loss     : {np.max(conv_losses):.2f} dB  @ {format_freq_short(conversion_results[int(np.argmax(conv_losses))]['rf_hz'])}",
            f"  Flatness     : {np.max(conv_losses) - np.min(conv_losses):.2f} dB  (max − min)",
            "",
            f"  {'RF Freq':>14}  {'IF Freq':>14}  {'IF Power':>10}  {'Conv Loss':>10}",
            f"  {'-'*14}  {'-'*14}  {'-'*10}  {'-'*10}",
        ]
        for r in conversion_results:
            lines.append(
                f"  {format_freq_short(r['rf_hz']):>14}  "
                f"{format_freq_short(r['if_hz']):>14}  "
                f"  {r['if_dbm']:>8.1f} dBm  "
                f"{r['conversion_loss_db']:>8.2f} dB"
            )
        lines.append("")

    # 1 dB compression
    if p1db_result is not None:
        lines += ["1 dB COMPRESSION POINT", "-" * 72]
        if p1db_result["p1db_found"]:
            lines += [
                f"  RF frequency : {format_freq_short(p1db_result['rf_hz'])}",
                f"  P1dB input   : {p1db_result['p1db_in']:+.2f} dBm",
                f"  P1dB output  : {p1db_result['p1db_out']:+.2f} dBm",
            ]
        else:
            lines += [
                f"  RF frequency : {format_freq_short(p1db_result['rf_hz'])}",
                "  P1dB         : NOT FOUND in sweep range",
                "  (try extending --p1db-stop or checking LO drive level)",
            ]
        lines.append("")

    # Isolation
    if isolation_result is not None:
        iso = isolation_result
        lines += [
            "PORT ISOLATION",
            "-" * 72,
            f"  LO→IF isolation  : {iso['lo_isolation_db']:.1f} dB  "
            f"(LO={format_freq_short(iso['lo_hz'])}, measured {iso['lo_at_if_dbm']:.1f} dBm at IF port)",
            f"  RF→IF isolation  : {iso['rf_isolation_db']:.1f} dB  "
            f"(RF={format_freq_short(iso['rf_hz'])}, measured {iso['rf_at_if_dbm']:.1f} dBm at IF port)",
            "",
        ]

    # Spurious products summary
    if spur_products:
        significant = [p for p in spur_products
                       if p["measured"] > -80]
        significant.sort(key=lambda x: x["measured"], reverse=True)
        if significant:
            lines += [
                "SIGNIFICANT SPURIOUS PRODUCTS  (above −80 dBm)",
                "-" * 72,
                f"  {'Product':>16}  {'Frequency':>14}  {'Measured':>10}",
                f"  {'-'*16}  {'-'*14}  {'-'*10}",
            ]
            for p in significant[:20]:
                lines.append(
                    f"  {p['label']:>16}  "
                    f"{format_freq_short(p['freq_hz']):>14}  "
                    f"  {p['measured']:>8.1f} dBm"
                )
            lines.append("")

    lines.append(sep)
    text = "\n".join(lines) + "\n"
    path = f"{output_prefix}_mixer.txt"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Mixer Characterizer — Siglent SDG + SSA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Physical setup:
  SDG CH1 (LO) ────────────────────── LO port of mixer
  SDG CH2 (RF) ──[attenuator]──────── RF port of mixer
                                        IF port ─── SSA RF In

Examples:
  python mixer_characterizer.py
  python mixer_characterizer.py --lo-freq 100000 --lo-level 7
  python mixer_characterizer.py --p1db --p1db-freq 5000
  python mixer_characterizer.py --isolation
  python mixer_characterizer.py --lo-freq 10000 --rf-start 100 --rf-stop 30000 --rf-points 101
""",
    )

    # Signal parameters
    sg = parser.add_argument_group("signal parameters")
    sg.add_argument("--lo-freq",    type=float, default=DEFAULT_LO_FREQ_KHZ, metavar="KHZ",
                    help=f"LO frequency in kHz (default {DEFAULT_LO_FREQ_KHZ})")
    sg.add_argument("--lo-level",   type=float, default=DEFAULT_LO_LEVEL, metavar="DBM",
                    help=f"LO output level in dBm (default {DEFAULT_LO_LEVEL})")
    sg.add_argument("--rf-start",   type=float, default=DEFAULT_RF_START_KHZ, metavar="KHZ",
                    help=f"RF sweep start in kHz (default {DEFAULT_RF_START_KHZ})")
    sg.add_argument("--rf-stop",    type=float, default=DEFAULT_RF_STOP_KHZ, metavar="KHZ",
                    help=f"RF sweep stop in kHz (default {DEFAULT_RF_STOP_KHZ})")
    sg.add_argument("--rf-points",  type=int, default=DEFAULT_RF_POINTS, metavar="N",
                    help=f"RF sweep points (default {DEFAULT_RF_POINTS})")
    sg.add_argument("--rf-level",   type=float, default=DEFAULT_RF_LEVEL, metavar="DBM",
                    help=f"RF input level in dBm (default {DEFAULT_RF_LEVEL})")
    sg.add_argument("--if-bw-khz",  type=float, default=DEFAULT_IF_BW_KHZ, metavar="KHZ",
                    help=f"IF window half-width in kHz (default {DEFAULT_IF_BW_KHZ})")

    # Measurement modes
    mg = parser.add_argument_group("measurement modes")
    mg.add_argument("--p1db",           action="store_true",
                    help="Sweep RF power to find IF 1 dB compression point")
    mg.add_argument("--p1db-freq",      type=float, default=DEFAULT_P1DB_FREQ_KHZ, metavar="KHZ",
                    help=f"RF frequency for P1dB sweep in kHz (default {DEFAULT_P1DB_FREQ_KHZ})")
    mg.add_argument("--p1db-start",     type=float, default=DEFAULT_P1DB_START, metavar="DBM",
                    help=f"P1dB sweep start power in dBm (default {DEFAULT_P1DB_START})")
    mg.add_argument("--p1db-stop",      type=float, default=DEFAULT_P1DB_STOP, metavar="DBM",
                    help=f"P1dB sweep stop power in dBm (default {DEFAULT_P1DB_STOP})")
    mg.add_argument("--isolation",      action="store_true",
                    help="Measure LO→IF and RF→IF isolation")
    mg.add_argument("--no-conversion",  action="store_true",
                    help="Skip the conversion loss frequency sweep")
    mg.add_argument("--no-spurious",    action="store_true",
                    help="Skip the wide-span spurious product capture")

    # Instrument connections
    ig = parser.add_argument_group("instruments")
    ig.add_argument("--sdg-host", default=DEFAULT_SDG_HOST, metavar="HOST",
                    help=f"SDG1000X IP address (default {DEFAULT_SDG_HOST})")
    ig.add_argument("--ssa-host", default=DEFAULT_SSA_HOST, metavar="HOST",
                    help=f"SSA3000X IP address (default {DEFAULT_SSA_HOST})")

    # Output
    og = parser.add_argument_group("output")
    og.add_argument("--output", default=None, metavar="PREFIX",
                    help="Output file prefix (default: timestamped)")

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"mixer_{ts}"

    # Convert kHz to Hz
    lo_hz        = args.lo_freq     * 1e3
    rf_start_hz  = args.rf_start    * 1e3
    rf_stop_hz   = args.rf_stop     * 1e3
    if_bw_hz     = args.if_bw_khz  * 1e3
    p1db_freq_hz = args.p1db_freq  * 1e3

    rf_freqs_hz = np.linspace(rf_start_hz, rf_stop_hz, args.rf_points)

    # Connect to instruments
    print(f"Connecting to SDG @ {args.sdg_host} ...", end=" ", flush=True)
    sdg = SDG1000X(args.sdg_host)
    print(sdg.identify().split(",")[1] if "," in sdg.identify() else "OK")

    print(f"Connecting to SSA @ {args.ssa_host} ...", end=" ", flush=True)
    ssa = SSA3000X(args.ssa_host)
    print(ssa.identify().split(",")[1] if "," in ssa.identify() else "OK")

    conversion_results = []
    p1db_result        = None
    isolation_result   = None
    spur_products      = None
    spur_freqs         = None
    spur_trace         = None

    try:
        # --- Conversion loss sweep ---
        if not args.no_conversion:
            conversion_results = run_conversion_sweep(
                ssa, sdg,
                lo_hz         = lo_hz,
                rf_freqs_hz   = rf_freqs_hz,
                rf_level_dbm  = args.rf_level,
                lo_level_dbm  = args.lo_level,
                if_bw_hz      = if_bw_hz,
            )

        # --- 1 dB compression ---
        if args.p1db:
            p1db_result = run_p1db(
                ssa, sdg,
                lo_hz         = lo_hz,
                rf_hz         = p1db_freq_hz,
                lo_level_dbm  = args.lo_level,
                if_bw_hz      = if_bw_hz,
                rf_start_dbm  = args.p1db_start,
                rf_stop_dbm   = args.p1db_stop,
                rf_steps      = DEFAULT_P1DB_STEPS,
            )

        # --- Port isolation ---
        if args.isolation:
            isolation_result = run_isolation(
                ssa, sdg,
                lo_hz        = lo_hz,
                rf_hz        = rf_freqs_hz[0],
                lo_level_dbm = args.lo_level,
                rf_level_dbm = args.rf_level,
                if_bw_hz     = if_bw_hz,
            )

        # --- Spurious products ---
        if not args.no_spurious:
            spur_freqs, spur_trace, spur_products = run_spurious(
                ssa, sdg,
                lo_hz        = lo_hz,
                rf_hz        = rf_freqs_hz[len(rf_freqs_hz) // 2],
                lo_level_dbm = args.lo_level,
                rf_level_dbm = args.rf_level,
            )

    except KeyboardInterrupt:
        print("\nInterrupted — saving partial results.")
    finally:
        sdg.output_off_all()
        sdg.close()
        ssa.disconnect()

    # --- Save outputs ---
    print("\n[SAVING RESULTS]")
    saved = []

    if conversion_results:
        path = save_conversion_plot(conversion_results, lo_hz,
                                    args.lo_level, args.rf_level, args.output)
        if path:
            print(f"  Conversion plot  → {path}")
            saved.append(path)

    if p1db_result is not None:
        path = save_p1db_plot(p1db_result, lo_hz, args.output)
        if path:
            print(f"  P1dB plot        → {path}")
            saved.append(path)

    if spur_freqs is not None and spur_trace is not None:
        path = save_spurs_plot(
            spur_freqs, spur_trace, spur_products or [],
            lo_hz, rf_freqs_hz[len(rf_freqs_hz) // 2],
            args.lo_level, args.rf_level, args.output,
        )
        if path:
            print(f"  Spurs plot       → {path}")
            saved.append(path)

    txt_path = save_text_report(
        conversion_results, p1db_result, isolation_result, spur_products,
        lo_hz, args.lo_level, args.rf_level, args.output,
    )
    print(f"  Text report      → {txt_path}")
    print()

    with open(txt_path) as fh:
        print(fh.read())


if __name__ == "__main__":
    try:
        main()
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to instrument: {exc}")
        print("Check that instruments are powered on and SCPI/LAN is enabled.")
        sys.exit(1)
    except OSError as exc:
        print(f"\nNetwork error: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
        sys.exit(1)
