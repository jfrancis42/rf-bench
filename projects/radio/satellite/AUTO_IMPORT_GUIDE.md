# Automatic Frequency Import — Complete Guide

This document explains the new **automatic frequency import** feature that fetches
satellite transponder data from SatNOGS and makes it available via `--sat NAME`
without manual configuration.

## Overview

**Before:** Only 6 satellites in the built-in database. To track others, you had
to manually look up frequencies and use `--norad` + `--dl` + `--ul` every time.

**After:** Run `--refresh-frequencies` once. The script fetches data for 50+
satellites from SatNOGS, caches it locally, and merges it with the built-in
database. Now use `--sat NAME` for any satellite.

## Quick start

```bash
# 1. First-time setup (takes ~20 seconds)
./satellite.py --refresh-frequencies

# 2. List all available satellites (built-in + auto-imported)
./satellite.py --list-sats

# 3. Track any satellite by name
./satellite.py --sat AO-73 --gps --track
./satellite.py --sat XW-2F --gps --track
./satellite.py --sat AO-95 --gps --track
```

No more manual frequency lookups!

## How it works

### Step 1: Fetch AMSAT TLE file

Downloads `nasabare.txt` from AMSAT → ~50 satellites with NORAD numbers

### Step 2: Query SatNOGS transmitters API

For each NORAD number:
```
https://db.satnogs.org/api/transmitters/?format=json&satellite__norad_cat_id={norad}
```

Returns list of transmitters with frequencies, modes, status (alive/dead)

### Step 3: Select best transponder

- Downlink: first transmitter with `downlink_low` and `alive: true`
- Uplink: first transmitter with `uplink_low` and `alive: true`

### Step 4: Cache locally

Saves to `~/.cache/rf-bench/tle/frequencies.json`:
```json
{
  "39444": {
    "name": "AO-73 (FUNcube-1)",
    "dl": 145960000,
    "ul": 435150000,
    "dl_mode": "FM",
    "ul_mode": "FM"
  },
  ...
}
```

Cache expires after 7 days (configurable in script).

### Step 5: Merge at runtime

On every script run:
1. Load built-in `TRANSPONDERS` dict (6 satellites, verified configs)
2. Load frequency cache from disk (if exists and not stale)
3. Merge cached frequencies into `TRANSPONDERS` (without overriding built-ins)
4. All subsequent code sees the extended database

## Cache management

### Cache location
```
~/.cache/rf-bench/tle/frequencies.json
```

### Cache expiration
- Default: 7 days
- Configurable: `_FREQ_CACHE_MAX_AGE_H` in script (line 79)
- TLE cache: 6 hours (orbital data changes faster than frequencies)

### Force refresh
```bash
./satellite.py --refresh-frequencies
```

Deletes old cache and fetches fresh data from SatNOGS.

### Clear cache manually
```bash
rm ~/.cache/rf-bench/tle/frequencies.json
```

Script will fall back to built-in database only.

### Check cache age
```bash
./satellite.py --list-sats
```

Output shows:
```
Cache age: 2 hours
```

## Built-in vs. auto-imported satellites

### Built-in (6 satellites)

**Verified configurations:**
- Frequencies confirmed against AMSAT-NA status page
- Mode (FM/USB/LSB) and inversion verified
- CTCSS tones and operational caveats documented
- Tested with real passes

**List:**
- AO-7, AO-91, AO-92, SO-50, ISS, FO-29

### Auto-imported (50+ satellites)

**From SatNOGS community data:**
- Frequencies may be stale or incorrect
- Mode detection may be wrong
- No CTCSS tone information
- No operational caveats
- Inversion defaults to False (may be wrong for linear transponders)

**Always verify before first use!**

## Listing satellites

```bash
./satellite.py --list-sats
```

**Output format:**
```
Satellite transponder database (59 total):

Built-in satellites (6):
Name             NORAD  Downlink (MHz)  Uplink (MHz)    DL     UL     Inv
───────────────  ──────  ──────────────  ──────────────  ─────  ─────  ───
AO-91              43017   145.960 MHz     435.250 MHz   FM     FM     no
  Fox-1B FM. UL: 67.0 Hz CTCSS required.
...

Auto-imported from SatNOGS (53):
Name             NORAD  Downlink (MHz)  Uplink (MHz)    Mode
───────────────  ──────  ──────────────  ──────────────  ─────
AO-73             39444   145.960 MHz     435.150 MHz   FM
XW-2F             40903   145.875 MHz     435.205 MHz   FM
...

Auto-imported satellites use SatNOGS data. Verify frequencies before use.
Cache age: 2 hours
Run with --refresh-frequencies to update from SatNOGS.
```

## Example: Tracking AO-73

### Before auto-import

```bash
# Look up frequencies on AMSAT website
# Find: AO-73, NORAD 39444, 145.960 MHz FM down, 435.150 MHz FM up

# Track (must specify everything)
./satellite.py --norad 39444 --dl 145.960e6 --ul 435.150e6 --gps --track
```

### After auto-import

```bash
# First-time setup
./satellite.py --refresh-frequencies

# Track (frequencies loaded automatically)
./satellite.py --sat AO-73 --gps --track
```

Much simpler!

## Verifying frequencies before first use

**CRITICAL:** Always verify auto-imported frequencies before transmitting.

### Step 1: Check AMSAT status page

https://www.amsat.org/status/

Look for the satellite, confirm:
- Downlink frequency
- Uplink frequency
- Mode (FM/USB/LSB/CW)
- CTCSS tones (if FM)
- Operational status (active/intermittent/eclipse)

### Step 2: Check SatNOGS dashboard

https://dashboard.satnogs.org/

Search for satellite, look at recent observations:
- Has anyone heard it recently?
- Are the frequencies correct?
- Is the transmitter "alive"?

### Step 3: Test receive-only first

```bash
# List passes (no radio commands)
./satellite.py --sat AO-73 --gps

# Track next pass, dry run (no radio, just display)
./satellite.py --sat AO-73 --gps --track --dry-run
```

Listen on the downlink during a pass. If you hear nothing, frequencies may be wrong.

### Step 4: Transmit only after verification

Once you confirm the downlink is correct, attempt an uplink.

## Handling special cases

### Case 1: Linear transponder with inverted passband

Auto-imported satellites default to `invert: False`. If the transponder is inverted
(lower uplink → higher downlink), you'll need to override this:

**Option A: Use manual frequencies**
```bash
./satellite.py --sat FO-29 --gps --track --invert
```

**Option B: Edit the cache file**
```bash
vim ~/.cache/rf-bench/tle/frequencies.json
```

Find the satellite entry, change `"invert": false` to `"invert": true`, save.

**Option C: Add to built-in database**

See `FREQUENCY_FETCHING.md` for instructions.

### Case 2: CTCSS tones required

Auto-imported FM satellites don't include CTCSS tone info. If your uplink doesn't
activate the repeater, check AMSAT docs for the required tone and configure it
manually on the IC-9700 before the pass.

Example: AO-91 requires 67.0 Hz CTCSS on uplink.

### Case 3: Multiple transponders on one satellite

Some satellites have multiple transmitters (e.g., Mode B + Mode J, or beacon +
repeater). The auto-import picks the **first alive downlink**, which may not be
the one you want.

**Solution:** Use manual frequencies:
```bash
./satellite.py --norad 7530 --dl 145.975e6 --ul 432.150e6 --gps --track  # AO-7 Mode B
./satellite.py --norad 7530 --dl 29.502e6 --ul 145.850e6 --gps --track   # AO-7 Mode T
```

Or add separate entries to the built-in database (see `FREQUENCY_FETCHING.md`).

### Case 4: Intermittent operation

Some satellites operate on schedules or only in sunlight (AO-7, ISS). Auto-import
doesn't capture this. If you can't hear the satellite during a pass, check AMSAT-BB
mailing list for recent activity reports.

## Disabling auto-import

If you prefer to only use the verified built-in database:

```bash
# Remove cache
rm ~/.cache/rf-bench/tle/frequencies.json

# Don't run --refresh-frequencies
```

The script will use only the 6 built-in satellites.

## Rate limiting and API etiquette

SatNOGS is a volunteer-run service. Be respectful:

- ✅ Run `--refresh-frequencies` once per week (or when new satellite launches)
- ✅ Use the 200ms rate limit (built-in, don't remove it)
- ✅ Cache results locally (the script does this automatically)

- ❌ Don't run `--refresh-frequencies` in a cron job
- ❌ Don't reduce or remove the rate limit sleep
- ❌ Don't fetch more than once per hour

If the entire amateur satellite community hammered the SatNOGS API, it would go
down. One fetch per week per user is sustainable.

## Troubleshooting

### "No cached frequencies found"

**Cause:** You haven't run `--refresh-frequencies` yet, or cache expired.

**Solution:**
```bash
./satellite.py --refresh-frequencies
```

### Auto-imported satellite not working

**Cause:** SatNOGS data may be wrong or stale.

**Solution:**
1. Verify frequencies on AMSAT status page
2. Use manual method:
   ```bash
   ./satellite.py --norad <NORAD> --dl <freq> --ul <freq> --gps --track
   ```

### Refresh takes forever / times out

**Cause:** SatNOGS API may be slow or down.

**Solution:** The script has a 200ms rate limit between requests. For 50 satellites,
this takes ~10-20 seconds minimum. If it stalls, wait or press Ctrl-C and try later.

### Wrong mode (says FM but it's USB)

**Cause:** SatNOGS mode field may be incorrect.

**Solution:** Verify mode from AMSAT docs. Override with manual frequencies if needed.

## Technical implementation details

### Merge strategy

The script merges built-in and auto-imported at runtime:

1. Load built-in `TRANSPONDERS` dict (line 114)
2. Call `_build_extended_transponders()` (line 923)
3. Load frequency cache from disk
4. For each cached satellite:
   - If NORAD already in built-in database → skip (built-in wins)
   - Otherwise → add to extended database
5. Return extended dict
6. All subsequent code uses extended database

### Cache format

JSON file, mapping NORAD (as string) to config:

```json
{
  "39444": {
    "name": "AO-73 (FUNcube-1)",
    "dl": 145960000,
    "ul": 435150000,
    "dl_mode": "FM",
    "ul_mode": "FM"
  }
}
```

### Automatic refresh on first run

If cache doesn't exist and you specify `--refresh-frequencies`, the script fetches
automatically. Otherwise, it uses only the built-in database.

### Performance impact

Loading the cache adds ~10ms to startup time (JSON parse of ~50 satellites). This
is negligible compared to TLE fetch or satellite computation.

## Future enhancements

Possible improvements (not yet implemented):

- **Smart cache update:** Only fetch satellites that changed since last refresh
- **Partial cache:** Allow user to select specific satellites to cache
- **CTCSS detection:** Parse SatNOGS notes field for CTCSS tones
- **Inversion heuristics:** Auto-detect inverted transponders from mode combination
- **Multi-transponder support:** Present all transponders, let user choose
- **Automatic verification:** Cross-check SatNOGS data against AMSAT API

Contributions welcome!

## See also

- [README.md](README.md) — Main documentation
- [FREQUENCY_FETCHING.md](FREQUENCY_FETCHING.md) — Manual frequency fetching guide
- [AMSAT Status Page](https://www.amsat.org/status/)
- [SatNOGS DB](https://db.satnogs.org/satellites/)
- [SatNOGS Network](https://network.satnogs.org/) — Live observations
