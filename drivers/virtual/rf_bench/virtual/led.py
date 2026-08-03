"""
led.py — Virtual LED Indicator SCPI driver

Connects to virtual LED indicator backend via TCP SCPI (default port 5025).
Single-instance only (no multi-LED support in this driver).

Usage::

    from rf_bench.virtual import VirtualLED

    # PTT indicator (red when active)
    with VirtualLED("10.1.1.52") as led:
        led.set_on_color("#ff0000")
        led.set_off_color("#440000")
        led.set_label("PTT")
        led.set_state(True)   # Turn on

    # GPS lock indicator (blue, blinking)
    with VirtualLED("10.1.1.52") as led:
        led.configure(
            on_color="#4488ff",
            off_color="#222244",
            label="GPS",
            blink_ms=500
        )
        led.set_state(True)
"""

import socket


class VirtualLEDError(Exception):
    pass


class VirtualLED:
    """Virtual LED indicator driver (SCPI over TCP)."""

    def __init__(self, host, port=5025, timeout=2.0):
        """Initialize connection to virtual LED indicator.

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
            raise VirtualLEDError(f"Connection failed to {self.host}:{self.port}: {e}")

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
            raise VirtualLEDError("Not connected")
        try:
            self._sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            raise VirtualLEDError(f"Write failed: {e}")

    def _query(self, cmd):
        """Send SCPI query and return response."""
        self._write(cmd)
        try:
            response = self._sock.recv(4096).decode().strip()
            return response
        except Exception as e:
            raise VirtualLEDError(f"Query failed: {e}")

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

    # LED state control

    def set_state(self, state):
        """Set LED state (on/off).

        Args:
            state: True/False, 1/0, "ON"/"OFF"
        """
        if isinstance(state, bool):
            val = 1 if state else 0
        elif isinstance(state, int):
            val = state
        elif isinstance(state, str):
            val = state.upper()
        else:
            raise ValueError("State must be bool, int, or string")
        self._write(f"STAT:VAL {val}")

    def get_state(self):
        """Query LED state.

        Returns:
            bool: True if LED is on, False if off
        """
        response = self._query("STAT:VAL?")
        return response.strip() == "1"

    # LED configuration

    def set_on_color(self, color):
        """Set LED color when ON.

        Args:
            color: CSS color string (e.g. "#00ff00", "#0f0")
        """
        self._write(f"CONF:ONCOL {color}")

    def get_on_color(self):
        """Query LED ON color.

        Returns:
            str: CSS color string
        """
        return self._query("CONF:ONCOL?")

    def set_off_color(self, color):
        """Set LED color when OFF.

        Args:
            color: CSS color string (e.g. "#333333", "#333")
        """
        self._write(f"CONF:OFFCOL {color}")

    def get_off_color(self):
        """Query LED OFF color.

        Returns:
            str: CSS color string
        """
        return self._query("CONF:OFFCOL?")

    def set_blink(self, blink_ms):
        """Set LED blink rate.

        Args:
            blink_ms: Blink period in milliseconds (0 = no blink)
        """
        if not isinstance(blink_ms, int) or blink_ms < 0:
            raise ValueError("Blink rate must be non-negative integer")
        self._write(f"CONF:BLINK {blink_ms}")

    def get_blink(self):
        """Query LED blink rate.

        Returns:
            int: Blink period in milliseconds (0 = no blink)
        """
        return int(self._query("CONF:BLINK?"))

    def set_size(self, size):
        """Set LED diameter in pixels.

        Args:
            size: Diameter in pixels (20-200)
        """
        if not (20 <= size <= 200):
            raise ValueError("Size must be 20-200 pixels")
        self._write(f"CONF:SIZE {size}")

    def get_size(self):
        """Query LED diameter.

        Returns:
            int: Diameter in pixels
        """
        return int(self._query("CONF:SIZE?"))

    def set_label(self, label):
        """Set LED label text.

        Args:
            label: Label string (appears below LED)
        """
        self._write(f"CONF:LABEL {label}")

    def get_label(self):
        """Query LED label text.

        Returns:
            str: Label string
        """
        return self._query("CONF:LABEL?")

    # Convenience methods

    def configure(self, on_color="#00ff00", off_color="#333333",
                  label="", blink_ms=0, size=80):
        """Configure all LED parameters at once.

        Args:
            on_color: LED color when ON (default green)
            off_color: LED color when OFF (default dark gray)
            label: Label text below LED
            blink_ms: Blink period in ms (0 = no blink)
            size: LED diameter in pixels (20-200)
        """
        self.set_on_color(on_color)
        self.set_off_color(off_color)
        self.set_label(label)
        self.set_blink(blink_ms)
        self.set_size(size)

    def on(self):
        """Turn LED on (shorthand for set_state(True))."""
        self.set_state(True)

    def off(self):
        """Turn LED off (shorthand for set_state(False))."""
        self.set_state(False)

    def toggle(self):
        """Toggle LED state."""
        current = self.get_state()
        self.set_state(not current)
