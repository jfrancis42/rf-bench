#!/usr/bin/env python3
"""
IC-9700 / RTL-SDR Receiver Cross-Calibration

Tunes both the IC-9700 and RTL-SDR to the same VHF/UHF frequency,
measures the same signal simultaneously, and builds a calibration table
mapping RTL-SDR relative power (dB re noise floor) to IC-9700 S-meter (dBm).

This enables the RTL-SDR to be used as a fast, wideband spectrum scanner
with readings calibrated against the IC-9700's known S-meter scale.

Signal source options:
  a) SSA3032X tracking generator (recommended — calibrated, any freq)
  b) A known beacon or repeater carrier on the air

Connection (SSA TG option):
    SSA TG Out → splitter/combiner → IC-9700 ANT port (via ≥30 dB atten)
                                   → RTL-SDR (via ≥20 dB atten)

Usage:
    # Cross-calibrate at 144.200 MHz using SSA TG:
    python rx_crosscheck.py --freq 144200 --source ssa

    # Use an on-air signal (no SSA required):
    python rx_crosscheck.py --freq 144390 --source air --label "APRS beacon"

    # Full sweep across multiple levels (SSA TG):
    python rx_crosscheck.py --freq 144200 --source ssa --sweep

Output:
    rx_crosscheck_<freq>_<timestamp>.json + .png
    ~/.rtlsdr_vhf_cal.json  — calibration table (loaded by other RTL-SDR projects)
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.icom   import IC9700
from rf_bench.rtlsdr import RTLSDR
from rf_bench.utils  import format_freq
from rf_bench import connect

DEFAULT_SSA_HOST     = None  # Now uses inventory
DEFAULT_RIG_HOST     = "localhost"
DEFAULT_RIG_PORT     = 4532
DEFAULT_FREQ_KHZ     = 144_200.0
DEFAULT_ATTEN_IC9700 = 30.0     # dB between splitter output and IC-9700
DEFAULT_ATTEN_RTLSDR = 20.0     # dB between splitter output and RTL-SDR
CAL_FILE             = Path.home() / ".rtlsdr_vhf_cal.json"
RTL_SAMPLE_RATE      = 2_400_000
RTL_FFT_SIZE         = 65_536


def rtlsdr_power_dbfs(sdr: RTLSDR, freq_hz: float,
                      bw_hz: float = 25_000) -> float:
    """
    Measure RTL-SDR power at freq_hz within bw_hz bandwidth.
    Returns dBFS (decibels relative to full scale).
    """
    sdr.set_center_freq(freq_hz)
    time.sleep(0.1)
    iq = sdr.capture_iq(RTL_FFT_SIZE)
    fft = np.fft.fftshift(np.fft.fft(iq, RTL_FFT_SIZE))
    psd = np.abs(fft) ** 2

    freqs = np.fft.fftshift(
        np.fft.fftfreq(RTL_FFT_SIZE, 1.0 / RTL_SAMPLE_RATE)
    )
    mask = np.abs(freqs) <= bw_hz / 2
    signal_power = np.mean(psd[mask])
    total_power  = np.mean(psd)
    dbfs = 10 * np.log10(signal_power / total_power + 1e-12)
    return float(dbfs)


def run_sweep(radio: IC9700, sdr: RTLSDR, ssa, freq_hz: float,
              atten_ic9700: float, atten_rtlsdr: float) -> list:
    """Sweep SSA TG level and measure both receivers."""
    from rf_bench.siglent import SSA3000X
    ssa.set_center(freq_hz)
    ssa.set_span(5_000_000)
    ssa.set_tracking_gen(on=True)

    tg_levels   = list(range(-50, 5, 5))
    rows        = []

    for tg_dbm in tg_levels:
        ssa.set_tracking_gen_level(tg_dbm)
        time.sleep(0.3)

        ic9700_dbm = radio.get_strength_settled(settle_s=0.3)
        rtl_dbfs   = rtlsdr_power_dbfs(sdr, freq_hz)
        true_dbm   = tg_dbm - atten_ic9700

        rows.append({
            "tg_dbm":     tg_dbm,
            "true_dbm":   true_dbm,
            "ic9700_dbm": ic9700_dbm,
            "rtl_dbfs":   rtl_dbfs,
        })
        print(f"  TG {tg_dbm:+4d} → true {true_dbm:+7.1f} dBm  "
              f"IC-9700 {ic9700_dbm:+7.1f} dBm  "
              f"RTL-SDR {rtl_dbfs:+7.1f} dBFS")

    ssa.set_tracking_gen(on=False)
    return rows


def run_air(radio: IC9700, sdr: RTLSDR, freq_hz: float,
            n_samples: int = 20, interval_s: float = 1.0) -> list:
    """Measure both receivers on an on-air signal simultaneously."""
    rows = []
    for i in range(n_samples):
        ic9700_dbm = radio.get_strength_settled(settle_s=0.2)
        rtl_dbfs   = rtlsdr_power_dbfs(sdr, freq_hz)
        rows.append({"ic9700_dbm": ic9700_dbm, "rtl_dbfs": rtl_dbfs})
        print(f"  [{i+1:3d}/{n_samples}]  "
              f"IC-9700 {ic9700_dbm:+7.1f} dBm  RTL-SDR {rtl_dbfs:+7.1f} dBFS")
        time.sleep(interval_s)
    return rows


def save_cal(rows: list, freq_hz: float):
    """Write/update ~/.rtlsdr_vhf_cal.json with the fitted offset."""
    # Linear fit: ic9700_dbm = slope * rtl_dbfs + offset
    x = np.array([r["rtl_dbfs"] for r in rows])
    y = np.array([r["ic9700_dbm"] for r in rows])
    coeffs = np.polyfit(x, y, 1)

    cal = {}
    if CAL_FILE.exists():
        try:
            cal = json.loads(CAL_FILE.read_text())
        except Exception:
            cal = {}

    freq_key = f"{freq_hz:.0f}"
    cal[freq_key] = {
        "freq_hz": freq_hz,
        "slope":   float(coeffs[0]),
        "offset":  float(coeffs[1]),
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    CAL_FILE.write_text(json.dumps(cal, indent=2))
    print(f"\nCalibration saved to {CAL_FILE}")
    print(f"  RTL-SDR dBFS → IC-9700 dBm: "
          f"{coeffs[0]:.3f} × dBFS + {coeffs[1]:.1f}")
    return coeffs


def main():
    p = argparse.ArgumentParser(
        description="IC-9700 / RTL-SDR cross-calibration"
    )
    p.add_argument("--freq",    type=float, default=DEFAULT_FREQ_KHZ,
                   help="Frequency in kHz (default %(default)s)")
    p.add_argument("--source",  choices=["ssa", "air"], default="ssa",
                   help="Signal source: 'ssa' (SSA TG) or 'air' (on-air beacon)")
    p.add_argument("--sweep",   action="store_true",
                   help="Sweep SSA TG level (--source ssa only)")
    p.add_argument("--samples", type=int, default=20,
                   help="Number of samples for --source air (default 20)")
    p.add_argument("--label",   default="",
                   help="Signal label for --source air output")
    p.add_argument("--atten-ic9700", type=float, default=DEFAULT_ATTEN_IC9700,
                   dest="atten_ic9700",
                   help="Path attenuation to IC-9700 in dB (default %(default)s)")
    p.add_argument("--atten-rtlsdr", type=float, default=DEFAULT_ATTEN_RTLSDR,
                   dest="atten_rtlsdr",
                   help="Path attenuation to RTL-SDR in dB (default %(default)s)")
    p.add_argument("--ssa-host", default=DEFAULT_SSA_HOST, dest="ssa_host")
    p.add_argument("--rig-host", default=DEFAULT_RIG_HOST, dest="rig_host")
    p.add_argument("--rig-port", type=int, default=DEFAULT_RIG_PORT, dest="rig_port")
    p.add_argument("--rtl-gain", type=float, default=30.0, dest="rtl_gain",
                   help="RTL-SDR gain in dB (default 30)")
    p.add_argument("--out",     default=None)
    args = p.parse_args()

    freq_hz = args.freq * 1000.0
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem    = args.out or f"rx_crosscheck_{args.freq:.0f}_{ts}"

    print(f"IC-9700 / RTL-SDR Cross-Calibration  {format_freq(freq_hz)}")
    print(f"Source: {args.source}")
    print()

    radio = IC9700(host=args.rig_host, port=args.rig_port)
    radio.set_frequency(freq_hz)
    radio.set_mode("fm")
    radio.set_agc("slow")

    sdr = RTLSDR()
    sdr.set_center_freq(freq_hz)
    sdr.set_sample_rate(RTL_SAMPLE_RATE)
    sdr.set_gain(args.rtl_gain)

    if args.source == "ssa":
        from rf_bench.siglent import SSA3000X
        ssa = connect(args.ssa_host or 'ssa')
        rows = run_sweep(radio, sdr, ssa, freq_hz,
                         args.atten_ic9700, args.atten_rtlsdr)
    else:
        rows = run_air(radio, sdr, freq_hz, args.samples)

    radio.close()
    sdr.close()

    if len(rows) >= 2:
        coeffs = save_cal(rows, freq_hz)

        x = np.array([r["rtl_dbfs"] for r in rows])
        y = np.array([r["ic9700_dbm"] for r in rows])
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.scatter(x, y, color="steelblue", zorder=3, label="Measured")
        fit_x = np.linspace(x.min(), x.max(), 200)
        ax.plot(fit_x, np.polyval(coeffs, fit_x), "r--",
                label=f"Fit  slope={coeffs[0]:.2f}")
        ax.set_xlabel("RTL-SDR power (dBFS)")
        ax.set_ylabel("IC-9700 S-meter (dBm)")
        ax.set_title(f"RTL-SDR ↔ IC-9700 Calibration  {format_freq(freq_hz)}")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        png = f"{stem}.png"
        fig.savefig(png, dpi=150)
        plt.close(fig)
        print(f"Plot saved: {png}")

    result = {
        "freq_hz":       freq_hz,
        "source":        args.source,
        "label":         args.label,
        "atten_ic9700":  args.atten_ic9700,
        "atten_rtlsdr":  args.atten_rtlsdr,
        "rtl_gain_db":   args.rtl_gain,
        "data":          rows,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }
    jpath = f"{stem}.json"
    with open(jpath, "w") as f:
        json.dump(result, f, indent=2)
    print(f"JSON saved: {jpath}")


if __name__ == "__main__":
    main()
