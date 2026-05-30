"""
et5406a.py — Yertai ET5406A+ programmable DC load

200 W / 120 V / 20 A.  Single channel.  USB connection via CH340 serial adapter.
Uses pyserial directly — no pyvisa required.

Usage::

    from rf_bench.yertai import ET5406A

    with ET5406A() as load:          # auto-detect CH340
        load.CC_mode(1.0)
        load.on()
        v, i, p, r = load.read_all()
        load.off()

    load = ET5406A("/dev/ttyUSB0")   # explicit port
"""

import time
import serial
import serial.tools.list_ports


BAUD_RATE   = 9600
TIMEOUT     = 2.0   # serial read timeout, seconds
QUERY_DELAY = 0.2   # seconds between write and read


class ET5406AError(Exception):
    pass


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------

def _strip(response):
    """Strip leading 'R' prefix from all query responses."""
    s = response.strip()
    return s[1:] if s.startswith("R") else s


def _toint(response):
    return int(_strip(response))


def _tofloat(response):
    return float(_strip(response))


def _tofloats(response):
    return [float(x) for x in _strip(response).split()]


def _value_extend(x, n):
    """Extend scalar or short list/tuple to exactly length n by repeating last element."""
    if isinstance(x, (int, float)):
        x = [x]
    else:
        x = list(x)
    if not 0 < len(x) <= n:
        raise ValueError(f"Expected 1–{n} values, got {len(x)}")
    x += [x[-1]] * (n - len(x))
    return x


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class ET5406A:
    """Yertai ET5406A+ programmable DC load driver."""

    _CH = "1"  # single-channel device — SCPI channel designator

    def __init__(self, port=None, baudrate=BAUD_RATE, timeout=TIMEOUT):
        if port is None:
            port = self._find_port()
        self._ser = serial.Serial(port, baudrate=baudrate, timeout=timeout)
        time.sleep(0.1)
        idn = self._query("*IDN?")
        parts = idn.split()
        if len(parts) != 4:
            raise ET5406AError(f"Unexpected IDN response: {idn!r}")
        self.model    = parts[0]
        self.serial_n = parts[1]
        self.firmware = parts[2]
        self.hardware = parts[3]

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
        """Unlock front panel and close serial port."""
        try:
            self._write("SYST:LOCA")
        except Exception:
            pass
        self._ser.close()

    def __repr__(self):
        return (f"ET5406A(model={self.model!r}, sn={self.serial_n!r}, "
                f"fw={self.firmware!r}, hw={self.hardware!r})")

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    def _query(self, cmd):
        self._ser.write((cmd + "\n").encode())
        time.sleep(QUERY_DELAY)
        return self._ser.read_until(b"\r\n").decode().strip()

    def _query_n(self, cmd, n, extra_timeout=0.5):
        """Send command and read n response lines."""
        self._ser.write((cmd + "\n").encode())
        time.sleep(QUERY_DELAY + extra_timeout)
        return [self._ser.read_until(b"\r\n").decode().strip() for _ in range(n)]

    def _write(self, cmd):
        self._ser.write((cmd + "\n").encode())
        time.sleep(QUERY_DELAY)
        resp = self._ser.read_until(b"\r\n").decode().strip()
        if resp == "Rexecu success":
            return
        elif resp == "Rcmd err":
            raise ET5406AError(f"Unknown command: {cmd!r}")
        elif resp == "Rexecu err":
            raise ET5406AError(f"Command execution failed: {cmd!r}")
        else:
            raise ET5406AError(f"Unexpected response to {cmd!r}: {resp!r}")

    # ------------------------------------------------------------------
    # Instrument commands
    # ------------------------------------------------------------------

    def beep(self):
        self._write("SYST:BEEP")

    def reset(self):
        """Reset device to factory defaults."""
        self._ser.write(b"RST\n")

    def unlock(self):
        """Release front-panel key lock."""
        self._write("SYST:LOCA")

    def fan(self):
        """Return fan state string."""
        return self._query("SELF:FAN?")

    def on(self):
        """Enable load input."""
        self._write(f"Ch{self._CH}:SW ON")

    def off(self):
        """Disable load input."""
        self._write(f"Ch{self._CH}:SW OFF")

    # ------------------------------------------------------------------
    # Input / mode / range
    # ------------------------------------------------------------------

    @property
    def input(self):
        """Input state: 'ON' or 'OFF'."""
        return self._query(f"Ch{self._CH}:SW?")

    @input.setter
    def input(self, value):
        v = value.upper()
        if v not in ("ON", "OFF"):
            raise ValueError(f"input must be 'ON' or 'OFF'")
        self._write(f"Ch{self._CH}:SW {v}")

    @property
    def mode(self):
        """Operating mode: CC|CV|CP|CR|CCCV|CRCV|TRAN|LIST|SCAN|SHOR|BATT|LED."""
        return self._query(f"Ch{self._CH}:MODE?")

    @mode.setter
    def mode(self, value):
        v = value.upper()
        valid = {"CC","CV","CP","CR","CCCV","CRCV","TRAN","LIST","SCAN","SHOR","BATT","LED"}
        if v not in valid:
            raise ValueError(f"mode must be one of {sorted(valid)}")
        self._write(f"Ch{self._CH}:MODE {v}")

    @property
    def Vrange(self):
        """Voltage range: 'HIGH' or 'LOW'."""
        return self._query(f"LOAD{self._CH}:VRANGE?")

    @Vrange.setter
    def Vrange(self, value):
        if value.lower() not in ("high", "low"):
            raise ValueError("Vrange must be 'high' or 'low'")
        self._write(f"LOAD{self._CH}:VRANge {value}")

    @property
    def Crange(self):
        """Current range: 'HIGH' or 'LOW'."""
        return self._query(f"LOAD{self._CH}:CRANGE?")

    @Crange.setter
    def Crange(self, value):
        if value.lower() not in ("high", "low"):
            raise ValueError("Crange must be 'high' or 'low'")
        self._write(f"LOAD{self._CH}:CRANge {value}")

    # ------------------------------------------------------------------
    # Protection limits
    # ------------------------------------------------------------------

    @property
    def OVP(self):
        """Over-voltage protection limit [V]."""
        return _tofloat(self._query(f"VOLT{self._CH}:VMAX?"))

    @OVP.setter
    def OVP(self, value):
        self._write(f"VOLT{self._CH}:VMAX {value}")

    @property
    def OCP(self):
        """Over-current protection limit [A]."""
        return _tofloat(self._query(f"CURR{self._CH}:IMAX?"))

    @OCP.setter
    def OCP(self, value):
        self._write(f"CURR{self._CH}:IMAX {value}")

    @property
    def OPP(self):
        """Over-power protection limit [W]."""
        return _tofloat(self._query(f"POWE{self._CH}:PMAX?"))

    @OPP.setter
    def OPP(self, value):
        self._write(f"POWE{self._CH}:PMAX {value}")

    @property
    def protection(self):
        """Active protection state: NONE|OV|OC|OP|OT|LRV|FAN."""
        return self._query(f"LOAD{self._CH}:ABNO?")

    # ------------------------------------------------------------------
    # CC mode
    # ------------------------------------------------------------------

    def CC_mode(self, current):
        """Set constant-current mode and target [A]."""
        self.CC_current = current
        self.mode = "CC"

    @property
    def CC_current(self):
        """CC target current [A]."""
        return _tofloat(self._query(f"CURR{self._CH}:CC?"))

    @CC_current.setter
    def CC_current(self, value):
        self._write(f"CURR{self._CH}:CC {value}")

    # ------------------------------------------------------------------
    # CV mode
    # ------------------------------------------------------------------

    def CV_mode(self, voltage):
        """Set constant-voltage mode and target [V]."""
        self.CV_voltage = voltage
        self.mode = "CV"

    @property
    def CV_voltage(self):
        """CV target voltage [V]."""
        return _tofloat(self._query(f"VOLT{self._CH}:CV?"))

    @CV_voltage.setter
    def CV_voltage(self, value):
        self._write(f"VOLT{self._CH}:CV {value}")

    # ------------------------------------------------------------------
    # CP mode
    # ------------------------------------------------------------------

    def CP_mode(self, power):
        """Set constant-power mode and target [W]."""
        self.CP_power = power
        self.mode = "CP"

    @property
    def CP_power(self):
        """CP target power [W]."""
        return _tofloat(self._query(f"POWE{self._CH}:CP?"))

    @CP_power.setter
    def CP_power(self, value):
        self._write(f"POWE{self._CH}:CP {value}")

    # ------------------------------------------------------------------
    # CR mode
    # ------------------------------------------------------------------

    def CR_mode(self, resistance):
        """Set constant-resistance mode and target [Ω]."""
        self.CR_resistance = resistance
        self.mode = "CR"

    @property
    def CR_resistance(self):
        """CR target resistance [Ω]."""
        return _tofloat(self._query(f"RESI{self._CH}:CR?"))

    @CR_resistance.setter
    def CR_resistance(self, value):
        self._write(f"RESI{self._CH}:CR {value}")

    # ------------------------------------------------------------------
    # CC+CV mode
    # ------------------------------------------------------------------

    def CCCV_mode(self, current, voltage):
        """Set CC+CV mode."""
        self.CCCV_current = current
        self.CCCV_voltage = voltage
        self.mode = "CCCV"

    @property
    def CCCV_current(self):
        return _tofloat(self._query(f"CURR{self._CH}:CCCV?"))

    @CCCV_current.setter
    def CCCV_current(self, value):
        self._write(f"CURR{self._CH}:CCCV {value}")

    @property
    def CCCV_voltage(self):
        return _tofloat(self._query(f"VOLT{self._CH}:CCCV?"))

    @CCCV_voltage.setter
    def CCCV_voltage(self, value):
        self._write(f"VOLT{self._CH}:CCCV {value}")

    # ------------------------------------------------------------------
    # CR+CV mode
    # ------------------------------------------------------------------

    def CRCV_mode(self, resistance, voltage):
        """Set CR+CV mode."""
        self.CRCV_resistance = resistance
        self.CRCV_voltage = voltage
        self.mode = "CRCV"

    @property
    def CRCV_resistance(self):
        return _tofloat(self._query(f"RESI{self._CH}:CRCV?"))

    @CRCV_resistance.setter
    def CRCV_resistance(self, value):
        self._write(f"RESI{self._CH}:CRCV {value}")

    @property
    def CRCV_voltage(self):
        return _tofloat(self._query(f"VOLT{self._CH}:CRCV?"))

    @CRCV_voltage.setter
    def CRCV_voltage(self, value):
        self._write(f"VOLT{self._CH}:CRCV {value}")

    # ------------------------------------------------------------------
    # Short mode
    # ------------------------------------------------------------------

    def SHORT_mode(self):
        """Set short-circuit mode. Use with caution."""
        self.mode = "SHOR"

    # ------------------------------------------------------------------
    # LED mode
    # ------------------------------------------------------------------

    def LED_mode(self, voltage, current, coefficient):
        """Set LED simulation mode.

        voltage:     V0 reference forward voltage [V]
        current:     I0 reference forward current [A]
        coefficient: Rd = (V0/I0) * coefficient
        """
        self.LED_voltage    = voltage
        self.LED_current    = current
        self.LED_coefficient = coefficient
        self.mode = "LED"

    @property
    def LED_voltage(self):
        return _tofloat(self._query(f"VOLT{self._CH}:LED?"))

    @LED_voltage.setter
    def LED_voltage(self, value):
        self._write(f"VOLT{self._CH}:LED {value}")

    @property
    def LED_current(self):
        return _tofloat(self._query(f"CURR{self._CH}:LED?"))

    @LED_current.setter
    def LED_current(self, value):
        self._write(f"CURR{self._CH}:LED {value}")

    @property
    def LED_coefficient(self):
        return _tofloat(self._query(f"LED{self._CH}:COEF?"))

    @LED_coefficient.setter
    def LED_coefficient(self, value):  # upstream was missing 'value' parameter
        self._write(f"LED{self._CH}:COEF {value}")

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
        self.BATT_submode = mode
        self.BATT_cutoff = cutoff
        if mode.upper() == "CC":
            self.BATT_current = value
        elif mode.upper() == "CR":
            self.BATT_resistance = value
        else:
            raise ValueError(f"BATT submode must be 'CC' or 'CR'")
        self.BATT_cutoff_value = cutoff_value
        self.mode = "BATT"

    @property
    def BATT_submode(self):
        return self._query(f"BATT{self._CH}:MODE?")

    @BATT_submode.setter
    def BATT_submode(self, value):
        v = value.upper()
        if v not in ("CC", "CR"):
            raise ValueError("BATT submode must be 'CC' or 'CR'")
        self._write(f"BATT{self._CH}:MODE {v}")

    @property
    def BATT_current(self):
        if self.BATT_cutoff == "Voltage":
            return tuple(_tofloat(self._query(f"CURR{self._CH}:BCC{i}?")) for i in (1, 2, 3))
        return _tofloat(self._query(f"CURR{self._CH}:BCC?"))

    @BATT_current.setter
    def BATT_current(self, value):
        if self.BATT_cutoff == "Voltage":
            for i, v in enumerate(_value_extend(value, 3), 1):
                self._write(f"CURR{self._CH}:BCC{i} {v}")
        else:
            self._write(f"CURR{self._CH}:BCC {value}")

    @property
    def BATT_resistance(self):
        return _tofloat(self._query(f"RESI{self._CH}:BCR?"))

    @BATT_resistance.setter
    def BATT_resistance(self, value):
        self._write(f"RESI{self._CH}:BCR {value}")

    @property
    def BATT_cutoff(self):
        """Cutoff condition type (returned as word: Voltage/Time/Energy/Capacity)."""
        return self._query(f"BATT{self._CH}:BCUT?")

    @BATT_cutoff.setter
    def BATT_cutoff(self, value):
        self._write(f"BATT{self._CH}:BCUT {value}")

    @property
    def BATT_cutoff_value(self):
        match self.BATT_cutoff:
            case "Voltage":
                if self.BATT_submode == "CC":
                    return tuple(_tofloat(self._query(f"VOLT{self._CH}:BCC{i}?")) for i in (1, 2, 3))
                return _tofloat(self._query(f"CURR{self._CH}:BCC?"))
            case "Time":
                return _tofloat(self._query(f"TIME{self._CH}:BTT?"))
            case "Capacity":
                return _tofloat(self._query(f"BATT{self._CH}:BTC?"))
            case "Energy":
                return _tofloat(self._query(f"BATT{self._CH}:BTE?"))

    @BATT_cutoff_value.setter
    def BATT_cutoff_value(self, value):
        match self.BATT_cutoff:
            case "Voltage":
                for i, v in enumerate(_value_extend(value, 3), 1):
                    self._write(f"VOLT{self._CH}:BCC{i} {v}")
            case "Time":
                self._write(f"TIME{self._CH}:BTT {value}")
            case "Capacity":
                self._write(f"BATT{self._CH}:BTC {value}")
            case "Energy":
                self._write(f"BATT{self._CH}:BTE {value}")

    @property
    def BATT_capacity(self):
        """Accumulated discharge capacity [Ah]."""
        return _tofloat(self._query(f"BATT{self._CH}:CAPA?"))

    @property
    def BATT_energy(self):
        """Accumulated discharge energy [Wh]."""
        return _tofloat(self._query(f"BATT{self._CH}:ENER?"))

    @property
    def BATT_cutoff_level(self):
        """Active CC+voltage step level (1|2|3); 3 is the initial state."""
        return _toint(self._query(f"BATT{self._CH}:BAEN?"))

    @BATT_cutoff_level.setter
    def BATT_cutoff_level(self, value):
        self._write(f"BATT{self._CH}:BAEN {value}")

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
        self.TRANSIENT_submode  = mode.upper()
        self.TRANSIENT_trigmode = trigmode
        if mode.upper() == "CC":
            self.TRANSIENT_current = value
        elif mode.upper() == "CV":
            self.TRANSIENT_voltage = value
        else:
            raise ValueError("TRANSIENT mode must be 'CC' or 'CV'")
        self.TRANSIENT_width = width
        self.mode = "TRAN"

    @property
    def TRANSIENT_submode(self):  # upstream had typo 'seld' here
        return self._query(f"TRAN{self._CH}:STATE?")

    @TRANSIENT_submode.setter
    def TRANSIENT_submode(self, value):
        v = value.upper()
        if v not in ("CC", "CV"):
            raise ValueError("TRANSIENT submode must be 'CC' or 'CV'")
        self._write(f"TRAN{self._CH}:STATE {v}")

    @property
    def TRANSIENT_trigmode(self):
        return self._query(f"TRAN{self._CH}:MODE?")

    @TRANSIENT_trigmode.setter
    def TRANSIENT_trigmode(self, value):
        v = value.upper()
        if v == "CONT":
            v = "COUT"
        if v not in ("COUT", "PULS", "TRIG"):
            raise ValueError("trigmode must be CONT/PULS/TRIG")
        self._write(f"TRAN{self._CH}:MODE {v}")

    @property
    def TRANSIENT_current(self):
        """(I_A, I_B) [A]."""
        return (
            _tofloat(self._query(f"CURR{self._CH}:TA?")),
            _tofloat(self._query(f"CURR{self._CH}:TB?")),
        )

    @TRANSIENT_current.setter
    def TRANSIENT_current(self, value):
        if len(value) != 2:
            raise ValueError("TRANSIENT_current requires (I_A, I_B)")
        self._write(f"CURR{self._CH}:TA {value[0]}")
        self._write(f"CURR{self._CH}:TB {value[1]}")

    @property
    def TRANSIENT_voltage(self):
        """(V_A, V_B) [V]."""
        return (
            _tofloat(self._query(f"VOLT{self._CH}:TA?")),
            _tofloat(self._query(f"VOLT{self._CH}:TB?")),
        )

    @TRANSIENT_voltage.setter
    def TRANSIENT_voltage(self, value):
        if len(value) != 2:
            raise ValueError("TRANSIENT_voltage requires (V_A, V_B)")
        self._write(f"VOLT{self._CH}:TA {value[0]}")
        self._write(f"VOLT{self._CH}:TB {value[1]}")

    @property
    def TRANSIENT_width(self):
        """(width_A, width_B) [s]."""
        return (
            _tofloat(self._query(f"TIME{self._CH}:WA?")),
            _tofloat(self._query(f"TIME{self._CH}:WB?")),
        )

    @TRANSIENT_width.setter
    def TRANSIENT_width(self, value):
        if len(value) != 2:
            raise ValueError("TRANSIENT_width requires (width_A, width_B)")
        self._write(f"TIME{self._CH}:WA {value[0]}")
        self._write(f"TIME{self._CH}:WB {value[1]}")

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
        self.LIST_stepmode = stepmode
        self.LIST_rows = params
        self.mode = "LIST"

    @property
    def LIST_stepmode(self):
        return self._query(f"LIST{self._CH}:MODE?")

    @LIST_stepmode.setter
    def LIST_stepmode(self, value):
        self._write(f"LIST{self._CH}:MODE {value.upper()}")

    @property
    def LIST_loop(self):
        return self._query(f"LIST{self._CH}:LOOP?")

    @LIST_loop.setter
    def LIST_loop(self, value):
        self._write(f"LIST{self._CH}:LOOP {value.upper()}")

    @property
    def LIST_steps(self):
        return _toint(self._query(f"LIST{self._CH}:NUM?"))

    @LIST_steps.setter
    def LIST_steps(self, value):
        self._write(f"LIST{self._CH}:NUM {value}")

    @property
    def LIST_rows(self):
        """All 10 list rows as a list of dicts."""
        lines = self._query_n(f"LIST{self._CH}:PARA? 1,10", 10, extra_timeout=0.5)
        rows = []
        for line in lines:
            s = _strip(line)
            fields = s.split(",")
            d = dict(zip(("num","mode","value","delay","comp","maxval","minval"), fields))
            d["mode"] = ["CC","CV","CP","CR","OPEN","SHORT"][int(d["mode"])]
            d["comp"] = ["OFF","CURRENT","VOLTAGE","POWER","RESISTANCE"][int(d["comp"])]
            d["num"]   = int(d["num"])
            d["delay"] = int(d["delay"])
            for k in ("value","maxval","minval"):
                try:
                    d[k] = float(d[k])
                except (ValueError, TypeError):
                    d[k] = None
            rows.append(d)
        return rows

    @LIST_rows.setter
    def LIST_rows(self, params):
        for row in params:
            if isinstance(row, dict):
                self._list_row(**row)
            else:
                self._list_row(*row)

    def _list_row(self, num, mode, value, delay, comp, maxval, minval):
        mode_i = {"CC":0,"CV":1,"CP":2,"CR":3,"OPEN":4,"SHORT":5}[mode.upper()]
        comp_i = {"OFF":0,"CURRENT":1,"VOLTAGE":2,"POWER":3,"RESISTANCE":4}[comp.upper()]
        params = ",".join(str(x) for x in [num, mode_i, value, delay, comp_i, maxval, minval])
        self._write(f"LIST{self._CH}:PARA {params}")

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
        self.SCAN_submode         = mode
        self.SCAN_threshold       = threshold
        self.SCAN_threshold_value = threshold_value
        self.SCAN_compare         = compare
        self.SCAN_limits          = limits
        self.SCAN_start_end       = start_end
        self.SCAN_step            = step
        self.SCAN_stepdelay       = step_time
        self.mode = "SCAN"

    @property
    def SCAN_submode(self):
        return self._query(f"SCAN{self._CH}:TYPE?")

    @SCAN_submode.setter
    def SCAN_submode(self, value):
        self._write(f"SCAN{self._CH}:TYPE {value}")

    @property
    def SCAN_threshold(self):
        return self._query(f"SCAN{self._CH}:THTYPE?")

    @SCAN_threshold.setter
    def SCAN_threshold(self, value):
        self._write(f"SCAN{self._CH}:THTYPE {value.upper()}")

    @property
    def SCAN_threshold_value(self):
        match self.SCAN_threshold:
            case "VTH":
                return _tofloat(self._query(f"VOLT{self._CH}:VTH?"))
            case "VMIN":
                return _tofloat(self._query(f"VOLT{self._CH}:VMIN?"))
            case _:
                return None

    @SCAN_threshold_value.setter
    def SCAN_threshold_value(self, value):
        match self.SCAN_threshold:
            case "VTH":
                self._write(f"VOLT{self._CH}:VTH {value}")
            case "VMIN":
                self._write(f"VOLT{self._CH}:VMIN {value}")

    @property
    def SCAN_compare(self):
        return self._query(f"SCAN{self._CH}:COMPARE?")

    @SCAN_compare.setter
    def SCAN_compare(self, value):
        self._write(f"SCAN{self._CH}:COMPARE {value.upper()}")

    @property
    def SCAN_limits(self):
        """(low, high) comparison limits."""
        match self.SCAN_submode:
            case "CC":
                return (_tofloat(self._query(f"CURR{self._CH}:LOW?")),
                        _tofloat(self._query(f"CURR{self._CH}:HIGH?")))
            case "CV":
                return (_tofloat(self._query(f"VOLT{self._CH}:LOW?")),
                        _tofloat(self._query(f"VOLT{self._CH}:HIGH?")))
            case "CP":
                return (_tofloat(self._query(f"POWE{self._CH}:LOW?")),
                        _tofloat(self._query(f"POWE{self._CH}:HIGH?")))

    @SCAN_limits.setter
    def SCAN_limits(self, value):
        low, high = value
        match self.SCAN_submode:
            case "CC":
                self._write(f"CURR{self._CH}:LOW {low}")
                self._write(f"CURR{self._CH}:HIGH {high}")
            case "CV":
                self._write(f"VOLT{self._CH}:LOW {low}")
                self._write(f"VOLT{self._CH}:HIGH {high}")
            case "CP":
                self._write(f"POWE{self._CH}:LOW {low}")
                self._write(f"POWE{self._CH}:HIGH {high}")

    @property
    def SCAN_start_end(self):
        """(start, end) sweep range."""
        match self.SCAN_submode:
            case "CC":
                return (_tofloat(self._query(f"CURR{self._CH}:START?")),
                        _tofloat(self._query(f"CURR{self._CH}:END?")))
            case "CV":
                return (_tofloat(self._query(f"VOLT{self._CH}:START?")),
                        _tofloat(self._query(f"VOLT{self._CH}:END?")))
            case "CP":
                return (_tofloat(self._query(f"POWE{self._CH}:START?")),
                        _tofloat(self._query(f"POWE{self._CH}:END?")))

    @SCAN_start_end.setter
    def SCAN_start_end(self, value):
        start, end = value
        match self.SCAN_submode:
            case "CC":
                self._write(f"CURR{self._CH}:START {start}")
                self._write(f"CURR{self._CH}:END {end}")
            case "CV":
                self._write(f"VOLT{self._CH}:START {start}")
                self._write(f"VOLT{self._CH}:END {end}")
            case "CP":
                self._write(f"POWE{self._CH}:START {start}")
                self._write(f"POWE{self._CH}:END {end}")

    @property
    def SCAN_step(self):
        match self.SCAN_submode:
            case "CC":
                return _tofloat(self._query(f"CURR{self._CH}:STEP?"))
            case "CV":
                return _tofloat(self._query(f"VOLT{self._CH}:STEP?"))
            case "CP":
                return _tofloat(self._query(f"POWE{self._CH}:STEP?"))

    @SCAN_step.setter
    def SCAN_step(self, value):
        match self.SCAN_submode:
            case "CC":
                self._write(f"CURR{self._CH}:STEP {value}")
            case "CV":
                self._write(f"VOLT{self._CH}:STEP {value}")
            case "CP":
                self._write(f"POWE{self._CH}:STEP {value}")

    @property
    def SCAN_stepdelay(self):
        """Time per scan step [s]."""
        return _toint(self._query(f"TIME{self._CH}:STEP?"))

    @SCAN_stepdelay.setter
    def SCAN_stepdelay(self, value):
        self._write(f"TIME{self._CH}:STEP {value}")

    # ------------------------------------------------------------------
    # Qualification test
    # ------------------------------------------------------------------

    def QUALI_mode(self, Vrange, Crange, Prange):
        """Enable qualification test.

        Vrange, Crange, Prange: (low, high) limit tuples
        """
        self.QUALI_Vrange = Vrange
        self.QUALI_Crange = Crange
        self.QUALI_Prange = Prange
        self.QUALI_state  = "ON"

    @property
    def QUALI_state(self):
        return self._query(f"QUAL{self._CH}:TEST?")

    @QUALI_state.setter
    def QUALI_state(self, value):
        self._write(f"QUAL{self._CH}:TEST {value}")  # upstream used query() here — bug

    @property
    def QUALI_result(self):
        """Qualification result: NONE|PASS|FAIL."""
        return self._query(f"QUAL{self._CH}:OUT?")

    @property
    def QUALI_Vrange(self):
        return (_tofloat(self._query(f"QUAL{self._CH}:VLOW?")),
                _tofloat(self._query(f"QUAL{self._CH}:VHIGH?")))

    @QUALI_Vrange.setter
    def QUALI_Vrange(self, value):
        self._write(f"QUAL{self._CH}:VLOW {value[0]}")
        self._write(f"QUAL{self._CH}:VHIGH {value[1]}")

    @property
    def QUALI_Crange(self):
        return (_tofloat(self._query(f"QUAL{self._CH}:CLOW?")),
                _tofloat(self._query(f"QUAL{self._CH}:CHIGH?")))

    @QUALI_Crange.setter
    def QUALI_Crange(self, value):
        self._write(f"QUAL{self._CH}:CLOW {value[0]}")
        self._write(f"QUAL{self._CH}:CHIGH {value[1]}")

    @property
    def QUALI_Prange(self):
        return (_tofloat(self._query(f"QUAL{self._CH}:PLOW?")),
                _tofloat(self._query(f"QUAL{self._CH}:PHIGH?")))

    @QUALI_Prange.setter
    def QUALI_Prange(self, value):
        self._write(f"QUAL{self._CH}:PLOW {value[0]}")
        self._write(f"QUAL{self._CH}:PHIGH {value[1]}")

    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------

    @property
    def trigger_mode(self):
        """Trigger source: MAN|EXT|TRG."""
        return self._query(f"LOAD{self._CH}:TRIG?")

    @trigger_mode.setter
    def trigger_mode(self, value):
        v = value.upper()
        if v not in ("MAN", "EXT", "TRG"):
            raise ValueError("trigger_mode must be MAN/EXT/TRG")
        self._write(f"LOAD{self._CH}:TRIG {v}")

    def trigger(self):
        """Send a remote trigger event."""
        self._write("*TRG")

    # ------------------------------------------------------------------
    # Measurement
    # ------------------------------------------------------------------

    def read_voltage(self):
        """Measure input voltage [V]."""
        return _tofloat(self._query(f"MEAS{self._CH}:VOLTAGE?"))

    def read_current(self):
        """Measure input current [A]."""
        return _tofloat(self._query(f"MEAS{self._CH}:CURRENT?"))

    def read_power(self):
        """Measure input power [W]."""
        return _tofloat(self._query(f"MEAS{self._CH}:POWER?"))

    def read_resistance(self):
        """Measure input resistance [Ω]."""
        return _tofloat(self._query(f"MEAS{self._CH}:RESISTANCE?"))

    def read_all(self):
        """Measure all channels: returns (voltage_V, current_A, power_W, resistance_Ω)."""
        vals = _tofloats(self._query(f"MEAS{self._CH}:ALL?"))
        # Device transmits fields in order: current, voltage, power, resistance
        current_a, voltage_v, power_w, resistance_ohm = vals
        return (voltage_v, current_a, power_w, resistance_ohm)
