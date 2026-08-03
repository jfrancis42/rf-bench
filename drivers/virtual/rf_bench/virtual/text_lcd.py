"""
text_lcd.py — Virtual Text LCD SCPI driver

Connects to virtual text LCD terminal backend via TCP SCPI (default port 5006).
Displays scrolling text output with configurable formatting, color, and scrollback.

Usage::

    from rf_bench.virtual import VirtualTextLCD

    # Basic text output
    with VirtualTextLCD("10.1.1.52") as lcd:
        lcd.write("System initialized")
        lcd.write("Temperature: 25.3°C")
        lcd.clear()

    # Configured terminal
    with VirtualTextLCD("10.1.1.52") as lcd:
        lcd.set_title("System Monitor")
        lcd.set_color("#00ff00")
        lcd.set_font_size(16)
        lcd.set_max_lines(100)

        for i in range(10):
            lcd.writeln(f"Processing item {i+1}/10")
"""

import socket
import time


class VirtualTextLCDError(Exception):
    pass


class VirtualTextLCD:
    """Virtual text LCD terminal driver (SCPI over TCP)."""

    def __init__(self, host, port=5006, timeout=2.0):
        """Initialize connection to virtual text LCD.

        Args:
            host: IP address or hostname
            port: SCPI TCP port (default 5006)
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
            raise VirtualTextLCDError(f"Connection failed to {self.host}:{self.port}: {e}")

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

    def _write(self, cmd):
        """Send SCPI command."""
        if not self._sock:
            raise VirtualTextLCDError("Not connected")
        try:
            self._sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            raise VirtualTextLCDError(f"Write failed: {e}")

    def _query(self, cmd):
        """Send SCPI query and return response."""
        self._write(cmd)
        try:
            response = self._sock.recv(4096).decode().strip()
            return response
        except Exception as e:
            raise VirtualTextLCDError(f"Query failed: {e}")

    # IEEE 488.2 common commands

    def idn(self):
        """Query instrument identification.

        Returns:
            str: Identification string (manufacturer,model,serial,firmware)
        """
        return self._query("*IDN?")

    def reset(self):
        """Reset instrument to default state (clears all text)."""
        self._write("*RST")

    def get_error(self):
        """Query error queue.

        Returns:
            str: Error code and message (e.g. "0,No error")
        """
        return self._query("SYST:ERR?")

    # Display commands

    def write(self, text):
        """Append text line to display (adds timestamp automatically).

        Args:
            text: Text string to display
        """
        # Escape quotes in text
        escaped = text.replace('"', '\\"')
        self._write(f'DISP:TEXT "{escaped}"')

    def writeln(self, text):
        """Append text line to display (alias for write).

        Args:
            text: Text string to display
        """
        self.write(text)

    def clear(self):
        """Clear all text from display."""
        self._write("DISP:CLEAR")

    def get_line_count(self):
        """Query number of lines currently in buffer.

        Returns:
            int: Number of lines
        """
        return int(self._query("DISP:TEXT?"))

    # Configuration commands

    def set_max_lines(self, lines):
        """Set scrollback buffer size.

        Args:
            lines: Maximum lines to keep (10-1000)
        """
        if not (10 <= lines <= 1000):
            raise ValueError("Lines must be 10-1000")
        self._write(f"CONF:LINES {lines}")

    def get_max_lines(self):
        """Query scrollback buffer size.

        Returns:
            int: Maximum lines (10-1000)
        """
        return int(self._query("CONF:LINES?"))

    def set_font_size(self, size):
        """Set font size.

        Args:
            size: Font size in points (10-24)
        """
        if not (10 <= size <= 24):
            raise ValueError("Size must be 10-24")
        self._write(f"CONF:SIZE {size}")

    def get_font_size(self):
        """Query font size.

        Returns:
            int: Font size in points (10-24)
        """
        return int(self._query("CONF:SIZE?"))

    def set_color(self, color):
        """Set text color.

        Args:
            color: CSS color string (e.g. "#00ff00", "#0f0")
        """
        if not color.startswith('#') or len(color) not in [4, 7]:
            raise ValueError("Color must be hex format: #RGB or #RRGGBB")
        self._write(f'CONF:COL "{color}"')

    def get_color(self):
        """Query text color.

        Returns:
            str: CSS color string (e.g. "#00ff00")
        """
        return self._query("CONF:COL?")

    def set_title(self, title):
        """Set terminal window title.

        Args:
            title: Title string
        """
        escaped = title.replace('"', '\\"')
        self._write(f'CONF:TITLE "{escaped}"')

    def get_title(self):
        """Query terminal window title.

        Returns:
            str: Title string
        """
        return self._query("CONF:TITLE?")

    # MQTT configuration

    def configure_mqtt(self, host, topic):
        """Configure MQTT broker and subscribe to topic.

        Args:
            host: MQTT broker hostname or IP
            topic: MQTT topic to subscribe to
        """
        self._write(f"MQTT:CONF {host},{topic}")

    def get_mqtt_config(self):
        """Query MQTT configuration.

        Returns:
            str: "host,topic" or "Not configured"
        """
        return self._query("MQTT:CONF?")

    # Convenience methods

    def configure(self, title="Terminal", color="#000000", font_size=14, max_lines=50):
        """Configure all terminal parameters at once.

        Args:
            title: Window title (default "Terminal")
            color: Text color hex string (default "#000000")
            font_size: Font size 10-24 (default 14)
            max_lines: Scrollback buffer 10-1000 (default 50)
        """
        self.set_title(title)
        self.set_color(color)
        self.set_font_size(font_size)
        self.set_max_lines(max_lines)

    def print_lines(self, lines, interval=0):
        """Print multiple lines with optional delay between each.

        Args:
            lines: Iterable of text strings
            interval: Delay between lines in seconds (default 0)
        """
        for line in lines:
            self.write(line)
            if interval > 0:
                time.sleep(interval)
