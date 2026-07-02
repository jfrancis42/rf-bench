#!/usr/bin/env python3
"""
Kestrel 5500L Virtual Instrument Panel

Graphical monitoring front panel for the Kestrel 5500L weather meter
via BLE. Displays temperature, humidity, wind speed, pressure, altitude,
dew point, wet bulb, heat index, and derived atmospheric properties
(density altitude, RF refractivity, air density, cloud base, speed of
sound, vapor pressure, QNH).

Usage:
    python kestrel5500_panel.py                           # default MAC
    python kestrel5500_panel.py --mac 88:6B:0F:5F:D0:EB  # explicit MAC
    python kestrel5500_panel.py --altitude 2003           # known MSL altitude (m)
    python kestrel5500_panel.py --interval 4000           # UI refresh ms
    python kestrel5500_panel.py --demo                    # simulated data

The Kestrel pushes data every ~4 seconds. The --interval controls how
often the UI redraws from the latest received reading.
"""

import argparse
import asyncio
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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'drivers', 'kestrel'))
try:
    from rf_bench.kestrel import Kestrel5500, KestrelReading, KestrelDeviceInfo
    _DRIVER_OK = True
except ImportError:
    _DRIVER_OK = False
    KestrelReading = None
    KestrelDeviceInfo = None


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
C_MEAS_LABEL    = "#4a5a6a"
C_VALUE_LIT     = "#33ccee"   # bright cyan (live value)
C_VALUE_DIM     = "#1c3a44"   # dim cyan (no data)
C_UNIT          = "#2299bb"
C_DIVIDER       = "#1c1c1c"
C_ONLINE        = "#33ee55"
C_OFFLINE       = "#cc2222"
C_BATTERY_GOOD  = "#33ee55"
C_BATTERY_MED   = "#ffcc00"
C_BATTERY_LOW   = "#ff3333"
C_REFRACT_NORM  = "#33ccee"
C_REFRACT_HIGH  = "#ffaa00"
C_REFRACT_DUCT  = "#ff4444"
C_STATUS_FG     = "#556666"
C_STATUS_BG     = "#0a0a0a"
C_WIND_CALM     = "#2299bb"
C_WIND_LIGHT    = "#33ccee"
C_WIND_MOD      = "#ffcc00"
C_WIND_STRONG   = "#ff6633"


# ─────────────────────────────────────────────────────────────────────────────
# Shared state dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class State:
    # Primary sensors
    temperature_c: Optional[float] = None
    temperature_f: Optional[float] = None
    relative_humidity: Optional[float] = None
    wind_speed_mph: Optional[float] = None
    wind_speed_ms: Optional[float] = None
    station_pressure_mbar: Optional[float] = None
    station_pressure_inhg: Optional[float] = None

    # Secondary
    altitude_ft: Optional[float] = None
    altitude_m: Optional[float] = None
    dew_point_f: Optional[float] = None
    wet_bulb_f: Optional[float] = None
    heat_index_f: Optional[float] = None

    # Derived atmospheric
    density_altitude_ft: Optional[float] = None
    rf_refractivity: Optional[float] = None
    air_density: Optional[float] = None
    cloud_base_agl_ft: Optional[float] = None
    speed_of_sound_ms: Optional[float] = None
    vapor_pressure_mbar: Optional[float] = None
    wind_chill_f: Optional[float] = None

    # QNH (if altitude provided)
    qnh_inhg: Optional[float] = None
    qnh_mbar: Optional[float] = None

    # Device info
    model: str = ""
    serial: str = ""
    firmware: str = ""
    hardware: str = ""
    battery_percent: Optional[int] = None

    # Connection state
    connected: bool = False
    error: str = ""
    last_update: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Demo data source
# ─────────────────────────────────────────────────────────────────────────────

class _DemoSource:
    def __init__(self, altitude_m: float):
        self._t0 = time.monotonic()
        self._alt_m = altitude_m

    def read(self) -> State:
        t = time.monotonic() - self._t0
        s = State(connected=True)

        # Simulate outdoor conditions with slow variation
        s.temperature_c = 24.0 + 3.0 * math.sin(t * 0.02) + random.gauss(0, 0.1)
        s.temperature_f = s.temperature_c * 9 / 5 + 32
        s.relative_humidity = 35.0 + 10.0 * math.sin(t * 0.015 + 1.0) + random.gauss(0, 0.3)
        s.wind_speed_ms = max(0, 2.5 + 2.0 * math.sin(t * 0.08) + random.gauss(0, 0.3))
        s.wind_speed_mph = s.wind_speed_ms * 2.23694
        s.station_pressure_mbar = 795.0 + 1.5 * math.sin(t * 0.005) + random.gauss(0, 0.05)
        s.station_pressure_inhg = s.station_pressure_mbar * 0.02953

        s.altitude_m = self._alt_m + random.gauss(0, 0.5)
        s.altitude_ft = s.altitude_m * 3.28084

        # Derived on-device
        t_c = s.temperature_c
        rh = s.relative_humidity
        es = 6.1078 * 10 ** (7.5 * t_c / (237.3 + t_c))
        e = es * rh / 100.0
        td_c = 237.3 * math.log10(e / 6.1078) / (7.5 - math.log10(e / 6.1078))
        s.dew_point_f = td_c * 9 / 5 + 32
        s.wet_bulb_f = (t_c - (t_c - td_c) / 3) * 9 / 5 + 32
        s.heat_index_f = s.temperature_f  # simplified

        # Derived atmospheric
        p_pa = s.station_pressure_mbar * 100.0
        t_k = t_c + 273.15
        e_pa = e * 100.0
        rho = (p_pa - e_pa) / (287.058 * t_k) + e_pa / (461.495 * t_k)
        s.air_density = rho
        s.density_altitude_ft = 44330.77 * (1 - (rho / 1.225) ** 0.234969) * 3.28084
        s.rf_refractivity = 77.6 * (s.station_pressure_mbar / t_k) + 3.73e5 * (e / t_k ** 2)
        tv_k = t_k / (1 - 0.378 * e / s.station_pressure_mbar)
        s.speed_of_sound_ms = 331.3 * (tv_k / 273.15) ** 0.5
        s.vapor_pressure_mbar = e
        spread = t_c - td_c
        s.cloud_base_agl_ft = spread / 2.5 * 1000
        s.wind_chill_f = None  # typically not applicable at these temps

        # QNH
        if self._alt_m > 0:
            s.qnh_mbar = s.station_pressure_mbar * (1 + 0.0065 * self._alt_m / t_k) ** 5.2561
            s.qnh_inhg = s.qnh_mbar * 0.02953

        s.model = "5500L"
        s.serial = "DEMO-001"
        s.firmware = "1.57"
        s.hardware = "Rev 11B"
        s.battery_percent = max(0, min(100, int(85 - t * 0.01)))
        s.last_update = time.time()
        return s


# ─────────────────────────────────────────────────────────────────────────────
# BLE poll worker (runs asyncio in a thread)
# ─────────────────────────────────────────────────────────────────────────────

def _state_from_reading(reading, info, altitude_m: float) -> State:
    s = State(connected=True, last_update=time.time())
    s.temperature_c = reading.temperature_c
    s.temperature_f = reading.temperature_f
    s.relative_humidity = reading.relative_humidity
    s.wind_speed_ms = reading.wind_speed_ms
    s.wind_speed_mph = reading.wind_speed_mph
    s.station_pressure_mbar = reading.station_pressure_mbar
    s.station_pressure_inhg = reading.station_pressure_inhg
    s.altitude_ft = reading.altitude_ft
    s.altitude_m = reading.altitude_m
    s.dew_point_f = reading.dew_point_f
    s.wet_bulb_f = reading.wet_bulb_f
    s.heat_index_f = reading.heat_index_f
    s.density_altitude_ft = reading.density_altitude_ft
    s.rf_refractivity = reading.rf_refractivity
    s.air_density = reading.air_density
    s.cloud_base_agl_ft = reading.cloud_base_agl_ft
    s.speed_of_sound_ms = reading.speed_of_sound_ms
    s.vapor_pressure_mbar = reading.vapor_pressure_mbar
    s.wind_chill_f = reading.wind_chill_f
    if altitude_m > 0:
        s.qnh_mbar = reading.sea_level_pressure_mbar(altitude_m)
        s.qnh_inhg = reading.sea_level_pressure_inhg(altitude_m)
    if info:
        s.model = info.model
        s.serial = info.serial
        s.firmware = info.firmware
        s.hardware = info.hardware
        s.battery_percent = info.battery_percent
    return s


def _ble_worker(mac: str, altitude_m: float, state_ref: list,
                lock: threading.Lock, stop: threading.Event) -> None:
    async def _run():
        info = None
        while not stop.is_set():
            try:
                async with Kestrel5500(mac) as kestrel:
                    info = await kestrel.get_device_info()
                    async for reading in kestrel.stream():
                        if stop.is_set():
                            break
                        if reading.temperature_c is None:
                            continue
                        s = _state_from_reading(reading, info, altitude_m)
                        with lock:
                            state_ref[0] = s
            except Exception as e:
                with lock:
                    state_ref[0] = State(connected=False, error=str(e))
                # Wait before retry
                for _ in range(50):
                    if stop.is_set():
                        return
                    await asyncio.sleep(0.1)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


# ─────────────────────────────────────────────────────────────────────────────
# Widget helpers
# ─────────────────────────────────────────────────────────────────────────────

def _label(parent, text, fg, bg, font, **kw):
    return tk.Label(parent, text=text, fg=fg, bg=bg, font=font, **kw)


def _frame(parent, bg, **kw):
    return tk.Frame(parent, bg=bg, **kw)


def _tile(parent, bg=C_TILE_BG, border=C_TILE_BORDER):
    outer = tk.Frame(parent, bg=border, padx=1, pady=1)
    inner = tk.Frame(outer, bg=bg)
    inner.pack(fill=tk.BOTH, expand=True)
    return outer, inner


# ─────────────────────────────────────────────────────────────────────────────
# Main panel window
# ─────────────────────────────────────────────────────────────────────────────

class KestrelPanel(tk.Tk):
    _REFRESH_MS = 4000

    def __init__(self, mac: str, altitude_m: float, interval_ms: int, demo: bool):
        super().__init__()
        self.title("Kestrel 5500L  Weather Station")
        self.configure(bg=C_WIN_BG)
        self.resizable(False, False)

        self._mac = mac
        self._altitude_m = altitude_m
        self._demo = demo

        self._state_ref: list = [State()]
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self._demo_src = _DemoSource(altitude_m) if demo else None

        # Fonts
        self._f_small = self._mono(8)
        self._f_label = self._mono(9)
        self._f_unit = self._mono(12, bold=True)
        self._f_value = self._mono(26, bold=True)
        self._f_value_sm = self._mono(18, bold=True)
        self._f_value_xs = self._mono(13, bold=True)
        self._f_section = self._mono(8)
        self._f_header = self._mono(9)
        self._f_status = self._mono(9)
        self._f_badge = self._mono(11, bold=True)

        self._build_ui()
        self._start_poll(interval_ms)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    @staticmethod
    def _mono(size: int, bold: bool = False) -> tuple:
        for name in ("DejaVu Sans Mono", "Liberation Mono", "Courier New", "Courier"):
            if name in tkfont.families():
                return (name, size, "bold" if bold else "normal")
        return ("Courier", size, "bold" if bold else "normal")

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        content = _frame(self, C_WIN_BG)
        content.pack(fill=tk.BOTH, padx=10, pady=(0, 4))
        self._build_primary(content)
        self._build_secondary(content)
        self._build_derived(content)
        self._build_status_bar()

    def _build_header(self):
        hdr = _frame(self, C_HEADER_BG)
        hdr.pack(fill=tk.X)
        inner = _frame(hdr, C_HEADER_BG)
        inner.pack(fill=tk.X, padx=12, pady=6)

        _label(inner, "KESTREL  5500L", C_HEADER_FG, C_HEADER_BG,
               self._mono(11, bold=True), anchor='w').pack(side=tk.LEFT)
        _label(inner, "  PORTABLE WEATHER STATION",
               "#444444", C_HEADER_BG, self._f_header, anchor='w').pack(side=tk.LEFT)

        # Battery
        self._batt_lbl = _label(inner, "---", C_BATTERY_GOOD, C_HEADER_BG,
                                self._f_badge)
        self._batt_lbl.pack(side=tk.RIGHT, padx=(8, 0))
        _label(inner, "BAT", "#555555", C_HEADER_BG, self._f_small).pack(side=tk.RIGHT)

        # Connection dot
        self._conn_dot = _label(inner, "●", C_OFFLINE, C_HEADER_BG,
                                self._mono(14, bold=True))
        self._conn_dot.pack(side=tk.RIGHT, padx=(12, 8))

        # Info line
        info_frame = _frame(hdr, C_HEADER_BG)
        info_frame.pack(fill=tk.X, padx=12, pady=(0, 6))
        self._info_var = tk.StringVar(value="—")
        tk.Label(info_frame, textvariable=self._info_var, fg="#3a4a5a",
                 bg=C_HEADER_BG, font=self._f_header).pack(side=tk.LEFT)

        tk.Frame(self, bg=C_DIVIDER, height=1).pack(fill=tk.X)

    def _build_primary(self, parent):
        """Large measurement tiles: Temperature, Humidity, Wind, Pressure."""
        section = _frame(parent, C_WIN_BG)
        section.pack(fill=tk.X, pady=(8, 0))
        _label(section, "PRIMARY SENSORS", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 4))

        grid = _frame(section, C_WIN_BG)
        grid.pack()
        self._w_temp = self._big_tile(grid, "TEMPERATURE", "°F", 0, 0)
        self._w_rh = self._big_tile(grid, "RELATIVE HUMIDITY", "%", 0, 1)
        self._w_wind = self._big_tile(grid, "WIND SPEED", "mph", 0, 2)
        self._w_pres = self._big_tile(grid, "BARO PRESSURE", "inHg", 0, 3)

    def _build_secondary(self, parent):
        """Medium tiles: Altitude, DA, Dew Pt, Wet Bulb, Heat Index."""
        section = _frame(parent, C_WIN_BG)
        section.pack(fill=tk.X, pady=(6, 0))
        _label(section, "ALTITUDE / DERIVED ON-DEVICE", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 4))

        grid = _frame(section, C_WIN_BG)
        grid.pack()
        self._w_alt = self._med_tile(grid, "PRESSURE ALT", "ft", 0, 0)
        self._w_da = self._med_tile(grid, "DENSITY ALT", "ft", 0, 1)
        self._w_dp = self._med_tile(grid, "DEW POINT", "°F", 0, 2)
        self._w_wb = self._med_tile(grid, "WET BULB", "°F", 0, 3)
        self._w_hi = self._med_tile(grid, "HEAT INDEX", "°F", 0, 4)

    def _build_derived(self, parent):
        """Derived atmospheric properties + QNH."""
        section = _frame(parent, C_WIN_BG)
        section.pack(fill=tk.X, pady=(6, 0))
        _label(section, "ATMOSPHERIC / RF", C_SECTION_LABEL, C_WIN_BG,
               self._f_section, anchor='w').pack(fill=tk.X, pady=(0, 4))

        grid = _frame(section, C_WIN_BG)
        grid.pack()
        self._w_refract = self._sm_tile(grid, "RF REFRACTIVITY", "N", 0, 0)
        self._w_rho = self._sm_tile(grid, "AIR DENSITY", "kg/m³", 0, 1)
        self._w_cloud = self._sm_tile(grid, "CLOUD BASE AGL", "ft", 0, 2)
        self._w_sos = self._sm_tile(grid, "SPEED OF SOUND", "m/s", 0, 3)
        self._w_vp = self._sm_tile(grid, "VAPOR PRESSURE", "mbar", 0, 4)
        self._w_qnh = self._sm_tile(grid, "QNH (ALTIMETER)", "inHg", 0, 5)

    def _big_tile(self, parent, label, unit, row, col):
        W, H = 220, 80
        outer, inner = _tile(parent)
        outer.grid(row=row, column=col, padx=3, pady=3)
        inner.configure(width=W, height=H)
        inner.pack_propagate(False)
        _label(inner, label, C_MEAS_LABEL, C_TILE_BG, self._f_label, anchor='w').place(x=6, y=4)
        u = _label(inner, unit, C_UNIT, C_TILE_BG, self._f_unit, anchor='e')
        u.place(relx=0.95, rely=0.95, anchor='se')
        val_var = tk.StringVar(value="---")
        val_lbl = tk.Label(inner, textvariable=val_var, fg=C_VALUE_DIM,
                           bg=C_TILE_BG, font=self._f_value, anchor='e')
        val_lbl.place(relx=0.92, rely=0.58, anchor='e')
        return {"var": val_var, "lbl": val_lbl}

    def _med_tile(self, parent, label, unit, row, col):
        W, H = 175, 65
        outer, inner = _tile(parent)
        outer.grid(row=row, column=col, padx=3, pady=3)
        inner.configure(width=W, height=H)
        inner.pack_propagate(False)
        _label(inner, label, C_MEAS_LABEL, C_TILE_BG, self._f_small, anchor='w').place(x=5, y=3)
        u = _label(inner, unit, C_UNIT, C_TILE_BG, self._mono(10), anchor='e')
        u.place(relx=0.95, rely=0.95, anchor='se')
        val_var = tk.StringVar(value="---")
        val_lbl = tk.Label(inner, textvariable=val_var, fg=C_VALUE_DIM,
                           bg=C_TILE_BG, font=self._f_value_sm, anchor='e')
        val_lbl.place(relx=0.90, rely=0.58, anchor='e')
        return {"var": val_var, "lbl": val_lbl}

    def _sm_tile(self, parent, label, unit, row, col):
        W, H = 148, 58
        outer, inner = _tile(parent)
        outer.grid(row=row, column=col, padx=2, pady=2)
        inner.configure(width=W, height=H)
        inner.pack_propagate(False)
        _label(inner, label, C_MEAS_LABEL, C_TILE_BG, self._mono(7), anchor='w').place(x=4, y=2)
        u = _label(inner, unit, C_UNIT, C_TILE_BG, self._mono(9), anchor='e')
        u.place(relx=0.95, rely=0.95, anchor='se')
        val_var = tk.StringVar(value="---")
        val_lbl = tk.Label(inner, textvariable=val_var, fg=C_VALUE_DIM,
                           bg=C_TILE_BG, font=self._f_value_xs, anchor='e')
        val_lbl.place(relx=0.88, rely=0.56, anchor='e')
        return {"var": val_var, "lbl": val_lbl}

    def _build_status_bar(self):
        tk.Frame(self, bg=C_DIVIDER, height=1).pack(fill=tk.X)
        bar = _frame(self, C_STATUS_BG)
        bar.pack(fill=tk.X)
        inner = _frame(bar, C_STATUS_BG)
        inner.pack(fill=tk.X, padx=10, pady=4)
        self._status_var = tk.StringVar(value="Initializing...")
        tk.Label(inner, textvariable=self._status_var, fg=C_STATUS_FG,
                 bg=C_STATUS_BG, font=self._f_status, anchor='w').pack(side=tk.LEFT)
        self._age_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self._age_var, fg="#3a4a3a",
                 bg=C_STATUS_BG, font=self._f_status, anchor='e').pack(side=tk.RIGHT)

    # ── Poll / refresh ─────────────────────────────────────────────────────

    def _start_poll(self, interval_ms: int):
        self._REFRESH_MS = interval_ms
        if self._demo:
            self._tick()
        else:
            if not _DRIVER_OK:
                self._status_var.set("ERROR: rf_bench.kestrel not importable (pip install bleak)")
                return
            t = threading.Thread(target=_ble_worker, daemon=True,
                                 args=(self._mac, self._altitude_m,
                                       self._state_ref, self._state_lock, self._stop))
            t.start()
            self._tick()

    def _tick(self):
        if self._demo:
            s = self._demo_src.read()
        else:
            with self._state_lock:
                s = self._state_ref[0]

        self._update_ui(s)
        self.after(self._REFRESH_MS, self._tick)

    def _update_ui(self, s: State):
        # Connection
        if s.connected:
            self._conn_dot.configure(fg=C_ONLINE)
        else:
            self._conn_dot.configure(fg=C_OFFLINE)

        # Battery
        bp = s.battery_percent
        if bp is not None:
            self._batt_lbl.configure(text=f"{bp}%")
            if bp > 50:
                self._batt_lbl.configure(fg=C_BATTERY_GOOD)
            elif bp > 20:
                self._batt_lbl.configure(fg=C_BATTERY_MED)
            else:
                self._batt_lbl.configure(fg=C_BATTERY_LOW)
        else:
            self._batt_lbl.configure(text="---", fg=C_VALUE_DIM)

        # Info line
        if s.model:
            self._info_var.set(
                f"Model: {s.model}  S/N: {s.serial}  "
                f"FW: {s.firmware}  HW: {s.hardware}")
        elif s.error:
            self._info_var.set(f"Error: {s.error[:60]}")
        else:
            self._info_var.set("—")

        # Primary tiles
        self._set_tile(self._w_temp, s.temperature_f, "{:.1f}")
        self._set_tile(self._w_rh, s.relative_humidity, "{:.1f}")
        self._set_wind(s)
        self._set_tile(self._w_pres, s.station_pressure_inhg, "{:.2f}")

        # Secondary tiles
        self._set_tile(self._w_alt, s.altitude_ft, "{:.0f}")
        self._set_tile(self._w_da, s.density_altitude_ft, "{:.0f}")
        self._set_tile(self._w_dp, s.dew_point_f, "{:.1f}")
        self._set_tile(self._w_wb, s.wet_bulb_f, "{:.1f}")
        self._set_tile(self._w_hi, s.heat_index_f, "{:.1f}")

        # Derived tiles
        self._set_refractivity(s)
        self._set_tile(self._w_rho, s.air_density, "{:.4f}")
        self._set_tile(self._w_cloud, s.cloud_base_agl_ft, "{:.0f}")
        self._set_tile(self._w_sos, s.speed_of_sound_ms, "{:.1f}")
        self._set_tile(self._w_vp, s.vapor_pressure_mbar, "{:.2f}")
        self._set_tile(self._w_qnh, s.qnh_inhg, "{:.2f}")

        # Status bar
        if s.connected:
            age = time.time() - s.last_update if s.last_update else 0
            self._status_var.set(f"Connected to {self._mac}" if not self._demo
                                 else "DEMO MODE — simulated data")
            if age < 10:
                self._age_var.set(f"Updated {age:.0f}s ago")
            else:
                self._age_var.set(f"Stale ({age:.0f}s)")
        else:
            self._status_var.set(s.error or "Connecting...")
            self._age_var.set("")

    def _set_tile(self, tile, value, fmt):
        if value is not None:
            tile["var"].set(fmt.format(value))
            tile["lbl"].configure(fg=C_VALUE_LIT)
        else:
            tile["var"].set("---")
            tile["lbl"].configure(fg=C_VALUE_DIM)

    def _set_wind(self, s: State):
        v = s.wind_speed_mph
        if v is not None:
            self._w_wind["var"].set(f"{v:.1f}")
            if v < 1.0:
                self._w_wind["lbl"].configure(fg=C_WIND_CALM)
            elif v < 10.0:
                self._w_wind["lbl"].configure(fg=C_WIND_LIGHT)
            elif v < 25.0:
                self._w_wind["lbl"].configure(fg=C_WIND_MOD)
            else:
                self._w_wind["lbl"].configure(fg=C_WIND_STRONG)
        else:
            self._w_wind["var"].set("---")
            self._w_wind["lbl"].configure(fg=C_VALUE_DIM)

    def _set_refractivity(self, s: State):
        n = s.rf_refractivity
        if n is not None:
            self._w_refract["var"].set(f"{n:.1f}")
            if n > 350:
                self._w_refract["lbl"].configure(fg=C_REFRACT_DUCT)
            elif n > 320:
                self._w_refract["lbl"].configure(fg=C_REFRACT_HIGH)
            else:
                self._w_refract["lbl"].configure(fg=C_REFRACT_NORM)
        else:
            self._w_refract["var"].set("---")
            self._w_refract["lbl"].configure(fg=C_VALUE_DIM)

    def _on_close(self):
        self._stop.set()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Kestrel 5500L Virtual Instrument Panel")
    parser.add_argument("--mac", default="88:6B:0F:5F:D0:EB",
                        help="BLE MAC address (default: 88:6B:0F:5F:D0:EB)")
    parser.add_argument("--altitude", type=float, default=2003.0,
                        help="Known MSL altitude in meters for QNH (default: 2003)")
    parser.add_argument("--interval", type=int, default=4000,
                        help="UI refresh interval in ms (default: 4000)")
    parser.add_argument("--demo", action="store_true",
                        help="Run with simulated data (no BLE hardware needed)")
    args = parser.parse_args()

    panel = KestrelPanel(args.mac, args.altitude, args.interval, args.demo)
    panel.mainloop()


if __name__ == "__main__":
    main()
