"""
text_input_multi.py — Virtual Text Input SCPI driver (Multi-instance)

Connects to virtual text input backend via TCP SCPI with support for
multiple indexed inputs (1-4).

Usage::

    from rf_bench.virtual import VirtualTextInputMulti

    # Create driver for multi-instance backend
    inputs = VirtualTextInputMulti("localhost", port=5100)

    # Get user-entered values
    voltage = float(inputs.get_value(1))
    current = float(inputs.get_value(2))

    # Configure labels
    inputs.set_label(1, "Voltage (V)")
    inputs.set_label(2, "Current (A)")

    inputs.close()
"""

import socket


class VirtualTextInputMultiError(Exception):
    pass


class VirtualTextInputMulti:
    """Virtual text input driver for multi-instance backend (SCPI over TCP)."""

    def __init__(self, host, port=5100, timeout=2.0):
        """Initialize connection to virtual text input multi-instance backend.

        Args:
            host: IP address or hostname
            port: SCPI TCP port (default 5100)
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
            raise VirtualTextInputMultiError(f"Write failed: {e}")

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
            raise VirtualTextInputMultiError(f"Query failed: {e}")

    def get_value(self, index):
        """Get the current value of an input field.

        Args:
            index: Input field index (1-4)

        Returns:
            str: Current value as string
        """
        return self._query(f'SOUR{index}:VAL?')

    def set_value(self, index, value):
        """Set the value of an input field (backend only, not visible to user).

        Args:
            index: Input field index (1-4)
            value: Value to set
        """
        self._write(f'SOUR{index}:VAL {value}')

    def set_label(self, index, label):
        """Set the label for an input field.

        Args:
            index: Input field index (1-4)
            label: Label text
        """
        self._write(f'CONF{index}:LAB {label}')

    def set_placeholder(self, index, placeholder):
        """Set the placeholder text for an input field.

        Args:
            index: Input field index (1-4)
            placeholder: Placeholder text
        """
        self._write(f'CONF{index}:PLACEHOLDER {placeholder}')

    def get_count(self):
        """Get the number of input fields configured.

        Returns:
            int: Number of inputs (1-4)
        """
        return int(self._query('INST:COUNT?'))

    def set_count(self, count):
        """Set the number of input fields (1-4).

        Args:
            count: Number of inputs
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
