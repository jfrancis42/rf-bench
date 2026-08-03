"""
numeric_display.py — Virtual Numeric Display SCPI driver

Connects to virtual numeric display backend via TCP SCPI (default port 5025).
Single-instance only (no multi-display support in this driver).

Usage::

    from rf_bench.virtual import VirtualNumericDisplay

    # Basic usage
    with VirtualNumericDisplay("10.1.1.52") as display:
        display.set_value(14.257000)
        display.set_units("MHz")
        display.set_precision(6)
        print(display.get_value())  # → 14.257000

    # Full configuration
    with VirtualNumericDisplay("localhost") as display:
        display.configure(
            precision=2,
            digits=8,
            units="V",
            font_size=100,
            color="#00ffff",
            style="7SEG"
        )
        display.set_value(13.8)
"""

import socket
from typing import Optional


class VirtualNumericDisplayError(Exception):
    """Exception raised by VirtualNumericDisplay driver."""
    pass


class VirtualNumericDisplay:
    """Virtual numeric display driver (SCPI over TCP).

    Connects to a single virtual numeric display backend server.
    NO multi-instance support (run separate servers for multiple displays).

    Attributes:
        host: IP address or hostname of backend server
        port: SCPI TCP port (default 5025)
        timeout: Socket timeout in seconds
    """

    def __init__(self, host: str, port: int = 5025, timeout: float = 2.0):
        """Initialize connection to virtual numeric display.

        Args:
            host: IP address or hostname
            port: SCPI TCP port (default 5025)
            timeout: Socket timeout in seconds

        Raises:
            VirtualNumericDisplayError: If connection fails
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._connect()

    def _connect(self):
        """Establish TCP connection.

        Raises:
            VirtualNumericDisplayError: If connection fails
        """
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))
        except Exception as e:
            raise VirtualNumericDisplayError(f"Connection failed to {self.host}:{self.port}: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, *_):
        """Context manager exit."""
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
        """Send SCPI command.

        Args:
            cmd: SCPI command string (without trailing newline)

        Raises:
            VirtualNumericDisplayError: If not connected or write fails
        """
        if not self._sock:
            raise VirtualNumericDisplayError("Not connected")
        try:
            self._sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            raise VirtualNumericDisplayError(f"Write failed: {e}")

    def _query(self, cmd: str) -> str:
        """Send SCPI query and return response.

        Args:
            cmd: SCPI query command string (without trailing newline)

        Returns:
            Response string (stripped of whitespace)

        Raises:
            VirtualNumericDisplayError: If query fails
        """
        self._write(cmd)
        try:
            response = self._sock.recv(4096).decode().strip()
            return response
        except Exception as e:
            raise VirtualNumericDisplayError(f"Query failed: {e}")

    # IEEE 488.2 common commands

    def idn(self) -> str:
        """Query instrument identification.

        Returns:
            Identification string (manufacturer,model,serial,firmware)
            Example: "N0GQ,Virtual-Numeric-Display,1.0,2026"
        """
        return self._query("*IDN?")

    def reset(self):
        """Reset instrument to default state.

        Resets to: value=0.0, precision=2, digits=8, units="",
        font_size=80, color="#00ff00", style="7SEG"
        """
        self._write("*RST")

    def get_error(self) -> str:
        """Query error queue.

        Returns:
            Error code and message (e.g. "0,No error" or "-222,Data out of range")
        """
        return self._query("SYST:ERR?")

    # Measurement value

    def set_value(self, value: float):
        """Set displayed value.

        Args:
            value: Numeric value to display

        Example:
            display.set_value(14.257000)
        """
        self._write(f"MEAS:VAL {value}")

    def get_value(self) -> float:
        """Query current displayed value.

        Returns:
            Current display value

        Example:
            >>> display.get_value()
            14.257
        """
        return float(self._query("MEAS:VAL?"))

    # Configuration commands

    def set_precision(self, precision: int):
        """Set decimal precision (number of decimal places).

        Args:
            precision: Number of decimal places (0-6, default 2)

        Raises:
            ValueError: If precision not in range 0-6

        Example:
            display.set_precision(6)  # 14.257000
            display.set_precision(2)  # 14.26
            display.set_precision(0)  # 14
        """
        if not (0 <= precision <= 6):
            raise ValueError("Precision must be 0-6")
        self._write(f"CONF:PREC {precision}")

    def get_precision(self) -> int:
        """Query decimal precision.

        Returns:
            Number of decimal places (0-6)
        """
        return int(self._query("CONF:PREC?"))

    def set_digits(self, digits: int):
        """Set total digit count (display width).

        Args:
            digits: Total number of digits (4-12, default 8)

        Raises:
            ValueError: If digits not in range 4-12

        Example:
            display.set_digits(8)   # ______14.257000 (fits in 8 chars with decimals)
            display.set_digits(12)  # ____14.257000 (wider display)
        """
        if not (4 <= digits <= 12):
            raise ValueError("Digits must be 4-12")
        self._write(f"CONF:DIG {digits}")

    def get_digits(self) -> int:
        """Query total digit count.

        Returns:
            Total number of digits (4-12)
        """
        return int(self._query("CONF:DIG?"))

    def set_units(self, units: str):
        """Set display units string.

        Args:
            units: Units text (e.g., "MHz", "V", "A", "°C", "dBm")

        Example:
            display.set_units("MHz")
            display.set_units("V")
            display.set_units("")  # No units
        """
        self._write(f"CONF:UNIT {units}")

    def get_units(self) -> str:
        """Query display units string.

        Returns:
            Units text
        """
        return self._query("CONF:UNIT?")

    def set_font_size(self, size: int):
        """Set font size in pixels.

        Args:
            size: Font size in pixels (20-120, default 80)

        Raises:
            ValueError: If size not in range 20-120

        Example:
            display.set_font_size(60)   # Smaller
            display.set_font_size(100)  # Larger
        """
        if not (20 <= size <= 120):
            raise ValueError("Font size must be 20-120")
        self._write(f"CONF:SIZE {size}")

    def get_font_size(self) -> int:
        """Query font size.

        Returns:
            Font size in pixels (20-120)
        """
        return int(self._query("CONF:SIZE?"))

    def set_color(self, color: str):
        """Set text color.

        Args:
            color: CSS hex color string (e.g., "#00ff00", "#0f0")

        Raises:
            ValueError: If color format invalid (must be #RGB or #RRGGBB)

        Example:
            display.set_color("#00ff00")  # Green (default)
            display.set_color("#00ffff")  # Cyan
            display.set_color("#ff0000")  # Red
            display.set_color("#fff")     # White (short form)
        """
        if not (color.startswith('#') and len(color) in [4, 7]):
            raise ValueError("Color must be hex format (#RGB or #RRGGBB)")
        self._write(f"CONF:COL {color}")

    def get_color(self) -> str:
        """Query text color.

        Returns:
            CSS hex color string
        """
        return self._query("CONF:COL?")

    def set_style(self, style: str):
        """Set display style.

        Args:
            style: Display style: "7SEG", "PLAIN", "LED", or "NIXIE" (default "7SEG")

        Raises:
            ValueError: If style not in valid set

        Example:
            display.set_style("7SEG")   # Classic 7-segment LCD
            display.set_style("PLAIN")  # Clean sans-serif
            display.set_style("LED")    # LED dot matrix look
            display.set_style("NIXIE")  # Nixie tube aesthetic
        """
        style_upper = style.upper()
        if style_upper not in ["7SEG", "PLAIN", "LED", "NIXIE"]:
            raise ValueError("Style must be 7SEG, PLAIN, LED, or NIXIE")
        self._write(f"CONF:STYLE {style_upper}")

    def get_style(self) -> str:
        """Query display style.

        Returns:
            Display style string (7SEG, PLAIN, LED, or NIXIE)
        """
        return self._query("CONF:STYLE?")

    # Convenience methods

    def configure(
        self,
        precision: Optional[int] = None,
        digits: Optional[int] = None,
        units: Optional[str] = None,
        font_size: Optional[int] = None,
        color: Optional[str] = None,
        style: Optional[str] = None
    ):
        """Configure all display parameters at once.

        Only sets parameters that are not None.

        Args:
            precision: Decimal places (0-6)
            digits: Total digit count (4-12)
            units: Units string
            font_size: Font size in pixels (20-120)
            color: CSS hex color
            style: Display style (7SEG, PLAIN, LED, NIXIE)

        Example:
            display.configure(
                precision=3,
                digits=8,
                units="MHz",
                font_size=90,
                color="#00ff88",
                style="7SEG"
            )
        """
        if precision is not None:
            self.set_precision(precision)
        if digits is not None:
            self.set_digits(digits)
        if units is not None:
            self.set_units(units)
        if font_size is not None:
            self.set_font_size(font_size)
        if color is not None:
            self.set_color(color)
        if style is not None:
            self.set_style(style)

    def update(self, value: float):
        """Update displayed value (alias for set_value).

        Args:
            value: Numeric value to display

        Example:
            display.update(14.257)  # Same as display.set_value(14.257)
        """
        self.set_value(value)
