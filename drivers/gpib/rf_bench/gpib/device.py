"""
device.py — a handle to one instrument on a GPIB bus.

Instrument drivers take a :class:`GPIBDevice` (or anything exposing the same
``write``/``read``/``query`` surface) and never touch the adapter.  Every method
here runs inside an adapter transaction, so address selection and the
send/receive pair are atomic with respect to other instruments on the bus.
"""

from __future__ import annotations

from typing import Optional


class GPIBDevice:
    """
    One instrument at one GPIB primary address.

    ::

        gpib = KISS488.shared("10.1.1.70")
        vna  = HP8712B(gpib.device(16))
        dmm  = Solartron7151(gpib.device(22))

    The device holds a reference on the adapter; :meth:`close` releases it and
    the adapter's link goes away when the last device closes.
    """

    def __init__(
        self,
        adapter,
        address: int,
        *,
        name: Optional[str] = None,
        read_timeout: Optional[float] = None,
    ):
        self._adapter = adapter
        self.address = address
        self.name = name or f"gpib{address}"
        self.read_timeout = read_timeout
        self._closed = False

    # -- I/O -----------------------------------------------------------------

    def write(self, command: str, expect_reply: bool = False) -> None:
        """
        Send ``command``.

        ``expect_reply=False`` (the default) terminates the host line with LF,
        which makes the adapter send and then leave the bus quiescent.  Set it
        True only when using the adapter's automatic-read path.
        """
        self._check_open()
        self._adapter.write(self.address, command, expect_reply=expect_reply)

    def read(self, timeout: Optional[float] = None, until: Optional[str] = None) -> str:
        """Read one pending reply. ``until="EOI"`` reads until EOI is asserted."""
        self._check_open()
        return self._adapter.read(self.address, self._timeout(timeout), until=until)

    def query(
        self, command: str, timeout: Optional[float] = None, until: Optional[str] = None
    ) -> str:
        """Send ``command`` and return its reply, as one atomic bus transaction."""
        self._check_open()
        return self._adapter.query(
            self.address, command, self._timeout(timeout), until=until
        )

    def query_lines(self, command: str, idle: float = 0.4, timeout: float = 5.0) -> str:
        """Send ``command`` and collect a multi-line reply until the bus goes idle."""
        self._check_open()
        return self._adapter.query_lines(
            self.address, command, idle=idle, timeout=timeout
        )

    # -- bus control ---------------------------------------------------------

    def clear(self) -> None:
        """Selected Device Clear (SDC)."""
        self._check_open()
        self._adapter.selected_device_clear(self.address)

    def trigger(self) -> None:
        """Group Execute Trigger (GET)."""
        self._check_open()
        self._adapter.trigger(self.address)

    def local(self) -> None:
        """Go To Local — restore front-panel control."""
        self._check_open()
        self._adapter.local(self.address)

    def local_lockout(self) -> None:
        """Local Lockout — instrument responds only to the bus."""
        self._check_open()
        self._adapter.local_lockout(self.address)

    def serial_poll(self):
        """Not available on KISS-488 — see :meth:`KISS488.serial_poll`."""
        return self._adapter.serial_poll(self.address)

    # -- passthroughs --------------------------------------------------------

    @property
    def adapter(self):
        return self._adapter

    def transaction(self):
        """
        Hold the bus for a multi-command sequence.

        ::

            with dev.transaction():
                dev.write("T0")
                dev.write("G")
                value = dev.read()

        Without this, another thread's instrument could interleave between the
        individual calls.
        """
        return self._adapter.transaction(self.address)

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        """Release this device's reference on the adapter."""
        if not self._closed:
            self._closed = True
            self._adapter.close()

    @property
    def closed(self) -> bool:
        return self._closed

    def _check_open(self) -> None:
        if self._closed:
            raise IOError(f"device {self.name} is closed")

    def _timeout(self, override: Optional[float]) -> Optional[float]:
        return override if override is not None else self.read_timeout

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self) -> str:
        return f"<GPIBDevice {self.name} addr={self.address} on {self._adapter!r}>"
