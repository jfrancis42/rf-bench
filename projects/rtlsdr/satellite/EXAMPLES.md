# Satellite Monitor — Usage Examples

## Example 1: Monitor AO-91 FM downlink (simplest)

AO-91 (Fox-1B) is an FM voice repeater on 145.960 MHz. No Doppler tracking needed
for FM — the receiver's AFC handles it.

```bash
python satellite_monitor.py --sat AO-91 --gps --waterfall-only
```

**What you see:**
- Real-time waterfall at 145.960 MHz, 50 kHz wide
- FM signals appear as bright vertical bands when stations transmit
- Waterfall scrolls down continuously until you press Ctrl-C

**Hardware:** RTL-SDR + any VHF antenna (dipole, handheld, Arrow beam)

---

## Example 2: Monitor FO-29 linear transponder with Doppler

FO-29 is a 50 kHz USB linear transponder at 435.850 MHz. Doppler at 70cm is
±10 kHz peak — tracking keeps signals centered in the waterfall.

```bash
python satellite_monitor.py --sat FO-29 --gps --doppler --bw 200e3 --waterfall-only
```

**What you see:**
- 200 kHz waterfall centered on 435.850 MHz
- CW and SSB signals appear as narrow traces
- As Doppler correction runs, signals stay horizontally stable
- At AOS/LOS (max Doppler), without correction signals would drift across ~10 kHz

**Hardware:** RTL-SDR + 70cm antenna + LNA (optional but recommended)

---

## Example 3: Record a pass for offline analysis

Record the full FO-29 downlink during a pass, save to SigMF format.

```bash
# Start recording at pass AOS
python satellite_monitor.py --sat FO-29 --gps --doppler --bw 200e3 --record fo29_$(date +%Y%m%d_%H%M)
```

**What happens:**
- Waterfall displays in real-time
- IQ samples written to `fo29_20260602_1234.sigmf-data`
- Metadata written to `fo29_20260602_1234.sigmf-meta` (includes TLE, location, timestamp)
- Press Ctrl-C at LOS to stop

**After the pass:**
```bash
# Open in inspectrum
inspectrum fo29_20260602_1234.sigmf-data

# Or GNU Radio
gnuradio-companion
# File Source → file=fo29_...sigmf-data, type=complex, rate=200000
```

**Typical file size:** 200 kHz × 10 minutes = ~1.4 GB (complex float32)

---

## Example 4: Custom satellite by frequency + NORAD

Monitor the ISS APRS downlink (145.825 MHz) using explicit frequency and NORAD
number for Doppler tracking.

```bash
python satellite_monitor.py --freq 145.825e6 --norad 25544 --gps --doppler --bw 50e3 --waterfall-only
```

**Use this pattern for any satellite not in the built-in database.**

Find NORAD catalog numbers at:
- [CelesTrak](https://celestrak.org/NORAD/elements/)
- [n2yo.com](https://www.n2yo.com)
- [AMSAT Status](https://www.amsat.org/status/)

---

## Example 5: Parallel operation with IC-9700 Doppler tracker

**Scenario:** You're operating through FO-29 with an IC-9700. You want the radio
to handle TX/RX Doppler, and you want a wideband waterfall of the downlink to see
other stations.

**Terminal 1 — Start rigctld:**
```bash
rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &
```

**Terminal 2 — Start IC-9700 Doppler tracker:**
```bash
cd ../../../projects/radio/satellite/
python satellite.py --sat FO-29 --gps --track &
```

**Terminal 3 — Start RTL-SDR waterfall monitor:**
```bash
python satellite_monitor.py --sat FO-29 --gps --doppler --bw 200e3 --waterfall-only
```

**Operation:**
- IC-9700: Tuned to 145.950 LSB (TX) and 435.850 USB (RX), with Doppler correction
- RTL-SDR: Waterfall shows 200 kHz around 435.850 MHz, Doppler corrected
- You transmit on the IC-9700; you see your own downlink signal in the RTL-SDR waterfall
- Other stations' signals also appear in the waterfall
- Adjust your TX frequency to move your signal to a clear spot in the passband

---

## Example 6: No GPS — use explicit coordinates

If you don't have a GPS receiver, specify your ground station location manually.

```bash
# Denver, Colorado: 39.7392°N, 104.9903°W, 1609m altitude
python satellite_monitor.py --sat AO-91 --lat 39.7392 --lon -104.9903 --alt 1609 --doppler --waterfall-only
```

---

## Example 7: Wideband capture of multiple FM satellites

Monitor a 200 kHz span covering both AO-91 (145.960) and AO-92 (145.880).

```bash
# Center between the two
python satellite_monitor.py --freq 145.92e6 --bw 200e3 --gps --waterfall-only
```

**What you see:**
- AO-91 at +40 kHz offset (145.960 - 145.920 = +0.040 MHz)
- AO-92 at −40 kHz offset (145.880 - 145.920 = −0.040 MHz)
- If both satellites are above the horizon, you see both simultaneously

This only works when both satellites are in range. Use n2yo.com to check passes.

---

## Example 8: Monitor with LNA bias tee enabled

If you have an LNA that needs DC power via the coax (bias tee):

```bash
python satellite_monitor.py --sat FO-29 --gps --doppler --bias-tee --waterfall-only
```

**Hardware note:** RTL-SDR Blog v4 has a built-in bias tee (5V, 180 mA max).
Enable with `--bias-tee` flag. The script disables it automatically on exit.

---

## Example 9: Lower CPU usage for slow machines

Default FFT size (2048) and update rate (0.1s = 10 Hz) can be CPU-intensive.

**For a slower machine:**
```bash
python satellite_monitor.py --sat AO-91 --gps --fft-size 1024 --update 0.2 --waterfall-only
```

- `--fft-size 1024` — half the FFT bins, lower frequency resolution
- `--update 0.2` — update every 200 ms (5 Hz) instead of 100 ms (10 Hz)

**Result:** ~50% reduction in CPU usage; slightly lower waterfall time resolution.

---

## Example 10: List all built-in satellites

```bash
python satellite_monitor.py --list-sats
```

**Output:**
```
Built-in Satellites:
Name       NORAD    Downlink (MHz)   Mode   BW (kHz)   Note
----------------------------------------------------------------------------------
AO-91      43017    145.960          FM     30         Fox-1B downlink
AO-92      43137    145.880          FM     30         Fox-1D downlink
SO-50      27607    436.795          FM     30         SaudiSat-1C downlink
ISS        25544    145.800          FM     30         ISS crossband repeater downlink
FO-29      24278    435.850          USB    50         FujiOscar-29 linear transponder
AO-7       7530     145.975          USB    50         AMSAT-OSCAR 7 Mode B downlink
```

---

## Example 11: Record + display (full operation)

Record the pass while displaying the waterfall. After the pass, replay the recording
in inspectrum to decode signals you missed.

```bash
python satellite_monitor.py --sat FO-29 --gps --doppler --bw 200e3 --record fo29_pass
```

**Press Ctrl-C at LOS to stop.** The waterfall window will close, and the script
will write the SigMF metadata file.

**Post-pass analysis:**
```bash
inspectrum fo29_pass.sigmf-data
# OR
sdrpp fo29_pass.sigmf-data
```

---

## Example 12: Monitor a satellite not in the built-in database

**Scenario:** You want to monitor XW-2A (NORAD 40903) downlink at 145.660 MHz.

```bash
# Fetch NORAD catalog number from celestrak.org or n2yo.com
python satellite_monitor.py --freq 145.660e6 --norad 40903 --gps --doppler --bw 50e3 --waterfall-only
```

---

## Troubleshooting

### "RTL-SDR error: Device busy"
Another process is using the RTL-SDR. Find and kill it:
```bash
lsof | grep rtl
kill <PID>
```

### Waterfall shows only noise
- Check antenna connection
- Verify satellite is above the horizon: run `../../../projects/radio/satellite/satellite.py --sat XYZ --gps` to list pass times
- Increase gain: `--gain 40` instead of `--gain auto`
- Enable LNA if available: `--bias-tee`

### "No TLE found for NORAD XXXXX"
The NORAD number may be wrong, or the satellite is not in AMSAT/SatNOGS databases.
Verify at [n2yo.com](https://www.n2yo.com) or [CelesTrak](https://celestrak.org).

### Doppler correction is wrong
- Verify ground station location: `--gps` or `--lat/--lon/--alt`
- TLE may be stale (weeks old). Delete `~/.cache/rf-bench/tle/nasabare.txt` to force refresh.
- Verify system clock is correct (TLE propagation is time-sensitive)

### Recording file is huge
- 2.4 MS/s × 10 min × complex float32 = ~11 GB
- Use narrower bandwidth: `--bw 200e3` → ~1.4 GB
- Or post-process to complex int8 (4× smaller) using GNU Radio

### matplotlib window doesn't appear
Set backend environment variable:
```bash
export MPLBACKEND=TkAgg
python satellite_monitor.py --sat AO-91 --gps --waterfall-only
```

Try `Qt5Agg` or `GTK3Agg` if `TkAgg` doesn't work.

---

## See also

- [README.md](README.md) — Full documentation
- [projects/radio/satellite/README.md](../../../projects/radio/satellite/README.md) — IC-9700 Doppler tracker
- [AMSAT Satellite Status](https://www.amsat.org/status/) — Current frequencies and modes
- [SatNOGS Network](https://network.satnogs.org) — Live satellite passes worldwide
