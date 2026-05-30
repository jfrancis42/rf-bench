"""
RTL-SDR receiver driver for rf-bench.

Wraps pyrtlsdr (librtlsdr) with:
  - PPM frequency-correction calibration (stored in ~/.rtlsdr_cal.json)
  - Consistent import pattern matching other rf_bench.* drivers
  - Workflow helpers: capture_iq(), power_spectrum(), scan_activity()
  - Streaming via a thread-safe generator
  - Device enumeration by serial number

Supported hardware:
  RTL-SDR Blog v3 (R820T2 tuner), RTL-SDR Blog v4 (R828D tuner, 1 PPM TCXO,
  bias tee), generic RTL2832U dongles.

Typical usage::

    from rf_bench.rtlsdr import RTLSDR

    with RTLSDR() as sdr:
        sdr.set_center_freq(144_390_000)
        sdr.set_sample_rate(2_400_000)
        sdr.set_gain(30)
        iq = sdr.capture_iq(262_144)
        freq_hz, power_db = sdr.power_spectrum(iq, rbw_hz=1000)

Calibration::

    with RTLSDR() as sdr:
        sdr.save_calibration(ppm=0.8)   # measure against SDG + SSA first
    # next time: RTLSDR() loads ~/.rtlsdr_cal.json automatically

Compatible with pyrtlsdr >= 0.2.93, < 0.4.  (0.4.0 requires
rtlsdr_set_dithering which is absent from the Arch rtl-sdr 2.0.2 package.)
"""

import json
import math
import queue
import threading
from pathlib import Path
from typing import Generator, List, Optional, Tuple

import numpy as np
import rtlsdr as _pyrtlsdr


# ── calibration file location ─────────────────────────────────────────────────

_CAL_PATH = Path.home() / ".rtlsdr_cal.json"


# ── exceptions ────────────────────────────────────────────────────────────────

class RTLSDRError(RuntimeError):
    """Raised on device errors, bad parameters, or calibration issues."""


class RTLSDRBusyError(RTLSDRError):
    """Raised when the device is already open by another process."""


# ── internal helpers ──────────────────────────────────────────────────────────

def _nearest_gain(target_db: float, valid_gains: List[float]) -> float:
    return min(valid_gains, key=lambda g: abs(g - target_db))


def _welch_psd(
    iq: np.ndarray,
    sample_rate: float,
    nperseg: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Welch's method PSD estimate (numpy-only, no scipy required).

    Hann window, 50% overlap.  Returns (freq_hz_relative, psd_linear)
    where freq_hz_relative is centred at 0 Hz.
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
        raise RTLSDRError("IQ block too short for the requested RBW")

    psd = np.mean(segments, axis=0) / win_power
    freq = np.fft.fftfreq(nperseg, d=1.0 / sample_rate)
    return np.fft.fftshift(freq), np.fft.fftshift(psd)


def _iso_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────────────────────────────────────

class RTLSDR:
    """
    RTL-SDR receiver driver.

    Args:
        serial:         USB serial number string, e.g. ``"00000001"``.  Pass
                        ``None`` (default) to open the first available device.
        device_index:   Numeric device index (0-based); used only when
                        *serial* is ``None``.
        ppm_correction: Explicit frequency correction in PPM.  If ``None``
                        (default), the stored calibration from
                        ``~/.rtlsdr_cal.json`` is loaded; 0.0 PPM is used
                        if no file exists.
        sample_rate:    Initial sample rate in S/s (default: 2.4 MS/s).
        gain:           Initial gain in dB, or ``'auto'`` for hardware AGC.
    """

    def __init__(
        self,
        serial: Optional[str] = None,
        device_index: int = 0,
        ppm_correction: Optional[float] = None,
        sample_rate: int = 2_400_000,
        gain: float | str = "auto",
    ) -> None:
        # Resolve index from serial if supplied
        if serial is not None:
            serials = _pyrtlsdr.RtlSdr.get_device_serial_addresses()
            if serial not in serials:
                raise RTLSDRError(
                    f"RTL-SDR serial '{serial}' not found. "
                    f"Available: {serials or '(none)'}"
                )
            device_index = list(serials).index(serial)

        try:
            self._sdr = _pyrtlsdr.RtlSdr(device_index=device_index)
        except OSError as exc:
            msg = str(exc).lower()
            if "resource busy" in msg or "access denied" in msg or "in use" in msg:
                raise RTLSDRBusyError(
                    "RTL-SDR device is already open by another process."
                ) from exc
            raise RTLSDRError(f"Failed to open RTL-SDR: {exc}") from exc

        # PPM calibration
        if ppm_correction is None:
            ppm_correction = self._load_calibration_ppm()
        self._ppm_correction = float(ppm_correction)
        self._sdr.set_freq_correction(int(round(self._ppm_correction)))

        # Track state locally for use in calculations (avoid extra hardware reads)
        self._center_freq: int = 100_000_000
        self._sample_rate: int = sample_rate
        self._serial = serial
        self._device_index = device_index

        # Streaming state
        self._stream_queue: Optional[queue.Queue] = None
        self._stream_stop: Optional[threading.Event] = None
        self._stream_thread: Optional[threading.Thread] = None

        # Apply initial settings (use explicit setters; compatible with all versions)
        self._sdr.set_sample_rate(sample_rate)
        if gain == "auto":
            self._sdr.set_gain("auto")
        else:
            nearest = _nearest_gain(float(gain), self._sdr.valid_gains_db)
            self._sdr.set_gain(nearest)

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "RTLSDR":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── device enumeration ────────────────────────────────────────────────────

    @classmethod
    def find_devices(cls) -> List[dict]:
        """
        Return a list of attached RTL-SDR devices.

        Each entry is a dict with keys ``index``, ``serial``, ``name``.
        """
        serials = list(_pyrtlsdr.RtlSdr.get_device_serial_addresses())
        devices = []
        for i, serial in enumerate(serials):
            try:
                name = _pyrtlsdr.RtlSdr.get_device_name(i)
            except Exception:
                name = "RTL2832U"
            devices.append({"index": i, "serial": serial, "name": name})
        return devices

    # ── identification ────────────────────────────────────────────────────────

    def identify(self) -> dict:
        """
        Return device information as a dict.

        Keys: ``serial``, ``tuner_type``, ``valid_gains_db``,
        ``sample_rate``, ``center_freq``, ``gain``, ``ppm_correction``.
        """
        try:
            tuner = self._sdr.get_tuner_type()
        except Exception:
            tuner = "unknown"
        return {
            "serial": self._serial or "(first device)",
            "tuner_type": tuner,
            "valid_gains_db": self._sdr.valid_gains_db,
            "sample_rate": self._sdr.get_sample_rate(),
            "center_freq": self._sdr.get_center_freq(),
            "gain": self._sdr.get_gain(),
            "ppm_correction": self._ppm_correction,
        }

    # ── tuning ────────────────────────────────────────────────────────────────

    def set_center_freq(self, freq_hz: int) -> None:
        """
        Set the tuning frequency in Hz.

        The stored PPM correction is applied automatically by the underlying
        librtlsdr; pass the desired receive frequency without pre-correction.
        """
        self._center_freq = int(freq_hz)
        self._sdr.set_center_freq(self._center_freq)

    def set_sample_rate(self, rate: int) -> None:
        """Set the IQ sample rate in S/s (typical range: 250_000–3_200_000)."""
        self._sample_rate = int(rate)
        self._sdr.set_sample_rate(self._sample_rate)

    def set_gain(self, gain_db: float | str) -> None:
        """
        Set receiver gain.

        Args:
            gain_db: Gain in dB, snapped to the nearest valid hardware step.
                     Use ``'auto'`` to enable hardware AGC.
        """
        if gain_db == "auto":
            self._sdr.set_gain("auto")
        else:
            nearest = _nearest_gain(float(gain_db), self._sdr.valid_gains_db)
            self._sdr.set_gain(nearest)

    def set_bias_tee(self, enabled: bool) -> None:
        """
        Enable or disable the RTL-SDR Blog v3/v4 bias tee (5 V, ~180 mA).

        Requires librtlsdr compiled with bias-tee support (Arch ``rtl-sdr``
        package includes this).  Raises ``RTLSDRError`` if unavailable.

        Always disable the bias tee before removing the LNA to avoid
        back-feeding the input with the bias voltage.
        """
        try:
            self._sdr.set_bias_tee(enabled)
        except AttributeError as exc:
            raise RTLSDRError(
                "Bias tee not supported by this librtlsdr build "
                "(requires rtl-sdr >= 0.6 / RTL-SDR Blog fork with bias tee)"
            ) from exc

    # ── IQ capture ───────────────────────────────────────────────────────────

    def capture_iq(self, num_samples: int = 262_144) -> np.ndarray:
        """
        Capture a block of IQ samples synchronously.

        Args:
            num_samples: Number of complex samples.  Powers of two are most
                         efficient (e.g. 65_536, 131_072, 262_144).

        Returns:
            complex64 numpy array of length *num_samples*.
        """
        raw = self._sdr.read_samples(num_samples)
        return np.asarray(raw, dtype=np.complex64)

    # ── spectrum ──────────────────────────────────────────────────────────────

    def power_spectrum(
        self,
        iq: np.ndarray,
        rbw_hz: float = 1000.0,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute power spectral density from an IQ capture.

        Uses Welch's method (Hann window, 50% overlap).  Power values are
        **relative** (0 dB = peak bin), not calibrated absolute dBm.  The
        RTL-SDR has no calibrated power reference; use the SSA for absolute
        amplitude measurements.

        Args:
            iq:      complex64 array from :meth:`capture_iq` or a block from
                     :meth:`stream_iq`.
            rbw_hz:  Desired resolution bandwidth in Hz.  The actual RBW is
                     the nearest power-of-two fraction of the sample rate.

        Returns:
            ``(freq_hz, power_db)`` — two float32 numpy arrays of equal
            length.  *freq_hz* gives absolute frequencies (centre_freq
            ± sample_rate / 2).  *power_db* is 0 at the peak bin.
        """
        nperseg = int(self._sample_rate / max(rbw_hz, 1.0))
        nperseg = max(64, 1 << int(math.log2(max(nperseg, 1))))
        nperseg = min(nperseg, len(iq))

        freq_rel, psd = _welch_psd(iq, float(self._sample_rate), nperseg)

        freq_hz = (freq_rel + self._center_freq).astype(np.float32)
        psd_db = (10.0 * np.log10(psd + 1e-30)).astype(np.float32)
        psd_db -= float(np.max(psd_db))   # normalise: 0 dB = peak

        return freq_hz, psd_db

    # ── activity scan ─────────────────────────────────────────────────────────

    def scan_activity(
        self,
        threshold_db: float = -20.0,
        num_samples: int = 65_536,
    ) -> List[dict]:
        """
        Quick signal presence check: capture one block, return detected signals.

        Args:
            threshold_db: Signals this many dB above the median noise floor
                          are returned.
            num_samples:  IQ block size for the scan.

        Returns:
            List of ``{'freq_hz': float, 'power_db': float}`` dicts sorted
            by power (strongest first).
        """
        iq = self.capture_iq(num_samples)
        freq_hz, power_db = self.power_spectrum(iq, rbw_hz=self._sample_rate / 512.0)

        noise_floor = float(np.median(power_db))
        above = power_db > (noise_floor + threshold_db)

        signals: List[dict] = []
        in_sig = False
        start = 0
        for i in range(len(above)):
            if above[i] and not in_sig:
                start, in_sig = i, True
            elif not above[i] and in_sig:
                mid = (start + i) // 2
                signals.append({"freq_hz": float(freq_hz[mid]), "power_db": float(power_db[mid])})
                in_sig = False
        if in_sig:
            mid = (start + len(above)) // 2
            signals.append({"freq_hz": float(freq_hz[mid]), "power_db": float(power_db[mid])})

        return sorted(signals, key=lambda x: x["power_db"], reverse=True)

    # ── streaming ─────────────────────────────────────────────────────────────

    def stream_iq(self, block_size: int = 65_536) -> Generator[np.ndarray, None, None]:
        """
        Stream IQ samples as a generator of complex64 numpy arrays.

        Runs librtlsdr's async read in a daemon thread and feeds a queue.
        Blocks are dropped (not backpressured) when the queue is full to
        prevent stalling USB reads.

        Example::

            sdr.set_center_freq(433_920_000)
            sdr.set_sample_rate(2_400_000)
            for block in sdr.stream_iq(block_size=65_536):
                process(block)
                if done:
                    break
            sdr.stop_stream()

        Args:
            block_size: Complex samples per yielded block (power-of-two preferred).

        Yields:
            complex64 numpy arrays of length *block_size*.
        """
        if self._stream_thread is not None and self._stream_thread.is_alive():
            raise RTLSDRError("A stream is already active; call stop_stream() first.")

        self._stream_queue = queue.Queue(maxsize=8)
        self._stream_stop = threading.Event()
        q = self._stream_queue
        stop_event = self._stream_stop

        def _callback(raw_samples, _sdr_obj):
            if not stop_event.is_set():
                try:
                    q.put_nowait(np.asarray(raw_samples, dtype=np.complex64))
                except queue.Full:
                    pass   # drop block rather than stall the USB read thread

        def _reader():
            try:
                self._sdr.read_samples_async(_callback, num_samples=block_size)
            except Exception:
                pass
            finally:
                stop_event.set()

        self._stream_thread = threading.Thread(target=_reader, daemon=True)
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
        """Stop an active :meth:`stream_iq` session and join the reader thread."""
        if self._stream_stop is not None:
            self._stream_stop.set()
        if self._stream_thread is not None:
            try:
                self._sdr.cancel_read_async()
            except Exception:
                pass
            self._stream_thread.join(timeout=3.0)
            self._stream_thread = None
        self._stream_queue = None
        self._stream_stop = None

    # ── calibration ───────────────────────────────────────────────────────────

    def save_calibration(self, ppm: float) -> None:
        """
        Save a measured PPM correction to ``~/.rtlsdr_cal.json`` and apply
        it to this instance immediately.

        Measure the correction by tuning to a known-frequency carrier (e.g.
        SDG1062X at 10.000000 MHz, verified on the SSA), then:
        ``ppm = (measured_hz - nominal_hz) / nominal_hz * 1e6``

        The file is shared across all RTLSDR instances; if you have multiple
        dongles with different PPM offsets, pass ``ppm_correction=`` explicitly
        at construction time instead.
        """
        self._ppm_correction = float(ppm)
        self._sdr.set_freq_correction(int(round(ppm)))
        cal = {
            "ppm_correction": self._ppm_correction,
            "measured_at": _iso_now(),
            "device_serial": self._serial or "(first device)",
        }
        _CAL_PATH.write_text(json.dumps(cal, indent=2))

    @staticmethod
    def _load_calibration_ppm() -> float:
        """Return stored PPM from ``~/.rtlsdr_cal.json``, or 0.0 if absent."""
        try:
            data = json.loads(_CAL_PATH.read_text())
            return float(data.get("ppm_correction", 0.0))
        except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
            return 0.0

    # ── close ─────────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Stop any active stream and close the hardware device."""
        self.stop_stream()
        try:
            self._sdr.close()
        except Exception:
            pass
