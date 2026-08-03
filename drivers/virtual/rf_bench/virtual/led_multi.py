"""
led_multi.py — Virtual LED Indicator SCPI driver (Multi-instance)

Connects to virtual LED indicator backend via TCP SCPI with support for
multiple indexed LEDs (1-4).

Usage::

    from rf_bench.virtual import VirtualLEDMulti

    # Create driver for multi-instance backend
    leds = VirtualLEDMulti("localhost", port=5102)

    # Configure LEDs
    leds.set_label(1, "Output")
    leds.set_on_color(1, "#00ff00")
    leds.set_off_color(1, "#333333")

    leds.set_label(2, "CC Mode")
    leds.set_on_color(2, "#ff0000")
    leds.set_off_color(2, "#333333")

    leds.set_label(3, "CV Mode")
    leds.set_on_color(3, "#00ff00")
    leds.set_off_color(3, "#333333")

    # Control LED states
    leds.on(1)         # Turn output LED on
    leds.set_state(2, True)   # Turn CC LED on
    leds.off(3)        # Turn CV LED off

    leds.close()
"""

import socket


class VirtualLEDMultiError(Exception):
    pass


class VirtualLEDMulti:
    """Virtual LED indicator driver for multi-instance backend (SCPI over TCP)."""

    def __init__(self, host, port=5102, timeout=2.0):
        """Initialize connection to virtual LED multi-instance backend.

        Args:
            host: IP address or hostname
            port: SCPI TCP port (default 5102)
            timeout: Socket timeout in seconds
        """
        self.host = host
        self.port = port
        self.timeout = timeout

    def _write(self, cmd):
        """Send SCPI command (no response expected)."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            sock.sendall(f"{cmd}\n".encode())
            sock.close()
        except Exception as e:
            raise VirtualLEDMultiError(f"Write failed: {e}")

    def _query(self, cmd):
        """Send SCPI query and return response."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            sock.sendall(f"{cmd}\n".encode())
            response = sock.recv(4096).decode().strip()
            sock.close()
            return response
        except Exception as e:
            raise VirtualLEDMultiError(f"Query failed: {e}")

    def set_state(self, index, state):
        """Set LED state (on/off).

        Args:
            index: LED index (1-4)
            state: True for ON, False for OFF
        """
        self._write(f'STAT{index}:VAL {"ON" if state else "OFF"}')

    def get_state(self, index):
        """Get LED state.

        Args:
            index: LED index (1-4)

        Returns:
            bool: True if ON, False if OFF
        """
        resp = self._query(f'STAT{index}:VAL?')
        return resp == '1'

    def on(self, index):
        """Turn LED on.

        Args:
            index: LED index (1-4)
        """
        self.set_state(index, True)

    def off(self, index):
        """Turn LED off.

        Args:
            index: LED index (1-4)
        """
        self.set_state(index, False)

    def set_label(self, index, label):
        """Set LED label text.

        Args:
            index: LED index (1-4)
            label: Label text
        """
        self._write(f'CONF{index}:LAB {label}')

    def set_on_color(self, index, color):
        """Set LED color when ON.

        Args:
            index: LED index (1-4)
            color: Hex color (e.g., '#00ff00')
        """
        self._write(f'CONF{index}:ONCOL {color}')

    def set_off_color(self, index, color):
        """Set LED color when OFF.

        Args:
            index: LED index (1-4)
            color: Hex color (e.g., '#333333')
        """
        self._write(f'CONF{index}:OFFCOL {color}')

    def set_blink(self, index, period_ms):
        """Set LED blink period.

        Args:
            index: LED index (1-4)
            period_ms: Blink period in milliseconds (0 = no blink)
        """
        self._write(f'CONF{index}:BLINK {period_ms}')

    def set_size(self, index, size_px):
        """Set LED size.

        Args:
            index: LED index (1-4)
            size_px: Diameter in pixels (20-200)
        """
        self._write(f'CONF{index}:SIZE {size_px}')

    def get_count(self):
        """Get the number of LEDs configured.

        Returns:
            int: Number of LEDs (1-4)
        """
        return int(self._query('INST:COUNT?'))

    def set_count(self, count):
        """Set the number of LEDs (1-4).

        Args:
            count: Number of LEDs
        """
        self._write(f'INST:COUNT {count}')

    def idn(self):
        """Query instrument identification.

        Returns:
            str: Identification string
        """
        return self._query('*IDN?')

    def reset(self):
        """Reset instrument to default state."""
        self._write('*RST')

    def close(self):
        """Close connection (stateless, no persistent connection)."""
        pass
