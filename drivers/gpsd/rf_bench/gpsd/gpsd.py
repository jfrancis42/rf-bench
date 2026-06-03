"""
gpsd client driver for rf-bench.

Connects to a running gpsd daemon over its JSON/TCP protocol and exposes
GPS position, speed, altitude, heading, and fix quality.  Both metric and
imperial unit accessors are provided.

The driver runs a background thread that maintains the TCP connection to
gpsd and auto-reconnects with exponential back-off on:
  - connection refused / network error
  - socket read error or remote close
  - data stall (no TPV update for ``stale_timeout`` seconds)

Typical usage::

    from rf_bench.gpsd import GPSD, GPSFix

    with GPSD() as gps:
        fix = gps.wait_for_fix(timeout=30)
        print(f"{fix.latitude:.6f}, {fix.longitude:.6f}  "
              f"alt={fix.altitude_m:.1f} m  spd={fix.speed_kmh:.1f} km/h")

    # Individual metric properties
    with GPSD() as gps:
        print(gps.latitude, gps.longitude)
        print(gps.altitude_m, gps.altitude_ft)
        print(gps.speed_ms, gps.speed_kmh, gps.speed_mph, gps.speed_knots)
        print(gps.heading, gps.fix_mode)
        print(gps.hdop, gps.vdop, gps.pdop)
        print(gps.satellites_used, gps.satellites_visible)

    # Snapshot dict
    with GPSD() as gps:
        d = gps.get_fix().as_dict()           # metric
        d = gps.get_fix().as_dict("imperial") # imperial

gpsd must be running and accessible at the given host/port.
Default: localhost:2947.  The gpsd daemon must have a GPS device attached
and configured; see ``gpsd(8)``.
"""

import copy
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 2947

# ?WATCH command: subscribe to JSON position reports, suppress raw NMEA
_WATCH_CMD = b'?WATCH={"enable":true,"json":true,"nmea":false}\n'

# Fix mode codes from gpsd JSON protocol
FIX_UNKNOWN = 0
FIX_NONE = 1
FIX_2D = 2
FIX_3D = 3

# Conversion constants (exact per NIST)
_MS_TO_KMH: float = 3.6
_MS_TO_MPH: float = 2.2369362920544
_MS_TO_KNOTS: float = 1.9438444924574
_M_TO_FT: float = 3.280839895013


# ── exceptions ────────────────────────────────────────────────────────────────

class GPSDError(RuntimeError):
    """Base exception for gpsd driver errors."""


class GPSDNoFixError(GPSDError):
    """Raised when a GPS fix is not obtained within the requested timeout."""


# ── fix snapshot ──────────────────────────────────────────────────────────────

@dataclass
class GPSFix:
    """
    Immutable snapshot of the GPS state at a single point in time.

    Metric fields are the native storage format; imperial fields are computed
    properties.  Any field may be ``None`` if the GPS has not reported it yet
    or if the current fix mode does not include that datum.

    Attributes:
        latitude:           Decimal degrees, positive = North.
        longitude:          Decimal degrees, positive = East.
        altitude_m:         Altitude above mean sea level in metres (MSL preferred,
                            falls back to HAE if MSL unavailable).
        speed_ms:           Speed over ground in m/s.
        heading:            True heading (course over ground) in degrees, 0–360.
        fix_mode:           ``FIX_UNKNOWN`` (0), ``FIX_NONE`` (1), ``FIX_2D`` (2),
                            or ``FIX_3D`` (3).
        hdop / vdop / pdop: Horizontal, vertical, and positional dilution of
                            precision (dimensionless; lower is better).
        error_lat_m:        1-sigma latitude error in metres (epy from gpsd).
        error_lon_m:        1-sigma longitude error in metres (epx from gpsd).
        error_alt_m:        1-sigma altitude error in metres (epv from gpsd).
        error_speed_ms:     1-sigma speed error in m/s (eps from gpsd).
        satellites_used:    Number of satellites used in the fix computation.
        satellites_visible: Total satellites visible to the receiver.
        time_utc:           ISO 8601 timestamp string from the GPS receiver.
        received_at:        ``time.monotonic()`` value when the fix was stored.
    """

    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    speed_ms: Optional[float] = None
    heading: Optional[float] = None
    fix_mode: int = FIX_UNKNOWN
    hdop: Optional[float] = None
    vdop: Optional[float] = None
    pdop: Optional[float] = None
    error_lat_m: Optional[float] = None
    error_lon_m: Optional[float] = None
    error_alt_m: Optional[float] = None
    error_speed_ms: Optional[float] = None
    satellites_used: Optional[int] = None
    satellites_visible: Optional[int] = None
    time_utc: Optional[str] = None
    received_at: float = field(default_factory=time.monotonic)

    # ── imperial derived properties ───────────────────────────────────────────

    @property
    def altitude_ft(self) -> Optional[float]:
        """Altitude in feet (MSL, same source as ``altitude_m``)."""
        return None if self.altitude_m is None else self.altitude_m * _M_TO_FT

    @property
    def speed_kmh(self) -> Optional[float]:
        """Speed over ground in km/h."""
        return None if self.speed_ms is None else self.speed_ms * _MS_TO_KMH

    @property
    def speed_mph(self) -> Optional[float]:
        """Speed over ground in miles per hour."""
        return None if self.speed_ms is None else self.speed_ms * _MS_TO_MPH

    @property
    def speed_knots(self) -> Optional[float]:
        """Speed over ground in knots."""
        return None if self.speed_ms is None else self.speed_ms * _MS_TO_KNOTS

    # ── fix status helpers ────────────────────────────────────────────────────

    @property
    def has_fix(self) -> bool:
        """True if at least a 2D position fix is available."""
        return self.fix_mode >= FIX_2D and self.latitude is not None

    @property
    def has_3d_fix(self) -> bool:
        """True if a 3D fix (with altitude) is available."""
        return self.fix_mode >= FIX_3D and self.altitude_m is not None

    @property
    def age_s(self) -> float:
        """Seconds elapsed since this fix was stored by the driver."""
        return time.monotonic() - self.received_at

    # ── dict export ───────────────────────────────────────────────────────────

    def as_dict(self, units: str = "metric") -> dict:
        """
        Return all fix fields as a plain dict.

        Args:
            units: ``'metric'`` (default) or ``'imperial'``.  Imperial replaces
                   altitude_m with altitude_ft and speed_ms with speed_mph /
                   speed_knots; latitude, longitude, and heading are identical
                   in both systems.

        Returns:
            dict with all available fields; unknown fields are ``None``.
        """
        base = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "heading": self.heading,
            "fix_mode": self.fix_mode,
            "has_fix": self.has_fix,
            "has_3d_fix": self.has_3d_fix,
            "hdop": self.hdop,
            "vdop": self.vdop,
            "pdop": self.pdop,
            "error_lat_m": self.error_lat_m,
            "error_lon_m": self.error_lon_m,
            "satellites_used": self.satellites_used,
            "satellites_visible": self.satellites_visible,
            "time_utc": self.time_utc,
            "age_s": self.age_s,
        }
        if units == "imperial":
            base.update({
                "altitude_ft": self.altitude_ft,
                "speed_mph": self.speed_mph,
                "speed_knots": self.speed_knots,
                "error_alt_ft": (
                    None if self.error_alt_m is None
                    else self.error_alt_m * _M_TO_FT
                ),
                "error_speed_mph": (
                    None if self.error_speed_ms is None
                    else self.error_speed_ms * _MS_TO_MPH
                ),
            })
        else:
            base.update({
                "altitude_m": self.altitude_m,
                "speed_ms": self.speed_ms,
                "speed_kmh": self.speed_kmh,
                "error_alt_m": self.error_alt_m,
                "error_speed_ms": self.error_speed_ms,
            })
        return base


# ── main driver ───────────────────────────────────────────────────────────────

class GPSD:
    """
    gpsd client driver with background auto-reconnect.

    Spawns a daemon thread that connects to gpsd, subscribes to JSON position
    reports, and keeps the internal fix state current.  On any failure the
    thread reconnects with exponential back-off up to ``max_reconnect_delay``.
    Data staleness (no TPV for ``stale_timeout`` seconds) also triggers a
    reconnect so a frozen GPS or hung socket does not silently return stale
    data indefinitely.

    Thread safety: all public properties and methods are safe to call from
    any thread simultaneously.

    Args:
        host:               gpsd hostname or IP address (default: ``'localhost'``).
        port:               gpsd TCP port (default: 2947).
        stale_timeout:      Seconds without a new TPV report before the driver
                            considers the connection stale and reconnects
                            (default: 10).
        reconnect_delay:    Initial retry delay in seconds after a failure
                            (default: 2).  Doubles on each consecutive failure
                            up to ``max_reconnect_delay``.
        max_reconnect_delay: Maximum retry delay in seconds (default: 60).
    """

    def __init__(
        self,
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        stale_timeout: float = 10.0,
        reconnect_delay: float = 2.0,
        max_reconnect_delay: float = 60.0,
    ) -> None:
        self._host = host
        self._port = port
        self._stale_timeout = stale_timeout
        self._initial_reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay

        self._lock = threading.Lock()
        self._fix = GPSFix()

        # Written only from the reader thread; float writes are atomic in CPython.
        # External readers (is_stale, is_connected) use volatile read semantics.
        # Initialise to now so is_stale is False while the first connection is
        # being established (avoids a spurious stale flag on startup).
        self._last_tpv_monotonic: float = time.monotonic()
        self._connected: bool = False

        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="gpsd-reader"
        )
        self._thread.start()

    # ── background reader ─────────────────────────────────────────────────────

    def _run(self) -> None:
        """Background thread: connect → read → reconnect loop."""
        delay = self._initial_reconnect_delay
        while not self._stop_event.is_set():
            try:
                self._connect_and_read()
                delay = self._initial_reconnect_delay  # reset after clean loop
            except Exception:
                pass
            if not self._stop_event.is_set():
                self._stop_event.wait(delay)
                delay = min(delay * 2.0, self._max_reconnect_delay)

    def _connect_and_read(self) -> None:
        """Open a socket to gpsd, subscribe, and read until stale or error."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        try:
            sock.connect((self._host, self._port))
        except OSError:
            sock.close()
            return

        self._last_tpv_monotonic = time.monotonic()
        self._connected = True

        try:
            sock.sendall(_WATCH_CMD)
            buf = b""
            while not self._stop_event.is_set():
                # Stale-data check: reconnect if gpsd stops sending TPV
                if time.monotonic() - self._last_tpv_monotonic > self._stale_timeout:
                    break

                sock.settimeout(2.0)
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break

                if not chunk:
                    break  # remote close

                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if line:
                        self._handle_json(line)
        finally:
            self._connected = False
            try:
                sock.close()
            except OSError:
                pass

    def _handle_json(self, line: bytes) -> None:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        cls = msg.get("class", "")
        if cls == "TPV":
            self._handle_tpv(msg)
        elif cls == "SKY":
            self._handle_sky(msg)

    def _handle_tpv(self, msg: dict) -> None:
        """Process a TPV (time-position-velocity) message."""
        # Prefer MSL altitude; fall back to HAE, then deprecated 'alt' key
        alt_m: Optional[float] = None
        for key in ("altMSL", "altHAE", "alt"):
            v = msg.get(key)
            if v is not None:
                alt_m = float(v)
                break

        new_fix = GPSFix(
            latitude=_opt_float(msg, "lat"),
            longitude=_opt_float(msg, "lon"),
            altitude_m=alt_m,
            speed_ms=_opt_float(msg, "speed"),
            heading=_opt_float(msg, "track"),
            fix_mode=int(msg.get("mode", FIX_UNKNOWN)),
            error_lat_m=_opt_float(msg, "epy"),
            error_lon_m=_opt_float(msg, "epx"),
            error_alt_m=_opt_float(msg, "epv"),
            error_speed_ms=_opt_float(msg, "eps"),
            time_utc=msg.get("time"),
        )

        with self._lock:
            # Carry over satellite and DOP data from the last SKY message
            new_fix.hdop = self._fix.hdop
            new_fix.vdop = self._fix.vdop
            new_fix.pdop = self._fix.pdop
            new_fix.satellites_used = self._fix.satellites_used
            new_fix.satellites_visible = self._fix.satellites_visible
            self._fix = new_fix

        self._last_tpv_monotonic = time.monotonic()

    def _handle_sky(self, msg: dict) -> None:
        """Process a SKY (satellite constellation) message."""
        sats = msg.get("satellites") or []
        used = sum(1 for s in sats if s.get("used", False))
        with self._lock:
            self._fix.hdop = _opt_float(msg, "hdop")
            self._fix.vdop = _opt_float(msg, "vdop")
            self._fix.pdop = _opt_float(msg, "pdop")
            self._fix.satellites_visible = len(sats)
            self._fix.satellites_used = used if sats else self._fix.satellites_used

    # ── status ────────────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        """True if the TCP connection to gpsd is currently open."""
        return self._connected

    @property
    def is_stale(self) -> bool:
        """True if no TPV update has been received within ``stale_timeout`` seconds."""
        return time.monotonic() - self._last_tpv_monotonic > self._stale_timeout

    # ── fix access ────────────────────────────────────────────────────────────

    def get_fix(self) -> GPSFix:
        """
        Return a snapshot of the current GPS state.

        The returned :class:`GPSFix` reflects the last data received from gpsd.
        Check ``fix.has_fix`` or ``fix.fix_mode`` before using position fields.
        The snapshot is safe to retain after the call — subsequent GPS updates
        do not modify it.
        """
        with self._lock:
            return copy.copy(self._fix)

    def wait_for_fix(self, timeout: float = 30.0, require_3d: bool = False) -> GPSFix:
        """
        Block until a GPS fix is acquired or *timeout* elapses.

        Args:
            timeout:    Maximum wait in seconds (default: 30).
            require_3d: If ``True``, wait until ``fix_mode == FIX_3D`` and
                        altitude is available (default: ``False``).

        Returns:
            :class:`GPSFix` with ``has_fix`` (or ``has_3d_fix``) equal to
            ``True``.

        Raises:
            :exc:`GPSDNoFixError`: If no qualifying fix arrives within *timeout*.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            fix = self.get_fix()
            if require_3d and fix.has_3d_fix:
                return fix
            if not require_3d and fix.has_fix:
                return fix
            time.sleep(0.25)
        kind = "3D GPS" if require_3d else "GPS"
        raise GPSDNoFixError(
            f"No {kind} fix obtained within {timeout:.0f} s "
            f"(current fix_mode={self.fix_mode})"
        )

    # ── metric properties ─────────────────────────────────────────────────────

    @property
    def latitude(self) -> Optional[float]:
        """Latitude in decimal degrees (+N)."""
        with self._lock:
            return self._fix.latitude

    @property
    def longitude(self) -> Optional[float]:
        """Longitude in decimal degrees (+E)."""
        with self._lock:
            return self._fix.longitude

    @property
    def altitude_m(self) -> Optional[float]:
        """Altitude above MSL in metres (or HAE if MSL unavailable)."""
        with self._lock:
            return self._fix.altitude_m

    @property
    def speed_ms(self) -> Optional[float]:
        """Speed over ground in metres per second."""
        with self._lock:
            return self._fix.speed_ms

    @property
    def speed_kmh(self) -> Optional[float]:
        """Speed over ground in kilometres per hour."""
        v = self.speed_ms
        return None if v is None else v * _MS_TO_KMH

    # ── imperial properties ───────────────────────────────────────────────────

    @property
    def altitude_ft(self) -> Optional[float]:
        """Altitude in feet (same source as ``altitude_m``)."""
        v = self.altitude_m
        return None if v is None else v * _M_TO_FT

    @property
    def speed_mph(self) -> Optional[float]:
        """Speed over ground in miles per hour."""
        v = self.speed_ms
        return None if v is None else v * _MS_TO_MPH

    @property
    def speed_knots(self) -> Optional[float]:
        """Speed over ground in knots."""
        v = self.speed_ms
        return None if v is None else v * _MS_TO_KNOTS

    # ── navigation ────────────────────────────────────────────────────────────

    @property
    def heading(self) -> Optional[float]:
        """True heading (course over ground) in degrees, 0–360."""
        with self._lock:
            return self._fix.heading

    @property
    def fix_mode(self) -> int:
        """
        Current fix mode: ``FIX_UNKNOWN`` (0), ``FIX_NONE`` (1),
        ``FIX_2D`` (2), or ``FIX_3D`` (3).
        """
        with self._lock:
            return self._fix.fix_mode

    @property
    def has_fix(self) -> bool:
        """True if a 2D or 3D position fix is available."""
        with self._lock:
            return self._fix.has_fix

    @property
    def has_3d_fix(self) -> bool:
        """True if a 3D fix with altitude is available."""
        with self._lock:
            return self._fix.has_3d_fix

    # ── precision / quality ───────────────────────────────────────────────────

    @property
    def hdop(self) -> Optional[float]:
        """Horizontal dilution of precision (dimensionless; lower is better)."""
        with self._lock:
            return self._fix.hdop

    @property
    def vdop(self) -> Optional[float]:
        """Vertical dilution of precision."""
        with self._lock:
            return self._fix.vdop

    @property
    def pdop(self) -> Optional[float]:
        """Positional (3D) dilution of precision."""
        with self._lock:
            return self._fix.pdop

    @property
    def satellites_used(self) -> Optional[int]:
        """Number of satellites used in the current fix."""
        with self._lock:
            return self._fix.satellites_used

    @property
    def satellites_visible(self) -> Optional[int]:
        """Total number of satellites visible to the receiver."""
        with self._lock:
            return self._fix.satellites_visible

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "GPSD":
        # Wait up to 2 s for the background thread to establish the TCP
        # connection so callers don't need to poll is_connected themselves.
        deadline = time.monotonic() + 2.0
        while not self._connected and time.monotonic() < deadline:
            time.sleep(0.05)
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        """Signal the background reader to stop and wait for it to exit."""
        self._stop_event.set()
        self._thread.join(timeout=8.0)


# ── helpers ───────────────────────────────────────────────────────────────────

def _opt_float(msg: dict, key: str) -> Optional[float]:
    """Return float(msg[key]) or None if the key is absent or None."""
    v = msg.get(key)
    return None if v is None else float(v)
