#!/usr/bin/env python3
"""
SDG1062X Virtual Instrument Panel

Graphical monitoring front panel for the Siglent SDG1062X dual-channel
function generator (60 MHz, arbitrary waveform).

Polls the instrument via the rf_bench.siglent.SDG1000X driver in a background
thread and updates channel frequency, amplitude, phase, output state, and
waveform type in real time.

Usage:
    python sdg1062x_panel.py                      # default 10.1.1.55:5025
    python sdg1062x_panel.py --host 10.1.1.55     # explicit IP
    python sdg1062x_panel.py --interval 1000      # UI refresh ms (default 1000)
    python sdg1062x_panel.py --demo               # simulated data, no hardware

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
    from rf_bench.siglent import SDG1000X
    from rf_bench.utils import format_freq_short, dbm_to_vpp
    _DRIVER_OK = True
except ImportError:
    _DRIVER_OK = False
    def format_freq_short(hz): return f"{hz/1e6:.4f} MHz"
    def dbm_to_vpp(dbm): return 0.6325 * (10 ** (dbm / 20))


# ─────────────────────────────────────────────────────────────────────────────
# Color palette
# ─────────────────────────────────────────────────────────────────────────────

C_WIN_BG        = "#141414"
C_HEADER_BG     = "#0a0a0a"
C_HEADER_FG     = "#999999"
C_PANEL_BG      = "#0d0d0d"
C_TILE_BG       = "#0f0f0f"
C_TILE_BORDER   = "#232323"
C_SECTION_LABEL = "#556644"
C_MEAS_LABEL    = "#6a8844"
C_VALUE_LIT     = "#ccff33"   # bright yellow-green LED (live value)
C_VALUE_DIM     = "#334420"   # dim olive (no data / "---")
C_UNIT          = "#99cc22"
C_DIVIDER       = "#1c1c1c"
C_ONLINE        = "#33ee55"
C_OFFLINE       = "#cc2222"

# Channel badge colors
C_CH1_FG = "#ffaa00"
C_CH1_BG = "#1a0e00"
C_CH2_FG = "#22aaff"
C_CH2_BG = "#001222"

C_OUTPUT_ON_FG   = "#33ee55"
C_OUTPUT_ON_BG   = "#002a10"
C_OUTPUT_OFF_FG  = "#ff3333"
C_OUTPUT_OFF_BG  = "#1a0000"

C_CTRL_FG       = "#2a2a2a"
C_CTRL_BTN_BG   = "#131313"
C_CTRL_BTN_BORDER = "#1e1e1e"

C_STATUS_BG     = "#0a0a0a"
C_STATUS_FG     = "#667755"


# ─────────────────────────────────────────────────────────────────────────────
# Shared state dataclass (poll thread → UI thread)
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class ChannelState:
    output:    bool = False
    freq_hz:   Optional[float] = None
    level_dbm: Optional[float] = None
    level_vpp: Optional[float] = None
    phase_deg: Optional[float] = None
    waveform:  str = "---"


@dataclasses.dataclass
class State:
    ch1: ChannelState = dataclasses.field(default_factory=ChannelState)
    ch2: ChannelState = dataclasses.field(default_factory=ChannelState)

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

    Cycles CH1 output on/off every ~8 s, keeps CH2 always on.
    """

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self._ch1_toggle_next = time.monotonic() + 8.0

    @property
    def _t(self) -> float:
        return time.monotonic() - self._t0

    def read(self) -> State:
        t = self._t

        # CH1: toggle output every 8 s
        ch1_on = (int(t / 8) % 2) == 0

        # Gentle frequency drift + noise
        ch1_f = 14_001_000 + 50 * math.sin(t * 0.2) + random.gauss(0, 1)
        ch2_f = 14_001_500 + 50 * math.sin(t * 0.25 + 1.2) + random.gauss(0, 1)

        ch1 = ChannelState(
            output=ch1_on,
            freq_hz=ch1_f,
            level_dbm=-20.0,
            level_vpp=dbm_to_vpp(-20.0),
            phase_deg=0.0,
            waveform="SINE",
        )
        ch2 = ChannelState(
            output=True,
            freq_hz=ch2_f,
            level_dbm=-20.0,
            level_vpp=dbm_to_vpp(-20.0),
            phase_deg=90.0,
            waveform="SINE",
        )

        return State(
            ch1=ch1, ch2=ch2,
            connected=True,
            model="SDG1062X", host="DEMO",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Live instrument state reader
# ─────────────────────────────────────────────────────────────────────────────

def _read_state(sdg: "SDG1000X") -> State:
    """Read all displayable state. Runs in the poll thread."""
    s = State(
        connected=True,
        model="SDG1062X",
        host=sdg._host,
    )

    for ch_num in (1, 2):
        ch = s.ch1 if ch_num == 1 else s.ch2
        try:
            ch.output = sdg.query_output_state(ch_num)
            info = sdg.query_channel(ch_num)
            ch.freq_hz = info.get("freq_hz")
            ch.level_dbm = info.get("level_dbm")
            if ch.level_dbm is not None:
                ch.level_vpp = dbm_to_vpp(ch.level_dbm)
            ch.phase_deg = info.get("phase_deg")
            ch.waveform = info.get("waveform", "---").upper()
        except Exception:
            pass

    return s


def _poll_worker(host: str, state_ref: list, lock: threading.Lock,
                 stop: threading.Event, cmd_queue: list, cmd_lock: threading.Lock,
                 sdg_ref: list) -> None:
    """Background thread: connect, poll, execute commands, store latest state in state_ref[0]."""
    sdg = None
    while not stop.is_set():
        # ── connect ────────────────────────────────────────────────────
        if sdg is None:
            try:
                sdg = SDG1000X(host)
                with lock:
                    sdg_ref[0] = sdg
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
                    cmd_func(sdg)
                except Exception as e:
                    with lock:
                        s = state_ref[0]
                        s.error = f"Command error: {e}"
                        state_ref[0] = s
            time.sleep(0.3)

        # ── read ───────────────────────────────────────────────────────
        try:
            s = _read_state(sdg)
            with lock:
                state_ref[0] = s
        except Exception as e:
            with lock:
                state_ref[0] = State(connected=False,
                                     error=f"Poll error: {e}",
                                     host=host)
                sdg_ref[0] = None
            try:
                sdg.close()
            except Exception:
                pass
            sdg = None

        # Throttle poll rate
        time.sleep(0.5)

    if sdg:
        try:
            sdg.close()
        except Exception:
            pass
        with lock:
            sdg_ref[0] = None


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

class SDG1062XPanel(tk.Tk):
    def __init__(self, host: str, interval_ms: int, demo: bool) -> None:
        super().__init__()
        self.title("SDG1062X  Virtual Panel")
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
        self._sdg_ref: list = [None]

        # Choose fonts after Tk() is constructed
        self._f_small  = self._mono(8)
        self._f_label  = self._mono(9)
        self._f_unit   = self._mono(11, bold=True)
        self._f_value  = self._mono(18, bold=True)
        self._f_badge  = self._mono(20, bold=True)
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

        # Two columns: CH1 | CH2
        left = _frame(content, C_WIN_BG)
        left.pack(side=tk.LEFT, fill=tk.Y, pady=8, padx=(0, 8))
        self._w_ch1 = self._build_channel(left, 1, C_CH1_FG, C_CH1_BG)

        _frame(content, C_DIVIDER, width=2).pack(side=tk.LEFT, fill=tk.Y, pady=8)

        right = _frame(content, C_WIN_BG)
        right.pack(side=tk.LEFT, fill=tk.Y, pady=8, padx=(8, 0))
        self._w_ch2 = self._build_channel(right, 2, C_CH2_FG, C_CH2_BG)

        self._build_controls()
        self._build_status_bar()

    def _build_header(self) -> None:
        hdr = _frame(self, C_HEADER_BG)
        hdr.pack(fill=tk.X, padx=0, pady=0)
        inner = _frame(hdr, C_HEADER_BG)
        inner.pack(fill=tk.X, padx=12, pady=6)

        # Left: branding
        _label(inner, "SIGLENT  SDG1062X", C_HEADER_FG, C_HEADER_BG,
               self._mono(11, bold=True), anchor='w').pack(side=tk.LEFT)
        _label(inner, "  DUAL-CHANNEL 60 MHz FUNCTION GENERATOR",
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

    def _build_channel(self, parent: tk.Frame, ch_num: int, fg_color: str, bg_color: str) -> dict:
        """Build a channel column. Returns dict of widgets for updating."""
        w = {}

        # Channel badge
        _label(parent, f"CHANNEL {ch_num}", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 3))
        badge_outer, badge_inner = _tile(parent)
        badge_outer.pack(fill=tk.X, pady=(0, 6))
        badge_inner.configure(height=48, width=320)
        badge_inner.pack_propagate(False)
        w["badge"] = tk.Label(badge_inner, text=f"CH{ch_num}", fg=fg_color,
                              bg=bg_color, font=self._f_badge, anchor='center')
        w["badge"].pack(fill=tk.BOTH, expand=True)

        # Output state
        _label(parent, "OUTPUT", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 3))
        out_outer, out_inner = _tile(parent)
        out_outer.pack(fill=tk.X, pady=(0, 8))
        out_inner.configure(height=40, width=320)
        out_inner.pack_propagate(False)
        w["output"] = tk.Label(out_inner, text="---", fg=C_OFFLINE,
                               bg=C_OUTPUT_OFF_BG, font=self._mono(16, bold=True),
                               anchor='center')
        w["output"].pack(fill=tk.BOTH, expand=True)

        _frame(parent, C_DIVIDER, height=1).pack(fill=tk.X, pady=(0, 6))

        # Parameters
        _label(parent, "PARAMETERS", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 2))
        params = _frame(parent, C_WIN_BG)
        params.pack(fill=tk.X, pady=(0, 2))

        w["freq"] = self._param_row(params, "FREQ")
        w["level_dbm"] = self._param_row(params, "LEVEL")
        w["level_vpp"] = self._param_row(params, "Vpp")
        w["phase"] = self._param_row(params, "PHASE")
        w["waveform"] = self._param_row(params, "WAVE")

        return w

    def _param_row(self, parent: tk.Frame, label_text: str) -> dict:
        row = _frame(parent, C_WIN_BG)
        row.pack(fill=tk.X, pady=1)

        _label(row, label_text, C_MEAS_LABEL, C_WIN_BG, self._mono(9),
               width=7, anchor='w').pack(side=tk.LEFT)

        vv = tk.StringVar(value="---")
        val = tk.Label(row, textvariable=vv, fg=C_VALUE_DIM, bg=C_WIN_BG,
                       font=self._f_value, anchor='e', width=18)
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

        _btn("CH1 ON", lambda: self._on_ch_on(1)).pack(side=tk.LEFT, padx=2)
        _btn("CH1 OFF", lambda: self._on_ch_off(1)).pack(side=tk.LEFT, padx=2)
        _btn("CH2 ON", lambda: self._on_ch_on(2)).pack(side=tk.LEFT, padx=2)
        _btn("CH2 OFF", lambda: self._on_ch_off(2)).pack(side=tk.LEFT, padx=2)
        _label(inner, "  │  ", "#222222", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT)
        _btn("SINE", lambda: self._on_sine()).pack(side=tk.LEFT, padx=2)
        _btn("SQUARE", lambda: self._on_square()).pack(side=tk.LEFT, padx=2)
        _btn("RAMP", lambda: self._on_ramp()).pack(side=tk.LEFT, padx=2)

        # Entry row for freq/level setting
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

        _label(inner2, "FREQ (Hz):", "#cccccc", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT, padx=(0, 4))
        self._freq_var = tk.StringVar()
        tk.Entry(inner2, width=12, textvariable=self._freq_var,
                 state=tk.DISABLED if self._demo else tk.NORMAL,
                 fg="#cccccc", bg="#1a1a1a", insertbackground="#cccccc",
                 relief=tk.FLAT, font=self._f_ctrl,
                 highlightbackground=C_CTRL_BTN_BORDER,
                 highlightthickness=1).pack(side=tk.LEFT, padx=(0, 4))
        _btn("SET", self._on_set_freq).pack(side=tk.LEFT, padx=2)

        _label(inner2, "  LEVEL (dBm):", "#cccccc", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT, padx=(4, 4))
        self._level_var = tk.StringVar()
        tk.Entry(inner2, width=8, textvariable=self._level_var,
                 state=tk.DISABLED if self._demo else tk.NORMAL,
                 fg="#cccccc", bg="#1a1a1a", insertbackground="#cccccc",
                 relief=tk.FLAT, font=self._f_ctrl,
                 highlightbackground=C_CTRL_BTN_BORDER,
                 highlightthickness=1).pack(side=tk.LEFT, padx=(0, 4))
        _btn("SET", self._on_set_level).pack(side=tk.LEFT, padx=2)

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
        tk.Label(bar, textvariable=self._status_right, fg="#3a5a2a",
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
                      self._cmd_queue, self._cmd_lock, self._sdg_ref),
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
        self._apply_channel(self._w_ch1, s.ch1)
        self._apply_channel(self._w_ch2, s.ch2)

        # ── status bar ────────────────────────────────────────────────
        if self._demo:
            self._status_right.set("DEMO  mode")
        else:
            self._status_right.set(f"refresh {self._refresh_ms} ms")

    def _apply_channel(self, w: dict, ch: ChannelState) -> None:
        # Output state
        if ch.output:
            w["output"].config(text="ON", fg=C_OUTPUT_ON_FG, bg=C_OUTPUT_ON_BG)
        else:
            w["output"].config(text="OFF", fg=C_OUTPUT_OFF_FG, bg=C_OUTPUT_OFF_BG)

        # Parameters
        if ch.freq_hz is not None:
            w["freq"]["var"].set(format_freq_short(ch.freq_hz))
            w["freq"]["lbl"].config(fg=C_VALUE_LIT)
        else:
            w["freq"]["var"].set("---")
            w["freq"]["lbl"].config(fg=C_VALUE_DIM)

        if ch.level_dbm is not None:
            w["level_dbm"]["var"].set(f"{ch.level_dbm:.2f} dBm")
            w["level_dbm"]["lbl"].config(fg=C_VALUE_LIT)
        else:
            w["level_dbm"]["var"].set("---")
            w["level_dbm"]["lbl"].config(fg=C_VALUE_DIM)

        if ch.level_vpp is not None:
            w["level_vpp"]["var"].set(f"{ch.level_vpp:.4f} Vpp")
            w["level_vpp"]["lbl"].config(fg=C_VALUE_LIT)
        else:
            w["level_vpp"]["var"].set("---")
            w["level_vpp"]["lbl"].config(fg=C_VALUE_DIM)

        if ch.phase_deg is not None:
            w["phase"]["var"].set(f"{ch.phase_deg:.1f}°")
            w["phase"]["lbl"].config(fg=C_VALUE_LIT)
        else:
            w["phase"]["var"].set("---")
            w["phase"]["lbl"].config(fg=C_VALUE_DIM)

        w["waveform"]["var"].set(ch.waveform)
        w["waveform"]["lbl"].config(fg=C_VALUE_LIT if ch.waveform != "---" else C_VALUE_DIM)

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
        self._queue_cmd(lambda sdg: sdg.output_on(ch))
        self._show_status(f"CH{ch} ON command sent")

    def _on_ch_off(self, ch: int):
        self._queue_cmd(lambda sdg: sdg.output_off(ch))
        self._show_status(f"CH{ch} OFF command sent")

    def _on_sine(self):
        try:
            ch = int(self._ch_var.get())
            if ch not in (1, 2):
                raise ValueError("Channel must be 1 or 2")
            self._queue_cmd(lambda sdg: sdg.set_waveform(ch, "SINE"))
            self._show_status(f"CH{ch} SINE command sent")
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    def _on_square(self):
        try:
            ch = int(self._ch_var.get())
            if ch not in (1, 2):
                raise ValueError("Channel must be 1 or 2")
            self._queue_cmd(lambda sdg: sdg.set_waveform(ch, "SQUARE"))
            self._show_status(f"CH{ch} SQUARE command sent")
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    def _on_ramp(self):
        try:
            ch = int(self._ch_var.get())
            if ch not in (1, 2):
                raise ValueError("Channel must be 1 or 2")
            self._queue_cmd(lambda sdg: sdg.set_waveform(ch, "RAMP"))
            self._show_status(f"CH{ch} RAMP command sent")
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    def _on_set_freq(self):
        try:
            ch = int(self._ch_var.get())
            if ch not in (1, 2):
                raise ValueError("Channel must be 1 or 2")
            freq = float(self._freq_var.get())
            if freq < 1e-6 or freq > 60e6:
                raise ValueError("Frequency must be 1 µHz to 60 MHz")
            self._queue_cmd(lambda sdg: sdg.set_frequency(ch, freq))
            self._freq_var.set("")
            self._show_status(f"CH{ch} freq {freq/1e6:.6f} MHz command sent")
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    def _on_set_level(self):
        try:
            ch = int(self._ch_var.get())
            if ch not in (1, 2):
                raise ValueError("Channel must be 1 or 2")
            level = float(self._level_var.get())
            if level < -46 or level > 24:
                raise ValueError("Level must be -46 to +24 dBm")
            self._queue_cmd(lambda sdg: sdg.set_level(ch, level))
            self._level_var.set("")
            self._show_status(f"CH{ch} level {level:.1f} dBm command sent")
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    # ── Cleanup ────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if not self._demo:
            with self._state_lock:
                sdg = self._sdg_ref[0]
            if sdg is not None:
                try:
                    sdg.output_off_all()
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
        description="SDG1062X Virtual Instrument Panel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python sdg1062x_panel.py                    # default 10.1.1.55:5025
  python sdg1062x_panel.py --host 10.1.1.55   # explicit IP
  python sdg1062x_panel.py --interval 1000    # refresh every 1000 ms (default 1000)
  python sdg1062x_panel.py --demo             # simulated data, dual-channel output
""")
    ap.add_argument("--host",     metavar="HOST", default="10.1.1.55",
                    help="Instrument IP address (default: 10.1.1.55)")
    ap.add_argument("--interval", metavar="MS",  type=int, default=1000,
                    help="UI refresh interval in ms (default 1000)")
    ap.add_argument("--demo",     action="store_true",
                    help="Run with simulated data — no hardware needed.")
    args = ap.parse_args()

    if not args.demo and not _DRIVER_OK:
        print("WARNING: rf_bench.siglent could not be imported. "
              "Use --demo to test the UI, or install the driver.", file=sys.stderr)

    panel = SDG1062XPanel(host=args.host, interval_ms=args.interval, demo=args.demo)
    panel.mainloop()


if __name__ == "__main__":
    main()
