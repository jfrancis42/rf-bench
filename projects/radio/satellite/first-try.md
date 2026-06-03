# Ham Radio Satellites — Easiest to Monitor (IC-9700, Moderate Antennas, No Tracking)

## Top Pick: ISS APRS (145.825 MHz)

The clear winner with this setup:

- Transmits at ~25W from a strong omni antenna — by far the strongest ham satellite signal
- Just park the IC-9700 on 145.825 MHz FM — no Doppler correction matters much at that power level with a fixed antenna
- Passes 4–6 times a day visible from most US locations
- You'll hear the AX.25 packet bursts during any pass above ~10° elevation
- The IC-9700 can feed audio to Direwolf/APRS software directly, so you can decode callsigns of stations being digipeated

## Second Easiest: RS-44

- Linear transponder: 70cm downlink (435.610–435.640 MHz SSB/CW), 2m uplink
- Strong enough that a fixed 2m/70cm yagi or even a decent vertical will copy it
- You can listen to SSB contacts without making any yourself

## FM Birds (SO-50, AO-91, etc.)

Work but have ~±10 kHz Doppler on the 70cm downlink that you'll need to chase manually for clean audio — not a showstopper, just more hands-on.

## Practical Next Step

Start with ISS APRS:
1. Check `heavens-above.com` for pass times
2. Point a 2m vertical at roughly the horizon in the pass direction
3. Open Direwolf on your laptop
4. Decode packets on the first good overhead pass

Once that's working, the IC-9700's satellite mode with two VFOs and Doppler correction (using Gpredict + CAT control) opens up everything else.



./satellite.py --sat ISS --track --dry-run --lat 39.35534 --lon -104.67297
