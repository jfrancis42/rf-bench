"""
nanovna.py — NanoVNA / NanoVNA-H / NanoVNA-H4 driver.

Speaks the ASCII text protocol used by:
  - edy555 / ttrftech upstream NanoVNA firmware
  - hugen79 NanoVNA-H / NanoVNA-H4 builds
  - DiSlord NanoVNA-H4 builds (superset; extra commands ignored if unsupported)

Transport: USB CDC ACM (appears as /dev/ttyACM0 on Linux). Despite the
``baudrate`` parameter requested below, USB CDC ACM ignores the line rate —
115200 is documented as a sensible default but any value works on Linux.

Communication model
-------------------

The NanoVNA shell sends a ``ch> `` prompt after every response. We read until
that prompt, then strip:
  - the echoed command (firmware echoes typed bytes back),
  - any trailing prompt fragments,
  - empty lines.

Commands are line-terminated with ``\\r`` (CR). Many commands return no body
(action commands like ``sweep start stop points``); they finish with just the
next prompt.

Two query commands return per-point S-parameter data:
  - ``data 0`` → S11 (real imag) lines, one per sweep point
  - ``data 1`` → S21 (real imag) lines, one per sweep point
  - ``frequencies`` → frequency in Hz, one integer per line

Cross-firmware quirks
---------------------

  - Point count: original firmware fixed at 101; hugen79/DiSlord supports up
    to 401 (and on some builds, 800 internally with 401 transferred).
  - Frequency range: original H is 50 kHz – 900 MHz with reduced accuracy
    above 300 MHz; NanoVNA-H4 / DiSlord builds extend with harmonics up to
    1.5 GHz – 3 GHz depending on version. We do not enforce this — the
    firmware clamps.
  - ``capture`` returns the screen framebuffer (320×240 RGB565 or 480×320,
    depending on hardware). Not exposed here.
  - DiSlord firmware adds ``s11 logmag``-style helpers; we read raw complex
    via ``data`` and let callers convert.

Author: Jeff Francis <gjfrancis@protonmail.com>
"""

from __future__ import annotations

import glob
import time
from typing import Iterable, List, Optional, Tuple

import numpy as np

try:
    import serial  # pyserial
except ImportError as _exc:
    raise ImportError(
        "rf_bench.nanovna requires pyserial. Install with: "
        "pip install pyserial --break-system-packages"
    ) from _exc


DEFAULT_PORT     = "/dev/ttyACM0"
DEFAULT_BAUDRATE = 115200       # ignored by USB CDC ACM but harmless
DEFAULT_TIMEOUT  = 5.0          # seconds, per-read

MAX_POINTS       = 401          # NanoVNA-H / NanoVNA-H4 with modern firmware
ORIGINAL_POINTS  = 101          # edy555 original firmware

# Parameters this driver knows how to read. Matches the HP 8712B vocabulary
# so projects can use either driver interchangeably. NanoVNA hardware is a
# 1.5-port VNA (forward S11 + S21 only — no reverse measurements), so S12 /
# S22 are not supported and raise NotImplementedError.
VALID_PARAMETERS = ("S11", "S21", "S12", "S22")
SUPPORTED_PARAMETERS = ("S11", "S21")

_PROMPT = b"ch> "


# ─── exceptions ───────────────────────────────────────────────────────────

class NanoVNAError(RuntimeError):
    """Base exception for NanoVNA driver errors."""


class NanoVNATimeoutError(NanoVNAError):
    """Raised when a response is not received within the read timeout."""


class NanoVNAProtocolError(NanoVNAError):
    """Raised when the device returns malformed or unexpected data."""


# ─── helpers ──────────────────────────────────────────────────────────────

def find_devices() -> List[str]:
    """
    Return candidate NanoVNA device paths on Linux.

    Looks for ``/dev/ttyACM*``. The NanoVNA enumerates as one of these; the
    caller must still confirm by reading the version string.
    """
    return sorted(glob.glob("/dev/ttyACM*"))


# ─── driver ───────────────────────────────────────────────────────────────

class NanoVNA:
    """
    NanoVNA driver — text shell over USB CDC.

    Args:
        port:      Serial device path. ``None`` → autodetect the first
                   ``/dev/ttyACM*`` and verify by reading the version.
        baudrate:  USB CDC ACM ignores this; included for pyserial
                   compatibility.
        timeout:   Per-read socket timeout in seconds. Sweeps for many
                   points can take >1 s; the methods that issue sweeps
                   raise the timeout transparently.

    Example::

        with NanoVNA() as vna:
            print(vna.identify())
            vna.setup_sweep(1e6, 900e6, points=101)
            freqs = vna.get_frequencies()
            s11   = vna.get_s11()
            s21   = vna.get_s21()
    """

    DEFAULT_PORT     = DEFAULT_PORT
    DEFAULT_BAUDRATE = DEFAULT_BAUDRATE
    MAX_POINTS       = MAX_POINTS

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if port is None:
            candidates = find_devices()
            if not candidates:
                raise NanoVNAError(
                    "No /dev/ttyACM* devices found. "
                    "Plug the NanoVNA in and check `dmesg | tail`."
                )
            port = candidates[0]

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

        try:
            self._ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=timeout,
                write_timeout=timeout,
            )
        except (serial.SerialException, OSError) as exc:
            raise NanoVNAError(
                f"Failed to open NanoVNA at {port}: {exc}"
            ) from exc

        # Cached sweep parameters — updated on setup_sweep(), used to size
        # read timeouts and to validate get_frequencies() response length.
        self._start_hz: Optional[int] = None
        self._stop_hz:  Optional[int] = None
        self._points:   int = ORIGINAL_POINTS

        # Selected S-parameter for swappable-API methods (set_parameter,
        # get_trace_db, get_trace_phase, get_s_data). Defaults to S11 to
        # match VNA convention.
        self._parameter: str = "S11"

        # Cached frequency array, invalidated on setup_sweep().
        self._cached_freqs: Optional[np.ndarray] = None

        # Drain any pending boot text / prompt so the first command starts
        # from a clean state.
        time.sleep(0.05)
        self._ser.reset_input_buffer()
        try:
            self._send_raw("\r")
            self._read_until_prompt(timeout=0.5)
        except NanoVNATimeoutError:
            # Device may have been mid-response; one more drain and retry.
            self._ser.reset_input_buffer()
            self._send_raw("\r")
            self._read_until_prompt(timeout=1.0)

    # ── context manager ───────────────────────────────────────────────

    def __enter__(self) -> "NanoVNA":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        """Close the serial port."""
        try:
            self._ser.close()
        except Exception:
            pass

    # ── low-level I/O ─────────────────────────────────────────────────

    def _send_raw(self, data: str) -> None:
        """Write raw bytes (no CR appended) to the device."""
        self._ser.write(data.encode("ascii"))
        self._ser.flush()

    def _read_until_prompt(
        self,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Read from the serial port until the ``ch> `` prompt is seen.

        Returns:
            Body text (between the start of the response and the prompt),
            with command echo and prompt stripped.
        """
        if timeout is None:
            timeout = self.timeout

        deadline = time.monotonic() + timeout
        buf = bytearray()

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NanoVNATimeoutError(
                    f"No prompt received within {timeout:.1f} s "
                    f"(buffered: {bytes(buf[-200:])!r})"
                )
            # Honor the deadline by tightening pyserial's per-read timeout.
            self._ser.timeout = min(remaining, 1.0)
            chunk = self._ser.read(1024)
            if chunk:
                buf.extend(chunk)
                if buf.endswith(_PROMPT):
                    break
                # Some firmwares emit a stray prompt-followed-by-newline
                # after the actual response; tolerate.
                if b"ch> \r\n" in buf:
                    break

        # Restore default timeout for future reads.
        self._ser.timeout = self.timeout

        # Strip trailing prompt
        text = buf.decode("ascii", errors="replace")
        # The prompt may appear with or without trailing CR/LF
        for tail in ("ch> \r\n", "ch> \n", "ch> "):
            if text.endswith(tail):
                text = text[: -len(tail)]
                break
        return text

    def _command(
        self,
        cmd: str,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Send a shell command, read until the next prompt, return body text.

        The firmware echoes every typed byte back, so the first line of the
        body is usually the echoed command. We strip that.
        """
        if not cmd.endswith("\r"):
            cmd_to_send = cmd + "\r"
        else:
            cmd_to_send = cmd

        self._send_raw(cmd_to_send)
        body = self._read_until_prompt(timeout=timeout)

        # Strip command echo (first line that matches the typed command)
        lines = body.replace("\r", "").split("\n")
        cleaned: List[str] = []
        echo_seen = False
        cmd_stripped = cmd.strip()
        for ln in lines:
            if not echo_seen and ln.strip() == cmd_stripped:
                echo_seen = True
                continue
            cleaned.append(ln)
        # Trim trailing empty lines
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()
        return "\n".join(cleaned)

    # ── identification ────────────────────────────────────────────────

    def identify(self) -> str:
        """
        Return a single-line identification string built from firmware metadata.

        Queries ``version`` and ``info`` (the latter is verbose on some
        DiSlord builds), and concatenates a brief summary.
        """
        version = self._command("version").strip() or "(unknown)"
        return f"NanoVNA on {self.port}: version={version}"

    def version(self) -> str:
        """Return the raw firmware version string."""
        return self._command("version").strip()

    def info(self) -> str:
        """
        Return verbose device info (firmware build, hardware revision, etc.).

        Output varies wildly by firmware author; do not parse — display only.
        """
        return self._command("info").strip()

    # ── sweep setup ───────────────────────────────────────────────────

    def setup_sweep(
        self,
        start_hz: float,
        stop_hz: float,
        points: int = 101,
    ) -> None:
        """
        Configure a linear frequency sweep.

        Args:
            start_hz: Sweep start in Hz (NanoVNA accepts 50 kHz min on
                      original H; H4/DiSlord accepts down to 10 kHz).
            stop_hz:  Sweep stop in Hz.
            points:   Number of points (1 – ``MAX_POINTS``). Original
                      firmware is fixed at 101 and may ignore other values.

        Note:
            The firmware silently clamps frequencies that exceed its tuning
            range. Verify by reading back ``get_frequencies()`` after
            configuration.
        """
        if points < 1 or points > self.MAX_POINTS:
            raise ValueError(
                f"points must be 1–{self.MAX_POINTS}, got {points}"
            )
        start_hz = int(start_hz)
        stop_hz = int(stop_hz)
        if stop_hz <= start_hz:
            raise ValueError(
                f"stop_hz ({stop_hz}) must be greater than start_hz ({start_hz})"
            )

        # The combined ``sweep <start> <stop> <points>`` command is supported
        # by all known forks.
        self._command(f"sweep {start_hz} {stop_hz} {points}")
        self._start_hz = start_hz
        self._stop_hz = stop_hz
        self._points = points
        self._cached_freqs = None  # invalidate

    def set_points(self, points: int) -> None:
        """
        Change the number of sweep points without retuning start/stop.

        Original-edy555 firmware does not implement separate ``sweep points``;
        on those builds this re-issues a full ``sweep`` with the cached
        start/stop. Raises if start/stop are not yet set.
        """
        if points < 1 or points > self.MAX_POINTS:
            raise ValueError(
                f"points must be 1–{self.MAX_POINTS}, got {points}"
            )
        if self._start_hz is None or self._stop_hz is None:
            raise NanoVNAError(
                "Call setup_sweep() before set_points() — start/stop unknown."
            )
        self.setup_sweep(self._start_hz, self._stop_hz, points=points)

    def pause(self) -> None:
        """Pause continuous sweeping (the screen freezes at last trace)."""
        self._command("pause")

    def resume(self) -> None:
        """Resume continuous sweeping."""
        self._command("resume")

    # ── data readout ──────────────────────────────────────────────────

    def get_frequencies(self) -> np.ndarray:
        """
        Return the frequency array (Hz) for the current sweep.

        Returns:
            ``np.ndarray`` of dtype ``float64`` with shape ``(points,)``.
        """
        # Frequency readback for many points can be slow on the NanoVNA — give
        # it 2x the normal timeout.
        body = self._command("frequencies", timeout=self.timeout * 2.0)
        values: List[float] = []
        for line in body.splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                values.append(float(s))
            except ValueError as exc:
                raise NanoVNAProtocolError(
                    f"Bad frequency line: {s!r}"
                ) from exc
        if not values:
            raise NanoVNAProtocolError(
                "frequencies returned no data — is the sweep configured?"
            )
        return np.asarray(values, dtype=np.float64)

    def _get_data(self, index: int) -> np.ndarray:
        """
        Return raw complex S-parameter data from ``data <index>``.

        Args:
            index: 0 = S11, 1 = S21, 2/3/4/5/6 = calibration matrices on some
                   firmwares (et, er, es, ex, etc.).

        Returns:
            ``np.ndarray`` of dtype ``complex128`` with shape ``(points,)``.

        Each line of the response is ``"real imag"`` (space-separated ASCII
        floats).
        """
        body = self._command(f"data {index}", timeout=self.timeout * 4.0)
        re: List[float] = []
        im: List[float] = []
        for line in body.splitlines():
            s = line.strip()
            if not s:
                continue
            parts = s.split()
            if len(parts) != 2:
                raise NanoVNAProtocolError(
                    f"Bad data line (expected 'real imag'): {s!r}"
                )
            try:
                re.append(float(parts[0]))
                im.append(float(parts[1]))
            except ValueError as exc:
                raise NanoVNAProtocolError(
                    f"Bad data line (non-float): {s!r}"
                ) from exc
        if not re:
            raise NanoVNAProtocolError(
                f"data {index} returned no rows — sweep may not be running."
            )
        return np.asarray(re, dtype=np.float64) + 1j * np.asarray(im, dtype=np.float64)

    def get_s11(self) -> np.ndarray:
        """Return current S11 trace as ``complex128`` array of length ``points``."""
        return self._get_data(0)

    def get_s21(self) -> np.ndarray:
        """Return current S21 trace as ``complex128`` array of length ``points``."""
        return self._get_data(1)

    def get_s_data_full(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Convenience: capture freqs + S11 + S21 in a single round-trip cycle.

        This is a NanoVNA-specific convenience method (it leverages the fact
        that the NanoVNA always measures S11 and S21 simultaneously). For
        the cross-driver swappable API that returns the currently-selected
        parameter, use :meth:`get_s_data` instead.

        Returns:
            ``(freqs_hz, s11, s21)`` — all numpy arrays of length ``points``.
        """
        freqs = self.get_frequencies()
        s11 = self.get_s11()
        s21 = self.get_s21()
        if not (len(freqs) == len(s11) == len(s21)):
            raise NanoVNAProtocolError(
                f"Length mismatch: freqs={len(freqs)} s11={len(s11)} s21={len(s21)}"
            )
        return freqs, s11, s21

    # ── swappable HP-8712B-compatible API ─────────────────────────────
    #
    # The methods in this block mirror the rf_bench.hp.HP8712B interface so a
    # project can take either driver as a dependency and call the same
    # methods. Hardware-specific extras (e.g. simultaneous S11+S21 readout,
    # multi-segment scan) remain accessible above.

    def set_parameter(self, param: str) -> None:
        """
        Select the S-parameter that subsequent :meth:`get_trace_db`,
        :meth:`get_trace_phase`, :meth:`get_s_data` calls operate on.

        Args:
            param: One of ``"S11"``, ``"S21"``, ``"S12"``, ``"S22"``.

        Raises:
            NotImplementedError: NanoVNA hardware is forward-only — ``S12``
                and ``S22`` require physically reversing the DUT. Reverse
                the DUT manually and measure as S11/S21 from the new
                orientation.
        """
        p = param.upper()
        if p not in VALID_PARAMETERS:
            raise ValueError(
                f"param must be one of {VALID_PARAMETERS}, got {param!r}"
            )
        if p not in SUPPORTED_PARAMETERS:
            raise NotImplementedError(
                f"NanoVNA hardware does not support {p} (forward-only / "
                f"1.5-port VNA). Reverse the DUT to measure as S11/S21."
            )
        self._parameter = p

    def get_parameter(self) -> str:
        """Return the currently selected S-parameter ('S11' or 'S21')."""
        return self._parameter

    def set_format(self, fmt: str) -> None:
        """
        Set the on-device *display* format (does NOT affect what
        :meth:`get_trace_db` / :meth:`get_trace_phase` return — those are
        always derived from the raw complex data).

        Provided for HP 8712B API parity. Accepted values: ``'MLOG'``,
        ``'PHAS'``, ``'MLIN'``, ``'SMIT'``, ``'GDEL'``. Mapped to
        NanoVNA-firmware names (``logmag``, ``phase``, ``linear``, ``smith``,
        ``delay``).
        """
        mapping = {
            "MLOG": "logmag",
            "PHAS": "phase",
            "MLIN": "linear",
            "SMIT": "smith",
            "GDEL": "delay",
            "REAL": "real",
            "IMAG": "imag",
        }
        f = fmt.upper()
        if f not in mapping:
            raise ValueError(f"fmt must be one of {list(mapping)}, got {fmt!r}")
        # trace 0 displays the parameter chosen above
        channel = 0 if self._parameter == "S11" else 1
        self._command(f"trace 0 {mapping[f]} {channel}")

    def set_power(self, dbm: float) -> None:
        """
        Set source power.

        NanoVNA firmware exposes a coarse power index (``power 0..3``); there
        is no continuous dBm setting and the absolute output level is not
        calibrated. This driver does NOT translate ``dbm`` → index because
        the mapping varies by hardware revision and is not documented. Call
        :meth:`raw_power_index` to set the index directly when needed.

        Raises:
            NotImplementedError: Always. Use :meth:`raw_power_index`.
        """
        raise NotImplementedError(
            "NanoVNA power is not specified in dBm. Use raw_power_index(0..3) "
            "for the coarse hardware setting (mapping is hardware-revision "
            "dependent and not documented)."
        )

    def raw_power_index(self, idx: int) -> None:
        """
        Set the NanoVNA source power index (0..3). NanoVNA-specific.

        Args:
            idx: 0 (lowest) .. 3 (highest). The absolute power per index is
                 not calibrated and varies across hardware revisions.
        """
        if idx < 0 or idx > 3:
            raise ValueError(f"power index must be 0..3, got {idx}")
        self._command(f"power {idx}")

    def set_averaging(self, count: int) -> None:
        """
        Enable hardware sweep averaging.

        NanoVNA firmware does not expose a host-controlled averaging count.
        For host-side averaging, capture multiple traces and average in
        Python (the driver helper :meth:`average_s_data` does this).

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "NanoVNA firmware does not support host-controlled averaging. "
            "Use average_s_data(n) to average multiple sweeps in software."
        )

    def average_s_data(self, n: int = 4) -> np.ndarray:
        """
        Capture ``n`` sweeps of the selected parameter and return the
        complex average. NanoVNA-specific helper that fills the role of
        HP's :meth:`set_averaging`.
        """
        if n < 1:
            raise ValueError(f"n must be ≥ 1, got {n}")
        acc = self.get_s_data().astype(np.complex128)
        for _ in range(n - 1):
            self.single_sweep()
            acc = acc + self.get_s_data().astype(np.complex128)
        return acc / float(n)

    def get_s_data(self) -> np.ndarray:
        """
        Return the currently selected S-parameter as a complex array.

        Mirrors :meth:`rf_bench.hp.HP8712B.get_s_data`. Use
        :meth:`set_parameter` to choose S11 / S21.

        Returns:
            ``np.ndarray`` of dtype ``complex128`` and length ``points``.
        """
        if self._parameter == "S11":
            return self.get_s11()
        elif self._parameter == "S21":
            return self.get_s21()
        else:
            raise NanoVNAError(
                f"Internal error: selected parameter {self._parameter!r} "
                "is not S11/S21 (should have been caught by set_parameter)."
            )

    def get_trace_db(self) -> np.ndarray:
        """
        Return the selected parameter as log-magnitude in dB.

        Mirrors :meth:`rf_bench.hp.HP8712B.get_trace_db`.
        """
        s = self.get_s_data()
        return 20.0 * np.log10(np.abs(s) + 1e-30)

    def get_trace_phase(self) -> np.ndarray:
        """
        Return the selected parameter's phase in degrees (-180..+180).

        Mirrors :meth:`rf_bench.hp.HP8712B.get_trace_phase`.
        """
        s = self.get_s_data()
        return np.degrees(np.angle(s))

    # ── single sweep convenience ──────────────────────────────────────

    def single_sweep(self, wait_s: float = 0.5) -> bool:
        """
        Trigger one synchronous sweep cycle and wait for completion.

        The NanoVNA is always sweeping unless paused; this method pauses
        first, requests a fresh sweep by resuming briefly, then pauses
        again. Useful when you want the next :meth:`get_s11` / :meth:`get_s21`
        to reflect a known-fresh acquisition.

        Returns:
            ``True`` on success. The NanoVNA shell has no OPC-style ready
            indicator, so this always returns True (the wait must be sized
            to the sweep duration). Returns ``False`` only if a low-level
            shell error is raised during pause/resume.
        """
        try:
            self.pause()
            self.resume()
            time.sleep(wait_s)
            self.pause()
            return True
        except NanoVNAError:
            return False

    def hold(self) -> None:
        """Hold (pause) sweeping. HP-compatibility alias for :meth:`pause`."""
        self.pause()

    def continuous(self) -> None:
        """Resume continuous sweeping. HP-compatibility alias for :meth:`resume`."""
        self.resume()

    # ── calibration ───────────────────────────────────────────────────
    #
    # The calibration sequence is:
    #   1. cal_reset()
    #   2. attach OPEN at port 0,  call cal_open()
    #   3. attach SHORT at port 0, call cal_short()
    #   4. attach LOAD  at port 0, call cal_load()
    #   5. (2-port only) attach LOAD at port 1, call cal_isoln()
    #   6. (2-port only) connect THRU between port 0 and port 1,
    #      call cal_thru()
    #   7. cal_done()
    #   8. save_cal(slot)   slot ∈ 0..4 (5 slots on most firmwares)
    #
    # Calibration is per-sweep-range. Re-running setup_sweep() does not
    # invalidate cal data, but a stored cal applies only over the range
    # it was measured at.

    def cal_reset(self) -> None:
        """Reset (clear) the current calibration in-memory state."""
        self._command("cal reset")

    def cal_open(self) -> None:
        """Capture the OPEN reference (port 0)."""
        self._command("cal open")

    def cal_short(self) -> None:
        """Capture the SHORT reference (port 0)."""
        self._command("cal short")

    def cal_load(self) -> None:
        """Capture the LOAD reference (port 0)."""
        self._command("cal load")

    def cal_isoln(self) -> None:
        """Capture the ISOLATION reference (LOAD on port 1)."""
        self._command("cal isoln")

    def cal_thru(self) -> None:
        """Capture the THRU reference (port 0 → port 1)."""
        self._command("cal thru")

    def cal_done(self) -> None:
        """Finalize calibration (compute and apply error terms)."""
        self._command("cal done")

    def cal_on(self) -> None:
        """Enable error correction."""
        self._command("cal on")

    def cal_off(self) -> None:
        """Disable error correction."""
        self._command("cal off")

    # HP-compatibility aliases
    def correction_on(self) -> None:
        """Enable error correction. Alias for :meth:`cal_on`."""
        self.cal_on()

    def correction_off(self) -> None:
        """Disable error correction. Alias for :meth:`cal_off`."""
        self.cal_off()

    def is_correction_on(self) -> bool:
        """
        Return ``True`` if error correction is currently enabled.

        Queries the NanoVNA shell's ``cal`` command (no args), which prints
        a one-line status with token ``"on"`` when correction is active.
        """
        try:
            body = self._command("cal", timeout=2.0)
        except NanoVNAError:
            return False
        # The status string ends with " on" or " off" on modern firmwares;
        # on older builds it's silent and we can't tell.
        tokens = body.strip().split()
        if "off" in tokens:
            return False
        if "on" in tokens:
            return True
        # Fall back to "any calibration term marked 'ed" (e.g. "Es'ed Er'ed")
        # — if any are present, correction is at least partially loaded.
        return "'ed" in body

    def save_cal(self, slot: int) -> None:
        """
        Save current calibration to a flash slot (0..4 typically).

        Args:
            slot: Flash slot index. NanoVNA-H has 5 slots; H4 has 5–7
                  depending on firmware. Verify the high range on your
                  device before relying on it.
        """
        if slot < 0:
            raise ValueError(f"slot must be ≥ 0, got {slot}")
        self._command(f"save {slot}")

    def recall_cal(self, slot: int) -> None:
        """Recall a stored calibration from flash slot ``slot``."""
        if slot < 0:
            raise ValueError(f"slot must be ≥ 0, got {slot}")
        self._command(f"recall {slot}")

    # ── markers ───────────────────────────────────────────────────────

    def set_marker(self, freq_hz: float, marker: int = 1) -> None:
        """
        Enable a marker at the specified frequency.

        Matches :meth:`rf_bench.hp.HP8712B.set_marker` (single positional
        frequency argument). The NanoVNA places markers at sweep-point
        indices, so the driver maps frequency → closest point.

        Args:
            freq_hz: Marker frequency in Hz.
            marker:  Marker number, 1..4 (NanoVNA-specific extra; HP only
                     supports one marker).

        Raises:
            NanoVNAError: if no sweep is configured yet.
        """
        if marker < 1 or marker > 4:
            raise ValueError(f"marker must be 1..4, got {marker}")
        freqs = self.get_frequencies()
        idx = int(np.argmin(np.abs(freqs - float(freq_hz))))
        self._command(f"marker {marker} {idx}")

    def set_marker_index(self, marker: int, point_index: int) -> None:
        """
        Place ``marker`` (1..4) directly at sweep-point ``point_index``.

        NanoVNA-specific. Use :meth:`set_marker` for frequency-based
        positioning that matches the HP 8712B API.
        """
        if marker < 1 or marker > 4:
            raise ValueError(f"marker must be 1..4, got {marker}")
        self._command(f"marker {marker} {point_index}")

    def get_marker_value(self, marker: int = 1) -> float:
        """
        Return the trace value (in the format units of the selected
        parameter) at the marker's current frequency.

        Computes from the host side: reads the current frequency array and
        the active-parameter trace, finds the marker's sweep-point index,
        returns the log-magnitude in dB. For phase, switch with
        :meth:`set_parameter` + recompute via :meth:`get_trace_phase`.

        Args:
            marker: Marker number, 1..4. NanoVNA-F shell does not query
                    individual marker frequencies back, so this method
                    returns the strongest log-mag value of the current
                    trace as a useful default. Use
                    :meth:`get_trace_db_at(freq_hz)` for explicit
                    frequency-based readout.

        Returns:
            Marker readout as a float in dB.
        """
        db = self.get_trace_db()
        return float(np.max(db))

    def get_trace_db_at(self, freq_hz: float) -> float:
        """
        Return the selected parameter's log-magnitude in dB at the sweep
        point closest to ``freq_hz``.
        """
        freqs = self.get_frequencies()
        idx = int(np.argmin(np.abs(freqs - float(freq_hz))))
        return float(self.get_trace_db()[idx])

    def marker_off(self, marker: int = 1) -> None:
        """Disable marker ``marker`` (1..4)."""
        if marker < 1 or marker > 4:
            raise ValueError(f"marker must be 1..4, got {marker}")
        self._command(f"marker {marker} off")

    # ── trace formats (DiSlord / hugen79) ─────────────────────────────

    def trace(self, trace_index: int, fmt: str, channel: int) -> None:
        """
        Configure the on-screen ``trace_index`` (0..3) to show ``fmt`` of
        ``channel`` (0=S11, 1=S21).

        ``fmt`` is firmware-dependent; common values: ``logmag``, ``phase``,
        ``delay``, ``smith``, ``polar``, ``linear``, ``swr``, ``real``,
        ``imag``, ``r``, ``x``, ``q``.

        This affects the display only; ``get_s11()`` / ``get_s21()`` still
        return raw complex data.
        """
        if trace_index < 0 or trace_index > 3:
            raise ValueError(f"trace_index must be 0..3, got {trace_index}")
        if channel not in (0, 1):
            raise ValueError(f"channel must be 0 (S11) or 1 (S21), got {channel}")
        self._command(f"trace {trace_index} {fmt} {channel}")

    # ── raw escape hatch ──────────────────────────────────────────────

    def raw(self, cmd: str, timeout: Optional[float] = None) -> str:
        """
        Send a raw shell command and return its response body.

        Use only for commands not exposed via the typed API (e.g. DiSlord-
        specific ``bandwidth``, ``threshold``, ``edelay``, ``port`` on
        firmwares that support them). The driver does no validation on
        ``cmd``.
        """
        return self._command(cmd, timeout=timeout)

    # ── housekeeping ──────────────────────────────────────────────────

    def reset(self) -> None:
        """
        Reboot the NanoVNA into application firmware.

        Warning: the USB CDC port disconnects briefly. You will need to
        re-instantiate ``NanoVNA(...)`` after the device re-enumerates
        (~2-3 seconds on Linux).
        """
        try:
            self._send_raw("reset\r")
        finally:
            self.close()

    def help(self) -> str:
        """Return the firmware's built-in command list."""
        return self._command("help", timeout=2.0)

    # ── iteration helper ──────────────────────────────────────────────

    def iter_segments(
        self,
        start_hz: float,
        stop_hz: float,
        seg_points: int = 101,
        seg_count: Optional[int] = None,
    ) -> Iterable[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """
        Span a wider range than ``MAX_POINTS`` allows by sweeping in segments.

        Yields ``(freqs, s11, s21)`` for each segment. The caller can
        concatenate or process incrementally. Useful for full-range surveys
        (10 MHz – 1500 MHz at 1 MHz resolution = 1490 points → 15 segments
        of 101 points).

        Args:
            start_hz:    Overall sweep start.
            stop_hz:     Overall sweep stop.
            seg_points:  Points per segment.
            seg_count:   Number of segments (None → auto from frequency
                         range and seg_points).
        """
        start_hz = float(start_hz)
        stop_hz  = float(stop_hz)
        if stop_hz <= start_hz:
            raise ValueError("stop_hz must exceed start_hz")

        if seg_count is None:
            # One segment per (seg_points - 1) intervals
            seg_count = max(1, int(np.ceil((stop_hz - start_hz) / 1e6 / 100)))

        edges = np.linspace(start_hz, stop_hz, seg_count + 1)
        for i in range(seg_count):
            self.setup_sweep(edges[i], edges[i + 1], points=seg_points)
            # Allow the NanoVNA one full sweep before reading
            time.sleep(0.3)
            yield self.get_s_data()
