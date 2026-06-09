# dstar-monitor

D-STAR digital voice activity monitor for the **Icom IC-9700**.

Monitors a D-STAR frequency in DV mode.  The IC-9700 decodes all D-STAR
frames internally; this script reads the decoded header data (originating
callsign, destination, repeater path, free-text message) via Hamlib CAT
and logs each transmission to SQLite.

## Hardware required

- Icom IC-9700 with D-STAR capability (rigctld running)
- 2m or 70cm antenna on a D-STAR-active frequency

## Setup

```bash
pip install rf-bench-drivers-icom

rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &
```

## Usage

```bash
# Monitor 144.490 MHz D-STAR calling:
python dstar_monitor.py --freq 144490

# With FCC callsign enrichment:
python dstar_monitor.py --freq 144490 --enrich

# 70cm D-STAR:
python dstar_monitor.py --freq 445000 --enrich
```

## Output

Live console display:

```
Time      MYCALL     URCALL     Signal    Message
──────────────────────────────────────────────────────────────────────
14:23:01  W6ABC    CQCQCQ     -82.0 dBm  testing 123  [Alice Smith]
14:25:44  N0GQ       W6ABC      -74.5 dBm  hello Alice
```

SQLite database `dstar_<freq>_<timestamp>.db`:

| Column | Description |
|--------|-------------|
| `mycall` | Originating station callsign |
| `urcall` | Destination (CQCQCQ for general calls) |
| `rpt1` / `rpt2` | Repeater path (gateway, reflector) |
| `message` | 20-character free-text message |
| `signal_dbm` | IC-9700 S-meter reading |
| `fcc_name` | FCC licensee name (if `--enrich`) |

## D-STAR CAT commands

The IC-9700 exposes decoded D-STAR header fields via CI-V commands.
Hamlib wraps these as `get_func DSTAR_MYCALL` etc.  If your Hamlib
version does not support these (older builds), the script falls back
to S-meter-only monitoring — it still detects when signal is present
but cannot decode callsigns.

Check support with:
```bash
rigctl -m 3081 -r /dev/ttyUSB0 u DSTAR_MYCALL
```

## Common D-STAR frequencies (US)

| Frequency | Use |
|-----------|-----|
| 144.490 MHz | 2m D-STAR simplex calling |
| 145.670 MHz | Common 2m D-STAR repeater output |
| 439.200 MHz | 70cm D-STAR simplex calling |
| 446.000 MHz | Common 70cm D-STAR repeater output |
