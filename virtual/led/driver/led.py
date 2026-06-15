#!/usr/bin/env python3
"""
Python driver for Virtual LED indicator instrument.

Connects to the LED backend via SCPI TCP and provides a clean
Python API without exposing raw SCPI to application code.
"""

import socket
from typing import Optional


class VirtualLED:
    """Driver for Virtual LED indicator instrument"""

    def __init__(self, host: str = "localhost", port: int = 5102):
        """
        Initialize connection to virtual LED backend.

        Args:
            host: Hostname or IP address of backend server
            port: SCPI TCP port (default 5102)
        """
        self.host = host
        self.port = port
        self._timeout = 2.0

    def _send_command(self, cmd: str) -> None:
        """Send SCPI command (no response expected)"""
        s = socket.socket()
        s.settimeout(self._timeout)
        s.connect((self.host, self.port))
        s.sendall(f'{cmd}\n'.encode())
        s.close()

    def _query(self, cmd: str) -> str:
        """Send SCPI query and return response"""
        s = socket.socket()
        s.settimeout(self._timeout)
        s.connect((self.host, self.port))
        s.sendall(f'{cmd}\n'.encode())
        resp = s.recv(4096).decode().strip()
        s.close()
        return resp

    def set_state(self, index: int, state: bool) -> None:
        """
        Set LED state (on/off).

        Args:
            index: LED index (1-4)
            state: True for ON, False for OFF
        """
        self._send_command(f'STAT{index}:VAL {"ON" if state else "OFF"}')

    def get_state(self, index: int) -> bool:
        """
        Get LED state.

        Args:
            index: LED index (1-4)

        Returns:
            True if ON, False if OFF
        """
        resp = self._query(f'STAT{index}:VAL?')
        return resp == '1'

    def on(self, index: int) -> None:
        """Turn LED on"""
        self.set_state(index, True)

    def off(self, index: int) -> None:
        """Turn LED off"""
        self.set_state(index, False)

    def set_label(self, index: int, label: str) -> None:
        """
        Set LED label text.

        Args:
            index: LED index (1-4)
            label: Label text
        """
        self._send_command(f'CONF{index}:LAB {label}')

    def set_on_color(self, index: int, color: str) -> None:
        """
        Set LED color when ON.

        Args:
            index: LED index (1-4)
            color: Hex color (e.g., '#00ff00')
        """
        self._send_command(f'CONF{index}:ONCOL {color}')

    def set_off_color(self, index: int, color: str) -> None:
        """
        Set LED color when OFF.

        Args:
            index: LED index (1-4)
            color: Hex color (e.g., '#333333')
        """
        self._send_command(f'CONF{index}:OFFCOL {color}')

    def set_blink(self, index: int, period_ms: int) -> None:
        """
        Set LED blink period.

        Args:
            index: LED index (1-4)
            period_ms: Blink period in milliseconds (0 = no blink)
        """
        self._send_command(f'CONF{index}:BLINK {period_ms}')

    def set_size(self, index: int, size_px: int) -> None:
        """
        Set LED size.

        Args:
            index: LED index (1-4)
            size_px: Diameter in pixels (20-200)
        """
        self._send_command(f'CONF{index}:SIZE {size_px}')

    def get_count(self) -> int:
        """Get the number of LEDs configured"""
        return int(self._query('INST:COUNT?'))

    def set_count(self, count: int) -> None:
        """
        Set the number of LEDs (1-4).

        Args:
            count: Number of LEDs
        """
        self._send_command(f'INST:COUNT {count}')

    def idn(self) -> str:
        """Query instrument identification"""
        return self._query('*IDN?')

    def reset(self) -> None:
        """Reset instrument to default state"""
        self._send_command('*RST')

    def close(self) -> None:
        """Close connection (no persistent connection maintained)"""
        pass
