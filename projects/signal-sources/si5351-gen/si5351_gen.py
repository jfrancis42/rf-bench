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
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench-drivers-buspirate'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))

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

SI5351_XTAL_LOAD_6PF  = 0x52
SI5351_XTAL_LOAD_8PF  = 0x92
SI5351_XTAL_LOAD_10PF = 0xD2   # Most common breakouts (Adafruit, generic)

SI5351_XTAL_HZ_DEFAULT = 25_000_000   # 25 MHz crystal

# CLK control register: drive bits for each output
DRIVE_BITS  = {2: 0b00, 4: 0b01, 6: 0b10, 8: 0b11}
DRIVE_MA    = [2, 4, 6, 8]

# PLL assignment: CLK n → PLL A (0) or B (1)
CLK_PLL     = [0, 1, 1]           # CLK0→PLL-A, CLK1/CLK2→PLL-B

# CLK control reg: bit5=PLL_SRC (0=A, 1=B), bits[4:3]=11 (MS src), bits[1:0]=drive
CLK_PLLSRC  = [0x00, 0x20, 0x20]  # bit5 set for CLK1, CLK2

MS_REGS     = [SI5351_REG_MS0, SI5351_REG_MS1, SI5351_REG_MS2]
PLL_REGS    = [SI5351_REG_PLLA, SI5351_REG_PLLB]

VCO_MIN     = 600_000_000
VCO_MAX     = 900_000_000
FREQ_MIN    =       3_000
FREQ_MAX    = 200_000_000

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
                 load_cap=SI5351_XTAL_LOAD_10PF):
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

        # Bring up I2C on the Bus Pirate
        bp.i2c_start()

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
    cli.add_argument('--stay', action='store_true',
                     help='In CLI mode, keep running until Ctrl-C')

    args = parser.parse_args()

    # Parse address / xtal
    addr     = int(args.addr, 16) if args.addr.startswith('0x') else int(args.addr)
    xtal_hz  = float(args.xtal)
    load_cap_map = {'6': SI5351_XTAL_LOAD_6PF, '8': SI5351_XTAL_LOAD_8PF,
                    '10': SI5351_XTAL_LOAD_10PF}
    load_cap = load_cap_map[args.load_cap]

    # Auto-detect port if default doesn't exist
    port = args.bp
    if not os.path.exists(port):
        devices = BusPirate.find_devices()
        if devices:
            port = devices[0]
            print(f'Bus Pirate found at {port}')
        else:
            print(f'ERROR: Bus Pirate not found at {args.bp}', file=sys.stderr)
            sys.exit(1)

    bp  = BusPirate(port)
    gen = Si5351(bp, addr=addr, xtal_hz=xtal_hz, load_cap=load_cap)

    try:
        if args.off:
            gen.all_off()
            print('All outputs disabled.')
        elif args.cli or any([args.clk0, args.clk1, args.clk2]):
            run_cli(gen, args)
        else:
            run_tui(gen)
    finally:
        gen.close()
        bp.close()


if __name__ == '__main__':
    main()
