"""
rf_bench.flipper.flipper — Flipper Zero USB driver for bench automation.

Two protocol modes:
  CLI  — text commands, Flipper echoes output then shows '>: ' prompt.
          Used for Sub-GHz, IR, RFID, NFC (no protobuf RPC definitions exist
          for those subsystems in the flipperzero-protobuf package).
  RPC  — varint-length-prefixed protobuf, protocol-compatible with the
          official flipperzero-protobuf library.
          Used for GPIO and file I/O.

Mode switching:
  CLI → RPC: send 'start_rpc_session\\r', read until '\\n'.
  RPC → CLI: send Main{stop_session=True} protobuf, read until '>: '.

Hardware:
  USB VID=0x0483  PID=0x5740  (CDC ACM)
  Linux: /dev/ttyACM0  Baud: 230400 (ignored by USB CDC, but required by pyserial)

Firmware compatibility:
  Official firmware uses 'subghz rx_carrier' / 'subghz tx_carrier' for
  continuous carrier mode.  Third-party forks (Momentum, RogueMaster,
  Xtreme, Unleashed, etc.) dropped those commands in favour of 'subghz rx'
  / 'subghz tx'.

  The driver detects the firmware fork on connect via the '!' info command
  and routes Sub-GHz commands accordingly.  On fork firmware, rx_carrier
  is emulated via 'subghz rx'; RSSI is available only when a packet is
  decoded (per-packet, not continuous).  tx_carrier is not available on
  fork firmware and raises FlipperError.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, List, Optional, Tuple

import serial
import serial.tools.list_ports
from google.protobuf.internal.encoder import _VarintBytes

from flipperzero_protobuf.flipperzero_protobuf_compiled import (
    application_pb2,
    flipper_pb2,
    gpio_pb2,
    storage_pb2,
)

__all__ = ["FlipperZero", "FlipperError", "FlipperTimeoutError", "FlipperProtocolError"]


class FlipperError(Exception):
    pass


class FlipperTimeoutError(FlipperError):
    pass


class FlipperProtocolError(FlipperError):
    pass


_USB_VID = 0x0483
_USB_PID = 0x5740
_BAUD = 230400
_PROMPT = b">: "

# Firmware forks that replaced rx_carrier/tx_carrier with rx/tx.
# Matched against the 'firmware_origin_fork' field from '!' info output.
_FORK_FIRMWARE = {"Momentum", "RogueMaster", "Xtreme", "Unleashed"}

_GPIO_PINS = ("PC0", "PC1", "PC3", "PB2", "PB3", "PA4", "PA6", "PA7")

_SUBGHZ_PRESETS = {
    "ook270":     "FuriHalSubGhzPresetOok270Async",
    "ook650":     "FuriHalSubGhzPresetOok650Async",
    "2fsk_dev238":"FuriHalSubGhzPreset2FskDev238Async",
    "2fsk_dev476":"FuriHalSubGhzPreset2FskDev476Async",
    "msk":        "FuriHalSubGhzPresetMsk99_97KbAsync",
    "gfsk":       "FuriHalSubGhzPresetGfsk9_99KbAsync",
}

# Temporary directory for bench-generated files on Flipper SD card
_BENCH_DIR = "/ext/bench"


class FlipperZero:
    """
    Flipper Zero USB driver for bench automation.

    Manages a single serial connection that operates in either CLI or RPC
    mode.  Switches automatically when Sub-GHz / IR / RFID / NFC methods
    (CLI) and GPIO / file-I/O methods (RPC) are interleaved.

    Blocking CLI commands (tx_carrier, rx_carrier, rfid emulate, etc.) run
    in a daemon background thread.  Call the matching ``*_stop()`` method to
    terminate them.

    GPIO pins available: PC0, PC1, PC3, PB2, PB3, PA4, PA6, PA7.

    Firmware forks (Momentum, RogueMaster, Xtreme, Unleashed, …) are
    auto-detected on connect via ``firmware_fork``.  Sub-GHz carrier
    commands adapt automatically; see method docstrings for per-fork notes.

    Usage::

        with FlipperZero() as fz:          # auto-detect
            print(fz.firmware_fork)        # e.g. 'Momentum' or 'Official'
            fz.gpio_set_mode("PA4", "output")
            fz.gpio_write("PA4", 1)
            readings = fz.subghz_get_rssi(433_920_000, duration_s=0.5)
    """

    GPIO_PINS: Tuple[str, ...] = _GPIO_PINS

    def __init__(self, port: Optional[str] = None, timeout: float = 5.0) -> None:
        """
        Open connection to a Flipper Zero.

        Args:
            port:    Serial port path (e.g. '/dev/ttyACM0').  Auto-detected
                     by USB VID/PID if None.
            timeout: Default serial read timeout in seconds (used for
                     synchronous CLI commands).

        Raises:
            FlipperError: If no device found (when port is None) or port
                          cannot be opened.
        """
        if port is None:
            port = self.find_device()
            if port is None:
                raise FlipperError("No Flipper Zero found (USB VID=0x0483 PID=0x5740)")

        self._serial = serial.Serial(port, baudrate=_BAUD, timeout=timeout)
        self._serial.flushInput()
        self._serial.flushOutput()
        self._mode = "cli"
        self._command_id = 0
        self._default_timeout = timeout

        # Background thread state for blocking CLI commands
        self._bg_thread: Optional[threading.Thread] = None
        self._bg_stop = threading.Event()

        # Sync to CLI prompt on connect
        self._flush_cli()

        # Detect firmware fork so Sub-GHz commands can be routed correctly.
        self._firmware_fork: str = self._detect_firmware_fork()

    # ------------------------------------------------------------------
    # Class helpers
    # ------------------------------------------------------------------

    @classmethod
    def find_device(cls) -> Optional[str]:
        """
        Scan serial ports for a Flipper Zero by USB VID/PID.

        Returns:
            Port path (e.g. '/dev/ttyACM0'), or None if not found.
        """
        for info in serial.tools.list_ports.comports():
            if info.vid == _USB_VID and info.pid == _USB_PID:
                return info.device
        return None

    def _detect_firmware_fork(self) -> str:
        """Read firmware_origin_fork from the '!' info output."""
        try:
            resp = self._cli_send("!", timeout=5.0)
            for line in resp.splitlines():
                if "firmware_origin_fork" in line:
                    _, _, val = line.partition(":")
                    return val.strip()
        except Exception:
            pass
        return "Official"

    @property
    def firmware_fork(self) -> str:
        """
        Firmware fork name detected at connect time.

        Returns 'Official' for stock Flipper firmware, or the fork name
        (e.g. 'Momentum', 'RogueMaster', 'Xtreme', 'Unleashed') for
        community firmware.  Used internally to route Sub-GHz commands.
        """
        return self._firmware_fork

    @property
    def uses_carrier_commands(self) -> bool:
        """True if this firmware supports 'subghz rx_carrier' / 'subghz tx_carrier'."""
        return self._firmware_fork not in _FORK_FIRMWARE

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "FlipperZero":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        """Stop background operations, return to CLI, close serial port."""
        self._stop_bg()
        try:
            self._ensure_cli()
        except Exception:
            pass
        if self._serial.is_open:
            self._serial.close()

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def identify(self) -> dict:
        """
        Return firmware and hardware info from the Flipper CLI '!' command.

        Returns:
            dict of key/value strings from the info output (e.g.
            {'hw_ver': '14', 'fw_version': '0.90.1', ...}).
        """
        self._ensure_cli()
        resp = self._cli_send("!", timeout=5.0)
        info: dict = {}
        for line in resp.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                info[k.strip()] = v.strip()
        return info

    # ------------------------------------------------------------------
    # Internal — CLI mode
    # ------------------------------------------------------------------

    def _flush_cli(self, timeout: float = 3.0) -> None:
        """Send CR and wait for '>: ' to confirm we are at a CLI prompt."""
        self._serial.write(b"\r")
        deadline = time.monotonic() + timeout
        buf = b""
        while time.monotonic() < deadline:
            chunk = self._serial.read(self._serial.in_waiting or 1)
            buf += chunk
            if _PROMPT in buf:
                return
        # Retry once
        self._serial.write(b"\r")
        self._serial.timeout = 2.0
        self._serial.read_until(_PROMPT)
        self._serial.timeout = self._default_timeout

    def _cli_send(self, cmd: str, timeout: float = 10.0) -> str:
        """
        Send a CLI command and return the response text.

        Waits for the next '>: ' prompt, strips the command echo and prompt.

        Args:
            cmd:     Command string (without trailing CR).
            timeout: Read timeout in seconds.

        Returns:
            Response text with echo and prompt stripped.
        """
        self._serial.timeout = timeout
        self._serial.write((cmd + "\r").encode())
        raw = self._serial.read_until(_PROMPT)
        self._serial.timeout = self._default_timeout
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        # Drop first line if it is the command echo
        if lines and lines[0].strip() == cmd.strip():
            lines = lines[1:]
        # Drop trailing prompt line
        if lines and lines[-1].startswith(">: "):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Internal — RPC mode
    # ------------------------------------------------------------------

    def _ensure_cli(self) -> None:
        """Switch from RPC to CLI mode if necessary."""
        if self._mode == "cli":
            return
        msg = flipper_pb2.Main()
        self._command_id += 1
        msg.command_id = self._command_id
        msg.command_status = flipper_pb2.CommandStatus.Value("OK")
        msg.stop_session.SetInParent()   # stop_session is an empty message in a oneof
        payload = bytearray(_VarintBytes(msg.ByteSize()) + msg.SerializeToString())
        self._serial.write(payload)
        self._serial.timeout = 3.0
        self._serial.read_until(_PROMPT)
        # Drain any extra prompts the device may have sent after the session end
        self._serial.timeout = 0.05
        while self._serial.in_waiting:
            self._serial.read(self._serial.in_waiting)
            import time as _time; _time.sleep(0.01)
        self._serial.timeout = self._default_timeout
        self._mode = "cli"

    def _ensure_rpc(self) -> None:
        """Switch from CLI to RPC mode if necessary."""
        if self._mode == "rpc":
            return
        self._flush_cli()
        self._serial.write(b"start_rpc_session\r")
        self._serial.timeout = 3.0
        self._serial.read_until(b"\n")
        self._serial.timeout = self._default_timeout
        self._mode = "rpc"

    def _rpc_read_varint(self) -> int:
        result = 0
        shift = 0
        while True:
            b = int.from_bytes(self._serial.read(1), "little")
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                return result & 0xFFFFFFFF
            shift += 7
            if shift >= 64:
                raise FlipperProtocolError("Varint too long")

    def _rpc_send(self, cmd_data, cmd_name: str) -> None:
        if self._mode != "rpc":
            raise FlipperProtocolError("Not in RPC mode")
        msg = flipper_pb2.Main()
        self._command_id += 1
        msg.command_id = self._command_id
        msg.command_status = flipper_pb2.CommandStatus.Value("OK")
        getattr(msg, cmd_name).CopyFrom(cmd_data)
        payload = bytearray(_VarintBytes(msg.ByteSize()) + msg.SerializeToString())
        self._serial.write(payload)

    def _rpc_read(self) -> flipper_pb2.Main:
        length = self._rpc_read_varint()
        raw = self._serial.read(length)
        if len(raw) < length:
            raise FlipperProtocolError(
                f"Short read: expected {length} bytes, got {len(raw)}"
            )
        msg = flipper_pb2.Main()
        msg.ParseFromString(raw)
        return msg

    def _rpc_cmd(self, cmd_data, cmd_name: str) -> flipper_pb2.Main:
        """Send an RPC command and return the matching response."""
        self._rpc_send(cmd_data, cmd_name)
        expected_id = self._command_id
        while True:
            resp = self._rpc_read()
            if resp.command_id == expected_id:
                return resp

    # ------------------------------------------------------------------
    # Internal — background thread management
    # ------------------------------------------------------------------

    def _stop_bg(self) -> None:
        """Signal the running background operation to stop and join its thread."""
        if self._bg_thread is None or not self._bg_thread.is_alive():
            self._bg_stop.clear()
            return
        self._bg_stop.set()
        try:
            self._serial.write(b"\r")
        except Exception:
            pass
        self._bg_thread.join(timeout=3.0)
        self._bg_thread = None
        self._bg_stop.clear()

    def _start_bg(self, target: Callable, *args) -> None:
        """Stop any existing background thread, then start a new one."""
        self._stop_bg()
        self._bg_thread = threading.Thread(target=target, args=args, daemon=True)
        self._bg_thread.start()

    # ------------------------------------------------------------------
    # Sub-GHz — CLI mode
    # ------------------------------------------------------------------

    def subghz_tx_carrier(self, freq_hz: int) -> None:
        """
        Transmit a continuous-wave Sub-GHz carrier.

        Runs asynchronously in the background.  Call subghz_stop() to stop.

        The Flipper CC1101 covers 300–348 MHz, 387–464 MHz, and 779–928 MHz.
        Common ISM band frequencies: 315 MHz, 433.92 MHz, 868 MHz, 915 MHz.

        Args:
            freq_hz: Carrier frequency in Hz (e.g. 433_920_000).

        Raises:
            FlipperError: On fork firmware (Momentum, RogueMaster, etc.) that
                          removed the tx_carrier command.
        """
        if not self.uses_carrier_commands:
            raise FlipperError(
                f"subghz tx_carrier is not available on {self._firmware_fork} firmware. "
                "Use subghz_transmit_raw() or subghz_transmit_protocol() instead."
            )
        self._ensure_cli()

        def _worker() -> None:
            self._serial.write(f"subghz tx_carrier {freq_hz}\r".encode())
            buf = b""
            while not self._bg_stop.is_set():
                chunk = self._serial.read(self._serial.in_waiting or 1)
                if chunk:
                    buf += chunk
                    if _PROMPT in buf:
                        break

        self._start_bg(_worker)

    def subghz_rx_carrier(
        self,
        freq_hz: int,
        rssi_callback: Optional[Callable[[float], None]] = None,
    ) -> None:
        """
        Start Sub-GHz receive mode at freq_hz.

        Runs in the background.  RSSI values (dBm) are delivered to
        rssi_callback as they arrive.  Call subghz_stop() to stop.

        On official firmware, uses 'subghz rx_carrier' which streams
        continuous RSSI samples even with no packet activity.

        On fork firmware (Momentum, RogueMaster, Xtreme, Unleashed, …),
        uses 'subghz rx' instead. RSSI is reported only when a packet is
        decoded, so rssi_callback fires per-packet rather than continuously.
        Frequencies with no active transmitters return no readings.

        Args:
            freq_hz:       Frequency in Hz.
            rssi_callback: Called with each RSSI reading (float, dBm).
        """
        self._ensure_cli()
        _rssi_re = re.compile(rb"RSSI:\s*(-?\d+(?:\.\d+)?)")

        if self.uses_carrier_commands:
            cmd = f"subghz rx_carrier {freq_hz}\r".encode()
        else:
            cmd = f"subghz rx {freq_hz} 0\r".encode()

        def _worker() -> None:
            self._serial.write(cmd)
            buf = b""
            while not self._bg_stop.is_set():
                chunk = self._serial.read(self._serial.in_waiting or 1)
                if chunk:
                    buf += chunk
                    if _PROMPT in buf:
                        break
                    if rssi_callback:
                        for m in _rssi_re.finditer(buf):
                            try:
                                rssi_callback(float(m.group(1)))
                            except Exception:
                                pass
                        buf = buf[-256:]  # Keep tail to avoid re-scanning

        self._start_bg(_worker)

    def subghz_stop(self) -> None:
        """Stop the active Sub-GHz TX or RX carrier operation."""
        self._stop_bg()
        self._flush_cli()

    def subghz_get_rssi(self, freq_hz: int, duration_s: float = 0.5) -> List[float]:
        """
        Measure Sub-GHz RSSI at freq_hz for duration_s seconds.

        Starts the receiver, collects readings, stops, and returns the list.

        Args:
            freq_hz:    Frequency in Hz.
            duration_s: Collection duration in seconds.

        Returns:
            List of RSSI readings in dBm.  Empty if none were received.
        """
        readings: List[float] = []
        self.subghz_rx_carrier(freq_hz, rssi_callback=readings.append)
        time.sleep(duration_s)
        self.subghz_stop()
        return readings

    def subghz_transmit_raw(
        self,
        freq_hz: int,
        timings_us: List[int],
        preset: str = "ook650",
        repeat: int = 1,
    ) -> None:
        """
        Transmit a raw OOK/FSK signal using pulse/gap timings.

        Writes a .sub file to /ext/bench/tx.sub on the Flipper SD card,
        then loads it with the Sub-GHz app.

        Args:
            freq_hz:    Carrier frequency in Hz.
            timings_us: List of mark/space durations in µs.  The list is
                        treated as alternating mark/space starting with a
                        mark, regardless of sign.
            preset:     Modulation preset.  One of:
                        'ook270', 'ook650', '2fsk_dev238', '2fsk_dev476',
                        'msk', 'gfsk'.
            repeat:     Number of times to repeat the timing sequence.

        Raises:
            FlipperError: On invalid preset or file-write failure.
        """
        if preset not in _SUBGHZ_PRESETS:
            raise FlipperError(
                f"Unknown preset {preset!r}. Choose from: {', '.join(_SUBGHZ_PRESETS)}"
            )
        raw_vals = [
            abs(int(t)) if i % 2 == 0 else -abs(int(t))
            for i, t in enumerate(timings_us)
        ]
        raw_str = " ".join(str(v) for v in raw_vals)
        lines = [
            "Filetype: Flipper SubGhz RAW File",
            "Version: 1",
            f"Frequency: {freq_hz}",
            f"Preset: {_SUBGHZ_PRESETS[preset]}",
            "Protocol: RAW",
        ]
        for _ in range(repeat):
            lines.append(f"RAW_Data: {raw_str}")
        content = "\n".join(lines) + "\n"
        path = f"{_BENCH_DIR}/tx.sub"
        self._rpc_write_file(path, content.encode())
        self._rpc_load_file(path)

    def subghz_get_raw(self, freq_hz: int, duration_s: float = 2.0) -> str:
        """
        Capture raw Sub-GHz output at freq_hz for duration_s seconds.

        On official firmware, uses 'subghz rx_carrier' (continuous RSSI
        stream).  On fork firmware, uses 'subghz rx' (packet decodes only).

        Args:
            freq_hz:    Frequency in Hz.
            duration_s: Capture duration in seconds.

        Returns:
            Raw CLI output string.
        """
        self._ensure_cli()
        captured: List[bytes] = []

        if self.uses_carrier_commands:
            cmd = f"subghz rx_carrier {freq_hz}\r".encode()
        else:
            cmd = f"subghz rx {freq_hz} 0\r".encode()

        def _worker() -> None:
            self._serial.write(cmd)
            while not self._bg_stop.is_set():
                chunk = self._serial.read(self._serial.in_waiting or 1)
                if chunk:
                    captured.append(chunk)
                    if _PROMPT in b"".join(captured[-5:]):
                        break

        self._start_bg(_worker)
        time.sleep(duration_s)
        self.subghz_stop()
        return b"".join(captured).decode("utf-8", errors="replace")

    def subghz_scan_rssi(
        self,
        freq_start_hz: int,
        freq_end_hz: int,
        step_hz: int,
        dwell_s: float = 0.1,
    ) -> List[Tuple[int, Optional[float]]]:
        """
        Sweep and measure RSSI from freq_start_hz to freq_end_hz.

        Args:
            freq_start_hz: Start frequency in Hz.
            freq_end_hz:   Stop frequency in Hz (inclusive).
            step_hz:       Frequency step in Hz.
            dwell_s:       Dwell time at each step in seconds.

        Returns:
            List of (freq_hz, rssi_dbm) tuples.  rssi_dbm is None if no
            readings were received at that frequency.
        """
        results: List[Tuple[int, Optional[float]]] = []
        freq = freq_start_hz
        while freq <= freq_end_hz:
            readings = self.subghz_get_rssi(freq, duration_s=dwell_s)
            avg = sum(readings) / len(readings) if readings else None
            results.append((freq, avg))
            freq += step_hz
        return results

    def subghz_transmit_protocol(
        self,
        freq_hz: int,
        protocol: str,
        address: int,
        command: int,
        repeat: int = 3,
    ) -> None:
        """
        Transmit a named Sub-GHz protocol (e.g. Princeton, NiceFlor-S).

        Uses the Flipper CLI 'subghz tx' command.  Availability depends on
        firmware version.

        Args:
            freq_hz:  Carrier frequency in Hz.
            protocol: Protocol name (e.g. 'Princeton', 'NiceFlor-S',
                      'Came', 'Keeloq').
            address:  Device address (integer).
            command:  Command code (integer).
            repeat:   Number of transmit repetitions.

        Raises:
            FlipperError: If the CLI command returns an error.
        """
        self._ensure_cli()
        cmd = f"subghz tx {protocol} {freq_hz} {address} {command} {repeat}"
        resp = self._cli_send(cmd, timeout=10.0)
        if "error" in resp.lower() or "failed" in resp.lower():
            raise FlipperError(f"subghz_transmit_protocol failed: {resp}")

    # ------------------------------------------------------------------
    # IR — CLI mode
    # ------------------------------------------------------------------

    def ir_transmit(
        self,
        protocol: str,
        address: int,
        command: int,
        repeat: int = 1,
    ) -> None:
        """
        Transmit an IR command using a named protocol.

        Uses the Flipper CLI 'ir tx' command.

        Args:
            protocol: IR protocol name (e.g. 'NEC', 'RC5', 'RC6',
                      'Samsung32', 'SIRC', 'Kaseikyo').
            address:  Device address (integer).
            command:  Command code (integer).
            repeat:   Number of repetitions (default 1).

        Raises:
            FlipperError: If the CLI returns an error string.
        """
        self._ensure_cli()
        cmd = f"ir tx {protocol} {address} {command}"
        if repeat > 1:
            cmd += f" {repeat}"
        resp = self._cli_send(cmd, timeout=5.0)
        if "error" in resp.lower() or "failed" in resp.lower():
            raise FlipperError(f"ir_transmit failed: {resp}")

    def ir_transmit_raw(
        self,
        timings_us: List[int],
        freq_hz: int = 38_000,
        duty_cycle: float = 0.33,
    ) -> None:
        """
        Transmit a raw IR signal using pulse/gap timings.

        Writes a .ir file to /ext/bench/tx.ir and loads it.

        Args:
            timings_us: Alternating mark/space durations in µs.
                        All values treated as positive (absolute µs).
            freq_hz:    Carrier frequency in Hz (default 38 kHz for NEC/RC5).
            duty_cycle: Modulation duty cycle 0–1 (default 0.33).
        """
        data_str = " ".join(str(abs(int(t))) for t in timings_us)
        content = (
            "Filetype: IR signals file\n"
            "Version: 1\n"
            "#\n"
            "name: bench_raw\n"
            "type: raw\n"
            f"frequency: {freq_hz}\n"
            f"duty_cycle: {duty_cycle:.6f}\n"
            f"data: {data_str}\n"
        )
        path = f"{_BENCH_DIR}/tx.ir"
        self._rpc_write_file(path, content.encode())
        self._rpc_load_file(path)

    def ir_receive(self, timeout_s: float = 10.0) -> Optional[dict]:
        """
        Receive and decode one IR signal.

        Starts 'ir rx' on the Flipper and blocks until a signal is received
        or timeout expires.

        Args:
            timeout_s: Receive timeout in seconds.

        Returns:
            dict with keys 'protocol', 'address', 'command' (integers where
            applicable), or None on timeout.
        """
        self._ensure_cli()
        self._serial.timeout = timeout_s
        self._serial.write(b"ir rx\r")
        raw = self._serial.read_until(_PROMPT).decode("utf-8", errors="replace")
        self._serial.timeout = self._default_timeout
        if not raw.strip():
            return None

        result: dict = {}
        proto_m = re.search(r"protocol[:\s]+(\w+)", raw, re.I)
        addr_m  = re.search(r"address[:\s]+(0x[\da-fA-F]+|\d+)", raw, re.I)
        cmd_m   = re.search(r"command[:\s]+(0x[\da-fA-F]+|\d+)", raw, re.I)
        if proto_m:
            result["protocol"] = proto_m.group(1)
        if addr_m:
            v = addr_m.group(1)
            result["address"] = int(v, 16) if v.startswith("0x") else int(v)
        if cmd_m:
            v = cmd_m.group(1)
            result["command"] = int(v, 16) if v.startswith("0x") else int(v)
        return result if result else None

    # ------------------------------------------------------------------
    # LF RFID — CLI mode
    # ------------------------------------------------------------------

    def lfrfid_read(self, timeout_s: float = 10.0) -> Optional[dict]:
        """
        Read a low-frequency RFID card (125 kHz, e.g. EM4100, HID Prox).

        Blocks until a card is presented or timeout expires.

        Args:
            timeout_s: Read timeout in seconds.

        Returns:
            dict with keys 'key_type' (str) and 'data' (hex string), or
            None on timeout.
        """
        self._ensure_cli()
        self._serial.timeout = timeout_s
        self._serial.write(b"lfrfid read\r")
        raw = self._serial.read_until(_PROMPT).decode("utf-8", errors="replace")
        self._serial.timeout = self._default_timeout
        if not raw.strip():
            return None

        result: dict = {}
        key_m  = re.search(r"key_type[:\s]+(\w+)", raw, re.I)
        data_m = re.search(r"data[:\s]+([0-9A-Fa-f][\s0-9A-Fa-f:]*)", raw, re.I)
        if key_m:
            result["key_type"] = key_m.group(1)
        if data_m:
            result["data"] = data_m.group(1).strip()
        return result if result else None

    def lfrfid_emulate(self, key_type: str, data: str) -> None:
        """
        Emulate a LF RFID card.

        Runs in the background.  Call lfrfid_stop() to stop.

        Args:
            key_type: Card type (e.g. 'EM4100', 'HIDProx', 'Indala26').
            data:     Card data as a hex string (e.g. '0102030405').
        """
        self._ensure_cli()

        def _worker() -> None:
            self._serial.write(f"lfrfid emulate {key_type} {data}\r".encode())
            buf = b""
            while not self._bg_stop.is_set():
                chunk = self._serial.read(self._serial.in_waiting or 1)
                if chunk:
                    buf += chunk
                    if _PROMPT in buf:
                        break

        self._start_bg(_worker)

    def lfrfid_stop(self) -> None:
        """Stop active RFID emulation."""
        self._stop_bg()
        self._flush_cli()

    # ------------------------------------------------------------------
    # NFC — CLI mode
    # ------------------------------------------------------------------

    def nfc_read(self, timeout_s: float = 10.0) -> Optional[dict]:
        """
        Detect and read an NFC tag (ISO 14443-A/B, ISO 15693, etc.).

        Blocks until a tag is found or timeout expires.

        Args:
            timeout_s: Detect timeout in seconds.

        Returns:
            dict with tag fields ('uid', 'type', 'atqa', 'sak', etc.)
            or None on timeout / no tag.
        """
        self._ensure_cli()
        self._serial.timeout = timeout_s
        self._serial.write(b"nfc detect\r")
        raw = self._serial.read_until(_PROMPT).decode("utf-8", errors="replace")
        self._serial.timeout = self._default_timeout
        if not raw.strip():
            return None

        result: dict = {}
        for pattern, key in [
            (r"uid[:\s]+([0-9A-Fa-f][\s0-9A-Fa-f:]*)", "uid"),
            (r"\btype[:\s]+([\w\-]+)",                  "type"),
            (r"atqa[:\s]+([0-9A-Fa-f\s]+)",             "atqa"),
            (r"\bsak[:\s]+([0-9A-Fa-f]+)",              "sak"),
        ]:
            m = re.search(pattern, raw, re.I)
            if m:
                result[key] = m.group(1).strip()
        return result if result else None

    # ------------------------------------------------------------------
    # GPIO — RPC mode
    # ------------------------------------------------------------------

    def gpio_set_mode(self, pin: str, mode: str) -> None:
        """
        Set a GPIO pin direction.

        Args:
            pin:  One of: 'PC0','PC1','PC3','PB2','PB3','PA4','PA6','PA7'.
            mode: 'output' or 'input' (case-insensitive).

        Raises:
            FlipperError: On invalid pin/mode or device error.
        """
        pin = pin.upper()
        mode = mode.upper()
        if pin not in _GPIO_PINS:
            raise FlipperError(f"Invalid GPIO pin: {pin!r}")
        if mode not in ("OUTPUT", "INPUT"):
            raise FlipperError("mode must be 'output' or 'input'")
        self._ensure_rpc()
        cmd = gpio_pb2.SetPinMode()
        cmd.pin = getattr(gpio_pb2, pin)
        cmd.mode = getattr(gpio_pb2, mode)
        resp = self._rpc_cmd(cmd, "gpio_set_pin_mode")
        if resp.command_status != 0:
            raise FlipperError(f"gpio_set_mode failed (status {resp.command_status})")

    def gpio_write(self, pin: str, value: int) -> None:
        """
        Write a digital value to a GPIO output pin.

        Args:
            pin:   One of the valid GPIO pin names.
            value: 0 (low) or 1 (high).  Any non-zero value is treated as 1.

        Raises:
            FlipperError: On invalid pin or device error.
        """
        pin = pin.upper()
        if pin not in _GPIO_PINS:
            raise FlipperError(f"Invalid GPIO pin: {pin!r}")
        self._ensure_rpc()
        cmd = gpio_pb2.WritePin()
        cmd.pin = getattr(gpio_pb2, pin)
        cmd.value = int(bool(value))
        resp = self._rpc_cmd(cmd, "gpio_write_pin")
        if resp.command_status != 0:
            raise FlipperError(f"gpio_write failed (status {resp.command_status})")

    def gpio_read(self, pin: str) -> int:
        """
        Read the digital value of a GPIO pin.

        Args:
            pin: One of the valid GPIO pin names.

        Returns:
            0 or 1.

        Raises:
            FlipperError: On invalid pin or device error.
        """
        pin = pin.upper()
        if pin not in _GPIO_PINS:
            raise FlipperError(f"Invalid GPIO pin: {pin!r}")
        self._ensure_rpc()
        cmd = gpio_pb2.ReadPin()
        cmd.pin = getattr(gpio_pb2, pin)
        resp = self._rpc_cmd(cmd, "gpio_read_pin")
        if resp.command_status != 0:
            raise FlipperError(f"gpio_read failed (status {resp.command_status})")
        return resp.gpio_read_pin_response.value

    def gpio_get_mode(self, pin: str) -> str:
        """
        Query the current direction of a GPIO pin.

        Args:
            pin: One of the valid GPIO pin names.

        Returns:
            'OUTPUT' or 'INPUT'.

        Raises:
            FlipperError: On invalid pin or device error.
        """
        pin = pin.upper()
        if pin not in _GPIO_PINS:
            raise FlipperError(f"Invalid GPIO pin: {pin!r}")
        self._ensure_rpc()
        cmd = gpio_pb2.GetPinMode()
        cmd.pin = getattr(gpio_pb2, pin)
        resp = self._rpc_cmd(cmd, "gpio_get_pin_mode")
        if resp.command_status != 0:
            raise FlipperError(f"gpio_get_mode failed (status {resp.command_status})")
        mode_num = resp.gpio_get_pin_mode_response.mode
        return (
            gpio_pb2.DESCRIPTOR.enum_types_by_name["GpioPinMode"]
            .values_by_number[mode_num]
            .name
        )

    def gpio_set_pull(self, pin: str, pull: str) -> None:
        """
        Set the input pull resistor on a GPIO pin.

        Args:
            pin:  One of the valid GPIO pin names.
            pull: 'none', 'up', or 'down' (case-insensitive).

        Raises:
            FlipperError: On invalid pin/pull or device error.
        """
        pin = pin.upper()
        pull_map = {"none": "NO", "up": "UP", "down": "DOWN"}
        pull_key = pull.lower()
        if pin not in _GPIO_PINS:
            raise FlipperError(f"Invalid GPIO pin: {pin!r}")
        if pull_key not in pull_map:
            raise FlipperError("pull must be 'none', 'up', or 'down'")
        self._ensure_rpc()
        cmd = gpio_pb2.SetInputPull()
        cmd.pin = getattr(gpio_pb2, pin)
        cmd.pull_mode = getattr(gpio_pb2, pull_map[pull_key])
        resp = self._rpc_cmd(cmd, "gpio_set_input_pull")
        if resp.command_status != 0:
            raise FlipperError(f"gpio_set_pull failed (status {resp.command_status})")

    # ------------------------------------------------------------------
    # File I/O — RPC mode (used internally for raw sub-ghz / IR)
    # ------------------------------------------------------------------

    def _rpc_mkdir(self, path: str) -> None:
        """Create a directory on the Flipper SD card (silently ignores errors)."""
        self._ensure_rpc()
        cmd = storage_pb2.MkdirRequest()
        cmd.path = path
        try:
            self._rpc_cmd(cmd, "storage_mkdir_request")
        except Exception:
            pass  # Directory may already exist

    def _rpc_write_file(self, path: str, data: bytes) -> None:
        """
        Write bytes to a file on the Flipper SD card.

        Creates parent directories as needed.  Overwrites existing file.

        Args:
            path: Absolute path on Flipper (e.g. '/ext/bench/tx.sub').
            data: Raw bytes to write.

        Raises:
            FlipperError: On write failure.
        """
        self._ensure_rpc()
        parent = "/".join(path.split("/")[:-1])
        if parent and parent != "/ext":
            self._rpc_mkdir(parent)
        cmd = storage_pb2.WriteRequest()
        cmd.path = path
        cmd.file.data = data
        resp = self._rpc_cmd(cmd, "storage_write_request")
        if resp.command_status != 0:
            raise FlipperError(
                f"File write failed: {path!r} (status {resp.command_status})"
            )

    def _rpc_load_file(self, path: str) -> None:
        """
        Load a file using the appropriate Flipper app via RPC.

        The correct app is selected based on the file extension:
        .sub → Sub-GHz app, .ir → IR app.

        Args:
            path: Absolute path on Flipper (e.g. '/ext/bench/tx.sub').
        """
        self._ensure_rpc()
        cmd = application_pb2.AppLoadFileRequest()
        cmd.path = path
        resp = self._rpc_cmd(cmd, "app_load_file_request")
        if resp.command_status != 0:
            raise FlipperError(
                f"app_load_file failed: {path!r} (status {resp.command_status})"
            )
