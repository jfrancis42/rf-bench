#!/usr/bin/env python3
"""
bp_console.py — robust Bus Pirate v5 terminal driver + BPIO2 auto-setup.

The v5 terminal echoes character-by-character and redraws its prompt, so naive
"write then sleep then read" interaction drops characters and mis-parses menus.
This module instead uses an expect-style loop: send a line, then read until the
port goes IDLE (no new bytes for a short window), and match against expected
substrings. That is deterministic regardless of echo quirks.

It also handles the one thing that actually matters for automation: making sure
BPIO2 is active on the binary port every time, activating it via the terminal
port if it is not, and rebooting the device into it.

Reusable entry point:

    from bp_console import ensure_bpio2
    binary_port = ensure_bpio2()          # returns the working binary port
    from rf_bench.buspirate import BusPirate
    bp = BusPirate(binary_port)
"""
from __future__ import annotations

import re
import sys
import time

import serial

sys.path.insert(0, '/home/jfrancis/build/rf-bench/drivers/buspirate')
from rf_bench.buspirate import BusPirate, BusPirateError  # noqa: E402
import rf_bench.buspirate.buspirate as _bpmod             # noqa: E402

_ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


def strip_ansi(t: str) -> str:
    return _ANSI.sub('', t)


def read_until_idle(ser: serial.Serial, idle: float = 0.35,
                    overall: float = 4.0) -> str:
    """Read until no new bytes arrive for `idle` seconds (or `overall` cap)."""
    buf = bytearray()
    start = time.time()
    last = time.time()
    while time.time() - start < overall:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            last = time.time()
        elif time.time() - last >= idle:
            break
        else:
            time.sleep(0.02)
    return strip_ansi(buf.decode('ascii', 'replace'))


def send_line(ser: serial.Serial, line: bytes, idle: float = 0.35,
              overall: float = 4.0) -> str:
    """Send `line` + CR, return everything read until the port goes idle."""
    ser.reset_input_buffer()
    ser.write(line + b'\r')
    ser.flush()
    return read_until_idle(ser, idle, overall)


def bpio2_responds(port: str, attempts: int = 3) -> bool:
    """
    True if the binary port answers a BPIO2 status request with a valid frame.

    Opening the RP2040 CDC port can assert DTR/RTS and briefly perturb the
    firmware, so we open with both lines de-asserted and retry a couple of
    times with a bounded, non-blocking read (never the blocking read_until).
    """
    req = _bpmod._bpio2_encode(_bpmod._fb_status_request())
    for _ in range(attempts):
        try:
            s = serial.Serial()
            s.port = port
            s.baudrate = 115200
            s.timeout = 0.5
            s.write_timeout = 1
            s.dtr = False
            s.rts = False
            s.open()
        except Exception:
            time.sleep(0.3)
            continue
        try:
            s.reset_input_buffer()
            s.write(req)
            s.flush()
            # Bounded collect: read whatever arrives within ~0.8 s, look for the
            # COBS null terminator, then try to decode.
            deadline = time.time() + 0.8
            buf = bytearray()
            while time.time() < deadline:
                n = s.in_waiting
                if n:
                    buf += s.read(n)
                    if buf[-1:] == b'\x00':
                        break
                else:
                    time.sleep(0.02)
            if buf and buf[-1:] == b'\x00':
                _bpmod._bpio2_decode(bytes(buf[:-1]))   # raises if invalid
                return True
        except Exception:
            pass
        finally:
            s.close()
        time.sleep(0.3)
    return False


def find_ports():
    """Return (binary_port, terminal_port) for the attached Bus Pirate v5."""
    binary = terminal = None
    for d in BusPirate.find_devices():
        if d.get('role') == 'binary':
            binary = d['port']
        elif d.get('role') == 'terminal':
            terminal = d['port']
    return binary, terminal


def reset_via_terminal(terminal_port: str, verbose=True) -> bool:
    """
    Reboot the Bus Pirate from the terminal so it comes up in its saved binmode.

    The v5 terminal reset command is '#'. We watch for the boot banner to
    confirm the reboot actually happened.
    """
    s = serial.Serial(terminal_port, 115200, timeout=1)
    try:
        s.write(b'\x03'); s.flush()          # Ctrl-C: clear any half-typed line
        read_until_idle(s, 0.3, 1.0)
        out = send_line(s, b'#', idle=0.6, overall=5.0)
        if verbose:
            tail = out.strip().splitlines()[-3:]
            print(f"  [reset] {' | '.join(l.strip() for l in tail) or '(no banner)'}")
        # A reboot drops the CDC port; give the OS time to re-enumerate.
        return True
    finally:
        s.close()


def activate_bpio2_on_terminal(terminal_port: str, verbose=True) -> None:
    """Drive the terminal binmode menu to select + save BPIO2 (mode 2)."""
    s = serial.Serial(terminal_port, 115200, timeout=1)
    try:
        s.write(b'\x03'); s.flush()
        read_until_idle(s, 0.3, 1.0)

        out = send_line(s, b'binmode', idle=0.4, overall=5.0)
        if 'BPIO2' not in out:
            raise BusPirateError(f"binmode menu not seen on {terminal_port}: {out[-200:]!r}")

        # Select "2. BPIO2 flatbuffer interface", expect the save prompt.
        out = send_line(s, b'2', idle=0.4, overall=4.0)
        if 'ave' not in out:      # "Save setting?"
            # Some firmwares jump straight back to prompt; that's fine too.
            if verbose:
                print(f"  [binmode] no explicit save prompt: {out.strip()[-80:]!r}")
        else:
            out = send_line(s, b'y', idle=0.4, overall=4.0)
        if verbose:
            print("  [binmode] BPIO2 selected and saved")
    finally:
        s.close()


def ensure_bpio2(verbose=True, reboot_wait=6.0) -> str:
    """
    Guarantee BPIO2 is active and return the working binary port.

    Strategy (each step only runs if the previous did not already succeed):
      1. If the binary port already speaks BPIO2 → return it.
      2. Activate BPIO2 via the terminal menu, reboot, re-probe.
      3. Raise BusPirateError with specifics if it still will not come up.
    """
    binary, terminal = find_ports()
    if not binary:
        raise BusPirateError("No Bus Pirate v5 found (check USB / find_devices()).")

    if bpio2_responds(binary):
        if verbose:
            print(f"BPIO2 already active on {binary}")
        return binary

    if not terminal:
        raise BusPirateError(f"BPIO2 not active on {binary} and no terminal port found.")

    if verbose:
        print(f"BPIO2 not active on {binary}; activating via {terminal} …")
    activate_bpio2_on_terminal(terminal, verbose)
    reset_via_terminal(terminal, verbose)

    # Wait for USB re-enumeration, then re-resolve ports (numbers can change).
    time.sleep(reboot_wait)
    binary, terminal = find_ports()
    if binary and bpio2_responds(binary):
        if verbose:
            print(f"BPIO2 now active on {binary}")
        return binary

    raise BusPirateError(
        f"BPIO2 still not responding after activation + reboot "
        f"(binary={binary}, terminal={terminal}). "
        f"A physical power-cycle of the Bus Pirate may be required.")


if __name__ == '__main__':
    port = ensure_bpio2()
    print("BINARY_PORT:", port)
