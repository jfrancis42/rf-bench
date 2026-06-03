"""
rf_bench.gpsd — gpsd client driver for bench automation.

Connects to a running gpsd daemon and provides GPS position, speed,
altitude, heading, and fix quality.  Both metric and imperial units
are supported.  Auto-reconnects on connection loss or data stall.

Typical usage::

    from rf_bench.gpsd import GPSD, GPSFix, GPSDError, GPSDNoFixError
    from rf_bench.gpsd import FIX_NONE, FIX_2D, FIX_3D

    with GPSD() as gps:
        fix = gps.wait_for_fix(timeout=30)
        print(f"{fix.latitude:.6f}, {fix.longitude:.6f}")
        print(f"alt: {fix.altitude_m:.1f} m / {fix.altitude_ft:.0f} ft")
        print(f"spd: {fix.speed_kmh:.1f} km/h / {fix.speed_knots:.1f} kn")
        print(f"hdg: {fix.heading:.1f}°  HDOP: {fix.hdop}")
"""

from .gpsd import (
    GPSD,
    GPSFix,
    GPSDError,
    GPSDNoFixError,
    FIX_UNKNOWN,
    FIX_NONE,
    FIX_2D,
    FIX_3D,
)

__all__ = [
    "GPSD",
    "GPSFix",
    "GPSDError",
    "GPSDNoFixError",
    "FIX_UNKNOWN",
    "FIX_NONE",
    "FIX_2D",
    "FIX_3D",
]
