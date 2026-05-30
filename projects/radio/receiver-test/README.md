# siglent-receiver-test

Automated HF receiver test suite. Drives a **Siglent SDG1062X** function generator and
**SDS2354X Plus** oscilloscope via SCPI, and an **Icom IC-7300** transceiver via Hamlib CAT,
to perform a standard battery of receiver performance measurements without human intervention.

## Measurements

| Test | What it measures | Method |
|------|-----------------|--------|
| `mds` | Minimum Discernible Signal / noise figure | SDG level sweep + IC-7300 S-meter via CAT |
| `smeter-cal` | S-meter calibration curve | SDG level sweep + IC-7300 S-meter via CAT |
| `imd` | Two-tone IMD / third-order intercept (IP3) | Dual-channel SDG + scope FFT on audio output |
| `blocking` | Blocking dynamic range | SDG two-tone + IC-7300 S-meter via CAT |
| `selectivity` | IF filter passband shape | SDG frequency sweep + IC-7300 S-meter via CAT |

## Hardware required

- Siglent SDG1062X function generator (LAN connected)
- Siglent SDS2354X Plus oscilloscope (LAN connected, for IMD test only)
- Icom IC-7300 transceiver (USB connected, rigctld running)
- Attenuator chain: ≥110 dB total (e.g. 60 dB + 30 dB + 20 dB SMA pads stacked)
- Resistive combiner for two-tone tests (two 100Ω + one 50Ω resistor in SMA box)

```
SDG CH1 ──[100Ω]──┬──[attn chain]── IC-7300 ANT
SDG CH2 ──[100Ω]──┘
                  │
                [50Ω]
                  ╧
```

For the IMD test, connect the IC-7300 audio output (rear panel ACC socket or headphone jack)
to scope CH1.

## Setup

### 1. Install dependencies

```bash
pip install numpy matplotlib scipy --break-system-packages
```

### 2. Set instrument IP addresses

The SDG and scope must have static IPs on your bench LAN. Configure via each instrument's
Utility → LAN menu. Edit the defaults at the top of `receiver_test.py` or pass on the
command line:

```python
SDG_HOST   = "10.1.1.61"   # SDG1062X
SCOPE_HOST = "10.1.1.62"   # SDS2354X Plus
```

### 3. Start rigctld

```bash
# IC-7300 on /dev/ttyUSB0 (Hamlib 4.x model number)
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 &

# Hamlib 3.x uses model 373:
# rigctld -m 373 -r /dev/ttyUSB0 -s 115200 &
```

The IC-7300's CI-V baud rate must be set to 115200 (Menu → Set → Connectors → CI-V Baud Rate).

### 4. Run S-meter calibration first

```bash
python receiver_test.py --test smeter-cal --freq 14200 --atten 110
```

This produces `~/.ic7300_smeter_cal.json`, which all subsequent tests use to convert S-meter
readings to dBm. Run it once per band; re-run if you change the attenuation chain.

## Usage

```
python receiver_test.py --test TEST [OPTIONS]

Tests:
  smeter-cal    S-meter calibration (run first)
  mds           Minimum Discernible Signal + noise figure
  imd           Two-tone IMD / IP3 (requires scope on audio output)
  blocking      Blocking dynamic range
  selectivity   IF filter shape

Options:
  --sdg HOST          SDG1062X IP address [default: 10.1.1.61]
  --scope HOST        SDS2354X Plus IP address [default: 10.1.1.62]
  --rigctld ADDR      rigctld host:port [default: localhost:4532]
  --freq KHZ          Test frequency in kHz [default: 14000]
  --mode MODE         Receiver mode: usb, lsb, cw [default: usb]
  --atten DB          Total attenuation in dB [default: 110]
  --scope-ch N        Scope channel for audio input [default: 1]
  --no-rig            Skip CAT control (manual tune, IMD-only)
  --output PREFIX     Output file prefix [default: auto-timestamped]
  --yes               Skip confirmation prompts
```

### Examples

```bash
# S-meter calibration on 20m
python receiver_test.py --test smeter-cal --freq 14200 --atten 110

# MDS on 40m (requires calibration file)
python receiver_test.py --test mds --freq 7100 --mode usb --atten 110

# Two-tone IMD / IP3 on 20m (scope CH1 connected to IC-7300 audio out)
python receiver_test.py --test imd --freq 14200 --atten 110

# IF selectivity in CW mode
python receiver_test.py --test selectivity --freq 14060 --mode cw --atten 110

# Blocking dynamic range on 20m
python receiver_test.py --test blocking --freq 14200 --atten 110

# Run all tests
python receiver_test.py --test smeter-cal mds imd blocking selectivity --freq 14200 --atten 110
```

## Theory

### MDS and noise figure

MDS (Minimum Discernible Signal) is the input signal level at which the received signal equals
the receiver noise floor (SNR = 0 dB, or equivalently, S+N = 3 dB above N). Measured by
stepping the SDG output down in 1 dB increments and reading the IC-7300's S-meter via CAT
until the reading drops to the undriven noise floor.

Noise figure is derived from MDS:
```
NF = MDS_dBm − (−174 + 10·log10(BW_Hz))
```
where BW is the receiver noise bandwidth of the selected filter.

### Two-tone IMD and IP3

Two RF tones (f₁, f₂) are injected into the receiver. The nonlinear front end generates
intermodulation products at 2f₁−f₂ and 2f₂−f₁, which fall in the receiver passband and
appear as audio tones. Their levels relative to the desired tones determine IP3:

```
IIP3 = P_in + (P_signal_audio − P_imd_audio) / 2   [dBm, input-referred]
```

The scope captures the audio output and a Python FFT finds the tone amplitudes. AGC does not
affect this measurement because it compresses signal and IMD products equally, preserving
their ratio.

Default tone placement for USB mode (receiver tuned to fc):
- f₁ = fc + 1.0 kHz → audio 1000 Hz
- f₂ = fc + 1.5 kHz → audio 1500 Hz
- IMD products → audio 500 Hz and 2000 Hz (all within SSB passband)

### Blocking dynamic range

A strong off-frequency interferer (CH1) is stepped up in level while a weak wanted signal
(CH2 at a fixed low level) is monitored on the S-meter. Blocking dynamic range = interferer
level at which the S-meter reading of the wanted signal drops 1 dB, minus the MDS.

## Output files

Each test run writes:
- `<prefix>_<test>.txt`  — text report with summary table
- `<prefix>_<test>.png`  — plot (level sweep, FFT spectrum, filter shape, etc.)
- `<prefix>_<test>.json` — raw measurement data for post-processing or comparison

## Instrument notes

**SDG1062X:** Uses Siglent EasyWave protocol (C1:BSWV / C2:BSWV commands), not standard SCPI.
Both channels are used simultaneously for two-tone tests. Amplitude is set in Vpp internally;
the script accepts and displays dBm.

**SDS2354X Plus:** Used only for the IMD test. Captures audio waveform via SCPI, returns raw
samples decoded from IEEE 488.2 binary block. FFT is done in Python (scipy / numpy).

**IC-7300:** Controlled via rigctld. Tests that use the S-meter require rigctld to be running.
The `--no-rig` flag disables CAT control; only the IMD test (scope-only) works in that mode.

## Notes on accuracy

- Level accuracy is limited by SDG amplitude accuracy (±2% + 2 mVpp) and attenuator
  tolerance. For best results, use precision attenuators (Mini-Circuits VAT series) and
  verify the total attenuation with the SDG + SSA at a convenient level before testing.
- The S-meter calibration test characterizes the IC-7300's signal meter; subsequent tests
  use the calibration curve to convert meter readings to dBm.
- MDS accuracy: ±2–3 dB typical without independent power reference.
- IP3 accuracy: ±1–2 dB typical; limited mainly by the FFT frequency/amplitude resolution
  and any AGC gain steps near the test level.
