"""
et5406a.py — Yertai ET5406A+ programmable DC load

200 W / 120 V / 20 A.  Single channel.  USB connection via CH340 serial adapter.
Wrapper around the ET54 library (https://github.com/philpagel/ET54.py) with
maintained API compatibility and CH340 auto-detection.

Usage::

    from rf_bench.yertai import ET5406A

    with ET5406A() as load:          # auto-detect CH340
        load.CC_mode(1.0)
        load.on()
        v, i, p, r = load.read_all()
        load.off()

    load = ET5406A("/dev/ttyUSB0")   # explicit port
"""

import serial.tools.list_ports
from ET54 import ET54


class ET5406AError(Exception):
    pass


class ET5406A:
    """Yertai ET5406A+ programmable DC load driver.

    Wrapper around upstream philpagel/ET54.py library (commit 82be1da, 2026-06-02)
    that maintains the original pyserial-based API surface for backward compatibility.
    """

    def __init__(self, port=None, baudrate=9600, timeout=2.0):
        """Initialize ET5406A+ electronic load.

        Args:
            port: Serial port path. If None, auto-detects CH340.
            baudrate: Serial baud rate (default 9600)
            timeout: Serial timeout in seconds (default 2.0)
        """
        if port is None:
            port = self._find_port()

        # Convert port to VISA resource string
        visa_resource = f"ASRL{port}::INSTR"

        # Initialize upstream ET54 library
        # timeout is in milliseconds for ET54
        try:
            self._inst = ET54(
                visa_resource,
                baudrate=baudrate,
                timeout=int(timeout * 1000)
            )
        except Exception as e:
            raise ET5406AError(f"Failed to connect to ET5406A+ at {port}: {e}")

        # Single-channel device — expose ch1 directly
        self._ch = self._inst.ch1

        # Extract identification from upstream
        self.model = self._inst.idn.get("model", "ET5406A+")
        self.serial_n = self._inst.idn.get("SN", "")
        self.firmware = self._inst.idn.get("firmware", "")
        self.hardware = self._inst.idn.get("hardware", "")

    @staticmethod
    def _find_port():
        """Return the first CH340 serial port found."""
        for p in serial.tools.list_ports.comports():
            hwid = (p.hwid or "").lower()
            desc = (p.description or "").lower()
            if "1a86:7523" in hwid or "ch340" in desc or "ch341" in desc:
                return p.device
        raise ET5406AError(
            "No ET5406A+ found (no CH340 adapter detected). "
            "Pass port= explicitly, e.g. ET5406A('/dev/ttyUSB0')."
        )

    @classmethod
    def find_device(cls):
        """Return an ET5406A connected to the first detected device, or None."""
        try:
            return cls()
        except ET5406AError:
            return None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        """Unlock front panel and close connection."""
        try:
            self._inst.unlock()
        except Exception:
            pass
        self._inst.close()

    def __repr__(self):
        return (f"ET5406A(model={self.model!r}, sn={self.serial_n!r}, "
                f"fw={self.firmware!r}, hw={self.hardware!r})")

    # ------------------------------------------------------------------
    # Escape hatch — raw serial commands
    # ------------------------------------------------------------------

    def write(self, cmd: str) -> None:
        """Send raw command to the load without expecting a response.

        This is an "escape hatch" for sending commands not yet wrapped by the driver.

        Args:
            cmd: Command string (will be sent as-is to the serial port)

        Example:
            >>> load.write(":SYST:BEEP")

        Warning:
            Use with caution. Invalid commands may put the instrument in an
            unexpected state. Consult the ET5406A+ programming manual for valid
            commands.
        """
        self._inst.write(cmd)

    def query(self, cmd: str) -> str:
        """Send raw query to the load and return the response.

        This is an "escape hatch" for sending queries not yet wrapped by the driver.

        Args:
            cmd: Query string (should typically end with '?')

        Returns:
            Response string from instrument

        Example:
            >>> model = load.query(":SYST:VERS?")

        Warning:
            Use with caution. Invalid queries may hang or return unexpected data.
            Consult the ET5406A+ programming manual for valid commands.
        """
        return self._inst.query(cmd)

    # ------------------------------------------------------------------
    # Utility commands
    # ------------------------------------------------------------------

    def beep(self):
        """Trigger beeper."""
        self._inst.beep()

    def reset(self):
        """Reset device to factory defaults."""
        self._inst.reset()

    def unlock(self):
        """Release front-panel key lock."""
        self._inst.unlock()

    def fan(self):
        """Return fan state string."""
        return self._inst.fan()

    def on(self):
        """Enable load input."""
        self._ch.on()

    def off(self):
        """Disable load input."""
        self._ch.off()

    # ------------------------------------------------------------------
    # Input / mode / range
    # ------------------------------------------------------------------

    @property
    def input(self):
        """Input state: 'ON' or 'OFF'."""
        return self._ch.input

    @input.setter
    def input(self, value):
        self._ch.input = value

    @property
    def mode(self):
        """Operating mode: CC|CV|CP|CR|CCCV|CRCV|TRAN|LIST|SCAN|SHOR|BATT|LED."""
        return self._ch.mode

    @mode.setter
    def mode(self, value):
        self._ch.mode = value

    @property
    def Vrange(self):
        """Voltage range: 'HIGH' or 'LOW'."""
        return self._ch.Vrange

    @Vrange.setter
    def Vrange(self, value):
        self._ch.Vrange = value

    @property
    def Crange(self):
        """Current range: 'HIGH' or 'LOW'."""
        return self._ch.Crange

    @Crange.setter
    def Crange(self, value):
        self._ch.Crange = value

    # ------------------------------------------------------------------
    # Protection limits
    # ------------------------------------------------------------------

    @property
    def OVP(self):
        """Over-voltage protection limit [V]."""
        return self._ch.OVP

    @OVP.setter
    def OVP(self, value):
        self._ch.OVP = value

    @property
    def OCP(self):
        """Over-current protection limit [A]."""
        return self._ch.OCP

    @OCP.setter
    def OCP(self, value):
        self._ch.OCP = value

    @property
    def OPP(self):
        """Over-power protection limit [W]."""
        return self._ch.OPP

    @OPP.setter
    def OPP(self, value):
        self._ch.OPP = value

    @property
    def protection(self):
        """Active protection state: NONE|OV|OC|OP|OT|LRV|FAN."""
        return self._ch.protection

    # ------------------------------------------------------------------
    # CC mode
    # ------------------------------------------------------------------

    def CC_mode(self, current):
        """Set constant-current mode and target [A]."""
        self._ch.CC_mode(current)

    @property
    def CC_current(self):
        """CC target current [A]."""
        return self._ch.CC_current

    @CC_current.setter
    def CC_current(self, value):
        self._ch.CC_current = value

    # ------------------------------------------------------------------
    # CV mode
    # ------------------------------------------------------------------

    def CV_mode(self, voltage):
        """Set constant-voltage mode and target [V]."""
        self._ch.CV_mode(voltage)

    @property
    def CV_voltage(self):
        """CV target voltage [V]."""
        return self._ch.CV_voltage

    @CV_voltage.setter
    def CV_voltage(self, value):
        self._ch.CV_voltage = value

    # ------------------------------------------------------------------
    # CP mode
    # ------------------------------------------------------------------

    def CP_mode(self, power):
        """Set constant-power mode and target [W]."""
        self._ch.CP_mode(power)

    @property
    def CP_power(self):
        """CP target power [W]."""
        return self._ch.CP_power

    @CP_power.setter
    def CP_power(self, value):
        self._ch.CP_power = value

    # ------------------------------------------------------------------
    # CR mode
    # ------------------------------------------------------------------

    def CR_mode(self, resistance):
        """Set constant-resistance mode and target [Ω]."""
        self._ch.CR_mode(resistance)

    @property
    def CR_resistance(self):
        """CR target resistance [Ω]."""
        return self._ch.CR_resistance

    @CR_resistance.setter
    def CR_resistance(self, value):
        self._ch.CR_resistance = value

    # ------------------------------------------------------------------
    # CC+CV mode
    # ------------------------------------------------------------------

    def CCCV_mode(self, current, voltage):
        """Set CC+CV mode."""
        self._ch.CCCV_mode(current, voltage)

    @property
    def CCCV_current(self):
        return self._ch.CCCV_current

    @CCCV_current.setter
    def CCCV_current(self, value):
        self._ch.CCCV_current = value

    @property
    def CCCV_voltage(self):
        return self._ch.CCCV_voltage

    @CCCV_voltage.setter
    def CCCV_voltage(self, value):
        self._ch.CCCV_voltage = value

    # ------------------------------------------------------------------
    # CR+CV mode
    # ------------------------------------------------------------------

    def CRCV_mode(self, resistance, voltage):
        """Set CR+CV mode."""
        self._ch.CRCV_mode(resistance, voltage)

    @property
    def CRCV_resistance(self):
        return self._ch.CRCV_resistance

    @CRCV_resistance.setter
    def CRCV_resistance(self, value):
        self._ch.CRCV_resistance = value

    @property
    def CRCV_voltage(self):
        return self._ch.CRCV_voltage

    @CRCV_voltage.setter
    def CRCV_voltage(self, value):
        self._ch.CRCV_voltage = value

    # ------------------------------------------------------------------
    # Short mode
    # ------------------------------------------------------------------

    def SHORT_mode(self):
        """Set short-circuit mode. Use with caution."""
        self._ch.SHORT_mode()

    # ------------------------------------------------------------------
    # LED mode
    # ------------------------------------------------------------------

    def LED_mode(self, voltage, current, coefficient):
        """Set LED simulation mode.

        voltage:     V0 reference forward voltage [V]
        current:     I0 reference forward current [A]
        coefficient: Rd = (V0/I0) * coefficient
        """
        self._ch.LED_mode(voltage, current, coefficient)

    @property
    def LED_voltage(self):
        return self._ch.LED_voltage

    @LED_voltage.setter
    def LED_voltage(self, value):
        self._ch.LED_voltage = value

    @property
    def LED_current(self):
        return self._ch.LED_current

    @LED_current.setter
    def LED_current(self, value):
        self._ch.LED_current = value

    @property
    def LED_coefficient(self):
        return self._ch.LED_coefficient

    @LED_coefficient.setter
    def LED_coefficient(self, value):
        self._ch.LED_coefficient = value

    # ------------------------------------------------------------------
    # Battery discharge mode
    # ------------------------------------------------------------------

    def BATT_mode(self, mode, value, cutoff, cutoff_value):
        """Set battery discharge mode.

        mode:         'CC' or 'CR'
        value:        current [A] (CC) or resistance [Ω] (CR).
                      For CC + voltage cutoff: list of up to 3 step currents.
        cutoff:       'V' (voltage), 'T' (time), 'E' (energy), 'C' (capacity)
        cutoff_value: cutoff threshold. For CC + voltage cutoff: list of up to 3 voltages.
        """
        self._ch.BATT_mode(mode, value, cutoff, cutoff_value)

    @property
    def BATT_submode(self):
        return self._ch.BATT_submode

    @BATT_submode.setter
    def BATT_submode(self, value):
        self._ch.BATT_submode = value

    @property
    def BATT_current(self):
        return self._ch.BATT_current

    @BATT_current.setter
    def BATT_current(self, value):
        self._ch.BATT_current = value

    @property
    def BATT_resistance(self):
        return self._ch.BATT_resistance

    @BATT_resistance.setter
    def BATT_resistance(self, value):
        self._ch.BATT_resistance = value

    @property
    def BATT_cutoff(self):
        """Cutoff condition type (returned as word: Voltage/Time/Energy/Capacity)."""
        return self._ch.BATT_cutoff

    @BATT_cutoff.setter
    def BATT_cutoff(self, value):
        self._ch.BATT_cutoff = value

    @property
    def BATT_cutoff_value(self):
        return self._ch.BATT_cutoff_value

    @BATT_cutoff_value.setter
    def BATT_cutoff_value(self, value):
        self._ch.BATT_cutoff_value = value

    @property
    def BATT_capacity(self):
        """Accumulated discharge capacity [Ah]."""
        return self._ch.BATT_capacity

    @property
    def BATT_energy(self):
        """Accumulated discharge energy [Wh]."""
        return self._ch.BATT_energy

    @property
    def BATT_cutoff_level(self):
        """Active CC+voltage step level (1|2|3); 3 is the initial state."""
        return self._ch.BATT_cutoff_level

    @BATT_cutoff_level.setter
    def BATT_cutoff_level(self, value):
        self._ch.BATT_cutoff_level = value

    # ------------------------------------------------------------------
    # Transient (dynamic) mode
    # ------------------------------------------------------------------

    def TRANSIENT_mode(self, mode, trigmode, value, width):
        """Set transient mode.

        mode:     'CC' or 'CV'
        trigmode: 'CONT', 'TRIG', or 'PULS'
        value:    (low, high) in A (CC) or V (CV)
        width:    (width_A_s, width_B_s) pulse widths in seconds
        """
        self._ch.TRANSIENT_mode(mode, trigmode, value, width)

    @property
    def TRANSIENT_submode(self):
        return self._ch.TRANSIENT_submode

    @TRANSIENT_submode.setter
    def TRANSIENT_submode(self, value):
        self._ch.TRANSIENT_submode = value

    @property
    def TRANSIENT_trigmode(self):
        return self._ch.TRANSIENT_trigmode

    @TRANSIENT_trigmode.setter
    def TRANSIENT_trigmode(self, value):
        self._ch.TRANSIENT_trigmode = value

    @property
    def TRANSIENT_current(self):
        """(I_A, I_B) [A]."""
        return self._ch.TRANSIENT_current

    @TRANSIENT_current.setter
    def TRANSIENT_current(self, value):
        self._ch.TRANSIENT_current = value

    @property
    def TRANSIENT_voltage(self):
        """(V_A, V_B) [V]."""
        return self._ch.TRANSIENT_voltage

    @TRANSIENT_voltage.setter
    def TRANSIENT_voltage(self, value):
        self._ch.TRANSIENT_voltage = value

    @property
    def TRANSIENT_width(self):
        """(width_A, width_B) [s]."""
        return self._ch.TRANSIENT_width

    @TRANSIENT_width.setter
    def TRANSIENT_width(self, value):
        self._ch.TRANSIENT_width = value

    # ------------------------------------------------------------------
    # List mode
    # ------------------------------------------------------------------

    def LIST_mode(self, stepmode, params):
        """Set list mode.

        stepmode: 'AUTO' or 'TRIGGER'
        params:   list of row dicts or tuples:
                  (num, mode, value, delay_s, comp, maxval, minval)
                  mode: CC|CV|CP|CR|OPEN|SHORT
                  comp: OFF|CURRENT|VOLTAGE|POWER|RESISTANCE
        """
        self._ch.LIST_mode(stepmode, params)

    @property
    def LIST_stepmode(self):
        return self._ch.LIST_stepmode

    @LIST_stepmode.setter
    def LIST_stepmode(self, value):
        self._ch.LIST_stepmode = value

    @property
    def LIST_loop(self):
        return self._ch.LIST_loop

    @LIST_loop.setter
    def LIST_loop(self, value):
        self._ch.LIST_loop = value

    @property
    def LIST_steps(self):
        return self._ch.LIST_steps

    @LIST_steps.setter
    def LIST_steps(self, value):
        self._ch.LIST_steps = value

    @property
    def LIST_rows(self):
        """All 10 list rows as a list of dicts."""
        return self._ch.LIST_rows

    @LIST_rows.setter
    def LIST_rows(self, params):
        self._ch.LIST_rows = params

    def LIST_result(self):
        """Return LIST mode execution results."""
        return self._ch.LIST_result()

    # ------------------------------------------------------------------
    # Scan mode
    # ------------------------------------------------------------------

    def SCAN_mode(self, mode, threshold, threshold_value, compare,
                  limits, start_end, step, step_time):
        """Configure and enter SCAN mode.

        mode:            'CC', 'CV', or 'CP'
        threshold:       'VTH', 'DROP', or 'VMIN'
        threshold_value: voltage threshold [V] (ignored for DROP)
        compare:         'INCURR', 'INVOLT', 'INPOW', or 'OFF'
        limits:          (low, high) for comparison
        start_end:       (start, end) sweep range
        step:            step size
        step_time:       time per step [s]
        """
        self._ch.SCAN_mode(mode, threshold, threshold_value, compare,
                          limits, start_end, step, step_time)

    @property
    def SCAN_submode(self):
        return self._ch.SCAN_submode

    @SCAN_submode.setter
    def SCAN_submode(self, value):
        self._ch.SCAN_submode = value

    @property
    def SCAN_threshold(self):
        return self._ch.SCAN_threshold

    @SCAN_threshold.setter
    def SCAN_threshold(self, value):
        self._ch.SCAN_threshold = value

    @property
    def SCAN_threshold_value(self):
        return self._ch.SCAN_threshold_value

    @SCAN_threshold_value.setter
    def SCAN_threshold_value(self, value):
        self._ch.SCAN_threshold_value = value

    @property
    def SCAN_compare(self):
        return self._ch.SCAN_compare

    @SCAN_compare.setter
    def SCAN_compare(self, value):
        self._ch.SCAN_compare = value

    @property
    def SCAN_limits(self):
        """(low, high) comparison limits."""
        return self._ch.SCAN_limits

    @SCAN_limits.setter
    def SCAN_limits(self, value):
        self._ch.SCAN_limits = value

    @property
    def SCAN_start_end(self):
        """(start, end) sweep range."""
        return self._ch.SCAN_start_end

    @SCAN_start_end.setter
    def SCAN_start_end(self, value):
        self._ch.SCAN_start_end = value

    @property
    def SCAN_step(self):
        return self._ch.SCAN_step

    @SCAN_step.setter
    def SCAN_step(self, value):
        self._ch.SCAN_step = value

    @property
    def SCAN_stepdelay(self):
        """Time per scan step [s]."""
        return self._ch.SCAN_stepdelay

    @SCAN_stepdelay.setter
    def SCAN_stepdelay(self, value):
        self._ch.SCAN_stepdelay = value

    # ------------------------------------------------------------------
    # Qualification test
    # ------------------------------------------------------------------

    def QUALI_mode(self, Vrange, Crange, Prange):
        """Enable qualification test.

        Vrange, Crange, Prange: (low, high) limit tuples
        """
        self._ch.QUALI_mode(Vrange, Crange, Prange)

    @property
    def QUALI_state(self):
        return self._ch.QUALI_state

    @QUALI_state.setter
    def QUALI_state(self, value):
        self._ch.QUALI_state = value

    @property
    def QUALI_result(self):
        """Qualification result: NONE|PASS|FAIL."""
        return self._ch.QUALI_result

    @property
    def QUALI_Vrange(self):
        return self._ch.QUALI_Vrange

    @QUALI_Vrange.setter
    def QUALI_Vrange(self, value):
        self._ch.QUALI_Vrange = value

    @property
    def QUALI_Crange(self):
        return self._ch.QUALI_Crange

    @QUALI_Crange.setter
    def QUALI_Crange(self, value):
        self._ch.QUALI_Crange = value

    @property
    def QUALI_Prange(self):
        return self._ch.QUALI_Prange

    @QUALI_Prange.setter
    def QUALI_Prange(self, value):
        self._ch.QUALI_Prange = value

    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------

    @property
    def trigger_mode(self):
        """Trigger source: MAN|EXT|TRG."""
        return self._ch.trigger_mode

    @trigger_mode.setter
    def trigger_mode(self, value):
        self._ch.trigger_mode = value

    def trigger(self):
        """Send a remote trigger event."""
        self._ch.trigger()

    # ------------------------------------------------------------------
    # Measurement
    # ------------------------------------------------------------------

    def read_voltage(self):
        """Measure input voltage [V]."""
        return self._ch.read_voltage()

    def read_current(self):
        """Measure input current [A]."""
        return self._ch.read_current()

    def read_power(self):
        """Measure input power [W]."""
        return self._ch.read_power()

    def read_resistance(self):
        """Measure input resistance [Ω]."""
        return self._ch.read_resistance()

    def read_all(self):
        """Measure all channels: returns (voltage_V, current_A, power_W, resistance_Ω).

        Note: Upstream read_all() returns raw order (current, voltage, power, resistance).
        This wrapper reorders to maintain backward compatibility with the original API.
        """
        current_a, voltage_v, power_w, resistance_ohm = self._ch.read_all()
        return (voltage_v, current_a, power_w, resistance_ohm)
