"""
hp8712b.py — HP 8712B Vector Network Analyzer driver

Controls the HP 8712B (300 kHz – 1.3 GHz, 2-port VNA) over GPIB.

Connection path:
    Python → rf_bench.gpib.KISS488 (TCP port 23) → GPIB bus → HP 8712B

The driver is transport-agnostic: it talks to a
:class:`rf_bench.gpib.GPIBDevice` (or anything exposing the same
``write``/``read``/``query`` surface) and knows nothing about sockets,
Prologix ``++`` commands, or which adapter is in use.  The adapter owns the
link and serialises access, which is what lets the 8712B share one KISS-488
with the Solartron 7151 without the two corrupting each other's transactions.

Preferred construction::

    from rf_bench.gpib import KISS488
    gpib = KISS488.shared("10.1.1.70")
    vna  = HP8712B(gpib.device(16))

Backwards-compatible construction (used by every script under
``projects/vna/``) opens or joins the shared adapter automatically::

    vna = HP8712B("10.1.1.70")          # positional host
    vna = HP8712B(host="10.1.1.70")     # keyword host

HP 8712B SCPI notes:
    - Instrument uses 1990s HP BASIC SCPI; some mnemonics differ from
      modern SCPI or the HP 8714C/8753 series.  Commands marked
      "# Verify against HP 8712B manual" should be confirmed against
      the HP 8712B Network Analyzer Programmer's Guide before production use.
      A KISS-488 Spy-mode capture of a front-panel-driven session is the
      quickest way to settle them — see rf_bench.gpib.spy.
    - SDAT (raw S-data) returns ASCII space-separated real,imag pairs,
      one pair per point: "r0 i0 r1 i1 ... rN iN"
    - FDAT (formatted data) returns ASCII comma-separated floats,
      one or two values per point depending on format.
    - Frequencies from :SENS:FREQ:DATA? are comma-separated floats in Hz.

Model: HP 8712B (300 kHz – 1.3 GHz)
Default GPIB address: 16
Default KISS-488 host: 10.1.1.70, TCP port 23
"""

from typing import Optional

import numpy as np

from rf_bench.gpib import DEFAULT_TELNET_PORT, KISS488


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HOST       = "10.1.1.70"
DEFAULT_PORT       = DEFAULT_TELNET_PORT   # 23 — KISS-488 Telnet, NOT 1234
DEFAULT_GPIB_ADDR  = 16

#: Deprecated alias. Was 1234, which is the *Prologix* GPIB-ETHERNET port; the
#: KISS-488 listens on Telnet port 23 (User Guide Rev 2.13, §5 "Network
#: Addressing"). Kept so old call sites still import cleanly.
DEFAULT_KISS_PORT  = DEFAULT_PORT

READ_TIMEOUT       = 5.0   # seconds — normal query response
OPC_TIMEOUT        = 30.0  # seconds — *OPC? after single sweep
#
# OPC_TIMEOUT is a *host-side* wait. It cannot be pushed into the adapter:
# ++read_tmo_ms accepts at most 3000 ms. For sweeps longer than 3 s, set the
# KISS-488 web UI's Timeout String to a null string, which switches it to
# inter-byte timeouts and allows the instrument unbounded time to begin its
# reply (User Guide Rev 2.13, §5 "Timeouts").


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class HP8712B:
    """
    HP 8712B VNA driver, over any GPIB transport.

    Usage:
        from rf_bench.gpib import KISS488
        gpib = KISS488.shared("10.1.1.70")
        vna  = HP8712B(gpib.device(16))

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
    DEFAULT_PORT      = DEFAULT_PORT
    DEFAULT_KISS_PORT = DEFAULT_KISS_PORT      # deprecated alias
    DEFAULT_GPIB_ADDR = DEFAULT_GPIB_ADDR

    def __init__(
        self,
        transport=None,
        port: int = DEFAULT_PORT,
        gpib_addr: int = DEFAULT_GPIB_ADDR,
        *,
        host: Optional[str] = None,
        kiss_port: Optional[int] = None,
        read_timeout: float = READ_TIMEOUT,
    ):
        """
        Args:
            transport: either a GPIB device handle (anything with
                ``write``/``read``/``query`` — normally
                ``KISS488.shared(host).device(addr)``), or a host string for
                the backwards-compatible path.
            port: adapter TCP port when constructing from a host. Defaults to
                23, the KISS-488 Telnet port.
            gpib_addr: instrument primary address when constructing from a host.
            host: keyword form of the host string.
            kiss_port: deprecated alias for ``port``.
            read_timeout: default host-side reply timeout, seconds.
        """
        if kiss_port is not None:
            port = kiss_port

        if isinstance(transport, str):
            if host is not None and host != transport:
                raise ValueError(
                    f"conflicting hosts: positional {transport!r} vs host={host!r}"
                )
            host, transport = transport, None

        self.read_timeout = read_timeout
        # Track the currently-selected S-parameter so get_s11()/get_s21()
        # convenience accessors can re-select and acquire as needed. The
        # actual on-instrument state is set when set_parameter() is called.
        self._parameter: str = "S11"

        if transport is not None:
            self._dev = transport
            self._owns_adapter = False
            self.host = getattr(getattr(transport, "adapter", None), "host", None)
            self.port = port
            self.gpib_addr = getattr(transport, "address", gpib_addr)
        else:
            self.host = host or DEFAULT_HOST
            self.port = port
            self.gpib_addr = gpib_addr
            adapter = KISS488.shared(self.host, self.port)
            self._dev = adapter.device(self.gpib_addr, name="hp8712b")
            self._owns_adapter = True

        self.kiss_port = self.port   # deprecated alias, kept for old call sites

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        No-op; retained for API compatibility.

        The adapter connects when it is created and is shared process-wide, so
        there is nothing per-instrument to open. Reconnecting is the adapter's
        job, not the instrument driver's.
        """

    def close(self) -> None:
        """Release this instrument's handle on the GPIB adapter."""
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    @property
    def device(self):
        """The underlying GPIB device handle."""
        return self._dev

    def send(self, cmd: str) -> None:
        """
        Send a SCPI command to the instrument (no response expected).

        Uses the no-reply path, so the adapter sends the command and then
        leaves the bus quiescent rather than addressing the instrument to talk.
        Sending a no-reply command such as ``*CLS`` down the reply path is the
        documented way to hang for the whole timeout and light the instrument's
        error LED (KISS-488 User Guide Rev 2.13, §9).
        """
        self._require_open()
        self._dev.write(cmd)

    def query(self, cmd: str, timeout: Optional[float] = None) -> str:
        """
        Send a SCPI query and return the response string.

        The command and its reply are one atomic bus transaction, so another
        instrument on the same adapter cannot interleave between them.
        """
        self._require_open()
        return self._dev.query(cmd, timeout if timeout is not None else self.read_timeout)

    def _require_open(self) -> None:
        if self._dev is None:
            raise IOError("HP8712B is closed")

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
