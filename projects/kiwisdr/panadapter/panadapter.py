#!/usr/bin/env python3
"""
Panadapter — Live KiwiSDR spectrum display synchronized to IC-7300 VFO.

Reads the IC-7300's current operating frequency via Hamlib rigctld (TCP port 4532),
tunes the KiwiSDR to match (centered on the operating frequency), and displays a
live ASCII waterfall in the terminal.  Updates every --refresh seconds.

The KiwiSDR passband is 5 kHz; use --span to control the displayed frequency range.
The IC-7300 must be on HF (≤30 MHz); a warning is shown above 30 MHz.

Usage:
    python panadapter.py
    python panadapter.py --kiwi-host 10.1.0.5 --span 20000
    python panadapter.py --refresh 0.25 --waterfall-lines 30
    python panadapter.py --record-s 30 --rec-dir /tmp/iq
    python panadapter.py --rigctld-host 192.168.1.10

Output:
    Live ASCII waterfall in terminal; optional IQ files in --rec-dir.
"""

import argparse
import os
import signal
import socket
import struct
import sys
import time
import wave
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from rf_bench.kiwisdr import KiwiSDR, KiwiSDRError, SAMPLE_RATE


# ── Constants ─────────────────────────────────────────────────────────────────

KIWI_MAX_HZ   = 30_000_000
RIGCTLD_RETRIES = 3
RIGCTLD_TIMEOUT = 2.0   # seconds per TCP attempt

# Waterfall characters ordered dark → bright
WATERFALL_CHARS = " ▁▂▃▄▅▆▇█"

# ── ANSI colours ──────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"
WHITE  = "\033[97m"


# ── rigctld client ────────────────────────────────────────────────────────────

def _rigctld_get_freq(host: str, port: int) -> int | None:
    """
    Query rigctld for the current VFO A frequency.

    Protocol: send `\\f\\n`, read response line like `14225000\n`.
    Returns frequency in Hz, or None on error.
    """
    for _ in range(RIGCTLD_RETRIES):
        try:
            with socket.create_connection((host, port), timeout=RIGCTLD_TIMEOUT) as s:
                s.sendall(b"\\f\n")
                data = b""
                while b"\n" not in data:
                    chunk = s.recv(64)
                    if not chunk:
                        break
                    data += chunk
                line = data.decode(errors="replace").strip()
                return int(line)
        except (OSError, ValueError):
            time.sleep(0.1)
    return None


def _rigctld_get_mode(host: str, port: int) -> str:
    """
    Query rigctld for the current mode string (e.g. "USB", "CW", "FM").
    Returns empty string on error.
    """
    try:
        with socket.create_connection((host, port), timeout=RIGCTLD_TIMEOUT) as s:
            s.sendall(b"\\m\n")
            data = b""
            deadline = time.monotonic() + RIGCTLD_TIMEOUT
            while b"\n" not in data and time.monotonic() < deadline:
                chunk = s.recv(64)
                if not chunk:
                    break
                data += chunk
            # Response is two lines: mode and passband width; take first
            line = data.decode(errors="replace").split("\n")[0].strip()
            return line
    except (OSError, ValueError):
        return ""


# ── IQ recording ──────────────────────────────────────────────────────────────

def _save_iq(iq: np.ndarray, freq_hz: int, rec_dir: str) -> str:
    """
    Save complex64 IQ data as a raw binary file (interleaved float32 I, Q).
    Returns the file path written.
    """
    Path(rec_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(rec_dir, f"iq_{freq_hz}Hz_{ts}.f32")
    # Interleave as float32: I0, Q0, I1, Q1, ...
    iq32 = iq.astype(np.complex64)
    interleaved = np.empty(len(iq32) * 2, dtype=np.float32)
    interleaved[0::2] = iq32.real
    interleaved[1::2] = iq32.imag
    interleaved.tofile(fname)
    return fname


# ── Spectrum / waterfall ──────────────────────────────────────────────────────

def _compute_spectrum(iq: np.ndarray, span_hz: int,
                      rbw_hz: float, center_hz: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute power spectrum of IQ block.

    Returns:
        freq_hz  — array of frequency values in Hz (absolute)
        power_db — array of power in dBFS
    """
    n   = len(iq)
    win = np.hanning(n).astype(np.float32)
    fft = np.fft.fftshift(np.fft.fft(iq * win))
    psd = 10.0 * np.log10(
        np.maximum(np.abs(fft) ** 2 / np.sum(win ** 2), 1e-30)
    )
    bin_hz = SAMPLE_RATE / n
    freq   = center_hz + np.arange(-n // 2, n // 2) * bin_hz
    # Trim to span
    half   = span_hz / 2.0
    mask   = (freq >= center_hz - half) & (freq <= center_hz + half)
    return freq[mask], psd[mask]


def _render_waterfall_line(power_db: np.ndarray, cols: int,
                           floor_db: float, ceil_db: float) -> str:
    """
    Map power_db array to a single waterfall line of `cols` characters.
    Each character represents one pixel column.
    """
    # Resample to cols via mean-pooling or interpolation
    if len(power_db) == 0:
        return WATERFALL_CHARS[0] * cols

    x_src = np.linspace(0, len(power_db) - 1, cols)
    resampled = np.interp(x_src, np.arange(len(power_db)), power_db)

    # Normalise to [0, 1]
    span = ceil_db - floor_db
    if span < 1.0:
        span = 1.0
    norm = np.clip((resampled - floor_db) / span, 0.0, 1.0)
    indices = (norm * (len(WATERFALL_CHARS) - 1)).astype(int)
    return "".join(WATERFALL_CHARS[i] for i in indices)


def _waterfall_color(line: str, use_color: bool) -> str:
    """Colorize a waterfall line: bright chars get YELLOW/RED, dim get CYAN."""
    if not use_color:
        return line
    out = []
    for ch in line:
        idx = WATERFALL_CHARS.find(ch)
        if idx < 0:
            out.append(ch)
        elif idx >= len(WATERFALL_CHARS) - 3:
            out.append(f"{YELLOW}{ch}{RESET}")
        elif idx >= len(WATERFALL_CHARS) - 5:
            out.append(f"{CYAN}{ch}{RESET}")
        else:
            out.append(f"{DIM}{ch}{RESET}")
    return "".join(out)


# ── Header / display ──────────────────────────────────────────────────────────

def _terminal_cols() -> int:
    try:
        return os.get_terminal_size().columns - 4
    except OSError:
        return 80


def _print_header(use_color: bool, vfo_hz: int, kiwi_hz: int,
                  mode: str, span_hz: int, refresh: float,
                  above_limit: bool, recording: bool, rec_file: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    if use_color:
        vfo_str   = f"{BOLD}{vfo_hz / 1e3:.3f} kHz{RESET}"
        mode_str  = f"{CYAN}{mode}{RESET}" if mode else ""
        title_str = f"{BOLD}Panadapter{RESET}"
    else:
        vfo_str   = f"{vfo_hz / 1e3:.3f} kHz"
        mode_str  = mode
        title_str = "Panadapter"

    rec_str = ""
    if recording:
        rec_str = f"  {RED if use_color else ''}[REC: {rec_file}]{RESET if use_color else ''}"

    print(f"\n  {title_str}  {ts}  |  VFO: {vfo_str}  {mode_str}  "
          f"|  KiwiSDR: {kiwi_hz / 1e3:.3f} kHz  |  span: {span_hz} Hz  "
          f"|  refresh: {refresh:.2f}s{rec_str}")

    if above_limit:
        warn = f"  {RED if use_color else ''}WARNING: IC-7300 above 30 MHz — KiwiSDR cannot follow.{RESET if use_color else ''}"
        print(warn)


def _print_freq_scale(center_hz: int, span_hz: int, cols: int,
                      use_color: bool) -> None:
    """Print a one-line frequency scale under the waterfall."""
    half = span_hz / 2
    lo   = (center_hz - half) / 1e3
    hi   = (center_hz + half) / 1e3
    mid  = center_hz / 1e3
    n_labels = 5
    labels = []
    for i in range(n_labels):
        frac   = i / (n_labels - 1)
        val_khz = lo + frac * (hi - lo)
        col_pos = int(frac * (cols - 1))
        labels.append((col_pos, f"{val_khz:.2f}"))

    line = [" "] * cols
    for col_pos, lbl in labels:
        start = max(0, col_pos - len(lbl) // 2)
        for j, ch in enumerate(lbl):
            if start + j < cols:
                line[start + j] = ch

    scale_str = "".join(line)
    if use_color:
        print(f"  {DIM}{scale_str}{RESET}")
    else:
        print(f"  {scale_str}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color  = not args.no_color and sys.stdout.isatty()
    cols       = _terminal_cols()
    waterfall: deque[str] = deque(maxlen=args.waterfall_lines)

    # Samples needed for one refresh cycle (at least 1 second for accuracy)
    n_samples  = max(SAMPLE_RATE, int(SAMPLE_RATE * max(args.refresh, 0.1)))

    stop       = False
    recording  = False
    rec_buffer: list[np.ndarray] = []
    rec_start  = 0.0
    rec_file   = ""

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    print(f"\n  Panadapter — IC-7300 + KiwiSDR")
    print(f"  rigctld: {args.rigctld_host}:{args.rigctld_port}")
    print(f"  KiwiSDR: {args.kiwi_host}:{args.kiwi_port}")
    print(f"  span: {args.span} Hz  |  refresh: {args.refresh}s  "
          f"|  RBW: {args.rbw} Hz  |  waterfall: {args.waterfall_lines} lines")
    if args.record_s > 0:
        print(f"  Will record {args.record_s}s of IQ to {args.rec_dir}/")
    print()

    # Connect KiwiSDR
    try:
        kiwi = KiwiSDR(args.kiwi_host, port=args.kiwi_port, password=args.kiwi_password,
                       channel=0, passband_hz=args.span)
    except KiwiSDRError as e:
        print(f"ERROR: KiwiSDR connect failed: {e}")
        sys.exit(1)

    # Waterfall floor/ceil: auto-calibrate on first few frames
    floor_db = -90.0
    ceil_db  = -40.0
    calibrated = False
    last_vfo_hz = 0
    last_rigctld_ok = True

    if args.record_s > 0:
        recording  = True
        rec_start  = time.monotonic()

    try:
        while not stop:
            t0 = time.monotonic()

            # ── Get radio VFO ─────────────────────────────────────────────────
            vfo_hz = _rigctld_get_freq(args.rigctld_host, args.rigctld_port)
            mode   = ""
            if vfo_hz is None:
                if last_rigctld_ok:
                    print(f"  WARNING: rigctld not responding at "
                          f"{args.rigctld_host}:{args.rigctld_port}")
                    last_rigctld_ok = False
                vfo_hz = last_vfo_hz or 14_100_000
            else:
                last_rigctld_ok = True
                last_vfo_hz     = vfo_hz
                mode = _rigctld_get_mode(args.rigctld_host, args.rigctld_port)

            above_limit = vfo_hz > KIWI_MAX_HZ

            # ── Tune KiwiSDR ──────────────────────────────────────────────────
            kiwi_hz = min(vfo_hz, KIWI_MAX_HZ - args.span // 2)
            if not above_limit:
                try:
                    kiwi.set_center_freq(kiwi_hz)
                    kiwi.set_passband(-args.span // 2, args.span // 2)
                    time.sleep(0.03)
                except KiwiSDRError as e:
                    print(f"  [KiwiSDR tune error: {e}]")
                    time.sleep(0.5)
                    continue

            # ── Capture IQ ───────────────────────────────────────────────────
            try:
                iq = kiwi.capture_iq(n_samples)
            except KiwiSDRError as e:
                print(f"  [KiwiSDR capture error: {e}]")
                time.sleep(0.5)
                continue

            # ── Recording ────────────────────────────────────────────────────
            if recording:
                rec_buffer.append(iq)
                elapsed_rec = time.monotonic() - rec_start
                if elapsed_rec >= args.record_s:
                    all_iq = np.concatenate(rec_buffer)
                    try:
                        rec_file = _save_iq(all_iq, kiwi_hz, args.rec_dir)
                    except OSError as e:
                        rec_file = f"ERROR: {e}"
                    recording    = False
                    rec_buffer   = []

            # ── Compute spectrum ─────────────────────────────────────────────
            freq_hz, power_db = _compute_spectrum(iq, args.span, args.rbw, kiwi_hz)

            # Auto-calibrate floor/ceil from first few frames
            if not calibrated and len(waterfall) >= 3:
                all_p  = power_db
                floor_db = float(np.percentile(all_p, 5))  - 5.0
                ceil_db  = float(np.percentile(all_p, 99)) + 3.0
                calibrated = True

            # ── Build waterfall line ─────────────────────────────────────────
            wf_line = _render_waterfall_line(power_db, cols, floor_db, ceil_db)
            waterfall.append(_waterfall_color(wf_line, use_color))

            # ── Render ───────────────────────────────────────────────────────
            if use_color:
                os.system("clear")
            else:
                print("\033[H\033[J", end="")

            _print_header(use_color, vfo_hz, kiwi_hz, mode,
                          args.span, args.refresh, above_limit,
                          recording, rec_file)

            # Power spectrum (single line, current frame)
            spectrum_line = _render_waterfall_line(power_db, cols, floor_db, ceil_db)
            if use_color:
                print(f"\n  {CYAN}{'─' * cols}{RESET}")
                print(f"  {_waterfall_color(spectrum_line, use_color)}")
                print(f"  {CYAN}{'─' * cols}{RESET}")
            else:
                print(f"\n  {'─' * cols}")
                print(f"  {spectrum_line}")
                print(f"  {'─' * cols}")

            # Waterfall history
            for line in waterfall:
                print(f"  {line}")

            _print_freq_scale(kiwi_hz, args.span, cols, use_color)

            # Stats line
            noise_db = float(np.median(power_db)) if len(power_db) > 0 else 0.0
            peak_db  = float(np.max(power_db))    if len(power_db) > 0 else 0.0
            snr_db   = peak_db - noise_db
            print(f"\n  noise: {noise_db:+.1f} dBFS  peak: {peak_db:+.1f} dBFS  "
                  f"S/N: {snr_db:.1f} dB  "
                  f"floor: {floor_db:.0f}  ceil: {ceil_db:.0f}")
            print(f"  Press Ctrl-C to stop.\n")

            # ── Timing ───────────────────────────────────────────────────────
            elapsed = time.monotonic() - t0
            wait    = args.refresh - elapsed
            if wait > 0 and not stop:
                time.sleep(wait)

    except Exception as e:
        print(f"\n  Unhandled error: {e}")
        raise
    finally:
        kiwi.close()
        if rec_buffer:
            all_iq = np.concatenate(rec_buffer)
            try:
                rec_file = _save_iq(all_iq, last_vfo_hz, args.rec_dir)
                print(f"  Saved partial IQ recording: {rec_file}")
            except OSError:
                pass

    print(f"\n  Stopped.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Panadapter — live KiwiSDR spectrum display locked to IC-7300 VFO",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Requires Hamlib rigctld running locally:
  rigctld -m 3073 -r /dev/ttyUSB0 -s 115200

Examples:
  python panadapter.py
  python panadapter.py --span 20000 --refresh 0.25
  python panadapter.py --kiwi-host 10.1.0.5 --waterfall-lines 30
  python panadapter.py --record-s 60 --rec-dir /tmp/iq
  python panadapter.py --rigctld-host 192.168.1.10 --no-color
        """,
    )

    # KiwiSDR
    p.add_argument("--kiwi-host",     default="kiwisdr.local", dest="kiwi_host",
                   help="KiwiSDR hostname or IP (default: kiwisdr.local)")
    p.add_argument("--kiwi-port",     type=int, default=8073, dest="kiwi_port",
                   help="KiwiSDR port (default: 8073)")
    p.add_argument("--kiwi-password", default="", dest="kiwi_password",
                   help="KiwiSDR password (default: empty)")

    # rigctld
    p.add_argument("--rigctld-host", default="localhost", dest="rigctld_host",
                   help="rigctld host (default: localhost)")
    p.add_argument("--rigctld-port", type=int, default=4532, dest="rigctld_port",
                   help="rigctld port (default: 4532)")

    # Display
    p.add_argument("--span",            type=int,   default=10_000,
                   help="Display span in Hz (default: 10000; = KiwiSDR passband)")
    p.add_argument("--refresh",         type=float, default=0.1,
                   help="Display update interval in seconds (default: 0.1)")
    p.add_argument("--waterfall-lines", type=int,   default=20, dest="waterfall_lines",
                   help="Scrolling waterfall history lines (default: 20)")
    p.add_argument("--rbw",             type=float, default=50.0,
                   help="Resolution bandwidth hint in Hz (default: 50)")
    p.add_argument("--no-color",        action="store_true", dest="no_color",
                   help="Disable ANSI colours")

    # Recording
    p.add_argument("--record-s",  type=int,   default=0, dest="record_s",
                   help="Record IQ for this many seconds then stop (default: 0 = disabled)")
    p.add_argument("--rec-dir",   default="recordings", dest="rec_dir",
                   help="Directory for IQ recordings (default: recordings/)")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
