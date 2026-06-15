# ESP32+MHS IQ Modulator with DAC Correction

**Status:** 🔨 In Development

Dual-channel IQ modulator with automated DAC correction combining scpi-dac + MHS-5225A + SSA3032X for high-performance quadrature modulation.

## What It Does

Generates precision IQ-modulated RF signals with automated optimization to achieve:
- **Carrier suppression:** >40 dB
- **Sideband imbalance:** <1 dB

The system uses closed-loop optimization with a spectrum analyzer to automatically tune DC offset and gain corrections via a 4-channel DAC, compensating for analog imperfections in the IQ modulator hardware.

## Hardware

### Required Components

1. **scpi-dac** — ESP32-based 4-channel DAC (MCP4728, 12-bit)
   - CH0: I-channel DC offset trim
   - CH1: I-channel gain adjust (0-5V → 0-1x multiplier)
   - CH2: Q-channel DC offset trim
   - CH3: Q-channel gain adjust

2. **MHS-5225A** — Dual-channel DDS signal generator
   - CH1: I-channel carrier (0° reference)
   - CH2: Q-channel carrier (90° phase shift)
   - Independent phase control per channel required for IQ generation

3. **SSA3032X** — Siglent spectrum analyzer (3.2 GHz)
   - Measures carrier suppression and sideband symmetry
   - Provides feedback for optimization loop

4. **Resistive combiner** — External 2-input RF combiner
   - Sums I and Q signals after DAC correction
   - Simple resistive design (e.g., two 50Ω resistors to 50Ω load)

### Wiring Diagram

```
MHS-5225A CH1 (I, 0°) ───→ [DAC CH0/CH1 trim] ───┐
                                                   ├─→ Combiner ───→ SSA3032X
MHS-5225A CH2 (Q, 90°) ──→ [DAC CH2/CH3 trim] ───┘

scpi-dac connections:
  CH0 output → I-channel DC offset summing junction
  CH1 output → I-channel gain control (VCA or analog multiplier)
  CH2 output → Q-channel DC offset summing junction
  CH3 output → Q-channel gain control
```

**Note:** The exact analog implementation between DAC outputs and the combiner depends on your hardware design. Common approaches include:
- **Summing amplifiers** with DAC-controlled offset voltage
- **Voltage-controlled attenuators** (VCA) for gain trim
- **Analog multipliers** (e.g., AD633) for precision gain control

## Installation

```bash
pip install rf-bench-drivers-koolertron rf-bench-drivers-siglent
```

Ensure you have:
- `scpi-dac` firmware flashed to ESP32 (see `~/Dropbox/build/rf-bench/projects/esp32/scpi-dac/`)
- MHS-5225A connected via USB-serial
- SSA3032X accessible via Ethernet

## Theory of Operation

### IQ Modulation Fundamentals

An IQ (In-phase/Quadrature) modulator generates complex RF signals by combining two carriers with a 90° phase relationship:

```
Output(t) = I(t) · cos(ωt) + Q(t) · sin(ωt)
```

Where:
- `I(t)` = in-phase baseband signal
- `Q(t)` = quadrature baseband signal (90° phase shift)
- `ω` = carrier angular frequency

### Why IQ Modulation?

IQ modulation enables:
- **Single-sideband (SSB) generation** — suppressing carrier and one sideband
- **Arbitrary modulation formats** — QPSK, QAM, OFDM, etc.
- **Precise frequency control** — generate signals at arbitrary offsets from the carrier

### Common Imperfections

Real-world IQ modulators suffer from:

1. **DC offset** — unwanted DC component in I or Q channel
   - Appears as carrier feedthrough (incomplete carrier suppression)
   - Typical uncorrected: 20-30 dB suppression

2. **Gain imbalance** — I and Q channels have different amplitudes
   - Causes asymmetric sidebands
   - One sideband higher than the other

3. **Phase imbalance** — I and Q not exactly 90° apart
   - Also causes sideband asymmetry
   - Not correctable with this DAC setup (requires phase adjustment)

### Optimization Metrics

**Carrier suppression:** Ratio of sideband power to carrier power
- Good: >40 dB
- Excellent: >50 dB
- Measured as: `(USB_level + LSB_level)/2 - Carrier_level`

**Sideband imbalance:** Difference between upper and lower sideband levels
- Good: <1 dB
- Excellent: <0.5 dB
- Measured as: `|USB_level - LSB_level|`

### Optimization Algorithms

#### Grid Search
- **Method:** Exhaustively test all combinations in a parameter grid
- **Pros:** Guaranteed to find global optimum within grid resolution
- **Cons:** Slow (resolution⁴ iterations; 5⁴ = 625 measurements)
- **Use when:** You need guaranteed best result and have time

#### Gradient Descent
- **Method:** Iteratively adjust parameters in direction of improvement
- **Pros:** Fast convergence (typically <50 iterations)
- **Cons:** Can get stuck in local optima
- **Use when:** You have a good initial guess or time is limited

#### Hybrid (Recommended)
- **Method:** Coarse grid search (3×3×3×3 = 81 measurements) followed by gradient descent
- **Pros:** Combines global search with fast convergence
- **Cons:** Moderate total time
- **Use when:** You want best of both worlds

## Usage

### Basic Optimization

```bash
./iq_optimize.py \
  --esp-dac 10.1.0.100 \
  --mhs-port /dev/ttyUSB0 \
  --ssa 10.1.0.101 \
  --carrier-freq-mhz 10 \
  --mod-freq-khz 10
```

This will:
1. Configure MHS-5225A to generate 10 MHz IQ carriers
2. Apply 10 kHz tone modulation (baseband)
3. Measure carrier at 10 MHz, sidebands at 10.01 MHz and 9.99 MHz
4. Optimize DAC corrections via hybrid method
5. Display optimal settings and achieved performance

### Save Corrections to EEPROM

```bash
./iq_optimize.py \
  --esp-dac 10.1.0.100 \
  --mhs-port /dev/ttyUSB0 \
  --ssa 10.1.0.101 \
  --carrier-freq-mhz 10 \
  --mod-freq-khz 10 \
  --save-eeprom
```

The MCP4728 DAC will retain these settings across power cycles.

### Choose Optimization Method

```bash
# Fast: gradient descent only (~2 minutes)
./iq_optimize.py ... --method gradient

# Thorough: exhaustive grid search (~10 minutes)
./iq_optimize.py ... --method grid

# Balanced: hybrid approach (~5 minutes, default)
./iq_optimize.py ... --method hybrid
```

### Example Output

```
============================================================
IQ Modulator Optimization
============================================================

Connecting to instruments...
✓ Connected to scpi-dac at 10.1.0.100
✓ Connected to MHS-5225A at /dev/ttyUSB0
✓ Connected to SSA3032X at 10.1.0.101

Configuring MHS-5225A:
  Carrier: 10.0 MHz
  Modulation: 10.0 kHz
✓ Generators configured

Configuring SSA3032X:
  Center: 10.0 MHz
  Span: 50.0 kHz
✓ Analyzer configured

Baseline measurement (no correction):
  Carrier suppression: 23.4 dB
  Sideband imbalance: 3.2 dB

Phase 1: Coarse grid search
  Progress: 50.0% (best carrier suppression: 38.7 dB)
✓ Grid search complete (81 iterations)

Phase 2: Fine gradient descent
  Iteration 10/100: carrier suppression = 42.1 dB, sideband imbalance = 0.8 dB
✓ Target performance achieved at iteration 23

============================================================
OPTIMAL SETTINGS
============================================================

DAC Voltages:
  I-channel offset: 2.487 V
  I-channel gain:   2.631 V
  Q-channel offset: 2.523 V
  Q-channel gain:   2.459 V

Performance:
  Carrier suppression: 43.7 dB
  Sideband imbalance:  0.7 dB
  USB level:           -12.3 dBm
  LSB level:           -13.0 dBm

Improvement: +20.3 dB carrier suppression

Goals:
  ✓ Carrier suppression >40 dB: PASS
  ✓ Sideband imbalance <1 dB: PASS

✓ Done
```

## Use Cases

### SDR Transmitter Calibration
Calibrate IQ DACs in SDR transmitters (e.g., HackRF, LimeSDR, PlutoSDR) by measuring their output and providing correction coefficients.

### IQ Modulator Testing
Characterize commercial IQ modulators or mixers. Sweep carrier frequency to measure suppression vs. frequency.

### Modulation Format Development
Generate clean IQ test signals for developing and testing demodulators for QPSK, 16QAM, 64QAM, etc.

### Education
Demonstrate practical IQ modulation concepts, show impact of DC offset and gain imbalance, visualize optimization in real-time.

## Limitations

### What This System Does NOT Correct

1. **Phase imbalance** — if I and Q are not exactly 90° apart
   - Requires hardware phase shifter control
   - MHS-5225A phase setting has ~1° resolution (adequate for basic IQ)
   - For <0.1° phase accuracy, use VNA-grade synthesizers

2. **Harmonic distortion** — nonlinearities in analog chain
   - Use high-quality op-amps and mixers
   - Keep signal levels in linear region

3. **Frequency-dependent effects** — filter group delay, mixer isolation
   - Optimization is valid only near the test frequency
   - For wideband operation, characterize corrections vs. frequency

### Hardware Constraints

- **DAC resolution:** 12-bit (0.0012 V steps) limits fine adjustment
- **Settling time:** ~200 ms per DAC update (includes analog circuit settling)
- **Frequency range:** Limited by MHS-5225A (0-25 MHz) and analog combiner bandwidth

## Future Enhancements

### Automated Modulation Format Testing
- Generate QPSK constellation, measure EVM (Error Vector Magnitude)
- Test 16QAM, 64QAM with symbol rate sweep
- BER (Bit Error Rate) testing with loopback to receiver

### Multi-Frequency Calibration
- Sweep carrier frequency, build correction lookup table
- Interpolate corrections for arbitrary frequencies
- Compensate for frequency-dependent mixer/amplifier response

### Phase Error Correction
- Add phase-adjustable splitter (e.g., LTC6957 with programmable delay)
- Optimize phase in addition to DC offset and gain
- Achieve >60 dB carrier suppression

### Real-Time Modulation
- Stream I/Q samples from PC to scpi-dac at audio rates
- Generate arbitrary waveforms (not just single tones)
- Implement digital pre-distortion

## References

- **IQ Modulation Theory:** "RF Microelectronics" by Razavi, Chapter 6
- **Calibration Techniques:** AN-1039 (Analog Devices), "Quadrature Error Correction"
- **MCP4728 Datasheet:** Microchip, 12-bit I²C DAC with EEPROM
- **MHS-5225A Protocol:** `~/Dropbox/build/rf-bench/drivers/koolertron/docs/`

## Troubleshooting

### Poor Carrier Suppression (<30 dB)

**Symptom:** Optimization improves suppression only slightly.

**Causes:**
1. Insufficient DAC range — offset or gain limit reached
2. Analog circuit has excessive DC drift or noise
3. Combiner has poor isolation

**Solutions:**
- Inspect DAC voltages in output — if any are at rail (0V or 5V), increase adjustment range in hardware
- Use low-drift op-amps (e.g., OPA2277, LT1013)
- Add shielding and bypass capacitors to analog circuitry
- Use hybrid combiner (transformer-based) instead of resistive

### High Sideband Imbalance (>2 dB)

**Symptom:** USB and LSB levels differ by >2 dB even after optimization.

**Causes:**
1. Phase error (I and Q not 90° apart)
2. Frequency-dependent amplitude response in analog path
3. Measurement error (SSA RBW too wide, noise floor too high)

**Solutions:**
- Verify MHS-5225A phase setting: CH2 should be exactly 90.0°
- Use narrower SSA RBW (100 Hz or less) for accurate sideband measurement
- Add adjustable phase shifter in analog path (varactor-tuned or trombone line)

### Optimization Doesn't Converge

**Symptom:** Gradient descent wanders, never reaches goal.

**Causes:**
1. Noise floor too high — SSA can't measure accurately
2. Local optima in cost function
3. Learning rate too high (oscillates) or too low (stuck)

**Solutions:**
- Increase signal level (MHS amplitude) to improve SNR
- Switch to grid search method (slower but more robust)
- Adjust learning rate: try 0.005 (slower, stabler) or 0.02 (faster, less stable)

### EEPROM Save Fails

**Symptom:** Settings lost after power cycle.

**Causes:**
1. scpi-dac firmware doesn't support `*SAV` command
2. I²C communication error with MCP4728
3. EEPROM write-protect enabled

**Solutions:**
- Update scpi-dac firmware to latest version
- Check I²C pull-ups (should be 4.7kΩ to 3.3V)
- Verify MCP4728 WP pin is grounded (write-protect disabled)

## License

GPL-3.0-or-later — see repository root for details.

## Author

Created as part of the rf-bench project: https://github.com/jfrancis42/rf-bench
