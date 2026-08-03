"""
waterfall.py — Virtual Waterfall Display SCPI driver

Connects to virtual waterfall backend via TCP SCPI (default port 5032).
Displays frequency-domain spectrum data as a scrolling color-coded waterfall.

Usage::

    from rf_bench.virtual import VirtualWaterfall

    # Basic waterfall display
    with VirtualWaterfall("10.1.1.52") as waterfall:
        waterfall.set_freq_range(144.0, 148.0)  # 2m band, MHz
        waterfall.set_power_range(-100, -50)    # dBm
        waterfall.set_title("2m Band Monitor")

        # Add spectrum trace (100 points)
        spectrum = [-80, -75, -70, -65, -60, ...]
        waterfall.add_spectrum(spectrum)

    # With MQTT integration
    with VirtualWaterfall("10.1.1.52") as waterfall:
        waterfall.configure_mqtt("mqtt.local", "spectrum/rtlsdr")
        # Waterfall updates automatically from MQTT messages
"""

import socket
import time
from typing import List, Optional


class VirtualWaterfallError(Exception):
    pass


class VirtualWaterfall:
    """Virtual waterfall display driver (SCPI over TCP)."""

    def __init__(self, host, port=5007, timeout=2.0):
        """Initialize connection to virtual waterfall display.

        Args:
            host: IP address or hostname
            port: SCPI TCP port (default 5007)
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
            raise VirtualWaterfallError(f"Connection failed to {self.host}:{self.port}: {e}")

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
            raise VirtualWaterfallError("Not connected")
        try:
            self._sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            raise VirtualWaterfallError(f"Write failed: {e}")

    def _query(self, cmd):
        """Send SCPI query and return response."""
        self._write(cmd)
        try:
            response = self._sock.recv(4096).decode().strip()
            return response
        except Exception as e:
            raise VirtualWaterfallError(f"Query failed: {e}")

    # IEEE 488.2 common commands

    def idn(self):
        """Query instrument identification.

        Returns:
            str: Identification string (manufacturer,model,serial,firmware)
        """
        return self._query("*IDN?")

    def reset(self):
        """Reset instrument to default state and clear waterfall."""
        self._write("*RST")

    def get_error(self):
        """Query error queue.

        Returns:
            str: Error code and message (e.g. "0,No error")
        """
        return self._query("SYST:ERR?")

    # Spectrum measurement commands

    def add_spectrum(self, spectrum: List[float]):
        """Add a spectrum trace to the waterfall.

        Args:
            spectrum: List of power values (dBm) across frequency bins
        """
        csv_data = ','.join(str(x) for x in spectrum)
        self._write(f"MEAS:SPEC {csv_data}")

    def get_trace_count(self):
        """Query number of traces in waterfall history.

        Returns:
            int: Number of traces currently stored
        """
        return int(self._query("MEAS:SPEC?"))

    def clear(self):
        """Clear all traces from waterfall history."""
        self._write("MEAS:CLEAR")

    # Configuration commands

    def set_history_depth(self, depth: int):
        """Set waterfall history depth (number of traces to display).

        Args:
            depth: Number of traces (10-500, default 100)
        """
        if not (10 <= depth <= 500):
            raise ValueError("History depth must be 10-500")
        self._write(f"CONF:HIST {depth}")

    def get_history_depth(self):
        """Query waterfall history depth.

        Returns:
            int: Number of traces in history (10-500)
        """
        return int(self._query("CONF:HIST?"))

    def set_freq_start(self, freq_mhz: float):
        """Set start frequency for waterfall X-axis.

        Args:
            freq_mhz: Start frequency in MHz
        """
        self._write(f"CONF:FSTART {freq_mhz}")

    def get_freq_start(self):
        """Query start frequency.

        Returns:
            float: Start frequency in MHz
        """
        return float(self._query("CONF:FSTART?"))

    def set_freq_stop(self, freq_mhz: float):
        """Set stop frequency for waterfall X-axis.

        Args:
            freq_mhz: Stop frequency in MHz
        """
        self._write(f"CONF:FSTOP {freq_mhz}")

    def get_freq_stop(self):
        """Query stop frequency.

        Returns:
            float: Stop frequency in MHz
        """
        return float(self._query("CONF:FSTOP?"))

    def set_freq_range(self, start_mhz: float, stop_mhz: float):
        """Set frequency range for waterfall X-axis.

        Args:
            start_mhz: Start frequency in MHz
            stop_mhz: Stop frequency in MHz
        """
        self.set_freq_start(start_mhz)
        self.set_freq_stop(stop_mhz)

    def get_freq_range(self):
        """Query frequency range.

        Returns:
            tuple: (start_mhz, stop_mhz)
        """
        return (self.get_freq_start(), self.get_freq_stop())

    def set_power_min(self, power_dbm: float):
        """Set minimum power for waterfall color scale.

        Args:
            power_dbm: Minimum power in dBm (default -100)
        """
        self._write(f"CONF:PMIN {power_dbm}")

    def get_power_min(self):
        """Query minimum power.

        Returns:
            float: Minimum power in dBm
        """
        return float(self._query("CONF:PMIN?"))

    def set_power_max(self, power_dbm: float):
        """Set maximum power for waterfall color scale.

        Args:
            power_dbm: Maximum power in dBm (default -20)
        """
        self._write(f"CONF:PMAX {power_dbm}")

    def get_power_max(self):
        """Query maximum power.

        Returns:
            float: Maximum power in dBm
        """
        return float(self._query("CONF:PMAX?"))

    def set_power_range(self, min_dbm: float, max_dbm: float):
        """Set power range for waterfall color scale.

        Args:
            min_dbm: Minimum power in dBm
            max_dbm: Maximum power in dBm
        """
        self.set_power_min(min_dbm)
        self.set_power_max(max_dbm)

    def get_power_range(self):
        """Query power range.

        Returns:
            tuple: (min_dbm, max_dbm)
        """
        return (self.get_power_min(), self.get_power_max())

    def set_title(self, title: str):
        """Set waterfall display title.

        Args:
            title: Title string
        """
        self._write(f"CONF:TITLE {title}")

    def get_title(self):
        """Query waterfall title.

        Returns:
            str: Title string
        """
        return self._query("CONF:TITLE?")

    # MQTT configuration

    def configure_mqtt(self, host: str, topic: str):
        """Configure MQTT broker and topic for automatic spectrum updates.

        The backend subscribes to the specified MQTT topic and expects
        messages containing comma-separated power values (CSV format).

        Args:
            host: MQTT broker hostname or IP
            topic: MQTT topic to subscribe to (e.g. "spectrum/rtlsdr")
        """
        self._write(f"MQTT:CONF {host},{topic}")

    def get_mqtt_config(self):
        """Query MQTT configuration.

        Returns:
            str: "host,topic" or "Not configured"
        """
        return self._query("MQTT:CONF?")

    # Convenience methods

    def configure(self, freq_start: float, freq_stop: float,
                  power_min: float, power_max: float,
                  title: str = "Waterfall",
                  history_depth: int = 100):
        """Configure all waterfall parameters at once.

        Args:
            freq_start: Start frequency in MHz
            freq_stop: Stop frequency in MHz
            power_min: Minimum power in dBm
            power_max: Maximum power in dBm
            title: Display title (default "Waterfall")
            history_depth: Number of traces to display (default 100)
        """
        self.set_freq_range(freq_start, freq_stop)
        self.set_power_range(power_min, power_max)
        self.set_title(title)
        self.set_history_depth(history_depth)

    def stream(self, spectrum_generator, interval: float = 0.1):
        """Stream spectrum traces from a generator.

        Args:
            spectrum_generator: Iterable that yields spectrum arrays
            interval: Delay between traces in seconds
        """
        for spectrum in spectrum_generator:
            self.add_spectrum(spectrum)
            time.sleep(interval)
