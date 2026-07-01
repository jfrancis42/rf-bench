"""
Pipeline — chains multiple DSPBlocks and runs them on an AudioStream.

Can also run offline on a WAV/numpy array for testing or batch processing.
"""

from __future__ import annotations

import signal
import sys
import time
import numpy as np

from .stream import AudioStream
from .block import DSPBlock


class Pipeline:
    """Chain of DSP blocks processing audio in real-time or offline."""

    def __init__(self, blocks: list[DSPBlock] | None = None, samplerate: int = 48000, blocksize: int = 1024):
        self.blocks = blocks or []
        self.samplerate = samplerate
        self.blocksize = blocksize
        self._stream = None

    def add(self, block: DSPBlock) -> "Pipeline":
        """Add a block to the end of the chain."""
        self.blocks.append(block)
        return self

    def process_block(self, samples: np.ndarray) -> np.ndarray:
        """Run one block of samples through all enabled DSP stages."""
        out = samples
        for block in self.blocks:
            if block.enabled:
                out = block.process(out)
        return out

    def process_array(self, audio: np.ndarray) -> np.ndarray:
        """Run an entire audio array through the pipeline in blocksize chunks.

        Useful for offline/test processing.
        """
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)
        n_samples = audio.shape[0]
        output_blocks = []
        for start in range(0, n_samples, self.blocksize):
            chunk = audio[start:start + self.blocksize]
            if chunk.shape[0] < self.blocksize:
                pad = np.zeros((self.blocksize - chunk.shape[0], chunk.shape[1]), dtype=audio.dtype)
                chunk = np.concatenate([chunk, pad])
            processed = self.process_block(chunk)
            output_blocks.append(processed[:min(self.blocksize, n_samples - start)])
        return np.concatenate(output_blocks, axis=0)

    def run_realtime(
        self,
        input_device=None,
        output_device=None,
        channels_in: int = 1,
        channels_out: int = 2,
    ):
        """Run the pipeline in real-time until Ctrl-C."""
        stream = AudioStream(
            input_device=input_device,
            output_device=output_device,
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            channels_in=channels_in,
            channels_out=channels_out,
        )

        def callback(indata, frames):
            return self.process_block(indata)

        stream.set_callback(callback)

        stop = [False]

        def sigint_handler(signum, frame):
            stop[0] = True

        old_handler = signal.signal(signal.SIGINT, sigint_handler)

        try:
            stream.start()
            print("Pipeline running (Ctrl-C to stop)...", file=sys.stderr)
            while not stop[0]:
                time.sleep(0.1)
        finally:
            stream.stop()
            signal.signal(signal.SIGINT, old_handler)
            print("\nStopped.", file=sys.stderr)

    def run_test(
        self,
        test_signal: np.ndarray,
        output_device=None,
        channels_out: int = 2,
    ):
        """Process a test signal through the pipeline and play it."""
        processed = self.process_array(test_signal)

        if output_device is not None:
            import sounddevice as sd
            if processed.ndim == 1:
                processed = processed.reshape(-1, 1)
            if processed.shape[1] < channels_out:
                processed = np.tile(processed, (1, channels_out))
            sd.play(processed[:, :channels_out], self.samplerate, device=output_device)
            sd.wait()

        return processed

    def reset(self):
        """Reset all blocks."""
        for block in self.blocks:
            block.reset()
