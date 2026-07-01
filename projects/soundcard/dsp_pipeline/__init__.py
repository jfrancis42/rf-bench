"""
dsp_pipeline — shared real-time audio DSP framework for soundcard projects.

Provides:
- AudioStream: sounddevice-based I/O with configurable devices and block size
- DSPBlock: base class for processing blocks (override `process`)
- Pipeline: chain multiple DSPBlocks, run in real-time or offline
- TestSignal: synthetic signal generators for --test mode
- common argparse flags via `add_audio_args` and `add_test_args`
"""

from .stream import AudioStream
from .block import DSPBlock
from .pipeline import Pipeline
from .test_signals import TestSignal
from .args import add_audio_args, add_test_args, open_stream_from_args

__all__ = [
    "AudioStream",
    "DSPBlock",
    "Pipeline",
    "TestSignal",
    "add_audio_args",
    "add_test_args",
    "open_stream_from_args",
]
