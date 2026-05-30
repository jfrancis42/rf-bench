#!/usr/bin/env python3
"""
SDM3045X Virtual Instrument Panel

Graphical monitoring front panel for the Siglent SDM3045X bench multimeter
(4.5-digit, 10 readings/s).

Polls the instrument via the rf_bench.siglent.SDM3000X driver in a background
thread and updates measurement readout, function mode, and range settings in real time.

Usage:
    python sdm3045x_panel.py                      # default 10.1.1.63:5025
    python sdm3045x_panel.py --host 10.1.1.63     # explicit IP
    python sdm3045x_panel.py --interval 500       # UI refresh ms (default 500)
    python sdm3045x_panel.py --demo               # simulated data, no hardware

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
    from rf_bench.siglent import SDM3000X
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
C_SECTION_LABEL = "#445566"
C_MEAS_LABEL    = "#4a6688"
C_VALUE_LIT     = "#33ccff"   # bright cyan LED (live value)
C_VALUE_DIM     = "#1c3340"   # dim cyan (no data / "---")
C_UNIT          = "#2299cc"
C_DIVIDER       = "#1c1c1c"
C_ONLINE        = "#33ee55"
C_OFFLINE       = "#cc2222"

# Function badge: (foreground, background) by function string
_FUNC_STYLE: dict[str, tuple[str, str]] = {
    "VDC":   ("#33ccff", "#001222"),
    "VAC":   ("#ff8844", "#1a0c00"),
    "IDC":   ("#ffaa00", "#1a0e00"),
    "IAC":   ("#ff66cc", "#1a0018"),
    "RES2W": ("#44ffcc", "#001a14"),
    "RES4W": ("#88ffcc", "#001814"),
    "FREQ":  ("#ffcc00", "#1a1400"),
    "PER":   ("#ccaa00", "#1a1200"),
    "CONT":  ("#33ee55", "#002a10"),
    "DIOD":  ("#ff4444", "#1a0000"),
    "CAP":   ("#cc88ff", "#10001a"),
    "TEMP":  ("#ffff66", "#1a1a00"),
}
_FUNC_DEFAULT = ("#888888", "#141414")

C_CTRL_FG       = "#2a2a2a"
C_CTRL_BTN_BG   = "#131313"
C_CTRL_BTN_BORDER = "#1e1e1e"

C_STATUS_BG     = "#0a0a0a"
C_STATUS_FG     = "#556677"


# ─────────────────────────────────────────────────────────────────────────────
# Shared state dataclass (poll thread → UI thread)
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class State:
    # Measurement
    value:      Optional[float] = None   # reading value
    unit:       str = ""                 # V, A, Ω, Hz, s, °C, F, "" (continuity)
    function:   Optional[str] = None     # VDC|VAC|IDC|IAC|RES2W|RES4W|FREQ|PER|CONT|DIOD|CAP|TEMP
    range_str:  str = ""                 # AUTO or numeric string

    # Connection metadata
    connected: bool = False
    error:     str  = ""
    model:     str  = ""
    serial_n:  str  = ""
    firmware:  str  = ""
    host:      str  = ""


# ─────────────────────────────────────────────────────────────────────────────
# Demo data source
# ─────────────────────────────────────────────────────────────────────────────

class _DemoSource:
    """
    Generates plausible simulated instrument state for --demo mode.

    Cycles through all measurement functions every ~6 s so the full panel layout
    can be inspected without hardware.
    """

    _FUNCS = [
        ("VDC",   3.299,  "V"),
        ("VAC",   6.125,  "V"),
        ("IDC",   0.247,  "A"),
        ("IAC",   0.133,  "A"),
        ("RES2W", 9985.3, "Ω"),
        ("RES4W", 10004.2,"Ω"),
        ("FREQ",  1000.02,"Hz"),
        ("PER",   0.000999,"s"),
        ("CONT",  12.4,   "Ω"),
        ("DIOD",  0.612,  "V"),
    ]

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self._func_idx = 0
        self._next_func_change = time.monotonic() + 6.0

    @property
    def _t(self) -> float:
        return time.monotonic() - self._t0

    def _advance_func(self) -> None:
        if time.monotonic() >= self._next_func_change:
            self._func_idx = (self._func_idx + 1) % len(self._FUNCS)
            self._next_func_change = time.monotonic() + 6.0

    def read(self) -> State:
        self._advance_func()
        t = self._t
        func, base, unit = self._FUNCS[self._func_idx]

        # Gentle sinusoidal variation + noise
        value = base * (1.0 + 0.003 * math.sin(t * 0.5) + random.gauss(0, 0.0002))

        return State(
            value=value, unit=unit, function=func,
            range_str="AUTO",
            connected=True,
            model="SDM3045X", serial_n="DEMO-001", firmware="1.01.01.22",
            host="DEMO",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Live instrument state reader
# ─────────────────────────────────────────────────────────────────────────────

def _read_state(dmm: "SDM3000X") -> State:
    """Read all displayable state. Runs in the poll thread."""
    s = State(
        connected=True,
        model="SDM3045X",
        host=dmm.host,
    )

    # Simplified: we read the current measurement and infer function from response
    # Real implementation would query :CONF? to get function + range explicitly
    try:
        # Query current function + range (CONF? returns function, range, resolution)
        conf = dmm._query(":CONF?").strip().upper()
        # Format: "VOLT:DC 20,0.0001" or "RES 200000,1"
        parts = conf.split()
        if len(parts) >= 1:
            func_part = parts[0].replace('"', '').strip()
            # Map to our function names
            if "VOLT:DC" in func_part:
                s.function = "VDC"
                s.unit = "V"
            elif "VOLT:AC" in func_part:
                s.function = "VAC"
                s.unit = "V"
            elif "CURR:DC" in func_part:
                s.function = "IDC"
                s.unit = "A"
            elif "CURR:AC" in func_part:
                s.function = "IAC"
                s.unit = "A"
            elif "RES" in func_part and "FOUR" in func_part:
                s.function = "RES4W"
                s.unit = "Ω"
            elif "RES" in func_part:
                s.function = "RES2W"
                s.unit = "Ω"
            elif "FREQ" in func_part:
                s.function = "FREQ"
                s.unit = "Hz"
            elif "PER" in func_part:
                s.function = "PER"
                s.unit = "s"
            elif "CONT" in func_part:
                s.function = "CONT"
                s.unit = "Ω"
            elif "DIOD" in func_part:
                s.function = "DIOD"
                s.unit = "V"

        if len(parts) >= 2:
            range_val = parts[1].split(',')[0]
            s.range_str = range_val if range_val else "AUTO"

        # Read measurement
        val = dmm.read()
        s.value = val
    except Exception:
        pass

    return s


def _poll_worker(host: str, state_ref: list, lock: threading.Lock,
                 stop: threading.Event, cmd_queue: list, cmd_lock: threading.Lock,
                 dmm_ref: list) -> None:
    """Background thread: connect, poll, execute commands, store latest state in state_ref[0]."""
    dmm = None
    while not stop.is_set():
        # ── connect ────────────────────────────────────────────────────
        if dmm is None:
            try:
                dmm = SDM3000X(host)
                with lock:
                    dmm_ref[0] = dmm
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
                    cmd_func(dmm)
                except Exception as e:
                    with lock:
                        s = state_ref[0]
                        s.error = f"Command error: {e}"
                        state_ref[0] = s
            time.sleep(0.3)

        # ── read ───────────────────────────────────────────────────────
        try:
            s = _read_state(dmm)
            with lock:
                state_ref[0] = s
        except Exception as e:
            with lock:
                state_ref[0] = State(connected=False,
                                     error=f"Poll error: {e}",
                                     host=host)
                dmm_ref[0] = None
            try:
                dmm.close()
            except Exception:
                pass
            dmm = None

        # Throttle poll rate
        time.sleep(0.1)

    if dmm:
        try:
            dmm.close()
        except Exception:
            pass
        with lock:
            dmm_ref[0] = None


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

class SDM3045XPanel(tk.Tk):
    def __init__(self, host: str, interval_ms: int, demo: bool) -> None:
        super().__init__()
        self.title("SDM3045X  Virtual Panel")
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
        self._dmm_ref: list = [None]

        # Choose fonts after Tk() is constructed
        self._f_small  = self._mono(8)
        self._f_label  = self._mono(9)
        self._f_unit   = self._mono(16, bold=True)
        self._f_value  = self._mono(42, bold=True)
        self._f_badge  = self._mono(22, bold=True)
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
        self._build_center(content)
        self._build_controls()
        self._build_status_bar()

    def _build_header(self) -> None:
        hdr = _frame(self, C_HEADER_BG)
        hdr.pack(fill=tk.X, padx=0, pady=0)
        inner = _frame(hdr, C_HEADER_BG)
        inner.pack(fill=tk.X, padx=12, pady=6)

        # Left: branding
        _label(inner, "SIGLENT  SDM3045X", C_HEADER_FG, C_HEADER_BG,
               self._mono(11, bold=True), anchor='w').pack(side=tk.LEFT)
        _label(inner, "  4.5-DIGIT BENCH MULTIMETER",
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
        tk.Label(info, textvariable=self._info_var, fg="#3a4a5a",
                 bg=C_HEADER_BG, font=self._f_header).pack(side=tk.LEFT)

        _hline(self, C_DIVIDER, 1).pack(fill=tk.X)

    def _build_center(self, parent: tk.Frame) -> None:
        center = _frame(parent, C_WIN_BG)
        center.pack(fill=tk.BOTH, pady=8)

        # ── Function badge ─────────────────────────────────────────────
        _label(center, "FUNCTION", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 3))
        func_outer, func_inner = _tile(center)
        func_outer.pack(fill=tk.X, pady=(0, 8))
        func_inner.configure(height=56, width=600)
        func_inner.pack_propagate(False)
        self._w_func = tk.Label(func_inner, text="---", fg=_FUNC_DEFAULT[0],
                                bg=_FUNC_DEFAULT[1], font=self._f_badge, anchor='center')
        self._w_func.pack(fill=tk.BOTH, expand=True)

        # ── Main readout tile ──────────────────────────────────────────
        _label(center, "MEASUREMENT", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 4))

        outer, inner = _tile(center)
        outer.pack(fill=tk.X, pady=(0, 8))
        inner.configure(width=600, height=110)
        inner.pack_propagate(False)

        # Unit (bottom-right)
        self._w_unit_var = tk.StringVar(value="")
        u = tk.Label(inner, textvariable=self._w_unit_var, fg=C_UNIT, bg=C_TILE_BG,
                     font=self._f_unit, anchor='e')
        u.place(relx=0.97, rely=0.98, anchor='se')

        # Value (right-aligned, vertically centred)
        self._w_val_var = tk.StringVar(value="---")
        self._w_val_lbl = tk.Label(inner, textvariable=self._w_val_var, fg=C_VALUE_DIM,
                           bg=C_TILE_BG, font=self._f_value, anchor='e')
        self._w_val_lbl.place(relx=0.94, rely=0.58, anchor='e')

        # ── Range display ──────────────────────────────────────────────
        _label(center, "RANGE", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 3))
        range_frame = _frame(center, C_WIN_BG)
        range_frame.pack(fill=tk.X)
        self._w_range_var = tk.StringVar(value="---")
        tk.Label(range_frame, textvariable=self._w_range_var, fg=C_VALUE_DIM,
                 bg=C_WIN_BG, font=self._mono(12), anchor='w').pack(side=tk.LEFT)

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

        _btn("VDC", self._on_vdc).pack(side=tk.LEFT, padx=2)
        _btn("VAC", self._on_vac).pack(side=tk.LEFT, padx=2)
        _btn("IDC", self._on_idc).pack(side=tk.LEFT, padx=2)
        _btn("IAC", self._on_iac).pack(side=tk.LEFT, padx=2)
        _label(inner, "  │  ", "#222222", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT)
        _btn("2W Ω", self._on_2w).pack(side=tk.LEFT, padx=2)
        _btn("4W Ω", self._on_4w).pack(side=tk.LEFT, padx=2)
        _label(inner, "  │  ", "#222222", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT)
        _btn("FREQ", self._on_freq).pack(side=tk.LEFT, padx=2)
        _btn("DIODE", self._on_diode).pack(side=tk.LEFT, padx=2)
        _btn("CONT", self._on_cont).pack(side=tk.LEFT, padx=2)

        if self._demo:
            _label(inner, "  (controls disabled in demo mode)",
                   "#666666", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT, padx=8)

        _label(inner, "  (controls not active — future version)",
               "#1e1e1e", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT, padx=8)

    def _build_status_bar(self) -> None:
        _hline(self, C_DIVIDER).pack(fill=tk.X)
        bar = _frame(self, C_STATUS_BG)
        bar.pack(fill=tk.X)
        inner = _frame(bar, C_STATUS_BG)
        inner.pack(fill=tk.X, padx=12, pady=5)

        self._status_right = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._status_right, fg="#2a3a5a",
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
                    error="rf_bench.siglent not importable — run from rf-bench-drivers-siglent/",
                )
                self._refresh()
                return
            t = threading.Thread(
                target=_poll_worker,
                args=(self._host, self._state_ref, self._state_lock, self._stop,
                      self._cmd_queue, self._cmd_lock, self._dmm_ref),
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
            self._info_var.set(
                f"Model: {s.model or '—'}   Host: {s.host}"
            )
            if s.error and not self._demo:
                self._status_right.set(s.error)
                s.error = ""
        else:
            self._conn_dot.config(fg=C_OFFLINE)
            self._conn_text.config(text="OFFLINE", fg=C_OFFLINE)
            self._info_var.set(s.error or "Not connected")

        # ── function badge ────────────────────────────────────────────
        if s.function:
            fg, bg = _FUNC_STYLE.get(s.function, _FUNC_DEFAULT)
            self._w_func.config(text=s.function, fg=fg, bg=bg)
        else:
            self._w_func.config(text="---", fg=_FUNC_DEFAULT[0], bg=_FUNC_DEFAULT[1])

        # ── main readout ──────────────────────────────────────────────
        if s.value is not None:
            # Format with appropriate precision
            if abs(s.value) < 0.001:
                val_str = f"{s.value:.6f}"
            elif abs(s.value) < 1:
                val_str = f"{s.value:.5f}"
            elif abs(s.value) < 100:
                val_str = f"{s.value:.4f}"
            else:
                val_str = f"{s.value:.3f}"
            self._w_val_var.set(val_str)
            self._w_val_lbl.config(fg=C_VALUE_LIT)
            self._w_unit_var.set(s.unit)
        else:
            self._w_val_var.set("---")
            self._w_val_lbl.config(fg=C_VALUE_DIM)
            self._w_unit_var.set("")

        # ── range ─────────────────────────────────────────────────────
        if s.range_str:
            self._w_range_var.set(s.range_str)
        else:
            self._w_range_var.set("---")

        # ── status bar ────────────────────────────────────────────────
        if self._demo:
            idx = self._demo_src._func_idx
            total = len(_DemoSource._FUNCS)
            nxt_idx = (idx + 1) % total
            nxt = _DemoSource._FUNCS[nxt_idx][0]
            remaining = max(0, self._demo_src._next_func_change - time.monotonic())
            self._status_right.set(
                f"DEMO  func {idx+1}/{total}  next: {nxt} in {remaining:.0f}s"
            )
        else:
            self._status_right.set(f"refresh {self._refresh_ms} ms")

    # ── Control callbacks ──────────────────────────────────────────────────

    def _queue_cmd(self, cmd_func):
        """Queue a command to be executed by the poll thread."""
        with self._cmd_lock:
            self._cmd_queue.append(cmd_func)

    def _show_status(self, msg: str, duration_ms: int = 2000):
        """Show a temporary status message."""
        self._status_right.set(msg)
        self.after(duration_ms, lambda: self._status_right.set(f"refresh {self._refresh_ms} ms"))

    def _on_vdc(self):
        self._queue_cmd(lambda dmm: dmm.configure_vdc())
        self._show_status("VDC mode command sent")

    def _on_vac(self):
        self._queue_cmd(lambda dmm: dmm.configure_vac())
        self._show_status("VAC mode command sent")

    def _on_idc(self):
        self._queue_cmd(lambda dmm: dmm.configure_idc())
        self._show_status("IDC mode command sent")

    def _on_iac(self):
        self._queue_cmd(lambda dmm: dmm.configure_iac())
        self._show_status("IAC mode command sent")

    def _on_2w(self):
        self._queue_cmd(lambda dmm: dmm.configure_resistance(four_wire=False))
        self._show_status("2W Ω mode command sent")

    def _on_4w(self):
        self._queue_cmd(lambda dmm: dmm.configure_resistance(four_wire=True))
        self._show_status("4W Ω mode command sent")

    def _on_freq(self):
        self._queue_cmd(lambda dmm: dmm.configure_frequency())
        self._show_status("FREQ mode command sent")

    def _on_diode(self):
        self._queue_cmd(lambda dmm: dmm.configure_diode())
        self._show_status("DIODE mode command sent")

    def _on_cont(self):
        self._queue_cmd(lambda dmm: dmm.configure_continuity())
        self._show_status("CONTINUITY mode command sent")

    # ── Cleanup ────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        self._stop.set()
        time.sleep(0.1)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="SDM3045X Virtual Instrument Panel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python sdm3045x_panel.py                    # default 10.1.1.63:5025
  python sdm3045x_panel.py --host 10.1.1.63   # explicit IP
  python sdm3045x_panel.py --interval 500     # refresh every 500 ms (default 500)
  python sdm3045x_panel.py --demo             # simulated data, cycles all functions
""")
    ap.add_argument("--host",     metavar="HOST", default="10.1.1.63",
                    help="Instrument IP address (default: 10.1.1.63)")
    ap.add_argument("--interval", metavar="MS",  type=int, default=500,
                    help="UI refresh interval in ms (default 500)")
    ap.add_argument("--demo",     action="store_true",
                    help="Run with simulated data — no hardware needed. "
                         "Cycles through all measurement functions every ~6 s.")
    args = ap.parse_args()

    if not args.demo and not _DRIVER_OK:
        print("WARNING: rf_bench.siglent could not be imported. "
              "Use --demo to test the UI, or install the driver.", file=sys.stderr)

    panel = SDM3045XPanel(host=args.host, interval_ms=args.interval, demo=args.demo)
    panel.mainloop()


if __name__ == "__main__":
    main()
