# siglent-protocol-analyzer

SPI, I2C, UART, and raw digital bus decoder using the MSO digital channels (D0–D15) of
the Siglent SDS2000X Plus oscilloscope. Captures transactions, decodes bytes in Python,
generates timing diagrams, and exports JSON.

> **MSO hardware note:** All MSO digital channel code is based on the Siglent SDS Series
> SCPI guide. The MSO probe pod has **not** been physically tested. Requires the MSO
> option license on the oscilloscope and the digital probe pod physically connected.

## Hardware required

- Siglent SDS2504X Plus with MSO option (LAN, `10.1.1.58`)
- MSO digital probe pod (connects to rear-panel Digital port)

## Probe connections

| Protocol | Ch | Signal |
|----------|----|--------|
| SPI | D0 | CLK |
| SPI | D1 | MOSI |
| SPI | D2 | MISO (optional, `--miso-ch -1` to omit) |
| SPI | D3 | CS (optional, `--cs-ch -1` for continuous) |
| I2C | D0 | SCL |
| I2C | D1 | SDA |
| UART | D0 | RX (of target board, which is TX of host) |
| UART | D1 | TX (optional) |

All channel assignments are configurable via CLI flags.

## Usage

```bash
# Decode SPI (CLK=D0, MOSI=D1, MISO=D2, CS=D3, Mode 0)
python protocol_analyzer.py --protocol spi

# SPI with custom channel mapping and mode
python protocol_analyzer.py --protocol spi --clk-ch 4 --mosi-ch 5 --cs-ch 6 --spi-mode 1

# I2C
python protocol_analyzer.py --protocol i2c --scl-ch 0 --sda-ch 1

# UART at 115200 baud
python protocol_analyzer.py --protocol uart --baud 115200

# Raw digital display (no decoding)
python protocol_analyzer.py --protocol raw --digital-channels 0,1,2,3

# Continuous capture mode (re-triggers until Ctrl-C)
python protocol_analyzer.py --protocol spi --continuous

# Set threshold for 1.8 V logic
python protocol_analyzer.py --protocol i2c --threshold-v 0.9
```

## Threshold presets

| Flag | Threshold | Suitable for |
|------|-----------|-------------|
| `lvcmos33` (default) | 1.65 V | 3.3 V CMOS |
| `ttl` | 1.4 V | 5 V TTL |
| `cmos` | 2.5 V | 5 V CMOS |
| `lvcmos25` | 1.25 V | 2.5 V CMOS |
| `--threshold-v 0.9` | Custom | 1.8 V or other |

## Output files

| File | Contents |
|------|----------|
| `<prefix>_protocol.json` | Decoded transactions with timestamps, byte values, R/W, ACK/NAK |
| `<prefix>_timing.png` | Logic-analyzer-style timing diagram showing all captured channels |

## Protocol decoder details

| Protocol | What is decoded |
|----------|----------------|
| SPI | Byte values and timestamps per transaction; CS boundaries delimit frames |
| I2C | 7-bit address + R/W, data bytes, ACK/NAK per transaction; START/STOP conditions |
| UART | Byte values decoded LSB-first with configurable baud rate and parity |
| Raw | Edge counts and sample counts per channel; timing diagram only |

## Notes

- Decoding runs in Python, not on the scope — works without the scope's optional
  decode license
- I2C repeated-START is handled as a new transaction
- UART framing errors (bad stop bit) are silently skipped

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
```
