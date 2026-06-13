# MDS Sweep - Automated Receiver Sensitivity Measurement

**Status:** 🔨 Under Development

Automated receiver MDS (Minimum Detectable Signal) measurement combining scpi-atten, SSA3032X tracking generator, and IC-7300/IC-9700 via Hamlib.

## What it Does

Measures receiver sensitivity across a frequency range by:
1. Tuning the radio to each frequency
2. Applying a calibrated signal from the SSA TG
3. Stepping attenuation until the S-meter drops to noise floor
4. Recording the MDS (signal level at threshold)
5. Generating a plot of MDS vs frequency

This provides a complete picture of receiver sensitivity across HF/VHF bands, useful for comparing radios, evaluating front-end filters, and diagnosing receiver problems.

## Hardware Requirements

- **scpi-atten** ESP32 device (PE4302 or HMC472 digital attenuator)
  - Provides 0-80 dB attenuation in 0.5 dB steps
  - See `~/Dropbox/build/rf-bench/projects/esp32/scpi-atten/`

- **SSA3032X Spectrum Analyzer** with tracking generator
  - TG provides calibrated signal source (verify with power meter)
  - Default: 0 dBm output

- **IC-7300 or IC-9700** transceiver via Hamlib
  - rigctld must be running and connected to radio
  - S-meter readout provides sensitivity threshold detection

## Wiring

```
SSA3032X TG output (50Ω)
    |
    v
scpi-atten input (50Ω)
    |
    v
scpi-atten output (50Ω)
    |
    v
Radio antenna input (50Ω)
```

**CRITICAL:** Verify TG output power with a calibrated power meter before first use. SSA TG output may vary from nominal specification. Record actual power and use `--tg-power` argument.

## Installation

```bash
pip install rf-bench-drivers-siglent rf-bench-drivers-icom requests matplotlib numpy
```

Ensure rigctld is running:
```bash
# IC-7300
rigctld -m 373 -r /dev/ttyUSB0 -s 115200

# IC-9700
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200
```

## Usage

### HF Sweep (7-30 MHz, IC-7300)

```bash
./mds_sweep.py \
  --esp-atten 10.1.0.50 \
  --ssa 10.1.0.40 \
  --radio IC7300 \
  --freq-start 7.0 \
  --freq-stop 30.0 \
  --step 1.0 \
  --output hf_mds.png
```

### VHF Sweep (144-148 MHz, IC-9700)

```bash
./mds_sweep.py \
  --esp-atten 10.1.0.50 \
  --ssa 10.1.0.40 \
  --radio IC9700 \
  --freq-start 144.0 \
  --freq-stop 148.0 \
  --step 0.5 \
  --output vhf_mds.png
```

### Fine-Resolution Sweep (1 MHz with 100 kHz steps)

```bash
./mds_sweep.py \
  --esp-atten 10.1.0.50 \
  --ssa 10.1.0.40 \
  --radio IC7300 \
  --freq-start 14.0 \
  --freq-stop 15.0 \
  --step 0.1 \
  --output 20m_mds_fine.png
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--esp-atten` | scpi-atten IP address | required |
| `--ssa` | SSA3032X IP address | required |
| `--rigctld-host` | rigctld hostname | localhost |
| `--rigctld-port` | rigctld port | 4532 |
| `--radio` | Radio model (IC7300, IC9700) | required |
| `--freq-start` | Start frequency (MHz) | required |
| `--freq-stop` | Stop frequency (MHz) | required |
| `--step` | Frequency step (MHz) | required |
| `--tg-power` | TG output power (dBm) | 0.0 |
| `--atten-start` | Starting attenuation (dB) | 0.0 |
| `--atten-stop` | Maximum attenuation (dB) | 80.0 |
| `--atten-step` | Attenuation step (dB) | 0.5 |
| `--s-threshold` | S-meter threshold (S-units) | 1 (S1) |
| `--output` | Output plot filename | mds_sweep.png |

## Interpreting Results

### Typical MDS Values

- **Excellent:** < -130 dBm (lab-grade receivers)
- **Very Good:** -125 to -130 dBm (high-end amateur transceivers)
- **Good:** -120 to -125 dBm (mid-range transceivers)
- **Fair:** -100 to -120 dBm (budget receivers, presence of strong signals)
- **Poor:** > -100 dBm (overload, desense, or equipment problem)

### Common Patterns

- **Flat response:** Good front-end filter design
- **Dips at specific frequencies:** Possible internal oscillator products or external interference
- **Rising MDS at band edges:** Normal for crystal/SAW filters with steep skirts
- **Sudden degradation:** May indicate preamp failure, filter damage, or connector problem

### S-Meter Linearity Issues

Most amateur transceivers have **non-linear S-meters** that do not follow the ITU standard (S9 = -73 dBm, 6 dB per S-unit). The script uses a consistent threshold (default S1) rather than assuming absolute calibration. This gives relative sensitivity comparison but not necessarily absolute MDS in the strict RF engineering sense.

For absolute MDS:
- Use a calibrated attenuator (scpi-atten PE4302 provides ±0.25 dB accuracy typical)
- Verify TG output power with a calibrated power meter
- Determine actual signal level at S1 threshold for your specific radio

## Relationship to Noise Figure

MDS is related to receiver noise figure (NF) by:

```
MDS = -174 dBm + 10·log₁₀(BW) + NF + SNR
```

Where:
- -174 dBm/Hz is thermal noise floor (kT at 290 K)
- BW is receiver bandwidth (Hz)
- NF is noise figure (dB)
- SNR is required signal-to-noise ratio for detection (typically 3-10 dB)

Example for SSB (2.4 kHz BW), 10 dB SNR:
- Thermal noise: -174 + 10·log₁₀(2400) = -140 dBm
- With 10 dB NF and 10 dB SNR: MDS = -140 + 10 + 10 = -120 dBm

This script measures the **system MDS** (combined noise floor + detection threshold) rather than computing theoretical NF. Use `~/Dropbox/build/rf-bench/projects/radio/noise-figure/` for direct NF measurement with Y-factor method.

## Future Enhancements

- **TX power sweep:** Add `--tx-mode` flag to measure transmit power vs frequency (requires scpi-ptt for PTT control)
- **Preamp comparison:** Measure with preamp on/off to quantify preamp gain and NF contribution
- **Attenuator testing:** Use `--internal-atten` flag to test radio's built-in attenuator accuracy
- **AGC response:** Record S-meter vs signal level to characterize AGC behavior
- **IMD testing:** Two-tone setup to measure third-order intercept point (IP3)

## Troubleshooting

### S-meter never reaches threshold
- Verify TG is enabled and outputting signal (check with external power meter or second receiver)
- Check coax connections between TG → atten → radio
- Verify scpi-atten is attenuating (measure with power meter at output while stepping attenuation)
- Try lower `--s-threshold` (e.g., S0 instead of S1)

### Inconsistent results
- Ensure radio AGC is enabled and set to consistent mode (FAST/MID/SLOW)
- Allow sufficient settling time between frequency changes (increase delays in code if needed)
- Verify no external interference or strong signals present (disconnect antenna, use shielded test setup)

### TG power inaccurate
- SSA3032X TG output varies by frequency (±2 dB typical across full range)
- Calibrate TG output with power meter at frequencies of interest
- Use `--tg-power` to specify actual measured power

## Related Projects

- **Noise Figure Meter:** `~/Dropbox/build/rf-bench/projects/radio/noise-figure/` - Y-factor NF measurement
- **IP3 Measurement:** `~/Dropbox/build/rf-bench/projects/radio/ip3/` - Third-order intercept point
- **TX Power vs Frequency:** `~/Dropbox/build/rf-bench/projects/radio/tx-power/` - Transmit power sweep
- **scpi-atten:** `~/Dropbox/build/rf-bench/projects/esp32/scpi-atten/` - Digital attenuator controller
- **scpi-ptt:** `~/Dropbox/build/rf-bench/projects/esp32/scpi-ptt/` - PTT controller for TX testing

## References

- **ARRL Handbook**, Chapter on Receiver Performance and Testing
- **ITU-R SM.331-6** - S-meter calibration standard
- **MIL-STD-188-125** - Transceiver specifications and test methods
- **Rohde & Schwarz AN: Measuring Receiver Sensitivity**
