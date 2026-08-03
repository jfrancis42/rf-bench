"""
solsdr driver for rf-bench — SunSDR2 PRO over solsdr's network servers.

This is the rf-bench client for the **solsdr** companion project
(github.com/jfrancis42/solsdr, ~/Dropbox/build/solsdr/), a pure-Python SunSDR2
PRO SDR that talks the radio's raw UDP protocol directly — **no ExpertSDR3**.

Unlike `rf_bench.sunsdr` (which drives the radio through ExpertSDR3's TCI
WebSocket and CANNOT transmit IQ), this driver:

  * needs no ExpertSDR3 running,
  * receives raw complex64 IQ, and
  * **transmits raw complex64 IQ** — an arbitrary waveform straight out the
    antenna, which TCI has no path for at all. (Hardware-verified in solsdr.)

## Architecture — it's a NETWORK CLIENT, not a library import

solsdr is a headless appliance: one solsdr process owns the radio and exposes
several TCP servers; any number of clients (this driver, GNU Radio, the MQTT
bridge) connect to them. So this driver does NOT import the solsdr package — it
speaks to solsdr's servers over TCP:

    control API  (:5556)  line-based text  — freq/mode/gain/rit/agc/smeter/status
    RX IQ server (:5555)  complex64 stream — capture / stream / spectrum
    RX2 IQ server(:5557)  complex64 stream — second receiver (if solsdr --rx2)
    TX IQ server (:5558)  complex64 sink   — transmit raw IQ (connect = key)

Start solsdr with the servers enabled, e.g. on the radio host::

    solsdr 14074 --control-api --iq-tx-server            # RX (default) + TX, no RF
    solsdr 14074 --control-api --iq-tx-server --tx-arm   # ARMED to key
    # (the RX IQ server on :5555 is ON BY DEFAULT; use --no-iq-server to disable)

Then, from anywhere on the network::

    from rf_bench.solsdr import SolSDR

    with SolSDR("10.1.2.50") as sdr:          # host running solsdr
        sdr.set_frequency(14_074_000)
        sdr.set_mode("USB")
        iq = sdr.capture_iq(65_536)           # complex64 from the RX IQ server
        freq_hz, power_db = sdr.power_spectrum(iq, rbw_hz=500)
        print("S:", sdr.get_strength(), "dBFS")

    # Arbitrary-waveform transmit (the capability nothing else on the bench has):
    with SolSDR("10.1.2.50") as sdr:
        tone = 0.5 * np.exp(2j*np.pi*1000*np.arange(int(sdr.sample_rate))/sdr.sample_rate)
        sdr.transmit_iq(tone.astype(np.complex64))   # ⚠ solsdr must be --tx-arm'd

## Sample rate

The IQ sample rate is fixed by how solsdr was launched (`--rate`; default
39062.5 S/s, options 39062.5 / 78125 / 156250 / 312500). It is READ-ONLY here —
the control API has no rate command — so `set_sample_rate()` raises
NotImplementedError (capability mismatch, not a silent fallback). Read the
current rate from :attr:`sample_rate` (learned from the IQ server header).

## PTT

solsdr's transmit model is "connect to the TX-IQ server = key; disconnect =
unkey." There is no bare PTT toggle over the control API, so `set_ptt()` raises
with a pointer to :meth:`transmit_iq`. This is intentional — keying without
feeding IQ is meaningless in this model.

## Frequency/mode readback

The control API tracks freq/mode as SHADOW state — what was set *through the
API* — not the radio's live tuning. `get_frequency()`/`get_mode()` therefore
return the last value this driver set (cached), falling back to solsdr's
`status`. Set the frequency once via the driver and readback is exact.
"""

import math
import socket
import time
from typing import Generator, List, Optional, Tuple

import numpy as np

DEFAULT_CONTROL_PORT = 5556
DEFAULT_IQ_PORT = 5555
DEFAULT_RX2_IQ_PORT = 5557
DEFAULT_TX_IQ_PORT = 5558

# Modes solsdr's control API accepts (control_api.VALID_MODES).
MODES = ("USB", "LSB", "AM", "FM", "CW")

# SunSDR2 PRO coverage (from solsdr's RadioProfile; RX ~0.1–65 MHz + 2 m).
RX_MIN_HZ = 100_000
RX_MAX_HZ = 65_000_000


class SolSDRError(Exception):
    """Base error for the solsdr driver."""


class SolSDRConnectionError(SolSDRError):
    """Could not reach a solsdr server (is solsdr running with that server on?)."""


class SolSDRTimeoutError(SolSDRError):
    """A solsdr server did not respond in time."""


class SolSDRCommandError(SolSDRError):
    """solsdr replied ERR to a control command."""


class SolSDRTXBusyError(SolSDRError):
    """The TX-IQ server is already in use by another transmitter."""


def _welch_psd(iq: np.ndarray, fs: float, nperseg: int
               ) -> Tuple[np.ndarray, np.ndarray]:
    """Welch PSD (Hann window, 50% overlap), numpy-only (no scipy dependency).

    Returns (freq_rel_hz, psd_linear) with freq spanning -fs/2 .. +fs/2 and the
    DC bin centered (fftshift), matching a complex-baseband spectrum.
    """
    x = np.asarray(iq, dtype=np.complex64)
    if nperseg > len(x):
        nperseg = len(x)
    if nperseg < 8:
        nperseg = min(8, len(x))
    win = np.hanning(nperseg).astype(np.float64)
    win_norm = np.sum(win ** 2) * fs
    step = max(1, nperseg // 2)
    segs = []
    for start in range(0, len(x) - nperseg + 1, step):
        seg = x[start:start + nperseg] * win
        spec = np.fft.fftshift(np.fft.fft(seg))
        segs.append((np.abs(spec) ** 2) / win_norm)
    if not segs:
        seg = x[:nperseg] * win[:len(x[:nperseg])]
        spec = np.fft.fftshift(np.fft.fft(seg, n=nperseg))
        segs.append((np.abs(spec) ** 2) / win_norm)
    psd = np.mean(segs, axis=0)
    freq_rel = np.fft.fftshift(np.fft.fftfreq(nperseg, d=1.0 / fs))
    return freq_rel.astype(np.float64), psd.astype(np.float64)


class SolSDR:
    """Network client for a solsdr appliance.

    Args:
        host: IP/hostname of the machine running solsdr.
        control_port: solsdr control API port (--control-api, default 5556).
        iq_port: solsdr RX IQ server port (on by default, default 5555).
        rx2_iq_port: solsdr RX2 IQ server port (default 5557; used when
            ``rx=1`` and solsdr was launched with --rx2).
        tx_iq_port: solsdr TX IQ server port (--iq-tx-server, default 5558).
        timeout: socket timeout in seconds for control/IQ operations.
        rx: which receiver the IQ methods read (0 = RX1 :5555, 1 = RX2 :5557).
    """

    def __init__(self, host: str = "127.0.0.1", *,
                 control_port: int = DEFAULT_CONTROL_PORT,
                 iq_port: int = DEFAULT_IQ_PORT,
                 rx2_iq_port: int = DEFAULT_RX2_IQ_PORT,
                 tx_iq_port: int = DEFAULT_TX_IQ_PORT,
                 timeout: float = 5.0,
                 rx: int = 0):
        self.host = host
        self.control_port = int(control_port)
        self.iq_port = int(iq_port)
        self.rx2_iq_port = int(rx2_iq_port)
        self.tx_iq_port = int(tx_iq_port)
        self.timeout = float(timeout)
        self.rx = int(rx)

        self._ctrl: Optional[socket.socket] = None
        self._stream_sock: Optional[socket.socket] = None
        self._running = False

        # Driver-side shadow (control API only tracks what's set THROUGH it).
        self._last_freq: Optional[int] = None
        self._last_mode: Optional[str] = None
        # Sample rate + center freq learned from the RX IQ server header.
        self._sample_rate: Optional[float] = None
        self._iq_center_hz: Optional[int] = None

    # ── control socket ──────────────────────────────────────────────────────
    def _rx_iq_port(self) -> int:
        return self.rx2_iq_port if self.rx == 1 else self.iq_port

    def _connect_ctrl(self):
        try:
            self._ctrl = socket.create_connection(
                (self.host, self.control_port), timeout=self.timeout)
            self._ctrl.settimeout(self.timeout)
        except OSError as e:
            self._ctrl = None
            raise SolSDRConnectionError(
                f"cannot reach solsdr control API at {self.host}:"
                f"{self.control_port} — is solsdr running with --control-api? "
                f"({e})") from e

    def _command(self, line: str) -> str:
        """Send one control command, return the reply string (without newline).

        Raises SolSDRCommandError on an ERR reply, SolSDRTimeoutError on no
        reply, SolSDRConnectionError if the server is unreachable. Reconnects
        once on a dropped socket.
        """
        for attempt in (1, 2):
            if self._ctrl is None:
                self._connect_ctrl()
            try:
                self._ctrl.sendall((line + "\n").encode("utf-8"))
                buf = b""
                while b"\n" not in buf:
                    chunk = self._ctrl.recv(4096)
                    if not chunk:
                        raise OSError("connection closed")
                    buf += chunk
                reply = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
            except socket.timeout as e:
                raise SolSDRTimeoutError(
                    f"no reply to {line!r} from solsdr control API") from e
            except OSError:
                # socket died — drop it and retry once
                try:
                    self._ctrl.close()
                except OSError:
                    pass
                self._ctrl = None
                if attempt == 2:
                    raise SolSDRConnectionError(
                        f"lost connection to solsdr control API sending {line!r}")
                continue
            if reply.startswith("ERR"):
                raise SolSDRCommandError(f"{line!r} -> {reply}")
            return reply
        raise SolSDRConnectionError("control command failed")  # unreachable

    def ping(self) -> bool:
        """True if the solsdr control API answers."""
        try:
            return self._command("ping") == "OK pong"
        except SolSDRError:
            return False

    def status(self) -> dict:
        """Parse solsdr's `status` line into a dict.

        Returns keys: freq (int|None), mode (str|None), ptt (bool),
        power (float|None), streaming (int), smeter (float|None). Note freq/mode
        are solsdr's SHADOW state (what was set via the API), not live tuning.
        """
        reply = self._command("status")            # "OK freq=.. mode=.. ..."
        out: dict = {"freq": None, "mode": None, "ptt": False,
                     "power": None, "streaming": 0, "smeter": None}
        for tok in reply.split()[1:]:               # skip leading "OK"
            if "=" not in tok:
                continue
            k, v = tok.split("=", 1)
            if k == "freq":
                out["freq"] = int(v) if v not in ("None", "") else None
            elif k == "mode":
                out["mode"] = None if v in ("None", "") else v
            elif k == "ptt":
                out["ptt"] = (v == "on")
            elif k == "power":
                out["power"] = None if v in ("None", "") else float(v)
            elif k == "streaming":
                out["streaming"] = int(float(v))
            elif k == "smeter":
                out["smeter"] = float(v)
        return out

    def identify(self) -> dict:
        """Best-effort identity of the connected solsdr appliance."""
        st = self.status()
        return {
            "driver": "rf_bench.solsdr.SolSDR",
            "backend": "solsdr (ExpertSDR3-free SunSDR2 PRO)",
            "host": self.host,
            "control_port": self.control_port,
            "streaming": st["streaming"],
            "sample_rate": self.sample_rate,
        }

    # ── frequency / mode ─────────────────────────────────────────────────────
    def set_frequency(self, freq_hz: int) -> None:
        """Tune the radio (Hz). Range-checked against SunSDR2 PRO coverage."""
        freq_hz = int(freq_hz)
        if not (RX_MIN_HZ <= freq_hz <= RX_MAX_HZ):
            raise SolSDRError(
                f"{freq_hz} Hz outside SunSDR2 PRO coverage "
                f"({RX_MIN_HZ}–{RX_MAX_HZ} Hz)")
        self._command(f"freq {freq_hz}")
        self._last_freq = freq_hz

    def get_frequency(self) -> Optional[int]:
        """Current tuned frequency (Hz). Returns the last value set via this
        driver, falling back to solsdr's status shadow (may be None if nothing
        has set it through the API this session)."""
        if self._last_freq is not None:
            return self._last_freq
        return self.status()["freq"]

    def set_mode(self, mode: str) -> None:
        mode = mode.upper()
        if mode not in MODES:
            raise SolSDRError(f"invalid mode {mode!r}; valid: {', '.join(MODES)}")
        self._command(f"mode {mode}")
        self._last_mode = mode

    def get_mode(self) -> Optional[str]:
        if self._last_mode is not None:
            return self._last_mode
        return self.status()["mode"]

    # ── gain / DSP controls ──────────────────────────────────────────────────
    def set_preamp(self, state: str) -> None:
        """RX preamp/attenuator: '-20', '-10', '0', '+10' (dB), 'off', 'preamp'."""
        self._command(f"preamp {state}")

    def set_rf_gain(self, gain_db: float) -> None:
        """Alias for the shared radio API: maps dB to the nearest solsdr preamp/
        att step (-20/-10/0/+10). Bench code that targets IC-7300/FT-891 by
        `set_rf_gain()` then works unchanged here."""
        steps = [-20, -10, 0, 10]
        nearest = min(steps, key=lambda s: abs(s - gain_db))
        self.set_preamp(f"{'+' if nearest > 0 else ''}{nearest}")

    def set_rit(self, hz: float) -> None:
        """Receiver incremental tuning offset (Hz); 0 disables."""
        self._command(f"rit {hz:g}")

    def set_squelch(self, level: float) -> None:
        """Squelch threshold, 0–1."""
        self._command(f"sql {level:g}")

    def set_agc(self, mode: str) -> None:
        """AGC mode: 'auto', 'on', 'off', or 'fixed:<gain>'."""
        self._command(f"agc {mode}")

    def get_agc(self) -> Optional[str]:
        """solsdr has no AGC query over the control API; returns None."""
        return None

    def set_nr(self, level: float) -> None:
        """Noise reduction strength, 0–1."""
        self._command(f"nr {level:g}")

    def set_power(self, watts: float) -> None:
        """TX output setpoint in watts (per-band cal in solsdr; may be clamped
        by solsdr's amp-protection limit / refused on an uncalibrated band)."""
        self._command(f"power {watts:g}")

    # ── signal strength ──────────────────────────────────────────────────────
    def get_strength(self) -> float:
        """RX signal level in dBFS (solsdr's IQ-derived S-meter).

        NOTE: dBFS, not dBm — solsdr has no absolute power calibration on RX.
        Use the SSA for absolute amplitude.
        """
        reply = self._command("smeter")            # "OK smeter=-73.4"
        for tok in reply.split():
            if tok.startswith("smeter="):
                return float(tok.split("=", 1)[1])
        raise SolSDRError(f"could not parse smeter reply: {reply!r}")

    def get_strength_settled(self, settle_s: float = 0.3) -> float:
        """S-meter after a short settle (solsdr smooths internally too)."""
        time.sleep(settle_s)
        return self.get_strength()

    def set_ptt(self, tx: bool) -> None:
        """Not supported in solsdr's network model — keying happens by
        connecting to the TX-IQ server. Use :meth:`transmit_iq`."""
        raise NotImplementedError(
            "solsdr keys the radio by connecting to its TX-IQ server, not via a "
            "bare PTT toggle. Use transmit_iq() to send a waveform (which keys "
            "and unkeys automatically). solsdr must be launched with --iq-tx-"
            "server --tx-arm to actually radiate.")

    # ── sample rate (read-only) ──────────────────────────────────────────────
    @property
    def sample_rate(self) -> Optional[float]:
        """IQ sample rate (S/s), learned from the RX IQ server header. None
        until the first capture/stream/_peek_header call."""
        if self._sample_rate is None:
            try:
                self._peek_iq_header()
            except SolSDRError:
                return None
        return self._sample_rate

    def set_sample_rate(self, rate: int) -> None:
        """Not settable over the network — solsdr's rate is fixed at launch
        (`--rate`). Restart solsdr with a different --rate to change it."""
        raise NotImplementedError(
            "solsdr's IQ sample rate is set at launch with --rate "
            "(39062.5 / 78125 / 156250 / 312500) and is not changeable over the "
            "network. Read it via the .sample_rate property.")

    # ── RX IQ ────────────────────────────────────────────────────────────────
    def _open_iq_stream(self) -> socket.socket:
        port = self._rx_iq_port()
        try:
            s = socket.create_connection((self.host, port), timeout=self.timeout)
            s.settimeout(self.timeout)
        except OSError as e:
            raise SolSDRConnectionError(
                f"cannot reach solsdr IQ server at {self.host}:{port} — is "
                f"solsdr running"
                f"{' with --rx2' if self.rx == 1 else ''} (RX IQ is on by default; "
                f"check it wasn't started with --no-iq-server)? ({e})") from e
        header = self._read_header(s)
        self._parse_iq_header(header)
        return s

    def _read_header(self, s: socket.socket) -> str:
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(256)
            if not chunk:
                raise SolSDRConnectionError("IQ server closed before header")
            buf += chunk
            if len(buf) > 4096:
                break
        return buf.split(b"\n", 1)[0].decode("utf-8", "replace")

    def _parse_iq_header(self, header: str):
        # "SOLSDR IQ rate=39062.5 fmt=complex64 freq=14074000"
        for tok in header.split():
            if tok.startswith("rate="):
                self._sample_rate = float(tok.split("=", 1)[1])
            elif tok.startswith("freq="):
                try:
                    self._iq_center_hz = int(tok.split("=", 1)[1])
                except ValueError:
                    self._iq_center_hz = None

    def _peek_iq_header(self):
        """Open the IQ stream just long enough to learn rate + center freq."""
        s = self._open_iq_stream()
        try:
            s.close()
        except OSError:
            pass

    def capture_iq(self, num_samples: int = 65_536) -> np.ndarray:
        """Capture ``num_samples`` complex64 samples from the RX IQ server.

        The stream is continuous; this connects, reads exactly num_samples, and
        disconnects. Sample rate is whatever solsdr was launched with (see
        :attr:`sample_rate`).
        """
        need = int(num_samples) * 8                 # 8 bytes per complex64
        s = self._open_iq_stream()
        buf = bytearray()
        try:
            while len(buf) < need:
                chunk = s.recv(min(65536, need - len(buf)))
                if not chunk:
                    raise SolSDRConnectionError(
                        "IQ server closed mid-capture "
                        f"({len(buf)//8}/{num_samples} samples)")
                buf.extend(chunk)
        finally:
            try:
                s.close()
            except OSError:
                pass
        return np.frombuffer(bytes(buf[:need]), dtype=np.complex64).copy()

    def stream_iq(self, block_size: int = 65_536
                  ) -> Generator[np.ndarray, None, None]:
        """Yield complex64 blocks of ``block_size`` samples from the RX IQ
        server until :meth:`stop_stream` is called or the generator is closed."""
        need = int(block_size) * 8
        s = self._open_iq_stream()
        self._stream_sock = s
        self._running = True
        buf = bytearray()
        try:
            while self._running:
                try:
                    chunk = s.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf.extend(chunk)
                while len(buf) >= need:
                    block = np.frombuffer(bytes(buf[:need]),
                                          dtype=np.complex64).copy()
                    del buf[:need]
                    yield block
        finally:
            self._running = False
            try:
                s.close()
            except OSError:
                pass
            self._stream_sock = None

    def stop_stream(self) -> None:
        """Stop a :meth:`stream_iq` generator."""
        self._running = False
        if self._stream_sock is not None:
            try:
                self._stream_sock.close()
            except OSError:
                pass

    # ── spectrum / activity ──────────────────────────────────────────────────
    def power_spectrum(self, iq: np.ndarray, rbw_hz: float = 1000.0
                       ) -> Tuple[np.ndarray, np.ndarray]:
        """Welch PSD from an IQ capture.

        Power is RELATIVE (0 dB = peak bin) — solsdr RX has no absolute power
        cal; use the SSA for absolute amplitude. Frequencies are absolute
        (center ± rate/2) when the IQ header carried a center freq, else
        baseband (±rate/2).

        Returns ``(freq_hz, power_db)`` float32 arrays.
        """
        fs = self.sample_rate or 39062.5
        nperseg = int(fs / max(rbw_hz, 1.0))
        nperseg = max(64, 1 << int(math.log2(max(nperseg, 1))))
        nperseg = min(nperseg, len(iq))
        freq_rel, psd = _welch_psd(iq, float(fs), nperseg)
        center = self._iq_center_hz or 0
        freq_hz = (freq_rel + center).astype(np.float32)
        psd_db = (10.0 * np.log10(psd + 1e-30)).astype(np.float32)
        psd_db -= float(np.max(psd_db))
        return freq_hz, psd_db

    def scan_activity(self, threshold_db: float = 20.0,
                      num_samples: int = 65_536) -> List[dict]:
        """Capture one block and return detected signals above the noise floor.

        Returns ``[{'freq_hz': float, 'power_db': float}, ...]`` strongest first.
        """
        iq = self.capture_iq(num_samples)
        fs = self.sample_rate or 39062.5
        freq_hz, power_db = self.power_spectrum(iq, rbw_hz=fs / 512.0)
        noise = float(np.median(power_db))
        above = power_db > (noise + threshold_db) if threshold_db > 0 \
            else power_db > threshold_db
        signals: List[dict] = []
        in_sig = False
        start = 0
        for i in range(len(above)):
            if above[i] and not in_sig:
                start, in_sig = i, True
            elif not above[i] and in_sig:
                mid = (start + i) // 2
                signals.append({"freq_hz": float(freq_hz[mid]),
                                "power_db": float(power_db[mid])})
                in_sig = False
        if in_sig:
            mid = (start + len(above)) // 2
            signals.append({"freq_hz": float(freq_hz[mid]),
                            "power_db": float(power_db[mid])})
        return sorted(signals, key=lambda x: x["power_db"], reverse=True)

    # ── TX IQ (the superpower) ───────────────────────────────────────────────
    def transmit_iq(self, iq: np.ndarray, *, extra_settle_s: float = 0.5,
                    tx_sample_rate: Optional[float] = None) -> None:
        """Transmit raw complex baseband IQ out the antenna via solsdr's TX-IQ
        server. This is genuine arbitrary-waveform HF transmit — impossible on
        the TCI driver.

        Connecting to the TX-IQ server KEYS the radio; this method streams the
        samples, waits for them to be paced out (len/rate seconds + margin),
        then disconnects, which UNKEYS. Only one transmitter at a time.

        ⚠ REQUIREMENTS:
          * solsdr must be launched with --iq-tx-server, and with --tx-arm to
            actually radiate (without --tx-arm the chain runs with NO RF).
          * ``iq`` MUST be complex64 at the radio wire rate (see the TX header /
            :attr:`sample_rate`). There is NO resampler on this path — a rate
            mismatch transmits at the wrong speed.
          * Amateur licence + antenna, or a dummy load. solsdr will transmit out
            of band and enforces nothing legal.

        Args:
            iq: complex64 baseband samples at the wire rate.
            extra_settle_s: seconds to hold the connection open past the samples'
                natural duration, so solsdr's pacer fully drains before unkey.
            tx_sample_rate: override the assumed wire rate (else read from the TX
                header) for the drain-time calculation.
        """
        iq = np.ascontiguousarray(iq, dtype=np.complex64)
        if iq.size == 0:
            return
        try:
            s = socket.create_connection(
                (self.host, self.tx_iq_port), timeout=self.timeout)
            s.settimeout(self.timeout)
        except OSError as e:
            raise SolSDRConnectionError(
                f"cannot reach solsdr TX-IQ server at {self.host}:"
                f"{self.tx_iq_port} — is solsdr running with --iq-tx-server? "
                f"({e})") from e
        try:
            header = self._read_header(s)           # "SOLSDR IQTX rate=.. .."
            if header.startswith("ERR"):
                raise SolSDRTXBusyError(f"TX-IQ server refused: {header}")
            rate = tx_sample_rate
            if rate is None:
                for tok in header.split():
                    if tok.startswith("rate="):
                        rate = float(tok.split("=", 1)[1])
                        break
            rate = rate or self.sample_rate or 39062.5
            s.sendall(iq.tobytes())
            # Hold open until solsdr has paced all samples out, then unkey.
            drain_s = len(iq) / float(rate) + max(0.0, extra_settle_s)
            time.sleep(drain_s)
        finally:
            try:
                s.close()
            except OSError:
                pass

    # ── lifecycle ────────────────────────────────────────────────────────────
    def close(self) -> None:
        """Close driver sockets. Does NOT power off the radio (solsdr owns it)."""
        self.stop_stream()
        if self._ctrl is not None:
            try:
                self._ctrl.close()
            except OSError:
                pass
            self._ctrl = None

    def __enter__(self) -> "SolSDR":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
