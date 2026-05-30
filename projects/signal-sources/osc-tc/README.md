# rf-bench-osc-tc

Measures oscillator temperature coefficient (TC) by logging frequency vs. temperature
simultaneously, then computes ppm/°C across the measured temperature range.

Works with any oscillator visible to the SSA3032X Plus. Temperature is read from an
I2C sensor wired to the Bus Pirate — no separate temperature logger needed.

## Hardware required

| Item | Notes |
|------|-------|
| Bus Pirate v3, v4, or v5 | I2C master; v5: use `/dev/ttyACM1` (see below) |
| MCP9808, LM75, or BMP280 | I2C temperature sensor breakout |
| Siglent SSA3032X Plus | Networked at 10.1.1.60 |
| Oscillator under test | Any source; connect to SSA RF input |

**Optional heat source:** hair dryer, heat gun, or oven to sweep temperature range.
Wider temperature sweep → better TC accuracy. At least ±10 °C from ambient recommended.

## Wiring

```
Bus Pirate +3.3V  →  Sensor VCC
Bus Pirate GND    →  Sensor GND
Bus Pirate SDA    →  Sensor SDA
Bus Pirate SCL    →  Sensor SCL
```

Default I2C addresses (A0/A1/A2 all low):

| Sensor | Default Address |
|--------|----------------|
| MCP9808 | 0x18 |
| LM75   | 0x48 |
| BMP280 | 0x76 |

## Bus Pirate v5 — one-time setup

```
screen /dev/ttyACM0 115200
# at the prompt: binmode → 2. BPIO2 flatbuffer interface → save as default
```

BPIO2 persists across reboots.  Then connect to `/dev/ttyACM1` (binary port).

## Usage

```bash
# MCP9808 at default address, 10 MHz oscillator, 2-hour run
python3 osc_tc.py --carrier 10e6 --sensor mcp9808

# v5: specify the binary port
python3 osc_tc.py --carrier 10e6 --sensor mcp9808 --bp /dev/ttyACM1

# LM75 at non-default address, 32.768 kHz TCXO
python3 osc_tc.py --carrier 32768 --sensor lm75 --sensor-addr 0x4A

# BMP280, faster 30-second sample interval, 4-hour run
python3 osc_tc.py --carrier 10e6 --sensor bmp280 \
    --interval 30 --duration 14400

# Re-plot from saved CSV without hardware
python3 osc_tc.py --plot osc_tc_20260527_120000.csv
```

## Output

```
osc_tc_20260527_120000.csv   ← raw data (timestamp, elapsed_s, temp_c, freq_hz, ppm)
osc_tc_20260527_120000.png   ← 4-panel plot
```

**Plots:**
- Temperature vs. time
- Frequency deviation (ppm) vs. time
- ppm vs. temperature scatter with linear + 3rd-order polynomial fits
- Residuals from polynomial fit

**Console output:** Linear TC (ppm/°C), temperature range covered, standard deviation of residuals.

## Notes

- SSA measures carrier frequency using a 5 kHz narrow span and centroid detection.
  Resolution is limited by SSA RBW; expect ±0.1–1 ppm per reading for a clean carrier.
- For TCXO/OCXO measurements, allow 15–30 minutes of warm-up before starting.
- The polynomial fit catches 2nd-order TC (parabolic) as seen in AT-cut crystals.
- BMP280 also measures pressure and humidity but only temperature is used here.
