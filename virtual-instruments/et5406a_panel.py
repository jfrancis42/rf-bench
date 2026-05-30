#!/usr/bin/env python3
"""
ET5406A+ Virtual Instrument Panel

Graphical monitoring front panel for the Yertai ET5406A+ programmable DC
electronic load (200 W / 120 V / 20 A).

Polls the instrument via the rf_bench.yertai.ET5406A driver in a background
thread and updates V / I / P / R readouts, operating mode, input on/off state,
mode set point, protection limits, and fault indicators in real time.

Usage:
    python et5406a_panel.py                      # auto-detect CH340 adapter
    python et5406a_panel.py --port /dev/ttyUSB0  # explicit serial port
    python et5406a_panel.py --interval 3000      # UI refresh ms (default 2000)
    python et5406a_panel.py --demo               # simulated data, no hardware

Note on poll timing: each full state read requires ~12 serial round-trips at
200 ms/round-trip = ~2.4 s per cycle. The --interval controls how often the UI
reads the latest state from the background thread; the thread itself runs as
fast as the instrument allows.

Controls are displayed as disabled stubs; future versions will wire callbacks.
"""

import argparse
import dataclasses
import math
import os
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional

# ── path bootstrap (run directly without pip install) ──────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
try:
    from rf_bench.yertai import ET5406A, ET5406AError
    _DRIVER_OK = True
except ImportError:
    _DRIVER_OK = False


# ─────────────────────────────────────────────────────────────────────────────
# Color palette
# ─────────────────────────────────────────────────────────────────────────────

C_WIN_BG        = "#141414"
C_HEADER_BG     = "#0a0a0a"
C_HEADER_FG     = "#999999"
C_PANEL_BG      = "#0d0d0d"
C_TILE_BG       = "#0f0f0f"
C_TILE_BORDER   = "#232323"
C_SECTION_LABEL = "#445544"
C_MEAS_LABEL    = "#4a664a"
C_VALUE_LIT     = "#33ee55"   # bright green LED (live value)
C_VALUE_DIM     = "#1c4426"   # dim green (no data / "---")
C_UNIT          = "#22aa3a"
C_DIVIDER       = "#1c1c1c"
C_ONLINE        = "#33ee55"
C_OFFLINE       = "#cc2222"

# Mode badge: (foreground, background) by mode string
_MODE_STYLE: dict[str, tuple[str, str]] = {
    "CC":   ("#ffaa00", "#1a0e00"),
    "CV":   ("#22aaff", "#001222"),
    "CP":   ("#ff66cc", "#1a0018"),
    "CR":   ("#44ffcc", "#001a14"),
    "CCCV": ("#ffcc00", "#1a1400"),
    "CRCV": ("#88ffcc", "#001814"),
    "TRAN": ("#ff8844", "#1a0c00"),
    "LIST": ("#cc88ff", "#10001a"),
    "SCAN": ("#ffff44", "#1a1a00"),
    "SHOR": ("#ff2222", "#1a0000"),
    "BATT": ("#ffff66", "#1a1a00"),
    "LED":  ("#88ccff", "#001020"),
}
_MODE_DEFAULT = ("#888888", "#141414")

C_INPUT_ON_FG   = "#33ee55"
C_INPUT_ON_BG   = "#002a10"
C_INPUT_OFF_FG  = "#ff3333"
C_INPUT_OFF_BG  = "#1a0000"

C_PROT_HIT_FG   = "#ff3333"
C_PROT_HIT_BG   = "#1a0000"
C_PROT_OK_FG    = "#2a4a2a"
C_PROT_OK_BG    = "#0d0d0d"

C_CTRL_FG       = "#2a2a2a"
C_CTRL_BTN_BG   = "#131313"
C_CTRL_BTN_BORDER = "#1e1e1e"

C_STATUS_BG     = "#0a0a0a"
C_STATUS_FG     = "#556655"


# ─────────────────────────────────────────────────────────────────────────────
# Shared state dataclass (poll thread → UI thread)
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class State:
    # Measured quantities
    voltage:    Optional[float] = None
    current:    Optional[float] = None
    power:      Optional[float] = None
    resistance: Optional[float] = None

    # Operating mode and input switch
    mode:  Optional[str] = None   # CC|CV|CP|CR|CCCV|CRCV|TRAN|LIST|SCAN|SHOR|BATT|LED
    input: Optional[str] = None   # ON|OFF

    # Set point (mode-dependent; up to two parameters for compound modes)
    sp1_label: str = ""
    sp1_value: Optional[float] = None
    sp1_unit:  str = ""
    sp2_label: str = ""
    sp2_value: Optional[float] = None
    sp2_unit:  str = ""

    # Protection state
    protection: Optional[str] = None  # NONE|OV|OC|OP|OT|LRV|FAN

    # Protection limits
    ovp: Optional[float] = None
    ocp: Optional[float] = None
    opp: Optional[float] = None

    # Range settings
    vrange: Optional[str] = None  # HIGH|LOW
    crange: Optional[str] = None  # HIGH|LOW

    # Battery accumulators (only meaningful in BATT mode)
    batt_capacity_ah: Optional[float] = None
    batt_energy_wh:   Optional[float] = None

    # Connection metadata
    connected: bool = False
    error:     str  = ""
    model:     str  = ""
    serial_n:  str  = ""
    firmware:  str  = ""
    port:      str  = ""


# ─────────────────────────────────────────────────────────────────────────────
# Demo data source
# ─────────────────────────────────────────────────────────────────────────────

class _DemoSource:
    """
    Generates plausible simulated instrument state for --demo mode.

    Cycles through all operating modes every ~8 s so the full panel layout
    can be inspected without hardware.
    """

    _MODES = ["CC", "CV", "CP", "CR", "CCCV", "CRCV", "BATT", "TRAN", "LED", "SHOR"]

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self._mode_idx = 0
        self._next_mode_change = time.monotonic() + 8.0
        # Battery accumulator grows over time
        self._batt_start = time.monotonic()

    @property
    def _t(self) -> float:
        return time.monotonic() - self._t0

    def _advance_mode(self) -> None:
        if time.monotonic() >= self._next_mode_change:
            self._mode_idx = (self._mode_idx + 1) % len(self._MODES)
            self._next_mode_change = time.monotonic() + 8.0

    def read(self) -> State:
        self._advance_mode()
        t = self._t
        mode = self._MODES[self._mode_idx]

        # Base measurements — gentle sinusoidal variation + small noise
        v = 12.0 + 0.4 * math.sin(t * 0.4) + random.gauss(0, 0.003)
        i = 2.0  + 0.15 * math.sin(t * 0.3 + 1.2) + random.gauss(0, 0.002)
        if mode == "SHOR":
            v = 0.02 + random.gauss(0, 0.001)
            i = 19.5 + random.gauss(0, 0.05)
        p = v * i
        r = v / max(i, 0.001)

        # Set point
        sp1_label = sp1_unit = sp2_label = sp2_unit = ""
        sp1_value = sp2_value = None
        if mode == "CC":
            sp1_label, sp1_value, sp1_unit = "I SET", 2.000, "A"
        elif mode == "CV":
            sp1_label, sp1_value, sp1_unit = "V SET", 12.000, "V"
        elif mode == "CP":
            sp1_label, sp1_value, sp1_unit = "P SET", 24.000, "W"
        elif mode == "CR":
            sp1_label, sp1_value, sp1_unit = "R SET", 6.000, "Ω"
        elif mode == "CCCV":
            sp1_label, sp1_value, sp1_unit = "I SET", 2.000, "A"
            sp2_label, sp2_value, sp2_unit = "V SET", 13.800, "V"
        elif mode == "CRCV":
            sp1_label, sp1_value, sp1_unit = "R SET", 6.000, "Ω"
            sp2_label, sp2_value, sp2_unit = "V SET", 10.500, "V"
        elif mode == "BATT":
            sp1_label, sp1_value, sp1_unit = "I SET", 1.500, "A"
        elif mode == "TRAN":
            sp1_label, sp1_value, sp1_unit = "I_A", 1.000, "A"
            sp2_label, sp2_value, sp2_unit = "I_B", 3.000, "A"
        elif mode == "LED":
            sp1_label, sp1_value, sp1_unit = "V REF", 3.200, "V"
            sp2_label, sp2_value, sp2_unit = "I REF", 0.350, "A"

        # Battery accumulators
        batt_t = time.monotonic() - self._batt_start
        batt_ah  = (batt_t / 3600.0) * 1.5 if mode == "BATT" else None
        batt_wh  = batt_ah * 12.0          if batt_ah is not None else None

        # Protection status — occasionally show a transient fault for demo
        prot = "NONE"
        if 6.8 < (t % 8.0) < 7.2 and mode not in ("SHOR",):
            prot = random.choice(["NONE", "NONE", "NONE", "OC"])
        if mode == "SHOR":
            prot = "NONE"  # short mode isn't a fault

        return State(
            voltage=v, current=i, power=p, resistance=r,
            mode=mode, input="ON" if mode != "SHOR" else "ON",
            sp1_label=sp1_label, sp1_value=sp1_value, sp1_unit=sp1_unit,
            sp2_label=sp2_label, sp2_value=sp2_value, sp2_unit=sp2_unit,
            protection=prot,
            ovp=120.0, ocp=20.0, opp=200.0,
            vrange="HIGH", crange="HIGH",
            batt_capacity_ah=batt_ah, batt_energy_wh=batt_wh,
            connected=True,
            model="ET5406A+", serial_n="DEMO-001", firmware="2.3",
            port="DEMO",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Live instrument state reader
# ─────────────────────────────────────────────────────────────────────────────

def _read_state(load: "ET5406A") -> State:
    """Read all displayable state. Runs in the poll thread; takes ~2–3 s."""
    s = State(
        connected=True,
        model=load.model, serial_n=load.serial_n,
        firmware=load.firmware, port=load._ser.port,
    )

    # Core measurements (single SCPI transaction)
    try:
        s.voltage, s.current, s.power, s.resistance = load.read_all()
    except ET5406AError:
        pass

    try:
        s.mode = load.mode
    except ET5406AError:
        pass

    try:
        s.input = load.input
    except ET5406AError:
        pass

    try:
        s.protection = load.protection
    except ET5406AError:
        pass

    # Mode-dependent set point
    m = s.mode or ""
    try:
        if m == "CC":
            s.sp1_label, s.sp1_value, s.sp1_unit = "I SET", load.CC_current, "A"
        elif m == "CV":
            s.sp1_label, s.sp1_value, s.sp1_unit = "V SET", load.CV_voltage, "V"
        elif m == "CP":
            s.sp1_label, s.sp1_value, s.sp1_unit = "P SET", load.CP_power, "W"
        elif m == "CR":
            s.sp1_label, s.sp1_value, s.sp1_unit = "R SET", load.CR_resistance, "Ω"
        elif m == "CCCV":
            s.sp1_label, s.sp1_value, s.sp1_unit = "I SET", load.CCCV_current, "A"
            s.sp2_label, s.sp2_value, s.sp2_unit = "V SET", load.CCCV_voltage, "V"
        elif m == "CRCV":
            s.sp1_label, s.sp1_value, s.sp1_unit = "R SET", load.CRCV_resistance, "Ω"
            s.sp2_label, s.sp2_value, s.sp2_unit = "V SET", load.CRCV_voltage, "V"
        elif m == "LED":
            s.sp1_label, s.sp1_value, s.sp1_unit = "V REF", load.LED_voltage, "V"
            s.sp2_label, s.sp2_value, s.sp2_unit = "I REF", load.LED_current, "A"
        elif m == "BATT":
            sub = load.BATT_submode
            if sub == "CC":
                s.sp1_label, s.sp1_value, s.sp1_unit = "I SET", load.CC_current, "A"
            else:
                s.sp1_label, s.sp1_value, s.sp1_unit = "R SET", load.BATT_resistance, "Ω"
        elif m == "TRAN":
            ia, ib = load.TRANSIENT_current
            s.sp1_label, s.sp1_value, s.sp1_unit = "I_A", ia, "A"
            s.sp2_label, s.sp2_value, s.sp2_unit = "I_B", ib, "A"
    except ET5406AError:
        pass

    # Battery accumulators
    if m == "BATT":
        try:
            s.batt_capacity_ah = load.BATT_capacity
        except ET5406AError:
            pass
        try:
            s.batt_energy_wh = load.BATT_energy
        except ET5406AError:
            pass

    # Protection limits
    try:
        s.ovp = load.OVP
    except ET5406AError:
        pass
    try:
        s.ocp = load.OCP
    except ET5406AError:
        pass
    try:
        s.opp = load.OPP
    except ET5406AError:
        pass

    # Range settings
    try:
        s.vrange = load.Vrange
    except ET5406AError:
        pass
    try:
        s.crange = load.Crange
    except ET5406AError:
        pass

    return s


def _poll_worker(port: Optional[str], state_ref: list, lock: threading.Lock,
                 stop: threading.Event, cmd_queue: list, cmd_lock: threading.Lock,
                 load_ref: list) -> None:
    """Background thread: connect, poll, execute commands, store latest state in state_ref[0]."""
    load = None
    while not stop.is_set():
        # ── connect ────────────────────────────────────────────────────
        if load is None:
            try:
                load = ET5406A(port)
                # Store load reference for cleanup
                with lock:
                    load_ref[0] = load
            except Exception as e:
                dead = State(connected=False,
                             error=f"Connect failed: {e}",
                             port=port or "(auto)")
                with lock:
                    state_ref[0] = dead
                stop.wait(5.0)
                continue

        # ── execute queued commands ────────────────────────────────────
        with cmd_lock:
            pending = list(cmd_queue)
            cmd_queue.clear()

        if pending:
            for cmd_func in pending:
                try:
                    cmd_func(load)
                except Exception as e:
                    # Store error in state for display
                    with lock:
                        s = state_ref[0]
                        s.error = f"Command error: {e}"
                        state_ref[0] = s
            # Give instrument time to process command before next poll
            time.sleep(0.3)

        # ── read ───────────────────────────────────────────────────────
        try:
            s = _read_state(load)
            with lock:
                state_ref[0] = s
        except Exception as e:
            with lock:
                state_ref[0] = State(connected=False,
                                     error=f"Poll error: {e}",
                                     port=port or "(auto)")
                load_ref[0] = None
            try:
                load.close()
            except Exception:
                pass
            load = None

    if load:
        try:
            load.close()
        except Exception:
            pass
        with lock:
            load_ref[0] = None


# ─────────────────────────────────────────────────────────────────────────────
# Widget helpers
# ─────────────────────────────────────────────────────────────────────────────

def _label(parent, text, fg, bg, font, **kw):
    return tk.Label(parent, text=text, fg=fg, bg=bg, font=font, **kw)


def _frame(parent, bg, **kw):
    return tk.Frame(parent, bg=bg, **kw)


def _tile(parent, bg=C_TILE_BG, border=C_TILE_BORDER):
    """Return a bordered frame that looks like a display tile."""
    outer = tk.Frame(parent, bg=border, padx=1, pady=1)
    inner = tk.Frame(outer, bg=bg)
    inner.pack(fill=tk.BOTH, expand=True)
    return outer, inner


def _hline(parent, bg=C_DIVIDER, height=1):
    return tk.Frame(parent, bg=bg, height=height)


# ─────────────────────────────────────────────────────────────────────────────
# Main panel window
# ─────────────────────────────────────────────────────────────────────────────

class ET5406APanel(tk.Tk):
    _REFRESH_MS = 2000  # how often we read the latest state and redraw

    def __init__(self, port: Optional[str], interval_ms: int, demo: bool) -> None:
        super().__init__()
        self.title("ET5406A+  Virtual Panel")
        self.configure(bg=C_WIN_BG)
        self.resizable(False, False)

        self._demo = demo
        self._port = port

        # Shared state (poll thread → UI thread)
        self._state_ref: list = [State()]
        self._state_lock = threading.Lock()
        self._stop = threading.Event()

        # Demo source (used when --demo)
        self._demo_src = _DemoSource() if demo else None

        # Choose fonts after Tk() is constructed
        self._f_small  = self._mono(8)
        self._f_label  = self._mono(9)
        self._f_unit   = self._mono(13, bold=True)
        self._f_value  = self._mono(30, bold=True)
        self._f_value_sm = self._mono(22, bold=True)
        self._f_badge  = self._mono(24, bold=True)
        self._f_badge_sm = self._mono(16, bold=True)
        self._f_section = self._mono(8)
        self._f_ctrl   = self._mono(9)
        self._f_status = self._mono(9)
        self._f_prot   = self._mono(10, bold=True)
        self._f_header = self._mono(9)

        # Command queue for sending commands to the load (thread-safe)
        self._cmd_queue: list = []
        self._cmd_lock = threading.Lock()

        # Reference to the load instance (set by poll thread, protected by state_lock)
        self._load_ref: list = [None]

        self._build_ui()
        self._start_poll(interval_ms)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── font helper ────────────────────────────────────────────────────────

    @staticmethod
    def _mono(size: int, bold: bool = False) -> tuple:
        for name in ("DejaVu Sans Mono", "Liberation Mono", "Courier New", "Courier"):
            if name in tkfont.families():
                return (name, size, "bold" if bold else "normal")
        return ("Courier", size, "bold" if bold else "normal")

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_header()
        content = _frame(self, C_WIN_BG)
        content.pack(fill=tk.BOTH, padx=10, pady=(0, 4))
        self._build_left(content)
        self._build_right(content)
        self._build_controls()
        self._build_status_bar()

    def _build_header(self) -> None:
        hdr = _frame(self, C_HEADER_BG)
        hdr.pack(fill=tk.X, padx=0, pady=0)
        inner = _frame(hdr, C_HEADER_BG)
        inner.pack(fill=tk.X, padx=12, pady=6)

        # Left: branding
        _label(inner, "YERTAI  ET5406A+", C_HEADER_FG, C_HEADER_BG,
               self._mono(11, bold=True), anchor='w').pack(side=tk.LEFT)
        _label(inner, "  200W / 120V / 20A  PROGRAMMABLE DC LOAD",
               "#444444", C_HEADER_BG, self._f_header, anchor='w').pack(side=tk.LEFT)

        # Right: connection badge
        self._conn_dot  = _label(inner, "●", C_OFFLINE, C_HEADER_BG,
                                 self._mono(14, bold=True))
        self._conn_dot.pack(side=tk.RIGHT, padx=(6, 0))
        self._conn_text = _label(inner, "OFFLINE", "#666666", C_HEADER_BG,
                                 self._f_header)
        self._conn_text.pack(side=tk.RIGHT)

        # Model / S/N / firmware info line
        info = _frame(hdr, C_HEADER_BG)
        info.pack(fill=tk.X, padx=12, pady=(0, 6))
        self._info_var = tk.StringVar(value="—")
        _label(info, "", "#333333", C_HEADER_BG, self._f_header).pack(side=tk.LEFT)
        tk.Label(info, textvariable=self._info_var, fg="#3a4a3a",
                 bg=C_HEADER_BG, font=self._f_header).pack(side=tk.LEFT)

        _hline(self, C_DIVIDER, 1).pack(fill=tk.X)

    def _build_left(self, parent: tk.Frame) -> None:
        left = _frame(parent, C_WIN_BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, pady=8, padx=(0, 8))

        # ── Section label ──────────────────────────────────────────────
        _label(left, "MEASUREMENTS", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 4))

        # ── 2×2 readout grid ──────────────────────────────────────────
        grid = _frame(left, C_WIN_BG)
        grid.pack()

        self._w_voltage    = self._readout_tile(grid, "VOLTAGE",    "V",  row=0, col=0)
        self._w_current    = self._readout_tile(grid, "CURRENT",    "A",  row=0, col=1)
        self._w_power      = self._readout_tile(grid, "POWER",      "W",  row=1, col=0)
        self._w_resistance = self._readout_tile(grid, "RESISTANCE", "Ω",  row=1, col=1)

        # ── Battery accumulators (always shown; grayed when not BATT) ─
        _frame(left, C_DIVIDER, height=1).pack(fill=tk.X, pady=6)
        _label(left, "BATTERY ACCUMULATORS", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 4))
        batt = _frame(left, C_WIN_BG)
        batt.pack()
        self._w_energy = self._readout_tile(batt, "ENERGY", "Wh", row=0, col=0, sm=True)
        self._w_charge = self._readout_tile(batt, "CHARGE", "Ah", row=0, col=1, sm=True)

    def _readout_tile(self, parent: tk.Frame, label: str, unit: str,
                      row: int, col: int, sm: bool = False) -> dict:
        """Create a bordered measurement tile and return its updatable widgets."""
        W, H = (320, 80) if not sm else (320, 65)
        outer, inner = _tile(parent)
        outer.grid(row=row, column=col, padx=3, pady=3)
        inner.configure(width=W, height=H)
        inner.pack_propagate(False)

        vfont = self._f_value if not sm else self._f_value_sm

        # Label (top-left)
        lbl = _label(inner, label, C_MEAS_LABEL, C_TILE_BG, self._f_label, anchor='w')
        lbl.place(x=8, y=5)

        # Unit (bottom-right)
        u = _label(inner, unit, C_UNIT, C_TILE_BG, self._f_unit, anchor='e')
        u.place(relx=0.97, rely=0.98, anchor='se')

        # Value (right-aligned, vertically centred; 320 px tile accommodates 7-char
        # values like "120.000" with 30pt bold font at any DPI)
        val_var = tk.StringVar(value="---")
        val_lbl = tk.Label(inner, textvariable=val_var, fg=C_VALUE_DIM,
                           bg=C_TILE_BG, font=vfont, anchor='e')
        val_lbl.place(relx=0.95, rely=0.62, anchor='e')

        return {"var": val_var, "lbl": val_lbl, "unit": u, "label": lbl}

    def _build_right(self, parent: tk.Frame) -> None:
        right = _frame(parent, C_WIN_BG)
        right.pack(side=tk.LEFT, fill=tk.Y, pady=8)

        # ── Mode badge ────────────────────────────────────────────────
        _label(right, "MODE", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 3))
        mode_outer, mode_inner = _tile(right)
        mode_outer.pack(fill=tk.X, pady=(0, 6))
        mode_inner.configure(height=52, width=200)
        mode_inner.pack_propagate(False)
        self._w_mode = tk.Label(mode_inner, text="---", fg=_MODE_DEFAULT[0],
                                bg=_MODE_DEFAULT[1], font=self._f_badge, anchor='center')
        self._w_mode.pack(fill=tk.BOTH, expand=True)

        # ── Input badge ───────────────────────────────────────────────
        _label(right, "INPUT", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 3))
        inp_outer, inp_inner = _tile(right)
        inp_outer.pack(fill=tk.X, pady=(0, 8))
        inp_inner.configure(height=44, width=200)
        inp_inner.pack_propagate(False)
        self._w_input = tk.Label(inp_inner, text="---", fg=C_OFFLINE,
                                 bg=C_INPUT_OFF_BG, font=self._f_badge_sm, anchor='center')
        self._w_input.pack(fill=tk.BOTH, expand=True)

        _frame(right, C_DIVIDER, height=1).pack(fill=tk.X, pady=(0, 6))

        # ── Set point ─────────────────────────────────────────────────
        _label(right, "SET POINT", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 2))
        sp_frame = _frame(right, C_WIN_BG)
        sp_frame.pack(fill=tk.X, pady=(0, 2))
        self._w_sp1 = self._sp_row(sp_frame)
        self._w_sp2 = self._sp_row(sp_frame)

        _frame(right, C_DIVIDER, height=1).pack(fill=tk.X, pady=6)

        # ── Protection limits ─────────────────────────────────────────
        _label(right, "PROTECTION LIMITS", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 2))
        lim = _frame(right, C_WIN_BG)
        lim.pack(fill=tk.X, pady=(0, 2))
        self._w_ovp = self._limit_row(lim, "OVP", "V")
        self._w_ocp = self._limit_row(lim, "OCP", "A")
        self._w_opp = self._limit_row(lim, "OPP", "W")

        _frame(right, C_DIVIDER, height=1).pack(fill=tk.X, pady=6)

        # ── Range settings ────────────────────────────────────────────
        _label(right, "RANGE", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 2))
        rng = _frame(right, C_WIN_BG)
        rng.pack(fill=tk.X)
        self._w_vrange = self._range_row(rng, "Voltage")
        self._w_crange = self._range_row(rng, "Current")

    def _sp_row(self, parent: tk.Frame) -> dict:
        row = _frame(parent, C_WIN_BG)
        row.pack(fill=tk.X, pady=1)
        lv = tk.StringVar(value="")
        vv = tk.StringVar(value="")
        uv = tk.StringVar(value="")
        lbl = tk.Label(row, textvariable=lv, fg=C_MEAS_LABEL, bg=C_WIN_BG,
                       font=self._mono(9), width=7, anchor='w')
        lbl.pack(side=tk.LEFT)
        val = tk.Label(row, textvariable=vv, fg=C_VALUE_DIM, bg=C_WIN_BG,
                       font=self._mono(14, bold=True), width=8, anchor='e')
        val.pack(side=tk.LEFT)
        unt = tk.Label(row, textvariable=uv, fg=C_UNIT, bg=C_WIN_BG,
                       font=self._mono(10), width=3, anchor='w')
        unt.pack(side=tk.LEFT)
        return {"label_var": lv, "val_var": vv, "unit_var": uv,
                "val_lbl": val, "row": row}

    def _limit_row(self, parent: tk.Frame, tag: str, unit: str) -> dict:
        row = _frame(parent, C_WIN_BG)
        row.pack(fill=tk.X, pady=1)
        _label(row, tag, "#3a5a3a", C_WIN_BG, self._mono(9), width=4,
               anchor='w').pack(side=tk.LEFT)
        vv = tk.StringVar(value="---")
        val = tk.Label(row, textvariable=vv, fg=C_VALUE_DIM, bg=C_WIN_BG,
                       font=self._mono(11, bold=True), width=9, anchor='e')
        val.pack(side=tk.LEFT)
        _label(row, f" {unit}", C_UNIT, C_WIN_BG, self._mono(10)).pack(side=tk.LEFT)
        return {"var": vv, "lbl": val}

    def _range_row(self, parent: tk.Frame, tag: str) -> dict:
        row = _frame(parent, C_WIN_BG)
        row.pack(fill=tk.X, pady=1)
        _label(row, tag, "#3a5a3a", C_WIN_BG, self._mono(9), width=8,
               anchor='w').pack(side=tk.LEFT)
        vv = tk.StringVar(value="---")
        val = tk.Label(row, textvariable=vv, fg=C_VALUE_DIM, bg=C_WIN_BG,
                       font=self._mono(10), anchor='w')
        val.pack(side=tk.LEFT)
        return {"var": vv, "lbl": val}

    def _build_controls(self) -> None:
        """Working controls section."""
        _hline(self, C_DIVIDER).pack(fill=tk.X)
        ctrl = _frame(self, C_CTRL_BTN_BG)
        ctrl.pack(fill=tk.X, padx=10, pady=4)
        inner = _frame(ctrl, C_CTRL_BTN_BG)
        inner.pack(fill=tk.X, padx=8, pady=6)

        _label(inner, "CONTROLS", "#cccccc", C_CTRL_BTN_BG,
               self._mono(8, bold=True), anchor='w').pack(side=tk.LEFT, padx=(0, 12))

        def _btn(text, cmd):
            state = tk.DISABLED if self._demo else tk.NORMAL
            return tk.Button(inner, text=text, state=state, command=cmd,
                             fg="#cccccc", bg="#252525",
                             activebackground="#353535",
                             activeforeground="#ffffff",
                             disabledforeground=C_CTRL_FG,
                             relief=tk.FLAT,
                             highlightbackground=C_CTRL_BTN_BORDER,
                             highlightthickness=1,
                             font=self._f_ctrl, padx=6, pady=2)

        _btn("INPUT ON", self._on_input_on).pack(side=tk.LEFT, padx=2)
        _btn("INPUT OFF", self._on_input_off).pack(side=tk.LEFT, padx=2)
        _label(inner, "  │  ", "#222222", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT)
        _btn("CC", self._on_cc).pack(side=tk.LEFT, padx=2)
        _btn("CV", self._on_cv).pack(side=tk.LEFT, padx=2)
        _btn("CP", self._on_cp).pack(side=tk.LEFT, padx=2)
        _btn("CR", self._on_cr).pack(side=tk.LEFT, padx=2)
        _btn("CCCV", self._on_cccv).pack(side=tk.LEFT, padx=2)
        _label(inner, "  │  ", "#222222", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT)
        _btn("OFF", self._on_off).pack(side=tk.LEFT, padx=2)

        # Set-value entry row
        inner2 = _frame(ctrl, C_CTRL_BTN_BG)
        inner2.pack(fill=tk.X, padx=8, pady=(0, 6))
        _label(inner2, "SET VALUE:", "#cccccc", C_CTRL_BTN_BG,
               self._f_ctrl, anchor='w').pack(side=tk.LEFT, padx=(0, 6))

        self._entry_var = tk.StringVar()
        self._entry = tk.Entry(inner2, width=12, textvariable=self._entry_var,
                       state=tk.DISABLED if self._demo else tk.NORMAL,
                       fg="#cccccc",
                       bg="#1a1a1a",
                       insertbackground="#cccccc",
                       relief=tk.FLAT, font=self._f_ctrl,
                       highlightbackground=C_CTRL_BTN_BORDER,
                       highlightthickness=1)
        self._entry.pack(side=tk.LEFT, padx=(0, 4))
        self._entry.bind('<Return>', lambda e: self._on_apply())

        _btn("APPLY", self._on_apply).pack(side=tk.LEFT)

        if self._demo:
            _label(inner2, "  (controls disabled in demo mode)",
                   "#666666", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT, padx=8)
        else:
            _label(inner2, "  (CC/CV/CP/CR: set value first, then click mode)",
                   "#666666", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT, padx=8)

    def _build_status_bar(self) -> None:
        _hline(self, C_DIVIDER).pack(fill=tk.X)
        bar = _frame(self, C_STATUS_BG)
        bar.pack(fill=tk.X)
        inner = _frame(bar, C_STATUS_BG)
        inner.pack(fill=tk.X, padx=12, pady=5)

        _label(inner, "PROTECTION:", C_STATUS_FG, C_STATUS_BG,
               self._f_status, anchor='w').pack(side=tk.LEFT, padx=(0, 8))

        self._w_prot: dict[str, tk.Label] = {}
        for tag in ("OC", "OV", "OP", "OT", "LRV", "FAN"):
            lbl = tk.Label(inner, text=f" {tag} ", fg=C_PROT_OK_FG,
                           bg=C_PROT_OK_BG, font=self._f_prot,
                           relief=tk.FLAT, padx=4, pady=1)
            lbl.pack(side=tk.LEFT, padx=3)
            self._w_prot[tag] = lbl

        # Right side: poll timing + mode cycle info (demo only)
        self._status_right = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._status_right, fg="#2a3a2a",
                 bg=C_STATUS_BG, font=self._f_status, anchor='e').pack(
            side=tk.RIGHT, padx=12, pady=5)

    # ── Poll / refresh ─────────────────────────────────────────────────────

    def _start_poll(self, interval_ms: int) -> None:
        self._refresh_ms = interval_ms
        if self._demo:
            # No background thread needed; demo generates data on the UI timer
            self._refresh()
        else:
            if not _DRIVER_OK:
                self._state_ref[0] = State(
                    connected=False,
                    error="rf_bench.yertai not importable — run from rf-bench-drivers-yertai/",
                )
                self._refresh()
                return
            t = threading.Thread(
                target=_poll_worker,
                args=(self._port, self._state_ref, self._state_lock, self._stop,
                      self._cmd_queue, self._cmd_lock, self._load_ref),
                daemon=True,
            )
            t.start()
            self._refresh()

    def _refresh(self) -> None:
        """Called periodically on the UI thread: read latest state, update widgets."""
        t0 = time.monotonic()

        if self._demo:
            s = self._demo_src.read()
        else:
            with self._state_lock:
                s = self._state_ref[0]

        self._apply(s)
        elapsed = (time.monotonic() - t0) * 1000
        self.after(max(50, self._refresh_ms - int(elapsed)), self._refresh)

    # ── State → widget update ──────────────────────────────────────────────

    def _apply(self, s: State) -> None:
        # ── header ────────────────────────────────────────────────────
        if s.connected:
            self._conn_dot.config(fg=C_ONLINE)
            self._conn_text.config(text=s.port or "CONNECTED", fg=C_ONLINE)
            self._info_var.set(
                f"Model: {s.model or '—'}   S/N: {s.serial_n or '—'}   "
                f"FW: {s.firmware or '—'}"
            )
            # Show command errors temporarily in status bar
            if s.error and not self._demo:
                self._status_right.set(s.error)
                # Clear error from state after displaying
                s.error = ""
        else:
            self._conn_dot.config(fg=C_OFFLINE)
            self._conn_text.config(text="OFFLINE", fg=C_OFFLINE)
            self._info_var.set(s.error or "Not connected")

        # ── main readouts ─────────────────────────────────────────────
        self._set_readout(self._w_voltage,    s.voltage,    ".3f")
        self._set_readout(self._w_current,    s.current,    ".3f")
        self._set_readout(self._w_power,      s.power,      ".3f")
        self._set_readout(self._w_resistance, s.resistance, ".3f")

        # ── battery accumulators ──────────────────────────────────────
        batt_mode = (s.mode == "BATT")
        self._set_readout(self._w_energy, s.batt_energy_wh,   ".4f",
                          dim=not batt_mode)
        self._set_readout(self._w_charge, s.batt_capacity_ah, ".4f",
                          dim=not batt_mode)

        # ── mode badge ────────────────────────────────────────────────
        if s.mode:
            fg, bg = _MODE_STYLE.get(s.mode, _MODE_DEFAULT)
            self._w_mode.config(text=s.mode, fg=fg, bg=bg)
        else:
            self._w_mode.config(text="---", fg=_MODE_DEFAULT[0], bg=_MODE_DEFAULT[1])

        # ── input badge ───────────────────────────────────────────────
        if s.input == "ON":
            self._w_input.config(text="ON", fg=C_INPUT_ON_FG, bg=C_INPUT_ON_BG)
        elif s.input == "OFF":
            self._w_input.config(text="OFF", fg=C_INPUT_OFF_FG, bg=C_INPUT_OFF_BG)
        else:
            self._w_input.config(text="---", fg=_MODE_DEFAULT[0], bg=_MODE_DEFAULT[1])

        # ── set point ─────────────────────────────────────────────────
        self._set_sp(self._w_sp1, s.sp1_label, s.sp1_value, s.sp1_unit)
        self._set_sp(self._w_sp2, s.sp2_label, s.sp2_value, s.sp2_unit)

        # ── protection limits ─────────────────────────────────────────
        self._set_limit(self._w_ovp, s.ovp, ".2f")
        self._set_limit(self._w_ocp, s.ocp, ".2f")
        self._set_limit(self._w_opp, s.opp, ".2f")

        # ── range settings ────────────────────────────────────────────
        self._set_range(self._w_vrange, s.vrange)
        self._set_range(self._w_crange, s.crange)

        # ── protection status indicators ──────────────────────────────
        active = s.protection or "NONE"
        # protection string is one of: NONE OV OC OP OT LRV FAN
        # map to the badge tag names
        _map = {"OV": "OV", "OC": "OC", "OP": "OP",
                "OT": "OT", "LRV": "LRV", "FAN": "FAN"}
        for tag, lbl in self._w_prot.items():
            hit = (_map.get(active) == tag)
            lbl.config(
                fg=C_PROT_HIT_FG if hit else C_PROT_OK_FG,
                bg=C_PROT_HIT_BG if hit else C_PROT_OK_BG,
            )

        # ── status bar right ──────────────────────────────────────────
        if self._demo:
            idx = self._demo_src._mode_idx
            total = len(_DemoSource._MODES)
            nxt = _DemoSource._MODES[(idx + 1) % total]
            remaining = max(0, self._demo_src._next_mode_change - time.monotonic())
            self._status_right.set(
                f"DEMO  mode {idx+1}/{total}  next: {nxt} in {remaining:.0f}s"
            )
        else:
            self._status_right.set(f"refresh {self._refresh_ms} ms")

    @staticmethod
    def _set_readout(w: dict, value: Optional[float], fmt: str,
                     dim: bool = False) -> None:
        if value is None or dim:
            w["var"].set("---")
            w["lbl"].config(fg=C_VALUE_DIM)
            w["unit"].config(fg=C_VALUE_DIM if dim else C_UNIT)
        else:
            w["var"].set(f"{value:{fmt}}")
            w["lbl"].config(fg=C_VALUE_LIT)
            w["unit"].config(fg=C_UNIT)

    @staticmethod
    def _set_sp(w: dict, label: str, value: Optional[float], unit: str) -> None:
        if not label or value is None:
            w["label_var"].set("")
            w["val_var"].set("")
            w["unit_var"].set("")
            w["val_lbl"].config(fg=C_VALUE_DIM)
        else:
            w["label_var"].set(label)
            w["val_var"].set(f"{value:.3f}")
            w["unit_var"].set(f" {unit}")
            w["val_lbl"].config(fg=C_VALUE_LIT)

    @staticmethod
    def _set_limit(w: dict, value: Optional[float], fmt: str) -> None:
        if value is None:
            w["var"].set("---")
            w["lbl"].config(fg=C_VALUE_DIM)
        else:
            w["var"].set(f"{value:{fmt}}")
            w["lbl"].config(fg="#559955")

    @staticmethod
    def _set_range(w: dict, value: Optional[str]) -> None:
        if not value:
            w["var"].set("---")
            w["lbl"].config(fg=C_VALUE_DIM)
        else:
            w["var"].set(value)
            w["lbl"].config(fg="#559955")

    # ── Control callbacks ──────────────────────────────────────────────────

    def _queue_cmd(self, cmd_func):
        """Queue a command to be executed by the poll thread."""
        with self._cmd_lock:
            self._cmd_queue.append(cmd_func)

    def _on_input_on(self):
        self._queue_cmd(lambda load: load.on())
        self._show_status("Input ON command sent", 2000)

    def _on_input_off(self):
        self._queue_cmd(lambda load: load.off())
        self._show_status("Input OFF command sent", 2000)

    def _show_status(self, msg: str, duration_ms: int = 3000):
        """Show a temporary status message."""
        self._status_right.set(msg)
        self.after(duration_ms, lambda: self._status_right.set(f"refresh {self._refresh_ms} ms"))

    def _on_cc(self):
        try:
            val = float(self._entry_var.get())
            if val < 0 or val > 20:
                raise ValueError("Current must be 0-20 A")
            self._queue_cmd(lambda load: load.CC_mode(val))
            self._entry_var.set("")
            self._show_status(f"CC {val:.3f} A command sent", 2000)
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    def _on_cv(self):
        try:
            val = float(self._entry_var.get())
            if val < 0 or val > 120:
                raise ValueError("Voltage must be 0-120 V")
            self._queue_cmd(lambda load: load.CV_mode(val))
            self._entry_var.set("")
            self._show_status(f"CV {val:.3f} V command sent", 2000)
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    def _on_cp(self):
        try:
            val = float(self._entry_var.get())
            if val < 0 or val > 200:
                raise ValueError("Power must be 0-200 W")
            self._queue_cmd(lambda load: load.CP_mode(val))
            self._entry_var.set("")
            self._show_status(f"CP {val:.3f} W command sent", 2000)
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    def _on_cr(self):
        try:
            val = float(self._entry_var.get())
            if val < 0:
                raise ValueError("Resistance must be > 0 Ω")
            self._queue_cmd(lambda load: load.CR_mode(val))
            self._entry_var.set("")
            self._show_status(f"CR {val:.3f} Ω command sent", 2000)
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    def _on_cccv(self):
        try:
            # Parse two values: current and voltage
            parts = self._entry_var.get().split()
            if len(parts) != 2:
                raise ValueError("CCCV needs 2 values: current(A) voltage(V)")
            i_val = float(parts[0])
            v_val = float(parts[1])
            if i_val < 0 or i_val > 20:
                raise ValueError("Current must be 0-20 A")
            if v_val < 0 or v_val > 120:
                raise ValueError("Voltage must be 0-120 V")
            self._queue_cmd(lambda load: load.CCCV_mode(i_val, v_val))
            self._entry_var.set("")
            self._show_status(f"CCCV {i_val:.3f} A / {v_val:.3f} V command sent", 2000)
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    def _on_off(self):
        """Turn off input (safe mode)."""
        self._queue_cmd(lambda load: load.off())
        self._show_status("OFF command sent", 2000)

    def _on_apply(self):
        """Generic apply - just shows the value is ready."""
        val = self._entry_var.get().strip()
        if val:
            self._show_status(f"Value ready: {val} — now click mode button", 2000)

    # ── Cleanup ────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        """Turn off load before closing (safety)."""
        if not self._demo:
            # Try to turn off the load directly before closing
            with self._state_lock:
                load = self._load_ref[0]
            if load is not None:
                try:
                    load.off()
                except Exception:
                    pass
        self._stop.set()
        # Give poll thread a moment to shut down gracefully
        time.sleep(0.1)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="ET5406A+ Virtual Instrument Panel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python et5406a_panel.py                      # auto-detect CH340 adapter
  python et5406a_panel.py --port /dev/ttyUSB0  # explicit port
  python et5406a_panel.py --interval 3000      # refresh every 3 s (default 2 s)
  python et5406a_panel.py --demo               # simulated data, cycles all modes
""")
    ap.add_argument("--port",     metavar="PORT",
                    help="Serial port (default: auto-detect CH340)")
    ap.add_argument("--interval", metavar="MS",  type=int, default=2000,
                    help="UI refresh interval in ms (default 2000). "
                         "Full poll cycle takes ~2.4 s; set higher if readouts stutter.")
    ap.add_argument("--demo",     action="store_true",
                    help="Run with simulated data — no hardware needed. "
                         "Cycles through all operating modes every ~8 s.")
    args = ap.parse_args()

    if not args.demo and not _DRIVER_OK:
        print("WARNING: rf_bench.yertai could not be imported. "
              "Use --demo to test the UI, or install the driver.", file=sys.stderr)

    panel = ET5406APanel(port=args.port, interval_ms=args.interval, demo=args.demo)
    panel.mainloop()


if __name__ == "__main__":
    main()
