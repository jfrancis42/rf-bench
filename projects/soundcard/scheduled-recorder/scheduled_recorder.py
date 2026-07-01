#!/usr/bin/env python3
"""
scheduled_recorder.py — Scheduled audio recorder with metadata tagging.

Cron-friendly: record audio for a specified duration at a specified time.
Tags output files with metadata (frequency, mode, antenna, etc.).
Can auto-tune a radio via Hamlib rigctld before recording.

Usage:
    # Record 60 seconds immediately
    python scheduled_recorder.py --duration 60

    # Record at a specific time
    python scheduled_recorder.py --duration 300 --at 14:30:00

    # Tune to 7074 kHz USB, record 10 minutes as FLAC
    python scheduled_recorder.py --duration 600 --frequency 7074 \
        --label "FT8-40m" --format flac

    # Test mode (synthetic audio, no hardware)
    python scheduled_recorder.py --duration 5 --test --label "test-run"
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsp_pipeline import TestSignal, add_audio_args, add_test_args


# ── Rigctld interface ────────────────────────────────────────────────────────

RIGCTLD_TIMEOUT = 3.0
RECV_BUFSIZE = 4096


def _rigctld_command(host: str, port: int, cmd: str) -> str:
    """Send a command to rigctld and return the response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(RIGCTLD_TIMEOUT)
    try:
        sock.connect((host, port))
        sock.sendall((cmd + "\n").encode())
        data = b""
        while True:
            try:
                chunk = sock.recv(RECV_BUFSIZE)
                if not chunk:
                    break
                data += chunk
                if data.endswith(b"\n"):
                    break
            except socket.timeout:
                break
        return data.decode().strip()
    finally:
        sock.close()


def tune_radio(freq_khz: float, host: str, port: int) -> float:
    """Tune rigctld-controlled radio to frequency (kHz). Returns actual Hz."""
    freq_hz = int(freq_khz * 1000)
    resp = _rigctld_command(host, port, f"F {freq_hz}")
    if resp and "RPRT" in resp and "-" in resp:
        raise RuntimeError(f"rigctld set_freq failed: {resp}")
    # Verify
    resp = _rigctld_command(host, port, "f")
    try:
        actual_hz = int(resp.split("\n")[0].strip())
    except (ValueError, IndexError):
        actual_hz = freq_hz
    return actual_hz


def get_radio_info(host: str, port: int) -> dict:
    """Query current radio state from rigctld."""
    info = {}
    try:
        resp = _rigctld_command(host, port, "f")
        info["frequency_hz"] = int(resp.split("\n")[0].strip())
    except Exception:
        pass
    try:
        resp = _rigctld_command(host, port, "m")
        lines = resp.split("\n")
        info["mode"] = lines[0].strip()
        if len(lines) > 1:
            info["passband_hz"] = int(lines[1].strip())
    except Exception:
        pass
    return info


# ── Wait-until logic ─────────────────────────────────────────────────────────

def parse_time(time_str: str) -> datetime:
    """Parse --at argument. Accepts HH:MM:SS or ISO datetime."""
    # Try full ISO first
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%H:%M:%S", "%H:%M"):
        try:
            dt = datetime.strptime(time_str, fmt)
            if fmt.startswith("%H"):
                # Time-only: use today's date in local time
                now = datetime.now()
                dt = dt.replace(year=now.year, month=now.month, day=now.day)
                # If the time has already passed today, schedule for tomorrow
                if dt < now:
                    from datetime import timedelta
                    dt += timedelta(days=1)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse time: {time_str!r}. Use HH:MM:SS or YYYY-MM-DDTHH:MM:SS")


def wait_until(target: datetime) -> None:
    """Sleep until the target local time."""
    now = datetime.now()
    delta = (target - now).total_seconds()
    if delta <= 0:
        return
    print(f"Waiting {delta:.1f}s until {target.strftime('%Y-%m-%d %H:%M:%S')}...",
          file=sys.stderr)
    # Sleep in chunks so Ctrl-C is responsive
    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(remaining, 1.0))


# ── Recording ────────────────────────────────────────────────────────────────

def record_audio(
    duration_sec: float,
    samplerate: int,
    blocksize: int,
    channels: int,
    input_device,
) -> np.ndarray:
    """Record audio from the soundcard. Returns float32 array."""
    import sounddevice as sd

    total_samples = int(duration_sec * samplerate)
    print(f"Recording {duration_sec:.1f}s ({total_samples} samples, "
          f"{samplerate} Hz, {channels} ch)...", file=sys.stderr)

    recording = sd.rec(
        total_samples,
        samplerate=samplerate,
        channels=channels,
        dtype="float32",
        device=input_device,
        blocksize=blocksize,
    )
    sd.wait()
    return recording


def generate_test_audio(duration_sec: float, samplerate: int) -> np.ndarray:
    """Generate synthetic test audio for --test mode."""
    ts = TestSignal(samplerate, duration_sec)
    # Mix of signals: tone + noise + CW
    n = int(samplerate * duration_sec)
    t = np.arange(n) / samplerate

    # 800 Hz tone with slow AM (simulates SSB voice-like envelope)
    tone = 0.3 * np.sin(2 * np.pi * 800 * t).astype(np.float32)
    mod = 0.5 + 0.5 * np.sin(2 * np.pi * 2.0 * t).astype(np.float32)
    signal = tone * mod

    # Add some noise
    rng = np.random.default_rng(42)
    signal += 0.02 * rng.standard_normal(n).astype(np.float32)

    return signal.reshape(-1, 1)


# ── File output ──────────────────────────────────────────────────────────────

def make_filename(output_dir: Path, label: str | None, fmt: str,
                  start_time: datetime) -> Path:
    """Generate output filename with timestamp and optional label."""
    ts = start_time.strftime("%Y%m%d_%H%M%S")
    parts = [ts]
    if label:
        # Sanitize label for filesystem
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
        parts.append(safe)
    return output_dir / f"{'_'.join(parts)}.{fmt}"


def write_audio(filepath: Path, audio: np.ndarray, samplerate: int,
                fmt: str) -> None:
    """Write audio to WAV or FLAC."""
    import soundfile as sf

    subtype = "FLOAT" if fmt == "wav" else "PCM_24"
    sf.write(str(filepath), audio, samplerate, subtype=subtype, format=fmt.upper())
    size_mb = filepath.stat().st_size / (1024 * 1024)
    print(f"Wrote {filepath} ({size_mb:.1f} MB)", file=sys.stderr)


def write_metadata(filepath: Path, metadata: dict) -> None:
    """Write JSON sidecar file alongside the recording."""
    meta_path = filepath.with_suffix(filepath.suffix + ".json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Wrote {meta_path}", file=sys.stderr)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scheduled audio recorder with metadata tagging. "
                    "Cron-friendly: record for a duration, optionally at a "
                    "specified time, with radio auto-tune support.")

    # Required
    parser.add_argument("--duration", type=float, required=True, metavar="SEC",
                        help="Recording duration in seconds (required)")

    # Scheduling
    parser.add_argument("--at", type=str, default=None, metavar="TIME",
                        help="Start time: HH:MM:SS or YYYY-MM-DDTHH:MM:SS "
                             "(omit to start immediately)")

    # Output
    parser.add_argument("--output-dir", type=str, default=".", metavar="DIR",
                        help="Output directory (default: current dir)")
    parser.add_argument("--label", type=str, default=None,
                        help="Label for filename and metadata")
    parser.add_argument("--format", choices=["wav", "flac"], default="wav",
                        dest="audio_format",
                        help="Output format (default: wav)")

    # Radio control
    radio_group = parser.add_argument_group("radio control (optional)")
    radio_group.add_argument("--frequency", type=float, default=None,
                             metavar="KHZ",
                             help="Tune radio to this frequency in kHz via rigctld")
    radio_group.add_argument("--rigctld-host", type=str, default="localhost",
                             help="rigctld hostname (default: localhost)")
    radio_group.add_argument("--rigctld-port", type=int, default=4532,
                             help="rigctld port (default: 4532)")

    # Metadata extras
    meta_group = parser.add_argument_group("metadata tags (optional)")
    meta_group.add_argument("--mode", type=str, default=None,
                            help="Operating mode (e.g., USB, LSB, CW, FM)")
    meta_group.add_argument("--antenna", type=str, default=None,
                            help="Antenna description")
    meta_group.add_argument("--notes", type=str, default=None,
                            help="Free-form notes for metadata")

    # Audio I/O (subset — input only)
    add_audio_args(parser, duplex=False)
    add_test_args(parser)

    args = parser.parse_args()

    # Validate output dir
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0

    # ── Wait for scheduled time ──────────────────────────────────────────
    if args.at:
        target = parse_time(args.at)
        wait_until(target)

    # ── Tune radio if requested ──────────────────────────────────────────
    radio_info = {}
    if args.frequency is not None:
        try:
            actual_hz = tune_radio(args.frequency, args.rigctld_host,
                                   args.rigctld_port)
            radio_info["tuned_hz"] = actual_hz
            print(f"Tuned to {actual_hz} Hz ({actual_hz/1000:.3f} kHz)",
                  file=sys.stderr)
            # Brief settle time for radio PLL
            time.sleep(0.1)
        except Exception as e:
            print(f"WARNING: Failed to tune radio: {e}", file=sys.stderr)
            radio_info["tune_error"] = str(e)

    # Query radio state (mode, passband) even if we didn't tune
    if args.frequency is not None:
        try:
            info = get_radio_info(args.rigctld_host, args.rigctld_port)
            radio_info.update(info)
        except Exception:
            pass

    # ── Record ───────────────────────────────────────────────────────────
    start_time = datetime.now()
    start_utc = datetime.now(timezone.utc)

    if args.test:
        audio = generate_test_audio(args.duration, args.samplerate)
        print(f"Generated {args.duration:.1f}s test audio", file=sys.stderr)
    else:
        audio = record_audio(
            duration_sec=args.duration,
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            channels=args.channels_in,
            input_device=args.input_device,
        )

    end_time = datetime.now()
    end_utc = datetime.now(timezone.utc)

    # ── Write output ─────────────────────────────────────────────────────
    filepath = make_filename(output_dir, args.label, args.audio_format,
                             start_time)
    write_audio(filepath, audio, args.samplerate, args.audio_format)

    # ── Write metadata sidecar ───────────────────────────────────────────
    metadata = {
        "file": filepath.name,
        "start_utc": start_utc.isoformat(timespec="seconds"),
        "end_utc": end_utc.isoformat(timespec="seconds"),
        "start_local": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "end_local": end_time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_sec": args.duration,
        "samplerate": args.samplerate,
        "channels": args.channels_in,
        "format": args.audio_format,
        "dtype": "float32",
        "blocksize": args.blocksize,
        "samples_recorded": len(audio),
    }

    if args.label:
        metadata["label"] = args.label
    if args.frequency is not None:
        metadata["frequency_khz"] = args.frequency
    if args.mode:
        metadata["mode"] = args.mode
    elif radio_info.get("mode"):
        metadata["mode"] = radio_info["mode"]
    if args.antenna:
        metadata["antenna"] = args.antenna
    if args.notes:
        metadata["notes"] = args.notes
    if radio_info:
        metadata["radio"] = radio_info
    if args.test:
        metadata["test_mode"] = True

    # Peak and RMS levels
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio ** 2)))
    metadata["peak_dbfs"] = round(20 * np.log10(peak + 1e-10), 1)
    metadata["rms_dbfs"] = round(20 * np.log10(rms + 1e-10), 1)

    write_metadata(filepath, metadata)

    return 0


if __name__ == "__main__":
    sys.exit(main())
