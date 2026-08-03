# MQTT Map — GPS (via gpsd)

**Prefix:** `bench/gps`

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/gps/fix` | bool | — | Has any GPS fix |
| `bench/gps/fix_3d` | bool | — | Has 3D fix |
| `bench/gps/lat` | float | ° | Latitude (WGS84) |
| `bench/gps/lon` | float | ° | Longitude (WGS84) |
| `bench/gps/alt_ft` | float | ft | Altitude above MSL |
| `bench/gps/speed_mph` | float | mph | Ground speed |
| `bench/gps/heading_deg` | float | ° | Track heading (true north) |
| `bench/gps/hdop` | float | — | Horizontal dilution of precision |
| `bench/gps/satellites_used` | int | — | Number of satellites used in fix |

## Command topics

None — GPS is read-only.

**Poll interval:** 1 s
**Connection:** gpsd daemon at localhost:2947
**Bridge script:** `drivers/mqtt/bridges/bridge_gps.py`
