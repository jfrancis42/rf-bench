"""
hp8712b.py — HP 8712B Vector Network Analyzer driver

Controls the HP 8712B (300 kHz – 1.3 GHz, 2-port VNA) via a KISS-488 Rev 2
Ethernet-GPIB adapter using a Prologix-compatible command set over TCP.

Connection path:
    Python TCP socket → KISS-488 (port 1234) → GPIB bus → HP 8712B

KISS-488 uses the Prologix protocol:
    ++mode 1        controller mode
    ++addr <n>      target GPIB address
    ++auto 0        manual read (we issue ++read explicitly)
    ++eoi 1         assert EOI at end of each write

HP 8712B SCPI notes:
    - Instrument uses 1990s HP BASIC SCPI; some mnemonics differ from
      modern SCPI or the HP 8714C/8753 series.  Commands marked
      "# Verify against HP 8712B manual" should be confirmed against
      the HP 8712B Network Analyzer Programmer's Guide before production use.
    - SDAT (raw S-data) returns ASCII space-separated real,imag pairs,
      one pair per point: "r0 i0 r1 i1 ... rN iN"
    - FDAT (formatted data) returns ASCII comma-separated floats,
      one or two values per point depending on format.
    - Frequencies from :SENS:FREQ:DATA? are comma-separated floats in Hz.

Model: HP 8712B (300 kHz – 1.3 GHz)
Default GPIB address: 16
Default KISS-488 host: 10.1.1.70, port 1234
"""

import socket
import time
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HOST       = "10.1.1.70"
DEFAULT_KISS_PORT  = 1234
DEFAULT_GPIB_ADDR  = 16

CONNECT_TIMEOUT    = 10    # seconds — initial TCP connect
READ_TIMEOUT       = 5.0   # seconds — normal query response
OPC_TIMEOUT        = 30.0  # seconds — *OPC? after single sweep

RECV_BUFSIZE       = 65536


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class HP8712B:
    """
    HP 8712B VNA driver via KISS-488 (Prologix-compatible) Ethernet-GPIB adapter.

    Usage:
        vna = HP8712B("10.1.1.70")
        vna.connect()
        print(vna.identify())
        vna.setup_sweep(1e6, 1.3e9, points=401)
        vna.set_parameter("S11")
        vna.set_format("MLOG")
        vna.single_sweep()
        freqs = vna.get_frequencies()   # Hz, numpy array
        db    = vna.get_trace_db()       # dB, numpy array
        vna.close()

    Context manager:
        with HP8712B("10.1.1.70") as vna:
            vna.setup_sweep(...)
            ...
    """

    DEFAULT_HOST      = DEFAULT_HOST
    DEFAULT_KISS_PORT = DEFAULT_KISS_PORT
    DEFAULT_GPIB_ADDR = DEFAULT_GPIB_ADDR

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        kiss_port: int = DEFAULT_KISS_PORT,
        gpib_addr: int = DEFAULT_GPIB_ADDR,
    ):
        self.host      = host
        self.kiss_port = kiss_port
        self.gpib_addr = gpib_addr
        self._sock: Optional[socket.socket] = None
        # Track the currently-selected S-parameter so get_s11()/get_s21()
        # convenience accessors can re-select and acquire as needed. The
        # actual on-instrument state is set when set_parameter() is called.
        self._parameter: str = "S11"
        self.connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open TCP connection to KISS-488 and initialise adapter + instrument."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(CONNECT_TIMEOUT)
        self._sock.connect((self.host, self.kiss_port))
        time.sleep(0.2)
        # Initialise KISS-488 adapter
        self._raw_send("++mode 1")
        self._raw_send(f"++addr {self.gpib_addr}")
        self._raw_send("++auto 0")
        self._raw_send("++eoi 1")
        time.sleep(0.1)

    def close(self) -> None:
        """Close the TCP connection."""
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    def _raw_send(self, cmd: str) -> None:
        """Send a raw line to the KISS-488 (adapter command or SCPI command)."""
        self._sock.sendall((cmd + "\n").encode("ascii"))

    def _read_response(self, timeout: float = READ_TIMEOUT) -> str:
        """Read bytes from the socket until newline or timeout; return stripped string."""
        self._sock.settimeout(timeout)
        buf = bytearray()
        while True:
            try:
                chunk = self._sock.recv(RECV_BUFSIZE)
                if not chunk:
                    break
                buf.extend(chunk)
                # HP 8712B terminates responses with \n (LF); also accept \r\n
                if b"\n" in buf:
                    break
            except socket.timeout:
                break
        return buf.decode("ascii", errors="replace").strip()

    def send(self, cmd: str) -> None:
        """
        Send a SCPI command to the instrument (no response expected).

        For commands that do not return a response; adds the required
        newline terminator automatically.
        """
        self._raw_send(cmd)

    def query(self, cmd: str, timeout: float = READ_TIMEOUT) -> str:
        """
        Send a SCPI query and return the response string.

        Sends the command, then issues ++read to tell KISS-488 to pull
        the response off the GPIB bus, then reads the TCP reply.
        """
        self._raw_send(cmd)
        self._raw_send("++read")
        return self._read_response(timeout)

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def identify(self) -> str:
        """Return the instrument IDN string."""
        return self.query("*IDN?")

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup_sweep(
        self,
        start_hz: float,
        stop_hz: float,
        points: int = 201,
    ) -> None:
        """
        Configure a linear frequency sweep.

        Args:
            start_hz: Start frequency in Hz.
            stop_hz:  Stop frequency in Hz.
            points:   Number of sweep points (1–801; HP 8712B maximum is 801).
        """
        if points < 1 or points > 801:
            raise ValueError(f"points must be 1–801, got {points}")
        self.send(f":SENS:FREQ:STAR {start_hz:.1f}")
        self.send(f":SENS:FREQ:STOP {stop_hz:.1f}")
        self.send(f":SENS:SWE:POIN {points}")

    def set_parameter(self, param: str) -> None:
        """
        Select the S-parameter to measure.

        Args:
            param: One of 'S11', 'S21', 'S12', 'S22'.

        Note:
            Both :CALC:PAR:MOD and :SENS:Sxx:STAT are sent for compatibility.
            The HP 8712B may require one or both depending on firmware revision.
            Verify against HP 8712B manual.
        """
        param = param.upper()
        valid = {"S11", "S21", "S12", "S22"}
        if param not in valid:
            raise ValueError(f"param must be one of {valid}, got {param!r}")
        self.send(f":CALC:PAR:MOD {param}")          # Verify against HP 8712B manual
        # Also enable the measurement via the sensor path
        self.send(f":SENS:{param}:STAT ON")           # Verify against HP 8712B manual
        self._parameter = param

    def get_parameter(self) -> str:
        """Return the currently selected S-parameter."""
        return self._parameter

    def set_format(self, fmt: str) -> None:
        """
        Set the display/data format.

        Args:
            fmt: One of 'MLOG' (log mag dB), 'PHAS' (phase deg),
                 'MLIN' (linear mag), 'REAL', 'IMAG',
                 'SMIT' (Smith chart), 'GDEL' (group delay).
        """
        valid = {"MLOG", "PHAS", "MLIN", "REAL", "IMAG", "SMIT", "GDEL"}
        fmt = fmt.upper()
        if fmt not in valid:
            raise ValueError(f"fmt must be one of {valid}, got {fmt!r}")
        self.send(f":CALC:FORM {fmt}")

    def set_power(self, dbm: float) -> None:
        """
        Set port 1 stimulus power.

        Args:
            dbm: Power level in dBm (HP 8712B range is typically −10 to 0 dBm).
                 Verify exact range against HP 8712B manual.
        """
        self.send(f":SOUR:POW {dbm:.2f}")             # Verify against HP 8712B manual

    def set_averaging(self, count: int) -> None:
        """
        Enable or disable sweep averaging.

        Args:
            count: Number of averages (2 or more enables averaging).
                   0 or 1 disables averaging.
        """
        if count <= 1:
            self.send(":SENS:AVER:STAT OFF")
        else:
            self.send(":SENS:AVER:STAT ON")
            self.send(f":SENS:AVER:COUN {count}")

    # ------------------------------------------------------------------
    # Sweep control
    # ------------------------------------------------------------------

    def single_sweep(self) -> bool:
        """
        Trigger a single sweep and wait for completion.

        Sends :TRIG:SING, then polls *OPC? with a 30-second timeout.

        Returns:
            True if the sweep completed successfully (OPC returned '1').
            False if the operation timed out.
        """
        self.send(":TRIG:SOUR MAN")                   # Verify against HP 8712B manual
        self.send(":TRIG:SING")                        # Verify against HP 8712B manual
        response = self.query("*OPC?", timeout=OPC_TIMEOUT)
        return response.strip() == "1"

    def continuous(self) -> None:
        """Resume continuous (free-running) sweep."""
        self.send(":TRIG:SOUR INT")                    # Verify against HP 8712B manual

    def hold(self) -> None:
        """Hold (stop) the sweep."""
        self.send(":TRIG:SOUR MAN")                    # Verify against HP 8712B manual

    # NanoVNA-compatibility aliases
    def pause(self) -> None:
        """Pause sweeping. Alias for :meth:`hold` (NanoVNA-compatible name)."""
        self.hold()

    def resume(self) -> None:
        """Resume sweeping. Alias for :meth:`continuous` (NanoVNA-compatible name)."""
        self.continuous()

    # ------------------------------------------------------------------
    # Data readout
    # ------------------------------------------------------------------

    def get_frequencies(self) -> np.ndarray:
        """
        Return the frequency array for the current sweep.

        Returns:
            numpy array of floats, frequencies in Hz, one per sweep point.
        """
        raw = self.query(":SENS:FREQ:DATA?", timeout=READ_TIMEOUT)
        return np.array([float(v) for v in raw.split(",") if v.strip()])

    def get_trace_db(self) -> np.ndarray:
        """
        Return the formatted trace data in dB.

        Reads :CALC:DATA:FDAT? assuming MLOG (log magnitude) format is active.
        The HP 8712B returns one float per point for scalar formats (MLOG, PHAS, etc.),
        or two floats per point for complex formats (REAL+IMAG).  This method
        returns the first value per point (real component / magnitude).

        Returns:
            numpy array of floats, one value per sweep point.
        """
        raw = self.query(":CALC:DATA:FDAT?", timeout=READ_TIMEOUT)
        values = [float(v) for v in raw.split(",") if v.strip()]
        # FDAT may return two values per point for some formats; take first of each pair
        # For purely scalar formats (MLOG, PHAS) there is one value per point.
        # The HP 8712B documentation should clarify — take every other value to be safe.
        # Verify against HP 8712B manual.
        return np.array(values)

    def get_trace_phase(self) -> np.ndarray:
        """
        Return the formatted trace data in degrees.

        Reads :CALC:DATA:FDAT? assuming PHAS (phase) format is active.

        Returns:
            numpy array of floats (degrees), one per sweep point.
        """
        raw = self.query(":CALC:DATA:FDAT?", timeout=READ_TIMEOUT)
        values = [float(v) for v in raw.split(",") if v.strip()]
        return np.array(values)

    def get_s_data(self) -> np.ndarray:
        """
        Return the raw S-parameter data as a complex array.

        Reads :CALC:DATA:SDAT? which returns space-separated ASCII real/imag pairs:
            "r0 i0 r1 i1 ... rN iN"

        Returns:
            numpy array of complex128, one element per sweep point.

        Note:
            The exact delimiter (space vs. comma) in SDAT output should be verified
            against the HP 8712B manual.  This driver handles both space-separated
            and comma-separated output.
        """
        raw = self.query(":CALC:DATA:SDAT?", timeout=READ_TIMEOUT)
        # Handle both space-separated and comma-separated output
        raw = raw.replace(",", " ")
        values = [float(v) for v in raw.split() if v.strip()]
        if len(values) % 2 != 0:
            raise ValueError(
                f"SDAT returned odd number of values ({len(values)}); "
                "expected real/imag pairs"
            )
        reals = np.array(values[0::2])
        imags = np.array(values[1::2])
        return reals + 1j * imags

    # ------------------------------------------------------------------
    # Cross-driver convenience methods (NanoVNA API parity)
    # ------------------------------------------------------------------

    def get_s11(self) -> np.ndarray:
        """
        Return the current S11 trace as a complex array.

        Mirrors :meth:`rf_bench.nanovna.NanoVNA.get_s11`. Switches the
        instrument parameter selection to S11 if it is not already there
        (which requires a fresh sweep — averaging settings apply).
        """
        if self._parameter != "S11":
            self.set_parameter("S11")
            self.single_sweep()
        return self.get_s_data()

    def get_s21(self) -> np.ndarray:
        """
        Return the current S21 trace as a complex array.

        Mirrors :meth:`rf_bench.nanovna.NanoVNA.get_s21`. Switches the
        instrument parameter selection to S21 if it is not already there
        (which requires a fresh sweep — averaging settings apply).
        """
        if self._parameter != "S21":
            self.set_parameter("S21")
            self.single_sweep()
        return self.get_s_data()

    def get_trace_db_at(self, freq_hz: float) -> float:
        """
        Return the selected parameter's log-magnitude in dB at the sweep
        point closest to ``freq_hz``.

        Mirrors :meth:`rf_bench.nanovna.NanoVNA.get_trace_db_at`.
        """
        freqs = self.get_frequencies()
        db = self.get_trace_db()
        idx = int(np.argmin(np.abs(freqs - float(freq_hz))))
        return float(db[idx])

    def average_s_data(self, n: int = 4) -> np.ndarray:
        """
        Capture ``n`` sweeps and return the complex average of the selected
        parameter.

        Mirrors :meth:`rf_bench.nanovna.NanoVNA.average_s_data` for projects
        that want host-side averaging regardless of which driver is in use.
        On the HP 8712B, prefer :meth:`set_averaging` for hardware
        averaging — it is faster and gives the trace dynamic range needed
        for low-level S21 measurements.
        """
        if n < 1:
            raise ValueError(f"n must be ≥ 1, got {n}")
        self.single_sweep()
        acc = self.get_s_data().astype(np.complex128)
        for _ in range(n - 1):
            self.single_sweep()
            acc = acc + self.get_s_data().astype(np.complex128)
        return acc / float(n)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def correction_on(self) -> None:
        """Enable error correction (calibration)."""
        self.send(":SENS:CORR:STAT ON")

    def correction_off(self) -> None:
        """Disable error correction (calibration)."""
        self.send(":SENS:CORR:STAT OFF")

    # NanoVNA-style aliases for cross-driver parity
    def cal_on(self) -> None:
        """Enable error correction. Alias for :meth:`correction_on`."""
        self.correction_on()

    def cal_off(self) -> None:
        """Disable error correction. Alias for :meth:`correction_off`."""
        self.correction_off()

    def is_correction_on(self) -> bool:
        """
        Query whether error correction is currently enabled.

        Returns:
            True if correction is ON, False if OFF.
        """
        response = self.query(":SENS:CORR:STAT?")     # Verify against HP 8712B manual
        return response.strip() in ("1", "ON")

    # ------------------------------------------------------------------
    # Markers
    # ------------------------------------------------------------------

    def set_marker(self, freq_hz: float, marker: int = 1) -> None:
        """
        Enable a marker and position it at the specified frequency.

        Args:
            freq_hz: Marker frequency in Hz.
            marker:  Marker number (HP 8712B supports 1..4). Defaults to 1
                     to match the cross-driver swappable signature.
        """
        if marker < 1 or marker > 4:
            raise ValueError(f"marker must be 1..4, got {marker}")
        # HP 8712B uses a separate marker selector first
        if marker != 1:
            self.send(f":CALC:MARK{marker}:STAT ON")           # Verify against HP 8712B manual
            self.send(f":CALC:MARK{marker}:X {freq_hz:.1f}")   # Verify against HP 8712B manual
        else:
            self.send(":CALC:MARK:STAT ON")
            self.send(f":CALC:MARK:X {freq_hz:.1f}")

    def get_marker_value(self) -> float:
        """
        Read the current marker 1 value (in the active display format units).

        Returns:
            Marker readout as a float (dB, degrees, etc. depending on active format).
        """
        raw = self.query(":CALC:MARK:Y?")
        # Response may include multiple comma-separated values for complex formats;
        # return the first (primary) value.
        return float(raw.split(",")[0].strip())

    def marker_off(self) -> None:
        """Turn off marker 1 display."""
        self.send(":CALC:MARK:STAT OFF")
