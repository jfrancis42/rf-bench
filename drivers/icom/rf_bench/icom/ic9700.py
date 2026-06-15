"""
ic9700.py — Icom IC-9700 CAT control via Hamlib rigctld

The IC-9700 is a VHF/UHF/SHF all-mode transceiver covering:
  144 MHz (2 m), 430/440 MHz (70 cm), 1296 MHz (23 cm)

Communicates with rigctld over a plain TCP socket on port 4532.
rigctld must be running before any IC9700 is instantiated:

    rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &

Hamlib model 3081 — confirmed stable in Hamlib 4.x.
CI-V baud rate must match: Menu → Set → Connectors → CI-V Baud Rate.
Default CI-V address: 0xA2 (IC-9700 factory default).

Connection methods
------------------
USB (CI-V over USB serial):

    rigctld -m 3081 -r /dev/ttyUSB0 -s 115200

LAN (CI-V over built-in Ethernet / WLAN, IC-9700 firmware 1.20+):

    rigctld -m 3081 -r 192.168.1.10     # Hamlib ≥ 4.3 auto-detects LAN address

  OR use a TCP-serial bridge if your Hamlib version does not support direct LAN:

    socat TCP-LISTEN:4573,fork,reuseaddr \
          UDP:192.168.1.10:50002,bind=:50001 &
    rigctld -m 3081 -r localhost:4573

  IC-9700 LAN settings (Menu → Set → Network):
    WLAN/LAN: ON
    CI-V USB Baud Rate: 115200 (the LAN baud setting has no effect; leave default)
    IP Address: (static or DHCP)

Use ``IC9700.rigctld_cmd()`` to generate the correct command string for
either connection type.

The core read/write API (get_frequency, set_frequency, get_mode, set_mode,
get_strength, set_agc, set_rf_gain, close) is intentionally identical to
IC7300 for drop-in substitution in bench test scripts.

IC-9700-specific additions:
  - DV mode (D-STAR digital voice)
  - VFO A/B selection
  - Split / duplex operation for satellite cross-band
  - TX frequency and mode control (uplink)
  - PTT control
  - Satellite operation helpers

Satellite workflow example::

    with IC9700() as rig:
        # AO-91: 145.960 MHz FM downlink / 435.250 MHz FM uplink
        rig.set_satellite_mode(
            rx_freq_hz=145_960_000, rx_mode="FM",
            tx_freq_hz=435_250_000, tx_mode="FM",
        )
        rig.set_ptt(True)
        # ... transmit ...
        rig.set_ptt(False)
        rig.clear_satellite_mode()
"""

import socket
import time


# ── constants ─────────────────────────────────────────────────────────────────

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 4532
CONNECT_TIMEOUT = 5    # seconds
RECV_TIMEOUT    = 3    # seconds
RECV_BUFSIZE    = 4096

# AGC mode values for rigctld set_level AGC
AGC_OFF   = 0
AGC_FAST  = 1
AGC_MID   = 2
AGC_SLOW  = 3

# VFO identifiers as accepted by rigctld \set_vfo
VFO_A = "VFOA"   # Main band (downlink in satellite mode)
VFO_B = "VFOB"   # Sub band  (uplink in satellite mode)

# PTT states
PTT_RX = 0
PTT_TX = 1

# Mode strings understood by Hamlib for IC-9700
MODES = {
    "usb":    "USB",
    "lsb":    "LSB",
    "cw":     "CW",
    "cwr":    "CWR",
    "am":     "AM",
    "fm":     "FM",
    "dv":     "DV",     # D-STAR digital voice
    "digi":   "PKTUSB", # data / packet modes route through PKTUSB in Hamlib
}

# Default IF passband widths by Hamlib mode name
DEFAULT_PASSBAND = {
    "USB":    2400,
    "LSB":    2400,
    "CW":     500,
    "CWR":    500,
    "AM":     6000,
    "FM":     15000,
    "DV":     0,       # DV bandwidth is rig-defined; let Hamlib use default
    "PKTUSB": 2400,
}

# IC-9700 band boundaries (Hz) — used for band identification helpers
_BAND_2M   = (144_000_000, 148_000_000)
_BAND_70CM = (420_000_000, 450_000_000)
_BAND_23CM = (1_240_000_000, 1_300_000_000)


# ── driver ────────────────────────────────────────────────────────────────────

class IC9700:
    """
    IC-9700 CAT driver via Hamlib rigctld.

    The core frequency/mode/strength/AGC/RF-gain API is identical to
    ``IC7300`` and ``FT891`` for drop-in substitution.  IC-9700-specific
    methods add VFO selection, split/duplex operation, PTT, and TX-side
    frequency and mode control required for satellite cross-band work.

    The radio may be connected to the host running rigctld via USB or via
    the IC-9700's built-in LAN port.  Use ``IC9700.rigctld_cmd()`` to
    generate the appropriate ``rigctld`` invocation for either connection
    type.  Once rigctld is running, this class connects to it identically
    regardless of whether the radio is on USB or LAN.

    Args:
        host: Hostname or IP of the machine running rigctld (default:
              ``'localhost'``).
        port: rigctld TCP listen port (default: 4532).

    All frequency values are in Hz throughout the API.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self._host = host
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(CONNECT_TIMEOUT)
        self._sock.connect((host, port))
        self._sock.settimeout(RECV_TIMEOUT)

    # ── connection helpers ────────────────────────────────────────────────────

    @staticmethod
    def rigctld_cmd(
        device: str = "/dev/ttyUSB0",
        baud: int = 115200,
        rigctld_port: int = 4532,
    ) -> str:
        """
        Return the ``rigctld`` command string for this radio.

        Args:
            device:       Serial port (``'/dev/ttyUSB0'``) for USB connection,
                          or an IP address (``'192.168.1.10'``) for LAN
                          connection (Hamlib ≥ 4.3).
            baud:         Baud rate — only used for serial/USB connections;
                          ignored for LAN addresses.
            rigctld_port: TCP port on which rigctld will listen (default 4532).

        Returns:
            Shell command string suitable for passing to ``subprocess`` or
            running directly in a terminal.

        Examples::

            IC9700.rigctld_cmd()
            # → 'rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 --port 4532'

            IC9700.rigctld_cmd("192.168.1.10")
            # → 'rigctld -m 3081 -r 192.168.1.10 --port 4532'

            IC9700.rigctld_cmd("/dev/ttyUSB1", rigctld_port=4533)
            # → 'rigctld -m 3081 -r /dev/ttyUSB1 -s 115200 --port 4533'
        """
        import re
        is_ip = bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}$", device))
        if is_ip:
            return f"rigctld -m 3081 -r {device} --port {rigctld_port}"
        return f"rigctld -m 3081 -r {device} -s {baud} --port {rigctld_port}"

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "IC9700":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── frequency ─────────────────────────────────────────────────────────────

    def get_frequency(self) -> float:
        """Return the active VFO frequency in Hz."""
        resp = self._cmd("\\get_freq")
        try:
            return float(resp.split()[-1])
        except (ValueError, IndexError):
            return 0.0

    def set_frequency(self, freq_hz: float) -> None:
        """Set the active VFO frequency in Hz."""
        self._cmd(f"\\set_freq {int(freq_hz)}")
        time.sleep(0.1)

    def get_tx_frequency(self) -> float:
        """
        Return the TX (split/uplink) frequency in Hz.

        When split is disabled this returns the same value as
        ``get_frequency()``.
        """
        resp = self._cmd("\\get_split_freq")
        try:
            return float(resp.split()[-1])
        except (ValueError, IndexError):
            return self.get_frequency()

    def set_tx_frequency(self, freq_hz: float) -> None:
        """
        Set the TX (uplink) frequency in Hz.

        Split must be enabled (``set_split(True)``) before calling this;
        otherwise the command is silently ignored by Hamlib.
        """
        self._cmd(f"\\set_split_freq {int(freq_hz)}")
        time.sleep(0.1)

    # ── mode ──────────────────────────────────────────────────────────────────

    def get_mode(self) -> tuple:
        """Return ``(mode_str, passband_hz)`` for the active VFO."""
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
        Set the receive mode on the active VFO.

        Args:
            mode:        ``'usb'``, ``'lsb'``, ``'cw'``, ``'cwr'``,
                         ``'am'``, ``'fm'``, ``'dv'``, ``'digi'``
            passband_hz: IF filter width. 0 = use rig default.
        """
        ham_mode = MODES.get(mode.lower(), mode.upper())
        if passband_hz == 0:
            passband_hz = DEFAULT_PASSBAND.get(ham_mode, 0)
        self._cmd(f"\\set_mode {ham_mode} {passband_hz}")
        time.sleep(0.15)

    def get_tx_mode(self) -> tuple:
        """Return ``(mode_str, passband_hz)`` for the TX VFO (split mode)."""
        resp = self._cmd("\\get_split_mode")
        lines = resp.strip().splitlines()
        mode = lines[0].strip() if lines else "?"
        try:
            passband = int(lines[1].strip()) if len(lines) > 1 else 0
        except ValueError:
            passband = 0
        return mode, passband

    def set_tx_mode(self, mode: str, passband_hz: int = 0) -> None:
        """
        Set the TX (uplink) mode.

        Split must be enabled first.  Useful when the satellite downlink
        and uplink use different modes (e.g. linear transponder with USB
        uplink and USB downlink, or FM satellite with FM both ways).
        """
        ham_mode = MODES.get(mode.lower(), mode.upper())
        if passband_hz == 0:
            passband_hz = DEFAULT_PASSBAND.get(ham_mode, 0)
        self._cmd(f"\\set_split_mode {ham_mode} {passband_hz}")
        time.sleep(0.15)

    # ── signal strength ───────────────────────────────────────────────────────

    def get_strength(self) -> float:
        """
        Return the S-meter / signal strength level.

        Hamlib returns STRENGTH as a float (dB relative to S9 for IC-9700
        via Hamlib 4.x; range approx −54 to +60 dB).  Returns ``NaN`` on
        read failure.
        """
        resp = self._cmd("\\get_level STRENGTH")
        try:
            return float(resp.split()[-1])
        except (ValueError, IndexError):
            return float("nan")

    def get_strength_settled(self, settle_s: float = 0.5,
                              samples: int = 3) -> float:
        """
        Wait ``settle_s`` seconds then average ``samples`` strength readings.

        Use after changing signal source level to allow AGC to stabilise.
        """
        time.sleep(settle_s)
        readings = []
        for _ in range(samples):
            v = self.get_strength()
            if v == v:  # not NaN
                readings.append(v)
            time.sleep(0.1)
        return sum(readings) / len(readings) if readings else float("nan")

    # ── AGC / gain ────────────────────────────────────────────────────────────

    def set_agc(self, mode: str) -> None:
        """
        Set AGC mode.

        Args:
            mode: ``'off'``, ``'fast'``, ``'mid'``, or ``'slow'``.
                  ``'off'`` is a true hardware AGC bypass on the IC-9700.
        """
        agc_map = {"off": AGC_OFF, "fast": AGC_FAST,
                   "mid": AGC_MID, "slow": AGC_SLOW}
        val = agc_map.get(mode.lower())
        if val is None:
            raise ValueError(
                f"AGC mode must be one of {list(agc_map)}, got {mode!r}"
            )
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
        """Set RF gain, 0.0 (minimum) to 1.0 (maximum)."""
        self._cmd(f"\\set_level RFGAIN {gain:.3f}")

    # ── VFO selection ─────────────────────────────────────────────────────────

    def get_vfo(self) -> str:
        """Return the active VFO: ``'VFOA'`` or ``'VFOB'``."""
        resp = self._cmd("\\get_vfo")
        return resp.strip().split()[-1] if resp.strip() else VFO_A

    def set_vfo(self, vfo: str) -> None:
        """
        Select the active VFO.

        Args:
            vfo: ``'VFOA'`` (main/downlink) or ``'VFOB'`` (sub/uplink).
                 Use the module constants ``VFO_A`` and ``VFO_B``.
        """
        self._cmd(f"\\set_vfo {vfo.upper()}")
        time.sleep(0.05)

    # ── split / duplex ────────────────────────────────────────────────────────

    def get_split(self) -> bool:
        """Return ``True`` if split (TX ≠ RX VFO) is active."""
        resp = self._cmd("\\get_split_vfo")
        parts = resp.strip().split()
        try:
            return int(parts[0]) != 0
        except (ValueError, IndexError):
            return False

    def set_split(self, enabled: bool, tx_vfo: str = VFO_B) -> None:
        """
        Enable or disable split (duplex) operation.

        When enabled, VFO A is used for receive and ``tx_vfo`` (default
        VFO B) is used for transmit.  This is the standard configuration
        for cross-band satellite work.

        Args:
            enabled: ``True`` to enable split, ``False`` to disable.
            tx_vfo:  VFO used for TX when split is enabled (default
                     ``VFO_B``).
        """
        val = 1 if enabled else 0
        vfo = tx_vfo.upper() if enabled else VFO_A
        self._cmd(f"\\set_split_vfo {val} {vfo}")
        time.sleep(0.05)

    # ── PTT ───────────────────────────────────────────────────────────────────

    def get_ptt(self) -> bool:
        """Return ``True`` if the transmitter is currently keyed."""
        resp = self._cmd("\\get_ptt")
        try:
            return int(resp.split()[-1]) != 0
        except (ValueError, IndexError):
            return False

    def set_ptt(self, tx: bool) -> None:
        """
        Key or unkey the transmitter.

        Args:
            tx: ``True`` to begin transmitting, ``False`` to return to RX.

        .. warning::
            Always call ``set_ptt(False)`` before closing the driver.
            An unhandled exception while transmitting will leave the radio
            keyed.  Use the context manager (``with IC9700() as rig:``) to
            ensure cleanup.
        """
        self._cmd(f"\\set_ptt {PTT_TX if tx else PTT_RX}")
        time.sleep(0.05)

    # ── satellite helpers ─────────────────────────────────────────────────────

    def set_satellite_mode(
        self,
        rx_freq_hz: float,
        rx_mode: str,
        tx_freq_hz: float,
        tx_mode: str,
        rx_passband_hz: int = 0,
        tx_passband_hz: int = 0,
    ) -> None:
        """
        Configure the radio for cross-band satellite operation in one call.

        Sets VFO A (downlink / RX) frequency and mode, enables split, then
        sets VFO B (uplink / TX) frequency and mode.  The active VFO is
        returned to VFO A (receive) on completion.

        Example — AO-91 (Fox-1B) FM satellite::

            rig.set_satellite_mode(
                rx_freq_hz=145_960_000, rx_mode="FM",
                tx_freq_hz=435_250_000, tx_mode="FM",
            )

        Example — IO-117 / FO-29 linear transponder (USB/LSB)::

            rig.set_satellite_mode(
                rx_freq_hz=435_850_000, rx_mode="USB",
                tx_freq_hz=145_950_000, tx_mode="LSB",
            )

        Args:
            rx_freq_hz:     Downlink (receive) frequency in Hz.
            rx_mode:        Downlink mode string (e.g. ``'FM'``, ``'USB'``).
            tx_freq_hz:     Uplink (transmit) frequency in Hz.
            tx_mode:        Uplink mode string.
            rx_passband_hz: Downlink IF filter (0 = rig default).
            tx_passband_hz: Uplink IF filter (0 = rig default).
        """
        # Set RX (downlink) on VFO A
        self.set_vfo(VFO_A)
        self.set_frequency(rx_freq_hz)
        self.set_mode(rx_mode, rx_passband_hz)

        # Enable split so VFO B is the TX VFO
        self.set_split(True, tx_vfo=VFO_B)

        # Set TX (uplink) frequency and mode via split commands
        self.set_tx_frequency(tx_freq_hz)
        self.set_tx_mode(tx_mode, tx_passband_hz)

        # Leave active VFO on A (receive)
        self.set_vfo(VFO_A)

    def clear_satellite_mode(self) -> None:
        """
        Disable split and ensure PTT is released.

        Call this after a satellite pass to return the radio to normal
        simplex operation.
        """
        if self.get_ptt():
            self.set_ptt(False)
        self.set_split(False)

    def update_doppler(
        self,
        rx_freq_hz: float,
        tx_freq_hz: float,
    ) -> None:
        """
        Apply a Doppler correction to both RX and TX frequencies.

        Designed to be called in a loop (e.g. every second) during a
        satellite pass.  Updates VFO A (downlink) and the split TX
        frequency (uplink) without changing modes or split state.

        Args:
            rx_freq_hz: Doppler-corrected downlink frequency in Hz.
            tx_freq_hz: Doppler-corrected uplink frequency in Hz.
        """
        self.set_frequency(rx_freq_hz)
        self.set_tx_frequency(tx_freq_hz)

    # ── band identification ───────────────────────────────────────────────────

    @staticmethod
    def band_of(freq_hz: float) -> str:
        """
        Return a human-readable band name for a frequency.

        Returns ``'2m'``, ``'70cm'``, ``'23cm'``, or ``'unknown'``.
        """
        if _BAND_2M[0] <= freq_hz <= _BAND_2M[1]:
            return "2m"
        if _BAND_70CM[0] <= freq_hz <= _BAND_70CM[1]:
            return "70cm"
        if _BAND_23CM[0] <= freq_hz <= _BAND_23CM[1]:
            return "23cm"
        return "unknown"

    # ── close ─────────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Release PTT if held, then close the rigctld connection."""
        try:
            if self.get_ptt():
                self.set_ptt(False)
        except Exception:
            pass
        self._sock.close()

    # ── internal ──────────────────────────────────────────────────────────────

    def _cmd(self, cmd: str) -> str:
        """Send a command to rigctld and return the stripped response."""
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
            >>> radio.raw_command("F 14250000")  # Set frequency

            >>> # Long-form commands (backslash prefix)
            >>> info = radio.raw_command("\\dump_state")
            >>> radio.raw_command("\\set_ptt 1")  # PTT on

        Warning:
            Use with caution. Invalid commands may put rigctld or the radio in an
            unexpected state. Consult the Hamlib documentation for valid commands:
            https://hamlib.sourceforge.net/manpages/4.5/rigctld.8.html
        """
        return self._cmd(cmd)
