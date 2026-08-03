"""
VirtualKnob — Python driver for virtual SCPI rotary encoder / knob

This driver controls a web-based virtual rotary knob over TCP/SCPI (port 5025).
The knob provides continuous or stepped rotation with configurable range, wrap-around,
visual appearance (color, size, label, units), and mouse/keyboard control.

Example usage:
    >>> from rf_bench.virtual import VirtualKnob
    >>> knob = VirtualKnob('localhost')
    >>> knob.configure(min_val=0, max_val=100, step=1, label='Volume', unit='%')
    >>> knob.set_value(50)
    >>> print(knob.get_value())
    50.0
    >>> knob.close()

Context manager:
    >>> with VirtualKnob('localhost') as knob:
    ...     knob.set_value(75)
    ...     print(knob.get_value())
    75.0
"""

import socket
from typing import Optional


class VirtualKnobError(Exception):
    """Base exception for VirtualKnob driver errors."""
    pass


class VirtualKnob:
    """
    Driver for virtual SCPI rotary knob instrument.

    Provides control over a web-based rotary encoder with configurable range,
    step size, wrap-around behavior, appearance, and SCPI interface on port 5025.

    Attributes:
        host (str): Hostname or IP address of the virtual knob server
        port (int): TCP port number (default 5025)
        timeout (float): Socket timeout in seconds (default 5.0)
    """

    def __init__(self, host: str, port: int = 5025, timeout: float = 5.0):
        """
        Initialize connection to virtual knob.

        Args:
            host: Hostname or IP address of the virtual knob server
            port: TCP port number (default 5025)
            timeout: Socket timeout in seconds (default 5.0)

        Raises:
            VirtualKnobError: If connection fails
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self._connect()

    def _connect(self) -> None:
        """Establish TCP connection to the virtual knob."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.host, self.port))
        except (socket.error, socket.timeout) as e:
            raise VirtualKnobError(f"Failed to connect to {self.host}:{self.port}: {e}")

    def _send(self, command: str) -> None:
        """
        Send a SCPI command to the instrument.

        Args:
            command: SCPI command string (newline will be appended)

        Raises:
            VirtualKnobError: If send fails or connection is closed
        """
        if not self.sock:
            raise VirtualKnobError("Connection not established")
        try:
            self.sock.sendall(f"{command}\n".encode('utf-8'))
        except (socket.error, socket.timeout) as e:
            raise VirtualKnobError(f"Failed to send command '{command}': {e}")

    def _query(self, command: str) -> str:
        """
        Send a SCPI query and return the response.

        Args:
            command: SCPI query string (newline will be appended)

        Returns:
            Response string with trailing whitespace stripped

        Raises:
            VirtualKnobError: If query fails or connection is closed
        """
        self._send(command)
        if not self.sock:
            raise VirtualKnobError("Connection not established")
        try:
            response = self.sock.recv(4096).decode('utf-8').strip()
            return response
        except (socket.error, socket.timeout) as e:
            raise VirtualKnobError(f"Failed to receive response for '{command}': {e}")

    def idn(self) -> str:
        """
        Query instrument identification string (IEEE 488.2 *IDN?).

        Returns:
            Identification string in format: Manufacturer,Model,Serial,Firmware
            Example: "N0GQ,Virtual-Knob,00001,1.0"

        Raises:
            VirtualKnobError: If query fails
        """
        return self._query("*IDN?")

    def reset(self) -> None:
        """
        Reset instrument to default state (IEEE 488.2 *RST).

        Default state:
            - Value: 0
            - Min: 0
            - Max: 100
            - Step: 0 (continuous)
            - Wrap: disabled
            - Label: "Knob"
            - Unit: ""
            - Color: #4A90E2 (blue)
            - Size: 150px

        Raises:
            VirtualKnobError: If reset fails
        """
        self._send("*RST")

    def get_error(self) -> str:
        """
        Query error queue (IEEE 488.2 SYST:ERR?).

        Returns:
            Error string in format "code,message"
            Example: "0,No error" or "-100,Command error"

        Raises:
            VirtualKnobError: If query fails
        """
        return self._query("SYST:ERR?")

    def set_value(self, value: float) -> None:
        """
        Set the knob value.

        The value will be clamped to [min, max] range unless wrap-around is enabled.
        If step > 0, value will be quantized to nearest step.

        Args:
            value: Knob value to set

        Raises:
            VirtualKnobError: If command fails
        """
        self._send(f"MEAS:VAL {value}")

    def get_value(self) -> float:
        """
        Query the current knob value.

        Returns:
            Current knob value

        Raises:
            VirtualKnobError: If query fails or response is invalid
        """
        response = self._query("MEAS:VAL?")
        try:
            return float(response)
        except ValueError:
            raise VirtualKnobError(f"Invalid value response: {response}")

    def set_min(self, min_val: float) -> None:
        """
        Set the minimum knob value.

        Args:
            min_val: Minimum value

        Raises:
            VirtualKnobError: If command fails
        """
        self._send(f"CONF:MIN {min_val}")

    def get_min(self) -> float:
        """
        Query the minimum knob value.

        Returns:
            Minimum value

        Raises:
            VirtualKnobError: If query fails or response is invalid
        """
        response = self._query("CONF:MIN?")
        try:
            return float(response)
        except ValueError:
            raise VirtualKnobError(f"Invalid min response: {response}")

    def set_max(self, max_val: float) -> None:
        """
        Set the maximum knob value.

        Args:
            max_val: Maximum value

        Raises:
            VirtualKnobError: If command fails
        """
        self._send(f"CONF:MAX {max_val}")

    def get_max(self) -> float:
        """
        Query the maximum knob value.

        Returns:
            Maximum value

        Raises:
            VirtualKnobError: If query fails or response is invalid
        """
        response = self._query("CONF:MAX?")
        try:
            return float(response)
        except ValueError:
            raise VirtualKnobError(f"Invalid max response: {response}")

    def set_step(self, step: float) -> None:
        """
        Set the step size for knob rotation.

        Args:
            step: Step size (0 = continuous rotation, >0 = discrete steps)

        Raises:
            VirtualKnobError: If command fails
        """
        self._send(f"CONF:STEP {step}")

    def get_step(self) -> float:
        """
        Query the step size.

        Returns:
            Step size (0 = continuous, >0 = discrete steps)

        Raises:
            VirtualKnobError: If query fails or response is invalid
        """
        response = self._query("CONF:STEP?")
        try:
            return float(response)
        except ValueError:
            raise VirtualKnobError(f"Invalid step response: {response}")

    def set_wrap(self, enabled: bool) -> None:
        """
        Enable or disable wrap-around behavior.

        When enabled, rotating past max wraps to min (and vice versa).
        When disabled, value is clamped at min/max.

        Args:
            enabled: True to enable wrap-around, False to disable

        Raises:
            VirtualKnobError: If command fails
        """
        self._send(f"CONF:WRAP {1 if enabled else 0}")

    def get_wrap(self) -> bool:
        """
        Query wrap-around state.

        Returns:
            True if wrap-around is enabled, False otherwise

        Raises:
            VirtualKnobError: If query fails or response is invalid
        """
        response = self._query("CONF:WRAP?")
        if response not in ('0', '1'):
            raise VirtualKnobError(f"Invalid wrap response: {response}")
        return response == '1'

    def set_label(self, label: str) -> None:
        """
        Set the knob label text.

        Args:
            label: Label text to display below the knob

        Raises:
            VirtualKnobError: If command fails
        """
        self._send(f"CONF:LABEL {label}")

    def get_label(self) -> str:
        """
        Query the knob label text.

        Returns:
            Current label text

        Raises:
            VirtualKnobError: If query fails
        """
        return self._query("CONF:LABEL?")

    def set_unit(self, unit: str) -> None:
        """
        Set the display units.

        Args:
            unit: Unit string (e.g., "Hz", "dB", "%", "V")

        Raises:
            VirtualKnobError: If command fails
        """
        self._send(f"CONF:UNIT {unit}")

    def get_unit(self) -> str:
        """
        Query the display units.

        Returns:
            Current unit string

        Raises:
            VirtualKnobError: If query fails
        """
        return self._query("CONF:UNIT?")

    def set_color(self, color: str) -> None:
        """
        Set the knob color.

        Args:
            color: Hex color string (e.g., "#4A90E2", "#FF5733")

        Raises:
            VirtualKnobError: If command fails
        """
        self._send(f"CONF:COL {color}")

    def get_color(self) -> str:
        """
        Query the knob color.

        Returns:
            Hex color string

        Raises:
            VirtualKnobError: If query fails
        """
        return self._query("CONF:COL?")

    def set_size(self, size: int) -> None:
        """
        Set the knob size in pixels.

        Args:
            size: Knob diameter in pixels (100-250)

        Raises:
            VirtualKnobError: If command fails
        """
        self._send(f"CONF:SIZE {size}")

    def get_size(self) -> int:
        """
        Query the knob size.

        Returns:
            Knob diameter in pixels

        Raises:
            VirtualKnobError: If query fails or response is invalid
        """
        response = self._query("CONF:SIZE?")
        try:
            return int(response)
        except ValueError:
            raise VirtualKnobError(f"Invalid size response: {response}")

    def configure(self,
                  min_val: Optional[float] = None,
                  max_val: Optional[float] = None,
                  step: Optional[float] = None,
                  wrap: Optional[bool] = None,
                  label: Optional[str] = None,
                  unit: Optional[str] = None,
                  color: Optional[str] = None,
                  size: Optional[int] = None) -> None:
        """
        Configure multiple knob parameters in a single call.

        All parameters are optional. Only provided parameters will be updated.

        Args:
            min_val: Minimum value
            max_val: Maximum value
            step: Step size (0 = continuous, >0 = discrete)
            wrap: Wrap-around enable
            label: Label text
            unit: Unit string
            color: Hex color string
            size: Knob diameter in pixels (100-250)

        Raises:
            VirtualKnobError: If any command fails

        Example:
            >>> knob.configure(min_val=0, max_val=100, step=1,
            ...                label='Volume', unit='%', color='#4A90E2')
        """
        if min_val is not None:
            self.set_min(min_val)
        if max_val is not None:
            self.set_max(max_val)
        if step is not None:
            self.set_step(step)
        if wrap is not None:
            self.set_wrap(wrap)
        if label is not None:
            self.set_label(label)
        if unit is not None:
            self.set_unit(unit)
        if color is not None:
            self.set_color(color)
        if size is not None:
            self.set_size(size)

    def close(self) -> None:
        """Close the TCP connection to the virtual knob."""
        if self.sock:
            try:
                self.sock.close()
            except socket.error:
                pass
            finally:
                self.sock = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit — closes connection."""
        self.close()
        return False

    def __repr__(self) -> str:
        """String representation of VirtualKnob instance."""
        return f"VirtualKnob(host={self.host!r}, port={self.port})"
