#!/usr/bin/env python3
"""
Flipper Zero IR Code Library Manager

Interactive session to capture, label, replay, and export IR remote control codes.
Supports export to JSON (internal), Flipper .ir format, LIRC lircd.conf, and Pronto hex.

Subcommands:
  capture  --device NAME --remote MODEL   capture IR codes interactively
  replay   --device NAME --button BTN     replay a stored code
  search   --protocol PROTO               search library by protocol
  list                                    list all devices in library
  import   PATH                           import a Flipper .ir file

Usage:
  python ir_library.py capture --device TV --remote "Samsung UN55"
  python ir_library.py replay  --device TV --button POWER
  python ir_library.py list
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SERIAL   = "/dev/ttyACM0"
DEFAULT_DB_FILE  = "ir_library_db.json"

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
        lib["devices"][device] = {"remote_model": remote, "buttons": {}}
    return lib["devices"][device]


# ---------------------------------------------------------------------------
# Export formats
# ---------------------------------------------------------------------------

def to_flipper_ir(device_name: str, device: dict) -> str:
    """Export to Flipper .ir file format."""
    lines = ["Filetype: IR signals file", "Version: 1", ""]
    for btn_name, btn in device["buttons"].items():
        lines.append(f"name: {btn_name}")
        if btn.get("type") == "parsed":
            lines.append("type: parsed")
            lines.append(f"protocol: {btn['protocol']}")
            lines.append(f"address: {btn['address']:08X}")
            lines.append(f"command: {btn['command']:08X}")
        else:
            lines.append("type: raw")
            lines.append(f"frequency: {btn.get('frequency', 38000)}")
            lines.append(f"duty_cycle: {btn.get('duty_cycle', 0.33):.2f}")
            timings = btn.get("timings_us", [])
            lines.append("data: " + " ".join(str(t) for t in timings))
        lines.append("")
    return "\n".join(lines)


def to_lirc_conf(device_name: str, device: dict) -> str:
    """Export to LIRC lircd.conf format."""
    lines = [
        "begin remote",
        f"  name  {device_name}",
        "  flags RAW_CODES",
        "  eps   30",
        "  aeps  100",
        "  gap   80000",
        "",
        "  begin raw_codes",
    ]
    for btn_name, btn in device["buttons"].items():
        timings = btn.get("timings_us", [])
        if timings:
            lines.append(f"    name {btn_name}")
            row = "      "
            for i, t in enumerate(timings):
                row += f"{t} "
                if (i + 1) % 10 == 0:
                    lines.append(row.rstrip())
                    row = "      "
            if row.strip():
                lines.append(row.rstrip())
    lines += ["  end raw_codes", "", "end remote"]
    return "\n".join(lines)


def to_pronto(timings_us: list, freq_hz: int = 38000) -> str:
    """Convert raw timings to Pronto hex format."""
    pronto_freq = int(4145152 / freq_hz)
    codes = [f"{0:04X}", f"{pronto_freq:04X}",
             f"{len(timings_us)//2:04X}", f"{0:04X}"]
    period_us = 1e6 / freq_hz
    for t in timings_us:
        burst_count = max(1, int(round(t / period_us)))
        codes.append(f"{burst_count:04X}")
    return " ".join(codes)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_capture(fz: FlipperZero, lib: dict, device_name: str, remote_model: str) -> None:
    device = get_or_create_device(lib, device_name, remote_model)
    print(f"\n[CAPTURE]  device={device_name}  remote={remote_model}")
    print("  Point remote at Flipper, press button, then type a label.")
    print("  Type 'done' or press Ctrl+C to finish.\n")

    while _running:
        try:
            label = input("  Button label (or 'done'): ").strip()
        except EOFError:
            break
        if not label or label.lower() == "done":
            break

        print(f"  Waiting for IR signal for '{label}' ...")
        result = fz.ir_receive(timeout_s=10.0)
        if result is None:
            print("  Timeout — no signal received. Try again.")
            continue

        if result.get("protocol") and result.get("protocol") != "Unknown":
            entry = {
                "type":     "parsed",
                "protocol": result["protocol"],
                "address":  result.get("address", 0),
                "command":  result.get("command", 0),
                "captured": datetime.now().isoformat(),
            }
            print(f"  Captured: {result['protocol']}  "
                  f"addr=0x{result.get('address',0):02X}  "
                  f"cmd=0x{result.get('command',0):02X}")
        else:
            timings = result.get("timings_us", [])
            entry = {
                "type":       "raw",
                "timings_us": timings,
                "frequency":  result.get("frequency", 38000),
                "duty_cycle": result.get("duty_cycle", 0.33),
                "captured":   datetime.now().isoformat(),
            }
            print(f"  Captured raw: {len(timings)} timing edges")

        device["buttons"][label] = entry


def cmd_replay(fz: FlipperZero, lib: dict, device_name: str, button: str) -> None:
    if device_name not in lib["devices"]:
        print(f"Error: device '{device_name}' not found in library.")
        sys.exit(1)
    device = lib["devices"][device_name]
    if button not in device["buttons"]:
        available = list(device["buttons"].keys())
        print(f"Error: button '{button}' not found. Available: {available}")
        sys.exit(1)

    btn = device["buttons"][button]
    print(f"Replaying {device_name}/{button} ...")
    if btn["type"] == "parsed":
        fz.ir_transmit(btn["protocol"], btn["address"], btn["command"])
    else:
        fz.ir_transmit_raw(btn["timings_us"],
                           frequency=btn.get("frequency", 38000))
    print("  Done.")


def cmd_search(lib: dict, protocol: str) -> None:
    print(f"\nSearching for protocol: {protocol}")
    found = 0
    for dev_name, device in lib["devices"].items():
        for btn_name, btn in device["buttons"].items():
            if btn.get("protocol", "").lower() == protocol.lower():
                print(f"  {dev_name}/{btn_name}  "
                      f"addr=0x{btn.get('address',0):02X}  "
                      f"cmd=0x{btn.get('command',0):02X}")
                found += 1
    if found == 0:
        print("  (no matches)")


def cmd_list(lib: dict) -> None:
    if not lib["devices"]:
        print("Library is empty.")
        return
    print(f"\n  {'Device':>20}  {'Remote Model':>24}  {'Buttons':>8}")
    print("  " + "-" * 58)
    for dev_name, device in lib["devices"].items():
        print(f"  {dev_name:>20}  {device.get('remote_model',''):>24}"
              f"  {len(device['buttons']):>8}")


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
        if line.startswith("name:"):
            if current.get("name"):
                device["buttons"][current["name"]] = {
                    k: v for k, v in current.items() if k != "name"
                }
                count += 1
            current = {"name": line.split(":", 1)[1].strip()}
        elif line.startswith("type:"):
            current["type"] = line.split(":", 1)[1].strip()
        elif line.startswith("protocol:"):
            current["protocol"] = line.split(":", 1)[1].strip()
        elif line.startswith("address:"):
            current["address"] = int(line.split(":", 1)[1].strip(), 16)
        elif line.startswith("command:"):
            current["command"] = int(line.split(":", 1)[1].strip(), 16)
        elif line.startswith("data:"):
            raw = line.split(":", 1)[1].strip()
            current["timings_us"] = [int(t) for t in raw.split()]

    if current.get("name"):
        device["buttons"][current["name"]] = {
            k: v for k, v in current.items() if k != "name"
        }
        count += 1

    print(f"Imported {count} buttons from {path} -> device '{device_name}'")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="IR code library: capture, replay, search, list, import",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ir_library.py capture --device TV --remote "Samsung UN55"
  python ir_library.py replay  --device TV --button POWER
  python ir_library.py search  --protocol NEC
  python ir_library.py list
  python ir_library.py import /path/to/remote.ir
""",
    )
    parser.add_argument("--serial",  default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")
    parser.add_argument("--library", default=DEFAULT_DB_FILE, metavar="FILE",
                        help=f"Library JSON file (default {DEFAULT_DB_FILE})")

    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="Capture IR codes interactively")
    cap.add_argument("--device", required=True, help="Device name (e.g. TV)")
    cap.add_argument("--remote", default="unknown", metavar="MODEL",
                     help="Remote model description")

    rep = sub.add_parser("replay", help="Replay a stored IR code")
    rep.add_argument("--device", required=True, help="Device name")
    rep.add_argument("--button", required=True, help="Button label")

    srch = sub.add_parser("search", help="Search library by protocol")
    srch.add_argument("--protocol", required=True, help="Protocol name (e.g. NEC)")

    sub.add_parser("list", help="List all devices")

    imp = sub.add_parser("import", help="Import a Flipper .ir file")
    imp.add_argument("path", help="Path to .ir file")

    args = parser.parse_args()
    lib  = load_library(args.library)

    fz = None
    if args.command in ("capture", "replay"):
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")

    try:
        if args.command == "capture":
            cmd_capture(fz, lib, args.device, args.remote)
            device = lib["devices"].get(args.device, {})
            ir_path  = f"{args.device}.ir"
            lrc_path = f"{args.device}.lircd.conf"
            with open(ir_path, "w") as fh:
                fh.write(to_flipper_ir(args.device, device))
            with open(lrc_path, "w") as fh:
                fh.write(to_lirc_conf(args.device, device))
            print(f"\n  Flipper .ir  -> {ir_path}")
            print(f"  LIRC conf    -> {lrc_path}")
        elif args.command == "replay":
            cmd_replay(fz, lib, args.device, args.button)
        elif args.command == "search":
            cmd_search(lib, args.protocol)
        elif args.command == "list":
            cmd_list(lib)
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
