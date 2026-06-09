# rx-crosscheck

Cross-calibrates the **RTL-SDR** against the **Icom IC-9700** S-meter.

Tunes both receivers to the same VHF/UHF frequency, measures the same
signal simultaneously, and produces a calibration table that converts
RTL-SDR relative power (dBFS) to calibrated dBm values traceable to the
IC-9700's ITU S-meter scale.

After running this once, RTL-SDR projects (`drivetest`, `survey`, `classify`,
etc.) can report calibrated signal levels instead of raw dBFS readings.

## Hardware required

- Icom IC-9700 (rigctld running)
- RTL-SDR Blog v4
- **Option A (recommended):** Siglent SSA3032X Plus as signal source
  - Power splitter or resistive T-combiner
  - Attenuators for each receiver leg (≥20 dB RTL-SDR, ≥30 dB IC-9700)
- **Option B:** Any on-air carrier (beacon, repeater, APRS)

```
SSA TG Out → power splitter ─┬─ [≥30 dB atten] → IC-9700 ANT
                              └─ [≥20 dB atten] → RTL-SDR
```

## Setup

```bash
pip install rf-bench-drivers-icom rf-bench-drivers-rtlsdr \
            rf-bench-drivers-siglent rf-bench-drivers-utils \
            numpy matplotlib

rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &
```

## Usage

```bash
# SSA TG sweep at 144.200 MHz:
python rx_crosscheck.py --freq 144200 --source ssa \
    --atten-ic9700 30 --atten-rtlsdr 20

# On-air APRS signal:
python rx_crosscheck.py --freq 144390 --source air --label "APRS"

# 70cm with SSA TG:
python rx_crosscheck.py --freq 432100 --source ssa \
    --atten-ic9700 30 --atten-rtlsdr 20
```

## Output

- `rx_crosscheck_<freq>_<timestamp>.json` — raw paired measurements
- `rx_crosscheck_<freq>_<timestamp>.png` — scatter plot with linear fit
- `~/.rtlsdr_vhf_cal.json` — calibration table (auto-loaded by RTL-SDR projects)

The calibration table contains a linear fit per frequency:

```json
{
  "144200000": {
    "freq_hz": 144200000,
    "slope": 1.02,
    "offset": 45.3,
    "updated": "2026-06-03T20:00:00Z"
  }
}
```

Convert RTL-SDR readings: `signal_dbm = slope × rtl_dbfs + offset`
