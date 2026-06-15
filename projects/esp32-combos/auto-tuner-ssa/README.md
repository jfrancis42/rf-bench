# ESP32+SSA Automated Antenna Tuner

Closed-loop antenna tuner combining three ESP32 SCPI projects with an SSA3032X spectrum analyzer's tracking generator. Automatically tunes stepper-motor-driven L/C network to achieve target SWR at a specified frequency.

## Hardware Requirements

### Required Devices

1. **scpi-tuner ESP32** (from `~/Dropbox/build/rf-bench/projects/esp32/scpi-tuner/`)
   - Controls stepper-motor-driven variable L and C network
   - Must be deployed and network-accessible

2. **scpi-ptt ESP32** (from `~/Dropbox/build/rf-bench/projects/esp32/scpi-ptt/`)
   - Handles TX sequencing and relay control
   - Keys transmitter/tracking generator signal path

3. **scpi-swr ESP32** (from `~/Dropbox/build/rf-bench/projects/esp32/scpi-swr/`)
   - Dual AD8307 logarithmic detectors
   - Measures forward and reflected power
   - Calculates SWR

4. **Siglent SSA3032X** spectrum analyzer with tracking generator option
   - Provides calibrated RF source at target frequency
   - Eliminates need for separate signal generator
   - Allows verification of harmonics/spurious

### Antenna System Components

- **Directional coupler** (Mini-Circuits ZFDC-20-5+ or similar)
  - Forward port → scpi-swr FWD input
  - Reflected port → scpi-swr REF input
  - Through port → antenna
  - Input port ← scpi-ptt relay output

- **Stepper-driven L/C network**
  - Inductors: air-wound coil on stepper shaft (e.g., 0-10 µH)
  - Capacitors: butterfly or vacuum variable on stepper (e.g., 10-500 pF)
  - Controlled by scpi-tuner

- **RF relay matrix** (controlled by scpi-ptt)
  - Switches SSA TG output to directional coupler input
  - Provides TX sequencing delay (PTT before RF, RF off before PTT release)

## Wiring Diagram

```
SSA3032X TG output
    |
    v
[scpi-ptt relay] -----> [L/C network] -----> [Directional Coupler] -----> Antenna
                        (scpi-tuner)              |            |
                                                  |            |
                                           (forward)      (reflected)
                                                  |            |
                                                  v            v
                                          [scpi-swr AD8307 detectors]
```

### scpi-swr Connection Detail

The scpi-swr ESP32 uses two AD8307 logarithmic detector ICs:

- **FWD detector**: Coupled output from directional coupler forward port
  - AD8307 VOUT → ESP32 ADC (GPIO 34 or similar)
  - Measures forward power in dBm

- **REF detector**: Coupled output from directional coupler reflected port
  - AD8307 VOUT → ESP32 ADC (GPIO 35 or similar)
  - Measures reflected power in dBm

Each AD8307:
- RFIN: 50-ohm input via DC block capacitor
- VOUT: 0-2.5V proportional to input power (25 mV/dB slope)
- Power: +5V from ESP32 VIN, GND to ESP32 GND
- Calibration: two-point cal (known power levels) stored in scpi-swr EEPROM

Reference: Analog Devices AD8307 datasheet, Mini-Circuits directional coupler app notes.

## Installation

### Python Dependencies

```bash
pip install rf-bench-drivers-siglent
```

This pulls in the SSA3000X driver. The ESP32 devices communicate via raw sockets (no additional libraries needed).

### Network Setup

All four devices must be on the same network and reachable from the machine running `auto_tuner.py`.

Recommended: assign static IPs or DHCP reservations to each ESP32:

```
10.1.0.100 - scpi-tuner
10.1.0.101 - scpi-ptt
10.1.0.102 - scpi-swr
10.1.0.50  - SSA3032X
```

Test connectivity:

```bash
# Ping each device
ping -c 1 10.1.0.100
ping -c 1 10.1.0.101
ping -c 1 10.1.0.102
ping -c 1 10.1.0.50

# Test SCPI on each ESP32 (should return "*IDN,ESP32,scpi-<project>,...")
echo '*IDN?' | nc 10.1.0.100 5025
echo '*IDN?' | nc 10.1.0.101 5025
echo '*IDN?' | nc 10.1.0.102 5025
```

## Usage

### Basic Auto-Tune

```bash
./auto_tuner.py \
  --esp-tuner 10.1.0.100 \
  --esp-ptt 10.1.0.101 \
  --esp-swr 10.1.0.102 \
  --ssa 10.1.0.50 \
  --freq 7.200
```

This will:
1. Connect to all four devices
2. Enable SSA tracking generator at 7.200 MHz
3. Run coarse grid search (10-step increments) across full L/C range
4. Run fine grid search (2-step increments) around best coarse result
5. Print final L/C position and SWR
6. Save iteration log to `auto_tuner_YYYYMMDD_HHMMSS.csv`
7. Disable SSA tracking generator

### Save to Memory

```bash
./auto_tuner.py \
  --esp-tuner 10.1.0.100 \
  --esp-ptt 10.1.0.101 \
  --esp-swr 10.1.0.102 \
  --ssa 10.1.0.50 \
  --freq 14.200 \
  --memory-slot 2
```

After tuning completes, the final L/C position is saved to scpi-tuner's non-volatile memory slot 2. Later, recall with:

```bash
echo 'TUNER:MEM:RECALL? 2' | nc 10.1.0.100 5025
```

### Custom Search Parameters

```bash
./auto_tuner.py \
  --esp-tuner 10.1.0.100 \
  --esp-ptt 10.1.0.101 \
  --esp-swr 10.1.0.102 \
  --ssa 10.1.0.50 \
  --freq 3.750 \
  --target-swr 1.3 \
  --max-iter 50 \
  --coarse-step 15 \
  --fine-step 1 \
  --log 80m_tune.csv
```

- `--target-swr 1.3`: Stop when SWR ≤ 1.3 (default 1.5)
- `--max-iter 50`: Allow up to 50 measurements (default 20)
- `--coarse-step 15`: Coarser initial search (default 10)
- `--fine-step 1`: Finest resolution search (default 2)
- `--log 80m_tune.csv`: Custom log filename

## Auto-Tune Workflow

### Algorithm

1. **Setup**
   - Connect to all devices
   - Query scpi-tuner for L_MAX and C_MAX limits
   - Configure SSA tracking generator at target frequency (-10 dBm output)
   - Set SSA analyzer to center on target frequency

2. **Coarse Grid Search**
   - Iterate L from 0 to L_MAX in `coarse_step` increments
   - For each L, iterate C from 0 to C_MAX in `coarse_step` increments
   - At each (L, C) position:
     - Move steppers via scpi-tuner
     - Key PTT via scpi-ptt (200 ms settle time)
     - Read SWR from scpi-swr
     - Unkey PTT (500 ms cool-down)
     - Log iteration, L, C, SWR to history
   - Track best (L, C) with minimum SWR
   - Exit early if SWR ≤ target or max iterations reached

3. **Fine Grid Search**
   - Center search window at coarse result: [L - coarse_step, L + coarse_step]
   - Iterate in `fine_step` increments (smaller steps, tighter coverage)
   - Same measure-log-track loop as coarse search
   - Exit early if SWR ≤ target or max iterations reached

4. **Save Result**
   - Move to final best (L, C)
   - Optionally save to scpi-tuner memory slot
   - Write full history to CSV log
   - Disable SSA tracking generator

### Why Grid Search?

- **Simplicity**: No gradient calculation, no local minima traps
- **Robustness**: Explores full space, finds global minimum
- **Predictability**: Deterministic, same result every run
- **Hardware-friendly**: No rapid back-and-forth, gentle on steppers

More sophisticated algorithms (gradient descent, Nelder-Mead) require differentiable SWR surface and can get stuck in local minima. For a small 2D space (L/C), exhaustive grid search is fast enough and guaranteed to find the global best.

### Two-Stage Coarse/Fine Strategy

- **Coarse**: Covers full range quickly, finds approximate region
- **Fine**: Refines around coarse result, achieves target SWR

Example: L_MAX=200, C_MAX=200, coarse_step=10, fine_step=2

- Coarse: 21 × 21 = 441 measurements (worst case)
- Fine: 11 × 11 = 121 measurements (worst case, centered on coarse result)
- Total: ~562 measurements max

With 200 ms key + 100 ms settle + 500 ms cooldown = 800 ms per measurement:

- Total time: ~450 seconds (7.5 minutes) worst case
- Typical: exits early when target SWR reached, often <2 minutes

## Troubleshooting

### No Response from ESP32

**Symptoms**: `socket.timeout` or "Connection refused" errors.

**Fixes**:

1. Verify ESP32 is powered and connected to network:
   ```bash
   ping 10.1.0.100
   ```

2. Check SCPI server is running (should see port 5025 open):
   ```bash
   nmap -p 5025 10.1.0.100
   ```

3. Try manual SCPI query:
   ```bash
   echo '*IDN?' | nc 10.1.0.100 5025
   # Should return: *IDN,ESP32,scpi-tuner,v1.0,...
   ```

4. If no response, reflash ESP32 with latest scpi-tuner firmware.

### SWR Readings Look Wrong

**Symptoms**: SWR always >10, or negative, or nonsense values.

**Fixes**:

1. Verify AD8307 calibration on scpi-swr:
   ```bash
   echo 'CAL:FWD?' | nc 10.1.0.102 5025
   echo 'CAL:REF?' | nc 10.1.0.102 5025
   # Should return two comma-separated values: m,b (slope, intercept)
   ```

   If calibration is missing or wrong, run two-point cal:
   - Apply known power (e.g., -20 dBm) to FWD detector
   - Read ADC value: `echo 'ADC:FWD?' | nc 10.1.0.102 5025`
   - Apply second known power (e.g., -10 dBm)
   - Read ADC value again
   - Calculate slope/intercept, save: `echo 'CAL:FWD m,b' | nc 10.1.0.102 5025`
   - Repeat for REF detector

2. Check directional coupler connections:
   - FWD port → scpi-swr FWD input
   - REF port → scpi-swr REF input
   - Swap them? (Common mistake)

3. Verify SSA tracking generator is actually outputting:
   - Look at SSA screen: should show TG marker at target frequency
   - Measure TG output with separate power meter: should be ~-10 dBm

4. Check RF path:
   - SSA TG → scpi-ptt relay → L/C network → directional coupler → antenna
   - Any open/shorted connection will produce bogus SWR

### Steppers Don't Move

**Symptoms**: Script runs, but scpi-tuner steppers stay at (0, 0).

**Fixes**:

1. Verify stepper drivers are powered:
   - Check 12V supply to A4988/DRV8825 driver boards
   - Measure voltage at driver VDD pin

2. Check STEP/DIR GPIO connections:
   - scpi-tuner code uses specific GPIO pins (see that project's README)
   - Loose wire? Wrong pin?

3. Test steppers manually:
   ```bash
   echo 'TUNER:L 50' | nc 10.1.0.100 5025
   echo 'TUNER:C 50' | nc 10.1.0.100 5025
   # Should hear/see steppers move
   ```

4. Query current position:
   ```bash
   echo 'TUNER:L?' | nc 10.1.0.100 5025
   echo 'TUNER:C?' | nc 10.1.0.100 5025
   ```

### Tuning Never Converges

**Symptoms**: Script runs to max iterations, SWR never reaches target.

**Causes**:

1. **Antenna fundamentally mismatched**: e.g., 80m dipole on 10m
   - L/C network has limited tuning range
   - Can't transform 200-ohm impedance to 50 ohms with available components
   - **Fix**: Use appropriate antenna for band, or add more L/C range

2. **Target SWR too aggressive**: asking for SWR < 1.2 on a compromised antenna
   - **Fix**: relax `--target-swr 1.5` or higher

3. **Grid resolution too coarse**: `coarse_step=10, fine_step=2` may miss narrow SWR null
   - **Fix**: decrease step sizes, increase `--max-iter`

4. **SWR measurement noise**: AD8307 has ~±0.5 dB accuracy, SWR may jitter
   - **Fix**: Average multiple measurements per position (code mod needed)

### SSA Tracking Generator Not Enabling

**Symptoms**: Script says "SSA tracking generator enabled" but SSA screen shows TG off.

**Fixes**:

1. Verify tracking generator option is installed:
   - SSA3032X-TG option required (hardware module)
   - Check SSA menu: Stimulus → TG Control (should not be greyed out)

2. Check SCPI connection to SSA:
   ```bash
   echo '*IDN?' | nc 10.1.0.50 5025
   # Should return: Siglent Technologies,SSA3032X,...
   ```

3. Manually enable TG via SCPI:
   ```bash
   echo ':TG:STATE ON' | nc 10.1.0.50 5025
   echo ':TG:STATE?' | nc 10.1.0.50 5025
   # Should return: ON
   ```

4. If still not working, enable TG via front panel, verify output with power meter.

## Integration with Other Projects

### Use with ~/rf-bench/projects/radio/ Scripts

Many scripts in `projects/radio/` (receiver_mds.py, transmitter_harmonics.py, etc.) can benefit from automated antenna tuning:

1. Run `auto_tuner.py` at test frequency to achieve optimal match
2. Run radio characterization script
3. Repeat at multiple frequencies (loop over band)

Example: Measure transmitter harmonics at 5 frequencies across 40m band:

```bash
for freq in 7.000 7.050 7.100 7.150 7.200; do
  echo "Tuning $freq MHz..."
  ./auto_tuner.py --esp-tuner 10.1.0.100 --esp-ptt 10.1.0.101 \
                  --esp-swr 10.1.0.102 --ssa 10.1.0.50 \
                  --freq $freq --memory-slot $(echo "$freq * 10 - 70000" | bc)

  echo "Measuring harmonics..."
  cd ~/Dropbox/build/rf-bench/projects/radio/
  ./transmitter_harmonics.py --ssa 10.1.0.50 --freq $freq --output harmonics_${freq}.csv
  cd -
done
```

### WSPR / Weak-Signal Testing

For WSPR beacon testing (projects using jf8call or JS8Call-improved):

1. Auto-tune antenna at WSPR frequency (e.g., 10.140 MHz)
2. Key transmitter via scpi-ptt, verify SWR < 1.5
3. Start WSPR beacon transmission
4. Monitor WSPRnet for reception reports

The low SWR ensures maximum power transfer and best propagation results.

### Multi-Band Memory Table

Use `--memory-slot` to build a lookup table of L/C positions per band:

```bash
# 80m
./auto_tuner.py ... --freq 3.750 --memory-slot 0
# 40m
./auto_tuner.py ... --freq 7.200 --memory-slot 1
# 30m
./auto_tuner.py ... --freq 10.125 --memory-slot 2
# 20m
./auto_tuner.py ... --freq 14.200 --memory-slot 3
# 17m
./auto_tuner.py ... --freq 18.100 --memory-slot 4
# 15m
./auto_tuner.py ... --freq 21.200 --memory-slot 5
# 12m
./auto_tuner.py ... --freq 24.950 --memory-slot 6
# 10m
./auto_tuner.py ... --freq 28.500 --memory-slot 7
```

Later, instant band changes via scpi-tuner memory recall:

```bash
# Switch to 40m
echo 'TUNER:MEM:RECALL? 1' | nc 10.1.0.100 5025
```

## Known Limitations

- **Blocking operation**: Script runs synchronously, no GUI or web interface
  - Future: migrate to FastAPI WebSocket server for live monitoring

- **Single frequency at a time**: Each run tunes one frequency
  - Future: accept frequency list, auto-tune across band, build memory table

- **No load impedance measurement**: Only SWR, not R+jX
  - Can't distinguish capacitive vs inductive mismatch
  - Grid search works anyway (minimizes SWR regardless of phase)
  - Future: add VNA mode (SSA tracking gen + IQ measurement, or separate VNA)

- **Stepper settling time hardcoded**: 300 ms per move
  - May be too slow (fast steppers) or too fast (heavy inductors)
  - Future: query scpi-tuner for optimal settle time, or add `--settle-ms` arg

- **No SWR averaging**: Single measurement per position
  - Noisy environments (QRM, EMI) may cause jitter
  - Future: measure N times, take median

- **SSA TG level fixed at -10 dBm**: Not adjustable from script
  - May overdrive AD8307 (max input ~+10 dBm)
  - May underdrive on very mismatched antenna (high loss)
  - Future: add `--tg-level` argument

- **No safety interlocks**: Script assumes scpi-ptt provides proper sequencing
  - If scpi-ptt relay fails closed → hot switching
  - If scpi-ptt fails open → no RF path during measurement
  - Hardware solution: add RF sensing interlock to scpi-ptt

## Future Enhancements

### Web UI

Migrate to FastAPI + WebSocket server:

- Real-time grid search visualization (L/C heatmap, SWR contour plot)
- Live tuning in browser, no SSH required
- Mobile-friendly (tablet in shack)

### Multi-Frequency Scanning

Accept CSV input with frequency list, auto-tune entire band:

```csv
frequency_mhz,memory_slot
3.500,0
3.600,1
3.700,2
...
3.900,9
```

Script tunes each frequency, saves to memory, generates report with coverage map.

### Kalman Filtering

Apply Kalman filter to SWR measurements:

- Reduces noise from QRM/EMI
- Allows faster tuning (fewer settle time delays)
- Improves convergence in electrically noisy environments

### Gradient Descent / Nelder-Mead

For very large L/C ranges (e.g., wide-range roller inductor), grid search becomes slow. Implement gradient descent or Nelder-Mead simplex:

- Faster convergence (10-20 iterations vs 500+)
- Risk of local minima (mitigate with random restart)

### Automatic Band Detection

Query connected transceiver (via Hamlib) for current frequency, auto-tune without user specifying `--freq`:

```bash
# Hamlib running on localhost:4532, tuned to 7.200 MHz
./auto_tuner.py ... --auto-freq --hamlib localhost:4532
```

### Load Impedance Measurement

Integrate VNA (HP 8712B project, hardware pending) or use SSA's IQ-capture mode:

- Measure Z = R + jX at antenna terminals
- Display Smith chart
- Guide L/C selection (e.g., "too capacitive, increase L")

### Integration with SOTA/POTA Tracker

Hook into `~/ota/` SOTA/POTA activator app:

- User selects active station from OTA list
- OTA queries station's frequency
- Auto-tuner tunes antenna
- OTA cues JF8Call to call the station
- Full automation: see → tune → call → log

---

## Hardware Reference

### Directional Coupler Specs

Recommended: **Mini-Circuits ZFDC-20-5+**

- Frequency: 2-2000 MHz
- Coupling: 20 dB ± 1.5 dB
- Directivity: >20 dB
- Insertion loss: <0.2 dB
- Power: 20W CW max
- Connectors: SMA

Cheaper alternative: **Chinese "20 dB dual directional coupler"** (~$15 on eBay)

- Frequency: 1-500 MHz (adequate for HF + 6m)
- Coupling: ~20 dB (uncalibrated, measure with VNA)
- Power: 10W CW typical
- Connectors: SMA or BNC

### AD8307 Wiring (per detector)

```
AD8307 Pin    Function         ESP32 Connection
-----------   --------------   ------------------
1 (VOUT)      Detector output  ADC GPIO (e.g., GPIO34 for FWD, GPIO35 for REF)
2 (GND)       Ground           ESP32 GND
3 (INP-)      RF input -       Directional coupler FWD/REF port via DC block
4 (INP+)      RF input +       Directional coupler center conductor via DC block
5 (ENB)       Enable           +5V (always enabled)
6 (COM)       Ground           ESP32 GND
7 (VPS)       Power supply     ESP32 VIN (+5V)
8 (INT)       Interceptor      Open (not used)
```

**DC Block Capacitor**: 100 nF / 50V ceramic between coupler SMA center pin and AD8307 INP+. Prevents DC bias from damaging AD8307.

**Calibration**: Two-point linear fit (details in scpi-swr project README).

### Stepper Motor Selection

**Inductance control**: NEMA 17 with hollow shaft, air-wound coil inside

- Coil: 20-30 turns AWG 18 magnet wire, 40mm diameter → ~5-10 µH
- Variable: 0-200 steps × 1.8° = 0-360° rotation
- Mount coil on shaft, fixed winding on stator

**Capacitance control**: NEMA 17 with gear reducer, butterfly capacitor

- Butterfly: dual variable cap, 10-500 pF per section
- Gear ratio: 5:1 (stepper 200 steps → capacitor 40 steps, finer resolution)
- Mount via coupling shaft

### PTT Relay Specs

**Recommended**: **Omron G5V-2** or **Panasonic TQ2-L2**

- Coil: 5V DC (matches ESP32 logic level via transistor driver)
- Contacts: DPDT, 1A @ 30 VDC (adequate for low-level RF switching)
- Switching time: <10 ms
- Lifetime: >10M operations

Drive circuit: ESP32 GPIO → 2N2222 NPN → relay coil (flyback diode across coil).

---

## License

(Same as parent rf-bench project: GPL-3.0-or-later)

## Author

Part of the rf-bench monorepo: https://github.com/jfrancis42/rf-bench
