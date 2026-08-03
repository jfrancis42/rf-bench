# MQTT Map — Kestrel 5500L Weather Meter

**Prefix:** `bench/kestrel`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/kestrel/temperature_c` | float | °C | Air temperature |
| `bench/kestrel/temperature_f` | float | °F | Air temperature |
| `bench/kestrel/relative_humidity` | float | % | Relative humidity |
| `bench/kestrel/pressure_mbar` | float | mbar | Station pressure |
| `bench/kestrel/station_pressure_inhg` | float | inHg | Station pressure |
| `bench/kestrel/wind_speed_ms` | float | m/s | Wind speed |
| `bench/kestrel/wind_speed_mph` | float | mph | Wind speed |
| `bench/kestrel/wind_speed_kt` | float | kt | Wind speed |
| `bench/kestrel/altitude_m` | float | m | Barometric altitude |
| `bench/kestrel/altitude_ft` | float | ft | Barometric altitude |
| `bench/kestrel/dew_point_c` | float | °C | Dew point temperature |
| `bench/kestrel/wet_bulb_c` | float | °C | Wet bulb temperature |
| `bench/kestrel/heat_index_c` | float | °C | Heat index |
| `bench/kestrel/wind_chill_c` | float | °C | Wind chill |
| `bench/kestrel/density_altitude_ft` | float | ft | Density altitude |
| `bench/kestrel/rf_refractivity` | float | N-units | RF refractivity (tropospheric ducting indicator) |
| `bench/kestrel/air_density` | float | kg/m³ | Air density |
| `bench/kestrel/cloud_base_agl_ft` | float | ft | Estimated cloud base AGL |
| `bench/kestrel/speed_of_sound_ms` | float | m/s | Local speed of sound |
| `bench/kestrel/vapor_pressure_mbar` | float | mbar | Vapor pressure |

## Command topics

None — the Kestrel is a read-only sensor.

## Notes

- **Push-based:** Data arrives via BLE notifications every ~4 seconds (not polled).
- **Async bridge:** Uses asyncio event loop, not the standard Bridge base class.
- **BLE connection:** MAC address 88:6B:0F:5F:D0:EB. Device must be powered on and
  within BLE range. Advertising stops ~30s after disconnect; toggle BT on Kestrel to restart.
- **RF refractivity** > 350 indicates enhanced tropospheric ducting conditions.

**Bridge script:** `drivers/mqtt/bridges/bridge_kestrel.py`
