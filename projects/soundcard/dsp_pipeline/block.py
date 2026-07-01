"""
DSPBlock — base class for audio processing blocks.

Subclass and override `process(samples)` to implement your DSP.
Each block maintains its own state and can be chained in a Pipeline.
"""

from __future__ import annotations

import numpy as np


class DSPBlock:
    """Base class for a single DSP processing stage."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024, channels: int = 1):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.channels = channels
        self.enabled = True

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Process a block of audio samples.

        Args:
            samples: ndarray of shape (blocksize, channels) or (blocksize,) for mono.

        Returns:
            Processed samples, same shape as input (unless the block changes channels).
        """
        return samples

    def reset(self):
        """Reset internal state (e.g., filter history, averages)."""
        pass

    def get_status(self) -> dict:
        """Return a dict of current status for display."""
        return {"enabled": self.enabled}
