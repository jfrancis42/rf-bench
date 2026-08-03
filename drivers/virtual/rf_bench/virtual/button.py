"""
Virtual Button Driver

Controls a web-based virtual button with press/release, state query,
press counting, and appearance configuration.

Example:
    >>> from rf_bench.virtual import VirtualButton
    >>> button = VirtualButton('localhost', 5025)
    >>> button.configure(label='TEST', color='#00FF00', pressed_color='#FF0000', size=120)
    >>> button.press()
    >>> print(button.get_count())
    1
    >>> button.close()
"""

import socket
from typing import Optional, Tuple


class VirtualButtonError(Exception):
    """Exception raised for Virtual Button errors."""
    pass


class VirtualButton:
    """
    Driver for the Virtual Button instrument.

    Provides control over a web-based virtual button with momentary press
    capability, state monitoring, press counting, and appearance customization.

    The button supports:
    - Momentary press triggering
    - Press state query (0 = released, 1 = pressed)
    - Total press count tracking and reset
    - Label text configuration
    - Color customization (normal and pressed states)
    - Size adjustment (80-200 pixels)

    Args:
        host: IP address or hostname of the button server
        port: TCP port (default 5025)
        timeout: Socket timeout in seconds (default 5.0)

    Example:
        >>> button = VirtualButton('10.1.1.50', 5025)
        >>> button.configure(label='FIRE', color='#FF0000', size=150)
        >>> button.press()
        >>> count = button.get_count()
        >>> button.close()

        Using context manager:
        >>> with VirtualButton('10.1.1.50') as button:
        ...     button.press()
        ...     print(f"Pressed {button.get_count()} times")
    """

    def __init__(self, host: str, port: int = 5025, timeout: float = 5.0):
        """
        Initialize connection to the virtual button.

        Args:
            host: IP address or hostname
            port: TCP port (default 5025)
            timeout: Socket timeout in seconds (default 5.0)

        Raises:
            VirtualButtonError: If connection fails
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self._connect()

    def _connect(self) -> None:
        """Establish TCP connection to the button server."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.host, self.port))
        except (socket.error, socket.timeout) as e:
            raise VirtualButtonError(f"Connection failed: {e}")

    def _send(self, command: str) -> None:
        """
        Send a SCPI command.

        Args:
            command: SCPI command string

        Raises:
            VirtualButtonError: If send fails
        """
        if not self.sock:
            raise VirtualButtonError("Not connected")
        try:
            self.sock.sendall(f"{command}\n".encode('ascii'))
        except socket.error as e:
            raise VirtualButtonError(f"Send failed: {e}")

    def _query(self, command: str) -> str:
        """
        Send a SCPI query and return the response.

        Args:
            command: SCPI query string

        Returns:
            Response string with trailing whitespace stripped

        Raises:
            VirtualButtonError: If query fails
        """
        self._send(command)
        if not self.sock:
            raise VirtualButtonError("Not connected")
        try:
            response = self.sock.recv(4096).decode('ascii').strip()
            return response
        except socket.error as e:
            raise VirtualButtonError(f"Query failed: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def close(self) -> None:
        """Close the connection."""
        if self.sock:
            try:
                self.sock.close()
            except socket.error:
                pass
            finally:
                self.sock = None

    # IEEE 488.2 Common Commands

    def idn(self) -> str:
        """
        Query instrument identification.

        Returns:
            Identification string (manufacturer,model,serial,version)

        Example:
            >>> button.idn()
            'N0GQ,VirtualButton,SN001,1.0'
        """
        return self._query("*IDN?")

    def reset(self) -> None:
        """
        Reset the button to default state.

        Resets all configuration parameters to factory defaults and clears
        the press count.

        Example:
            >>> button.reset()
        """
        self._send("*RST")

    def get_error(self) -> str:
        """
        Query the error queue.

        Returns:
            Error string (code and message)

        Example:
            >>> button.get_error()
            '0,No error'
        """
        return self._query("SYST:ERR?")

    # Button Control

    def press(self) -> None:
        """
        Trigger a momentary button press.

        Simulates a button press event. The button visual state will briefly
        change to the pressed appearance, then return to normal. The press
        counter is incremented.

        Example:
            >>> button.press()
        """
        self._send("STAT:PRESS")

    def is_pressed(self) -> bool:
        """
        Query if the button is currently pressed.

        Returns:
            True if pressed, False if released

        Example:
            >>> if button.is_pressed():
            ...     print("Button is active")
        """
        response = self._query("STAT:PRESS?")
        return response.strip() == "1"

    def get_count(self) -> int:
        """
        Query total press count.

        Returns:
            Number of times the button has been pressed since last reset

        Example:
            >>> count = button.get_count()
            >>> print(f"Button pressed {count} times")
        """
        response = self._query("STAT:COUNT?")
        return int(response)

    def clear_count(self) -> None:
        """
        Clear the press count.

        Resets the press counter to zero without affecting other settings.

        Example:
            >>> button.clear_count()
        """
        self._send("STAT:COUNT:CLEAR")

    # Configuration

    def set_label(self, label: str) -> None:
        """
        Set button label text.

        Args:
            label: Text to display on the button

        Example:
            >>> button.set_label('START')
        """
        self._send(f"CONF:LABEL {label}")

    def get_label(self) -> str:
        """
        Query button label text.

        Returns:
            Current label text

        Example:
            >>> label = button.get_label()
        """
        return self._query("CONF:LABEL?")

    def set_color(self, color: str) -> None:
        """
        Set button color (normal state).

        Args:
            color: Hex color code (e.g., '#00FF00' or '00FF00')

        Example:
            >>> button.set_color('#00FF00')  # Green
        """
        self._send(f"CONF:COL {color}")

    def get_color(self) -> str:
        """
        Query button color (normal state).

        Returns:
            Hex color code

        Example:
            >>> color = button.get_color()
        """
        return self._query("CONF:COL?")

    def set_pressed_color(self, color: str) -> None:
        """
        Set button color when pressed.

        Args:
            color: Hex color code (e.g., '#FF0000' or 'FF0000')

        Example:
            >>> button.set_pressed_color('#FF0000')  # Red when pressed
        """
        self._send(f"CONF:PRESSCOL {color}")

    def get_pressed_color(self) -> str:
        """
        Query button pressed color.

        Returns:
            Hex color code for pressed state

        Example:
            >>> pressed_color = button.get_pressed_color()
        """
        return self._query("CONF:PRESSCOL?")

    def set_size(self, size: int) -> None:
        """
        Set button size in pixels.

        Args:
            size: Button diameter in pixels (range: 80-200)

        Raises:
            ValueError: If size is outside valid range

        Example:
            >>> button.set_size(120)
        """
        if not 80 <= size <= 200:
            raise ValueError("Size must be between 80 and 200 pixels")
        self._send(f"CONF:SIZE {size}")

    def get_size(self) -> int:
        """
        Query button size.

        Returns:
            Button diameter in pixels

        Example:
            >>> size = button.get_size()
        """
        response = self._query("CONF:SIZE?")
        return int(response)

    def configure(self,
                  label: Optional[str] = None,
                  color: Optional[str] = None,
                  pressed_color: Optional[str] = None,
                  size: Optional[int] = None) -> None:
        """
        Configure multiple button parameters at once.

        Args:
            label: Button label text
            color: Normal state color (hex)
            pressed_color: Pressed state color (hex)
            size: Button diameter in pixels (80-200)

        Example:
            >>> button.configure(
            ...     label='FIRE',
            ...     color='#FF0000',
            ...     pressed_color='#800000',
            ...     size=150
            ... )
        """
        if label is not None:
            self.set_label(label)
        if color is not None:
            self.set_color(color)
        if pressed_color is not None:
            self.set_pressed_color(pressed_color)
        if size is not None:
            self.set_size(size)

    def get_config(self) -> dict:
        """
        Query all configuration parameters.

        Returns:
            Dictionary containing label, color, pressed_color, and size

        Example:
            >>> config = button.get_config()
            >>> print(config)
            {'label': 'TEST', 'color': '#00FF00', 'pressed_color': '#FF0000', 'size': 120}
        """
        return {
            'label': self.get_label(),
            'color': self.get_color(),
            'pressed_color': self.get_pressed_color(),
            'size': self.get_size()
        }
