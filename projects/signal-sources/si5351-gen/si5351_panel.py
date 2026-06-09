#!/usr/bin/env python3
"""
Si5351 Three-Channel Clock Generator — Tkinter Panel

Graphical alternative to the si5351_gen.py curses TUI.  Provides the same
controls (frequency entry, drive strength, enable/disable, presets) in a
Tkinter window instead of a terminal.

Hardware: Si5351A breakout wired to Bus Pirate I2C pins.

Usage:
    python si5351_panel.py                          # auto-detect Bus Pirate
    python si5351_panel.py --bp /dev/ttyACM1        # explicit port
    python si5351_panel.py --addr 0x61              # 26 MHz xtal (0x61)
    python si5351_panel.py --xtal 26e6              # 26 MHz reference crystal
    python si5351_panel.py --ssa 10.1.1.60          # enable SSA measure button
    python si5351_panel.py --demo                   # no hardware needed
"""

import argparse
import dataclasses
import json
import math
import os
import random
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont, messagebox, simpledialog
from typing import Optional

# ── driver imports ────────────────────────────────────────────────────────────
# Re-use Si5351 register math and BusPirate from si5351_gen.py in same directory
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', '..', '..'))

try:
    from rf_bench.buspirate import BusPirate
    _BP_OK = True
except ImportError:
    _BP_OK = False

try:
    from rf_bench.siglent import SSA3000X
    _SSA_OK = True
except ImportError:
    _SSA_OK = False

# ── Si5351 register constants (mirrored from si5351_gen.py) ─────────────────
SI5351_ADDR_DEFAULT  = 0x60
SI5351_REG_OEB       = 3
SI5351_REG_CLK_BASE  = 16
SI5351_REG_PLLA      = 26
SI5351_REG_PLLB      = 34
SI5351_REG_MS_BASE   = [42, 50, 58]   # CLK0=42, CLK1=50, CLK2=58
SI5351_REG_PLL_RST   = 177
SI5351_REG_XTAL_LOAD = 183
SI5351_XTAL_LOAD_10PF = 0xD2
DRIVE_BITS  = {2: 0b00, 4: 0b01, 6: 0b10, 8: 0b11}
DRIVE_MA    = [2, 4, 6, 8]
PRESET_FILE = Path.home() / ".si5351_presets.json"

# ── colour palette ────────────────────────────────────────────────────────────
C_BG        = "#111111"
C_TILE      = "#0f0f0f"
C_BORDER    = "#252525"
C_LIT       = "#33ccff"
C_DIM       = "#1c3340"
C_ON        = "#33ee55"
C_OFF       = "#cc2222"
C_WARN      = "#ffaa00"
C_LABEL     = "#4a6688"
C_UNIT      = "#2299cc"
C_STATUS    = "#556677"
C_BTN_BG    = "#181818"
C_BTN_FG    = "#2a7aaa"
C_BTN_BORDER = "#1e2e3e"

# PLL note colours
C_PLLA      = "#33ccff"
C_PLLB      = "#ffaa00"
C_PLLB_WARN = "#ff5533"    # both CLK1+CLK2 active → PLL-B contention

# ── Si5351 math ───────────────────────────────────────────────────────────────

def _compute_pll_ms(target_hz: float, xtal_hz: float, clk_idx: int):
    """
    Compute PLL multiplier (a + b/c) and MS divider (a + b/c) for target_hz.
    Returns (pll_params, ms_params, actual_hz).
    Both parameter tuples are (a, b, c) integers.

    CLK0 uses PLL-A; CLK1/CLK2 use PLL-B.
    We target a VCO of 600–900 MHz (Si5351 spec).
    """
    # VCO target: pick integer MS divider that gives VCO in 600–900 MHz
    for ms_a in range(6, 1800):
        vco_hz = target_hz * ms_a
        if 600e6 <= vco_hz <= 900e6:
            # PLL multiplier (integer for lowest phase noise)
            pll_a = int(vco_hz / xtal_hz)
            # Fractional remainder
            remainder = vco_hz - pll_a * xtal_hz
            if remainder < 1e-6:
                pll_b, pll_c = 0, 1
            else:
                pll_c = 1_048_575
                pll_b = round(remainder / xtal_hz * pll_c)
            actual_vco = xtal_hz * (pll_a + pll_b / pll_c)
            actual_hz  = actual_vco / ms_a
            return (pll_a, pll_b, pll_c), (ms_a, 0, 1), actual_hz
    raise ValueError(f"Cannot find valid PLL config for {target_hz:.0f} Hz")


def _pll_regs(a: int, b: int, c: int) -> list:
    """Convert (a, b/c) PLL multiplier to 8 Si5351 register bytes."""
    P1 = 128 * a + math.floor(128 * b / c) - 512
    P2 = 128 * b - c * math.floor(128 * b / c)
    P3 = c
    return [
        (P3 >> 8) & 0xFF, P3 & 0xFF,
        (P1 >> 16) & 0x03,
        (P1 >> 8) & 0xFF, P1 & 0xFF,
        (((P3 >> 12) & 0xF0) | ((P2 >> 16) & 0x0F)),
        (P2 >> 8) & 0xFF, P2 & 0xFF,
    ]


def _ms_regs(a: int, b: int, c: int) -> list:
    """Convert (a, b/c) MS divider to 8 Si5351 register bytes."""
    P1 = 128 * a + math.floor(128 * b / c) - 512
    P2 = 128 * b - c * math.floor(128 * b / c)
    P3 = c
    return [
        (P3 >> 8) & 0xFF, P3 & 0xFF,
        (P1 >> 16) & 0x03,
        (P1 >> 8) & 0xFF, P1 & 0xFF,
        (((P3 >> 12) & 0xF0) | ((P2 >> 16) & 0x0F)),
        (P2 >> 8) & 0xFF, P2 & 0xFF,
    ]


# ── shared state ──────────────────────────────────────────────────────────────

@dataclasses.dataclass
class ClkState:
    freq_hz:    Optional[float] = None   # None = not set yet
    enabled:    bool            = False
    drive_ma:   int             = 8
    pll:        str             = "A"    # "A" or "B"
    actual_hz:  Optional[float] = None


@dataclasses.dataclass
class State:
    clk:        tuple = dataclasses.field(
                    default_factory=lambda: (ClkState(), ClkState(pll="B"), ClkState(pll="B"))
                )
    connected:  bool = False
    error:      str  = ""
    xtal_hz:    float = 25_000_000.0


# ── Si5351 hardware interface ─────────────────────────────────────────────────

class Si5351:
    """Thin Si5351 wrapper using BusPirate I2C."""

    def __init__(self, bp: "BusPirate", addr: int = SI5351_ADDR_DEFAULT,
                 xtal_hz: float = 25_000_000.0):
        self._bp   = bp
        self._addr = addr
        self._xtal = xtal_hz
        self._oeb  = 0xFF   # all disabled at start
        bp.i2c_write(addr, [SI5351_REG_XTAL_LOAD, SI5351_XTAL_LOAD_10PF])
        bp.i2c_write(addr, [SI5351_REG_OEB, 0xFF])

    def set_freq(self, clk_idx: int, freq_hz: float, drive_ma: int = 8) -> float:
        pll_params, ms_params, actual_hz = _compute_pll_ms(freq_hz, self._xtal, clk_idx)
        pll_reg   = SI5351_REG_PLLA if clk_idx == 0 else SI5351_REG_PLLB
        ms_reg    = SI5351_REG_MS_BASE[clk_idx]
        pll_src   = 0b00000000 if clk_idx == 0 else 0b00100000   # PLLB src bit
        drv_bits  = DRIVE_BITS.get(drive_ma, 0b11)
        clk_ctrl  = 0x0F | pll_src | (drv_bits << 6)   # CLK enabled, integer mode

        self._bp.i2c_write(self._addr, [pll_reg] + _pll_regs(*pll_params))
        self._bp.i2c_write(self._addr, [ms_reg]  + _ms_regs(*ms_params))
        self._bp.i2c_write(self._addr, [SI5351_REG_CLK_BASE + clk_idx, clk_ctrl])
        # Reset PLL
        rst_bit = 0x20 if clk_idx == 0 else 0x80
        self._bp.i2c_write(self._addr, [SI5351_REG_PLL_RST, rst_bit])
        return actual_hz

    def set_enable(self, clk_idx: int, enabled: bool):
        bit = (1 << clk_idx)
        if enabled:
            self._oeb &= ~bit
        else:
            self._oeb |= bit
        self._bp.i2c_write(self._addr, [SI5351_REG_OEB, self._oeb])

    def all_off(self):
        self._oeb = 0xFF
        self._bp.i2c_write(self._addr, [SI5351_REG_OEB, 0xFF])


# ── demo source ───────────────────────────────────────────────────────────────

class _DemoSource:
    def __init__(self, xtal_hz: float = 25_000_000.0):
        self._xtal = xtal_hz
        self._state = State(
            xtal_hz=xtal_hz,
            connected=True,
            clk=(
                ClkState(freq_hz=10_000_000, enabled=True,  drive_ma=8, pll="A", actual_hz=10_000_000),
                ClkState(freq_hz=7_074_000,  enabled=True,  drive_ma=4, pll="B", actual_hz=7_074_000),
                ClkState(freq_hz=14_318_180, enabled=False, drive_ma=2, pll="B", actual_hz=14_318_180),
            ),
        )
        self._t0 = time.monotonic()

    def read(self) -> State:
        t = time.monotonic() - self._t0
        # Gentle drift on CLK0 to show update
        drift = 0.5 * math.sin(t * 0.3)
        c0 = self._state.clk[0]
        c0 = dataclasses.replace(c0, actual_hz=10_000_000 + drift)
        clk = (c0,) + self._state.clk[1:]
        return dataclasses.replace(self._state, clk=clk)


# ── panel ─────────────────────────────────────────────────────────────────────

def _fmt_freq(hz: float) -> str:
    if hz >= 1e9:  return f"{hz/1e9:.6f} GHz"
    if hz >= 1e6:  return f"{hz/1e6:.6f} MHz"
    if hz >= 1e3:  return f"{hz/1e3:.3f} kHz"
    return f"{hz:.0f} Hz"


def _parse_freq(s: str) -> Optional[float]:
    s = s.strip().upper()
    try:
        if s.endswith("GHZ"): return float(s[:-3]) * 1e9
        if s.endswith("MHZ"): return float(s[:-3]) * 1e6
        if s.endswith("KHZ"): return float(s[:-3]) * 1e3
        if s.endswith("HZ"):  return float(s[:-2])
        return float(s)
    except ValueError:
        return None


class Si5351Panel:
    CLK_LABELS = ("CLK0", "CLK1", "CLK2")
    CLK_COLORS = (C_LIT, C_WARN, "#aa88ff")

    def __init__(self, root: tk.Tk, args):
        self._root      = root
        self._args      = args
        self._lock      = threading.Lock()
        self._state_ref = [State()]
        self._cmd_queue: list = []
        self._cmd_lock  = threading.Lock()
        self._stop      = threading.Event()
        self._si_ref    = [None]    # Si5351 object (set by poll thread)
        self._bp_ref    = [None]    # BusPirate object

        root.title("Si5351 Generator")
        root.configure(bg=C_BG)
        root.resizable(False, False)

        self._build_ui()
        self._start_poll(args)
        self._tick()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        fnt_hdr  = tkfont.Font(family="Helvetica", size=10, weight="bold")
        fnt_freq = tkfont.Font(family="Courier",   size=18, weight="bold")
        fnt_sub  = tkfont.Font(family="Helvetica", size=9)
        fnt_btn  = tkfont.Font(family="Helvetica", size=8)

        # Header
        hdr = tk.Frame(self._root, bg="#0a0a0a", pady=4)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Si5351  THREE-CHANNEL CLOCK GENERATOR",
                 fg="#999999", bg="#0a0a0a", font=fnt_hdr).pack(side=tk.LEFT, padx=10)
        self._conn_lbl = tk.Label(hdr, text="⬤ OFFLINE", fg=C_OFF, bg="#0a0a0a", font=fnt_sub)
        self._conn_lbl.pack(side=tk.RIGHT, padx=10)

        # Three channel tiles
        body = tk.Frame(self._root, bg=C_BG)
        body.pack(fill=tk.BOTH, padx=8, pady=4)

        self._ch_frames = []
        self._freq_vars  = []
        self._en_btns    = []
        self._drv_vars   = []
        self._pll_lbls   = []
        self._actual_vars= []

        for i in range(3):
            col = self.CLK_COLORS[i]
            outer = tk.Frame(body, bg=C_BORDER, padx=1, pady=1)
            outer.grid(row=0, column=i, padx=4, pady=4)
            inner = tk.Frame(outer, bg=C_TILE)
            inner.pack(fill=tk.BOTH, expand=True)

            tk.Label(inner, text=self.CLK_LABELS[i], fg=col, bg=C_TILE,
                     font=fnt_hdr).pack(pady=(8,2))

            # PLL indicator
            pll_lbl = tk.Label(inner, text="PLL-A", fg=C_PLLA, bg=C_TILE, font=fnt_sub)
            pll_lbl.pack()
            self._pll_lbls.append(pll_lbl)

            # Frequency display
            freq_var = tk.StringVar(value="---")
            tk.Label(inner, textvariable=freq_var, fg=col, bg=C_TILE,
                     font=fnt_freq, width=16).pack(pady=4)
            self._freq_vars.append(freq_var)

            # Actual freq
            actual_var = tk.StringVar(value="")
            tk.Label(inner, textvariable=actual_var, fg=C_STATUS, bg=C_TILE,
                     font=fnt_sub).pack()
            self._actual_vars.append(actual_var)

            tk.Frame(inner, bg=C_BORDER, height=1).pack(fill=tk.X, padx=8, pady=4)

            # Drive strength
            drv_var = tk.StringVar(value="8 mA")
            tk.Label(inner, text="Drive", fg=C_LABEL, bg=C_TILE, font=fnt_sub).pack()
            drv_menu = tk.OptionMenu(inner, drv_var, "2 mA", "4 mA", "6 mA", "8 mA",
                                     command=lambda v, idx=i: self._set_drive(idx, v))
            drv_menu.config(bg=C_BTN_BG, fg=C_BTN_FG, activebackground=C_BORDER,
                            activeforeground=C_LIT, bd=0, font=fnt_btn,
                            highlightthickness=0)
            drv_menu["menu"].config(bg=C_BTN_BG, fg=C_BTN_FG)
            drv_menu.pack(pady=2)
            self._drv_vars.append(drv_var)

            # Set frequency button
            tk.Button(inner, text="Set Frequency",
                      bg=C_BTN_BG, fg=C_BTN_FG, relief=tk.FLAT,
                      font=fnt_btn, activebackground=C_BORDER,
                      command=lambda idx=i: self._on_set_freq(idx)
                      ).pack(pady=2, fill=tk.X, padx=12)

            # Enable / disable toggle
            en_btn = tk.Button(inner, text="Enable",
                               bg="#003300", fg=C_ON, relief=tk.FLAT,
                               font=fnt_btn, activebackground=C_BORDER,
                               command=lambda idx=i: self._on_toggle(idx))
            en_btn.pack(pady=2, fill=tk.X, padx=12)
            self._en_btns.append(en_btn)

            self._ch_frames.append(inner)

        # Bottom row: all-off, presets, status
        bot = tk.Frame(self._root, bg="#0a0a0a", pady=4)
        bot.pack(fill=tk.X, padx=8)
        tk.Button(bot, text="All Off", bg=C_BTN_BG, fg="#cc4444",
                  relief=tk.FLAT, font=fnt_btn,
                  command=self._on_all_off).pack(side=tk.LEFT, padx=4)
        tk.Button(bot, text="Save Preset", bg=C_BTN_BG, fg=C_BTN_FG,
                  relief=tk.FLAT, font=fnt_btn,
                  command=self._on_save_preset).pack(side=tk.LEFT, padx=4)
        tk.Button(bot, text="Load Preset", bg=C_BTN_BG, fg=C_BTN_FG,
                  relief=tk.FLAT, font=fnt_btn,
                  command=self._on_load_preset).pack(side=tk.LEFT, padx=4)

        if self._args.ssa:
            tk.Button(bot, text="Measure (SSA)", bg=C_BTN_BG, fg=C_WARN,
                      relief=tk.FLAT, font=fnt_btn,
                      command=self._on_measure_ssa).pack(side=tk.LEFT, padx=8)

        self._status_var = tk.StringVar(value="Starting…")
        tk.Label(bot, textvariable=self._status_var, fg=C_STATUS,
                 bg="#0a0a0a", font=tkfont.Font(family="Helvetica", size=8)
                 ).pack(side=tk.RIGHT, padx=8)

    # ── poll thread ───────────────────────────────────────────────────────────

    def _start_poll(self, args):
        if args.demo:
            self._source = _DemoSource(args.xtal)
            t = threading.Thread(target=self._demo_loop, daemon=True)
        else:
            self._source = None
            t = threading.Thread(target=self._hw_loop, args=(args,), daemon=True)
        t.start()

    def _demo_loop(self):
        while not self._stop.is_set():
            s = self._source.read()
            with self._lock:
                self._state_ref[0] = s
            time.sleep(0.25)

    def _hw_loop(self, args):
        bp = si = None
        while not self._stop.is_set():
            if bp is None:
                try:
                    port = args.bp or BusPirate.find_devices()[0]
                    bp = BusPirate(port)
                    bp.set_pullups(True)
                    bp.i2c_configure(speed_hz=100_000)
                    si = Si5351(bp, addr=args.addr, xtal_hz=args.xtal)
                    with self._lock:
                        self._si_ref[0] = si
                        self._bp_ref[0] = bp
                        self._state_ref[0] = dataclasses.replace(
                            self._state_ref[0], connected=True, error="")
                except Exception as e:
                    with self._lock:
                        self._state_ref[0] = State(connected=False, error=str(e))
                    self._stop.wait(5.0)
                    continue

            # Execute commands
            with self._cmd_lock:
                pending = list(self._cmd_queue)
                self._cmd_queue.clear()
            for fn in pending:
                try:
                    fn(si)
                except Exception as e:
                    with self._lock:
                        s = self._state_ref[0]
                        self._state_ref[0] = dataclasses.replace(s, error=str(e))

            self._stop.wait(0.1)

        if bp:
            try:
                if si: si.all_off()
                bp.i2c_exit()
                bp.close()
            except Exception:
                pass

    # ── commands ──────────────────────────────────────────────────────────────

    def _enqueue(self, fn):
        with self._cmd_lock:
            self._cmd_queue.append(fn)

    def _on_set_freq(self, idx: int):
        val = simpledialog.askstring(
            f"CLK{idx} Frequency",
            "Enter frequency (e.g. 10MHz, 14.074e6, 7200kHz):",
            parent=self._root,
        )
        if not val:
            return
        hz = _parse_freq(val)
        if hz is None or not (3000 <= hz <= 200e6):
            messagebox.showerror("Invalid", "Frequency must be 3 kHz – 200 MHz")
            return
        drv_ma = int(self._drv_vars[idx].get().split()[0])

        def _set(si):
            actual = si.set_freq(idx, hz, drv_ma)
            si.set_enable(idx, True)
            with self._lock:
                s = self._state_ref[0]
                clk = list(s.clk)
                clk[idx] = dataclasses.replace(clk[idx],
                    freq_hz=hz, actual_hz=actual, enabled=True, drive_ma=drv_ma)
                self._state_ref[0] = dataclasses.replace(s, clk=tuple(clk))

        if self._args.demo:
            with self._lock:
                s = self._state_ref[0]
                clk = list(s.clk)
                clk[idx] = dataclasses.replace(clk[idx], freq_hz=hz, actual_hz=hz,
                                                enabled=True, drive_ma=drv_ma)
                self._state_ref[0] = dataclasses.replace(s, clk=tuple(clk))
        else:
            self._enqueue(_set)

    def _on_toggle(self, idx: int):
        with self._lock:
            s = self._state_ref[0]
            cur = s.clk[idx].enabled
        new_state = not cur

        def _toggle(si):
            si.set_enable(idx, new_state)
            with self._lock:
                s = self._state_ref[0]
                clk = list(s.clk)
                clk[idx] = dataclasses.replace(clk[idx], enabled=new_state)
                self._state_ref[0] = dataclasses.replace(s, clk=tuple(clk))

        if self._args.demo:
            with self._lock:
                s = self._state_ref[0]
                clk = list(s.clk)
                clk[idx] = dataclasses.replace(clk[idx], enabled=new_state)
                self._state_ref[0] = dataclasses.replace(s, clk=tuple(clk))
        else:
            self._enqueue(_toggle)

    def _set_drive(self, idx: int, label: str):
        ma = int(label.split()[0])
        with self._lock:
            s = self._state_ref[0]
            clk = list(s.clk)
            clk[idx] = dataclasses.replace(clk[idx], drive_ma=ma)
            self._state_ref[0] = dataclasses.replace(s, clk=tuple(clk))
        self._status_var.set(f"CLK{idx} drive → {ma} mA (takes effect on next frequency set)")

    def _on_all_off(self):
        def _off(si):
            si.all_off()
            with self._lock:
                s = self._state_ref[0]
                clk = tuple(dataclasses.replace(c, enabled=False) for c in s.clk)
                self._state_ref[0] = dataclasses.replace(s, clk=clk)
        if self._args.demo:
            with self._lock:
                s = self._state_ref[0]
                clk = tuple(dataclasses.replace(c, enabled=False) for c in s.clk)
                self._state_ref[0] = dataclasses.replace(s, clk=clk)
        else:
            self._enqueue(_off)
        self._status_var.set("All outputs off")

    def _on_save_preset(self):
        name = simpledialog.askstring("Save Preset", "Preset name:", parent=self._root)
        if not name:
            return
        with self._lock:
            s = self._state_ref[0]
        presets = {}
        if PRESET_FILE.exists():
            try: presets = json.loads(PRESET_FILE.read_text())
            except Exception: pass
        presets[name] = [
            {"freq_hz": c.freq_hz, "enabled": c.enabled, "drive_ma": c.drive_ma}
            for c in s.clk
        ]
        PRESET_FILE.write_text(json.dumps(presets, indent=2))
        self._status_var.set(f"Saved preset '{name}'")

    def _on_load_preset(self):
        if not PRESET_FILE.exists():
            messagebox.showinfo("No Presets", "No presets saved yet.")
            return
        try:
            presets = json.loads(PRESET_FILE.read_text())
        except Exception:
            messagebox.showerror("Error", "Could not read presets file.")
            return
        if not presets:
            messagebox.showinfo("No Presets", "Presets file is empty.")
            return
        name = simpledialog.askstring(
            "Load Preset",
            "Available: " + ", ".join(presets.keys()) + "\n\nEnter name:",
            parent=self._root,
        )
        if not name or name not in presets:
            return
        data = presets[name]
        for idx, d in enumerate(data[:3]):
            hz = d.get("freq_hz")
            ma = d.get("drive_ma", 8)
            en = d.get("enabled", False)
            if hz:
                if self._args.demo:
                    with self._lock:
                        s = self._state_ref[0]
                        clk = list(s.clk)
                        clk[idx] = dataclasses.replace(clk[idx],
                            freq_hz=hz, actual_hz=hz, enabled=en, drive_ma=ma)
                        self._state_ref[0] = dataclasses.replace(s, clk=tuple(clk))
                else:
                    def _apply(si, i=idx, f=hz, m=ma, e=en):
                        actual = si.set_freq(i, f, m)
                        si.set_enable(i, e)
                        with self._lock:
                            s = self._state_ref[0]
                            clk = list(s.clk)
                            clk[i] = dataclasses.replace(clk[i],
                                freq_hz=f, actual_hz=actual, enabled=e, drive_ma=m)
                            self._state_ref[0] = dataclasses.replace(s, clk=tuple(clk))
                    self._enqueue(_apply)
        self._status_var.set(f"Loaded preset '{name}'")

    def _on_measure_ssa(self):
        with self._lock:
            s = self._state_ref[0]
        # Find first enabled output with a frequency set
        for i, c in enumerate(s.clk):
            if c.enabled and c.freq_hz:
                threading.Thread(
                    target=self._ssa_measure, args=(i, c.freq_hz), daemon=True
                ).start()
                self._status_var.set(f"Measuring CLK{i} on SSA…")
                return
        self._status_var.set("No enabled output to measure")

    def _ssa_measure(self, idx: int, freq_hz: float):
        try:
            ssa = SSA3000X(self._args.ssa)
            ssa.set_center(freq_hz)
            ssa.set_span(max(freq_hz * 0.01, 1_000_000))
            ssa.single_sweep()
            pwr = ssa.get_peak_marker()
            self._status_var.set(f"CLK{idx}: {pwr:.1f} dBm at {_fmt_freq(freq_hz)}")
        except Exception as e:
            self._status_var.set(f"SSA error: {e}")

    # ── UI refresh tick ───────────────────────────────────────────────────────

    def _tick(self):
        with self._lock:
            s = self._state_ref[0]

        # Connection indicator
        if s.connected:
            self._conn_lbl.config(text="⬤ ONLINE", fg=C_ON)
        else:
            self._conn_lbl.config(text="⬤ OFFLINE", fg=C_OFF)
            if s.error:
                self._status_var.set(s.error[:80])

        for i, c in enumerate(s.clk):
            col = self.CLK_COLORS[i] if c.enabled else C_DIM

            # Frequency
            if c.freq_hz is not None:
                self._freq_vars[i].set(_fmt_freq(c.freq_hz))
            else:
                self._freq_vars[i].set("---")

            # Actual frequency (drift display)
            if c.actual_hz is not None and c.freq_hz is not None:
                err_ppm = (c.actual_hz - c.freq_hz) / c.freq_hz * 1e6
                self._actual_vars[i].set(f"actual {_fmt_freq(c.actual_hz)}  ({err_ppm:+.3f} ppm)")
            else:
                self._actual_vars[i].set("")

            # PLL indicator
            pll_text = f"PLL-{c.pll}"
            pll_fg = C_PLLA if c.pll == "A" else C_PLLB
            # Warn if CLK1 and CLK2 both enabled (PLL-B contention)
            if c.pll == "B" and s.clk[1].enabled and s.clk[2].enabled:
                pll_fg = C_PLLB_WARN
                pll_text += " ⚠"
            self._pll_lbls[i].config(text=pll_text, fg=pll_fg)

            # Enable button
            if c.enabled:
                self._en_btns[i].config(text="Disable", bg="#003300", fg=C_ON)
            else:
                self._en_btns[i].config(text="Enable",  bg="#1a0000", fg=C_OFF)

            # Drive
            self._drv_vars[i].set(f"{c.drive_ma} mA")

        self._root.after(200, self._tick)

    def destroy(self):
        self._stop.set()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Si5351 3-channel clock generator panel")
    p.add_argument("--bp",    default=None,
                   help="Bus Pirate serial port (default: auto-detect)")
    p.add_argument("--addr",  type=lambda x: int(x, 0), default=SI5351_ADDR_DEFAULT,
                   help="Si5351 I2C address (default 0x60; 0x61 if ADDR pin high)")
    p.add_argument("--xtal",  type=float, default=25_000_000.0,
                   help="Reference crystal frequency Hz (default 25000000)")
    p.add_argument("--ssa",   default=None,
                   help="SSA3032X IP for measure button (e.g. 10.1.1.60)")
    p.add_argument("--demo",  action="store_true",
                   help="Demo mode — no Bus Pirate needed")
    args = p.parse_args()

    root = tk.Tk()
    panel = Si5351Panel(root, args)
    root.protocol("WM_DELETE_WINDOW", lambda: (panel.destroy(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
