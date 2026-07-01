# rf-bench-drivers-kestrel

Linux BLE driver for the Kestrel 5500L weather meter (Nielsen-Kellerman).

## Hardware

The Kestrel 5500L measures:
- Wind speed (impeller anemometer, 0.4–60 m/s)
- Temperature (-29°C to +70°C, ±0.5°C)
- Relative humidity (10–90% non-condensing, ±2%)
- Barometric pressure (300–1100 mbar, ±1.5 mbar)
- Altitude (derived from pressure)
- Dew point (derived)
- Wet bulb temperature (derived)
- Heat index (derived)
- Density altitude (derived)
- Wind chill (derived)

## Installation

```bash
pip install rf-bench-drivers-kestrel
```

Requires Linux with BlueZ 5.x and a BLE-capable adapter.

## Connection Notes

The Kestrel 5500L BLE has specific behaviors:

1. **Do NOT OS-pair** — connect directly by MAC address
2. **Toggle Bluetooth** on the Kestrel to restart advertising (it stops ~30s after disconnection)
3. **Only one connection** at a time — disconnect the Kestrel LiNK phone app first
4. **Initial setup**: pair once with the Kestrel LiNK app to complete firmware setup, then disconnect and use this driver

To find the MAC address:
```python
import asyncio
from rf_bench.kestrel import Kestrel5500

async def find():
    devices = await Kestrel5500.discover()
    for d in devices:
        print(f"{d['name']}  MAC={d['address']}  RSSI={d['rssi']}")

asyncio.run(find())
```

The device advertises as `WEATHER - <serial_number>`.

**Important: BLE advertising is finicky.** The Kestrel stops advertising
approximately 30 seconds after the last BLE disconnection. To make it
discoverable again, you must toggle Bluetooth off and back on from the
Kestrel's menu (gear icon → Bluetooth → toggle off → toggle on). There is
no way to force it to re-advertise without this manual toggle. Plan your
connection logic accordingly — if the scan fails, prompt the user to
toggle BLE on the device.

## Usage

### Single reading

```python
import asyncio
from rf_bench.kestrel import Kestrel5500

async def main():
    async with Kestrel5500("88:6B:0F:5F:D0:EB") as kestrel:
        reading = await kestrel.read_once()
        print(f"Temperature: {reading.temperature_f:.1f}°F")
        print(f"Humidity:    {reading.relative_humidity:.1f}%")
        print(f"Wind:        {reading.wind_speed_mph:.1f} mph")
        print(f"Pressure:    {reading.station_pressure_inhg:.2f} inHg")
        print(f"Altitude:    {reading.altitude_ft:.0f} ft")
        print(f"Dew point:   {reading.dew_point_f:.1f}°F")
        print(f"Wet bulb:    {reading.wet_bulb_f:.1f}°F")
        print(f"Heat index:  {reading.heat_index_f:.1f}°F")

asyncio.run(main())
```

### Continuous streaming

```python
import asyncio
from rf_bench.kestrel import Kestrel5500

async def main():
    async with Kestrel5500("88:6B:0F:5F:D0:EB") as kestrel:
        async for reading in kestrel.stream():
            print(f"T={reading.temperature_f:.1f}°F  "
                  f"RH={reading.relative_humidity:.1f}%  "
                  f"Wind={reading.wind_speed_mph:.1f} mph")

asyncio.run(main())
```

### Callback-based

```python
import asyncio
from rf_bench.kestrel import Kestrel5500

async def main():
    async with Kestrel5500("88:6B:0F:5F:D0:EB") as kestrel:
        @kestrel.on_reading
        def updated(reading):
            print(f"Wind: {reading.wind_speed_mph:.1f} mph")

        reading = await kestrel.read_once()

asyncio.run(main())
```

### Device info

```python
async with Kestrel5500("88:6B:0F:5F:D0:EB") as kestrel:
    info = await kestrel.get_device_info()
    print(f"Model:    {info.model}")
    print(f"Serial:   {info.serial}")
    print(f"Firmware: {info.firmware}")
    print(f"Hardware: {info.hardware}")
    print(f"Battery:  {info.battery_percent}%")
```

## BLE Protocol Reference

Protocol reverse-engineered 2026-07-01 from GATT notifications on firmware 1.57.

### Device identification

| Characteristic | UUID | Contents |
|---|---|---|
| Device Name | `00002a00` | `"WEATHER - XXXXXXX"` |
| Manufacturer | `00002a29` | `"Kestrel by NK"` |
| Model Number | `00002a24` | `"5500L"` |
| Serial Number | `00002a25` | `"XXXXXXX"` |
| Firmware Rev | `00002a26` | `"1.57"` |
| Hardware Rev | `00002a27` | `"Rev 11B"` |
| Battery Level | `00002a19` | uint8, 0–100% |

### Sensor data service

Service UUID: `03290000-eab4-dea1-b24e-44ec023874db`

All sensor data is delivered via BLE notifications (subscribe to receive
updates every ~4 seconds). Values are unsigned 16-bit little-endian integers.
Sentinel values: `0xFFFF` = no data / sensor unavailable, `0x8001` = field not applicable.

#### Characteristic `03290310` — Primary sensors (20 bytes)

| Offset | Bytes | Field | Unit | Encoding | Range |
|--------|-------|-------|------|----------|-------|
| 0 | 2 | Wind speed | m/s | uint16 LE × 0.001 | 0–60000 (0–60 m/s) |
| 2 | 2 | Temperature | °C | uint16 LE × 0.01 | 0–9999 (-29°C to +70°C) |
| 4 | 2 | (reserved/sentinel) | — | typically 0x8001 | — |
| 6 | 2 | Relative humidity | % | uint16 LE × 0.01 | 0–10000 (0–100%) |
| 8 | 2 | Station pressure | mbar | uint16 LE × 0.1 | 3000–11000 (300–1100 mbar) |
| 10 | 10 | (padding/unused) | — | 0xFF or 0x00 | — |

Temperature encoding note: values represent absolute Celsius × 100. At the
observed range (indoor ~24°C), values are around 2400. Negative temperatures
have not been verified but likely use signed int16 (two's complement).

Wind speed 0 = calm. The impeller requires ~0.4 m/s minimum to register.

#### Characteristic `03290320` — Altitude (20 bytes)

| Offset | Bytes | Field | Unit | Encoding | Range |
|--------|-------|-------|------|----------|-------|
| 0 | 4 | (unused) | — | 0xFFFFFFFF | — |
| 4 | 2 | Altitude | meters | uint16 LE × 0.1 | 0–65534 (0–6553.4 m) |
| 6 | 14 | (other derived values, partially decoded) | — | — | — |

Altitude is pressure altitude derived from station pressure using the
standard atmosphere model. Matches the "Altitude" reading on the Kestrel
display. To get MSL altitude, the device's reference pressure must be set
correctly (done via the Kestrel LiNK app or on-device menu).

#### Characteristic `03290330` — Derived measurements (20 bytes)

| Offset | Bytes | Field | Unit | Encoding | Range |
|--------|-------|-------|------|----------|-------|
| 0 | 2 | Dew point | °C | uint16 LE × 0.01 | — |
| 2 | 2 | Heat index | °C | uint16 LE × 0.01 | — |
| 4 | 12 | (other fields, not yet decoded) | — | — | — |
| 16 | 2 | Wet bulb temperature | °C | uint16 LE × 0.01 | — |
| 18 | 2 | (temperature echo or wind chill) | °C | uint16 LE × 0.01 | — |

Heat index is computed from temperature and humidity per the NWS algorithm.
Wet bulb is the thermodynamic wet-bulb temperature (psychrometric).

#### Characteristics `03290340`, `03290350`, `03290360`, `03290370`, `03290380`

These characteristics also carry notifications but have not been fully
decoded. Based on the 5500L's capabilities, they likely contain:
- Density altitude
- Wind chill
- Crosswind / headwind components
- Evaporation rate
- WBGT (Wet Bulb Globe Temperature)
- Logging/min/max data

Contributions to decode these fields are welcome.

#### Control service `85920000-0338-4b83-ae4a-ac1d217adb03`

| Characteristic | Properties | Purpose |
|---|---|---|
| `85920200` | write | Command channel (device control) |
| `85920100` | read, indicate | Response/status channel |
| `8592ffff` | read | Lookup table (battery discharge curve or calibration) |

The control service is used by the Kestrel LiNK app for log downloads,
firmware updates, and device configuration. Not needed for live sensor data.

## Unit Conversions and Derived Properties

The `KestrelReading` object provides properties for unit conversions and
computed atmospheric values. All return `None` if the required input
sensors haven't reported yet.

### Direct unit conversions

| Property | Unit | Source |
|---|---|---|
| `temperature_c` | °C | raw sensor |
| `temperature_f` | °F | temperature_c × 9/5 + 32 |
| `wind_speed_ms` | m/s | raw sensor |
| `wind_speed_mph` | mph | wind_speed_ms × 2.23694 |
| `wind_speed_kt` | knots | wind_speed_ms × 1.94384 |
| `wind_speed_kmh` | km/h | wind_speed_ms × 3.6 |
| `altitude_m` | meters | raw sensor (pressure altitude) |
| `altitude_ft` | feet | altitude_m × 3.28084 |
| `station_pressure_mbar` | mbar | raw sensor |
| `station_pressure_inhg` | inHg | station_pressure_mbar × 0.02953 |
| `relative_humidity` | % | raw sensor |
| `dew_point_c` / `dew_point_f` | °C / °F | derived on-device |
| `wet_bulb_c` / `wet_bulb_f` | °C / °F | derived on-device |
| `heat_index_c` / `heat_index_f` | °C / °F | derived on-device |

### Computed atmospheric properties

| Property | Unit | Description |
|---|---|---|
| `vapor_pressure_mbar` | mbar | Actual water vapor pressure (Magnus formula from T + RH) |
| `air_density` | kg/m³ | Moist air density from pressure, temperature, humidity |
| `density_altitude_m` / `density_altitude_ft` | m / ft | Performance altitude accounting for temperature and humidity |
| `virtual_temperature_c` | °C | Effective temperature for density calculations |
| `speed_of_sound_ms` | m/s | Temperature and humidity corrected (Cramer 1993) |
| `rf_refractivity` | N-units | Radio refractivity: 77.6(P/T) + 3.73×10⁵(e/T²). Typical surface: 250–400. >350 suggests ducting. |
| `cloud_base_agl_ft` / `cloud_base_agl_m` | ft / m | Estimated cloud base AGL (Espy/spread method: (T−Td)/2.5 × 1000 ft) |
| `wind_chill_c` / `wind_chill_f` | °C / °F | NWS wind chill (valid for wind > 3 mph and temp < 50°F; None otherwise) |

### Methods requiring user-supplied reference

```python
# Given your known true altitude (GPS or survey), compute QNH:
qnh_mbar = reading.sea_level_pressure_mbar(true_altitude_m=2003.0)
qnh_inhg = reading.sea_level_pressure_inhg(true_altitude_m=2003.0)

# Given QNH from a METAR/ATIS, compute true altitude:
true_alt_m = reading.true_altitude_m(qnh_mbar=1013.25)
true_alt_ft = reading.true_altitude_ft(qnh_mbar=1013.25)
```

| Method | Input | Output | Use case |
|---|---|---|---|
| `sea_level_pressure_mbar(true_altitude_m)` | Known MSL altitude in meters | QNH in mbar | Weather reporting, altimeter setting |
| `sea_level_pressure_inhg(true_altitude_m)` | Known MSL altitude in meters | QNH in inHg | Aviation altimeter setting |
| `true_altitude_m(qnh_mbar)` | Sea-level pressure from METAR | True altitude in meters | Position determination |
| `true_altitude_ft(qnh_mbar)` | Sea-level pressure from METAR | True altitude in feet | Aviation |

## Tested Configuration

- Kestrel 5500L, serial XXXXXXX, firmware 1.57, hardware Rev 11B
- Linux 6.8 (Ubuntu), BlueZ 5.x, Python 3.14, bleak 3.0.2
- Host: Intel NUC (10.1.0.10) with built-in BLE adapter
