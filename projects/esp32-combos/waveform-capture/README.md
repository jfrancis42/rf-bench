# ESP32 Waveform Capture/Replay

**Status:** 🔨 In development

Arbitrary waveform recorder/playback system combining scpi-adc (ADS1115), scpi-relay (trigger), and Siglent SDG1062X arbitrary waveform generator.

## What It Does

Captures real-world voltage waveforms at up to 860 samples/second (16-bit resolution) and replays them on a function generator for testing, simulation, or analysis.

**Use Cases:**
- Motor startup transients (inrush current profiling)
- Audio glitches and transient analysis
- RF burst capture and replay
- Battery discharge curves
- Switch-mode power supply ripple reproduction
- Sensor signal replay for embedded system testing

## Hardware Requirements

| Component | Purpose | Connection |
|-----------|---------|------------|
| **scpi-adc (ADS1115)** | 16-bit ADC capture | ESP32 I2C + target signal on AIN0-3 |
| **scpi-relay (optional)** | Hardware trigger input | ESP32 GPIO + external trigger source |
| **Siglent SDG1062X** | Arbitrary waveform playback | Ethernet, external trigger input |

## Wiring

### ADS1115 Input
Connect the signal to capture to one of the ADS1115 differential inputs:
- **Single-ended:** Signal to AIN0-3, GND to GND
- **Differential:** Signal+ to AIN0/2, Signal- to AIN1/3
- **Voltage range:** +/- 4.096V (script configures this range for best 16-bit resolution)

### Trigger (Optional Hardware Mode)
If using `--trigger-mode relay`:
- Connect trigger source to scpi-relay digital input 0
- Rising edge starts capture

### SDG1062X Output
- External trigger input (rear panel BNC) receives trigger to replay waveform
- Output on CH1 or CH2 (configurable with `--sdg-channel`)

## Installation

```bash
# Install Siglent driver
pip install rf-bench-drivers-siglent

# Install VISA library
pip install pyvisa pyvisa-py
```

## Usage

### Basic Capture (Auto-Trigger)
Capture 1 second of data at 860 SPS and upload to SDG channel 1:

```bash
./waveform_capture.py --esp-adc 10.1.0.100 --sdg 10.1.0.50 \
    --channel 0 --sample-rate 860 --duration-sec 1
```

### Hardware-Triggered Capture
Wait for relay trigger, then capture 2 seconds at 500 SPS:

```bash
./waveform_capture.py --esp-adc 10.1.0.100 --esp-relay 10.1.0.101 --sdg 10.1.0.50 \
    --channel 0 --sample-rate 500 --duration-sec 2 --trigger-mode relay
```

### Capture Only (No Upload)
Save waveform to CSV without uploading to function generator:

```bash
./waveform_capture.py --esp-adc 10.1.0.100 --sdg 10.1.0.50 \
    --channel 0 --sample-rate 860 --duration-sec 1 --no-upload --output motor_startup.csv
```

### Replay Captured Waveform
After upload, the SDG is configured for external trigger burst mode. Apply a trigger pulse to the SDG's external trigger input to replay the waveform.

## Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--esp-adc IP` | IP address of scpi-adc (ADS1115) device | Required |
| `--esp-relay IP` | IP address of scpi-relay device (for trigger) | Optional |
| `--sdg IP` | IP address of Siglent SDG1062X | Required |
| `--channel N` | ADC input channel (0-3) | 0 |
| `--sdg-channel N` | SDG output channel (1 or 2) | 1 |
| `--sample-rate SPS` | Samples per second (max 860) | 860 |
| `--duration-sec S` | Capture duration in seconds | 1.0 |
| `--trigger-mode MODE` | `auto` (immediate) or `relay` (wait for trigger) | auto |
| `--output FILE` | Output CSV filename | waveform_capture.csv |
| `--no-upload` | Skip SDG upload (capture to CSV only) | False |

## Technical Details

### Sample Rate Limitations
- **ADS1115 maximum:** 860 samples/second (determined by I2C overhead and conversion time)
- For higher sample rates, consider external ADC with faster interface (SPI, parallel)
- Script clamps `--sample-rate` to 860 if higher value specified

### Resolution
- **ADS1115 input:** 16-bit (65536 levels over +/- 4.096V = 125 µV resolution)
- **SDG1062X arbitrary waveform:** 14-bit (16384 levels)
- Quantization during upload: 16-bit capture → 14-bit playback (16 µV loss per level)

### Waveform Conversion
1. **Capture:** Raw 16-bit ADC values at actual voltage levels
2. **Normalization:** Map voltage range to -1.0 to +1.0 for SDG arbitrary waveform format
3. **Quantization:** Convert normalized floats to 14-bit integers (-8191 to +8191)
4. **Upload:** SCPI command uploads data points to SDG volatile memory
5. **Configuration:** SDG channel configured with correct amplitude, offset, and duration

### CSV Format
```
timestamp,voltage
0.000000,-0.0012
0.001163,0.0034
0.002326,0.0089
...
```
- **timestamp:** Seconds since trigger (monotonic)
- **voltage:** Measured voltage (V)

## Example Workflows

### Motor Inrush Current Capture
1. Connect current shunt resistor output to ADS1115 AIN0
2. Connect motor power switch to scpi-relay input 0 (trigger)
3. Run: `./waveform_capture.py --esp-adc 10.1.0.100 --esp-relay 10.1.0.101 --sdg 10.1.0.50 --trigger-mode relay --duration-sec 0.5 --sample-rate 860`
4. Turn on motor power
5. Captured inrush waveform now available for replay on SDG

### Audio Glitch Reproduction
1. Connect audio output to ADS1115 via voltage divider (line level → 0-4V)
2. Capture problematic audio segment: `./waveform_capture.py --esp-adc 10.1.0.100 --sdg 10.1.0.50 --duration-sec 2 --sample-rate 860 --output glitch.csv`
3. Connect SDG output to device under test
4. Trigger SDG to replay glitch repeatedly for debugging

### Battery Discharge Curve
1. Connect battery voltage to ADS1115 (through voltage divider if >4.096V)
2. Capture long discharge: `./waveform_capture.py --esp-adc 10.1.0.100 --sdg 10.1.0.50 --duration-sec 3600 --sample-rate 100 --output battery_discharge.csv`
3. Replay on SDG to test low-voltage cutoff circuits without waiting hours

## Limitations

- **Bandwidth:** 860 Hz Nyquist limit (430 Hz signal bandwidth)
- **Capture length:** Limited by CSV file size and SDG memory (check SDG1062X specs for max arb waveform length)
- **Single-channel:** One ADC channel at a time (differential or single-ended)
- **No pre-trigger:** Circular buffer not implemented (trigger occurs at t=0)

## Future Enhancements

- Circular buffer for pre-trigger capture (capture N samples before trigger event)
- Multi-channel synchronized capture (interleave ADS1115 channels)
- Interpolation for SDG sample rate mismatch (e.g., capture at 860 SPS, replay at 1 kHz)
- Waveform editing (trim, scale, DC offset removal) before upload
- Direct SDG trigger output control (capture → auto-replay without manual trigger)

## Related Projects

- `/home/jfrancis/Dropbox/build/rf-bench/projects/esp32/scpi-adc/` — ADS1115 SCPI server firmware
- `/home/jfrancis/Dropbox/build/rf-bench/projects/esp32/scpi-relay/` — Relay SCPI server firmware
- `/home/jfrancis/Dropbox/build/rf-bench/drivers/siglent/` — SDG1000X Python driver
