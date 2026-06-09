# fm-deviation

Measures FM transmitter deviation of the **Icom IC-9700** using the
**Siglent SSA3032X Plus**.

Injects an audio tone into the IC-9700 microphone input, keys the
transmitter, and reads FM deviation from the SSA's built-in FM
demodulation measurement.  Verifies compliance with ±5 kHz narrow FM
specification used on 2m and 70cm repeaters.

## Hardware required

- Icom IC-9700 (USB or LAN, rigctld running)
- Siglent SSA3032X Plus (LAN connected)
- **Attenuator ≥ 30 dB** between IC-9700 TX output and SSA RF input
- Audio source: signal generator, PC audio, or BNC-to-3.5mm adapter

> ⚠️  **Always use an attenuator** between IC-9700 TX and SSA.
> The IC-9700 outputs up to 75 W (48.8 dBm) on 2m.
> The SSA RF input maximum is +30 dBm.
> A 30 dB pad brings 75 W down to 75 mW (+18.8 dBm) — within spec.
> For safety, use ≥ 50 dB total.

```
IC-9700 ANT → [≥30 dB attenuator] → SSA RF In
Audio source → BNC-to-3.5mm → IC-9700 MIC jack
```

## Setup

```bash
pip install rf-bench-drivers-icom rf-bench-drivers-siglent rf-bench-drivers-utils \
            numpy matplotlib

rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &
```

## Usage

```bash
# Single measurement at 144.200 MHz, 50 dB path attenuation:
python fm_deviation.py --freq 144200 --atten 50

# Sweep audio input level (deviation vs. drive level curve):
python fm_deviation.py --freq 146520 --atten 50 --sweep

# 70cm:
python fm_deviation.py --freq 432100 --atten 50

# Custom test tone frequency (default 1 kHz):
python fm_deviation.py --freq 144200 --audio-hz 400
```

## Output

- `fm_dev_<freq>_<timestamp>.json` — deviation measurement(s)
- `fm_dev_<freq>_<timestamp>.png` — deviation vs. audio level plot (sweep mode)

## Narrow FM specification

| Parameter | Value |
|-----------|-------|
| Channel spacing | 15 kHz (IARU Region 2) |
| Maximum deviation | ±5 kHz |
| Standard tone | 1 kHz (EIA/TIA-603) |

A deviation of more than ±5 kHz will splatter into adjacent channels.
Less than ±2 kHz results in weak, hard-to-copy audio.
