#!/usr/bin/env python3
"""
IC-7300 Virtual Instrument Panel

Graphical monitoring and control front panel for the Icom IC-7300 HF transceiver.
Communicates via Hamlib rigctld (must be running before starting this panel).

Polls the radio via the rf_bench.icom.IC7300 driver in a background thread and
displays frequency, mode, passband, S-meter reading, and AGC state in real time.

Usage:
    # Start rigctld first:
    rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 &

    # Then run panel:
    python ic7300_panel.py                      # default localhost:4532
    python ic7300_panel.py --host localhost     # explicit host
    python ic7300_panel.py --port 4532          # explicit port
    python ic7300_panel.py --interval 500       # UI refresh ms (default 500)
    python ic7300_panel.py --demo               # simulated data, no hardware

Working controls: frequency entry, mode buttons, AGC buttons, quick band buttons.
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
    from rf_bench.icom import IC7300
    from rf_bench.utils import format_freq_short
    _DRIVER_OK = True
except ImportError:
    _DRIVER_OK = False
    def format_freq_short(hz): return f"{hz/1e6:.4f} MHz"


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
C_MEAS_LABEL    = "#8a7744"
C_VALUE_LIT     = "#ffcc33"   # bright amber LED (live value)
C_VALUE_DIM     = "#443320"   # dim amber (no data / "---")
C_UNIT          = "#cc9922"
C_DIVIDER       = "#1c1c1c"
C_ONLINE        = "#33ee55"
C_OFFLINE       = "#cc2222"

# Mode badge colors
_MODE_STYLE = {
    "USB":  ("#33aaff", "#001a2a"),
    "LSB":  ("#33aaff", "#001a2a"),
    "CW":   ("#ffaa33", "#2a1800"),
    "CWR":  ("#ffaa33", "#2a1800"),
    "AM":   ("#ff6633", "#2a0c00"),
    "FM":   ("#66ff33", "#0c2a00"),
    "RTTY": ("#ff33aa", "#2a0018"),
}
_MODE_DEFAULT = ("#888888", "#141414")

# AGC badge colors
_AGC_STYLE = {
    "OFF":  ("#ff3333", "#1a0000"),
    "FAST": ("#33ff33", "#001a00"),
    "MID":  ("#ffaa33", "#1a0e00"),
    "SLOW": ("#3388ff", "#00122a"),
}
_AGC_DEFAULT = ("#888888", "#141414")

C_CTRL_FG       = "#2a2a2a"
C_CTRL_BTN_BG   = "#131313"
C_CTRL_BTN_BORDER = "#1e1e1e"

C_STATUS_BG     = "#0a0a0a"
C_STATUS_FG     = "#667755"


# ─────────────────────────────────────────────────────────────────────────────
# Shared state dataclass (poll thread → UI thread)
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class State:
    freq_hz:      Optional[float] = None
    mode:         str = "---"
    passband_hz:  Optional[int] = None
    strength:     Optional[float] = None
    agc:          int = -1  # 0=off, 1=fast, 2=mid, 3=slow

    # Connection metadata
    connected: bool = False
    error:     str  = ""
    host:      str  = ""
    port:      int  = 0


# ─────────────────────────────────────────────────────────────────────────────
# Demo data source
# ─────────────────────────────────────────────────────────────────────────────

class _DemoSource:
    """
    Generates plausible simulated radio state for --demo mode.

    Drifts around 14.200 MHz, cycles through modes every ~10 s.
    """

    _MODES = ["USB", "LSB", "CW", "AM", "FM", "RTTY"]

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self._mode_idx = 0
        self._next_mode_change = time.monotonic() + 10.0

    @property
    def _t(self) -> float:
        return time.monotonic() - self._t0

    def read(self) -> State:
        t = self._t

        # Cycle modes
        if time.monotonic() >= self._next_mode_change:
            self._mode_idx = (self._mode_idx + 1) % len(self._MODES)
            self._next_mode_change = time.monotonic() + 10.0

        mode = self._MODES[self._mode_idx]
        freq = 14_200_000 + 500 * math.sin(t * 0.1) + random.gauss(0, 10)
        strength = -40 + 10 * math.sin(t * 0.3) + random.gauss(0, 2)
        agc = (int(t / 15) % 4)  # cycle through AGC modes

        passband = {"USB": 2400, "LSB": 2400, "CW": 500, "CWR": 500,
                    "AM": 6000, "FM": 15000, "RTTY": 500}.get(mode, 2400)

        return State(
            freq_hz=freq,
            mode=mode,
            passband_hz=passband,
            strength=strength,
            agc=agc,
            connected=True,
            host="DEMO",
            port=4532,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Live radio state reader
# ─────────────────────────────────────────────────────────────────────────────

def _read_state(rig: "IC7300", host: str, port: int) -> State:
    """Read all displayable state. Runs in the poll thread."""
    s = State(
        connected=True,
        host=host,
        port=port,
    )

    try:
        s.freq_hz = rig.get_frequency()
    except Exception:
        pass

    try:
        mode, pb = rig.get_mode()
        s.mode = mode
        s.passband_hz = pb
    except Exception:
        pass

    try:
        s.strength = rig.get_strength()
    except Exception:
        pass

    try:
        s.agc = rig.get_agc()
    except Exception:
        pass

    return s


def _poll_worker(host: str, port: int, state_ref: list, lock: threading.Lock,
                 stop: threading.Event, cmd_queue: list, cmd_lock: threading.Lock,
                 rig_ref: list) -> None:
    """Background thread: connect, poll, execute commands, store latest state in state_ref[0]."""
    rig = None
    while not stop.is_set():
        # ── connect ────────────────────────────────────────────────────
        if rig is None:
            try:
                rig = IC7300(host, port)
                with lock:
                    rig_ref[0] = rig
            except Exception as e:
                dead = State(connected=False,
                             error=f"Connect failed: {e}",
                             host=host, port=port)
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
                    cmd_func(rig)
                except Exception as e:
                    with lock:
                        s = state_ref[0]
                        s.error = f"Command error: {e}"
                        state_ref[0] = s
            time.sleep(0.2)

        # ── read ───────────────────────────────────────────────────────
        try:
            s = _read_state(rig, host, port)
            with lock:
                state_ref[0] = s
        except Exception as e:
            with lock:
                state_ref[0] = State(connected=False,
                                     error=f"Poll error: {e}",
                                     host=host, port=port)
                rig_ref[0] = None
            try:
                rig.close()
            except Exception:
                pass
            rig = None

        # Throttle poll rate
        time.sleep(0.2)

    if rig:
        try:
            rig.close()
        except Exception:
            pass
        with lock:
            rig_ref[0] = None


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

class IC7300Panel(tk.Tk):
    def __init__(self, host: str, port: int, interval_ms: int, demo: bool) -> None:
        super().__init__()
        self.title("IC-7300  Virtual Panel")
        self.configure(bg=C_WIN_BG)
        self.resizable(False, False)

        self._demo = demo
        self._host = host
        self._port = port

        # Shared state (poll thread → UI thread)
        self._state_ref: list = [State()]
        self._state_lock = threading.Lock()
        self._stop = threading.Event()

        # Demo source (used when --demo)
        self._demo_src = _DemoSource() if demo else None

        # Command queue for sending commands to the radio (thread-safe)
        self._cmd_queue: list = []
        self._cmd_lock = threading.Lock()
        self._rig_ref: list = [None]

        # Choose fonts after Tk() is constructed
        self._f_small  = self._mono(8)
        self._f_label  = self._mono(9)
        self._f_unit   = self._mono(12, bold=True)
        self._f_value  = self._mono(28, bold=True)
        self._f_freq   = self._mono(36, bold=True)
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
        self._build_main(content)
        self._build_controls()
        self._build_status_bar()

    def _build_header(self) -> None:
        hdr = _frame(self, C_HEADER_BG)
        hdr.pack(fill=tk.X, padx=0, pady=0)
        inner = _frame(hdr, C_HEADER_BG)
        inner.pack(fill=tk.X, padx=12, pady=6)

        # Left: branding
        _label(inner, "ICOM  IC-7300", C_HEADER_FG, C_HEADER_BG,
               self._mono(11, bold=True), anchor='w').pack(side=tk.LEFT)
        _label(inner, "  HF/50MHz TRANSCEIVER",
               "#444444", C_HEADER_BG, self._f_header, anchor='w').pack(side=tk.LEFT)

        # Right: connection badge
        self._conn_dot  = _label(inner, "●", C_OFFLINE, C_HEADER_BG,
                                 self._mono(14, bold=True))
        self._conn_dot.pack(side=tk.RIGHT, padx=(6, 0))
        self._conn_text = _label(inner, "OFFLINE", "#666666", C_HEADER_BG,
                                 self._f_header)
        self._conn_text.pack(side=tk.RIGHT)

        # Host / port info line
        info = _frame(hdr, C_HEADER_BG)
        info.pack(fill=tk.X, padx=12, pady=(0, 6))
        self._info_var = tk.StringVar(value="—")
        tk.Label(info, textvariable=self._info_var, fg="#3a4a3a",
                 bg=C_HEADER_BG, font=self._f_header).pack(side=tk.LEFT)

        _hline(self, C_DIVIDER, 1).pack(fill=tk.X)

    def _build_main(self, parent: tk.Frame) -> None:
        main = _frame(parent, C_WIN_BG)
        main.pack(fill=tk.BOTH, pady=8)

        # ── Frequency display (large) ─────────────────────────────────
        _label(main, "FREQUENCY", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 3))
        freq_outer, freq_inner = _tile(main)
        freq_outer.pack(fill=tk.X, pady=(0, 8))
        freq_inner.configure(height=70, width=650)
        freq_inner.pack_propagate(False)
        self._w_freq_var = tk.StringVar(value="---")
        self._w_freq_lbl = tk.Label(freq_inner, textvariable=self._w_freq_var,
                                     fg=C_VALUE_DIM, bg=C_TILE_BG,
                                     font=self._f_freq, anchor='center')
        self._w_freq_lbl.pack(fill=tk.BOTH, expand=True)

        _frame(main, C_DIVIDER, height=1).pack(fill=tk.X, pady=(0, 6))

        # ── Mode / Passband / S-meter / AGC (grid) ───────────────────
        _label(main, "STATUS", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 3))

        grid = _frame(main, C_WIN_BG)
        grid.pack()

        self._w_mode = self._status_tile(grid, "MODE", row=0, col=0)
        self._w_passband = self._status_tile(grid, "PASSBAND", row=0, col=1)
        self._w_strength = self._status_tile(grid, "S-METER", row=1, col=0)
        self._w_agc = self._status_tile(grid, "AGC", row=1, col=1)

    def _status_tile(self, parent: tk.Frame, label: str, row: int, col: int) -> dict:
        """Create a bordered status tile and return its updatable widgets."""
        W, H = 320, 70
        outer, inner = _tile(parent)
        outer.grid(row=row, column=col, padx=3, pady=3)
        inner.configure(width=W, height=H)
        inner.pack_propagate(False)

        # Label (top-left)
        lbl = _label(inner, label, C_MEAS_LABEL, C_TILE_BG, self._f_label, anchor='w')
        lbl.place(x=8, y=5)

        # Value (center)
        val_var = tk.StringVar(value="---")
        val_lbl = tk.Label(inner, textvariable=val_var, fg=C_VALUE_DIM,
                           bg=C_TILE_BG, font=self._f_value, anchor='center')
        val_lbl.place(relx=0.5, rely=0.6, anchor='center')

        return {"var": val_var, "lbl": val_lbl, "label": lbl}

    def _build_controls(self) -> None:
        """Working controls section."""
        _hline(self, C_DIVIDER).pack(fill=tk.X)
        ctrl = _frame(self, C_CTRL_BTN_BG)
        ctrl.pack(fill=tk.X, padx=10, pady=4)

        # Row 1: Mode buttons
        inner = _frame(ctrl, C_CTRL_BTN_BG)
        inner.pack(fill=tk.X, padx=8, pady=(6, 3))

        _label(inner, "MODE", "#cccccc", C_CTRL_BTN_BG,
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
                             font=self._f_ctrl, padx=8, pady=2)

        _btn("USB", lambda: self._on_mode("usb")).pack(side=tk.LEFT, padx=2)
        _btn("LSB", lambda: self._on_mode("lsb")).pack(side=tk.LEFT, padx=2)
        _btn("CW", lambda: self._on_mode("cw")).pack(side=tk.LEFT, padx=2)
        _btn("AM", lambda: self._on_mode("am")).pack(side=tk.LEFT, padx=2)
        _btn("FM", lambda: self._on_mode("fm")).pack(side=tk.LEFT, padx=2)
        _btn("RTTY", lambda: self._on_mode("rtty")).pack(side=tk.LEFT, padx=2)

        _label(inner, "  │  ", "#222222", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT)

        _label(inner, "AGC", "#cccccc", C_CTRL_BTN_BG,
               self._mono(8, bold=True), anchor='w').pack(side=tk.LEFT, padx=(8, 12))

        _btn("OFF", lambda: self._on_agc("off")).pack(side=tk.LEFT, padx=2)
        _btn("FAST", lambda: self._on_agc("fast")).pack(side=tk.LEFT, padx=2)
        _btn("MID", lambda: self._on_agc("mid")).pack(side=tk.LEFT, padx=2)
        _btn("SLOW", lambda: self._on_agc("slow")).pack(side=tk.LEFT, padx=2)

        # Row 2: Frequency entry + band buttons
        inner2 = _frame(ctrl, C_CTRL_BTN_BG)
        inner2.pack(fill=tk.X, padx=8, pady=(3, 6))

        _label(inner2, "FREQ (Hz):", "#cccccc", C_CTRL_BTN_BG,
               self._f_ctrl).pack(side=tk.LEFT, padx=(0, 6))

        self._freq_var = tk.StringVar()
        self._freq_entry = tk.Entry(inner2, width=14, textvariable=self._freq_var,
                                     state=tk.DISABLED if self._demo else tk.NORMAL,
                                     fg="#cccccc", bg="#1a1a1a",
                                     insertbackground="#cccccc",
                                     relief=tk.FLAT, font=self._f_ctrl,
                                     highlightbackground=C_CTRL_BTN_BORDER,
                                     highlightthickness=1)
        self._freq_entry.pack(side=tk.LEFT, padx=(0, 4))
        self._freq_entry.bind('<Return>', lambda e: self._on_set_freq())

        _btn("SET", self._on_set_freq).pack(side=tk.LEFT, padx=2)

        _label(inner2, "  │  ", "#222222", C_CTRL_BTN_BG, self._f_ctrl).pack(side=tk.LEFT)

        _label(inner2, "QUICK BAND:", "#cccccc", C_CTRL_BTN_BG,
               self._mono(8, bold=True)).pack(side=tk.LEFT, padx=(8, 8))

        # HF bands (center frequencies)
        bands = [
            ("160m", 1_850_000),
            ("80m", 3_700_000),
            ("40m", 7_100_000),
            ("20m", 14_200_000),
            ("17m", 18_100_000),
            ("15m", 21_200_000),
            ("12m", 24_920_000),
            ("10m", 28_400_000),
        ]

        for label, freq in bands:
            _btn(label, lambda f=freq: self._on_band(f)).pack(side=tk.LEFT, padx=1)

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
        tk.Label(bar, textvariable=self._status_right, fg="#5a6a4a",
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
                    error="rf_bench.icom not importable — run from rf-bench-drivers-icom/",
                )
                self._refresh()
                return
            t = threading.Thread(
                target=_poll_worker,
                args=(self._host, self._port, self._state_ref, self._state_lock,
                      self._stop, self._cmd_queue, self._cmd_lock, self._rig_ref),
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
            self._conn_text.config(text=f"{s.host}:{s.port}", fg=C_ONLINE)
            self._info_var.set(f"rigctld @ {s.host}:{s.port}")
            if s.error and not self._demo:
                self._status_right.set(s.error)
                s.error = ""
        else:
            self._conn_dot.config(fg=C_OFFLINE)
            self._conn_text.config(text="OFFLINE", fg=C_OFFLINE)
            self._info_var.set(s.error or "Not connected")

        # ── frequency ─────────────────────────────────────────────────
        if s.freq_hz is not None:
            self._w_freq_var.set(format_freq_short(s.freq_hz))
            self._w_freq_lbl.config(fg=C_VALUE_LIT)
        else:
            self._w_freq_var.set("---")
            self._w_freq_lbl.config(fg=C_VALUE_DIM)

        # ── mode ──────────────────────────────────────────────────────
        if s.mode and s.mode != "---":
            fg, bg = _MODE_STYLE.get(s.mode, _MODE_DEFAULT)
            self._w_mode["var"].set(s.mode)
            self._w_mode["lbl"].config(fg=fg, bg=bg)
        else:
            self._w_mode["var"].set("---")
            self._w_mode["lbl"].config(fg=_MODE_DEFAULT[0], bg=_MODE_DEFAULT[1])

        # ── passband ──────────────────────────────────────────────────
        if s.passband_hz is not None:
            pb_khz = s.passband_hz / 1000
            self._w_passband["var"].set(f"{pb_khz:.1f} kHz")
            self._w_passband["lbl"].config(fg=C_VALUE_LIT)
        else:
            self._w_passband["var"].set("---")
            self._w_passband["lbl"].config(fg=C_VALUE_DIM)

        # ── strength ──────────────────────────────────────────────────
        if s.strength is not None and not math.isnan(s.strength):
            # Display as dB (Hamlib 4.x returns dB relative to S9)
            self._w_strength["var"].set(f"{s.strength:.1f} dB")
            self._w_strength["lbl"].config(fg=C_VALUE_LIT)
        else:
            self._w_strength["var"].set("---")
            self._w_strength["lbl"].config(fg=C_VALUE_DIM)

        # ── AGC ───────────────────────────────────────────────────────
        agc_map = {0: "OFF", 1: "FAST", 2: "MID", 3: "SLOW"}
        agc_str = agc_map.get(s.agc, "---")
        if agc_str != "---":
            fg, bg = _AGC_STYLE.get(agc_str, _AGC_DEFAULT)
            self._w_agc["var"].set(agc_str)
            self._w_agc["lbl"].config(fg=fg, bg=bg)
        else:
            self._w_agc["var"].set("---")
            self._w_agc["lbl"].config(fg=_AGC_DEFAULT[0], bg=_AGC_DEFAULT[1])

        # ── status bar ────────────────────────────────────────────────
        if self._demo:
            self._status_right.set("DEMO mode")
        elif not s.error:
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

    def _on_mode(self, mode: str):
        self._queue_cmd(lambda rig: rig.set_mode(mode))
        self._show_status(f"{mode.upper()} mode command sent")

    def _on_agc(self, agc: str):
        self._queue_cmd(lambda rig: rig.set_agc(agc))
        self._show_status(f"AGC {agc.upper()} command sent")

    def _on_set_freq(self):
        try:
            freq_str = self._freq_var.get().strip()
            if not freq_str:
                return

            # Parse frequency (accept Hz, kHz suffix, MHz suffix)
            freq_str_lower = freq_str.lower()
            if 'mhz' in freq_str_lower:
                freq = float(freq_str_lower.replace('mhz', '').strip()) * 1e6
            elif 'khz' in freq_str_lower:
                freq = float(freq_str_lower.replace('khz', '').strip()) * 1e3
            else:
                freq = float(freq_str)

            if freq < 30000 or freq > 74_800_000:
                raise ValueError("Frequency must be 30 kHz to 74.8 MHz")

            self._queue_cmd(lambda rig: rig.set_frequency(freq))
            self._freq_var.set("")
            self._show_status(f"Frequency {freq/1e6:.4f} MHz command sent")
        except ValueError as e:
            self._show_status(f"Error: {e}", 3000)

    def _on_band(self, freq_hz: int):
        self._queue_cmd(lambda rig: rig.set_frequency(freq_hz))
        self._show_status(f"Tuned to {freq_hz/1e6:.3f} MHz")

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
        description="IC-7300 Virtual Instrument Panel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # Start rigctld first:
  rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 &

  # Then run panel:
  python ic7300_panel.py                    # default localhost:4532
  python ic7300_panel.py --host localhost   # explicit host
  python ic7300_panel.py --port 4532        # explicit port
  python ic7300_panel.py --interval 500     # refresh every 500 ms (default)
  python ic7300_panel.py --demo             # simulated data, cycles modes
""")
    ap.add_argument("--host",     metavar="HOST", default="localhost",
                    help="rigctld host (default: localhost)")
    ap.add_argument("--port",     metavar="PORT", type=int, default=4532,
                    help="rigctld port (default: 4532)")
    ap.add_argument("--interval", metavar="MS",  type=int, default=500,
                    help="UI refresh interval in ms (default 500)")
    ap.add_argument("--demo",     action="store_true",
                    help="Run with simulated data — no hardware needed.")
    args = ap.parse_args()

    if not args.demo and not _DRIVER_OK:
        print("WARNING: rf_bench.icom could not be imported. "
              "Use --demo to test the UI, or install the driver.", file=sys.stderr)

    panel = IC7300Panel(host=args.host, port=args.port,
                        interval_ms=args.interval, demo=args.demo)
    panel.mainloop()


if __name__ == "__main__":
    main()
