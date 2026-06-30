# rf-bench-drivers-arduino-relay-board

Python driver for the Arduino+W5500 network-controlled 4-channel relay
board. See [`hardware/arduino-relay-board/`](../../hardware/arduino-relay-board/)
for the firmware.

> **Status:** ✅ tested on hardware 2026-06-25 against the board running
> at `10.1.1.36`. Full acceptance test in
> `hardware/arduino-relay-board/test_relays.py` passes against the
> shipped firmware.

---

## Install

```bash
pip install -e ~/Dropbox/build/rf-bench/drivers/arduino-relay-board
```

Once published to PyPI:

```bash
pip install rf-bench-drivers-arduino-relay-board
```

---

## Quick start

```python
from rf_bench.arduino_relay_board import ArduinoRelayBoard

with ArduinoRelayBoard("10.1.1.36") as r:
    print(r.idn())            # N0GQ,ArduinoRelayBoard,1.0,2026,id=1

    r.on(1)                   # energize relay 1
    r.on(3)                   # energize relay 3
    print(f"{r.status():04b}") # → "0101" (relays 1 and 3 on)

    r.pulse_high(2, 250)      # energize relay 2 for 250 ms, then off

    print(r.get_state(1))     # → True
    print(r.status_all())     # → (True, False, True, False)

    r.off(1)
    r.reset()                 # all off
```

---

## API

```python
class ArduinoRelayBoard:
    NUM_RELAYS = 4

    def __init__(self, host, port=5025, timeout=2.0, auto_connect=True): ...
    def connect(self) -> None
    def close(self) -> None

    def idn(self) -> str
    def help(self) -> str

    def on(self, relay: int) -> None                # relay = 1..4
    def off(self, relay: int) -> None

    def pulse_high(self, relay: int, duration_ms: int) -> None
    def pulse_low(self, relay: int, duration_ms: int) -> None

    def get_state(self, relay: int) -> bool
    def status(self) -> int                          # bitmask, bit 0 = relay 1
    def status_all(self) -> tuple[bool, ...]         # length 4

    def reset(self) -> None
    def all_off(self) -> None                        # alias for reset()
```

All methods are thread-safe — internal `threading.Lock` serializes
access to the TCP socket.

### Errors

- `ArduinoRelayBoardError` — board returned `ERR: …`, or the socket
  was closed unexpectedly.
- `ArduinoRelayBoardTimeoutError` — no response within `timeout`
  seconds. Subclass of `ArduinoRelayBoardError`.
- `ValueError` — bad relay index (not 1..4) or non-positive duration.

---

## Pulse semantics

`pulse_high(n, ms)` and `pulse_low(n, ms)` return *immediately*. The
board schedules the revert internally using `millis()`, so the timed
behaviour is independent of network latency or Python-side scheduling.

- `pulse_high(1, 30000)` — relay 1 energized now, de-energized 30 s
  later. The driver returns in milliseconds; the board handles the
  delay.
- `pulse_low(1, 250)` — relay 1 de-energized now, re-energized 250 ms
  later. Useful when a relay was previously commanded `ON`.

A subsequent `on()`, `off()`, or `pulse_*()` on the same relay cancels
any pulse in flight.

---

## Related

- `hardware/arduino-relay-board/` — board firmware.
- `drivers/relay/` — XL9535 I²C 16-channel relay expander (different
  hardware: local I²C via Bus Pirate, not Ethernet).
- `projects/esp32/scpi-relay/` — ESP32+WiFi equivalent.

---

## License

GPL-3.0-or-later, same as the rest of rf-bench.
