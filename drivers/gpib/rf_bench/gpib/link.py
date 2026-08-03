"""
link.py — byte-level links to a GPIB adapter.

A ``Link`` is the dumb pipe underneath an adapter: it moves bytes and knows
nothing about GPIB, ``++`` commands, or instruments.  The KISS-488 Rev 2
exposes two behaviourally identical interfaces (User Guide Rev 2.13, §10:
"all action is identical to use under TelNet"), so both are modelled here:

    TcpLink     — Telnet, TCP port 23 by default
    SerialLink  — USB serial, 115200 8N1, FTDI (Rev 2 hardware only)

``FakeLink`` lives in :mod:`rf_bench.gpib.testing` and is used to exercise the
whole stack without hardware.

Subclasses implement ``_send_bytes`` / ``_recv_bytes`` / ``_close``; the base
class provides buffered line reading on top, because a single GPIB reply (an
801-point SDAT dump, say) will arrive split across many TCP segments or serial
chunks and may carry the tail of the next reply with it.
"""

from __future__ import annotations

import socket
import time
from abc import ABC, abstractmethod
from typing import Optional


DEFAULT_TELNET_PORT = 23        # KISS-488 default; configurable in its web UI
DEFAULT_SERIAL_BAUD = 115200    # KISS-488 Rev 2 USB serial: 115200 8N1, no handshake

CONNECT_TIMEOUT = 10.0          # seconds — initial TCP connect
DEFAULT_READ_TIMEOUT = 5.0      # seconds — host-side wait for a reply
RECV_BUFSIZE = 65536


class LinkError(IOError):
    """Raised when the underlying link fails or is used after close."""


class Link(ABC):
    """Buffered byte pipe to an adapter."""

    def __init__(self, description: str):
        self.description = description
        self._buf = bytearray()
        self._closed = False

    # -- subclass interface -------------------------------------------------

    @abstractmethod
    def _send_bytes(self, data: bytes) -> None:
        """Write raw bytes. Must raise LinkError on failure."""

    @abstractmethod
    def _recv_bytes(self, timeout: float) -> bytes:
        """Read whatever is available within ``timeout``. b"" means nothing arrived."""

    @abstractmethod
    def _close(self) -> None:
        """Release the underlying resource. Must be idempotent."""

    # -- public interface ---------------------------------------------------

    def write(self, data: bytes) -> None:
        self._check_open()
        self._send_bytes(data)

    def write_line(self, text: str, terminator: bytes = b"\n") -> None:
        self.write(text.encode("ascii", errors="strict") + terminator)

    def read_line(
        self,
        timeout: float = DEFAULT_READ_TIMEOUT,
        terminator: bytes = b"\n",
    ) -> str:
        """
        Read until ``terminator``, or until ``timeout`` expires.

        Returns the decoded line with the terminator and surrounding whitespace
        stripped.  A timeout is NOT an error: the KISS-488 default configuration
        uses a *silent* timeout (null Timeout String — User Guide Rev 2.13, §5
        "Timeouts"), so an empty string is the documented result of asking an
        instrument for data it does not have.  Callers that need to distinguish
        "empty" from "nothing" should compare against "".
        """
        self._check_open()
        deadline = time.monotonic() + timeout
        while True:
            idx = self._buf.find(terminator)
            if idx >= 0:
                line = bytes(self._buf[:idx])
                del self._buf[: idx + len(terminator)]
                return line.decode("ascii", errors="replace").strip()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Timed out: return whatever partial data accumulated, if any.
                line = bytes(self._buf)
                self._buf.clear()
                return line.decode("ascii", errors="replace").strip()
            chunk = self._recv_bytes(remaining)
            if chunk:
                self._buf.extend(chunk)

    def read_until_idle(self, idle: float = 0.3, timeout: float = DEFAULT_READ_TIMEOUT) -> str:
        """
        Read until no new bytes arrive for ``idle`` seconds, or ``timeout`` total.

        Used for replies with no reliable terminator — notably ``++spy`` output
        and multi-line echoback such as the Solartron 7151's ``E`` command.
        """
        self._check_open()
        deadline = time.monotonic() + timeout
        last = time.monotonic()
        while time.monotonic() < deadline:
            chunk = self._recv_bytes(min(idle, max(0.0, deadline - time.monotonic())))
            if chunk:
                self._buf.extend(chunk)
                last = time.monotonic()
            elif time.monotonic() - last >= idle:
                break
        out = bytes(self._buf)
        self._buf.clear()
        return out.decode("ascii", errors="replace")

    def reset_input_buffer(self, drain: float = 0.1) -> None:
        """Discard buffered and in-flight input (e.g. a stale sign-on banner)."""
        self._buf.clear()
        deadline = time.monotonic() + drain
        while time.monotonic() < deadline:
            if not self._recv_bytes(deadline - time.monotonic()):
                break

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._close()

    @property
    def closed(self) -> bool:
        return self._closed

    def _check_open(self) -> None:
        if self._closed:
            raise LinkError(f"link is closed: {self.description}")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.description}{' closed' if self._closed else ''}>"


class TcpLink(Link):
    """Telnet/raw-TCP link to a KISS-488. Default port 23."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_TELNET_PORT,
        connect_timeout: float = CONNECT_TIMEOUT,
    ):
        super().__init__(f"tcp://{host}:{port}")
        self.host = host
        self.port = port
        try:
            self._sock = socket.create_connection((host, port), timeout=connect_timeout)
        except OSError as e:
            raise LinkError(f"cannot connect to {host}:{port}: {e}") from e
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def _send_bytes(self, data: bytes) -> None:
        try:
            self._sock.sendall(data)
        except OSError as e:
            raise LinkError(f"send failed on {self.description}: {e}") from e

    def _recv_bytes(self, timeout: float) -> bytes:
        if timeout <= 0:
            return b""
        self._sock.settimeout(timeout)
        try:
            return self._sock.recv(RECV_BUFSIZE)
        except socket.timeout:
            return b""
        except OSError as e:
            raise LinkError(f"recv failed on {self.description}: {e}") from e

    def _close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class SerialLink(Link):
    """
    USB-serial link to a KISS-488 Rev 2 (115200 8N1, no handshake, FTDI).

    Requires ``pyserial``; imported lazily so the package installs and the TCP
    path works on hosts without it.
    """

    def __init__(
        self,
        device: str,
        baud: int = DEFAULT_SERIAL_BAUD,
        connect_timeout: float = CONNECT_TIMEOUT,
    ):
        super().__init__(f"serial://{device}@{baud}")
        try:
            import serial  # noqa: PLC0415 — optional dependency, imported on use
        except ImportError as e:  # pragma: no cover - environment dependent
            raise LinkError(
                "SerialLink needs pyserial: pip install pyserial"
            ) from e
        try:
            self._port = serial.Serial(
                device, baudrate=baud, bytesize=8, parity="N", stopbits=1,
                timeout=0, write_timeout=connect_timeout, rtscts=False, dsrdtr=False,
            )
        except Exception as e:  # serial.SerialException and friends
            raise LinkError(f"cannot open {device}: {e}") from e

    def _send_bytes(self, data: bytes) -> None:
        try:
            self._port.write(data)
            self._port.flush()
        except Exception as e:
            raise LinkError(f"send failed on {self.description}: {e}") from e

    def _recv_bytes(self, timeout: float) -> bytes:
        if timeout <= 0:
            return b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                waiting = self._port.in_waiting
                if waiting:
                    return self._port.read(waiting)
            except Exception as e:
                raise LinkError(f"recv failed on {self.description}: {e}") from e
            time.sleep(0.005)
        return b""

    def _close(self) -> None:
        try:
            self._port.close()
        except Exception:
            pass


def open_link(
    host: Optional[str] = None,
    port: int = DEFAULT_TELNET_PORT,
    *,
    device: Optional[str] = None,
    baud: int = DEFAULT_SERIAL_BAUD,
) -> Link:
    """Convenience factory: pass ``host`` for TCP or ``device`` for USB serial."""
    if (host is None) == (device is None):
        raise ValueError("specify exactly one of host= (TCP) or device= (serial)")
    if host is not None:
        return TcpLink(host, port)
    return SerialLink(device, baud)
