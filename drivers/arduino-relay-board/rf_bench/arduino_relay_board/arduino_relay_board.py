"""
TCP client for the Arduino+W5500 network-controlled 4-channel relay board.

The board listens on TCP port 5025 and speaks a line-oriented ASCII
protocol — every command returns exactly one line, either ``OK`` /
a value / ``ERR: <reason>``. See the board firmware in
``~/Dropbox/build/rf-bench/hardware/arduino-relay-board/`` for the
full command set.
"""

from __future__ import annotations

import socket
import threading
from typing import Tuple


_DEFAULT_PORT = 5025
_DEFAULT_TIMEOUT = 2.0
_NUM_RELAYS = 4


class ArduinoRelayBoardError(RuntimeError):
    """Raised when the board returns an error response (``ERR: …``)."""


class ArduinoRelayBoardTimeoutError(ArduinoRelayBoardError):
    """Raised when a command does not produce a response within the timeout."""


class ArduinoRelayBoard:
    """
    Network client for the Arduino + W5500 4-channel relay board.

    Maintains a single persistent TCP connection. Each public method
    sends one command and waits for one response line. Access is
    serialised by an internal lock so the driver is safe to share
    across threads.

    Parameters
    ----------
    host : str
        IP address or hostname of the board.
    port : int
        TCP port (default 5025).
    timeout : float
        Per-command timeout in seconds (default 2.0).
    auto_connect : bool
        If True (default), open the TCP connection in ``__init__``.

    Usage
    -----
    As a context manager (recommended)::

        with ArduinoRelayBoard("192.168.1.177") as r:
            r.on(1)
            r.pulse_high(2, 250)
            r.off(1)

    Or manually::

        r = ArduinoRelayBoard("192.168.1.177")
        try:
            r.on(1)
        finally:
            r.close()
    """

    NUM_RELAYS = _NUM_RELAYS

    def __init__(
        self,
        host: str,
        port: int = _DEFAULT_PORT,
        timeout: float = _DEFAULT_TIMEOUT,
        auto_connect: bool = True,
    ):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._rxbuf = b""
        self._lock = threading.Lock()
        if auto_connect:
            self.connect()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the TCP connection. Safe to call again after ``close()``."""
        with self._lock:
            if self._sock is not None:
                return
            s = socket.create_connection((self._host, self._port), timeout=self._timeout)
            s.settimeout(self._timeout)
            # Lower latency for short commands; Nagle would coalesce them with
            # the response stream into single packets that delay round-trip.
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock = s
            self._rxbuf = b""

    def close(self) -> None:
        """Close the TCP connection. Safe to call multiple times."""
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
                self._rxbuf = b""

    def __enter__(self) -> "ArduinoRelayBoard":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Low-level send/recv
    # ------------------------------------------------------------------

    def _readline(self) -> str:
        """Read one '\\n'-terminated line from the socket."""
        assert self._sock is not None
        while b"\n" not in self._rxbuf:
            try:
                chunk = self._sock.recv(256)
            except socket.timeout as e:
                raise ArduinoRelayBoardTimeoutError(
                    f"timeout waiting for response from {self._host}:{self._port}"
                ) from e
            if not chunk:
                raise ArduinoRelayBoardError(
                    f"connection to {self._host}:{self._port} closed by peer"
                )
            self._rxbuf += chunk
        line, _, rest = self._rxbuf.partition(b"\n")
        self._rxbuf = rest
        return line.decode("ascii", errors="replace").rstrip("\r\n").strip()

    def _command(self, cmd: str) -> str:
        """
        Send a single command and return the single response line.

        Raises ArduinoRelayBoardError if the board returns ``ERR: …``.
        """
        with self._lock:
            if self._sock is None:
                # Reconnect lazily if the user closed and re-used the object
                self._sock = socket.create_connection(
                    (self._host, self._port), timeout=self._timeout
                )
                self._sock.settimeout(self._timeout)
                self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._rxbuf = b""
            payload = (cmd + "\n").encode("ascii")
            try:
                self._sock.sendall(payload)
            except (OSError, socket.timeout) as e:
                raise ArduinoRelayBoardError(
                    f"send failed: {e!r}"
                ) from e
            resp = self._readline()
        if resp.startswith("ERR:"):
            raise ArduinoRelayBoardError(resp)
        return resp

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_relay(n: int) -> None:
        if not (1 <= n <= _NUM_RELAYS):
            raise ValueError(
                f"relay index {n} out of range (1..{_NUM_RELAYS})"
            )

    @staticmethod
    def _check_ms(ms: int) -> None:
        if not isinstance(ms, int) or ms <= 0:
            raise ValueError(f"pulse duration must be a positive integer ms (got {ms!r})")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def idn(self) -> str:
        """Return the board identification string."""
        return self._command("*IDN?")

    def help(self) -> str:
        """Return the multi-line HELP banner from the board."""
        # HELP is the one command that returns multiple lines terminated
        # by a final 'END' marker.
        with self._lock:
            if self._sock is None:
                raise ArduinoRelayBoardError("not connected")
            self._sock.sendall(b"HELP\n")
            lines: list[str] = []
            while True:
                line = self._readline()
                if line == "END":
                    break
                lines.append(line)
        return "\n".join(lines)

    def on(self, relay: int) -> None:
        """Energize ``relay`` (1..4)."""
        self._check_relay(relay)
        resp = self._command(f"ON {relay}")
        if resp != "OK":
            raise ArduinoRelayBoardError(f"unexpected response: {resp!r}")

    def off(self, relay: int) -> None:
        """De-energize ``relay`` (1..4)."""
        self._check_relay(relay)
        resp = self._command(f"OFF {relay}")
        if resp != "OK":
            raise ArduinoRelayBoardError(f"unexpected response: {resp!r}")

    def pulse_high(self, relay: int, duration_ms: int) -> None:
        """
        Drive ``relay`` HIGH (energized) for ``duration_ms`` milliseconds,
        then return to LOW (de-energized).

        Returns immediately; the timed revert is handled on the board.
        """
        self._check_relay(relay)
        self._check_ms(duration_ms)
        resp = self._command(f"PULSEH {relay} {duration_ms}")
        if resp != "OK":
            raise ArduinoRelayBoardError(f"unexpected response: {resp!r}")

    def pulse_low(self, relay: int, duration_ms: int) -> None:
        """
        Drive ``relay`` LOW (de-energized) for ``duration_ms`` milliseconds,
        then return to HIGH (energized).

        Returns immediately; the timed revert is handled on the board.
        """
        self._check_relay(relay)
        self._check_ms(duration_ms)
        resp = self._command(f"PULSEL {relay} {duration_ms}")
        if resp != "OK":
            raise ArduinoRelayBoardError(f"unexpected response: {resp!r}")

    def get_state(self, relay: int) -> bool:
        """Return True if ``relay`` is currently energized."""
        self._check_relay(relay)
        resp = self._command(f"STATUS {relay}")
        if resp == "0":
            return False
        if resp == "1":
            return True
        raise ArduinoRelayBoardError(f"unexpected status response: {resp!r}")

    def status(self) -> int:
        """
        Return the 4-bit status bitmask (bit 0 = relay 1, bit 3 = relay 4).

        Example: ``0b1010`` = 0xA = relays 2 and 4 are energized.
        """
        resp = self._command("STATUS")
        # Board sends "0xH" — accept any base via int(..., 0).
        try:
            return int(resp, 0)
        except ValueError as e:
            raise ArduinoRelayBoardError(f"bad STATUS response: {resp!r}") from e

    def status_all(self) -> Tuple[bool, ...]:
        """Return a tuple of bool per relay (length = 4)."""
        bits = self.status()
        return tuple(bool((bits >> i) & 1) for i in range(_NUM_RELAYS))

    def reset(self) -> None:
        """De-energize all relays and cancel any in-flight pulses."""
        resp = self._command("RESET")
        if resp != "OK":
            raise ArduinoRelayBoardError(f"unexpected response: {resp!r}")

    def all_off(self) -> None:
        """Alias for :meth:`reset` matching other rf-bench relay drivers."""
        self.reset()
