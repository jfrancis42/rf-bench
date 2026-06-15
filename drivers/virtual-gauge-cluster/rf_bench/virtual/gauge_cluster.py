"""
gauge_cluster.py — Virtual Gauge Cluster SCPI driver

Connects to virtual gauge cluster backend via TCP SCPI (default port 5025).
Displays 2-4 analog gauges in dashboard layout for real-time monitoring.

Usage::

    from rf_bench.virtual import VirtualGaugeCluster

    # Four-gauge dashboard (voltage, current, power, temperature)
    with VirtualGaugeCluster("10.1.1.52") as cluster:
        cluster.configure_gauge(1, "Voltage", "V", 0, 15, "#00ff00")
        cluster.configure_gauge(2, "Current", "A", 0, 10, "#0088ff")
        cluster.configure_gauge(3, "Power", "W", 0, 150, "#ff8800")
        cluster.configure_gauge(4, "Temperature", "°C", 0, 100, "#ff0000")

        cluster.set_value(1, 13.8)
        cluster.set_value(2, 8.2)
        cluster.set_value(3, 113.2)
        cluster.set_value(4, 45.3)

    # Two-gauge layout
    with VirtualGaugeCluster("10.1.1.52") as cluster:
        cluster.set_layout(2)
        cluster.configure_gauge(1, "Forward", "W", 0, 100, "#00ff00")
        cluster.configure_gauge(2, "Reflected", "W", 0, 20, "#ff0000")
        cluster.set_value(1, 50.2)
        cluster.set_value(2, 3.1)

    # MQTT integration
    with VirtualGaugeCluster("10.1.1.52") as cluster:
        cluster.configure_gauge(1, "Power", "W", 0, 100)
        cluster.configure_mqtt(1, "localhost", "radio/power")
        # Backend subscribes and updates automatically
"""

import socket
import time


class VirtualGaugeClusterError(Exception):
    pass


class VirtualGaugeCluster:
    """Virtual gauge cluster driver (SCPI over TCP)."""

    def __init__(self, host, port=5025, timeout=2.0):
        """Initialize connection to virtual gauge cluster.

        Args:
            host: IP address or hostname
            port: SCPI TCP port (default 5025)
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
            raise VirtualGaugeClusterError(f"Connection failed to {self.host}:{self.port}: {e}")

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
            raise VirtualGaugeClusterError("Not connected")
        try:
            self._sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            raise VirtualGaugeClusterError(f"Write failed: {e}")

    def _query(self, cmd):
        """Send SCPI query and return response."""
        self._write(cmd)
        try:
            response = self._sock.recv(4096).decode().strip()
            return response
        except Exception as e:
            raise VirtualGaugeClusterError(f"Query failed: {e}")

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

    # Layout management

    def set_layout(self, count):
        """Set number of gauges in display.

        Args:
            count: Number of gauges (2 or 4)
        """
        if count not in [2, 4]:
            raise ValueError("Layout must be 2 or 4 gauges")
        self._write(f"CONF:LAYOUT {count}")

    def get_layout(self):
        """Query number of gauges in display.

        Returns:
            int: Number of gauges (2 or 4)
        """
        return int(self._query("CONF:LAYOUT?"))

    # Gauge value control (1-based indexing)

    def set_value(self, index, value):
        """Set gauge value.

        Args:
            index: Gauge index (1-4)
            value: Display value (clamped to min/max range)
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        self._write(f"MEAS{index}:VAL {value}")

    def get_value(self, index):
        """Query gauge value.

        Args:
            index: Gauge index (1-4)

        Returns:
            float: Current display value
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        return float(self._query(f"MEAS{index}:VAL?"))

    # Gauge configuration

    def set_min(self, index, min_val):
        """Set gauge minimum value.

        Args:
            index: Gauge index (1-4)
            min_val: Minimum scale value
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        self._write(f"CONF{index}:MIN {min_val}")

    def get_min(self, index):
        """Query gauge minimum value.

        Args:
            index: Gauge index (1-4)

        Returns:
            float: Minimum scale value
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        return float(self._query(f"CONF{index}:MIN?"))

    def set_max(self, index, max_val):
        """Set gauge maximum value.

        Args:
            index: Gauge index (1-4)
            max_val: Maximum scale value
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        self._write(f"CONF{index}:MAX {max_val}")

    def get_max(self, index):
        """Query gauge maximum value.

        Args:
            index: Gauge index (1-4)

        Returns:
            float: Maximum scale value
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        return float(self._query(f"CONF{index}:MAX?"))

    def set_units(self, index, units):
        """Set gauge display units.

        Args:
            index: Gauge index (1-4)
            units: Units string (e.g. "W", "V", "dBm", "°C")
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        self._write(f"CONF{index}:UNIT {units}")

    def get_units(self, index):
        """Query gauge display units.

        Args:
            index: Gauge index (1-4)

        Returns:
            str: Units string
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        return self._query(f"CONF{index}:UNIT?")

    def set_label(self, index, label):
        """Set gauge label text.

        Args:
            index: Gauge index (1-4)
            label: Label string (e.g. "Voltage", "Power", "Temperature")
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        self._write(f"CONF{index}:LABEL {label}")

    def get_label(self, index):
        """Query gauge label text.

        Args:
            index: Gauge index (1-4)

        Returns:
            str: Label string
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        return self._query(f"CONF{index}:LABEL?")

    def set_color(self, index, color):
        """Set needle color.

        Args:
            index: Gauge index (1-4)
            color: CSS color string (e.g. "#00ff88", "#ff0000", "red")
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        self._write(f"CONF{index}:COL {color}")

    def get_color(self, index):
        """Query needle color.

        Args:
            index: Gauge index (1-4)

        Returns:
            str: CSS color string
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        return self._query(f"CONF{index}:COL?")

    # MQTT integration

    def configure_mqtt(self, index, host, topic):
        """Configure MQTT subscription for gauge.

        Args:
            index: Gauge index (1-4)
            host: MQTT broker hostname/IP
            topic: MQTT topic to subscribe (value published as float)
        """
        if not (1 <= index <= 4):
            raise ValueError("Index must be 1-4")
        self._write(f"MQTT:CONF {index},{host},{topic}")

    def get_mqtt_config(self):
        """Query MQTT configuration for all gauges.

        Returns:
            str: Semicolon-separated config strings (e.g. "1:localhost,radio/power; 2:localhost,radio/voltage")
        """
        return self._query("MQTT:CONF?")

    # Convenience methods

    def configure_gauge(self, index, label, units, min_val, max_val, color="#00ff00"):
        """Configure all gauge parameters at once.

        Args:
            index: Gauge index (1-4)
            label: Label text
            units: Units string
            min_val: Minimum scale value
            max_val: Maximum scale value
            color: Needle color (default green)
        """
        self.set_label(index, label)
        self.set_units(index, units)
        self.set_min(index, min_val)
        self.set_max(index, max_val)
        self.set_color(index, color)

    def update(self, index, value):
        """Update gauge value (same as set_value, shorter name).

        Args:
            index: Gauge index (1-4)
            value: Display value
        """
        self.set_value(index, value)

    def animate(self, index, values, interval=0.1):
        """Animate gauge through a sequence of values.

        Args:
            index: Gauge index (1-4)
            values: Iterable of values to display
            interval: Delay between updates in seconds
        """
        for value in values:
            self.set_value(index, value)
            time.sleep(interval)

    def update_all(self, values):
        """Update all gauge values at once.

        Args:
            values: Dict or list of values (dict keys are 1-based indices)

        Example:
            cluster.update_all({1: 13.8, 2: 8.2, 3: 113.2, 4: 45.3})
            cluster.update_all([13.8, 8.2, 113.2, 45.3])  # 1-indexed
        """
        if isinstance(values, dict):
            for index, value in values.items():
                self.set_value(index, value)
        else:
            for index, value in enumerate(values, start=1):
                self.set_value(index, value)
