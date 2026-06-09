"""
KiwiSDR HF receiver driver for rf-bench.

Connects to a KiwiSDR (0–30 MHz HF software-defined receiver) over its
WebSocket SND API and exposes a capture_iq() / stream_iq() / power_spectrum()
interface that matches rf_bench.rtlsdr.RTLSDR as closely as the hardware allows,
enabling drop-in use for HF automation projects.

Key differences from RTL-SDR:
  - Fixed 12 kHz IQ sample rate (hardware-defined by the FPGA; cannot be changed)
  - 0–30 MHz coverage only (no VHF/UHF)
  - Network-connected via WebSocket (host:port), not USB
  - ±5 kHz instantaneous passband per channel (10 kHz total; configurable up to ±6 kHz)
  - No PPM calibration required — the KiwiSDR has an onboard GPS-disciplined oscillator
  - Up to 4–8 simultaneous independent channels on one device (depending on build)
  - scan_band() sweeps an HF range by retuning; no wideband FFT sweep

Typical usage::

    from rf_bench.kiwisdr import KiwiSDR

    with KiwiSDR("192.168.1.100") as kiwi:
        kiwi.set_center_freq(14_074_000)    # 20m FT8
        iq = kiwi.capture_iq(4_096)         # complex64 at 12 kHz
        freq_hz, power_db = kiwi.power_spectrum(iq)

Multiple simultaneous channels (independent WebSocket connections to same device)::

    ch0 = KiwiSDR("192.168.1.100", channel=0)
    ch1 = KiwiSDR("192.168.1.100", channel=1)
    ch0.set_center_freq(14_074_000)   # 20m FT8
    ch1.set_center_freq(7_074_000)    # 40m FT8

Protocol note:
    Frame format derived from kiwiclient source (https://github.com/jks-prv/kiwiclient)
    and the KiwiSDR firmware header kiwi_ws.h.  If you see parse errors or silent
    garbage output, the most likely culprits are _SND_HEADER_LEN and whether the
    firmware is sending IQ samples as big-endian or little-endian int16.
    Verify with a scope: a pure carrier should produce a complex tone in capture_iq().
"""

import math
import queue
import struct
import threading
import time
from typing import Generator, Iterator, List, Optional, Tuple

import numpy as np
import websocket as _websocket  # websocket-client (PyPI: websocket-client)


# ── module-level constants ────────────────────────────────────────────────────

SAMPLE_RATE       = 12_000          # KiwiSDR IQ output sample rate (Hz, hardware-fixed)
MIN_FREQ_HZ       = 0
MAX_FREQ_HZ       = 30_000_000
MAX_PASSBAND_HZ   = 6_000           # one-sided max IQ bandwidth (Hz)
DEFAULT_PASSBAND  = 5_000           # default: ±5 kHz

# SND frame constants — derived from kiwiclient source inspection.
# If your firmware version produces garbled data, compare these against:
#   https://github.com/jks-prv/kiwiclient/blob/master/kiwipy/kiwiSDRStream.py
_SND_TAG          = b"SND"
_SND_TAG_LEN      = 3
_FLAG_IQ_MODE     = 0x01            # flags byte bit 0: IQ (not audio) mode
_FLAG_GPS_BLOCK   = 0x80            # flags byte bit 7: GPS data block appended after header
_SND_HEADER_LEN   = 10              # tag(3) + flags(1) + seq(4) + rssi(1) + pad(1)
_GPS_BLOCK_LEN    = 8               # GPS block appended when FLAG_GPS_BLOCK is set


# ── exceptions ────────────────────────────────────────────────────────────────

class KiwiSDRError(RuntimeError):
    """Raised on connection, protocol, parameter, or timeout errors."""


class KiwiSDRBusyError(KiwiSDRError):
    """Raised when the KiwiSDR has no free receiver channels."""


class KiwiSDRTimeoutError(KiwiSDRError):
    """Raised when a receive operation exceeds the configured timeout."""


# ── internal helpers ──────────────────────────────────────────────────────────

def _welch_psd(
    iq: np.ndarray,
    sample_rate: float,
    nperseg: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Welch's method PSD estimate (numpy-only, no scipy required).

    Hann window, 50% overlap.  Returns (freq_hz_relative, psd_linear)
    with freq_hz_relative centred at 0 Hz.
    """
    n = len(iq)
    step = max(1, nperseg // 2)
    window = np.hanning(nperseg).astype(np.float32)
    win_power = float(np.sum(window ** 2))

    segments: List[np.ndarray] = []
    pos = 0
    while pos + nperseg <= n:
        seg = iq[pos : pos + nperseg] * window
        spec = np.fft.fft(seg, n=nperseg)
        segments.append(np.abs(spec) ** 2)
        pos += step

    if not segments:
        raise KiwiSDRError("IQ block too short for the requested RBW")

    psd  = np.mean(segments, axis=0) / win_power
    freq = np.fft.fftfreq(nperseg, d=1.0 / sample_rate)
    return np.fft.fftshift(freq), np.fft.fftshift(psd)


def _parse_snd_frame(data: bytes) -> Optional[np.ndarray]:
    """
    Parse one KiwiSDR SND binary WebSocket frame into complex64 IQ samples.

    Frame layout:
        bytes 0–2:   b"SND"
        byte  3:     flags  (bit 0 = IQ mode; bit 7 = GPS block follows header)
        bytes 4–7:   sequence number (uint32, big-endian)
        byte  8:     RSSI  (int8, 1-second smoothed)
        byte  9:     padding
        [bytes 10–17: 8-byte GPS block when FLAG_GPS_BLOCK is set]
        bytes N+:    sample data
                       IQ mode:    interleaved int16 big-endian I/Q pairs
                       audio mode: mono int16 big-endian samples

    Returns None for frames that are too short, have the wrong tag, or carry
    no usable payload.
    """
    if len(data) < _SND_HEADER_LEN + 4:
        return None
    if data[:_SND_TAG_LEN] != _SND_TAG:
        return None

    flags   = data[_SND_TAG_LEN]
    iq_mode = bool(flags & _FLAG_IQ_MODE)
    has_gps = bool(flags & _FLAG_GPS_BLOCK)

    payload_start = _SND_HEADER_LEN + (_GPS_BLOCK_LEN if has_gps else 0)
    payload       = data[payload_start:]

    if len(payload) < 2:
        return None

    if iq_mode:
        # Interleaved I/Q as big-endian int16 pairs
        n_pairs = len(payload) // 4
        if n_pairs == 0:
            return None
        raw = np.frombuffer(payload[:n_pairs * 4], dtype=">i2").reshape(n_pairs, 2)
        iq  = (raw[:, 0].astype(np.float32)
               + 1j * raw[:, 1].astype(np.float32)) / 32768.0
    else:
        # Audio mode: mono big-endian int16 → real-valued complex
        n = len(payload) // 2
        if n == 0:
            return None
        real = np.frombuffer(payload[:n * 2], dtype=">i2").astype(np.float32) / 32768.0
        iq   = real.astype(np.complex64)

    return iq.astype(np.complex64)


# ── main class ────────────────────────────────────────────────────────────────

class KiwiSDR:
    """
    KiwiSDR HF receiver driver.

    Each instance opens one independent WebSocket connection to the KiwiSDR,
    consuming one receiver channel slot.  Standard KiwiSDRs support 4 slots;
    some builds support 8.  Use different ``channel`` values to open multiple
    simultaneous connections to the same device.

    Args:
        host:         Hostname or IP of the KiwiSDR (e.g. ``"192.168.1.100"``).
        port:         WebSocket port (default 8073).
        password:     KiwiSDR password; empty string for open (no-password) servers.
        channel:      Receiver slot index (0-based).  If the slot is occupied,
                      ``KiwiSDRBusyError`` is raised.
        passband_hz:  One-sided IQ passband in Hz (default 5000 → ±5 kHz, 10 kHz
                      total).  Maximum is 6000 (±6 kHz).  Narrowing this does not
                      change the sample rate; it only adjusts the digital filter
                      applied before output.
        timeout:      WebSocket receive timeout in seconds (default 10.0).
    """

    SAMPLE_RATE = SAMPLE_RATE   # expose as class attribute for external code

    def __init__(
        self,
        host: str,
        port: int = 8073,
        password: str = "",
        channel: int = 0,
        passband_hz: int = DEFAULT_PASSBAND,
        timeout: float = 10.0,
    ) -> None:
        self._host        = host
        self._port        = port
        self._password    = password
        self._channel     = channel
        self._passband_hz = min(int(passband_hz), MAX_PASSBAND_HZ)
        self._timeout     = float(timeout)
        self._center_freq = 10_000_000  # 10 MHz default

        self._ws: Optional[_websocket.WebSocket] = None

        # Streaming state
        self._stream_queue:  Optional[queue.Queue]    = None
        self._stream_stop:   Optional[threading.Event] = None
        self._stream_thread: Optional[threading.Thread] = None

        self._connect()

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "KiwiSDR":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        return (f"KiwiSDR({self._host}:{self._port} ch={self._channel} "
                f"freq={self._center_freq/1e6:.3f}MHz)")

    # ── internal: WebSocket connection ────────────────────────────────────────

    def _connect(self) -> None:
        url = f"ws://{self._host}:{self._port}/kiwi/{self._channel}/SND"
        try:
            ws = _websocket.WebSocket()
            ws.settimeout(self._timeout)
            ws.connect(url, subprotocols=["kiwi"])
            self._ws = ws
        except _websocket.WebSocketException as exc:
            raise KiwiSDRError(
                f"WebSocket handshake failed connecting to {url}: {exc}"
            ) from exc
        except OSError as exc:
            raise KiwiSDRError(
                f"Cannot reach KiwiSDR at {self._host}:{self._port} — "
                f"is the device powered on and reachable? ({exc})"
            ) from exc

        self._authenticate()
        self._start_stream()

    def _ws_send(self, text: str) -> None:
        try:
            self._ws.send(text)
        except _websocket.WebSocketException as exc:
            raise KiwiSDRError(f"WebSocket send failed: {exc}") from exc

    def _ws_recv(self) -> bytes | str:
        try:
            return self._ws.recv()
        except _websocket.WebSocketTimeoutException:
            raise KiwiSDRTimeoutError(
                f"Timed out ({self._timeout:.0f}s) waiting for KiwiSDR data.  "
                "Check host, port, and password."
            )
        except _websocket.WebSocketException as exc:
            raise KiwiSDRError(f"WebSocket receive failed: {exc}") from exc

    def _drain_text_msgs(self, deadline: float) -> None:
        """Receive and discard text MSG frames until a binary frame arrives or deadline."""
        while time.monotonic() < deadline:
            try:
                data = self._ws.recv()
            except _websocket.WebSocketTimeoutException:
                return
            if isinstance(data, str):
                if "too_busy" in data or "no_more_ch" in data:
                    raise KiwiSDRBusyError(
                        f"KiwiSDR has no free channels (tried channel={self._channel}).  "
                        "Try a higher channel index (e.g. KiwiSDR(..., channel=1))."
                    )
            elif isinstance(data, bytes):
                return  # binary data already arriving; done draining

    def _authenticate(self) -> None:
        self._ws_send(f"SET auth t=kiwi p={self._password}")
        self._drain_text_msgs(time.monotonic() + self._timeout)

    def _start_stream(self) -> None:
        lo = -self._passband_hz
        hi =  self._passband_hz
        self._ws_send(
            f"SET mod=iq low_cut={lo} high_cut={hi} "
            f"freq={self._center_freq / 1000.0:.3f}"
        )
        self._ws_send("SET AR OK in=12000 out=12000")
        self._ws_send("SET gen=0 mix=-1")
        self._ws_send("SET squelch=0 th=0")

    # ── identification ────────────────────────────────────────────────────────

    def identify(self) -> dict:
        """Return a dict describing the current connection and configuration."""
        return {
            "host":        self._host,
            "port":        self._port,
            "channel":     self._channel,
            "center_freq": self._center_freq,
            "passband_hz": self._passband_hz,
            "sample_rate": SAMPLE_RATE,
        }

    # ── tuning ────────────────────────────────────────────────────────────────

    def set_center_freq(self, freq_hz: int) -> None:
        """
        Tune the receiver to *freq_hz* (Hz).  Valid range: 0–30 MHz.

        Unlike RTL-SDR, retuning does not interrupt the stream — the KiwiSDR
        FPGA is always sampling the full 0–30 MHz; this just repositions the
        digital mixer.  The first ~40 ms of IQ after retuning may contain
        filter transients.
        """
        freq_hz = int(freq_hz)
        if not (MIN_FREQ_HZ <= freq_hz <= MAX_FREQ_HZ):
            raise KiwiSDRError(
                f"Frequency {freq_hz / 1e6:.3f} MHz is outside the KiwiSDR range "
                f"(0–30 MHz)."
            )
        self._center_freq = freq_hz
        lo = -self._passband_hz
        hi =  self._passband_hz
        self._ws_send(
            f"SET mod=iq low_cut={lo} high_cut={hi} "
            f"freq={freq_hz / 1000.0:.3f}"
        )

    def set_passband(self, lo_hz: int, hi_hz: int) -> None:
        """
        Set the IQ passband asymmetrically (Hz relative to centre frequency).

        Useful for single-sideband work:
          - LSB: ``set_passband(-3000, 0)``
          - USB: ``set_passband(0, 3000)``
          - Symmetric 10 kHz: ``set_passband(-5000, 5000)``

        Magnitude of each value is clamped to MAX_PASSBAND_HZ (6000 Hz).
        """
        lo_hz = max(-MAX_PASSBAND_HZ, int(lo_hz))
        hi_hz = min( MAX_PASSBAND_HZ, int(hi_hz))
        self._passband_hz = max(abs(lo_hz), abs(hi_hz))
        self._ws_send(
            f"SET mod=iq low_cut={lo_hz} high_cut={hi_hz} "
            f"freq={self._center_freq / 1000.0:.3f}"
        )

    def set_sample_rate(self, rate: int) -> None:
        """
        The KiwiSDR IQ output rate is fixed at 12 000 S/s by the FPGA.

        Calling with ``rate == 12000`` is silently accepted (no-op).
        Any other value raises ``KiwiSDRError``.  This method exists solely
        for interface compatibility with rf_bench.rtlsdr.RTLSDR.
        """
        if int(rate) != SAMPLE_RATE:
            raise KiwiSDRError(
                f"KiwiSDR sample rate is hardware-fixed at {SAMPLE_RATE} S/s; "
                f"cannot set {rate}."
            )

    def set_gain(self, gain_db: float | str = 0) -> None:
        """
        Adjust receiver gain via the AGC threshold.

        The KiwiSDR's gain model differs from the RTL-SDR:
          - Pass 0 or ``'auto'`` for normal AGC operation (recommended).
          - Negative values lower the AGC threshold, reducing gain for
            strong-signal environments (equivalent to RF attenuation).
          - Positive values are clamped to 0 (gain cannot exceed hardware max).

        For most HF use, leave at the default (0 / auto AGC).
        """
        if gain_db == "auto":
            gain_db = 0
        thresh = max(-120, min(0, -int(abs(float(gain_db)))))
        self._ws_send(
            f"SET agc=1 hang=0 thresh={thresh} slope=6 decay=1000 manGain=0"
        )

    # ── IQ capture ───────────────────────────────────────────────────────────

    def capture_iq(self, num_samples: int = 4_096) -> np.ndarray:
        """
        Capture a block of IQ samples synchronously.

        Collects binary SND frames from the WebSocket stream until
        *num_samples* complex samples have been received, then returns them.

        Args:
            num_samples: Number of complex samples to return.  At 12 kHz:
                           512 samples  ≈  43 ms  (one WebSocket frame)
                          4096 samples  ≈ 341 ms
                         12000 samples  ≈   1.0 s

        Returns:
            complex64 numpy array of exactly *num_samples* samples.

        Note:
            The first capture after ``set_center_freq()`` may include up to
            one frame (~43 ms) of data from the previous frequency due to
            pipelining in the FPGA downsampler.  Insert a ``time.sleep(0.05)``
            after retuning if clean channel switching is required.
        """
        chunks: List[np.ndarray] = []
        collected = 0

        while collected < num_samples:
            data = self._ws_recv()
            if isinstance(data, bytes):
                frame = _parse_snd_frame(data)
                if frame is not None:
                    chunks.append(frame)
                    collected += len(frame)
            # Text MSG frames (status updates) are silently skipped

        result = np.concatenate(chunks)[:num_samples]
        return result.astype(np.complex64)

    # ── spectrum ──────────────────────────────────────────────────────────────

    def power_spectrum(
        self,
        iq: np.ndarray,
        rbw_hz: float = 100.0,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute power spectral density from a ``capture_iq()`` block.

        Uses Welch's method (Hann window, 50% overlap).  Power is normalised
        so that the peak bin is 0 dB (relative, not absolute dBm).

        Args:
            iq:      complex64 array from :meth:`capture_iq`.
            rbw_hz:  Desired resolution bandwidth (Hz).  At 12 kHz sample rate
                     the practical minimum is ~12 Hz (requires ≥1000 samples).

        Returns:
            ``(freq_hz, power_db)`` — two float32 arrays of equal length.
            *freq_hz* gives absolute frequencies within the passband
            (center_freq ± passband_hz).  *power_db* is 0 at the peak bin.
        """
        nperseg = int(SAMPLE_RATE / max(rbw_hz, 1.0))
        nperseg = max(64, 1 << int(math.log2(max(nperseg, 1))))
        nperseg = min(nperseg, len(iq))

        freq_rel, psd = _welch_psd(iq, float(SAMPLE_RATE), nperseg)

        freq_hz = (freq_rel + self._center_freq).astype(np.float32)
        psd_db  = (10.0 * np.log10(psd + 1e-30)).astype(np.float32)
        psd_db -= float(np.max(psd_db))

        return freq_hz, psd_db

    # ── activity detection ────────────────────────────────────────────────────

    def scan_activity(
        self,
        threshold_db: float = -20.0,
        num_samples: int = 4_096,
    ) -> List[dict]:
        """
        Detect signals at the current tuned frequency.

        Captures *num_samples* IQ, computes the PSD, and returns any signals
        found above *threshold_db* relative to the local noise floor.

        Returns:
            List of ``{'freq_hz': float, 'power_db': float}`` dicts, sorted
            strongest-first.

        See Also:
            :meth:`scan_band` for sweeping a frequency range.
        """
        iq = self.capture_iq(num_samples)
        freq_hz, power_db = self.power_spectrum(iq, rbw_hz=50.0)

        noise_floor = float(np.median(power_db))
        above = power_db > (noise_floor + threshold_db)

        signals: List[dict] = []
        in_sig, start = False, 0
        for i, flag in enumerate(above):
            if flag and not in_sig:
                start, in_sig = i, True
            elif not flag and in_sig:
                mid = (start + i) // 2
                signals.append({
                    "freq_hz":  float(freq_hz[mid]),
                    "power_db": float(power_db[mid]),
                })
                in_sig = False
        if in_sig:
            mid = (start + len(above)) // 2
            signals.append({
                "freq_hz":  float(freq_hz[mid]),
                "power_db": float(power_db[mid]),
            })

        return sorted(signals, key=lambda x: x["power_db"], reverse=True)

    def scan_band(
        self,
        start_hz: int,
        stop_hz: int,
        step_hz: int = 10_000,
        threshold_db: float = -20.0,
        dwell_samples: int = 2_048,
        settle_s: float = 0.05,
    ) -> List[dict]:
        """
        Sweep a frequency range and return all detected signals.

        Retunes in *step_hz* steps from *start_hz* to *stop_hz*, capturing
        *dwell_samples* IQ at each step.  Note that this is a sequential
        narrowband sweep — the KiwiSDR can only observe one 10 kHz window at
        a time, unlike the RTL-SDR's 2.4 MHz instantaneous capture.

        A full sweep of 80m (3.5–4.0 MHz, 500 kHz) with 10 kHz steps and
        2048 samples (~170 ms dwell) takes roughly 8–9 seconds.

        Args:
            start_hz:       Start frequency (Hz).
            stop_hz:        Stop frequency (Hz).
            step_hz:        Frequency step (Hz; default 10 000 = passband width).
            threshold_db:   Signal detection threshold above noise floor (dB).
            dwell_samples:  IQ samples captured at each step.
            settle_s:       Seconds to wait after retuning before capturing
                            (allows the FPGA downsampler to settle).

        Returns:
            List of ``{'freq_hz', 'power_db'}`` dicts sorted by power.
        """
        results: List[dict] = []
        freq = int(start_hz)
        while freq <= int(stop_hz):
            try:
                self.set_center_freq(freq)
                if settle_s > 0:
                    time.sleep(settle_s)
                results.extend(self.scan_activity(threshold_db, dwell_samples))
            except KiwiSDRError:
                pass
            freq += int(step_hz)
        return sorted(results, key=lambda x: x["power_db"], reverse=True)

    # ── streaming ─────────────────────────────────────────────────────────────

    def stream_iq(self, block_size: int = 4_096) -> Generator[np.ndarray, None, None]:
        """
        Stream IQ samples as a generator of complex64 numpy arrays.

        Assembles SND frames into blocks of *block_size* samples.  The stream
        runs until the caller ``break``s or :meth:`stop_stream` is called.

        Example::

            kiwi.set_center_freq(14_025_000)    # 20m CW
            for block in kiwi.stream_iq(block_size=12_000):   # 1 s blocks
                process(block)
                if done:
                    break
            kiwi.stop_stream()

        Args:
            block_size: Complex samples per yielded block.  12 000 = 1 second;
                        512 = one raw WebSocket frame (~43 ms).

        Yields:
            complex64 numpy arrays of length *block_size*.
        """
        if self._stream_thread is not None and self._stream_thread.is_alive():
            raise KiwiSDRError(
                "A stream is already running on this channel; call stop_stream() first."
            )

        self._stream_queue = queue.Queue(maxsize=32)
        self._stream_stop  = threading.Event()
        q          = self._stream_queue
        stop_event = self._stream_stop

        def _reader() -> None:
            buf: List[np.ndarray] = []
            collected = 0
            try:
                while not stop_event.is_set():
                    try:
                        data = self._ws.recv()
                    except _websocket.WebSocketTimeoutException:
                        continue
                    except Exception:
                        break

                    if not isinstance(data, bytes):
                        continue

                    frame = _parse_snd_frame(data)
                    if frame is None:
                        continue

                    buf.append(frame)
                    collected += len(frame)

                    while collected >= block_size:
                        merged = np.concatenate(buf)
                        out    = merged[:block_size].astype(np.complex64)
                        try:
                            q.put_nowait(out)
                        except queue.Full:
                            pass  # drop rather than stall the reader
                        remainder = merged[block_size:]
                        buf       = [remainder] if len(remainder) else []
                        collected = len(remainder)
            finally:
                stop_event.set()

        self._stream_thread = threading.Thread(target=_reader, daemon=True,
                                               name=f"kiwi-ch{self._channel}")
        self._stream_thread.start()

        try:
            while not stop_event.is_set() or not q.empty():
                try:
                    yield q.get(timeout=0.5)
                except queue.Empty:
                    continue
        finally:
            stop_event.set()

    def stop_stream(self) -> None:
        """Stop an active :meth:`stream_iq` and join the reader thread."""
        if self._stream_stop is not None:
            self._stream_stop.set()
        thread = self._stream_thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._stream_thread = None
        self._stream_queue  = None
        self._stream_stop   = None

    # ── close ─────────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Stop any active stream and close the WebSocket connection."""
        self.stop_stream()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
