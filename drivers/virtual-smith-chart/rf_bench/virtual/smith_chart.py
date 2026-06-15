"""
Virtual Smith Chart SCPI driver

Python client for controlling a Virtual Smith Chart instrument via SCPI-over-TCP.
Provides methods for plotting complex impedance data, setting reference impedance,
managing multiple traces, and displaying SWR circles.

Author: Jeff Francis (N0GQ) <gjfrancis@protonmail.com>
License: GPL-3.0-or-later
"""

import socket
import time
import math
import cmath
from typing import Optional, Tuple


class SmithChartError(Exception):
    """Base exception for Smith Chart errors"""
    pass


class SmithChartConnectionError(SmithChartError):
    """Connection-related errors"""
    pass


class SmithChartCommandError(SmithChartError):
    """SCPI command errors"""
    pass


class VirtualSmithChart:
    """
    Virtual Smith Chart SCPI driver

    Controls a virtual Smith chart instrument for complex impedance visualization.
    Supports multiple traces, frequency markers, SWR circles, and MQTT integration.

    Example:
        with VirtualSmithChart("10.1.1.52") as chart:
            chart.set_z0(50)
            chart.set_trace(1)
            chart.add_point(0.8, 0.5)
            chart.set_swr(2.0)
    """

    def __init__(self, host: str, port: int = 5025, timeout: float = 2.0):
        """
        Initialize Smith Chart driver

        Args:
            host: Hostname or IP address of instrument
            port: SCPI TCP port (default: 5025)
            timeout: Socket timeout in seconds (default: 2.0)
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._connect()

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, *args):
        """Context manager exit"""
        self.close()

    def _connect(self):
        """Establish TCP connection"""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))
        except socket.error as e:
            raise SmithChartConnectionError(f"Failed to connect to {self.host}:{self.port}: {e}")

    def _write(self, cmd: str):
        """Send SCPI command"""
        if not self._sock:
            raise SmithChartConnectionError("Not connected")

        try:
            self._sock.sendall(f"{cmd}\n".encode('utf-8'))
        except socket.error as e:
            raise SmithChartConnectionError(f"Write failed: {e}")

    def _query(self, cmd: str) -> str:
        """Send SCPI query and read response"""
        self._write(cmd)

        try:
            response = self._sock.recv(4096).decode('utf-8').strip()
            return response
        except socket.timeout:
            raise SmithChartConnectionError(f"Query timeout: {cmd}")
        except socket.error as e:
            raise SmithChartConnectionError(f"Query failed: {e}")

    def close(self):
        """Close connection"""
        if self._sock:
            self._sock.close()
            self._sock = None

    # IEEE 488.2 common commands

    def idn(self) -> str:
        """Query instrument identification"""
        return self._query("*IDN?")

    def reset(self):
        """Reset instrument to defaults"""
        self._write("*RST")
        time.sleep(0.1)

    def get_error(self) -> str:
        """Query error queue"""
        return self._query("SYST:ERR?")

    # Impedance point commands

    def add_point(self, real: float, imag: float):
        """
        Add impedance point (rectangular coordinates, normalized)

        Args:
            real: Real part of normalized impedance (Z/Z0)
            imag: Imaginary part of normalized impedance

        Example:
            chart.add_point(0.8, 0.5)  # Z = 0.8+0.5j (40+25j Ω @ Z0=50)
        """
        self._write(f"SMIT:POIN {real},{imag}")

    def add_point_polar(self, magnitude: float, angle_deg: float):
        """
        Add impedance point (polar coordinates, normalized)

        Args:
            magnitude: Magnitude of normalized impedance
            angle_deg: Phase angle in degrees

        Example:
            chart.add_point_polar(1.2, 45)  # Z = 1.2∠45°
        """
        self._write(f"SMIT:POIN:POL {magnitude},{angle_deg}")

    def add_point_with_freq(self, real: float, imag: float, freq_hz: float):
        """
        Add impedance point with frequency marker

        Args:
            real: Real part of normalized impedance
            imag: Imaginary part of normalized impedance
            freq_hz: Frequency in Hz

        Example:
            chart.add_point_with_freq(0.8, 0.5, 14.2e6)  # Label "14.2 MHz"
        """
        self._write(f"SMIT:MARK:FREQ {freq_hz}")
        self._write(f"SMIT:POIN {real},{imag}")

    def get_point(self) -> Tuple[float, float]:
        """
        Query most recent impedance point

        Returns:
            Tuple of (real, imag)
        """
        response = self._query("SMIT:POIN?")
        parts = response.split(',')
        return float(parts[0]), float(parts[1])

    # Configuration commands

    def set_z0(self, ohms: float):
        """
        Set reference impedance

        Args:
            ohms: Reference impedance in ohms (must be > 0)

        Example:
            chart.set_z0(75)  # 75 Ω reference
        """
        if ohms <= 0:
            raise ValueError("Reference impedance must be > 0")
        self._write(f"SMIT:Z0 {ohms}")

    def get_z0(self) -> float:
        """Query reference impedance"""
        return float(self._query("SMIT:Z0?"))

    def set_trace(self, trace_id: int):
        """
        Select active trace (1-4)

        Args:
            trace_id: Trace number (1, 2, 3, or 4)
        """
        if trace_id not in [1, 2, 3, 4]:
            raise ValueError("Trace ID must be 1, 2, 3, or 4")
        self._write(f"SMIT:TRAC {trace_id}")

    def get_trace(self) -> int:
        """Query active trace number"""
        return int(self._query("SMIT:TRAC?"))

    def clear_trace(self, trace_id: Optional[int] = None):
        """
        Clear trace data

        Args:
            trace_id: Trace to clear (None = current active trace)
        """
        if trace_id is not None:
            current = self.get_trace()
            self.set_trace(trace_id)
            self._write("SMIT:TRAC:CLE")
            self.set_trace(current)
        else:
            self._write("SMIT:TRAC:CLE")

    def clear_all_traces(self):
        """Clear all traces"""
        self._write("SMIT:TRAC:ALL:CLE")

    def set_trace_color(self, trace_id: int, color: str):
        """
        Set trace color

        Args:
            trace_id: Trace number (1-4)
            color: Hex color string (e.g., "#00ff00")

        Example:
            chart.set_trace_color(1, "#ff0000")  # Red
        """
        if not color.startswith('#') or len(color) != 7:
            raise ValueError("Color must be hex format: #rrggbb")

        current = self.get_trace()
        self.set_trace(trace_id)
        self._write(f"SMIT:TRAC:COL {color}")
        self.set_trace(current)

    def get_trace_color(self, trace_id: int) -> str:
        """Query trace color"""
        current = self.get_trace()
        self.set_trace(trace_id)
        color = self._query("SMIT:TRAC:COL?")
        self.set_trace(current)
        return color

    def set_trace_label(self, trace_id: int, label: str):
        """
        Set trace label

        Args:
            trace_id: Trace number (1-4)
            label: Trace label text
        """
        current = self.get_trace()
        self.set_trace(trace_id)
        self._write(f"SMIT:TRAC:LAB {label}")
        self.set_trace(current)

    def get_trace_label(self, trace_id: int) -> str:
        """Query trace label"""
        current = self.get_trace()
        self.set_trace(trace_id)
        label = self._query("SMIT:TRAC:LAB?")
        self.set_trace(current)
        return label

    # Display commands

    def set_swr(self, swr: float):
        """
        Draw SWR circle

        Args:
            swr: SWR ratio (1.0-10.0)

        Example:
            chart.set_swr(2.0)  # Draw SWR=2.0 circle
        """
        if swr < 1.0 or swr > 10.0:
            raise ValueError("SWR must be between 1.0 and 10.0")
        self._write(f"SMIT:SWR {swr}")

    def get_swr(self) -> Optional[float]:
        """Query SWR circle value (None if not set)"""
        response = self._query("SMIT:SWR?")
        swr = float(response)
        return swr if swr > 0 else None

    def set_mode(self, mode: str):
        """
        Set impedance/admittance mode

        Args:
            mode: "IMPED" or "ADMIT"
        """
        mode = mode.upper()
        if mode not in ['IMPED', 'ADMIT']:
            raise ValueError("Mode must be 'IMPED' or 'ADMIT'")
        self._write(f"SMIT:MODE {mode}")

    def get_mode(self) -> str:
        """Query current mode"""
        return self._query("SMIT:MODE?")

    def set_grid(self, enabled: bool):
        """Enable/disable grid display"""
        self._write(f"SMIT:GRID {'ON' if enabled else 'OFF'}")

    def get_grid(self) -> bool:
        """Query grid state"""
        return self._query("SMIT:GRID?") == "ON"

    def set_title(self, title: str):
        """Set chart title"""
        self._write(f"CONF:TITLE {title}")

    def get_title(self) -> str:
        """Query chart title"""
        return self._query("CONF:TITLE?")

    # MQTT commands

    def configure_mqtt(self, host: str, topic: str):
        """
        Configure MQTT broker and topic

        Args:
            host: MQTT broker hostname/IP
            topic: MQTT topic to subscribe

        Example:
            chart.configure_mqtt("10.1.0.20", "bench/vna/impedance")
        """
        self._write(f"MQTT:CONF {host},{topic}")

    def get_mqtt_config(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Query MQTT configuration

        Returns:
            Tuple of (host, topic) or (None, None) if not configured
        """
        response = self._query("MQTT:CONF?")
        if response == "NOT_CONFIGURED":
            return None, None
        parts = response.split(',')
        return parts[0], parts[1]

    # Utility methods

    def configure(self, z0: float = 50, title: str = "Smith Chart",
                  trace: int = 1, trace_label: str = "Trace 1",
                  trace_color: str = "#00ff00"):
        """
        Configure chart with common settings

        Args:
            z0: Reference impedance (default: 50 Ω)
            title: Chart title
            trace: Active trace number
            trace_label: Trace label text
            trace_color: Trace color (hex)

        Example:
            chart.configure(z0=75, title="Antenna Test", trace=1,
                          trace_label="40m Dipole", trace_color="#ff0000")
        """
        self.set_z0(z0)
        self.set_title(title)
        self.set_trace(trace)
        self.set_trace_label(trace, trace_label)
        self.set_trace_color(trace, trace_color)

    @staticmethod
    def ohms_to_normalized(z_ohms: complex, z0: float = 50.0) -> Tuple[float, float]:
        """
        Convert absolute impedance to normalized impedance

        Args:
            z_ohms: Impedance in ohms (complex)
            z0: Reference impedance (default: 50 Ω)

        Returns:
            Tuple of (real, imag) normalized impedance

        Example:
            real, imag = VirtualSmithChart.ohms_to_normalized(40+25j, 50)
            # Returns (0.8, 0.5)
        """
        z_norm = z_ohms / z0
        return z_norm.real, z_norm.imag

    @staticmethod
    def reflection_to_impedance(gamma: complex) -> Tuple[float, float]:
        """
        Convert reflection coefficient to normalized impedance

        Args:
            gamma: Reflection coefficient (complex)

        Returns:
            Tuple of (real, imag) normalized impedance

        Example:
            real, imag = VirtualSmithChart.reflection_to_impedance(0.2+0.1j)
        """
        z_norm = (1 + gamma) / (1 - gamma)
        return z_norm.real, z_norm.imag

    @staticmethod
    def impedance_to_reflection(z_norm: complex) -> complex:
        """
        Convert normalized impedance to reflection coefficient

        Args:
            z_norm: Normalized impedance (complex)

        Returns:
            Reflection coefficient (complex)
        """
        return (z_norm - 1) / (z_norm + 1)

    @staticmethod
    def swr_from_reflection(gamma: complex) -> float:
        """
        Calculate SWR from reflection coefficient

        Args:
            gamma: Reflection coefficient

        Returns:
            SWR ratio
        """
        mag = abs(gamma)
        if mag >= 1.0:
            return float('inf')
        return (1 + mag) / (1 - mag)
