# siglent-psu-characterizer

Power supply and voltage regulator characterization suite. Measures load regulation,
conversion efficiency, output ripple, and load-step transient response.

## Hardware required

- Siglent SPD3303X-E (LAN, `10.1.1.56`) — source / DUT pass-through supply
- Yertai ET5406A+ DC load (USB serial, `/dev/ttyUSB0`) — programmable load for sweeps
- Siglent SDM3045X DMM (LAN, `10.1.1.63`) — output voltage measurement
- Siglent SDS2504X Plus (LAN, `10.1.1.58`) — ripple and transient capture

Without the ET5406A+, the script skips load-sweep tests but static voltage and ripple
measurements still work.

## Cable setup

```
SPD CH1 (+) ─────────── DUT input (+)
SPD CH1 (−) ─────────── DUT input (−) = GND

DUT output (+) ─┬─── ET5406A+ load V+
                ├─── SDM sense Hi
                └─── Scope CH1 (AC-coupled, ripple/transient)
DUT output (−) ─┴─── ET5406A+ load V−  =  SDM sense Lo  =  Scope GND
```

To characterize the SPD directly (no external DUT), connect scope and DMM to the
SPD CH1 output terminals and use `--v-set` to set the output voltage.

## Usage

```bash
# Full test suite (load regulation + efficiency + ripple + transient)
python psu_characterizer.py

# Load regulation only
python psu_characterizer.py --mode load-reg

# Efficiency sweep
python psu_characterizer.py --mode efficiency

# Output ripple capture at full load
python psu_characterizer.py --mode ripple

# Load step transient response
python psu_characterizer.py --mode transient

# 3.3 V DUT, sweep to 1.5 A
python psu_characterizer.py --v-set 3.3 --i-max 1.5

# 5 V DUT, 10-point load sweep
python psu_characterizer.py --v-set 5.0 --i-max 2.0 --i-points 10
```

## Output files

| File | Contents |
|------|----------|
| `<prefix>_psu.png` | Multi-panel: V_out vs I_load, efficiency vs I_load, ripple waveform, transient response |
| `<prefix>_psu.csv` | i_load_a, v_out_v, p_in_w, p_out_w, efficiency_pct per load step |
| `<prefix>_psu.txt` | Summary: load regulation %, peak efficiency and load point, ripple Vpp/Vrms, transient undershoot/overshoot |

## Test descriptions

| Mode | What it measures |
|------|-----------------|
| `load-reg` | V_out vs I_load from no-load to full load; regulation = (V_noload − V_full) / V_noload × 100% |
| `efficiency` | P_out / P_in at each load step; P_in from SPD power measurement |
| `ripple` | AC-coupled scope capture at full load; reports Vpp and AC RMS |
| `transient` | Load step from low to high current; reports undershoot, overshoot, settling time |

## Notes

- ET5406A+ is not currently bench-connected; script gracefully skips ET54-dependent tests
- P_in is measured at the SPD output terminals — external wiring resistance causes slight
  pessimism in efficiency; for precision use a separate wattmeter at the DUT input
- Ripple capture uses `capture_audio()` from the scope driver — adequate for switching
  frequencies up to a few MHz; for very fast switchers consider manual scope measurement

## Dependencies

```
rf-bench >= 0.2.0
numpy >= 1.20
matplotlib >= 3.4
ET54 (install: pip install "git+https://github.com/philpagel/ET54.py.git")
pyvisa >= 1.11
pyvisa-py >= 0.5
```
