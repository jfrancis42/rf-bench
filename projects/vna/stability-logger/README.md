# stability-logger — Long-running VNA drift monitor

Cron- or systemd-friendly. Each run captures one S11 sweep of a
fixed reference DUT and appends the headline metrics to a CSV log.
Optionally writes a trend-line PDF.

Use it to:

- Track SOLT calibration drift on a precision LOAD or SHORT (run
  hourly via cron).
- Track antenna feedpoint drift over seasons (run nightly with the
  real antenna as DUT).
- Alert on shifted readings: `--alert-mag 0.3` makes the script
  exit 2 when median |Γ| crosses a threshold (cron's mailer picks
  that up).

## Usage

```bash
# Hourly via cron
0 * * * *  python /path/to/stability_logger.py \
   --start 1 --stop 30 --log ~/loadcheck.csv \
   --summary-pdf ~/loadcheck.pdf --alert-mag 0.05

# Manual run
python stability_logger.py --start 1 --stop 30 \
   --log /tmp/test.csv --summary-pdf /tmp/test.pdf --verbose
```

## Output

Console: nothing unless `--verbose` (quiet for cron).

CSV: one row per run with timestamp + peak |Γ|, peak frequency,
median |Γ|, min/max return loss in dB.

PDF: trend lines of peak |Γ| and median |Γ| over all logged
captures so far.

## Exit codes

- 0 — captured and logged successfully
- 1 — script error
- 2 — `--alert-mag` threshold was exceeded
