"""
toggle.py — Virtual Toggle Switch SCPI driver

Connects to virtual toggle switch backend via TCP SCPI (default port 5025).
Single-instance only (no multi-toggle support).

Usage::

    from rf_bench.virtual import VirtualToggle

    # Basic usage
    with VirtualToggle("10.1.1.52") as toggle:
        toggle.set_label("PTT")
        toggle.on()
        print(toggle.get_state())  # → True
        toggle.off()
        print(toggle.get_state())  # → False

    # Configuration
    with VirtualToggle("10.1.1.52") as toggle:
        toggle.configure(
            label="TX Enable",
            on_color="#ff0000",
            off_color="#444444",
            on_label="TRANSMIT",
            off_label="STANDBY",
            size=150
        )
        toggle.toggle()  # Flip state
"""

import socket


class VirtualToggleError(Exception):
    pass


class VirtualToggle:
    """Virtual toggle switch driver (SCPI over TCP)."""

    def __init__(self, host: str, port: int = 5025, timeout: float = 2.0):
        """Initialize connection to virtual toggle switch.

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
            raise VirtualToggleError(f"Connection failed to {self.host}:{self.port}: {e}")

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

    def _write(self, cmd: str):
        """Send SCPI command."""
        if not self._sock:
            raise VirtualToggleError("Not connected")
        try:
            self._sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            raise VirtualToggleError(f"Write failed: {e}")

    def _query(self, cmd: str) -> str:
        """Send SCPI query and return response."""
        self._write(cmd)
        try:
            response = self._sock.recv(4096).decode().strip()
            return response
        except Exception as e:
            raise VirtualToggleError(f"Query failed: {e}")

    # IEEE 488.2 common commands

    def idn(self) -> str:
        """Query instrument identification.

        Returns:
            str: Identification string (manufacturer,model,serial,firmware)
        """
        return self._query("*IDN?")

    def reset(self):
        """Reset instrument to default state."""
        self._write("*RST")

    def get_error(self) -> str:
        """Query error queue.

        Returns:
            str: Error code and message (e.g. "0,No error")
        """
        return self._query("SYST:ERR?")

    # State control

    def set_state(self, state: bool):
        """Set toggle switch state.

        Args:
            state: True for ON, False for OFF
        """
        value = "1" if state else "0"
        self._write(f"STAT:VAL {value}")

    def get_state(self) -> bool:
        """Query current toggle state.

        Returns:
            bool: True if ON, False if OFF
        """
        response = self._query("STAT:VAL?")
        return response.strip() == "1"

    # Configuration commands

    def set_label(self, label: str):
        """Set toggle switch label text.

        Args:
            label: Label string (e.g. "PTT", "TX Enable")
        """
        self._write(f"CONF:LABEL {label}")

    def get_label(self) -> str:
        """Query toggle switch label.

        Returns:
            str: Label string
        """
        return self._query("CONF:LABEL?")

    def set_on_color(self, color: str):
        """Set ON state color.

        Args:
            color: CSS color string (e.g. "#00ff00", "green")
        """
        self._write(f"CONF:ONCOL {color}")

    def get_on_color(self) -> str:
        """Query ON state color.

        Returns:
            str: CSS color string
        """
        return self._query("CONF:ONCOL?")

    def set_off_color(self, color: str):
        """Set OFF state color.

        Args:
            color: CSS color string (e.g. "#444444", "gray")
        """
        self._write(f"CONF:OFFCOL {color}")

    def get_off_color(self) -> str:
        """Query OFF state color.

        Returns:
            str: CSS color string
        """
        return self._query("CONF:OFFCOL?")

    def set_on_label(self, label: str):
        """Set ON state label text.

        Args:
            label: ON label string (e.g. "TRANSMIT", "ON")
        """
        self._write(f"CONF:ONLABEL {label}")

    def get_on_label(self) -> str:
        """Query ON state label.

        Returns:
            str: ON label string
        """
        return self._query("CONF:ONLABEL?")

    def set_off_label(self, label: str):
        """Set OFF state label text.

        Args:
            label: OFF label string (e.g. "STANDBY", "OFF")
        """
        self._write(f"CONF:OFFLABEL {label}")

    def get_off_label(self) -> str:
        """Query OFF state label.

        Returns:
            str: OFF label string
        """
        return self._query("CONF:OFFLABEL?")

    def set_size(self, size: int):
        """Set toggle switch display size.

        Args:
            size: Size in pixels (50-200)
        """
        if not (50 <= size <= 200):
            raise ValueError("Size must be between 50 and 200 pixels")
        self._write(f"CONF:SIZE {size}")

    def get_size(self) -> int:
        """Query toggle switch size.

        Returns:
            int: Size in pixels
        """
        return int(self._query("CONF:SIZE?"))

    # Convenience methods

    def on(self):
        """Turn toggle switch ON.

        Convenience method equivalent to set_state(True).
        """
        self.set_state(True)

    def off(self):
        """Turn toggle switch OFF.

        Convenience method equivalent to set_state(False).
        """
        self.set_state(False)

    def toggle(self):
        """Flip toggle switch to opposite state.

        Reads current state and inverts it.
        """
        current = self.get_state()
        self.set_state(not current)

    def configure(
        self,
        label: str = None,
        on_color: str = None,
        off_color: str = None,
        on_label: str = None,
        off_label: str = None,
        size: int = None
    ):
        """Configure all toggle parameters at once.

        Args:
            label: Main toggle label (optional)
            on_color: ON state color (optional)
            off_color: OFF state color (optional)
            on_label: ON state label text (optional)
            off_label: OFF state label text (optional)
            size: Toggle size in pixels 50-200 (optional)
        """
        if label is not None:
            self.set_label(label)
        if on_color is not None:
            self.set_on_color(on_color)
        if off_color is not None:
            self.set_off_color(off_color)
        if on_label is not None:
            self.set_on_label(on_label)
        if off_label is not None:
            self.set_off_label(off_label)
        if size is not None:
            self.set_size(size)
