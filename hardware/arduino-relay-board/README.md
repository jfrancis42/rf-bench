# arduino-relay-board

Network-controlled 4-channel relay board built from an Arduino Uno R3 +
**Vilros Ethernet R3 shield** (a clone of the Arduino Ethernet Shield R3,
W5100-based, with on-board microSD slot). Speaks a simple line-oriented
ASCII protocol over **TCP port 5025** — every command yields exactly one
response line.

> **Status:** ✅ tested on hardware 2026-06-25. Running at **10.1.1.36** with
> a 4-channel active-HIGH relay module on D5–D8. All commands round-trip
> correctly through `test_relays.py`.

The same sketch also runs unchanged on a W5500 module — the Arduino
`Ethernet` library auto-detects which Wiznet chip is present.
The only practical difference is socket count (W5100 = 4 total, of which
3 are usable for accepted clients; W5500 = 8 total).

---

## Hardware

| Part | Notes |
|------|-------|
| Arduino Uno R3 / Nano / Mega | 5V logic. Any AVR-based board works. |
| Vilros Ethernet R3 shield | Clone of Arduino Ethernet Shield R3 (W5100 + microSD). Stacks on a Uno; works with stock `Ethernet.h` (v2.x). |
| 4-channel relay module | Active-HIGH in the as-shipped sketch (matches the module currently on the bench); flip `RELAY_ACTIVE_HIGH` to `false` for cheap SainSmart-style active-LOW boards. |
| 5V supply for relay coils | Do **not** rely on the Arduino's 5V rail. |

### Wiring

The Vilros R3 shield mates with the Uno's headers — there is no shield
wiring to do. The shield consumes these Arduino pins; the relay control
pins (D5–D8) and serial console (D0/D1) are clear:

| Arduino pin | Used by Vilros R3 shield |
|-------------|--------------------------|
| D4          | microSD card CS |
| D10         | W5100 CS |
| D11         | SPI MOSI (shared) |
| D12         | SPI MISO (shared) |
| D13         | SPI SCK (shared) |
| D2          | W5100 INT (optional; library doesn't use it) |
| ICSP header | SPI passthrough for Mega compatibility |
| 5V / GND    | Shield power |

D4 is driven HIGH in `setup()` to deselect the SD card so it doesn't
fight on the SPI bus during W5100 transfers.

On Mega 2560: SPI is on the ICSP header (D50 MISO / D51 MOSI / D52 SCK).
D10 is still the W5100 CS, D4 is still the SD CS.

**Relay control:**

| Relay | Arduino pin |
|-------|-------------|
| 1 | D5 |
| 2 | D6 |
| 3 | D7 |
| 4 | D8 |

D5–D8 were chosen because they avoid every pin the Vilros R3 shield
uses (D2, D4, D10–D13 plus the ICSP SPI passthrough). D9 is left free
as a margin.

---

## Network

- **DHCP** on power-up. If DHCP fails, falls back to **192.168.1.177**.
- MAC: `02:AB:CD:EF:42:<BOARD_ID>`. Change `BOARD_ID` at the top of
  the sketch if you put more than one of these boards on the same LAN.
- Listens on **TCP port 5025** (the SCPI / rf-bench convention).
- Up to **3 concurrent clients** on W5100 (4 hardware sockets total,
  one consumed by the listening server). On a W5500 you can bump
  `MAX_CLIENTS` in the sketch up to 7.

---

## Protocol

Line-oriented ASCII. Each command is terminated by `\n` (or `\r\n`).
Commands are case-insensitive. Every command produces **exactly one
response line** terminated by `\n`. On success the response is `OK` (or
a value); on failure it starts with `ERR:`.

| Command | Response | Meaning |
|---------|----------|---------|
| `ON <n>` | `OK` | Energize relay `n` (n = 1..4). |
| `OFF <n>` | `OK` | De-energize relay `n`. |
| `PULSEH <n> <ms>` | `OK` | Drive relay `n` HIGH for `ms` milliseconds, then back to LOW. Non-blocking. |
| `PULSEL <n> <ms>` | `OK` | Drive relay `n` LOW for `ms` milliseconds, then back to HIGH. Non-blocking. |
| `STATUS <n>` | `0` or `1` | Query single relay (energized = 1). |
| `STATUS` | `0xH` | Hex bitmask of all four relays. Bit 0 = relay 1. e.g. `0xA` = relays 2 and 4 on. |
| `*IDN?` | `N0GQ,ArduinoRelayBoard,1.0,2026,id=<n>` | Identification. |
| `RESET` (or `*RST`) | `OK` | All relays off, all pulses cancelled. |
| `HELP` (or `?`) | banner ending with `END` | Print command summary. |

**Semantics of "HIGH" and "LOW" in PULSEH/PULSEL:**
"HIGH" and "LOW" refer to the *logical* relay state — HIGH = energized,
LOW = de-energized. The Arduino sketch handles the active-low vs.
active-high inversion at the pin layer.

- `PULSEH 1 250` — energize relay 1, then de-energize after 250 ms.
- `PULSEL 1 250` — de-energize relay 1, then re-energize after 250 ms
  (useful when the relay was previously commanded ON).

A subsequent `ON`/`OFF`/`PULSE*` on the same relay cancels any pulse in
flight.

### Pulses are non-blocking

A `PULSEH 1 30000` (30 second pulse) does **not** stall the network.
The command returns `OK` immediately; the relay reverts 30 s later via
a `millis()`-based scheduler in `loop()`. Other commands keep working.

### Echo / confirmation

Every command — even the side-effecting ones — produces a response
line, so a client that wants confirmation of action receives it on the
same TCP connection it issued the command on. There is no separate
echo channel.

---

## Example session

```
$ nc 192.168.1.177 5025
*IDN?
N0GQ,ArduinoRelayBoard,1.0,2026,id=1
ON 1
OK
ON 3
OK
STATUS
0x5
PULSEH 2 1000
OK
STATUS
0x7
(... 1 second later ...)
STATUS
0x5
OFF 1
OK
OFF 3
OK
STATUS
0x0
```

---

## Building and uploading

1. Open `arduino-relay-board.ino` in the Arduino IDE.
2. Tools → Manage Libraries → install/update **Ethernet** (>= 2.0.0).
3. Tools → Board → your board (Arduino Uno / Nano / Mega 2560).
4. Tools → Port → your USB serial port.
5. Edit `BOARD_ID` if you'll have multiple units on the LAN.
6. Verify `RELAY_ACTIVE_HIGH` matches your module — `true` for the
   current 4-ch board on the bench (drive pin HIGH to energize), `false`
   for cheap SainSmart-style active-LOW modules. If the states come out
   inverted after a first run, flip this constant and re-flash.
7. Upload, then open Serial Monitor (115200 baud) to see the DHCP-
   assigned IP address.

---

## Python driver

See [`../../drivers/arduino-relay-board/`](../../drivers/arduino-relay-board/)
for a Python client:

```python
from rf_bench.arduino_relay_board import ArduinoRelayBoard

with ArduinoRelayBoard("10.1.1.36") as r:
    r.on(1)
    r.pulse_high(2, 250)
    print(f"status: {r.status():04b}")
    r.off(1)
```

### Acceptance test

`test_relays.py` (in this directory) is the canonical acceptance test —
it exercises ON/OFF on every relay individually, all-on/all-off, both
pulse modes, pulse cancellation, and input validation. Run it after
swapping relay modules, re-flashing, or moving the board:

```bash
python3 test_relays.py           # defaults to 10.1.1.36
python3 test_relays.py 10.1.1.X  # other address
```

Exit code: 0 = all checks pass, 1 = at least one check failed,
2 = could not reach the board.

---

## Limitations

- **No authentication.** Anyone on the LAN can flip relays. Run on a
  trusted network or behind a firewall.
- **No state persistence.** Power-cycle → all relays off, all pulses
  cancelled. Add EEPROM save/restore if power-on state recall is
  needed.
- **No interlock.** Multiple relays can be on simultaneously; the
  firmware does not enforce any "only one in group X" rule. Add
  application-level interlock in the driver or sketch if required.
- **No real contact feedback.** State is tracked from what the firmware
  commanded, not from sense lines. If a coil fails, the firmware still
  reports the commanded state.
- **Single-threaded command processing.** Commands from different
  clients are processed serially; the loop is fast enough that this is
  not a practical limit for control-rate traffic.

---

## License

GPL-3.0-or-later, same as the rest of rf-bench.
