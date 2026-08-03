#!/usr/bin/env python3
"""
SDS2504X Plus Virtual Instrument Panel

Four-channel oscilloscope waveform display with embedded matplotlib.
Polls the instrument in a background thread and updates waveform traces,
trigger settings, and measurement readouts in real time.

Usage:
    python sds2504x_panel.py                    # default 10.1.1.58:5025
    python sds2504x_panel.py --host 10.1.1.58   # explicit IP
    python sds2504x_panel.py --interval 500     # refresh ms (default 500)
    python sds2504x_panel.py --demo             # simulated 4-channel waveforms
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

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..'))
try:
    from rf_bench.siglent import SDS2000X
    _DRIVER_OK = True
except ImportError:
    _DRIVER_OK = False

# ── colours ───────────────────────────────────────────────────────────────────
C_BG      = "#111111"
C_TILE    = "#0f0f0f"
C_BORDER  = "#252525"
C_ON      = "#33ee55"
C_OFF     = "#cc2222"
C_LABEL   = "#4a6688"
C_STATUS  = "#556677"
C_BTN_BG  = "#181818"
C_BTN_FG  = "#2a7aaa"
C_PLOT_BG = "#060c0a"
C_AX_FG   = "#444444"
C_GRID    = "#0d1a14"
C_TRIG    = "#ffaa00"

# Channel colours (match Siglent scope default):
CH_COLORS = ["#f7c800", "#00c4cc", "#ff5555", "#8855ff"]
CH_NAMES  = ["CH1", "CH2", "CH3", "CH4"]

# ── state ─────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class ChannelState:
    enabled:    bool  = True
    vdiv:       float = 1.0      # V/div
    offset:     float = 0.0     # V
    coupling:   str   = "DC"
    waveform:   Optional[np.ndarray] = None
    time_arr:   Optional[np.ndarray] = None
    vpp:        Optional[float] = None
    freq:       Optional[float] = None
    rms:        Optional[float] = None


@dataclasses.dataclass
class State:
    channels:   tuple = dataclasses.field(
                    default_factory=lambda: tuple(ChannelState() for _ in range(4))
                )
    tdiv:       float = 1e-3     # s/div
    trig_level: float = 0.0
    trig_ch:    int   = 0
    trig_slope: str   = "RISE"
    running:    bool  = True
    connected:  bool  = False
    error:      str   = ""
    host:       str   = ""


# ── demo source ───────────────────────────────────────────────────────────────

class _DemoSource:
    def __init__(self):
        self._t0   = time.monotonic()
        self._n    = 1000

    def read(self) -> State:
        t    = time.monotonic() - self._t0
        ts   = np.linspace(0, 10e-3, self._n)   # 10 ms window

        # CH1: 1 kHz sine, 2 Vpp, slight noise
        ch1_w = 2.0 * np.sin(2 * np.pi * 1000 * ts + t * 0.1)
        ch1_w += np.random.normal(0, 0.02, self._n)

        # CH2: 1 kHz square, 3.3 Vpp
        ch2_w = 1.65 * np.sign(np.sin(2 * np.pi * 1000 * ts)) + np.random.normal(0, 0.01, self._n)

        # CH3: 5 kHz pulse train, 5 Vpp
        ch3_w = 2.5 * (np.mod(ts * 5000, 1.0) < 0.1).astype(float)
        ch3_w += np.random.normal(0, 0.02, self._n)

        # CH4: noise
        ch4_w = np.random.normal(0, 0.15, self._n)

        def _ch(w, vdiv, enabled=True):
            return ChannelState(
                enabled=enabled, vdiv=vdiv, offset=0.0, coupling="DC",
                waveform=w, time_arr=ts,
                vpp=float(np.ptp(w)),
                freq=1000.0 if vdiv <= 2.0 else 5000.0,
                rms=float(np.sqrt(np.mean(w**2))),
            )

        return State(
            channels=(_ch(ch1_w, 1.0), _ch(ch2_w, 2.0), _ch(ch3_w, 2.0), _ch(ch4_w, 0.1)),
            tdiv=1e-3, trig_level=0.0, trig_ch=0, trig_slope="RISE",
            running=True, connected=True, host="DEMO",
        )


# ── live reader ───────────────────────────────────────────────────────────────

def _read_channel(scope: "SDS2000X", idx: int) -> ChannelState:
    ch_num = idx + 1
    try:
        enabled  = scope.get_channel_display(ch_num)
        vdiv     = scope.get_vdiv(ch_num)
        offset   = scope.get_offset(ch_num)
        coupling = scope.get_coupling(ch_num)
    except Exception:
        return ChannelState(enabled=False)

    if not enabled:
        return ChannelState(enabled=False, vdiv=vdiv, coupling=coupling)

    try:
        t_arr, w = scope.capture_waveform(ch_num, points=1000)
    except Exception:
        t_arr = w = None

    vpp = freq = rms = None
    if w is not None and len(w):
        vpp  = float(np.ptp(w))
        rms  = float(np.sqrt(np.mean(w**2)))
        try:
            freq = float(scope.measure(ch_num, "FREQ"))
        except Exception:
            pass

    return ChannelState(
        enabled=True, vdiv=vdiv, offset=offset, coupling=coupling,
        waveform=w, time_arr=t_arr, vpp=vpp, freq=freq, rms=rms,
    )


def _read_state(scope: "SDS2000X", host: str) -> State:
    channels = tuple(_read_channel(scope, i) for i in range(4))
    try:
        tdiv       = scope.get_tdiv()
        trig_level = scope.get_trigger_level()
        trig_ch    = scope.get_trigger_source()
        running    = scope.is_running()
    except Exception:
        tdiv = 1e-3; trig_level = 0.0; trig_ch = 0; running = True
    return State(
        channels=channels, tdiv=tdiv,
        trig_level=trig_level, trig_ch=trig_ch,
        running=running, connected=True, host=host,
    )


def _poll_worker(host: str, state_ref: list, lock: threading.Lock,
                 stop: threading.Event, interval_s: float,
                 cmd_queue: list, cmd_lock: threading.Lock):
    scope = None
    while not stop.is_set():
        if scope is None:
            try:
                scope = SDS2000X(host)
                with lock:
                    state_ref[0] = dataclasses.replace(state_ref[0],
                        connected=True, host=host)
            except Exception as e:
                with lock:
                    state_ref[0] = State(connected=False, error=str(e), host=host)
                stop.wait(5.0)
                continue

        with cmd_lock:
            pending = list(cmd_queue)
            cmd_queue.clear()
        for fn in pending:
            try: fn(scope)
            except Exception as e:
                with lock:
                    s = state_ref[0]
                    state_ref[0] = dataclasses.replace(s, error=str(e))

        try:
            s = _read_state(scope, host)
            with lock:
                state_ref[0] = s
        except Exception as e:
            with lock:
                state_ref[0] = State(connected=False, error=str(e), host=host)
            try: scope.close()
            except Exception: pass
            scope = None

        stop.wait(interval_s)

    if scope:
        try: scope.close()
        except Exception: pass


# ── panel ─────────────────────────────────────────────────────────────────────

def _fmt_si(val: float, unit: str) -> str:
    if val is None: return "---"
    if abs(val) >= 1e6:  return f"{val/1e6:.3f} M{unit}"
    if abs(val) >= 1e3:  return f"{val/1e3:.3f} k{unit}"
    if abs(val) >= 1.0:  return f"{val:.4f} {unit}"
    if abs(val) >= 1e-3: return f"{val*1e3:.3f} m{unit}"
    if abs(val) >= 1e-6: return f"{val*1e6:.3f} µ{unit}"
    return f"{val:.3e} {unit}"


class SDS2504XPanel:
    def __init__(self, root: tk.Tk, args):
        self._root      = root
        self._args      = args
        self._lock      = threading.Lock()
        self._state_ref = [State()]
        self._cmd_queue: list = []
        self._cmd_lock  = threading.Lock()
        self._stop      = threading.Event()
        self._interval  = args.interval / 1000.0

        root.title("SDS2504X Plus")
        root.configure(bg=C_BG)

        self._build_ui()
        self._start_poll(args)
        self._tick()

    def _build_ui(self):
        fnt_hdr  = tkfont.Font(family="Helvetica", size=10, weight="bold")
        fnt_val  = tkfont.Font(family="Courier",   size=9,  weight="bold")
        fnt_sub  = tkfont.Font(family="Helvetica", size=8)
        fnt_btn  = tkfont.Font(family="Helvetica", size=8)

        # Header
        hdr = tk.Frame(self._root, bg="#0a0a0a", pady=4)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="SDS2504X PLUS  4-CHANNEL OSCILLOSCOPE",
                 fg="#999999", bg="#0a0a0a", font=fnt_hdr).pack(side=tk.LEFT, padx=10)
        self._run_lbl  = tk.Label(hdr, text="RUN", fg=C_ON, bg="#0a0a0a", font=fnt_hdr)
        self._run_lbl.pack(side=tk.RIGHT, padx=16)
        self._conn_lbl = tk.Label(hdr, text="⬤ OFFLINE", fg=C_OFF, bg="#0a0a0a", font=fnt_sub)
        self._conn_lbl.pack(side=tk.RIGHT, padx=8)

        # Main: waveform plot | right measurement panel
        main = tk.Frame(self._root, bg=C_BG)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Waveform figure: 4 subplots sharing X axis
        self._fig = Figure(figsize=(7.5, 5.5), dpi=96, facecolor=C_PLOT_BG)
        gs = self._fig.add_gridspec(4, 1, hspace=0.08)
        self._axes = [self._fig.add_subplot(gs[i], facecolor=C_PLOT_BG) for i in range(4)]
        self._lines = []
        for i, (ax, col) in enumerate(zip(self._axes, CH_COLORS)):
            ax.tick_params(colors=C_AX_FG, labelsize=6)
            for spine in ax.spines.values():
                spine.set_edgecolor("#111111")
            ax.grid(True, color=C_GRID, linewidth=0.4)
            ax.set_ylabel(CH_NAMES[i], color=col, fontsize=7, rotation=0, labelpad=20)
            ax.yaxis.set_label_position("right")
            if i < 3:
                ax.set_xticklabels([])
            line, = ax.plot([], [], color=col, linewidth=0.7)
            self._lines.append(line)
        self._axes[-1].set_xlabel("Time (ms)", color=C_AX_FG, fontsize=7)
        self._fig.tight_layout(pad=0.3)

        self._canvas = FigureCanvasTkAgg(self._fig, master=main)
        self._canvas.get_tk_widget().pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Right panel
        right = tk.Frame(main, bg=C_BG, width=185)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        right.pack_propagate(False)

        # Timebase / trigger
        meta = tk.Frame(right, bg=C_TILE,
                        highlightbackground=C_BORDER, highlightthickness=1)
        meta.pack(fill=tk.X, pady=2)
        self._tdiv_var  = tk.StringVar(value="---")
        self._trig_var  = tk.StringVar(value="---")
        for lbl, var in [("T/div", self._tdiv_var), ("Trigger", self._trig_var)]:
            row = tk.Frame(meta, bg=C_TILE)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=lbl+":", fg=C_LABEL, bg=C_TILE,
                     font=fnt_sub, width=8, anchor="w").pack(side=tk.LEFT, padx=4)
            tk.Label(row, textvariable=var, fg=C_TRIG, bg=C_TILE,
                     font=fnt_val).pack(side=tk.LEFT)

        # Per-channel measurement tiles
        self._ch_tiles = []
        for i, col in enumerate(CH_COLORS):
            f = tk.Frame(right, bg=C_TILE,
                         highlightbackground=col, highlightthickness=1)
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=CH_NAMES[i], fg=col, bg=C_TILE,
                     font=fnt_btn).pack(anchor="w", padx=6, pady=(3,0))
            row_vpp = tk.Frame(f, bg=C_TILE); row_vpp.pack(fill=tk.X)
            row_frq = tk.Frame(f, bg=C_TILE); row_frq.pack(fill=tk.X)
            row_rms = tk.Frame(f, bg=C_TILE); row_rms.pack(fill=tk.X)
            vpp_v = tk.StringVar(value="---"); frq_v = tk.StringVar(value="---"); rms_v = tk.StringVar(value="---")
            for row, lbl, var in [(row_vpp,"Vpp",vpp_v),(row_frq,"Freq",frq_v),(row_rms,"RMS",rms_v)]:
                tk.Label(row, text=lbl+":", fg=C_LABEL, bg=C_TILE,
                         font=fnt_sub, width=5, anchor="w").pack(side=tk.LEFT, padx=4)
                tk.Label(row, textvariable=var, fg=col, bg=C_TILE,
                         font=fnt_val).pack(side=tk.LEFT)
            self._ch_tiles.append((vpp_v, frq_v, rms_v))

        # Controls
        tk.Frame(right, bg=C_BORDER, height=1).pack(fill=tk.X, pady=4)
        for txt, cmd in [
            ("Run / Stop",  self._do_run_stop),
            ("Auto Scale",  self._do_auto_scale),
            ("Single",      self._do_single),
            ("Screenshot",  self._do_screenshot),
        ]:
            tk.Button(right, text=txt, bg=C_BTN_BG, fg=C_BTN_FG,
                      relief=tk.FLAT, font=fnt_btn, command=cmd
                      ).pack(fill=tk.X, padx=4, pady=1)

        # Status bar
        bot = tk.Frame(self._root, bg="#0a0a0a", pady=3)
        bot.pack(fill=tk.X)
        self._status_var = tk.StringVar(value="")
        tk.Label(bot, textvariable=self._status_var, fg=C_STATUS, bg="#0a0a0a",
                 font=tkfont.Font(family="Helvetica", size=8)).pack(side=tk.LEFT, padx=8)

    def _enqueue(self, fn):
        with self._cmd_lock:
            self._cmd_queue.append(fn)

    def _do_run_stop(self):
        with self._lock:
            running = self._state_ref[0].running
        if running:
            self._enqueue(lambda s: s.stop())
        else:
            self._enqueue(lambda s: s.run())
        with self._lock:
            st = self._state_ref[0]
            self._state_ref[0] = dataclasses.replace(st, running=not running)

    def _do_auto_scale(self):
        self._enqueue(lambda s: s.auto_scale())

    def _do_single(self):
        self._enqueue(lambda s: s.single())

    def _do_screenshot(self):
        import datetime
        fname = f"sds2504x_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        self._fig.savefig(fname, dpi=150, facecolor=C_PLOT_BG)
        self._status_var.set(f"Saved {fname}")

    def _start_poll(self, args):
        if args.demo:
            self._source = _DemoSource()
            t = threading.Thread(target=self._demo_loop, daemon=True)
        else:
            self._source = None
            t = threading.Thread(
                target=_poll_worker,
                args=(args.host, self._state_ref, self._lock, self._stop,
                      self._interval, self._cmd_queue, self._cmd_lock),
                daemon=True,
            )
        t.start()

    def _demo_loop(self):
        while not self._stop.is_set():
            s = self._source.read()
            with self._lock:
                self._state_ref[0] = s
            time.sleep(0.2)

    def _tick(self):
        with self._lock:
            s = self._state_ref[0]

        if s.connected:
            self._conn_lbl.config(text="⬤ ONLINE", fg=C_ON)
        else:
            self._conn_lbl.config(text="⬤ OFFLINE", fg=C_OFF)
            if s.error:
                self._status_var.set(s.error[:80])

        self._run_lbl.config(text="RUN" if s.running else "STOP",
                             fg=C_ON if s.running else C_OFF)
        self._tdiv_var.set(_fmt_si(s.tdiv, "s/div"))
        trig_str = f"CH{s.trig_ch+1}  {s.trig_level:+.2f} V  {s.trig_slope}"
        self._trig_var.set(trig_str)

        redraw = False
        for i, ch in enumerate(s.channels):
            vpp_v, frq_v, rms_v = self._ch_tiles[i]
            if ch.vpp is not None:
                vpp_v.set(_fmt_si(ch.vpp, "V"))
            else:
                vpp_v.set("---")
            if ch.freq is not None:
                frq_v.set(_fmt_si(ch.freq, "Hz"))
            else:
                frq_v.set("---")
            if ch.rms is not None:
                rms_v.set(_fmt_si(ch.rms, "V"))
            else:
                rms_v.set("---")

            ax   = self._axes[i]
            line = self._lines[i]
            if ch.enabled and ch.waveform is not None and ch.time_arr is not None:
                t_ms = ch.time_arr * 1e3
                line.set_data(t_ms, ch.waveform)
                ax.set_xlim(t_ms[0], t_ms[-1])
                half = ch.vdiv * 4.5
                ax.set_ylim(-half + ch.offset, half + ch.offset)
                line.set_alpha(1.0)
                redraw = True
            else:
                line.set_data([], [])
                line.set_alpha(0.3)

        if redraw:
            self._canvas.draw_idle()

        self._root.after(self._args.interval, self._tick)

    def destroy(self):
        self._stop.set()


def main():
    p = argparse.ArgumentParser(description="SDS2504X Plus virtual panel")
    p.add_argument("--host",     default="10.1.1.58",
                   help="Scope IP address (default 10.1.1.58)")
    p.add_argument("--interval", type=int, default=500,
                   help="Refresh interval in ms (default 500)")
    p.add_argument("--demo",     action="store_true",
                   help="Demo mode — no hardware needed")
    args = p.parse_args()

    root = tk.Tk()
    panel = SDS2504XPanel(root, args)
    root.protocol("WM_DELETE_WINDOW", lambda: (panel.destroy(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
