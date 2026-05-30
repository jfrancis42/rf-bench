# rf-bench-synthesizer-characterizer

Programs Si5351 or ADF4351 PLL synthesizer modules via Bus Pirate and measures
their actual RF output on a Siglent SSA3032X Plus spectrum analyzer.

Produces a complete performance map — what your specific chip actually does
across its frequency range, not just datasheet typical values.

## Measurements

At each programmed frequency:
- **Frequency accuracy** (ppm error vs. programmed value)
- **Output power** (dBm)
- **2nd and 3rd harmonic** levels (dBc)

## Hardware required

| Item | Notes |
|------|-------|
| Bus Pirate v3, v4, or v5 | v5: connect to `/dev/ttyACM1` (binary port) |
| Si5351 or ADF4351 module | With SMA output |
| Siglent SSA3032X Plus | Networked at 10.1.1.60 |
| SMA cable | Chip output → SSA RF input |
| Attenuator (optional) | Protect SSA if output > 0 dBm |

**Si5351 wiring:**
```
Bus Pirate MOSI/SDA  →  Si5351 SDA (with pull-up to 3.3V)
Bus Pirate CLK/SCL   →  Si5351 SCL (with pull-up to 3.3V)
Bus Pirate GND       →  Si5351 GND
Bus Pirate +3.3V     →  Si5351 VCC (or use set_power(True))
Si5351 CLK0 output   →  SSA RF input (via SMA)
```

**ADF4351 wiring:**
```
Bus Pirate MOSI  →  ADF4351 DATA
Bus Pirate CLK   →  ADF4351 CLK
Bus Pirate CS    →  ADF4351 LE  (latch enable, active-high pulse)
Bus Pirate GND   →  ADF4351 GND
ADF4351 RFOUT+   →  SSA RF input
```
> Note: ADF4351 requires a separate 3.3V/5V supply for VCC; Bus Pirate 3.3V
> output may not source enough current for the ADF4351 VCO.

## Bus Pirate v5 — one-time setup

Before first use with a v5, activate BPIO2 on the terminal port:

```
screen /dev/ttyACM0 115200
# at the prompt: binmode → 2. BPIO2 flatbuffer interface → save as default
# then connect the driver to /dev/ttyACM1 (the binary port)
```

BPIO2 persists across reboots — this is a one-time step.

## Usage

```bash
# Si5351: default sweep 100 kHz–200 MHz  (v3/v4)
python3 synthesizer_characterizer.py --chip si5351 --bp /dev/ttyUSB1

# Si5351 on Bus Pirate v5 (connect to binary port)
python3 synthesizer_characterizer.py --chip si5351 --bp /dev/ttyACM1

# ADF4351: 35 MHz – 500 MHz, 60 steps
python3 synthesizer_characterizer.py --chip adf4351 --bp /dev/ttyUSB1 \
    --start 35e6 --stop 500e6 --steps 60

# Different crystal reference (27 MHz)
python3 synthesizer_characterizer.py --chip si5351 --xtal 27e6

# Re-plot from saved data (no instruments needed)
python3 synthesizer_characterizer.py --plot synth_si5351_20260527_120000.json
```

## Output

```
synth_si5351_20260527_120000.json   ← all data
synth_si5351_20260527_120000.png    ← 3-panel plot
```

The JSON calibration table can be loaded by other bench scripts that need to
know the actual vs. nominal frequency at each programmed output.

## Sample results — Si5351A, 25 MHz crystal, 4 mA drive

100-point geomspace sweep, 100 kHz – 200 MHz, Bus Pirate v5 / SSA3032X Plus.

![Si5351 characterization — 100 kHz to 200 MHz](synth_si5351_20260527_171324.png)

**Frequency accuracy (100 kHz – 120 MHz):**
Crystal running ~125 ppm high across the full HF range — consistent with an
un-trimmed 25 MHz crystal module.  Corrects to sub-1 ppm once this offset is applied.

**Output power:**
Rises from −9 dBm at 100 kHz to a peak of +8.6 dBm at ~4.3 MHz (4 mA drive),
holds ~+8 dBm through 100 MHz, then rolls off sharply above ~130 MHz.

**2nd harmonic:** −25 to −40 dBc across 1–100 MHz (worsens at lower frequencies
where the square-wave output has many harmonics in the measurement band).

**3rd harmonic:** −8 to −10 dBc in the HF range — poor, as expected from a
square-wave output stage.  A low-pass filter on CLK0 is strongly recommended for
any spurious-sensitive application.

**High-frequency anomalies:** PLL loses reliable lock above ~130 MHz on this
sample; output power collapses and frequency accuracy degrades significantly.
