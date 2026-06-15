"""
SunSDR2 Pro / ExpertSDR3 TCI driver for rf-bench.

Connects to ExpertSDR3 over its TCI (Transceiver Control Interface)
WebSocket API and provides both radio control (frequency, mode, PTT,
filter) and IQ streaming (capture_iq, stream_iq, power_spectrum),
plus TX IQ injection.

This is the most capable driver in the rf-bench collection: it combines
the control interface of rf_bench.icom/yaesu (cf. IC7300, FT891) with
the IQ streaming of rf_bench.rtlsdr/kiwisdr, adds TX, and supports two
simultaneous independent receivers.

Hardware:  SunSDR2 Pro (and compatible: SunSDR2 DX, MB1).
Protocol:  TCI v1.5+ via WebSocket (ExpertSDR3 default port 50001).

Frequency ranges (SunSDR2 Pro):
  RX/TX:  0.1 – 55 MHz    (HF + 6m)
  RX only: 100 – 150 MHz  (covers 2m: 144 MHz)

IQ rates and instantaneous bandwidth:
   48 000 S/s  →  ±24 kHz  ( 48 kHz)
   96 000 S/s  →  ±48 kHz  ( 96 kHz)
  192 000 S/s  →  ±96 kHz  (192 kHz)

Typical usage::

    from rf_bench.sunsdr import SunSDR

    with SunSDR("192.168.1.100") as sdr:
        sdr.set_frequency(14_074_000)
        sdr.set_mode("USB")
        sdr.set_sample_rate(192_000)
        iq = sdr.capture_iq(192_000)          # 1 second
        freq_hz, power_db = sdr.power_spectrum(iq, rbw_hz=500)

Dual simultaneous receivers (each opens its own WebSocket connection)::

    rx0 = SunSDR("192.168.1.100", trx=0)
    rx1 = SunSDR("192.168.1.100", trx=1)
    rx0.set_frequency(14_074_000)   # 20m FT8
    rx1.set_frequency(144_174_000)  # 2m FT8 (VHF receive-only port)

TX (amateur licence and appropriate antenna required)::

    with SunSDR("192.168.1.100") as sdr:
        sdr.set_frequency(14_074_000)
        sdr.set_mode("USB")
        sdr.set_ptt(True)
        sdr.transmit_iq(tx_samples)   # complex64 at current IQ rate
        sdr.set_ptt(False)

Protocol (TCI v2.0, Expert Electronics, January 2024):
    Text commands:   COMMAND:arg1,arg2,...;   (comma-separated args)
    Binary frames:   40-byte Stream struct header (8×uint32 LE + 8 reserved)
                     followed by sample data (float32 for IQ streams).

    TCI spec reference:
      ~/Dropbox/build/Hamlib/TCI_Protocol.pdf  (v2.0, January 2024)
"""

import math
import queue
import struct
import threading
import time
from typing import Any, Dict, Generator, List, Optional, Tuple

import numpy as np
import websocket as _websocket


# ── hardware / protocol constants ─────────────────────────────────────────────

DEFAULT_PORT       = 50001
DEFAULT_TRX        = 0
DEFAULT_IQ_RATE    = 48_000
VALID_IQ_RATES     = (48_000, 96_000, 192_000)

# SunSDR2 Pro RX frequency ranges (Hz).  TX is limited to the first range.
RX_RANGES: List[Tuple[int, int]] = [
    (100_000,     55_000_000),   # HF + 6m  (0.1 – 55 MHz)
    (100_000_000, 150_000_000),  # VHF      (100 – 150 MHz, covers 2m)
]
TX_RANGE: Tuple[int, int] = (100_000, 55_000_000)  # HF + 6m only

# TCI mode strings accepted by ExpertSDR3
MODES: Tuple[str, ...] = (
    "USB", "LSB", "CW", "CWR", "AM", "SAM", "DSB",
    "NFM", "WFM", "DIGU", "DIGL", "SPEC",
)

# Default RX filter passband (Hz, symmetric around carrier) per mode
DEFAULT_FILTER: Dict[str, Tuple[int, int]] = {
    "USB":  (0,     2_800),
    "LSB":  (-2_800, 0),
    "CW":   (-250,   250),
    "CWR":  (-250,   250),
    "AM":   (-4_000, 4_000),
    "SAM":  (-4_000, 4_000),
    "DSB":  (-2_800, 2_800),
    "NFM":  (-6_000, 6_000),
    "WFM":  (-80_000, 80_000),
    "DIGU": (0,     2_800),
    "DIGL": (-2_800, 0),
}

# TCI v2.0 binary Stream struct (all fields uint32_t little-endian, 40-byte header):
#   offset  0  receiver    — TRX index
#   offset  4  sample_rate — Hz
#   offset  8  format      — SampleType enum (see below)
#   offset 12  codec       — always 0
#   offset 16  crc         — always 0
#   offset 20  length      — number of real samples in data[]
#   offset 24  type        — StreamType enum (see below)
#   offset 28  channels    — 1 or 2
#   offset 32  reserv[8]   — reserved/zero
#   offset 40  data[]      — sample bytes
_STREAM_HDR_FMT = "<IIIIIIII8x"   # 8 × uint32 + 8 pad bytes = 40 bytes
_STREAM_HDR_LEN = 40

# StreamType enum
_STREAM_IQ_STREAM     = 0   # Receiver IQ signal stream
_STREAM_RX_AUDIO      = 1   # Receiver audio stream
_STREAM_TX_AUDIO      = 2   # Audio stream for transmitter
_STREAM_TX_CHRONO     = 3   # Time marker for TX audio handshake
_STREAM_LINEOUT       = 4   # Line-out audio stream

# SampleType enum
_SAMPLE_INT16   = 0
_SAMPLE_INT24   = 1   # not supported by this driver
_SAMPLE_INT32   = 2
_SAMPLE_FLOAT32 = 3


# ── exceptions ────────────────────────────────────────────────────────────────

class SunSDRError(RuntimeError):
    """Raised on TCI protocol errors, bad parameters, or device faults."""

class SunSDRConnectionError(SunSDRError):
    """Raised when the WebSocket connection to ExpertSDR3 fails."""

class SunSDRTimeoutError(SunSDRError):
    """Raised when a receive or command operation exceeds the timeout."""

class SunSDRFrequencyError(SunSDRError):
    """Raised when a requested frequency is outside all hardware RX ranges."""

class SunSDRModeError(SunSDRError):
    """Raised when an unsupported TCI mode string is requested."""


# ── TCI text parser ──────────────────────────────────────────────────────────

def _parse_tci(text: str) -> List[Tuple[str, List[str]]]:
    """
    Parse one WebSocket text frame into a list of (command, [args]) tuples.

    TCI v2.0 format: COMMAND:arg1,arg2,...;
    The colon separates command name from its argument list; arguments are
    comma-separated.  A single frame may contain multiple ';'-delimited events.

    E.g.  "VFO:0,0,14074000;MODULATION:0,USB;"  →
          [("vfo",        ["0", "0", "14074000"]),
           ("modulation", ["0", "USB"])]
    """
    events: List[Tuple[str, List[str]]] = []
    for raw in text.split(";"):
        raw = raw.strip()
        if not raw:
            continue
        if ":" in raw:
            name, arg_str = raw.split(":", 1)
            args = [a for a in arg_str.split(",") if a != ""]
        else:
            name, args = raw, []
        events.append((name.lower(), args))
    return events


# ── IQ frame parser ──────────────────────────────────────────────────────────

def _parse_iq(data: bytes) -> Optional[Tuple[int, np.ndarray]]:
    """
    Parse a TCI v2.0 binary WebSocket frame into (trx_index, complex64_array).

    Only accepts IQ_STREAM frames (StreamType = 0).  Audio and other stream
    types are silently ignored (return None).

    The 40-byte Stream struct header carries the TRX index, sample format,
    sample count, stream type, and channel count.  IQ data is always two-
    channel float32 (interleaved I, Q).

    Returns None if the frame is not an IQ frame or is malformed.
    """
    if len(data) < _STREAM_HDR_LEN + 8:   # header + at least one I/Q pair
        return None

    receiver    = struct.unpack_from("<I", data,  0)[0]
    fmt         = struct.unpack_from("<I", data,  8)[0]
    length      = struct.unpack_from("<I", data, 20)[0]   # total real samples
    stream_type = struct.unpack_from("<I", data, 24)[0]
    channels    = struct.unpack_from("<I", data, 28)[0]

    if stream_type != _STREAM_IQ_STREAM:
        return None
    if channels < 2 or length < 2:
        return None

    n_complex = length // channels   # spec: complex_count = length / channels
    if n_complex == 0:
        return None

    payload = data[_STREAM_HDR_LEN:]
    if fmt == _SAMPLE_FLOAT32:
        n_floats = n_complex * 2
        if len(payload) < n_floats * 4:
            n_complex = len(payload) // 8
        raw = np.frombuffer(payload[:n_complex * 8], dtype="<f4").reshape(n_complex, 2)
    elif fmt == _SAMPLE_INT32:
        n_ints = n_complex * 2
        if len(payload) < n_ints * 4:
            n_complex = len(payload) // 8
        raw32 = np.frombuffer(payload[:n_complex * 8], dtype="<i4").reshape(n_complex, 2)
        raw = raw32.astype("<f4") / 2_147_483_648.0
    else:
        return None   # INT16 / INT24 are not expected for IQ streams

    if len(raw) == 0:
        return None

    iq = (raw[:, 0] + 1j * raw[:, 1]).astype(np.complex64)
    return receiver, iq


# ── PSD helper ────────────────────────────────────────────────────────────────

def _welch_psd(
    iq: np.ndarray,
    sample_rate: float,
    nperseg: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Welch's method PSD (numpy-only).  Returns (freq_rel_hz, psd_linear)."""
    n      = len(iq)
    step   = max(1, nperseg // 2)
    window = np.hanning(nperseg).astype(np.float32)
    wpow   = float(np.sum(window ** 2))
    segs: List[np.ndarray] = []
    pos = 0
    while pos + nperseg <= n:
        seg = iq[pos : pos + nperseg] * window
        segs.append(np.abs(np.fft.fft(seg, n=nperseg)) ** 2)
        pos += step
    if not segs:
        raise SunSDRError("IQ block too short for the requested RBW")
    psd  = np.mean(segs, axis=0) / wpow
    freq = np.fft.fftfreq(nperseg, d=1.0 / sample_rate)
    return np.fft.fftshift(freq), np.fft.fftshift(psd)


# ── frequency range helpers ───────────────────────────────────────────────────

def _in_rx_range(freq_hz: int) -> bool:
    return any(lo <= freq_hz <= hi for lo, hi in RX_RANGES)

def _in_tx_range(freq_hz: int) -> bool:
    return TX_RANGE[0] <= freq_hz <= TX_RANGE[1]

def _rx_range_str() -> str:
    return "  /  ".join(f"{lo/1e6:.1f}–{hi/1e6:.0f} MHz" for lo, hi in RX_RANGES)


# ── main driver class ─────────────────────────────────────────────────────────

class SunSDR:
    """
    SunSDR2 Pro transceiver driver via ExpertSDR3 TCI.

    Combines radio control (like rf_bench.icom.IC7300) and IQ streaming
    (like rf_bench.rtlsdr.RTLSDR) in a single object, plus TX IQ injection.

    Args:
        host:     ExpertSDR3 host IP or hostname.
        port:     TCI WebSocket port (default 50001).
        trx:      Transceiver index, 0-based (0 = primary, 1 = second receiver).
        iq_rate:  Initial IQ output sample rate — 48000 / 96000 / 192000.
                  Higher rates give wider instantaneous bandwidth.
        timeout:  WebSocket and command timeout in seconds (default 10).
    """

    # Expose module-level constants as class attributes
    VALID_IQ_RATES = VALID_IQ_RATES
    RX_RANGES      = RX_RANGES
    TX_RANGE       = TX_RANGE
    MODES          = MODES

    def __init__(
        self,
        host:    str,
        port:    int   = DEFAULT_PORT,
        trx:     int   = DEFAULT_TRX,
        iq_rate: int   = DEFAULT_IQ_RATE,
        timeout: float = 10.0,
    ) -> None:
        self._host    = host
        self._port    = port
        self._trx     = trx
        self._timeout = float(timeout)

        # ── state cache — updated by background receiver thread ───────────────
        self._state: Dict[str, Any] = {
            "rx_freq":      14_000_000,
            "tx_freq":      14_000_000,
            "mode":         "USB",
            "ptt":          False,
            "tune":         False,
            "volume":       50.0,
            "iq_rate":      iq_rate,
            "filter_lo":    0,
            "filter_hi":    2_800,
            "squelch_on":   False,
            "squelch_thr":  -80.0,
            "device":       "SunSDR",
            "tci_version":  "unknown",
            "trx_count":    1,
            "ready":        False,
        }
        self._state_lock = threading.Lock()

        # ── queues ────────────────────────────────────────────────────────────
        self._event_q: queue.Queue  = queue.Queue(maxsize=512)
        self._iq_q:    queue.Queue  = queue.Queue(maxsize=64)

        # ── IQ / stream state ─────────────────────────────────────────────────
        self._iq_active      = False
        self._stream_stop:   Optional[threading.Event]  = None
        self._stream_thread: Optional[threading.Thread] = None

        # ── WebSocket and receiver thread ─────────────────────────────────────
        self._ws:      Optional[_websocket.WebSocket]  = None
        self._rx_stop  = threading.Event()
        self._rx_thread: Optional[threading.Thread]   = None

        self._connect(iq_rate)

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "SunSDR":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        return (f"SunSDR({self._host}:{self._port}  trx={self._trx}  "
                f"{self._state['rx_freq']/1e6:.4f} MHz  {self._state['mode']}  "
                f"IQ {self._state['iq_rate']//1000} kS/s)")

    # ── connection internals ──────────────────────────────────────────────────

    def _connect(self, initial_iq_rate: int) -> None:
        url = f"ws://{self._host}:{self._port}"
        try:
            ws = _websocket.WebSocket()
            ws.settimeout(self._timeout)
            ws.connect(url)
            self._ws = ws
        except _websocket.WebSocketException as exc:
            raise SunSDRConnectionError(
                f"WebSocket handshake failed at {url}: {exc}\n"
                "Verify ExpertSDR3 is running and TCI is enabled "
                "(Settings → TCI → Enable)."
            ) from exc
        except OSError as exc:
            raise SunSDRConnectionError(
                f"Cannot reach ExpertSDR3 at {self._host}:{self._port}: {exc}\n"
                "Check the host address and that ExpertSDR3 is running."
            ) from exc

        # Start background receiver before any sends
        self._rx_stop.clear()
        self._rx_thread = threading.Thread(
            target=self._receiver_loop,
            daemon=True,
            name=f"sunsdr-rx-{self._trx}",
        )
        self._rx_thread.start()

        # Collect initial state (ExpertSDR3 sends a burst of events on connect)
        self._wait_for_ready()

        # Apply requested IQ rate if different from state default
        if initial_iq_rate != self._state["iq_rate"]:
            self.set_sample_rate(initial_iq_rate)

    def _receiver_loop(self) -> None:
        """Background thread: receive all TCI messages and dispatch."""
        while not self._rx_stop.is_set():
            try:
                data = self._ws.recv()
            except _websocket.WebSocketTimeoutException:
                continue
            except Exception:
                self._rx_stop.set()
                break

            if isinstance(data, str):
                for cmd, args in _parse_tci(data):
                    self._handle_event(cmd, args)
            elif isinstance(data, bytes):
                result = _parse_iq(data)
                if result is not None:
                    trx_idx, iq = result
                    if trx_idx == self._trx:
                        try:
                            self._iq_q.put_nowait(iq)
                        except queue.Full:
                            try: self._iq_q.get_nowait()
                            except queue.Empty: pass
                            try: self._iq_q.put_nowait(iq)
                            except queue.Full: pass

    def _handle_event(self, cmd: str, args: List[str]) -> None:
        """Update state cache from a parsed TCI v2.0 text event."""
        try:
            with self._state_lock:
                if cmd == "vfo" and len(args) >= 3:
                    # VFO:receiver,channel,freq  — channel 0=A (RX), 1=B (TX/split)
                    if int(args[0]) == self._trx:
                        ch = args[1]
                        if ch in ("0", "a", "A"):
                            self._state["rx_freq"] = int(args[2])
                        elif ch in ("1", "b", "B"):
                            self._state["tx_freq"] = int(args[2])
                elif cmd == "dds" and len(args) >= 2:
                    # DDS:receiver,freq — panorama centre; fallback if VFO not yet seen
                    if int(args[0]) == self._trx and self._state["rx_freq"] == 14_000_000:
                        self._state["rx_freq"] = int(args[1])
                elif cmd == "tx_frequency" and len(args) >= 1:
                    # TX_FREQUENCY:freq — server-only TX frequency notification (no TRX arg)
                    self._state["tx_freq"] = int(args[0])
                elif cmd == "modulation" and len(args) >= 2:
                    if int(args[0]) == self._trx:
                        self._state["mode"] = args[1].upper()
                elif cmd == "trx" and len(args) >= 2:
                    # TRX:receiver,true/false — PTT state
                    if int(args[0]) == self._trx:
                        self._state["ptt"] = args[1].lower() in ("true", "1")
                elif cmd == "tune" and len(args) >= 2:
                    if int(args[0]) == self._trx:
                        self._state["tune"] = args[1].lower() in ("true", "1")
                elif cmd == "volume" and len(args) >= 1:
                    # VOLUME:dB  range -60..0; map to 0..100 for API compatibility
                    db = float(args[0])
                    self._state["volume"] = max(0.0, min(100.0, (db + 60.0) / 60.0 * 100.0))
                elif cmd == "iq_samplerate" and len(args) >= 1:
                    self._state["iq_rate"] = int(args[0])
                elif cmd == "rx_filter_band" and len(args) >= 3:
                    if int(args[0]) == self._trx:
                        self._state["filter_lo"] = int(args[1])
                        self._state["filter_hi"] = int(args[2])
                elif cmd == "sql_enable" and len(args) >= 2:
                    if int(args[0]) == self._trx:
                        self._state["squelch_on"] = args[1].lower() in ("true", "1")
                elif cmd == "sql_level" and len(args) >= 2:
                    if int(args[0]) == self._trx:
                        self._state["squelch_thr"] = float(args[1])
                elif cmd == "device" and len(args) >= 1:
                    self._state["device"] = args[0]
                elif cmd == "protocol" and len(args) >= 2:
                    self._state["tci_version"] = args[1]
                elif cmd == "trx_count" and len(args) >= 1:
                    self._state["trx_count"] = int(args[0])
                elif cmd == "ready":
                    self._state["ready"] = True
        except (ValueError, IndexError):
            pass  # ignore malformed events

        try:
            self._event_q.put_nowait((cmd, args))
        except queue.Full:
            pass

    def _wait_for_ready(self) -> None:
        """
        Wait for ExpertSDR3 to send the 'ready;' event, or timeout.

        Some firmware versions omit 'ready;'; in that case we fall through
        after collecting events for the timeout period.
        """
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            with self._state_lock:
                if self._state["ready"]:
                    return
            time.sleep(0.05)
        # Continue even without 'ready' — the state cache will have been
        # populated by whatever events arrived during the wait.

    def _send(self, command: str) -> None:
        """Send a TCI text command, appending ';' if absent."""
        if not command.endswith(";"):
            command += ";"
        try:
            self._ws.send(command)
        except _websocket.WebSocketException as exc:
            raise SunSDRError(f"TCI send failed: {exc}") from exc

    def _wait_for(self, cmd: str, timeout: Optional[float] = None) -> Tuple[str, List[str]]:
        """Wait for a specific TCI event type and return its args."""
        deadline = time.monotonic() + (timeout or self._timeout)
        while time.monotonic() < deadline:
            try:
                ev_cmd, args = self._event_q.get(timeout=0.1)
                if ev_cmd == cmd.lower():
                    return ev_cmd, args
            except queue.Empty:
                continue
        raise SunSDRTimeoutError(f"Timeout waiting for TCI event '{cmd}'")

    # ── identification ────────────────────────────────────────────────────────

    def identify(self) -> dict:
        """Return a snapshot of connection parameters and current radio state."""
        with self._state_lock:
            return {
                "host":        self._host,
                "port":        self._port,
                "trx":         self._trx,
                "device":      self._state["device"],
                "tci_version": self._state["tci_version"],
                "trx_count":   self._state["trx_count"],
                "rx_freq":     self._state["rx_freq"],
                "tx_freq":     self._state["tx_freq"],
                "mode":        self._state["mode"],
                "ptt":         self._state["ptt"],
                "iq_rate":     self._state["iq_rate"],
                "filter_lo":   self._state["filter_lo"],
                "filter_hi":   self._state["filter_hi"],
            }

    def send_raw(self, command: str) -> None:
        """Send raw TCI command to SunSDR/ExpertSDR3 WebSocket.

        This is an "escape hatch" for sending commands not yet wrapped by the driver.

        Args:
            command: TCI command string (semicolon will be appended if missing)

        Examples:
            >>> sdr.send_raw("RX_MUTE:0,true;")  # Mute receiver
            >>> sdr.send_raw("CW_MACROS_SPEED:25")  # Set CW speed
            >>> sdr.send_raw("DRIVE:0,50")  # Set TX drive level

        Warning:
            Use with caution. Invalid commands may put the radio in an
            unexpected state. Consult the TCI 2.0 protocol specification:
            https://github.com/ExpertSDR3/TCI
        """
        self._send(command)

    # ── radio control — frequency ─────────────────────────────────────────────

    def get_frequency(self) -> int:
        """Return the current RX frequency in Hz (from state cache)."""
        with self._state_lock:
            return self._state["rx_freq"]

    def set_frequency(self, freq_hz: int) -> None:
        """
        Set the RX (and TX) frequency in Hz.

        Valid ranges: 0.1–55 MHz, 100–150 MHz.
        Raises SunSDRFrequencyError if outside all RX ranges.
        TX is only possible in the 0.1–55 MHz range.
        """
        freq_hz = int(freq_hz)
        if not _in_rx_range(freq_hz):
            raise SunSDRFrequencyError(
                f"{freq_hz/1e6:.4f} MHz is outside SunSDR2 Pro RX ranges "
                f"({_rx_range_str()})"
            )
        self._send(f"VFO:{self._trx},0,{freq_hz}")   # channel 0 = VFO A (RX)
        if _in_tx_range(freq_hz):
            self._send(f"VFO:{self._trx},1,{freq_hz}")   # channel 1 = VFO B (TX)

    def get_tx_frequency(self) -> int:
        """Return the current TX frequency in Hz."""
        with self._state_lock:
            return self._state["tx_freq"]

    def set_tx_frequency(self, freq_hz: int) -> None:
        """Set the TX frequency independently of RX (split operation)."""
        freq_hz = int(freq_hz)
        if not _in_tx_range(freq_hz):
            raise SunSDRFrequencyError(
                f"{freq_hz/1e6:.4f} MHz is outside TX range "
                f"({TX_RANGE[0]/1e6:.1f}–{TX_RANGE[1]/1e6:.0f} MHz)"
            )
        self._send(f"VFO:{self._trx},1,{freq_hz}")   # channel 1 = VFO B (TX/split)

    # ── radio control — mode ──────────────────────────────────────────────────

    def get_mode(self) -> str:
        """Return the current demodulation mode string (e.g. 'USB')."""
        with self._state_lock:
            return self._state["mode"]

    def set_mode(self, mode: str, apply_default_filter: bool = True) -> None:
        """
        Set the demodulation mode.

        Valid: USB LSB CW CWR AM SAM DSB NFM WFM DIGU DIGL SPEC

        Args:
            mode:                 Mode string (case-insensitive).
            apply_default_filter: Apply the standard filter for this mode
                                  (e.g. USB → 0–2800 Hz).  Default True.
        """
        mode = mode.upper()
        if mode not in MODES:
            raise SunSDRModeError(
                f"'{mode}' is not a valid TCI mode.  Valid: {', '.join(MODES)}"
            )
        self._send(f"MODULATION:{self._trx},{mode}")
        if apply_default_filter and mode in DEFAULT_FILTER:
            lo, hi = DEFAULT_FILTER[mode]
            self.set_rx_filter(lo, hi)

    # ── radio control — receiver ──────────────────────────────────────────────

    def set_rx_filter(self, lo_hz: int, hi_hz: int) -> None:
        """
        Set the RX filter passband (Hz, relative to carrier frequency).

        Examples:
            USB 2.8 kHz:   set_rx_filter(0,      2800)
            LSB 2.8 kHz:   set_rx_filter(-2800,  0)
            CW  500 Hz:    set_rx_filter(-250,    250)
            AM  8 kHz:     set_rx_filter(-4000,   4000)
        """
        self._send(f"RX_FILTER_BAND:{self._trx},{int(lo_hz)},{int(hi_hz)}")

    def set_volume(self, volume: float) -> None:
        """Set audio output volume (0–100); mapped to TCI VOLUME range of -60..0 dB."""
        pct = max(0.0, min(100.0, float(volume)))
        db  = pct / 100.0 * 60.0 - 60.0   # 0→-60 dB, 100→0 dB
        self._send(f"VOLUME:{db:.0f}")

    def get_volume(self) -> float:
        """Return the current audio volume (0–100)."""
        with self._state_lock:
            return self._state["volume"]

    def set_squelch(self, enable: bool, threshold_dbfs: float = -80.0) -> None:
        """
        Enable or disable squelch.

        Args:
            enable:          True to enable squelch.
            threshold_dbfs:  Open threshold in dBFS (negative, e.g. −80).
        """
        self._send(f"SQL_ENABLE:{self._trx},{'true' if enable else 'false'}")
        if enable:
            self._send(f"SQL_LEVEL:{self._trx},{threshold_dbfs:.1f}")

    def set_rf_gain(self, gain_db: float) -> None:
        """
        Adjust RF gain via preamp / attenuator.

        Positive values suggest preamp; negative values apply attenuation.
        The exact TCI commands for preamp and attenuation vary by ExpertSDR3
        version — these are best-effort approximations.  Use send_raw() for
        precise control once you know your firmware's command names.
        """
        # Note: TCI v2.0 does not define standard preamp/attenuator commands.
        # These are ExpertSDR3-specific extensions that may vary by firmware version.
        if gain_db >= 10:
            self._send(f"rx_preamp:{self._trx},1")
            self._send(f"rx_att:{self._trx},0")
        elif gain_db <= -10:
            att = min(40, abs(int(gain_db)))
            self._send(f"rx_preamp:{self._trx},0")
            self._send(f"rx_att:{self._trx},{att}")
        else:
            self._send(f"rx_preamp:{self._trx},0")
            self._send(f"rx_att:{self._trx},0")

    # ── radio control — TX ────────────────────────────────────────────────────

    def get_ptt(self) -> bool:
        """Return True if PTT is currently active."""
        with self._state_lock:
            return self._state["ptt"]

    def set_ptt(self, tx: bool) -> None:
        """
        Enable (True) or disable (False) PTT.

        IMPORTANT: Ensure a suitable antenna or dummy load is connected,
        power is appropriate, and you hold a valid amateur radio licence
        for the frequency and power level before enabling TX.
        """
        self._send(f"TRX:{self._trx},{'true' if tx else 'false'}")

    def set_tune(self, enable: bool) -> None:
        """Enable or disable the built-in carrier/tune tone."""
        self._send(f"TUNE:{self._trx},{'true' if enable else 'false'}")

    # ── signal strength ───────────────────────────────────────────────────────

    def get_strength(self) -> float:
        """
        Return approximate signal strength in dBFS.

        Captures a brief IQ block and returns the RMS power level.
        This is relative (not calibrated to dBm); use the rx-crosscheck
        project to build a calibration against a known S-meter reference.
        """
        iq = self.capture_iq(4_096)
        return float(10.0 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-30))

    def get_strength_settled(self, settle_s: float = 0.1) -> float:
        """Return signal strength after a brief settle delay."""
        time.sleep(settle_s)
        return self.get_strength()

    # ── IQ rate ───────────────────────────────────────────────────────────────

    def set_sample_rate(self, rate: int) -> None:
        """
        Set the IQ output sample rate in S/s.

        Valid values: 48 000 / 96 000 / 192 000.
        The rate applies globally to all TRX; all capture_iq() calls on all
        SunSDR instances connected to the same ExpertSDR3 will see the new rate.

        Higher rates give wider instantaneous bandwidth:
            48 kHz  → ±24 kHz  passband
            96 kHz  → ±48 kHz  passband
           192 kHz  → ±96 kHz  passband (scan 40m in 3 captures)
        """
        rate = int(rate)
        if rate not in VALID_IQ_RATES:
            raise SunSDRError(
                f"IQ rate {rate} not valid.  Choose from {VALID_IQ_RATES}."
            )
        self._send(f"IQ_SAMPLERATE:{rate}")
        with self._state_lock:
            self._state["iq_rate"] = rate

    @property
    def sample_rate(self) -> int:
        """Current IQ sample rate in S/s."""
        with self._state_lock:
            return self._state["iq_rate"]

    # ── IQ streaming ─────────────────────────────────────────────────────────

    def _start_iq(self) -> None:
        if not self._iq_active:
            self._send(f"IQ_START:{self._trx}")
            self._iq_active = True

    def _stop_iq(self) -> None:
        if self._iq_active:
            try:
                self._send(f"IQ_STOP:{self._trx}")
            except SunSDRError:
                pass
            self._iq_active = False

    def capture_iq(self, num_samples: int = 65_536) -> np.ndarray:
        """
        Capture a block of IQ samples synchronously.

        Starts the IQ stream if not already running, accumulates binary frames
        until *num_samples* complex samples have been collected, then returns
        exactly *num_samples* samples as a complex64 array.

        Sample counts by duration at common IQ rates:
            @  48 kHz:  48 000 samples = 1.0 s  |  65 536 ≈ 1.4 s
            @  96 kHz:  96 000 samples = 1.0 s  |  65 536 ≈ 0.7 s
            @ 192 kHz: 192 000 samples = 1.0 s  |  65 536 ≈ 0.3 s

        Args:
            num_samples: Number of complex samples.

        Returns:
            complex64 numpy array of exactly *num_samples* samples.
        """
        self._start_iq()
        chunks: List[np.ndarray] = []
        collected = 0
        rate      = self._state.get("iq_rate", DEFAULT_IQ_RATE)
        deadline  = time.monotonic() + self._timeout + num_samples / max(1, rate) + 1.0

        while collected < num_samples:
            if time.monotonic() > deadline:
                raise SunSDRTimeoutError(
                    f"Timeout collecting {num_samples} IQ samples.  "
                    "Verify TCI IQ streaming is enabled in ExpertSDR3 "
                    "(Settings → TCI → IQ) and the transceiver is active."
                )
            try:
                chunk = self._iq_q.get(timeout=1.0)
                chunks.append(chunk)
                collected += len(chunk)
            except queue.Empty:
                continue

        return np.concatenate(chunks)[:num_samples].astype(np.complex64)

    def stream_iq(self, block_size: int = 65_536) -> Generator[np.ndarray, None, None]:
        """
        Yield IQ blocks continuously as a generator of complex64 arrays.

        Example::

            sdr.set_frequency(14_074_000)
            sdr.set_mode("USB")
            sdr.set_sample_rate(192_000)
            for block in sdr.stream_iq(192_000):   # 1-second blocks
                process(block)
                if done:
                    break
            sdr.stop_stream()

        Args:
            block_size: Complex samples per yielded block.

        Yields:
            complex64 numpy arrays of exactly *block_size* samples.
        """
        if self._stream_thread is not None and self._stream_thread.is_alive():
            raise SunSDRError(
                "A stream is already active on this TRX; call stop_stream() first."
            )

        self._start_iq()
        self._stream_stop  = threading.Event()
        out_q  = queue.Queue(maxsize=32)
        stop_e = self._stream_stop

        def _assembler() -> None:
            buf: List[np.ndarray] = []
            count = 0
            try:
                while not stop_e.is_set():
                    try:
                        chunk = self._iq_q.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    buf.append(chunk)
                    count += len(chunk)
                    while count >= block_size:
                        merged = np.concatenate(buf)
                        try:
                            out_q.put_nowait(merged[:block_size].astype(np.complex64))
                        except queue.Full:
                            pass
                        remainder = merged[block_size:]
                        buf   = [remainder] if len(remainder) else []
                        count = len(remainder)
            finally:
                stop_e.set()

        self._stream_thread = threading.Thread(
            target=_assembler, daemon=True, name=f"sunsdr-stream-{self._trx}"
        )
        self._stream_thread.start()

        try:
            while not stop_e.is_set() or not out_q.empty():
                try:
                    yield out_q.get(timeout=0.5)
                except queue.Empty:
                    continue
        finally:
            stop_e.set()

    def stop_stream(self) -> None:
        """Stop an active stream_iq() generator."""
        if self._stream_stop is not None:
            self._stream_stop.set()
        thread = self._stream_thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._stream_thread = None
        self._stream_stop   = None

    # ── spectrum ──────────────────────────────────────────────────────────────

    def power_spectrum(
        self,
        iq:      np.ndarray,
        rbw_hz:  float = 1_000.0,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute power spectral density from a capture_iq() block.

        Uses Welch's method (Hann window, 50% overlap).  Power is normalised
        to 0 dB at the peak bin (relative, not calibrated dBm).

        Args:
            iq:      complex64 array from capture_iq().
            rbw_hz:  Desired resolution bandwidth (Hz).
                     At 192 kHz rate, 1 kHz RBW requires ≥192 samples.

        Returns:
            (freq_hz, power_db) — float32 arrays.  freq_hz gives absolute
            frequencies centred on the current RX frequency.
        """
        rate    = self._state.get("iq_rate", DEFAULT_IQ_RATE)
        nperseg = int(rate / max(rbw_hz, 1.0))
        nperseg = max(64, 1 << int(math.log2(max(nperseg, 1))))
        nperseg = min(nperseg, len(iq))

        freq_rel, psd = _welch_psd(iq, float(rate), nperseg)

        freq_hz = (freq_rel + self._state["rx_freq"]).astype(np.float32)
        psd_db  = (10.0 * np.log10(psd + 1e-30)).astype(np.float32)
        psd_db -= float(np.max(psd_db))
        return freq_hz, psd_db

    def scan_activity(
        self,
        threshold_db:  float = -20.0,
        num_samples:   int   = 65_536,
    ) -> List[dict]:
        """
        Detect signals within the current IQ passband.

        At 192 kHz rate, the passband is ±96 kHz — a single capture can
        scan the entire width of most HF amateur sub-bands in one shot.

        Returns:
            List of {'freq_hz': float, 'power_db': float}, strongest-first.
        """
        iq = self.capture_iq(num_samples)
        freq_hz, power_db = self.power_spectrum(iq, rbw_hz=500.0)

        noise = float(np.median(power_db))
        above = power_db > (noise + threshold_db)

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
        start_hz:       int,
        stop_hz:        int,
        step_hz:        int   = 100_000,
        threshold_db:   float = -20.0,
        dwell_samples:  int   = 65_536,
        settle_s:       float = 0.02,
    ) -> List[dict]:
        """
        Sweep a frequency range and return detected signals.

        At 192 kHz rate the default 100 kHz step provides ≈2× overlap for
        reliable detection.  The 40m band (7.0–7.3 MHz, 300 kHz) takes only
        3 captures.  Compare: KiwiSDR needs 30 steps for the same band.

        Args:
            start_hz:      Start frequency (Hz).
            stop_hz:       Stop frequency (Hz).
            step_hz:       Frequency step (Hz; default 100 kHz).
            threshold_db:  Detection threshold above noise floor (dB).
            dwell_samples: IQ samples per step.
            settle_s:      Settle time after retuning (seconds).

        Returns:
            List of {'freq_hz', 'power_db'} dicts, strongest-first.
        """
        results: List[dict] = []
        freq = int(start_hz)
        while freq <= int(stop_hz):
            try:
                self.set_frequency(freq)
                if settle_s > 0:
                    time.sleep(settle_s)
                results.extend(self.scan_activity(threshold_db, dwell_samples))
            except (SunSDRError, SunSDRFrequencyError):
                pass
            freq += int(step_hz)
        return sorted(results, key=lambda x: x["power_db"], reverse=True)

    # ── TX IQ injection ───────────────────────────────────────────────────────

    def transmit_iq(self, iq: np.ndarray) -> None:
        """
        Inject a block of IQ samples into the TX chain.

        The sample rate of *iq* must match the current IQ rate
        (set via set_sample_rate()).  PTT must be active.

        The frame format mirrors the RX IQ frame format with stream_type = 1
        (TX).  Exact framing behaviour should be verified against your
        ExpertSDR3 firmware version.

        WARNING: Transmitting on amateur frequencies requires a valid licence
        and appropriate antenna/power levels.  Always start with a dummy load.

        Args:
            iq: complex64 numpy array of TX samples.
        """
        iq_c64 = iq.astype(np.complex64)
        raw    = np.empty(len(iq_c64) * 2, dtype="<f4")
        raw[0::2] = iq_c64.real
        raw[1::2] = iq_c64.imag

        rate     = self._state.get("iq_rate", DEFAULT_IQ_RATE)
        n_total  = len(raw)   # total real samples (2× complex count)
        # Build 40-byte Stream header: TX_AUDIO_STREAM, float32, 2-channel (I/Q)
        header = struct.pack(
            _STREAM_HDR_FMT,
            self._trx,           # receiver
            rate,                # sample_rate
            _SAMPLE_FLOAT32,     # format
            0,                   # codec (always 0)
            0,                   # crc   (always 0)
            n_total,             # length (real sample count)
            _STREAM_TX_AUDIO,    # type = TX_AUDIO_STREAM
            2,                   # channels (I and Q)
        )
        payload = header + raw.tobytes()
        try:
            self._ws.send_binary(payload)
        except _websocket.WebSocketException as exc:
            raise SunSDRError(f"TX IQ binary send failed: {exc}") from exc

    # ── close ─────────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Stop all streams, send TCI stop, and close the WebSocket."""
        self.stop_stream()
        try:
            self._stop_iq()
        except Exception:
            pass
        # Ensure PTT is off before disconnecting
        try:
            if self._state.get("ptt"):
                self.set_ptt(False)
                time.sleep(0.05)
        except Exception:
            pass
        self._rx_stop.set()
        if self._rx_thread is not None:
            self._rx_thread.join(timeout=3.0)
        if self._ws is not None:
            try:
                self._send("stop")
            except Exception:
                pass
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
