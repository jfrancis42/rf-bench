"""
ic7300.py — Icom IC-7300 CAT control via Hamlib rigctld

Communicates with rigctld over a plain TCP socket on port 4532.
rigctld must be running before any test is started:

    rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 &

Hamlib model numbers: 3073 (Hamlib 4.x), 373 (Hamlib 3.x).

The IC-7300 CI-V baud rate must match (Menu → Set → Connectors → CI-V Baud Rate).
"""

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

# AGC mode values as sent to rigctld set_level AGC
AGC_OFF   = 0
AGC_FAST  = 1
AGC_MID   = 2   # "medium" on IC-7300 front panel
AGC_SLOW  = 3

# Mode strings understood by Hamlib
MODES = {"usb": "USB", "lsb": "LSB", "cw": "CW", "cwr": "CWR",
         "am": "AM", "fm": "FM", "rtty": "RTTY"}

# Standard passband widths (Hz) by mode — used as default if not specified
DEFAULT_PASSBAND = {"USB": 2400, "LSB": 2400, "CW": 500, "CWR": 500,
                    "AM": 6000, "FM": 15000, "RTTY": 500}


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class IC7300:
    """
    IC-7300 CAT driver via Hamlib rigctld.

    All frequency values are in Hz. get_strength() returns a numeric value
    whose scale depends on the Hamlib version and calibration; use the
    smeter-cal test to map it to dBm.

    Usage:
        rig = IC7300()
        rig.set_mode("usb")
        rig.set_frequency(14_200_000)
        rig.set_agc("off")
        strength = rig.get_strength()
        rig.close()
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self._host = host
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(CONNECT_TIMEOUT)
        self._sock.connect((host, port))
        self._sock.settimeout(RECV_TIMEOUT)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_frequency(self) -> float:
        """Return current VFO-A frequency in Hz."""
        resp = self._cmd("\\get_freq")
        try:
            # rigctld responds with just the number, or "Frequency: <n>"
            return float(resp.split()[-1])
        except (ValueError, IndexError):
            return 0.0

    def set_frequency(self, freq_hz: float) -> None:
        """Set VFO-A frequency in Hz."""
        self._cmd(f"\\set_freq {int(freq_hz)}")
        time.sleep(0.1)   # give the IC-7300 time to tune

    def get_mode(self) -> tuple[str, int]:
        """
        Return current (mode_string, passband_hz).
        Mode string is a Hamlib mode name e.g. "USB", "CW".
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
            mode:        One of 'usb', 'lsb', 'cw', 'cwr', 'am', 'fm', 'rtty'
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

        Hamlib returns STRENGTH as a float. For the IC-7300 via Hamlib 4.x
        this is typically in dB relative to S9 (range ≈ −54 to +60 dB).
        The exact mapping depends on the Hamlib version; use smeter-cal to
        characterize the specific rig/version combination.

        Returns NaN if the read fails.
        """
        resp = self._cmd("\\get_level STRENGTH")
        try:
            return float(resp.split()[-1])
        except (ValueError, IndexError):
            return float("nan")

    def get_strength_settled(self, settle_s: float = 0.5, samples: int = 3) -> float:
        """
        Wait settle_s seconds then take the average of `samples` strength readings.

        Use after changing SDG level to let the IC-7300's AGC settle before reading.
        """
        time.sleep(settle_s)
        readings = []
        for _ in range(samples):
            v = self.get_strength()
            if not float("nan") == v:  # isnan check
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
        """
        agc_map = {"off": AGC_OFF, "fast": AGC_FAST, "mid": AGC_MID, "slow": AGC_SLOW}
        val = agc_map.get(mode.lower())
        if val is None:
            raise ValueError(f"AGC mode must be one of {list(agc_map)}, got {mode!r}")
        self._cmd(f"\\set_level AGC {val}")
        time.sleep(0.1)

    def get_agc(self) -> int:
        """Return current AGC value (0=off, 1=fast, 2=mid, 3=slow)."""
        resp = self._cmd("\\get_level AGC")
        try:
            return int(float(resp.split()[-1]))
        except (ValueError, IndexError):
            return -1

    def set_rf_gain(self, gain: float) -> None:
        """
        Set RF gain (0.0 – 1.0, where 1.0 = maximum gain).
        With AGC off, this directly controls receiver sensitivity.
        """
        self._cmd(f"\\set_level RFGAIN {gain:.3f}")

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
                # rigctld responses end with a newline (or blank line for multi-line)
                if resp.endswith(b"\n"):
                    break
            return resp.decode(errors="replace").strip()
        except socket.timeout:
            return ""
