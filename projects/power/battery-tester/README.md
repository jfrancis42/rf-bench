# siglent-battery-tester

Battery capacity (mAh), internal resistance (mΩ), and multi-cycle charge/discharge tester.
Uses the ET5406A+ programmable DC load for CC discharge, the SDM3045X for voltage
measurement, and optionally the SPD3303X for CC-CV recharging in cycle mode.

## Hardware required

- Yertai ET5406A+ DC load (USB serial, `/dev/ttyUSB0`) — required for discharge
- Siglent SDM3045X DMM (LAN, `10.1.1.63`) — battery voltage measurement
- Siglent SPD3303X-E (LAN, `10.1.1.56`) — CC-CV charging in `--mode cycle` only

> **NOTE:** The ET5406A+ is not currently bench-connected. All ET54 API calls are
> from library documentation. The script degrades gracefully — if ET54 is unavailable
> it will print a warning and skip load-dependent tests.

## Cable setup

### Capacity / internal resistance mode

```
Battery (+) ──── ET5406A+ load V+  ──── SDM sense Hi
Battery (−) ──── ET5406A+ load V−  ──── SDM sense Lo
```

Use separate Kelvin sense leads from the battery terminals to the SDM for best accuracy.
The ET5406A+ has its own voltage readback, but the SDM3045X is more accurate.

### Cycle mode (charge + discharge)

```
SPD CH1 (+) ──[1N5819 Schottky]── Battery (+) ─── ET5406A+ V+
SPD CH1 (−) ─────────────────── Battery (−) ─── ET5406A+ V−
```

The series Schottky diode prevents the ET54 load from back-driving the SPD during
the discharge phase. A 1N5819 works well; the ~0.3 V forward drop is acceptable.

## Usage

```bash
# Measure capacity: CC discharge at 1 A to cutoff voltage 3.0 V
python battery_tester.py

# 2 A discharge rate, 2.8 V cutoff
python battery_tester.py --mode capacity --discharge-current 2.0 --cutoff-voltage 2.8

# DC pulse internal resistance measurement
python battery_tester.py --mode internal-resistance

# 3 charge/discharge cycles (tracks capacity fade)
python battery_tester.py --mode cycle --cycles 3

# Custom USB port (if load is not at /dev/ttyUSB0)
python battery_tester.py --load-port "ASRL/dev/ttyUSB1::INSTR"
```

## Output files

| File | Contents |
|------|----------|
| `<prefix>_capacity.png` | Voltage and current vs. time; mAh accumulated annotated |
| `<prefix>_capacity.csv` | time_s, voltage_v, current_a, mah |
| `<prefix>_capacity.txt` | Summary: total capacity mAh, start/end voltage, mean discharge current |
| `<prefix>_ir.txt` | Internal resistance: pulse method result in mΩ; OCV comparison |
| `<prefix>_cycle.png` | Capacity fade: mAh per cycle (multi-cycle mode) |

## Modes

| Mode | Description |
|------|-------------|
| `capacity` | CC discharge at `--discharge-current` amps; stops at `--cutoff-voltage` |
| `internal-resistance` | DC pulse method: R = ΔV / ΔI at two current levels |
| `cycle` | SPD CC-CV charge → ET54 CC discharge × `--cycles` times; plots capacity fade |

## Notes

- Default discharge current: 1.0 A. Set `--discharge-current` to match the battery's
  rated C-rate (e.g., 0.5 A for a 500 mAh cell at 1C).
- Capacity is integrated via the trapezoidal rule — logged every `--log-interval-s` seconds
  (default 5 s). Shorter intervals give more accurate integration.
- No temperature monitoring is implemented. Do not leave lithium batteries unattended.
- Internal resistance measured here is DC ESR (pulse method), not AC impedance (EIS).

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
ET54 (install: pip install "git+https://github.com/philpagel/ET54.py.git")
pyvisa >= 1.11
pyvisa-py >= 0.5
```
