# Quick Start — Auto-Import Frequencies

## What you saw vs. what you need

### What happened when you ran `--fetch-frequencies`

✅ Script fetched data from SatNOGS  
✅ Script displayed a table of frequencies  
✅ Script **now also saves** the data to cache  
❌ ~~Data was thrown away~~ (this was the old behavior — **fixed now!**)

### What to do now

**Option 1: Run it again (since the first run, the fix is now in place)**

```bash
./satellite.py --fetch-frequencies
```

This time it will save the cache at the end.

**Option 2: Check if cache already exists**

```bash
ls -lh ~/.cache/rf-bench/tle/frequencies.json
```

If the file exists and is recent, you're already good! Skip to step 3.

### Now use the satellites

```bash
# List all available satellites (built-in + auto-imported)
./satellite.py --list-sats

# Track any satellite by name
./satellite.py --sat AO-73 --gps --track
./satellite.py --sat XW-2F --gps --track
```

## Two ways to fetch frequencies

Both do the same thing now (fetch + save):

```bash
./satellite.py --fetch-frequencies      # Shows table, then saves
./satellite.py --refresh-frequencies    # Quieter, just saves
```

Use whichever you prefer. The difference is:
- `--fetch-frequencies` shows a pretty table of results
- `--refresh-frequencies` runs quietly in the background

## Cache location

```bash
~/.cache/rf-bench/tle/frequencies.json
```

To check cache age:
```bash
stat ~/.cache/rf-bench/tle/frequencies.json
```

To manually delete cache:
```bash
rm ~/.cache/rf-bench/tle/frequencies.json
```

## Still confused?

Just run this:

```bash
./satellite.py --fetch-frequencies
./satellite.py --list-sats
```

The first line fetches and saves. The second line shows everything.

If you see "Auto-imported from SatNOGS (N)" in the output, it worked!
