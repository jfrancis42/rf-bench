#!/usr/bin/env python3
"""
ptt.py — read the PTT button on a C-Media USB handset (e.g. H-250).

The handset's C-Media chip (USB 0d8c:aaa0) exposes a fourth HID interface
alongside its three audio interfaces. Pressing the handset button toggles
one bit in a 4-byte HID report delivered on the raw HID node:

    /dev/hidraw*  (symlinked as /dev/input/by-id/usb-TEC_H-250_Handset-if03-hidraw)

Report format (observed on H-250, firmware as shipped 2026-07):

    byte 0 : 0x00           (report id / constant)
    byte 1 : bit 0x10 = button, bit 0x01 constant-set
    byte 2 : 0x00
    byte 3 : 0x00

So the button state is simply  report[1] & PTT_MASK.

The device only emits a report when something CHANGES, so a simple
blocking read() blocks until the next press or release — no polling.

Usage:
    ./ptt.py                 # print PRESSED / released edges as they happen
    ./ptt.py --device PATH   # use a specific hidraw node
    ./ptt.py --find          # print the resolved hidraw path and exit

As a library:
    from ptt import watch_ptt
    watch_ptt(lambda pressed: print("TX" if pressed else "RX"))
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

# The bit in byte 1 that reflects the button. If your unit reads
# inverted (release shows as PRESSED), flip PTT_ACTIVE_HIGH to False.
PTT_MASK = 0x10
PTT_ACTIVE_HIGH = True

# Stable symlink the kernel creates for this handset's HID interface.
BY_ID = "/dev/input/by-id/usb-TEC_H-250_Handset-if03-hidraw"


def find_hidraw() -> str | None:
    """Locate the handset's hidraw node.

    Prefers the stable by-id symlink; falls back to scanning
    /sys for a hidraw device belonging to VID:PID 0D8C:AAA0.
    """
    if os.path.exists(BY_ID):
        return os.path.realpath(BY_ID)

    # Fallback: walk sysfs looking for the C-Media handset HID node.
    for node in glob.glob("/sys/class/hidraw/hidraw*"):
        try:
            uevent = open(os.path.join(node, "device", "uevent")).read()
        except OSError:
            continue
        # HID_ID line looks like: HID_ID=0003:00000D8C:0000AAA0
        if "0D8C" in uevent.upper() and "AAA0" in uevent.upper():
            return "/dev/" + os.path.basename(node)
    return None


def is_pressed(report: bytes) -> bool:
    """Decode a raw HID report into a boolean button state."""
    if len(report) < 2:
        return False
    bit = bool(report[1] & PTT_MASK)
    return bit if PTT_ACTIVE_HIGH else not bit


def watch_ptt(callback, device: str | None = None) -> None:
    """Call callback(pressed: bool) on every button state change.

    Blocks forever (until KeyboardInterrupt). `callback` receives True
    on press, False on release. Uses a blocking read, so it consumes no
    CPU while the button is idle.
    """
    path = device or find_hidraw()
    if not path:
        raise FileNotFoundError(
            "No H-250 hidraw node found. Is the handset plugged in? "
            "Try: ls /dev/input/by-id/"
        )
    fd = os.open(path, os.O_RDONLY)
    last = None
    try:
        while True:
            report = os.read(fd, 64)      # blocks until state changes
            pressed = is_pressed(report)
            if pressed != last:           # debounce duplicate reports
                last = pressed
                callback(pressed)
    finally:
        os.close(fd)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Read the PTT button on a C-Media USB handset (H-250)."
    )
    ap.add_argument("--device", default=None,
                    help="hidraw node path (default: auto-detect the H-250)")
    ap.add_argument("--find", action="store_true",
                    help="Print the resolved hidraw path and exit")
    args = ap.parse_args()

    if args.find:
        path = args.device or find_hidraw()
        print(path or "not found")
        return 0 if path else 1

    print("Watching PTT button — press it (Ctrl-C to stop).", file=sys.stderr)
    try:
        watch_ptt(
            lambda pressed: print("PRESSED" if pressed else "released", flush=True),
            device=args.device,
        )
    except KeyboardInterrupt:
        pass
    except PermissionError:
        print("Permission denied on the hidraw node. Add yourself to the "
              "'input' group (or use a udev rule).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
