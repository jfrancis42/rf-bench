"""
Shared argparse helpers for soundcard projects.

Provides consistent --input-device, --output-device, --samplerate,
--blocksize, --test, and --list-devices flags across all projects.
"""

from __future__ import annotations

import argparse
import sys

import sounddevice as sd

from .stream import AudioStream


def add_audio_args(parser: argparse.ArgumentParser, duplex: bool = True) -> None:
    """Add standard audio device/format arguments."""
    g = parser.add_argument_group("audio I/O")
    g.add_argument("--input-device", type=int, default=None, metavar="ID",
                   help="Input device ID (use --list-devices to see available)")
    if duplex:
        g.add_argument("--output-device", type=int, default=None, metavar="ID",
                       help="Output device ID (use --list-devices to see available)")
    g.add_argument("--samplerate", type=int, default=48000, metavar="HZ",
                   help="Sample rate (default 48000)")
    g.add_argument("--blocksize", type=int, default=1024, metavar="N",
                   help="Block size in samples (default 1024)")
    g.add_argument("--channels-in", type=int, default=1, metavar="N",
                   help="Input channels (default 1)")
    if duplex:
        g.add_argument("--channels-out", type=int, default=2, metavar="N",
                       help="Output channels (default 2)")
    g.add_argument("--list-devices", action="store_true",
                   help="List audio devices and exit")


def add_test_args(parser: argparse.ArgumentParser) -> None:
    """Add --test and --test-duration flags."""
    g = parser.add_argument_group("test mode")
    g.add_argument("--test", action="store_true",
                   help="Use synthetic test signal instead of live audio")
    g.add_argument("--test-duration", type=float, default=5.0, metavar="SEC",
                   help="Duration of test signal in seconds (default 5.0)")


def open_stream_from_args(args, duplex: bool = True) -> AudioStream:
    """Create an AudioStream from parsed argparse namespace."""
    if getattr(args, "list_devices", False):
        print(sd.query_devices())
        sys.exit(0)

    channels_out = getattr(args, "channels_out", 2) if duplex else 1
    output_device = getattr(args, "output_device", None) if duplex else None

    return AudioStream(
        input_device=args.input_device,
        output_device=output_device,
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        channels_in=args.channels_in,
        channels_out=channels_out,
    )
