> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-relay-multidut

GitHub: https://github.com/jfrancis42/rf-bench-relay-multidut

Multi-DUT sequential component tester. An XL9535 16-bit I2C relay board (controlled
through a Bus Pirate I2C master) connects up to 16 DUT sockets to a Siglent SDM3045X
bench DMM. The script steps through each relay position in sequence, closes one relay
at a time, takes three measurements and uses the median (to reject relay-bounce
transients), then opens the relay and advances to the next position. Results are
printed live, saved to a timestamped CSV, and plotted as a bar chart. Supports
2-wire resistance, 4-wire Kelvin resistance, capacitance, and diode Vf modes, plus a
`ping` relay self-test mode that exercises each relay without needing the DMM connected.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SDM3045X (10.1.1.63) | Bench DMM — measures resistance, capacitance, diode Vf |
| Bus Pirate v3/v4 (/dev/ttyUSB1) or v5 (/dev/ttyACM1) | I2C master for XL9535 relay board |
| XL9535 I2C relay board | Up to 16 SPDT relay sockets for DUTs |

## Wiring

**Bus Pirate → XL9535:**

| Bus Pirate pin | XL9535 pin |
|---------------|-----------|
| SDA           | SDA       |
| SCL           | SCL       |
| GND           | GND       |
| 3.3V or 5V    | VCC (match relay board supply) |

Set the XL9535 I2C address via its A0/A1/A2 solder jumpers (default 0x20 = all low).

**DUT socket wiring:**

All relay NO (normally-open) contacts share a common rail; wire that rail to the
DMM HI (or SENSE HI for 4-wire) terminal. The COM terminal of each relay connects
to one pin of its DUT socket. Wire the other DUT socket pin to the DMM LO terminal
(and SENSE LO for 4-wire Kelvin).

For diode Vf: orient all DUT sockets with anode toward DMM HI, cathode toward LO.

## Usage

**2-wire resistance (8 sockets, default):**
```
python relay_multidut.py --mode res
```

**4-wire Kelvin resistance with labels:**
```
python relay_multidut.py --mode res4w --label labels.json
```

**Capacitor binning, 12 sockets:**
```
python relay_multidut.py --mode cap --positions 0,1,2,3,4,5,6,7,8,9,10,11
```

**Crystal sorting — flag units outside ±0.5% of 14.074 MHz:**
```
python relay_multidut.py --mode res --nominal 14074000 --tolerance 0.5 --sort
```

**Diode Vf matching, sort ascending:**
```
python relay_multidut.py --mode diode --sort
```

**Relay self-test (no DMM required):**
```
python relay_multidut.py --mode ping
```

**Custom Bus Pirate port, slower settle:**
```
python relay_multidut.py --mode cap --bp /dev/ttyACM1 --delay 100
```

**Full options:**
```
  --bp PORT          Bus Pirate port (default /dev/ttyUSB1)
  --dmm HOST         SDM3045X IP (default 10.1.1.63)
  --addr ADDR        XL9535 I2C address in hex (default 0x20)
  --positions LIST   Comma-separated relay positions to test (default 0,1,2,3,4,5,6,7)
  --active-high      Relay board polarity active-HIGH (default, ULN2803 boards)
  --active-low       Relay board polarity active-LOW
  --delay MS         Settle delay after relay closes in ms (default 50)
  --label FILE       JSON file mapping position to label {"0":"X1","1":"X2",...}
  --out CSV          Output CSV file (default: timestamped filename)
  --sort             Sort summary results by measured value (ascending)
  --nominal VAL      Nominal value for deviation % and PASS/FAIL
  --tolerance PCT    Flag components outside ±N% of nominal (default 1.0)
```

## Notes

The XL9535 relay board typically uses HK19F SPDT relays, which are fine for
DC and audio-frequency measurements. At RF frequencies the relay parasitics
(~5 pF capacitance, ~10 nH lead inductance) will affect results — this tool
is intended for LF/DC component sorting only.

The script takes 3 readings per position and uses the median. This rejects single
outliers caused by relay contact bounce immediately after closure. The default
50 ms settle delay is adequate for most relays; increase it with `--delay` if
you observe inconsistent readings.

Capacitance measurements (`--mode cap`) use one-shot `MEAS:CAP?` SCPI commands
because the SDM3045X (4.5-digit) does not support capacitance. Use an SDM3055 or
SDM3065X for capacitance mode.

An SDM overrange reading (±9.9×10³⁷) is detected and displayed as `OPEN`, indicating
no DUT in the socket or an open-circuit fault.
