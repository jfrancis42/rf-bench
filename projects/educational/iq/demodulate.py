#!/usr/bin/env python3
"""
demodulate.py — IQ Demodulator (Educational)

Converts baseband IQ (In-phase / Quadrature) samples back into audible
audio using AM, FM, USB, or LSB demodulation.

INPUT FORMAT:
    Raw interleaved complex64 (float32 I, float32 Q pairs).
    Load manually with: np.fromfile("input.iq", dtype=np.complex64)

WHAT HAPPENS DURING DEMODULATION:
    The modulator encoded audio information into a complex IQ signal.
    The demodulator reverses that encoding:

    - AM:  The audio is in the AMPLITUDE (envelope) of the IQ signal.
           Demod = take the magnitude: |I + jQ| = sqrt(I² + Q²)

    - FM:  The audio is in the FREQUENCY (rate of phase change).
           Demod = measure how fast the phase is rotating between samples.

    - USB: The audio IS the real part of the analytic signal.
           Demod = just take the real part: audio = I

    - LSB: The audio is the real part of the conjugated signal.
           Demod = conjugate then take real part (same as just taking I)

USAGE:
    # Demodulate an IQ file to WAV:
    python demodulate.py --mode usb --input voice_usb.iq --output voice_out.wav

    # Demodulate and play on speaker:
    python demodulate.py --mode fm --input signal.iq --speaker

    # Receive from pipe (streaming from modulator):
    python modulate.py --mode usb --mic --stdout | python demodulate.py --mode usb --stdin --speaker
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import firwin, lfilter, lfilter_zi, resample_poly


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  CONSTANTS                                                                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Audio output rate — standard for soundcards and WAV files.
OUTPUT_RATE = 48000

# Default IQ input rate (can be overridden by --rate or companion .json).
DEFAULT_IQ_RATE = 8000

# Block size at the IQ rate (512 samples = 4096 bytes = 64 ms).
DEFAULT_BLOCK_SIZE = 512

# Output lowpass filter: removes interpolation artifacts above the original
# audio bandwidth. Set slightly above 3 kHz to avoid cutting off speech.
OUTPUT_LPF_CUTOFF = 3500  # Hz


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  AGC (Automatic Gain Control)                                               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class AGC:
    """Automatic Gain Control — keeps audio at a consistent volume.

    Real radio signals vary enormously in strength. A station might be
    S9+20dB one moment (very strong) and S3 the next (weak) due to
    fading. Without AGC, you'd constantly be reaching for the volume knob.

    HOW IT WORKS:
    The AGC tracks the signal envelope (overall amplitude) and adjusts
    gain inversely: strong signals get reduced, weak signals get boosted.

    The key insight is ASYMMETRIC timing:
    - ATTACK (fast, 5ms): When signal suddenly gets LOUDER, reduce gain
      quickly to prevent painful blasting in the headphones.
    - DECAY (slow, 300ms): When signal gets QUIETER, increase gain slowly
      to avoid pumping artifacts (gain jumping up during brief pauses
      between words).

    This mimics how real radio AGC circuits work — they use a capacitor
    that charges fast (attack) and discharges slowly (decay).

    The per-sample loop below is intentionally NOT vectorized. It's
    written as a simple loop so you can trace exactly what happens at
    each sample. A numpy-vectorized version would be 50x faster but
    much harder to understand.
    """

    def __init__(self, sample_rate: int = OUTPUT_RATE,
                 attack_ms: float = 5.0, decay_ms: float = 300.0,
                 target: float = 0.3, max_gain: float = 50.0):
        """
        Args:
            sample_rate: Audio sample rate (Hz)
            attack_ms: How fast gain DECREASES when signal is too loud (ms)
            decay_ms: How fast gain INCREASES when signal is too quiet (ms)
            target: Desired output amplitude (0.0 to 1.0)
            max_gain: Maximum gain (prevents amplifying silence to full scale)
        """
        # Convert time constants from milliseconds to per-sample coefficients.
        # These are exponential smoothing coefficients: smaller = slower response.
        # The formula: coeff = 1 - exp(-1 / (time_constant_in_samples))
        self.attack = 1.0 - np.exp(-1.0 / (attack_ms * sample_rate / 1000))
        self.decay = 1.0 - np.exp(-1.0 / (decay_ms * sample_rate / 1000))
        self.target = target
        self.max_gain = max_gain

        # Current smoothed estimate of the signal envelope.
        # Start at a reasonable level to avoid initial gain spike.
        self.level = 0.1

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply AGC to a block of audio samples.

        For each sample:
        1. Measure instantaneous amplitude (absolute value)
        2. Update smoothed level estimate (fast attack / slow decay)
        3. Compute gain = target / level (louder signal → less gain)
        4. Apply gain to the sample
        """
        output = np.empty_like(audio)

        for i in range(len(audio)):
            # Instantaneous amplitude of this sample
            amplitude = abs(audio[i])

            # Update the smoothed level estimate.
            # If the signal is LOUDER than our estimate: attack (fast)
            # If the signal is QUIETER than our estimate: decay (slow)
            if amplitude > self.level:
                # Fast attack: quickly track the rising envelope
                self.level += self.attack * (amplitude - self.level)
            else:
                # Slow decay: gradually release when signal drops
                self.level += self.decay * (amplitude - self.level)

            # Compute gain: we want 'target' amplitude at the output,
            # and we're measuring 'level' at the input.
            # gain = target / level (inverse relationship)
            gain = self.target / (self.level + 1e-10)  # +epsilon prevents /0

            # Clamp gain to prevent wild amplification of silence
            if gain > self.max_gain:
                gain = self.max_gain

            # Apply gain
            output[i] = audio[i] * gain

        return output.astype(np.float32)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DEMODULATION ALGORITHMS                                                    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# Each demodulation function takes complex IQ samples and returns real audio.
# The demodulator must match the modulator: AM↔AM, FM↔FM, USB↔USB, LSB↔LSB.
#

def demodulate_am(iq: np.ndarray) -> np.ndarray:
    """AM Demodulation — Envelope Detection.

    The AM modulator encoded audio as amplitude variations:
        IQ(t) = (1 + m*audio(t)) + 0j

    To recover the audio, we take the magnitude (envelope):
        envelope(t) = |IQ(t)| = sqrt(I² + Q²)

    Then remove the DC offset (the "1" that represents the carrier):
        audio(t) = envelope(t) - mean(envelope)

    Finally normalize so the output fills [-1, 1].

    This is exactly how a crystal radio works — the diode rectifies
    the RF signal (takes the magnitude), and the headphones see only
    the slowly-varying envelope (the audio).

    np.abs() on a complex array computes the magnitude of each element:
        |a + jb| = sqrt(a² + b²)
    """
    # Take magnitude = envelope
    envelope = np.abs(iq)

    # Remove DC (the carrier component). In a real receiver, this would
    # be done by a coupling capacitor that blocks DC.
    audio = envelope - np.mean(envelope)

    # Normalize to [-1, 1]
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak

    return audio.astype(np.float32)


def demodulate_fm(iq: np.ndarray, deviation_hz: float = 2500,
                  sample_rate: int = DEFAULT_IQ_RATE) -> np.ndarray:
    """FM Demodulation — Conjugate-Multiply Discriminator.

    The FM modulator encoded audio as the instantaneous frequency:
        IQ(t) = exp(j * phase(t))    where d(phase)/dt = audio

    To recover audio, we need to measure how fast the phase is changing
    between adjacent samples. The elegant trick: multiply each sample by
    the conjugate of the previous sample.

    Math:
        IQ[n] * conj(IQ[n-1]) = exp(j*phase[n]) * exp(-j*phase[n-1])
                               = exp(j * (phase[n] - phase[n-1]))
                               = exp(j * Δphase)

    Then: angle(exp(j*Δphase)) = Δphase = instantaneous frequency!

    This is called a "conjugate-multiply discriminator" or "polar
    discriminator." It's the standard FM demod algorithm in SDR.

    Advantages over unwrap+diff:
    - No phase unwrapping state needed between blocks
    - Each output depends on only two adjacent inputs
    - Numerically stable (no accumulated errors)

    The output is scaled by the inverse of the sensitivity so that
    full deviation (±2500 Hz) maps to ±1.0 in the audio.
    """
    # Conjugate-multiply: IQ[n] * conj(IQ[n-1])
    # This gives us exp(j * delta_phase) for each sample pair.
    product = iq[1:] * np.conj(iq[:-1])

    # Extract the phase difference using np.angle (atan2).
    # Result is in radians, range [-π, +π].
    delta_phase = np.angle(product)

    # Scale to audio: divide by the maximum expected phase change.
    # At full deviation, delta_phase = 2π * deviation / sample_rate.
    sensitivity = 2 * np.pi * deviation_hz / sample_rate
    audio = delta_phase / sensitivity

    # The discriminator output is one sample shorter (we lose the first).
    # Prepend a zero to maintain the same length.
    audio = np.concatenate([[0.0], audio])

    return audio.astype(np.float32)


def demodulate_usb(iq: np.ndarray) -> np.ndarray:
    """USB Demodulation — Extract Real Part.

    The USB modulator created an analytic signal: only positive frequencies.
    The real part of an analytic signal IS the original audio signal.

    That's it. USB demod at baseband is just: audio = Re(IQ) = I channel.

    Why does this work? The analytic signal is:
        analytic(t) = audio(t) + j * hilbert(audio(t))

    Taking the real part gives back audio(t) directly.

    In a real receiver at RF, you'd first have to mix the signal down to
    baseband (multiply by exp(-j*2π*f_carrier*t)) before taking the real
    part. But since our IQ is already at baseband, the mixing step is
    implicitly done — the carrier frequency is 0 Hz.
    """
    return iq.real.astype(np.float32)


def demodulate_lsb(iq: np.ndarray) -> np.ndarray:
    """LSB Demodulation — Conjugate then Extract Real Part.

    The LSB modulator conjugated the analytic signal to flip the spectrum.
    To undo this, we conjugate again (flipping back), then take the real part.

    Mathematically:
        modulate:   iq = conj(analytic(audio))
        demodulate: audio = Re(conj(iq)) = Re(analytic(audio)) = audio ✓

    Since conjugation doesn't change the real part (Re(a+jb) = Re(a-jb) = a),
    LSB demod is actually identical to USB demod: just take iq.real.

    But conceptually, the signals are different! USB has positive frequencies,
    LSB has negative frequencies. The difference shows up if you look at the
    spectrum (FFT) of the IQ signal — they're mirror images.

    We conjugate here for conceptual clarity (undo what the modulator did),
    even though the .real extraction makes it numerically identical to USB demod.
    """
    return np.conj(iq).real.astype(np.float32)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  FILE-BASED PROCESSING (complete IQ file at once)                           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def process_file(args) -> None:
    """Process a complete IQ file: load, demodulate, interpolate, output."""

    # --- Try to load companion JSON for defaults ---
    iq_rate = args.rate
    json_path = Path(args.input).with_suffix(".json")
    if json_path.exists():
        with open(json_path) as f:
            meta = json.load(f)
        print(f"Metadata: {json_path}", file=sys.stderr)
        # Use metadata values as defaults (CLI args override)
        if args.rate == DEFAULT_IQ_RATE and "sample_rate" in meta:
            iq_rate = meta["sample_rate"]
        if "modulation" in meta:
            print(f"  Recorded mode: {meta['modulation'].upper()}", file=sys.stderr)
        if "duration_s" in meta:
            print(f"  Duration: {meta['duration_s']}s", file=sys.stderr)

    # --- Load IQ file ---
    print(f"Loading: {args.input}", file=sys.stderr)
    iq = np.fromfile(args.input, dtype=np.complex64)
    duration = len(iq) / iq_rate
    print(f"  {len(iq)} samples, {iq_rate} Hz, {duration:.1f}s", file=sys.stderr)

    # --- Demodulate ---
    print(f"  Demodulating: {args.mode.upper()}", file=sys.stderr)
    if args.mode == "am":
        audio = demodulate_am(iq)
    elif args.mode == "fm":
        audio = demodulate_fm(iq, args.deviation, iq_rate)
    elif args.mode == "usb":
        audio = demodulate_usb(iq)
    elif args.mode == "lsb":
        audio = demodulate_lsb(iq)

    # --- Interpolate to output rate (8 kHz → 48 kHz) ---
    # When you decimate a signal, you lose time resolution. Interpolation
    # reconstructs the "in-between" samples using a lowpass filter.
    # resample_poly(audio, 6, 1) upsamples by 6 with anti-imaging filter.
    interp_factor = OUTPUT_RATE // iq_rate
    if interp_factor > 1:
        audio = resample_poly(audio, interp_factor, 1).astype(np.float32)

    # --- AGC ---
    if args.agc:
        print("  AGC: enabled", file=sys.stderr)
        agc = AGC(sample_rate=OUTPUT_RATE)
        audio = agc.process(audio)

    # --- Output lowpass filter ---
    # After interpolation, there may be spectral images above our audio band.
    # This lowpass removes them, producing clean audio.
    lpf_taps = firwin(127, OUTPUT_LPF_CUTOFF, fs=OUTPUT_RATE)
    audio = lfilter(lpf_taps, 1.0, audio).astype(np.float32)

    # --- Clip to prevent any samples exceeding [-1, 1] ---
    audio = np.clip(audio, -1.0, 1.0)

    # --- Output ---
    if args.speaker:
        _play_audio(audio, OUTPUT_RATE)
    else:
        output_path = args.output
        if output_path is None:
            stem = Path(args.input).stem
            output_path = f"{stem}_demod.wav"

        import soundfile as sf
        sf.write(output_path, audio, OUTPUT_RATE, subtype="PCM_16")
        print(f"\nOutput: {output_path}", file=sys.stderr)
        print(f"  {len(audio)} samples, {OUTPUT_RATE} Hz, "
              f"{len(audio)/OUTPUT_RATE:.1f}s", file=sys.stderr)


def _play_audio(audio: np.ndarray, sample_rate: int) -> None:
    """Play audio through the default speaker (blocking)."""
    import sounddevice as sd
    print(f"  Playing on speaker ({sample_rate} Hz, {len(audio)/sample_rate:.1f}s)...",
          file=sys.stderr)
    sd.play(audio, sample_rate)
    sd.wait()  # Block until playback finishes


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STREAMING (stdin pipe → real-time demod → speaker or file)                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def process_stream(args) -> None:
    """Stream from stdin: read IQ blocks, demodulate, play or write."""
    import sounddevice as sd

    iq_rate = args.rate
    interp_factor = OUTPUT_RATE // iq_rate

    # --- AGC ---
    agc = AGC(sample_rate=OUTPUT_RATE) if args.agc else None

    # --- Output lowpass filter (with state for streaming) ---
    lpf_taps = firwin(127, OUTPUT_LPF_CUTOFF, fs=OUTPUT_RATE)
    lpf_zi = lfilter_zi(lpf_taps, 1.0) * 0

    # --- Output setup ---
    output_file = None
    output_stream = None

    if args.speaker:
        # Open a sounddevice output stream for real-time playback.
        # blocksize=0 means "accept whatever size we feed it."
        output_stream = sd.OutputStream(
            samplerate=OUTPUT_RATE, channels=1, dtype="float32"
        )
        output_stream.start()
    elif args.output:
        output_file = open(args.output, "wb")

    # --- Streaming state ---
    # FM demodulator needs the last sample from the previous block to
    # compute the phase difference at the block boundary.
    fm_last_sample = np.complex64(0)

    # Bytes per block: each complex64 sample is 8 bytes.
    bytes_per_block = args.block_size * 8  # 512 * 8 = 4096

    # Buffer for accumulating partial reads from the pipe.
    # Unix pipes can deliver fewer bytes than requested (short reads).
    read_buffer = b""

    # --- Graceful shutdown ---
    stop = [False]
    total_blocks = [0]

    def sigint_handler(sig, frame):
        stop[0] = True
    signal.signal(signal.SIGINT, sigint_handler)

    print(f"Streaming from stdin ({iq_rate} Hz IQ → {OUTPUT_RATE} Hz audio)",
          file=sys.stderr)
    print(f"  Mode: {args.mode.upper()}", file=sys.stderr)
    if args.speaker:
        print("  Output: speaker", file=sys.stderr)
    print("  Ctrl-C to stop.", file=sys.stderr)

    try:
        while not stop[0]:
            # --- Read one block from stdin ---
            # Pipes may deliver partial data, so we accumulate until
            # we have a complete block.
            while len(read_buffer) < bytes_per_block:
                chunk = sys.stdin.buffer.read(bytes_per_block - len(read_buffer))
                if not chunk:
                    # EOF — modulator closed the pipe
                    stop[0] = True
                    break
                read_buffer += chunk

            if stop[0] and len(read_buffer) < 8:
                break  # Not enough data for even one sample

            # Extract one block (or whatever we have left at EOF)
            block_bytes = read_buffer[:bytes_per_block]
            read_buffer = read_buffer[bytes_per_block:]

            # Convert raw bytes to complex64 numpy array
            iq_block = np.frombuffer(block_bytes, dtype=np.complex64)

            if len(iq_block) == 0:
                break

            # --- Demodulate ---
            if args.mode == "am":
                audio_block = demodulate_am(iq_block)
            elif args.mode == "fm":
                # For streaming FM, we need continuity at block boundaries.
                # Prepend the last sample from the previous block so the
                # conjugate-multiply discriminator can compute the first
                # phase difference of this block.
                iq_with_overlap = np.concatenate([[fm_last_sample], iq_block])
                product = iq_with_overlap[1:] * np.conj(iq_with_overlap[:-1])
                delta_phase = np.angle(product)
                sensitivity = 2 * np.pi * args.deviation / iq_rate
                audio_block = (delta_phase / sensitivity).astype(np.float32)
                fm_last_sample = iq_block[-1]
            elif args.mode == "usb":
                audio_block = demodulate_usb(iq_block)
            elif args.mode == "lsb":
                audio_block = demodulate_lsb(iq_block)

            # --- Interpolate to output rate ---
            if interp_factor > 1:
                audio_block = resample_poly(audio_block, interp_factor, 1).astype(np.float32)

            # --- AGC ---
            if agc is not None:
                audio_block = agc.process(audio_block)

            # --- Output lowpass ---
            audio_block, lpf_zi = lfilter(lpf_taps, 1.0, audio_block, zi=lpf_zi)
            audio_block = audio_block.astype(np.float32)

            # --- Clip ---
            audio_block = np.clip(audio_block, -1.0, 1.0)

            # --- Output ---
            total_blocks[0] += 1

            if output_stream is not None:
                # Play through speaker. Reshape to (N, 1) for mono output.
                output_stream.write(audio_block.reshape(-1, 1))
            elif output_file is not None:
                # Write raw float32 audio (not a proper WAV — use file mode for WAV)
                output_file.write(audio_block.tobytes())

    except KeyboardInterrupt:
        pass
    finally:
        if output_stream is not None:
            output_stream.stop()
            output_stream.close()
        if output_file is not None:
            output_file.close()
        total_samples = total_blocks[0] * args.block_size * interp_factor
        elapsed = total_samples / OUTPUT_RATE if OUTPUT_RATE > 0 else 0
        print(f"\n  Stopped. {total_blocks[0]} blocks ({elapsed:.1f}s)",
              file=sys.stderr)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  COMMAND-LINE INTERFACE                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def main() -> int:
    parser = argparse.ArgumentParser(
        description="IQ Demodulator — convert baseband IQ back to audio.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s --mode usb --input voice_usb.iq --output voice_out.wav
  %(prog)s --mode fm --input signal.iq --speaker
  python modulate.py --mode usb --mic --stdout | %(prog)s --mode usb --stdin --speaker
"""
    )

    # Mode (required)
    parser.add_argument("--mode", required=True, choices=["am", "fm", "usb", "lsb"],
                        help="Demodulation type (must match modulator)")

    # Input source (one required)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", type=str,
                            help="Input .iq file (raw complex64)")
    input_group.add_argument("--stdin", action="store_true",
                            help="Read raw complex64 from stdin (for piping)")

    # Output destination
    parser.add_argument("--output", type=str, default=None,
                        help="Output WAV file path (default: <input_stem>_demod.wav)")
    parser.add_argument("--speaker", action="store_true",
                        help="Play through default speaker")

    # Processing options
    parser.add_argument("--rate", type=int, default=DEFAULT_IQ_RATE,
                        help=f"Input IQ sample rate in Hz (default: {DEFAULT_IQ_RATE}, "
                             "or from companion .json)")
    parser.add_argument("--deviation", type=float, default=2500,
                        help="FM deviation in Hz (default: 2500, FM mode only)")
    parser.add_argument("--agc", action="store_true", default=True,
                        help="Enable AGC (default: enabled)")
    parser.add_argument("--no-agc", action="store_true",
                        help="Disable AGC")
    parser.add_argument("--block-size", type=int, default=DEFAULT_BLOCK_SIZE,
                        help=f"IQ samples per processing block (default: {DEFAULT_BLOCK_SIZE})")

    args = parser.parse_args()

    # Handle --no-agc flag
    if args.no_agc:
        args.agc = False

    # Validate
    if OUTPUT_RATE % args.rate != 0:
        print(f"Error: output rate ({OUTPUT_RATE}) must be divisible by "
              f"IQ rate ({args.rate})", file=sys.stderr)
        return 1

    # Route to file or streaming mode
    if args.stdin:
        process_stream(args)
    else:
        process_file(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
