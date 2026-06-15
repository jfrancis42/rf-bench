"""
ft891.py — Yaesu FT-891 CAT control via Hamlib rigctld

Communicates with rigctld over a plain TCP socket on port 4532.
rigctld must be running before any test is started:

    rigctld -m 1036 -r /dev/ttyUSB0 -s 38400 &

Hamlib model: 1036 (confirmed stable, Hamlib 4.x).

Connection: the FT-891 front-panel USB-B port presents as a USB serial device
(/dev/ttyUSB0 or /dev/ttyUSB1) and handles both audio and CAT. CAT baud rate
is set in Menu 031 (CAT RATE); factory default is 38400. Set the menu and the
-s flag to match.

AGC note: the FT-891 does not have a dedicated hardware AGC-OFF button.
Hamlib's AGC=0 maps to the minimum AGC constant (slowest time constant), which
is not the same as a true gain-stabilized bypass. For applications that need
AGC genuinely disabled (e.g. absolute signal level measurement), use set_rf_gain()
to set a fixed gain and verify output-level linearity empirically.
"""

import math
import socket
import time


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 4532
CONNECT_TIMEOUT = 5    # seconds
RECV_TIMEOUT    = 3    # seconds
RECV_BUFSIZE    = 4096

# AGC constants as passed to rigctld set_level AGC
AGC_OFF   = 0   # Maps to slowest AGC on FT-891 — NOT a true bypass
AGC_FAST  = 1
AGC_MID   = 2
AGC_SLOW  = 3

# Preamp / IPO constants for set_preamp()
PREAMP_OFF  = 0   # IPO engaged — preamp bypassed (best for strong-signal tests)
PREAMP_AMP1 = 1   # AMP1 — first preamp stage (~10 dB gain)

# Mode strings understood by Hamlib
MODES = {"usb": "USB", "lsb": "LSB", "cw": "CW", "cwr": "CWR",
         "am": "AM", "fm": "FM", "rtty": "RTTY", "pkt-u": "PKTUSB",
         "pkt-l": "PKTLSB", "pkt-fm": "PKTFM"}

# Standard passband widths (Hz) by mode — used when passband_hz=0
DEFAULT_PASSBAND = {"USB": 2400, "LSB": 2400, "CW": 500, "CWR": 500,
                    "AM": 6000, "FM": 15000, "RTTY": 500,
                    "PKTUSB": 2400, "PKTLSB": 2400, "PKTFM": 15000}


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class FT891:
    """
    FT-891 CAT driver via Hamlib rigctld.

    API is intentionally identical to IC7300 for drop-in substitution.
    Additional methods: set_preamp(), get_preamp(), set_att().

    All frequency values are in Hz. get_strength() returns a Hamlib STRENGTH
    value whose scale depends on the Hamlib version and calibration; use the
    smeter-cal test to map it to dBm before comparing with IC7300 readings.

    Usage:
        rig = FT891()
        rig.set_mode("usb")
        rig.set_frequency(14_200_000)
        rig.set_agc("slow")
        rig.set_preamp(PREAMP_OFF)   # IPO: bypass preamp for strong-signal tests
        strength = rig.get_strength()
        rig.close()

    Context manager:
        with FT891() as rig:
            rig.set_frequency(14_200_000)
            ...
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self._host = host
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(CONNECT_TIMEOUT)
        self._sock.connect((host, port))
        self._sock.settimeout(RECV_TIMEOUT)

    # ------------------------------------------------------------------
    # Public API — matches IC7300 for interchangeability
    # ------------------------------------------------------------------

    def identify(self) -> str:
        """Return a short identification string (model + frequency)."""
        freq = self.get_frequency()
        mode, _ = self.get_mode()
        return f"FT-891 @ {freq/1e6:.4f} MHz {mode}"

    def get_frequency(self) -> float:
        """Return current VFO-A frequency in Hz."""
        resp = self._cmd("\\get_freq")
        try:
            return float(resp.split()[-1])
        except (ValueError, IndexError):
            return 0.0

    def set_frequency(self, freq_hz: float) -> None:
        """Set VFO-A frequency in Hz."""
        self._cmd(f"\\set_freq {int(freq_hz)}")
        time.sleep(0.15)   # FT-891 PLL settle; slightly longer than IC-7300

    def get_mode(self) -> tuple[str, int]:
        """
        Return current (mode_string, passband_hz).
        Mode string is a Hamlib mode name e.g. 'USB', 'CW'.
        """
        resp = self._cmd("\\get_mode")
        lines = resp.strip().splitlines()
        mode = lines[0].strip() if lines else "?"
        try:
            passband = int(lines[1].strip()) if len(lines) > 1 else 0
        except ValueError:
            passband = 0
        return mode, passband

    def set_mode(self, mode: str, passband_hz: int = 0) -> None:
        """
        Set receiver mode.

        Args:
            mode:        One of 'usb', 'lsb', 'cw', 'cwr', 'am', 'fm', 'rtty',
                         'pkt-u', 'pkt-l', 'pkt-fm'
            passband_hz: IF filter width in Hz. 0 = use rig default.
        """
        ham_mode = MODES.get(mode.lower(), mode.upper())
        if passband_hz == 0:
            passband_hz = DEFAULT_PASSBAND.get(ham_mode, 0)
        self._cmd(f"\\set_mode {ham_mode} {passband_hz}")
        time.sleep(0.15)

    def get_strength(self) -> float:
        """
        Return the S-meter / signal strength level.

        Hamlib returns STRENGTH as a float. The numeric scale is specific to
        the FT-891 / Hamlib version combination and differs from the IC-7300.
        Use the smeter-cal test to build a calibration curve.

        Returns NaN if the read fails.
        """
        resp = self._cmd("\\get_level STRENGTH")
        try:
            return float(resp.split()[-1])
        except (ValueError, IndexError):
            return float("nan")

    def get_strength_settled(self, settle_s: float = 0.5, samples: int = 3) -> float:
        """
        Wait settle_s seconds then return the average of `samples` strength readings.

        Use after changing signal level to allow AGC to stabilize. The FT-891's
        AGC time constants (FAST ~0.2 s, MID ~0.5 s, SLOW ~1–2 s) are similar
        to the IC-7300; increase settle_s to 2.0 when using SLOW AGC.
        """
        time.sleep(settle_s)
        readings = []
        for _ in range(samples):
            v = self.get_strength()
            if not math.isnan(v):
                readings.append(v)
            time.sleep(0.1)
        if not readings:
            return float("nan")
        return sum(readings) / len(readings)

    def set_agc(self, mode: str) -> None:
        """
        Set AGC mode.

        Args:
            mode: 'off', 'fast', 'mid', or 'slow'

        Note: 'off' maps to Hamlib AGC=0, which sets the FT-891 to its
        slowest AGC constant — it is NOT a true bypass. For absolute level
        measurements, use 'slow' + set_rf_gain() and verify linearity.
        """
        agc_map = {"off": AGC_OFF, "fast": AGC_FAST, "mid": AGC_MID, "slow": AGC_SLOW}
        val = agc_map.get(mode.lower())
        if val is None:
            raise ValueError(f"AGC mode must be one of {list(agc_map)}, got {mode!r}")
        self._cmd(f"\\set_level AGC {val}")
        time.sleep(0.1)

    def get_agc(self) -> int:
        """Return current AGC value (0=off/slowest, 1=fast, 2=mid, 3=slow)."""
        resp = self._cmd("\\get_level AGC")
        try:
            return int(float(resp.split()[-1]))
        except (ValueError, IndexError):
            return -1

    def set_rf_gain(self, gain: float) -> None:
        """
        Set RF gain (0.0 – 1.0, where 1.0 = maximum gain).

        With AGC in its slowest setting, this provides coarse manual attenuation
        useful for large-signal tests. Note: the FT-891 RF GAIN control reduces
        preamp/front-end gain, not just IF gain.
        """
        if not 0.0 <= gain <= 1.0:
            raise ValueError(f"RF gain must be 0.0–1.0, got {gain}")
        self._cmd(f"\\set_level RFGAIN {gain:.3f}")

    # ------------------------------------------------------------------
    # FT-891-specific methods (no IC-7300 equivalent)
    # ------------------------------------------------------------------

    def set_preamp(self, level: int = PREAMP_OFF) -> None:
        """
        Set preamp / IPO mode.

        Args:
            level: PREAMP_OFF (0) — IPO engaged, preamp bypassed.
                   PREAMP_AMP1 (1) — AMP1 active (~10 dB).

        Use PREAMP_OFF (IPO) when injecting strong test signals to avoid
        front-end compression. Use PREAMP_AMP1 for MDS and sensitivity tests.
        """
        if level not in (PREAMP_OFF, PREAMP_AMP1):
            raise ValueError(f"Preamp level must be {PREAMP_OFF} or {PREAMP_AMP1}, got {level}")
        self._cmd(f"\\set_level PREAMP {level}")
        time.sleep(0.1)

    def get_preamp(self) -> int:
        """Return current preamp level (0 = IPO/off, 1 = AMP1)."""
        resp = self._cmd("\\get_level PREAMP")
        try:
            return int(float(resp.split()[-1]))
        except (ValueError, IndexError):
            return -1

    def set_att(self, att_db: int) -> None:
        """
        Set front-end attenuator.

        The FT-891 supports 6 dB and 12 dB attenuation via the ATT menu.
        Via Hamlib, pass 0 (off), 6 (6 dB), or 12 (12 dB).

        Note: Hamlib support for FT-891 ATT control may be incomplete on some
        Hamlib versions. Verify the attenuator actually engaged on the front-panel
        display.
        """
        if att_db not in (0, 6, 12):
            raise ValueError(f"ATT must be 0, 6, or 12 dB, got {att_db}")
        self._cmd(f"\\set_level ATT {att_db}")
        time.sleep(0.1)

    def get_att(self) -> int:
        """Return current attenuator setting in dB (0, 6, or 12)."""
        resp = self._cmd("\\get_level ATT")
        try:
            return int(float(resp.split()[-1]))
        except (ValueError, IndexError):
            return -1

    def close(self) -> None:
        """Close the rigctld connection."""
        self._sock.close()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cmd(self, cmd: str) -> str:
        """Send a command to rigctld and return the response."""
        self._sock.sendall((cmd + "\n").encode())
        time.sleep(0.05)
        try:
            resp = b""
            while True:
                chunk = self._sock.recv(RECV_BUFSIZE)
                resp += chunk
                if resp.endswith(b"\n"):
                    break
            return resp.decode(errors="replace").strip()
        except socket.timeout:
            return ""

    # ------------------------------------------------------------------ #
    # Escape hatch — raw Hamlib commands                                 #
    # ------------------------------------------------------------------ #

    def raw_command(self, cmd: str) -> str:
        """Send raw command to Hamlib rigctld and return the response.

        This is an "escape hatch" for sending commands not yet wrapped by the driver.

        Args:
            cmd: Hamlib command (single letter or long form)

        Returns:
            Response from rigctld (may be multi-line)

        Examples:
            >>> # Single-letter commands
            >>> freq = radio.raw_command("f")  # Get frequency
            >>> radio.raw_command("F 7200000")  # Set frequency

            >>> # Long-form commands (backslash prefix)
            >>> info = radio.raw_command("\\dump_state")
            >>> radio.raw_command("\\set_level PREAMP 1")  # Preamp on

        Warning:
            Use with caution. Invalid commands may put rigctld or the radio in an
            unexpected state. Consult the Hamlib documentation for valid commands:
            https://hamlib.sourceforge.net/manpages/4.5/rigctld.8.html
        """
        return self._cmd(cmd)
