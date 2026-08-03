"""
spy.py — decoder for KISS-488 Spy mode (bus analyzer).

Spy mode (``++spy``, firmware 2.64+) makes the adapter eavesdrop on every
transaction on the IEEE-488 bus, including traffic driven by another controller
or by KISS-488's own web UI Control page.  The User Guide Rev 2.13 §12 says it
has negligible electrical impact and does not alter transfers except by possibly
throttling them.

This is the fastest way to learn what an instrument actually wants: drive it
from the web UI, capture the bus, and diff against what a driver emits.

Wire formats (§12)
------------------
ASCII mode (``++spy 1``)
    Printable ASCII (0x20–0x7F) rendered literally; other bytes as two hex
    digits in arrow brackets, e.g. ``<1F>``.  Bytes carried with ATN asserted
    are prefixed ``!`` and rendered as the standard three-uppercase-letter
    mnemonic where one exists; ``LAG``/``TAG`` are followed by the one- or
    two-digit decimal address.  Bytes with EOI asserted are suffixed ``]``
    followed by CR-LF.

Hex mode (``++spy 2``)
    Every byte as two hex digits, space separated.  ATN bytes prefixed ``[``;
    EOI bytes suffixed ``]`` followed by CR-LF.

VERIFY-ON-HARDWARE
    The decoders below were written from the prose above; no captured sample
    was available.  Both are deliberately tolerant — unrecognised tokens become
    ``kind="unknown"`` events rather than exceptions, so a format surprise
    degrades into visible noise instead of a crash.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, List, Optional

from .kiss488 import SPY_ASCII, SPY_HEX, SPY_OFF


# ---------------------------------------------------------------------------
# IEEE-488.1 command bytes (used with ATN asserted)
# ---------------------------------------------------------------------------

#: Universal and addressed commands, by byte value.
GPIB_COMMANDS = {
    0x01: ("GTL", "Go To Local"),
    0x04: ("SDC", "Selected Device Clear"),
    0x05: ("PPC", "Parallel Poll Configure"),
    0x08: ("GET", "Group Execute Trigger"),
    0x09: ("TCT", "Take Control"),
    0x11: ("LLO", "Local Lockout"),
    0x14: ("DCL", "Device Clear"),
    0x15: ("PPU", "Parallel Poll Unconfigure"),
    0x18: ("SPE", "Serial Poll Enable"),
    0x19: ("SPD", "Serial Poll Disable"),
    0x3F: ("UNL", "Unlisten"),
    0x5F: ("UNT", "Untalk"),
}

#: Mnemonics that carry a decimal GPIB address suffix.
ADDRESSED_GROUPS = {"LAG", "TAG", "SCG"}


def classify_command_byte(value: int) -> tuple:
    """
    Map an ATN-asserted byte to ``(mnemonic, address_or_None, description)``.

    Address groups: LAG 0x20–0x3E, TAG 0x40–0x5E, SCG 0x60–0x7E.  UNL (0x3F)
    and UNT (0x5F) are the group escapes and are looked up first.
    """
    if value in GPIB_COMMANDS:
        mnem, desc = GPIB_COMMANDS[value]
        return (mnem, None, desc)
    if 0x20 <= value <= 0x3E:
        return ("LAG", value - 0x20, "Listen Address")
    if 0x40 <= value <= 0x5E:
        return ("TAG", value - 0x40, "Talk Address")
    if 0x60 <= value <= 0x7E:
        return ("SCG", value - 0x60, "Secondary Command")
    return ("?", None, f"undefined command byte 0x{value:02X}")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@dataclass
class SpyEvent:
    """One decoded item from the spy stream."""

    kind: str                              # "command" | "data" | "unknown"
    raw: str                               # the token(s) as they appeared
    text: str = ""                         # decoded payload, for data events
    data: bytes = b""                      # payload bytes, for data events
    mnemonic: Optional[str] = None         # for command events
    address: Optional[int] = None          # for LAG / TAG / SCG
    description: str = ""
    eoi: bool = False                      # EOI asserted on the final byte

    def __str__(self) -> str:
        if self.kind == "command":
            if self.address is not None:
                return f"!{self.mnemonic} {self.address}"
            return f"!{self.mnemonic}"
        if self.kind == "data":
            return repr(self.text) + ("]" if self.eoi else "")
        return f"?{self.raw!r}"


@dataclass
class SpyTranscript:
    """A decoded capture, plus convenience views over it."""

    events: List[SpyEvent] = field(default_factory=list)
    raw: str = ""

    def commands(self) -> List[SpyEvent]:
        return [e for e in self.events if e.kind == "command"]

    def data(self) -> List[SpyEvent]:
        return [e for e in self.events if e.kind == "data"]

    def messages(self) -> List[str]:
        """Data payloads split at EOI — i.e. one entry per complete message."""
        out, cur = [], []
        for e in self.events:
            if e.kind != "data":
                continue
            cur.append(e.text)
            if e.eoi:
                out.append("".join(cur))
                cur = []
        if cur:
            out.append("".join(cur))
        return out

    def addressed(self) -> List[int]:
        """GPIB addresses seen in LAG/TAG traffic, in order of first appearance."""
        seen, out = set(), []
        for e in self.commands():
            if e.mnemonic in ("LAG", "TAG") and e.address is not None:
                if e.address not in seen:
                    seen.add(e.address)
                    out.append(e.address)
        return out

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterator[SpyEvent]:
        return iter(self.events)

    def pretty(self) -> str:
        return "\n".join(str(e) for e in self.events)


# ---------------------------------------------------------------------------
# ASCII-mode decoding
# ---------------------------------------------------------------------------

_ASCII_TOKEN = re.compile(
    r"""
      !(?P<mnem>[A-Z?]{2,3})(?:\s*(?P<addr>\d{1,2}))?   # !UNT, !LAG 16
    | <(?P<hex>[0-9A-Fa-f]{2})>                          # <1F>
    | (?P<eoi>\])                                        # EOI marker
    | (?P<text>[^!<\]\r\n]+)                             # literal run
    | (?P<nl>[\r\n]+)
    """,
    re.VERBOSE,
)


def decode_ascii(stream: str) -> SpyTranscript:
    """Decode ``++spy 1`` output into a :class:`SpyTranscript`."""
    transcript = SpyTranscript(raw=stream)
    pending: Optional[SpyEvent] = None

    def flush():
        nonlocal pending
        if pending is not None:
            transcript.events.append(pending)
            pending = None

    for m in _ASCII_TOKEN.finditer(stream):
        if m.group("mnem") is not None:
            flush()
            mnem = m.group("mnem")
            addr = int(m.group("addr")) if m.group("addr") is not None else None
            desc = ""
            for value, (known, description) in GPIB_COMMANDS.items():  # noqa: B007
                if known == mnem:
                    desc = description
                    break
            if not desc and mnem in ADDRESSED_GROUPS:
                desc = {"LAG": "Listen Address", "TAG": "Talk Address",
                        "SCG": "Secondary Command"}[mnem]
            transcript.events.append(
                SpyEvent(
                    kind="command", raw=m.group(0), mnemonic=mnem,
                    address=addr, description=desc,
                )
            )
        elif m.group("hex") is not None:
            byte = bytes([int(m.group("hex"), 16)])
            if pending is None:
                pending = SpyEvent(kind="data", raw="", text="", data=b"")
            pending.raw += m.group(0)
            pending.data += byte
            pending.text += byte.decode("ascii", errors="replace")
        elif m.group("eoi") is not None:
            if pending is None:
                pending = SpyEvent(kind="data", raw="", text="", data=b"")
            pending.raw += "]"
            pending.eoi = True
            flush()
        elif m.group("text") is not None:
            chunk = m.group("text")
            if pending is None:
                pending = SpyEvent(kind="data", raw="", text="", data=b"")
            pending.raw += chunk
            pending.text += chunk
            pending.data += chunk.encode("ascii", errors="replace")
        # newlines are structural only; they follow an EOI marker

    flush()
    return transcript


# ---------------------------------------------------------------------------
# Hex-mode decoding
# ---------------------------------------------------------------------------

_HEX_TOKEN = re.compile(r"(?P<atn>\[)?(?P<hex>[0-9A-Fa-f]{2})(?P<eoi>\])?")


def decode_hex(stream: str) -> SpyTranscript:
    """Decode ``++spy 2`` output into a :class:`SpyTranscript`."""
    transcript = SpyTranscript(raw=stream)
    pending: Optional[SpyEvent] = None

    def flush():
        nonlocal pending
        if pending is not None:
            transcript.events.append(pending)
            pending = None

    for m in _HEX_TOKEN.finditer(stream):
        value = int(m.group("hex"), 16)
        eoi = m.group("eoi") is not None
        if m.group("atn") is not None:
            flush()
            mnem, addr, desc = classify_command_byte(value)
            transcript.events.append(
                SpyEvent(
                    kind="command", raw=m.group(0), mnemonic=mnem, address=addr,
                    description=desc, data=bytes([value]), eoi=eoi,
                )
            )
            continue
        if pending is None:
            pending = SpyEvent(kind="data", raw="", text="", data=b"")
        pending.raw += m.group(0)
        pending.data += bytes([value])
        pending.text += chr(value) if 0x20 <= value <= 0x7E else f"<{value:02X}>"
        if eoi:
            pending.eoi = True
            flush()

    flush()
    return transcript


def decode(stream: str, mode: int = SPY_ASCII) -> SpyTranscript:
    """Decode a spy capture in either mode."""
    if mode == SPY_ASCII:
        return decode_ascii(stream)
    if mode == SPY_HEX:
        return decode_hex(stream)
    raise ValueError(f"mode must be SPY_ASCII (1) or SPY_HEX (2); got {mode!r}")


# ---------------------------------------------------------------------------
# Live capture
# ---------------------------------------------------------------------------

@contextmanager
def spy_session(adapter, mode: int = SPY_ASCII):
    """
    Put ``adapter`` into spy mode for the duration of the block.

    ``++spy 0`` is issued on exit **including on exception** — from firmware
    2.65 the setting is nonvolatile (§12), so an adapter left spying comes back
    up spying after a power cycle and will refuse to control the bus.

    ::

        with spy_session(gpib) as spy:
            transcript = spy.capture(seconds=10)
        print(transcript.pretty())
    """
    adapter.spy(mode)
    try:
        yield _SpyCapture(adapter, mode)
    finally:
        adapter.spy(SPY_OFF)


class _SpyCapture:
    """Handle yielded by :func:`spy_session`."""

    def __init__(self, adapter, mode: int):
        self._adapter = adapter
        self._mode = mode

    def capture(self, seconds: float = 5.0, idle: float = 0.5) -> SpyTranscript:
        """Collect for up to ``seconds``, stopping early after ``idle`` quiet."""
        raw = self._adapter.read_spy(idle=idle, timeout=seconds)
        return decode(raw, self._mode)

    def capture_raw(self, seconds: float = 5.0, idle: float = 0.5) -> str:
        """Collect without decoding — for saving a ground-truth sample to disk."""
        return self._adapter.read_spy(idle=idle, timeout=seconds)
