# Op-Amp Offset Voltage Tester

Precision measurement of op-amp input offset voltage (Vos) using ESP32 scpi-mux, scpi-relay, SPD3303X dual PSU, and SDM3045X 6.5-digit DMM.

Status: 🔨 (Under Construction)

## Hardware

- **scpi-mux**: ESP32-based CD4067 16-channel analog multiplexer (selects which op-amp output to measure)
- **scpi-relay**: ESP32-based power relay (gates DUT power to prevent thermal crosstalk)
- **SPD3303X**: Siglent dual power supply (provides ±15V rails)
- **SDM3045X**: Siglent 6.5-digit DMM (~10 µV resolution on 200 mV range)

## Test Circuit

Each op-amp is wired in **unity-gain configuration**:

```
    V+ ──┐
         │
    Vin ─┤─\
         │  >─── Vout (to DMM via scpi-mux)
    ┌────┤+/
    │    │
    │    └── V-
    │
    └────────┘ (feedback to inverting input)
```

With Vin = 0V (grounded):
- Ideal op-amp: Vout = 0V
- Real op-amp: Vout = Vos (input offset voltage)

The DMM directly measures Vos with no additional math required.

## Theory of Operation

**Input offset voltage (Vos)** is the voltage that must be applied between the op-amp's inputs to drive the output to zero. In a unity-gain buffer with the non-inverting input grounded, the output voltage equals Vos directly.

**Why power gating matters:** Op-amps dissipate heat when powered. Testing 16 DUTs simultaneously would create thermal gradients on the test board, causing Vos to drift during measurement. The scpi-relay powers each DUT only during its measurement window, then immediately turns it off. This prevents thermal crosstalk and ensures each measurement is taken at the same ambient temperature.

**Matched pairs:** Audio amplifiers, instrumentation amps, and high-precision circuits often require matched op-amp pairs (low ΔVos between channels). This tool tests a batch, sorts by |Vos|, and identifies the best-matched pairs.

## Installation

```bash
pip install rf-bench-drivers-siglent requests
```

## Usage

### Basic measurement (16 op-amps, ±15V)

```bash
./opamp_offset.py --esp-mux 10.1.0.50 --esp-relay 10.1.0.51 \
                   --psu 10.1.0.44 --dmm 10.1.0.42 \
                   --duts 16 --supply-v 15.0
```

### Test fewer DUTs (8 op-amps)

```bash
./opamp_offset.py --esp-mux 10.1.0.50 --esp-relay 10.1.0.51 \
                   --psu 10.1.0.44 --dmm 10.1.0.42 \
                   --duts 8
```

### Different supply voltage (±12V) and longer settling time

```bash
./opamp_offset.py --esp-mux 10.1.0.50 --esp-relay 10.1.0.51 \
                   --psu 10.1.0.44 --dmm 10.1.0.42 \
                   --supply-v 12.0 --settling 2.0
```

### Custom output file

```bash
./opamp_offset.py --esp-mux 10.1.0.50 --esp-relay 10.1.0.51 \
                   --psu 10.1.0.44 --dmm 10.1.0.42 \
                   --output tl072_batch_42.csv
```

## Output

The script produces:
1. **CSV file** with raw measurements (DUT number, Vos in V and µV)
2. **Sorted table** of DUTs by |Vos| (best to worst)
3. **Matched pairs** list (adjacent DUTs in sorted order)

Example output:

```
DUT  1: Vos = +0.4523 mV (+452.30 µV)
DUT  2: Vos = -0.2134 mV (-213.40 µV)
DUT  3: Vos = +1.0234 mV (+1023.40 µV)
...

DUTs sorted by |Vos| (best to worst):
 1. DUT  7: +0.0345 mV (+34.50 µV)
 2. DUT 12: -0.0512 mV (-51.20 µV)
 3. DUT  2: -0.2134 mV (-213.40 µV)
 4. DUT  1: +0.4523 mV (+452.30 µV)
...

Matched pairs (adjacent in sorted list):
Pair 1: DUT  7 + DUT 12  (ΔVos = 16.70 µV)
Pair 2: DUT  2 + DUT  1  (ΔVos = 238.90 µV)
...
```

## Hardware Setup

1. **Power supply connections:**
   - SPD3303X CH1 (+15V) → all op-amp V+ pins
   - SPD3303X CH2 (+15V, configured as -15V) → all op-amp V- pins
   - scpi-relay in series with V+ or V- rail (gates power per DUT)

2. **Signal routing:**
   - Non-inverting inputs (+) → GND (Vin = 0V)
   - Inverting inputs (-) → op-amp outputs (unity-gain feedback)
   - Op-amp outputs → scpi-mux channels 1-16
   - scpi-mux common output → SDM3045X input

3. **Decoupling:**
   - 0.1 µF ceramic + 10 µF electrolytic on each V+/V- rail, close to each op-amp
   - Star-ground layout to minimize ground loops

## Use Cases

### Op-Amp Selection
Test a batch of 16 TL072 op-amps, identify the ones with lowest Vos for precision applications (instrumentation amps, active filters, current sources).

### Matched Pairs for Audio
Build a stereo headphone amp with matched TL072 pairs to minimize channel-to-channel offset (DC at output causes clicks/pops). Sort by |Vos|, pick the top two pairs.

### Production Testing
Incoming inspection of op-amps. Measure a sample from each reel, reject batches with excessive Vos or high spread.

### Precision Instrumentation
Select op-amps for a 4-channel data acquisition front-end. Matched Vos reduces inter-channel error and simplifies calibration.

## Temperature Coefficient Testing

Combine with **scpi-temp** (ESP32-based temperature controller) to measure Vos vs. temperature:

```bash
# Sweep from 0°C to 70°C in 10°C steps
for temp in 0 10 20 30 40 50 60 70; do
  curl http://10.1.0.52/setpoint/$temp
  sleep 300  # Wait for thermal equilibrium
  ./opamp_offset.py --esp-mux 10.1.0.50 --esp-relay 10.1.0.51 \
                     --psu 10.1.0.44 --dmm 10.1.0.42 \
                     --output "vos_${temp}C.csv"
done

# Plot Vos vs temp to extract TC (µV/°C)
```

## Measurement Resolution

- **SDM3045X on 200 mV range:** ~10 µV resolution
- **10 PLC + 10 averages:** ~1.7 seconds per measurement, excellent noise rejection
- **Typical op-amp Vos:**
  - TL07x: ±3 mV (±3000 µV)
  - OP07: ±75 µV
  - LT1028: ±50 µV
  - OPA627: ±200 µV

All well within the DMM's range. For ultra-low-offset op-amps (<10 µV), consider chopper-stabilized parts or a nanovoltmeter.

## Future Enhancements

- **CMRR (Common-Mode Rejection Ratio):** Apply common-mode voltage to both inputs, measure output change
- **PSRR (Power Supply Rejection Ratio):** Modulate V+ or V-, measure output ripple
- **Offset drift vs. time:** Log Vos every 10 sec for 1 hour, identify long-term drift
- **Slew rate:** Unity-gain pulse response
- **Noise:** FFT of output in unity-gain, measure voltage noise density (nV/√Hz)
- **THD+N:** Inject sine wave, measure distortion via FFT

## References

- [Op-Amp Offset Voltage and Drift](https://www.analog.com/en/technical-articles/op-amp-offset-voltage-and-drift.html) (Analog Devices)
- [Measuring Op-Amp Parameters](https://www.ti.com/lit/an/sloa059/sloa059.pdf) (Texas Instruments SLOA059)
- [Precision Op-Amp Selection](https://www.ti.com/lit/an/slyt277/slyt277.pdf) (Texas Instruments SLYT277)
