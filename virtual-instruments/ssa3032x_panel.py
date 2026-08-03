#!/usr/bin/env python3
"""
SSA3032X Plus Virtual Instrument Panel

Live spectrum display with embedded matplotlib, marker readouts, and controls
for the Siglent SSA3032X Plus spectrum analyzer.

Usage:
    python ssa3032x_panel.py                    # default 10.1.1.60:5025
    python ssa3032x_panel.py --host 10.1.1.60   # explicit IP
    python ssa3032x_panel.py --interval 2000    # refresh ms (default 2000)
    python ssa3032x_panel.py --demo             # simulated data, no hardware
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
    from rf_bench.siglent import SSA3000X
    _DRIVER_OK = True
except ImportError:
    _DRIVER_OK = False

# ── colour palette ────────────────────────────────────────────────────────────
C_BG      = "#111111"
C_TILE    = "#0f0f0f"
C_BORDER  = "#252525"
C_LIT     = "#33ccff"
C_DIM     = "#1c3340"
C_ON      = "#33ee55"
C_OFF     = "#cc2222"
C_WARN    = "#ffaa00"
C_LABEL   = "#4a6688"
C_STATUS  = "#556677"
C_BTN_BG  = "#181818"
C_BTN_FG  = "#2a7aaa"
C_TRACE   = "#33ccff"
C_PEAK    = "#ff4444"
C_GRID    = "#1a2a2a"
C_PLOT_BG = "#080c0c"
C_AX_FG   = "#556677"

# ── state dataclass ───────────────────────────────────────────────────────────

@dataclasses.dataclass
class State:
    freqs:        Optional[np.ndarray] = None   # frequency array (Hz)
    powers:       Optional[np.ndarray] = None   # power array (dBm)
    center_hz:    float = 1_000_000_000.0
    span_hz:      float = 100_000_000.0
    rbw_hz:       float = 3_000_000.0
    ref_level:    float = 0.0
    atten_db:     float = 20.0
    peak_freq:    Optional[float] = None
    peak_dbm:     Optional[float] = None
    tg_on:        bool = False
    tg_level:     float = 0.0
    connected:    bool = False
    error:        str  = ""
    model:        str  = ""
    host:         str  = ""

# ── demo source ───────────────────────────────────────────────────────────────

class _DemoSource:
    def __init__(self):
        self._t0          = time.monotonic()
        self._carrier_hz  = 433_920_000.0
        self._center      = 433_920_000.0
        self._span        = 20_000_000.0
        self._n_pts       = 751

    def read(self) -> State:
        t = time.monotonic() - self._t0
        # Carrier drifts slowly
        carrier = self._carrier_hz + 50_000 * math.sin(t * 0.05)
        freqs   = np.linspace(self._center - self._span/2,
                              self._center + self._span/2, self._n_pts)
        noise   = np.random.normal(-90, 1.5, self._n_pts)
        # Main carrier
        bw      = self._span / self._n_pts * 3
        noise  += 35 * np.exp(-0.5 * ((freqs - carrier) / bw) ** 2)
        # Harmonic
        h2 = carrier * 2
        if freqs[0] < h2 < freqs[-1]:
            noise += 15 * np.exp(-0.5 * ((freqs - h2) / bw) ** 2)

        peak_idx = int(np.argmax(noise))
        return State(
            freqs=freqs, powers=noise,
            center_hz=self._center, span_hz=self._span,
            rbw_hz=10_000, ref_level=0.0, atten_db=20.0,
            peak_freq=float(freqs[peak_idx]),
            peak_dbm=float(noise[peak_idx]),
            tg_on=False, tg_level=0.0,
            connected=True, model="SSA3032X Plus (DEMO)", host="DEMO",
        )

# ── live reader ───────────────────────────────────────────────────────────────

def _read_state(ssa: "SSA3000X") -> State:
    freqs = ssa.get_frequencies()
    powers = ssa.get_trace()
    peak_freq = peak_dbm = None
    try:
        ssa.set_marker(1, freqs[len(freqs)//2])
        ssa.peak_search()
        peak_freq, peak_dbm = ssa.get_marker(1)
    except Exception:
        if powers is not None and len(powers):
            idx = int(np.argmax(powers))
            peak_freq = float(freqs[idx])
            peak_dbm  = float(powers[idx])

    center = ssa.get_center()
    span   = ssa.get_span()
    rbw    = ssa.get_rbw()
    ref    = ssa.get_ref_level()
    atten  = ssa.get_atten()
    return State(
        freqs=freqs, powers=powers,
        center_hz=center, span_hz=span, rbw_hz=rbw,
        ref_level=ref, atten_db=atten,
        peak_freq=peak_freq, peak_dbm=peak_dbm,
        connected=True, host=ssa.host,
    )

def _poll_worker(host: str, state_ref: list, lock: threading.Lock,
                 stop: threading.Event, interval_s: float,
                 cmd_queue: list, cmd_lock: threading.Lock):
    ssa = None
    while not stop.is_set():
        if ssa is None:
            try:
                ssa = SSA3000X(host)
                with lock:
                    state_ref[0] = dataclasses.replace(state_ref[0],
                        connected=True, model="SSA3032X Plus", host=host)
            except Exception as e:
                with lock:
                    state_ref[0] = State(connected=False, error=str(e), host=host)
                stop.wait(5.0)
                continue

        with cmd_lock:
            pending = list(cmd_queue)
            cmd_queue.clear()
        for fn in pending:
            try:
                fn(ssa)
            except Exception as e:
                with lock:
                    s = state_ref[0]
                    state_ref[0] = dataclasses.replace(s, error=str(e))

        try:
            s = _read_state(ssa)
            with lock:
                state_ref[0] = s
        except Exception as e:
            with lock:
                state_ref[0] = State(connected=False, error=str(e), host=host)
            try: ssa.close()
            except Exception: pass
            ssa = None

        stop.wait(interval_s)

    if ssa:
        try: ssa.close()
        except Exception: pass

# ── panel ─────────────────────────────────────────────────────────────────────

def _fmt_freq(hz: float) -> str:
    if abs(hz) >= 1e9: return f"{hz/1e9:.4f} GHz"
    if abs(hz) >= 1e6: return f"{hz/1e6:.4f} MHz"
    if abs(hz) >= 1e3: return f"{hz/1e3:.3f} kHz"
    return f"{hz:.0f} Hz"


class SSAPanelApp:
    def __init__(self, root: tk.Tk, args):
        self._root      = root
        self._args      = args
        self._lock      = threading.Lock()
        self._state_ref = [State()]
        self._cmd_queue: list = []
        self._cmd_lock  = threading.Lock()
        self._stop      = threading.Event()
        self._interval  = args.interval / 1000.0

        root.title("SSA3032X Plus")
        root.configure(bg=C_BG)

        self._build_ui()
        self._start_poll(args)
        self._tick()

    def _build_ui(self):
        fnt_hdr  = tkfont.Font(family="Helvetica", size=10, weight="bold")
        fnt_val  = tkfont.Font(family="Courier",   size=11, weight="bold")
        fnt_sub  = tkfont.Font(family="Helvetica", size=9)
        fnt_btn  = tkfont.Font(family="Helvetica", size=8)

        # Header
        hdr = tk.Frame(self._root, bg="#0a0a0a", pady=4)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="SSA3032X PLUS  SPECTRUM ANALYZER",
                 fg="#999999", bg="#0a0a0a", font=fnt_hdr).pack(side=tk.LEFT, padx=10)
        self._conn_lbl = tk.Label(hdr, text="⬤ OFFLINE", fg=C_OFF,
                                   bg="#0a0a0a", font=fnt_sub)
        self._conn_lbl.pack(side=tk.RIGHT, padx=10)

        # Main area: spectrum on left, tiles on right
        main = tk.Frame(self._root, bg=C_BG)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Spectrum plot
        self._fig = Figure(figsize=(7, 4), dpi=96, facecolor=C_PLOT_BG)
        self._ax  = self._fig.add_subplot(111, facecolor=C_PLOT_BG)
        self._ax.tick_params(colors=C_AX_FG, which="both")
        for spine in self._ax.spines.values():
            spine.set_edgecolor(C_GRID)
        self._ax.grid(True, color=C_GRID, linewidth=0.5)
        self._line, = self._ax.plot([], [], color=C_TRACE, linewidth=0.8)
        self._peak_dot, = self._ax.plot([], [], "o", color=C_PEAK, markersize=5)
        self._ax.set_xlabel("Frequency", color=C_AX_FG, fontsize=8)
        self._ax.set_ylabel("Power (dBm)", color=C_AX_FG, fontsize=8)
        self._ax.tick_params(labelsize=7, colors=C_AX_FG)
        self._fig.tight_layout(pad=0.5)

        self._canvas = FigureCanvasTkAgg(self._fig, master=main)
        self._canvas.get_tk_widget().pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Right panel: measurement tiles + controls
        right = tk.Frame(main, bg=C_BG, width=200)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(8,0))
        right.pack_propagate(False)

        def _tile(label, var):
            f = tk.Frame(right, bg=C_TILE,
                         highlightbackground=C_BORDER, highlightthickness=1)
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=label, fg=C_LABEL, bg=C_TILE,
                     font=fnt_sub, anchor="w").pack(fill=tk.X, padx=6, pady=(4,0))
            tk.Label(f, textvariable=var, fg=C_LIT, bg=C_TILE,
                     font=fnt_val, anchor="e").pack(fill=tk.X, padx=6, pady=(0,4))

        self._center_var  = tk.StringVar(value="---")
        self._span_var    = tk.StringVar(value="---")
        self._rbw_var     = tk.StringVar(value="---")
        self._ref_var     = tk.StringVar(value="---")
        self._atten_var   = tk.StringVar(value="---")
        self._peak_f_var  = tk.StringVar(value="---")
        self._peak_p_var  = tk.StringVar(value="---")

        _tile("Center",      self._center_var)
        _tile("Span",        self._span_var)
        _tile("RBW",         self._rbw_var)
        _tile("Ref Level",   self._ref_var)
        _tile("Attenuation", self._atten_var)
        tk.Frame(right, bg=C_BORDER, height=1).pack(fill=tk.X, pady=4)
        _tile("Peak Freq",   self._peak_f_var)
        _tile("Peak Power",  self._peak_p_var)

        # Controls
        tk.Frame(right, bg=C_BORDER, height=1).pack(fill=tk.X, pady=4)
        self._tg_var = tk.StringVar(value="TG: OFF")
        tk.Label(right, textvariable=self._tg_var, fg=C_STATUS, bg=C_BG,
                 font=fnt_sub).pack()

        for txt, cmd in [
            ("Peak Search", self._do_peak),
            ("Auto Scale",  self._do_auto_scale),
            ("TG On/Off",   self._do_tg_toggle),
            ("Screenshot",  self._do_screenshot),
        ]:
            tk.Button(right, text=txt, bg=C_BTN_BG, fg=C_BTN_FG,
                      relief=tk.FLAT, font=fnt_btn, command=cmd
                      ).pack(fill=tk.X, padx=4, pady=1)

        # Status bar
        bot = tk.Frame(self._root, bg="#0a0a0a", pady=3)
        bot.pack(fill=tk.X, padx=8)
        self._status_var = tk.StringVar(value="")
        tk.Label(bot, textvariable=self._status_var, fg=C_STATUS, bg="#0a0a0a",
                 font=tkfont.Font(family="Helvetica", size=8)).pack(side=tk.LEFT, padx=6)

    # ── controls ──────────────────────────────────────────────────────────────

    def _enqueue(self, fn):
        with self._cmd_lock:
            self._cmd_queue.append(fn)

    def _do_peak(self):
        self._enqueue(lambda ssa: ssa.peak_search())
        self._status_var.set("Peak search")

    def _do_auto_scale(self):
        def _scale(ssa):
            ssa.auto_scale()
        self._enqueue(_scale)
        self._status_var.set("Auto scale")

    def _do_tg_toggle(self):
        with self._lock:
            tg_on = self._state_ref[0].tg_on
        def _toggle(ssa):
            ssa.set_tracking_gen(not tg_on)
            with self._lock:
                s = self._state_ref[0]
                self._state_ref[0] = dataclasses.replace(s, tg_on=not tg_on)
        self._enqueue(_toggle)

    def _do_screenshot(self):
        import datetime
        fname = f"ssa_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        self._fig.savefig(fname, dpi=150, facecolor=C_PLOT_BG)
        self._status_var.set(f"Saved {fname}")

    # ── poll ──────────────────────────────────────────────────────────────────

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
            time.sleep(self._interval)

    # ── UI tick ───────────────────────────────────────────────────────────────

    def _tick(self):
        with self._lock:
            s = self._state_ref[0]

        if s.connected:
            self._conn_lbl.config(text="⬤ ONLINE", fg=C_ON)
        else:
            self._conn_lbl.config(text="⬤ OFFLINE", fg=C_OFF)
            if s.error:
                self._status_var.set(s.error[:80])

        self._center_var.set(_fmt_freq(s.center_hz))
        self._span_var.set(_fmt_freq(s.span_hz))
        self._rbw_var.set(_fmt_freq(s.rbw_hz))
        self._ref_var.set(f"{s.ref_level:.1f} dBm")
        self._atten_var.set(f"{s.atten_db:.0f} dB")

        if s.peak_freq is not None:
            self._peak_f_var.set(_fmt_freq(s.peak_freq))
            self._peak_p_var.set(f"{s.peak_dbm:.2f} dBm")
        else:
            self._peak_f_var.set("---")
            self._peak_p_var.set("---")

        self._tg_var.set(f"TG: {'ON' if s.tg_on else 'OFF'}  {s.tg_level:.1f} dBm")

        # Update spectrum trace
        if s.freqs is not None and s.powers is not None and len(s.freqs):
            freqs_mhz = s.freqs / 1e6
            self._line.set_data(freqs_mhz, s.powers)
            self._ax.set_xlim(freqs_mhz[0], freqs_mhz[-1])
            p_min = max(float(np.min(s.powers)) - 5, s.ref_level - 100)
            p_max = s.ref_level + 5
            self._ax.set_ylim(p_min, p_max)

            # X-axis labels in GHz/MHz
            if s.center_hz >= 1e9:
                self._ax.set_xlabel("Frequency (GHz)", color=C_AX_FG, fontsize=8)
                self._ax.xaxis.set_major_formatter(
                    matplotlib.ticker.FuncFormatter(lambda x, _: f"{x/1000:.3f}"))
            else:
                self._ax.set_xlabel("Frequency (MHz)", color=C_AX_FG, fontsize=8)

            # Peak marker
            if s.peak_freq is not None:
                self._peak_dot.set_data([s.peak_freq / 1e6], [s.peak_dbm])
            else:
                self._peak_dot.set_data([], [])

            self._canvas.draw_idle()

        self._root.after(self._args.interval, self._tick)

    def destroy(self):
        self._stop.set()


# ── main ──────────────────────────────────────────────────────────────────────

import matplotlib.ticker

def main():
    p = argparse.ArgumentParser(description="SSA3032X Plus virtual panel")
    p.add_argument("--host",     default="10.1.1.60",
                   help="SSA3032X IP address (default 10.1.1.60)")
    p.add_argument("--interval", type=int, default=2000,
                   help="Refresh interval in ms (default 2000)")
    p.add_argument("--demo",     action="store_true",
                   help="Demo mode — no hardware needed")
    args = p.parse_args()

    root = tk.Tk()
    panel = SSAPanelApp(root, args)
    root.protocol("WM_DELETE_WINDOW", lambda: (panel.destroy(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
