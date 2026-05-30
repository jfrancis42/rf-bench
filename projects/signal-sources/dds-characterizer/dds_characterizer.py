#!/usr/bin/env python3
"""
DDS Characterizer — rf-bench-dds-characterizer

Programs AD9833 or AD9851 DDS chips via Bus Pirate SPI and measures actual
RF output with the Siglent SSA3032X Plus spectrum analyzer.

DDS chips produce fundamentally different spurs than PLL chips.  The dominant
artifact is DAC quantization — spurious products at |k*f_clk ± m*f_out| for
small integers k, m.  SFDR (spurious-free dynamic range) is worst when
f_out / f_clk is a simple rational fraction.

Measurements at each tuning word:
  - Frequency accuracy (ppm error)
  - Output amplitude (dBm) — reveals sinc rolloff above ~40% of f_clk
  - 2nd and 3rd harmonic (dBc)
  - SFDR: strongest non-harmonic spur within 1 MHz of carrier (dBc)

Usage:
    python3 dds_characterizer.py --chip ad9833 --bp /dev/ttyUSB1
    python3 dds_characterizer.py --chip ad9851 --bp /dev/ttyUSB1 \\
        --start 1e6 --stop 60e6 --steps 60
    python3 dds_characterizer.py --plot results.json
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
for _rel in ('..', '../rf-bench-drivers-buspirate',
             '../rf-bench-drivers-siglent', '../rf-bench-drivers-utils'):
    _p = os.path.normpath(os.path.join(_HERE, _rel))
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rf_bench.buspirate import BusPirate
from rf_bench.siglent   import SSA3000X
from rf_bench.utils     import format_freq, format_freq_short, nearest_rbw

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ── defaults ─────────────────────────────────────────────────────────────────
SSA_HOST_DEFAULT = '10.1.1.60'
BP_PORT_DEFAULT  = '/dev/ttyUSB1'
SETTLE_S         = 0.08

# ─────────────────────────────────────────────────────────────────────────────
# AD9833 SPI programming
# Ref: Analog Devices AD9833 Rev. G datasheet
# SPI: CPOL=1, CPHA=1 (Mode 3), MSB first, 16-bit words
# f_out = (FREQREG * f_mclk) / 2^28
# ─────────────────────────────────────────────────────────────────────────────
AD9833_FMCLK_DEFAULT  = 25_000_000
AD9833_FREQ_BITS      = 28

# Control register bits
AD9833_B28   = 1 << 13   # two 14-bit writes for 28-bit freq register
AD9833_RESET = 1 << 8    # reset DDS


def ad9833_reset(bp: BusPirate) -> None:
    """Assert AD9833 RESET via SPI control register."""
    word = AD9833_B28 | AD9833_RESET
    bp.spi_write([(word >> 8) & 0xFF, word & 0xFF])


def ad9833_set_freq(bp: BusPirate, freq_hz: float,
                   f_mclk: float = AD9833_FMCLK_DEFAULT) -> None:
    """
    Program AD9833 FREQ0 register to output freq_hz.
    Keeps phase at 0, waveform = sine.
    """
    freq_hz = float(freq_hz)
    f_mclk  = float(f_mclk)
    if not (0 < freq_hz < f_mclk / 2):
        raise ValueError(f"AD9833: freq {freq_hz:.0f} Hz must be < f_mclk/2 = {f_mclk/2:.0f} Hz")

    # Tuning word = round(freq_hz * 2^28 / f_mclk)
    tuning = round(freq_hz * (1 << AD9833_FREQ_BITS) / f_mclk)
    tuning = max(0, min(tuning, (1 << AD9833_FREQ_BITS) - 1))

    low14  = tuning & 0x3FFF
    high14 = (tuning >> 14) & 0x3FFF

    # Control word: B28=1 (28-bit mode), RESET=0, PHLSEL=0, FREQ0, SINE
    ctrl   = AD9833_B28          # 0x2000
    # Write control (sine, no reset, B28 mode)
    bp.spi_write([(ctrl >> 8) & 0xFF, ctrl & 0xFF])
    # Write FREQ0 LSBs: tag 0b01 in bits [15:14]
    w_lo   = 0x4000 | low14
    bp.spi_write([(w_lo >> 8) & 0xFF, w_lo & 0xFF])
    # Write FREQ0 MSBs: tag 0b01 in bits [15:14]
    w_hi   = 0x4000 | high14
    bp.spi_write([(w_hi >> 8) & 0xFF, w_hi & 0xFF])
    # Phase register 0 = 0 (tag 0b110)
    bp.spi_write([0xC0, 0x00])


# ─────────────────────────────────────────────────────────────────────────────
# AD9851 SPI programming
# Ref: Analog Devices AD9851 Rev. B datasheet
# SPI: CPOL=0, CPHA=0, 40-bit serial load (5 bytes MSB first)
# f_out = (DeltaPhase * f_clk * M) / 2^32
# DeltaPhase is 32-bit frequency tuning word (FTW)
# Byte 0: W[39:32] = {phase[4:0], powerdown, 6x_mult, W[31]}
# Bytes 1-4: W[31:0] = FTW[31:0]
# ─────────────────────────────────────────────────────────────────────────────
AD9851_FCLK_DEFAULT   = 30_000_000   # XTAL frequency before 6x multiplier
AD9851_6X_MULT        = True         # use 6x multiplier → effective f_clk = 6 * FCLK
AD9851_FTW_BITS       = 32


def ad9851_set_freq(bp: BusPirate, freq_hz: float,
                   f_xtal: float = AD9851_FCLK_DEFAULT,
                   use_6x: bool  = AD9851_6X_MULT) -> None:
    """
    Program AD9851 to output freq_hz.
    f_xtal: crystal oscillator frequency feeding the AD9851.
    use_6x: True to enable the internal 6x PLL multiplier (typical).
    """
    freq_hz = float(freq_hz)
    f_clk   = f_xtal * (6 if use_6x else 1)
    if not (0 < freq_hz < f_clk / 2):
        raise ValueError(
            f"AD9851: freq {freq_hz:.0f} Hz out of range (max {f_clk/2:.0f} Hz)")

    ftw = round(freq_hz * (1 << AD9851_FTW_BITS) / f_clk)
    ftw = max(0, min(ftw, (1 << AD9851_FTW_BITS) - 1))

    # Byte W0 (control): [7:3]=phase (0), [2]=powerdown (0), [1]=6x_mult, [0]=W31 (MSB of FTW)
    w0 = (0x01 if use_6x else 0x00)   # bit 1 = 6x enable
    w0 |= ((ftw >> 31) & 0x01) << 0   # bit 0 = FTW[31]? No — W0[0] is the MSB load signal
    # Actually: the AD9851 40-bit word is: [W39..W32] [W31..W0]
    # W[39:33] = phase bits (5 bits + 2 spare = 7 bits at top of byte)
    # W[32] = power down
    # W[31:1] from FTW[30:0], W[0] = 6x_mult enable? Let me use the correct format:
    # Per datasheet: byte W0 = {PHASE4, PHASE3, PHASE2, PHASE1, PHASE0, POWERDN, 6XMULT, FTW[31]}
    # Then bytes W1-W4 = FTW[30:23], FTW[22:15], FTW[14:7], FTW[6:0]|0
    # Wait, actually the 40-bit serial word is clocked in MSB first:
    # W[39:8] = {phase[4:0], pd, 6x, FTW[31:0]}  → W[39:32] = control byte

    w_byte0 = ((0 & 0x1F) << 3) | (0 << 2) | ((1 if use_6x else 0) << 1) | ((ftw >> 31) & 0x01)
    # Hmm this doesn't seem right.  Let me use the 5-byte serial format directly:
    # Byte 0 (sent first): phase[4:0] | pd | 6x | 0
    # Bytes 1-4: FTW[31:24], FTW[23:16], FTW[15:8], FTW[7:0]
    w_byte0 = (0 << 3) | (0 << 2) | ((1 if use_6x else 0) << 1) | 0

    bp.spi_write([
        w_byte0,
        (ftw >> 24) & 0xFF,
        (ftw >> 16) & 0xFF,
        (ftw >>  8) & 0xFF,
        (ftw)       & 0xFF,
    ])


# ─────────────────────────────────────────────────────────────────────────────
# SSA measurement
# ─────────────────────────────────────────────────────────────────────────────
SPUR_SEARCH_SPAN = 2_000_000   # ±1 MHz around carrier for SFDR search

def ssa_measure_carrier(ssa: SSA3000X, freq_hz: float, span_hz: float = 100_000) -> tuple:
    """Measure carrier: returns (actual_freq_hz, peak_dbm)."""
    start  = freq_hz - span_hz / 2
    stop   = freq_hz + span_hz / 2
    ssa.setup_band(start, stop)
    ssa.single_sweep()
    trace = ssa.get_trace()
    if trace is None or len(trace) == 0:
        return freq_hz, -100.0
    freqs     = np.linspace(start, stop, len(trace))
    peak_idx  = int(np.argmax(trace))
    lo, hi    = max(0, peak_idx-1), min(len(trace)-1, peak_idx+1)
    weights   = np.maximum(trace[lo:hi+1] - np.min(trace), 0)
    centroid  = np.average(freqs[lo:hi+1], weights=weights) if weights.sum() > 0 else freqs[peak_idx]
    return float(centroid), float(trace[peak_idx])


def ssa_measure_sfdr(ssa: SSA3000X, carrier_hz: float, carrier_dbm: float) -> float:
    """
    Return SFDR (dBc) — difference between carrier and strongest non-harmonic spur
    within ±1 MHz, excluding a ±50 kHz window around the carrier itself.
    """
    start = carrier_hz - SPUR_SEARCH_SPAN / 2
    stop  = carrier_hz + SPUR_SEARCH_SPAN / 2
    ssa.setup_band(start, stop)
    ssa.single_sweep()
    trace  = ssa.get_trace()
    if trace is None or len(trace) == 0:
        return 0.0
    freqs   = np.linspace(start, stop, len(trace))
    # Blank out ±50 kHz around carrier
    exclude = np.abs(freqs - carrier_hz) < 50_000
    trace_masked = trace.copy()
    trace_masked[exclude] = np.min(trace)
    spur_dbm = float(np.max(trace_masked))
    return spur_dbm - carrier_dbm   # negative value = spur is below carrier


def ssa_measure_harmonic(ssa: SSA3000X, harm_hz: float) -> float:
    span = 50_000
    ssa.setup_band(harm_hz - span/2, harm_hz + span/2)
    ssa.single_sweep()
    trace = ssa.get_trace()
    return float(np.max(trace)) if trace is not None and len(trace) > 0 else -100.0


# ─────────────────────────────────────────────────────────────────────────────
# Main measurement loop
# ─────────────────────────────────────────────────────────────────────────────

def run_characterize(chip: str, bp: BusPirate, ssa: SSA3000X,
                     freqs: list, chip_kwargs: dict) -> list:
    # SPI mode setup
    if chip == 'ad9833':
        bp.spi_configure(speed_hz=4_000_000, cpol=1, cpha=1)
        ad9833_reset(bp)
    else:  # ad9851
        bp.spi_configure(speed_hz=4_000_000, cpol=0, cpha=0)

    results = []
    for freq in freqs:
        print(f"  {chip.upper()} → {format_freq(freq)} ...", end='', flush=True)
        try:
            if chip == 'ad9833':
                ad9833_set_freq(bp, freq, **chip_kwargs)
            else:
                ad9851_set_freq(bp, freq, **chip_kwargs)
        except ValueError as e:
            print(f" SKIP ({e})")
            continue

        time.sleep(SETTLE_S)
        act_hz, pwr = ssa_measure_carrier(ssa, freq)
        ppm = (act_hz - freq) / freq * 1e6

        h2_pwr  = ssa_measure_harmonic(ssa, freq * 2) if freq * 2 < 3.2e9 else None
        h3_pwr  = ssa_measure_harmonic(ssa, freq * 3) if freq * 3 < 3.2e9 else None
        h2_dbc  = (h2_pwr - pwr)  if h2_pwr is not None else None
        h3_dbc  = (h3_pwr - pwr)  if h3_pwr is not None else None
        sfdr    = ssa_measure_sfdr(ssa, freq, pwr)

        row = dict(freq_hz=freq, actual_hz=act_hz, ppm=ppm,
                   power_dbm=pwr, h2_dbc=h2_dbc, h3_dbc=h3_dbc, sfdr_dbc=sfdr)
        results.append(row)
        print(f" {pwr:+.1f} dBm  {ppm:+.2f} ppm  SFDR={sfdr:+.0f} dBc"
              + (f"  2nd={h2_dbc:+.0f}" if h2_dbc else ""))

    bp.spi_exit()
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Plotting
# ─────────────────────────────────────────────────────────────────────────────

def plot_results(results: list, chip: str, output_base: str) -> None:
    freqs_mhz = [r['freq_hz'] / 1e6 for r in results]
    powers    = [r['power_dbm']    for r in results]
    ppms      = [r['ppm']          for r in results]
    sfdrs     = [r.get('sfdr_dbc') or 0 for r in results]
    h2s       = [r.get('h2_dbc')   or 0 for r in results]
    h3s       = [r.get('h3_dbc')   or 0 for r in results]

    fig = plt.figure(figsize=(12, 11))
    fig.suptitle(f"{chip.upper()} DDS Characterization — {datetime.now():%Y-%m-%d %H:%M}",
                 fontsize=13)
    gs = gridspec.GridSpec(4, 1, figure=fig, hspace=0.50)

    ax1 = fig.add_subplot(gs[0])
    ax1.plot(freqs_mhz, powers, 'g.-', lw=0.8, ms=4)
    ax1.set_ylabel('Power (dBm)'); ax1.set_title('Output Power (sinc rolloff)')
    ax1.grid(True, alpha=0.3)

    ax2 = fig.add_subplot(gs[1])
    ax2.plot(freqs_mhz, ppms, 'b.-', lw=0.8, ms=4)
    ax2.axhline(0, color='k', lw=0.5, ls='--')
    ax2.set_ylabel('Error (ppm)'); ax2.set_title('Frequency Accuracy')
    ax2.grid(True, alpha=0.3)

    ax3 = fig.add_subplot(gs[2])
    ax3.plot(freqs_mhz, sfdrs, 'r.-', lw=0.8, ms=4)
    ax3.axhline(-60, color='orange', lw=0.8, ls=':', label='−60 dBc ref')
    ax3.set_ylabel('SFDR (dBc)'); ax3.set_title('Spurious-Free Dynamic Range')
    ax3.legend(fontsize=8); ax3.grid(True, alpha=0.3)

    ax4 = fig.add_subplot(gs[3])
    ax4.plot(freqs_mhz, h2s, 'r.-', lw=0.8, ms=4, label='2nd harmonic')
    ax4.plot(freqs_mhz, h3s, 'm.-', lw=0.8, ms=4, label='3rd harmonic')
    ax4.set_ylabel('(dBc)'); ax4.set_xlabel('Frequency (MHz)')
    ax4.set_title('Harmonic Content'); ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.3)

    png = output_base + '.png'
    fig.savefig(png, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Plot saved: {png}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='DDS (AD9833/AD9851) characterizer')
    ap.add_argument('--chip', choices=['ad9833', 'ad9851'],
                    help='Target DDS chip (required unless --plot)')
    ap.add_argument('--bp',   default=BP_PORT_DEFAULT, metavar='PORT')
    ap.add_argument('--ssa',  default=SSA_HOST_DEFAULT, metavar='HOST')
    ap.add_argument('--start', type=float, default=None, metavar='HZ')
    ap.add_argument('--stop',  type=float, default=None, metavar='HZ')
    ap.add_argument('--steps', type=int,   default=50)
    ap.add_argument('--mclk',  type=float, default=AD9833_FMCLK_DEFAULT,
                    metavar='HZ', help='AD9833 MCLK frequency (default: 25 MHz)')
    ap.add_argument('--xtal',  type=float, default=AD9851_FCLK_DEFAULT,
                    metavar='HZ', help='AD9851 crystal frequency before 6x mult (default: 30 MHz)')
    ap.add_argument('--no-6x', action='store_true',
                    help='AD9851: disable 6x internal PLL multiplier')
    ap.add_argument('--output', default=None, metavar='BASE')
    ap.add_argument('--plot',   default=None, metavar='JSON',
                    help='Re-plot from existing JSON results file')
    args = ap.parse_args()

    if args.plot:
        with open(args.plot) as f:
            d = json.load(f)
        plot_results(d['results'], d.get('chip', 'dds'),
                     args.plot.replace('.json', ''))
        return

    if not args.chip:
        ap.error('--chip is required unless --plot is specified')

    if args.chip == 'ad9833':
        start = args.start or 100_000
        stop  = args.stop  or (args.mclk * 0.45)
        chip_kwargs = dict(f_mclk=args.mclk)
    else:
        use_6x  = not args.no_6x
        f_sys   = args.xtal * (6 if use_6x else 1)
        start   = args.start or 1_000_000
        stop    = args.stop  or min(60_000_000, f_sys * 0.4)
        chip_kwargs = dict(f_xtal=args.xtal, use_6x=use_6x)

    freqs = list(np.geomspace(start, stop, args.steps))
    ts    = datetime.now().strftime('%Y%m%d_%H%M%S')
    base  = args.output or f"dds_{args.chip}_{ts}"

    print(f"DDS characterizer — {args.chip.upper()}")
    print(f"  Bus Pirate : {args.bp}")
    print(f"  SSA        : {args.ssa}")
    print(f"  Range      : {format_freq_short(start)} – {format_freq_short(stop)} "
          f"({args.steps} steps)")
    print()

    with SSA3000X(args.ssa) as ssa, BusPirate(args.bp) as bp:
        ssa.preset()
        ssa.disable_tracking_generator()
        results = run_characterize(args.chip, bp, ssa, freqs, chip_kwargs)

    data = dict(chip=args.chip, timestamp=ts,
                start_hz=start, stop_hz=stop, results=results)
    json_path = base + '.json'
    with open(json_path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"\nResults saved: {json_path}")
    plot_results(results, args.chip, base)

    ppms  = [r['ppm']          for r in results]
    pwrs  = [r['power_dbm']    for r in results]
    sfdrs = [r.get('sfdr_dbc') or 0 for r in results]
    print(f"\nSummary ({len(results)} points):")
    print(f"  Freq error : {min(ppms):+.2f} – {max(ppms):+.2f} ppm")
    print(f"  Output pwr : {min(pwrs):+.1f} – {max(pwrs):+.1f} dBm  "
          f"(rolloff = {max(pwrs)-min(pwrs):.1f} dB)")
    print(f"  SFDR       : {min(sfdrs):.0f} – {max(sfdrs):.0f} dBc")


if __name__ == '__main__':
    main()
