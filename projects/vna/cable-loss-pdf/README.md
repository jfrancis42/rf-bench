# cable-loss-pdf — Coax cable insertion-loss PDF

S21 sweep with the cable connected as a THRU between VNA port 1 and
port 2 → cable insertion loss in dB → single-page PDF with an optional
second panel showing loss-per-100-ft (or per-100-m).

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Setup

```
VNA Port 1 ── coax under test ── VNA Port 2
```

Run a THRU (or full SOLT) calibration across the same sweep range
first and leave correction enabled. Without calibration the trace
includes the port-to-port reference loss of whatever adapters and
patch leads stay in place.

## Usage

```bash
# 50-ft RG-58 run, 1–500 MHz, compare to RG-58 published curve
python cable_loss_pdf.py --start 1 --stop 500 --length-ft 50 \
    --compare RG-58 --label "50 ft RG-58 to attic dipole" \
    --output rg58_attic.pdf

# 30-ft LMR-400, 144–148 MHz, with pass/fail line at 3 dB/100ft
python cable_loss_pdf.py --start 144 --stop 148 --length-ft 30 \
    --compare LMR-400 --target 3.0 \
    --label "30 ft LMR-400 to 2 m beam" --output lmr400_2m.pdf

# Just total loss, no length normalisation
python cable_loss_pdf.py --start 50 --stop 1500 \
    --label "Patch lead under test" --output patch.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps
- `--power DBM` — HP source power; ignored on NanoVNA
- `--length-ft FT` or `--length-m M` — adds a second panel in dB/100·unit
- `--compare CABLE` — overlay the manufacturer-published loss curve for
  a known cable type. Known types: `RG-58`, `RG-8X`, `RG-213`,
  `LMR-240`, `LMR-400`, `LMR-600`, `9913`, `Heliax-1/2`.
- `--target DB` — draw a horizontal pass/fail line (dB/100 ft)

## Output

Single-page PDF with:

- **Total loss vs frequency** in dB, with endpoint annotations
- (optional) **Loss per 100 ft** or **per 100 m** panel if a length is
  passed, with:
  - the measured curve
  - an optional published cable-type overlay (`--compare`)
  - an optional pass/fail target line (`--target`)
- Title with DUT label, sweep range, point count, driver, IDN, timestamp

## Notes

- The reference cable curves are interpolated against √f (skin-effect
  model). They're useful for sanity-checking — a new factory-terminated
  RG-58 should sit within a couple of dB of the published curve. Bigger
  divergence usually means a wet, kinked, or badly-terminated cable.
- Above the cable's published cutoff, this √f model under-estimates
  loss. The library tables are populated up to ~2 GHz for most cables;
  beyond that, the extrapolation is conservative.
- Length must be the **electrical** run — if you're testing a 50-ft
  patch with two PL-259 pigtails at each end, just use 50 ft. The
  connector losses fold into the total but are negligible for an
  honest cable.
