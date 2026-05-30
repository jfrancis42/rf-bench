# siglent-rf-impedance

Measures component impedance (|Z|, R+jX, phase) vs frequency from 100 kHz to 60 MHz.
Identifies self-resonant frequency (SRF) of inductors, capacitor ESR at RF, and ferrite
bead impedance profiles.

## Hardware required

- Siglent SDS2504X Plus (LAN, `10.1.1.58`)
- 50 Ω precision metal-film resistor (1% or better) as series reference
- Small PCB or BNC test fixture (keep leads short — stray inductance matters above 10 MHz)
- For `--source sdg` (default): Siglent SDG1062X (LAN, `10.1.1.55`)

## Cable setup (series injection)

```
Source ──── R_ref (50 Ω 1%) ──── DUT ──── GND
       CH1 ↑                CH2 ↑
```

CH1 monitors the source side of R_ref; CH2 monitors the DUT terminal.
`Z_DUT = R_ref × V_CH2 / (V_CH1 − V_CH2)`

## Generator options

| | SDG (default) | AWG |
|---|---|---|
| Frequency range | 100 kHz – 60 MHz | 100 kHz – 25 MHz |
| Amplitude accuracy | Better | ±few % |
| Best for | Full HF range | Component work below 25 MHz |

## Usage

```bash
# Measure an RF inductor (annotates SRF and Q)
python rf_impedance.py --component inductor

# Measure a bypass capacitor (annotates SRF and ESR)
python rf_impedance.py --component capacitor --stop-khz 50000

# Ferrite bead characterization (100 kHz – 300 MHz range useful, but limited to 60 MHz here)
python rf_impedance.py --component ferrite --start-khz 1000 --stop-khz 60000

# Higher resolution sweep
python rf_impedance.py --points 500 --start-khz 500 --stop-khz 30000

# AWG source (no SDG needed, up to 25 MHz)
python rf_impedance.py --source awg --stop-khz 25000

# Low excitation for sensitive components
python rf_impedance.py --level-vpp 0.05
```

## Output files

| File | Contents |
|------|----------|
| `<prefix>_impedance.png` | Two-panel: \|Z\| (log Ω) + phase (°) vs frequency; ideal overlay dashed |
| `<prefix>_impedance.csv` | freq_hz, z_mag_ohm, z_real_ohm, z_imag_ohm, phase_deg, L_uh / C_pf |
| `<prefix>_impedance.txt` | Summary: component type, nominal value at ref frequency, SRF, Q |

## Notes

- Keep fixture leads < 5 mm — 10 nH of lead inductance resonates with 100 pF at ~140 MHz
- Default excitation is 0.2 Vpp (small signal to avoid inductor core saturation)
- Accuracy is ±5–20% depending on fixture quality; adequate for SRF identification and matching

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
```
