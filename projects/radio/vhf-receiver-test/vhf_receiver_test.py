#!/usr/bin/env python3
"""
VHF/UHF Receiver Sensitivity Test — IC-9700 + SSA3032X

Measures IC-9700 receiver sensitivity on 2m, 70cm, and 23cm using the
SSA3032X Plus tracking generator as the signal source.  The SSA tracking
generator covers 9 kHz–3.2 GHz, reaching all three IC-9700 bands.

Measurements:
  mds         Minimum Discernible Signal: signal level at 10 dB S/N over noise
  smeter-cal  S-meter calibration: maps rigctld dBm → true input dBm
  nf          Noise figure from MDS measurement

Connection:
    SSA TG Out → [attenuator chain] → IC-9700 antenna port

    Recommended: 30 dB + 20 dB = 50 dB total.  The SSA TG output is
    typically 0 dBm; a 50 dB chain gives −50 dBm at the IC-9700 input.
    For MDS measurements (−120 to −135 dBm), stack additional pads.

Usage:
    python vhf_receiver_test.py --test smeter-cal --freq 144200 --atten 50
    python vhf_receiver_test.py --test mds        --freq 432100 --atten 110
    python vhf_receiver_test.py --test nf         --freq 144200 --atten 110
    python vhf_receiver_test.py --all             --freq 144200 --atten 110

    # 23cm:
    python vhf_receiver_test.py --test smeter-cal --freq 1296100 --atten 50

Output:
    vhf_rx_<test>_<freq>_<timestamp>.json + .png
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
from rf_bench.utils   import noise_figure_from_mds, thermal_noise_floor, format_freq
from rf_bench import connect

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_SSA_HOST  = None  # Now uses inventory
DEFAULT_RIG_HOST  = "localhost"
DEFAULT_RIG_PORT  = 4532
DEFAULT_ATTEN     = 110.0       # dB
DEFAULT_FREQ_KHZ  = 144_200.0   # kHz

# SSA TG output level (dBm).  Keep at or below 0 to avoid damaging SSA circuits.
SSA_TG_LEVEL_DBM  = 0.0

# Mode noise bandwidths for NF calculation (Hz)
MODE_NOISE_BW = {
    "usb":  2400,
    "lsb":  2400,
    "cw":    500,
    "cwr":   500,
    "fm":  15000,
    "am":   6000,
    "dv":   12000,
}

# IC-9700 VHF/UHF S9 reference (ITU): S9 = −73 dBm on VHF/UHF (not −93 dBm as on HF)
S9_VHF_DBM = -73.0


# ── S-meter calibration ───────────────────────────────────────────────────────

def smeter_cal(radio: IC9700, ssa: SSA3000X, freq_hz: float, atten_db: float,
               mode: str, stem: str) -> dict:
    """Sweep SSA TG level and log IC-9700 S-meter at each level."""
    print(f"\n── S-meter Calibration  {format_freq(freq_hz)} ──")
    print(f"   Path attenuation: {atten_db:.1f} dB  Mode: {mode.upper()}")

    radio.set_frequency(freq_hz)
    radio.set_mode(mode)
    radio.set_agc("slow")

    ssa.set_center(freq_hz)
    ssa.set_span(1_000_000)
    ssa.set_tracking_gen(on=True)
    ssa.set_tracking_gen_level(SSA_TG_LEVEL_DBM)

    # Sweep from just above noise floor up to a safe level
    tg_levels = list(range(-50, 5, 5))   # −50 to 0 dBm in 5 dB steps
    input_dbm_list = []
    smeter_dbm_list = []

    for tg_dbm in tg_levels:
        input_dbm = tg_dbm - atten_db
        ssa.set_tracking_gen_level(tg_dbm)
        time.sleep(0.4)
        s_dbm = radio.get_strength_settled(settle_s=0.4)
        input_dbm_list.append(input_dbm)
        smeter_dbm_list.append(s_dbm)
        print(f"   TG {tg_dbm:+4d} dBm → input {input_dbm:+7.1f} dBm  "
              f"S-meter {s_dbm:+7.1f} dBm")

    ssa.set_tracking_gen(on=False)

    # Fit a line to the linear region
    x = np.array(input_dbm_list)
    y = np.array(smeter_dbm_list)
    coeffs = np.polyfit(x, y, 1)
    offset_db = float(np.mean(y - x))

    result = {
        "test":           "smeter-cal",
        "freq_hz":        freq_hz,
        "mode":           mode,
        "atten_db":       atten_db,
        "tg_levels_dbm":  tg_levels,
        "input_dbm":      input_dbm_list,
        "smeter_dbm":     smeter_dbm_list,
        "slope":          float(coeffs[0]),
        "offset_db":      offset_db,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }

    # Plot
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(x, y, color="steelblue", zorder=3, label="Measured")
    fit_x = np.linspace(x.min(), x.max(), 200)
    ax.plot(fit_x, np.polyval(coeffs, fit_x), "r--", label=f"Fit (slope={coeffs[0]:.2f})")
    ax.plot(fit_x, fit_x, "k:", alpha=0.4, label="Ideal (1:1)")
    ax.set_xlabel("True input level (dBm)")
    ax.set_ylabel("IC-9700 S-meter reading (dBm)")
    ax.set_title(f"IC-9700 S-meter Calibration  {format_freq(freq_hz)}")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    png = f"{stem}.png"
    fig.savefig(png, dpi=150)
    plt.close(fig)
    print(f"   Plot saved: {png}")
    print(f"   S-meter offset: {offset_db:+.1f} dB  slope: {coeffs[0]:.2f}")
    return result


# ── MDS / NF ──────────────────────────────────────────────────────────────────

def mds_test(radio: IC9700, ssa: SSA3000X, freq_hz: float, atten_db: float,
             mode: str, stem: str) -> dict:
    """Find minimum discernible signal (10 dB above noise floor)."""
    print(f"\n── MDS / Noise Figure  {format_freq(freq_hz)} ──")
    print(f"   Path attenuation: {atten_db:.1f} dB  Mode: {mode.upper()}")

    radio.set_frequency(freq_hz)
    radio.set_mode(mode)
    radio.set_agc("off")    # AGC off for clean noise floor reading

    ssa.set_center(freq_hz)
    ssa.set_span(1_000_000)

    # Noise floor — SSA TG off, measure baseline S-meter noise
    ssa.set_tracking_gen(on=False)
    time.sleep(1.0)
    noise_readings = [radio.get_strength() for _ in range(10)]
    noise_dbm = float(np.mean(noise_readings))
    print(f"   Noise floor: {noise_dbm:+.1f} dBm")

    target_dbm = noise_dbm + 10.0   # MDS = 10 dB S/N

    # Sweep TG level downward until S-meter is at target
    ssa.set_tracking_gen(on=True)
    mds_input_dbm = None
    tg_sweep = list(range(int(SSA_TG_LEVEL_DBM), -80, -1))
    for tg_dbm in tg_sweep:
        input_dbm = tg_dbm - atten_db
        ssa.set_tracking_gen_level(tg_dbm)
        time.sleep(0.3)
        s = radio.get_strength_settled(settle_s=0.2)
        if s <= target_dbm:
            mds_input_dbm = input_dbm
            print(f"   MDS found at TG {tg_dbm:+d} dBm → input {input_dbm:+.1f} dBm  "
                  f"S-meter {s:+.1f} dBm")
            break

    ssa.set_tracking_gen(on=False)
    radio.set_agc("slow")

    if mds_input_dbm is None:
        print("   WARNING: MDS not found in sweep range. Increase attenuation.")
        mds_input_dbm = float("nan")

    bw_hz = MODE_NOISE_BW.get(mode, 2400)
    nf_db = noise_figure_from_mds(mds_input_dbm, bw_hz) if not math.isnan(mds_input_dbm) else float("nan")
    thermal_floor = thermal_noise_floor(bw_hz)
    print(f"   MDS: {mds_input_dbm:+.1f} dBm  BW: {bw_hz} Hz  NF: {nf_db:.1f} dB")
    print(f"   Thermal noise floor ({bw_hz} Hz): {thermal_floor:.1f} dBm")

    result = {
        "test":           "mds",
        "freq_hz":        freq_hz,
        "mode":           mode,
        "atten_db":       atten_db,
        "noise_floor_dbm": noise_dbm,
        "mds_dbm":        mds_input_dbm,
        "noise_figure_db": nf_db,
        "noise_bw_hz":    bw_hz,
        "thermal_floor_dbm": thermal_floor,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }

    # Simple bar chart
    if not math.isnan(nf_db):
        fig, ax = plt.subplots(figsize=(5, 4))
        bars = ["Thermal\nNoise Floor", "IC-9700\nNoise Figure", "IC-9700\nMDS"]
        vals = [thermal_floor, nf_db, mds_input_dbm]
        colors = ["steelblue", "darkorange", "firebrick"]
        ax.bar(bars, vals, color=colors)
        ax.set_ylabel("dBm / dB")
        ax.set_title(f"IC-9700 MDS  {format_freq(freq_hz)}  {mode.upper()}")
        ax.grid(True, alpha=0.3, axis="y")
        for bar, val in zip(ax.patches, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    f"{val:.1f}", ha="center", va="bottom", fontsize=9)
        plt.tight_layout()
        png = f"{stem}.png"
        fig.savefig(png, dpi=150)
        plt.close(fig)
        print(f"   Plot saved: {png}")

    return result


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="IC-9700 VHF/UHF receiver sensitivity test")
    p.add_argument("--test",   choices=["smeter-cal", "mds", "nf"], default=None)
    p.add_argument("--all",    action="store_true", help="Run smeter-cal then mds")
    p.add_argument("--freq",   type=float, default=DEFAULT_FREQ_KHZ,
                   help="Test frequency in kHz (default %(default)s)")
    p.add_argument("--mode",   default="usb",
                   choices=["usb","lsb","cw","cwr","fm","am","dv"])
    p.add_argument("--atten",  type=float, default=DEFAULT_ATTEN,
                   help="Total path attenuation in dB (default %(default)s)")
    p.add_argument("--ssa-host", default=DEFAULT_SSA_HOST, dest="ssa_host")
    p.add_argument("--rig-host", default=DEFAULT_RIG_HOST, dest="rig_host")
    p.add_argument("--rig-port", type=int, default=DEFAULT_RIG_PORT, dest="rig_port")
    p.add_argument("--out",    default=None, help="Output file stem (default: auto)")
    args = p.parse_args()

    if not args.test and not args.all:
        p.error("Specify --test TEST or --all")

    freq_hz = args.freq * 1000.0
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    freq_tag = f"{args.freq:.0f}"

    tests_to_run = []
    if args.all:
        tests_to_run = ["smeter-cal", "mds"]
    else:
        tests_to_run = [args.test]
    if "nf" in tests_to_run:
        tests_to_run = [t if t != "nf" else "mds" for t in tests_to_run]

    radio = IC9700(host=args.rig_host, port=args.rig_port)
    ssa   = connect(args.ssa_host or 'ssa')

    all_results = []
    for test in tests_to_run:
        stem = args.out or f"vhf_rx_{test}_{freq_tag}_{ts}"
        if test == "smeter-cal":
            r = smeter_cal(radio, ssa, freq_hz, args.atten, args.mode, stem)
        elif test == "mds":
            r = mds_test(radio, ssa, freq_hz, args.atten, args.mode, stem)
        else:
            continue
        all_results.append(r)
        jpath = f"{stem}.json"
        with open(jpath, "w") as f:
            json.dump(r, f, indent=2)
        print(f"   JSON saved: {jpath}")

    radio.close()


if __name__ == "__main__":
    main()
