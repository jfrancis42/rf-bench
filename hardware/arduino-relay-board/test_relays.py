#!/usr/bin/env python3
"""
Exercise the Arduino+W5100 network relay board.

Runs through every relay individually, every relay in combination, and
both pulse modes; after each command it reads back the board's state
and verifies it matches what we asked for.

Because the board tracks *commanded* state (not physical contact
sense), this test exercises the firmware command-parser and the Python
driver end-to-end without any relays physically plugged in.

Usage:
    python3 test_relays.py                 # uses default IP 10.1.1.36
    python3 test_relays.py 192.168.1.177
"""

from __future__ import annotations

import sys
import time

from rf_bench.arduino_relay_board import (
    ArduinoRelayBoard,
    ArduinoRelayBoardError,
)


DEFAULT_HOST = "10.1.1.36"
NUM_RELAYS = ArduinoRelayBoard.NUM_RELAYS


# ---- tiny pass/fail harness -------------------------------------------------

PASSED = 0
FAILED = 0


def check(label: str, expected, actual) -> None:
    """Compare expected vs actual; print result; tally."""
    global PASSED, FAILED
    ok = expected == actual
    marker = "PASS" if ok else "FAIL"
    print(f"  [{marker}] {label}: expected={expected!r}  got={actual!r}")
    if ok:
        PASSED += 1
    else:
        FAILED += 1


def banner(s: str) -> None:
    print()
    print("=" * 72)
    print(s)
    print("=" * 72)


# ---- per-test sequences -----------------------------------------------------

def test_identification(r: ArduinoRelayBoard) -> None:
    banner("1. Identification")
    idn = r.idn()
    print(f"  *IDN? -> {idn}")
    check("IDN starts with 'N0GQ,ArduinoRelayBoard'",
          True, idn.startswith("N0GQ,ArduinoRelayBoard"))


def test_reset_clears_all(r: ArduinoRelayBoard) -> None:
    banner("2. RESET clears all relays")
    r.reset()
    check("status bitmask after reset", 0, r.status())
    check("status_all after reset",
          (False,) * NUM_RELAYS, r.status_all())
    for n in range(1, NUM_RELAYS + 1):
        check(f"get_state({n}) after reset", False, r.get_state(n))


def test_each_relay_on_off(r: ArduinoRelayBoard) -> None:
    banner("3. Per-relay ON/OFF round-trip (one at a time)")
    for n in range(1, NUM_RELAYS + 1):
        print(f"\n  -- Relay {n} --")
        r.reset()                                   # known clean state

        r.on(n)
        expected_bits = 1 << (n - 1)
        check(f"get_state({n}) after ON",   True,  r.get_state(n))
        check(f"status() bitmask",          expected_bits, r.status())
        # Every other relay must still be OFF.
        for m in range(1, NUM_RELAYS + 1):
            if m == n:
                continue
            check(f"  relay {m} unaffected", False, r.get_state(m))

        r.off(n)
        check(f"get_state({n}) after OFF",  False, r.get_state(n))
        check("status() bitmask after OFF", 0,     r.status())


def test_all_on_then_all_off(r: ArduinoRelayBoard) -> None:
    banner("4. All relays on, then all off")
    r.reset()
    for n in range(1, NUM_RELAYS + 1):
        r.on(n)
    all_on_mask = (1 << NUM_RELAYS) - 1
    check("status() with all on", all_on_mask, r.status())
    check("status_all() with all on",
          (True,) * NUM_RELAYS, r.status_all())

    r.reset()
    check("status() after RESET",   0, r.status())
    check("status_all() after RESET",
          (False,) * NUM_RELAYS, r.status_all())


def test_pulse_high(r: ArduinoRelayBoard) -> None:
    banner("5. PULSEH — drive HIGH for n ms, then return LOW")
    r.reset()
    pulse_ms = 600                                   # comfortably observable

    for n in range(1, NUM_RELAYS + 1):
        print(f"\n  -- Relay {n}: PULSEH {pulse_ms} ms --")
        r.pulse_high(n, pulse_ms)

        # Sample shortly after the pulse starts — relay must be ON.
        time.sleep(0.1)
        check(f"relay {n} HIGH mid-pulse",  True,  r.get_state(n))
        check("bitmask mid-pulse",          1 << (n - 1), r.status())

        # Wait past the pulse end with a generous margin (network +
        # driver round-trip can eat ~50 ms).
        time.sleep((pulse_ms / 1000.0) + 0.3)
        check(f"relay {n} reverted to LOW", False, r.get_state(n))
        check("bitmask after pulse",        0,     r.status())


def test_pulse_low(r: ArduinoRelayBoard) -> None:
    banner("6. PULSEL — drive LOW for n ms, then return HIGH")
    r.reset()
    pulse_ms = 600

    for n in range(1, NUM_RELAYS + 1):
        print(f"\n  -- Relay {n}: ON, then PULSEL {pulse_ms} ms --")
        r.on(n)                                      # start from energized
        check(f"relay {n} starts HIGH",     True,  r.get_state(n))

        r.pulse_low(n, pulse_ms)

        time.sleep(0.1)
        check(f"relay {n} LOW mid-pulse",   False, r.get_state(n))

        time.sleep((pulse_ms / 1000.0) + 0.3)
        check(f"relay {n} returned to HIGH", True, r.get_state(n))

        r.off(n)


def test_pulse_cancels_with_explicit_set(r: ArduinoRelayBoard) -> None:
    banner("7. Explicit ON/OFF cancels an in-flight pulse")
    r.reset()
    # Long pulse so we have time to intervene.
    r.pulse_high(1, 5000)
    time.sleep(0.1)
    check("relay 1 high during pulse", True, r.get_state(1))

    # Explicit OFF must override the pulse's pending revert and stay OFF
    # even past the original pulse expiration.
    r.off(1)
    check("relay 1 off immediately after explicit OFF", False, r.get_state(1))

    time.sleep(0.6)   # was scheduled to revert ~5 s in; we should still be OFF
    check("relay 1 still off (pulse not re-firing)", False, r.get_state(1))


def test_bad_inputs(r: ArduinoRelayBoard) -> None:
    banner("8. Error handling — bad inputs")
    r.reset()

    # Python-side range check
    try:
        r.on(0)
    except ValueError as e:
        print(f"  [PASS] on(0) raised ValueError: {e}")
        globals()["PASSED"] += 1
    else:
        print("  [FAIL] on(0) should have raised ValueError")
        globals()["FAILED"] += 1

    try:
        r.on(NUM_RELAYS + 1)
    except ValueError as e:
        print(f"  [PASS] on({NUM_RELAYS + 1}) raised ValueError: {e}")
        globals()["PASSED"] += 1
    else:
        print(f"  [FAIL] on({NUM_RELAYS + 1}) should have raised ValueError")
        globals()["FAILED"] += 1

    try:
        r.pulse_high(1, 0)
    except ValueError as e:
        print(f"  [PASS] pulse_high(1, 0) raised ValueError: {e}")
        globals()["PASSED"] += 1
    else:
        print("  [FAIL] pulse_high(1, 0) should have raised ValueError")
        globals()["FAILED"] += 1


# ---- entry point ------------------------------------------------------------

def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
    print(f"Connecting to Arduino relay board at {host}:5025 ...")
    try:
        with ArduinoRelayBoard(host) as r:
            test_identification(r)
            test_reset_clears_all(r)
            test_each_relay_on_off(r)
            test_all_on_then_all_off(r)
            test_pulse_high(r)
            test_pulse_low(r)
            test_pulse_cancels_with_explicit_set(r)
            test_bad_inputs(r)

            print()
            print("Final cleanup: RESET to leave all relays OFF.")
            r.reset()
            check("final state is all-off", 0, r.status())
    except ArduinoRelayBoardError as e:
        print(f"\nFATAL: {e}")
        return 2
    except OSError as e:
        print(f"\nFATAL: could not connect to {host}:5025 — {e}")
        return 2

    banner("Results")
    print(f"  Passed: {PASSED}")
    print(f"  Failed: {FAILED}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
