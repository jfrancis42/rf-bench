# siglent-psrr

Measures Power Supply Rejection Ratio (PSRR) vs frequency for voltage regulators and LDOs.
Injects AC ripple onto the regulator input via a passive coupling network and computes
`PSRR(f) = 20 × log10(Vin_ripple / Vout_ripple)` at each frequency. Higher dB = better.

## Hardware required

- Siglent SDS2504X Plus (LAN, `10.1.1.58`) — scope and AWG source
- Passive AC injection circuit (user-built, ~$5 in parts):
  - 10 µF ceramic capacitor (DC block)
  - 10 µH inductor (prevents supply from shorting the AWG signal)
- DC supply for the DUT (e.g., Siglent SPD3303X or bench supply)

> **HARDWARE SAFETY:** Never connect the AWG output directly to a live DC rail.
> The coupling capacitor and inductor are mandatory — they protect both the AWG
> and the power supply from each other.

## Cable setup

```
SDS2504X Plus
  AWG "Gen Out" ──[C 10µF]──[L 10µH]──┐
                                        ├── Regulator Vin ── CH1 (AC coupled)
                                        │
                               [DC supply]

Regulator GND  ── Scope GND (BNC shield)
Regulator Vout ── CH2 (AC coupled)
```

CH1 monitors the actual AC ripple reaching the regulator input.
CH2 monitors the resulting ripple on the regulated output.

## Generator

This tool uses the **scope AWG only** (no SDG option). The AWG shares chassis ground
with the scope, eliminating the ground loop that would occur with an external generator.
Using the SDG would introduce a ground loop that contaminates the measurement.

AWG range: 1 Hz – 25 MHz. Most regulators' PSRR bandwidth of interest is 100 Hz – 1 MHz,
well within range.

## Usage

```bash
# Default: 100 Hz – 1 MHz, 80 points, 100 mVpp injection
python psrr.py

# Sweep to 500 kHz
python psrr.py --stop-hz 500000

# Lower injection for quiet regulators (reduces disturbance to circuit under test)
python psrr.py --level-vpp 0.05

# More resolution
python psrr.py --points 120

# Use channels 3/4 instead of 1/2
python psrr.py --ch-input 3 --ch-output 4
```

## Output files

| File | Contents |
|------|----------|
| `<prefix>_psrr.png` | PSRR (dB) vs frequency (log scale); 20/40/60/80 dB reference lines; green shading above 40 dB |
| `<prefix>_psrr.csv` | freq_hz, psrr_db, phase_deg |
| `<prefix>_psrr.txt` | Summary: frequency where PSRR drops below 40 dB and 20 dB; average PSRR by band |

## Interpreting results

- **> 60 dB**: excellent (most modern LDOs at low frequency)
- **40–60 dB**: good — adequate for most applications
- **< 20 dB**: poor — the supply noise passes nearly unattenuated to the output
- The frequency where PSRR first drops below 40 dB is the practical PSRR bandwidth

## Notes

- At very high PSRR (> 80 dB), Vout ripple approaches the scope noise floor (~0.5 mV
  at 2 mV/div). Increase `--level-vpp` if the output channel appears noisy.
- The injection inductor self-resonance limits useful injection to ~10–50 MHz depending
  on inductor selection. A 10 µH air-core inductor is typical.
- Output ripple is measured with AC coupling on both channels — DC rail voltage is
  irrelevant to the ratio measurement.

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
```
