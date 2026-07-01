#!/usr/bin/env python3
"""
modulate.py — IQ Modulator (Educational)

Converts real audio (WAV/MP3/OGG file or live microphone) into baseband
IQ (In-phase / Quadrature) samples using AM, FM, USB, or LSB modulation.

OUTPUT FORMAT:
    Raw interleaved complex64 (float32 I, float32 Q pairs).
    Each sample is 8 bytes. At 8000 samples/second, one second = 64000 bytes.
    Load in Python with: np.fromfile("output.iq", dtype=np.complex64)

WHAT IS IQ?
    A real signal (like audio from a microphone) has both positive and
    negative frequency content — they're mirror images of each other.
    An IQ (complex) signal can represent ONLY positive frequencies, or
    ONLY negative frequencies, or an asymmetric spectrum. This is how
    radios work internally: the signal is split into I (in-phase) and
    Q (quadrature, 90° shifted) components, which together form a
    complex-valued signal that can represent any modulation.

    Think of I and Q as the X and Y coordinates of a phasor spinning
    on the complex plane. AM changes the radius. FM changes the spin
    rate. SSB removes half the spectrum entirely.

USAGE:
    # Modulate a WAV file as Upper Sideband, write to .iq file:
    python modulate.py --mode usb --input voice.wav

    # Modulate live microphone as FM, stream to stdout for piping:
    python modulate.py --mode fm --mic --stdout

    # Pipe modulator directly into demodulator for live listen-through:
    python modulate.py --mode usb --mic --stdout | python demodulate.py --mode usb --stdin --speaker
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from math import gcd
from pathlib import Path

import numpy as np
from scipy.signal import firwin, lfilter, lfilter_zi, resample_poly


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  CONSTANTS                                                                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Internal processing is done at 48 kHz — this is the standard soundcard rate,
# and it divides evenly into our 8 kHz output (48000 / 8000 = 6).
INTERNAL_RATE = 48000

# Output IQ sample rate. At 8 kHz, the maximum representable frequency is
# 4 kHz (Nyquist theorem). This is plenty for voice (300-3000 Hz).
DEFAULT_IQ_RATE = 8000

# Block size at the IQ output rate. 512 samples = 64 ms at 8 kHz.
# This is 4096 bytes (one Linux memory page), which makes pipe I/O efficient.
DEFAULT_BLOCK_SIZE = 512

# Default voice bandpass filter edges (Hz). Standard communications audio:
# 300 Hz removes rumble and hum; 3000 Hz removes hiss and keeps bandwidth
# narrow enough to fit in our 4 kHz Nyquist.
FILTER_LOW_DEFAULT = 300
FILTER_HIGH_DEFAULT = 3000

# Number of FIR filter taps. More taps = sharper filter edges, but more
# processing delay. 255 is a good balance for educational clarity — the
# filter is sharp enough to see the effect, but not so many taps that
# the group delay becomes confusing.
FILTER_TAPS = 255


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  AUDIO INPUT                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def load_audio_file(path: str) -> tuple[np.ndarray, int]:
    """Load an audio file (WAV, MP3, OGG, FLAC) and return mono float32 samples.

    Uses the 'soundfile' library, which delegates to libsndfile for decoding.
    Stereo files are mixed down to mono by averaging the channels.

    Returns:
        audio: numpy array of float32 samples, normalized to [-1.0, 1.0]
        sample_rate: the file's native sample rate in Hz
    """
    import soundfile as sf

    # soundfile.read() returns (data, samplerate).
    # 'dtype' forces float32 output regardless of the file's internal format.
    # 'always_2d=True' ensures stereo files come back as (N, 2) not (N,).
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)

    # Mix stereo (or multi-channel) down to mono.
    # For stereo: mono = (left + right) / 2
    # For mono files: this is a no-op (averages one column with itself).
    audio = audio.mean(axis=1)

    # Normalize so the loudest sample is exactly 1.0 (or -1.0).
    # This ensures consistent modulation depth regardless of recording level.
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak

    return audio, sample_rate


def resample_to_internal(audio: np.ndarray, source_rate: int) -> np.ndarray:
    """Resample audio to the internal processing rate (48 kHz).

    Uses polyphase resampling (resample_poly), which:
    1. Upsamples by inserting zeros
    2. Applies an anti-aliasing FIR filter
    3. Downsamples by discarding samples

    The ratio must be expressed as integers (up/down). For 44100→48000,
    that's 160/147 (since 48000/44100 = 160/147 when reduced by GCD=300).
    """
    if source_rate == INTERNAL_RATE:
        return audio  # Already at 48 kHz, nothing to do

    # Find the simplest integer ratio for the resampling.
    # GCD(48000, 44100) = 300, so 48000/44100 = 160/147.
    g = gcd(INTERNAL_RATE, source_rate)
    up = INTERNAL_RATE // g    # upsample factor
    down = source_rate // g    # downsample factor

    return resample_poly(audio, up, down).astype(np.float32)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  AUDIO PROCESSING (Filter + Compression)                                    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def design_bandpass(low_hz: float, high_hz: float,
                    sample_rate: int = INTERNAL_RATE) -> np.ndarray:
    """Design a FIR bandpass filter using the window method.

    A bandpass filter passes frequencies between 'low_hz' and 'high_hz'
    and rejects everything else. For voice communications, this is
    typically 300-3000 Hz — removing low-frequency rumble and high-
    frequency hiss while preserving speech intelligibility.

    The 'firwin' function uses the window method:
    1. Start with an ideal (sinc) filter impulse response
    2. Multiply by a window function (default: Hamming) to reduce ripple
    3. Result: a linear-phase FIR filter with smooth passband

    'pass_zero=False' means: the filter does NOT pass DC (0 Hz).
    This is what makes it bandpass rather than lowpass.
    """
    taps = firwin(
        FILTER_TAPS,            # Number of coefficients (filter length)
        [low_hz, high_hz],      # Passband edges in Hz
        pass_zero=False,        # Bandpass (reject DC)
        fs=sample_rate          # Sample rate (so we can specify edges in Hz)
    )
    return taps


def compress(audio: np.ndarray, drive: float = 1.5) -> np.ndarray:
    """Soft-clip compression using hyperbolic tangent (tanh).

    In radio, compression is used to increase average power without
    clipping. Speech has a high peak-to-average ratio (~12 dB) — the
    loudest syllables are much louder than the average. Compression
    "squishes" the peaks, allowing you to turn up the overall level.

    The tanh function is a smooth S-curve that approaches ±1 asymptotically:
    - For small inputs (|x| < 0.5): nearly linear (no effect)
    - For large inputs: smoothly saturates toward ±1 (compression)

    The 'drive' parameter controls how hard we push into the curve:
    - drive=1.0: very mild compression (almost linear)
    - drive=2.0: moderate (sounds like FM radio)
    - drive=4.0: heavy (sounds like AM broadcast radio)

    The normalization (dividing by tanh(drive)) ensures that a full-scale
    input still produces a full-scale output, regardless of drive setting.
    """
    if drive <= 1.0:
        return audio  # No compression
    return np.tanh(audio * drive) / np.tanh(drive)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  MODULATION ALGORITHMS                                                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# Each modulation function takes real audio samples and returns complex IQ
# samples. The complex output represents a baseband signal — the carrier
# frequency is implicitly 0 Hz. In a real radio, this baseband IQ would be
# mixed up to the transmit frequency by a hardware mixer.
#

def modulate_am(audio: np.ndarray, mod_index: float = 0.8) -> np.ndarray:
    """Amplitude Modulation (Double-Sideband Full Carrier).

    AM is the simplest modulation: vary the amplitude of a carrier wave
    proportional to the audio signal. The carrier is always present
    (even during silence), which wastes power but allows simple envelope
    detection in the receiver.

    The IQ representation at baseband:
        I(t) = 1 + m * audio(t)    (carrier + modulated signal)
        Q(t) = 0                    (no quadrature component)

    Where 'm' is the modulation index (0 to 1):
        m=0:   carrier only (no audio)
        m=0.5: 50% modulation (safe, no distortion)
        m=1.0: 100% modulation (maximum before clipping)
        m>1.0: overmodulation (distortion, don't do this)

    The "1 +" adds the carrier. Without it, you'd have DSB-SC
    (suppressed carrier), which requires a more complex receiver.
    """
    # The carrier is the "1.0" — it's always there.
    # The audio multiplied by mod_index rides on top of it.
    # Result is purely real (Q=0) because AM doesn't use the quadrature axis.
    iq = (1.0 + mod_index * audio).astype(np.complex64)
    return iq


def modulate_fm(audio: np.ndarray, deviation_hz: float = 2500,
                sample_rate: int = INTERNAL_RATE,
                phase_state: float = 0.0) -> tuple[np.ndarray, float]:
    """Frequency Modulation (Narrowband FM).

    FM encodes audio in the instantaneous frequency of the carrier.
    When the audio is positive, the frequency goes up; when negative,
    the frequency goes down. The amplitude stays constant (constant
    envelope), which is why FM is resistant to amplitude noise.

    The math:
        instantaneous_frequency(t) = deviation * audio(t)
        phase(t) = integral of frequency = cumulative sum of frequency
        IQ(t) = exp(j * phase(t)) = cos(phase) + j*sin(phase)

    'deviation_hz' is the maximum frequency swing. At 2500 Hz deviation
    with full-scale audio (±1.0), the instantaneous frequency swings
    ±2500 Hz around the carrier. This matches amateur radio NBFM.

    'sensitivity' converts audio amplitude to radians-per-sample:
        sensitivity = 2π * deviation / sample_rate

    The exp(j*phase) produces a unit-magnitude complex signal that
    traces a circle on the IQ plane — the radius is always 1, but
    the speed of rotation (frequency) varies with the audio.

    Returns the IQ samples AND the final phase value (needed for
    streaming to maintain phase continuity between blocks).
    """
    # Convert deviation to radians per sample per unit of audio amplitude.
    # When audio=1.0, frequency = deviation_hz, so:
    #   phase_change_per_sample = 2*pi * deviation_hz / sample_rate
    sensitivity = 2 * np.pi * deviation_hz / sample_rate

    # Instantaneous phase = integral of instantaneous frequency.
    # np.cumsum does numerical integration (rectangular rule).
    # We add phase_state to maintain continuity from the previous block.
    phase = phase_state + np.cumsum(audio * sensitivity)

    # Save the final phase for the next block (streaming continuity).
    # Modulo 2π prevents the float from growing without bound over time.
    final_phase = phase[-1] % (2 * np.pi) if len(phase) > 0 else phase_state

    # Convert phase to IQ: exp(j*θ) = cos(θ) + j*sin(θ)
    # This traces a unit circle on the complex plane.
    iq = np.exp(1j * phase).astype(np.complex64)

    return iq, final_phase


def modulate_usb(audio: np.ndarray) -> np.ndarray:
    """Upper Sideband modulation (USB).

    SSB (Single Sideband) transmits only ONE sideband of an AM signal.
    AM has two sidebands — upper and lower — that are mirror images.
    They carry identical information, so transmitting both is wasteful.
    SSB cuts the bandwidth in half and eliminates the carrier entirely.

    USB keeps the upper sideband (positive frequencies).
    LSB keeps the lower sideband (negative frequencies).

    The mathematical trick: the "analytic signal."
    A real signal x(t) has symmetric spectrum: X(f) = X(-f)*.
    The analytic signal keeps only the positive frequencies:
        analytic(t) = x(t) + j * hilbert(x(t))

    scipy.signal.hilbert() computes the analytic signal:
    1. FFT the input
    2. Zero out all negative frequency bins
    3. Double the positive frequency bins
    4. IFFT back to time domain
    Result: a complex signal whose spectrum exists only at f > 0.

    This IS the USB signal. The real part is the original audio;
    the imaginary part is the Hilbert transform (90° phase shift of
    every frequency component).
    """
    from scipy.signal import hilbert

    # hilbert() returns the full analytic signal (complex-valued).
    # Real part = original audio, Imag part = Hilbert transform.
    analytic = hilbert(audio)
    return analytic.astype(np.complex64)


def modulate_lsb(audio: np.ndarray) -> np.ndarray:
    """Lower Sideband modulation (LSB).

    Same as USB, but we keep the LOWER sideband (negative frequencies)
    instead of the upper. The trick: conjugating a complex signal flips
    its spectrum. Positive frequencies become negative and vice versa.

    So: analytic signal (positive-only) → conjugate → negative-only = LSB.

    Convention in amateur radio:
    - Below 10 MHz: use LSB (historical reasons from mechanical filters)
    - Above 10 MHz: use USB
    - VHF/UHF: always USB
    """
    from scipy.signal import hilbert

    analytic = hilbert(audio)
    # Conjugate flips the spectrum: what was at +f is now at -f.
    return np.conj(analytic).astype(np.complex64)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STREAMING SSB (FIR Hilbert filter for block processing)                    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class StreamingSSBModulator:
    """Block-based SSB modulator using an FIR Hilbert filter.

    The scipy.signal.hilbert() function works on the entire signal at once
    (it uses a full-length FFT). For streaming (processing one block at a
    time), we need an FIR approximation of the Hilbert transform.

    An FIR Hilbert filter shifts every frequency by 90° — the same thing
    as the Hilbert transform, but implemented as a causal FIR filter that
    can process samples block-by-block with state carried between blocks.

    The filter is designed with scipy.signal.remez (Parks-McClellan optimal
    equiripple design) using type='hilbert'.

    For USB: IQ = delayed_audio + j * hilbert_filtered_audio
    For LSB: IQ = delayed_audio - j * hilbert_filtered_audio
    (which is equivalent to conjugate)
    """

    def __init__(self, mode: str = "usb", sample_rate: int = INTERNAL_RATE):
        # Design the Hilbert FIR filter.
        # Must be odd length (even-length Hilbert filters have issues).
        self.n_taps = 95

        # The ideal Hilbert transform impulse response is:
        #   h[n] = 2/(π*n) for odd n, 0 for even n
        # We window it with a Hamming window to control sidelobes.
        # This is more numerically stable than remez() which can produce
        # divergent taps in some scipy versions (>=1.18).
        n = self.n_taps
        k = np.arange(n) - (n - 1) / 2.0
        h = np.zeros(n)
        for i in range(n):
            if k[i] == 0:
                h[i] = 0.0  # center tap is always zero
            elif int(round(k[i])) % 2 != 0:  # odd offsets only
                h[i] = 2.0 / (np.pi * k[i])
        h *= np.hamming(n)  # window to reduce Gibbs ripple
        self.hilbert_taps = h

        # The Hilbert filter introduces a group delay of (n_taps-1)/2 samples.
        # We must delay the I (real) channel by the same amount so that I and Q
        # are time-aligned. We do this with a simple delay buffer.
        self.delay = (self.n_taps - 1) // 2  # 63 samples

        # Filter state for lfilter (carries the "tail" between blocks).
        # Use a plain zero array rather than lfilter_zi — the Hilbert filter
        # has zero DC gain, so lfilter_zi's step-response initialization
        # produces numerical garbage. A zero-initialized state means a brief
        # transient at startup (n_taps/2 samples) but stable operation.
        self.hilbert_zi = np.zeros(self.n_taps - 1)

        # Delay buffer for the I channel (FIFO of 'delay' samples)
        self.delay_buffer = np.zeros(self.delay, dtype=np.float32)

        self.mode = mode  # "usb" or "lsb"

    def process(self, audio_block: np.ndarray) -> np.ndarray:
        """Process one block of audio, return IQ samples.

        The Q channel comes from the Hilbert FIR filter.
        The I channel is the original audio delayed to match the filter's
        group delay (so I and Q are time-aligned).
        """
        # Apply Hilbert FIR filter to get the quadrature (Q) component.
        # lfilter with zi carries state between blocks seamlessly.
        q_channel, self.hilbert_zi = lfilter(
            self.hilbert_taps, 1.0, audio_block, zi=self.hilbert_zi
        )

        # Delay the I channel to compensate for the filter's group delay.
        # Concatenate the delay buffer with the new audio, then split:
        #   - first 'delay' samples are from the previous block (the buffer)
        #   - the new buffer is the last 'delay' samples of current audio
        delayed = np.concatenate([self.delay_buffer, audio_block])
        i_channel = delayed[:len(audio_block)]
        self.delay_buffer = delayed[len(audio_block):len(audio_block) + self.delay]

        # Combine I and Q into complex IQ.
        if self.mode == "usb":
            iq = (i_channel + 1j * q_channel).astype(np.complex64)
        else:  # lsb
            # Negate Q to flip the spectrum (equivalent to conjugation)
            iq = (i_channel - 1j * q_channel).astype(np.complex64)

        return iq


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  FILE-BASED PROCESSING (complete audio at once)                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def _open_audio_source(path: str):
    """Open an audio file for streaming, returning (generator, sample_rate, duration_s).

    Tries libsndfile first (WAV, FLAC, OGG, AIFF). Falls back to ffmpeg for
    container formats (MKV, MP4, M4A, WebM) or codecs libsndfile can't handle
    (AAC, MP3 in some builds). The generator yields mono float32 blocks.

    ffmpeg decodes to raw PCM and pipes it, so memory usage is constant
    regardless of file size — even an 8-hour audiobook uses only ~400 KB.
    """
    import subprocess
    import soundfile as sf

    # Formats that libsndfile can decode but produce noisy stderr warnings
    # (libmpg123 errors on malformed frames, etc.). Use ffmpeg for these.
    noisy_extensions = {".mp3", ".mp2", ".mp1"}
    ext = Path(path).suffix.lower()

    # Try libsndfile first for formats it handles cleanly
    if ext not in noisy_extensions:
        try:
            audio_file = sf.SoundFile(path)
            source_rate = audio_file.samplerate
            duration = audio_file.frames / source_rate
            block_size = source_rate  # 1 second per block

            def sf_generator():
                try:
                    while True:
                        block = audio_file.read(block_size, dtype="float32", always_2d=True)
                        if len(block) == 0:
                            break
                        yield block.mean(axis=1)  # mix to mono
                finally:
                    audio_file.close()

            return sf_generator(), source_rate, duration
        except Exception:
            pass

    # Fall back to ffmpeg (handles MKV, MP4, M4A, AAC, MP3, etc.)
    # Probe the file first to get duration and sample rate
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-select_streams", "a:0", path],
        capture_output=True, text=True
    )
    if probe.returncode != 0:
        raise RuntimeError(f"Cannot open audio file: {path}")

    import json as json_mod
    info = json_mod.loads(probe.stdout)
    streams = info.get("streams", [])
    if not streams:
        raise RuntimeError(f"No audio stream found in: {path}")

    stream_info = streams[0]
    source_rate = int(stream_info.get("sample_rate", 44100))
    duration_str = stream_info.get("duration")
    if duration_str:
        duration = float(duration_str)
    else:
        # Fallback: probe container duration
        probe2 = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True
        )
        fmt = json_mod.loads(probe2.stdout).get("format", {})
        duration = float(fmt.get("duration", 0))

    # Decode to raw PCM via pipe — mono, float32 LE, native sample rate
    block_size = source_rate  # 1 second per block
    bytes_per_block = block_size * 4  # float32 = 4 bytes per sample

    def ffmpeg_generator():
        proc = subprocess.Popen(
            ["ffmpeg", "-v", "quiet", "-i", path,
             "-vn",                    # discard video
             "-ac", "1",               # mono
             "-ar", str(source_rate),  # native rate
             "-f", "f32le",            # raw float32 little-endian
             "-"],                     # pipe to stdout
            stdout=subprocess.PIPE
        )
        try:
            while True:
                raw = proc.stdout.read(bytes_per_block)
                if not raw:
                    break
                block = np.frombuffer(raw, dtype=np.float32)
                yield block
        finally:
            proc.stdout.close()
            proc.wait()

    return ffmpeg_generator(), source_rate, duration


def process_file(args) -> None:
    """Process an audio file in streaming chunks — constant memory regardless of file size.

    Rather than loading the entire file into RAM (which can exhaust memory on
    multi-hour audiobooks), this reads the file in blocks, processes each block
    through the filter/compress/modulate chain, and immediately writes the
    output. Memory usage is bounded by the block size (~400 KB), not file size.

    Supports any format ffmpeg can decode: WAV, MP3, FLAC, OGG, MKV, MP4, M4A, etc.
    """
    # --- Open the audio file for streaming read ---
    print(f"Loading: {args.input}", file=sys.stderr)
    audio_source, source_rate, duration = _open_audio_source(args.input)
    print(f"  {duration:.1f}s, {source_rate} Hz", file=sys.stderr)

    # --- Set up processing chain (stateful, carries between blocks) ---

    # Resampling ratio
    resample_needed = (source_rate != INTERNAL_RATE)
    if resample_needed:
        print(f"  Resampling {source_rate} → {INTERNAL_RATE} Hz", file=sys.stderr)
        g = gcd(INTERNAL_RATE, source_rate)
        up = INTERNAL_RATE // g
        down = source_rate // g

    # Bandpass filter state
    bp_taps = None
    bp_zi = None
    if not args.no_filter:
        print(f"  Bandpass filter: {args.filter_low}-{args.filter_high} Hz",
              file=sys.stderr)
        bp_taps = design_bandpass(args.filter_low, args.filter_high)
        bp_zi = lfilter_zi(bp_taps, 1.0) * 0

    # Compression
    if args.compress > 1.0:
        print(f"  Compression: drive={args.compress:.1f}", file=sys.stderr)

    # Modulation state
    print(f"  Modulating: {args.mode.upper()}", file=sys.stderr)
    fm_phase = 0.0
    ssb_mod = None
    if args.mode in ("usb", "lsb"):
        ssb_mod = StreamingSSBModulator(mode=args.mode)

    # Decimation
    decimation = INTERNAL_RATE // args.rate

    # --- Output setup ---
    output_file = None
    if not args.stdout:
        output_path = args.output
        if output_path is None:
            stem = Path(args.input).stem
            output_path = f"{stem}_{args.mode}.iq"
        output_file = open(output_path, "wb")

    # --- Graceful shutdown ---
    stop = [False]
    total_iq_samples = 0

    def sigint_handler(sig, frame):
        stop[0] = True
    signal.signal(signal.SIGINT, sigint_handler)

    # --- Process blocks ---
    try:
        for audio_block in audio_source:
            if stop[0]:
                break

            # Resample to internal rate (48 kHz)
            if resample_needed:
                audio_block = resample_poly(audio_block, up, down).astype(np.float32)

            # Bandpass filter (stateful — carries filter tails between blocks)
            if bp_taps is not None:
                audio_block, bp_zi = lfilter(bp_taps, 1.0, audio_block, zi=bp_zi)
                audio_block = audio_block.astype(np.float32)

            # Normalize block (keeps levels consistent for modulation)
            peak = np.max(np.abs(audio_block))
            if peak > 0:
                audio_block = audio_block / peak

            # Compression
            if args.compress > 1.0:
                audio_block = compress(audio_block, args.compress)

            # Modulate
            if args.mode == "am":
                iq_block = modulate_am(audio_block, args.mod_index)
            elif args.mode == "fm":
                iq_block, fm_phase = modulate_fm(
                    audio_block, args.deviation, INTERNAL_RATE, fm_phase
                )
            elif args.mode in ("usb", "lsb"):
                iq_block = ssb_mod.process(audio_block)

            # Decimate to output IQ rate
            if decimation > 1:
                iq_block = resample_poly(iq_block, 1, decimation).astype(np.complex64)

            # Write output
            total_iq_samples += len(iq_block)
            raw = iq_block.tobytes()

            if args.stdout:
                sys.stdout.buffer.write(raw)
                sys.stdout.buffer.flush()
            elif output_file:
                output_file.write(raw)

    except KeyboardInterrupt:
        pass
    finally:
        if output_file:
            output_file.close()

    # --- Summary ---
    elapsed = total_iq_samples / args.rate if args.rate > 0 else 0

    if args.stdout:
        print(f"  Done. {total_iq_samples} IQ samples ({elapsed:.1f}s)",
              file=sys.stderr)
    elif output_file:
        # Write companion JSON metadata
        meta = {
            "sample_rate": args.rate,
            "dtype": "complex64",
            "modulation": args.mode,
            "source_file": str(args.input),
            "source_rate": source_rate,
            "filter_low_hz": args.filter_low if not args.no_filter else None,
            "filter_high_hz": args.filter_high if not args.no_filter else None,
            "compression_drive": args.compress,
            "duration_s": round(elapsed, 3),
            "samples": total_iq_samples,
            "created": datetime.now(timezone.utc).isoformat(),
        }
        if args.mode == "am":
            meta["mod_index"] = args.mod_index
        elif args.mode == "fm":
            meta["deviation_hz"] = args.deviation

        json_path = Path(output_path).with_suffix(".json")
        with open(json_path, "w") as f:
            json.dump(meta, f, indent=2)

        file_size = Path(output_path).stat().st_size
        print(f"\nOutput: {output_path}", file=sys.stderr)
        print(f"  {total_iq_samples} samples, {elapsed:.1f}s, "
              f"{file_size} bytes", file=sys.stderr)
        print(f"  Metadata: {json_path}", file=sys.stderr)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STREAMING (microphone → real-time processing → stdout or file)             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def process_stream(args) -> None:
    """Stream from microphone: capture audio blocks, modulate, output."""
    import sounddevice as sd

    # --- Set up processing chain ---
    # Filter state (carries between blocks for seamless filtering)
    bp_taps = None
    bp_zi = None
    if not args.no_filter:
        bp_taps = design_bandpass(args.filter_low, args.filter_high)
        bp_zi = lfilter_zi(bp_taps, 1.0) * 0

    # FM needs phase continuity between blocks
    fm_phase = 0.0

    # SSB needs the streaming FIR Hilbert modulator
    ssb_mod = None
    if args.mode in ("usb", "lsb"):
        ssb_mod = StreamingSSBModulator(mode=args.mode)

    # Decimation ratio
    decimation = INTERNAL_RATE // args.rate

    # Block size at internal rate: we want 'block_size' samples at the
    # output rate, so we need block_size * decimation at internal rate.
    internal_block = args.block_size * decimation  # e.g., 512 * 6 = 3072

    # --- Output setup ---
    output_file = None
    if not args.stdout and args.output:
        output_file = open(args.output, "wb")

    # --- Graceful shutdown ---
    stop = [False]
    total_samples = [0]

    def sigint_handler(sig, frame):
        stop[0] = True
    signal.signal(signal.SIGINT, sigint_handler)

    print(f"Streaming from microphone ({INTERNAL_RATE} Hz)", file=sys.stderr)
    print(f"  Mode: {args.mode.upper()}", file=sys.stderr)
    print(f"  Output rate: {args.rate} Hz IQ", file=sys.stderr)
    print(f"  Block size: {args.block_size} IQ samples ({args.block_size/args.rate*1000:.0f} ms)",
          file=sys.stderr)
    if not args.no_filter:
        print(f"  Filter: {args.filter_low}-{args.filter_high} Hz", file=sys.stderr)
    print("  Ctrl-C to stop.", file=sys.stderr)

    try:
        # Open microphone input stream.
        # blocksize = number of samples per callback invocation.
        # channels=1 for mono microphone input.
        with sd.InputStream(samplerate=INTERNAL_RATE, channels=1,
                            blocksize=internal_block,
                            dtype="float32") as stream:
            while not stop[0]:
                # Read one block from microphone.
                # 'frames' is the actual number of samples read.
                audio_block, overflowed = stream.read(internal_block)
                if overflowed:
                    print("  [overflow]", file=sys.stderr, end="")

                # Flatten from (N, 1) to (N,) — mono
                audio_block = audio_block[:, 0]

                # --- Bandpass filter ---
                if bp_taps is not None:
                    audio_block, bp_zi = lfilter(
                        bp_taps, 1.0, audio_block, zi=bp_zi
                    )
                    audio_block = audio_block.astype(np.float32)

                # --- Compression ---
                if args.compress > 1.0:
                    audio_block = compress(audio_block, args.compress)

                # --- Modulate ---
                if args.mode == "am":
                    iq_block = modulate_am(audio_block, args.mod_index)
                elif args.mode == "fm":
                    iq_block, fm_phase = modulate_fm(
                        audio_block, args.deviation, INTERNAL_RATE, fm_phase
                    )
                elif args.mode in ("usb", "lsb"):
                    iq_block = ssb_mod.process(audio_block)

                # --- Decimate to output rate ---
                if decimation > 1:
                    iq_block = resample_poly(iq_block, 1, decimation).astype(np.complex64)

                # --- Output ---
                total_samples[0] += len(iq_block)
                raw = iq_block.tobytes()

                if args.stdout:
                    sys.stdout.buffer.write(raw)
                    sys.stdout.buffer.flush()
                elif output_file:
                    output_file.write(raw)

    except KeyboardInterrupt:
        pass
    finally:
        if output_file:
            output_file.close()
        elapsed = total_samples[0] / args.rate if args.rate > 0 else 0
        print(f"\n  Stopped. {total_samples[0]} samples ({elapsed:.1f}s)",
              file=sys.stderr)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  COMMAND-LINE INTERFACE                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def main() -> int:
    parser = argparse.ArgumentParser(
        description="IQ Modulator — convert audio to baseband IQ samples.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s --mode usb --input voice.wav
  %(prog)s --mode fm --mic --stdout | python demodulate.py --mode fm --stdin --speaker
  %(prog)s --mode am --input music.mp3 --mod-index 0.9 --compress 2.0
"""
    )

    # Mode (required)
    parser.add_argument("--mode", required=True, choices=["am", "fm", "usb", "lsb"],
                        help="Modulation type: am, fm, usb (upper sideband), "
                             "lsb (lower sideband)")

    # Input source (one required)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", type=str,
                            help="Input audio file (WAV, MP3, OGG, FLAC)")
    input_group.add_argument("--mic", action="store_true",
                            help="Use default microphone (48 kHz)")

    # Output destination
    parser.add_argument("--output", type=str, default=None,
                        help="Output .iq file path (default: <input_stem>_<mode>.iq)")
    parser.add_argument("--stdout", action="store_true",
                        help="Write raw complex64 to stdout (for piping)")

    # Processing options
    parser.add_argument("--rate", type=int, default=DEFAULT_IQ_RATE,
                        help=f"Output IQ sample rate in Hz (default: {DEFAULT_IQ_RATE})")
    parser.add_argument("--deviation", type=float, default=2500,
                        help="FM deviation in Hz (default: 2500, FM mode only)")
    parser.add_argument("--mod-index", type=float, default=0.8,
                        help="AM modulation index 0.0-1.0 (default: 0.8, AM only)")
    parser.add_argument("--compress", type=float, default=1.5,
                        help="Compressor drive (1.0=off, 2.0=moderate, 4.0=heavy; "
                             "default: 1.5)")
    parser.add_argument("--no-filter", action="store_true",
                        help="Skip input bandpass filter")
    parser.add_argument("--filter-low", type=float, default=FILTER_LOW_DEFAULT,
                        help=f"Bandpass lower edge in Hz (default: {FILTER_LOW_DEFAULT})")
    parser.add_argument("--filter-high", type=float, default=FILTER_HIGH_DEFAULT,
                        help=f"Bandpass upper edge in Hz (default: {FILTER_HIGH_DEFAULT})")
    parser.add_argument("--block-size", type=int, default=DEFAULT_BLOCK_SIZE,
                        help=f"Output block size in IQ samples (default: {DEFAULT_BLOCK_SIZE})")

    args = parser.parse_args()

    # Validate
    if args.rate <= 0 or INTERNAL_RATE % args.rate != 0:
        print(f"Error: --rate must divide evenly into {INTERNAL_RATE} "
              f"(e.g., 8000, 16000, 24000, 48000)", file=sys.stderr)
        return 1

    # Route to file or streaming mode
    if args.mic:
        process_stream(args)
    else:
        process_file(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
