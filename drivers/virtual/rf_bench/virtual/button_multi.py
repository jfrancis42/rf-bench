"""button_multi.py — VirtualButton SCPI driver (Multi-instance)"""

import socket


class VirtualButtonMultiError(Exception):
    pass


class VirtualButtonMulti:
    """Virtual button driver for multi-instance backend (SCPI over TCP)."""

    def __init__(self, host, port=5025, timeout=2.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _write(self, cmd):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            sock.sendall(f"{cmd}\n".encode())
            sock.close()
        except Exception as e:
            raise VirtualButtonMultiError(f"Write failed: {e}")

    def _query(self, cmd):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            sock.sendall(f"{cmd}\n".encode())
            response = sock.recv(4096).decode().strip()
            sock.close()
            return response
        except Exception as e:
            raise VirtualButtonMultiError(f"Query failed: {e}")

    def set_state(self, index, state):
        """Set state."""
        self._write(f'STAT{index}:VAL {"ON" if state else "OFF"}')

    def get_state(self, index):
        """Get state."""
        return self._query(f'STAT{index}:VAL?') == '1'

    def on(self, index):
        """Turn on."""
        self.set_state(index, True)

    def off(self, index):
        """Turn off."""
        self.set_state(index, False)

    def set_label(self, index, label):
        """Set label."""
        self._write(f'CONF{index}:LAB {label}')

    def get_count(self):
        """Get count."""
        return int(self._query('INST:COUNT?'))

    def set_count(self, count):
        """Set count."""
        self._write(f'INST:COUNT {count}')

    def idn(self):
        """Query identification."""
        return self._query('*IDN?')

    def reset(self):
        """Reset."""
        self._write('*RST')

    def close(self):
        """Close connection."""
        pass
