"""
ssa3000x.py — Siglent SSA 3000X Plus spectrum analyzer driver

Connects via raw TCP/SCPI to port 5025. No pyvisa dependency.

Model: Siglent SSA 3000X Plus (9 kHz – 3.2 GHz)
Default address: 10.1.1.60:5025

Key firmware quirk: some firmware versions use `:TRACE1:DATA?` instead of
`:TRAC:DATA? TRC1` for trace readback. If get_trace() returns empty, try
the alternate command by subclassing and overriding get_trace().
"""

import socket
import time

import numpy as np

from rf_bench.utils.rf_utils import nearest_rbw


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HOST        = "10.1.1.60"
DEFAULT_PORT        = 5025
DEFAULT_POINTS      = 1001     # sweep points; Siglent supports 101–3601
DEFAULT_TG_LEVEL    = 0.0      # dBm; max TG output (range −20 to 0 dBm)
CONNECT_TIMEOUT     = 10       # seconds
SWEEP_TIMEOUT       = 120      # seconds; HF sweeps with narrow RBW can be slow


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class SSA3000X:
    """
    SCPI-over-TCP driver for the Siglent SSA 3000X Plus spectrum analyzer.

    Usage:
        ssa = SSA3000X("10.1.1.60")
        ssa.connect()
        print(ssa.identify())
        ssa.enable_tracking_generator(tg_level_dbm=0)
        ssa.setup_band(7_000_000, 7_300_000, points=1001)
        ssa.single_sweep()
        trace = ssa.get_trace()   # numpy array of dBm values
        ssa.disable_tracking_generator()
        ssa.disconnect()

    Context manager:
        with SSA3000X("10.1.1.60") as ssa:
            ssa.setup_band(...)
            ...
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host  = host
        self.port  = port
        self._sock: socket.socket | None = None
        self.connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self):
        """Open TCP connection to the instrument."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(CONNECT_TIMEOUT)
        self._sock.connect((self.host, self.port))
        time.sleep(0.3)

    def disconnect(self):
        """Close the TCP connection."""
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def close(self):
        """Close the connection (alias for disconnect)."""
        try:
            self.disable_tracking_generator()
        except Exception:
            pass
        self.disconnect()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    def _send(self, cmd: str) -> None:
        self._sock.sendall((cmd + "\n").encode("ascii"))
        time.sleep(0.04)

    def _recv(self, timeout: float = 10.0) -> str:
        self._sock.settimeout(timeout)
        buf = bytearray()
        while True:
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    break
                buf.extend(chunk)
                if buf[-1:] in (b"\n", b">"):
                    break
            except socket.timeout:
                break
        return buf.decode("ascii", errors="replace").strip()

    def write(self, cmd: str) -> None:
        """Send a command with no response expected."""
        self._send(cmd)

    def query(self, cmd: str, timeout: float = 10.0) -> str:
        """Send a command and return the response string."""
        self._send(cmd)
        return self._recv(timeout)

    # ------------------------------------------------------------------
    # Instrument commands
    # ------------------------------------------------------------------

    def identify(self) -> str:
        """Return the IDN string."""
        return self.query("*IDN?")

    def preset(self) -> None:
        """Preset the instrument to factory defaults. Takes ~2 s."""
        self.write(":SYST:PRES")
        time.sleep(2.0)

    def enable_tracking_generator(self, tg_level_dbm: float = DEFAULT_TG_LEVEL) -> bool:
        """
        Enable the tracking generator output at the specified level.

        Args:
            tg_level_dbm: Output level in dBm (range −20 to 0 on SSA3000X Plus).
                          0 dBm = maximum output; best SNR for reflection measurements.

        Returns:
            True if TG confirmed on, False if state query returned unexpected value.

        Note: Always recalibrate after changing tg_level_dbm — the calibration
        reference was taken at a specific level and changing it invalidates it.
        """
        self.write(f":OUTP:LEV {tg_level_dbm:.1f}")
        self.write(":OUTP:STAT ON")
        time.sleep(0.5)
        state = self.query(":OUTP:STAT?")
        return state.strip() in ("1", "ON")

    def disable_tracking_generator(self) -> None:
        """Disable the tracking generator output."""
        try:
            self.write(":OUTP:STAT OFF")
        except OSError:
            pass

    def get_sweep_points(self) -> int:
        """Return the actual number of sweep points the firmware is using."""
        return int(self.query(":SENS:SWE:POIN?").strip())

    def setup_band(self, start_hz: int, stop_hz: int,
                   points: int = DEFAULT_POINTS) -> int:
        """
        Configure the analyzer for a frequency span.

        Sets start/stop frequency, sweep points, and auto-selects RBW/VBW
        using the Siglent 1-3-10 standard sequence.

        Args:
            start_hz: Start frequency in Hz
            stop_hz:  Stop frequency in Hz
            points:   Requested sweep points (101–3601; default 1001).
                      Some firmware versions (e.g. SSA3032X Plus 3.2.x) ignore
                      this command; call get_sweep_points() to read the actual
                      count after setup.

        Returns:
            The RBW actually set (Hz).
        """
        span_hz    = stop_hz - start_hz
        actual_pts = self.get_sweep_points()
        target_rbw = max(1_000, span_hz / actual_pts * 3)
        rbw        = nearest_rbw(target_rbw)

        self.write(f":FREQ:STAR {int(start_hz)}")
        self.write(f":FREQ:STOP {int(stop_hz)}")
        self.write(f":SENS:SWE:POIN {points}")
        self.write(f":SENS:BAND:RES {rbw}")
        self.write(f":SENS:BAND:VID {rbw}")
        self.write(":DISP:WIND:TRAC:Y:RLEV 0")
        self.write(":DISP:WIND:TRAC:Y:SCAL:PDIV 10")
        return rbw

    def single_sweep(self) -> bool:
        """
        Trigger a single sweep and block until it completes.

        Returns:
            True if *OPC? returned "1" (sweep finished cleanly).
            False on timeout (sweep may still have data, but timing is uncertain).
        """
        self.write(":INIT:CONT OFF")
        self.write(":INIT:IMM")
        result = self.query("*OPC?", timeout=SWEEP_TIMEOUT)
        return result.strip() == "1"

    def get_trace(self) -> np.ndarray:
        """
        Read trace 1 and return a numpy array of dBm values.

        Parses both ASCII CSV format and IEEE 488.2 binary block format.

        Firmware note: some versions use `:TRACE1:DATA?` instead of
        `:TRAC:DATA? TRC1`. If this returns an empty array, try overriding
        with the alternate command.
        """
        raw = self.query(":TRAC:DATA? TRC1", timeout=30.0)
        return self._parse_trace(raw)

    def continuous_sweep(self) -> None:
        """Return to free-running continuous sweep mode."""
        self.write(":INIT:CONT ON")

    def set_ref_level(self, dbm: float) -> None:
        """Set the display reference level (top of screen) in dBm."""
        self.write(f":DISP:WIND:TRAC:Y:RLEV {dbm:.1f}")

    def set_input_attenuation(self, db=None) -> None:
        """
        Set input attenuation.

        Args:
            db: Attenuation in dB (integer, multiples of 5 on SSA3032X Plus: 0–51).
                Pass None (default) or the string 'AUTO' for automatic attenuation.
        """
        if db is None or str(db).upper() == "AUTO":
            self.write(":SENS:POW:RF:ATT:AUTO ON")
        else:
            self.write(":SENS:POW:RF:ATT:AUTO OFF")
            self.write(f":SENS:POW:RF:ATT {int(db)}")

    def enable_averaging(self, count: int = 10) -> None:
        """
        Enable trace averaging.

        Args:
            count: Number of sweeps to average (typically 2–1000).
        """
        self.write(f":TRAC:AVER:COUN {count}")
        self.write(":TRAC:TYPE AVER")

    def disable_averaging(self) -> None:
        """Disable trace averaging; return to clear-write mode."""
        self.write(":TRAC:TYPE WRIT")

    def get_peak(self, trace: np.ndarray | None = None) -> tuple[float, float]:
        """
        Return the (frequency_hz, level_dbm) of the highest point on the trace.

        Queries the current start/stop frequencies from the instrument to build
        the frequency axis, then finds the max point.

        Args:
            trace: Optional pre-fetched trace array.  If None, calls get_trace().

        Returns:
            (freq_hz, level_dbm) of the peak.
        """
        if trace is None:
            trace = self.get_trace()
        start_hz = float(self.query(":FREQ:STAR?"))
        stop_hz  = float(self.query(":FREQ:STOP?"))
        freqs    = np.linspace(start_hz, stop_hz, len(trace))
        idx      = int(np.argmax(trace))
        return float(freqs[idx]), float(trace[idx])

    @staticmethod
    def _parse_trace(raw: str) -> np.ndarray:
        """Parse a trace response (ASCII CSV or IEEE 488.2 block)."""
        raw = raw.strip()
        if raw.startswith("#"):
            # IEEE 488.2 binary/ASCII block: #<n><length><data>
            n   = int(raw[1])
            raw = raw[2 + n:] if n > 0 else raw[2:]
        values = [float(x) for x in raw.split(",") if x.strip()]
        return np.asarray(values, dtype=float)
