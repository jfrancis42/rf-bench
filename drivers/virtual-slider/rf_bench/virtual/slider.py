"""
Virtual Slider Instrument Driver

Provides SCPI control interface for a virtual slider instrument that displays
a configurable slider control in a web browser. Supports linear and logarithmic
scales, horizontal and vertical orientations, and customizable appearance.

Example:
    >>> from rf_bench.virtual import VirtualSlider
    >>> slider = VirtualSlider('localhost')
    >>> slider.configure(min_val=0, max_val=100, step=1, label='Volume', unit='%')
    >>> slider.set_value(75)
    >>> print(slider.get_value())
    75.0
"""

import socket
from typing import Optional, Tuple


class VirtualSliderError(Exception):
    """Exception raised for Virtual Slider errors."""
    pass


class VirtualSlider:
    """
    Virtual Slider instrument driver.

    Provides SCPI control for a browser-based slider instrument with configurable
    range, scale, orientation, and appearance. Does NOT support multiple instances
    per connection (single slider only).

    Args:
        host: IP address or hostname of the virtual slider server
        port: TCP port (default 5025)
        timeout: Socket timeout in seconds (default 5.0)

    Example:
        >>> with VirtualSlider('localhost') as slider:
        ...     slider.configure(min_val=20, max_val=20000, scale='LOG',
        ...                     label='Frequency', unit='Hz')
        ...     slider.set_value(1000)
        ...     print(f"Current: {slider.get_value()} Hz")
    """

    def __init__(self, host: str, port: int = 5025, timeout: float = 5.0):
        """
        Initialize connection to virtual slider server.

        Args:
            host: IP address or hostname
            port: TCP port (default 5025)
            timeout: Socket timeout in seconds (default 5.0)

        Raises:
            VirtualSliderError: If connection fails
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self._connect()

    def _connect(self) -> None:
        """Establish TCP connection to the instrument."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.host, self.port))
        except (socket.error, socket.timeout) as e:
            raise VirtualSliderError(f"Connection failed: {e}")

    def _send(self, command: str) -> None:
        """
        Send SCPI command to instrument.

        Args:
            command: SCPI command string (newline added automatically)

        Raises:
            VirtualSliderError: If send fails
        """
        if not self.sock:
            raise VirtualSliderError("Not connected")
        try:
            self.sock.sendall(f"{command}\n".encode('ascii'))
        except socket.error as e:
            raise VirtualSliderError(f"Send failed: {e}")

    def _query(self, command: str) -> str:
        """
        Send SCPI query and return response.

        Args:
            command: SCPI query string (newline added automatically)

        Returns:
            Response string with trailing whitespace stripped

        Raises:
            VirtualSliderError: If query fails
        """
        self._send(command)
        try:
            response = self.sock.recv(4096).decode('ascii').strip()
            return response
        except socket.error as e:
            raise VirtualSliderError(f"Query failed: {e}")

    def close(self) -> None:
        """Close connection to instrument."""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    # IEEE 488.2 Common Commands

    def idn(self) -> str:
        """
        Query instrument identification string.

        Returns:
            Identification string (manufacturer,model,serial,version)

        Example:
            >>> slider.idn()
            'N0GQ,Virtual-Slider,0001,1.0.0'
        """
        return self._query("*IDN?")

    def reset(self) -> None:
        """
        Reset instrument to default state.

        Resets to: min=0, max=100, step=0 (continuous), orientation=horizontal,
        scale=linear, label='Slider', unit='', color=#007bff (blue), value=50.

        Example:
            >>> slider.reset()
        """
        self._send("*RST")

    def get_error(self) -> Tuple[int, str]:
        """
        Query error queue.

        Returns:
            Tuple of (error_code, error_message). (0, 'No error') if queue empty.

        Example:
            >>> code, msg = slider.get_error()
            >>> if code != 0:
            ...     print(f"Error {code}: {msg}")
        """
        response = self._query("SYST:ERR?")
        parts = response.split(',', 1)
        code = int(parts[0])
        message = parts[1].strip('"') if len(parts) > 1 else ""
        return (code, message)

    # Configuration Commands

    def set_min(self, value: float) -> None:
        """
        Set slider minimum value.

        Args:
            value: Minimum value

        Example:
            >>> slider.set_min(0.0)
        """
        self._send(f"CONF:MIN {value}")

    def get_min(self) -> float:
        """
        Query slider minimum value.

        Returns:
            Minimum value

        Example:
            >>> min_val = slider.get_min()
        """
        return float(self._query("CONF:MIN?"))

    def set_max(self, value: float) -> None:
        """
        Set slider maximum value.

        Args:
            value: Maximum value

        Example:
            >>> slider.set_max(100.0)
        """
        self._send(f"CONF:MAX {value}")

    def get_max(self) -> float:
        """
        Query slider maximum value.

        Returns:
            Maximum value

        Example:
            >>> max_val = slider.get_max()
        """
        return float(self._query("CONF:MAX?"))

    def set_step(self, value: float) -> None:
        """
        Set slider step size.

        Args:
            value: Step size (0 for continuous, >0 for discrete steps)

        Example:
            >>> slider.set_step(1.0)    # Discrete integer steps
            >>> slider.set_step(0.0)    # Continuous smooth sliding
        """
        self._send(f"CONF:STEP {value}")

    def get_step(self) -> float:
        """
        Query slider step size.

        Returns:
            Step size (0 = continuous)

        Example:
            >>> step = slider.get_step()
        """
        return float(self._query("CONF:STEP?"))

    def set_orientation(self, orientation: str) -> None:
        """
        Set slider orientation.

        Args:
            orientation: 'HOR' (horizontal) or 'VERT' (vertical)

        Raises:
            VirtualSliderError: If orientation invalid

        Example:
            >>> slider.set_orientation('VERT')
        """
        orientation = orientation.upper()
        if orientation not in ('HOR', 'VERT'):
            raise VirtualSliderError(f"Invalid orientation: {orientation}")
        self._send(f"CONF:ORIENT {orientation}")

    def get_orientation(self) -> str:
        """
        Query slider orientation.

        Returns:
            'HOR' or 'VERT'

        Example:
            >>> orient = slider.get_orientation()
        """
        return self._query("CONF:ORIENT?")

    def set_scale(self, scale: str) -> None:
        """
        Set slider scale type.

        Args:
            scale: 'LIN' (linear) or 'LOG' (logarithmic)

        Raises:
            VirtualSliderError: If scale invalid

        Example:
            >>> slider.set_scale('LOG')
        """
        scale = scale.upper()
        if scale not in ('LIN', 'LOG'):
            raise VirtualSliderError(f"Invalid scale: {scale}")
        self._send(f"CONF:SCALE {scale}")

    def get_scale(self) -> str:
        """
        Query slider scale type.

        Returns:
            'LIN' or 'LOG'

        Example:
            >>> scale = slider.get_scale()
        """
        return self._query("CONF:SCALE?")

    def set_label(self, label: str) -> None:
        """
        Set slider label text.

        Args:
            label: Display label (max 50 chars recommended)

        Example:
            >>> slider.set_label('Frequency')
        """
        # Escape any quotes in the label
        label = label.replace('"', '\\"')
        self._send(f'CONF:LABEL "{label}"')

    def get_label(self) -> str:
        """
        Query slider label text.

        Returns:
            Label string (quotes stripped)

        Example:
            >>> label = slider.get_label()
        """
        response = self._query("CONF:LABEL?")
        return response.strip('"')

    def set_unit(self, unit: str) -> None:
        """
        Set display unit string.

        Args:
            unit: Unit string (e.g., 'Hz', 'V', 'dB', '%')

        Example:
            >>> slider.set_unit('dBm')
        """
        # Escape any quotes in the unit
        unit = unit.replace('"', '\\"')
        self._send(f'CONF:UNIT "{unit}"')

    def get_unit(self) -> str:
        """
        Query display unit string.

        Returns:
            Unit string (quotes stripped)

        Example:
            >>> unit = slider.get_unit()
        """
        response = self._query("CONF:UNIT?")
        return response.strip('"')

    def set_color(self, color: str) -> None:
        """
        Set slider color.

        Args:
            color: Hex color code (e.g., '#007bff', 'ff0000')

        Example:
            >>> slider.set_color('#ff0000')  # Red
            >>> slider.set_color('00ff00')    # Green (# optional)
        """
        self._send(f"CONF:COL {color}")

    def get_color(self) -> str:
        """
        Query slider color.

        Returns:
            Hex color code (with # prefix)

        Example:
            >>> color = slider.get_color()
        """
        return self._query("CONF:COL?")

    # Measurement Commands

    def set_value(self, value: float) -> None:
        """
        Set slider value.

        Args:
            value: Value (clamped to min/max range by server)

        Example:
            >>> slider.set_value(75.5)
        """
        self._send(f"MEAS:VAL {value}")

    def get_value(self) -> float:
        """
        Query current slider value.

        Returns:
            Current value

        Example:
            >>> value = slider.get_value()
        """
        return float(self._query("MEAS:VAL?"))

    # Convenience Methods

    def configure(self,
                  min_val: Optional[float] = None,
                  max_val: Optional[float] = None,
                  step: Optional[float] = None,
                  orientation: Optional[str] = None,
                  scale: Optional[str] = None,
                  label: Optional[str] = None,
                  unit: Optional[str] = None,
                  color: Optional[str] = None) -> None:
        """
        Configure multiple slider parameters in one call.

        Args:
            min_val: Minimum value
            max_val: Maximum value
            step: Step size (0 = continuous)
            orientation: 'HOR' or 'VERT'
            scale: 'LIN' or 'LOG'
            label: Display label
            unit: Display unit
            color: Hex color code

        Example:
            >>> slider.configure(
            ...     min_val=20,
            ...     max_val=20000,
            ...     scale='LOG',
            ...     label='Frequency',
            ...     unit='Hz',
            ...     color='#28a745'
            ... )
        """
        if min_val is not None:
            self.set_min(min_val)
        if max_val is not None:
            self.set_max(max_val)
        if step is not None:
            self.set_step(step)
        if orientation is not None:
            self.set_orientation(orientation)
        if scale is not None:
            self.set_scale(scale)
        if label is not None:
            self.set_label(label)
        if unit is not None:
            self.set_unit(unit)
        if color is not None:
            self.set_color(color)
