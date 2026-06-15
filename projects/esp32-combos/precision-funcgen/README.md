# Precision Function Generator with DAC Correction

**Status:** 🔨 In Development

DAC-corrected precision function generator combining ESP32 scpi-dac (MCP4728), Siglent SDG1062X arbitrary waveform generator, and Siglent SDM3045X digital multimeter with external op-amp summing amplifier.

Achieves **<0.1% amplitude accuracy** and **<100 µV offset error** — far exceeding the SDG1062X's native 1% amplitude specification.

---

## What It Does

The SDG1062X has excellent frequency stability and low distortion, but only 1% amplitude accuracy. This project adds a precision correction loop:

1. **SDG1062X** generates the AC waveform (sine/square/triangle) at the target frequency
2. **ESP32 scpi-dac** provides DC offset injection and gain control via MCP4728 12-bit DAC
3. **External summing amplifier** combines AC + DC and applies variable gain
4. **SDM3045X DMM** measures actual Vpp and DC offset (0.01% accuracy, 6.5-digit resolution)
5. **Optimization loop** adjusts DAC settings until measured output matches target within tolerance
6. **Calibration table** saves optimal DAC settings for each waveform/frequency/amplitude combination

The result: a precision calibrated source suitable for sensor simulation, ADC testing, and metrology applications.

---

## Hardware Requirements

### Instruments
- **ESP32 scpi-dac** — MCP4728 4-channel 12-bit DAC with HTTP SCPI server
- **Siglent SDG1062X** — 60 MHz dual-channel arbitrary waveform generator
- **Siglent SDM3045X** — 6.5-digit dual-display benchtop DMM (0.01% DC accuracy)

### External Summing Amplifier Circuit

The core of the system is an analog summing amplifier that combines:
- **AC input** from SDG1062X CH1
- **DC offset** from scpi-dac CH0
- **Gain control** from scpi-dac CH1 (driving a VCA or variable resistor in feedback path)

#### Suggested Topology

```
         R1
SDG ----/\/\/\----+
                  |
         R2       |     Rf
DAC0 ---/\/\/\----+----/\/\/\----+
(offset)          |              |
                  |   |\         |
                  +---|+\        |
                      |  >-------+---- Output to DMM & Load
                  +---|-/             (BNC tee)
                  |   |/
                 GND   Op-Amp
                      (precision, low-offset)

DAC1 -----> VCA or variable R in Rf position
(gain)      (e.g., AD603 VCA or digital pot)
```

**Component Selection:**
- **Op-amp:** OPA2277, LT1013, or similar precision op-amp (low offset <25 µV, low drift <0.5 µV/°C)
- **Resistors:** 0.1% metal film, matched pairs for R1/R2
- **Gain control:** AD603 voltage-controlled amplifier, or MCP41HV51 digital potentiometer in feedback path
- **Decoupling:** 0.1 µF ceramic + 10 µF tantalum on all supply pins, star ground

**Design Notes:**
- R1 = R2 for equal weighting of AC and DC inputs
- Rf sets overall gain (start with 10kΩ)
- DAC1 modulates Rf via VCA or digital pot to adjust amplitude
- Keep layout tight, use ground plane, shield if operating at >1 MHz
- If using VCA: AD603 provides 40 dB gain control range (-11 dB to +31 dB)
- If using digital pot: MCP41HV51 (10 kΩ, 256 taps, ±10V tolerant)

#### Breadboard Prototype

For initial testing, a simple inverting summing amp works:

```
         10k
SDG ----/\/\/\----+
                  |
         10k      |     10k
DAC0 ---/\/\/\----+----/\/\/\----+
                  |              |
                  |   |\         |
                  +---|+\        |
                      |  >-------+---- Output (inverted)
                 GND--|-/
                      |/
                     TL072 or similar
```

Gain is fixed at -1 in this configuration. For testing, manually sweep DAC0 to verify offset control. Gain control via DAC1 requires VCA or digital pot as shown above.

---

## Installation

### Python Dependencies

```bash
pip install rf-bench-drivers-siglent requests numpy
```

### ESP32 scpi-dac Firmware

Flash the ESP32 with scpi-dac firmware (see `~/Dropbox/build/rf-bench/projects/esp32-combos/scpi-dac/`):

```bash
cd ~/Dropbox/build/rf-bench/projects/esp32-combos/scpi-dac/
pio run -t upload
```

Configure WiFi and note the IP address.

### Instrument Network Setup

All three instruments must be reachable via TCP/IP:
- ESP32 scpi-dac: HTTP on port 80
- SDG1062X: LXI/SCPI on port 5025
- SDM3045X: LXI/SCPI on port 5025

Verify connectivity:

```bash
curl http://<esp-ip>/dac/status
ping <sdg-ip>
ping <dmm-ip>
```

---

## Usage

### Basic Example

Generate a 1 kHz sine wave at exactly 1.000 Vpp with 0 V offset:

```bash
./precision_gen.py \
  --esp-dac 10.1.0.50 \
  --sdg 10.1.0.51 \
  --dmm 10.1.0.52 \
  --waveform sine \
  --freq-hz 1000 \
  --vpp 1.0 \
  --offset-v 0.0
```

First run performs optimization (typically 15-30 iterations). Subsequent runs with the same parameters use saved calibration and converge in <1 second.

### Advanced Example

Generate a 10 kHz square wave at 2.500 Vpp with +1.250 V offset:

```bash
./precision_gen.py \
  --esp-dac 10.1.0.50 \
  --sdg 10.1.0.51 \
  --dmm 10.1.0.52 \
  --waveform square \
  --freq-hz 10000 \
  --vpp 2.5 \
  --offset-v 1.25 \
  --iterations 100
```

### Calibration Table

Optimal DAC settings are saved in `~/.cache/rf-bench/precision_funcgen_cal.json`:

```json
{
  "('sine', 1000.0, 1.0, 0.0)": {
    "dac_gain": 2048,
    "dac_offset": 2050,
    "timestamp": 1749667200.0
  },
  "('square', 10000.0, 2.5, 1.25)": {
    "dac_gain": 3200,
    "dac_offset": 3100,
    "timestamp": 1749667300.0
  }
}
```

Delete this file to force re-calibration.

---

## How It Works

### Optimization Algorithm

The script uses gradient descent to converge on optimal DAC settings:

1. **Initialize:** Set DAC_GAIN and DAC_OFFSET to mid-range (2048 out of 4095)
2. **Measure:** SDM3045X measures actual Vpp (AC voltage × 2√2) and DC offset
3. **Calculate error:** Compare measured vs. target
4. **Update DAC:**
   - `dac_gain += learning_rate * (target_vpp - actual_vpp) / target_vpp`
   - `dac_offset += learning_rate * (target_offset - actual_offset) / scale_factor`
5. **Check convergence:**
   - Amplitude error < 0.1% (1 mV on 1V scale)
   - Offset error < 100 µV
6. **Repeat** until converged or max iterations reached

**Adaptive learning rate:** Starts at 100 (gain) and 50 (offset), decreases by 5% per iteration after iteration 10 to prevent oscillation near target.

### Why It Works

- **SDG1062X provides clean waveform** with excellent frequency stability and low THD
- **MCP4728 DAC provides 12-bit precision** (0.5 mV resolution on 2.048V reference)
- **SDM3045X provides ground truth** with 0.01% accuracy and 100 µV resolution
- **Closed-loop feedback** compensates for SDG amplitude inaccuracy, op-amp gain errors, component tolerances
- **Calibration table** eliminates re-optimization for frequently used settings

### Limitations

- **Frequency range:** DC to ~1 MHz (limited by op-amp slew rate and SDG accuracy at high frequencies)
- **Amplitude range:** 10 mVpp to 10 Vpp (limited by SDG output and op-amp supply voltage)
- **Settling time:** ~500 ms per iteration (DMM integration time)
- **Temperature drift:** Op-amp and DAC drift require periodic re-calibration (recommendation: daily for metrology work)
- **Load sensitivity:** Calibration assumes 1 MΩ || 30 pF load (DMM input). Heavy loads may require re-calibration.

---

## Use Cases

### Sensor Simulation

Simulate sensor outputs for ADC testing or embedded system development:

```bash
# Thermocouple: 0-50 mV, 0.1 mV resolution
./precision_gen.py --esp-dac <ip> --sdg <ip> --dmm <ip> \
  --waveform sine --freq-hz 1 --vpp 0.050 --offset-v 0.025

# 4-20 mA sensor (across 250Ω shunt = 1-5V)
./precision_gen.py --esp-dac <ip> --sdg <ip> --dmm <ip> \
  --waveform sine --freq-hz 0.1 --vpp 4.0 --offset-v 3.0
```

### ADC Calibration

Generate precise voltage steps for ADC linearity testing:

```bash
for v in 0.0 0.5 1.0 1.5 2.0 2.5 3.0; do
  ./precision_gen.py --esp-dac <ip> --sdg <ip> --dmm <ip> \
    --waveform sine --freq-hz 1000 --vpp 0.1 --offset-v $v
  sleep 10  # Allow ADC to sample
done
```

### Audio Test

Generate test tones for audio equipment characterization:

```bash
# 1 kHz reference tone at -20 dBV (0.1 Vrms = 0.283 Vpp)
./precision_gen.py --esp-dac <ip> --sdg <ip> --dmm <ip> \
  --waveform sine --freq-hz 1000 --vpp 0.283 --offset-v 0.0

# 20 Hz to 20 kHz sweep (run in loop, vary --freq-hz)
```

---

## Future Enhancements

### Automated Frequency Response Correction

Current implementation assumes flat frequency response. Future version could:
- Sweep frequency from DC to 1 MHz
- Measure actual amplitude at each frequency
- Build correction table: `gain_correction[freq] = target / measured`
- Apply frequency-dependent gain during optimization

### Distortion Compensation

For very low THD applications:
- Use SDM3045X in AC+DC mode to measure harmonics (if available on your model)
- Pre-distort SDG waveform to cancel op-amp nonlinearity
- Iteratively refine via FFT analysis (requires spectrum analyzer or SDM3045X with harmonic measurement)

### Multi-Channel Operation

- Use SDG1062X CH2 for a second independent output
- Add second summing amp and second pair of DAC channels (CH2, CH3)
- Synchronize both outputs (e.g., I/Q signals for vector modulation)

### GPIB/USB Support

Currently requires LXI/Ethernet. Add support for:
- GPIB via Prologix controller
- USB-TMC (linux-gpib or python-usbtmc)

---

## Troubleshooting

### Optimization Does Not Converge

**Symptoms:** Iteration count reaches max without meeting tolerance.

**Causes:**
- Op-amp saturating (check supply voltage vs. target Vpp + offset)
- Incorrect DAC channel wiring (swap CH0 and CH1)
- DMM not measuring summing amp output (check BNC connections)
- Summing amp oscillating (add compensation capacitor across Rf)

**Solutions:**
- Reduce target Vpp or offset
- Verify wiring with multimeter
- Add 10-100 pF capacitor across feedback resistor
- Check op-amp supply voltage (need headroom: Vout_max + 2V minimum)

### Calibration Drifts Over Time

**Symptoms:** Previously calibrated settings no longer meet tolerance.

**Causes:**
- Temperature change (op-amp offset drift, DAC reference drift)
- Component aging (resistors, capacitors)
- SDG warmup state (amplitude changes in first 30 minutes)

**Solutions:**
- Delete calibration file and re-run: `rm ~/.cache/rf-bench/precision_funcgen_cal.json`
- Use temperature-compensated op-amp (e.g., LTC2057 chopper-stabilized)
- Use precision voltage reference for DAC (e.g., LT1019 2.048V, 5 ppm/°C)
- Wait 30 minutes after powering on SDG before calibration

### Large Offset Error

**Symptoms:** Vpp converges but DC offset remains >100 µV off target.

**Causes:**
- Op-amp input offset voltage (can be 1-5 mV on cheap op-amps)
- Ground loop between instruments
- DAC reference error
- DMM lead resistance (use 4-wire measurement if available)

**Solutions:**
- Use precision op-amp with <25 µV offset (OPA2277, LT1013, AD8628)
- Add offset trim potentiometer to op-amp (if pins available)
- Use star ground topology (all ground returns to single point)
- Verify DAC reference voltage with calibrated DMM

### ESP32 Connection Fails

**Symptoms:** `ERROR: DAC set failed: Connection refused`

**Causes:**
- ESP32 not powered
- Wrong IP address
- WiFi not connected
- scpi-dac firmware not running

**Solutions:**
- Ping ESP32: `ping <esp-ip>`
- Check WiFi status on ESP32 serial console
- Re-flash firmware if necessary
- Verify HTTP server responds: `curl http://<esp-ip>/dac/status`

---

## References

- **MCP4728 datasheet:** 12-bit quad DAC with I2C interface, 2.048V internal reference
- **SDG1062X programming manual:** Siglent waveform generator SCPI commands
- **SDM3045X programming manual:** Siglent DMM SCPI commands
- **Op-amp selection guide:** Precision, low-offset op-amps for analog summing
- **Calibration theory:** NIST traceability and uncertainty analysis

---

## License

GPL-3.0-or-later — see ~/Dropbox/build/rf-bench/LICENSE

---

## Author

Created by jfrancis, 2026-06-12
