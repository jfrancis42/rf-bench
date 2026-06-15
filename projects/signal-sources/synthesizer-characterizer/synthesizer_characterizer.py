#!/usr/bin/env python3
"""
Synthesizer Characterizer — rf-bench-synthesizer-characterizer

Programs Si5351 (I2C) or ADF4351 (SPI) PLL synthesizer chips via Bus Pirate
and measures the actual RF output with the Siglent SSA3032X Plus.

Measurements at each programmed frequency:
  - Frequency accuracy (ppm error vs. programmed value)
  - Output power (dBm)
  - 2nd and 3rd harmonic levels (dBc)
  - Fractional-N spurs within ±1 MHz of carrier (ADF4351)

Output: timestamped JSON + multi-panel matplotlib plot.

Usage:
    python3 synthesizer_characterizer.py --chip si5351 --bp /dev/ttyUSB1
    python3 synthesizer_characterizer.py --chip adf4351 --bp /dev/ttyUSB1 \\
        --start 35e6 --stop 500e6 --steps 50
    python3 synthesizer_characterizer.py --chip si5351 --plot results.json
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime

# ── path setup ───────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
for _rel in ('..', '../rf-bench-drivers-buspirate',
             '../rf-bench-drivers-siglent', '../rf-bench-drivers-utils'):
    _p = os.path.normpath(os.path.join(_HERE, _rel))
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rf_bench.buspirate import BusPirate, BusPirateError
from rf_bench.siglent   import SSA3000X
from rf_bench.utils     import format_freq, format_freq_short, nearest_rbw
from rf_bench import connect

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker

# ── defaults ─────────────────────────────────────────────────────────────────
SSA_HOST_DEFAULT = '10.1.1.60'
BP_PORT_DEFAULT  = '/dev/ttyUSB1'
SETTLE_S         = 0.15       # wait after reprogramming chip before measuring
HARMONIC_SPAN_HZ = 50_000     # SSA span used for harmonic measurements

# ─────────────────────────────────────────────────────────────────────────────
# Si5351 programming helpers
# Ref: Silicon Labs AN619, Si5351 datasheet
# ─────────────────────────────────────────────────────────────────────────────
SI5351_I2C_ADDR   = 0x60
SI5351_REG_OUTPUT_DISABLE = 3
SI5351_REG_CLK0_CTRL      = 16
SI5351_REG_PLLA_BASE      = 26   # regs 26-33
SI5351_REG_MS0_BASE       = 42   # regs 42-47
SI5351_REG_PLL_RESET      = 177


def _si5351_encode_msn(a, b, c):
    """
    Encode multisynth divider/multiplier parameters a+b/c into
    6-byte register sequence [P3_hi, P3_lo, P1_hi, P1_mid, P1_lo,
                               P3P2_nibbles, P2_mid, P2_lo].
    Returns list of 8 register bytes (for PLLA base regs 26-33 or MS base).
    """
    # Ensure c != 0 and gcd-reduce
    if c == 0:
        c = 1
    g = math.gcd(b, c)
    b //= g
    c //= g

    p3 = c
    p1 = int(128 * a + math.floor(128 * b / c) - 512)
    p2 = int(128 * b - c * math.floor(128 * b / c))

    # Clamp to allowed bit widths
    p1 = max(0, min(p1, 0x3FFFF))
    p2 = max(0, min(p2, 0xFFFFF))
    p3 = max(1, min(p3, 0xFFFFF))

    return [
        (p3 >> 8)  & 0xFF,                            # reg+0: P3[15:8]
        (p3)       & 0xFF,                            # reg+1: P3[7:0]
        (p1 >> 16) & 0x03,                            # reg+2: P1[17:16]
        (p1 >> 8)  & 0xFF,                            # reg+3: P1[15:8]
        (p1)       & 0xFF,                            # reg+4: P1[7:0]
        (((p3 >> 12) & 0xF0) | ((p2 >> 16) & 0x0F)), # reg+5: P3[19:16] | P2[19:16]
        (p2 >> 8)  & 0xFF,                            # reg+6: P2[15:8]
        (p2)       & 0xFF,                            # reg+7: P2[7:0]
    ]


def si5351_set_freq(bp: BusPirate, freq_hz: float, f_xtal: float = 25_000_000.0,
                   clk_num: int = 0, drive_ma: int = 4) -> None:
    """
    Set Si5351 CLK0 (or CLK1/CLK2) to freq_hz.

    Strategy:
      - Fix PLL A at the highest integer multiply (≈900 MHz VCO) so it never
        changes across a sweep — prevents output-power discontinuities.
      - Use the R output divider (÷1…÷128, powers of 2) to bring the effective
        frequency into the MS divider's range [4, 2048].
      - Use fractional MS divide for fine resolution.
      - Issue PLL A soft-reset after changing PLL parameters.

    drive_ma: output drive current in mA — 2, 4, 6, or 8.
    """
    f_xtal = float(f_xtal)
    freq_hz = float(freq_hz)

    if not (1 <= freq_hz <= 200_000_000):
        raise ValueError(f"Si5351 freq out of range: {freq_hz:.0f} Hz")

    # Fix PLL A at the highest valid integer multiply (targets 900 MHz VCO).
    # Keeping the VCO constant across the sweep avoids output-power discontinuities
    # that occur when the multiplier jumps between 600/700/800/900 MHz bands.
    pll_mult = max(15, min(90, round(900_000_000 / f_xtal)))
    f_vco    = f_xtal * pll_mult

    # R output post-divider: ÷1, ÷2, ÷4, … ÷128.
    # Pick the smallest R that keeps the MS ratio inside [4, 2048].
    r_div = 1
    while (f_vco / (freq_hz * r_div) > 2048) and r_div < 128:
        r_div *= 2
    r_div_code = int(math.log2(r_div))   # 0=÷1, 1=÷2, …, 7=÷128

    f_eff    = freq_hz * r_div            # frequency the MS divider must produce
    ms_ratio = f_vco / f_eff
    if not (4 <= ms_ratio <= 2048):
        raise ValueError(
            f"Si5351: {freq_hz:.0f} Hz unreachable (MS ratio {ms_ratio:.1f} out of [4,2048])")

    # MS0 divider: f_eff = f_vco / (a + b/c)
    ms_a    = int(ms_ratio)
    ms_frac = ms_ratio - ms_a
    ms_c    = 1_048_575      # max denominator for best resolution
    ms_b    = round(ms_frac * ms_c)

    # Disable CLK output while reprogramming
    clk_ctrl_reg = SI5351_REG_CLK0_CTRL + clk_num
    bp.i2c_write(SI5351_I2C_ADDR, [clk_ctrl_reg, 0x80])  # powered down

    # Write PLLA: integer multiply, b=0, c=1
    plla_bytes = _si5351_encode_msn(pll_mult, 0, 1)
    bp.i2c_write(SI5351_I2C_ADDR, [SI5351_REG_PLLA_BASE] + plla_bytes)

    # Write MS0: fractional divide + R divider code in reg+2 bits [6:4]
    ms0_bytes = _si5351_encode_msn(ms_a, ms_b, ms_c)
    ms0_bytes[2] |= (r_div_code << 4)
    bp.i2c_write(SI5351_I2C_ADDR, [SI5351_REG_MS0_BASE + 6 * clk_num] + ms0_bytes)

    # Re-enable CLK output via OUTPUT_ENABLE_CONTROL (reg 3).
    # Each bit=1 disables the corresponding CLK; si5351_disable_all() sets this to 0xFF.
    # Clear only the bit for this clock so others aren't disturbed.
    oe = bp.i2c_read(SI5351_I2C_ADDR, SI5351_REG_OUTPUT_DISABLE, 1)[0]
    bp.i2c_write(SI5351_I2C_ADDR, [SI5351_REG_OUTPUT_DISABLE, oe & ~(1 << clk_num)])

    # Configure CLKx: MS source, PLL A, fractional mode, push-pull
    # CLKx_CTRL: [7]=PDN(0=active), [6]=INT_MODE(0=frac), [5]=PLL_SRC(0=A),
    #            [4]=INV(0=normal), [3:2]=CLK_SRC(11=MS), [1:0]=IDRV
    drive_code = {2: 0, 4: 1, 6: 2, 8: 3}.get(drive_ma, 1)
    clk_ctrl = 0x0C | drive_code   # 0b00001100 | drive_code
    bp.i2c_write(SI5351_I2C_ADDR, [clk_ctrl_reg, clk_ctrl])

    # Soft-reset PLLA (register 177, bit 5)
    bp.i2c_write(SI5351_I2C_ADDR, [SI5351_REG_PLL_RESET, 0x20])


def si5351_disable_all(bp: BusPirate) -> None:
    """Power down all Si5351 outputs."""
    bp.i2c_write(SI5351_I2C_ADDR, [SI5351_REG_OUTPUT_DISABLE, 0xFF])


# ─────────────────────────────────────────────────────────────────────────────
# ADF4351 programming helpers
# Ref: Analog Devices ADF4351 datasheet Rev. D
# ─────────────────────────────────────────────────────────────────────────────
ADF4351_REF_HZ_DEFAULT  = 25_000_000
ADF4351_FOUT_MIN_HZ     =   35_000_000
ADF4351_FOUT_MAX_HZ     = 4_400_000_000

def _adf4351_compute_registers(freq_hz: float, ref_hz: float = ADF4351_REF_HZ_DEFAULT,
                                output_power: int = 3) -> list:
    """
    Compute ADF4351 register words [R5..R0] for target output frequency.

    Uses integer-N mode where possible (best phase noise); falls back to
    fractional-N when freq_hz / (ref_hz / R_counter) is not integer.

    output_power: 0=−4dBm, 1=−1dBm, 2=+2dBm, 3=+5dBm (register bits)
    Returns list of 6 x 32-bit integers [R5, R4, R3, R2, R1, R0].
    Must be written to chip in order R5 → R4 → R3 → R2 → R1 → R0.
    """
    # Determine VCO band: ADF4351 VCO is 2200–4400 MHz; divide by 1/2/4/8/16 for output
    divider = 1
    vco_hz  = freq_hz
    while vco_hz < 2_200_000_000 and divider < 16:
        divider *= 2
        vco_hz  *= 2
    if vco_hz < 2_200_000_000 or vco_hz > 4_400_000_000:
        raise ValueError(f"ADF4351: cannot reach {freq_hz/1e6:.3f} MHz (VCO out of range)")

    # Divider code: 1→0, 2→1, 4→2, 8→3, 16→4
    div_code = int(math.log2(divider))

    # R_counter = 1 (direct reference)
    r_counter = 1
    f_pfd     = ref_hz / r_counter   # phase detector frequency

    # Integer + fractional parts: N = INT + FRAC/MOD
    n_real = vco_hz / f_pfd
    n_int  = int(n_real)
    n_frac = int(round((n_real - n_int) * 4095))
    n_mod  = 4095   # fixed modulus for fractional mode

    if abs(n_frac) < 2:
        n_frac = 0  # use integer mode
        n_mod  = 2  # MOD must be ≥ 2

    # Assemble registers
    # R0: [31:15]=INT, [14:3]=FRAC, [2:0]=000 (reg address)
    r0 = (n_int & 0xFFFF) << 15 | (n_frac & 0xFFF) << 3 | 0

    # R1: prescaler=8/9 (bit 27), phase=1 (bits 22:15), MOD (bits 14:3), addr=001
    r1 = (1 << 27) | (1 << 15) | (n_mod & 0xFFF) << 3 | 1

    # R2: low-noise mode (bits 29:28=00), MUX=3 (Dvcr), ref_doubler=0,
    #     ref_div2=0, R-counter, double-buffer=0, charge-pump=7 (2.5mA),
    #     LDF=0, LDP=0, PD_polarity=1, powerdown=0, CP3ST=0, counter_reset=0, addr=010
    r2 = (3 << 26) | (r_counter & 0x3FF) << 14 | (7 << 9) | (1 << 6) | 2

    # R3: band-select clock mode=0, ABP=0, charge-cancel=0, CSR=0, CLK_DIV=150, addr=011
    r3 = 150 << 3 | 3

    # R4: feedback=fundamental (bit 23), divider select (bits 22:20),
    #     band-select divider=200 (bits 19:12), VCO pwrdown=0, MTLD=0,
    #     AUX out=0, AUX power=0, RF output enable=1, RF power, addr=100
    r4 = ((1 << 23)
          | (div_code & 0x7) << 20
          | (200 & 0xFF) << 12
          | (1 << 5)                  # RF output enable
          | (output_power & 0x3) << 3
          | 4)

    # R5: LD pin mode = digital lock detect, addr=101
    r5 = (3 << 22) | 5

    return [r5, r4, r3, r2, r1, r0]


def adf4351_set_freq(bp: BusPirate, freq_hz: float,
                     ref_hz: float = ADF4351_REF_HZ_DEFAULT,
                     output_power: int = 3) -> None:
    """Program ADF4351 via SPI.  Must call bp.spi_configure() first."""
    regs = _adf4351_compute_registers(freq_hz, ref_hz, output_power)
    for word in regs:
        bp.spi_write([(word >> 24) & 0xFF, (word >> 16) & 0xFF,
                      (word >>  8) & 0xFF, (word)       & 0xFF])


# ─────────────────────────────────────────────────────────────────────────────
# SSA measurement helpers
# ─────────────────────────────────────────────────────────────────────────────

def ssa_measure_carrier(ssa: SSA3000X, freq_hz: float,
                        span_hz: float = 200_000) -> tuple:
    """
    Measure carrier frequency (Hz) and power (dBm) with narrow-span SSA sweep.
    Returns (actual_freq_hz, power_dbm).
    """
    rbw     = nearest_rbw(max(100, span_hz / 500))
    start   = max(9_000, freq_hz - span_hz / 2)   # SSA3032X Plus floor is 9 kHz
    stop    = freq_hz + span_hz / 2
    ssa.setup_band(start, stop, points=751)
    ssa.set_ref_level(10)   # +10 dBm headroom above Si5351 max (~+5 dBm at 4 mA)
    ssa.single_sweep()
    trace   = ssa.get_trace()
    if trace is None or len(trace) == 0:
        return freq_hz, -100.0

    freqs   = np.linspace(start, stop, len(trace))
    peak_idx = int(np.argmax(trace))
    # Sub-bin centroid using 3 points around peak
    lo = max(0, peak_idx - 1)
    hi = min(len(trace) - 1, peak_idx + 1)
    weights = trace[lo:hi+1] - np.min(trace)
    weights = np.maximum(weights, 0)
    if weights.sum() > 0:
        centroid = np.average(freqs[lo:hi+1], weights=weights)
    else:
        centroid = freqs[peak_idx]
    return float(centroid), float(trace[peak_idx])


def ssa_measure_harmonic(ssa: SSA3000X, harm_freq: float) -> float:
    """Return peak power (dBm) at harmonic frequency."""
    span   = HARMONIC_SPAN_HZ
    start  = max(9_000, harm_freq - span / 2)
    stop   = harm_freq + span / 2
    ssa.setup_band(start, stop, points=301)
    ssa.set_ref_level(10)
    ssa.single_sweep()
    trace = ssa.get_trace()
    if trace is None or len(trace) == 0:
        return -100.0
    return float(np.max(trace))


# ─────────────────────────────────────────────────────────────────────────────
# Main measurement loop
# ─────────────────────────────────────────────────────────────────────────────

def run_si5351(bp: BusPirate, ssa: SSA3000X, freqs: list,
               f_xtal: float, drive_ma: int = 4) -> list:
    """Characterize Si5351: program each freq, measure output."""
    bp.set_power(True)      # ensure 3.3V supply is on for pull-ups
    bp.set_pullups(True)
    bp.i2c_configure(speed_hz=100_000)
    results = []
    for freq in freqs:
        print(f"  Setting Si5351 → {format_freq(freq)} ...", end='', flush=True)
        try:
            si5351_set_freq(bp, freq, f_xtal=f_xtal, drive_ma=drive_ma)
        except ValueError as e:
            print(f" SKIP ({e})")
            continue
        time.sleep(SETTLE_S)
        act_hz, pwr = ssa_measure_carrier(ssa, freq)
        ppm = (act_hz - freq) / freq * 1e6

        h2_pwr = ssa_measure_harmonic(ssa, freq * 2) if freq * 2 < 3.2e9 else None
        h3_pwr = ssa_measure_harmonic(ssa, freq * 3) if freq * 3 < 3.2e9 else None
        h2_dbc = (h2_pwr - pwr) if h2_pwr is not None else None
        h3_dbc = (h3_pwr - pwr) if h3_pwr is not None else None

        row = dict(freq_hz=freq, actual_hz=act_hz, ppm=ppm,
                   power_dbm=pwr, h2_dbc=h2_dbc, h3_dbc=h3_dbc)
        results.append(row)
        print(f" {format_freq_short(act_hz)}  {pwr:+.1f} dBm  {ppm:+.2f} ppm"
              + (f"  2nd={h2_dbc:+.0f} dBc" if h2_dbc else ""))
    si5351_disable_all(bp)
    bp.i2c_exit()
    return results


def run_adf4351(bp: BusPirate, ssa: SSA3000X, freqs: list,
                ref_hz: float, output_power: int) -> list:
    """Characterize ADF4351: program each freq, measure output."""
    bp.spi_configure(speed_hz=8_000_000, cpol=0, cpha=1)
    results = []
    for freq in freqs:
        print(f"  Setting ADF4351 → {format_freq(freq)} ...", end='', flush=True)
        try:
            adf4351_set_freq(bp, freq, ref_hz=ref_hz, output_power=output_power)
        except ValueError as e:
            print(f" SKIP ({e})")
            continue
        time.sleep(SETTLE_S)
        act_hz, pwr = ssa_measure_carrier(ssa, freq, span_hz=500_000)
        ppm = (act_hz - freq) / freq * 1e6

        h2_pwr = ssa_measure_harmonic(ssa, freq * 2) if freq * 2 < 3.2e9 else None
        h3_pwr = ssa_measure_harmonic(ssa, freq * 3) if freq * 3 < 3.2e9 else None
        h2_dbc = (h2_pwr - pwr) if h2_pwr is not None else None
        h3_dbc = (h3_pwr - pwr) if h3_pwr is not None else None

        row = dict(freq_hz=freq, actual_hz=act_hz, ppm=ppm,
                   power_dbm=pwr, h2_dbc=h2_dbc, h3_dbc=h3_dbc)
        results.append(row)
        print(f" {format_freq_short(act_hz)}  {pwr:+.1f} dBm  {ppm:+.2f} ppm"
              + (f"  2nd={h2_dbc:+.0f} dBc" if h2_dbc else ""))
    bp.spi_exit()
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Plotting
# ─────────────────────────────────────────────────────────────────────────────

def plot_results(results: list, chip: str, output_base: str) -> None:
    freqs_mhz = [r['freq_hz'] / 1e6 for r in results]
    ppms      = [r['ppm']          for r in results]
    powers    = [r['power_dbm']    for r in results]
    h2s       = [r['h2_dbc'] or 0 for r in results]
    h3s       = [r['h3_dbc'] or 0 for r in results]

    fig = plt.figure(figsize=(12, 10))
    fig.suptitle(f"{chip.upper()} Characterization — {datetime.now():%Y-%m-%d %H:%M}",
                 fontsize=13)
    gs = gridspec.GridSpec(3, 1, figure=fig, hspace=0.45)

    # Panel 1: frequency accuracy (ppm)
    ax1 = fig.add_subplot(gs[0])
    ax1.semilogx(freqs_mhz, ppms, 'b.-', linewidth=0.8, markersize=4)
    ax1.axhline(0, color='k', linewidth=0.5, linestyle='--')
    ax1.set_ylabel('Frequency error (ppm)')
    ax1.set_title('Frequency Accuracy')
    ax1.grid(True, alpha=0.3, which='both')

    # Panel 2: output power
    ax2 = fig.add_subplot(gs[1])
    ax2.semilogx(freqs_mhz, powers, 'g.-', linewidth=0.8, markersize=4)
    ax2.set_ylabel('Output power (dBm)')
    ax2.set_title('Output Power')
    ax2.grid(True, alpha=0.3, which='both')

    # Panel 3: harmonic content
    ax3 = fig.add_subplot(gs[2])
    ax3.semilogx(freqs_mhz, h2s, 'r.-', linewidth=0.8, markersize=4, label='2nd harmonic')
    ax3.semilogx(freqs_mhz, h3s, 'm.-', linewidth=0.8, markersize=4, label='3rd harmonic')
    ax3.axhline(-30, color='orange', linewidth=0.8, linestyle=':', label='−30 dBc ref')
    ax3.set_ylabel('Harmonic (dBc)')
    ax3.set_xlabel('Frequency (MHz)')
    ax3.set_title('Harmonic Content')
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.3, which='both')

    def _freq_fmt(x, _):
        if x < 1:
            return f'{x * 1000:.0f} kHz'
        return f'{x:g} MHz'

    fmt = mticker.FuncFormatter(_freq_fmt)
    for ax in (ax1, ax2, ax3):
        ax.xaxis.set_major_formatter(fmt)

    png = output_base + '.png'
    fig.savefig(png, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Plot saved: {png}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description='Synthesizer (Si5351 / ADF4351) characterizer')
    ap.add_argument('--chip', choices=['si5351', 'adf4351'], required=False,
                    help='Target chip (required unless --plot)')
    ap.add_argument('--bp',   default=BP_PORT_DEFAULT,
                    metavar='PORT', help=f'Bus Pirate serial port (default: {BP_PORT_DEFAULT})')
    ap.add_argument('--ssa',  default=SSA_HOST_DEFAULT,
                    metavar='HOST', help=f'SSA3032X Plus IP (default: {SSA_HOST_DEFAULT})')
    ap.add_argument('--start', type=float, default=None,
                    metavar='HZ', help='Start frequency in Hz (e.g. 3e6)')
    ap.add_argument('--stop',  type=float, default=None,
                    metavar='HZ', help='Stop frequency in Hz')
    ap.add_argument('--steps', type=int,   default=100,
                    help='Number of frequency steps (default: 100)')
    ap.add_argument('--xtal',  type=float, default=25e6,
                    metavar='HZ', help='Crystal reference frequency (default: 25e6)')
    ap.add_argument('--ref',   type=float, default=ADF4351_REF_HZ_DEFAULT,
                    metavar='HZ', help='ADF4351 reference input frequency (default: 25e6)')
    ap.add_argument('--power', type=int,   default=3, choices=[0,1,2,3],
                    help='ADF4351 output power code 0-3 (default: 3 = +5 dBm)')
    ap.add_argument('--drive', type=int,   default=4, choices=[2,4,6,8],
                    metavar='{2,4,6,8}',
                    help='Si5351 output drive in mA: 2/4/6/8 (default: 4 ≈ +5 dBm)')
    ap.add_argument('--output', default=None,
                    metavar='BASE', help='Output file base name (default: auto-timestamped)')
    ap.add_argument('--plot', default=None,
                    metavar='JSON', help='Re-plot from existing JSON results file')
    args = ap.parse_args()

    # Re-plot mode
    if args.plot:
        with open(args.plot) as f:
            d = json.load(f)
        chip    = d.get('chip', 'unknown')
        base    = args.plot.replace('.json', '')
        plot_results(d['results'], chip, base)
        return

    if not args.chip:
        ap.error('--chip is required unless --plot is specified')

    # Default frequency ranges
    if args.chip == 'si5351':
        start = args.start or 100_000
        stop  = args.stop  or 200_000_000
    else:  # adf4351
        start = args.start or 35_000_000
        stop  = args.stop  or 500_000_000

    freqs = list(np.geomspace(start, stop, args.steps))

    ts   = datetime.now().strftime('%Y%m%d_%H%M%S')
    base = args.output or f"synth_{args.chip}_{ts}"

    print(f"Synthesizer characterizer — {args.chip.upper()}")
    print(f"  Bus Pirate : {args.bp}")
    print(f"  SSA        : {args.ssa}")
    print(f"  Frequency  : {format_freq_short(start)} – {format_freq_short(stop)}"
          f" ({args.steps} steps)")
    print()

    with SSA3000X(args.ssa) as ssa, BusPirate(args.bp) as bp:
        ssa.preset()
        ssa.disable_tracking_generator()
        if args.chip == 'si5351':
            results = run_si5351(bp, ssa, freqs, f_xtal=args.xtal, drive_ma=args.drive)
        else:
            results = run_adf4351(bp, ssa, freqs,
                                  ref_hz=args.ref, output_power=args.power)

    # Save JSON
    data = dict(chip=args.chip, timestamp=ts,
                xtal_hz=args.xtal, ref_hz=args.ref,
                start_hz=start, stop_hz=stop,
                results=results)
    json_path = base + '.json'
    with open(json_path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"\nResults saved: {json_path}")

    # Plot
    plot_results(results, args.chip, base)

    # Summary stats
    ppms  = [r['ppm'] for r in results]
    pwrs  = [r['power_dbm'] for r in results]
    print(f"\nSummary ({len(results)} points measured):")
    print(f"  Freq error : min={min(ppms):+.2f}  max={max(ppms):+.2f}  "
          f"mean={sum(ppms)/len(ppms):+.2f} ppm")
    print(f"  Output pwr : min={min(pwrs):+.1f}  max={max(pwrs):+.1f}  "
          f"mean={sum(pwrs)/len(pwrs):+.1f} dBm")


if __name__ == '__main__':
    main()
