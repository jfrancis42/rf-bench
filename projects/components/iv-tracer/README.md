# siglent-iv-tracer

I-V curve tracer for diodes, Zener diodes, LEDs, BJTs (family of curves), and MOSFETs.
Sweeps voltage with the SPD3303X bench supply, reads current from the supply's built-in
sense or from the SDM3045X DMM (for µA-range measurements).

## Hardware required

- Siglent SPD3303X-E bench power supply (LAN, `10.1.1.56`)
- For µA current measurement: Siglent SDM3045X DMM (LAN, `10.1.1.63`) with `--use-dmm`

## Cable setup

### Diode / Zener / LED

```
SPD CH1 (+) ─── anode
               [DUT]
SPD CH1 (−) ─── cathode ─── GND
```

For Zener reverse breakdown: swap anode/cathode so CH1 sweeps in the reverse direction.
For µA leakage (e.g., reverse-biased diode): insert SDM in series and use `--use-dmm`.

### BJT (NPN, common-emitter family)

```
SPD CH1 (+) ─── collector
               [NPN BJT]
SPD CH1 (−) ─── emitter ─── GND

SPD CH2 (+) ─── R_base ─── base
SPD CH2 (−) ────────────── GND
```

### MOSFET (N-channel, common-source family)

```
SPD CH1 (+) ─── drain
               [N-MOSFET]
SPD CH1 (−) ─── source ─── GND

SPD CH2 (+) ─── gate
SPD CH2 (−) ────────────── GND
```

## Usage

```bash
# Diode (default), 0–1.5 V
python iv_tracer.py

# Zener, 0–5.1 V
python iv_tracer.py --device zener

# LED, 0–3.5 V (use --v-stop 3.8 for blue/UV LEDs)
python iv_tracer.py --device led --v-stop 3.2

# BJT family of curves, 5 I_B steps
python iv_tracer.py --device bjt --r-base 1000 --base-current-ma 10 --n-curves 5

# MOSFET family, 6 V_GS steps
python iv_tracer.py --device mosfet --n-curves 6 --v-stop 8.0

# High-accuracy current with DMM (µA range)
python iv_tracer.py --use-dmm

# Print voltage sequence without touching instruments
python iv_tracer.py --dry-run --device bjt
```

## Output files

| File | Contents |
|------|----------|
| `<prefix>_iv.png` | I-V curve(s) — V on X axis, I (mA) on Y axis; V_f at 10/20 mA annotated for diodes |
| `<prefix>_iv.csv` | Diode: voltage_v, current_a, current_ma. BJT: ib_ma_set, ib_actual_ma, v_ce_v, i_c_a. MOSFET: v_gs_v, v_ds_v, i_d_a |
| `<prefix>_iv.txt` | Summary: V_f at standard currents (diode/LED/Zener), hFE table (BJT), peak I_D per V_GS (MOSFET) |

## Safety

- The SPD current limit (`--i-limit`, default 100 mA) is enforced in hardware at all times.
- If the supply enters constant-current (CC) mode during a sweep, the script stops
  immediately to protect the device.
- `--dry-run` prints the full voltage sequence without connecting to any instrument.
- All channels are disabled in the `finally:` block even on exception or Ctrl-C.

## Notes

- SPD built-in current sense resolution is ~1 mA — use `--use-dmm` for leakage measurements
- V_BE is estimated at 0.65 V for BJT I_B calculation; actual I_B depends on the transistor
- PNP and P-channel devices require reversed connections (not automatic)

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
```
