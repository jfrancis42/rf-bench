#!/usr/bin/env python3
"""
SPD3303X Virtual Instrument Panel

Graphical monitoring front panel for the Siglent SPD3303X-E triple-output
programmable bench power supply (2×32V/3.2A + 1×fixed).

Polls the instrument via the rf_bench.siglent.SPD3303X driver in a background
thread and updates channel voltage, current, power, output state, CV/CC mode,
and tracking configuration in real time.

Usage:
    python spd3303x_panel.py                      # default 10.1.1.56:5025
    python spd3303x_panel.py --host 10.1.1.56     # explicit IP
    python spd3303x_panel.py --interval 1000      # UI refresh ms (default 1000)
    python spd3303x_panel.py --demo               # simulated data, no hardware

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
    from rf_bench.siglent import SPD3303X, TRACKING_INDEPENDENT, TRACKING_SERIES, TRACKING_PARALLEL
    _DRIVER_OK = True
except ImportError:
    _DRIVER_OK = False
    TRACKING_INDEPENDENT = "INDEP"
    TRACKING_SERIES = "SER"
    TRACKING_PARALLEL = "PARA"


# ─────────────────────────────────────────────────────────────────────────────
# Color palette
# ─────────────────────────────────────────────────────────────────────────────

C_WIN_BG        = "#141414"
C_HEADER_BG     = "#0a0a0a"
C_HEADER_FG     = "#999999"
C_PANEL_BG      = "#0d0d0d"
C_TILE_BG       = "#0f0f0f"
C_TILE_BORDER   = "#232323"
C_SECTION_LABEL = "#665544"
C_MEAS_LABEL    = "#886644"
C_VALUE_LIT     = "#ffcc33"   # bright amber LED (live value)
C_VALUE_DIM     = "#443320"   # dim brown (no data / "---")
C_UNIT          = "#cc9922"
C_DIVIDER       = "#1c1c1c"
C_ONLINE        = "#33ee55"
C_OFFLINE       = "#cc2222"

# Channel badge colors
C_CH1_FG = "#ff6644"
C_CH1_BG = "#1a0800"
C_CH2_FG = "#44ff66"
C_CH2_BG = "#001a08"
C_CH3_FG = "#6644ff"
C_CH3_BG = "#08001a"

# Mode badge: CV / CC
C_CV_FG = "#22aaff"
C_CV_BG = "#001222"
C_CC_FG = "#ffaa00"
C_CC_BG = "#1a0e00"

C_OUTPUT_ON_FG   = "#33ee55"
C_OUTPUT_ON_BG   = "#002a10"
C_OUTPUT_OFF_FG  = "#ff3333"
C_OUTPUT_OFF_BG  = "#1a0000"

C_CTRL_FG       = "#2a2a2a"
C_CTRL_BTN_BG   = "#131313"
C_CTRL_BTN_BORDER = "#1e1e1e"

C_STATUS_BG     = "#0a0a0a"
C_STATUS_FG     = "#776655"


# ─────────────────────────────────────────────────────────────────────────────
# Shared state dataclass (poll thread → UI thread)
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class ChannelState:
    output:      bool = False
    voltage:     Optional[float] = None   # measured V
    current:     Optional[float] = None   # measured A
    power:       Optional[float] = None   # measured W
    v_setpoint:  Optional[float] = None   # V set
    i_setpoint:  Optional[float] = None   # A limit
    mode:        str = "---"              # CV | CC


@dataclasses.dataclass
class State:
    ch1: ChannelState = dataclasses.field(default_factory=ChannelState)
    ch2: ChannelState = dataclasses.field(default_factory=ChannelState)
    ch3: ChannelState = dataclasses.field(default_factory=ChannelState)

    tracking: str = TRACKING_INDEPENDENT  # INDEP | SER | PARA

    # Connection metadata
    connected: bool = False
    error:     str  = ""
    model:     str  = ""
    host:      str  = ""


# ─────────────────────────────────────────────────────────────────────────────
# Demo data source
# ─────────────────────────────────────────────────────────────────────────────

class _DemoSource:
    """
    Generates plausible simulated instrument state for --demo mode.

    Cycles tracking mode every ~10 s.
    """

    _TRACKING = [TRACKING_INDEPENDENT, TRACKING_SERIES, TRACKING_PARALLEL]

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self._track_idx = 0
        self._next_track_change = time.monotonic() + 10.0

    @property
    def _t(self) -> float:
        return time.monotonic() - self._t0

    def _advance_tracking(self) -> None:
        if time.monotonic() >= self._next_track_change:
            self._track_idx = (self._track_idx + 1) % len(self._TRACKING)
            self._next_track_change = time.monotonic() + 10.0

    def read(self) -> State:
        self._advance_tracking()
        t = self._t
        track = self._TRACKING[self._track_idx]

        # CH1: gentle variation + noise
        v1 = 5.0 + 0.01 * math.sin(t * 0.3) + random.gauss(0, 0.001)
        i1 = 0.5 + 0.005 * math.sin(t * 0.25 + 1.2) + random.gauss(0, 0.0002)
        p1 = v1 * i1

        # CH2: mirrors CH1 in some modes
        if track == TRACKING_SERIES:
            v2 = v1
            i2 = i1
        elif track == TRACKING_PARALLEL:
            v2 = v1
            i2 = 0.5 + 0.005 * math.sin(t * 0.28) + random.gauss(0, 0.0002)
        else:  # INDEP
            v2 = 12.0 + 0.01 * math.sin(t * 0.35) + random.gauss(0, 0.001)
            i2 = 1.2 + 0.01 * math.sin(t * 0.22) + random.gauss(0, 0.0005)
        p2 = v2 * i2

        # CH3: fixed voltage
        v3 = 5.0 + random.gauss(0, 0.0005)
        i3 = 0.05 + random.gauss(0, 0.0001)
        p3 = v3 * i3

        ch1 = ChannelState(
            output=True, voltage=v1, current=i1, power=p1,
            v_setpoint=5.0, i_setpoint=3.2, mode="CV",
        )
        ch2 = ChannelState(
            output=True, voltage=v2, current=i2, power=p2,
            v_setpoint=12.0, i_setpoint=3.2, mode="CV",
        )
        ch3 = ChannelState(
            output=True, voltage=v3, current=i3, power=p3,
            v_setpoint=None, i_setpoint=None, mode="CV",
        )

        return State(
            ch1=ch1, ch2=ch2, ch3=ch3,
            tracking=track,
            connected=True,
            model="SPD3303X-E", host="DEMO",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Live instrument state reader
# ─────────────────────────────────────────────────────────────────────────────

def _read_state(psu: "SPD3303X") -> State:
    """Read all displayable state. Runs in the poll thread."""
    s = State(
        connected=True,
        model="SPD3303X-E",
        host=psu.host,
    )

    # Read tracking mode
    try:
        status = psu.get_status()
        s.tracking = status.get("tracking", TRACKING_INDEPENDENT)
    except Exception:
        pass

    # Read each channel
    for ch_num in (1, 2, 3):
        ch = s.ch1 if ch_num == 1 else (s.ch2 if ch_num == 2 else s.ch3)
        try:
            ch.output = psu.is_enabled(ch_num)
            meas = psu.measure_all(ch_num)
            ch.voltage = meas.get("voltage")
            ch.current = meas.get("current")
            ch.power = meas.get("power")
            ch.mode = psu.get_mode(ch_num)
            if ch_num in (1, 2):
                ch.v_setpoint = psu.get_voltage_setpoint(ch_num)
                ch.i_setpoint = psu.get_current_setpoint(ch_num)
        except Exception:
            pass

    return s


def _poll_worker(host: str, state_ref: list, lock: threading.Lock,
                 stop: threading.Event, cmd_queue: list, cmd_lock: threading.Lock,
                 psu_ref: list) -> None:
    """Background thread: connect, poll, execute commands, store latest state in state_ref[0]."""
    psu = None
    while not stop.is_set():
        # ── connect ────────────────────────────────────────────────────
        if psu is None:
            try:
                psu = SPD3303X(host)
                with lock:
                    psu_ref[0] = psu
            except Exception as e:
                dead = State(connected=False,
                             error=f"Connect failed: {e}",
                             host=host)
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
                    cmd_func(psu)
                except Exception as e:
                    with lock:
                        s = state_ref[0]
                        s.error = f"Command error: {e}"
                        state_ref[0] = s
            time.sleep(0.3)

        # ── read ───────────────────────────────────────────────────────
        try:
            s = _read_state(psu)
            with lock:
                state_ref[0] = s
        except Exception as e:
            with lock:
                state_ref[0] = State(connected=False,
                                     error=f"Poll error: {e}",
                                     host=host)
                psu_ref[0] = None
            try:
                psu.close()
            except Exception:
                pass
            psu = None

        # Throttle poll rate
        time.sleep(0.5)

    if psu:
        try:
            psu.close()
        except Exception:
            pass
        with lock:
            psu_ref[0] = None


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

class SPD3303XPanel(tk.Tk):
    def __init__(self, host: str, interval_ms: int, demo: bool) -> None:
        super().__init__()
        self.title("SPD3303X  Virtual Panel")
        self.configure(bg=C_WIN_BG)
        self.resizable(False, False)

        self._demo = demo
        self._host = host

        # Shared state (poll thread → UI thread)
        self._state_ref: list = [State()]
        self._state_lock = threading.Lock()
        self._stop = threading.Event()

        # Demo source (used when --demo)
        self._demo_src = _DemoSource() if demo else None

        # Command queue for sending commands to the instrument (thread-safe)
        self._cmd_queue: list = []
        self._cmd_lock = threading.Lock()
        self._psu_ref: list = [None]

        # Choose fonts after Tk() is constructed
        self._f_small  = self._mono(8)
        self._f_label  = self._mono(9)
        self._f_unit   = self._mono(10, bold=True)
        self._f_value  = self._mono(16, bold=True)
        self._f_badge  = self._mono(18, bold=True)
        self._f_section = self._mono(8)
        self._f_ctrl   = self._mono(9)
        self._f_status = self._mono(9)
        self._f_header = self._mono(9)

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

        # Three columns: CH1 | CH2 | CH3
        col1 = _frame(content, C_WIN_BG)
        col1.pack(side=tk.LEFT, fill=tk.Y, pady=8, padx=(0, 6))
        self._w_ch1 = self._build_channel(col1, 1, C_CH1_FG, C_CH1_BG)

        _frame(content, C_DIVIDER, width=2).pack(side=tk.LEFT, fill=tk.Y, pady=8)

        col2 = _frame(content, C_WIN_BG)
        col2.pack(side=tk.LEFT, fill=tk.Y, pady=8, padx=6)
        self._w_ch2 = self._build_channel(col2, 2, C_CH2_FG, C_CH2_BG)

        _frame(content, C_DIVIDER, width=2).pack(side=tk.LEFT, fill=tk.Y, pady=8)

        col3 = _frame(content, C_WIN_BG)
        col3.pack(side=tk.LEFT, fill=tk.Y, pady=8, padx=(6, 0))
        self._w_ch3 = self._build_channel(col3, 3, C_CH3_FG, C_CH3_BG, fixed=True)

        self._build_tracking()
        self._build_controls()
        self._build_status_bar()

    def _build_header(self) -> None:
        hdr = _frame(self, C_HEADER_BG)
        hdr.pack(fill=tk.X, padx=0, pady=0)
        inner = _frame(hdr, C_HEADER_BG)
        inner.pack(fill=tk.X, padx=12, pady=6)

        # Left: branding
        _label(inner, "SIGLENT  SPD3303X-E", C_HEADER_FG, C_HEADER_BG,
               self._mono(11, bold=True), anchor='w').pack(side=tk.LEFT)
        _label(inner, "  TRIPLE-OUTPUT PROGRAMMABLE POWER SUPPLY",
               "#444444", C_HEADER_BG, self._f_header, anchor='w').pack(side=tk.LEFT)

        # Right: connection badge
        self._conn_dot  = _label(inner, "●", C_OFFLINE, C_HEADER_BG,
                                 self._mono(14, bold=True))
        self._conn_dot.pack(side=tk.RIGHT, padx=(6, 0))
        self._conn_text = _label(inner, "OFFLINE", "#666666", C_HEADER_BG,
                                 self._f_header)
        self._conn_text.pack(side=tk.RIGHT)

        # Model / host info line
        info = _frame(hdr, C_HEADER_BG)
        info.pack(fill=tk.X, padx=12, pady=(0, 6))
        self._info_var = tk.StringVar(value="—")
        tk.Label(info, textvariable=self._info_var, fg="#3a4a3a",
                 bg=C_HEADER_BG, font=self._f_header).pack(side=tk.LEFT)

        _hline(self, C_DIVIDER, 1).pack(fill=tk.X)

    def _build_channel(self, parent: tk.Frame, ch_num: int, fg_color: str,
                       bg_color: str, fixed: bool = False) -> dict:
        """Build a channel column. Returns dict of widgets for updating."""
        w = {}

        # Channel badge
        _label(parent, f"CHANNEL {ch_num}", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 3))
        badge_outer, badge_inner = _tile(parent)
        badge_outer.pack(fill=tk.X, pady=(0, 6))
        badge_inner.configure(height=44, width=240)
        badge_inner.pack_propagate(False)
        w["badge"] = tk.Label(badge_inner, text=f"CH{ch_num}", fg=fg_color,
                              bg=bg_color, font=self._f_badge, anchor='center')
        w["badge"].pack(fill=tk.BOTH, expand=True)

        # Output state
        _label(parent, "OUTPUT", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 3))
        out_outer, out_inner = _tile(parent)
        out_outer.pack(fill=tk.X, pady=(0, 6))
        out_inner.configure(height=36, width=240)
        out_inner.pack_propagate(False)
        w["output"] = tk.Label(out_inner, text="---", fg=C_OFFLINE,
                               bg=C_OUTPUT_OFF_BG, font=self._mono(14, bold=True),
                               anchor='center')
        w["output"].pack(fill=tk.BOTH, expand=True)

        # Mode badge (CV/CC) — not shown for CH3 fixed
        if not fixed:
            _label(parent, "MODE", C_SECTION_LABEL, C_WIN_BG,
                   self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 3))
            mode_outer, mode_inner = _tile(parent)
            mode_outer.pack(fill=tk.X, pady=(0, 8))
            mode_inner.configure(height=32, width=240)
            mode_inner.pack_propagate(False)
            w["mode"] = tk.Label(mode_inner, text="---", fg="#888888",
                                 bg="#141414", font=self._mono(14, bold=True),
                                 anchor='center')
            w["mode"].pack(fill=tk.BOTH, expand=True)
        else:
            _frame(parent, C_WIN_BG, height=8).pack()

        _frame(parent, C_DIVIDER, height=1).pack(fill=tk.X, pady=(0, 6))

        # Measurements
        _label(parent, "MEASUREMENTS", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 2))
        meas = _frame(parent, C_WIN_BG)
        meas.pack(fill=tk.X, pady=(0, 4))

        w["voltage"] = self._meas_row(meas, "V")
        w["current"] = self._meas_row(meas, "A")
        w["power"]   = self._meas_row(meas, "W")

        # Set points (not shown for CH3 fixed)
        if not fixed:
            _frame(parent, C_DIVIDER, height=1).pack(fill=tk.X, pady=4)
            _label(parent, "SET POINTS", C_SECTION_LABEL, C_WIN_BG,
                   self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 2))
            setpt = _frame(parent, C_WIN_BG)
            setpt.pack(fill=tk.X)
            w["v_set"] = self._meas_row(setpt, "V SET")
            w["i_set"] = self._meas_row(setpt, "I SET")

        return w

    def _meas_row(self, parent: tk.Frame, unit_text: str) -> dict:
        row = _frame(parent, C_WIN_BG)
        row.pack(fill=tk.X, pady=1)

        vv = tk.StringVar(value="---")
        val = tk.Label(row, textvariable=vv, fg=C_VALUE_DIM, bg=C_WIN_BG,
                       font=self._f_value, anchor='e', width=12)
        val.pack(side=tk.LEFT)

        _label(row, f" {unit_text}", C_UNIT, C_WIN_BG, self._f_unit,
               anchor='w').pack(side=tk.LEFT)

        return {"var": vv, "lbl": val}

    def _build_tracking(self) -> None:
        """Tracking mode indicator."""
        _hline(self, C_DIVIDER).pack(fill=tk.X)
        track_frame = _frame(self, C_WIN_BG)
        track_frame.pack(fill=tk.X, padx=10, pady=4)

        _label(track_frame, "TRACKING:", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(side=tk.LEFT, padx=(0, 8))

        self._w_track_var = tk.StringVar(value="---")
        tk.Label(track_frame, textvariable=self._w_track_var, fg=C_VALUE_DIM,
                 bg=C_WIN_BG, font=self._mono(11, bold=True),
                 anchor='w').pack(side=tk.LEFT)

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

        _btn("CH1 ON", lambda: self._on_ch_on(1)).pack(side=tk.LEFT, padx=2)
        _btn("CH1 OFF", lambda: self._on_ch_off(1)).pack(side=tk.LEFT, padx=2)
        _btn("CH2 ON", lambda: self._on_ch_on(2)).pack(side=tk.LEFT, padx=2)
        _btn("CH2 OFF", lambda: self._on_ch_off(2)).pack(side=tk.LEFT, padx=2)
        _btn("CH3 ON", lambda: self._on_ch_on(3)).pack(side=tk.LEFT, padx=2)
        _btn("CH3 OFF", lambda: self._on_ch_off(3)).pack(side=tk.LEFT, padx=2)
        _label(inner, "  │  ", "#222222", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT)
        _btn("INDEP", self._on_indep).pack(side=tk.LEFT, padx=2)
        _btn("SERIES", self._on_series).pack(side=tk.LEFT, padx=2)
        _btn("PARA", self._on_para).pack(side=tk.LEFT, padx=2)

        # Entry row for voltage/current setting
        inner2 = _frame(ctrl, C_CTRL_BTN_BG)
        inner2.pack(fill=tk.X, padx=8, pady=(0, 6))

        _label(inner2, "CH:", "#cccccc", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT, padx=(0, 4))
        self._ch_var = tk.StringVar(value="1")
        tk.Entry(inner2, width=3, textvariable=self._ch_var,
                 state=tk.DISABLED if self._demo else tk.NORMAL,
                 fg="#cccccc", bg="#1a1a1a", insertbackground="#cccccc",
                 relief=tk.FLAT, font=self._f_ctrl,
                 highlightbackground=C_CTRL_BTN_BORDER,
                 highlightthickness=1).pack(side=tk.LEFT, padx=(0, 8))

        _label(inner2, "VOLTAGE (V):", "#cccccc", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT, padx=(0, 4))
        self._volt_var = tk.StringVar()
        tk.Entry(inner2, width=8, textvariable=self._volt_var,
                 state=tk.DISABLED if self._demo else tk.NORMAL,
                 fg="#cccccc", bg="#1a1a1a", insertbackground="#cccccc",
                 relief=tk.FLAT, font=self._f_ctrl,
                 highlightbackground=C_CTRL_BTN_BORDER,
                 highlightthickness=1).pack(side=tk.LEFT, padx=(0, 4))
        _btn("SET", self._on_set_volt).pack(side=tk.LEFT, padx=2)

        _label(inner2, "  CURRENT (A):", "#cccccc", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT, padx=(4, 4))
        self._curr_var = tk.StringVar()
        tk.Entry(inner2, width=8, textvariable=self._curr_var,
                 state=tk.DISABLED if self._demo else tk.NORMAL,
                 fg="#cccccc", bg="#1a1a1a", insertbackground="#cccccc",
                 relief=tk.FLAT, font=self._f_ctrl,
                 highlightbackground=C_CTRL_BTN_BORDER,
                 highlightthickness=1).pack(side=tk.LEFT, padx=(0, 4))
        _btn("SET", self._on_set_curr).pack(side=tk.LEFT, padx=2)

        if self._demo:
            _label(inner2, "  (controls disabled in demo mode)",
                   "#666666", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT, padx=8)

    def _build_status_bar(self) -> None:
        _hline(self, C_DIVIDER).pack(fill=tk.X)
        bar = _frame(self, C_STATUS_BG)
        bar.pack(fill=tk.X)
        inner = _frame(bar, C_STATUS_BG)
        inner.pack(fill=tk.X, padx=12, pady=5)

        self._status_right = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._status_right, fg="#5a4a2a",
                 bg=C_STATUS_BG, font=self._f_status, anchor='e').pack(
            side=tk.RIGHT, padx=12, pady=5)

    # ── Poll / refresh ─────────────────────────────────────────────────────

    def _start_poll(self, interval_ms: int) -> None:
        self._refresh_ms = interval_ms
        if self._demo:
            self._refresh()
        else:
            if not _DRIVER_OK:
                self._state_ref[0] = State(
                    connected=False,
                    error="rf_bench.siglent not importable — run from rf-bench-drivers-siglent/",
                )
                self._refresh()
                return
            t = threading.Thread(
                target=_poll_worker,
                args=(self._host, self._state_ref, self._state_lock, self._stop,
                      self._cmd_queue, self._cmd_lock, self._psu_ref),
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
            self._conn_text.config(text=s.host or "CONNECTED", fg=C_ONLINE)
            self._info_var.set(f"Model: {s.model or '—'}   Host: {s.host}")
            if s.error and not self._demo:
                self._status_right.set(s.error)
                s.error = ""
        else:
            self._conn_dot.config(fg=C_OFFLINE)
            self._conn_text.config(text="OFFLINE", fg=C_OFFLINE)
            self._info_var.set(s.error or "Not connected")

        # ── channels ──────────────────────────────────────────────────
        self._apply_channel(self._w_ch1, s.ch1, fixed=False)
        self._apply_channel(self._w_ch2, s.ch2, fixed=False)
        self._apply_channel(self._w_ch3, s.ch3, fixed=True)

        # ── tracking ──────────────────────────────────────────────────
        track_map = {
            TRACKING_INDEPENDENT: "INDEPENDENT",
            TRACKING_SERIES: "SERIES",
            TRACKING_PARALLEL: "PARALLEL",
        }
        self._w_track_var.set(track_map.get(s.tracking, "---"))

        # ── status bar ────────────────────────────────────────────────
        if self._demo:
            idx = self._demo_src._track_idx
            total = len(_DemoSource._TRACKING)
            nxt_idx = (idx + 1) % total
            nxt = track_map.get(_DemoSource._TRACKING[nxt_idx], "---")
            remaining = max(0, self._demo_src._next_track_change - time.monotonic())
            self._status_right.set(
                f"DEMO  tracking {idx+1}/{total}  next: {nxt} in {remaining:.0f}s"
            )
        else:
            self._status_right.set(f"refresh {self._refresh_ms} ms")

    def _apply_channel(self, w: dict, ch: ChannelState, fixed: bool) -> None:
        # Output state
        if ch.output:
            w["output"].config(text="ON", fg=C_OUTPUT_ON_FG, bg=C_OUTPUT_ON_BG)
        else:
            w["output"].config(text="OFF", fg=C_OUTPUT_OFF_FG, bg=C_OUTPUT_OFF_BG)

        # Mode (CV/CC) — not for CH3
        if not fixed:
            if ch.mode == "CV":
                w["mode"].config(text="CV", fg=C_CV_FG, bg=C_CV_BG)
            elif ch.mode == "CC":
                w["mode"].config(text="CC", fg=C_CC_FG, bg=C_CC_BG)
            else:
                w["mode"].config(text="---", fg="#888888", bg="#141414")

        # Measurements
        if ch.voltage is not None:
            w["voltage"]["var"].set(f"{ch.voltage:.3f}")
            w["voltage"]["lbl"].config(fg=C_VALUE_LIT)
        else:
            w["voltage"]["var"].set("---")
            w["voltage"]["lbl"].config(fg=C_VALUE_DIM)

        if ch.current is not None:
            w["current"]["var"].set(f"{ch.current:.3f}")
            w["current"]["lbl"].config(fg=C_VALUE_LIT)
        else:
            w["current"]["var"].set("---")
            w["current"]["lbl"].config(fg=C_VALUE_DIM)

        if ch.power is not None:
            w["power"]["var"].set(f"{ch.power:.3f}")
            w["power"]["lbl"].config(fg=C_VALUE_LIT)
        else:
            w["power"]["var"].set("---")
            w["power"]["lbl"].config(fg=C_VALUE_DIM)

        # Set points (not for CH3)
        if not fixed:
            if ch.v_setpoint is not None:
                w["v_set"]["var"].set(f"{ch.v_setpoint:.3f}")
                w["v_set"]["lbl"].config(fg=C_VALUE_LIT)
            else:
                w["v_set"]["var"].set("---")
                w["v_set"]["lbl"].config(fg=C_VALUE_DIM)

            if ch.i_setpoint is not None:
                w["i_set"]["var"].set(f"{ch.i_setpoint:.3f}")
                w["i_set"]["lbl"].config(fg=C_VALUE_LIT)
            else:
                w["i_set"]["var"].set("---")
                w["i_set"]["lbl"].config(fg=C_VALUE_DIM)

    # ── Cleanup ────────────────────────────────────────────────────────────

    # ── Control callbacks ──────────────────────────────────────────────────

    def _queue_cmd(self, cmd_func):
        """Queue a command to be executed by the poll thread."""
        with self._cmd_lock:
            self._cmd_queue.append(cmd_func)

    def _show_status(self, msg: str, duration_ms: int = 2000):
        """Show a temporary status message."""
        self._status_right.set(msg)
        self.after(duration_ms, lambda: self._status_right.set(f"refresh {self._refresh_ms} ms"))

    def _on_ch_on(self, ch: int):
        self._queue_cmd(lambda psu: psu.enable(ch))
        self._show_status(f"CH{ch} ON command sent")

    def _on_ch_off(self, ch: int):
        self._queue_cmd(lambda psu: psu.disable(ch))
        self._show_status(f"CH{ch} OFF command sent")

    def _on_indep(self):
        self._queue_cmd(lambda psu: psu.set_tracking(TRACKING_INDEPENDENT))
        self._show_status("INDEPENDENT tracking command sent")

    def _on_series(self):
        self._queue_cmd(lambda psu: psu.set_tracking(TRACKING_SERIES))
        self._show_status("SERIES tracking command sent")

    def _on_para(self):
        self._queue_cmd(lambda psu: psu.set_tracking(TRACKING_PARALLEL))
        self._show_status("PARALLEL tracking command sent")

    def _on_set_volt(self):
        try:
            ch = int(self._ch_var.get())
            if ch not in (1, 2):
                raise ValueError("Channel must be 1 or 2 (CH3 is fixed voltage)")
            volts = float(self._volt_var.get())
            if volts < 0 or volts > 32:
                raise ValueError("Voltage must be 0-32 V")
            self._queue_cmd(lambda psu: psu.set_voltage(ch, volts))
            self._volt_var.set("")
            self._show_status(f"CH{ch} voltage {volts:.3f} V command sent")
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    def _on_set_curr(self):
        try:
            ch = int(self._ch_var.get())
            if ch not in (1, 2):
                raise ValueError("Channel must be 1 or 2 (CH3 current limit is fixed)")
            amps = float(self._curr_var.get())
            if amps < 0 or amps > 3.2:
                raise ValueError("Current must be 0-3.2 A")
            self._queue_cmd(lambda psu: psu.set_current(ch, amps))
            self._curr_var.set("")
            self._show_status(f"CH{ch} current {amps:.3f} A command sent")
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    # ── Cleanup ────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if not self._demo:
            with self._state_lock:
                psu = self._psu_ref[0]
            if psu is not None:
                try:
                    psu.disable_all()
                except Exception:
                    pass
        self._stop.set()
        time.sleep(0.1)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="SPD3303X Virtual Instrument Panel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python spd3303x_panel.py                    # default 10.1.1.56:5025
  python spd3303x_panel.py --host 10.1.1.56   # explicit IP
  python spd3303x_panel.py --interval 1000    # refresh every 1000 ms (default 1000)
  python spd3303x_panel.py --demo             # simulated data, cycles tracking modes
""")
    ap.add_argument("--host",     metavar="HOST", default="10.1.1.56",
                    help="Instrument IP address (default: 10.1.1.56)")
    ap.add_argument("--interval", metavar="MS",  type=int, default=1000,
                    help="UI refresh interval in ms (default 1000)")
    ap.add_argument("--demo",     action="store_true",
                    help="Run with simulated data — no hardware needed.")
    args = ap.parse_args()

    if not args.demo and not _DRIVER_OK:
        print("WARNING: rf_bench.siglent could not be imported. "
              "Use --demo to test the UI, or install the driver.", file=sys.stderr)

    panel = SPD3303XPanel(host=args.host, interval_ms=args.interval, demo=args.demo)
    panel.mainloop()


if __name__ == "__main__":
    main()
