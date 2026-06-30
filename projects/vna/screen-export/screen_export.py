#!/usr/bin/env python3
"""
screen_export.py — Grab the NanoVNA's LCD framebuffer as PNG.

The NanoVNA shell has a `capture` command that emits the current
screen's framebuffer in raw RGB565 (320×240 on H-series, 480×320 on
H4 / F-series). This script:

  1. Issues `capture` via the driver's raw() escape hatch.
  2. Decodes the RGB565 bytes into a PIL image.
  3. Writes a PNG, optionally with a timestamp watermark.

NOTE: not all NanoVNA firmwares expose `capture` over the shell.
NanoVNA-F's Deepelec firmware DOES support it (verified per the
project doc). NanoVNA-V2 and LiteVNA use binary protocols and are
not supported by this script (or by the rf_bench.nanovna driver).
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, sys, struct
from datetime import datetime


def open_vna(port):
    from rf_bench.nanovna import NanoVNA
    return NanoVNA(port=port)


def capture_framebuffer(vna, width=480, height=320):
    """
    Send 'capture' and read width*height*2 bytes of RGB565 from the
    shell. The default 480x320 is the F-series resolution; H-series
    needs 320x240.

    The 'capture' command's output isn't pure binary on the shell —
    different firmware versions wrap it differently. This routine
    tries the common DiSlord/Deepelec convention: ASCII echo of
    `capture` + a known marker + the raw bytes + a trailing prompt.
    On some firmware it's pure binary between the command echo and
    the prompt.
    """
    # Use the driver's raw command. The driver currently expects
    # ASCII responses, so this may not work cleanly with all
    # firmwares. If it fails, an alternative is the lower-level
    # _ser.read() loop — left as future work.
    raw_resp = vna.raw("capture", timeout=10.0)
    # Strip command echo and prompt
    expected = width * height * 2
    # Take last `expected` bytes from the raw response
    encoded = raw_resp.encode("latin-1")
    if len(encoded) < expected:
        raise RuntimeError(
            f"Got {len(encoded)} bytes from capture; expected ≥ "
            f"{expected} for {width}×{height}. Firmware may not "
            f"support `capture` over the shell — try the device's "
            f"USB-mass-storage screenshot feature instead.")
    return encoded[-expected:]


def rgb565_to_rgb888(raw_bytes, width, height):
    from PIL import Image
    pixels = []
    for i in range(width*height):
        b0 = raw_bytes[2*i]; b1 = raw_bytes[2*i+1]
        # NanoVNA: big-endian RGB565
        v = (b0 << 8) | b1
        r = (v >> 11) & 0x1F
        g = (v >> 5)  & 0x3F
        b =  v        & 0x1F
        # Scale to 8-bit
        pixels.append(((r << 3) | (r >> 2),
                       (g << 2) | (g >> 4),
                       (b << 3) | (b >> 2)))
    img = Image.new("RGB", (width, height))
    img.putdata(pixels)
    return img


def main() -> int:
    p = argparse.ArgumentParser(
        description="Capture the NanoVNA LCD framebuffer as PNG.")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--width", type=int, default=480,
                   help="LCD width (default 480 for NanoVNA-F)")
    p.add_argument("--height", type=int, default=320,
                   help="LCD height (default 320 for NanoVNA-F)")
    p.add_argument("--output", required=True, metavar="FILE.png")
    args = p.parse_args()

    try:
        vna = open_vna(args.port)
    except Exception as exc:
        print(f"Failed to open VNA at {args.port}: {exc}", file=sys.stderr)
        return 1
    try:
        raw = capture_framebuffer(vna, args.width, args.height)
    finally:
        try: vna.close()
        except Exception: pass

    try:
        from PIL import Image  # noqa
        img = rgb565_to_rgb888(raw, args.width, args.height)
        img.save(args.output)
        print(f"Wrote {args.output}")
        return 0
    except ImportError:
        print("Pillow required: pip install pillow --break-system-packages",
              file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
