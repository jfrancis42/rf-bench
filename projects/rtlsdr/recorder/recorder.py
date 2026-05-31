#!/usr/bin/env python3
"""
Wideband IQ Recorder

Records any 2.4 MHz slice of spectrum as a raw IQ file in SigMF format —
a timestamped, annotated capture that can be replayed, demodulated, and
analyzed offline indefinitely.

SigMF format: JSON metadata (.sigmf-meta) + binary samples (.sigmf-data).
Compatible with GNU Radio, SDR++, inspectrum, and most SDR software.

Usage:
    python recorder.py --freq 433.92e6 --duration 60
    python recorder.py --freq 137.62e6 --start "2026-05-28T21:14:00Z" --dur 600
    python recorder.py --freq 144.39e6 --trigger -60 --dur 120
    python recorder.py --freq 433.92e6 --rotate 30 --outdir /captures/ism
    python recorder.py --info capture.sigmf-meta
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import sigmf
    from sigmf import SigMFFile, sigmffile
    HAS_SIGMF = True
except ImportError:
    HAS_SIGMF = False

from rf_bench.rtlsdr import RTLSDR, RTLSDRError

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE  = 2_400_000
DEFAULT_GAIN         = "auto"
DEFAULT_BLOCK_SIZE   = 65_536
DEFAULT_OUTDIR       = "."

_running = True

def _sigint(_sig, _frame):
    global _running
    _running = False

signal.signal(signal.SIGINT, _sigint)


# ---------------------------------------------------------------------------
# SigMF helpers (fallback if sigmf library not available)
# ---------------------------------------------------------------------------

def _write_sigmf_meta(meta_path: Path, info: dict) -> None:
    """Write a minimal SigMF metadata file."""
    meta = {
        "global": {
            "core:datatype":    info["datatype"],
            "core:sample_rate": info["sample_rate"],
            "core:hw":          info.get("hw", "RTL-SDR"),
            "core:version":     "1.0.0",
            "core:author":      "rf-bench-rtlsdr-recorder",
        },
        "captures": [
            {
                "core:sample_start": 0,
                "core:frequency":    info["center_freq"],
                "core:datetime":     info["datetime"],
            }
        ],
        "annotations": info.get("annotations", []),
    }
    meta_path.write_text(json.dumps(meta, indent=2))


def _read_sigmf_meta(meta_path: Path) -> dict:
    raw = json.loads(meta_path.read_text())
    g   = raw.get("global", {})
    c   = raw.get("captures", [{}])[0]
    return {
        "sample_rate": g.get("core:sample_rate"),
        "datatype":    g.get("core:datatype"),
        "hw":          g.get("core:hw"),
        "center_freq": c.get("core:frequency"),
        "datetime":    c.get("core:datetime"),
        "annotations": raw.get("annotations", []),
    }


# ---------------------------------------------------------------------------
# Capture modes
# ---------------------------------------------------------------------------

def capture_immediate(sdr: RTLSDR, duration_s: float,
                      out_stem: Path, dtype: np.dtype) -> Path:
    """Capture for a fixed duration."""
    data_path = out_stem.with_suffix(".sigmf-data")
    n_total   = int(sdr._sample_rate * duration_s)
    n_written = 0

    print(f"Recording {duration_s:.0f}s @ "
          f"{sdr._center_freq/1e6:.3f} MHz / "
          f"{sdr._sample_rate/1e6:.2f} MS/s → {data_path.name}")

    with open(data_path, "wb") as fh:
        for block in sdr.stream_iq(block_size=DEFAULT_BLOCK_SIZE):
            if not _running:
                break
            if dtype == np.dtype("complex64"):
                fh.write(block.astype(np.complex64).tobytes())
            else:
                # complex int8: pack real/imag as int8 pairs
                scaled = (block * 127).astype(np.int8)
                interleaved = np.empty(len(scaled) * 2, dtype=np.int8)
                interleaved[0::2] = scaled.real
                interleaved[1::2] = scaled.imag
                fh.write(interleaved.tobytes())
            n_written += len(block)
            elapsed = n_written / sdr._sample_rate
            print(f"\r  {elapsed:.1f}s / {duration_s:.0f}s  "
                  f"({n_written:,} samples)", end="", flush=True)
            if n_written >= n_total:
                break
        sdr.stop_stream()

    print()
    return data_path


def capture_scheduled(sdr: RTLSDR, start_utc: datetime,
                      duration_s: float, out_stem: Path,
                      dtype: np.dtype) -> Path:
    """Wait until start_utc, then capture."""
    now  = datetime.now(tz=timezone.utc)
    wait = (start_utc - now).total_seconds()
    if wait > 0:
        print(f"Scheduled capture at {start_utc.strftime('%H:%M:%S UTC')}  "
              f"(in {int(wait)}s)")
        deadline = time.time() + wait
        while time.time() < deadline and _running:
            remaining = deadline - time.time()
            print(f"\r  Waiting {int(remaining)}s...", end="", flush=True)
            time.sleep(min(remaining, 5))
        print()
        if not _running:
            sys.exit(0)
    else:
        print("Start time is in the past; capturing immediately.")
    return capture_immediate(sdr, duration_s, out_stem, dtype)


def capture_threshold(sdr: RTLSDR, threshold_db: float,
                      hold_s: float, duration_s: float,
                      out_stem: Path, dtype: np.dtype) -> list[Path]:
    """
    Threshold-triggered capture: record when a signal exceeds threshold_db
    above the noise floor, stop hold_s after the last burst.
    """
    print(f"Threshold mode: trigger at noise_floor + {threshold_db:.0f} dB  "
          f"hold {hold_s:.1f}s  max_duration {duration_s:.0f}s")

    paths: list[Path] = []
    recording = False
    last_trigger = 0.0
    fh    = None
    n_rec = 0
    cap_n = 0
    cur_stem = out_stem

    for block in sdr.stream_iq(block_size=DEFAULT_BLOCK_SIZE):
        if not _running:
            break

        # Quick power check
        noise_est  = float(np.median(np.abs(block)))
        peak_power = float(np.max(np.abs(block)))
        if noise_est > 1e-10 and (peak_power / noise_est) > 10 ** (threshold_db / 20):
            last_trigger = time.time()
            triggered    = True
        else:
            triggered = False

        if triggered and not recording:
            ts   = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
            cur_stem = out_stem.parent / f"{out_stem.name}_{ts}_{cap_n:04d}"
            fh       = open(cur_stem.with_suffix(".sigmf-data"), "wb")
            recording = True
            n_rec     = 0
            print(f"\nTriggered → {cur_stem.with_suffix('.sigmf-data').name}")

        if recording and fh:
            if dtype == np.dtype("complex64"):
                fh.write(block.astype(np.complex64).tobytes())
            else:
                scaled = (block * 127).astype(np.int8)
                interleaved = np.empty(len(scaled) * 2, dtype=np.int8)
                interleaved[0::2] = scaled.real
                interleaved[1::2] = scaled.imag
                fh.write(interleaved.tobytes())
            n_rec += len(block)
            elapsed_rec = n_rec / sdr._sample_rate
            print(f"\r  Recording {elapsed_rec:.1f}s "
                  f"(peak {20*np.log10(peak_power+1e-10):.0f} dB)", end="", flush=True)

            if (time.time() - last_trigger > hold_s) or elapsed_rec >= duration_s:
                fh.close()
                paths.append(cur_stem.with_suffix(".sigmf-data"))
                _write_sigmf_meta(
                    cur_stem.with_suffix(".sigmf-meta"),
                    {
                        "datatype":    "cf32_le" if dtype == np.dtype("complex64") else "ci8_le",
                        "sample_rate": sdr._sample_rate,
                        "center_freq": sdr._center_freq,
                        "datetime":    datetime.now(tz=timezone.utc).isoformat(),
                    }
                )
                cap_n    += 1
                recording = False
                fh        = None
                print(f"\n  Saved {n_rec:,} samples")

    if fh:
        fh.close()

    sdr.stop_stream()
    return paths


def capture_rotating(sdr: RTLSDR, window_s: float,
                     out_stem: Path, dtype: np.dtype) -> None:
    """
    Rotating buffer: maintain a rolling window of recent IQ; write to disk on Ctrl-C.
    """
    max_samples = int(sdr._sample_rate * window_s)
    buf: list[np.ndarray] = []
    total = 0

    print(f"Rotating buffer: {window_s:.0f}s window.  Ctrl-C to save and exit.")

    for block in sdr.stream_iq(block_size=DEFAULT_BLOCK_SIZE):
        if not _running:
            break
        buf.append(block.copy())
        total += len(block)
        while total > max_samples and buf:
            total -= len(buf[0])
            buf.pop(0)
        print(f"\r  Buffer: {total/sdr._sample_rate:.1f}s / {window_s:.0f}s", end="", flush=True)

    sdr.stop_stream()
    print()

    if not buf:
        print("No data captured.")
        return

    data_path = out_stem.with_suffix(".sigmf-data")
    print(f"Saving {total:,} samples → {data_path.name}")
    with open(data_path, "wb") as fh:
        for chunk in buf:
            if dtype == np.dtype("complex64"):
                fh.write(chunk.astype(np.complex64).tobytes())
            else:
                scaled = (chunk * 127).astype(np.int8)
                iv = np.empty(len(scaled) * 2, dtype=np.int8)
                iv[0::2] = scaled.real
                iv[1::2] = scaled.imag
                fh.write(iv.tobytes())

    _write_sigmf_meta(
        out_stem.with_suffix(".sigmf-meta"),
        {
            "datatype":    "cf32_le" if dtype == np.dtype("complex64") else "ci8_le",
            "sample_rate": sdr._sample_rate,
            "center_freq": sdr._center_freq,
            "datetime":    datetime.now(tz=timezone.utc).isoformat(),
        }
    )
    print(f"Saved.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Wideband IQ recorder (SigMF)")
    ap.add_argument("--freq",     required=True, type=float,
                    help="Center frequency in Hz (e.g. 433.92e6)")
    ap.add_argument("--bw",       type=float, default=DEFAULT_SAMPLE_RATE,
                    help="Sample rate / bandwidth in S/s (default: 2.4e6)")
    ap.add_argument("--gain",     default=DEFAULT_GAIN,
                    help="Gain in dB or 'auto' (default: auto)")
    ap.add_argument("--duration", "--dur", type=float, default=60.0,
                    help="Capture duration in seconds (default: 60)")
    ap.add_argument("--start",    metavar="ISO8601",
                    help="Scheduled start time in UTC (e.g. 2026-05-28T21:14:00Z)")
    ap.add_argument("--trigger",  type=float, metavar="DB",
                    help="Threshold-trigger: N dB above noise floor")
    ap.add_argument("--hold",     type=float, default=2.0,
                    help="Threshold hold time in seconds (default: 2)")
    ap.add_argument("--rotate",   type=float, metavar="WINDOW_S",
                    help="Rotating buffer mode: keep last N seconds")
    ap.add_argument("--outdir",   default=DEFAULT_OUTDIR,
                    help="Output directory (default: current dir)")
    ap.add_argument("--prefix",   default="recording",
                    help="Output filename prefix (default: recording)")
    ap.add_argument("--int8",     action="store_true",
                    help="Save as complex int8 instead of complex float32 (4× smaller)")
    ap.add_argument("--bias-tee", action="store_true",
                    help="Enable RTL-SDR Blog bias tee to power an LNA")
    ap.add_argument("--serial",   help="RTL-SDR serial number")
    ap.add_argument("--info",     metavar="FILE",
                    help="Print metadata from a .sigmf-meta file and exit")
    args = ap.parse_args()

    # Info mode — no hardware needed
    if args.info:
        meta = _read_sigmf_meta(Path(args.info))
        print(json.dumps(meta, indent=2))
        return

    outdir   = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_stem = outdir / f"{args.prefix}_{ts}"
    dtype    = np.dtype("int8") if args.int8 else np.dtype("complex64")

    gain = args.gain if args.gain == "auto" else float(args.gain)

    try:
        with RTLSDR(serial=args.serial) as sdr:
            sdr.set_center_freq(int(args.freq))
            sdr.set_sample_rate(int(args.bw))
            sdr.set_gain(gain)
            if args.bias_tee:
                sdr.set_bias_tee(True)

            info = sdr.identify()
            print(f"RTL-SDR: {info['tuner_type']}  "
                  f"freq={info['center_freq']/1e6:.3f} MHz  "
                  f"rate={info['sample_rate']/1e6:.2f} MS/s  "
                  f"gain={info['gain']} dB  ppm={info['ppm_correction']}")

            if args.rotate:
                capture_rotating(sdr, args.rotate, out_stem, dtype)
            elif args.trigger is not None:
                paths = capture_threshold(sdr, args.trigger, args.hold,
                                          args.duration, out_stem, dtype)
                print(f"Saved {len(paths)} triggered capture(s).")
                return
            elif args.start:
                start_utc = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
                data_path = capture_scheduled(sdr, start_utc, args.duration, out_stem, dtype)
            else:
                data_path = capture_immediate(sdr, args.duration, out_stem, dtype)

            if args.bias_tee:
                sdr.set_bias_tee(False)

        if not args.rotate:
            meta_path = out_stem.with_suffix(".sigmf-meta")
            data_file = out_stem.with_suffix(".sigmf-data")
            _write_sigmf_meta(meta_path, {
                "datatype":    "ci8_le" if args.int8 else "cf32_le",
                "sample_rate": int(args.bw),
                "center_freq": int(args.freq),
                "datetime":    datetime.fromtimestamp(
                    data_file.stat().st_mtime, tz=timezone.utc
                ).isoformat() if data_file.exists() else
                datetime.now(tz=timezone.utc).isoformat(),
            })
            size_mb = out_stem.with_suffix(".sigmf-data").stat().st_size / 1e6
            print(f"SigMF: {out_stem.with_suffix('.sigmf-data').name}  "
                  f"({size_mb:.1f} MB)")

    except RTLSDRError as exc:
        print(f"RTL-SDR error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
