"""Kestrel 5500L weather meter driver via BLE (bleak).

Connects to the Kestrel 5500L by MAC address and subscribes to live
sensor notifications. The device advertises as "WEATHER - <serial>"
after Bluetooth is toggled on from the instrument menu.

Protocol reverse-engineered 2026-07-01 from BLE GATT notifications.
All sensor data is in service 03290000-eab4-dea1-b24e-44ec023874db.

Connection notes:
  - Device stops advertising ~30s after last disconnection.
  - Toggle Bluetooth off/on on the Kestrel to restart advertising.
  - Do NOT OS-pair the device; connect directly by MAC.
  - Only one BLE connection at a time.
"""

import asyncio
import struct
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner


KESTREL_SERVICE = "03290000-eab4-dea1-b24e-44ec023874db"

CHAR_PRIMARY = "03290310-eab4-dea1-b24e-44ec023874db"
CHAR_ALTITUDE = "03290320-eab4-dea1-b24e-44ec023874db"
CHAR_DERIVED = "03290330-eab4-dea1-b24e-44ec023874db"
CHAR_DEVICE_INFO_MODEL = "00002a24-0000-1000-8000-00805f9b34fb"
CHAR_DEVICE_INFO_SERIAL = "00002a25-0000-1000-8000-00805f9b34fb"
CHAR_DEVICE_INFO_FW = "00002a26-0000-1000-8000-00805f9b34fb"
CHAR_DEVICE_INFO_HW = "00002a27-0000-1000-8000-00805f9b34fb"
CHAR_DEVICE_INFO_MFR = "00002a29-0000-1000-8000-00805f9b34fb"
CHAR_BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"

SENTINEL = 0x8001
NO_DATA = 0xFFFF


@dataclass(slots=True)
class KestrelReading:
    """A single snapshot of all Kestrel sensor values."""
    timestamp: float = 0.0

    # Primary sensors (03290310)
    wind_speed_ms: Optional[float] = None
    temperature_c: Optional[float] = None
    relative_humidity: Optional[float] = None
    station_pressure_mbar: Optional[float] = None

    # Altitude (03290320)
    altitude_m: Optional[float] = None

    # Derived (03290330)
    dew_point_c: Optional[float] = None
    heat_index_c: Optional[float] = None
    wet_bulb_c: Optional[float] = None

    # Convenience conversions
    @property
    def temperature_f(self) -> Optional[float]:
        if self.temperature_c is None:
            return None
        return self.temperature_c * 9 / 5 + 32

    @property
    def dew_point_f(self) -> Optional[float]:
        if self.dew_point_c is None:
            return None
        return self.dew_point_c * 9 / 5 + 32

    @property
    def heat_index_f(self) -> Optional[float]:
        if self.heat_index_c is None:
            return None
        return self.heat_index_c * 9 / 5 + 32

    @property
    def wet_bulb_f(self) -> Optional[float]:
        if self.wet_bulb_c is None:
            return None
        return self.wet_bulb_c * 9 / 5 + 32

    @property
    def wind_speed_mph(self) -> Optional[float]:
        if self.wind_speed_ms is None:
            return None
        return self.wind_speed_ms * 2.23694

    @property
    def wind_speed_kt(self) -> Optional[float]:
        if self.wind_speed_ms is None:
            return None
        return self.wind_speed_ms * 1.94384

    @property
    def wind_speed_kmh(self) -> Optional[float]:
        if self.wind_speed_ms is None:
            return None
        return self.wind_speed_ms * 3.6

    @property
    def altitude_ft(self) -> Optional[float]:
        if self.altitude_m is None:
            return None
        return self.altitude_m * 3.28084

    @property
    def station_pressure_inhg(self) -> Optional[float]:
        if self.station_pressure_mbar is None:
            return None
        return self.station_pressure_mbar * 0.02953

    @property
    def vapor_pressure_mbar(self) -> Optional[float]:
        """Actual vapor pressure (e) from temperature and RH. Magnus formula."""
        if self.temperature_c is None or self.relative_humidity is None:
            return None
        t = self.temperature_c
        es = 6.1078 * 10 ** (7.5 * t / (237.3 + t))
        return es * self.relative_humidity / 100.0

    @property
    def air_density(self) -> Optional[float]:
        """Air density in kg/m³ from pressure, temp, humidity."""
        if self.station_pressure_mbar is None or self.temperature_c is None:
            return None
        p = self.station_pressure_mbar * 100.0  # Pa
        t_k = self.temperature_c + 273.15
        e = (self.vapor_pressure_mbar or 0.0) * 100.0  # Pa
        r_d = 287.058  # dry air gas constant
        r_v = 461.495  # water vapor gas constant
        return (p - e) / (r_d * t_k) + e / (r_v * t_k)

    @property
    def density_altitude_m(self) -> Optional[float]:
        """Density altitude in meters. Accounts for temp and humidity."""
        rho = self.air_density
        if rho is None:
            return None
        # ISA sea-level density = 1.225 kg/m³
        # DA = 44330.77 * (1 - (rho/1.225)^0.234969)
        return 44330.77 * (1 - (rho / 1.225) ** 0.234969)

    @property
    def density_altitude_ft(self) -> Optional[float]:
        da = self.density_altitude_m
        if da is None:
            return None
        return da * 3.28084

    @property
    def virtual_temperature_c(self) -> Optional[float]:
        """Virtual temperature — effective temp for density calculations."""
        if self.temperature_c is None or self.station_pressure_mbar is None:
            return None
        e = self.vapor_pressure_mbar or 0.0
        p = self.station_pressure_mbar
        t_k = self.temperature_c + 273.15
        tv_k = t_k / (1 - 0.378 * e / p)
        return tv_k - 273.15

    @property
    def speed_of_sound_ms(self) -> Optional[float]:
        """Speed of sound in m/s (temperature + humidity corrected)."""
        if self.temperature_c is None:
            return None
        t_k = self.temperature_c + 273.15
        # Cramer (1993) simplified: c = 331.3 * sqrt(Tv/273.15)
        tv_k = (self.virtual_temperature_c or self.temperature_c) + 273.15
        return 331.3 * (tv_k / 273.15) ** 0.5

    @property
    def rf_refractivity(self) -> Optional[float]:
        """Radio refractivity N-units. Controls VHF/UHF propagation beyond LOS.

        N = 77.6*(P/T) + 3.73e5*(e/T²)  where P in mbar, T in K, e in mbar.
        Typical surface: 250-400 N. >350 suggests possible ducting.
        """
        if self.station_pressure_mbar is None or self.temperature_c is None:
            return None
        t_k = self.temperature_c + 273.15
        p = self.station_pressure_mbar
        e = self.vapor_pressure_mbar or 0.0
        return 77.6 * (p / t_k) + 3.73e5 * (e / t_k ** 2)

    @property
    def cloud_base_agl_ft(self) -> Optional[float]:
        """Estimated cloud base AGL in feet (Espy/spread method).

        (T - Td) / 2.5 * 1000. Only valid when condensation forms clouds.
        """
        if self.temperature_c is None or self.dew_point_c is None:
            return None
        spread = self.temperature_c - self.dew_point_c
        return spread / 2.5 * 1000

    @property
    def cloud_base_agl_m(self) -> Optional[float]:
        cb = self.cloud_base_agl_ft
        if cb is None:
            return None
        return cb * 0.3048

    @property
    def wind_chill_c(self) -> Optional[float]:
        """NWS wind chill. Valid for wind > 3 mph and temp < 10°C (50°F)."""
        if self.temperature_c is None or self.wind_speed_ms is None:
            return None
        t_f = self.temperature_c * 9 / 5 + 32
        v_mph = self.wind_speed_ms * 2.23694
        if v_mph <= 3.0 or t_f > 50.0:
            return None
        wc_f = (35.74 + 0.6215 * t_f - 35.75 * v_mph ** 0.16
                + 0.4275 * t_f * v_mph ** 0.16)
        return (wc_f - 32) * 5 / 9

    @property
    def wind_chill_f(self) -> Optional[float]:
        wc = self.wind_chill_c
        if wc is None:
            return None
        return wc * 9 / 5 + 32

    def sea_level_pressure_mbar(self, true_altitude_m: float) -> Optional[float]:
        """Compute QNH (sea-level pressure) given known true altitude.

        Supply your GPS or surveyed altitude to get the pressure that would
        make altimeters read correctly at your location.
        """
        if self.station_pressure_mbar is None or self.temperature_c is None:
            return None
        t_k = self.temperature_c + 273.15
        # Hypsometric equation
        return self.station_pressure_mbar * (
            1 + 0.0065 * true_altitude_m / t_k
        ) ** 5.2561

    def sea_level_pressure_inhg(self, true_altitude_m: float) -> Optional[float]:
        qnh = self.sea_level_pressure_mbar(true_altitude_m)
        if qnh is None:
            return None
        return qnh * 0.02953

    def true_altitude_m(self, qnh_mbar: float) -> Optional[float]:
        """Compute true altitude given QNH (sea-level pressure from METAR).

        Corrects pressure altitude for non-standard atmospheric conditions.
        """
        if self.station_pressure_mbar is None or self.temperature_c is None:
            return None
        t_k = self.temperature_c + 273.15
        return t_k / 0.0065 * ((self.station_pressure_mbar / qnh_mbar) ** (-1 / 5.2561) - 1)

    def true_altitude_ft(self, qnh_mbar: float) -> Optional[float]:
        ta = self.true_altitude_m(qnh_mbar)
        if ta is None:
            return None
        return ta * 3.28084


@dataclass
class KestrelDeviceInfo:
    """Static device identification."""
    model: str = ""
    serial: str = ""
    firmware: str = ""
    hardware: str = ""
    manufacturer: str = ""
    battery_percent: int = 0


def _decode_uint16(data: bytes, offset: int) -> Optional[int]:
    val = struct.unpack_from("<H", data, offset)[0]
    if val == NO_DATA or val == SENTINEL:
        return None
    return val


class Kestrel5500:
    """BLE driver for the Kestrel 5500L weather meter.

    Usage:
        async with Kestrel5500("88:6B:0F:5F:D0:EB") as kestrel:
            info = await kestrel.get_device_info()
            print(f"{info.model} s/n {info.serial}, battery {info.battery_percent}%")

            async for reading in kestrel.stream():
                print(f"T={reading.temperature_f:.1f}°F  "
                      f"RH={reading.relative_humidity:.1f}%  "
                      f"Wind={reading.wind_speed_mph:.1f} mph  "
                      f"Pressure={reading.station_pressure_inhg:.2f} inHg")

    Or single-shot:
        async with Kestrel5500("88:6B:0F:5F:D0:EB") as kestrel:
            reading = await kestrel.read_once()
    """

    def __init__(self, address: str, scan_timeout: float = 15.0,
                 connect_timeout: float = 20.0):
        self._address = address
        self._scan_timeout = scan_timeout
        self._connect_timeout = connect_timeout
        self._client: Optional[BleakClient] = None
        self._reading = KestrelReading()
        self._callbacks: list[Callable[[KestrelReading], None]] = []
        self._update_event = asyncio.Event()

    @staticmethod
    async def discover(timeout: float = 15.0) -> list[dict]:
        """Scan for Kestrel devices. Returns list of {address, name, serial, rssi}."""
        results = []
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
        for addr, (dev, adv) in devices.items():
            name = dev.name or ""
            if name.startswith("WEATHER - "):
                serial = name.split(" - ", 1)[1].strip()
                results.append({
                    "address": addr,
                    "name": name,
                    "serial": serial,
                    "rssi": adv.rssi,
                })
        return results

    async def connect(self):
        """Scan for device and establish BLE connection."""
        device = await BleakScanner.find_device_by_address(
            self._address, timeout=self._scan_timeout
        )
        if not device:
            raise ConnectionError(
                f"Kestrel at {self._address} not found. "
                f"Toggle Bluetooth off/on on the device to restart advertising."
            )
        self._client = BleakClient(device, timeout=self._connect_timeout)
        await self._client.connect()

    async def disconnect(self):
        """Disconnect from device."""
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def latest(self) -> KestrelReading:
        """Most recent reading (may have stale fields if not all chars have updated)."""
        return self._reading

    def on_reading(self, fn: Callable[[KestrelReading], None]) -> Callable:
        """Register a callback for each new reading update."""
        self._callbacks.append(fn)
        return fn

    async def get_device_info(self) -> KestrelDeviceInfo:
        """Read static device information."""
        info = KestrelDeviceInfo()
        info.model = (await self._client.read_gatt_char(CHAR_DEVICE_INFO_MODEL)).decode().strip()
        info.serial = (await self._client.read_gatt_char(CHAR_DEVICE_INFO_SERIAL)).decode().strip()
        info.firmware = (await self._client.read_gatt_char(CHAR_DEVICE_INFO_FW)).decode().strip()
        info.hardware = (await self._client.read_gatt_char(CHAR_DEVICE_INFO_HW)).decode().strip()
        info.manufacturer = (await self._client.read_gatt_char(CHAR_DEVICE_INFO_MFR)).decode().strip()
        batt = await self._client.read_gatt_char(CHAR_BATTERY)
        info.battery_percent = batt[0]
        return info

    def _handle_primary(self, _char, data: bytes):
        """Decode characteristic 03290310 — wind, temp, RH, pressure."""
        if len(data) < 10:
            return

        wind_raw = _decode_uint16(data, 0)
        if wind_raw is not None:
            self._reading.wind_speed_ms = wind_raw * 0.001

        temp_raw = _decode_uint16(data, 2)
        if temp_raw is not None:
            self._reading.temperature_c = temp_raw * 0.01

        rh_raw = _decode_uint16(data, 6)
        if rh_raw is not None:
            self._reading.relative_humidity = rh_raw * 0.01

        pres_raw = _decode_uint16(data, 8)
        if pres_raw is not None:
            self._reading.station_pressure_mbar = pres_raw * 0.1

        self._reading.timestamp = time.time()
        self._notify()

    def _handle_altitude(self, _char, data: bytes):
        """Decode characteristic 03290320 — altitude."""
        if len(data) < 6:
            return

        alt_raw = _decode_uint16(data, 4)
        if alt_raw is not None:
            self._reading.altitude_m = alt_raw * 0.1

    def _handle_derived(self, _char, data: bytes):
        """Decode characteristic 03290330 — dew point, heat index, wet bulb."""
        if len(data) < 20:
            return

        dp_raw = _decode_uint16(data, 0)
        if dp_raw is not None:
            self._reading.dew_point_c = dp_raw * 0.01

        hi_raw = _decode_uint16(data, 2)
        if hi_raw is not None:
            self._reading.heat_index_c = hi_raw * 0.01

        wb_raw = _decode_uint16(data, 16)
        if wb_raw is not None:
            self._reading.wet_bulb_c = wb_raw * 0.01

    def _notify(self):
        """Dispatch reading to callbacks and signal waiters."""
        for fn in self._callbacks:
            fn(self._reading)
        self._update_event.set()

    async def _subscribe(self):
        """Subscribe to all sensor notification characteristics."""
        await self._client.start_notify(CHAR_PRIMARY, self._handle_primary)
        await self._client.start_notify(CHAR_ALTITUDE, self._handle_altitude)
        await self._client.start_notify(CHAR_DERIVED, self._handle_derived)

    async def read_once(self, timeout: float = 10.0) -> KestrelReading:
        """Subscribe, wait for one complete reading, return it."""
        self._update_event.clear()
        await self._subscribe()
        try:
            await asyncio.wait_for(self._update_event.wait(), timeout=timeout)
        finally:
            try:
                await self._client.stop_notify(CHAR_PRIMARY)
                await self._client.stop_notify(CHAR_ALTITUDE)
                await self._client.stop_notify(CHAR_DERIVED)
            except Exception:
                pass
        return self._reading

    async def stream(self, interval: float = 0.0):
        """Async generator yielding KestrelReading on each update.

        If interval > 0, yields at most once per interval seconds.
        """
        await self._subscribe()
        try:
            while self.is_connected:
                self._update_event.clear()
                await self._update_event.wait()
                yield self._reading
                if interval > 0:
                    await asyncio.sleep(interval)
        finally:
            try:
                await self._client.stop_notify(CHAR_PRIMARY)
                await self._client.stop_notify(CHAR_ALTITUDE)
                await self._client.stop_notify(CHAR_DERIVED)
            except Exception:
                pass

    def __repr__(self):
        state = "connected" if self.is_connected else "disconnected"
        return f"Kestrel5500({self._address!r}, {state})"
