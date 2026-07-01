# vocoder-nature — Channel Vocoder with Ambient Sound

Classic channel vocoder that lets you speak through rain, wind, traffic,
or any ambient sound — or flip it so that nature "speaks" using your
voice as the texture.

## How it works

A channel vocoder splits audio into many frequency bands (16 by default).
For each band, it extracts the envelope (volume shape) of the modulator
and applies it to the carrier. The result has the timbre of the carrier
but the rhythmic/phonemic structure of the modulator.

- **Carrier = ambient, Modulator = your voice**: your words come out
  in the timbre of rain, traffic, wind, a river
- **Carrier = your voice, Modulator = ambient** (`--swap`): the
  environment's rhythmic patterns are imposed on your voice texture

## Usage

```bash
# Stereo input: Left = carrier (ambient mic), Right = modulator (close mic)
python vocoder_nature.py --input-device 2 --output-device 2

# Swap: nature speaks through you
python vocoder_nature.py --swap

# Use a pre-recorded WAV as carrier (mic input is modulator)
python vocoder_nature.py --carrier-file rain.wav

# More bands for finer frequency resolution
python vocoder_nature.py --bands 32

# Faster envelope tracking (more intelligible speech)
python vocoder_nature.py --attack-ms 2 --release-ms 10

# Wider frequency range
python vocoder_nature.py --freq-low 50 --freq-high 12000

# Test mode (pink noise + synthetic speech)
python vocoder_nature.py --test
```

## Flags

- `--bands N` — number of vocoder bands (default: 16)
- `--freq-low HZ` — lowest band (default: 80)
- `--freq-high HZ` — highest band (default: 8000)
- `--attack-ms MS` — envelope attack time (default: 5)
- `--release-ms MS` — envelope release time (default: 20)
- `--swap` — swap carrier and modulator roles
- `--carrier-file FILE` — use WAV file as carrier
- Standard audio device flags

## Input configuration

### Two microphones (best)
Use a stereo USB interface. Ambient mic (omni, pointed away) on
channel 1 = carrier. Close mic (cardioid, at mouth) on channel 2
= modulator.

### One microphone + file
Use `--carrier-file` with a pre-recorded ambient sound (rain, river,
traffic noise). Your mic input becomes the modulator.

### One microphone (experimental)
Mono input is used as both carrier and modulator — creates a
strange resonant effect (self-vocoding).

## Vocoder parameters

| Parameter | Effect |
|-----------|--------|
| More bands | Finer frequency resolution, more intelligible speech |
| Fewer bands | More "robotic", broader spectral smearing |
| Fast attack | Crisper consonants, more intelligible |
| Slow release | Smoother, more legato output |
| Wider freq range | More presence in HF, deeper bass |

## Live display

Shows a band-activity meter: filled blocks indicate bands where
the modulator has significant energy. You can see the spectral
shape of the modulator in real-time.

## Best carrier sounds

| Source | Character | Why it works |
|--------|-----------|-------------|
| Rain | Broadband, gentle | Energy everywhere, speech emerges from noise |
| River/stream | Rich, variable | Turbulence has all frequencies |
| Traffic | Dense, low-mid | Good for bass-heavy robotic speech |
| Wind | Airy, HF-heavy | Whispered quality |
| Crowd noise | Complex | Multiple voices create rich texture |
| Fire crackling | Impulsive + tonal | Rhythmic, warm |

## Requirements

- `numpy`, `scipy`
- `sounddevice`
- `soundfile` (for `--carrier-file`)
