#!/usr/bin/env python3
"""
Flipper Zero Virtual Instrument Panel

Tabbed Tkinter panel for live monitoring and control of the Flipper Zero.
Tabs: Sub-GHz, IR, RFID/NFC, GPIO.

Usage:
    python flipper_panel.py                     # default /dev/ttyACM0
    python flipper_panel.py --port /dev/ttyACM1 # explicit port
    python flipper_panel.py --demo              # no hardware needed
"""

import argparse
import dataclasses
import math
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont, messagebox, simpledialog
from typing import Optional

try:
    from rf_bench.flipper import FlipperZero
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
C_TAB_ACT = "#0d1a24"
C_TAB_IN  = "#0a0a0a"

RSSI_MIN = -120.0
RSSI_MAX = -20.0

# ── state dataclasses ─────────────────────────────────────────────────────────

@dataclasses.dataclass
class SubGhzState:
    freq_hz:    float = 433_920_000.0
    mode:       str   = "idle"      # idle | rx | tx_carrier
    rssi_dbm:   Optional[float] = None
    modulation: str   = "OOK_650"
    power_idx:  int   = 4

@dataclasses.dataclass
class IRState:
    last_protocol: Optional[str] = None
    last_address:  Optional[int] = None
    last_command:  Optional[int] = None
    raw_timings:   Optional[list] = None
    receiving:     bool = False

@dataclasses.dataclass
class RFIDState:
    card_type:  Optional[str] = None
    card_uid:   Optional[str] = None
    detected:   bool = False

@dataclasses.dataclass
class GPIOState:
    pins: dict = dataclasses.field(default_factory=dict)  # pin_name → bool

@dataclasses.dataclass
class State:
    subghz:    SubGhzState  = dataclasses.field(default_factory=SubGhzState)
    ir:        IRState      = dataclasses.field(default_factory=IRState)
    rfid:      RFIDState    = dataclasses.field(default_factory=RFIDState)
    gpio:      GPIOState    = dataclasses.field(default_factory=GPIOState)
    connected: bool         = False
    firmware:  str          = ""
    error:     str          = ""

# ── demo source ───────────────────────────────────────────────────────────────

class _DemoSource:
    def __init__(self):
        self._t0     = time.monotonic()
        self._rssi   = -75.0
        self._ir_idx = 0
        self._ir_protocols = [
            ("NEC", 0x07, 0x02, None),
            ("NEC", 0x07, 0x13, None),
            (None, None, None, None),
        ]
        self._card_shown = False
        self._card_t = time.monotonic() + 8.0

    def read(self) -> State:
        t  = time.monotonic() - self._t0
        # RSSI drifts
        self._rssi = max(RSSI_MIN, min(RSSI_MAX,
            -75.0 + 8.0 * math.sin(t * 0.4) + random.gauss(0, 2)))

        ir_proto, ir_addr, ir_cmd, _ = self._ir_protocols[self._ir_idx % len(self._ir_protocols)]
        if int(t) % 7 == 0 and int(t) > 1:
            self._ir_idx += 1

        card = time.monotonic() > self._card_t
        return State(
            connected=True,
            firmware="DEMO-0.96.1",
            subghz=SubGhzState(
                freq_hz=433_920_000,
                mode="rx",
                rssi_dbm=self._rssi,
                modulation="OOK_650",
                power_idx=4,
            ),
            ir=IRState(
                last_protocol=ir_proto,
                last_address=ir_addr,
                last_command=ir_cmd,
                receiving=False,
            ),
            rfid=RFIDState(
                card_type="EM4100" if card else None,
                card_uid="3F A2 B1 12" if card else None,
                detected=card,
            ),
            gpio=GPIOState(pins={
                "PA7": False, "PA6": False, "PB3": False, "PB2": False,
                "PC3": False, "PC1": False, "PC0": False, "PA4": False,
            }),
        )

# ── panel ─────────────────────────────────────────────────────────────────────

class FlipperPanel:
    def __init__(self, root: tk.Tk, args):
        self._root      = root
        self._args      = args
        self._lock      = threading.Lock()
        self._state_ref = [State()]
        self._cmd_queue: list = []
        self._cmd_lock  = threading.Lock()
        self._stop      = threading.Event()
        self._fz_ref    = [None]

        root.title("Flipper Zero")
        root.configure(bg=C_BG)
        root.resizable(False, False)

        self._build_ui()
        self._start_poll(args)
        self._tick()

    def _build_ui(self):
        fnt_hdr  = tkfont.Font(family="Helvetica", size=10, weight="bold")
        fnt_big  = tkfont.Font(family="Courier",   size=16, weight="bold")
        fnt_sub  = tkfont.Font(family="Helvetica", size=9)
        fnt_btn  = tkfont.Font(family="Helvetica", size=8)

        # Header
        hdr = tk.Frame(self._root, bg="#0a0a0a", pady=4)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="FLIPPER ZERO", fg="#999999",
                 bg="#0a0a0a", font=fnt_hdr).pack(side=tk.LEFT, padx=10)
        self._fw_lbl = tk.Label(hdr, text="", fg=C_STATUS,
                                bg="#0a0a0a", font=fnt_sub)
        self._fw_lbl.pack(side=tk.LEFT, padx=8)
        self._conn_lbl = tk.Label(hdr, text="⬤ OFFLINE", fg=C_OFF,
                                  bg="#0a0a0a", font=fnt_sub)
        self._conn_lbl.pack(side=tk.RIGHT, padx=10)

        # Notebook (manual tabs with frames)
        tab_bar = tk.Frame(self._root, bg="#0a0a0a")
        tab_bar.pack(fill=tk.X)
        self._tab_content = tk.Frame(self._root, bg=C_BG)
        self._tab_content.pack(fill=tk.BOTH, padx=8, pady=4)

        self._tabs        = {}
        self._tab_btns    = {}
        self._active_tab  = "subghz"

        for name, label in [("subghz","Sub-GHz"), ("ir","IR"),
                             ("rfid","RFID/NFC"), ("gpio","GPIO")]:
            f = tk.Frame(self._tab_content, bg=C_BG)
            self._tabs[name] = f
            btn = tk.Button(tab_bar, text=label, relief=tk.FLAT,
                            font=fnt_btn, padx=12, pady=4,
                            command=lambda n=name: self._show_tab(n))
            btn.pack(side=tk.LEFT)
            self._tab_btns[name] = btn

        self._build_subghz(self._tabs["subghz"], fnt_hdr, fnt_big, fnt_sub, fnt_btn)
        self._build_ir    (self._tabs["ir"],     fnt_hdr, fnt_big, fnt_sub, fnt_btn)
        self._build_rfid  (self._tabs["rfid"],   fnt_hdr, fnt_big, fnt_sub, fnt_btn)
        self._build_gpio  (self._tabs["gpio"],   fnt_hdr, fnt_big, fnt_sub, fnt_btn)

        # Status bar
        bot = tk.Frame(self._root, bg="#0a0a0a", pady=3)
        bot.pack(fill=tk.X)
        self._status_var = tk.StringVar(value="")
        tk.Label(bot, textvariable=self._status_var, fg=C_STATUS,
                 bg="#0a0a0a",
                 font=tkfont.Font(family="Helvetica", size=8)).pack(side=tk.LEFT, padx=8)

        self._show_tab("subghz")

    def _show_tab(self, name: str):
        for n, f in self._tabs.items():
            f.pack_forget()
        self._tabs[name].pack(fill=tk.BOTH, expand=True)
        self._active_tab = name
        for n, btn in self._tab_btns.items():
            btn.config(bg=C_TAB_ACT if n == name else C_TAB_IN,
                       fg=C_LIT if n == name else C_STATUS)

    # ── Sub-GHz tab ───────────────────────────────────────────────────────────

    def _build_subghz(self, parent, fnt_hdr, fnt_big, fnt_sub, fnt_btn):
        tk.Label(parent, text="Sub-GHz (CC1101)", fg=C_LABEL,
                 bg=C_BG, font=fnt_hdr).pack(pady=(10,4))

        info = tk.Frame(parent, bg=C_TILE, pady=8, padx=16)
        info.pack(fill=tk.X, padx=8)

        rows = [("Frequency", ""), ("Mode", ""), ("Modulation", ""), ("Power Index", "")]
        self._sg_freq_var = tk.StringVar(value="---")
        self._sg_mode_var = tk.StringVar(value="---")
        self._sg_mod_var  = tk.StringVar(value="---")
        self._sg_pwr_var  = tk.StringVar(value="---")
        var_map = [self._sg_freq_var, self._sg_mode_var, self._sg_mod_var, self._sg_pwr_var]
        for (lbl, _), var in zip(rows, var_map):
            row = tk.Frame(info, bg=C_TILE)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=lbl+":", fg=C_LABEL, bg=C_TILE,
                     font=fnt_sub, width=14, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, textvariable=var, fg=C_LIT, bg=C_TILE,
                     font=fnt_sub).pack(side=tk.LEFT)

        # RSSI bar
        tk.Label(parent, text="RSSI", fg=C_LABEL, bg=C_BG,
                 font=fnt_sub).pack(pady=(8,0))
        self._sg_rssi_var = tk.StringVar(value="---")
        tk.Label(parent, textvariable=self._sg_rssi_var, fg=C_LIT,
                 bg=C_BG, font=fnt_big).pack()
        bar_frame = tk.Frame(parent, bg=C_BORDER, height=14, width=300)
        bar_frame.pack(pady=4)
        bar_frame.pack_propagate(False)
        self._rssi_bar = tk.Frame(bar_frame, bg=C_ON, height=14)
        self._rssi_bar.place(x=0, y=0, width=0, height=14)
        self._rssi_bar_frame = bar_frame

        # Controls
        ctrl = tk.Frame(parent, bg=C_BG)
        ctrl.pack(pady=8)
        tk.Button(ctrl, text="Start RX", bg=C_BTN_BG, fg=C_BTN_FG, relief=tk.FLAT,
                  font=fnt_btn, command=self._sg_start_rx
                  ).grid(row=0, column=0, padx=4, pady=2)
        tk.Button(ctrl, text="TX Carrier", bg=C_BTN_BG, fg=C_WARN, relief=tk.FLAT,
                  font=fnt_btn, command=self._sg_tx_carrier
                  ).grid(row=0, column=1, padx=4, pady=2)
        tk.Button(ctrl, text="Stop", bg=C_BTN_BG, fg=C_OFF, relief=tk.FLAT,
                  font=fnt_btn, command=self._sg_stop
                  ).grid(row=0, column=2, padx=4, pady=2)
        tk.Button(ctrl, text="Set Frequency", bg=C_BTN_BG, fg=C_BTN_FG, relief=tk.FLAT,
                  font=fnt_btn, command=self._sg_set_freq
                  ).grid(row=1, column=0, columnspan=3, pady=2, sticky="ew")

    def _sg_start_rx(self):
        self._enqueue(lambda fz: fz.subghz_rx(
            self._state_ref[0].subghz.freq_hz, "OOK_650"))
        self._status_var.set("Sub-GHz RX started")

    def _sg_tx_carrier(self):
        self._enqueue(lambda fz: fz.subghz_tx_carrier(
            self._state_ref[0].subghz.freq_hz, 4))
        self._status_var.set("TX carrier started — ensure antenna connected!")

    def _sg_stop(self):
        self._enqueue(lambda fz: fz.subghz_stop())
        self._status_var.set("Sub-GHz stopped")

    def _sg_set_freq(self):
        val = simpledialog.askstring("Frequency", "Enter frequency in MHz:", parent=self._root)
        if val:
            try:
                hz = float(val) * 1e6
                with self._lock:
                    s = self._state_ref[0]
                    self._state_ref[0] = dataclasses.replace(
                        s, subghz=dataclasses.replace(s.subghz, freq_hz=hz))
                self._status_var.set(f"Frequency set to {hz/1e6:.3f} MHz")
            except ValueError:
                messagebox.showerror("Invalid", "Enter a number in MHz (e.g. 433.92)")

    # ── IR tab ────────────────────────────────────────────────────────────────

    def _build_ir(self, parent, fnt_hdr, fnt_big, fnt_sub, fnt_btn):
        tk.Label(parent, text="Infrared", fg=C_LABEL,
                 bg=C_BG, font=fnt_hdr).pack(pady=(10,4))

        info = tk.Frame(parent, bg=C_TILE, pady=8, padx=16)
        info.pack(fill=tk.X, padx=8)

        self._ir_proto_var = tk.StringVar(value="---")
        self._ir_addr_var  = tk.StringVar(value="---")
        self._ir_cmd_var   = tk.StringVar(value="---")
        self._ir_rx_var    = tk.StringVar(value="Idle")

        for lbl, var in [("Protocol", self._ir_proto_var),
                         ("Address", self._ir_addr_var),
                         ("Command", self._ir_cmd_var),
                         ("Status",  self._ir_rx_var)]:
            row = tk.Frame(info, bg=C_TILE)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=lbl+":", fg=C_LABEL, bg=C_TILE,
                     font=fnt_sub, width=10, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, textvariable=var, fg=C_LIT, bg=C_TILE,
                     font=fnt_sub).pack(side=tk.LEFT)

        ctrl = tk.Frame(parent, bg=C_BG)
        ctrl.pack(pady=8)
        tk.Button(ctrl, text="Start Receive", bg=C_BTN_BG, fg=C_BTN_FG, relief=tk.FLAT,
                  font=fnt_btn, command=self._ir_start_rx
                  ).grid(row=0, column=0, padx=4)
        tk.Button(ctrl, text="Transmit Last", bg=C_BTN_BG, fg=C_WARN, relief=tk.FLAT,
                  font=fnt_btn, command=self._ir_tx_last
                  ).grid(row=0, column=1, padx=4)

    def _ir_start_rx(self):
        self._status_var.set("IR receive — point remote at Flipper")
        def _rx(fz):
            result = fz.ir_receive(timeout_s=10.0)
            if result:
                with self._lock:
                    s = self._state_ref[0]
                    self._state_ref[0] = dataclasses.replace(s, ir=IRState(
                        last_protocol=result.get("protocol"),
                        last_address=result.get("address"),
                        last_command=result.get("command"),
                    ))
        self._enqueue(_rx)

    def _ir_tx_last(self):
        with self._lock:
            ir = self._state_ref[0].ir
        if ir.last_protocol and ir.last_command is not None:
            self._enqueue(lambda fz: fz.ir_transmit(
                protocol=ir.last_protocol,
                address=ir.last_address or 0,
                command=ir.last_command))
            self._status_var.set(f"TX {ir.last_protocol} cmd 0x{ir.last_command:02X}")
        else:
            self._status_var.set("No IR code received yet")

    # ── RFID/NFC tab ──────────────────────────────────────────────────────────

    def _build_rfid(self, parent, fnt_hdr, fnt_big, fnt_sub, fnt_btn):
        tk.Label(parent, text="RFID / NFC", fg=C_LABEL,
                 bg=C_BG, font=fnt_hdr).pack(pady=(10,4))

        self._rfid_det_lbl = tk.Label(parent, text="NO CARD", fg=C_OFF,
                                       bg=C_BG, font=fnt_big)
        self._rfid_det_lbl.pack(pady=8)

        info = tk.Frame(parent, bg=C_TILE, pady=8, padx=16)
        info.pack(fill=tk.X, padx=8)
        self._rfid_type_var = tk.StringVar(value="---")
        self._rfid_uid_var  = tk.StringVar(value="---")
        for lbl, var in [("Type", self._rfid_type_var), ("UID", self._rfid_uid_var)]:
            row = tk.Frame(info, bg=C_TILE)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=lbl+":", fg=C_LABEL, bg=C_TILE,
                     font=fnt_sub, width=8, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, textvariable=var, fg=C_LIT, bg=C_TILE,
                     font=fnt_sub).pack(side=tk.LEFT)

        ctrl = tk.Frame(parent, bg=C_BG)
        ctrl.pack(pady=8)
        tk.Button(ctrl, text="Read LF RFID (125 kHz)", bg=C_BTN_BG, fg=C_BTN_FG,
                  relief=tk.FLAT, font=fnt_btn,
                  command=self._rfid_read_lf).pack(padx=4, pady=2)
        tk.Button(ctrl, text="Read NFC (13.56 MHz)", bg=C_BTN_BG, fg=C_BTN_FG,
                  relief=tk.FLAT, font=fnt_btn,
                  command=self._rfid_read_nfc).pack(padx=4, pady=2)

    def _rfid_read_lf(self):
        self._status_var.set("RFID read — place card near Flipper…")
        def _read(fz):
            result = fz.lfrfid_read(timeout_s=10.0)
            if result:
                with self._lock:
                    s = self._state_ref[0]
                    self._state_ref[0] = dataclasses.replace(s, rfid=RFIDState(
                        card_type=result.get("type"),
                        card_uid=result.get("uid"),
                        detected=True,
                    ))
        self._enqueue(_read)

    def _rfid_read_nfc(self):
        self._status_var.set("NFC read — place card near Flipper…")
        def _read(fz):
            result = fz.nfc_read(timeout_s=10.0)
            if result:
                with self._lock:
                    s = self._state_ref[0]
                    self._state_ref[0] = dataclasses.replace(s, rfid=RFIDState(
                        card_type=result.get("type", "NFC ISO14443A"),
                        card_uid=result.get("uid"),
                        detected=True,
                    ))
        self._enqueue(_read)

    # ── GPIO tab ──────────────────────────────────────────────────────────────

    def _build_gpio(self, parent, fnt_hdr, fnt_big, fnt_sub, fnt_btn):
        tk.Label(parent, text="GPIO Pins", fg=C_LABEL,
                 bg=C_BG, font=fnt_hdr).pack(pady=(10,4))

        self._gpio_leds = {}
        grid = tk.Frame(parent, bg=C_BG)
        grid.pack()
        pins = ["PA7","PA6","PB3","PB2","PC3","PC1","PC0","PA4"]
        for i, pin in enumerate(pins):
            col, row_ = i % 4, i // 4
            f = tk.Frame(grid, bg=C_TILE, padx=10, pady=6,
                         highlightbackground=C_BORDER, highlightthickness=1)
            f.grid(row=row_, column=col, padx=3, pady=3)
            tk.Label(f, text=pin, fg=C_LABEL, bg=C_TILE,
                     font=fnt_sub).pack()
            led = tk.Label(f, text="⬤", fg=C_OFF, bg=C_TILE,
                           font=tkfont.Font(size=14))
            led.pack()
            tk.Button(f, text="Toggle", bg=C_BTN_BG, fg=C_BTN_FG,
                      relief=tk.FLAT, font=tkfont.Font(size=7),
                      command=lambda p=pin: self._gpio_toggle(p)
                      ).pack(pady=2)
            self._gpio_leds[pin] = led

    def _gpio_toggle(self, pin: str):
        with self._lock:
            s   = self._state_ref[0]
            cur = s.gpio.pins.get(pin, False)
        new_val = not cur
        def _toggle(fz):
            fz.gpio_write(pin, new_val)
        with self._lock:
            s = self._state_ref[0]
            pins = dict(s.gpio.pins)
            pins[pin] = new_val
            self._state_ref[0] = dataclasses.replace(s,
                gpio=GPIOState(pins=pins))
        self._enqueue(_toggle)

    # ── poll thread ───────────────────────────────────────────────────────────

    def _enqueue(self, fn):
        if self._args.demo:
            return    # demo mode: state updated directly
        with self._cmd_lock:
            self._cmd_queue.append(fn)

    def _start_poll(self, args):
        if args.demo:
            self._source = _DemoSource()
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
        fz = None
        while not self._stop.is_set():
            if fz is None:
                try:
                    fz = FlipperZero(args.port)
                    fw = fz.identify()
                    with self._lock:
                        self._state_ref[0] = dataclasses.replace(
                            self._state_ref[0], connected=True, firmware=fw, error="")
                        self._fz_ref[0] = fz
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
                    fn(fz)
                except Exception as e:
                    with self._lock:
                        s = self._state_ref[0]
                        self._state_ref[0] = dataclasses.replace(s, error=str(e))

            # Poll RSSI if in RX mode
            try:
                with self._lock:
                    mode = self._state_ref[0].subghz.mode
                if mode == "rx":
                    rssi = fz.subghz_get_rssi()
                    with self._lock:
                        s = self._state_ref[0]
                        sg = dataclasses.replace(s.subghz, rssi_dbm=rssi)
                        self._state_ref[0] = dataclasses.replace(s, subghz=sg)
            except Exception:
                pass

            self._stop.wait(0.3)

        if fz:
            try:
                fz.subghz_stop()
                fz.close()
            except Exception:
                pass

    # ── UI refresh tick ───────────────────────────────────────────────────────

    def _tick(self):
        with self._lock:
            s = self._state_ref[0]

        # Header
        if s.connected:
            self._conn_lbl.config(text="⬤ ONLINE", fg=C_ON)
            self._fw_lbl.config(text=s.firmware)
        else:
            self._conn_lbl.config(text="⬤ OFFLINE", fg=C_OFF)
            if s.error:
                self._status_var.set(s.error[:80])

        # Sub-GHz
        sg = s.subghz
        self._sg_freq_var.set(f"{sg.freq_hz/1e6:.3f} MHz")
        self._sg_mode_var.set(sg.mode.upper())
        self._sg_mod_var.set(sg.modulation)
        self._sg_pwr_var.set(str(sg.power_idx))
        if sg.rssi_dbm is not None:
            self._sg_rssi_var.set(f"{sg.rssi_dbm:+.1f} dBm")
            frac = max(0.0, min(1.0, (sg.rssi_dbm - RSSI_MIN) / (RSSI_MAX - RSSI_MIN)))
            bw = max(2, int(frac * self._rssi_bar_frame.winfo_width()))
            self._rssi_bar.place(x=0, y=0, width=bw, height=14)
        else:
            self._sg_rssi_var.set("---")

        # IR
        ir = s.ir
        self._ir_proto_var.set(ir.last_protocol or "---")
        self._ir_addr_var.set(f"0x{ir.last_address:02X}" if ir.last_address is not None else "---")
        self._ir_cmd_var.set(f"0x{ir.last_command:02X}" if ir.last_command is not None else "---")
        self._ir_rx_var.set("Receiving…" if ir.receiving else "Idle")

        # RFID
        rf = s.rfid
        if rf.detected:
            self._rfid_det_lbl.config(text="CARD DETECTED", fg=C_ON)
            self._rfid_type_var.set(rf.card_type or "---")
            self._rfid_uid_var.set(rf.card_uid or "---")
        else:
            self._rfid_det_lbl.config(text="NO CARD", fg=C_OFF)
            self._rfid_type_var.set("---")
            self._rfid_uid_var.set("---")

        # GPIO
        for pin, led in self._gpio_leds.items():
            val = s.gpio.pins.get(pin, False)
            led.config(fg=C_ON if val else C_OFF)

        self._root.after(250, self._tick)

    def destroy(self):
        self._stop.set()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Flipper Zero virtual panel")
    p.add_argument("--port",  default="/dev/ttyACM0",
                   help="USB CDC serial port (default /dev/ttyACM0)")
    p.add_argument("--demo",  action="store_true",
                   help="Demo mode — no Flipper Zero needed")
    args = p.parse_args()

    root = tk.Tk()
    panel = FlipperPanel(root, args)
    root.protocol("WM_DELETE_WINDOW", lambda: (panel.destroy(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
