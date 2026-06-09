# vhf-receiver-test

VHF/UHF receiver sensitivity test suite for the **Icom IC-9700**, using the
**Siglent SSA3032X Plus** tracking generator as the signal source.

The SSA tracking generator covers 9 kHz–3.2 GHz, reaching all three IC-9700
bands (2m, 70cm, 23cm) without needing an upconverter.

## Measurements

| Test | What it measures |
|------|-----------------|
| `smeter-cal` | S-meter calibration: maps IC-9700 S-meter reading → true input level (dBm) |
| `mds` | Minimum Discernible Signal (10 dB S/N) and noise figure |
| `nf` | Alias for `mds` |

## Hardware required

- Icom IC-9700 transceiver (USB or LAN, rigctld running)
- Siglent SSA3032X Plus spectrum analyzer (LAN connected)
- Attenuator chain: ≥50 dB recommended (more for MDS — see below)

```
SSA TG Out → [attenuator chain] → IC-9700 antenna port
```

**Attenuation guide:**

| Test | Minimum | Recommended |
|------|---------|-------------|
| S-meter cal | 30 dB | 50 dB |
| MDS (2m) | 80 dB | 110 dB |
| MDS (70cm) | 80 dB | 110 dB |

IC-9700 MDS is approximately −135 dBm on 2m (USB/CW).  With the SSA TG at
0 dBm, you need 135 dB of attenuation to reach MDS.  Use calibrated SMA
pad stackups: 30 dB + 30 dB + 30 dB + 20 dB = 110 dB, then increase TG
level or reduce pads as needed.

## Setup

```bash
pip install rf-bench-drivers-icom rf-bench-drivers-siglent rf-bench-drivers-utils \
            numpy matplotlib

# Start rigctld (USB):
rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &
```

## Usage

```bash
# S-meter calibration at 144.200 MHz, 50 dB path:
python vhf_receiver_test.py --test smeter-cal --freq 144200 --atten 50

# MDS + noise figure at 144.200 MHz, 110 dB path:
python vhf_receiver_test.py --test mds --freq 144200 --atten 110

# Full test suite (cal + MDS) on 70cm:
python vhf_receiver_test.py --all --freq 432100 --atten 110

# 23cm (1296 MHz):
python vhf_receiver_test.py --test smeter-cal --freq 1296100 --atten 50 --mode usb

# FM sensitivity on 2m repeater input:
python vhf_receiver_test.py --test mds --freq 146520 --mode fm --atten 110
```

## Output

Each run produces:
- `vhf_rx_<test>_<freq>_<timestamp>.json` — measurements and settings
- `vhf_rx_<test>_<freq>_<timestamp>.png` — calibration curve or NF bar chart

## Notes on IC-9700 S-meter calibration

Unlike the IC-7300 (S9 = −93 dBm on HF), the IC-9700 uses **S9 = −73 dBm**
on VHF/UHF (ITU standard for VHF).  Each S-unit = 6 dB, so S5 = −97 dBm.

The actual Hamlib S-meter calibration may differ from ideal; the `smeter-cal`
test produces a correction table for use by other projects (`beacon-logger`,
`coverage`, etc.).
