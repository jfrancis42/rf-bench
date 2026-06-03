# rf-bench-drivers-gpsd

gpsd client driver for the [rf-bench](https://github.com/jfrancis42/rf-bench) bench automation framework.

Connects to a running [gpsd](https://gpsd.gitlab.io/gpsd/) daemon over its JSON/TCP protocol and exposes GPS position, speed, altitude, heading, and fix quality.  Both metric and imperial units are provided.  A background thread maintains the connection and auto-reconnects with exponential back-off on any failure or data stall.

## Requirements

- Python ≥ 3.9
- `gpsd` running and accessible (default: `localhost:2947`)
- No additional Python dependencies — uses stdlib `socket`, `json`, `threading` only

## Installation

```bash
pip install rf-bench-drivers-gpsd
```

Or as part of the full rf-bench suite:

```bash
pip install rf-bench
```

## Quick start

```python
from rf_bench.gpsd import GPSD, GPSDNoFixError

with GPSD() as gps:
    # Block until 2D fix (or raise GPSDNoFixError after 30 s)
    fix = gps.wait_for_fix(timeout=30)
    print(f"Position : {fix.latitude:.6f}, {fix.longitude:.6f}")
    print(f"Altitude : {fix.altitude_m:.1f} m  /  {fix.altitude_ft:.0f} ft")
    print(f"Speed    : {fix.speed_kmh:.1f} km/h  /  {fix.speed_knots:.1f} kn  /  {fix.speed_mph:.1f} mph")
    print(f"Heading  : {fix.heading}°")
    print(f"Fix mode : {fix.fix_mode}  (sats used: {fix.satellites_used})")
    print(f"HDOP     : {fix.hdop}  VDOP: {fix.vdop}  PDOP: {fix.pdop}")
```

## API

### `GPSD(host='localhost', port=2947, stale_timeout=10, reconnect_delay=2, max_reconnect_delay=60)`

The main driver class.  Spawns a background daemon thread on construction.

| Method / property | Description |
|-------------------|-------------|
| `get_fix()` | Return a `GPSFix` snapshot (non-blocking, may have no fix) |
| `wait_for_fix(timeout=30, require_3d=False)` | Block until fix; raises `GPSDNoFixError` on timeout |
| `is_connected` | `True` while TCP socket to gpsd is open |
| `is_stale` | `True` if no TPV update received within `stale_timeout` seconds |
| `has_fix` | `True` if 2D or 3D fix is available |
| `has_3d_fix` | `True` if 3D fix with altitude is available |
| `fix_mode` | `FIX_UNKNOWN`/`FIX_NONE`/`FIX_2D`/`FIX_3D` (0–3) |
| `latitude` | Decimal degrees, +N |
| `longitude` | Decimal degrees, +E |
| `altitude_m` | Metres MSL (or HAE fallback) |
| `altitude_ft` | Feet |
| `speed_ms` | m/s over ground |
| `speed_kmh` | km/h |
| `speed_mph` | mph |
| `speed_knots` | knots |
| `heading` | True heading, 0–360° |
| `hdop` / `vdop` / `pdop` | Dilution of precision |
| `satellites_used` / `satellites_visible` | Satellite counts |
| `close()` | Stop background thread |

`GPSD` is a context manager (`with GPSD() as gps: ...`).

### `GPSFix`

Dataclass snapshot returned by `get_fix()` and `wait_for_fix()`.  Contains all the same fields as the GPSD properties above, plus:

- `time_utc` — ISO 8601 timestamp from the GPS receiver
- `received_at` — `time.monotonic()` when the fix was stored
- `age_s` — seconds since `received_at`
- `error_lat_m`, `error_lon_m`, `error_alt_m`, `error_speed_ms` — 1-sigma error estimates in SI units
- `as_dict(units='metric')` — all fields as a plain dict; pass `'imperial'` for ft/mph/knots

### Fix mode constants

```python
from rf_bench.gpsd import FIX_UNKNOWN, FIX_NONE, FIX_2D, FIX_3D
```

### Exceptions

```python
from rf_bench.gpsd import GPSDError, GPSDNoFixError
```

`GPSDNoFixError` is raised by `wait_for_fix()` on timeout.

## Remote gpsd

```python
gps = GPSD(host="10.1.0.20", port=2947)
```

## Auto-reconnect behaviour

The background thread reconnects automatically on:
- Connection refused or network error
- Socket read error or remote disconnect
- No TPV update received for `stale_timeout` seconds (default 10 s)

Reconnect delay starts at `reconnect_delay` seconds (default 2 s), doubles on each consecutive failure, and caps at `max_reconnect_delay` (default 60 s).  The delay resets to the initial value after a successful connection cycle.
