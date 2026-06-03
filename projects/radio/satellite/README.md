# satellite — Pass Planner and Doppler Tracker

Predicts upcoming passes for amateur satellites and, during a pass, applies
real-time Doppler correction to an IC-9700 (or IC-7300/FT-891) via Hamlib rigctld.

## How it works

TLE data (orbital parameters) is fetched from AMSAT (`nasabare.txt`) for the
amateur satellite group; individual satellites are looked up by NORAD number via
the SatNOGS API.  All data is cached in `~/.cache/rf-bench/tle/` and refreshed
every 6 hours.

Pass times and az/el are computed locally with `skyfield` (SGP4 propagator) — no
internet connection is needed once TLEs are cached.  Doppler corrections use the
radial range rate between the ground station and the satellite.

Ground station location comes from `gpsd` (--gps) or explicit coordinates.

**NEW:** The script now **automatically imports satellite frequencies** from the
SatNOGS database! After running `--refresh-frequencies` once, you can track 50+
satellites using `--sat NAME` without manually looking up frequencies. The frequency
cache is stored locally and refreshed weekly (or on demand).

## Quick start

```bash
# List next 5 passes for AO-91 over Denver
python satellite.py --sat AO-91 --lat 39.7392 --lon -104.9903 --alt 1609

# Same, using GPS for location
python satellite.py --sat AO-91 --gps

# Show available satellites (built-in + auto-imported from SatNOGS)
python satellite.py --list-sats

# Auto-import frequencies from SatNOGS (first-time setup, takes ~20 seconds)
python satellite.py --fetch-frequencies
# OR
python satellite.py --refresh-frequencies

# After auto-import, list all available satellites
python satellite.py --list-sats

# Show ALL satellites in AMSAT TLE file (50+ satellites, TLE only, no frequencies)
python satellite.py --list-all-tle

# Advanced: generate Python code to add satellites to built-in database
python satellite.py --fetch-frequencies --generate-db > new_transponders.txt

# Track next pass, dry run (no radio commands)
python satellite.py --sat AO-91 --gps --track --dry-run

# Full operation: configure IC-9700 and apply live Doppler correction
python satellite.py --sat AO-91 --gps --track

# Linear transponder (FO-29, inverted passband)
python satellite.py --sat FO-29 --gps --track \
    --dl 435.850e6 --dl-mode USB --ul 145.950e6 --ul-mode LSB --invert

# Custom satellite by NORAD number
python satellite.py --norad 43017 --gps --track \
    --dl 145.960e6 --ul 435.250e6 --dl-mode FM --ul-mode FM
```

## Options

### Satellite identification
| Flag | Description |
|------|-------------|
| `--sat NAME` | Name from built-in database (AO-91, AO-92, SO-50, ISS, FO-29, AO-7) |
| `--norad CATNUM` | NORAD catalog number (for any satellite not in built-in DB) |
| `--list-sats` | Print built-in + auto-imported satellites and exit |
| `--list-all-tle` | Download and list ALL satellites in AMSAT TLE file (50+) and exit |
| `--fetch-frequencies` | Fetch frequencies from SatNOGS, display table, and save to cache |
| `--generate-db` | Generate Python code for TRANSPONDERS dict (use with `--fetch-frequencies`) |

### Location
| Flag | Description |
|------|-------------|
| `--gps` | Use gpsd for ground station location |
| `--lat DEG` | Latitude in decimal degrees (+N) |
| `--lon DEG` | Longitude in decimal degrees (+E) |
| `--alt M` | Altitude in metres (default: 0) |

### Pass prediction
| Flag | Default | Description |
|------|---------|-------------|
| `--passes N` | 5 | Number of passes to list |
| `--hours H` | 24 | Look-ahead window |
| `--min-elev DEG` | 5 | Minimum elevation for a valid pass |

### Transponder frequencies (override built-in database)
| Flag | Description |
|------|-------------|
| `--dl HZ` | Downlink (RX) center frequency in Hz |
| `--ul HZ` | Uplink (TX) center frequency in Hz (omit for RX-only) |
| `--dl-mode MODE` | FM, USB, LSB, CW (default: FM) |
| `--ul-mode MODE` | FM, USB, LSB, CW (default: FM) |
| `--invert` | Linear transponder: passband is inverted |

### Radio control
| Flag | Default | Description |
|------|---------|-------------|
| `--track` | — | Wait for next pass and apply Doppler correction |
| `--pass-num N` | 1 | Which upcoming pass to track |
| `--radio MODEL` | ic9700 | ic9700, ic7300, or ft891 |
| `--rigctld-host HOST` | localhost | rigctld hostname |
| `--rigctld-port PORT` | 4532 | rigctld TCP port |
| `--dry-run` | — | Display without commanding radio |
| `--interval S` | 1.0 | Doppler update interval in seconds |

### TLE data
| Flag | Default | Description |
|------|---------|-------------|
| `--refresh-tle` | — | Force re-fetch TLE data |
| `--tle-max-age H` | 6 | Max cache age before re-fetching |
| `--refresh-frequencies` | — | Fetch frequencies from SatNOGS and rebuild cache (takes ~20s) |

## Built-in satellites

| Name | NORAD | Downlink | Uplink | Notes |
|------|-------|----------|--------|-------|
| AO-91 | 43017 | 145.960 FM | 435.250 FM | Fox-1B; UL needs 67.0 Hz CTCSS |
| AO-92 | 43137 | 145.880 FM | 435.350 FM | Fox-1D |
| SO-50 | 27607 | 436.795 FM | 145.850 FM | UL: arm 74.4 Hz CTCSS, then 67.0 Hz |
| ISS | 25544 | 145.800 FM | 144.490 FM | Crossband repeater; intermittent |
| FO-29 | 24278 | 435.850 USB | 145.950 LSB | Linear transponder, inverted |
| AO-7 | 7530 | 145.975 USB | 432.150 USB | Mode B linear; battery-less |

Frequencies are from AMSAT-NA documentation. Verify against current AMSAT news
before use — satellite configurations can change.

## Auto-importing satellite frequencies from SatNOGS

**NEW FEATURE:** The script can automatically fetch and cache transponder frequencies
for all amateur satellites from the SatNOGS database.

### First-time setup (takes ~20 seconds)

```bash
# Fetch frequencies from SatNOGS for all satellites in AMSAT TLE file
python satellite.py --fetch-frequencies
# OR
python satellite.py --refresh-frequencies
```

**Both flags do the same thing:** fetch from SatNOGS and save to cache. Use whichever you prefer.

This will:
1. Download the AMSAT TLE file (~50 satellites)
2. Query SatNOGS transmitters API for each satellite
3. Cache frequencies locally in `~/.cache/rf-bench/tle/frequencies.json`
4. Show progress as it fetches (rate-limited to respect SatNOGS API)

**Example output:**
```
Refreshing frequency cache for 53 satellites...
Refreshing frequency cache: 10/53
Refreshing frequency cache: 20/53
...
Refreshing frequency cache: 53/53   Done.
```

### After auto-import, list all satellites

```bash
python satellite.py --list-sats
```

**Example output:**
```
Satellite transponder database (59 total):

Built-in satellites (6):
Name             NORAD  Downlink (MHz)  Uplink (MHz)    DL     UL     Inv
───────────────  ──────  ──────────────  ──────────────  ─────  ─────  ───
AO-7                7530   145.975 MHz     432.150 MHz   USB    USB    yes
  Mode B linear. Battery-less; active only in sunlight.
AO-91              43017   145.960 MHz     435.250 MHz   FM     FM     no
  Fox-1B FM. UL: 67.0 Hz CTCSS required.
...

Auto-imported from SatNOGS (53):
Name             NORAD  Downlink (MHz)  Uplink (MHz)    Mode
───────────────  ──────  ──────────────  ──────────────  ─────
AO-73             39444   145.960 MHz     435.150 MHz   FM
XW-2F             40903   145.875 MHz     435.205 MHz   FM
AO-95             43798   145.970 MHz     435.310 MHz   FM
...

Auto-imported satellites use SatNOGS data. Verify frequencies before use.
Cache age: 2 hours
Run with --refresh-frequencies to update from SatNOGS.
```

### Now use any satellite with --sat NAME

```bash
# Track AO-73 (was not in built-in database, now auto-imported)
python satellite.py --sat AO-73 --gps --track

# No need to specify --dl / --ul anymore!
```

### Cache expiration and refresh

- Frequency cache expires after **7 days** (frequencies change less often than TLEs)
- If cache is stale, the script uses only the built-in database
- Refresh manually: `python satellite.py --refresh-frequencies`
- Cache location: `~/.cache/rf-bench/tle/frequencies.json`

### Important caveats

⚠️ **SatNOGS data may be stale or incorrect** — the community-maintained database
is not always up-to-date. Always verify frequencies against the
[AMSAT status page](https://www.amsat.org/status/) before first use.

⚠️ **Linear transponders** — auto-imported satellites default to `invert: False`.
Manually verify inverted passbands for SSB/CW transponders.

⚠️ **CTCSS tones** — auto-imported satellites don't include CTCSS tone info.
Check AMSAT docs if uplink doesn't work.

⚠️ **Multiple transponders** — some satellites have multiple transmitters; the
script picks the first "alive" downlink it finds, which may not be the one you want.

### Disabling auto-import

If you prefer to only use the verified built-in database:
- Don't run `--refresh-frequencies`
- Delete `~/.cache/rf-bench/tle/frequencies.json` if it exists

The script will fall back to the 6 built-in satellites only.

## Using satellites not in the built-in database (manual method)

The built-in database (above) contains only 6 satellites with **verified transponder
configurations**. However, the AMSAT TLE file (`nasabare.txt`) contains **50+
active amateur satellites**.

### Step 1: List all available satellites

```bash
python satellite.py --list-all-tle
```

This downloads the AMSAT TLE file and displays all satellites with their NORAD
catalog numbers. Example output:

```
Found 53 satellites in AMSAT TLE file:

    NORAD  Name                                      In DB
  ────────  ────────────────────────────────────────  ──────
      7530  AO-7                                      yes
     20480  FO-20 (JAS-1)
     22825  AO-16
     24278  FO-29                                     yes
     25544  ISS                                       yes
     ...
     43017  AO-91 (Fox-1B)                            yes
     43137  AO-92 (Fox-1D)                            yes
     43798  AO-95 (Fox-1Cliff)
     43803  JY1SAT (JY1-Sat)
     ...
```

The "In DB" column shows which satellites are in the built-in transponder database.

### Step 2: Look up transponder frequencies

For satellites **not** in the built-in database, look up their frequencies at:
- [AMSAT Satellite Status](https://www.amsat.org/status/)
- [SatNOGS DB](https://db.satnogs.org/satellites/)
- [n2yo.com](https://www.n2yo.com)

### Step 3: Track the satellite using --norad

Example — track **AO-73** (NORAD 39444, not in built-in DB):

From AMSAT status page:
- Downlink: 145.960 MHz FM
- Uplink: 435.150 MHz FM

```bash
python satellite.py --norad 39444 --dl 145.960e6 --ul 435.150e6 --gps --track
```

The script will:
1. Fetch TLE data for NORAD 39444 from AMSAT or SatNOGS
2. Predict the next pass over your location
3. Apply Doppler correction to the IC-9700 during the pass

### Example: Track XW-2F (CAS-3F, NORAD 40903)

```bash
# List passes (no tracking)
python satellite.py --norad 40903 --dl 145.875e6 --ul 435.205e6 --gps

# Track next pass
python satellite.py --norad 40903 --dl 145.875e6 --ul 435.205e6 --gps --track
```

### Why only 6 satellites in the built-in database?

The built-in database is intentionally small — it contains only satellites where:
1. Transponder frequencies are **verified** against current AMSAT documentation
2. Mode (FM/USB/LSB) and passband inversion are **confirmed**
3. Special notes (CTCSS tones, operational caveats) are documented

**Adding more satellites to the built-in database is straightforward** — just edit
the `TRANSPONDERS` dict at the top of `satellite.py`. Pull requests welcome!

## Automatically fetching frequencies for all satellites

Instead of manually looking up frequencies, you can have the script **automatically
fetch transmitter data from SatNOGS** for all satellites in the AMSAT TLE file.

### Step 1: Fetch and display frequencies

```bash
python satellite.py --fetch-frequencies
```

This will:
1. Download the AMSAT TLE file (50+ satellites)
2. Query the SatNOGS transmitters API for each satellite
3. Display a table with downlink/uplink frequencies, modes, and status

**Example output:**
```
Found 53 satellites. Fetching transmitter data from SatNOGS...

    NORAD  Name                            Downlink (MHz)   Uplink (MHz)    Mode      Status
  ────────  ──────────────────────────────  ────────────────  ────────────────  ────────  ────────
      7530  AO-7                                  145.975           432.150  USB       alive
     24278  FO-29                                 435.850           145.950  USB       alive
     25544  ISS                                   145.800           144.490  FM        alive
     27607  SO-50                                 436.795           145.850  FM        alive
     39444  AO-73 (FUNcube-1)                     145.960           435.150  FM        alive
     40903  XW-2F (CAS-3F)                        145.875           435.205  FM        alive
     43017  AO-91 (Fox-1B)                        145.960           435.250  FM        alive
     43137  AO-92 (Fox-1D)                        145.880           435.350  FM        alive
     ...
```

**Note:** This queries the SatNOGS API ~50+ times, so it takes 10-20 seconds
(rate-limited to avoid hammering their server).

### Step 2: Generate Python code to add satellites to the database

```bash
python satellite.py --fetch-frequencies --generate-db > new_transponders.txt
```

This outputs **ready-to-paste Python code** for the `TRANSPONDERS` dict:

```python
# Generated TRANSPONDERS entries (paste into satellite.py):

TRANSPONDERS = {
    "AO-73": {
        "norad": 39444, "tle_group": "amateur",
        "dl": 145960000, "ul": 435150000,
        "dl_mode": "FM", "ul_mode": "FM", "invert": False,
        "note": "AO-73 (FUNcube-1)",
    },
    "XW-2F": {
        "norad": 40903, "tle_group": "amateur",
        "dl": 145875000, "ul": 435205000,
        "dl_mode": "FM", "ul_mode": "FM", "invert": False,
        "note": "XW-2F (CAS-3F)",
    },
    ...
}
```

### Step 3: Edit satellite.py and add the satellites you want

1. Open `new_transponders.txt` in a text editor
2. Copy the entries for satellites you want to add
3. Paste them into the `TRANSPONDERS` dict in `satellite.py` (around line 114)
4. Verify the frequencies against AMSAT status page (SatNOGS data may be stale)
5. Add any special notes (CTCSS tones, operational caveats, etc.)
6. Save the file

Now those satellites are available via `--sat NAME` without needing `--norad` and `--dl/--ul`!

### Limitations and caveats

**SatNOGS data quality:**
- SatNOGS is community-maintained — frequencies may be out of date
- "alive" status means the transmitter was recently heard by the SatNOGS network
- "dead" status may be temporary (satellite in eclipse, transmitter off, etc.)
- **Always verify frequencies against AMSAT status page before use**

**Mode detection:**
- SatNOGS stores mode as a string: "FM", "USB", "LSB", "CW", "FSK", etc.
- The script uses this directly, but you should verify for linear transponders
- For inverted linear transponders, manually set `"invert": True` after generating

**Multiple transmitters:**
- Many satellites have multiple transmitters (different bands, modes, beacons)
- The script picks the **first alive downlink** it finds
- You may need to manually select the correct transponder from the SatNOGS data

**Rate limiting:**
- The script adds a 200ms delay between API requests to avoid rate limits
- Fetching ~50 satellites takes ~10-20 seconds
- Don't run `--fetch-frequencies` in a tight loop

### Why not fetch frequencies automatically every time?

The built-in database contains **verified, stable transponder configurations** that
are known to work. Auto-fetching from SatNOGS would:
- Add startup latency (10+ seconds)
- Risk stale/incorrect data breaking tracking
- Require network access every time (not always available)
- Obscure special notes (CTCSS tones, operational caveats)

The current approach (small built-in DB + manual verification) ensures reliability
while still giving you easy access to the full satellite list when needed.

## CTCSS tones (AO-91, AO-92, SO-50)

These FM satellites require CTCSS tones on the uplink.  This script does **not**
set CTCSS automatically.  Configure the tone on the IC-9700 before the pass:

```
IC-9700: Menu → Tone → TSQL or TONE, set the required Hz
```

## rigctld setup for IC-9700

```bash
# USB connection
rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &

# LAN connection (Hamlib ≥ 4.3)
rigctld -m 3081 -r 192.168.1.10 &
```

## Doppler physics

Range rate is the radial component of the satellite's velocity relative to
the ground station (positive = moving away, negative = approaching).

- **Downlink (RX):** `f_rx = f_nominal × (1 − range_rate / c)`
  Approaching satellite → heard higher; receding → heard lower.
- **Uplink (TX):** `f_tx = f_nominal × (1 + range_rate / c)`
  Pre-corrects so the satellite hears us at the nominal frequency.

For a linear transponder with **inverted passband**, both corrections still
apply to their respective VFOs independently.

At max elevation the range rate is near zero (satellite moving perpendicular),
so Doppler is minimal at culmination and maximal at AOS/LOS.

Typical peak Doppler:
- 145 MHz: ±3.4 kHz at 7 km/s approach/recession
- 435 MHz: ±10 kHz at 7 km/s

## TLE data sources

- **AMSAT** (`amsat.org/tle/current/nasabare.txt`) — primary group source;
  authoritative for amateur satellites; updated daily.
- **SatNOGS** (`db.satnogs.org/api/tle/`) — per-NORAD fallback; used for
  satellites not in the AMSAT file (e.g. ISS by NORAD number).
- Cache: `~/.cache/rf-bench/tle/` — refreshed every 6 hours by default.

## Hardware requirements

- IC-9700 (or IC-7300/FT-891) connected via USB or LAN
- Hamlib `rigctld` running (see above)
- GPS receiver with `gpsd` running, or known coordinates
- `python -m pip install skyfield requests numpy`
