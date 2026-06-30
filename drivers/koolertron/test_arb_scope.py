#!/usr/bin/env python3
"""
Scope verification script for arbitrary waveforms.
Connect channel 1 output to oscilloscope before running.

Usage:
    python3 test_arb_scope.py [--port /dev/ttyUSB0]
"""

import argparse
import math
import sys

sys.path.insert(0, ".")
from rf_bench.koolertron import MHS5200A, Waveform


def test_sine(gen):
    """Test 1: Clean sine wave at 100 Hz."""
    print("\n" + "=" * 60)
    print("Test 1: Sine Wave")
    print("=" * 60)
    print("Uploading sine wave to slot 0...")

    sine = [math.sin(2 * math.pi * i / 1024) for i in range(1024)]
    gen.upload_arb_normalized(0, sine)

    print("Setting output: 100 Hz, 2 Vpp")
    gen.set_frequency(1, 100)
    gen.set_amplitude(1, 2.0)
    gen.set_waveform(1, Waveform.ARB0)
    gen.output_on()

    print("\nScope check:")
    print("  - Expect: Clean sine wave")
    print("  - Frequency: ~100 Hz (period ~10 ms)")
    print("  - Amplitude: ~2 Vpp")
    print("  - Scope settings: 2 ms/div, 500 mV/div, DC coupling, 50 Ω")

    input("\nPress Enter when verification complete...")
    gen.output_off()


def test_ramp(gen):
    """Test 2: Rising ramp (sawtooth)."""
    print("\n" + "=" * 60)
    print("Test 2: Ramp (Sawtooth)")
    print("=" * 60)
    print("Uploading ramp to slot 1...")

    ramp = [int(i * 255 / 1023) for i in range(1024)]
    gen.upload_arb(1, ramp)

    print("Setting output: 100 Hz")
    gen.set_frequency(1, 100)
    gen.set_waveform(1, Waveform.ARB1)
    gen.output_on()

    print("\nScope check:")
    print("  - Expect: Linear rising ramp with sharp reset")
    print("  - Should be smooth (DAC interpolates between samples)")

    input("\nPress Enter when verification complete...")
    gen.output_off()


def test_square(gen):
    """Test 3: 50% duty square wave."""
    print("\n" + "=" * 60)
    print("Test 3: Square Wave")
    print("=" * 60)
    print("Uploading square wave to slot 2...")

    square = [-1.0] * 512 + [1.0] * 512
    gen.upload_arb_normalized(2, square)

    print("Setting output: 1 kHz")
    gen.set_frequency(1, 1000)
    gen.set_waveform(1, Waveform.ARB2)
    gen.output_on()

    print("\nScope check:")
    print("  - Expect: 50% duty cycle square wave")
    print("  - Sharp transitions")
    print("  - Flat top and bottom")

    input("\nPress Enter when verification complete...")
    gen.output_off()


def test_multi_cycle(gen):
    """Test 4: Multi-cycle sine (5 cycles per period = 5× frequency)."""
    print("\n" + "=" * 60)
    print("Test 4: Multi-Cycle Sine (5× Frequency Multiplier)")
    print("=" * 60)
    print("Uploading 5-cycle sine to slot 3...")

    sine_5x = [math.sin(2 * math.pi * i * 5 / 1024) for i in range(1024)]
    gen.upload_arb_normalized(3, sine_5x)

    print("Setting output: 100 Hz (will produce 500 Hz effective)")
    gen.set_frequency(1, 100)
    gen.set_waveform(1, Waveform.ARB3)
    gen.output_on()

    print("\nScope check:")
    print("  - Expect: 5 complete sine cycles per period")
    print("  - Effective frequency: ~500 Hz")
    print("  - No discontinuities at boundaries")

    input("\nPress Enter when verification complete...")
    gen.output_off()


def test_pulse(gen):
    """Test 5: Narrow pulse train."""
    print("\n" + "=" * 60)
    print("Test 5: Pulse Train")
    print("=" * 60)
    print("Uploading pulse train to slot 4...")

    pulse = [1.0 if (i % 102) < 5 else -1.0 for i in range(1024)]
    gen.upload_arb_normalized(4, pulse)

    print("Setting output: 100 Hz")
    gen.set_frequency(1, 100)
    gen.set_waveform(1, Waveform.ARB4)
    gen.output_on()

    print("\nScope check:")
    print("  - Expect: ~10 narrow pulses per period")
    print("  - Pulse width: ~0.5 ms (5 samples)")
    print("  - Sharp edges")

    input("\nPress Enter when verification complete...")
    gen.output_off()


def test_frequency_accuracy(gen):
    """Test 6: Frequency accuracy at multiple settings."""
    print("\n" + "=" * 60)
    print("Test 6: Frequency Accuracy")
    print("=" * 60)
    print("Using sine wave from slot 0...")

    gen.set_waveform(1, Waveform.ARB0)

    for freq in [100, 1000, 10000, 100000]:
        print(f"\nSetting frequency to {freq} Hz...")
        gen.set_frequency(1, freq)
        gen.output_on()

        print(f"  Scope check: Verify frequency ≈ {freq} Hz (±1%)")
        input("  Press Enter when verified...")

        gen.output_off()


def test_amplitude_accuracy(gen):
    """Test 7: Amplitude accuracy at multiple settings."""
    print("\n" + "=" * 60)
    print("Test 7: Amplitude Accuracy")
    print("=" * 60)
    print("Using sine wave from slot 0 at 1 kHz...")

    gen.set_waveform(1, Waveform.ARB0)
    gen.set_frequency(1, 1000)

    for amp in [0.5, 1.0, 2.0, 4.0]:
        print(f"\nSetting amplitude to {amp} Vpp...")
        gen.set_amplitude(1, amp)
        gen.output_on()

        print(f"  Scope check: Measure Vpp ≈ {amp} V (±10%)")
        print(f"  Use scope's measurement function for accuracy")
        input("  Press Enter when verified...")

        gen.output_off()


def main():
    parser = argparse.ArgumentParser(
        description="Scope verification for MHS-5200A arbitrary waveforms"
    )
    parser.add_argument(
        "--port",
        type=str,
        default="/dev/ttyUSB0",
        help="Serial port (default: /dev/ttyUSB0)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("MHS-5200A Arbitrary Waveform Scope Verification")
    print("=" * 60)
    print("\nPREREQUISITES:")
    print("  - Connect CH1 output to oscilloscope")
    print("  - Set scope to 50 Ω input impedance")
    print("  - DC coupling")
    print("  - Rising edge trigger at ~0V")
    print(f"  - Device on {args.port}")

    input("\nPress Enter when scope is connected and ready...")

    try:
        gen = MHS5200A(port=args.port)
    except Exception as e:
        print(f"\nERROR: Could not connect to device: {e}")
        return 1

    with gen:
        print(f"\nConnected: {gen.identify()}")
        print(f"Port: {gen.port}")

        try:
            # Run all tests
            test_sine(gen)
            test_ramp(gen)
            test_square(gen)
            test_multi_cycle(gen)
            test_pulse(gen)
            test_frequency_accuracy(gen)
            test_amplitude_accuracy(gen)

            # Final summary
            print("\n" + "=" * 60)
            print("All tests complete!")
            print("=" * 60)
            print("\nIf all waveforms matched expectations:")
            print("  1. Document results in SCOPE_VERIFICATION_RESULTS.md")
            print("  2. Update README.md status to 'scope-verified'")
            print("  3. Bump version to 0.2.0 in pyproject.toml")
            print("  4. Git commit and push")
            print("  5. Optionally publish to PyPI")
            print("\nOtherwise, document issues and resolve before release.")

        except KeyboardInterrupt:
            print("\n\nTest interrupted by user.")
            return 1

        finally:
            gen.output_off()

    return 0


if __name__ == "__main__":
    sys.exit(main())
