"""
numeric_display_multi.py — Virtual Numeric Display SCPI driver (Multi-instance)

Connects to virtual numeric display backend via TCP SCPI with support for
multiple indexed displays (1-4).

Usage::

    from rf_bench.virtual import VirtualNumericDisplayMulti

    # Create driver for multi-instance backend
    displays = VirtualNumericDisplayMulti("localhost", port=5101)

    # Update display values
    displays.set_value(1, 12.345)  # Display 1
    displays.set_value(2, 5.000)   # Display 2
    displays.set_value(3, 1.250)   # Display 3
    displays.set_value(4, 15.625)  # Display 4

    # Configure display appearance
    displays.set_style(1, "NIXIE")
    displays.set_color(1, "#ff6600")
    displays.set_units(1, "V")
    displays.set_precision(1, 3)

    displays.close()
"""

import socket


class VirtualNumericDisplayMultiError(Exception):
    pass


class VirtualNumericDisplayMulti:
    """Virtual numeric display driver for multi-instance backend (SCPI over TCP)."""

    def __init__(self, host, port=5101, timeout=2.0):
        """Initialize connection to virtual numeric display multi-instance backend.

        Args:
            host: IP address or hostname
            port: SCPI TCP port (default 5101)
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
            raise VirtualNumericDisplayMultiError(f"Write failed: {e}")

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
            raise VirtualNumericDisplayMultiError(f"Query failed: {e}")

    def set_value(self, index, value):
        """Set the display value.

        Args:
            index: Display index (1-4)
            value: Numeric value to display
        """
        self._write(f'MEAS{index}:VAL {value}')

    def get_value(self, index):
        """Get the current display value.

        Args:
            index: Display index (1-4)

        Returns:
            float: Current displayed value
        """
        return float(self._query(f'MEAS{index}:VAL?'))

    def set_units(self, index, units):
        """Set the units string.

        Args:
            index: Display index (1-4)
            units: Units string (e.g., 'V', 'A', 'MHz')
        """
        self._write(f'CONF{index}:UNIT {units}')

    def set_precision(self, index, precision):
        """Set the number of decimal places.

        Args:
            index: Display index (1-4)
            precision: Number of decimal places (0-9)
        """
        self._write(f'CONF{index}:PREC {precision}')

    def set_label(self, index, label):
        """Set the display label.

        Args:
            index: Display index (1-4)
            label: Label text
        """
        self._write(f'CONF{index}:LAB {label}')

    def set_style(self, index, style):
        """Set the display style.

        Args:
            index: Display index (1-4)
            style: Style name (e.g., '7SEG', 'NIXIE', 'VFD', 'LCD')
        """
        self._write(f'CONF{index}:STYLE {style}')

    def set_color(self, index, color):
        """Set the display color.

        Args:
            index: Display index (1-4)
            color: Hex color (e.g., '#ff6600')
        """
        self._write(f'CONF{index}:COL {color}')

    def get_count(self):
        """Get the number of displays configured.

        Returns:
            int: Number of displays (1-4)
        """
        return int(self._query('INST:COUNT?'))

    def set_count(self, count):
        """Set the number of displays (1-4).

        Args:
            count: Number of displays
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
