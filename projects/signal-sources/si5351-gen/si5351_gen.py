#!/usr/bin/env python3
"""
si5351_gen.py — Si5351 3-output I2C clock generator via Bus Pirate

Curses TUI for interactive control, or CLI mode for scripted use.

Hardware: Si5351A breakout ($5) wired to Bus Pirate I2C pins.
Outputs: CLK0, CLK1, CLK2 — each independently settable from ~3 kHz to ~200 MHz.

PLL assignment:
  CLK0 → PLL-A (exclusive)
  CLK1 → PLL-B  )  CLK1 and CLK2 share PLL-B.  Setting either one
  CLK2 → PLL-B  )  reprograms PLL-B; the last write wins.

Usage:
    python3 si5351_gen.py [--bp PORT] [--addr 0x60]
    python3 si5351_gen.py --cli --clk0 10e6 --clk1 14.2e6 [--clk2 7e6] [--stay]
    python3 si5351_gen.py --off           # disable all outputs and exit
"""

import argparse
import curses
import json
import math
import os
import sys
import time

# ── sys.path so we work both installed and from source tree ──────────────────
# The buspirate driver lives at <repo>/drivers/buspirate. This file is at
# <repo>/projects/signal-sources/si5351-gen, so the driver is three levels up.
_here = os.path.dirname(os.path.abspath(__file__))
for _rel in (
    os.path.join(_here, '..', '..', '..', 'drivers', 'buspirate'),  # monorepo source
    os.path.join(_here, '..', 'rf-bench-drivers-buspirate'),        # legacy layout
    os.path.join(_here, '..', 'rf-bench'),
):
    _p = os.path.abspath(_rel)
    if os.path.isdir(_p):
        sys.path.insert(0, _p)

from rf_bench.buspirate import BusPirate


# ── Si5351 register map ───────────────────────────────────────────────────────
SI5351_ADDR_DEFAULT  = 0x60
SI5351_REG_OEB       = 3       # Output enable (active-low per bit)
SI5351_REG_CLK_BASE  = 16      # CLK0=16, CLK1=17, CLK2=18
SI5351_REG_PLLA      = 26      # 8 bytes: regs 26-33
SI5351_REG_PLLB      = 34      # 8 bytes: regs 34-41
SI5351_REG_MS0       = 42      # 8 bytes: regs 42-49
SI5351_REG_MS1       = 50      # 8 bytes: regs 50-57
SI5351_REG_MS2       = 58      # 8 bytes: regs 58-65
SI5351_REG_PLL_RST   = 177     # 0x20=reset PLL-A, 0x80=reset PLL-B
SI5351_REG_XTAL_LOAD = 183     # Crystal load capacitance
SI5351_REG_CLK0_PHOFF = 165    # CLK0 initial phase offset; CLK1=166, CLK2=167

SI5351_XTAL_LOAD_6PF  = 0x52
SI5351_XTAL_LOAD_8PF  = 0x92
SI5351_XTAL_LOAD_10PF = 0xD2   # Most common breakouts (Adafruit, generic)

SI5351_XTAL_HZ_DEFAULT = 25_000_000   # 25 MHz crystal

# CLK control register: drive bits for each output
DRIVE_BITS  = {2: 0b00, 4: 0b01, 6: 0b10, 8: 0b11}
DRIVE_MA    = [2, 4, 6, 8]

# Default output drive strength for quadrature (I/Q) mode. 2 mA is the lowest
# setting (highest output impedance, smallest delivered swing) — the safe
# starting point when driving an AD831 mixer LO, whose input must stay under
# ±1 V while a 3.3 V CMOS square at higher drive would exceed that. Adjust via
# the drive_ma argument to set_quadrature(), or change this module default.
QUAD_DEFAULT_DRIVE_MA = 2

# PLL assignment: CLK n → PLL A (0) or B (1)
CLK_PLL     = [0, 1, 1]           # CLK0→PLL-A, CLK1/CLK2→PLL-B

# CLK control reg: bit5=PLL_SRC (0=A, 1=B), bits[4:3]=11 (MS src), bits[1:0]=drive
CLK_PLLSRC  = [0x00, 0x20, 0x20]  # bit5 set for CLK1, CLK2

MS_REGS     = [SI5351_REG_MS0, SI5351_REG_MS1, SI5351_REG_MS2]
PLL_REGS    = [SI5351_REG_PLLA, SI5351_REG_PLLB]
PHOFF_REGS  = [SI5351_REG_CLK0_PHOFF,
               SI5351_REG_CLK0_PHOFF + 1,
               SI5351_REG_CLK0_PHOFF + 2]

VCO_MIN     = 600_000_000
VCO_MAX     = 900_000_000
FREQ_MIN    =       3_000
FREQ_MAX    = 200_000_000

# ── Quadrature (I/Q) synthesis limits ─────────────────────────────────────────
# For a deterministic 90° phase relationship the Si5351 requires BOTH outputs to
# share one PLL and use the SAME even integer output divider `d`. The 90° shift
# is then produced by loading the Q channel's phase-offset register with `d`
# (each phase LSB = one VCO period / 4; T_out/4 works out to exactly `d` LSBs).
#
#   f_out = f_vco / d,  f_vco in [600, 900] MHz,  d even.
#
# The phase-offset register is 7 bits (max 127), and we avoid the divide-by-4
# hardware special case, so the usable even divider range is [8, 126]. That sets
# the hard frequency window for pure-Si5351 quadrature:
#
#   f_min = VCO_MIN / QUAD_DIV_MAX = 600e6 / 126 ≈ 4.762 MHz
#   f_max = VCO_MAX / QUAD_DIV_MIN = 900e6 /   8 = 112.5   MHz
#
# 40m/30m/20m/17m/15m/12m/10m/6m are all comfortably inside this window.
# 80m and 160m fall below f_min and CANNOT be done with the Si5351 alone — they
# need an external ÷4 Johnson counter (e.g. 74AC74) fed at 4× the target.
QUAD_DIV_MIN = 8
QUAD_DIV_MAX = 126
QUAD_FREQ_MIN = VCO_MIN / QUAD_DIV_MAX   # ≈ 4.762 MHz
QUAD_FREQ_MAX = VCO_MAX / QUAD_DIV_MIN   # = 112.5 MHz

PRESETS_FILE = os.path.expanduser('~/.si5351_presets.json')


# ── AN619 multisynth encoding ─────────────────────────────────────────────────

def _encode_multisynth(a, b, c, r_div=0):
    """
    Encode AN619 multisynth parameters into 8 register bytes.
    a = integer part, b/c = fractional part, r_div = 0..7 (R = 2^r_div)
    """
    if b == 0:
        # Integer mode — cleaner phase noise
        p1 = 128 * a - 512
        p2 = 0
        p3 = 1
    else:
        p1 = 128 * a + int(128 * b / c) - 512
        p2 = 128 * b - c * int(128 * b / c)
        p3 = c

    regs = [
        (p3 >> 8) & 0xFF,
        p3 & 0xFF,
        (r_div << 4) | ((p1 >> 16) & 0x03),
        (p1 >> 8) & 0xFF,
        p1 & 0xFF,
        ((p3 >> 12) & 0xF0) | ((p2 >> 16) & 0x0F),
        (p2 >> 8) & 0xFF,
        p2 & 0xFF,
    ]
    return regs


def _best_pll_params(target_vco, xtal_hz):
    """
    Find best integer PLL multiplier a such that a*xtal_hz is in [600, 900] MHz
    and closest to target_vco.
    Returns (a, vco_actual_hz).
    """
    best_a   = None
    best_err = float('inf')
    best_vco = 0
    for a in range(15, 91):   # AN619 valid range
        vco = a * xtal_hz
        if VCO_MIN <= vco <= VCO_MAX:
            err = abs(vco - target_vco)
            if err < best_err:
                best_err = err
                best_a   = a
                best_vco = vco
    return best_a, best_vco


def _solve_frequency(freq_hz, xtal_hz):
    """
    Given desired output frequency, compute:
      - PLL integer multiplier (a_pll)
      - MS divider as rational a_ms + b_ms/c_ms
      - R divider exponent r_div (0..7)
      - Actual achievable frequency

    Returns dict with keys: a_pll, a_ms, b_ms, c_ms, r_div, actual_hz, vco_hz
    Returns None if frequency is out of range.
    """
    if not (FREQ_MIN <= freq_hz <= FREQ_MAX):
        return None

    # Choose R divider so that f_ms = freq_hz * R is in a reasonable MS range
    # MS divider range: 4..2048 (integer), or 4+fractional
    r_div = 0
    f_ms  = freq_hz
    while f_ms < VCO_MIN / 2048 and r_div < 7:
        r_div += 1
        f_ms  *= 2

    # Target VCO: mid of valid range gives most headroom
    # We want vco = f_ms * ms_div, ms_div in [4, 2048]
    # Try to pick ms_div that hits vco close to 800 MHz centre
    target_vco = 800_000_000
    target_ms  = target_vco / f_ms
    # Clamp ms_div to [4, 2048]
    ms_div_int = max(4, min(2048, round(target_ms)))
    vco_target = f_ms * ms_div_int

    # PLL: integer multiplier only (a*xtal = vco)
    a_pll, vco_actual = _best_pll_params(vco_target, xtal_hz)
    if a_pll is None:
        return None

    # MS divider: fractional a_ms + b_ms/c_ms = vco_actual / f_ms
    ms_exact = vco_actual / f_ms
    a_ms     = int(ms_exact)
    frac     = ms_exact - a_ms

    # Use denominator c = 1_000_000 for reasonable precision
    c_ms = 1_000_000
    b_ms = round(frac * c_ms)

    # Simplify fraction
    if b_ms > 0:
        g    = math.gcd(b_ms, c_ms)
        b_ms //= g
        c_ms //= g
    else:
        b_ms = 0
        c_ms = 1

    # Compute actual output frequency
    if b_ms == 0:
        ms_actual = a_ms
    else:
        ms_actual = a_ms + b_ms / c_ms

    actual_hz = vco_actual / ms_actual / (2 ** r_div)

    return {
        'a_pll': a_pll, 'vco_hz': vco_actual,
        'a_ms': a_ms, 'b_ms': b_ms, 'c_ms': c_ms,
        'r_div': r_div, 'actual_hz': actual_hz
    }


def _solve_quadrature(freq_hz, xtal_hz):
    """
    Solve synthesis parameters for a QUADRATURE (I/Q) pair.

    Unlike _solve_frequency (integer PLL + fractional multisynth), quadrature
    demands the OPPOSITE split:

      - The output divider `d` must be an EVEN INTEGER, identical on both the I
        and Q channels, because the 90° phase step is expressed in units of `d`
        (phase-offset register = d gives exactly T_out/4). r_div is forced to 0.
      - All fine frequency resolution therefore has to come from a FRACTIONAL
        PLL multiplier a + b/c, since `d` is quantised to even integers.

    Strategy: pick the even divider whose ideal VCO (= freq*d) sits closest to
    the centre of the VCO band, then realise that VCO exactly with a fractional
    PLL feedback ratio.

    Returns dict: a_pll, b_pll, c_pll, div, phase_q, vco_hz, actual_hz
    or None if freq is outside the pure-Si5351 quadrature window.
    """
    if not (QUAD_FREQ_MIN <= freq_hz <= QUAD_FREQ_MAX):
        return None

    # Choose the even divider that lands the VCO nearest 750 MHz (band centre),
    # subject to the VCO staying inside [600, 900] MHz.
    target_vco = 750_000_000
    best = None
    for d in range(QUAD_DIV_MIN, QUAD_DIV_MAX + 1, 2):   # even only
        vco = freq_hz * d
        if not (VCO_MIN <= vco <= VCO_MAX):
            continue
        err = abs(vco - target_vco)
        if best is None or err < best[0]:
            best = (err, d, vco)
    if best is None:
        return None

    _, div, vco_target = best

    # Fractional PLL feedback: a + b/c = vco_target / xtal_hz.
    # AN619 requires a in [15, 90], b in [0, c), c in [1, 1048575].
    ratio = vco_target / xtal_hz
    a_pll = int(ratio)
    if not (15 <= a_pll <= 90):
        return None
    frac = ratio - a_pll
    c_pll = 1_048_575                      # max denominator → finest resolution
    b_pll = round(frac * c_pll)
    if b_pll >= c_pll:                     # guard rounding to the next integer
        b_pll = c_pll - 1
    if b_pll > 0:
        g = math.gcd(b_pll, c_pll)
        b_pll //= g
        c_pll //= g
    else:
        b_pll, c_pll = 0, 1

    vco_actual = xtal_hz * (a_pll + b_pll / c_pll)
    actual_hz  = vco_actual / div

    return {
        'a_pll': a_pll, 'b_pll': b_pll, 'c_pll': c_pll,
        'div': div, 'phase_q': div,        # phase-offset LSBs for a 90° Q shift
        'vco_hz': vco_actual, 'actual_hz': actual_hz,
    }


# ── Si5351 driver ─────────────────────────────────────────────────────────────

class Si5351:
    """
    Si5351 I2C clock generator driver via Bus Pirate.

    Example:
        bp = BusPirate('/dev/ttyUSB0')
        gen = Si5351(bp, xtal_hz=25e6)
        gen.set_freq(0, 10e6)
        gen.enable(0, True)
        gen.enable(1, False)
        gen.close()
    """

    def __init__(self, bp, addr=SI5351_ADDR_DEFAULT, xtal_hz=SI5351_XTAL_HZ_DEFAULT,
                 load_cap=SI5351_XTAL_LOAD_10PF, power=True, pullups=True):
        self.bp      = bp
        self.addr    = addr
        self.xtal_hz = int(xtal_hz)

        # State tracking
        self.freq_hz  = [0,  0,  0 ]  # Requested frequencies
        self.actual_hz= [0., 0., 0.]  # Actual achievable
        self.drive_ma = [2,  2,  2 ]  # Drive strength mA
        self.enabled  = [False, False, False]
        self._params  = [None, None, None]   # Last _solve_frequency result
        self._pll_vco = [0, 0]               # Current VCO for each PLL

        # Bring up I2C on the Bus Pirate. The current driver exposes
        # i2c_configure() (BPIO2/BBIO1); older revisions used i2c_start().
        if hasattr(bp, 'i2c_configure'):
            bp.i2c_configure()
        else:
            bp.i2c_start()
        # The Si5351 breakout is powered from the Bus Pirate on this bench, and
        # needs bus pull-ups. Enable both (harmless if externally powered).
        if power and hasattr(bp, 'set_power'):
            try: bp.set_power(True)
            except Exception: pass
        if pullups and hasattr(bp, 'set_pullups'):
            try: bp.set_pullups(True)
            except Exception: pass
        time.sleep(0.2)   # let rails settle before programming

        # Init chip
        self._write_reg(SI5351_REG_XTAL_LOAD, load_cap)
        # Power down all outputs initially
        for clk in range(3):
            self._write_reg(SI5351_REG_CLK_BASE + clk, 0x80)  # PDN bit
        # Disable all outputs via OEB
        self._write_reg(SI5351_REG_OEB, 0xFF)

    def _write_reg(self, reg, val):
        self.bp.i2c_write(self.addr, [reg, val & 0xFF])

    def _write_regs(self, start_reg, data):
        """Write consecutive registers starting at start_reg."""
        for i, v in enumerate(data):
            self._write_reg(start_reg + i, v)

    def _program_pll(self, pll_idx, a_pll):
        """Program PLL A or B with integer multiplier a_pll (15-90)."""
        # Integer mode: b=0, c=1
        regs = _encode_multisynth(a_pll, 0, 1)
        self._write_regs(PLL_REGS[pll_idx], regs)
        self._pll_vco[pll_idx] = a_pll * self.xtal_hz

    def _program_pll_frac(self, pll_idx, a_pll, b_pll, c_pll):
        """Program PLL A or B with fractional feedback a + b/c (for quadrature)."""
        regs = _encode_multisynth(a_pll, b_pll, c_pll)
        self._write_regs(PLL_REGS[pll_idx], regs)
        self._pll_vco[pll_idx] = int(self.xtal_hz * (a_pll + b_pll / c_pll))

    def _set_phase(self, clk, phase_lsbs):
        """Set CLKn initial phase offset (0..127 LSBs of one VCO period / 4)."""
        self._write_reg(PHOFF_REGS[clk], phase_lsbs & 0x7F)

    def _program_ms(self, clk, a_ms, b_ms, c_ms, r_div):
        """Program multisynth divider for CLKn."""
        regs = _encode_multisynth(a_ms, b_ms, c_ms, r_div)
        self._write_regs(MS_REGS[clk], regs)

    def _update_clk_ctrl(self, clk):
        """Write CLK control register for given channel."""
        if self.enabled[clk]:
            drive = DRIVE_BITS.get(self.drive_ma[clk], 0b00)
            val   = CLK_PLLSRC[clk] | 0x0C | drive   # 0x0C = bits[3:2]=11 (MS src)
        else:
            val = 0x80   # PDN (power down)
        self._write_reg(SI5351_REG_CLK_BASE + clk, val)

    def _update_oeb(self):
        """Update output enable register from self.enabled[]."""
        # OEB bit = 0 means enabled, bit = 1 means disabled
        mask = 0xF8  # CLK3-7 always disabled
        for clk in range(3):
            if not self.enabled[clk]:
                mask |= (1 << clk)
        self._write_reg(SI5351_REG_OEB, mask)

    def set_freq(self, clk, freq_hz):
        """
        Set output frequency for CLKn. Does not enable the output.
        Returns actual achievable frequency (float Hz), or None if out of range.
        """
        freq_hz = int(freq_hz)
        params  = _solve_frequency(freq_hz, self.xtal_hz)
        if params is None:
            return None

        self._params[clk]   = params
        self.freq_hz[clk]   = freq_hz
        self.actual_hz[clk] = params['actual_hz']

        pll_idx = CLK_PLL[clk]

        # For CLK1/CLK2 sharing PLL-B: only reprogram PLL if the other channel
        # is not currently using it, or if we must change VCO.
        # Simple policy: always reprogram — last write wins on shared PLL-B.
        self._program_pll(pll_idx, params['a_pll'])
        self._program_ms(clk, params['a_ms'], params['b_ms'], params['c_ms'], params['r_div'])

        # Reset the affected PLL
        reset_bit = 0x20 if pll_idx == 0 else 0x80
        self._write_reg(SI5351_REG_PLL_RST, reset_bit)

        return params['actual_hz']

    def set_quadrature(self, freq_hz, i_clk=0, q_clk=1, sideband='usb',
                       drive_ma=QUAD_DEFAULT_DRIVE_MA):
        """
        Configure two outputs as a phase-locked I/Q (quadrature) pair.

        This is a SPECIAL MODE that deliberately breaks the normal PLL map: both
        the I and Q outputs are forced onto PLL-A and given the same even integer
        divider, which is what the Si5351 requires for a deterministic 90° phase
        relationship. The 90° shift is produced entirely in hardware via the
        Q channel's phase-offset register, so the two outputs stay locked.

            gen.set_quadrature(7_074_000)            # 40m, CLK0=I, CLK1=Q, USB
            gen.set_quadrature(14_010_000, sideband='lsb')
            gen.enable(0, True); gen.enable(1, True)

        Args:
            freq_hz  : output frequency, Hz. Must be in the pure-Si5351
                       quadrature window (~4.762 MHz .. 112.5 MHz).
            i_clk    : CLK index for the in-phase (I) output (default 0).
            q_clk    : CLK index for the quadrature (Q) output (default 1).
            sideband : 'usb'/'i-lead' → Q lags I by 90°; 'lsb'/'q-lead' →
                       Q leads I by 90° (swaps which channel carries the offset).
            drive_ma : drive strength (2/4/6/8 mA) applied to both outputs.
                       Defaults to QUAD_DEFAULT_DRIVE_MA (2 mA, the lowest) —
                       chosen for driving an AD831 mixer LO: a 3.3 V CMOS square
                       at higher drive over-drives the AD831's ±1 V LO input, so
                       the weakest setting (highest output Z) is the safe start.
                       Raise it only if a specific load needs more level.

        Returns:
            actual_hz (float) on success, or None if freq is outside the window
            (e.g. 80m/160m — use an external ÷4 counter for those) or i_clk==q_clk.

        NOTE: Both outputs are driven from PLL-A. If CLK2 was previously set with
        set_freq() on PLL-B it is unaffected; a prior CLK0/CLK1 frequency on this
        PLL is overwritten.
        """
        if i_clk == q_clk:
            return None
        if i_clk not in (0, 1, 2) or q_clk not in (0, 1, 2):
            return None

        params = _solve_quadrature(int(freq_hz), self.xtal_hz)
        if params is None:
            return None

        div     = params['div']
        phase   = params['phase_q']            # == div → 90°
        sb      = sideband.lower()
        # For USB we want Q to LAG I: I offset 0, Q offset `div`.
        # For LSB we want Q to LEAD I: put the offset on I instead.
        if sb in ('lsb', 'q-lead', 'q_lead'):
            i_phase, q_phase = phase, 0
        else:                                  # usb / i-lead / default
            i_phase, q_phase = 0, phase

        # Both channels use PLL-A (index 0) in quadrature mode.
        pll_idx = 0

        # 1. Program PLL-A with the fractional feedback ratio.
        self._program_pll_frac(pll_idx, params['a_pll'], params['b_pll'],
                               params['c_pll'])

        # 2. Program the SAME even integer divider on both channels (r_div=0).
        for clk in (i_clk, q_clk):
            self._program_ms(clk, div, 0, 1, 0)

        # 3. Load phase offsets (this is what creates the 90°).
        self._set_phase(i_clk, i_phase)
        self._set_phase(q_clk, q_phase)

        # 4. Force both channels' control regs onto PLL-A, MS source, enabled.
        if drive_ma in DRIVE_MA:
            self.drive_ma[i_clk] = drive_ma
            self.drive_ma[q_clk] = drive_ma
        for clk in (i_clk, q_clk):
            self.freq_hz[clk]   = int(freq_hz)
            self.actual_hz[clk] = params['actual_hz']
            self._params[clk]   = params
            self.enabled[clk]   = True
            drive = DRIVE_BITS.get(self.drive_ma[clk], 0b00)
            # PLL_SRC=0 (PLL-A) regardless of the channel's normal assignment,
            # MS as source (0x0C), plus drive bits.
            self._write_reg(SI5351_REG_CLK_BASE + clk, 0x0C | drive)
        self._update_oeb()

        # 5. A SINGLE PLL-A reset AFTER everything is programmed aligns the two
        #    multisynths so the phase offset takes effect. (Per-channel resets,
        #    as set_freq does, would destroy the phase relationship — hence the
        #    dedicated code path here.)
        self._write_reg(SI5351_REG_PLL_RST, 0x20)

        return params['actual_hz']

    def clear_phase(self, clk):
        """Reset a channel's phase offset to 0 (undo quadrature on that CLK)."""
        self._set_phase(clk, 0)

    def enable(self, clk, state):
        """Enable or disable CLKn output."""
        self.enabled[clk] = bool(state)
        self._update_clk_ctrl(clk)
        self._update_oeb()

    def set_drive(self, clk, ma):
        """Set output drive strength in mA (2, 4, 6, or 8)."""
        if ma not in DRIVE_MA:
            return
        self.drive_ma[clk] = ma
        if self.enabled[clk]:
            self._update_clk_ctrl(clk)

    def all_on(self):
        for clk in range(3):
            self.enabled[clk] = True
        for clk in range(3):
            self._update_clk_ctrl(clk)
        self._update_oeb()

    def all_off(self):
        for clk in range(3):
            self.enabled[clk] = False
        for clk in range(3):
            self._update_clk_ctrl(clk)
        self._update_oeb()

    def close(self):
        self.all_off()
        # Older driver revisions had i2c_stop(); the current BPIO2/BBIO1 driver
        # tears the bus down on bp.close(), so only call it if present.
        if hasattr(self.bp, 'i2c_stop'):
            self.bp.i2c_stop()


# ── Frequency formatting helpers ──────────────────────────────────────────────

def _fmt_hz(hz):
    """Format frequency with units. Always shows full precision."""
    if hz == 0:
        return '---'
    if hz >= 1_000_000:
        return f'{hz/1e6:.6f} MHz'
    if hz >= 1_000:
        return f'{hz/1e3:.3f} kHz'
    return f'{hz:.0f} Hz'


def _fmt_hz_short(hz):
    """Compact display for TUI headers."""
    if hz == 0:
        return '---'
    if hz >= 1_000_000:
        v = hz / 1e6
        s = f'{v:.4f}'.rstrip('0').rstrip('.')
        return f'{s} MHz'
    if hz >= 1_000:
        v = hz / 1e3
        s = f'{v:.3f}'.rstrip('0').rstrip('.')
        return f'{s} kHz'
    return f'{hz:.0f} Hz'


def _parse_freq(s):
    """
    Parse frequency string to Hz. Accepts Hz/kHz/MHz suffixes or bare numbers.
    Examples: '14.2e6', '14.2MHz', '14200kHz', '14200000'
    Returns float Hz or None on error.
    """
    s = s.strip().replace(' ', '').upper()
    if not s:
        return None
    try:
        mult = 1
        if s.endswith('MHZ'):
            mult = 1e6; s = s[:-3]
        elif s.endswith('KHZ'):
            mult = 1e3; s = s[:-3]
        elif s.endswith('HZ'):
            s = s[:-2]
        elif s.endswith('M'):
            mult = 1e6; s = s[:-1]
        elif s.endswith('K'):
            mult = 1e3; s = s[:-1]
        return float(s) * mult
    except ValueError:
        return None


# ── Preset storage ────────────────────────────────────────────────────────────

def _load_presets():
    if not os.path.exists(PRESETS_FILE):
        return {}
    try:
        with open(PRESETS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_presets(presets):
    with open(PRESETS_FILE, 'w') as f:
        json.dump(presets, f, indent=2)


# ── Curses TUI ────────────────────────────────────────────────────────────────

HELP_LINES = [
    'Keys:',
    '  ↑↓       Select channel',
    '  SPACE     Toggle output on/off',
    '  f         Enter frequency',
    '  d         Cycle drive strength (2/4/6/8 mA)',
    '  a         All outputs ON',
    '  z         All outputs OFF',
    '  p         Save preset',
    '  l         Load preset',
    '  q / ESC   Quit',
]

CLK_NAMES = ['CLK0', 'CLK1', 'CLK2']
PLL_NAMES = ['PLL-A', 'PLL-B', 'PLL-B']


def _draw_ui(stdscr, gen, sel, status, presets):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    # Title
    title = ' Si5351 3-Output Clock Generator '
    stdscr.addstr(0, max(0, (w - len(title)) // 2), title,
                  curses.A_BOLD | curses.color_pair(1))

    # Column headers
    stdscr.addstr(2, 2,  'Ch   PLL    Freq (requested)     Freq (actual)       Drive  En',
                  curses.A_UNDERLINE)

    # Channel rows
    for clk in range(3):
        y    = 4 + clk * 2
        attr = curses.color_pair(3) | curses.A_BOLD if clk == sel else curses.A_NORMAL

        arrow = '→' if clk == sel else '  '
        en    = '●' if gen.enabled[clk] else '○'
        en_col= curses.color_pair(2) if gen.enabled[clk] else curses.color_pair(4)

        f_req = _fmt_hz_short(gen.freq_hz[clk])   if gen.freq_hz[clk]   else '---'
        f_act = _fmt_hz_short(gen.actual_hz[clk]) if gen.actual_hz[clk] else '---'

        # Error flag for shared PLL-B
        pll_warn = ''
        if clk > 0:
            other = 2 if clk == 1 else 1
            if gen.enabled[other] and gen.freq_hz[other] != gen.freq_hz[clk]:
                pll_warn = '*'   # PLL-B is shared; only one freq wins

        row = (f'{arrow} {CLK_NAMES[clk]}  {PLL_NAMES[clk]}{pll_warn:<2}'
               f' {f_req:<20} {f_act:<20} {gen.drive_ma[clk]}mA  ')

        if y < h - 1:
            stdscr.addstr(y, 1, row, attr)
        if y < h - 1:
            stdscr.addstr(y, 1 + len(row), en, en_col | curses.A_BOLD)

    # PLL-B shared warning
    if gen.enabled[1] and gen.enabled[2] and gen.freq_hz[1] != gen.freq_hz[2]:
        warn = '* CLK1 and CLK2 share PLL-B — only the last-set frequency is active'
        if 10 < h - 1:
            stdscr.addstr(10, 2, warn, curses.color_pair(4) | curses.A_BOLD)

    # Status bar
    if status and h > 2:
        stdscr.addstr(h - 2, 2, status[:w - 3], curses.color_pair(5))

    # Help
    help_y = 12
    for i, line in enumerate(HELP_LINES):
        if help_y + i < h - 1:
            stdscr.addstr(help_y + i, 2, line, curses.color_pair(6))

    stdscr.refresh()


def _prompt_string(stdscr, y, x, prompt):
    """Ask user to type a string in-place. Returns stripped input or '' on cancel."""
    h, w = stdscr.getmaxyx()
    stdscr.addstr(y, x, prompt + ' ' * (w - x - len(prompt) - 1))
    stdscr.move(y, x + len(prompt))
    curses.echo()
    curses.curs_set(1)
    stdscr.nodelay(False)
    try:
        raw = stdscr.getstr(y, x + len(prompt), 30)
        result = raw.decode('utf-8', errors='ignore').strip()
    except Exception:
        result = ''
    curses.noecho()
    curses.curs_set(0)
    return result


def _run_tui(stdscr, gen):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.color_pair(0)
    curses.init_pair(1, curses.COLOR_CYAN,    -1)   # title
    curses.init_pair(2, curses.COLOR_GREEN,   -1)   # enabled
    curses.init_pair(3, curses.COLOR_YELLOW,  -1)   # selected row
    curses.init_pair(4, curses.COLOR_RED,     -1)   # warning / disabled
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)   # status
    curses.init_pair(6, curses.COLOR_WHITE,   -1)   # help

    stdscr.nodelay(False)
    stdscr.keypad(True)

    sel    = 0
    status = 'Ready. Select a channel and press f to set frequency.'
    presets = _load_presets()

    while True:
        _draw_ui(stdscr, gen, sel, status, presets)
        key = stdscr.getch()

        if key in (ord('q'), ord('Q'), 27):     # q or ESC
            break

        elif key == curses.KEY_UP:
            sel = (sel - 1) % 3

        elif key == curses.KEY_DOWN:
            sel = (sel + 1) % 3

        elif key == ord(' '):
            if gen.freq_hz[sel] == 0 and not gen.enabled[sel]:
                status = 'Set a frequency first (press f).'
            else:
                new_state = not gen.enabled[sel]
                gen.enable(sel, new_state)
                status = f'{CLK_NAMES[sel]} {"enabled" if new_state else "disabled"}.'

        elif key in (ord('f'), ord('F')):
            h, _ = stdscr.getmaxyx()
            raw = _prompt_string(stdscr, h - 2, 2, f'Set {CLK_NAMES[sel]} freq: ')
            if raw:
                hz = _parse_freq(raw)
                if hz is None or hz < FREQ_MIN or hz > FREQ_MAX:
                    status = f'Bad frequency. Range: {_fmt_hz_short(FREQ_MIN)} – {_fmt_hz_short(FREQ_MAX)}'
                else:
                    actual = gen.set_freq(sel, hz)
                    if actual is None:
                        status = f'Cannot synthesize {_fmt_hz_short(hz)}.'
                    else:
                        err_ppm = (actual - hz) / hz * 1e6
                        status = (f'{CLK_NAMES[sel]} set to {_fmt_hz_short(actual)}'
                                  f'  (error {err_ppm:+.2f} ppm)')

        elif key in (ord('d'), ord('D')):
            idx = DRIVE_MA.index(gen.drive_ma[sel])
            new_ma = DRIVE_MA[(idx + 1) % len(DRIVE_MA)]
            gen.set_drive(sel, new_ma)
            status = f'{CLK_NAMES[sel]} drive → {new_ma} mA'

        elif key in (ord('a'), ord('A')):
            if all(gen.freq_hz[c] == 0 for c in range(3)):
                status = 'Set frequencies first.'
            else:
                gen.all_on()
                status = 'All outputs enabled.'

        elif key in (ord('z'), ord('Z')):
            gen.all_off()
            status = 'All outputs disabled.'

        elif key in (ord('p'), ord('P')):
            h, _ = stdscr.getmaxyx()
            name = _prompt_string(stdscr, h - 2, 2, 'Save preset name: ')
            if name:
                presets[name] = {
                    'freq':  list(gen.freq_hz),
                    'drive': list(gen.drive_ma),
                }
                _save_presets(presets)
                status = f'Preset "{name}" saved.'

        elif key in (ord('l'), ord('L')):
            if not presets:
                status = 'No presets saved.'
            else:
                h, _ = stdscr.getmaxyx()
                keys_str = ', '.join(presets.keys())
                name = _prompt_string(stdscr, h - 2, 2, f'Load preset [{keys_str}]: ')
                if name in presets:
                    p = presets[name]
                    for clk in range(3):
                        if p['freq'][clk]:
                            gen.set_freq(clk, p['freq'][clk])
                        gen.set_drive(clk, p['drive'][clk])
                    status = f'Loaded preset "{name}".'
                elif name:
                    status = f'Preset "{name}" not found.'


def run_tui(gen):
    curses.wrapper(_run_tui, gen)


# ── CLI mode ──────────────────────────────────────────────────────────────────

def run_cli(gen, args):
    """Non-interactive mode: set frequencies and optionally hold."""
    # Quadrature mode takes precedence: CLK0=I, CLK1=Q, phase-locked 90°.
    if args.quad is not None:
        hz = _parse_freq(args.quad)
        if hz is None:
            print(f'ERROR: Invalid quadrature frequency: {args.quad}', file=sys.stderr)
            sys.exit(1)
        actual = gen.set_quadrature(hz, i_clk=0, q_clk=1, sideband=args.sideband,
                                    drive_ma=args.drive)
        if actual is None:
            print(f'ERROR: Cannot synthesize quadrature at {_fmt_hz_short(hz)}.',
                  file=sys.stderr)
            print(f'       Pure-Si5351 I/Q window is '
                  f'{_fmt_hz_short(QUAD_FREQ_MIN)} .. {_fmt_hz_short(QUAD_FREQ_MAX)}. '
                  f'80m/160m need an external ÷4 counter (74AC74).',
                  file=sys.stderr)
            sys.exit(1)
        err_ppm = (actual - hz) / hz * 1e6
        print(f'QUADRATURE ({args.sideband.upper()}): '
              f'CLK0=I, CLK1=Q  {_fmt_hz(hz)} → {_fmt_hz(actual)}  ({err_ppm:+.2f} ppm)')
        print(f'  divider={gen._params[0]["div"]}  '
              f'VCO={_fmt_hz(gen._params[0]["vco_hz"])}  phase offset=90°  '
              f'drive={args.drive}mA')
        if args.stay:
            print('Outputs active. Press Ctrl-C to stop.')
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        else:
            print('Outputs active. Exiting — outputs remain on until reset.')
        return

    channels = [
        (0, args.clk0),
        (1, args.clk1),
        (2, args.clk2),
    ]
    any_set = False
    for clk, freq_str in channels:
        if freq_str is None:
            continue
        hz = _parse_freq(freq_str)
        if hz is None or not (FREQ_MIN <= hz <= FREQ_MAX):
            print(f'ERROR: Invalid frequency for CLK{clk}: {freq_str}', file=sys.stderr)
            sys.exit(1)
        actual = gen.set_freq(clk, hz)
        if actual is None:
            print(f'ERROR: Cannot synthesize {_fmt_hz_short(hz)} on CLK{clk}', file=sys.stderr)
            sys.exit(1)
        gen.enable(clk, True)
        err_ppm = (actual - hz) / hz * 1e6
        print(f'CLK{clk}: {_fmt_hz(hz)} → {_fmt_hz(actual)}  ({err_ppm:+.2f} ppm)')
        any_set = True

    if not any_set:
        print('No frequencies specified. Use --clk0/--clk1/--clk2.', file=sys.stderr)
        sys.exit(1)

    if args.stay:
        print('Outputs active. Press Ctrl-C to stop.')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        print('Outputs active. Exiting — outputs remain on until chip power-cycled or reset.')


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Si5351 3-output clock generator via Bus Pirate',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--bp',   default='/dev/ttyUSB0',
                        help='Bus Pirate serial port (default: /dev/ttyUSB0)')
    parser.add_argument('--addr', default='0x60',
                        help='Si5351 I2C address (default: 0x60)')
    parser.add_argument('--xtal', default='25e6',
                        help='Crystal frequency Hz (default: 25e6)')
    parser.add_argument('--load-cap', choices=['6', '8', '10'], default='10',
                        help='Crystal load capacitance pF (default: 10)')
    parser.add_argument('--off', action='store_true',
                        help='Disable all outputs and exit')

    # CLI mode
    cli = parser.add_argument_group('CLI mode (non-interactive)')
    cli.add_argument('--cli',  action='store_true', help='CLI mode (no curses TUI)')
    cli.add_argument('--clk0', metavar='FREQ', help='CLK0 frequency (e.g. 10e6, 14.2MHz)')
    cli.add_argument('--clk1', metavar='FREQ', help='CLK1 frequency')
    cli.add_argument('--clk2', metavar='FREQ', help='CLK2 frequency')
    cli.add_argument('--quad', metavar='FREQ',
                     help='Quadrature I/Q pair: CLK0=I, CLK1=Q, locked 90° apart '
                          '(e.g. 7.074MHz). Window ~4.76–112.5 MHz.')
    cli.add_argument('--sideband', choices=['usb', 'lsb'], default='usb',
                     help='Quadrature sideband: usb (Q lags I) or lsb (Q leads I). '
                          'Default: usb')
    cli.add_argument('--drive', type=int, choices=[2, 4, 6, 8],
                     default=QUAD_DEFAULT_DRIVE_MA,
                     help=f'Quadrature output drive strength in mA (2/4/6/8). '
                          f'Default: {QUAD_DEFAULT_DRIVE_MA} mA — safe level for an '
                          f'AD831 LO input.')
    cli.add_argument('--stay', action='store_true',
                     help='In CLI mode, keep running until Ctrl-C')

    args = parser.parse_args()

    # Parse address / xtal
    addr     = int(args.addr, 16) if args.addr.startswith('0x') else int(args.addr)
    xtal_hz  = float(args.xtal)
    load_cap_map = {'6': SI5351_XTAL_LOAD_6PF, '8': SI5351_XTAL_LOAD_8PF,
                    '10': SI5351_XTAL_LOAD_10PF}
    load_cap = load_cap_map[args.load_cap]

    # Resolve the Bus Pirate port. find_devices() returns dicts describing each
    # detected unit; for the v5 the driver needs the BPIO2 binary port, and
    # BPIO2 must be active. ensure_bpio2() (in bp_console) auto-detects the
    # binary port and activates + reboots into BPIO2 if it is not already up —
    # so this "just works" on every connect, including when a GPS or other CDC
    # device shifts the ttyACM numbering.
    port = None
    if args.bp and args.bp != '/dev/ttyUSB0' and os.path.exists(args.bp):
        # User explicitly named a port that exists — respect it.
        port = args.bp
    else:
        try:
            from bp_console import ensure_bpio2
            port = ensure_bpio2()
            print(f'Bus Pirate BPIO2 binary port: {port}')
        except Exception as e:
            # Fall back to legacy string-list behaviour for v3/v4.
            devices = BusPirate.find_devices()
            strs = [d if isinstance(d, str) else d.get('port') for d in devices]
            binaries = [d.get('port') for d in devices
                        if isinstance(d, dict) and d.get('role') == 'binary']
            port = (binaries or strs or [None])[0]
            if not port:
                print(f'ERROR: Bus Pirate not found ({e})', file=sys.stderr)
                sys.exit(1)
            print(f'Bus Pirate found at {port}')

    bp  = BusPirate(port)
    gen = Si5351(bp, addr=addr, xtal_hz=xtal_hz, load_cap=load_cap)

    try:
        if args.off:
            gen.all_off()
            print('All outputs disabled.')
        elif args.cli or args.quad or any([args.clk0, args.clk1, args.clk2]):
            run_cli(gen, args)
        else:
            run_tui(gen)
    finally:
        gen.close()
        bp.close()


if __name__ == '__main__':
    main()
