# Frequency Fetching Guide

This document explains how to automatically fetch transmitter frequencies for all
amateur satellites and add them to the built-in database.

## Quick start

```bash
# 1. See which satellites have transmitter data
./satellite.py --fetch-frequencies

# 2. Generate Python code for TRANSPONDERS dict
./satellite.py --fetch-frequencies --generate-db > new_transponders.txt

# 3. Edit satellite.py and paste in the entries you want
vim satellite.py  # Add entries from new_transponders.txt to TRANSPONDERS dict

# 4. Verify it works
./satellite.py --list-sats  # Should show new satellites
./satellite.py --sat NEW-SAT --gps  # Test pass prediction
```

## How it works

### Step 1: Fetch TLE data

The script downloads `nasabare.txt` from AMSAT, which contains orbital data (TLE)
for ~50 active amateur satellites. This gives us:
- Satellite names
- NORAD catalog numbers
- Orbital parameters (for pass prediction)

**What's missing:** Transponder frequencies and modes.

### Step 2: Query SatNOGS transmitters API

For each NORAD number, the script queries:
```
https://db.satnogs.org/api/transmitters/?format=json&satellite__norad_cat_id={norad}
```

This returns a JSON list of transmitters for that satellite:
```json
[
  {
    "uuid": "...",
    "description": "Voice FM Repeater",
    "downlink_low": 145960000,
    "uplink_low": 435250000,
    "mode": "FM",
    "alive": true,
    "status": "active"
  },
  {
    "description": "Telemetry Beacon",
    "downlink_low": 437525000,
    "mode": "GFSK",
    "alive": true
  }
]
```

### Step 3: Select best transponder

The script selects:
- **Downlink:** First transmitter with `downlink_low` and `alive: true`
- **Uplink:** First transmitter with `uplink_low` and `alive: true`

This heuristic works well for FM voice repeaters but may need manual adjustment
for satellites with multiple transponders (e.g., both V/U and U/V).

### Step 4: Generate Python code

The script outputs ready-to-paste Python dict entries:

```python
"AO-73": {
    "norad": 39444, "tle_group": "amateur",
    "dl": 145960000, "ul": 435150000,
    "dl_mode": "FM", "ul_mode": "FM", "invert": False,
    "note": "AO-73 (FUNcube-1)",
},
```

## Example: Adding AO-73 to the database

### Before: Manual method

```bash
# Look up AO-73 on AMSAT status page
# Find: NORAD 39444, 145.960 MHz FM down, 435.150 MHz FM up

# Track by NORAD (must specify frequencies every time)
./satellite.py --norad 39444 --dl 145.960e6 --ul 435.150e6 --gps --track
```

### After: Using --fetch-frequencies

```bash
# 1. Generate code
./satellite.py --fetch-frequencies --generate-db > new_transponders.txt

# 2. Open satellite.py, find the TRANSPONDERS dict (around line 114)
vim satellite.py

# 3. Paste the AO-73 entry from new_transponders.txt:
TRANSPONDERS = {
    "AO-91": { ... },
    "AO-92": { ... },
    ...
    "AO-73": {  # ← NEW ENTRY
        "norad": 39444, "tle_group": "amateur",
        "dl": 145960000, "ul": 435150000,
        "dl_mode": "FM", "ul_mode": "FM", "invert": False,
        "note": "AO-73 (FUNcube-1)",
    },
}

# 4. Save and test
./satellite.py --sat AO-73 --gps  # Now works with --sat!
```

## Verifying frequencies

**CRITICAL:** SatNOGS data may be stale. Always verify frequencies before use:

1. [AMSAT Status Page](https://www.amsat.org/status/)
2. [SatNOGS Dashboard](https://dashboard.satnogs.org/) (check recent observations)
3. [n2yo.com](https://www.n2yo.com) (links to official frequency docs)

## Handling special cases

### Case 1: Satellite with multiple transponders

Some satellites (e.g., AO-7) have multiple transponders on different bands.

```bash
# Fetch frequencies
./satellite.py --fetch-frequencies

# Output shows:
#   AO-7: 145.975 MHz USB (Mode B)
#   AO-7: 29.502 MHz USB (Mode T)
```

**Solution:** Manually add separate entries:
```python
"AO-7-B": {
    "norad": 7530,
    "dl": 145975000, "ul": 432150000,
    "dl_mode": "USB", "ul_mode": "USB", "invert": True,
    "note": "AO-7 Mode B (linear, inverted)",
},
"AO-7-T": {
    "norad": 7530,
    "dl": 29502000, "ul": 145850000,
    "dl_mode": "USB", "ul_mode": "USB", "invert": True,
    "note": "AO-7 Mode T (linear, inverted)",
},
```

### Case 2: Inverted linear transponder

Linear transponders with inverted passbands (lower uplink → higher downlink)
require `"invert": True`.

**How to detect:**
- AMSAT docs explicitly state "inverted" or "Mode B/J/L"
- USB downlink + LSB uplink (or vice versa) is a strong hint
- If in doubt, ask on AMSAT-BB mailing list

**Example:**
```python
"FO-29": {
    "norad": 24278,
    "dl": 435850000, "ul": 145950000,
    "dl_mode": "USB", "ul_mode": "LSB", "invert": True,  # ← Note invert=True
    "note": "FujiOSCAR-29 linear transponder (inverted passband)",
},
```

### Case 3: CTCSS tones required

Some FM satellites require CTCSS tones on the uplink. **The script does not set
these automatically** — you must configure them on the radio manually before the pass.

Add a note to the database entry:
```python
"AO-91": {
    ...
    "note": "Fox-1B FM. UL: 67.0 Hz CTCSS required.",
},
"SO-50": {
    ...
    "note": "SaudiSat-1C FM. UL: arm with 74.4 Hz CTCSS (5 s), then 67.0 Hz.",
},
```

### Case 4: Intermittent or conditional operation

Some satellites have operational caveats:
- ISS crossband repeater: only active during special operations
- AO-7: battery-less, active only in sunlight
- Some satellites: transmitter schedule (only on during certain passes)

Add these to the notes:
```python
"ISS": {
    ...
    "note": "ISS crossband repeater. Active during special operations only.",
},
"AO-7": {
    ...
    "note": "Mode B linear. Battery-less; active only in sunlight.",
},
```

## Troubleshooting

### "No transmitters found for NORAD XXXXX"

**Cause:** Satellite is in the AMSAT TLE file but has no transmitter data in SatNOGS.

**Solutions:**
1. Check [SatNOGS DB](https://db.satnogs.org/satellites/) manually
2. Check AMSAT status page for official frequencies
3. Satellite may be inactive or decommissioned

### Frequencies in SatNOGS don't match AMSAT docs

**Cause:** SatNOGS is community-maintained; data may be out of date.

**Solution:** Trust AMSAT docs over SatNOGS. Manually edit the generated code
to match official frequencies.

### Mode is wrong (says FM but it's actually USB)

**Cause:** SatNOGS mode field may be incorrect or ambiguous.

**Solution:** Verify mode from AMSAT docs. Linear transponders are almost always
USB or CW. FM repeaters are FM.

### Multiple downlinks shown for one satellite

**Cause:** Satellite has multiple transmitters (beacon + repeater, or multiple bands).

**Solution:** The script picks the first one. Check SatNOGS or AMSAT docs to
determine which is the voice repeater vs. telemetry beacon, and edit manually.

### "alive": false — should I still add it?

**Cause:** SatNOGS hasn't heard this transmitter recently. May be:
- Satellite in eclipse (solar-powered transmitter off)
- Transmitter on a schedule (not always active)
- Satellite dead or decommissioned

**Solution:** Check [SatNOGS observations](https://network.satnogs.org/) for
recent activity. If last heard within a week, probably still active. If months
old, verify on AMSAT-BB mailing list before adding.

## Rate limiting and API etiquette

The script fetches data for ~50 satellites sequentially with a 200ms delay
between requests. Total time: ~10-20 seconds.

**Do NOT:**
- Run `--fetch-frequencies` in a cron job or tight loop
- Remove or reduce the 200ms sleep
- Fetch data more than once per hour

**Do:**
- Cache the output (`> frequencies.txt`) and refer to it
- Only re-run when you need updated data (e.g., after a new satellite launch)

SatNOGS is a volunteer-run service. Be respectful of their API.

## Contributing back to rf-bench

If you add satellites to your local `TRANSPONDERS` dict and verify they work,
**please submit a pull request** to add them to the upstream repository!

Requirements for inclusion:
1. Frequencies verified against AMSAT-NA status page (within last 30 days)
2. Mode (FM/USB/LSB/CW) confirmed
3. `invert` flag correct for linear transponders
4. Special notes added (CTCSS, operational caveats, etc.)
5. Tested on at least one pass with `--track --dry-run`

Pull requests welcome at: https://github.com/jfrancis42/rf-bench

## See also

- [AMSAT Satellite Status](https://www.amsat.org/status/)
- [SatNOGS DB](https://db.satnogs.org/satellites/)
- [SatNOGS Network](https://network.satnogs.org/) (live observations)
- [AMSAT-BB Mailing List](https://www.amsat.org/mailman/listinfo/amsat-bb)
- [n2yo.com](https://www.n2yo.com) (satellite tracking and info)
