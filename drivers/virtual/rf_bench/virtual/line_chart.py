"""
line_chart.py — Virtual Line Chart SCPI driver

Connects to virtual line chart backend via TCP SCPI (default port 5004).
Time-series scrolling line chart with configurable history, auto-scaling,
and threshold zones.

Usage::

    from rf_bench.virtual import VirtualLineChart

    # Basic usage
    with VirtualLineChart("10.1.1.52") as chart:
        chart.set_title("Temperature Monitor")
        chart.set_units("°C")
        chart.set_history_length(200)
        chart.add_value(25.3)
        chart.add_value(25.5)
        print(chart.get_value())  # → 25.5 (most recent)

    # With manual scaling
    with VirtualLineChart("10.1.1.52") as chart:
        chart.set_title("RF Power")
        chart.set_units("dBm")
        chart.set_auto_scale(False)
        chart.set_range(-50, 10)
        chart.set_color("#00ff00")
        chart.add_value(-23.4)

    # MQTT integration
    with VirtualLineChart("10.1.1.52") as chart:
        chart.configure_mqtt("10.1.0.20", "sensors/temperature")
        # Chart now updates automatically when MQTT messages arrive
"""

import socket
import time


class VirtualLineChartError(Exception):
    pass


class VirtualLineChart:
    """Virtual line chart driver (SCPI over TCP)."""

    def __init__(self, host, port=5004, timeout=2.0):
        """Initialize connection to virtual line chart.

        Args:
            host: IP address or hostname
            port: SCPI TCP port (default 5004)
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
            raise VirtualLineChartError(f"Connection failed to {self.host}:{self.port}: {e}")

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
            raise VirtualLineChartError("Not connected")
        try:
            self._sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            raise VirtualLineChartError(f"Write failed: {e}")

    def _query(self, cmd):
        """Send SCPI query and return response."""
        self._write(cmd)
        try:
            response = self._sock.recv(4096).decode().strip()
            return response
        except Exception as e:
            raise VirtualLineChartError(f"Query failed: {e}")

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

    # Measurement commands

    def add_value(self, value):
        """Add a data point to the chart.

        Args:
            value: Data point value
        """
        self._write(f"MEAS:VAL {value}")

    def get_value(self):
        """Query most recent data point.

        Returns:
            float: Most recent value (or 0.0 if no data)
        """
        return float(self._query("MEAS:VAL?"))

    # Configuration commands

    def set_history_length(self, length):
        """Set history length in samples.

        Args:
            length: Number of samples to retain (10-1000, default 100)
        """
        if not (10 <= length <= 1000):
            raise ValueError("History length must be 10-1000")
        self._write(f"CONF:HIST {length}")

    def get_history_length(self):
        """Query history length.

        Returns:
            int: Number of samples retained
        """
        return int(self._query("CONF:HIST?"))

    def set_min(self, min_value):
        """Set Y-axis minimum value.

        Args:
            min_value: Minimum Y value (disables auto-scale for min)
        """
        self._write(f"CONF:MIN {min_value}")

    def get_min(self):
        """Query Y-axis minimum value.

        Returns:
            str: Minimum value or "AUTO"
        """
        return self._query("CONF:MIN?")

    def set_max(self, max_value):
        """Set Y-axis maximum value.

        Args:
            max_value: Maximum Y value (disables auto-scale for max)
        """
        self._write(f"CONF:MAX {max_value}")

    def get_max(self):
        """Query Y-axis maximum value.

        Returns:
            str: Maximum value or "AUTO"
        """
        return self._query("CONF:MAX?")

    def set_range(self, min_value, max_value):
        """Set Y-axis range (convenience method).

        Args:
            min_value: Minimum Y value
            max_value: Maximum Y value
        """
        self.set_min(min_value)
        self.set_max(max_value)

    def set_auto_scale(self, enabled):
        """Enable or disable auto-scaling.

        Args:
            enabled: True to enable auto-scaling, False to disable
        """
        state = "ON" if enabled else "OFF"
        self._write(f"CONF:AUTO {state}")

    def get_auto_scale(self):
        """Query auto-scaling state.

        Returns:
            bool: True if auto-scaling enabled
        """
        return self._query("CONF:AUTO?") == "ON"

    def set_units(self, units):
        """Set display units.

        Args:
            units: Units string (e.g., "dBm", "V", "°C")
        """
        self._write(f"CONF:UNIT {units}")

    def get_units(self):
        """Query display units.

        Returns:
            str: Units string
        """
        return self._query("CONF:UNIT?")

    def set_color(self, color):
        """Set line color.

        Args:
            color: CSS color string (e.g., "#00ff00", "red")
        """
        self._write(f"CONF:COL {color}")

    def get_color(self):
        """Query line color.

        Returns:
            str: CSS color string
        """
        return self._query("CONF:COL?")

    def set_title(self, title):
        """Set chart title.

        Args:
            title: Title string
        """
        self._write(f"CONF:TITLE {title}")

    def get_title(self):
        """Query chart title.

        Returns:
            str: Title string
        """
        return self._query("CONF:TITLE?")

    # MQTT configuration

    def configure_mqtt(self, host, topic):
        """Configure MQTT broker and topic to subscribe.

        Once configured, the chart will automatically update when
        messages arrive on the specified topic. Message payload
        must be a numeric value (int or float as string).

        Args:
            host: MQTT broker hostname or IP
            topic: MQTT topic to subscribe to
        """
        self._write(f"MQTT:CONF {host},{topic}")

    def get_mqtt_config(self):
        """Query MQTT configuration.

        Returns:
            str: "host,topic" or "Not configured"
        """
        return self._query("MQTT:CONF?")

    # Convenience methods

    def configure(self, title, units, min_val=None, max_val=None,
                  color="#00ff00", history=100):
        """Configure all chart parameters at once.

        Args:
            title: Chart title
            units: Display units
            min_val: Y-axis minimum (None for auto)
            max_val: Y-axis maximum (None for auto)
            color: Line color (default green)
            history: History length in samples (default 100)
        """
        self.set_title(title)
        self.set_units(units)
        self.set_history_length(history)
        self.set_color(color)

        if min_val is not None and max_val is not None:
            self.set_auto_scale(False)
            self.set_range(min_val, max_val)
        else:
            self.set_auto_scale(True)

    def stream(self, values, interval=0.1):
        """Stream a sequence of values to the chart.

        Args:
            values: Iterable of values to add
            interval: Delay between updates in seconds
        """
        for value in values:
            self.add_value(value)
            time.sleep(interval)
