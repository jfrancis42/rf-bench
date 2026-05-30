> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-audio-chain

**GitHub:** https://github.com/jfrancis42/rf-bench-audio-chain

IC-7300 transmit audio chain analyzer. The SDG1062X injects calibrated tones into the
IC-7300 microphone input; USB audio (via sounddevice) captures the processed TX audio.
Four measurement modes: frequency response, ALC compression curve, 1 kHz THD, and
DSP/IF filter shape in CW mode.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SDG1062X (10.1.1.55) | Function generator — audio tone injection |
| Icom IC-7300 | Radio under test — TX audio processing |
| Computer USB | IC-7300 USB audio — TX monitor capture |
| rigctld | Hamlib radio control daemon |

**Wiring:** SDG CH1 output to IC-7300 8-pin MIC jack (pin 1 = mic, pin 5 = GND).
Reduce SDG amplitude to 50-100 mVpp to avoid mic preamp saturation.

## Prerequisites

Start rigctld: rigctld -m 3073 -r /dev/ttyUSB0 -s 115200

List audio devices: python -c "import sounddevice; print(sounddevice.query_devices())"

## Usage

python audio_chain.py --test TEST --audio-device INDEX [options]

### Options

--sdg HOST (10.1.1.55): SDG1062X IP
--rig-host HOST (localhost): rigctld host
--rig-port N (4532): rigctld port
--test response|alc|thd|filter|all (response): Test to run
--freq-start HZ (100): Response sweep start
--freq-stop HZ (5000): Response sweep stop
--audio-device INDEX (system default): sounddevice input index
--plot FILE (timestamped): Output PNG

## Notes

sounddevice must be installed: pip install sounddevice --break-system-packages
