# rf-bench-dds-characterizer

Programs AD9833 or AD9851 DDS chips via Bus Pirate and measures actual RF output
on a Siglent SSA3032X Plus.

DDS chips produce different spurs than PLL chips — DAC quantization aliases land
at predictable offsets based on the tuning word / clock ratio.  This tool maps
SFDR (spurious-free dynamic range) across the full frequency range so you know
which frequencies are "clean" and which to avoid in your design.

## Hardware required

| Item | Notes |
|------|-------|
| Bus Pirate v3, v4, or v5 | SPI master; v5: use `/dev/ttyACM1` (see below) |
| AD9833 or AD9851 breakout | With SMA or coax output |
| Siglent SSA3032X Plus | Networked at 10.1.1.60 |

**AD9833 wiring:**
```
Bus Pirate CLK   →  AD9833 SCLK
Bus Pirate MOSI  →  AD9833 SDATA
Bus Pirate CS    →  AD9833 FSYNC (active-low)
Bus Pirate GND   →  AD9833 GND
AD9833 OUT       →  SSA RF input (via SMA)
```

**AD9851 wiring:**
```
Bus Pirate CLK   →  AD9851 W_CLK
Bus Pirate MOSI  →  AD9851 D7 (serial data)
Bus Pirate CS    →  AD9851 FQ_UD (frequency update, active rising edge)
AD9851 IOUT      →  SSA RF input (50Ω termination)
```

## Bus Pirate v5 — one-time setup

```
screen /dev/ttyACM0 115200
# at the prompt: binmode → 2. BPIO2 flatbuffer interface → save as default
```

BPIO2 persists across reboots.  Then connect to `/dev/ttyACM1` (binary port).

## Usage

```bash
# AD9833 with 25 MHz MCLK (default)
python3 dds_characterizer.py --chip ad9833 --bp /dev/ttyUSB1

# AD9833 on Bus Pirate v5
python3 dds_characterizer.py --chip ad9833 --bp /dev/ttyACM1

# AD9851 with 30 MHz crystal + 6x multiplier
python3 dds_characterizer.py --chip ad9851 --bp /dev/ttyUSB1 \
    --xtal 30e6 --start 1e6 --stop 60e6 --steps 60

# Re-plot without hardware
python3 dds_characterizer.py --plot dds_ad9833_20260527.json
```

## Output

```
dds_ad9833_20260527_120000.json   ← all data
dds_ad9833_20260527_120000.png    ← 4-panel plot
```

Panels: output power (sinc rolloff) · frequency accuracy (ppm) ·
SFDR (worst spur within ±1 MHz) · harmonic content.
