"""
rf_bench.siglent.sdm3000x — Siglent SDM3000 series bench multimeter driver.

Connects via raw TCP/SCPI to port 5025.  No pyvisa required.
Tested with: Siglent SDM3045X (4.5-digit)

All SDM3000 models (SDM3045X, SDM3055, SDM3065X) share the same SCPI base.
Model-specific feature availability is noted in each method's docstring.

Measurement functions return floats in SI units: V, A, Ω, Hz, F, s, °C.

Usage::

    from rf_bench.siglent import SDM3000X

    with SDM3000X("10.1.1.63") as dmm:
        v = dmm.measure_vdc()               # → 3.299 V (auto-range)
        r = dmm.measure_resistance()        # → 9985.3 Ω
        f = dmm.measure_frequency()         # → 1000.02 Hz
        samples = dmm.read_multiple(10)     # → [3.299, 3.298, ...]
"""

import socket
import statistics
import time

DEFAULT_HOST = "10.1.1.63"
DEFAULT_PORT = 5025
DEFAULT_TIMEOUT = 10.0  # longer than other instruments: slow functions (cap, 4W) can take 2–3 s

# Convenience constants for range arguments — pass to measure_* and configure_* methods
RANGE_AUTO = "AUTO"

# DC voltage ranges (V)
RANGE_VDC_200MV  = 0.2
RANGE_VDC_2V     = 2
RANGE_VDC_20V    = 20
RANGE_VDC_200V   = 200
RANGE_VDC_1000V  = 1000

# AC voltage ranges (V)
RANGE_VAC_200MV  = 0.2
RANGE_VAC_2V     = 2
RANGE_VAC_20V    = 20
RANGE_VAC_200V   = 200
RANGE_VAC_750V   = 750

# Resistance ranges (Ω)
RANGE_RES_200    = 200
RANGE_RES_2K     = 2_000
RANGE_RES_20K    = 20_000
RANGE_RES_200K   = 200_000
RANGE_RES_2M     = 2_000_000
RANGE_RES_10M    = 10_000_000
RANGE_RES_100M   = 100_000_000  # SDM3055/3065X only

# Current ranges (A)
RANGE_IDC_200UA  = 200e-6
RANGE_IDC_2MA    = 2e-3
RANGE_IDC_20MA   = 20e-3
RANGE_IDC_200MA  = 200e-3
RANGE_IDC_2A     = 2.0
RANGE_IDC_10A    = 10.0

# Temperature probe types (for measure_temperature / configure_temperature)
TEMP_FRTD   = "FRTD"   # 4-wire RTD (most accurate; SDM3055/3065X only)
TEMP_RTD    = "RTD"    # 2-wire RTD (SDM3055/3065X only)
TEMP_TC     = "TC"     # Thermocouple (SDM3055/3065X only)


class SDM3000X:
    """
    Siglent SDM3000 series bench multimeter driver (SCPI / TCP port 5025).

    Tested with: Siglent SDM3045X (4.5-digit)
    Compatible with: SDM3045X, SDM3055 (5.5-digit), SDM3065X (6.5-digit)

    Feature availability by model:

    +---------------------+---------+---------+---------+
    | Feature             | 3045X   | 3055    | 3065X   |
    +=====================+=========+=========+=========+
    | DC/AC V, I          | yes     | yes     | yes     |
    | 2W/4W resistance    | yes     | yes     | yes     |
    | Frequency / period  | yes     | yes     | yes     |
    | Continuity / diode  | yes     | yes     | yes     |
    | Capacitance         | no      | yes     | yes     |
    | Temperature         | no      | yes     | yes     |
    | 100 MΩ range        | no      | yes     | yes     |
    +---------------------+---------+---------+---------+

    All MEAS:* commands are one-shot (configure + trigger + return value).
    Use configure_*() + read() / read_multiple() for repeated measurements
    in the same function without re-configuration overhead.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = DEFAULT_TIMEOUT):
        """
        Args:
            host:    Instrument IP address.  Assign via Utility → LAN on the SDM front panel.
            port:    TCP port (default 5025).
            timeout: Socket timeout in seconds (default 10 s; slow functions need headroom).
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = b""
        self.connect()

    # ------------------------------------------------------------------ #
    # Connection management                                                 #
    # ------------------------------------------------------------------ #

    def connect(self):
        """Open the TCP connection to the instrument."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))
        self._buf = b""

    def close(self):
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

    # ------------------------------------------------------------------ #
    # Low-level SCPI transport                                             #
    # ------------------------------------------------------------------ #

    def _send(self, cmd: str):
        self._sock.sendall((cmd + "\n").encode())

    def _recv_line(self) -> str:
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed by instrument")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode().strip()

    def _query(self, cmd: str) -> str:
        """Send command, return one response line."""
        self._send(cmd)
        return self._recv_line()

    def _query_float(self, cmd: str) -> float:
        return float(self._query(cmd))

    # ------------------------------------------------------------------ #
    # Escape hatch — raw SCPI commands                                    #
    # ------------------------------------------------------------------ #

    def write(self, cmd: str) -> None:
        """Send raw SCPI command without expecting a response.

        This is an "escape hatch" for sending commands not yet wrapped by the driver.

        Args:
            cmd: SCPI command string (newline will be appended automatically)

        Example:
            >>> dmm.write("SYST:BEEP")  # Beep the instrument
            >>> dmm.write("DISP:TEXT 'HELLO'")  # Display text (if supported)

        Warning:
            Use with caution. Invalid commands may put the instrument in an
            unexpected state. Consult the SDM3000X programming manual for valid
            SCPI commands.
        """
        self._send(cmd)

    def query(self, cmd: str) -> str:
        """Send raw SCPI query and return the response.

        This is an "escape hatch" for sending queries not yet wrapped by the driver.

        Args:
            cmd: SCPI query string (should end with '?')

        Returns:
            Response string from instrument (stripped of whitespace)

        Example:
            >>> resp = dmm.query("SYST:VERS?")  # Query SCPI version
            >>> print(resp)
            '1995.0'

        Warning:
            Use with caution. Invalid queries may hang or return unexpected data.
            Consult the SDM3000X programming manual for valid SCPI queries.
        """
        return self._query(cmd)

    # ------------------------------------------------------------------ #
    # Helpers                                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _range_suffix(range_val, resolution=None) -> str:
        """Build the optional ' range[,resolution]' suffix for MEAS/CONF commands."""
        if range_val is None or str(range_val).upper() == "AUTO":
            return ""
        if resolution is not None:
            return f" {range_val},{resolution}"
        return f" {range_val}"

    # ------------------------------------------------------------------ #
    # Instrument-level commands                                            #
    # ------------------------------------------------------------------ #

    def identify(self) -> str:
        """Return instrument identification string (*IDN?)."""
        return self._query("*IDN?")

    def reset(self):
        """Reset to factory defaults (*RST). Blocks 2 s for the instrument to initialise."""
        self._send("*RST")
        time.sleep(2.0)

    # ------------------------------------------------------------------ #
    # One-shot MEAS commands (configure + trigger + return value)          #
    # ------------------------------------------------------------------ #

    def measure_vdc(self, range_v=RANGE_AUTO, resolution=None) -> float:
        """Measure DC voltage. Returns volts (float).

        Args:
            range_v:    0.2, 2, 20, 200, 1000 (V), or 'AUTO'.
            resolution: Optional resolution in volts (float).
        """
        return self._query_float(
            "MEAS:VOLT:DC?" + self._range_suffix(range_v, resolution)
        )

    def measure_vac(self, range_v=RANGE_AUTO, resolution=None) -> float:
        """Measure AC voltage (true RMS). Returns volts (float).

        Args:
            range_v:    0.2, 2, 20, 200, 750 (V), or 'AUTO'.
            resolution: Optional resolution in volts (float).
        """
        return self._query_float(
            "MEAS:VOLT:AC?" + self._range_suffix(range_v, resolution)
        )

    def measure_idc(self, range_a=RANGE_AUTO, resolution=None) -> float:
        """Measure DC current. Returns amperes (float).

        Args:
            range_a:    200e-6, 2e-3, 0.02, 0.2, 2, 10 (A), or 'AUTO'.
            resolution: Optional resolution in amperes (float).
        """
        return self._query_float(
            "MEAS:CURR:DC?" + self._range_suffix(range_a, resolution)
        )

    def measure_iac(self, range_a=RANGE_AUTO, resolution=None) -> float:
        """Measure AC current (true RMS). Returns amperes (float).

        Args:
            range_a:    200e-6, 2e-3, 0.02, 0.2, 2, 10 (A), or 'AUTO'.
            resolution: Optional resolution in amperes (float).
        """
        return self._query_float(
            "MEAS:CURR:AC?" + self._range_suffix(range_a, resolution)
        )

    def measure_resistance(self, range_ohm=RANGE_AUTO, resolution=None,
                            four_wire: bool = False) -> float:
        """Measure resistance. Returns ohms (float).

        Args:
            range_ohm:  200, 2k, 20k, 200k, 2M, 10M Ω (100M Ω on SDM3055/3065X only),
                        or 'AUTO'.
            resolution: Optional resolution in ohms (float).
            four_wire:  If True, use 4-wire (Kelvin) sense — far more accurate for
                        low-resistance measurements (<100 Ω).  All SDM3000 models support
                        4-wire; the SDM3045X requires an appropriate test fixture.
        """
        cmd = "MEAS:FRES?" if four_wire else "MEAS:RES?"
        return self._query_float(cmd + self._range_suffix(range_ohm, resolution))

    def measure_frequency(self, range_v=RANGE_AUTO) -> float:
        """Measure frequency. Returns hertz (float).

        Args:
            range_v: Voltage range for the front-end (V): 0.2, 2, 20, 200, 750, or 'AUTO'.
        """
        return self._query_float("MEAS:FREQ?" + self._range_suffix(range_v))

    def measure_period(self, range_v=RANGE_AUTO) -> float:
        """Measure period. Returns seconds (float).

        Args:
            range_v: Voltage range for the front-end (V): 0.2, 2, 20, 200, 750, or 'AUTO'.
        """
        return self._query_float("MEAS:PER?" + self._range_suffix(range_v))

    def measure_continuity(self) -> float:
        """Continuity test. Returns resistance in ohms (float).

        The instrument beeps when resistance is below its continuity threshold (~30 Ω).
        """
        return self._query_float("MEAS:CONT?")

    def measure_diode(self) -> float:
        """Diode forward-voltage test. Returns volts (float).

        The test current is typically 1 mA.  A reading near 9.9 V indicates open circuit.
        """
        return self._query_float("MEAS:DIOD?")

    def measure_capacitance(self, range_f=RANGE_AUTO) -> float:
        """Measure capacitance. Returns farads (float).

        **SDM3055 / SDM3065X only.** The SDM3045X does not support capacitance.

        Args:
            range_f: 2e-9, 2e-8, 2e-7, 2e-6, 2e-5, 2e-4, 1e-2 (F), or 'AUTO'.
        """
        return self._query_float("MEAS:CAP?" + self._range_suffix(range_f))

    def measure_temperature(self, probe: str = TEMP_FRTD) -> float:
        """Measure temperature. Returns degrees Celsius (float).

        **SDM3055 / SDM3065X only.** The SDM3045X does not support temperature.

        Args:
            probe: Probe type — TEMP_FRTD (4-wire RTD, default), TEMP_RTD (2-wire RTD),
                   or TEMP_TC (thermocouple).
        """
        return self._query_float(f"MEAS:TEMP? {probe.upper()}")

    # ------------------------------------------------------------------ #
    # Configuration (configure once, then use read() / read_multiple())    #
    # ------------------------------------------------------------------ #

    def configure_vdc(self, range_v=RANGE_AUTO, resolution=None):
        """Configure for DC voltage.  Does not trigger.  Call read() to take a sample."""
        self._send("CONF:VOLT:DC" + self._range_suffix(range_v, resolution))

    def configure_vac(self, range_v=RANGE_AUTO, resolution=None):
        """Configure for AC voltage.  Does not trigger."""
        self._send("CONF:VOLT:AC" + self._range_suffix(range_v, resolution))

    def configure_idc(self, range_a=RANGE_AUTO, resolution=None):
        """Configure for DC current.  Does not trigger."""
        self._send("CONF:CURR:DC" + self._range_suffix(range_a, resolution))

    def configure_iac(self, range_a=RANGE_AUTO, resolution=None):
        """Configure for AC current.  Does not trigger."""
        self._send("CONF:CURR:AC" + self._range_suffix(range_a, resolution))

    def configure_resistance(self, range_ohm=RANGE_AUTO, resolution=None,
                              four_wire: bool = False):
        """Configure for resistance measurement.  Does not trigger.

        Args:
            four_wire: If True, configure for 4-wire (FRES) measurement.
        """
        cmd = "CONF:FRES" if four_wire else "CONF:RES"
        self._send(cmd + self._range_suffix(range_ohm, resolution))

    def configure_frequency(self, range_v=RANGE_AUTO):
        """Configure for frequency measurement.  Does not trigger."""
        self._send("CONF:FREQ" + self._range_suffix(range_v))

    def configure_period(self, range_v=RANGE_AUTO):
        """Configure for period measurement.  Does not trigger."""
        self._send("CONF:PER" + self._range_suffix(range_v))

    def configure_continuity(self):
        """Configure for continuity test.  Does not trigger."""
        self._send("CONF:CONT")

    def configure_diode(self):
        """Configure for diode forward-voltage test.  Does not trigger."""
        self._send("CONF:DIOD")

    # ------------------------------------------------------------------ #
    # Trigger model                                                         #
    # ------------------------------------------------------------------ #

    def set_sample_count(self, n: int):
        """Set the number of samples per INIT trigger (SAMP:COUN).

        Args:
            n: Number of samples (1–2000).
        """
        self._send(f"SAMP:COUN {int(n)}")

    def set_trigger_source(self, source: str = "IMM"):
        """Set trigger source (TRIG:SOUR).

        Args:
            source: 'IMM' (immediate, default), 'EXT' (external), or 'BUS' (*TRG command).
        """
        self._send(f"TRIG:SOUR {source.upper()}")

    def read(self) -> float:
        """Trigger one measurement in the current configuration and return the result.

        Equivalent to MEAS:* for a single shot, but avoids re-configuring the instrument.
        """
        return self._query_float("READ?")

    def fetch(self) -> float:
        """Fetch the last completed measurement without re-triggering. Returns float."""
        return self._query_float("FETCH?")

    def read_multiple(self, n: int, settle_s: float = 0.05) -> list[float]:
        """Take n measurements in the current configuration.

        Uses SAMP:COUN + INIT + FETCH? to acquire n samples without re-configuring.
        Returns list of floats in SI units matching the configured function.

        Args:
            n:        Number of samples (1–2000).
            settle_s: Per-sample settle time hint used to compute the wait before FETCH?.
                      Increase for slow functions (capacitance, 4-wire resistance): ~3–5 s
                      per sample.  For DC voltage / current, 0.05 s is adequate.

        Example::

            dmm.configure_vdc(range_v=5)
            samples = dmm.read_multiple(20, settle_s=0.05)
            mean_v  = sum(samples) / len(samples)
        """
        self.set_sample_count(n)
        self._send("INIT")
        time.sleep(n * settle_s + 0.5)
        raw = self._query("FETCH?")
        return [float(x) for x in raw.split(",") if x.strip()]

    # ------------------------------------------------------------------ #
    # Display                                                               #
    # ------------------------------------------------------------------ #

    def measure_stats(self, n: int, settle_s: float = 0.05) -> dict:
        """
        Take n readings in the current configuration and return statistics.

        Must be called after configure_*().

        Args:
            n:        Number of samples (1–2000).
            settle_s: Per-sample settle time (passed to read_multiple).

        Returns:
            dict with keys: n (int), mean, stdev, min, max — all in SI units.

        Example::

            dmm.configure_vdc(range_v=5)
            stats = dmm.measure_stats(50)
            print(f"{stats['mean']:.6f} V  ±{stats['stdev']:.6f}")
        """
        samples = self.read_multiple(n, settle_s)
        return {
            "n":     len(samples),
            "mean":  statistics.mean(samples),
            "stdev": statistics.stdev(samples) if len(samples) > 1 else 0.0,
            "min":   min(samples),
            "max":   max(samples),
        }

    def display_text(self, text: str):
        """Show a custom message on the front-panel display (max ~20 characters)."""
        self._send(f'DISP:TEXT "{text[:20]}"')

    def clear_display(self):
        """Restore the normal measurement readout on the front panel."""
        self._send("DISP:TEXT:STAT OFF")
