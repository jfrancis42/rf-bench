"""
kiss488.py — Hx Engineering KISS-488 Rev 2 Ethernet/USB GPIB adapter.

Everything in this module is implemented against the KISS-488 Rev 2 User Guide
revision 2.13 (firmware 2.65), cached locally under ``rf-bench/docs/`` (not published).
Section references below point into that document.

The adapter is deliberately NOT an instrument driver.  It owns one link, owns
the adapter's global mutable state, and hands out :class:`GPIBDevice` handles —
one per instrument on the bus.  Instrument drivers talk to a device handle and
never touch the adapter.

Two hard constraints from the User Guide drive this design:

1. §9 "Telnet Usage": *"Up to two Telnet sessions can be active
   simultaneously"*, and a client that drops without ``++quit`` leaves the
   socket wedged *"until KISS-488 is reset"*.  Therefore: one link per adapter,
   shared and refcounted via :meth:`KISS488.shared`, with ``++quit`` guaranteed
   on the way out.

2. §11 "IEEE-488 Instrument Address": ``++addr`` is a single, persistent,
   adapter-global setting.  Therefore: address selection happens *inside* a
   locked transaction, so two instruments on one bus cannot interleave.

Known-uncertain items are marked ``VERIFY-ON-HARDWARE`` and listed in
``rf-bench/docs/kiss-488-driver.md`` (local only).
"""

from __future__ import annotations

import atexit
import threading
import weakref
from contextlib import contextmanager
from typing import Dict, Optional, Tuple

from .link import (
    DEFAULT_READ_TIMEOUT,
    DEFAULT_SERIAL_BAUD,
    DEFAULT_TELNET_PORT,
    Link,
    LinkError,
    SerialLink,
    TcpLink,
)


# ---------------------------------------------------------------------------
# Protocol constants (User Guide Rev 2.13, §11)
# ---------------------------------------------------------------------------

#: ``++eos`` bus-terminator codes.
EOS_CRLF = 0
EOS_CR = 1
EOS_LF = 2
EOS_NONE = 3
EOS_OTHER = 4          # reply-only; cannot be set

#: ``++read_tmo_ms`` accepts 1..3000 inclusive. Granularity is 1/300 s.
READ_TMO_MS_MIN = 1
READ_TMO_MS_MAX = 3000

#: Valid GPIB primary addresses for ``++addr``.
ADDR_MIN = 0
ADDR_MAX = 30

#: ``++spy`` modes.
SPY_OFF = 0
SPY_ASCII = 1
SPY_HEX = 2

#: Host-side line terminator for ``++`` commands.
#:
#: VERIFY-ON-HARDWARE. The CR-vs-LF rule in §9 governs whether KISS-488
#: addresses the *instrument* to talk; ``++`` commands are stated in §11 to be
#: *"not passed thru to the instrument, but executed directly within KISS-488"*,
#: so the rule should not apply to them. LF is the Prologix convention and is
#: the safe choice (it cannot trigger an unwanted bus read).
PLUSPLUS_TERMINATOR = b"\n"

#: Host-side terminator that tells KISS-488 to address the instrument to talk
#: and wait for a reply (§9 "Telnet Usage").
CR = b"\r"

#: Host-side terminator that tells KISS-488 to send, then Untalk/Unlisten and
#: leave the bus quiescent — no read attempted (§9 "Telnet Usage").
LF = b"\n"

#: Query strategies — see :class:`KISS488`.
QUERY_EXPLICIT_READ = "read"
QUERY_AUTO = "auto"


class GPIBError(IOError):
    """Raised on an adapter-level protocol failure."""


class GPIBTimeout(GPIBError):
    """Raised when a read produced nothing within the allotted time."""


class KISS488:
    """
    A KISS-488 Rev 2 GPIB adapter.

    Prefer :meth:`shared` over constructing directly — the adapter permits only
    two concurrent Telnet sessions and leaks them on unclean disconnect, so
    every consumer in a process must be routed onto one link.

    ::

        gpib = KISS488.shared("10.1.1.70")
        vna  = gpib.device(16)
        dmm  = gpib.device(22)

    Query strategy
    --------------
    Two ways exist to get a reply off the bus, and which one the hardware
    actually likes is unknown until the adapter is on the bench:

    ``QUERY_EXPLICIT_READ`` (default)
        ``++auto 0``; send the command LF-terminated, then issue ``++read``.
        Deterministic and independent of the adapter's nonvolatile state.

    ``QUERY_AUTO``
        ``++auto 1``; send the command CR-terminated and let KISS-488 address
        the instrument to talk automatically (§9, §11).

    Switch with ``KISS488.shared(host, query_strategy=QUERY_AUTO)`` if the
    default misbehaves on real hardware.
    """

    DEFAULT_PORT = DEFAULT_TELNET_PORT

    # -- shared-instance registry -------------------------------------------

    _registry: Dict[Tuple, "KISS488"] = {}
    _registry_lock = threading.Lock()

    @classmethod
    def shared(cls, host: str, port: int = DEFAULT_TELNET_PORT, **kwargs) -> "KISS488":
        """
        Return the process-wide adapter for ``host:port``, creating it if needed.

        Refcounted: each call increments, each :meth:`close` decrements, and the
        link is torn down (with ``++quit``) only when the count reaches zero.
        ``kwargs`` are honoured on first creation and ignored afterwards.
        """
        key = ("tcp", host, port)
        with cls._registry_lock:
            inst = cls._registry.get(key)
            if inst is None or inst._link.closed:
                inst = cls(TcpLink(host, port), _registry_key=key, **kwargs)
                cls._registry[key] = inst
            inst._refcount += 1
            return inst

    @classmethod
    def shared_serial(
        cls, device: str, baud: int = DEFAULT_SERIAL_BAUD, **kwargs
    ) -> "KISS488":
        """As :meth:`shared`, over the Rev 2 USB serial port."""
        key = ("serial", device, baud)
        with cls._registry_lock:
            inst = cls._registry.get(key)
            if inst is None or inst._link.closed:
                inst = cls(SerialLink(device, baud), _registry_key=key, **kwargs)
                cls._registry[key] = inst
            inst._refcount += 1
            return inst

    @classmethod
    def _forget(cls, key) -> None:
        with cls._registry_lock:
            cls._registry.pop(key, None)

    # -- construction --------------------------------------------------------

    def __init__(
        self,
        link: Link,
        *,
        eoi: bool = True,
        eos: int = EOS_LF,
        read_tmo_ms: Optional[int] = None,
        savecfg: Optional[bool] = False,
        query_strategy: str = QUERY_EXPLICIT_READ,
        cache_address: bool = False,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        _registry_key=None,
    ):
        """
        Args:
            link: an open :class:`~rf_bench.gpib.link.Link`.
            eoi: assert/expect EOI (``++eoi``).
            eos: bus terminator code (``++eos``); one of the ``EOS_*`` constants.
            read_tmo_ms: bus timeout in ms (``++read_tmo_ms``), 1..3000, or None
                to leave the adapter's saved value alone.  **The HP 8712B needs
                more than the 3000 ms ceiling for a full sweep** — leave this
                None and set the web UI's Timeout String to a null string, which
                §5 says switches to inter-byte timeouts with unbounded time to
                first byte.
            savecfg: ``++savecfg``.  Defaults to False so that this driver's
                setup does not rewrite the adapter's nonvolatile configuration
                (and thereby change the behaviour of the browser UI and every
                other client).  Note §11: savecfg resets to 1 at each power-up.
            query_strategy: ``QUERY_EXPLICIT_READ`` or ``QUERY_AUTO``.
            cache_address: skip a redundant ``++addr`` when the address is
                already selected.  Defaults to False: the setting is global and
                a second Telnet session or the web UI can change it behind our
                back, so correctness beats saving one short line per transaction.
            read_timeout: default host-side reply timeout in seconds.
        """
        if query_strategy not in (QUERY_EXPLICIT_READ, QUERY_AUTO):
            raise ValueError(f"unknown query_strategy {query_strategy!r}")

        self._link = link
        self._lock = threading.RLock()
        self._refcount = 0
        self._registry_key = _registry_key
        self._addr: Optional[int] = None
        self._depth = 0
        self._cache_address = cache_address
        self._query_strategy = query_strategy
        self.read_timeout = read_timeout
        self._spying = False
        self._closed = False

        # The adapter emits a sign-on banner ("KISS-488 Revision: 2.65 ...")
        # on Telnet connect (§9). Discard it before issuing anything.
        self._link.reset_input_buffer()

        with self._lock:
            if savecfg is not None:
                self._command(f"++savecfg {int(bool(savecfg))}")
            self._command("++mode 1")  # no-op on KISS-488; kept for portability
            self._command(f"++eoi {int(bool(eoi))}")
            self.set_eos(eos)
            self._command(
                f"++auto {0 if query_strategy == QUERY_EXPLICIT_READ else 1}"
            )
            if read_tmo_ms is not None:
                self.set_read_timeout_ms(read_tmo_ms)

        self._finalizer = weakref.finalize(self, _quit_link, link)
        atexit.register(self._atexit_close)

    # -- low-level primitives (call with the lock held) ----------------------

    def _command(self, text: str) -> None:
        """Send a ``++`` command; no reply expected."""
        self._link.write_line(text, PLUSPLUS_TERMINATOR)

    def _command_query(self, text: str, timeout: Optional[float] = None) -> str:
        """Send a ``++`` command that replies, and return the reply."""
        self._link.write_line(text, PLUSPLUS_TERMINATOR)
        return self._link.read_line(timeout if timeout is not None else self.read_timeout)

    def _select(self, address: int) -> None:
        """Point the adapter at ``address``. Caller must hold the lock."""
        _validate_address(address)
        if self._cache_address and self._addr == address:
            return
        self._command(f"++addr {address}")
        self._addr = address

    @contextmanager
    def transaction(self, address: int):
        """
        Hold the adapter lock and select ``address`` for the duration.

        Every device-level operation runs inside one of these.  Nested use from
        the same thread is safe (the lock is reentrant) but nesting *different*
        addresses is a bug — the inner selection would leak out to the caller,
        so it is rejected.
        """
        if self._closed:
            raise GPIBError("adapter is closed")
        with self._lock:
            if self._spying:
                raise GPIBError(
                    "adapter is in spy mode; issue spy(SPY_OFF) before bus control"
                )
            # Only a genuinely nested transaction needs its selection restored;
            # at the top level the next transaction sets the address itself, so
            # restoring would just put a redundant ++addr on the wire.
            outer = self._addr if self._depth > 0 else None
            self._depth += 1
            self._select(address)
            try:
                yield self
            finally:
                self._depth -= 1
                if outer is not None and outer != address:
                    try:
                        self._select(outer)
                    except (LinkError, GPIBError):
                        pass

    # -- instrument I/O (used by GPIBDevice) ---------------------------------

    def write(self, address: int, command: str, expect_reply: bool = False) -> None:
        """
        Send ``command`` to the instrument at ``address``.

        ``expect_reply`` selects the host-side terminator per §9: CR makes
        KISS-488 address the instrument to talk and wait; LF makes it send and
        then Untalk/Unlisten, leaving the bus quiescent.  Sending a no-reply
        command (``*CLS``) with CR is the documented way to hang for the whole
        timeout and light the instrument's error LED — hence the explicit flag.
        """
        with self.transaction(address):
            self._link.write_line(command, CR if expect_reply else LF)

    def read(
        self,
        address: int,
        timeout: Optional[float] = None,
        until: Optional[str] = None,
    ) -> str:
        """
        Read a pending reply from the instrument at ``address``.

        Args:
            until: ``None`` for normal termination, ``"EOI"`` to read until EOI
                is asserted, or a single character to read up to that character
                (``++read`` parameter forms, §11).
        """
        with self.transaction(address):
            arg = ""
            if until is not None:
                arg = " EOI" if str(until).upper() == "EOI" else f" {ord(str(until)[0])}"
            self._command(f"++read{arg}")
            return self._link.read_line(
                timeout if timeout is not None else self.read_timeout
            )

    def query(
        self,
        address: int,
        command: str,
        timeout: Optional[float] = None,
        until: Optional[str] = None,
    ) -> str:
        """Send ``command`` and return the instrument's reply, atomically."""
        with self.transaction(address):
            if self._query_strategy == QUERY_AUTO:
                self._link.write_line(command, CR)
            else:
                self._link.write_line(command, LF)
                arg = ""
                if until is not None:
                    arg = (
                        " EOI" if str(until).upper() == "EOI"
                        else f" {ord(str(until)[0])}"
                    )
                self._command(f"++read{arg}")
            return self._link.read_line(
                timeout if timeout is not None else self.read_timeout
            )

    def query_lines(
        self, address: int, command: str, idle: float = 0.4, timeout: float = 5.0
    ) -> str:
        """
        Send ``command`` and collect a multi-line reply until the bus goes idle.

        For replies with no single-line terminator — e.g. the Solartron 7151's
        ``E`` (echoback of all settings) command.
        """
        with self.transaction(address):
            if self._query_strategy == QUERY_AUTO:
                self._link.write_line(command, CR)
            else:
                self._link.write_line(command, LF)
                self._command("++read")
            return self._link.read_until_idle(idle=idle, timeout=timeout)

    # -- bus / adapter control ----------------------------------------------

    def selected_device_clear(self, address: int) -> None:
        """``++clr`` — Selected Device Clear (SDC) to one instrument."""
        with self.transaction(address):
            self._command("++clr")

    def trigger(self, address: int) -> None:
        """``++trg`` — Group Execute Trigger (GET)."""
        with self.transaction(address):
            self._command("++trg")

    def local(self, address: int) -> None:
        """``++loc`` — Go To Local (GTL): restore front-panel control."""
        with self.transaction(address):
            self._command("++loc")

    def local_lockout(self, address: int) -> None:
        """``++llo`` — Local Lockout: instrument responds only to the bus."""
        with self.transaction(address):
            self._command("++llo")

    def interface_clear(self) -> None:
        """``++ifc`` — assert IFC; all devices unaddressed, KISS-488 resumes
        System Controller.  Not address-scoped, so it invalidates the cached
        address selection."""
        with self._lock:
            self._command("++ifc")
            self._addr = None

    def serial_poll(self, address: int = None):
        """
        Not available.

        The KISS-488 command set (User Guide Rev 2.13, §11) has **no**
        ``++spoll`` and no other serial-poll primitive.  GPIB serial poll and
        therefore SRQ-driven waiting are simply not reachable through this
        adapter; use instrument-specific status commands and host-side polling.
        """
        raise NotImplementedError(
            "KISS-488 provides no serial-poll command (no ++spoll in the Rev 2.13 "
            "command set). Use the instrument's own status query and poll on the host."
        )

    def set_address(self, address: int) -> None:
        """Set ``++addr`` explicitly. Prefer :meth:`transaction`."""
        with self._lock:
            self._select(address)

    def get_address(self) -> int:
        """Query ``++addr`` from the adapter (authoritative, not the cache)."""
        with self._lock:
            resp = self._command_query("++addr")
            try:
                addr = int(resp.strip())
            except ValueError as e:
                raise GPIBError(f"unexpected ++addr reply: {resp!r}") from e
            self._addr = addr
            return addr

    def set_eos(self, code: int) -> None:
        """``++eos`` — bus terminator. One of ``EOS_CRLF/CR/LF/NONE``."""
        if code not in (EOS_CRLF, EOS_CR, EOS_LF, EOS_NONE):
            raise ValueError(
                f"eos must be one of 0 (CRLF), 1 (CR), 2 (LF), 3 (none); got {code!r}"
            )
        with self._lock:
            self._command(f"++eos {int(code)}")

    def set_eoi(self, enabled: bool) -> None:
        """``++eoi`` — send/expect EOI at end of message."""
        with self._lock:
            self._command(f"++eoi {int(bool(enabled))}")

    def set_auto(self, enabled: bool) -> None:
        """
        ``++auto`` — auto-read-after-write.

        Warning (§11): this setting is **nonvolatile**, is shared across the
        HTTP, Telnet and USB-serial interfaces, and persists across reset and
        power cycle.  Switching 0→1 also auto-fetches any pending data, which
        may provoke a bus timeout when there is none.
        """
        with self._lock:
            self._command(f"++auto {int(bool(enabled))}")
            self._query_strategy = QUERY_AUTO if enabled else QUERY_EXPLICIT_READ

    def set_eot(self, enabled: bool, char: Optional[int] = None) -> None:
        """``++eot_enable`` / ``++eot_char`` — flag EOI in the host byte stream."""
        with self._lock:
            if char is not None:
                if not 0 <= int(char) <= 255:
                    raise ValueError(f"eot_char must be 0..255, got {char!r}")
                self._command(f"++eot_char {int(char)}")
            self._command(f"++eot_enable {int(bool(enabled))}")

    def set_read_timeout_ms(self, ms: int) -> None:
        """
        ``++read_tmo_ms`` — bus timeout, **1..3000 ms only** (§11).

        Granularity is 1/300 s, so the adapter selects the nearest achievable
        value (100 → 99).  Anything needing longer than 3 s must instead rely on
        the null Timeout String mode described in §5.
        """
        ms = int(ms)
        if not READ_TMO_MS_MIN <= ms <= READ_TMO_MS_MAX:
            raise ValueError(
                f"++read_tmo_ms accepts {READ_TMO_MS_MIN}..{READ_TMO_MS_MAX} ms "
                f"(KISS-488 hard limit), got {ms}. For longer instrument "
                "operations set the web UI Timeout String to a null string and "
                "raise the host-side read timeout instead."
            )
        with self._lock:
            self._command(f"++read_tmo_ms {ms}")

    def set_savecfg(self, enabled: bool) -> None:
        """``++savecfg`` — persist ``++`` config changes to NVM. Resets to 1 at power-up."""
        with self._lock:
            self._command(f"++savecfg {int(bool(enabled))}")

    def factory_reset(self) -> None:
        """``++factory`` — reset all NVM settings, saved data and screen captures."""
        with self._lock:
            self._command("++factory")
            self._addr = None

    def reset(self):
        """
        Not available.

        ``++rst`` is documented as NOT IMPLEMENTED (§11) — deliberately, so a
        remote attacker cannot force a reset and load hostile firmware.  A power
        cycle is required for a full reset.
        """
        raise NotImplementedError(
            "KISS-488 does not implement ++rst (deliberate; see User Guide Rev 2.13 "
            "§11 'Reset'). Power-cycle the adapter instead."
        )

    # -- adapter identification ---------------------------------------------

    def version(self) -> str:
        """``++ver`` — firmware revision and build date."""
        with self._lock:
            return self._command_query("++ver")

    def ip_address(self) -> str:
        """``++ip`` — currently assigned IP address."""
        with self._lock:
            return self._command_query("++ip")

    def mac_address(self) -> str:
        """``++mac`` — permanent MAC address."""
        with self._lock:
            return self._command_query("++mac")

    def firmware_revision(self) -> Optional[float]:
        """
        Parse ``++ver`` into a float, or None if it cannot be read.

        Spy mode needs >= 2.64, and nonvolatile spy needs >= 2.65.
        """
        import re

        m = re.search(r"(\d+\.\d+)", self.version())
        return float(m.group(1)) if m else None

    # -- spy mode ------------------------------------------------------------

    def spy(self, mode: int = SPY_ASCII) -> None:
        """
        ``++spy`` — bus analyzer. ``SPY_OFF`` / ``SPY_ASCII`` / ``SPY_HEX``.

        While spying, the adapter is not a controller: :meth:`transaction` and
        everything built on it will refuse to run.  Prefer
        :func:`rf_bench.gpib.spy.spy_session`, which guarantees ``++spy 0`` on
        exit — from firmware 2.65 the setting is nonvolatile, so an adapter left
        spying comes back up spying after a power cycle.
        """
        if mode not in (SPY_OFF, SPY_ASCII, SPY_HEX):
            raise ValueError(f"spy mode must be 0, 1 or 2; got {mode!r}")
        with self._lock:
            self._command(f"++spy {int(mode)}")
            self._spying = mode != SPY_OFF
            if self._spying:
                self._addr = None

    @property
    def spying(self) -> bool:
        return self._spying

    def read_spy(self, idle: float = 0.5, timeout: float = 5.0) -> str:
        """Collect raw spy output. Returns "" if the bus was quiet."""
        with self._lock:
            if not self._spying:
                raise GPIBError("not in spy mode; call spy(SPY_ASCII) first")
            return self._link.read_until_idle(idle=idle, timeout=timeout)

    # -- devices -------------------------------------------------------------

    def device(self, address: int, **kwargs):
        """Return a :class:`~rf_bench.gpib.device.GPIBDevice` for ``address``."""
        from .device import GPIBDevice  # circular at module scope

        _validate_address(address)
        return GPIBDevice(self, address, **kwargs)

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        """
        Release one reference; tear the link down when the last one goes.

        Sends ``++quit`` first — §9 warns that a Telnet client which drops
        without it wedges one of the adapter's two sessions until reset.
        """
        with KISS488._registry_lock:
            if self._refcount > 0:
                self._refcount -= 1
            if self._refcount > 0:
                return
            if self._registry_key is not None:
                KISS488._registry.pop(self._registry_key, None)
        self._teardown()

    def close_now(self) -> None:
        """Force teardown regardless of refcount."""
        with KISS488._registry_lock:
            self._refcount = 0
            if self._registry_key is not None:
                KISS488._registry.pop(self._registry_key, None)
        self._teardown()

    def _teardown(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            with self._lock:
                if self._spying:
                    try:
                        self._command(f"++spy {SPY_OFF}")
                    except LinkError:
                        pass
                    self._spying = False
        finally:
            self._finalizer.detach()
            _quit_link(self._link)
            try:
                atexit.unregister(self._atexit_close)
            except Exception:
                pass

    def _atexit_close(self) -> None:  # pragma: no cover - interpreter shutdown
        try:
            self.close_now()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self) -> str:
        return (
            f"<KISS488 {self._link.description} addr={self._addr} "
            f"refs={self._refcount}{' spying' if self._spying else ''}>"
        )


def _quit_link(link: Link) -> None:
    """Send ``++quit`` and close. Safe to call more than once."""
    if link.closed:
        return
    try:
        link.write_line("++quit", PLUSPLUS_TERMINATOR)
    except (LinkError, OSError):
        pass
    link.close()


def _validate_address(address: int) -> None:
    if not isinstance(address, int) or isinstance(address, bool):
        raise TypeError(f"GPIB address must be an int, got {address!r}")
    if not ADDR_MIN <= address <= ADDR_MAX:
        raise ValueError(
            f"GPIB primary address must be {ADDR_MIN}..{ADDR_MAX}, got {address}"
        )
