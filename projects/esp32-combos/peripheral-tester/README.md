# ESP32+Bus Pirate Peripheral Tester

I2C/SPI device characterization combining scpi-i2c (or scpi-spi) + scpi-relay (power cycling) + Bus Pirate (golden reference).

## Hardware Required

- **ESP32 running scpi-i2c** or **scpi-spi** firmware (see `~/rf-bench/projects/esp32/scpi-i2c/` or `~/rf-bench/projects/esp32/scpi-spi/`)
- **ESP32 running scpi-relay** firmware (see `~/rf-bench/projects/esp32/scpi-relay/`) for DUT power cycling
- **Bus Pirate** (v3 or v4) — golden reference for I2C/SPI protocol verification
- **Device Under Test (DUT)** — I2C or SPI peripheral (ADC, DAC, EEPROM, sensor, etc.)
- **Wiring:** parallel I2C or SPI buses — both ESP32 and Bus Pirate monitor/drive the same signals

## Installation

```bash
pip install rf-bench-drivers-buspirate
```

## Wiring

### I2C Configuration

```
ESP32 scpi-i2c:        Bus Pirate:         DUT:
  SDA (GPIO 21) ----+---- MOSI/SDA -------- SDA
  SCL (GPIO 22) ----+---- CLK/SCL --------- SCL
  GND --------------+---- GND -------------- GND
                    |
ESP32 scpi-relay:   |
  Relay 1 NO -------+-------------------- DUT VCC
  Relay 1 COM --------------------------- PSU VCC
```

Both I2C masters (ESP32 and Bus Pirate) are connected in parallel to the DUT. The scpi-relay controls DUT power for reset/power-cycle tests.

**IMPORTANT:** External pull-ups (4.7kΩ to 3.3V) are recommended on SDA/SCL. Bus Pirate can provide weak pull-ups, but external resistors improve signal integrity.

### SPI Configuration

```
ESP32 scpi-spi:        Bus Pirate:         DUT:
  MOSI (GPIO 23) ----+---- MOSI ----------- MOSI/SDI
  MISO (GPIO 19) ----+---- MISO ----------- MISO/SDO
  CLK  (GPIO 18) ----+---- CLK ------------ CLK/SCK
  CS   (GPIO 5)  ----+---- CS ------------- CS/SS
  GND ---------------+---- GND ------------ GND
                     |
ESP32 scpi-relay:    |
  Relay 1 NO --------+------------------- DUT VCC
  Relay 1 COM ---------------------------- PSU VCC
```

Both SPI masters monitor the same signals. Only one should drive at a time (controlled by test script). The scpi-relay controls DUT power.

## Use Cases

- **Protocol verification:** Compare ESP32 I2C/SPI implementation against Bus Pirate golden reference
- **Signal integrity analysis:** Detect timing or voltage-level issues (requires scope for full analysis)
- **Device characterization:** Map register address space, identify read-only vs read-write registers
- **Stress testing:** Power-cycle DUT, verify recovery behavior
- **Regression testing:** Validate firmware updates to scpi-i2c/scpi-spi don't break compatibility

## Scripts

### i2c_device_test.py

Sweeps I2C device register addresses, writes test patterns, reads back data, compares ESP32 vs Bus Pirate results.

**Example: Scan I2C EEPROM at 0x50, full 256-byte address space**

```bash
./i2c_device_test.py \
    --esp-i2c 10.1.0.100 \
    --buspirate /dev/ttyUSB0 \
    --device-addr 0x50 \
    --reg-start 0x00 \
    --reg-end 0xFF
```

**Example: With power cycling between tests**

```bash
./i2c_device_test.py \
    --esp-i2c 10.1.0.100 \
    --esp-relay 10.1.0.101 \
    --buspirate /dev/ttyUSB0 \
    --device-addr 0x50 \
    --power-cycle
```

**Test pattern details:**
- All zeros (0x00), all ones (0xFF)
- Alternating bits (0xAA, 0x55)
- Walking 1s (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)
- Walking 0s (0xFE, 0xFD, 0xFB, 0xF7, 0xEF, 0xDF, 0xBF, 0x7F)
- 8 random patterns

**Output:**
- Real-time mismatch/failure logging
- Summary: total tests, mismatches, write failures, success rate

### spi_device_test.py

Sweeps SPI device register addresses with same test patterns as I2C script.

**Example: Scan SPI device registers 0x00-0xFF**

```bash
./spi_device_test.py \
    --esp-spi 10.1.0.100 \
    --buspirate /dev/ttyUSB0 \
    --reg-start 0x00 \
    --reg-end 0xFF \
    --spi-mode 0 \
    --spi-speed 1000000
```

**SPI modes:**
- Mode 0: CPOL=0, CPHA=0 (sample on rising edge, shift on falling edge)
- Mode 1: CPOL=0, CPHA=1 (shift on rising edge, sample on falling edge)
- Mode 2: CPOL=1, CPHA=0 (sample on falling edge, shift on rising edge)
- Mode 3: CPOL=1, CPHA=1 (shift on falling edge, sample on rising edge)

**Note:** The SPI script assumes a typical register-based interface (reg address byte with read/write bit, followed by data). Device-specific protocols may require modifications to `spi_read_register()` and `spi_write_register()` functions in the script.

## Interpreting Results

### Clean Pass

```
SUMMARY: 6144 total tests
  Mismatches: 0 (0.00%)
  Write failures: 0 (0.00%)
  Success rate: 100.00%
```

ESP32 implementation matches Bus Pirate exactly. Protocol implementation is correct.

### Mismatches

```
MISMATCH: reg 0x42, ESP32=0x5A BP=0x5B
```

ESP32 read 0x5A, Bus Pirate read 0x5B from the same register. Possible causes:
- Timing issue (ESP32 sampling too early/late)
- Signal integrity problem (ringing, undershoot, overshoot)
- DUT behavior (register changes state on read, non-repeatable reads)

**Debug steps:**
1. Re-run the failing register/pattern in isolation
2. Capture with oscilloscope: verify signal levels, setup/hold times
3. Check pull-ups (I2C) or termination (SPI)
4. Reduce clock speed, test again

### Write Failures

```
WRITE FAIL: reg 0x12, pattern 0xAA
```

Write operation failed — neither ESP32 nor Bus Pirate could verify the write. Possible causes:
- Register is read-only
- Write-protect is enabled on DUT
- Power supply issue
- DUT not responding (clock stretch timeout on I2C, CS not asserted on SPI)

## Common Devices

### I2C

| Device | Address | Registers | Notes |
|--------|---------|-----------|-------|
| AT24C256 EEPROM | 0x50 | 0x00-0xFF | 256-byte pages, 5ms write cycle |
| MCP4725 DAC | 0x60 | 0x00-0x05 | 12-bit DAC, fast mode |
| BME280 sensor | 0x76 | 0x88-0xFE | Many read-only cal registers |
| PCF8574 I/O expander | 0x20 | Single byte | No register addressing |
| DS3231 RTC | 0x68 | 0x00-0x12 | Time/date/alarm registers |

### SPI

| Device | Mode | Speed | Notes |
|--------|------|-------|-------|
| MCP3008 ADC | 0 | 1 MHz | 10-bit, 8 channels |
| MCP4922 DAC | 0 | 20 MHz | 12-bit, 2 channels |
| 25LC256 EEPROM | 0 | 5 MHz | 256 Kbit, page write |
| MAX7219 LED driver | 0 | 10 MHz | 8-digit 7-segment |
| BME280 sensor | 0 or 3 | 10 MHz | Also has I2C interface |

## Signal Integrity Verification (Future)

The current scripts compare **logical results** (MISO data) but not signal quality. For full characterization:

1. **Capture with oscilloscope:** Use 4-channel scope to monitor I2C (SDA, SCL) or SPI (MOSI, MISO, CLK, CS) during test
2. **Measure timing:** Setup/hold times, clock duty cycle, rise/fall times
3. **Check voltage levels:** Ensure signals meet VOH/VOL specs for DUT
4. **Eye diagram analysis:** For high-speed SPI (>1 MHz), use scope persistence mode to check for jitter/ringing
5. **Compare ESP32 vs Bus Pirate waveforms:** Overlay traces to see timing differences

**Future enhancement:** Add scope automation (via scpi-scope or similar) to capture and analyze waveforms during mismatches.

## Troubleshooting

### Bus Pirate not responding

- Check serial port: `ls -l /dev/ttyUSB*`
- Verify permissions: `sudo usermod -a -G dialout $USER` (logout/login required)
- Try manual reset: unplug/replug USB

### ESP32 SCPI timeout

- Verify IP address: `ping 10.1.0.100`
- Check SCPI port 5025: `nc -zv 10.1.0.100 5025`
- Restart ESP32 firmware

### All writes fail

- Verify DUT is powered (check with multimeter)
- Check pull-ups (I2C) or ensure CS is properly connected (SPI)
- Confirm correct device address (I2C) or SPI mode/speed

### Random mismatches

- Reduce clock speed (I2C: 100 kHz, SPI: 250 kHz)
- Add/strengthen pull-ups (I2C: use 2.2kΩ instead of 4.7kΩ)
- Check for EMI sources (switch-mode PSU, nearby RF transmitter)
- Use shorter wires (< 10 cm for breadboard, < 50 cm for device-to-device)

## Status

🔨 **In development** — I2C script complete, SPI script complete, signal integrity capture planned.

## References

- Bus Pirate documentation: http://dangerousprototypes.com/docs/Bus_Pirate
- I2C specification: NXP UM10204
- SPI protocol overview: Wikipedia SPI (no single governing spec)
- rf-bench drivers: `~/rf-bench/drivers/buspirate/`
