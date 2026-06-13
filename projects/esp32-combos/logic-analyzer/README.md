# ESP32 + Scope Logic Analyzer

Protocol decode validation combining ESP32 traffic generation (via scpi-i2c/scpi-spi/scpi-uart) with Siglent SDS2504X hardware protocol decode. Generates known I2C/SPI/UART traffic on the ESP32, captures with scope digital channels, decodes in hardware, and compares transmitted vs decoded frames in Python.

## Purpose

Validate that:
- Sensor datasheets are correct (I2C addresses, register maps, timing)
- Protocol implementations meet spec (setup/hold times, clock polarity)
- Scope decode accurately captures real-world traffic
- Custom protocol drivers work as expected

## Hardware Requirements

### Essential
- **ESP32** running one of:
  - `scpi-i2c` (from `~/rf-bench/projects/esp32/scpi-i2c/`)
  - `scpi-spi` (from `~/rf-bench/projects/esp32/scpi-spi/`)
  - `scpi-uart` (from `~/rf-bench/projects/esp32/scpi-uart/`)
- **Siglent SDS2504X with MSO option** (digital channels + hardware decode)

### Wiring

Parallel connection: ESP32 protocol pins tap into scope digital probes.

#### I2C
```
ESP32 GPIO21 (SDA) ──┬── I2C device SDA
                     └── Scope D0

ESP32 GPIO22 (SCL) ──┬── I2C device SCL
                     └── Scope D1

ESP32 GND ─────────────── Scope GND
```

#### SPI
```
ESP32 GPIO23 (MOSI) ──┬── SPI device MOSI
                      └── Scope D0

ESP32 GPIO19 (MISO) ──┬── SPI device MISO
                      └── Scope D1

ESP32 GPIO18 (SCLK) ──┬── SPI device SCLK
                      └── Scope D2

ESP32 GPIO5  (CS)   ──┬── SPI device CS
                      └── Scope D3

ESP32 GND ───────────────── Scope GND
```

#### UART
```
ESP32 GPIO17 (TX) ──┬── UART device RX
                    └── Scope D0

ESP32 GPIO16 (RX) ──┬── UART device TX
                    └── Scope D1

ESP32 GND ─────────────── Scope GND
```

## Installation

```bash
pip install rf-bench-drivers-siglent
```

ESP32 firmware: flash the appropriate `scpi-*` project from `~/rf-bench/projects/esp32/`.

## Usage

### I2C Protocol Test

```bash
./i2c_protocol_test.py --esp 10.1.0.100 --scope 10.1.0.200 \
    --test-vectors test_vectors_i2c.csv
```

**Test vector CSV format:**
```csv
operation,address,data,frequency,byte_count,description
write,0x50,0xAA55,100000,,Write to EEPROM
read,0x50,,100000,16,Read 16-byte block
scan,,,100000,,Address scan 0x00-0x7F
```

### SPI Protocol Test

```bash
./spi_protocol_test.py --esp 10.1.0.100 --scope 10.1.0.200 \
    --test-vectors test_vectors_spi.csv
```

**Test vector CSV format:**
```csv
operation,data,frequency,mode,bit_order,byte_count,description
write,0xAA55BB,1000000,0,MSB,,Write 3 bytes
read,0xFF,1000000,0,MSB,4,Read with dummy byte
transfer,0xDEADBEEF,500000,3,MSB,,Full duplex mode 3
```

**SPI modes:**
- `0`: CPOL=0, CPHA=0 (sample rising, shift falling)
- `1`: CPOL=0, CPHA=1 (sample falling, shift rising)
- `2`: CPOL=1, CPHA=0 (sample falling, shift rising)
- `3`: CPOL=1, CPHA=1 (sample rising, shift falling)

### UART Protocol Test

```bash
./uart_protocol_test.py --esp 10.1.0.100 --scope 10.1.0.200 \
    --test-vectors test_vectors_uart.csv
```

**Test vector CSV format:**
```csv
data,baudrate,data_bits,parity,stop_bits,description
"Hello World",115200,8,NONE,1,Standard 8N1 ASCII
0xDEADBEEF,9600,8,EVEN,2,Hex with parity
"@ABCDEFG",57600,7,ODD,1,7-bit + odd parity
```

**Parity options:** `NONE`, `EVEN`, `ODD`, `MARK`, `SPACE`

## Example: I2C EEPROM Validation

**Scenario:** Verify that a 24LC256 EEPROM at address 0x50 responds correctly to read/write cycles.

1. Create `eeprom_test.csv`:
   ```csv
   operation,address,data,frequency,byte_count,description
   write,0x50,0x00AA,100000,,Write 0xAA to address 0x00
   read,0x50,,100000,1,Read back byte (expect 0xAA)
   write,0x50,0x00DEADBEEF,100000,,Write 4 bytes starting at 0x00
   read,0x50,,100000,4,Read back 4 bytes
   ```

2. Run test:
   ```bash
   ./i2c_protocol_test.py --esp 10.1.0.100 --scope 10.1.0.200 \
       --test-vectors eeprom_test.csv
   ```

3. Script output shows:
   - ESP32 transmitted commands
   - Scope decoded I2C frames
   - Pass/fail for each test vector

## Example: SPI Flash ID Read

**Scenario:** Read manufacturer/device ID from W25Q32 flash chip (command 0x9F).

1. Create `flash_id_test.csv`:
   ```csv
   operation,data,frequency,mode,bit_order,byte_count,description
   transfer,0x9F000000,1000000,0,MSB,,READ_JEDEC_ID command + 3 dummy bytes
   ```

2. Run test:
   ```bash
   ./spi_protocol_test.py --esp 10.1.0.100 --scope 10.1.0.200 \
       --test-vectors flash_id_test.csv --mosi-channel D0 --miso-channel D1 \
       --sclk-channel D2 --cs-channel D3
   ```

3. Scope decode should show MOSI=0x9F followed by MISO returning manufacturer ID (e.g., 0xEF for Winbond).

## Common Workflows

### Validate Sensor Datasheet
1. Write test vectors covering all documented I2C registers
2. Run test suite
3. Flag any discrepancies between datasheet and actual behavior

### Debug Protocol Timing Issues
1. Generate borderline-spec traffic (minimum setup/hold times)
2. Capture with scope at high sample rate
3. Use scope cursors to measure actual timing vs datasheet

### Characterize Unknown Device
1. Run address scan (I2C) or command sweep (SPI/UART)
2. Log all responses
3. Reverse-engineer register map or command set

### Inject Protocol Errors
(Future enhancement)
1. Modify test vectors to violate spec (wrong parity, invalid stop bits)
2. Verify scope decode flags errors
3. Validate error-handling in firmware

## Status

**Current:** 🔨 Implementation in progress

**Blockers:**
- Requires SDS2504X MSO option (digital channels) — hardware on order
- Scope decode API (`DECODE1:DATA?`) syntax needs verification against actual firmware

**Next steps:**
1. Test with real SDS2504X to confirm SCPI decode commands
2. Add detailed frame comparison (byte-by-byte validation)
3. Add error-injection test vectors (glitches, timing violations)
4. Support for other protocols (1-Wire, CAN, LIN) if scope supports them

## Notes

- **Why ESP32 as reference?** SCPI control gives reproducible, known-good traffic with precise timing.
- **Scope hardware decode vs software decode:** Hardware decode offloads CPU, but is opaque (can't inspect intermediate symbols). Software decode gives more insight but requires higher sample rates.
- **Test vector CSV is the source of truth:** All expected traffic, timing, and pass/fail criteria live in the CSV. Scripts just execute and compare.

## Related Projects

- `~/rf-bench/projects/esp32/scpi-i2c/` — ESP32 I2C traffic generator
- `~/rf-bench/projects/esp32/scpi-spi/` — ESP32 SPI traffic generator
- `~/rf-bench/projects/esp32/scpi-uart/` — ESP32 UART traffic generator
- `~/rf-bench/drivers/siglent/` — SDS2000X scope driver (includes protocol decode API)

## License

MIT
