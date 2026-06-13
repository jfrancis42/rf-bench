# RF Matrix Router

Multi-instrument RF routing matrix combining scpi-matrix + XL9535 relay board + external RF relays for automated multi-DUT RF testing without manual cable swaps.

## Status

**🔨 IN DEVELOPMENT** - Blocked on XL9535 hardware (ordered 2026-06-03)

## Overview

The RF Matrix Router provides automated switching between multiple RF sources and test fixtures/DUTs. Eliminates manual cable swapping during multi-instrument characterization runs.

### Hardware Components

- **Control**: scpi-matrix ESP32 (direct GPIO) or XL9535 I2C GPIO expander (via Bus Pirate)
- **RF Relays**: External coaxial RF relays (SMA or BNC connectors, user-supplied)
- **Topology**: 4×4 (4 sources, 4 destinations) or 8×2 (8 sources, 2 destinations)

### Supported Sources

- **SSA_TG**: SSA3032X spectrum analyzer tracking generator output
- **SDG**: SDG1062X function generator output
- **IC7300**: IC-7300 HF transceiver TX output
- **RTLSDR**: RTL-SDR input (for monitoring/loopback)

### Supported Destinations

- **DUT1 - DUT4** (4×4 topology): Four test fixtures or devices under test
- **DUT1 - DUT2** (8×2 topology): Two test fixtures with more source options

## Installation

### Python Dependencies

```bash
# When XL9535 driver is tested and published:
pip install rf-bench-drivers-relay

# For now (development):
cd ~/Dropbox/build/rf-bench/drivers/relay
pip install -e .
```

### Hardware Wiring

#### Crosspoint Topology (4×4 example)

```
          DUT1  DUT2  DUT3  DUT4
SSA_TG    R0    R1    R2    R3
SDG       R4    R5    R6    R7
IC7300    R8    R9    R10   R11
RTLSDR    R12   R13   R14   R15
```

Each relay Rx is controlled by XL9535 GPIO bit x or scpi-matrix GPIO pin x.

#### RF Relay Selection

- **SMA coaxial relays** (recommended for < 6 GHz): Low insertion loss, good VSWR
- **BNC relays** (lab bench): Easier prototyping, adequate for HF/VHF
- Suggested models:
  - SMA: G6Y-1-DC5 (RF relay, 0-3 GHz, 0.15 dB insertion loss)
  - BNC: Similar form factor, verify RF specs

Connect relay coil driver outputs from XL9535/scpi-matrix GPIOs to relay coils (via driver transistors if needed for current/voltage).

## Usage

### Basic Routing

```bash
# Route SSA tracking generator to DUT 2
./rf_matrix.py --topology 4x4 --route SSA_TG!DUT2

# Route SDG function generator to DUT 1 using scpi-matrix
./rf_matrix.py --esp-matrix 192.168.1.100 --route SDG!DUT1

# Route IC-7300 to DUT 3 using XL9535 via Bus Pirate
./rf_matrix.py --xl9535-buspirate /dev/ttyUSB0 --route IC7300!DUT3

# Disconnect all routes
./rf_matrix.py --disconnect-all
```

### List Available Sources

```bash
./rf_matrix.py --list-sources
```

### Verify Connection (Optional)

```bash
# Route and verify continuity/RF power
./rf_matrix.py --route SSA_TG!DUT2 --verify
```

Verification requires either:
- scpi-relay continuity measurement (low-frequency check)
- RF power detection at destination (requires additional hardware)

## Use Cases

### Automated Multi-DUT S-Parameter Sweep

```bash
for dut in 1 2 3 4; do
    ./rf_matrix.py --route SSA_TG!DUT${dut}
    # Run S21 measurement script here
    # Results saved to s21_dut${dut}.csv
done
```

### HF Amplifier Comparison

```bash
# Route IC-7300 TX output to each amplifier DUT
./rf_matrix.py --route IC7300!DUT1
# Measure output power, harmonics, IMD
./rf_matrix.py --route IC7300!DUT2
# Repeat measurements
# etc.
```

### Filter Bank Characterization

```bash
# Route SDG sweep to filter DUT1, capture on SSA
./rf_matrix.py --route SDG!DUT1
# Measure passband, stopband, insertion loss
# Repeat for DUT2, DUT3, DUT4
```

## Routing Abstraction Layer

The script provides high-level source/destination names that map to relay bit patterns:

- **Input**: Human-readable names (e.g., "SSA_TG!DUT2")
- **Processing**: Compute crosspoint relay index = source * num_dests + dest
- **Output**: 16-bit pattern sent to XL9535 or scpi-matrix GPIO

This abstraction hides the hardware-specific bit manipulation from the user.

## Future Enhancements

- **VSWR monitoring per route**: Detect bad connections, high SWR at DUT input
- **Automated calibration**: Store insertion loss per path, apply corrections
- **Relay health tracking**: Count actuations, predict relay lifetime
- **Web UI**: Browser-based matrix control panel
- **Integration with rf-bench measurement scripts**: Auto-route before measurement

## Hardware Status

- **scpi-matrix**: ✅ Available (ESP32 SCPI controller at ~/Dropbox/build/rf-bench/projects/esp32/scpi-matrix/)
- **XL9535**: 🔨 Ordered 2026-06-03, pending arrival
- **RF relays**: 🛒 User-supplied (see "RF Relay Selection" above)

## References

- XL9535 I2C GPIO expander datasheet
- scpi-matrix project: `~/Dropbox/build/rf-bench/projects/esp32/scpi-matrix/`
- Bus Pirate I2C reference: http://dangerousprototypes.com/docs/I2C
- rf_bench.relay driver: `~/Dropbox/build/rf-bench/drivers/relay/`
