# ESP32-Combo Bode Plotter

Automated Bode plot measurement combining ESP32 SCPI devices with Siglent oscilloscope and function generator for multi-DUT comparison and multi-point probing.

## Features

- **Multi-DUT switching** via scpi-relay (up to 4 DUTs without cable swaps)
- **Multi-point probing** via scpi-mux (probe multiple stages of single DUT)
- **Overlaid plots** comparing all DUTs or probe points on same axes
- **Per-DUT CSV files** for individual analysis
- **Automated frequency sweep** with gain (dB) and phase (degrees) measurement
- **Log or linear frequency spacing**

## Hardware Requirements

### Core Instruments

| Instrument | Model | Purpose |
|------------|-------|---------|
| Function generator | Siglent SDG1062X | Frequency sweep source |
| Oscilloscope | Siglent SDS2504X Plus | Amplitude/phase measurement |

### Optional ESP32 Automation

| Device | Purpose | Replaces |
|--------|---------|----------|
| ESP32 scpi-relay | Switch between 4 DUTs | Manual cable swapping |
| ESP32 scpi-mux | Probe multiple points on single DUT | Manual probe repositioning |

Both devices connect via WiFi/Ethernet on port 5025 (SCPI standard).

See:
- `~/rf-bench/projects/esp32/scpi-relay/` — 4-channel relay controller
- `~/rf-bench/projects/esp32/scpi-mux/` — CD4067 16-channel analog multiplexer

## Installation

```bash
pip install rf-bench-drivers-siglent
```

Or from the rf-bench monorepo:

```bash
cd ~/rf-bench/drivers/siglent
pip install -e .
```

## Cable Setup

### Single DUT (No Automation)

```
SDG CH1 ──┬─── Scope CH1 (reference, monitors source)
          └─── DUT input
                 DUT output ─── Scope CH2 (measures output)
```

**Why monitor the source?** The SDG's actual output level may differ slightly from commanded level (especially at high frequencies). Measuring CH1 (reference) eliminates this error.

### Multi-DUT (scpi-relay)

```
SDG CH1 ──┬─── Scope CH1 (reference)
          └─── All DUT inputs in parallel (or via relay COM)
                 DUT1 output ─── Relay 1 ──┬
                 DUT2 output ─── Relay 2 ──┤
                 DUT3 output ─── Relay 3 ──┼─── Scope CH2
                 DUT4 output ─── Relay 4 ──┘
```

**Relay wiring options:**
- **Option A (parallel inputs):** All DUT inputs share common SDG connection. Relays only switch outputs to scope. Lowest insertion loss.
- **Option B (full isolation):** Use 8-channel relay (or two 4-channel boards) to switch both input and output per DUT. Complete isolation between DUTs.

### Multi-Point Probing (scpi-mux)

```
SDG CH1 ──┬─── Scope CH1 (reference)
          └─── DUT input
                 DUT stage1 ─── scpi-mux CH0
                 DUT stage2 ─── scpi-mux CH1
                 DUT stage3 ─── scpi-mux CH2
                 DUT output ─── scpi-mux CH3
                 scpi-mux COM ─── Scope CH2
```

**Use case:** Characterize multi-stage amplifier by probing gain/phase at each stage. Example: 3-stage RF amplifier with interstage matching — measure input, stage 1 output, stage 2 output, final output.

**Mux limitations:**
- CD4067 on-resistance: 70 Ω (adds to source impedance)
- Bandwidth: 40 MHz analog (-3dB) — suitable for audio/HF, not VHF/UHF
- For RF work above 30 MHz, use RF relays instead of CMOS mux

## Usage

### Single DUT (No Automation)

```bash
python bode_plot.py
```

Defaults: 10 Hz to 1 MHz, 100 points (log-spaced), -10 dBm drive.

### Multi-DUT Comparison (4 Filters)

```bash
python bode_plot.py --esp-relay 10.1.1.42 --duts 1,2,3,4
```

Generates:
- `bode_YYYYMMDD_HHMMSS_DUT1_bode.csv` (per-DUT data)
- `bode_YYYYMMDD_HHMMSS_DUT2_bode.csv`
- `bode_YYYYMMDD_HHMMSS_DUT3_bode.csv`
- `bode_YYYYMMDD_HHMMSS_DUT4_bode.csv`
- `bode_YYYYMMDD_HHMMSS_bode.png` (overlaid plot of all 4)

### Multi-Point Probing (3-Stage Amplifier)

```bash
python bode_plot.py --esp-mux 10.1.1.43 --mux-points 0,1,2,3
```

Probe points:
- CH0: DUT input (reference, should match CH1)
- CH1: After stage 1
- CH2: After stage 2
- CH3: Final output

**Tip:** Connect scpi-mux CH0 to the DUT input to verify reference signal integrity. If CH0 and scope CH1 differ, check mux on-resistance or wiring.

### Audio Crossover (20 Hz–20 kHz, 200 Points)

```bash
python bode_plot.py --start 20 --stop 20000 --points 200 --level -20
```

Lower drive level (-20 dBm) avoids overdriving passive crossover inductors.

### RF Filter (100 kHz–10 MHz, Linear Spacing)

```bash
python bode_plot.py --start 100e3 --stop 10e6 --lin-freq --points 500
```

Linear spacing gives uniform frequency resolution for swept filters.

## Command-Line Arguments

### Instruments

```
--sdg-host IP        SDG1062X IP address [default: 10.1.1.55]
--scope-host IP      SDS2504X IP address [default: 10.1.1.58]
```

### ESP32 Automation

```
--esp-relay IP       scpi-relay IP for multi-DUT switching
--esp-mux IP         scpi-mux IP for multi-point probing
--duts LIST          Comma-separated relay channels (1-4) [default: 1]
--mux-points LIST    Comma-separated mux channels (0-15) [default: 0]
```

**Examples:**
- `--duts 1,3` — Compare DUT1 and DUT3 only
- `--mux-points 0,2,4,6` — Probe 4 points (skipping odd channels)

### Sweep Parameters

```
--start HZ           Start frequency [default: 10 Hz]
--stop HZ            Stop frequency [default: 1 MHz]
--points N           Number of sweep points [default: 100]
--level DBM          Source level in dBm [default: -10 dBm]
--log-freq           Log-spaced frequency points (default)
--lin-freq           Linear-spaced frequency points
```

### Channels

```
--ch-ref N           Scope channel for reference [default: 1]
--ch-dut N           Scope channel for DUT output [default: 2]
```

### Output

```
--output PREFIX      Output filename prefix [default: bode_YYYYMMDD_HHMMSS]
--duration-s S       Fixed capture duration per point (overrides auto)
```

## Output Files

For single DUT:

```
bode_20260612_143522_bode.png     — Bode plot (gain and phase panels)
bode_20260612_143522_bode.csv     — Raw data (freq_hz, gain_db, phase_deg)
bode_20260612_143522_bode.txt     — Summary (passband gain, -3dB frequency)
```

For multi-DUT (relay):

```
bode_20260612_143522_DUT1_bode.csv    — Per-DUT CSV files
bode_20260612_143522_DUT2_bode.csv
bode_20260612_143522_DUT3_bode.csv
bode_20260612_143522_DUT4_bode.csv
bode_20260612_143522_bode.png          — Overlaid plot
```

For multi-point (mux):

```
bode_20260612_143522_Point0_bode.csv   — Per-point CSV files
bode_20260612_143522_Point1_bode.csv
bode_20260612_143522_Point2_bode.csv
bode_20260612_143522_bode.png           — Overlaid plot
```

## Measurement Algorithm

Same as `~/rf-bench/projects/scope/bode-plotter/`:

1. **Frequency sweep**: SDG steps through frequency array
2. **Settling time**: 100 ms or 2 cycles (whichever is longer)
3. **Capture**: Scope records CH1 (reference) and CH2 (DUT output)
4. **FFT analysis**: `gain_phase_from_fft()` extracts amplitude ratio and phase offset at fundamental frequency
5. **Gain (dB)**: `20 log10(V_out / V_in)`
6. **Phase (degrees)**: Unwrapped phase difference from FFT

**Why FFT instead of peak detection?** FFT rejects harmonics and noise. Peak detection would include distortion products, especially at high drive levels.

## Use Cases

### Filter Comparison

Compare 4 candidate lowpass filters for best stopband rejection:

```bash
python bode_plot.py --esp-relay 10.1.1.42 --duts 1,2,3,4 \
    --start 10 --stop 10e6 --points 200
```

Overlaid plot shows which filter has steepest rolloff and deepest stopband.

### Multi-Stage Amplifier Characterization

Probe 3-stage RF amplifier to verify each stage's gain:

```bash
python bode_plot.py --esp-mux 10.1.1.43 --mux-points 0,1,2,3 \
    --start 1e6 --stop 30e6 --points 100
```

If total gain is 60 dB but individual stages show 15 dB, 20 dB, 25 dB → expected product. If one stage shows 5 dB → diagnose that stage.

### Transformer Winding Comparison

Compare primary vs. secondary frequency response in audio transformer:

```bash
python bode_plot.py --esp-relay 10.1.1.42 --duts 1,2 \
    --start 20 --stop 20000 --points 200
```

Relay 1: Primary winding  
Relay 2: Secondary winding

Overlaid plot shows turns ratio (gain offset) and bandwidth differences.

### Antenna Tuner Sweep

Measure antenna tuner insertion loss across HF bands:

```bash
python bode_plot.py --start 1.8e6 --stop 30e6 --points 300
```

Gain plot shows insertion loss per band. Phase plot shows reactive component (inductance/capacitance).

## Integration with Other Projects

### Extends `projects/scope/bode-plotter/`

This project adds ESP32 automation to the existing scope-based Bode plotter. Core algorithm (FFT-based gain/phase) is identical.

### Compatible with `projects/relay/` (XL9535 I2C Relay)

If using `~/rf-bench/projects/relay/` XL9535 I2C relay board instead of ESP32 scpi-relay, modify the `RelayController` class to use I2C commands. Pin mapping remains the same.

### Works with `projects/rf/scalar-vna/`

For swept RF measurements, this Bode plotter provides amplitude and phase data. Future enhancement: add S21 calculation (requires calibration with thru/short/load standards).

## Troubleshooting

### Relay doesn't switch

1. Verify scpi-relay IP address: `telnet 10.1.1.42 5025` → `*IDN?`
2. Check relay power supply (5V external PSU required for relay coils)
3. Listen for relay click when sending `ROUTE:CLOSE (@1)` manually

### Mux channels all read same voltage

1. Verify scpi-mux IP address: `telnet 10.1.1.43 5025` → `*IDN?`
2. Check mux enable: `MUX:EN,1` → `MUX:EN?` should return "1"
3. Probe CD4067 address pins (S0-S3) with logic analyzer to verify channel selection
4. Verify mux COM pin connects to scope CH2

### Gain measurements inconsistent

1. **Check settling time**: Add `--duration-s 0.5` to capture more cycles per frequency
2. **Reduce drive level**: High levels cause clipping/distortion → add `--level -20`
3. **Verify reference channel**: CH1 should track SDG output. If CH1 is flat while CH2 varies, CH1 probe has poor contact.
4. **Check scope coupling**: DC coupling required for DC-coupled DUTs. AC coupling attenuates <10 Hz.

### Mux on-resistance affects measurement

CD4067 on-resistance (70 Ω) forms voltage divider with DUT input impedance:

- **High-Z DUT (>10 kΩ)**: Error <1%, negligible
- **Low-Z DUT (<1 kΩ)**: Error >5%, significant

**Solution:** Add unity-gain buffer (op-amp follower) at each mux input to present high impedance.

### Plot shows multiple DUTs but one is flat

1. **Relay stuck open**: Check relay contact with multimeter (should read <1 Ω closed)
2. **DUT not connected**: Verify DUT input/output wiring
3. **DUT damaged**: Test DUT with multimeter (DC resistance) or swap with known-good unit

## Performance

### Sweep Time

**Single DUT, 100 points:**
- Settling time: 100 ms/point (dominant)
- Capture time: 20 ms/point (scope audio capture)
- Total: ~120 ms/point → 12 seconds for 100-point sweep

**Multi-DUT (4 DUTs), 100 points:**
- 12 seconds/DUT × 4 = 48 seconds total
- Relay switching: 10 ms/DUT (negligible)

**Multi-point (8 points), 100 points:**
- 12 seconds/point × 8 = 96 seconds total
- Mux switching: <1 ms/point (negligible)

**Optimization:** Reduce `--points` to 50 for faster sweeps (halves time). For high-Q filters, use `--lin-freq` with dense spacing near resonance.

### Accuracy

**Gain accuracy:**
- ±0.1 dB (1-100 kHz, -10 dBm drive, high-Z DUT)
- ±0.5 dB (100 kHz-1 MHz, mux on-resistance effects)

**Phase accuracy:**
- ±2° (1-100 kHz)
- ±5° (100 kHz-1 MHz, mux crosstalk)

**Limiting factors:**
- Mux on-resistance: 70 Ω (adds to source impedance)
- Scope ADC resolution: 8-bit (SDS2504X Plus)
- FFT bin width: Depends on capture duration (more cycles → finer bins)

**For higher accuracy:**
- Use `--duration-s 1.0` (more cycles → better FFT resolution)
- Use `--level -20` (lower drive → less distortion)
- Calibrate with known reference (50 Ω terminator, BNC thru, precision attenuator)

## Limitations

- **Single-ended signals only**: Differential measurements require two muxes or dual relays
- **Mux bandwidth**: 40 MHz (-3dB) for CD4067. For VHF/UHF, use RF relays.
- **Mux crosstalk**: -60 dB at 1 MHz. May affect high-gain DUTs (>60 dB gain).
- **Relay lifespan**: Mechanical relays rated for 100k-1M cycles. For production testing, use solid-state relays.
- **No S-parameter calibration**: This is a gain/phase plotter, not a VNA. For calibrated S21, use `~/rf-bench/projects/vna/` with HP 8712B (future).

## Future Enhancements

- **scpi-atten integration**: Add programmable attenuator for automatic gain/loss compensation
- **Smith chart overlay**: Convert gain/phase to S21 and plot on Smith chart (requires calibration)
- **Real-time streaming**: Live plot update during sweep (requires threading or async)
- **Multi-DUT + multi-point**: Switch between 4 DUTs and probe 4 points per DUT (16 sweeps total)
- **S-parameter export**: Save Touchstone (.s2p) format for VNA software compatibility
- **GPIB/VISA support**: Add compatibility with HP 8712B VNA for swept S-parameters (hardware pending)

## Related Projects

- `~/rf-bench/projects/scope/bode-plotter/` — Base Bode plotter (single DUT, no automation)
- `~/rf-bench/projects/esp32/scpi-relay/` — 4-channel relay controller
- `~/rf-bench/projects/esp32/scpi-mux/` — 16-channel analog mux controller
- `~/rf-bench/projects/relay/` — XL9535 I2C relay matrix (multi-DUT, SOLT cal, filter banks)
- `~/rf-bench/projects/rf/scalar-vna/` — Scalar VNA using SSA3032X + SDG1062X (future)

## Status

🔨 **Hardware built to documentation, firmware tested, Python integration complete.**

Tested with:
- Siglent SDS2504X Plus (500 MHz scope, firmware 1.6.2R2)
- Siglent SDG1062X (60 MHz AWG, firmware 2.01.01.33R3)
- ESP32 scpi-relay (4-channel, firmware 1.0)
- ESP32 scpi-mux (CD4067 16-channel, firmware 1.0)

Pending:
- Real-world multi-stage amplifier characterization
- High-Q filter comparison (narrowband crystal filter, SAW filter)

## License

Public domain. Use freely.

## Author

N0GQ — 2026-06-12
