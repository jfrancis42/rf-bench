#!/usr/bin/env python3
"""
play-usb-iq.py — audio file → USB (upper-sideband) IQ → default audio device.

Reads an audio file, modulates it to upper-sideband IQ, and plays the complex
IQ out of the default audio output device at an 8 kHz IQ rate. IQ is complex
(I + jQ) but a sound card carries real samples, so the standard soundcard-SDR
convention is used: a two-channel (stereo) stream with

    I  →  left channel
    Q  →  right channel

which is exactly what a soundcard-fed quadrature/QSE transmit mixer expects.

Usage:
    ./play-usb-iq.py voice.wav
    ./play-usb-iq.py voice.mp3 --device pipewire      # pick an output device
    ./play-usb-iq.py voice.wav --rate 8000            # IQ sample rate (default 8000)
    ./play-usb-iq.py --list-devices

Input formats: anything libsndfile reads (WAV/FLAC/OGG/…), plus WebM/MKV/MP4/
M4A/AAC/Opus and other container formats via an ffmpeg fallback. Stereo is
mixed to mono before modulation.

This is a thin front end over modulate.py's DSP — it reuses that module's
audio loader, USB modulator, and rate constants rather than reimplementing them.
"""
from __future__ import annotations

import argparse
import shutil
import signal
import sys
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

# Reuse the existing, tested DSP from modulate.py (import-safe: its argparse is
# guarded under __main__). INTERNAL_RATE = 48 kHz, DEFAULT_IQ_RATE = 8 kHz.
from modulate import (
    load_audio_file,
    modulate_usb,
    INTERNAL_RATE,
    DEFAULT_IQ_RATE,
)


def parse_device(spec):
    """Resolve a --device argument for sounddevice.

    Accepts an integer index ("3"), a name substring ("pipewire", "Handset"),
    or None → the system default output device. Mirrors modulate.py's helper.
    """
    if spec is None:
        return None
    try:
        return int(spec)
    except ValueError:
        return spec


def _load_via_ffmpeg(path: str) -> tuple[np.ndarray, int]:
    """Decode any ffmpeg-readable file to mono float32, normalized to [-1, 1].

    Used for formats libsndfile can't handle — WebM, MKV, MP4, M4A, AAC, etc.
    ffmpeg decodes the whole file to raw f32le mono at its native sample rate;
    we read it in one shot (playback is whole-file anyway) and normalize to
    match load_audio_file()'s behaviour.
    """
    import json as _json
    import subprocess

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError(
            f"Cannot decode {path!r}: libsndfile does not support this format "
            f"and ffmpeg/ffprobe are not installed.")

    # Probe the audio stream for its native sample rate.
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-select_streams", "a:0", path],
        capture_output=True, text=True)
    if probe.returncode != 0:
        raise RuntimeError(f"ffprobe could not read: {path}")
    streams = _json.loads(probe.stdout or "{}").get("streams", [])
    if not streams:
        raise RuntimeError(f"No audio stream found in: {path}")
    source_rate = int(streams[0].get("sample_rate", 48000))

    # Decode to raw mono float32 at the native rate.
    proc = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-i", path,
         "-vn", "-ac", "1", "-ar", str(source_rate), "-f", "f32le", "-"],
        capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"ffmpeg failed to decode: {path}")

    audio = np.frombuffer(proc.stdout, dtype=np.float32).copy()
    peak = np.max(np.abs(audio)) if len(audio) else 0.0
    if peak > 0:
        audio = audio / peak
    return audio, source_rate


def load_audio_any(path: str) -> tuple[np.ndarray, int]:
    """Load audio as mono float32 + sample rate, using ffmpeg where needed.

    Tries libsndfile (via modulate.load_audio_file) first — fast and clean for
    WAV/FLAC/OGG/… — then falls back to ffmpeg for container formats libsndfile
    rejects (WebM, MKV, MP4, M4A, AAC, …).
    """
    ext = Path(path).suffix.lower()
    # Formats libsndfile definitely can't open — skip straight to ffmpeg.
    ffmpeg_only = {".webm", ".mkv", ".mp4", ".m4a", ".aac", ".mov", ".opus"}
    if ext not in ffmpeg_only:
        try:
            return load_audio_file(path)
        except Exception:
            pass  # fall through to ffmpeg
    return _load_via_ffmpeg(path)


def build_iq(path: str, iq_rate: int) -> np.ndarray:
    """Load `path`, resample to 48 kHz, USB-modulate, decimate to `iq_rate`.

    Returns interleaved-ready complex64 IQ at `iq_rate`. The whole file is
    processed at once (offline) — simplest and correct for playback of a file.
    """
    audio, source_rate = load_audio_any(path)
    print(f"Loaded {path}: {len(audio)} samples @ {source_rate} Hz "
          f"({len(audio) / source_rate:.1f} s)", file=sys.stderr)

    # Resample to the 48 kHz internal rate (no-op if already 48 kHz).
    if source_rate != INTERNAL_RATE:
        from math import gcd
        g = gcd(INTERNAL_RATE, source_rate)
        audio = resample_poly(audio, INTERNAL_RATE // g,
                              source_rate // g).astype(np.float32)
        print(f"  Resampled {source_rate} → {INTERNAL_RATE} Hz", file=sys.stderr)

    # USB modulate at 48 kHz: analytic signal (positive frequencies only).
    iq_48k = modulate_usb(audio)

    # Decimate 48 kHz → iq_rate. resample_poly anti-alias filters, so this is
    # clean even though we're dropping to 8 kHz.
    if iq_rate != INTERNAL_RATE:
        from math import gcd
        g = gcd(INTERNAL_RATE, iq_rate)
        iq = resample_poly(iq_48k, iq_rate // g,
                           INTERNAL_RATE // g).astype(np.complex64)
    else:
        iq = iq_48k.astype(np.complex64)

    return iq


# --- I/Q balance trim -------------------------------------------------------
# A phasing (Hartley) upconverter (e.g. the AD831 board) cancels the unwanted
# sideband only as well as the I and Q paths match in gain and quadrature.
# Soundcard channel gain mismatch + analog/mixer phase skew leak an image at
# the mirror frequency. We pre-distort the IQ so the downstream imbalance
# cancels:
#     I' = I
#     Q' = g * Q + p * I
# `g` (~1) trims gain imbalance; `p` (~0) trims phase/quadrature skew.
#
# Defaults below were measured on N0GQ's bench with iq_balance_trim.py against
# the SSA3032X (LO 7200 kHz, 1 kHz tone): they took opposite-sideband
# suppression from ~27 dB to the analyzer noise floor (>65 dB). They are
# bench-specific — re-run iq_balance_trim.py for a different soundcard/board
# and override with --iq-gain / --iq-phase.
IQ_BALANCE_GAIN = 0.95987
IQ_BALANCE_PHASE = 0.08293


def iq_to_stereo(iq: np.ndarray, gain: float = 1.0,
                 phase: float = 0.0) -> np.ndarray:
    """Pack complex IQ into a float32 (N, 2) stereo buffer, with balance trim.

    Applies Q' = gain*Q + phase*I so a phasing upconverter's opposite-sideband
    image cancels. gain=1.0, phase=0.0 is the identity (no correction).
    """
    i = iq.real
    q = iq.imag
    stereo = np.empty((len(iq), 2), dtype=np.float32)
    stereo[:, 0] = i                      # I → left
    stereo[:, 1] = gain * q + phase * i   # Q' → right (balance-corrected)
    return stereo


def list_devices() -> None:
    import sounddevice as sd
    print(sd.query_devices())


def main() -> int:
    p = argparse.ArgumentParser(
        description="Play an audio file as USB IQ out the default audio device.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("input", nargs="?", help="input audio file (WAV/FLAC/OGG/MP3/…)")
    p.add_argument("--device", default=None,
                   help="output device: index or name substring "
                        "(default: system default output device)")
    p.add_argument("--rate", type=int, default=DEFAULT_IQ_RATE,
                   help=f"IQ sample rate in Hz (default: {DEFAULT_IQ_RATE})")
    p.add_argument("--iq-gain", type=float, default=IQ_BALANCE_GAIN,
                   help=f"I/Q balance gain trim on Q (default: {IQ_BALANCE_GAIN}; "
                        "1.0 disables). See iq_balance_trim.py.")
    p.add_argument("--iq-phase", type=float, default=IQ_BALANCE_PHASE,
                   help=f"I/Q balance phase trim (I->Q crossfeed; default: "
                        f"{IQ_BALANCE_PHASE}; 0.0 disables).")
    p.add_argument("--list-devices", action="store_true",
                   help="list audio devices and exit")
    args = p.parse_args()

    if args.list_devices:
        list_devices()
        return 0

    if not args.input:
        p.error("no input file specified (use --list-devices to see outputs)")

    import sounddevice as sd

    # Build the full IQ stream offline.
    iq = build_iq(args.input, args.rate)
    stereo = iq_to_stereo(iq, gain=args.iq_gain, phase=args.iq_phase)
    print(f"I/Q balance trim: gain={args.iq_gain:.5f} phase={args.iq_phase:.5f}",
          file=sys.stderr)
    peak = float(np.max(np.abs(stereo))) if len(stereo) else 0.0
    print(f"USB IQ: {len(iq)} samples @ {args.rate} Hz "
          f"({len(iq) / args.rate:.1f} s), peak |IQ| = {peak:.3f}", file=sys.stderr)

    device = parse_device(args.device)
    if device is not None:
        info = sd.query_devices(device)
        print(f"Output device: {device} ({info['name']})", file=sys.stderr)
    else:
        print("Output device: <system default>", file=sys.stderr)

    print(f"Playing USB IQ (I→left, Q→right) at {args.rate} Hz. Ctrl-C to stop.",
          file=sys.stderr)

    # Play. sd.play() streams the buffer at the given samplerate; sd.wait()
    # blocks until playback finishes. A stereo (N, 2) float32 buffer carries
    # I and Q as the two channels.
    try:
        sd.play(stereo, samplerate=args.rate, device=device)
        sd.wait()
    except KeyboardInterrupt:
        sd.stop()
        print("\nStopped.", file=sys.stderr)
        return 130

    print("Done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    # Make Ctrl-C behave predictably (default SIGINT → KeyboardInterrupt).
    signal.signal(signal.SIGINT, signal.default_int_handler)
    sys.exit(main())
