# rf-bench-drivers-gpib

GPIB (IEEE-488 / HPIB) bus transport for the [rf-bench](https://github.com/jfrancis42/rf-bench)
instrument collection.

This package is the **bus**, not an instrument. It exists because GPIB is the
first link on the bench where several instruments share one physical connection
and the adapter carries global mutable state that must be set per transaction.

```python
from rf_bench.gpib import KISS488
from rf_bench.hp import HP8712B
from rf_bench.solartron import Solartron7151

gpib = KISS488.shared("10.1.1.70")     # one socket, refcounted
vna  = HP8712B(gpib.device(16))
dmm  = Solartron7151(gpib.device(22))

print(vna.identify())
print(dmm.measure_vdc())
```

Instrument drivers take a device handle and never touch sockets or `++`
commands. Any adapter exposing the same surface — a Prologix GPIB-ETHERNET, an
AR488, an NI GPIB-USB-HS — can be dropped in without changing a driver.

> **Status: no hardware contact.** Written against the KISS-488 Rev 2 User Guide
> revision 2.13 and unit-tested against an in-process emulator. Items still to
> confirm on real hardware are marked `VERIFY-ON-HARDWARE` in the source and
> listed in the local design notes in `docs/kiss-488-driver.md` (not published).

## Install

```bash
pip install rf-bench-drivers-gpib          # TCP only
pip install rf-bench-drivers-gpib[serial]  # + USB serial (pyserial)
```

## Supported adapter

**Hx Engineering KISS-488 Rev 2** — Ethernet (Telnet) and, on Rev 2 hardware,
USB serial. Implements a *subset* of the Prologix command set, Controller mode
only.

| | |
|---|---|
| Telnet | **TCP port 23** by default, configurable in the web UI |
| USB serial | 115200 8N1, no handshake, FTDI |
| Web UI | port 80 — configuration, Control page, Capture, Graphs |
| Announce | UDP :30303 broadcast (IP / NetBIOS name / MAC / firmware) |

Port 23, **not 1234** — 1234 is the Prologix GPIB-ETHERNET port.

## Why the adapter is shared

Two facts from the User Guide force the design:

1. **Only two Telnet sessions exist**, and a client that drops without `++quit`
   leaves the socket wedged *"until KISS-488 is reset"*. So there is one link
   per adapter, obtained through `KISS488.shared()`, refcounted, with `++quit`
   guaranteed on teardown.
2. **`++addr` is a single, persistent, adapter-global setting.** So address
   selection happens *inside* a locked transaction. Two instruments on one bus
   cannot interleave; without this you eventually read the DMM's reply into the
   VNA's trace buffer.

```python
gpib = KISS488.shared("10.1.1.70")   # first caller opens the link
same = KISS488.shared("10.1.1.70")   # second caller gets the same object
assert gpib is same
```

## API

### `KISS488`

```python
KISS488.shared(host, port=23, **kw)      # refcounted TCP adapter
KISS488.shared_serial(device, baud=115200, **kw)
adapter.device(address, name=None)       # -> GPIBDevice
adapter.version() / ip_address() / mac_address() / firmware_revision()
adapter.set_eos(code) / set_eoi(b) / set_auto(b) / set_eot(b, char)
adapter.set_read_timeout_ms(ms)          # 1..3000 only
adapter.interface_clear()                # ++ifc
adapter.spy(mode)                        # SPY_OFF / SPY_ASCII / SPY_HEX
adapter.close()                          # release one reference
```

### `GPIBDevice`

```python
dev.write(cmd, expect_reply=False)
dev.read(timeout=None, until=None)       # until="EOI" or a single character
dev.query(cmd, timeout=None)
dev.query_lines(cmd)                     # multi-line, read until idle
dev.clear() / trigger() / local() / local_lockout()
with dev.transaction():                  # hold the bus across several calls
    ...
```

### Query strategies

Two ways exist to pull a reply off the bus. Which one real hardware prefers is
unknown until the adapter is on the bench, so both are implemented:

| Strategy | Mechanism |
|---|---|
| `QUERY_EXPLICIT_READ` (default) | `++auto 0`; send LF-terminated, then `++read` |
| `QUERY_AUTO` | `++auto 1`; send CR-terminated, adapter reads automatically |

```python
gpib = KISS488.shared("10.1.1.70", query_strategy=QUERY_AUTO)
```

The CR-vs-LF distinction is a real protocol feature, not formatting: a command
terminated with **CR** makes KISS-488 address the instrument to talk and wait
for a reply; terminated with **LF** it sends, then Untalks/Unlistens and reads
nothing. Sending `*CLS` down the CR path is the User Guide's own example of how
to hang for the full timeout and light the instrument's error LED.

## Spy mode — the bus analyzer

`++spy` (firmware 2.64+) makes the adapter eavesdrop on every transaction on the
bus, *including* traffic driven by another controller or by KISS-488's own web
UI. This is the fastest way to learn what an instrument actually wants: drive it
from the front panel or the web UI, capture the bus, and diff against what your
driver emits.

```python
from rf_bench.gpib.spy import spy_session

with spy_session(gpib) as spy:
    transcript = spy.capture(seconds=10)

print(transcript.pretty())
print(transcript.messages())     # payloads split at EOI
print(transcript.addressed())    # GPIB addresses seen in LAG/TAG traffic
```

`spy_session` guarantees `++spy 0` on exit including on exception — from
firmware 2.65 the setting is nonvolatile, so an adapter left spying comes back
up spying and refuses to control the bus.

## Testing without hardware

`rf_bench.gpib.testing` ships a KISS-488 protocol emulator, so drivers built on
this package get real tests before any hardware exists.

```python
from rf_bench.gpib import KISS488
from rf_bench.gpib.testing import FakeInstrument, FakeLink

link = FakeLink()
link.add_instrument(16, FakeInstrument({"*IDN?": "HEWLETT PACKARD,8712B,0,1.0"}))
gpib = KISS488(link)

assert gpib.device(16).query("*IDN?").startswith("HEWLETT")
assert link.commands("++addr") == ["++addr 16"]
```

It is a *protocol* emulator, not an instrument simulator: it proves the plumbing
is right. It cannot tell you whether `:CALC:PAR:MOD S11` is a mnemonic an HP
8712B accepts — only hardware, or a Spy capture, can answer that.

Ready-made fixtures: `fake_hp8712b()`, `fake_solartron7151()`.

## Things the KISS-488 cannot do

| | |
|---|---|
| `++spoll` | **Does not exist.** No GPIB serial poll, therefore no SRQ-driven waiting. Use instrument status commands and poll on the host. |
| `++rst` | Deliberately unimplemented — a remote reset would let an attacker load hostile firmware. Power-cycle instead. |
| `++read_tmo_ms` > 3000 ms | Hard ceiling. For longer operations set the web UI's Timeout String to a *null string*, which switches to inter-byte timeouts with unbounded time to first byte. |
| Device mode | Controller mode only. |

`serial_poll()` and `reset()` raise `NotImplementedError` with the reason rather
than failing silently.

## Running the tests

```bash
cd drivers/gpib
PYTHONPATH=. python3 -m pytest tests -q
```

## License

GPL-3.0-or-later.
