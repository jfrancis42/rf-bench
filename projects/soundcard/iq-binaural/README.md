# iq-binaural — IQ-to-Binaural Stereo Converter

Accepts stereo L=I, R=Q audio from a radio's IQ output and produces
binaural stereo headphone audio where signals at different frequency
offsets from the carrier are spatially distributed across the
soundstage.

## The idea

An I/Q signal represents a complex baseband: negative frequencies
are below the carrier, positive are above. A station 1 kHz below
your dial frequency appears at -1000 Hz in the IQ stream; one 2 kHz
above appears at +2000 Hz.

This converter maps that frequency offset to a spatial position:
negative offsets → left ear, positive → right ear, center → straight
ahead. The result: in a crowded band, each station occupies a
different spatial position. Your brain separates them via the
cocktail-party effect.

## Input sources

- IC-7300 / IC-9700 "I/Q output" mode (USB audio, stereo L=I R=Q)
- SoftRock / QRP Labs receiver (analog I/Q to stereo soundcard)
- SDRplay / Airspy via virtual audio cable
- RTL-SDR via `rtl_fm -E direct` piped to soundcard
- Any SDR that can route I/Q to a stereo audio output

## Usage

```bash
# Real-time: stereo IQ in → binaural headphones out
python iq_binaural.py --input-device 2 --output-device 4

# SSB passband (±3 kHz), linear panning
python iq_binaural.py --passband 3000 --pan-mode linear

# CW (narrower passband, log panning for center emphasis)
python iq_binaural.py --passband 1000 --pan-mode log

# Test mode with synthetic IQ
python iq_binaural.py --test --output binaural_iq.wav
```

## Flags

- `--passband HZ` — half-width of the passband (default 3000 Hz).
  Signals beyond ±passband are panned fully L or R.
- `--pan-mode {linear,log}` — frequency-to-position mapping:
  - `linear`: offset maps linearly to stereo position.
  - `log`: compresses near-zero offsets (center), expands edges.
    Better for CW where signals cluster near the BFO.
- `--itd-ms MS` — max interaural time delay (default 0.6 ms)
- `--ild-db DB` — max interaural level difference (default 10 dB)
- `--output WAV` — save binaural output (test mode)
- Standard audio flags. Input MUST be stereo (channels-in=2).

## Pan modes

### Linear

```
Frequency:    -3000 Hz -------- 0 Hz -------- +3000 Hz
Pan position:   Left --------- Center --------- Right
```

Simple, predictable. Good for SSB where the passband is uniform.

### Logarithmic

```
Frequency:    -3000 Hz -- -500 Hz -- 0 Hz -- +500 Hz -- +3000 Hz
Pan position:   Left --- slight L --- Center --- slight R --- Right
```

Concentrates the center of the passband in the middle. Signals
far from center get pushed to the edges. Better when you care
about one signal near the BFO and want off-frequency QRM pushed
away.

## Limitations

- Requires true I/Q stereo input (Left=I, Right=Q). If your
  radio provides only demodulated audio (not IQ), use binaural-cw
  or stereo-expander instead.
- Per-bin processing in the FFT domain. Processing latency is one
  block (~21 ms at 1024/48k). Not suitable for real-time
  break-in CW where latency matters.
- Full complex FFT (not rfft) since IQ is a complex signal with
  negative frequencies. Twice the FFT cost of real-signal tools.
- I/Q imbalance (amplitude or phase mismatch between channels) will
  create a mirror image. Correct in the radio or use a Gram-Schmidt
  pre-processor (not implemented here — future enhancement).
