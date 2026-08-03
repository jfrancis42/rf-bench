#!/usr/bin/env python3
"""
Transmitter Test — IC-7300 / FT-891 via SSA3000X

Measures HF transmitter output power, harmonic content, ALC compression curve,
and SSB carrier suppression.  The TX port is connected to the SSA through a
fixed attenuator chain (default 60 dB).  All measured levels are corrected by
the path attenuation to report true TX power.

Connection:
    Radio TX → fixed attenuator (e.g. 3×20 dB = 60 dB total) → SSA RF In

Usage:
    python transmitter_test.py --radio ic7300 --power
    python transmitter_test.py --radio ft891 --harmonics --atten 50
    python transmitter_test.py --radio ic7300 --all
    python transmitter_test.py --radio ic7300 --alc --freq 14200
    python transmitter_test.py --radio ic7300 --carrier-suppression --freq 14200
"""

import argparse
import json
import socket
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.siglent import SSA3000X                                      # noqa: E402
from rf_bench.utils import (                                                # noqa: E402
    format_freq, format_freq_short, watts_to_dbm, dbm_to_watts,
)
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SSA_HOST    = None  # Now uses inventory
DEFAULT_INSTRUMENT_PORT = 5025
DEFAULT_RIG_HOST    = "localhost"
DEFAULT_RIG_PORT    = 4532
DEFAULT_ATTENUATION = 60.0      # dB total path attenuation
DEFAULT_FREQ_KHZ    = 14_200.0  # kHz
SSA_MAX_HZ          = 3_200_000_000.0   # SSA3032X Plus upper limit

# HF bands for power sweep
TX_BANDS = {
    '160m': 1_850_000,
    '80m':  3_700_000,
    '60m':  5_358_500,
    '40m':  7_150_000,
    '30m': 10_125_000,
    '20m': 14_200_000,
    '17m': 18_118_000,
    '15m': 21_250_000,
    '12m': 24_930_000,
    '10m': 28_500_000,
    '6m':  51_000_000,
}

DEFAULT_BANDS = ['160m', '80m', '40m', '20m', '15m', '10m']

# Power levels to sweep for ALC curve (fraction of full power, 0.0–1.0)
ALC_POWER_LEVELS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


# ---------------------------------------------------------------------------
# PTT / rigctld helpers
# ---------------------------------------------------------------------------

class RigCtld:
    """
    Minimal rigctld socket client.  Handles PTT keying and basic CAT commands.
    """

    def __init__(self, host: str = DEFAULT_RIG_HOST, port: int = DEFAULT_RIG_PORT):
        self._host = host
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(5)
        self._sock.connect((host, port))
        self._sock.settimeout(3)

    def _cmd(self, cmd: str) -> str:
        self._sock.sendall((cmd + "\n").encode())
        time.sleep(0.05)
        try:
            resp = b""
            while True:
                chunk = self._sock.recv(4096)
                resp += chunk
                if resp.endswith(b"\n"):
                    break
        except socket.timeout:
            pass
        return resp.decode(errors="replace").strip()

    def ptt_on(self) -> None:
        """Key transmitter (PTT on)."""
        self._cmd("T 1")
        time.sleep(0.5)   # let carrier stabilize

    def ptt_off(self) -> None:
        """Unkey transmitter (PTT off)."""
        self._cmd("T 0")

    def set_frequency(self, hz: float) -> None:
        self._cmd(f"\\set_freq {int(hz)}")
        time.sleep(0.15)

    def set_mode(self, mode: str) -> None:
        """mode: 'cw', 'usb', 'lsb', 'am', 'fm'"""
        mode_map = {"cw": "CW", "usb": "USB", "lsb": "LSB", "am": "AM", "fm": "FM"}
        ham_mode = mode_map.get(mode.lower(), mode.upper())
        passband = {"CW": 500, "USB": 2400, "LSB": 2400, "AM": 6000, "FM": 15000}
        pb = passband.get(ham_mode, 0)
        self._cmd(f"\\set_mode {ham_mode} {pb}")
        time.sleep(0.15)

    def set_rf_power(self, level: float) -> None:
        """Set RF power level via Hamlib RFPOWER parameter (0.0–1.0)."""
        self._cmd(f"\\set_level RFPOWER {level:.3f}")
        time.sleep(0.2)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# SSA measurement helpers
# ---------------------------------------------------------------------------

def measure_peak_dbm(ssa: SSA3000X, center_hz: float,
                     span_hz: float = 200_000, points: int = 201) -> float:
    """
    Configure SSA with a span around center_hz, run one sweep, return peak dBm.
    """
    start_hz = max(9_000, int(center_hz - span_hz / 2))
    stop_hz  = int(center_hz + span_hz / 2)
    ssa.setup_band(start_hz, stop_hz, points)
    ssa.single_sweep()
    trace = ssa.get_trace()
    return float(np.max(trace))


# ---------------------------------------------------------------------------
# Power output vs. frequency test
# ---------------------------------------------------------------------------

def run_power_test(ssa: SSA3000X, rig: RigCtld,
                   bands: list[str], attenuation_db: float) -> dict:
    """
    Measure CW carrier power at each band center.

    Returns dict with band, freq_hz, measured_dbm (at SSA), true_dbm, true_W.
    """
    results = []
    print(f"\n[POWER TEST — CW carrier, path attenuation {attenuation_db:.0f} dB]")
    print(f"  {'Band':<6}  {'Frequency':>15}  {'SSA dBm':>8}  {'True dBm':>9}  {'True W':>8}  Status")
    print("  " + "-" * 60)

    for band in bands:
        if band not in TX_BANDS:
            print(f"  {band:<6}  unknown band — skipping")
            continue
        freq_hz = TX_BANDS[band]

        rig.set_mode('cw')
        rig.set_frequency(freq_hz)
        time.sleep(0.3)

        try:
            rig.ptt_on()
            ssa_dbm = measure_peak_dbm(ssa, freq_hz, span_hz=200_000)
            true_dbm = ssa_dbm + attenuation_db
            true_w   = dbm_to_watts(true_dbm)
            status   = "OK"
        except Exception as exc:
            ssa_dbm  = float('nan')
            true_dbm = float('nan')
            true_w   = float('nan')
            status   = f"ERR: {exc}"
        finally:
            rig.ptt_off()

        print(f"  {band:<6}  {format_freq(freq_hz):>15}  {ssa_dbm:>+8.1f}  "
              f"{true_dbm:>+9.1f}  {true_w:>7.1f} W  {status}")
        results.append({
            'band':       band,
            'freq_hz':    freq_hz,
            'ssa_dbm':    ssa_dbm,
            'true_dbm':   true_dbm,
            'true_w':     true_w,
        })

    return {'attenuation_db': attenuation_db, 'bands': results}


def plot_power(data: dict, output_prefix: str, radio: str) -> str:
    """Plot power output vs. frequency.  Returns PNG path."""
    bands   = [r for r in data['bands'] if not np.isnan(r['true_dbm'])]
    if not bands:
        return ""
    freqs   = np.array([r['freq_hz'] for r in bands]) / 1e6
    pwr_dbm = np.array([r['true_dbm'] for r in bands])
    labels  = [r['band'] for r in bands]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(freqs, pwr_dbm, 'o-', color='#1f77b4', markersize=7, linewidth=1.5)

    for x, y, lbl in zip(freqs, pwr_dbm, labels):
        ax.annotate(lbl, (x, y), textcoords='offset points',
                    xytext=(0, 8), ha='center', fontsize=8)

    avg = float(np.mean(pwr_dbm))
    ax.axhline(avg, color='gray', linestyle='--', linewidth=0.8,
               label=f'Mean {avg:.1f} dBm')

    ax.set_xlabel('Frequency (MHz)', fontsize=10)
    ax.set_ylabel('Output Power (dBm)', fontsize=10)
    ax.set_title(
        f'Transmitter Output Power — {radio.upper()}  '
        f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
        f'Path attenuation: {data["attenuation_db"]:.0f} dB',
        fontsize=10,
    )
    ax.grid(True, alpha=0.35)
    ax.legend(fontsize=8)
    ax.tick_params(labelsize=9)
    plt.tight_layout()

    path = f"{output_prefix}_power.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def save_power_txt(data: dict, output_prefix: str, radio: str) -> str:
    """Write power test text report.  Returns path."""
    path = f"{output_prefix}_power.txt"
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "=" * 70

    lines = [
        sep,
        "  TRANSMITTER POWER OUTPUT TEST",
        f"  Radio     : {radio.upper()}",
        f"  Generated : {ts}",
        f"  Path atten: {data['attenuation_db']:.0f} dB",
        sep,
        "",
        f"  {'Band':<6}  {'Frequency':>15}  {'SSA dBm':>8}  {'True dBm':>9}  {'True W':>8}",
        "  " + "-" * 55,
    ]

    valid = [r for r in data['bands'] if not np.isnan(r['true_dbm'])]
    for r in data['bands']:
        if np.isnan(r['true_dbm']):
            lines.append(f"  {r['band']:<6}  {format_freq(r['freq_hz']):>15}  {'N/A':>8}  {'N/A':>9}  {'N/A':>8}")
        else:
            lines.append(
                f"  {r['band']:<6}  {format_freq(r['freq_hz']):>15}  "
                f"{r['ssa_dbm']:>+8.1f}  {r['true_dbm']:>+9.1f}  {r['true_w']:>7.1f} W"
            )

    if valid:
        powers = [r['true_dbm'] for r in valid]
        lines += [
            "",
            f"  Min output: {min(powers):+.1f} dBm ({dbm_to_watts(min(powers)):.1f} W)",
            f"  Max output: {max(powers):+.1f} dBm ({dbm_to_watts(max(powers)):.1f} W)",
            f"  Variation:  {max(powers) - min(powers):.1f} dB",
        ]

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# Harmonic content test
# ---------------------------------------------------------------------------

# FCC Part 97 harmonic limit thresholds
FCC_LIMIT_LOW_DBW  = -43.0    # dBc for output < 5 W
FCC_LIMIT_HIGH_DBW = -60.0    # dBW absolute (= −30 dBm) for output ≥ 5 W; often simplified as -60 dBc
FCC_HIGH_POWER_W   =  5.0     # W threshold


def fcc_limit_dbc(power_w: float) -> float:
    """Return the FCC Part 97 harmonic suppression requirement in dBc."""
    if power_w < FCC_HIGH_POWER_W:
        return FCC_LIMIT_LOW_DBW          # −43 dBc
    # For ≥5 W: must be ≤ −60 dBW, i.e. −60 − 10*log10(P_W) dBc
    power_dbw = 10.0 * np.log10(power_w)
    return -60.0 - power_dbw             # typically ≈ −43 to −77 dBc depending on power


def run_harmonic_test(ssa: SSA3000X, rig: RigCtld,
                      bands: list[str], attenuation_db: float) -> dict:
    """
    Measure 2nd, 3rd, and 4th harmonics at each band center.

    Returns per-band harmonic data including dBc and FCC pass/fail.
    """
    results = []
    print(f"\n[HARMONIC TEST — path attenuation {attenuation_db:.0f} dB]")

    for band in bands:
        if band not in TX_BANDS:
            continue
        freq_hz = TX_BANDS[band]

        print(f"\n  {band} ({format_freq_short(freq_hz)}):")
        rig.set_mode('cw')
        rig.set_frequency(freq_hz)
        time.sleep(0.3)

        harmonics = []
        try:
            rig.ptt_on()

            # Fundamental
            fund_ssa_dbm = measure_peak_dbm(ssa, freq_hz, span_hz=200_000)
            fund_dbm     = fund_ssa_dbm + attenuation_db
            fund_w       = dbm_to_watts(fund_dbm)
            fcc_lim      = fcc_limit_dbc(fund_w)
            print(f"    Fundamental  {format_freq_short(freq_hz):>10}  "
                  f"{fund_dbm:>+7.1f} dBm  ({fund_w:.1f} W)")

            for n in [2, 3, 4]:
                h_hz = freq_hz * n
                if h_hz > SSA_MAX_HZ:
                    print(f"    {n}nd/rd/th harmonic  {format_freq_short(h_hz):>10}  "
                          f"(above SSA range — skipped)")
                    harmonics.append({'n': n, 'freq_hz': h_hz,
                                      'ssa_dbm': float('nan'),
                                      'true_dbm': float('nan'),
                                      'dbc': float('nan'),
                                      'fcc_pass': None})
                    continue

                h_ssa_dbm = measure_peak_dbm(ssa, h_hz, span_hz=200_000)
                h_dbm     = h_ssa_dbm + attenuation_db
                dbc       = h_dbm - fund_dbm
                fcc_pass  = dbc <= fcc_lim
                suffix_map = {2: 'nd', 3: 'rd', 4: 'th'}
                pf = "PASS" if fcc_pass else "FAIL"
                print(f"    {n}{suffix_map[n]} harmonic   {format_freq_short(h_hz):>10}  "
                      f"{h_dbm:>+7.1f} dBm  {dbc:>+7.1f} dBc  "
                      f"(FCC limit {fcc_lim:+.0f} dBc) [{pf}]")
                harmonics.append({
                    'n':        n,
                    'freq_hz':  h_hz,
                    'ssa_dbm':  h_ssa_dbm,
                    'true_dbm': h_dbm,
                    'dbc':      dbc,
                    'fcc_pass': fcc_pass,
                })

        finally:
            rig.ptt_off()

        results.append({
            'band':        band,
            'freq_hz':     freq_hz,
            'fund_dbm':    fund_dbm,
            'fund_w':      fund_w,
            'fcc_limit_dbc': fcc_lim,
            'harmonics':   harmonics,
        })

    return {'attenuation_db': attenuation_db, 'bands': results}


def plot_harmonics(data: dict, output_prefix: str, radio: str) -> str:
    """Bar chart of harmonic levels (dBc) by band.  Returns PNG path."""
    band_data = [b for b in data['bands']
                 if any(not np.isnan(h['dbc']) for h in b['harmonics'])]
    if not band_data:
        return ""

    n_bands = len(band_data)
    fig, axes = plt.subplots(1, n_bands,
                             figsize=(max(8, 3.5 * n_bands), 6),
                             sharey=True)
    if n_bands == 1:
        axes = [axes]

    colors = {2: '#ff7f0e', 3: '#d62728', 4: '#9467bd'}

    for ax, bdata in zip(axes, band_data):
        freqs_mhz = [bdata['freq_hz'] / 1e6]
        fcc_lim   = bdata['fcc_limit_dbc']

        for h in bdata['harmonics']:
            if np.isnan(h['dbc']):
                continue
            bar_color = colors.get(h['n'], 'gray')
            ax.bar(h['n'], h['dbc'], color=bar_color, alpha=0.8,
                   label=f"H{h['n']}  {h['dbc']:+.1f} dBc")

        ax.axhline(fcc_lim, color='red', linestyle='--', linewidth=1.2,
                   label=f'FCC limit {fcc_lim:+.0f} dBc')
        ax.axhline(0, color='black', linestyle='-', linewidth=0.5)

        ax.set_title(
            f"{bdata['band']}\n"
            f"{format_freq_short(bdata['freq_hz'])}\n"
            f"Fund: {bdata['fund_dbm']:+.1f} dBm ({bdata['fund_w']:.0f} W)",
            fontsize=9,
        )
        ax.set_xlabel("Harmonic #", fontsize=9)
        ax.set_xticks([2, 3, 4])
        ax.set_xticklabels(['2nd', '3rd', '4th'])
        ax.grid(True, alpha=0.35, axis='y')
        ax.legend(fontsize=7, loc='upper right')
        ax.tick_params(labelsize=8)

    axes[0].set_ylabel("Level (dBc)", fontsize=10)
    fig.suptitle(
        f"Harmonic Content — {radio.upper()}  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Path attenuation: {data['attenuation_db']:.0f} dB",
        fontsize=11,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.93])
    path = f"{output_prefix}_harmonics.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def save_harmonic_txt(data: dict, output_prefix: str, radio: str) -> str:
    """Write harmonic test text report.  Returns path."""
    path = f"{output_prefix}_harmonics.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 75

    lines = [
        sep,
        "  HARMONIC CONTENT TEST",
        f"  Radio     : {radio.upper()}",
        f"  Generated : {ts}",
        f"  Path atten: {data['attenuation_db']:.0f} dB",
        f"  FCC Part 97: harmonics ≤ −43 dBc (<5 W) or −60 dBW absolute (≥5 W)",
        sep,
        "",
    ]

    for bdata in data['bands']:
        lines += [
            f"{bdata['band']}  {format_freq(bdata['freq_hz'])}  "
            f"Fundamental: {bdata['fund_dbm']:+.1f} dBm ({bdata['fund_w']:.1f} W)  "
            f"FCC limit: {bdata['fcc_limit_dbc']:+.0f} dBc",
            f"  {'Harmonic':>12}  {'Frequency':>15}  {'Level (dBm)':>12}  {'dBc':>8}  {'FCC':>6}",
            "  " + "-" * 60,
        ]
        for h in bdata['harmonics']:
            if np.isnan(h['dbc']):
                lines.append(
                    f"  {'H' + str(h['n']):>12}  {format_freq(h['freq_hz']):>15}  "
                    f"{'above SSA range':>12}"
                )
            else:
                pf = "PASS" if h['fcc_pass'] else "FAIL"
                lines.append(
                    f"  {'H' + str(h['n']):>12}  {format_freq(h['freq_hz']):>15}  "
                    f"{h['true_dbm']:>+12.1f}  {h['dbc']:>+8.1f}  {pf:>6}"
                )
        lines.append("")

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# ALC compression curve
# ---------------------------------------------------------------------------

def run_alc_test(ssa: SSA3000X, rig: RigCtld,
                 freq_hz: float, attenuation_db: float) -> dict:
    """
    Sweep RF power control setting and measure output power to characterize
    the ALC / power control linearity.

    Returns a dict with requested_level, ssa_dbm, true_dbm, true_w arrays.
    """
    print(f"\n[ALC / POWER CONTROL TEST @ {format_freq_short(freq_hz)}]")
    print(f"  Sweeping power level from 10% to 100% in {len(ALC_POWER_LEVELS)} steps")
    print(f"  {'Level %':>8}  {'SSA dBm':>8}  {'True dBm':>9}  {'True W':>8}")
    print("  " + "-" * 44)

    rig.set_mode('cw')
    rig.set_frequency(freq_hz)
    time.sleep(0.3)

    req_levels = []
    ssa_powers = []
    true_powers = []
    true_watts  = []

    for level in ALC_POWER_LEVELS:
        try:
            rig.set_rf_power(level)
            time.sleep(0.3)
            rig.ptt_on()
            ssa_dbm  = measure_peak_dbm(ssa, freq_hz, span_hz=200_000)
            true_dbm = ssa_dbm + attenuation_db
            true_w   = dbm_to_watts(true_dbm)
        finally:
            rig.ptt_off()

        print(f"  {level*100:>7.0f}%  {ssa_dbm:>+8.1f}  {true_dbm:>+9.1f}  {true_w:>7.1f} W")
        req_levels.append(level)
        ssa_powers.append(ssa_dbm)
        true_powers.append(true_dbm)
        true_watts.append(true_w)

    # Restore full power
    rig.set_rf_power(1.0)

    return {
        'freq_hz':          freq_hz,
        'attenuation_db':   attenuation_db,
        'requested_level':  req_levels,
        'ssa_dbm':          ssa_powers,
        'true_dbm':         true_powers,
        'true_w':           true_watts,
    }


def plot_alc(data: dict, output_prefix: str, radio: str) -> str:
    """Plot ALC / power control curve.  Returns PNG path."""
    levels  = np.array(data['requested_level']) * 100.0
    dbm_arr = np.array(data['true_dbm'])
    w_arr   = np.array(data['true_w'])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 8), sharex=True)

    # Output power (dBm) vs requested level
    ax1.plot(levels, dbm_arr, 'o-', color='#1f77b4', markersize=6, linewidth=1.5)
    ax1.set_ylabel('Output Power (dBm)', fontsize=10)
    ax1.set_title(
        f"ALC / Power Control — {radio.upper()}  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{format_freq_short(data['freq_hz'])}  |  "
        f"Path attenuation: {data['attenuation_db']:.0f} dB",
        fontsize=10,
    )
    ax1.grid(True, alpha=0.35)
    ax1.tick_params(labelsize=9)

    # Annotation: max power
    max_dbm = float(np.max(dbm_arr))
    max_w   = float(np.max(w_arr))
    ax1.text(0.98, 0.05, f"Max: {max_dbm:+.1f} dBm ({max_w:.1f} W)",
             transform=ax1.transAxes, ha='right', fontsize=9,
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    # Watts vs requested level
    ax2.plot(levels, w_arr, 's-', color='darkorange', markersize=6, linewidth=1.5)
    ax2.set_xlabel('Requested Power Level (%)', fontsize=10)
    ax2.set_ylabel('Output Power (W)', fontsize=10)
    ax2.set_title('Output Watts vs. Requested Level', fontsize=10)
    ax2.grid(True, alpha=0.35)
    ax2.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{output_prefix}_alc.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def save_alc_txt(data: dict, output_prefix: str, radio: str) -> str:
    """Write ALC test text report.  Returns path."""
    path = f"{output_prefix}_alc.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 65

    lines = [
        sep,
        "  ALC / POWER CONTROL CURVE",
        f"  Radio     : {radio.upper()}",
        f"  Generated : {ts}",
        f"  Frequency : {format_freq(data['freq_hz'])}",
        f"  Path atten: {data['attenuation_db']:.0f} dB",
        sep,
        "",
        f"  {'Level %':>8}  {'SSA dBm':>8}  {'True dBm':>9}  {'True W':>8}",
        "  " + "-" * 44,
    ]

    for lvl, sdbm, tdbm, tw in zip(data['requested_level'], data['ssa_dbm'],
                                    data['true_dbm'], data['true_w']):
        lines.append(f"  {lvl*100:>7.0f}%  {sdbm:>+8.1f}  {tdbm:>+9.1f}  {tw:>7.1f} W")

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# SSB carrier suppression
# ---------------------------------------------------------------------------

def run_carrier_suppression(ssa: SSA3000X, rig: RigCtld,
                             freq_hz: float, attenuation_db: float) -> dict:
    """
    Measure SSB carrier suppression.

    1. Key in USB, no audio → measure residual at carrier frequency.
    2. This is the carrier suppression (lower is better; a well-balanced SSB
       exciter should suppress the carrier by 40–60 dB below PEP output).

    For a true suppression number we compare residual carrier to the
    reference level read with the radio in CW (full carrier) mode.
    """
    print(f"\n[SSB CARRIER SUPPRESSION TEST @ {format_freq_short(freq_hz)}]")

    rig.set_frequency(freq_hz)

    # Step 1: Measure full CW carrier for reference
    print("  Step 1: measuring CW reference power ...")
    rig.set_mode('cw')
    time.sleep(0.3)
    cw_ssa_dbm = float('nan')
    try:
        rig.ptt_on()
        cw_ssa_dbm = measure_peak_dbm(ssa, freq_hz, span_hz=200_000)
    finally:
        rig.ptt_off()
    cw_dbm = cw_ssa_dbm + attenuation_db
    cw_w   = dbm_to_watts(cw_dbm)
    print(f"    CW reference: {cw_dbm:+.1f} dBm ({cw_w:.1f} W)")

    # Step 2: USB, no audio input → residual carrier
    print("  Step 2: USB, no audio — measuring carrier suppression ...")
    rig.set_mode('usb')
    time.sleep(0.3)
    res_ssa_dbm = float('nan')
    try:
        rig.ptt_on()
        # For SSB the carrier suppression is at the dial frequency in USB.
        # SSA needs a narrow span — 10 kHz is enough.
        res_ssa_dbm = measure_peak_dbm(ssa, freq_hz, span_hz=20_000)
    finally:
        rig.ptt_off()

    res_dbm = res_ssa_dbm + attenuation_db
    suppression_dbc = res_dbm - cw_dbm  # negative = good

    print(f"    Residual carrier: {res_dbm:+.1f} dBm")
    print(f"    Carrier suppression: {suppression_dbc:+.1f} dBc "
          f"({'good' if suppression_dbc < -40 else 'marginal' if suppression_dbc < -30 else 'poor'})")

    # Assessment
    if suppression_dbc < -50:
        assessment = "Excellent (>50 dBc)"
    elif suppression_dbc < -40:
        assessment = "Good (40–50 dBc)"
    elif suppression_dbc < -30:
        assessment = "Marginal (30–40 dBc)"
    else:
        assessment = "Poor (<30 dBc)"

    return {
        'freq_hz':           freq_hz,
        'attenuation_db':    attenuation_db,
        'cw_ssa_dbm':        cw_ssa_dbm,
        'cw_true_dbm':       cw_dbm,
        'cw_true_w':         cw_w,
        'residual_ssa_dbm':  res_ssa_dbm,
        'residual_true_dbm': res_dbm,
        'suppression_dbc':   suppression_dbc,
        'assessment':        assessment,
    }


def save_carrier_suppression_txt(data: dict, output_prefix: str, radio: str) -> str:
    """Write carrier suppression text report.  Returns path."""
    path = f"{output_prefix}_carrier.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 65

    lines = [
        sep,
        "  SSB CARRIER SUPPRESSION TEST",
        f"  Radio     : {radio.upper()}",
        f"  Generated : {ts}",
        f"  Frequency : {format_freq(data['freq_hz'])}",
        f"  Path atten: {data['attenuation_db']:.0f} dB",
        sep,
        "",
        f"  CW reference power  : {data['cw_true_dbm']:+.1f} dBm  ({data['cw_true_w']:.1f} W)",
        f"  Residual carrier    : {data['residual_true_dbm']:+.1f} dBm",
        f"  Carrier suppression : {data['suppression_dbc']:+.1f} dBc",
        f"  Assessment          : {data['assessment']}",
        "",
    ]

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Transmitter Test — IC-7300 / FT-891 via SSA3000X",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Connection:
  Radio TX port → attenuator chain (e.g. 3×20 dB = 60 dB total) → SSA RF In.
  Never connect a TX directly to the SSA (max +30 dBm input).

Tests:
  --power              CW carrier power vs. frequency for each band
  --harmonics          2nd/3rd/4th harmonic levels and FCC Part 97 pass/fail
  --alc                Power control linearity (10%–100% RFPOWER sweep)
  --carrier-suppression  SSB carrier suppression (USB no-audio vs. CW reference)
  --all                Run all tests

Examples:
  python transmitter_test.py --radio ic7300 --power
  python transmitter_test.py --radio ft891 --harmonics --atten 50
  python transmitter_test.py --radio ic7300 --all --freq 14200
  python transmitter_test.py --radio ic7300 --power --bands 40m 20m 10m
""",
    )

    parser.add_argument("--radio",    choices=["ic7300", "ic9700", "ft891"], default="ic7300",
                        help="Radio type (default ic7300)")
    parser.add_argument("--rig-host", default=DEFAULT_RIG_HOST, metavar="HOST",
                        help=f"rigctld host (default {DEFAULT_RIG_HOST})")
    parser.add_argument("--rig-port", type=int, default=DEFAULT_RIG_PORT, metavar="PORT",
                        help=f"rigctld port (default {DEFAULT_RIG_PORT})")
    parser.add_argument("--ssa",      default=DEFAULT_SSA_HOST, metavar="HOST",
                        help=f"SSA IP address (default {DEFAULT_SSA_HOST})")
    parser.add_argument("--atten",    type=float, default=DEFAULT_ATTENUATION, metavar="DB",
                        help=f"Total path attenuation in dB (default {DEFAULT_ATTENUATION})")

    tgrp = parser.add_argument_group("tests (combine as needed)")
    tgrp.add_argument("--power",               action="store_true",
                      help="Power output vs. frequency sweep")
    tgrp.add_argument("--harmonics",           action="store_true",
                      help="Harmonic content measurement with FCC Part 97 pass/fail")
    tgrp.add_argument("--carrier-suppression", action="store_true",
                      help="SSB carrier suppression (USB no-audio vs. CW reference)")
    tgrp.add_argument("--alc",                 action="store_true",
                      help="ALC / power control linearity curve")
    tgrp.add_argument("--all",                 action="store_true",
                      help="Run all tests")

    parser.add_argument("--freq",   type=float, default=DEFAULT_FREQ_KHZ, metavar="KHZ",
                        help=f"Frequency in kHz for single-frequency tests (default {DEFAULT_FREQ_KHZ})")
    parser.add_argument("--bands",  nargs="+", default=DEFAULT_BANDS, metavar="BAND",
                        help=f"Bands for power/harmonic sweep (default: {' '.join(DEFAULT_BANDS)})")
    parser.add_argument("--output", default=None, metavar="PREFIX",
                        help="Output prefix (default: timestamped)")

    args = parser.parse_args()

    if args.all:
        args.power = args.harmonics = args.alc = args.carrier_suppression = True

    if not any([args.power, args.harmonics, args.alc, args.carrier_suppression]):
        print("Error: specify at least one test: --power, --harmonics, --alc, "
              "--carrier-suppression, or --all")
        sys.exit(1)

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"transmitter_test_{args.radio}_{ts}"

    freq_hz = args.freq * 1_000.0

    # Validate bands
    valid_bands = [b for b in args.bands if b in TX_BANDS]
    if not valid_bands and (args.power or args.harmonics):
        unknown = [b for b in args.bands if b not in TX_BANDS]
        print(f"Error: no valid bands. Unknown: {unknown}")
        print(f"Available: {' '.join(TX_BANDS.keys())}")
        sys.exit(1)

    ssa = None
    rig = None
    ptt_active = False

    try:
        print(f"Connecting to SSA via inventory ...")
        ssa = connect(args.ssa or 'ssa')
        print(f"  {ssa.identify()}")
        ssa.disable_tracking_generator()

        print(f"Connecting to rigctld via inventory:{args.rig_port} ...")
        rig = RigCtld(args.rig_host, args.rig_port)
        print(f"  Connected (radio: {args.radio.upper()})")

        print(f"\nSetup:")
        print(f"  Radio         : {args.radio.upper()}")
        print(f"  Path atten    : {args.atten:.0f} dB")
        print(f"  Single freq   : {format_freq_short(freq_hz)}")
        print(f"  Band list     : {' '.join(valid_bands)}")
        print()

        power_data    = None
        harmonic_data = None
        alc_data      = None
        carrier_data  = None

        # --- Power test ---
        if args.power:
            power_data = run_power_test(ssa, rig, valid_bands, args.atten)

        # --- Harmonic test ---
        if args.harmonics:
            harmonic_data = run_harmonic_test(ssa, rig, valid_bands, args.atten)

        # --- ALC test ---
        if args.alc:
            alc_data = run_alc_test(ssa, rig, freq_hz, args.atten)

        # --- Carrier suppression ---
        if args.carrier_suppression:
            carrier_data = run_carrier_suppression(ssa, rig, freq_hz, args.atten)

        # --- Save outputs ---
        print("\n[SAVING RESULTS]")

        if power_data:
            txt_path  = save_power_txt(power_data, args.output, args.radio)
            json_path = f"{args.output}_power.json"
            with open(json_path, "w") as jf:
                json.dump({
                    'timestamp':   datetime.now().isoformat(),
                    'radio':       args.radio,
                    'ssa_host':    args.ssa,
                    'atten_db':    args.atten,
                    'bands':       power_data['bands'],
                }, jf, indent=2)
            print(f"Text   → {txt_path}")
            print(f"JSON   → {json_path}")
            try:
                png_path = plot_power(power_data, args.output, args.radio)
                if png_path:
                    print(f"Plot   → {png_path}")
            except Exception as exc:
                print(f"Power plot failed: {exc}")

        if harmonic_data:
            txt_path  = save_harmonic_txt(harmonic_data, args.output, args.radio)
            json_path = f"{args.output}_harmonics.json"

            def _jsonify_band(b):
                out = dict(b)
                out['harmonics'] = [dict(h) for h in b['harmonics']]
                return out

            with open(json_path, "w") as jf:
                json.dump({
                    'timestamp':   datetime.now().isoformat(),
                    'radio':       args.radio,
                    'ssa_host':    args.ssa,
                    'atten_db':    args.atten,
                    'bands':       [_jsonify_band(b) for b in harmonic_data['bands']],
                }, jf, indent=2)
            print(f"Text   → {txt_path}")
            print(f"JSON   → {json_path}")
            try:
                png_path = plot_harmonics(harmonic_data, args.output, args.radio)
                if png_path:
                    print(f"Plot   → {png_path}")
            except Exception as exc:
                print(f"Harmonics plot failed: {exc}")

        if alc_data:
            txt_path  = save_alc_txt(alc_data, args.output, args.radio)
            json_path = f"{args.output}_alc.json"
            with open(json_path, "w") as jf:
                json.dump({
                    'timestamp':   datetime.now().isoformat(),
                    'radio':       args.radio,
                    'ssa_host':    args.ssa,
                    **alc_data,
                }, jf, indent=2)
            print(f"Text   → {txt_path}")
            print(f"JSON   → {json_path}")
            try:
                png_path = plot_alc(alc_data, args.output, args.radio)
                if png_path:
                    print(f"Plot   → {png_path}")
            except Exception as exc:
                print(f"ALC plot failed: {exc}")

        if carrier_data:
            txt_path  = save_carrier_suppression_txt(carrier_data, args.output, args.radio)
            json_path = f"{args.output}_carrier.json"
            with open(json_path, "w") as jf:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'radio':     args.radio,
                    'ssa_host':  args.ssa,
                    **carrier_data,
                }, jf, indent=2)
            print(f"Text   → {txt_path}")
            print(f"JSON   → {json_path}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to instrument: {exc}")
        print("Verify SSA is on and rigctld is running.")
        sys.exit(1)
    except OSError as exc:
        print(f"\nNetwork error: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        # ALWAYS ensure PTT is released
        if rig is not None:
            try:
                rig.ptt_off()
            except Exception:
                pass
            try:
                rig.close()
            except Exception:
                pass
        if ssa is not None:
            try:
                ssa.disable_tracking_generator()
                ssa.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
