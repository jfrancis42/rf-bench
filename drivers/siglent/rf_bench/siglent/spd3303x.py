"""
rf_bench.siglent.spd3303x — Siglent SPD3303X series triple-output power supply driver.

Connects via raw TCP/SCPI to port 5025.  No pyvisa required.
Tested with: Siglent SPD3303X-E

Channel map:
    CH1, CH2 — Programmable: 0–32 V, 0–3.2 A (CC/CV)
    CH3      — Fixed voltage: 2.5 V, 3.3 V, or 5 V (hardware switch; up to 3 A)

CH3 voltage is selected by a physical switch on the front panel of the SPD3303X-E
and cannot be changed via SCPI.  The driver can enable and disable CH3 output and
measure its voltage, current, and power.

Usage::

    from rf_bench.siglent import SPD3303X

    with SPD3303X("10.1.1.64") as psu:
        psu.set_voltage(1, 5.0)
        psu.set_current(1, 0.5)          # current limit, not target
        psu.enable(1)

        v    = psu.measure_voltage(1)    # → 4.998 V (actual output)
        i    = psu.measure_current(1)    # → 0.247 A
        p    = psu.measure_power(1)      # → 1.234 W
        mode = psu.get_mode(1)           # → 'CV' or 'CC'

        psu.disable_all()

    # Series tracking: CH1+CH2 in series doubles the available voltage (up to 64 V):
    with SPD3303X("10.1.1.64") as psu:
        psu.set_tracking(SPD3303X.TRACKING_SERIES)
        psu.set_voltage(1, 15.0)         # CH2 mirrors CH1 in series mode
        psu.enable(1)
        psu.enable(2)
"""

import socket
import time

DEFAULT_HOST = "10.1.1.56"
DEFAULT_PORT = 5025
DEFAULT_TIMEOUT = 5.0

# Tracking mode constants — passed to set_tracking()
TRACKING_INDEPENDENT = "INDEP"
TRACKING_SERIES      = "SER"
TRACKING_PARALLEL    = "PARA"


class SPD3303X:
    """
    Siglent SPD3303X series triple-output bench power supply driver (SCPI / TCP port 5025).

    Tested with: Siglent SPD3303X-E
    Compatible with: SPD3303C, SPD3303X, SPD3303X-E

    Channels:
        CH1, CH2 — Programmable CC/CV outputs, 0–32 V / 0–3.2 A each.
        CH3      — Fixed-voltage output (2.5 V, 3.3 V, or 5 V, up to 3 A).
                   Voltage selection is a front-panel hardware switch on the SPD3303X-E.
                   set_voltage(3, ...) and set_current(3, ...) raise ValueError.

    Class-level tracking constants::

        SPD3303X.TRACKING_INDEPENDENT   # 'INDEP' — CH1 and CH2 operate independently
        SPD3303X.TRACKING_SERIES        # 'SER'   — CH1+CH2 in series (up to 64 V)
        SPD3303X.TRACKING_PARALLEL      # 'PARA'  — CH1+CH2 in parallel (up to 6.4 A)

    NOTE on SYST:STAT? bit layout: the bit mapping is taken from the SPD3303X-E
    programming guide and is consistent with the tested firmware.  If the mode bits
    return unexpected values, verify against Siglent's current programming guide for
    your firmware version.
    """

    # Expose tracking constants as class attributes too (handy without importing module)
    TRACKING_INDEPENDENT = TRACKING_INDEPENDENT
    TRACKING_SERIES      = TRACKING_SERIES
    TRACKING_PARALLEL    = TRACKING_PARALLEL

    # SYST:STAT? bitmask (SPD3303X-E programming guide)
    _STAT_CH1_CV   = 0x01   # bit 0: CH1 CV(1)/CC(0)
    _STAT_CH2_CV   = 0x02   # bit 1: CH2 CV(1)/CC(0)
    _STAT_TRACK    = 0x0C   # bits 2-3: tracking mode (0=INDEP, 1=SER, 2=PARA)
    _STAT_TRACK_SH = 2      # shift right by 2 to get tracking code
    _STAT_CH1_OUT  = 0x10   # bit 4: CH1 output on
    _STAT_CH2_OUT  = 0x20   # bit 5: CH2 output on
    _STAT_CH3_OUT  = 0x40   # bit 6: CH3 output on

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = DEFAULT_TIMEOUT):
        """
        Args:
            host:    Instrument IP address.  Assign via Utility → LAN on the SPD front panel.
            port:    TCP port (default 5025).
            timeout: Socket timeout in seconds.
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

    @staticmethod
    def _validate_channel(channel: int, allow_ch3: bool = True) -> str:
        """Return 'CH1', 'CH2', or 'CH3' after range-checking channel."""
        if channel not in (1, 2, 3):
            raise ValueError(f"channel must be 1, 2, or 3 (got {channel!r})")
        if not allow_ch3 and channel == 3:
            raise ValueError(
                "CH3 voltage and current are hardware-fixed on the SPD3303X-E "
                "and cannot be set via SCPI."
            )
        return f"CH{channel}"

    # ------------------------------------------------------------------ #
    # Instrument management                                                 #
    # ------------------------------------------------------------------ #

    def identify(self) -> str:
        """Return the instrument identification string (*IDN?)."""
        return self._query("*IDN?")

    def reset(self):
        """Reset to factory defaults (*RST).  All outputs are disabled.  Blocks 2 s."""
        self._send("*RST")
        time.sleep(2.0)

    # ------------------------------------------------------------------ #
    # Setpoints — CH1 and CH2 only                                         #
    # ------------------------------------------------------------------ #

    def set_voltage(self, channel: int, volts: float):
        """Set output voltage setpoint for CH1 or CH2.

        Args:
            channel: 1 or 2.  CH3 raises ValueError (hardware-fixed voltage).
            volts:   Voltage setpoint in volts (0–32 V).
        """
        ch = self._validate_channel(channel, allow_ch3=False)
        self._send(f"{ch}:VOLT {volts:.4f}")

    def set_current(self, channel: int, amps: float):
        """Set current limit for CH1 or CH2.

        The supply will not exceed this current; it will drop into CC mode if
        the load demands more.

        Args:
            channel: 1 or 2.  CH3 raises ValueError.
            amps:    Current limit in amperes (0–3.2 A).
        """
        ch = self._validate_channel(channel, allow_ch3=False)
        self._send(f"{ch}:CURR {amps:.4f}")

    def get_voltage_setpoint(self, channel: int) -> float:
        """Query the programmed voltage setpoint for CH1 or CH2.  Returns volts.

        Note: this returns the *setpoint*, not the measured output voltage.
        Use measure_voltage() for the actual output.
        """
        ch = self._validate_channel(channel, allow_ch3=False)
        return self._query_float(f"{ch}:VOLT?")

    def get_current_setpoint(self, channel: int) -> float:
        """Query the programmed current limit for CH1 or CH2.  Returns amperes."""
        ch = self._validate_channel(channel, allow_ch3=False)
        return self._query_float(f"{ch}:CURR?")

    # ------------------------------------------------------------------ #
    # Output enable / disable                                               #
    # ------------------------------------------------------------------ #

    def enable(self, channel: int):
        """Enable the output of the specified channel (1, 2, or 3).

        Args:
            channel: 1, 2, or 3.
        """
        ch = self._validate_channel(channel)
        self._send(f"OUTP {ch},ON")

    def disable(self, channel: int):
        """Disable the output of the specified channel (1, 2, or 3).

        Args:
            channel: 1, 2, or 3.
        """
        ch = self._validate_channel(channel)
        self._send(f"OUTP {ch},OFF")

    def disable_all(self):
        """Disable all three channel outputs. Safe to call at any time."""
        for ch in (1, 2, 3):
            self._send(f"OUTP CH{ch},OFF")

    def enable_all(self):
        """Enable all three channel outputs."""
        for ch in (1, 2, 3):
            self._send(f"OUTP CH{ch},ON")

    def is_enabled(self, channel: int) -> bool:
        """Query whether a channel output is currently on.

        Reads the SYST:STAT? register and checks the appropriate output bit.
        Bit 4 = CH1 on, bit 5 = CH2 on, bit 6 = CH3 on.
        """
        self._validate_channel(channel)
        raw = self._query("SYST:STAT?")
        try:
            val = int(raw, 16)
        except ValueError:
            val = int(raw.replace("0x", "").replace("0X", ""), 16)
        mask = {1: self._STAT_CH1_OUT, 2: self._STAT_CH2_OUT, 3: self._STAT_CH3_OUT}[channel]
        return bool(val & mask)

    # ------------------------------------------------------------------ #
    # Measurements                                                          #
    # ------------------------------------------------------------------ #

    def measure_voltage(self, channel: int) -> float:
        """Measure actual output voltage.  Returns volts (float).

        Args:
            channel: 1, 2, or 3.
        """
        ch = self._validate_channel(channel)
        return self._query_float(f"MEAS:VOLT? {ch}")

    def measure_current(self, channel: int) -> float:
        """Measure actual output current.  Returns amperes (float).

        Args:
            channel: 1, 2, or 3.
        """
        ch = self._validate_channel(channel)
        return self._query_float(f"MEAS:CURR? {ch}")

    def measure_power(self, channel: int) -> float:
        """Measure actual output power.  Returns watts (float).

        Args:
            channel: 1, 2, or 3.
        """
        ch = self._validate_channel(channel)
        return self._query_float(f"MEAS:POWE? {ch}")

    def measure_all(self, channel: int) -> dict:
        """Measure voltage, current, and power for a channel in a single call.

        Returns:
            dict with keys 'voltage_v' (V), 'current_a' (A), 'power_w' (W).

        Example::

            state = psu.measure_all(1)
            print(f"CH1: {state['voltage_v']:.3f} V, "
                  f"{state['current_a']:.3f} A, "
                  f"{state['power_w']:.3f} W")
        """
        return {
            "voltage_v": self.measure_voltage(channel),
            "current_a": self.measure_current(channel),
            "power_w":   self.measure_power(channel),
        }

    # ------------------------------------------------------------------ #
    # Status and operating mode                                             #
    # ------------------------------------------------------------------ #

    def get_status(self) -> dict:
        """Query the system status register (SYST:STAT?).

        Returns a dict:
            'ch1_mode':   'CV' or 'CC'
            'ch2_mode':   'CV' or 'CC'
            'track_mode': 'INDEP', 'SER', or 'PARA'

        The SYST:STAT? response is a hex byte (e.g. '0x14'):
            bit 0  (0x01): CH1 mode — 1=CV, 0=CC
            bit 1  (0x02): CH2 mode — 1=CV, 0=CC
            bits 2-3 (0x0C): tracking — 0=INDEP, 1=SER, 2=PARA

        Additional bits vary by firmware version; only the above are decoded here.
        """
        raw = self._query("SYST:STAT?")
        try:
            val = int(raw, 16)
        except ValueError:
            # Some firmware versions omit the '0x' prefix
            val = int(raw.replace("0x", "").replace("0X", ""), 16)

        track_code = (val & self._STAT_TRACK) >> self._STAT_TRACK_SH
        track_map  = {0: TRACKING_INDEPENDENT, 1: TRACKING_SERIES, 2: TRACKING_PARALLEL}

        return {
            "ch1_mode":   "CV" if (val & self._STAT_CH1_CV) else "CC",
            "ch2_mode":   "CV" if (val & self._STAT_CH2_CV) else "CC",
            "track_mode": track_map.get(track_code, TRACKING_INDEPENDENT),
            "ch1_on":     bool(val & self._STAT_CH1_OUT),
            "ch2_on":     bool(val & self._STAT_CH2_OUT),
            "ch3_on":     bool(val & self._STAT_CH3_OUT),
        }

    def get_mode(self, channel: int) -> str:
        """Return 'CV' or 'CC' for a programmable channel.

        Args:
            channel: 1 or 2.  CH3 always returns 'CV' (it is a regulated fixed output).

        Returns:
            'CV' if in constant-voltage mode, 'CC' if in constant-current mode.
        """
        if channel == 3:
            return "CV"
        if channel not in (1, 2):
            raise ValueError(f"channel must be 1, 2, or 3 (got {channel!r})")
        status = self.get_status()
        return status[f"ch{channel}_mode"]

    # ------------------------------------------------------------------ #
    # Tracking mode (CH1+CH2 linked)                                       #
    # ------------------------------------------------------------------ #

    def set_all(self, channel: int, volts: float, amps: float):
        """Set voltage setpoint and current limit for CH1 or CH2 in one call.

        Args:
            channel: 1 or 2.
            volts:   Voltage setpoint in volts (0–32 V).
            amps:    Current limit in amperes (0–3.2 A).
        """
        self.set_voltage(channel, volts)
        self.set_current(channel, amps)

    def ramp_voltage(self, channel: int, target_v: float,
                     step_v: float = 0.1, delay_s: float = 0.05):
        """
        Gradually ramp the output voltage to target_v.

        Reads the current setpoint and steps toward target in increments of
        step_v, pausing delay_s between steps.  Safe to call whether output is
        enabled or not.  Always ends at exactly target_v.

        Args:
            channel:  1 or 2.
            target_v: Final voltage setpoint (V).
            step_v:   Voltage step size (V).  Default 0.1 V.
            delay_s:  Pause between steps (s).  Default 0.05 s.
        """
        current_v = self.get_voltage_setpoint(channel)
        if current_v < target_v:
            while current_v < target_v:
                current_v = min(current_v + step_v, target_v)
                self.set_voltage(channel, current_v)
                time.sleep(delay_s)
        else:
            while current_v > target_v:
                current_v = max(current_v - step_v, target_v)
                self.set_voltage(channel, current_v)
                time.sleep(delay_s)

    def wait_settled(self, channel: int, timeout_s: float = 5.0,
                     tol_v: float = 0.05) -> bool:
        """
        Block until the measured output voltage is within tol_v of the setpoint.

        Args:
            channel:   1 or 2.
            timeout_s: Maximum wait time in seconds.
            tol_v:     Voltage tolerance band (V).  Default 50 mV.

        Returns:
            True if the output settled within timeout_s, False on timeout.
        """
        target = self.get_voltage_setpoint(channel)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if abs(self.measure_voltage(channel) - target) <= tol_v:
                return True
            time.sleep(0.1)
        return False

    def set_tracking(self, mode: str = TRACKING_INDEPENDENT):
        """Set CH1/CH2 tracking mode.

        Args:
            mode: TRACKING_INDEPENDENT ('INDEP') — CH1 and CH2 operate independently.
                  TRACKING_SERIES       ('SER')   — CH1 and CH2 in series; CH2 mirrors
                                                    CH1.  Output voltage is up to 64 V.
                  TRACKING_PARALLEL     ('PARA')  — CH1 and CH2 in parallel; both
                                                    supply the same voltage.  Combined
                                                    current limit is up to 6.4 A.

        In SER or PARA mode, set the voltage and current on CH1 only; CH2 is slaved.
        """
        mode = mode.upper()
        if mode not in (TRACKING_INDEPENDENT, TRACKING_SERIES, TRACKING_PARALLEL):
            raise ValueError(
                f"mode must be 'INDEP', 'SER', or 'PARA' (got {mode!r})"
            )
        self._send(f"OUTP:TRAC {mode}")
