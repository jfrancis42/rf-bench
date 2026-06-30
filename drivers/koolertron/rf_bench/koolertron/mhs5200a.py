"""
mhs5200a.py — Koolertron / MHinstek MHS-5200A series dual-channel DDS signal
generator with built-in frequency counter and sweep generator.

200 MSa/s, 12-bit, dual-channel DDS arbitrary waveform generator. Sold under
many brand names — Koolertron, MHinstek, KKmoon, and various AliExpress / eBay
listings labelled "200MSa/s 12Bit DDS". The hardware and protocol are common
to every variant; only the upper sine-wave frequency limit changes per model
suffix (5206A=6 MHz, 5212A=12 MHz, 5220A=20 MHz, 5225A=25 MHz).

USB interface uses a CH340 (1a86:7523) on older firmware-4.22 units, or a
PL2303 (067b:2303) on newer units; both present a virtual COM port at
57600 baud, 8N1, no flow control. CR LF line terminators on writes; the
device terminates each response line with CR LF.

This driver was written from scratch against the public reverse-engineering
documentation cited under "Protocol reference and credits" in the README.
No source code from any other implementation is reproduced or modified here.

Verified hardware:
    Model code:      "5225A5040000"  (returned by :r0c)
    Friendly model:  MHS-5225A (25 MHz upper limit)
    Hardware/FW tag: 5040000
    USB chip:        QinHeng CH340 (1a86:7523)
    Confirmed:       2026-06-08 against unit at /dev/ttyUSB0

Usage::

    from rf_bench.koolertron import MHS5200A, Waveform, CounterMode, Gate

    with MHS5200A() as gen:                        # auto-detect CH340 / PL2303
        print(gen.identify())                      # 'MHS-5225A (5040000)'

        # Function generator
        gen.set_frequency(1, 1_000_000)
        gen.set_amplitude(1, 1.0)
        gen.set_waveform(1, Waveform.SINE)
        gen.set_frequency(2, 100_000)
        gen.output_on()

        # Arbitrary waveforms (16 slots: ARB0..ARB15)
        import math
        sine = [math.sin(2*math.pi*i/1024) for i in range(1024)]
        gen.upload_arb_normalized(0, sine)
        gen.set_waveform(1, Waveform.ARB0)

        # Frequency counter (EXT IN connector on rear)
        gen.counter_setup(mode=CounterMode.FREQ, gate=Gate.S1, source_ttl=False)
        gen.counter_start()
        time.sleep(2)
        hz = gen.read_counter()
        gen.counter_stop()

        # Sweep
        gen.sweep_setup(start_hz=1e3, stop_hz=1e6, time_s=10, log=True)
        gen.sweep_start()
        ...
        gen.sweep_stop()
"""

import json
import math
import os
import time
from enum import IntEnum
from typing import Optional, Union

import serial
import serial.tools.list_ports


# ---------------------------------------------------------------------------
# Calibration file: schema + helpers
# ---------------------------------------------------------------------------

# Default cal file path. The driver looks here automatically if the user does
# not pass calibration= explicitly. Absence of the file is not an error — the
# driver simply uses the unit's built-in (factory) calibration.
DEFAULT_CAL_FILE = os.path.expanduser("~/.koolertron_mhs5200_cal.json")


class CalibrationError(Exception):
    """Raised on malformed calibration files (not on a missing file)."""


def _load_calibration(source: Union[None, str, dict]) -> Optional[dict]:
    """Resolve a calibration source to a dict, or None if unavailable.

    `source` may be:
        - None       — try DEFAULT_CAL_FILE; return None if not present
        - str path   — load that JSON file; raise CalibrationError if not present
        - dict       — return as-is
    """
    if isinstance(source, dict):
        return source
    if source is None:
        path = DEFAULT_CAL_FILE
        if not os.path.exists(path):
            return None
    else:
        path = str(source)
        if not os.path.exists(path):
            raise CalibrationError(f"calibration file not found: {path}")
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        raise CalibrationError(f"could not load calibration {path!r}: {e}") from e


def _interp_amplitude_correction_db(
    cal: dict, channel: int, freq_hz: float, commanded_v: float
) -> float:
    """Interpolate the amplitude correction (dB) for the given channel/freq/level.

    The amplitude block of the calibration is::

        cal["amplitude"][str(channel)] = [
            {"freq_hz": f, "commanded_v": v, "correction_db": dB},
            ...
        ]

    For simplicity we do a 1D interpolation along frequency at the nearest
    commanded_v level. If multiple levels are present, the level closest to
    `commanded_v` in log-V space is selected and its frequency curve is used.
    Outside the calibrated frequency range the endpoint value is held.
    Returns 0.0 if no calibration is available for the channel.
    """
    block = (cal.get("amplitude") or {}).get(str(channel))
    if not block:
        return 0.0

    # Group by commanded_v
    by_level: dict = {}
    for row in block:
        v = float(row["commanded_v"])
        by_level.setdefault(v, []).append((float(row["freq_hz"]),
                                           float(row["correction_db"])))
    if not by_level:
        return 0.0

    # Pick the cal level closest in log-space to the commanded value
    cv = max(float(commanded_v), 1e-6)
    levels = sorted(by_level)
    chosen = min(levels, key=lambda lv: abs(math.log10(max(lv, 1e-6)) - math.log10(cv)))
    curve = sorted(by_level[chosen])

    # Clamp / linear interpolate in log-frequency
    f = max(float(freq_hz), 1e-6)
    if f <= curve[0][0]:
        return curve[0][1]
    if f >= curve[-1][0]:
        return curve[-1][1]
    lf = math.log10(f)
    for (f_lo, c_lo), (f_hi, c_hi) in zip(curve[:-1], curve[1:]):
        if f_lo <= f <= f_hi:
            t = (lf - math.log10(f_lo)) / (math.log10(f_hi) - math.log10(f_lo))
            return c_lo + t * (c_hi - c_lo)
    return 0.0


def _dbm_to_vpp_50(dbm: float) -> float:
    """Convert dBm into 50 Ω to peak-to-peak volts.

    P = V_rms^2 / R; V_rms = V_pp / (2*sqrt(2)); => V_pp = sqrt(P*8*R).
    """
    p_w = 10.0 ** (dbm / 10.0) * 1e-3
    return math.sqrt(p_w * 8.0 * 50.0)


def _vpp_to_dbm_50(vpp: float) -> float:
    """Convert peak-to-peak volts (across 50 Ω) to dBm."""
    if vpp <= 0:
        return float("-inf")
    p_w = (vpp ** 2) / (8.0 * 50.0)
    return 10.0 * math.log10(p_w * 1000.0)


# ---------------------------------------------------------------------------
# Constants from the protocol
# ---------------------------------------------------------------------------

DEFAULT_BAUD          = 57600
DEFAULT_TIMEOUT       = 0.6   # seconds — per-line read timeout
COMMAND_DELAY         = 0.01  # tiny inter-command spacing
RESET_DELAY           = 0.2   # post-init settling time

# USB-serial chips known to be used on MHS-5200A units in the wild
_USB_IDS = ("1a86:7523", "067b:2303")  # CH340 (older fw); PL2303 (newer)


class Waveform(IntEnum):
    """Built-in waveform codes for set_waveform().

    The MHS-5200A also supports 16 user-defined arbitrary waveforms (ARB0..ARB15)
    uploaded via :meth:`MHS5200A.upload_arb`. Wave codes 100-115 select them.
    """
    SINE       = 0
    SQUARE     = 1
    TRIANGLE   = 2
    UP_SAW     = 3   # rising sawtooth
    DOWN_SAW   = 4   # falling sawtooth
    TTL        = 5   # TTL digital output mode (maximized slew rate)
    ARB0       = 100
    ARB1       = 101
    ARB2       = 102
    ARB3       = 103
    ARB4       = 104
    ARB5       = 105
    ARB6       = 106
    ARB7       = 107
    ARB8       = 108
    ARB9       = 109
    ARB10      = 110
    ARB11      = 111
    ARB12      = 112
    ARB13      = 113
    ARB14      = 114
    ARB15      = 115


class CounterMode(IntEnum):
    """Frequency-counter measurement mode for the EXT IN connector."""
    FREQ        = 0   # measure frequency in Hz (per gate window)
    COUNT       = 1   # total event count (incrementing)
    PULSE_HIGH  = 2   # positive pulse width
    PULSE_LOW   = 3   # negative pulse width
    PERIOD      = 4   # period in nanoseconds
    DUTY        = 5   # duty cycle


class Gate(IntEnum):
    """Counter gate (integration) time."""
    S1   = 0   # 1 s
    S10  = 1   # 10 s
    S0_01 = 2  # 0.01 s
    S0_1  = 3  # 0.1 s


class SweepShape(IntEnum):
    """Sweep frequency progression (linear vs logarithmic)."""
    LOG = 0
    LIN = 1


class Atten(IntEnum):
    """Per-channel output attenuator state."""
    MINUS_20DB = 0   # -20 dB attenuator engaged
    ZERO_DB    = 1   # full output (default)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class MHS5200AError(Exception):
    pass


class MHS5200A:
    """Koolertron / MHinstek MHS-5200A series DDS signal generator + counter.

    Wire protocol summary (see "Protocol reference and credits" in the README
    for the source document):

        Baud:        57600 8N1, no flow control
        Framing:     every command starts with ':' and ends with CR LF
        Set form:    :s<channel><param><value>\\r\\n   -> 'ok\\r\\n'
        Read form:   :r<channel><param>\\r\\n          -> ':r<ch><param><value>\\r\\n'
        Channel arg: 1, 2 = the two output channels
                     0    = device-level (model query, counter readout, ...)
                     3    = sweep start frequency register
                     4    = sweep end frequency / ext-in source select
                     5    = sweep time / counter reset
                     6    = counter start/stop
                     7    = sweep lin/log shape
                     8    = sweep run/stop
                     9    = power amp on/off (if equipped)

    The numeric units (centi-hertz for frequency, hundredths of a volt for
    amplitude, signed offset 0=120 etc.) are documented per-method below.
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = DEFAULT_BAUD,
        timeout: float = DEFAULT_TIMEOUT,
        calibration: Union[None, str, dict, bool] = None,
    ):
        """Open a connection to an MHS-5200A.

        Args:
            port:        Serial device path (e.g. '/dev/ttyUSB0'). If None,
                         auto-detects the first CH340 or PL2303 USB-serial
                         adapter on the system.
            baudrate:    Almost always 57600 — the MHS-5200A protocol does not
                         support other rates.
            timeout:     Per-line read timeout in seconds.
            calibration: Optional calibration source.

                         - ``None`` (default): if the file
                           ``~/.koolertron_mhs5200_cal.json`` exists, load it;
                           otherwise use the unit's built-in (factory)
                           calibration. Either way the driver works.
                         - ``False``: disable calibration even if the default
                           file exists. Useful for explicitly bypassing a stale
                           cal file or for cal-run scripts that need raw set/
                           get behavior to characterize the bare instrument.
                         - ``str`` path: load that JSON file (raises
                           :class:`CalibrationError` if the path doesn't exist).
                         - ``dict``: use the given calibration dict directly.

                         A loaded calibration enables transparent corrections in
                         :meth:`set_frequency` (ppm offset) and provides
                         :meth:`set_amplitude_dbm` (frequency- and channel-
                         aware amplitude correction). Without calibration these
                         methods fall back to the device's nominal behavior.
        """
        if port is None:
            port = self._find_port()
        self.port: str = port

        # Resolve calibration source. False means "explicitly disabled".
        if calibration is False:
            self.calibration: Optional[dict] = None
        else:
            self.calibration = _load_calibration(calibration)

        try:
            self._ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
                timeout=timeout,
                write_timeout=timeout,
            )
        except (OSError, serial.SerialException) as e:
            raise MHS5200AError(
                f"Failed to open MHS-5200A on {port}: {e}"
            ) from e

        time.sleep(RESET_DELAY)
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()

        # Identify (also acts as a connectivity check)
        raw = self._read_raw("r0c")
        if not raw:
            raise MHS5200AError(
                f"Connected to {port} but the unit did not respond to the "
                f":r0c model query. Wrong baud rate? Wrong device on this port?"
            )
        self.raw_model: str = raw
        self.model: str = self._friendly_model(raw)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self) -> "MHS5200A":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        """Close the serial port. The device output state is unchanged."""
        try:
            if self._ser is not None and self._ser.isOpen():
                self._ser.close()
        except (OSError, serial.SerialException):
            pass

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    def _send(self, body: str, expect_ok: bool = True) -> str:
        """Send `:body\\r\\n` and return the device's reply line (sans CR LF).

        If `expect_ok` is True, raise unless the reply is exactly 'ok'.

        The device terminates each reply line with CR LF. For `:s...` set
        commands the reply is `ok\\r\\n`; for `:r...` read commands the reply
        is `:r<ch><param><value>\\r\\n`. We use readline() and strip.
        """
        self._ser.reset_input_buffer()
        wire = f":{body}\r\n".encode("ascii")
        try:
            self._ser.write(wire)
        except serial.SerialException as e:
            raise MHS5200AError(f"serial write failed: {e}") from e

        # Wait briefly for the device to start responding, then read one line.
        time.sleep(COMMAND_DELAY)
        line = self._ser.readline()
        text = line.decode("ascii", errors="replace").strip()

        if expect_ok and text != "ok":
            raise MHS5200AError(
                f"unexpected reply to {body!r}: {text!r} (expected 'ok')"
            )
        return text

    def _read_raw(self, body: str) -> str:
        """Issue a `:rXY\\r\\n` style read and return only the value portion.

        For a query `:rXY` the reply is `:rXYvalue` (with optional CRLF mid-
        line on some firmware revisions where the device echoes on one line
        and emits the value on a second). This method strips the protocol
        framing and returns just the value string.
        """
        reply = self._send(body, expect_ok=False)
        # reply may be ':rXY<value>' or ':rXY\r\n<value>' (already stripped)
        # In either case the leading ':rXY' has the same length as ':' + body.
        prefix = f":{body}"
        if reply.startswith(prefix):
            value = reply[len(prefix):]
            # Some firmware emits the prefix on its own line followed by the
            # value; the strip() in _send collapses CR/LF to nothing in that
            # case, so the value is glued onto the prefix already.
            return value.strip()
        return reply

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def identify(self) -> str:
        """Return e.g. ``'MHS-5225A (5040000)'``."""
        if len(self.raw_model) >= 5 and self.raw_model[4] == "A":
            return f"{self.model} ({self.raw_model[5:]})"
        return self.model or self.raw_model

    def calibration_info(self) -> dict:
        """Return a small summary describing the active calibration (or its absence).

        Useful for logging at startup to make it obvious whether a script is
        running corrected or uncorrected:

            >>> gen.calibration_info()
            {'loaded': True, 'frequency_ppm_offset': 7.4,
             'amplitude_channels': [1, 2], 'calibrated_at': '2026-06-08T...'}
            >>> # or, with no cal:
            {'loaded': False}
        """
        if self.calibration is None:
            return {"loaded": False}
        amp = self.calibration.get("amplitude") or {}
        return {
            "loaded": True,
            "frequency_ppm_offset": float(self.calibration.get("frequency_ppm_offset", 0.0)),
            "amplitude_channels": sorted(int(k) for k in amp.keys()),
            "calibrated_at": self.calibration.get("calibrated_at", "unknown"),
        }

    @staticmethod
    def _friendly_model(raw: str) -> str:
        """Convert ``"5225A5040000"`` to ``"MHS-5225A"``; passthrough on unknown form."""
        if len(raw) >= 5 and raw[:4].isdigit() and raw[4] == "A":
            return f"MHS-{raw[:5]}"
        return raw

    @classmethod
    def find_port(cls) -> Optional[str]:
        """Return the first CH340 / PL2303 USB-serial port found, or None."""
        for p in serial.tools.list_ports.comports():
            hwid = (p.hwid or "").lower()
            if any(vid_pid in hwid for vid_pid in _USB_IDS):
                return p.device
            desc = (p.description or "").lower()
            if "ch340" in desc or "ch341" in desc or "pl2303" in desc:
                return p.device
        return None

    @classmethod
    def _find_port(cls) -> str:
        port = cls.find_port()
        if port is None:
            raise MHS5200AError(
                "No CH340 or PL2303 USB-serial adapter detected. "
                "Pass port= explicitly, e.g. MHS5200A('/dev/ttyUSB0')."
            )
        return port

    # ------------------------------------------------------------------
    # Per-channel waveform parameters
    # ------------------------------------------------------------------

    def _check_channel(self, channel: int) -> int:
        if channel not in (1, 2):
            raise ValueError(f"channel must be 1 or 2, got {channel!r}")
        return channel

    def set_frequency(self, channel: int, freq_hz: float) -> None:
        """Set channel frequency in Hz (wire register is 0.01 Hz units).

        If a calibration file is loaded with a ``frequency_ppm_offset`` field,
        the requested frequency is pre-corrected so that the *actual* output
        matches the requested value. The correction is the inverse of the
        observed device error: e.g. if the unit's TCXO measured +7.4 ppm fast
        (cal value), commanding 1.000 000 MHz writes 999 992.6 Hz and the
        device produces 1.000 000 MHz.

        Without a cal file, no correction is applied and the wire-level
        frequency register is set to the requested value verbatim.
        """
        ch = self._check_channel(channel)
        f = float(freq_hz)
        if self.calibration is not None:
            ppm = float(self.calibration.get("frequency_ppm_offset", 0.0))
            f = f / (1.0 + ppm * 1e-6)
        raw = int(round(f * 100))
        if raw < 0:
            raise ValueError(f"freq_hz must be >= 0, got {freq_hz!r}")
        self._send(f"s{ch}f{raw}")

    def get_frequency(self, channel: int) -> float:
        """Return channel frequency in Hz."""
        ch = self._check_channel(channel)
        v = self._read_raw(f"r{ch}f")
        return int(v) / 100.0

    # Amplitude register scaling, characterised against an MHS-5225A on
    # 2026-06-08 by sweeping the register through known values and reading
    # the actual amplitude on a calibrated SDS2504X oscilloscope at 50 Ω
    # input impedance. Linear up to register ≈ 500 (= 2.5 Vpp into 50 Ω);
    # above that the unit clips at roughly 4.25 Vpp_50Ω.
    #
    #   register     Vpp into 50 Ω    register × 5 mV
    #   -----------------------------------------------
    #     50          0.267 V          0.250 V (close)
    #    100          0.500 V          0.500 V (exact)
    #    200          0.983 V          1.000 V (close)
    #    500          2.520 V          2.500 V (close)
    #
    # So: register = Vpp_50Ω × 200, equivalently 5 mV per LSB into 50 Ω.
    # This driver therefore takes Vpp into 50 Ω (the conventional function-
    # generator convention and what most users want to measure with a scope).
    _AMP_UNITS_PER_VOLT_50 = 200

    # Practical maximum (the scope shows clipping at ~4.25 Vpp_50Ω regardless
    # of register value above ~850). Writing a register above this is allowed
    # but the device clips.
    _AMP_MAX_REGISTER = 850

    def set_amplitude(self, channel: int, volts_pp: float) -> None:
        """Set channel amplitude in Vpp into a 50 Ω load.

        The wire register's LSB is 5 mV into 50 Ω. Values are quantised on
        write. The unit clips at about 4.25 Vpp into 50 Ω regardless of
        commanded value above that (register ≈ 850).

        Args:
            volts_pp: Target peak-to-peak amplitude into 50 Ω, in volts.
                      Maximum useful value is roughly 4.25 V; above that
                      the output clips.
        """
        ch = self._check_channel(channel)
        raw = int(round(float(volts_pp) * self._AMP_UNITS_PER_VOLT_50))
        if raw < 0:
            raise ValueError(f"amplitude must be >= 0, got {volts_pp!r}")
        self._send(f"s{ch}a{raw}")

    def get_amplitude(self, channel: int) -> float:
        """Return channel amplitude setting in Vpp into 50 Ω.

        Note this is the wire register interpreted as Vpp_50Ω; if the actual
        output is in clipping (register above ~850) the wire value will exceed
        what is physically delivered.
        """
        ch = self._check_channel(channel)
        v = self._read_raw(f"r{ch}a")
        return int(v) / float(self._AMP_UNITS_PER_VOLT_50)

    def set_amplitude_dbm(self, channel: int, freq_hz: float, dbm: float) -> None:
        """Set channel amplitude calibrated to a target dBm into a 50 Ω load.

        With a calibration loaded, this looks up the per-channel correction at
        the (freq, level) pair and writes a wire-level amplitude that produces
        the requested delivered power into a 50 Ω termination.

        Without a calibration loaded, this falls back to the analytic
        Vpp ↔ dBm conversion (which assumes the unit is perfectly flat —
        which it is not above ~10 MHz). In that case the delivered power may
        differ from the request by 1-2 dB or more at high frequencies, but
        the call still succeeds and produces a sensible result.

        Args:
            channel:  1 or 2.
            freq_hz:  The output frequency at which the amplitude is being set
                      (used to look up the correction). It is NOT enough to
                      pass the freq once at startup — the correction varies
                      strongly with frequency above 10 MHz, so call this each
                      time the frequency changes.
            dbm:      Target output level in dBm into a 50 Ω load.
        """
        ch = self._check_channel(channel)
        # Nominal Vpp into 50 Ω for the requested dBm
        nominal_vpp_50 = _dbm_to_vpp_50(float(dbm))

        if self.calibration is not None:
            corr_db = _interp_amplitude_correction_db(
                self.calibration, ch, float(freq_hz), nominal_vpp_50
            )
            target_vpp_50 = _dbm_to_vpp_50(float(dbm) + corr_db)
        else:
            target_vpp_50 = nominal_vpp_50

        # set_amplitude takes Vpp into 50 Ω directly.
        self.set_amplitude(ch, target_vpp_50)

    def set_waveform(self, channel: int, wave) -> None:
        """Set channel waveform (Waveform enum or raw integer code)."""
        ch = self._check_channel(channel)
        self._send(f"s{ch}w{int(wave)}")

    def get_waveform(self, channel: int) -> int:
        """Return channel waveform code (use the :class:`Waveform` enum to interpret)."""
        ch = self._check_channel(channel)
        v = self._read_raw(f"r{ch}w")
        # Manual notes the readback may use codes 32-47 for ARB0..ARB15;
        # normalize to the documented 100-115 range.
        n = int(v)
        if 32 <= n <= 47:
            return 100 + (n - 32)
        return n

    def set_duty_cycle(self, channel: int, percent: float) -> None:
        """Set duty cycle in percent (wire register is 0.1% units)."""
        ch = self._check_channel(channel)
        raw = int(round(float(percent) * 10))
        if not 0 <= raw <= 999:
            raise ValueError(f"duty cycle must be 0..99.9 %, got {percent!r}")
        self._send(f"s{ch}d{raw}")

    def get_duty_cycle(self, channel: int) -> float:
        """Return duty cycle in percent."""
        ch = self._check_channel(channel)
        v = self._read_raw(f"r{ch}d")
        return int(v) / 10.0

    def set_offset(self, channel: int, signed: int) -> None:
        """Set DC offset.

        The wire register is 0..240 with 120 = no offset; this method takes a
        signed integer in the range -120..+120 and converts. The unit is the
        device's internal step; verify the actual voltage on a scope before
        trusting calibration. Per the protocol document: "0% = 120".
        """
        ch = self._check_channel(channel)
        raw = int(signed) + 120
        if not 0 <= raw <= 240:
            raise ValueError(f"offset must be -120..+120, got {signed!r}")
        self._send(f"s{ch}o{raw}")

    def get_offset(self, channel: int) -> int:
        """Return signed offset in -120..+120 device units (0 = no offset)."""
        ch = self._check_channel(channel)
        v = self._read_raw(f"r{ch}o")
        return int(v) - 120

    def set_phase(self, channel: int, degrees: int) -> None:
        """Set phase offset in degrees (0..359, integer)."""
        ch = self._check_channel(channel)
        if not 0 <= int(degrees) <= 359:
            raise ValueError(f"phase must be 0..359 deg, got {degrees!r}")
        self._send(f"s{ch}p{int(degrees)}")

    def get_phase(self, channel: int) -> int:
        """Return phase offset in degrees."""
        ch = self._check_channel(channel)
        v = self._read_raw(f"r{ch}p")
        return int(v)

    def set_attenuator(self, channel: int, atten: Atten) -> None:
        """Set per-channel output attenuator (Atten.ZERO_DB or Atten.MINUS_20DB)."""
        ch = self._check_channel(channel)
        self._send(f"s{ch}y{int(atten)}")

    def get_attenuator(self, channel: int) -> int:
        """Return per-channel output attenuator state (0=-20dB, 1=0dB)."""
        ch = self._check_channel(channel)
        v = self._read_raw(f"r{ch}y")
        return int(v)

    def set_channel_enable(self, channel: int, on: bool) -> None:
        """Set per-channel output enable. NOTE: the master :meth:`output_on` /
        :meth:`output_off` is global to both channels and is what most users
        actually want; this per-channel command may be a no-op on some
        firmware revisions."""
        ch = self._check_channel(channel)
        self._send(f"s{ch}b{1 if on else 0}")

    def get_channel_enable(self, channel: int) -> bool:
        ch = self._check_channel(channel)
        v = self._read_raw(f"r{ch}b")
        return int(v) != 0

    # ------------------------------------------------------------------
    # Master output enable (global to both channels — hardware behaviour)
    # ------------------------------------------------------------------

    def output_on(self) -> None:
        """Enable the output stage (BOTH channels — master enable is global)."""
        self._send("s1b1")

    def output_off(self) -> None:
        """Disable the output stage (BOTH channels)."""
        self._send("s1b0")

    # ------------------------------------------------------------------
    # Memory slots (0 = power-on default)
    # ------------------------------------------------------------------

    def save_slot(self, slot: int = 0) -> None:
        """Save the current full setup to memory slot `slot` (0..9)."""
        if not 0 <= int(slot) <= 9:
            raise ValueError(f"slot must be 0..9, got {slot!r}")
        self._send(f"s{int(slot)}u")

    def load_slot(self, slot: int = 0) -> None:
        """Load setup from memory slot `slot` (0..9). Slot 0 is the power-on default."""
        if not 0 <= int(slot) <= 9:
            raise ValueError(f"slot must be 0..9, got {slot!r}")
        self._send(f"s{int(slot)}v")

    # ------------------------------------------------------------------
    # Frequency counter (EXT IN connector)
    # ------------------------------------------------------------------

    def counter_setup(
        self,
        mode: CounterMode = CounterMode.FREQ,
        gate: Gate = Gate.S1,
        source_ttl: bool = False,
    ) -> None:
        """Configure the frequency counter.

        Args:
            mode:        FREQ / COUNT / PULSE_HIGH / PULSE_LOW / PERIOD / DUTY
            gate:        Counter gate (integration) time
            source_ttl:  True selects the TTL-level input; False selects the
                         analogue EXT IN connector (the front-panel "EXT IN").

        After calling this, use :meth:`counter_start`, then :meth:`read_counter`
        after waiting at least 3 × ``gate`` seconds for a stable reading.
        For one-shot measurements the :meth:`measure_frequency_hz` helper
        handles the timing for you.
        """
        # First make sure the counter is stopped, so reset semantics are clean
        self._send("s6b0")
        time.sleep(0.05)
        # Set ext-in source (:s4b0=ext, :s4b1=ttl)
        self._send(f"s4b{1 if source_ttl else 0}")
        # Set gate window (:sNg uses N to encode the four gate values 0..3
        # — wd5gnr's PDF lists this as ":sNg" but the exact channel-letter
        # encoding ":s1g0" works in firmware 5040000 and is what we use.)
        self._send(f"s1g{int(gate)}")
        # Set measurement mode (:s0m, :s1m, ...)
        self._send(f"s{int(mode)}m")

    def counter_start(self) -> None:
        """Start (or resume) the frequency counter.

        Sends a reset pulse, waits 0.5 s for the firmware to clear the count
        register, then enables run mode. Without that gap the run command
        can race against the reset and the first gate window is lost.
        """
        self._send("s5b1")   # reset counter
        time.sleep(0.5)
        self._send("s6b1")   # start

    def counter_stop(self) -> None:
        """Stop the frequency counter."""
        self._send("s6b0")

    def counter_reset(self) -> None:
        """Zero the counter without changing run state."""
        self._send("s5b1")

    def read_counter(self) -> float:
        """Read the current counter value.

        Interpretation depends on the active mode:

            - FREQ        → frequency in Hz (10-digit integer; e.g.
                             "0012340092" means 1,234,009.2 Hz on this firmware)
            - COUNT       → integer pulse count
            - PERIOD      → period in nanoseconds (raw integer ns)
            - PULSE_HIGH/
              PULSE_LOW   → pulse width in nanoseconds
            - DUTY        → duty cycle in tenths of a percent

        Returns the numeric value as a float; for FREQ mode, the "tenth-of-Hz"
        scaling observed on firmware 5040000 (raw value / 10) is applied.
        """
        v = self._read_raw("r0e")
        if not v:
            return 0.0
        n = int(v)
        # On firmware 5040000 the FREQ readout is in tenths of Hz (a 1.234 MHz
        # signal returns 12_340_092 → 1_234_009.2 Hz). Other modes are direct.
        # We don't know the active mode here without round-tripping :rNm, so
        # we just return the raw integer; callers in FREQ mode should divide
        # by 10. This is a deliberate API choice: better to return the wire
        # value verbatim than to silently mis-scale other modes.
        return float(n)

    def read_counter_hz(self) -> float:
        """Convenience: return the FREQ-mode counter reading in Hz.

        Applies the /10 scaling observed on firmware 5040000. Only call this
        when the counter has been put into :data:`CounterMode.FREQ`.

        Note: after :meth:`counter_start`, allow at least 2 × the gate time
        before reading to be sure the counter has completed a full gate cycle
        and updated the result register. Reading sooner returns a stale or
        partial-gate value.
        """
        return self.read_counter() / 10.0

    # Empirically determined on firmware 5040000: at the 1 s gate, the
    # counter only locks reliably for input signals at ≥ ~10 MHz. Below
    # that, the counter holds partial-gate intermediate values for many
    # gate windows. With the 10 s gate, it locks reliably from ≥ ~10 kHz
    # upward. Gates shorter than 1 s have not been characterised.
    _COUNTER_MIN_HZ_AT_GATE = {
        Gate.S10:   10_000.0,    # 10 kHz min input freq with 10 s gate
        Gate.S1:    10_000_000.0,  # 10 MHz min input freq with 1 s gate
        Gate.S0_1:  100_000_000.0,
        Gate.S0_01: 1_000_000_000.0,
    }

    def measure_frequency_hz(
        self,
        gate: Gate = Gate.S10,
        source_ttl: bool = False,
        settle_gates: int = 2,
        stability_window: int = 2,
        stability_tol_hz: float = 0.5,
        timeout_s: float = 60.0,
    ) -> float:
        """Measure the frequency at the EXT IN connector and return it in Hz.

        The MHS-5200A counter result register updates once per gate window
        (``gate`` seconds) but takes 2+ gate cycles to flush partial values
        after the input signal changes. This method polls the result every
        gate period and returns the first reading that agrees with the
        previous reading within ``stability_tol_hz``.

        Args:
            gate:                Gate (integration) time. Default Gate.S10
                                 (10 second gate) — empirically the most
                                 reliable choice on firmware 5040000.
                                 Use Gate.S1 only for input frequencies
                                 ≥ 10 MHz; the 1 s gate is unreliable below
                                 that on this firmware.
            source_ttl:          True for TTL input, False for analogue EXT IN.
            settle_gates:        Minimum gate periods to wait before the
                                 first read (default 2 = 20 s with 10 s gate).
            stability_window:    How many consecutive readings must agree.
            stability_tol_hz:    Maximum spread between agreeing readings.
                                 0.5 Hz is below the counter's 1 Hz LSB
                                 quantisation, so this effectively means
                                 "exact-match consecutive readings".
            timeout_s:           Give up if the counter never stabilises.

        Returns:
            Frequency in Hz. Returns the last-read value if the counter
            never stabilises within timeout_s — the caller should sanity-
            check the returned value against the expected input frequency.

        Empirical reliability (firmware 5040000):
            * Gate.S10 + ≥ 10 kHz input  → ±1 ppm reproducibility
            * Gate.S10 + < 10 kHz input  → may not lock; result unreliable
            * Gate.S1  + ≥ 10 MHz input  → ±0.1 ppm reproducibility
            * Gate.S1  + < 10 MHz input  → frequently does not lock

        For input frequencies below the gate's minimum, this method does
        not raise — it returns whatever the counter eventually reports.
        Check the returned value before trusting it.
        """
        gate_seconds = {Gate.S1: 1.0, Gate.S10: 10.0,
                        Gate.S0_01: 0.01, Gate.S0_1: 0.1}[gate]
        self.counter_setup(mode=CounterMode.FREQ, gate=gate, source_ttl=source_ttl)
        self.counter_start()
        try:
            # Initial wait: the source usually needs ≥ 1 s to settle on a
            # new frequency, then at least settle_gates windows must elapse
            # for the result register to acquire a non-stale value.
            time.sleep(max(gate_seconds * settle_gates, 1.0))

            history = []
            t_end = time.monotonic() + timeout_s
            last = 0.0
            while time.monotonic() < t_end:
                cur = self.read_counter_hz()
                last = cur
                history.append(cur)
                if len(history) >= stability_window:
                    window = history[-stability_window:]
                    if max(window) - min(window) <= stability_tol_hz:
                        return cur
                time.sleep(gate_seconds * 1.05)
            return last
        finally:
            self.counter_stop()

    # ------------------------------------------------------------------
    # Sweep generator
    # ------------------------------------------------------------------

    def sweep_setup(
        self,
        start_hz: float,
        stop_hz: float,
        time_s: int,
        log: bool = False,
    ) -> None:
        """Configure a frequency sweep on CH1.

        Args:
            start_hz:  Sweep start frequency in Hz (wire register is 0.01 Hz units)
            stop_hz:   Sweep stop frequency in Hz
            time_s:    Total sweep time, in seconds (integer)
            log:       True for logarithmic progression, False for linear
        """
        s_raw = int(round(float(start_hz) * 100))
        e_raw = int(round(float(stop_hz) * 100))
        if s_raw < 0 or e_raw < 0:
            raise ValueError("sweep frequencies must be >= 0")
        self._send(f"s3f{s_raw}")             # start freq
        self._send(f"s4f{e_raw}")             # stop freq
        self._send(f"s5t{int(time_s)}")       # sweep time (seconds)
        self._send(f"s7b{0 if log else 1}")   # 1=lin, 0=log

    def sweep_start(self) -> None:
        """Start the configured sweep."""
        self._send("s8b1")

    def sweep_stop(self) -> None:
        """Stop the sweep."""
        self._send("s8b0")

    def get_sweep_state(self) -> bool:
        """Return True if the sweep is running."""
        v = self._read_raw("r8b")
        return int(v) != 0

    # ------------------------------------------------------------------
    # Arbitrary waveform upload (ARB0..ARB15)
    # ------------------------------------------------------------------

    def upload_arb(self, slot: int, samples: list) -> None:
        """Upload an arbitrary waveform to one of the 16 user-defined slots.

        The MHS-5200A supports 16 arbitrary waveform memories (slots 0-15),
        each storing 1024 samples. After upload, select the waveform with
        ``set_waveform(channel, Waveform.ARB0 + slot)``.

        Args:
            slot:    Memory slot 0-15. Slot N corresponds to Waveform.ARBN
                     (e.g. slot 0 → Waveform.ARB0 = waveform code 100).
            samples: Exactly 1024 integers in the range 0-255.
                     0 = minimum voltage, 255 = maximum voltage.
                     The device interpolates between samples at its 200 MSa/s
                     DAC rate when playing back the waveform.

        Example — upload a simple ramp::

            ramp = [int(i * 255 / 1023) for i in range(1024)]
            gen.upload_arb(0, ramp)
            gen.set_waveform(1, Waveform.ARB0)
            gen.output_on()

        Example — upload a sine wave::

            import math
            sine = [int((math.sin(2*math.pi*i/1024) + 1) * 127.5)
                    for i in range(1024)]
            gen.upload_arb(1, sine)
            gen.set_waveform(1, Waveform.ARB1)

        Protocol reference:
            Arbitrary waveform upload protocol reverse-engineered by Al Williams
            (wd5gnr) and documented in https://github.com/wd5gnr/mhs5200a (public
            domain). This implementation is independent.

            Wire format: The 1024-sample waveform is uploaded as 16 chunks of 64
            samples each. Each chunk is sent as:
                :a<slot><chunk>\\r\\n
                v0,v1,v2,...,v63\\r\\n
            where <slot> and <chunk> are single hex digits (0-F). The device
            replies 'ok\\r\\n' after each chunk. A 10 ms inter-chunk delay is
            required for reliable uploads on firmware 5040000.

        Raises:
            ValueError: if slot is not 0-15, if samples is not exactly 1024
                        elements, or if any sample is outside 0-255.
            MHS5200AError: if the device fails to acknowledge a chunk upload.
        """
        # Validation
        if not isinstance(slot, int) or not 0 <= slot <= 15:
            raise ValueError(f"slot must be 0-15, got {slot!r}")
        if len(samples) != 1024:
            raise ValueError(f"samples must be exactly 1024 elements, got {len(samples)}")

        # Convert to integers and validate range
        try:
            samples_int = [int(s) for s in samples]
        except (TypeError, ValueError) as e:
            raise ValueError(f"all samples must be convertible to int: {e}") from e

        for i, v in enumerate(samples_int):
            if not 0 <= v <= 255:
                raise ValueError(
                    f"sample[{i}] = {v} is out of range (must be 0-255)"
                )

        # Upload 16 chunks of 64 samples each
        for chunk_idx in range(16):
            # Extract this chunk's 64 samples
            chunk_start = chunk_idx * 64
            chunk_end = chunk_start + 64
            chunk_samples = samples_int[chunk_start:chunk_end]

            # Protocol quirk: send a blank ':' line before each chunk (from wd5gnr's
            # reference implementation). This appears to be required for reliable uploads.
            self._ser.reset_input_buffer()
            self._ser.write(b":\r\n")
            time.sleep(COMMAND_DELAY)
            self._ser.reset_input_buffer()

            # Format: :a<slot_hex><chunk_hex><comma-separated values>\r\n
            # Header and data must be on the SAME line (not two separate lines)
            data_str = ",".join(str(v) for v in chunk_samples)
            line = f":a{slot:x}{chunk_idx:x}{data_str}\r\n"
            try:
                self._ser.write(line.encode("ascii"))
            except serial.SerialException as e:
                raise MHS5200AError(
                    f"failed to send chunk {chunk_idx}: {e}"
                ) from e

            # Wait for 'ok' response
            time.sleep(COMMAND_DELAY)
            response_line = self._ser.readline()
            response = response_line.decode("ascii", errors="replace").strip()

            if response != "ok":
                raise MHS5200AError(
                    f"chunk {chunk_idx} upload failed: expected 'ok', got {response!r}"
                )

            # Inter-chunk delay — the device needs time to commit the chunk
            # to flash. 10 ms is the value used in wd5gnr's bash script and
            # is empirically reliable on firmware 5040000.
            time.sleep(0.010)

    def upload_arb_normalized(self, slot: int, samples: list) -> None:
        """Upload an arbitrary waveform from normalized -1.0 to +1.0 samples.

        Convenience wrapper around :meth:`upload_arb` that accepts floating-point
        samples in the range -1.0 to +1.0 and scales them to the device's 0-255
        integer range.

        Args:
            slot:    Memory slot 0-15.
            samples: Exactly 1024 floats in the range -1.0 to +1.0.
                     -1.0 maps to 0 (minimum voltage).
                      0.0 maps to 128 (center / no DC offset).
                     +1.0 maps to 255 (maximum voltage).

        Example — upload a normalized sine wave::

            import math
            sine_norm = [math.sin(2 * math.pi * i / 1024) for i in range(1024)]
            gen.upload_arb_normalized(2, sine_norm)
            gen.set_waveform(1, Waveform.ARB2)

        Raises:
            ValueError: if any sample is outside -1.0 to +1.0, or other
                        validation failures from :meth:`upload_arb`.
        """
        if len(samples) != 1024:
            raise ValueError(f"samples must be exactly 1024 elements, got {len(samples)}")

        # Validate range and scale
        scaled = []
        for i, s in enumerate(samples):
            try:
                f = float(s)
            except (TypeError, ValueError) as e:
                raise ValueError(f"sample[{i}] is not a valid float: {e}") from e

            if not -1.0 <= f <= 1.0:
                raise ValueError(
                    f"sample[{i}] = {f} is out of range (must be -1.0 to +1.0)"
                )

            # Scale: -1.0 → 0, 0.0 → 128, +1.0 → 255
            scaled_val = int(round((f + 1.0) * 127.5))
            # Clamp to 0-255 to handle any floating-point rounding edge cases
            scaled_val = max(0, min(255, scaled_val))
            scaled.append(scaled_val)

        self.upload_arb(slot, scaled)

    # ------------------------------------------------------------------
    # Power amplifier (if equipped — model dependent)
    # ------------------------------------------------------------------

    def power_amp(self, on: bool) -> None:
        """Enable/disable the optional power amplifier (no-op on units without one)."""
        self._send(f"s9b{1 if on else 0}")

    def get_power_amp(self) -> bool:
        v = self._read_raw("r9b")
        return int(v) != 0

    # ------------------------------------------------------------------
    # Convenience read-back of full state (handy for debug / panel apps)
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Return a dict of all the per-channel parameters for both channels."""
        out = {"model": self.model, "raw_model": self.raw_model, "port": self.port}
        for ch in (1, 2):
            out[f"ch{ch}"] = {
                "frequency_hz": self.get_frequency(ch),
                "amplitude_v":  self.get_amplitude(ch),
                "waveform":     self.get_waveform(ch),
                "duty_cycle":   self.get_duty_cycle(ch),
                "offset":       self.get_offset(ch),
                "phase_deg":    self.get_phase(ch),
                "attenuator":   self.get_attenuator(ch),
            }
        return out
