# atten-cal — Per-code per-frequency attenuator calibration

For each control code of a digital step attenuator, sweep S21 and
record actual attenuation. Output: JSON 2-D table (code → freq →
atten_db) and optional PDF overlay.

**⚠ Untested against hardware.** The attenuator-setting logic is a
placeholder; pass `--manual` to set each code by hand, or wire in
your Bus Pirate / SPI controller in `set_attenuator_code()`.

## Usage

```bash
python atten_cal.py --start 1 --stop 1000 \
    --code-start 0 --code-stop 63 --manual \
    --label "PE43602 #2" \
    --output pe43602.json --plot pe43602.pdf
```

## Output

JSON: `{label, timestamp, table: {code: {freq_hz, atten_db}}}`.
PDF: stacked traces, one per code.

## Notes

- Downstream projects load this and interpolate `atten(code, f)` for
  true-dB-accurate attenuation control.
- Compare to the project domain's `projects/signal-sources/dig-atten-cal/`
  which is the existing SDG+SSA-based calibration of the same chips.
