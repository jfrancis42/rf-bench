"""
testing.py — a KISS-488 emulator, so the whole stack runs without hardware.

``FakeLink`` speaks enough of the KISS-488 Rev 2 protocol (User Guide Rev 2.13,
§9 and §11) to exercise the adapter, the device layer, and the instrument
drivers on top of them:

* ``++`` commands are executed by the emulator, never delivered to instruments
* ``++addr`` routes subsequent traffic to a registered :class:`FakeInstrument`
* the CR-vs-LF host terminator selects read-after-write, as §9 describes
* ``++read`` pulls one pending message off the addressed instrument
* every byte written by the host is recorded for assertions

This is a *protocol* emulator, not an instrument simulator: it proves the
plumbing is right.  It cannot tell you whether ``:CALC:PAR:MOD S11`` is the
mnemonic an HP 8712B actually wants — only real hardware, or a Spy-mode
capture, can answer that.

::

    link = FakeLink()
    link.add_instrument(16, FakeInstrument({"*IDN?": "HEWLETT PACKARD,8712B,0,1.0"}))
    gpib = KISS488(link)
    assert gpib.device(16).query("*IDN?").startswith("HEWLETT")
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Union

from .link import Link


DEFAULT_FIRMWARE = "KISS-488 Revision: 2.65"
DEFAULT_BUILD = "Feb 28 2026 06:01:26"


class FakeInstrument:
    """
    A scripted GPIB instrument.

    Args:
        responses: maps a command to its reply.  A value may be a string, a
            list of strings (consumed in order, last one repeating), or a
            callable taking the command and returning a string or None.
        default: reply for unmatched commands; None means "say nothing", which
            is what a real instrument does when addressed to talk with an empty
            output buffer (and what produces the adapter's silent timeout).
        standing: a reply always available to a bare read, even with nothing
            queued.  Models a free-running instrument that overwrites its
            output buffer continuously — e.g. a Solartron 7151 with TRACK ON,
            where the most recent reading is always there for the taking.
        name: for diagnostics.
    """

    def __init__(
        self,
        responses: Optional[Dict[str, Union[str, List[str], Callable]]] = None,
        default: Optional[Union[str, Callable]] = None,
        standing: Optional[Union[str, Callable]] = None,
        name: str = "fake",
    ):
        self.responses = dict(responses or {})
        self.default = default
        self.standing = standing
        self.name = name
        #: every command this instrument received, in order
        self.received: List[str] = []
        #: messages waiting to be read off the bus
        self.output: List[str] = []
        self.cleared = 0
        self.triggered = 0
        self.local_calls = 0
        self.lockout_calls = 0

    # -- bus events ----------------------------------------------------------

    def receive(self, command: str) -> None:
        """Accept a command; queue any reply it produces."""
        self.received.append(command)
        reply = self._lookup(command)
        if reply is not None:
            self.output.append(reply)

    def read(self) -> Optional[str]:
        """Pop one pending message, or the standing reply, or None."""
        if self.output:
            return self.output.pop(0)
        if self.standing is not None:
            return self.standing("") if callable(self.standing) else str(self.standing)
        return None

    def clear(self) -> None:
        self.cleared += 1
        self.output.clear()

    def trigger(self) -> None:
        self.triggered += 1

    def go_to_local(self) -> None:
        self.local_calls += 1

    def local_lockout(self) -> None:
        self.lockout_calls += 1

    # -- helpers -------------------------------------------------------------

    def queue(self, *messages: str) -> "FakeInstrument":
        """Pre-load messages to be read, e.g. an unsolicited tracking reading."""
        self.output.extend(messages)
        return self

    def last(self) -> Optional[str]:
        return self.received[-1] if self.received else None

    def _lookup(self, command: str) -> Optional[str]:
        entry = self.responses.get(command)
        if entry is None:
            for pattern, value in self.responses.items():
                if pattern.startswith("re:") and re.fullmatch(pattern[3:], command):
                    entry = value
                    break
        if entry is None:
            entry = self.default
        if entry is None:
            return None
        if callable(entry):
            return entry(command)
        if isinstance(entry, list):
            if not entry:
                return None
            return entry.pop(0) if len(entry) > 1 else entry[0]
        return str(entry)

    def __repr__(self) -> str:
        return f"<FakeInstrument {self.name} rx={len(self.received)} tx={len(self.output)}>"


class FakeLink(Link):
    """
    In-memory KISS-488 emulator.

    Attributes:
        written: every line the host sent, terminator stripped, in order.
        state: the emulated adapter's nonvolatile-ish settings.
        instruments: address -> :class:`FakeInstrument`.
    """

    def __init__(
        self,
        firmware: str = DEFAULT_FIRMWARE,
        ip: str = "10.1.1.70",
        mac: str = "00:04:A3:0B:00:2A",
        banner: bool = True,
        strict: bool = True,
    ):
        super().__init__("fake://kiss-488")
        self.firmware = firmware
        self.ip = ip
        self.mac = mac
        #: True to raise on a write to an address with no registered instrument
        self.strict = strict

        self.written: List[str] = []
        self.instruments: Dict[int, FakeInstrument] = {}
        self.state: Dict[str, object] = {
            "addr": None,
            "auto": 1,        # §11: auto-read defaults to on
            "eoi": 1,
            "eos": 0,
            "eot_enable": 0,
            "eot_char": 0,
            "read_tmo_ms": 500,
            "savecfg": 1,     # §11: resets to 1 at each power-up
            "spy": 0,
            "quit": False,
        }
        #: lines the emulator has queued for the host to read
        self._out = bytearray()
        #: raw spy text handed back by ``++read`` while spying
        self.spy_stream = ""
        self._partial = bytearray()

        if banner:
            self._emit(firmware)
            self._emit(DEFAULT_BUILD)

    # -- setup ---------------------------------------------------------------

    def add_instrument(self, address: int, instrument: FakeInstrument) -> FakeInstrument:
        self.instruments[address] = instrument
        return instrument

    def instrument(self, address: int) -> Optional[FakeInstrument]:
        return self.instruments.get(address)

    @property
    def address(self) -> Optional[int]:
        return self.state["addr"]

    def commands(self, prefix: str = "") -> List[str]:
        """Host lines, optionally filtered by prefix (e.g. ``"++"``)."""
        return [c for c in self.written if c.startswith(prefix)]

    def instrument_commands(self) -> List[str]:
        """Host lines that were destined for an instrument, not the adapter."""
        return [c for c in self.written if not c.startswith("++")]

    # -- Link interface ------------------------------------------------------

    def _send_bytes(self, data: bytes) -> None:
        self._partial.extend(data)
        while True:
            idx = _find_terminator(self._partial)
            if idx is None:
                return
            end, term = idx
            line = bytes(self._partial[:end]).decode("ascii", errors="replace")
            del self._partial[: end + 1]
            self._handle_line(line, term)

    def _recv_bytes(self, timeout: float) -> bytes:
        # Spy output is unsolicited: once the adapter is spying it pushes bus
        # traffic at the host with no ++read (User Guide Rev 2.13, §12).
        if self.state["spy"] and self.spy_stream:
            self._out.extend(self.spy_stream.encode("ascii", errors="replace"))
            self.spy_stream = ""
        if not self._out:
            return b""
        out = bytes(self._out)
        self._out.clear()
        return out

    def _close(self) -> None:
        self.state["quit"] = True

    # -- emulation -----------------------------------------------------------

    def _emit(self, text: str) -> None:
        self._out.extend(text.encode("ascii", errors="replace") + b"\n")

    def _handle_line(self, line: str, terminator: bytes) -> None:
        line = line.strip("\r")
        self.written.append(line)
        if line.startswith("++"):
            self._handle_adapter(line)
        else:
            self._handle_instrument(line, terminator)

    def _handle_adapter(self, line: str) -> None:
        parts = line[2:].split()
        if not parts:
            return
        cmd = parts[0].lower()
        args = parts[1:]

        def arg_int(default=None):
            return int(args[0]) if args else default

        if cmd == "addr":
            if args:
                value = arg_int()
                if not 0 <= value <= 30:
                    self._emit("ERROR")
                    return
                self.state["addr"] = value
            else:
                self._emit(str(self.state["addr"] if self.state["addr"] is not None else 0))
        elif cmd == "read":
            self._do_read(args)
        elif cmd in ("auto", "eoi", "eos", "eot_enable", "eot_char",
                     "read_tmo_ms", "savecfg"):
            if args:
                self.state[cmd] = arg_int()
            else:
                self._emit(str(self.state[cmd]))
        elif cmd == "spy":
            self.state["spy"] = arg_int(1)
        elif cmd == "mode":
            # §11: accepted silently; always Controller
            if not args:
                self._emit("1")
        elif cmd == "clr":
            self._with_instrument(lambda i: i.clear())
        elif cmd == "trg":
            self._with_instrument(lambda i: i.trigger())
        elif cmd == "loc":
            self._with_instrument(lambda i: i.go_to_local())
        elif cmd == "llo":
            self._with_instrument(lambda i: i.local_lockout())
        elif cmd == "ifc":
            self.state["addr"] = None
        elif cmd == "ver":
            self._emit(f"{self.firmware} {DEFAULT_BUILD}")
        elif cmd == "ip":
            self._emit(self.ip)
        elif cmd == "mac":
            self._emit(self.mac)
        elif cmd == "quit":
            self.state["quit"] = True
        elif cmd == "factory":
            self.state.update({"auto": 1, "eoi": 1, "eos": 0, "savecfg": 1,
                               "spy": 0, "addr": None})
        elif cmd == "rst":
            # §11: NOT IMPLEMENTED on real hardware. Emulate the silence.
            pass
        else:
            self._emit("ERROR")

    def _handle_instrument(self, line: str, terminator: bytes) -> None:
        if self.state["spy"]:
            # While spying the adapter is not a controller.
            return
        inst = self._current()
        if inst is None:
            if self.strict:
                raise AssertionError(
                    f"host wrote {line!r} with ++addr={self.state['addr']!r}, "
                    "but no instrument is registered at that address"
                )
            return
        inst.receive(line)
        # §9/§11: read-after-write happens when the host terminated with CR
        # AND automatic read is enabled.
        if terminator == b"\r" and self.state["auto"]:
            self._pull(inst)

    def _do_read(self, args) -> None:
        if self.state["spy"]:
            if self.spy_stream:
                self._out.extend(self.spy_stream.encode("ascii", errors="replace"))
                self.spy_stream = ""
            return
        inst = self._current()
        if inst is None:
            return
        self._pull(inst)

    def _pull(self, inst: FakeInstrument) -> None:
        message = inst.read()
        if message is not None:
            self._emit(message)
        # else: silent timeout, exactly as a null Timeout String produces (§5)

    def _current(self) -> Optional[FakeInstrument]:
        addr = self.state["addr"]
        return self.instruments.get(addr) if addr is not None else None

    def _with_instrument(self, fn) -> None:
        inst = self._current()
        if inst is not None:
            fn(inst)

    def __repr__(self) -> str:
        return (
            f"<FakeLink addr={self.state['addr']} auto={self.state['auto']} "
            f"instruments={sorted(self.instruments)} lines={len(self.written)}>"
        )


def _find_terminator(buf: bytearray):
    """Return ``(index, terminator_byte)`` of the first CR or LF, or None."""
    for i, byte in enumerate(buf):
        if byte in (0x0A, 0x0D):
            return i, bytes([byte])
    return None


# ---------------------------------------------------------------------------
# Ready-made fixtures
# ---------------------------------------------------------------------------

def fake_hp8712b(name: str = "hp8712b") -> FakeInstrument:
    """
    A minimal HP 8712B stand-in.

    Replies only to commands whose syntax this driver is confident about.
    Anything marked VERIFY-ON-HARDWARE in the driver is deliberately left
    unanswered so a test cannot accidentally "prove" an unverified mnemonic.
    """
    points = {"n": 201}

    def freq_data(_cmd):
        n = points["n"]
        return ",".join(f"{1e6 + i * 1e6:.1f}" for i in range(n))

    def fdat(_cmd):
        return ",".join(f"{-i * 0.1:.4f}" for i in range(points["n"]))

    def sdat(_cmd):
        vals = []
        for i in range(points["n"]):
            vals.append(f"{1.0 - i * 0.001:.6f}")
            vals.append(f"{i * 0.002:.6f}")
        return " ".join(vals)

    def set_points(cmd):
        points["n"] = int(float(cmd.split()[-1]))
        return None

    return FakeInstrument(
        {
            "*IDN?": "HEWLETT PACKARD,8712B,US00000000,1.0",
            "*OPC?": "1",
            ":SENS:FREQ:DATA?": freq_data,
            ":CALC:DATA:FDAT?": fdat,
            ":CALC:DATA:SDAT?": sdat,
            ":CALC:MARK:Y?": "-12.345",
            ":SENS:CORR:STAT?": "1",
            "re::SENS:SWE:POIN .*": set_points,
        },
        name=name,
    )


def fake_solartron7151(name: str = "solartron7151", reading: str = "+ 2.798450 V DC") -> FakeInstrument:
    """
    A minimal Solartron 7151 stand-in.

    The 7151 in TRACK ON mode measures continuously and overwrites its output
    buffer, so a bare read always yields the most recent value — modelled here
    by ``standing``, not by queueing a reply per command.
    """
    return FakeInstrument(
        {
            "E": "M0 R0 I3 T1 U7 N0 D0 Y0 Z0 K0 Q0",
            "!": "ERROR 00 OK",
            "M?": "M0",
            "R?": "R10",
        },
        standing=reading,
        name=name,
    )
