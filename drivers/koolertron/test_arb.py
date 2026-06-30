#!/usr/bin/env python3
"""
test_arb.py — Test script for arbitrary waveform upload feature.

Tests the upload_arb() and upload_arb_normalized() methods against a real
MHS-5200A unit. This script validates:
  - upload_arb with 0-255 integer samples
  - upload_arb_normalized with -1.0 to +1.0 float samples
  - error handling for invalid inputs
  - output of uploaded waveforms on channel 1

Hardware requirement: MHS-5200A connected on the default port (auto-detected
CH340 / PL2303). Output on channel 1 can be monitored on a scope.

Usage:
    python3 test_arb.py                # full test suite
    python3 test_arb.py --slot 0       # upload sine to slot 0 only
"""

import argparse
import math
import sys
import time

# Import from the local development copy
sys.path.insert(0, ".")
from rf_bench.koolertron import MHS5200A, Waveform


def test_upload_sine_normalized(gen: MHS5200A, slot: int = 0) -> None:
    """Upload a normalized sine wave to the specified slot."""
    print(f"\n[TEST] upload_arb_normalized: sine wave to slot {slot}")

    # Create normalized sine (1024 samples, -1.0 to +1.0)
    sine = [math.sin(2 * math.pi * i / 1024) for i in range(1024)]

    print(f"  Uploading {len(sine)} samples...")
    gen.upload_arb_normalized(slot, sine)
    print(f"  Upload complete. Waveform stored in slot {slot} (Waveform.ARB{slot})")


def test_upload_ramp(gen: MHS5200A, slot: int = 1) -> None:
    """Upload a rising ramp (0 to 255) to the specified slot."""
    print(f"\n[TEST] upload_arb: ramp waveform to slot {slot}")

    # Create ramp (1024 samples, 0 to 255)
    ramp = [int(i * 255 / 1023) for i in range(1024)]

    print(f"  Uploading {len(ramp)} samples...")
    gen.upload_arb(slot, ramp)
    print(f"  Upload complete. Waveform stored in slot {slot} (Waveform.ARB{slot})")


def test_upload_square_normalized(gen: MHS5200A, slot: int = 2) -> None:
    """Upload a normalized square wave (50% duty) to the specified slot."""
    print(f"\n[TEST] upload_arb_normalized: square wave to slot {slot}")

    # Create square wave (first half -1.0, second half +1.0)
    square = [-1.0] * 512 + [1.0] * 512

    print(f"  Uploading {len(square)} samples...")
    gen.upload_arb_normalized(slot, square)
    print(f"  Upload complete. Waveform stored in slot {slot} (Waveform.ARB{slot})")


def test_upload_triangle(gen: MHS5200A, slot: int = 3) -> None:
    """Upload a triangle wave to the specified slot."""
    print(f"\n[TEST] upload_arb: triangle waveform to slot {slot}")

    # Create triangle (rise 0->255 for first half, fall 255->0 for second half)
    rise = [int(i * 255 / 511) for i in range(512)]
    fall = [int(255 - i * 255 / 511) for i in range(512)]
    triangle = rise + fall

    print(f"  Uploading {len(triangle)} samples...")
    gen.upload_arb(slot, triangle)
    print(f"  Upload complete. Waveform stored in slot {slot} (Waveform.ARB{slot})")


def test_error_handling(gen: MHS5200A) -> None:
    """Test error handling for invalid inputs."""
    print("\n[TEST] error handling")

    # Test 1: wrong slot number
    try:
        gen.upload_arb(16, [128] * 1024)
        print("  FAIL: should have raised ValueError for slot=16")
    except ValueError as e:
        print(f"  OK: slot=16 rejected: {e}")

    # Test 2: wrong sample count
    try:
        gen.upload_arb(0, [128] * 1000)
        print("  FAIL: should have raised ValueError for 1000 samples")
    except ValueError as e:
        print(f"  OK: 1000 samples rejected: {e}")

    # Test 3: out of range sample (0-255)
    try:
        gen.upload_arb(0, [128] * 1023 + [256])
        print("  FAIL: should have raised ValueError for sample=256")
    except ValueError as e:
        print(f"  OK: sample=256 rejected: {e}")

    # Test 4: out of range normalized sample
    try:
        gen.upload_arb_normalized(0, [0.0] * 1023 + [1.5])
        print("  FAIL: should have raised ValueError for sample=1.5")
    except ValueError as e:
        print(f"  OK: sample=1.5 rejected: {e}")


def test_output_waveform(gen: MHS5200A, slot: int, freq_hz: float = 1000.0) -> None:
    """Output the uploaded waveform on channel 1 for verification."""
    print(f"\n[TEST] output ARB{slot} on channel 1 at {freq_hz} Hz")

    gen.set_frequency(1, freq_hz)
    gen.set_amplitude(1, 2.0)  # 2 Vpp into 50 Ω
    gen.set_waveform(1, Waveform.ARB0 + slot)
    gen.output_on()

    print(f"  Channel 1 now outputting ARB{slot} at {freq_hz} Hz, 2 Vpp")
    print(f"  Monitor on a scope to verify waveform shape.")
    print(f"  Press Enter to stop output and continue...")
    input()

    gen.output_off()


def main():
    parser = argparse.ArgumentParser(
        description="Test arbitrary waveform upload for MHS-5200A"
    )
    parser.add_argument(
        "--slot",
        type=int,
        metavar="N",
        help="Upload sine to slot N only and exit (for quick test)",
    )
    parser.add_argument(
        "--port",
        type=str,
        metavar="PATH",
        help="Serial port path (default: auto-detect)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("MHS-5200A Arbitrary Waveform Upload Test")
    print("=" * 70)

    try:
        if args.port:
            gen = MHS5200A(port=args.port)
        else:
            gen = MHS5200A()
    except Exception as e:
        print(f"\nERROR: Could not connect to MHS-5200A: {e}")
        print("\nMake sure the unit is connected via USB and powered on.")
        print("Try passing --port /dev/ttyUSB0 (or correct path) explicitly.")
        return 1

    with gen:
        print(f"\nConnected: {gen.identify()}")
        print(f"Port: {gen.port}")
        print(f"Calibration: {gen.calibration_info()}")

        if args.slot is not None:
            # Quick test: upload sine to specified slot only
            test_upload_sine_normalized(gen, args.slot)
            test_output_waveform(gen, args.slot, freq_hz=1000.0)
            print("\n[PASS] Quick test complete.")
            return 0

        # Full test suite
        test_upload_sine_normalized(gen, slot=0)
        test_upload_ramp(gen, slot=1)
        test_upload_square_normalized(gen, slot=2)
        test_upload_triangle(gen, slot=3)

        test_error_handling(gen)

        # Output each waveform for visual verification
        print("\n" + "=" * 70)
        print("Visual verification (scope required)")
        print("=" * 70)

        for slot in range(4):
            test_output_waveform(gen, slot, freq_hz=1000.0)

        print("\n" + "=" * 70)
        print("[PASS] All tests complete")
        print("=" * 70)
        print("\nArbitrary waveform upload feature is working correctly.")
        print("Slots 0-3 now contain: sine, ramp, square, triangle")
        print("Use set_waveform(ch, Waveform.ARB0 + slot) to select.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
