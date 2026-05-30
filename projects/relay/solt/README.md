> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on results.

# rf-bench-relay-solt

GitHub: https://github.com/jfrancis42/rf-bench-relay-solt

Automated SOLT (Short-Open-Load-Thru) calibration fixture for the HP 8712B
Vector Network Analyzer.  Instead of manually connecting calibration standards
one at a time, all standards are permanently wired to a relay board and the
script switches between them automatically via GPIB.

## Hardware

| Instrument / Component | Role |
|------------------------|------|
| HP 8712B VNA (10.1.1.70) | 300 kHz – 1.3 GHz 2-port vector network analyzer |
| KISS-488 Rev 2 Ethernet-GPIB adapter | Transparent GPIB bridge; Prologix-compatible TCP on port 1234 |
| Bus Pirate v3/v4/v5 (/dev/ttyUSB1) | I2C master for relay board |
| XL9535 I2C I/O expander relay board | 8-relay board at I2C address 0x20 |
| SMA calibration standards | OPEN, SHORT, LOAD (50 Ω) × 2 ports |
| SMA-SMA THRU cable or adapter | Completes the THRU standard path when DUT relays close |

## Wiring diagram

```
                         ┌─────────────────────────────────┐
                         │     XL9535 relay board (0x20)   │
                         │                                  │
  HP 8712B Port 1 ───────┤ relay 0 → OPEN  standard (P1)   │
                         │ relay 1 → SHORT standard (P1)   │
                         │ relay 2 → LOAD  50Ω  (P1)       │
                         │ relay 3 → DUT / THRU end (P1)   │
                         │                                  │
  HP 8712B Port 2 ───────┤ relay 4 → OPEN  standard (P2)   │
                         │ relay 5 → SHORT standard (P2)   │
                         │ relay 6 → LOAD  50Ω  (P2)       │
                         │ relay 7 → DUT / THRU end (P2)   │
                         └─────────────────────────────────┘
                                  │
                              Bus Pirate (I2C SDA/SCL)
                                  │
                              /dev/ttyUSB1

THRU: relay 3 + relay 7 closed simultaneously
      P1 → relay 3 → [THRU path] → relay 7 → P2
```

All relay COM pins connect to the respective VNA port.  The SMA calibration
standards plug into the relay NO (normally-open) terminals.  Use a short SMA
cable or coupler to tie the relay-3 and relay-7 NO terminals together to form
the THRU path.

## Usage

```bash
# Full 2-port SOLT calibration (default settings):
python relay_solt.py

# 1-port calibration only (S11):
python relay_solt.py --one-port

# Dry run — verify relay wiring without touching hardware:
python relay_solt.py --dry-run

# Full calibration, then connect DUT automatically:
python relay_solt.py --dut

# Save calibration state to JSON for later reference:
python relay_solt.py --save-cal solt_cal.json

# Custom frequency range (1–500 MHz, 201 points):
python relay_solt.py --start 1e6 --stop 500e6 --points 201

# Non-default Bus Pirate port:
python relay_solt.py --bp /dev/ttyUSB2

# Custom relay wiring:
python relay_solt.py --p1-open 2 --p1-short 3 --p1-load 4 --p1-dut 5
```

## Options

```
--vna HOST       HP 8712B IP address (default 10.1.1.70)
--bp PORT        Bus Pirate serial port (default /dev/ttyUSB1)
--addr ADDR      XL9535 I2C address, hex OK (default 0x20)
--start FREQ     Start frequency Hz (default 300000)
--stop FREQ      Stop frequency Hz (default 1300000000)
--points N       Sweep points 1–801 (default 801)
--p1-open N      Relay for port-1 OPEN standard (default 0)
--p1-short N     Relay for port-1 SHORT standard (default 1)
--p1-load N      Relay for port-1 LOAD standard (default 2)
--p1-dut N       Relay for port-1 DUT / THRU end (default 3)
--p2-open N      Relay for port-2 OPEN standard (default 4)
--p2-short N     Relay for port-2 SHORT standard (default 5)
--p2-load N      Relay for port-2 LOAD standard (default 6)
--p2-dut N       Relay for port-2 DUT / THRU end (default 7)
--settle-ms MS   Delay after relay switch before VNA command (default 200)
--save-cal FILE  Save calibration state JSON after completion
--one-port       1-port (S11 only) calibration; skip port-2 and THRU
--dut            After calibration, switch to DUT position and wait
--dry-run        Print relay commands without executing (wiring verification)
```

## GPIB calibration sequence

The HP 8712B full 2-port SOLT calibration sequence over GPIB:

| Step | GPIB command | Standard |
|------|-------------|----------|
| 1 | `CALIS11A` | Port-1 OPEN |
| 2 | `CALIS11B` | Port-1 SHORT |
| 3 | `CALIL1`   | Port-1 LOAD (50 Ω) |
| 4 | `CALIS22A` | Port-2 OPEN |
| 5 | `CALIS22B` | Port-2 SHORT |
| 6 | `CALIL2`   | Port-2 LOAD (50 Ω) |
| 7 | `CALT`     | THRU |
| 8 | `SAVC`     | Save / complete calibration |

Each command is sent after the relay has settled.  No operator prompts are
needed — the relay board substitutes for the manual connections that would
normally be required.

## Important: relay hardware recommendations

**Use reed relays (Coto 9011 or similar) — not HK19F — for calibration standards
wired above 100 MHz.**

The HK19F is a common PCB relay but it has significant parasitic inductance and
capacitance in the switching contacts.  At VHF and above (100 MHz+) this causes
measurable insertion loss and impedance deviation that will corrupt the calibration.

Reed relays such as the Coto 9011 (3 GHz rated) have much lower parasitics and
are suitable for use as calibration standard switching relays through the HP 8712B's
full 1.3 GHz range.

For DUT switching (relay 3 / relay 7) the HK19F is acceptable if the DUT path
is only used at lower frequencies, but reed relays are still preferred for
wideband accuracy.
