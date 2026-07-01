"""
AudioStream — sounddevice wrapper for real-time audio I/O.

Handles device selection, sample rate, block size, and channel count.
Supports input-only, output-only, or duplex (pass-through) operation.
"""

from __future__ import annotations

import threading
import numpy as np
import sounddevice as sd


class AudioStream:
    """Real-time audio I/O via sounddevice."""

    def __init__(
        self,
        input_device=None,
        output_device=None,
        samplerate: int = 48000,
        blocksize: int = 1024,
        channels_in: int = 1,
        channels_out: int = 2,
        dtype: str = "float32",
    ):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.channels_in = channels_in
        self.channels_out = channels_out
        self.dtype = dtype
        self.input_device = input_device
        self.output_device = output_device
        self._callback = None
        self._stream = None
        self._running = threading.Event()

    def set_callback(self, fn):
        """Set the processing callback: fn(indata, frames) -> outdata or None."""
        self._callback = fn

    def _sd_callback(self, indata, outdata, frames, time_info, status):
        if status:
            pass  # drop status messages silently for real-time
        if self._callback is not None:
            result = self._callback(indata.copy(), frames)
            if result is not None:
                if result.shape != outdata.shape:
                    # handle mono->stereo or channel mismatch
                    if result.ndim == 1:
                        result = result.reshape(-1, 1)
                    if result.shape[1] < outdata.shape[1]:
                        result = np.tile(result, (1, outdata.shape[1]))
                    elif result.shape[1] > outdata.shape[1]:
                        result = result[:, :outdata.shape[1]]
                outdata[:] = result
            else:
                outdata.fill(0)
        else:
            outdata[:] = indata[:, :outdata.shape[1]] if indata.shape[1] >= outdata.shape[1] else np.tile(indata, (1, outdata.shape[1] // indata.shape[1] + 1))[:, :outdata.shape[1]]

    def _sd_input_callback(self, indata, frames, time_info, status):
        if self._callback is not None:
            self._callback(indata.copy(), frames)

    def _split_duplex_callback(self, indata, frames, time_info, status):
        """Callback for the input half of a split duplex stream."""
        if self._callback is not None:
            result = self._callback(indata.copy(), frames)
            if result is not None:
                if result.ndim == 1:
                    result = result.reshape(-1, 1)
                if result.shape[1] < self.channels_out:
                    result = np.tile(result, (1, self.channels_out))
                elif result.shape[1] > self.channels_out:
                    result = result[:, :self.channels_out]
                self._out_buf[:] = result
            else:
                self._out_buf.fill(0)

    def _split_output_callback(self, outdata, frames, time_info, status):
        """Callback for the output half of a split duplex stream."""
        outdata[:] = self._out_buf

    def start(self):
        """Start the audio stream."""
        if self.output_device is not None or (self.input_device is not None and self.output_device is not None):
            try:
                self._stream = sd.Stream(
                    device=(self.input_device, self.output_device),
                    samplerate=self.samplerate,
                    blocksize=self.blocksize,
                    channels=(self.channels_in, self.channels_out),
                    dtype=self.dtype,
                    callback=self._sd_callback,
                )
                self._stream.start()
            except sd.PortAudioError:
                # duplex across different backends fails — use separate streams
                self._out_buf = np.zeros((self.blocksize, self.channels_out),
                                          dtype=self.dtype)
                self._input_stream = sd.InputStream(
                    device=self.input_device,
                    samplerate=self.samplerate,
                    blocksize=self.blocksize,
                    channels=self.channels_in,
                    dtype=self.dtype,
                    callback=self._split_duplex_callback,
                )
                self._output_stream = sd.OutputStream(
                    device=self.output_device,
                    samplerate=self.samplerate,
                    blocksize=self.blocksize,
                    channels=self.channels_out,
                    dtype=self.dtype,
                    callback=self._split_output_callback,
                )
                self._input_stream.start()
                self._output_stream.start()
                self._stream = None
        else:
            self._stream = sd.InputStream(
                device=self.input_device,
                samplerate=self.samplerate,
                blocksize=self.blocksize,
                channels=self.channels_in,
                dtype=self.dtype,
                callback=self._sd_input_callback,
            )
            self._stream.start()
        self._running.set()

    def stop(self):
        """Stop the audio stream."""
        self._running.clear()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if hasattr(self, '_input_stream') and self._input_stream is not None:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None
        if hasattr(self, '_output_stream') and self._output_stream is not None:
            self._output_stream.stop()
            self._output_stream.close()
            self._output_stream = None

    def is_running(self) -> bool:
        return self._running.is_set()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    @staticmethod
    def list_devices():
        """Return list of available audio devices."""
        return sd.query_devices()

    @staticmethod
    def get_default_input():
        return sd.default.device[0]

    @staticmethod
    def get_default_output():
        return sd.default.device[1]
