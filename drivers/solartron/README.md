# rf-bench-drivers-solartron

> **Untested — awaiting physical hardware.** This driver was written from documentation
> (Solartron 7151 Computing Multimeter User Manual ND/7151/2 Issue 2 1985, Solartron 7151
> Service Manual, the open-source `s7150` C reference driver by Joerg Hau, and the
> KISS-488 / Prologix protocol specification). It has not been run against a real
> Solartron 7151. See "Documentation provenance" below for source URLs.

Solartron 7151 6.5-digit Computing Multimeter driver for Python bench automation.

The Solartron 7151 (and its 7150 / 7150-plus siblings) is a 1985-era IEEE-488
6.5-digit bench DMM. It speaks a device-specific ASCII command language —
single ASCII letters with optional integer arguments — that predates SCPI by a
decade. The same command set covers the 7150, 7150-plus (with extra °C/°F
modes), and 7151.

Connection path:

```
Python -> rf_bench.gpib.KISS488 (TCP port 23) -> GPIB -> Solartron 7151 @ addr 22
```

## Installation

```bash
pip install rf-bench-drivers-solartron
```

## Quick start

```python
from rf_bench.solartron import Solartron7151

with Solartron7151("10.1.1.70") as dmm:
    dmm.set_mode("VDC")
    dmm.set_range_auto()
    dmm.set_integration(Solartron7151.INT_5X9_FILT_OFF)   # 5.5 digits, 400 ms
    dmm.set_track(True)                                   # continuous
    print(dmm.read_value())   # one float, e.g. 2.798450
```

Single-shot example (no tracking):

```python
with Solartron7151("10.1.1.70") as dmm:
    dmm.set_mode("KOHM")
    dmm.set_range(Solartron7151.RANGE_OHM_200K if hasattr(Solartron7151, "RANGE_OHM_200K") else 4)
    dmm.set_integration(Solartron7151.INT_6X9_8S)         # 6.5 digits (~8 s)
    dmm.set_track(False)
    dmm.trigger_single()
    import time; time.sleep(8.5)
    print(dmm.read_value())
```

## Hardware

| Item | Value |
|------|-------|
| Instrument | Solartron 7151 |
| GPIB address | Set via rear-panel DIP switches (1, 2, 4, 8, 16). Default in this driver: 16. |
| Default state | MODE VDC, RANGE AUTO, NINES 5 FILTER OFF, TRACK ON, LITERALS ON, DELIMIT CR LF |
| Calibration plug | 2.5 mm jack with internal short, in rear-panel CAL socket. Required for any C/H/L/W command. |
| Adapter | KISS-488 Rev 2 (HX Engineering), Prologix-compatible |
| Adapter port | TCP 23 (Telnet; NOT the Prologix port 1234) |
| Default host | 10.1.1.70 |

## Command set summary

The 7151 speaks ASCII-letter commands; this driver wraps them with safe Python:

| Letter | Meaning | Driver method |
|--------|---------|---------------|
| `A` | Device clear (initialise) | `device_clear()` |
| `M0..M4` | MODE: VDC, VAC, KOHM, IDC, IAC | `set_mode()` |
| `R0..R6` | RANGE (meaning per-function) | `set_range()`, `set_range_auto()` |
| `I0..I5` | NINES (integration time) | `set_integration()` |
| `T0`/`T1` | TRACK off/on | `set_track()` |
| `G` | TRIG (single-shot) | `trigger_single()` |
| `U0..U8` | DELIMIT (output terminator) | `set_delimiter()` |
| `N0`/`N1` | LITERALS on/off | `set_literals()` |
| `D0`/`D1` | DISPLAY on/off (D1 = OFF) | `set_display()` |
| `Q0..Q3` | SRQ mode | `set_srq()` |
| `Y0..Y2` | DRIFT correct mode | `set_drift_correct()` |
| `Z0`/`Z1` | NULL off / take-now | `set_null()` |
| `K0`/`K1` | LOCK rtl key off/on | `set_lock()` |
| `J0..J8` | POLL (parallel-poll line) | (use `send("Jn")`) |
| `E` | Echoback all settings | `identify()` |
| `!` | STATUS (read last error) | `get_error()`, `get_status_string()` |
| `?` | Query previous letter | `get_mode()`, `get_range()`, `query("M?")` etc. |
| `C0`/`C1` | CALIBRATE off/on | `calibrate_off()` / `calibrate_on()` |
| `H<n>` | HI calibration point | `cal_hi(count)` |
| `L<n>` | LO calibration point | `cal_lo(count)` |
| `W` | WRITE cal constants | `cal_write()` |
| `REFRESH` | Refresh existing cal | `cal_refresh()` |

### Output reading format

With **LITERALS ON** (default):

```
+ 2.798450 V DC 01.15.00 DAY 5
```

With **LITERALS OFF**:

```
+ 2.798450
```

An ASCII `!` anywhere in the output string indicates input overload. The
driver's `read_value()` raises `OverflowError` in that case.

### Serial poll status byte

| Bit | Mask | Meaning |
|-----|------|---------|
| 6 | 0x40 | Service Request |
| 5 | 0x20 | Calibration error |
| 4 | 0x10 | Output available |
| 3 | 0x08 | Remote control |
| 0 | 0x01 | Command/operational error |

`Solartron7151.serial_poll()` returns this byte; `get_error()` reads the verbose
error string via the `!` command (and clears the internal error).

### Error codes (from `!` command)

`0`=OK, `01`=BAD COMMAND, `02`=BAD ARGUMENT, `03`=I/P BUFFER OVERFLOW,
`04`=HI NULL, `05`=ILLEGAL MODE FOR NULL (AC range), `06`=ILLEGAL MODE FOR 6×9s
(AC range), `08`=CAL INHIBITED (no shorting plug), `09`=COMMAND ILLEGAL IN CAL,
`10`=CAL OUTSIDE LIMITS, `12-18`=program/clock/numeric errors. See
`solartron7151.ERROR_MESSAGES`.

## Documentation provenance

- **User Manual** (KO4BB scan, 114 pp, image-only PDF, OCR'd at archive.org)
  - https://www.ko4bb.com/manuals/98.97.107.39/Solartron_7151_Computing_Multimeter_User_Manual.pdf
  - https://archive.org/details/solartron_Solartron_7151_Computing_Multimeter_User_Manual
- **Service Manual** (KO4BB OCR'd PDF, 82 pp)
  - https://www.ko4bb.com/manuals/98.97.107.39/Solartron_7151_Computing_Multimeter_Service_Manual.pdf
- **Reference C driver** (works against 7150 / 7150-plus / 7151) — Joerg Hau, GPL-2.0
  - https://github.com/JoergCH/s7150

The shortform command tables, default state, error codes, calibration
procedure, and status-byte format in this driver were extracted from User
Manual pages 6.4 (status byte), 6.24-6.25 (shortform), 6.26 (default state),
6.27 (error codes), and Chapter 7 (calibration). The init sequence
(`A` + 2 s sleep, then `U7N0T1`) follows the s7150 reference driver.

## Verification status

The following items have NOT been verified against real hardware and may need
adjustment after first power-on:

- **Mode 5 (DIODE)** — present on 7150 / 7150-plus per the s7150 driver, but
  not documented for the 7151 in the OCR'd User Manual.
- **Modes 6/7 (DEGC / DEGF)** — 7150-plus only, omitted here.
- **`++spoll` response format** — KISS-488 Rev 2 is documented as
  Prologix-compatible; the spoll reply is assumed to be a decimal integer.
  Verify against the KISS-488 manual.
- **Reading-string parser** — `_parse_reading()` strips an optional space
  between the leading sign and the mantissa; the actual on-the-wire
  whitespace pattern from the OCR'd manual example `"+ 2.798450 V DC ..."` is
  the literal text but may include slightly different whitespace in the
  binary stream.

## License

GPL-3.0-or-later
