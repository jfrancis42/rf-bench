"""
xy_plot.py — Virtual XY Plot SCPI driver

Connects to virtual XY plot backend via TCP SCPI (default port 5025).
Displays scatter or line plots with configurable axes, styling, and grid.

Usage::

    from rf_bench.virtual import VirtualXYPlot

    # Simple scatter plot
    with VirtualXYPlot("10.1.1.52") as plot:
        plot.set_title("Smith Chart")
        plot.set_labels("Resistance", "Reactance")
        plot.add_point(50, 0)
        plot.add_point(75, 25)
        plot.add_point(100, 50)

    # Line plot with explicit axis ranges
    with VirtualXYPlot("10.1.1.52") as plot:
        plot.set_title("Antenna Pattern")
        plot.set_labels("Azimuth (deg)", "Gain (dBi)")
        plot.set_ranges(x_min=0, x_max=360, y_min=-20, y_max=10)
        plot.set_style("LINE")
        plot.set_color("#00ff00")

        for angle in range(0, 361, 10):
            gain = compute_gain(angle)
            plot.add_point(angle, gain)

    # S-parameter Smith chart
    with VirtualXYPlot("10.1.1.52") as plot:
        plot.configure_smith_chart()

        for freq in freqs:
            s11_real, s11_imag = measure_s11(freq)
            plot.add_point(s11_real, s11_imag)
"""

import socket


class VirtualXYPlotError(Exception):
    pass


class VirtualXYPlot:
    """Virtual XY plot driver (SCPI over TCP)."""

    def __init__(self, host, port=5025, timeout=2.0):
        """Initialize connection to virtual XY plot.

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
            raise VirtualXYPlotError(f"Connection failed to {self.host}:{self.port}: {e}")

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
            raise VirtualXYPlotError("Not connected")
        try:
            self._sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            raise VirtualXYPlotError(f"Write failed: {e}")

    def _query(self, cmd):
        """Send SCPI query and return response."""
        self._write(cmd)
        try:
            response = self._sock.recv(4096).decode().strip()
            return response
        except Exception as e:
            raise VirtualXYPlotError(f"Query failed: {e}")

    # IEEE 488.2 common commands

    def idn(self):
        """Query instrument identification.

        Returns:
            str: Identification string (manufacturer,model,serial,firmware)
        """
        return self._query("*IDN?")

    def reset(self):
        """Reset instrument to default state (clears all data points)."""
        self._write("*RST")

    def get_error(self):
        """Query error queue.

        Returns:
            str: Error code and message (e.g. "0,No error")
        """
        return self._query("SYST:ERR?")

    # Data point management

    def add_point(self, x, y):
        """Add XY data point to plot.

        Args:
            x: X-coordinate value
            y: Y-coordinate value
        """
        self._write(f"MEAS:XY {x},{y}")

    def add_points(self, points):
        """Add multiple XY data points.

        Args:
            points: Iterable of (x, y) tuples
        """
        for x, y in points:
            self.add_point(x, y)

    def get_point_count(self):
        """Query number of data points.

        Returns:
            int: Number of points in plot
        """
        return int(self._query("MEAS:XY?"))

    def clear(self):
        """Clear all data points from plot."""
        self._write("MEAS:CLEAR")

    # Axis range configuration

    def set_x_min(self, value):
        """Set X-axis minimum value.

        Args:
            value: Minimum X value (or None for auto)
        """
        self._write(f"CONF:XMIN {value}")

    def get_x_min(self):
        """Query X-axis minimum value.

        Returns:
            float or str: Minimum X value, or "AUTO" if auto-ranging
        """
        result = self._query("CONF:XMIN?")
        return result if result == "AUTO" else float(result)

    def set_x_max(self, value):
        """Set X-axis maximum value.

        Args:
            value: Maximum X value (or None for auto)
        """
        self._write(f"CONF:XMAX {value}")

    def get_x_max(self):
        """Query X-axis maximum value.

        Returns:
            float or str: Maximum X value, or "AUTO" if auto-ranging
        """
        result = self._query("CONF:XMAX?")
        return result if result == "AUTO" else float(result)

    def set_y_min(self, value):
        """Set Y-axis minimum value.

        Args:
            value: Minimum Y value (or None for auto)
        """
        self._write(f"CONF:YMIN {value}")

    def get_y_min(self):
        """Query Y-axis minimum value.

        Returns:
            float or str: Minimum Y value, or "AUTO" if auto-ranging
        """
        result = self._query("CONF:YMIN?")
        return result if result == "AUTO" else float(result)

    def set_y_max(self, value):
        """Set Y-axis maximum value.

        Args:
            value: Maximum Y value (or None for auto)
        """
        self._write(f"CONF:YMAX {value}")

    def get_y_max(self):
        """Query Y-axis maximum value.

        Returns:
            float or str: Maximum Y value, or "AUTO" if auto-ranging
        """
        result = self._query("CONF:YMAX?")
        return result if result == "AUTO" else float(result)

    def set_ranges(self, x_min=None, x_max=None, y_min=None, y_max=None):
        """Set all axis ranges at once.

        Args:
            x_min: Minimum X value (None for auto)
            x_max: Maximum X value (None for auto)
            y_min: Minimum Y value (None for auto)
            y_max: Maximum Y value (None for auto)
        """
        if x_min is not None:
            self.set_x_min(x_min)
        if x_max is not None:
            self.set_x_max(x_max)
        if y_min is not None:
            self.set_y_min(y_min)
        if y_max is not None:
            self.set_y_max(y_max)

    # Label configuration

    def set_x_label(self, label):
        """Set X-axis label.

        Args:
            label: X-axis label text
        """
        self._write(f"CONF:XLABEL {label}")

    def get_x_label(self):
        """Query X-axis label.

        Returns:
            str: X-axis label text
        """
        return self._query("CONF:XLABEL?")

    def set_y_label(self, label):
        """Set Y-axis label.

        Args:
            label: Y-axis label text
        """
        self._write(f"CONF:YLABEL {label}")

    def get_y_label(self):
        """Query Y-axis label.

        Returns:
            str: Y-axis label text
        """
        return self._query("CONF:YLABEL?")

    def set_labels(self, x_label, y_label):
        """Set both axis labels.

        Args:
            x_label: X-axis label text
            y_label: Y-axis label text
        """
        self.set_x_label(x_label)
        self.set_y_label(y_label)

    def set_title(self, title):
        """Set plot title.

        Args:
            title: Plot title text
        """
        self._write(f"CONF:TITLE {title}")

    def get_title(self):
        """Query plot title.

        Returns:
            str: Plot title text
        """
        return self._query("CONF:TITLE?")

    # Style configuration

    def set_style(self, style):
        """Set plot style.

        Args:
            style: "SCATTER" or "LINE"
        """
        if style.upper() not in ["SCATTER", "LINE"]:
            raise ValueError("Style must be SCATTER or LINE")
        self._write(f"CONF:STYLE {style.upper()}")

    def get_style(self):
        """Query plot style.

        Returns:
            str: "SCATTER" or "LINE"
        """
        return self._query("CONF:STYLE?")

    def set_color(self, color):
        """Set point/line color.

        Args:
            color: CSS color string (e.g. "#00ff00", "#0f0")
        """
        if not color.startswith('#'):
            raise ValueError("Color must be hex format (#RRGGBB or #RGB)")
        self._write(f"CONF:COL {color}")

    def get_color(self):
        """Query point/line color.

        Returns:
            str: CSS color string
        """
        return self._query("CONF:COL?")

    # MQTT configuration

    def configure_mqtt(self, host, topic):
        """Configure MQTT broker for live data streaming.

        Args:
            host: MQTT broker hostname/IP
            topic: MQTT topic to subscribe (expects "x,y" CSV messages)
        """
        self._write(f"MQTT:CONF {host},{topic}")

    def get_mqtt_config(self):
        """Query MQTT configuration.

        Returns:
            str: MQTT configuration string "host,topic" or "Not configured"
        """
        return self._query("MQTT:CONF?")

    # Convenience methods

    def configure(self, title, x_label, y_label, style="SCATTER",
                  color="#00ff00", x_min=None, x_max=None, y_min=None, y_max=None):
        """Configure all plot parameters at once.

        Args:
            title: Plot title
            x_label: X-axis label
            y_label: Y-axis label
            style: "SCATTER" or "LINE" (default SCATTER)
            color: Point/line color (default green)
            x_min: X-axis minimum (None for auto)
            x_max: X-axis maximum (None for auto)
            y_min: Y-axis minimum (None for auto)
            y_max: Y-axis maximum (None for auto)
        """
        self.set_title(title)
        self.set_labels(x_label, y_label)
        self.set_style(style)
        self.set_color(color)
        self.set_ranges(x_min, x_max, y_min, y_max)

    def configure_smith_chart(self, title="Smith Chart"):
        """Configure plot for Smith chart display.

        Args:
            title: Chart title (default "Smith Chart")
        """
        self.configure(
            title=title,
            x_label="Resistance",
            y_label="Reactance",
            style="SCATTER",
            color="#00ff00",
            x_min=-1.2,
            x_max=1.2,
            y_min=-1.2,
            y_max=1.2
        )

    def configure_polar(self, title="Polar Plot", r_max=1.0):
        """Configure plot for polar display (converts to Cartesian internally).

        Args:
            title: Plot title (default "Polar Plot")
            r_max: Maximum radius (default 1.0)
        """
        self.configure(
            title=title,
            x_label="X",
            y_label="Y",
            style="LINE",
            color="#00ff00",
            x_min=-r_max,
            x_max=r_max,
            y_min=-r_max,
            y_max=r_max
        )

    def add_polar_point(self, angle_deg, radius):
        """Add point in polar coordinates (converted to Cartesian).

        Args:
            angle_deg: Angle in degrees (0 = east, counterclockwise)
            radius: Distance from origin
        """
        import math
        angle_rad = math.radians(angle_deg)
        x = radius * math.cos(angle_rad)
        y = radius * math.sin(angle_rad)
        self.add_point(x, y)

    def plot_function(self, func, x_min, x_max, num_points=100):
        """Plot a mathematical function y = f(x).

        Args:
            func: Callable that takes x and returns y
            x_min: Minimum X value
            x_max: Maximum X value
            num_points: Number of points to sample (default 100)
        """
        import numpy as np
        x_values = np.linspace(x_min, x_max, num_points)
        for x in x_values:
            y = func(x)
            self.add_point(x, y)
