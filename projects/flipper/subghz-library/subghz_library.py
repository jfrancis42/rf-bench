#!/usr/bin/env python3
"""
Flipper Zero Sub-GHz Code Library

Sub-GHz counterpart to ir_library.py. Capture session for garage doors, gate
controllers, and other 433/315 MHz devices. Labels each code and exports to
JSON and Flipper .sub format. Supports list, replay, and import from Flipper
SD card .sub files.

Subcommands:
  capture --device NAME --remote MODEL  capture codes interactively
  replay  --device NAME --button BTN     transmit a stored code
  list    [--freq MHZ]                   list stored devices
  send    --device NAME --button BTN     alias for replay
  import  PATH                           import a Flipper .sub file

Usage:
  python subghz_library.py capture --device Garage --remote "Chamberlain B970"
  python subghz_library.py replay  --device Garage --button OPEN
  python subghz_library.py list
"""

import argparse
import json
import os
import signal
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SERIAL  = "/dev/ttyACM0"
DEFAULT_LIBRARY = "subghz_library_db.json"
DEFAULT_FREQ    = 433.92

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Library I/O
# ---------------------------------------------------------------------------

def load_library(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {"devices": {}}


def save_library(lib: dict, path: str) -> None:
    with open(path, "w") as fh:
        json.dump(lib, fh, indent=2)


def get_or_create_device(lib: dict, device: str, remote: str) -> dict:
    if device not in lib["devices"]:
        lib["devices"][device] = {
            "remote_model": remote, "buttons": {}
        }
    return lib["devices"][device]


# ---------------------------------------------------------------------------
# Flipper .sub export
# ---------------------------------------------------------------------------

def to_flipper_sub(device_name: str, device: dict) -> str:
    """Export to Flipper .sub file format."""
    lines = [
        "Filetype: Flipper SubGhz RAW File",
        "Version: 1",
        "",
    ]
    for btn_name, btn in device["buttons"].items():
        freq_hz = int(btn.get("freq_hz", DEFAULT_FREQ * 1e6))
        lines.append(f"# Button: {btn_name}")
        lines.append(f"Frequency: {freq_hz}")
        lines.append(f"Preset: {btn.get('preset', 'FuriHalSubGhzPresetOok650Async')}")
        timings = btn.get("timings_us", [])
        if timings:
            lines.append("Protocol: RAW")
            lines.append("RAW_Data: " + " ".join(str(t) for t in timings))
        elif btn.get("protocol"):
            lines.append(f"Protocol: {btn['protocol']}")
            lines.append(f"Bit: {btn.get('bits', 24)}")
            lines.append(f"Key: {btn.get('code', 0):06X}")
            lines.append(f"Te: {btn.get('te', 400)}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_capture(fz: FlipperZero, lib: dict, device_name: str, remote: str) -> None:
    device = get_or_create_device(lib, device_name, remote)
    print(f"\n[CAPTURE]  device={device_name}  remote={remote}")
    print("  Press button on remote/fob, then enter a label.")
    print("  Type 'done' or Ctrl+C to finish.\n")

    freq_mhz = DEFAULT_FREQ
    try:
        freq_in = input(f"  Frequency MHz [{freq_mhz}]: ").strip()
        if freq_in:
            freq_mhz = float(freq_in)
    except (ValueError, EOFError):
        pass
    freq_hz = int(freq_mhz * 1e6)

    while _running:
        try:
            label = input("  Button label (or 'done'): ").strip()
        except EOFError:
            break
        if not label or label.lower() == "done":
            break

        print(f"  Capturing for '{label}' ...")
        raw = fz.subghz_get_raw(freq_hz, duration_s=3.0)
        if not raw:
            print("  No signal captured. Try again.")
            continue

        # Extract from Flipper output
        timings, protocol, code, te = _parse_subghz_raw(raw)
        if timings:
            entry = {
                "type":       "raw",
                "freq_hz":    freq_hz,
                "timings_us": timings,
                "preset":     "FuriHalSubGhzPresetOok650Async",
                "captured":   datetime.now().isoformat(),
            }
        elif protocol:
            entry = {
                "type":     "protocol",
                "freq_hz":  freq_hz,
                "protocol": protocol,
                "code":     code,
                "te":       te,
                "captured": datetime.now().isoformat(),
            }
        else:
            entry = {
                "type":     "raw_string",
                "freq_hz":  freq_hz,
                "raw":      raw,
                "captured": datetime.now().isoformat(),
            }
        device["buttons"][label] = entry
        print(f"  Saved '{label}'  freq={freq_hz/1e6:.3f} MHz  "
              f"type={'raw' if timings else 'protocol' if protocol else 'raw_string'}")


def _parse_subghz_raw(raw: str) -> tuple:
    """Parse Flipper raw output. Returns (timings, protocol, code, te)."""
    timings  = []
    protocol = ""
    code     = 0
    te       = 400
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("RAW_Data:"):
            data = line.split(":", 1)[1].strip()
            try:
                timings = [int(t) for t in data.split()]
            except ValueError:
                pass
        elif line.startswith("Protocol:"):
            protocol = line.split(":", 1)[1].strip()
        elif line.startswith("Code:"):
            try:
                code = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("Te:"):
            try:
                te = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return timings, protocol, code, te


def cmd_replay(fz: FlipperZero, lib: dict, device_name: str, button: str) -> None:
    if device_name not in lib["devices"]:
        print(f"Error: device '{device_name}' not in library.")
        sys.exit(1)
    device = lib["devices"][device_name]
    if button not in device["buttons"]:
        print(f"Error: button '{button}' not found. Available: "
              f"{list(device['buttons'].keys())}")
        sys.exit(1)

    btn     = device["buttons"][button]
    freq_hz = int(btn.get("freq_hz", DEFAULT_FREQ * 1e6))
    print(f"Transmitting {device_name}/{button} @ {freq_hz/1e6:.3f} MHz ...")

    if btn.get("type") == "raw" and btn.get("timings_us"):
        fz.subghz_transmit_raw(freq_hz, btn["timings_us"],
                               preset=btn.get("preset", "ook650"))
    elif btn.get("type") == "protocol":
        fz.subghz_transmit_protocol(freq_hz, btn["protocol"], btn["code"])
    else:
        print("  Warning: no timings or protocol stored; cannot transmit.")
        return
    print("  Done.")


def cmd_list(lib: dict, freq_filter: float = None) -> None:
    if not lib["devices"]:
        print("Library is empty.")
        return
    print(f"\n  {'Device':>20}  {'Remote':>20}  {'Buttons':>8}")
    print("  " + "-" * 54)
    for dev_name, device in lib["devices"].items():
        btns = device["buttons"]
        if freq_filter is not None:
            btns = {k: v for k, v in btns.items()
                    if abs(v.get("freq_hz", 0) - freq_filter * 1e6) < 1e6}
        if freq_filter is not None and not btns:
            continue
        print(f"  {dev_name:>20}  {device.get('remote_model',''):>20}  {len(btns):>8}")
        for btn_name, btn in btns.items():
            print(f"    {btn_name:<24}  {btn.get('freq_hz',0)/1e6:.3f} MHz  "
                  f"{btn.get('type','?')}")


def cmd_import(lib: dict, path: str) -> None:
    if not os.path.exists(path):
        print(f"Error: file not found: {path}")
        sys.exit(1)
    device_name = os.path.splitext(os.path.basename(path))[0]
    device = get_or_create_device(lib, device_name, "imported")

    with open(path) as fh:
        content = fh.read()

    current: dict = {}
    count = 0
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# Button:"):
            if current.get("label"):
                device["buttons"][current["label"]] = {
                    k: v for k, v in current.items() if k != "label"
                }
                count += 1
            current = {"label": line.split(":", 1)[1].strip()}
        elif line.startswith("Frequency:"):
            current["freq_hz"] = int(line.split(":", 1)[1].strip())
        elif line.startswith("Protocol:"):
            current["type"] = "raw" if line.split(":", 1)[1].strip() == "RAW" else "protocol"
            current["protocol"] = line.split(":", 1)[1].strip()
        elif line.startswith("RAW_Data:"):
            data = line.split(":", 1)[1].strip()
            try:
                current["timings_us"] = [int(t) for t in data.split()]
                current["type"] = "raw"
            except ValueError:
                pass
        elif line.startswith("Key:"):
            try:
                current["code"] = int(line.split(":", 1)[1].strip(), 16)
            except ValueError:
                pass

    if current.get("label"):
        device["buttons"][current["label"]] = {
            k: v for k, v in current.items() if k != "label"
        }
        count += 1
    print(f"Imported {count} buttons -> device '{device_name}'")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sub-GHz code library: capture, replay, list, import",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python subghz_library.py capture --device Garage --remote "Chamberlain"
  python subghz_library.py replay  --device Garage --button OPEN
  python subghz_library.py list
  python subghz_library.py import /path/to/remote.sub
""",
    )
    parser.add_argument("--serial",  default=DEFAULT_SERIAL, metavar="PORT")
    parser.add_argument("--library", default=DEFAULT_LIBRARY, metavar="FILE")

    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture")
    cap.add_argument("--device", required=True)
    cap.add_argument("--remote", default="unknown")

    rep = sub.add_parser("replay")
    rep.add_argument("--device", required=True)
    rep.add_argument("--button", required=True)

    snd = sub.add_parser("send")
    snd.add_argument("--device", required=True)
    snd.add_argument("--button", required=True)

    lst = sub.add_parser("list")
    lst.add_argument("--freq", type=float, default=None, metavar="MHZ",
                     help="Filter by frequency MHz")

    imp = sub.add_parser("import")
    imp.add_argument("path", help="Path to .sub file")

    args = parser.parse_args()
    lib  = load_library(args.library)

    fz = None
    if args.command in ("capture", "replay", "send"):
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")

    try:
        if args.command == "capture":
            cmd_capture(fz, lib, args.device, args.remote)
            # Export .sub sidecar
            device  = lib["devices"].get(args.device, {})
            sub_path = f"{args.device}.sub"
            with open(sub_path, "w") as fh:
                fh.write(to_flipper_sub(args.device, device))
            print(f"  Flipper .sub -> {sub_path}")
        elif args.command in ("replay", "send"):
            cmd_replay(fz, lib, args.device, args.button)
        elif args.command == "list":
            cmd_list(lib, freq_filter=args.freq)
        elif args.command == "import":
            cmd_import(lib, args.path)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        save_library(lib, args.library)
        print(f"\nLibrary saved -> {args.library}")


if __name__ == "__main__":
    main()
