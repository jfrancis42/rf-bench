#!/usr/bin/env python3
"""
RTL-SDR Virtual Instrument Panel

Live waterfall + instantaneous spectrum display for the RTL-SDR Blog v4.
Shows the last 60 seconds of spectrum history as a color waterfall alongside
the current FFT trace.

Usage:
    python rtlsdr_panel.py                          # default: first RTL-SDR
    python rtlsdr_panel.py --freq 144.39            # APRS (MHz)
    python rtlsdr_panel.py --freq 433.92 --bw 2.4   # ISM band
    python rtlsdr_panel.py --serial 00000001        # explicit RTL-SDR
    python rtlsdr_panel.py --demo                   # no hardware needed
"""

import argparse
import dataclasses
import math
import random
import sys
import os
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional
from collections import deque

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.colors as mcolors

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..'))
try:
    from rf_bench.rtlsdr import RTLSDR
    _DRIVER_OK = True
except ImportError:
    _DRIVER_OK = False

# ── constants ─────────────────────────────────────────────────────────────────
C_BG     = "#111111"
C_TILE   = "#0f0f0f"
C_BORDER = "#252525"
C_LIT    = "#33ccff"
C_ON     = "#33ee55"
C_OFF    = "#cc2222"
C_WARN   = "#ffaa00"
C_LABEL  = "#4a6688"
C_STATUS = "#556677"
C_BTN_BG = "#181818"
C_BTN_FG = "#2a7aaa"
C_PLOT_BG = "#050a0a"
C_AX_FG  = "#556677"

FFT_SIZE      = 2048
DEFAULT_RATE  = 2_400_000
WATERFALL_ROWS = 120   # rows of waterfall history


# ── state ─────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class State:
    freq_hz:     float = 144_390_000.0
    rate_hz:     int   = DEFAULT_RATE
    gain_db:     float = 30.0
    bias_tee:    bool  = False
    ppm:         int   = 0
    spectrum:    Optional[np.ndarray] = None   # current FFT (dBFS)
    waterfall:   Optional[np.ndarray] = None   # [rows × freqs]
    peak_freq:   Optional[float] = None
    peak_dbfs:   Optional[float] = None
    connected:   bool = False
    device_name: str  = ""
    error:       str  = ""


# ── demo source ───────────────────────────────────────────────────────────────

class _DemoSource:
    def __init__(self, freq_hz: float, rate_hz: int):
        self._freq  = freq_hz
        self._rate  = rate_hz
        self._t0    = time.monotonic()
        self._wf    = np.full((WATERFALL_ROWS, FFT_SIZE), -80.0)
        self._row   = 0

    def read(self) -> State:
        t       = time.monotonic() - self._t0
        freqs   = np.linspace(-self._rate/2, self._rate/2, FFT_SIZE)
        noise   = np.random.normal(-80, 2, FFT_SIZE)
        # Moving carrier at ±50 kHz drift
        cf      = 50_000 * math.sin(t * 0.3)
        bw      = self._rate / FFT_SIZE * 4
        noise  += 25 * np.exp(-0.5 * ((freqs - cf) / bw) ** 2)
        # Second weaker signal
        cf2 = -300_000 + 20_000 * math.sin(t * 0.07)
        noise  += 12 * np.exp(-0.5 * ((freqs - cf2) / bw) ** 2)

        self._wf = np.roll(self._wf, 1, axis=0)
        self._wf[0] = noise

        peak_bin  = int(np.argmax(noise))
        peak_freq = self._freq + freqs[peak_bin]
        return State(
            freq_hz=self._freq, rate_hz=self._rate, gain_db=30.0,
            spectrum=noise, waterfall=self._wf.copy(),
            peak_freq=peak_freq, peak_dbfs=float(noise[peak_bin]),
            connected=True, device_name="RTL-SDR v4 (DEMO)",
        )


# ── live reader thread ────────────────────────────────────────────────────────

def _poll_worker(state_ref: list, lock: threading.Lock, stop: threading.Event,
                 cmd_queue: list, cmd_lock: threading.Lock,
                 args):
    sdr = None
    wf  = np.full((WATERFALL_ROWS, FFT_SIZE), -80.0)

    while not stop.is_set():
        if sdr is None:
            try:
                sdr = RTLSDR(serial=args.serial, ppm_correction=args.ppm)
                sdr.set_center_freq(args.freq * 1e6)
                sdr.set_sample_rate(int(args.bw * 1e6))
                sdr.set_gain(args.gain)
                if args.bias_tee:
                    sdr.set_bias_tee(True)
                name = sdr.identify()
                with lock:
                    state_ref[0] = dataclasses.replace(state_ref[0],
                        connected=True, device_name=name)
            except Exception as e:
                with lock:
                    state_ref[0] = State(connected=False, error=str(e))
                stop.wait(5.0)
                continue

        # Commands
        with cmd_lock:
            pending = list(cmd_queue)
            cmd_queue.clear()
        for fn in pending:
            try:
                fn(sdr)
            except Exception as e:
                with lock:
                    s = state_ref[0]
                    state_ref[0] = dataclasses.replace(s, error=str(e))

        try:
            iq      = sdr.capture_iq(FFT_SIZE)
            window  = np.hanning(len(iq))
            fft_raw = np.fft.fftshift(np.fft.fft(iq * window))
            psd     = 20 * np.log10(np.abs(fft_raw) / FFT_SIZE + 1e-12)

            wf      = np.roll(wf, 1, axis=0)
            wf[0]   = psd

            peak_bin  = int(np.argmax(psd))
            rate      = sdr._sdr.sample_rate if hasattr(sdr, '_sdr') else int(args.bw * 1e6)
            freqs_off = np.linspace(-rate/2, rate/2, FFT_SIZE)
            freq_hz   = args.freq * 1e6
            peak_freq = freq_hz + freqs_off[peak_bin]

            with lock:
                state_ref[0] = dataclasses.replace(state_ref[0],
                    freq_hz=freq_hz, spectrum=psd, waterfall=wf.copy(),
                    peak_freq=peak_freq, peak_dbfs=float(psd[peak_bin]))
        except Exception as e:
            with lock:
                state_ref[0] = State(connected=False, error=str(e))
            try: sdr.close()
            except Exception: pass
            sdr = None
            continue

    if sdr:
        try:
            if args.bias_tee:
                sdr.set_bias_tee(False)
            sdr.close()
        except Exception:
            pass


# ── panel ─────────────────────────────────────────────────────────────────────

class RTLSDRPanel:
    def __init__(self, root: tk.Tk, args):
        self._root      = root
        self._args      = args
        self._lock      = threading.Lock()
        self._state_ref = [State(freq_hz=args.freq * 1e6,
                                 rate_hz=int(args.bw * 1e6),
                                 gain_db=args.gain)]
        self._cmd_queue: list = []
        self._cmd_lock  = threading.Lock()
        self._stop      = threading.Event()

        root.title("RTL-SDR")
        root.configure(bg=C_BG)

        self._build_ui()
        self._start_poll(args)
        self._tick()

    def _build_ui(self):
        fnt_hdr = tkfont.Font(family="Helvetica", size=10, weight="bold")
        fnt_val = tkfont.Font(family="Courier",   size=10, weight="bold")
        fnt_sub = tkfont.Font(family="Helvetica", size=9)
        fnt_btn = tkfont.Font(family="Helvetica", size=8)

        # Header
        hdr = tk.Frame(self._root, bg="#0a0a0a", pady=4)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="RTL-SDR  SPECTRUM MONITOR",
                 fg="#999999", bg="#0a0a0a", font=fnt_hdr).pack(side=tk.LEFT, padx=10)
        self._dev_lbl  = tk.Label(hdr, text="", fg=C_STATUS, bg="#0a0a0a", font=fnt_sub)
        self._dev_lbl.pack(side=tk.LEFT, padx=8)
        self._conn_lbl = tk.Label(hdr, text="⬤ OFFLINE", fg=C_OFF, bg="#0a0a0a", font=fnt_sub)
        self._conn_lbl.pack(side=tk.RIGHT, padx=10)

        # Main: dual plot (spectrum + waterfall) | right panel
        main = tk.Frame(self._root, bg=C_BG)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Two-row figure: spectrum on top, waterfall below
        self._fig = Figure(figsize=(7, 5), dpi=96, facecolor=C_PLOT_BG)
        gs = self._fig.add_gridspec(2, 1, height_ratios=[1, 2], hspace=0.05)
        self._ax_spec = self._fig.add_subplot(gs[0], facecolor=C_PLOT_BG)
        self._ax_wf   = self._fig.add_subplot(gs[1], facecolor=C_PLOT_BG)

        for ax in (self._ax_spec, self._ax_wf):
            ax.tick_params(colors=C_AX_FG, labelsize=7)
            for spine in ax.spines.values():
                spine.set_edgecolor("#1a2020")

        self._ax_spec.set_ylabel("dBFS", color=C_AX_FG, fontsize=8)
        self._ax_spec.set_xticklabels([])
        self._ax_wf.set_xlabel("Offset (kHz)", color=C_AX_FG, fontsize=8)
        self._ax_wf.set_ylabel("Time →", color=C_AX_FG, fontsize=8)

        self._spec_line, = self._ax_spec.plot([], [], color=C_LIT, linewidth=0.8)
        self._peak_mark, = self._ax_spec.plot([], [], "v", color=C_WARN, markersize=6)

        # Waterfall image placeholder
        dummy = np.zeros((WATERFALL_ROWS, FFT_SIZE))
        self._wf_im = self._ax_wf.imshow(
            dummy, aspect="auto", origin="upper",
            cmap="inferno", vmin=-100, vmax=-40,
            extent=[0, 1, WATERFALL_ROWS, 0]
        )
        self._fig.tight_layout(pad=0.5)

        self._canvas = FigureCanvasTkAgg(self._fig, master=main)
        self._canvas.get_tk_widget().pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Right panel
        right = tk.Frame(main, bg=C_BG, width=190)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        right.pack_propagate(False)

        def _tile(label, var):
            f = tk.Frame(right, bg=C_TILE,
                         highlightbackground=C_BORDER, highlightthickness=1)
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=label, fg=C_LABEL, bg=C_TILE, font=fnt_sub,
                     anchor="w").pack(fill=tk.X, padx=6, pady=(3,0))
            tk.Label(f, textvariable=var, fg=C_LIT, bg=C_TILE, font=fnt_val,
                     anchor="e").pack(fill=tk.X, padx=6, pady=(0,3))

        self._freq_var  = tk.StringVar(value="---")
        self._rate_var  = tk.StringVar(value="---")
        self._gain_var  = tk.StringVar(value="---")
        self._ppm_var   = tk.StringVar(value="---")
        self._peak_f_var= tk.StringVar(value="---")
        self._peak_p_var= tk.StringVar(value="---")
        self._bt_var    = tk.StringVar(value="Bias Tee: OFF")

        _tile("Center Freq",  self._freq_var)
        _tile("Bandwidth",    self._rate_var)
        _tile("Gain",         self._gain_var)
        _tile("PPM Offset",   self._ppm_var)
        tk.Frame(right, bg=C_BORDER, height=1).pack(fill=tk.X, pady=3)
        _tile("Peak Freq",    self._peak_f_var)
        _tile("Peak dBFS",    self._peak_p_var)
        tk.Label(right, textvariable=self._bt_var, fg=C_STATUS, bg=C_BG,
                 font=fnt_sub).pack(pady=2)

        for txt, cmd in [
            ("Bias Tee On/Off", self._do_bias_tee),
            ("Screenshot",      self._do_screenshot),
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

    def _do_bias_tee(self):
        with self._lock:
            cur = self._state_ref[0].bias_tee
        new_state = not cur
        def _bt(sdr):
            sdr.set_bias_tee(new_state)
        with self._lock:
            s = self._state_ref[0]
            self._state_ref[0] = dataclasses.replace(s, bias_tee=new_state)
        with self._cmd_lock:
            self._cmd_queue.append(_bt)
        self._status_var.set(f"Bias tee {'ON' if new_state else 'OFF'}")

    def _do_screenshot(self):
        import datetime
        fname = f"rtlsdr_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        self._fig.savefig(fname, dpi=150, facecolor=C_PLOT_BG)
        self._status_var.set(f"Saved {fname}")

    def _start_poll(self, args):
        if args.demo:
            self._source = _DemoSource(args.freq * 1e6, int(args.bw * 1e6))
            t = threading.Thread(target=self._demo_loop, daemon=True)
        else:
            self._source = None
            t = threading.Thread(
                target=_poll_worker,
                args=(self._state_ref, self._lock, self._stop,
                      self._cmd_queue, self._cmd_lock, args),
                daemon=True,
            )
        t.start()

    def _demo_loop(self):
        while not self._stop.is_set():
            s = self._source.read()
            with self._lock:
                self._state_ref[0] = s
            time.sleep(0.15)

    def _tick(self):
        with self._lock:
            s = self._state_ref[0]

        if s.connected:
            self._conn_lbl.config(text="⬤ ONLINE", fg=C_ON)
            self._dev_lbl.config(text=s.device_name)
        else:
            self._conn_lbl.config(text="⬤ OFFLINE", fg=C_OFF)
            if s.error:
                self._status_var.set(s.error[:80])

        rate_hz = s.rate_hz or int(self._args.bw * 1e6)
        self._freq_var.set(f"{s.freq_hz/1e6:.4f} MHz")
        self._rate_var.set(f"{rate_hz/1e6:.1f} MHz")
        self._gain_var.set(f"{s.gain_db:.1f} dB")
        self._ppm_var.set(f"{s.ppm:+d}")
        self._bt_var.set(f"Bias Tee: {'ON' if s.bias_tee else 'OFF'}")

        if s.peak_freq is not None:
            self._peak_f_var.set(f"{s.peak_freq/1e6:.4f} MHz")
            self._peak_p_var.set(f"{s.peak_dbfs:.1f}")

        if s.spectrum is not None and len(s.spectrum):
            off_khz = np.linspace(-rate_hz/2/1e3, rate_hz/2/1e3, len(s.spectrum))
            self._spec_line.set_data(off_khz, s.spectrum)
            self._ax_spec.set_xlim(off_khz[0], off_khz[-1])
            p_min = max(float(np.min(s.spectrum)) - 5, -120)
            self._ax_spec.set_ylim(p_min, max(float(np.max(s.spectrum)) + 5, p_min + 30))

            # Peak marker
            if s.peak_freq is not None:
                off = (s.peak_freq - s.freq_hz) / 1e3
                self._peak_mark.set_data([off], [s.peak_dbfs])
            else:
                self._peak_mark.set_data([], [])

        if s.waterfall is not None:
            self._wf_im.set_data(s.waterfall)
            self._wf_im.set_extent([
                -rate_hz/2/1e3, rate_hz/2/1e3, WATERFALL_ROWS, 0
            ])
            p_min = max(float(np.min(s.waterfall)) - 2, -120)
            p_max = float(np.max(s.waterfall)) + 2
            self._wf_im.set_clim(p_min, p_max)

        self._canvas.draw_idle()
        self._root.after(100, self._tick)

    def destroy(self):
        self._stop.set()


def main():
    p = argparse.ArgumentParser(description="RTL-SDR virtual panel")
    p.add_argument("--freq",   type=float, default=144.39,
                   help="Center frequency in MHz (default 144.39)")
    p.add_argument("--bw",     type=float, default=2.4,
                   help="Bandwidth in MHz (default 2.4)")
    p.add_argument("--gain",   type=float, default=30.0,
                   help="Gain in dB (default 30)")
    p.add_argument("--ppm",    type=int, default=0,
                   help="PPM correction offset (default 0)")
    p.add_argument("--serial", default=None,
                   help="RTL-SDR serial number (default: first device)")
    p.add_argument("--bias-tee", action="store_true", dest="bias_tee",
                   help="Enable bias tee on startup")
    p.add_argument("--demo",   action="store_true",
                   help="Demo mode — no hardware needed")
    args = p.parse_args()

    root = tk.Tk()
    panel = RTLSDRPanel(root, args)
    root.protocol("WM_DELETE_WINDOW", lambda: (panel.destroy(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
