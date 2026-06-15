"""
text_input.py — Virtual Text Input SCPI driver

Connects to virtual text input backend via TCP SCPI (default port 5104).
Provides interactive text entry with command history and MQTT integration.

Usage::

    from rf_bench.virtual import VirtualTextInput

    # Basic usage
    with VirtualTextInput("10.1.1.52") as text_input:
        text_input.send("FREQ:CENT 100MHz")
        last_text = text_input.get_last()
        history = text_input.get_history()

    # Configure display
    with VirtualTextInput("10.1.1.52") as text_input:
        text_input.set_label("SCPI Command")
        text_input.set_rows(3)
        text_input.set_placeholder("Enter instrument command...")
        text_input.send("*IDN?")

    # MQTT bidirectional integration
    with VirtualTextInput("10.1.1.52") as text_input:
        text_input.configure_mqtt(
            host="mqtt.n0gq.org",
            sub_topic="scpi/commands/in",
            pub_topic="scpi/commands/out"
        )
"""

import socket


class VirtualTextInputError(Exception):
    pass


class VirtualTextInput:
    """Virtual text input driver (SCPI over TCP)."""

    def __init__(self, host, port=5104, timeout=2.0):
        """Initialize connection to virtual text input.

        Args:
            host: IP address or hostname
            port: SCPI TCP port (default 5104)
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
            raise VirtualTextInputError(f"Connection failed to {self.host}:{self.port}: {e}")

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
            raise VirtualTextInputError("Not connected")
        try:
            self._sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            raise VirtualTextInputError(f"Write failed: {e}")

    def _query(self, cmd):
        """Send SCPI query and return response."""
        self._write(cmd)
        try:
            response = self._sock.recv(4096).decode().strip()
            return response
        except Exception as e:
            raise VirtualTextInputError(f"Query failed: {e}")

    # IEEE 488.2 common commands

    def idn(self):
        """Query instrument identification.

        Returns:
            str: Identification string (manufacturer,model,serial,firmware)
        """
        return self._query("*IDN?")

    def reset(self):
        """Reset instrument to default state."""
        self._write("*RST")

    def get_error(self):
        """Query error queue.

        Returns:
            str: Error code and message (e.g. "0,No error")
        """
        return self._query("SYST:ERR?")

    # Text commands

    def send(self, text):
        """Send text string (triggers display update and MQTT publish).

        Args:
            text: Text to send (can be multi-line, SCPI command, etc.)
        """
        self._write(f"TEXT:SEND {text}")

    def get_last(self):
        """Query last sent text.

        Returns:
            str: Last text that was sent
        """
        return self._query("TEXT:SEND?")

    def get_history(self):
        """Query command history.

        Returns:
            list: List of historical commands (most recent last)
        """
        response = self._query("TEXT:HIST?")
        if response:
            return response.split('\n')
        return []

    def clear_history(self):
        """Clear command history."""
        self._write("TEXT:HIST:CLEAR")

    # Configuration commands

    def set_label(self, label):
        """Set input field label.

        Args:
            label: Label text (e.g. "Command", "SCPI Input")
        """
        self._write(f"CONF:LABEL {label}")

    def get_label(self):
        """Query input field label.

        Returns:
            str: Current label text
        """
        return self._query("CONF:LABEL?")

    def set_rows(self, rows):
        """Set number of text input rows (1-10).

        Args:
            rows: Number of rows (1=single line, >1=textarea)
        """
        if not (1 <= rows <= 10):
            raise ValueError("Rows must be 1-10")
        self._write(f"CONF:ROWS {rows}")

    def get_rows(self):
        """Query number of text input rows.

        Returns:
            int: Number of rows (1-10)
        """
        return int(self._query("CONF:ROWS?"))

    def set_history_depth(self, depth):
        """Set command history depth (0-100).

        Args:
            depth: Maximum number of commands to retain (0=no history)
        """
        if not (0 <= depth <= 100):
            raise ValueError("History depth must be 0-100")
        self._write(f"CONF:HIST {depth}")

    def get_history_depth(self):
        """Query command history depth.

        Returns:
            int: Maximum history size (0-100)
        """
        return int(self._query("CONF:HIST?"))

    def set_placeholder(self, text):
        """Set placeholder text (shown when input is empty).

        Args:
            text: Placeholder text
        """
        self._write(f"CONF:PLACEHOLDER {text}")

    def get_placeholder(self):
        """Query placeholder text.

        Returns:
            str: Current placeholder text
        """
        return self._query("CONF:PLACEHOLDER?")

    # MQTT configuration

    def configure_mqtt(self, host, sub_topic, pub_topic=None):
        """Configure MQTT bidirectional integration.

        Args:
            host: MQTT broker hostname/IP
            sub_topic: Topic to subscribe to (receives text from MQTT)
            pub_topic: Topic to publish to (sends text to MQTT, optional)
        """
        if pub_topic:
            self._write(f"MQTT:CONF {host},{sub_topic},{pub_topic}")
        else:
            self._write(f"MQTT:CONF {host},{sub_topic}")

    def get_mqtt_config(self):
        """Query MQTT configuration.

        Returns:
            dict: {"host": str, "sub_topic": str, "pub_topic": str or None}
                  or None if not configured
        """
        response = self._query("MQTT:CONF?")
        if response == "Not configured":
            return None

        parts = response.split(',')
        config = {
            "host": parts[0],
            "sub_topic": parts[1] if len(parts) > 1 else None,
            "pub_topic": parts[2] if len(parts) > 2 else None
        }
        return config

    # Convenience methods

    def configure(self, label=None, rows=None, placeholder=None, history_depth=None):
        """Configure multiple display parameters at once.

        Args:
            label: Input field label (optional)
            rows: Number of rows 1-10 (optional)
            placeholder: Placeholder text (optional)
            history_depth: History size 0-100 (optional)
        """
        if label is not None:
            self.set_label(label)
        if rows is not None:
            self.set_rows(rows)
        if placeholder is not None:
            self.set_placeholder(placeholder)
        if history_depth is not None:
            self.set_history_depth(history_depth)
