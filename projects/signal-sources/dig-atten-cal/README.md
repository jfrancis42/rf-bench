# rf-bench-dig-atten-cal

Programs a PE4302 or HMC624A digital step attenuator via Bus Pirate SPI and
measures actual attenuation at every step across multiple frequencies using
the Siglent SSA3032X Plus tracking generator.

Produces a calibration table (JSON) and a 4-panel plot showing actual attenuation,
calibration error per step, error heatmap (step × frequency), and RMS error by frequency.

## Hardware required

| Item | Notes |
|------|-------|
| Bus Pirate v3, v4, or v5 | SPI master; v5: use `/dev/ttyACM1` (see below) |
| PE4302 or HMC624A breakout | Digital step attenuator with SMA connectors |
| Siglent SSA3032X Plus | Networked at 10.1.1.60 — source + measurement |

The SSA tracking generator is used as the RF source, so no separate signal
generator is required. A clean −10 dBm to 0 dBm input level is typical.

## Wiring

```
SSA Tracking Gen Out  →  Attenuator RF-IN (SMA)
Attenuator RF-OUT     →  SSA RF Input (SMA)

Bus Pirate CLK   →  Attenuator CLK / SCLK
Bus Pirate MOSI  →  Attenuator DATA / SIN
Bus Pirate CS    →  Attenuator LE (PE4302) or CSB (HMC624A)
Bus Pirate GND   →  Attenuator GND
Bus Pirate +3.3V →  Attenuator VDD (3.3 V)
```

## Bus Pirate v5 — one-time setup

```
screen /dev/ttyACM0 115200
# at the prompt: binmode → 2. BPIO2 flatbuffer interface → save as default
```

BPIO2 persists across reboots.  Then connect to `/dev/ttyACM1` (binary port).

## Usage

```bash
# PE4302 — default 10-frequency calibration (10 MHz to 3 GHz)
python3 dig_atten_cal.py --chip pe4302 --bp /dev/ttyUSB1

# PE4302 on Bus Pirate v5
python3 dig_atten_cal.py --chip pe4302 --bp /dev/ttyACM1

# HMC624A — custom frequency list
python3 dig_atten_cal.py --chip hmc624a --bp /dev/ttyUSB1 \
    --freqs 100e6,500e6,1e9,2e9,3e9

# Re-plot without hardware
python3 dig_atten_cal.py --plot dig_atten_cal_pe4302_20260527.json
```

## Output

```
dig_atten_cal_pe4302_20260527_120000.json   ← calibration data
dig_atten_cal_pe4302_20260527_120000.png    ← 4-panel plot
```

## Chip SPI protocol summary

| Chip | Word length | CPOL/CPHA | Latch |
|------|------------|-----------|-------|
| PE4302 | 7-bit (pad to 8) | 0/0 | CS rising edge |
| HMC624A | 8-bit | 0/0 | CS rising edge |

Both chips encode attenuation as a 6-bit value where each bit represents a binary
weight: 16 dB, 8 dB, 4 dB, 2 dB, 1 dB, 0.5 dB. Full scale = 31.5 dB.
