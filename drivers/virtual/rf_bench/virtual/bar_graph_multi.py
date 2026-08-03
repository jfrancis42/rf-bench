"""bar_graph_multi.py — VirtualBarGraph SCPI driver (Multi-instance)"""

import socket


class VirtualBarGraphMultiError(Exception):
    pass


class VirtualBarGraphMulti:
    """Virtual bar-graph driver for multi-instance backend (SCPI over TCP)."""

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
            raise VirtualBarGraphMultiError(f"Write failed: {e}")

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
            raise VirtualBarGraphMultiError(f"Query failed: {e}")

    def set_value(self, index, value):
        """Set value."""
        self._write(f'MEAS{index}:VAL {value}')

    def get_value(self, index):
        """Get value."""
        return float(self._query(f'MEAS{index}:VAL?'))

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
