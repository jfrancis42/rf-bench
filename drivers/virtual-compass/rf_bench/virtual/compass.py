"""
compass.py — Virtual Compass SCPI driver

Connects to virtual compass backend via TCP SCPI (default port 5033).
Displays directional heading with compass rose, cardinal directions,
and optional customization.

Usage::

    from rf_bench.virtual import VirtualCompass

    # Basic compass display
    with VirtualCompass("10.1.1.52") as compass:
        compass.set_heading(45.5)      # Northeast
        compass.set_title("Aircraft Heading")
        compass.enable_labels()
        compass.enable_rose()
        print(compass.get_heading())   # → 45.5

    # GPS integration
    from rf_bench.gpsd import GPSD

    gps = GPSD()
    compass = VirtualCompass("10.1.1.52")

    compass.set_title("GPS Track")
    compass.set_needle_color("#00ff00")

    while True:
        fix = gps.get_fix()
        if fix.heading is not None:
            compass.set_heading(fix.heading)
        time.sleep(0.5)

    # MQTT integration for remote heading updates
    compass = VirtualCompass("10.1.1.52")
    compass.configure_mqtt("mqtt.example.com", "heading/gps1")
    # Now backend subscribes and updates automatically
"""

import socket


class VirtualCompassError(Exception):
    pass


class VirtualCompass:
    """Virtual compass driver (SCPI over TCP)."""

    def __init__(self, host, port=5033, timeout=2.0):
        """Initialize connection to virtual compass.

        Args:
            host: IP address or hostname
            port: SCPI TCP port (default 5033)
            timeout: Socket timeout in seconds
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = None
        self._connect()

    def _connect(self):
        """Establish TCP connection."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))
        except Exception as e:
            raise VirtualCompassError(f"Connection failed to {self.host}:{self.port}: {e}")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        """Close TCP connection."""
        if self._sock:
            try:
                self._sock.close()
            except:
                pass
            self._sock = None

    def _write(self, cmd):
        """Send SCPI command."""
        if not self._sock:
            raise VirtualCompassError("Not connected")
        try:
            self._sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            raise VirtualCompassError(f"Write failed: {e}")

    def _query(self, cmd):
        """Send SCPI query and return response."""
        self._write(cmd)
        try:
            response = self._sock.recv(4096).decode().strip()
            return response
        except Exception as e:
            raise VirtualCompassError(f"Query failed: {e}")

    # IEEE 488.2 common commands

    def idn(self):
        """Query instrument identification.

        Returns:
            str: Identification string (manufacturer,model,serial,firmware)
        """
        return self._query("*IDN?")

    def reset(self):
        """Reset instrument to default state."""
        self._write("*RST")

    def get_error(self):
        """Query error queue.

        Returns:
            str: Error code and message (e.g. "0,No error")
        """
        return self._query("SYST:ERR?")

    # Heading control

    def set_heading(self, heading):
        """Set compass heading in degrees (0=North, clockwise).

        Args:
            heading: Heading in degrees (0-360, automatically normalized)
                    0/360 = North, 90 = East, 180 = South, 270 = West

        Examples:
            compass.set_heading(0)      # North
            compass.set_heading(45)     # Northeast
            compass.set_heading(90)     # East
            compass.set_heading(180)    # South
            compass.set_heading(270)    # West
            compass.set_heading(365)    # Normalized to 5° (just east of north)
        """
        self._write(f"MEAS:HEAD {heading}")

    def get_heading(self):
        """Query current compass heading.

        Returns:
            float: Current heading in degrees (0-360)
        """
        return float(self._query("MEAS:HEAD?"))

    # Display configuration

    def set_size(self, size):
        """Set compass display size in pixels.

        Args:
            size: Diameter in pixels (200-600, default 350)
        """
        if not (200 <= size <= 600):
            raise ValueError("Size must be 200-600 pixels")
        self._write(f"CONF:SIZE {size}")

    def get_size(self):
        """Query compass display size.

        Returns:
            int: Diameter in pixels
        """
        return int(self._query("CONF:SIZE?"))

    def set_needle_color(self, color):
        """Set needle color.

        Args:
            color: CSS color string (e.g. "#ff0000", "#f00", "red")
        """
        self._write(f'CONF:COL {color}')

    def get_needle_color(self):
        """Query needle color.

        Returns:
            str: CSS color string
        """
        return self._query("CONF:COL?")

    def enable_labels(self):
        """Enable cardinal direction labels (N, E, S, W)."""
        self._write("CONF:LABEL ON")

    def disable_labels(self):
        """Disable cardinal direction labels."""
        self._write("CONF:LABEL OFF")

    def get_labels_enabled(self):
        """Query label state.

        Returns:
            bool: True if labels are enabled
        """
        return self._query("CONF:LABEL?") == "ON"

    def enable_rose(self):
        """Enable compass rose (degree markings)."""
        self._write("CONF:ROSE ON")

    def disable_rose(self):
        """Disable compass rose."""
        self._write("CONF:ROSE OFF")

    def get_rose_enabled(self):
        """Query compass rose state.

        Returns:
            bool: True if rose is enabled
        """
        return self._query("CONF:ROSE?") == "ON"

    def set_title(self, title):
        """Set display title text.

        Args:
            title: Title string (e.g. "Aircraft Heading", "GPS Track")
        """
        self._write(f'CONF:TITLE {title}')

    def get_title(self):
        """Query display title.

        Returns:
            str: Title string
        """
        return self._query("CONF:TITLE?")

    # MQTT integration

    def configure_mqtt(self, host, topic):
        """Configure MQTT broker and topic for automatic heading updates.

        The backend server will subscribe to the specified MQTT topic and
        automatically update the compass heading when messages are received.
        Topic messages should contain a single floating-point heading value.

        Args:
            host: MQTT broker hostname or IP
            topic: MQTT topic to subscribe to (e.g. "heading/gps1")

        Examples:
            # Subscribe to GPS heading updates
            compass.configure_mqtt("mqtt.example.com", "heading/gps1")

            # Subscribe to antenna rotator position
            compass.configure_mqtt("10.1.0.20", "rotator/az")
        """
        self._write(f"MQTT:CONF {host},{topic}")

    def get_mqtt_config(self):
        """Query MQTT configuration.

        Returns:
            str: "host,topic" if configured, "Not configured" otherwise
        """
        return self._query("MQTT:CONF?")

    # Convenience methods

    def configure(self, title="Compass", size=350, needle_color="#ff0000",
                  show_labels=True, show_rose=True):
        """Configure all compass parameters at once.

        Args:
            title: Display title (default "Compass")
            size: Diameter in pixels (default 350)
            needle_color: CSS color string (default "#ff0000" red)
            show_labels: Enable cardinal labels (default True)
            show_rose: Enable compass rose (default True)
        """
        self.set_title(title)
        self.set_size(size)
        self.set_needle_color(needle_color)
        if show_labels:
            self.enable_labels()
        else:
            self.disable_labels()
        if show_rose:
            self.enable_rose()
        else:
            self.disable_rose()

    def update(self, heading):
        """Update compass heading (same as set_heading, shorter name).

        Args:
            heading: Heading in degrees (0-360)
        """
        self.set_heading(heading)

    def point_north(self):
        """Point compass north (0°)."""
        self.set_heading(0)

    def point_east(self):
        """Point compass east (90°)."""
        self.set_heading(90)

    def point_south(self):
        """Point compass south (180°)."""
        self.set_heading(180)

    def point_west(self):
        """Point compass west (270°)."""
        self.set_heading(270)
