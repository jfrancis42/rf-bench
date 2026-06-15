#!/usr/bin/env python3
"""
Python driver for Virtual Text Input instrument.

Connects to the text-input backend via SCPI TCP and provides a clean
Python API without exposing raw SCPI to application code.
"""

import socket
from typing import Optional


class VirtualTextInput:
    """Driver for Virtual Text Input instrument"""

    def __init__(self, host: str = "localhost", port: int = 5100):
        """
        Initialize connection to virtual text input backend.

        Args:
            host: Hostname or IP address of backend server
            port: SCPI TCP port (default 5100)
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

    def get_value(self, index: int = 1) -> str:
        """
        Get the current value of an input field.

        Args:
            index: Input field index (1-4)

        Returns:
            Current value as string
        """
        return self._query(f'SOUR{index}:VAL?')

    def set_value(self, index: int, value: str) -> None:
        """
        Set the value of an input field (backend only, not visible to user).

        Args:
            index: Input field index (1-4)
            value: Value to set
        """
        self._send_command(f'SOUR{index}:VAL {value}')

    def set_label(self, index: int, label: str) -> None:
        """
        Set the label for an input field.

        Args:
            index: Input field index (1-4)
            label: Label text
        """
        self._send_command(f'CONF{index}:LAB {label}')

    def set_placeholder(self, index: int, placeholder: str) -> None:
        """
        Set the placeholder text for an input field.

        Args:
            index: Input field index (1-4)
            placeholder: Placeholder text
        """
        self._send_command(f'CONF{index}:PLACEHOLDER {placeholder}')

    def get_count(self) -> int:
        """Get the number of input fields configured"""
        return int(self._query('INST:COUNT?'))

    def set_count(self, count: int) -> None:
        """
        Set the number of input fields (1-4).

        Args:
            count: Number of inputs
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
