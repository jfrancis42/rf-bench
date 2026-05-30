"""
sdg1000x.py — Siglent SDG1000X function generator driver

Connects via raw TCP/SCPI to port 5025. Uses Siglent's EasyWave protocol
(C1:BSWV / C2:BSWV commands), not standard IEEE SCPI. Both channels are
independent; each can be set to different frequencies and levels simultaneously.

Model: Siglent SDG1000X series
Default address: 10.1.1.61:5025

Amplitude notes:
    All public methods accept and return dBm (into 50 Ω).
    Internally the SDG uses Vpp across its configured load impedance.
    With LOAD,50 the displayed/set amplitude IS the voltage across the 50 Ω load.
    Conversion is handled by rf_utils.dbm_to_vpp / vpp_to_dbm.

Known firmware behavior:
    Some SDG firmware versions ignore the LOAD parameter inside BSWV and require
    a separate `C1:OUTP ON,LOAD,50` to set the termination. Always enable output
    with the LOAD parameter explicit (output_on() handles this).
"""

import re
import socket
import time

from ..utils.rf_utils import dbm_to_vpp, vpp_to_dbm


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HOST = "10.1.1.55"
DEFAULT_PORT = 5025
CONNECT_TIMEOUT = 10      # seconds
RECV_TIMEOUT    = 5       # seconds
RECV_BUFSIZE    = 65536

# SDG1000X amplitude limits (Vpp into 50 Ω)
VPP_MIN_50 = 0.002   # 2 mVpp ≈ −46 dBm; waveform quality degrades below ~10 mVpp
VPP_MAX_50 = 10.0    # 10 Vpp ≈ +24 dBm

DBM_MIN = vpp_to_dbm(VPP_MIN_50)   # ≈ −46 dBm
DBM_MAX = vpp_to_dbm(VPP_MAX_50)   # ≈ +24 dBm


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class SDG1000X:
    """
    Driver for the Siglent SDG1000X dual-channel function generator.

    Usage:
        sdg = SDG1000X("10.1.1.61")
        sdg.set_sine(1, freq_hz=14_001_000, level_dbm=-20)
        sdg.set_sine(2, freq_hz=14_001_500, level_dbm=-20)
        sdg.output_on(1)
        sdg.output_on(2)
        ...
        sdg.output_off_all()
        sdg.close()

    Context manager:
        with SDG1000X("10.1.1.61") as sdg:
            sdg.set_sine(1, 14e6, -20)
            sdg.output_on(1)
            ...
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self._host = host
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(CONNECT_TIMEOUT)
        self._sock.connect((host, port))
        self._sock.settimeout(RECV_TIMEOUT)
        # Drain any startup banner
        time.sleep(0.1)
        try:
            self._sock.recv(RECV_BUFSIZE)
        except socket.timeout:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def identify(self) -> str:
        """Return IDN string."""
        return self._query("*IDN?")

    def set_sine(self, channel: int, freq_hz: float, level_dbm: float,
                 phase_deg: float = 0.0) -> None:
        """
        Configure a channel for sine wave output.

        Args:
            channel:   1 or 2
            freq_hz:   Frequency in Hz (1 μHz to 60 MHz)
            level_dbm: Output level in dBm into 50 Ω
            phase_deg: Phase offset in degrees [default 0]

        The channel output is NOT enabled by this call; follow with output_on().
        """
        self._check_channel(channel)
        self._check_level(level_dbm)

        vpp = dbm_to_vpp(level_dbm)
        ch  = f"C{channel}"
        self._cmd(
            f"{ch}:BSWV WVTP,SINE,"
            f"FRQ,{freq_hz:.6f},"
            f"AMP,{vpp:.6f},"
            f"OFST,0,"
            f"PHSE,{phase_deg:.3f}"
        )

    def output_on(self, channel: int) -> None:
        """Enable output on the specified channel with 50 Ω termination."""
        self._check_channel(channel)
        self._cmd(f"C{channel}:OUTP ON,LOAD,50")

    def output_off(self, channel: int) -> None:
        """Disable output on the specified channel."""
        self._check_channel(channel)
        self._cmd(f"C{channel}:OUTP OFF")

    def output_off_all(self) -> None:
        """Disable both channel outputs."""
        self.output_off(1)
        self.output_off(2)

    def set_level(self, channel: int, level_dbm: float) -> None:
        """
        Change only the output level of a configured channel (preserves frequency).
        """
        self._check_channel(channel)
        self._check_level(level_dbm)
        vpp = dbm_to_vpp(level_dbm)
        self._cmd(f"C{channel}:BSWV AMP,{vpp:.6f}")

    def set_frequency(self, channel: int, freq_hz: float) -> None:
        """
        Change only the output frequency; preserve the current amplitude.

        Sends a partial BSWV update — the SDG applies only the fields present
        in the command and leaves all others unchanged.

        Args:
            channel:  1 or 2
            freq_hz:  Frequency in Hz (1 μHz to 60 MHz)
        """
        self._check_channel(channel)
        self._cmd(f"C{channel}:BSWV FRQ,{freq_hz:.6f}")

    def query_output_state(self, channel: int) -> bool:
        """Return True if the output is currently enabled on this channel."""
        self._check_channel(channel)
        resp = self._query(f"C{channel}:OUTP?")
        return "ON" in resp.upper()

    def query_channel(self, channel: int) -> dict:
        """
        Query current channel settings.

        Returns a dict with keys: wvtp, freq_hz, amp_vpp, amp_dbm, ofst_v, phase_deg.

        The SDG firmware appends unit suffixes to numeric values (e.g. '1000HZ',
        '0.2V', '-10.0dBm').  _strip_unit() strips the suffix before parsing.
        """
        self._check_channel(channel)
        resp = self._query(f"C{channel}:BSWV?")
        # Response: "C1:BSWV WVTP,SINE,FRQ,1000HZ,PERI,0.001S,AMP,0.2V,AMPDBM,-10.0dBm,..."
        params = {}
        if "BSWV" in resp:
            resp = resp.split("BSWV", 1)[1].strip()
        parts = resp.split(",")
        for i in range(0, len(parts) - 1, 2):
            key = parts[i].strip().upper()
            val = parts[i + 1].strip()
            params[key] = val

        result = {"wvtp": params.get("WVTP", "?")}
        try:
            result["freq_hz"]   = self._strip_unit(params.get("FRQ",  "0"))
            result["amp_vpp"]   = self._strip_unit(params.get("AMP",  "0"))
            # Prefer the firmware-reported dBm value if present (avoids roundtrip error)
            if "AMPDBM" in params:
                result["amp_dbm"] = self._strip_unit(params["AMPDBM"])
            else:
                result["amp_dbm"] = vpp_to_dbm(result["amp_vpp"])
            result["ofst_v"]    = self._strip_unit(params.get("OFST", "0"))
            result["phase_deg"] = self._strip_unit(params.get("PHSE", "0"))
        except (ValueError, ZeroDivisionError):
            pass
        return result

    @staticmethod
    def _strip_unit(val_str: str) -> float:
        """Parse a numeric value that may have a trailing unit suffix (e.g. '1000HZ', '0.2V')."""
        m = re.match(r'([-+]?[\d.]+(?:[eE][-+]?\d+)?)', val_str)
        if m:
            return float(m.group(1))
        return float(val_str)

    def close(self) -> None:
        """Disable outputs and close the TCP connection."""
        try:
            self.output_off_all()
        except Exception:
            pass
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

    @staticmethod
    def _check_channel(channel: int) -> None:
        if channel not in (1, 2):
            raise ValueError(f"Channel must be 1 or 2, got {channel}")

    def _check_level(self, level_dbm: float) -> None:
        if not (DBM_MIN <= level_dbm <= DBM_MAX):
            raise ValueError(
                f"Level {level_dbm:.1f} dBm out of range "
                f"[{DBM_MIN:.1f}, {DBM_MAX:.1f}] dBm"
            )

    def _cmd(self, cmd: str) -> None:
        """Send a command and wait briefly for the instrument to process it."""
        self._sock.sendall((cmd + "\n").encode())
        time.sleep(0.05)

    def _query(self, cmd: str) -> str:
        """Send a query and return the response string."""
        self._sock.sendall((cmd + "\n").encode())
        time.sleep(0.05)
        try:
            data = self._sock.recv(RECV_BUFSIZE)
            return data.decode(errors="replace").strip()
        except socket.timeout:
            return ""
