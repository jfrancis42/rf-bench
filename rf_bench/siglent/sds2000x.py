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
    # Built-in AWG (arbitrary waveform generator)
    # ------------------------------------------------------------------
    # SDS2000X Plus has a licensed 25 MHz AWG on a dedicated "Gen Out" BNC.
    # SCPI prefix: AWG: (not channel-prefixed — single-channel AWG output).

    def set_awg_sine(self, freq_hz: float, amplitude_vpp: float,
                     offset_v: float = 0.0, phase_deg: float = 0.0) -> None:
        """
        Configure the AWG for sine wave output and enable the output.

        Args:
            freq_hz:       Frequency in Hz (1 mHz – 25 MHz on SDS2504X Plus)
            amplitude_vpp: Peak-to-peak amplitude in V (0.002–6 V into high impedance)
            offset_v:      DC offset in V (default 0)
            phase_deg:     Phase offset in degrees (default 0)
        """
        self._cmd(f":AWG:FUNCtion SINE")
        self._cmd(f":AWG:FREQuency {freq_hz:.6f}")
        self._cmd(f":AWG:AMPLitude {amplitude_vpp:.4f}")
        self._cmd(f":AWG:OFFSet {offset_v:.4f}")
        self._cmd(f":AWG:PHASe {phase_deg:.3f}")
        self._cmd(":AWG:OUTPut ON")
        time.sleep(0.1)

    def set_awg_square(self, freq_hz: float, amplitude_vpp: float,
                       duty_pct: float = 50.0, offset_v: float = 0.0) -> None:
        """
        Configure the AWG for square wave output and enable the output.

        Args:
            freq_hz:       Frequency in Hz
            amplitude_vpp: Peak-to-peak amplitude in V
            duty_pct:      Duty cycle in percent (1–99, default 50)
            offset_v:      DC offset in V (default 0)
        """
        self._cmd(f":AWG:FUNCtion SQUARE")
        self._cmd(f":AWG:FREQuency {freq_hz:.6f}")
        self._cmd(f":AWG:AMPLitude {amplitude_vpp:.4f}")
        self._cmd(f":AWG:DUTyCycle {duty_pct:.2f}")
        self._cmd(f":AWG:OFFSet {offset_v:.4f}")
        self._cmd(":AWG:OUTPut ON")
        time.sleep(0.1)

    def set_awg_ramp(self, freq_hz: float, amplitude_vpp: float,
                     symmetry_pct: float = 100.0, offset_v: float = 0.0) -> None:
        """
        Configure the AWG for ramp (sawtooth) wave output and enable the output.

        Args:
            freq_hz:       Frequency in Hz
            amplitude_vpp: Peak-to-peak amplitude in V
            symmetry_pct:  Ramp symmetry — 100% = sawtooth, 50% = triangle (default 100)
            offset_v:      DC offset in V (default 0)
        """
        self._cmd(f":AWG:FUNCtion RAMP")
        self._cmd(f":AWG:FREQuency {freq_hz:.6f}")
        self._cmd(f":AWG:AMPLitude {amplitude_vpp:.4f}")
        self._cmd(f":AWG:SYMMetry {symmetry_pct:.2f}")
        self._cmd(f":AWG:OFFSet {offset_v:.4f}")
        self._cmd(":AWG:OUTPut ON")
        time.sleep(0.1)

    def set_awg_dc(self, offset_v: float) -> None:
        """Output a DC voltage from the AWG.

        Args:
            offset_v: DC level in V (within the AWG's offset range).
        """
        self._cmd(":AWG:FUNCtion DC")
        self._cmd(f":AWG:OFFSet {offset_v:.4f}")
        self._cmd(":AWG:OUTPut ON")
        time.sleep(0.1)

    def awg_output_on(self) -> None:
        """Enable the AWG output without changing the waveform configuration."""
        self._cmd(":AWG:OUTPut ON")

    def awg_output_off(self) -> None:
        """Disable the AWG output."""
        self._cmd(":AWG:OUTPut OFF")

    def get_awg_state(self) -> dict:
        """
        Query the current AWG configuration.

        Returns:
            dict with keys: function (str), freq_hz (float), amplitude_vpp (float),
            offset_v (float), output_on (bool).
        """
        func   = self._query(":AWG:FUNCtion?").strip()
        freq   = float(self._query(":AWG:FREQuency?").strip())
        amp    = float(self._query(":AWG:AMPLitude?").strip())
        offset = float(self._query(":AWG:OFFSet?").strip())
        outp   = self._query(":AWG:OUTPut?").strip().upper()
        return {
            "function":      func,
            "freq_hz":       freq,
            "amplitude_vpp": amp,
            "offset_v":      offset,
            "output_on":     outp in ("ON", "1"),
        }

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
