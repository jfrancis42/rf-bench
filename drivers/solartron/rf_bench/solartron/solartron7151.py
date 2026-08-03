"""
solartron7151.py — Solartron 7151 Computing Multimeter driver

Controls the Solartron 7151 (6.5-digit bench DMM, 1985-era IEEE-488) over GPIB.

Connection path:
    Python -> rf_bench.gpib.KISS488 (TCP port 23) -> GPIB bus -> Solartron 7151

The driver is transport-agnostic: it talks to a
:class:`rf_bench.gpib.GPIBDevice` (or anything exposing the same
``write``/``read``/``query`` surface) and knows nothing about sockets or
adapter ``++`` commands.  The adapter owns the link and serialises access,
which is what lets the 7151 share one KISS-488 with the HP 8712B.

Preferred construction::

    from rf_bench.gpib import KISS488
    gpib = KISS488.shared("10.1.1.70")
    dmm  = Solartron7151(gpib.device(22))

Backwards-compatible construction opens or joins the shared adapter::

    dmm = Solartron7151("10.1.1.70")        # positional host

The Solartron 7151 uses a 1985-era device-specific ASCII command language —
NOT modern SCPI. Commands are single ASCII letters with optional integer
arguments; spaces are ignored, separators are not required, and the verbose
keyword form (e.g. "MODE VDC") is also accepted.

Programming reference: Solartron 7151 Computing Multimeter User Manual,
ND/7151/2 Issue 2 (1985), Chapter 6 (GPIB Operation).

Default GPIB address: 22
    Both this meter and the HP 8712B ship set to address 16, and they share one
    KISS-488, so the 7151 is moved to 22 on this bench.  The address is set on
    the rear-panel DIP switches and takes effect only after a power-on reset.

Default KISS-488 host: 10.1.1.70, TCP port 23
"""

import time
from typing import Optional

from rf_bench.gpib import DEFAULT_TELNET_PORT, KISS488


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HOST       = "10.1.1.70"
DEFAULT_PORT       = DEFAULT_TELNET_PORT   # 23 — KISS-488 Telnet, NOT 1234
DEFAULT_GPIB_ADDR  = 22                    # 16 collides with the HP 8712B

#: Deprecated alias. Was 1234, which is the *Prologix* GPIB-ETHERNET port; the
#: KISS-488 listens on Telnet port 23 (User Guide Rev 2.13, §5 "Network
#: Addressing"). Kept so old call sites still import cleanly.
DEFAULT_KISS_PORT  = DEFAULT_PORT

READ_TIMEOUT       = 5.0   # seconds — normal query response
RESET_DELAY        = 2.0   # seconds — required wait after DCL ('A') per s7150 reference


# Function codes — argument to MODE (M) command. Source: User Manual page 6.24
MODE_VDC    = 0   # M0 = MODE VDC   (DC volts)
MODE_VAC    = 1   # M1 = MODE VAC   (AC volts)
MODE_KOHM   = 2   # M2 = MODE KOHM  (resistance)
MODE_IDC    = 3   # M3 = MODE IDC   (DC current)
MODE_IAC    = 4   # M4 = MODE IAC   (AC current)

MODES: dict = {
    "VDC":  MODE_VDC,
    "DCV":  MODE_VDC,
    "VAC":  MODE_VAC,
    "ACV":  MODE_VAC,
    "OHM":  MODE_KOHM,
    "KOHM": MODE_KOHM,
    "IDC":  MODE_IDC,
    "DCA":  MODE_IDC,
    "IAC":  MODE_IAC,
    "ACA":  MODE_IAC,
}

# Range codes — argument to RANGE (R) command. The numeric meaning depends on
# the active function (User Manual page 6.24).
#
#   For voltage  (M0/M1): R0=auto, R1=0.2V, R2=2V, R3=20V, R4=200V, R5=2000V
#   For ohms     (M2):    R0=auto, R3=20kOhm, R4=200kOhm, R5=2MOhm, R6=20MOhm
#                         (2kOhm is N/A; the s7150 reference driver also notes
#                         that ranges below 20k are not present.)
#   For current  (M3/M4): R0=auto.  Per the manual: "if current, dc is selected,
#                         sending any argument (0->6) with R causes the one
#                         suitable range to be selected" — i.e. only one fixed
#                         range is implemented. The s7150 reference driver
#                         encodes this as R5=2000 mA.
RANGE_AUTO       = 0
RANGE_V_200MV    = 1
RANGE_V_2V       = 2
RANGE_V_20V      = 3
RANGE_V_200V     = 4
RANGE_V_2000V    = 5
RANGE_OHM_20K    = 3
RANGE_OHM_200K   = 4
RANGE_OHM_2M     = 5
RANGE_OHM_20M    = 6
RANGE_I_2000MA   = 5

# Integration / NINES codes — argument to NINES (I) command. User Manual 6.24.
INT_3X9_6P67MS   = 0   # I0 = NINES 3        (6.66 ms)
INT_4X9_50HZ     = 1   # I1 = 4 HZ 50        (40 ms; for 50 Hz line)
INT_4X9_60HZ     = 2   # I2 = 4 HZ 60        (50 ms; -> not 50 ms verbatim;
                       #                      manual lists "50 ms measurement
                       #                      time" for I2)
INT_5X9_FILT_OFF = 3   # I3 = 5 FILTER OFF   (400 ms)
INT_6X9_8S       = 4   # I4 = 6              (~8.0 s, "walking window";
                       #                      needs ~8 s prefill before first
                       #                      sample)
INT_5X9_FILT_ON  = 5   # I5 = 5 FILTER ON    (1.6 s)

# Trigger / TRACK codes — User Manual 6.25
TRACK_OFF        = 0   # T0 = TRACK OFF (single-sample mode; use G to trigger)
TRACK_ON         = 1   # T1 = TRACK ON  (continuous repetitive measurements)

# DELIMIT (U) command codes — output delimiter. User Manual 6.25.
#   U0 = CR LF       (default)
#   U1 = ETX
#   U2 = CR LF ETX
#   U3 = EOI
#   U4 = CR LF EOI
#   U5 = ETX EOI
#   U6 = CR LF ETX EOI
#   U7 = CR
#   U8 = SPACE
DELIM_CRLF      = 0
DELIM_ETX       = 1
DELIM_CRLFETX   = 2
DELIM_EOI       = 3
DELIM_CRLFEOI   = 4
DELIM_ETXEOI    = 5
DELIM_CRLFETXEOI = 6
DELIM_CR        = 7
DELIM_SPACE     = 8

# LITERALS (N) command codes
LITERALS_ON  = 0   # N0 = LITERALS ON   (verbose: "+2.798450 V DC ...")
LITERALS_OFF = 1   # N1 = LITERALS OFF  (numeric only: "+2.798450")

# DISPLAY (D) command codes — note: D1 DISABLES the display (counter-intuitive)
DISPLAY_ON   = 0   # D0 = DISPLAY ON
DISPLAY_OFF  = 1   # D1 = DISPLAY OFF

# SRQ (Q) command codes
SRQ_ERROR  = 0   # Q0 = SRQ on error only           (default)
SRQ_BOTH   = 1   # Q1 = SRQ on error or output
SRQ_OFF    = 2   # Q2 = SRQ disabled
SRQ_OUTPUT = 3   # Q3 = SRQ on output only

# DRIFT (Y) command codes
DRIFT_ON   = 0   # Y0 = DRIFT ON       (timed drift correct enabled)
DRIFT_NOW  = 1   # Y1 = DRIFT NOW      (drift correct with next measurement)
DRIFT_OFF  = 2   # Y2 = DRIFT OFF

# NULL (Z) command codes
NULL_OFF   = 0   # Z0 = NULL OFF
NULL_NOW   = 1   # Z1 = NULL NOW       (take a new null reading)

# Serial poll status byte bits — User Manual page 6.4 ("3.4 SERIAL POLL BYTE")
STB_CMD_ERROR  = 0x01   # bit 0 — Command/operational error
STB_REMOTE     = 0x08   # bit 3 — Remote control
STB_OUTPUT_AVL = 0x10   # bit 4 — Output available
STB_CAL_ERROR  = 0x20   # bit 5 — Calibration error
STB_SRQ        = 0x40   # bit 6 — Service Request

# STATUS (!) command error codes — User Manual page 6.27
ERROR_MESSAGES: dict = {
    0:  "OK",
    1:  "BAD COMMAND",
    2:  "BAD ARGUMENT",
    3:  "I/P BUFFER OVERFLOW",
    4:  "HI NULL",
    5:  "ILLEGAL MODE FOR NULL",
    6:  "ILLEGAL MODE FOR 6x9s",
    8:  "CAL INHIBITED",
    9:  "COMMAND ILLEGAL IN CAL",
    10: "CAL OUTSIDE LIMITS",
    12: "INVALID PROGRAM NAME",
    13: "PROGRAM NOT SELECTED",
    14: "PROGRAM ALREADY SELECTED",
    15: "INVALID OPTION SELECTED",
    16: "NUMERIC OVERFLOW",
    17: "NO PROGRAMS SELECTED",
    18: "CLOCK ALREADY ON",
}


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class Solartron7151:
    """
    Solartron 7151 6.5-digit computing multimeter driver via KISS-488 (Prologix-
    compatible) Ethernet-GPIB adapter.

    The 7151 (and its 7150 / 7150-plus siblings) speaks a 1985-era device-
    specific ASCII command set, NOT modern SCPI. Commands are single ASCII
    letters with integer arguments. The verbose form (full keywords) is also
    accepted by the instrument but this driver uses the compact shortform
    everywhere.

    Power-on default state (after RESET / DCL):
        MODE VDC, RANGE AUTO, NINES 5 FILTER OFF (400 ms), TRACK ON,
        DELIMIT 13 10 (CR LF), LITERALS ON, DRIFT ON, NULL OFF, LOCK OFF,
        DISPLAY ON, POLL 0, SRQ ERROR.

    Usage:
        dmm = Solartron7151("10.1.1.70")
        dmm.identify()
        dmm.set_mode("VDC")
        dmm.set_range_auto()
        dmm.set_integration(Solartron7151.INT_5X9_FILT_OFF)
        v = dmm.read_value()
        dmm.close()

    Context manager:
        with Solartron7151("10.1.1.70") as dmm:
            dmm.set_mode("VDC")
            ...
    """

    DEFAULT_HOST      = DEFAULT_HOST
    DEFAULT_PORT      = DEFAULT_PORT
    DEFAULT_KISS_PORT = DEFAULT_KISS_PORT      # deprecated alias
    DEFAULT_GPIB_ADDR = DEFAULT_GPIB_ADDR

    # Re-export key constants on the class for convenience
    MODE_VDC = MODE_VDC
    MODE_VAC = MODE_VAC
    MODE_KOHM = MODE_KOHM
    MODE_IDC = MODE_IDC
    MODE_IAC = MODE_IAC

    INT_3X9_6P67MS   = INT_3X9_6P67MS
    INT_4X9_50HZ     = INT_4X9_50HZ
    INT_4X9_60HZ     = INT_4X9_60HZ
    INT_5X9_FILT_OFF = INT_5X9_FILT_OFF
    INT_6X9_8S       = INT_6X9_8S
    INT_5X9_FILT_ON  = INT_5X9_FILT_ON

    TRACK_OFF = TRACK_OFF
    TRACK_ON  = TRACK_ON

    def __init__(
        self,
        transport=None,
        port: int = DEFAULT_PORT,
        gpib_addr: int = DEFAULT_GPIB_ADDR,
        *,
        host: Optional[str] = None,
        kiss_port: Optional[int] = None,
        read_timeout: float = READ_TIMEOUT,
        initialise: bool = True,
    ):
        """
        Args:
            transport: either a GPIB device handle (anything with
                ``write``/``read``/``query`` — normally
                ``KISS488.shared(host).device(22)``), or a host string for the
                backwards-compatible path.
            port: adapter TCP port when constructing from a host (default 23).
            gpib_addr: instrument primary address when constructing from a host.
            host: keyword form of the host string.
            kiss_port: deprecated alias for ``port``.
            read_timeout: default host-side reply timeout, seconds.
            initialise: run the DCL + ``U7N0T1`` startup sequence. Set False to
                attach to an instrument already in a known state (and to keep
                unit tests from paying the 2 s reset delay).
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
        self._literals = True   # connect() sets N0 (literals on)

        if transport is not None:
            self._dev = transport
            self.host = getattr(getattr(transport, "adapter", None), "host", None)
            self.port = port
            self.gpib_addr = getattr(transport, "address", gpib_addr)
        else:
            self.host = host or DEFAULT_HOST
            self.port = port
            self.gpib_addr = gpib_addr
            adapter = KISS488.shared(self.host, self.port)
            self._dev = adapter.device(self.gpib_addr, name="solartron7151")

        self.kiss_port = self.port   # deprecated alias, kept for old call sites

        if initialise:
            self.connect()

    # ------------------------------------------------------------------
    # Connection / lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Initialise the instrument to a known state.

        Issues the 7151 DCL ('A') command and waits 2 s (per the s7150
        reference driver — the instrument reports its RESTART message via the
        bus during this time and is not ready for further commands until the
        message has been emitted).

        Then sets the output delimiter to CR (U7), turns on verbose output with
        literals (N0), and enables tracking (T1) — the standard init sequence
        used by the s7150 reference driver.

        The adapter itself is configured by :class:`rf_bench.gpib.KISS488`; this
        method deals only with the instrument.
        """
        self._require_open()
        # Reset the instrument (DCL) — returns to power-on default state. The
        # 7151 emits a RESTART message during this period; discard it by
        # waiting RESET_DELAY before issuing further commands.
        self._dev.write("A")
        time.sleep(RESET_DELAY)

        # Configure output: CR delimiter, literals on, tracking on.
        self._dev.write("U7N0T1")
        self._literals = True
        time.sleep(0.1)

    def close(self) -> None:
        """Reset the instrument and release the GPIB adapter handle."""
        if self._dev is not None:
            try:
                # DC1 = CANCEL, A = DCL — restore default state
                self._dev.write("DC1")
                self._dev.write("A")
            except Exception:
                pass
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
        """Send a Solartron command (no response expected)."""
        self._require_open()
        self._dev.write(cmd)

    def query(self, cmd: str, timeout: Optional[float] = None) -> str:
        """Send a command, then read one response line.

        The command and its reply are one atomic bus transaction. The 7151
        makes its output buffer available once a result is ready; queries that
        ask "what is your present setting" (e.g. "M?") return immediately, but
        a read just after issuing a measurement command in single-shot mode
        must wait out the integration period.
        """
        self._require_open()
        return self._dev.query(cmd, timeout if timeout is not None else self.read_timeout)

    def _require_open(self) -> None:
        if self._dev is None:
            raise IOError("Solartron7151 is closed")

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def identify(self) -> str:
        """Return the present settings of all shortform commands (echoback).

        The 7151 has no *IDN? — it predates SCPI by a decade. The closest
        equivalent is the E command, which causes the 7151 to output the
        present settings of all shortform commands in alphabetical order.
        At power-on a "RESTART" or "RESUMED" message is emitted that includes
        the time, date, software version, and calibration status, but that
        message is consumed by connect()'s 2-second startup delay.
        """
        return self.query("E", timeout=READ_TIMEOUT)

    def get_status_string(self) -> str:
        """Return the most recent error status string from the STATUS (!) command.

        Form: "error n + fault condition" (e.g. "ERROR 02 BAD ARGUMENT").
        Reading the status clears the present error to "no error" condition.
        """
        return self.query("!", timeout=READ_TIMEOUT)

    # ------------------------------------------------------------------
    # Measurement function / range / integration time
    # ------------------------------------------------------------------

    def set_mode(self, mode) -> None:
        """Select the measurement function.

        Args:
            mode: Either an integer 0-4 (MODE_VDC..MODE_IAC), or one of the
                  strings "VDC"/"DCV"/"VAC"/"ACV"/"OHM"/"KOHM"/"IDC"/"DCA"/
                  "IAC"/"ACA" (case-insensitive).

        Sending a MODE command automatically switches out any previously
        selected PROBE function (per User Manual section 6.1, MODE).
        """
        if isinstance(mode, str):
            key = mode.upper()
            if key not in MODES:
                raise ValueError(
                    f"mode must be 0-4 or one of {sorted(MODES)}, got {mode!r}"
                )
            code = MODES[key]
        else:
            code = int(mode)
            if code not in (0, 1, 2, 3, 4):
                raise ValueError(f"mode must be 0-4 or string, got {mode!r}")
        self.send(f"M{code}")

    def get_mode(self) -> str:
        """Query the present MODE setting (returns the verbose response string)."""
        return self.query("M?")

    def set_range(self, range_code: int) -> None:
        """Select the measurement range by numeric code.

        Args:
            range_code: 0-6 (see RANGE_* constants). Meaning depends on the
                        active function. For volts: R0=auto, R1=200mV,
                        R2=2V, R3=20V, R4=200V, R5=2000V. For ohms: R0=auto,
                        R3=20kOhm..R6=20MOhm. For current: R0=auto, R5=2000mA.

        If the requested range is not valid for the active function, the 7151
        will automatically adopt the nearest valid range (per User Manual
        page 6.24).
        """
        if not 0 <= int(range_code) <= 6:
            raise ValueError(f"range_code must be 0-6, got {range_code!r}")
        self.send(f"R{int(range_code)}")

    def set_range_auto(self) -> None:
        """Enable autoranging (R0)."""
        self.set_range(RANGE_AUTO)

    def get_range(self) -> str:
        """Query the present RANGE setting.

        On echoback, R is followed by two numbers, e.g. "R13" -> autorange=1
        (on), present range index=3.
        """
        return self.query("R?")

    def set_integration(self, code: int) -> None:
        """Set the measurement integration time / resolution.

        Args:
            code: 0-5 (see INT_* constants).
                  I0 = 6.66 ms (3.5 digits)
                  I1 = 40 ms   (4.5 digits, 50 Hz line)
                  I2 = 50 ms   (4.5 digits, 60 Hz line)
                  I3 = 400 ms  (5.5 digits, filter off)
                  I4 = ~8 s    (6.5 digits, walking window)
                  I5 = 1.6 s   (5.5 digits, filter on)

        Note: I4 needs to fill its measurement buffer before the first sample
        is available — this takes ~8 s after switching to I4.

        Note: 6x9s (I4) is illegal on AC ranges (returns ERROR 06).
        """
        if not 0 <= int(code) <= 5:
            raise ValueError(f"integration code must be 0-5, got {code!r}")
        self.send(f"I{int(code)}")

    # ------------------------------------------------------------------
    # Trigger / measurement initiation
    # ------------------------------------------------------------------

    def set_track(self, on: bool = True) -> None:
        """Enable (T1) or disable (T0) continuous repetitive measurements.

        With TRACK ON, the 7151 takes measurements continuously and overwrites
        the output buffer with each new result so the most recent reading is
        always available for read.

        With TRACK OFF, single-sample measurements must be initiated by the
        TRIG (G) command.
        """
        self.send("T1" if on else "T0")

    def trigger_single(self) -> None:
        """Issue the TRIG (G) command to take a single (one-shot) measurement.

        Only valid when TRACK is OFF. After triggering, allow time for the
        integration period to elapse before reading.
        """
        self.send("G")

    # ------------------------------------------------------------------
    # Reading parsing
    # ------------------------------------------------------------------

    def read_value(self, timeout: float = READ_TIMEOUT) -> float:
        """Read one measurement and return it as a float.

        Reads one output string off the bus and parses the leading signed
        mantissa. Examples:

            With LITERALS ON:  "+ 2.798450 V DC 01.15.00 DAY 5"  ->  2.798450
            With LITERALS OFF: "+2.798450"                       ->  2.798450
            Overload:          "+ 9.999999! V DC ..."            -> raises OverflowError
                                                                     (the '!' character
                                                                     in the data string
                                                                     indicates input
                                                                     overload)

        Per User Manual section 6.9 (Error Reporting): "If an input overload
        is detected by 7151 during a measurement period, the data string
        contained within the output buffer will contain the ASCII character
        '!' to indicate the error."
        """
        raw = self._read_one_reading(timeout)
        return self._parse_reading(raw)

    def read_raw(self, timeout: float = READ_TIMEOUT) -> str:
        """Read one raw output string from the instrument (no parsing)."""
        return self._read_one_reading(timeout)

    def _read_one_reading(self, timeout: float) -> str:
        """Read one pending output string off the bus (no command sent).

        In TRACK ON mode the 7151 measures continuously and overwrites its
        output buffer, so a bare read always yields the most recent result.
        """
        self._require_open()
        return self._dev.read(timeout if timeout is not None else self.read_timeout)

    @staticmethod
    def _parse_reading(s: str) -> float:
        """Parse a 7151 reading string into a float.

        Handles both LITERALS ON ("+ 2.798450 V DC ...") and LITERALS OFF
        ("+2.798450") forms. Raises OverflowError if the '!' overload flag
        is present anywhere in the string.
        """
        if "!" in s:
            raise OverflowError(f"7151 input overload (! flag): {s!r}")
        # Take the first whitespace-separated numeric token after stripping a
        # leading sign-with-space ("+ 1.23" or "- 1.23") variant.
        cleaned = s.strip().replace("+ ", "+").replace("- ", "-")
        # Take the first token of the cleaned string
        tok = cleaned.split()[0] if cleaned else ""
        try:
            return float(tok)
        except ValueError as e:
            raise ValueError(f"could not parse 7151 reading {s!r}") from e

    # ------------------------------------------------------------------
    # Cross-driver DMM API (parity with rf_bench.siglent.SDM3000X)
    # ------------------------------------------------------------------
    #
    # These give the 7151 the same measure_*() surface as the Siglent
    # SDM3045X, so projects under projects/dmm/ can take a --dmm flag, and so
    # rf_bench.fluke.Fluke80i400(dmm=...) — documented to compose with "any
    # rf-bench DMM driver that exposes measure_iac()" — accepts this meter.
    #
    # All return SI base units (volts, amperes, ohms) regardless of the range
    # the instrument reports in.

    def _measure(self, mode: int, range_code: Optional[int], settle: float) -> float:
        """Select a function/range, let it settle, and return one reading."""
        self.set_mode(mode)
        if range_code is not None:
            self.set_range(range_code)
        if settle:
            time.sleep(settle)
        return self.wait_for_reading()

    def measure_vdc(self, range_code: Optional[int] = None, settle: float = 0.5) -> float:
        """DC volts. Returns volts."""
        return self._measure(MODE_VDC, range_code, settle)

    def measure_vac(self, range_code: Optional[int] = None, settle: float = 0.5) -> float:
        """AC volts. Returns volts."""
        return self._measure(MODE_VAC, range_code, settle)

    def measure_idc(self, range_code: Optional[int] = None, settle: float = 0.5) -> float:
        """DC current. Returns amperes.

        The 7151 implements a single current range (User Manual p. 6.24: with
        current selected, any R argument selects the one suitable range).
        """
        return self._measure(MODE_IDC, range_code, settle)

    def measure_iac(self, range_code: Optional[int] = None, settle: float = 0.5) -> float:
        """AC current. Returns amperes.

        This is the method ``rf_bench.fluke.Fluke80i400(dmm=...)`` calls.
        """
        return self._measure(MODE_IAC, range_code, settle)

    def measure_resistance(
        self, range_code: Optional[int] = None, settle: float = 0.5
    ) -> float:
        """Resistance. Returns **ohms**.

        The 7151's resistance function is named KOHM (``M2``) and its ranges are
        quoted in kΩ/MΩ.  Whether the numeric mantissa is scaled in kΩ or Ω is
        not settled by the OCR'd manual, so this method does not guess: with
        LITERALS ON it reads the unit token out of the reply and scales from
        that.  With LITERALS OFF there is no unit to read and it raises rather
        than return a number that might be off by 1000.

        VERIFY-ON-HARDWARE: confirm the literal unit token the 7151 actually
        emits (expected "K OHM"/"KOHM"/"M OHM") and extend UNIT_SCALE if the
        real firmware spells it differently.
        """
        self.set_mode(MODE_KOHM)
        if range_code is not None:
            self.set_range(range_code)
        if settle:
            time.sleep(settle)
        if not self._literals:
            raise RuntimeError(
                "measure_resistance() needs LITERALS ON to determine the unit "
                "scale of the 7151's resistance reading. Call set_literals(True), "
                "or use read_value() and apply the scale yourself."
            )
        raw = self._wait_for_raw()
        return self._parse_reading(raw) * self._unit_scale(raw)

    def _wait_for_raw(self, timeout: float = 10.0, interval: float = 0.1) -> str:
        """As :meth:`wait_for_reading`, but returns the unparsed string."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = self._read_one_reading(
                min(interval, max(0.0, deadline - time.monotonic()))
            )
            if raw:
                return raw
            time.sleep(interval)
        raise TimeoutError(f"no reading from Solartron 7151 within {timeout:.1f} s")

    #: Multipliers applied to a literal reading to reach SI base units.
    UNIT_SCALE = {
        "KOHM": 1e3, "K OHM": 1e3, "KILOHM": 1e3,
        "MOHM": 1e6, "M OHM": 1e6, "MEGOHM": 1e6,
        "OHM": 1.0,
        "MV": 1e-3, "V": 1.0,
        "MA": 1e-3, "A": 1.0,
    }

    @classmethod
    def _unit_scale(cls, reading: str) -> float:
        """Derive the SI multiplier from the unit token in a literal reading."""
        text = reading.upper()
        # Longest match first so "K OHM" wins over "OHM".
        for token in sorted(cls.UNIT_SCALE, key=len, reverse=True):
            if token in text:
                return cls.UNIT_SCALE[token]
        raise ValueError(
            f"no recognised unit in 7151 reading {reading!r}; "
            f"known units: {sorted(cls.UNIT_SCALE)}"
        )

    # ------------------------------------------------------------------
    # Output formatting
    # ------------------------------------------------------------------

    def set_literals(self, on: bool = True) -> None:
        """Enable (N0) or disable (N1) the non-numeric portion of result strings.

        With LITERALS ON the 7151 emits e.g. "+ 2.798450 V DC 01.15.00 DAY 5";
        with LITERALS OFF it emits just "+ 2.798450". Disable literals (N1) for
        maximum output throughput.

        Note that the unit-aware helpers (:meth:`measure_resistance` and
        friends) need literals ON to read the units off the instrument rather
        than assuming them.
        """
        self.send("N0" if on else "N1")
        self._literals = bool(on)

    def set_display(self, on: bool = True) -> None:
        """Enable (D0) or disable (D1) the front-panel display.

        Note: the 7151 uses D1 to switch the display OFF (the verbose form is
        DISPLAY OFF). Disabling the display modestly improves measurement
        throughput at high integration rates.
        """
        self.send("D0" if on else "D1")

    def set_delimiter(self, code: int = DELIM_CR) -> None:
        """Set the output result delimiter.

        Args:
            code: One of DELIM_CRLF (0), DELIM_CR (7), etc. See the User
                  Manual page 6.25 table or the DELIM_* constants in this
                  module. Default in this driver after connect() is U7 (CR
                  only) to match the s7150 reference driver.
        """
        if not 0 <= int(code) <= 8:
            raise ValueError(f"delimiter code must be 0-8, got {code!r}")
        self.send(f"U{int(code)}")

    # ------------------------------------------------------------------
    # Drift / null / SRQ / lock
    # ------------------------------------------------------------------

    def set_drift_correct(self, mode: int = DRIFT_ON) -> None:
        """Configure the drift-correct facility.

        Args:
            mode: DRIFT_ON (0), DRIFT_NOW (1), or DRIFT_OFF (2).

        Disable drift corrects (Y2) for the highest measurement rates.
        """
        if mode not in (DRIFT_ON, DRIFT_NOW, DRIFT_OFF):
            raise ValueError(f"drift mode must be 0/1/2, got {mode!r}")
        self.send(f"Y{int(mode)}")

    def set_null(self, mode: int = NULL_OFF) -> None:
        """Configure the null facility.

        Args:
            mode: NULL_OFF (0) or NULL_NOW (1, take a fresh null reading).

        Note: NULL is illegal on AC ranges (returns ERROR 05).
        """
        if mode not in (NULL_OFF, NULL_NOW):
            raise ValueError(f"null mode must be 0 or 1, got {mode!r}")
        self.send(f"Z{int(mode)}")

    def set_srq(self, mode: int = SRQ_ERROR) -> None:
        """Configure SRQ generation.

        Args:
            mode: SRQ_ERROR (0), SRQ_BOTH (1), SRQ_OFF (2), or SRQ_OUTPUT (3).
        """
        if mode not in (0, 1, 2, 3):
            raise ValueError(f"srq mode must be 0-3, got {mode!r}")
        self.send(f"Q{int(mode)}")

    def set_lock(self, locked: bool = False) -> None:
        """Enable (K1) or disable (K0) the front-panel return-to-local key."""
        self.send("K1" if locked else "K0")

    # ------------------------------------------------------------------
    # Status / serial poll
    # ------------------------------------------------------------------

    def serial_poll(self) -> int:
        """Perform a GPIB serial poll and return the 7151's status byte.

        **Not reachable through a KISS-488.**  The KISS-488 Rev 2 command set
        (User Guide Rev 2.13, §11) has no ``++spoll`` and no other serial-poll
        primitive, so the 7151's status byte (the ``STB_*`` constants) and
        SRQ-driven waiting cannot be used with that adapter.  An earlier
        revision of this driver issued ``++spoll`` on the assumption that
        KISS-488 was fully Prologix-compatible; it is not.

        Use :meth:`get_error` (the instrument's own STATUS ``!`` command) for
        error state, and :meth:`wait_for_reading` to wait for data.

        Raises:
            NotImplementedError: always, on a KISS-488.  A different adapter
            that implements serial poll would satisfy this via its own device
            handle.
        """
        self._require_open()
        return self._dev.serial_poll()

    def wait_for_reading(
        self, timeout: float = 10.0, interval: float = 0.1
    ) -> float:
        """Poll the output buffer until a reading appears, or ``timeout`` elapses.

        The host-side replacement for the SRQ/serial-poll wait that KISS-488
        cannot provide.  Each attempt is a bare bus read: in TRACK ON mode the
        7151 always has the most recent result available, while in TRACK OFF
        mode nothing appears until the integration period after a
        :meth:`trigger_single` has elapsed.

        Raises:
            TimeoutError: if no reading arrived within ``timeout``.
            OverflowError: if the reading carries the '!' input-overload flag.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = self._read_one_reading(min(interval, max(0.0, deadline - time.monotonic())))
            if raw:
                return self._parse_reading(raw)
            time.sleep(interval)
        raise TimeoutError(
            f"no reading from Solartron 7151 within {timeout:.1f} s "
            "(check TRACK mode, integration time, and that a trigger was issued)"
        )

    def get_error(self) -> tuple:
        """Read the present error status via the STATUS (!) command.

        Returns:
            (code, message) tuple. code=0 means no error. After the call, the
            7151's internal error state is cleared. Only the most recent error
            is reported.
        """
        raw = self.get_status_string().strip()
        # Manual: "error 'n' + fault condition" -> e.g. "ERROR 02 BAD ARGUMENT"
        # Fall back to a permissive parse — the OCR'd manual shows the exact
        # capitalization may vary across firmware versions.
        upper = raw.upper()
        for code in sorted(ERROR_MESSAGES):
            tag = f"ERROR {code:02d}"
            if tag in upper:
                return (code, ERROR_MESSAGES[code])
        return (-1, raw)

    def device_clear(self) -> None:
        """Issue the DCL (A) command — initialise to default state.

        Also clears any pending SRQ and resets the input/output buffers. The
        instrument needs ~2 s to complete the DCL response (it emits a
        RESTART message); this method sleeps RESET_DELAY on the caller's behalf.
        """
        self.send("A")
        time.sleep(RESET_DELAY)

    # ------------------------------------------------------------------
    # Calibration (advanced — requires CAL shorting plug in rear-panel jack)
    # ------------------------------------------------------------------

    def calibrate_on(self) -> None:
        """Enter calibration mode (CALIBRATE ON / C1).

        REQUIREMENTS — failure to meet these will return ERROR 08 CAL INHIBITED:

            (1) Insert a 2.5 mm shorted jack plug into the rear-panel CAL
                socket. The plug must remain inserted throughout the
                calibration session.
            (2) Do NOT switch mains power on or off while the plug is fitted —
                doing so may corrupt the internal calibration constants.

        While in CAL mode:
            - TRIG, TRACK ON, NULL ON are unavailable.
            - HI, LO, WRITE, REFRESH become available.
        """
        self.send("C1")

    def calibrate_off(self) -> None:
        """Exit calibration mode (CALIBRATE OFF / C0)."""
        self.send("C0")

    def cal_hi(self, count: int) -> None:
        """Apply the present input as the calibration HI point (HI <count>).

        Args:
            count: Integer 0-999999. An integer of 200000 corresponds to
                   nominal full scale for the active range. The argument
                   describes the precise value of the externally-applied
                   reference in 5-and-a-half-nines counts. No decimal point.

        Examples (from User Manual page 7.3):
            applying 2V on 2V range:    cal_hi(200000)   # 2.00000 V FS
            applying 20V on 20V range:  cal_hi(200000)
            applying 5V on 200V range:  cal_hi(5000)     # leading zeros optional

        The 7151 displays "Hi Pt" for ~1.5 s while it measures, then displays
        and outputs its measured count.
        """
        if not 0 <= int(count) <= 999999:
            raise ValueError(f"HI count must be 0-999999, got {count!r}")
        self.send(f"H{int(count)}")

    def cal_lo(self, count: int) -> None:
        """Apply the present input as the calibration LO point (LO <count>).

        For DC ranges the LO point is typically a short circuit (count=0).
        For AC ranges, the LO point should not be less than ~5% of full scale.
        See cal_hi() for argument semantics.
        """
        if not 0 <= int(count) <= 999999:
            raise ValueError(f"LO count must be 0-999999, got {count!r}")
        self.send(f"L{int(count)}")

    def cal_write(self) -> None:
        """Calculate and store calibration constants for the active range (W).

        Issued after both HI and LO points have been entered for the active
        function/range. On success the 7151 displays "Good"; on failure an
        ERROR message is output (e.g. ERROR 10 CAL OUTSIDE LIMITS).
        """
        self.send("W")

    def cal_refresh(self) -> None:
        """Refresh (re-write) the existing calibration constants (REFRESH).

        Used when the existing calibration is judged satisfactory and the user
        simply wants to re-write the constants without performing the full
        HI/LO measurement sequence.
        """
        self.send("REFRESH")
