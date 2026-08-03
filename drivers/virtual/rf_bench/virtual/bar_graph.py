"""
bar_graph.py — Virtual Bar Graph SCPI driver

Connects to virtual bar graph backend via TCP SCPI (default port 5025).
Single bar graph instance per backend (no multi-instance support).

Usage::

    from rf_bench.virtual import VirtualBarGraph

    # Basic usage
    with VirtualBarGraph("10.1.1.52") as bar:
        bar.set_value(45.3)
        bar.set_units("dB")
        bar.set_range(min_val=0, max_val=100)
        bar.set_orientation("VERT")
        print(bar.get_value())  # → 45.3

    # Full configuration
    with VirtualBarGraph("10.1.1.52") as bar:
        bar.configure(
            min_val=0,
            max_val=100,
            units="W",
            orientation="HOR",
            color="#00ff00",
            threshold_yellow=70,
            threshold_red=90
        )
        bar.set_value(85.2)
"""

import socket
import time
from typing import Optional


class VirtualBarGraphError(Exception):
    """Exception raised by VirtualBarGraph driver."""
    pass


class VirtualBarGraph:
    """Virtual bar graph driver (SCPI over TCP)."""

    def __init__(self, host: str, port: int = 5025, timeout: float = 2.0):
        """Initialize connection to virtual bar graph.

        Args:
            host: IP address or hostname
            port: SCPI TCP port (default 5025)
            timeout: Socket timeout in seconds
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._connect()

    def _connect(self) -> None:
        """Establish TCP connection."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))
        except Exception as e:
            raise VirtualBarGraphError(f"Connection failed to {self.host}:{self.port}: {e}")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        """Close TCP connection."""
        if self._sock:
            try:
                self._sock.close()
            except:
                pass
            self._sock = None

    def _write(self, cmd: str) -> None:
        """Send SCPI command."""
        if not self._sock:
            raise VirtualBarGraphError("Not connected")
        try:
            self._sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            raise VirtualBarGraphError(f"Write failed: {e}")

    def _query(self, cmd: str) -> str:
        """Send SCPI query and return response."""
        self._write(cmd)
        try:
            response = self._sock.recv(4096).decode().strip()
            return response
        except Exception as e:
            raise VirtualBarGraphError(f"Query failed: {e}")

    # IEEE 488.2 common commands

    def idn(self) -> str:
        """Query instrument identification.

        Returns:
            str: Identification string (manufacturer,model,serial,firmware)
        """
        return self._query("*IDN?")

    def reset(self) -> None:
        """Reset instrument to default state."""
        self._write("*RST")

    def get_error(self) -> str:
        """Query error queue.

        Returns:
            str: Error code and message (e.g. "0,No error")
        """
        return self._query("SYST:ERR?")

    # Bar value control

    def set_value(self, value: float) -> None:
        """Set bar graph value.

        Args:
            value: Display value (clamped to min/max range)
        """
        self._write(f"MEAS:VAL {value}")

    def get_value(self) -> float:
        """Query bar graph value.

        Returns:
            float: Current display value
        """
        return float(self._query("MEAS:VAL?"))

    # Bar configuration

    def set_range(self, min_val: float, max_val: float) -> None:
        """Set bar graph scale range.

        Args:
            min_val: Minimum scale value
            max_val: Maximum scale value
        """
        self._write(f"CONF:MIN {min_val}")
        self._write(f"CONF:MAX {max_val}")

    def set_min(self, min_val: float) -> None:
        """Set bar graph minimum value.

        Args:
            min_val: Minimum scale value
        """
        self._write(f"CONF:MIN {min_val}")

    def get_min(self) -> float:
        """Query bar graph minimum value.

        Returns:
            float: Minimum scale value
        """
        return float(self._query("CONF:MIN?"))

    def set_max(self, max_val: float) -> None:
        """Set bar graph maximum value.

        Args:
            max_val: Maximum scale value
        """
        self._write(f"CONF:MAX {max_val}")

    def get_max(self) -> float:
        """Query bar graph maximum value.

        Returns:
            float: Maximum scale value
        """
        return float(self._query("CONF:MAX?"))

    def set_orientation(self, orientation: str) -> None:
        """Set bar graph orientation.

        Args:
            orientation: "HOR" (horizontal) or "VERT" (vertical)
        """
        if orientation.upper() not in ["HOR", "VERT"]:
            raise ValueError("Orientation must be HOR or VERT")
        self._write(f"CONF:ORIENT {orientation.upper()}")

    def get_orientation(self) -> str:
        """Query bar graph orientation.

        Returns:
            str: "HOR" or "VERT"
        """
        return self._query("CONF:ORIENT?")

    def set_units(self, units: str) -> None:
        """Set bar graph display units.

        Args:
            units: Units string (e.g. "W", "V", "dBm", "%")
        """
        self._write(f"CONF:UNIT {units}")

    def get_units(self) -> str:
        """Query bar graph display units.

        Returns:
            str: Units string
        """
        return self._query("CONF:UNIT?")

    def set_color(self, color: str) -> None:
        """Set bar color.

        Args:
            color: CSS color string (e.g. "#00ff00", "red")
        """
        self._write(f"CONF:COL {color}")

    def get_color(self) -> str:
        """Query bar color.

        Returns:
            str: CSS color string
        """
        return self._query("CONF:COL?")

    def set_thresholds(self, yellow: float, red: float) -> None:
        """Set bar graph color thresholds.

        Args:
            yellow: Yellow threshold value
            red: Red threshold value
        """
        self._write(f"CONF:THRES {yellow},{red}")

    def get_thresholds(self) -> tuple[float, float]:
        """Query bar graph color thresholds.

        Returns:
            tuple[float, float]: (yellow_threshold, red_threshold)
        """
        response = self._query("CONF:THRES?")
        parts = response.split(',')
        return (float(parts[0]), float(parts[1]))

    # Convenience methods

    def configure(
        self,
        min_val: float,
        max_val: float,
        units: str = "",
        orientation: str = "VERT",
        color: str = "#00ff00",
        threshold_yellow: Optional[float] = None,
        threshold_red: Optional[float] = None
    ) -> None:
        """Configure all bar graph parameters at once.

        Args:
            min_val: Minimum scale value
            max_val: Maximum scale value
            units: Units string (default "")
            orientation: "HOR" or "VERT" (default "VERT")
            color: Bar color (default green)
            threshold_yellow: Yellow threshold value (optional)
            threshold_red: Red threshold value (optional)
        """
        self.set_range(min_val, max_val)
        self.set_units(units)
        self.set_orientation(orientation)
        self.set_color(color)
        if threshold_yellow is not None and threshold_red is not None:
            self.set_thresholds(threshold_yellow, threshold_red)

    def update(self, value: float) -> None:
        """Update bar graph value (same as set_value, shorter name).

        Args:
            value: Display value
        """
        self.set_value(value)

    def animate(self, values, interval: float = 0.1) -> None:
        """Animate bar graph through a sequence of values.

        Args:
            values: Iterable of values to display
            interval: Delay between updates in seconds
        """
        for value in values:
            self.set_value(value)
            time.sleep(interval)
