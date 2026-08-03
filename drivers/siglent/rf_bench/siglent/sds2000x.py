"""
sds2000x.py — Siglent SDS2000X Plus oscilloscope driver

Connects via raw TCP to port 5025.  Used primarily for audio waveform
capture and FFT analysis in the two-tone IMD test.

Protocol notes (verified on SDS2504X Plus firmware 5.4.x):
  - Channel config uses Siglent EasyScope format: C1:CPL A1M, C1:VDIV 0.05V
  - Timebase:  TDIV 0.02S
  - Trigger mode: TRMD AUTO
  - Measurements: C1:PAVA? RMS  →  'C1:PAVA RMS,1.48E-01V'
  - Waveform preamble (:WAVeform:PREamble?) returns a 346-byte binary WAVEDESC
    block, NOT a comma-separated ASCII string.  Parsed via _parse_wavedesc().
  - Waveform data (:WAVeform:DATA?) returns a signed-byte IEEE 488.2 binary
    block.  Conversion: voltage = raw_count * VERTICAL_GAIN - VERTICAL_OFFSET
  - Standard SCPI :MEASure:* commands do not return responses on this firmware.
    Use C1:PAVA? instead.
"""

import re
import socket
import struct
import time

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HOST    = "10.1.1.58"
DEFAULT_PORT    = 5025
CONNECT_TIMEOUT = 10       # seconds
RECV_TIMEOUT    = 60       # seconds — 10 MB waveform transfer at 1 GbE ≈ 80 ms
RECV_BUFSIZE    = 1 << 20  # 1 MB read buffer

# Audio capture defaults
AUDIO_VDIV_DEFAULT  = 0.1      # 100 mV/div starting point for auto-range
_AUTORANGE_SAT_THRESH = 0.005  # >0.5% saturated samples → scale up vdiv
_AUTORANGE_MAX_STEPS  = 6      # max doublings: 0.1 → 0.2 → 0.4 → 0.8 → 1.6 → 3.2 → 6.4 V/div

# WAVEDESC binary offsets (Siglent SDS2000X Plus, 346-byte block)
_WD_VERTICAL_GAIN   = 156   # float32 — volts per ADC count
_WD_VERTICAL_OFFSET = 160   # float32 — subtract after gain to get voltage
_WD_HORIZ_INTERVAL  = 176   # float32 — seconds per sample
_WD_WAVE_ARRAY_1    = 60    # int32   — byte count of data array


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class SDS2000X:
    """
    Driver for the Siglent SDS2000X Plus oscilloscope.

    Primary use: capture audio waveform for FFT-based IMD analysis.

    Usage:
        scope = SDS2000X("10.1.1.58")
        voltages, sample_rate = scope.capture_audio(channel=1, duration_s=2.0)
        scope.close()
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self._host = host
        self._port = port
        self._sock = None
        self._last_capture_vdiv: dict = {}   # channel → last vdiv used in capture_audio
        self.connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self):
        """Open TCP connection to the instrument."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(CONNECT_TIMEOUT)
        self._sock.connect((self._host, self._port))
        time.sleep(0.1)
        # Flush any welcome / leftover data with a short timeout (1 s).
        # RECV_TIMEOUT (60 s) is only appropriate for large waveform transfers.
        self._sock.settimeout(1.0)
        try:
            self._sock.recv(RECV_BUFSIZE)
        except socket.timeout:
            pass
        self._sock.settimeout(RECV_TIMEOUT)

    def disconnect(self):
        """Close the TCP connection."""
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def identify(self) -> str:
        return self._query("*IDN?")

    def capture_audio(
        self,
        channel: int = 1,
        duration_s: float = 2.0,
        vdiv: float | None = None,
    ) -> tuple[np.ndarray, float]:
        """
        Capture a waveform from an audio signal on the specified channel.

        Configures the channel for AC coupling and the requested V/div, sets
        the timebase so the capture window = duration_s, triggers one sweep,
        then reads the waveform as a signed-byte WAVEDESC block.

        Args:
            channel:    Scope channel number (1–4)
            duration_s: Capture window in seconds (timebase = duration_s / 10
                        s/div, 10 divisions total).  Longer → finer FFT bins.
                        2.0 s → ~0.5 Hz bin width at audio sample rates.
            vdiv:       Vertical sensitivity in V/div.  None (default) = auto-
                        range: takes a quick capture at AUDIO_VDIV_DEFAULT and
                        doubles the scale until <0.5% of samples saturate.
                        Pass an explicit value to skip auto-ranging.

        Returns:
            (voltages, sample_rate_hz):
                voltages       — numpy float64 array (signed, in volts)
                sample_rate_hz — actual sample rate from WAVEDESC (Hz)

        Note:
            The scope may return up to ~10 M samples per channel at fast
            timebases.  Transfer time over 1 GbE is ~80 ms for 10 MB.

        Raises:
            RuntimeError: if waveform read fails or WAVEDESC is malformed.
        """
        ch   = f"C{channel}"
        tdiv = duration_s / 10.0

        if vdiv is None:
            vdiv = self._autorange_vdiv(channel)

        # Firmware 5.4.x intermittently returns a 1000-sample display buffer at
        # 2 GSps instead of deep memory.  The bug is state-dependent (not tied to
        # a specific VDIV), so retry once on display-buffer detection.
        for attempt in range(2):
            # Always start from STOP so TDIV/VDIV changes take effect cleanly
            self.stop()
            time.sleep(0.1)

            # Channel: AC coupling, vertical scale
            self._cmd(f"{ch}:CPL A1M")
            self._cmd(f"{ch}:VDIV {vdiv:.4f}V")

            # Timebase
            self._cmd(f"TDIV {tdiv:.6f}S")

            # Trigger: free-run (no external event needed for audio)
            self._cmd("TRMD AUTO")

            # Acquire then freeze
            self.run()
            time.sleep(duration_s + 0.5)
            self.stop()
            time.sleep(0.2)

            # Select waveform source, byte format, and request full memory depth
            self._cmd(f":WAVeform:SOURce {ch}")
            self._cmd(":WAVeform:FORMat BYTE")
            self._cmd(":WAVeform:POINt MAX")

            # Read 346-byte binary WAVEDESC preamble
            pre = self._read_binary_block(":WAVeform:PREamble?")
            horiz_interval, vgain, voffset = self._parse_wavedesc(pre)

            # Read waveform data
            raw = self._read_binary_block(":WAVeform:DATA?")
            if not raw:
                raise RuntimeError("Waveform data empty — check channel and timebase")

            # Signed bytes; voltage = count × vgain − voffset
            counts   = np.frombuffer(raw, dtype=np.int8).astype(np.float64)
            voltages = counts * vgain - voffset

            sample_rate_hz = 1.0 / horiz_interval if horiz_interval > 0 else 0.0

            # Check for display-buffer firmware bug (≤1000 samples at >500 MHz)
            if len(voltages) <= 1000 and sample_rate_hz > 500e6:
                if attempt == 0:
                    continue   # retry once — bug is state-dependent, clears on re-arm
                raise RuntimeError(
                    f"Scope returned display-buffer data ({len(voltages)} pts at "
                    f"{sample_rate_hz/1e6:.0f} MHz) after 2 attempts — "
                    f"VDIV={vdiv:.4f} V, TDIV={tdiv:.4f} S.  "
                    f"Try disconnecting/reconnecting the scope."
                )

            self._last_capture_vdiv[channel] = vdiv
            return voltages, sample_rate_hz

        raise RuntimeError("capture_audio: unreachable")

    def _read_channel_waveform(self, channel: int):
        """Read one channel's waveform from the CURRENTLY FROZEN acquisition.

        Assumes the scope is already stopped and holding an acquired sweep.
        Does NOT arm, run, or stop — the caller owns acquisition state. This is
        what lets two channels be read from the *same* single acquisition so
        they stay phase-aligned.

        Returns (voltages float64 array, sample_rate_hz).
        """
        ch = f"C{channel}"
        self._cmd(f":WAVeform:SOURce {ch}")
        self._cmd(":WAVeform:FORMat BYTE")
        self._cmd(":WAVeform:POINt MAX")
        pre = self._read_binary_block(":WAVeform:PREamble?")
        horiz_interval, vgain, voffset = self._parse_wavedesc(pre)
        raw = self._read_binary_block(":WAVeform:DATA?")
        if not raw:
            raise RuntimeError(f"Waveform data empty on C{channel}")
        counts = np.frombuffer(raw, dtype=np.int8).astype(np.float64)
        voltages = counts * vgain - voffset
        sample_rate_hz = 1.0 / horiz_interval if horiz_interval > 0 else 0.0
        return voltages, sample_rate_hz

    def capture_two_channels(
        self,
        ch_a: int = 1,
        ch_b: int = 2,
        duration_s: float = 0.1,
        vdiv_a: float | None = None,
        vdiv_b: float | None = None,
    ):
        """Capture two channels from a SINGLE phase-locked acquisition.

        Both channels are read off the same frozen sweep, so sample *i* on
        ch_a and sample *i* on ch_b are simultaneous. This is required for any
        instantaneous-product math — e.g. real power p(t)=v(t)·i(t) and power
        factor — where a free-run per-channel capture (as in capture_audio)
        would leave the two waveforms uncorrelated in phase.

        Args:
            ch_a, ch_b: Scope channel numbers (1–4). Convention for power work:
                        ch_a = voltage sense, ch_b = current (clamp/burden).
            duration_s: Capture window (timebase = duration_s / 10). Default
                        0.1 s ≈ 5–6 mains cycles at 50/60 Hz — enough for a
                        stable power/PF estimate.
            vdiv_a, vdiv_b: V/div per channel. None → auto-range that channel.

        Returns:
            dict with keys:
              't'            — time array (s), shared by both channels
              'a'            — ch_a voltages (V)
              'b'            — ch_b voltages (V)
              'sample_rate'  — Hz
              'ch_a', 'ch_b' — the channel numbers used

        Raises:
            RuntimeError: on empty/short waveform or display-buffer firmware bug.
        """
        tdiv = duration_s / 10.0

        # Auto-range each channel first (each call arms/stops on its own; that's
        # fine — it only sets vdiv). Do this BEFORE the shared acquisition.
        if vdiv_a is None:
            vdiv_a = self._autorange_vdiv(ch_a)
        if vdiv_b is None:
            vdiv_b = self._autorange_vdiv(ch_b)

        for attempt in range(2):
            self.stop()
            time.sleep(0.1)
            for ch, vdiv in ((ch_a, vdiv_a), (ch_b, vdiv_b)):
                self._cmd(f"C{ch}:CPL A1M")
                self._cmd(f"C{ch}:VDIV {vdiv:.4f}V")
            self._cmd(f"TDIV {tdiv:.6f}S")
            self._cmd("TRMD AUTO")

            # ONE acquisition, then freeze — both reads come from this sweep.
            self.run()
            time.sleep(duration_s + 0.5)
            self.stop()
            time.sleep(0.2)

            va, sr_a = self._read_channel_waveform(ch_a)
            vb, sr_b = self._read_channel_waveform(ch_b)

            # Display-buffer firmware bug (see capture_audio): retry once.
            if (min(len(va), len(vb)) <= 1000 and max(sr_a, sr_b) > 500e6):
                if attempt == 0:
                    continue
                raise RuntimeError(
                    f"Scope returned display-buffer data "
                    f"({len(va)}/{len(vb)} pts) after 2 attempts — "
                    f"try disconnecting/reconnecting the scope."
                )

            # Guard: both channels must share the same sample rate and length
            # or the phase-lock assumption is void. Truncate to the shorter.
            n = min(len(va), len(vb))
            va, vb = va[:n], vb[:n]
            sr = sr_a if sr_a > 0 else sr_b
            t = np.arange(n) / sr if sr > 0 else np.arange(n, dtype=np.float64)

            self._last_capture_vdiv[ch_a] = vdiv_a
            self._last_capture_vdiv[ch_b] = vdiv_b
            return {
                "t": t, "a": va, "b": vb,
                "sample_rate": sr, "ch_a": ch_a, "ch_b": ch_b,
            }

        raise RuntimeError("capture_two_channels: unreachable")

    def _pava_setup(self, channel: int) -> None:
        """
        Set a short TDIV and start a fresh acquisition for PAVA.

        Must stop first — changing TDIV while running corrupts the acquisition
        (firmware bug: TDIV/VDIV changes must be made while scope is stopped).

        Also explicitly re-applies VDIV.  Without this, a TDIV change while
        stopped can silently corrupt the VDIV register on firmware 5.4.x,
        causing PAVA FREQ to return garbage values.  Uses the last vdiv set
        by capture_audio for this channel, or 0.5 V/div as a safe default.
        """
        ch   = f"C{channel}"
        vdiv = self._last_capture_vdiv.get(channel, 0.5)
        self.stop()
        time.sleep(0.05)
        self._cmd(f"{ch}:VDIV {vdiv:.4f}V")
        self._cmd("TDIV 0.002000S")   # 20 ms window — PAVA needs a complete sweep
        self._cmd("TRMD AUTO")
        self.run()
        time.sleep(0.5)
        self._drain()   # flush any stale bytes left in socket from prior captures

    def measure_rms(self, channel: int = 1) -> float:
        """
        Return the RMS voltage from the scope's built-in measurement.

        Uses EasyScope: C{n}:PAVA? RMS → 'C1:PAVA RMS,1.48E-01V'
        Units: volts RMS.
        """
        self._pava_setup(channel)
        resp = self._query(f"C{channel}:PAVA? RMS")
        return self._parse_pava(resp)

    def measure_vpp(self, channel: int = 1) -> float:
        """Return the peak-to-peak voltage measurement. Units: volts."""
        self._pava_setup(channel)
        resp = self._query(f"C{channel}:PAVA? PKPK")
        return self._parse_pava(resp)

    def measure_freq(self, channel: int = 1) -> float:
        """Return the frequency measurement. Units: Hz."""
        self._pava_setup(channel)
        resp = self._query(f"C{channel}:PAVA? FREQ")
        return self._parse_pava(resp)

    def autoscale_vdiv(self, channel: int, target_divisions: float = 3.0) -> float:
        """
        Run the scope for a moment, read the peak-to-peak voltage, and return
        a suggested V/div that fills ~target_divisions of screen.

        Returns the suggested V/div (not yet applied — caller must set it).
        """
        self.run()
        time.sleep(0.5)
        vpp = self.measure_vpp(channel)
        self.stop()
        if vpp > 0:
            return vpp / (2 * target_divisions)
        return AUDIO_VDIV_DEFAULT

    def run(self) -> None:
        """Start (resume) continuous acquisition."""
        self._cmd(":RUN")

    def stop(self) -> None:
        """Stop (freeze) acquisition."""
        self._cmd(":STOP")

    def close(self) -> None:
        self.run()
        self.disconnect()

    # ------------------------------------------------------------------
    # Built-in AWG ("Gen Out" arbitrary waveform generator)
    # ------------------------------------------------------------------
    # SDS2000X Plus has a licensed 25 MHz AWG on a dedicated "Gen Out" BNC.
    #
    # SCPI: the AWG is addressed as channel C1 with SDG-style commands —
    # `C1:BSWV` for waveform parameters (TYPE, FRQ, AMP, OFST, DUTY, etc.),
    # `C1:OUTP` for output enable + load impedance, `C1:ARWV` for selecting
    # built-in arbitrary waveforms by index. This mirrors the standalone
    # Siglent SDG signal generator command set.
    #
    # NOTE: the AWG's "C1" namespace is disjoint from the analog input C1
    # commands (`C1:CPL`, `C1:VDIV`, etc.) — the second token disambiguates.
    # The published Siglent programming guide's WGEN/WAVEGENERATOR family
    # is for the older non-Plus SDS2000X, NOT this scope; live testing on
    # firmware 5.4.0.1.6.2R5 confirms WGEN-prefixed commands return -113
    # Undefined header.
    #
    # Verified working against:
    #   *IDN?  Siglent Technologies,SDS2504X Plus,SDS2PEEX7R1702,5.4.0.1.6.2R5
    #   *OPT?  ...,FG,...   (Function Generator license installed)

    # Default load impedance for the AWG (50 Ω = into-50Ω; HZ = high-Z).
    # Most measurements assume a 50 Ω load. Change with set_awg_load(...).
    _AWG_LOAD = "50"

    def set_awg_sine(self, freq_hz: float, amplitude_vpp: float,
                     offset_v: float = 0.0, phase_deg: float = 0.0) -> None:
        """Configure the AWG for sine wave and enable the output.

        Args:
            freq_hz:       Frequency in Hz (1 mHz – 25 MHz on SDS2504X Plus)
            amplitude_vpp: Peak-to-peak amplitude in V into the configured load
            offset_v:      DC offset in V (default 0)
            phase_deg:     Phase offset in degrees (default 0)
        """
        self._cmd(
            f"C1:BSWV WVTP,SINE,FRQ,{freq_hz:g}HZ,AMP,{amplitude_vpp:g}V,"
            f"OFST,{offset_v:g}V,PHSE,{phase_deg:g}"
        )
        self._cmd(f"C1:OUTP ON,LOAD,{self._AWG_LOAD}")
        time.sleep(0.1)

    def set_awg_square(self, freq_hz: float, amplitude_vpp: float,
                       duty_pct: float = 50.0, offset_v: float = 0.0) -> None:
        """Configure the AWG for square wave and enable the output.

        Args:
            freq_hz:       Frequency in Hz
            amplitude_vpp: Peak-to-peak amplitude in V
            duty_pct:      Duty cycle in percent (1–99, default 50)
            offset_v:      DC offset in V (default 0)
        """
        self._cmd(
            f"C1:BSWV WVTP,SQUARE,FRQ,{freq_hz:g}HZ,AMP,{amplitude_vpp:g}V,"
            f"OFST,{offset_v:g}V,DUTY,{duty_pct:g}"
        )
        self._cmd(f"C1:OUTP ON,LOAD,{self._AWG_LOAD}")
        time.sleep(0.1)

    def set_awg_ramp(self, freq_hz: float, amplitude_vpp: float,
                     symmetry_pct: float = 100.0, offset_v: float = 0.0) -> None:
        """Configure the AWG for ramp (sawtooth) wave and enable the output.

        Args:
            freq_hz:       Frequency in Hz
            amplitude_vpp: Peak-to-peak amplitude in V
            symmetry_pct:  Ramp symmetry — 100% = sawtooth, 50% = triangle (default 100)
            offset_v:      DC offset in V (default 0)
        """
        self._cmd(
            f"C1:BSWV WVTP,RAMP,FRQ,{freq_hz:g}HZ,AMP,{amplitude_vpp:g}V,"
            f"OFST,{offset_v:g}V,SYM,{symmetry_pct:g}"
        )
        self._cmd(f"C1:OUTP ON,LOAD,{self._AWG_LOAD}")
        time.sleep(0.1)

    def set_awg_dc(self, offset_v: float) -> None:
        """Output a DC voltage from the AWG.

        Args:
            offset_v: DC level in V (within the AWG's offset range).
        """
        self._cmd(f"C1:BSWV WVTP,DC,OFST,{offset_v:g}V")
        self._cmd(f"C1:OUTP ON,LOAD,{self._AWG_LOAD}")
        time.sleep(0.1)

    def set_awg_load(self, load) -> None:
        """Set the AWG output load convention.

        Args:
            load: 50 / "50" → 50 Ω termination (most measurements);
                  "HZ" / None → high-impedance (open-circuit) reporting.

        The setting affects how the AWG reports its amplitude, not its
        actual output impedance. The AWG's source impedance is fixed at
        ~50 Ω; this just tells it which units the user expects.
        """
        if load is None or str(load).upper() == "HZ":
            self._AWG_LOAD = "HZ"
        else:
            self._AWG_LOAD = str(int(load))
        # Push the new load setting to the scope without changing output state
        self._cmd(f"C1:OUTP LOAD,{self._AWG_LOAD}")

    def awg_output_on(self) -> None:
        """Enable the AWG output without changing the waveform configuration."""
        self._cmd(f"C1:OUTP ON,LOAD,{self._AWG_LOAD}")

    def awg_output_off(self) -> None:
        """Disable the AWG output."""
        self._cmd(f"C1:OUTP OFF,LOAD,{self._AWG_LOAD}")

    def get_awg_state(self) -> dict:
        """Query the current AWG configuration.

        Returns:
            dict with keys: function (str), freq_hz (float), amplitude_vpp (float),
            offset_v (float), phase_deg (float, where applicable),
            duty_pct (float, where applicable), output_on (bool), load (str).
        """
        bswv_response = self._query("C1:BSWV?").strip()
        outp_response = self._query("C1:OUTP?").strip()
        return {
            **self._parse_bswv(bswv_response),
            **self._parse_outp(outp_response),
        }

    @staticmethod
    def _parse_bswv(response: str) -> dict:
        """Parse a `C1:BSWV WVTP,SINE,FRQ,1000000HZ,AMP,1V,...` response."""
        result: dict = {}
        # Strip leading 'C1:BSWV ' prefix
        if response.startswith("C1:BSWV"):
            response = response[len("C1:BSWV"):].lstrip()
        tokens = response.split(",")
        # tokens come in KEY,VALUE,KEY,VALUE,... pairs
        i = 0
        while i + 1 < len(tokens):
            key = tokens[i].strip().upper()
            val = tokens[i + 1].strip()
            i += 2
            if key == "WVTP":
                result["function"] = val.upper()
            elif key == "FRQ":
                result["freq_hz"] = SDS2000X._strip_unit(val, "HZ")
            elif key == "AMP":
                result["amplitude_vpp"] = SDS2000X._strip_unit(val, "V")
            elif key == "OFST":
                result["offset_v"] = SDS2000X._strip_unit(val, "V")
            elif key == "PHSE":
                result["phase_deg"] = float(val) if val else 0.0
            elif key == "DUTY":
                result["duty_pct"] = float(val) if val else 0.0
            elif key == "SYM":
                result["symmetry_pct"] = float(val) if val else 0.0
        return result

    @staticmethod
    def _parse_outp(response: str) -> dict:
        """Parse a `C1:OUTP ON,LOAD,50,PLRT,NOR` response."""
        result = {"output_on": False, "load": "HZ"}
        if response.startswith("C1:OUTP"):
            response = response[len("C1:OUTP"):].lstrip()
        tokens = response.split(",")
        if tokens:
            result["output_on"] = tokens[0].strip().upper() == "ON"
        # Walk remaining KEY,VALUE pairs
        i = 1
        while i + 1 < len(tokens):
            key = tokens[i].strip().upper()
            val = tokens[i + 1].strip()
            i += 2
            if key == "LOAD":
                result["load"] = val.upper()
        return result

    @staticmethod
    def _strip_unit(value: str, unit_suffix: str) -> float:
        """Convert e.g. '1000000HZ' or '1.000000E+06HZ' to float Hz."""
        v = value.strip()
        if v.upper().endswith(unit_suffix):
            v = v[: -len(unit_suffix)]
        return float(v)

    # ------------------------------------------------------------------
    # MSO / Digital channels [Option — requires MSO hardware probe pod]
    # ------------------------------------------------------------------
    # The digital subsystem is a licensed option on the SDS2000X Plus.
    # It requires the physical MSO probe pod to be connected.
    #
    # Channels: D0–D15 in two pods — D0–D7 (pod 1), D8–D15 (pod 2).
    # Thresholds are per-pod.  Each channel can be individually enabled.
    #
    # Waveform data format (from Siglent EN11F programming guide):
    #   :WAVeform:SOURce D<n>  then  :WAVeform:DATA?
    #   Returns packed bits: 1 bit per sample, LSB of each byte = first
    #   (earliest) sample.  e.g. 2500 samples → 313 bytes (⌈2500/8⌉).
    #
    # NOTE: This code is derived from official Siglent SCPI documentation
    # and has NOT been tested with physical MSO hardware.

    def digital_enable(self) -> None:
        """Enable the MSO digital channel display."""
        self._cmd(":DIGital ON")

    def digital_disable(self) -> None:
        """Disable the MSO digital channel display."""
        self._cmd(":DIGital OFF")

    def is_digital_enabled(self) -> bool:
        """Return True if the MSO digital display is ON."""
        return self._query(":DIGital?").strip().upper() in ("ON", "1")

    def digital_channel_enable(self, channel: int) -> None:
        """Enable digital channel n (0–15)."""
        self._cmd(f":DIGital:D{channel} ON")

    def digital_channel_disable(self, channel: int) -> None:
        """Disable digital channel n (0–15)."""
        self._cmd(f":DIGital:D{channel} OFF")

    def is_digital_channel_enabled(self, channel: int) -> bool:
        """Return True if digital channel n (0–15) is enabled."""
        return self._query(f":DIGital:D{channel}?").strip().upper() in ("ON", "1")

    def set_digital_threshold(
        self, pod: int, threshold: "str | float" = "TTL"
    ) -> None:
        """
        Set the logic threshold for a digital pod.

        Args:
            pod:       1 = D0–D7, 2 = D8–D15.
            threshold: 'TTL', 'CMOS', 'LVCMOS33', 'LVCMOS25', or a
                       float voltage in volts for a custom level (±10 V).
                       Custom uses Siglent syntax: CUSTom.<value>
        """
        if isinstance(threshold, (int, float)):
            self._cmd(f":DIGital:THReshold{pod} CUSTom.{threshold:.3f}")
        else:
            self._cmd(f":DIGital:THReshold{pod} {str(threshold).upper()}")

    def get_digital_threshold(self, pod: int) -> str:
        """Return the current threshold setting string for pod 1 or 2."""
        return self._query(f":DIGital:THReshold{pod}?").strip()

    def get_digital_sample_rate(self) -> float:
        """Return the digital acquisition sample rate in Hz."""
        return float(self._query(":DIGital:SRATe?").strip())

    def get_digital_point_count(self) -> int:
        """Return the number of samples in the current digital acquisition."""
        return int(float(self._query(":DIGital:POINts?").strip()))

    def set_digital_label(self, channel: int, label: str) -> None:
        """Set the on-screen label for digital channel n (0–15, max 7 chars)."""
        self._cmd(f":DIGital:LABel{channel} {label[:7]}")

    def capture_digital(self, channel: int) -> tuple[np.ndarray, float]:
        """
        Read one digital channel from the current acquisition.

        Does NOT trigger a new sweep — reads whatever data the scope
        currently holds.  Call after stop() or after capture_audio()
        has frozen the acquisition.

        Args:
            channel: Digital channel number, 0–15.

        Returns:
            (samples, sample_rate_hz):
                samples        — numpy bool array, True = logic HIGH,
                                 one element per sample point
                sample_rate_hz — sample rate from WAVEDESC preamble (Hz)

        Raises:
            RuntimeError: if data is empty.  Check that the MSO option
                          is installed, the digital pod is connected,
                          and the channel is enabled.
        """
        self._cmd(f":WAVeform:SOURce D{channel}")
        self._cmd(":WAVeform:POINt MAX")

        pre = self._read_binary_block(":WAVeform:PREamble?")
        horiz_interval, _vgain, _voffset = self._parse_wavedesc(pre)
        sample_rate_hz = 1.0 / horiz_interval if horiz_interval > 0 else 0.0

        raw = self._read_binary_block(":WAVeform:DATA?")
        if not raw:
            raise RuntimeError(
                f"Digital waveform D{channel} returned no data — verify the "
                f"MSO option is installed, the digital pod is connected, and "
                f"D{channel} is enabled (:DIGital:D{channel} ON)."
            )

        buf     = np.frombuffer(raw, dtype=np.uint8)
        samples = np.unpackbits(buf, bitorder="little").astype(bool)

        # Trim trailing zero-padding: packed bits pads the last byte to 8
        # if the sample count is not a multiple of 8.
        n_pts = self.get_digital_point_count()
        if 0 < n_pts <= len(samples):
            samples = samples[:n_pts]

        return samples, sample_rate_hz

    def capture_all_digital(
        self,
        channels: "list[int] | None" = None,
    ) -> tuple[dict[int, np.ndarray], float]:
        """
        Read multiple digital channels from the current acquisition.

        Reads each requested channel sequentially.  The scope must remain
        stopped for the duration (no new trigger should occur between reads
        or the traces will be inconsistent).

        Args:
            channels: Channel numbers to read (0–15).  None = all 16.
                      Disabled or unavailable channels are silently skipped.

        Returns:
            (traces, sample_rate_hz):
                traces         — dict mapping channel number → bool numpy array
                sample_rate_hz — sample rate (same for all channels)

        Example:
            scope.stop()
            traces, sr = scope.capture_all_digital([0, 1, 2, 3])
            clk  = traces[0]   # D0
            data = traces[1]   # D1
        """
        if channels is None:
            channels = list(range(16))

        traces: dict[int, np.ndarray] = {}
        sample_rate_hz = 0.0

        # Query point count once; it's the same for all channels.
        n_pts = self.get_digital_point_count()

        for ch in channels:
            self._cmd(f":WAVeform:SOURce D{ch}")
            self._cmd(":WAVeform:POINt MAX")

            if not sample_rate_hz:
                pre = self._read_binary_block(":WAVeform:PREamble?")
                hint, _vg, _vo = self._parse_wavedesc(pre)
                sample_rate_hz = 1.0 / hint if hint > 0 else 0.0

            raw = self._read_binary_block(":WAVeform:DATA?")
            if not raw:
                continue    # channel disabled or MSO option not available

            buf     = np.frombuffer(raw, dtype=np.uint8)
            samples = np.unpackbits(buf, bitorder="little").astype(bool)
            if 0 < n_pts <= len(samples):
                samples = samples[:n_pts]
            traces[ch] = samples

        return traces, sample_rate_hz

    def enable_digital_channels(self, channels: "list[int]") -> None:
        """Enable a list of digital channels (0–15) in a single call."""
        for ch in channels:
            self._cmd(f":DIGital:D{ch} ON")

    def disable_digital_channels(self, channels: "list[int]") -> None:
        """Disable a list of digital channels (0–15) in a single call."""
        for ch in channels:
            self._cmd(f":DIGital:D{ch} OFF")

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

    # V/div steps for autorange selection (full Siglent 1-2-5 sequence).
    # SDS2000X Plus firmware 5.4.x intermittently returns display-buffer data
    # at 2 GSps for any of these; the bug is state-dependent (clears on retry).
    # Retry logic in capture_audio handles this transparently.
    _VDIV_STEPS = [0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0]

    # Probe VDIV for _autorange_vdiv.  0.1 V/div is a working step, gives
    # vgain = 10 mV/cnt, and handles signals from ~1 mVpk to ~1.27 Vpk.
    _AUTORANGE_PROBE_VDIV = 0.1

    def _autorange_vdiv(self, channel: int) -> float:
        """
        Find a V/div appropriate for the signal on the channel.

        Captures a short probe waveform at _AUTORANGE_PROBE_VDIV (0.1 V/div),
        measures the 99th-percentile peak directly from the ADC counts (avoids
        PAVA, which is unreliable at extreme V/div ratios), then rounds up to
        the nearest working step in _VDIV_STEPS so the peak fills ≤ 4 divisions.

        Fallback (probe fails or signal not detected): return AUDIO_VDIV_DEFAULT.

        Does NOT leave the scope running — caller is responsible for state.
        """
        ch = f"C{channel}"
        self._cmd(f"{ch}:CPL A1M")
        self._cmd(f"{ch}:VDIV {self._AUTORANGE_PROBE_VDIV:.4f}V")
        self._cmd("TDIV 0.005000S")   # fast probe: 50 ms window, 0.4 s total wait
        self._cmd("TRMD AUTO")
        self.run()
        time.sleep(0.4)
        self.stop()
        time.sleep(0.1)
        self._cmd(f":WAVeform:SOURce {ch}")
        self._cmd(":WAVeform:FORMat BYTE")
        self._cmd(":WAVeform:POINt MAX")
        try:
            pre = self._read_binary_block(":WAVeform:PREamble?")
            horiz_interval, vgain, voffset = self._parse_wavedesc(pre)
            raw = self._read_binary_block(":WAVeform:DATA?")
        except RuntimeError:
            return AUDIO_VDIV_DEFAULT
        if not raw or len(raw) < 100:
            return AUDIO_VDIV_DEFAULT

        sr = 1.0 / horiz_interval if horiz_interval > 0 else 0.0
        if len(raw) <= 1000 and sr > 500e6:
            return AUDIO_VDIV_DEFAULT   # display-buffer firmware bug

        counts = np.frombuffer(raw, dtype=np.int8)
        peak_count = float(np.percentile(np.abs(counts), 99))
        vpeak = peak_count * abs(vgain)
        if vpeak <= 0:
            return AUDIO_VDIV_DEFAULT
        vdiv_needed = vpeak / 4.0   # signal fills ≤ 4 of the ~5 visible half-divs
        for step in self._VDIV_STEPS:
            if step >= vdiv_needed:
                return step
        return self._VDIV_STEPS[-1]

    def _drain(self) -> None:
        """Discard any bytes sitting in the socket receive buffer."""
        self._sock.settimeout(0.05)
        try:
            while True:
                chunk = self._sock.recv(RECV_BUFSIZE)
                if not chunk:
                    break
        except socket.timeout:
            pass
        finally:
            self._sock.settimeout(RECV_TIMEOUT)

    def _cmd(self, cmd: str) -> None:
        self._sock.sendall((cmd + "\n").encode())
        time.sleep(0.05)

    def _query(self, cmd: str) -> str:
        self._sock.sendall((cmd + "\n").encode())
        time.sleep(0.05)
        try:
            return self._recvall_text().strip()
        except socket.timeout:
            return ""

    def _recvall_text(self) -> str:
        """Read text response terminated by newline."""
        buf = b""
        while True:
            try:
                chunk = self._sock.recv(RECV_BUFSIZE)
                buf += chunk
                if buf.endswith(b"\n"):
                    break
            except socket.timeout:
                break
        return buf.decode(errors="replace")

    # ------------------------------------------------------------------ #
    # Escape hatch — raw SCPI commands                                    #
    # ------------------------------------------------------------------ #

    def write(self, cmd: str) -> None:
        """Send raw SCPI command without expecting a response.

        This is an "escape hatch" for sending commands not yet wrapped by the driver.

        Args:
            cmd: SCPI command string (newline will be appended automatically)

        Example:
            >>> scope.write("TRMD AUTO")  # Set trigger mode to AUTO
            >>> scope.write("BUZZ BEEP")  # Beep the instrument

        Warning:
            Use with caution. Invalid commands may put the instrument in an
            unexpected state. Consult the SDS2000X programming manual for valid
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
            >>> trig = scope.query("TRMD?")  # Query trigger mode
            >>> print(trig)
            'AUTO'

        Warning:
            Use with caution. Invalid queries may hang or return unexpected data.
            Consult the SDS2000X programming manual for valid SCPI queries.
        """
        return self._query(cmd)

    def _read_binary_block(self, cmd: str) -> bytes:
        """
        Send cmd and receive an IEEE 488.2 binary block response.

        Format: [optional_prefix,]#<n><length_digits><data>\\n
        Skips any text prefix before the '#' marker.  This handles the
        SDS2504X Plus firmware wrapping data responses in 'C1:WF DAT2,' etc.
        Works for :WAVeform:PREamble? (346-byte WAVEDESC) and :WAVeform:DATA?.
        """
        self._sock.sendall((cmd + "\n").encode())
        time.sleep(0.1)

        # Scan for '#' byte — skip any prefix text the scope prepends
        prefix_buf = b""
        while True:
            b = self._sock.recv(1)
            if not b:
                raise RuntimeError("Connection closed while waiting for binary block")
            if b == b"#":
                break
            prefix_buf += b
            if len(prefix_buf) > 256:
                raise RuntimeError(
                    f"Binary block '#' not found in first 256 bytes: {prefix_buf!r}"
                )

        # '#' consumed; next byte is the digit count
        n_byte = self._sock.recv(1)
        if not n_byte:
            raise RuntimeError("Connection closed reading block digit count")

        n_digits = int(n_byte)
        len_bytes = b""
        while len(len_bytes) < n_digits:
            len_bytes += self._sock.recv(n_digits - len(len_bytes))
        data_length = int(len_bytes)

        data = b""
        remaining = data_length
        while remaining > 0:
            chunk = self._sock.recv(min(remaining, RECV_BUFSIZE))
            if not chunk:
                break
            data += chunk
            remaining -= len(chunk)

        # Drain any trailing bytes (scope appends a newline after the binary block).
        # Use a short non-blocking drain to handle cases where the newline arrives
        # slightly after the data, without risking reading the next response.
        self._sock.settimeout(0.05)
        try:
            while True:
                chunk = self._sock.recv(RECV_BUFSIZE)
                if not chunk:
                    break
        except socket.timeout:
            pass
        finally:
            self._sock.settimeout(RECV_TIMEOUT)

        return data

    @staticmethod
    def _parse_wavedesc(pre: bytes) -> tuple[float, float, float]:
        """
        Parse the 346-byte Siglent WAVEDESC binary preamble block.

        Key fields (little-endian):
            offset 156: VERTICAL_GAIN   (float32) — volts per ADC count
            offset 160: VERTICAL_OFFSET (float32) — zero-offset voltage
            offset 176: HORIZ_INTERVAL  (float32) — seconds per sample

        Voltage conversion: V = raw_count * VERTICAL_GAIN - VERTICAL_OFFSET
        (raw_count is a signed int8 when :WAVeform:FORMat BYTE is set)

        Returns: (horiz_interval_s, vertical_gain, vertical_offset)
        """
        if len(pre) < 188:
            raise RuntimeError(
                f"WAVEDESC too short: {len(pre)} bytes (expected ≥ 188)"
            )
        vgain   = struct.unpack_from("<f", pre, _WD_VERTICAL_GAIN)[0]
        voffset = struct.unpack_from("<f", pre, _WD_VERTICAL_OFFSET)[0]
        hint    = struct.unpack_from("<f", pre, _WD_HORIZ_INTERVAL)[0]
        return hint, vgain, voffset

    @staticmethod
    def _parse_pava(resp: str) -> float:
        """
        Parse a PAVA response: 'C1:PAVA RMS,1.48E-01V' → 1.48e-1.

        Returns NaN if the response is empty or malformed.
        """
        try:
            val_str = resp.split(",", 1)[1].strip()
            m = re.match(r"([-+]?[\d.]+(?:[eE][-+]?\d+)?)", val_str)
            return float(m.group(1)) if m else float("nan")
        except (IndexError, AttributeError, ValueError):
            return float("nan")
