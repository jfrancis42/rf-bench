#!/usr/bin/env python3
"""
Simple non-interactive test of arbitrary waveform upload.
Just uploads a sine wave to slot 0 and reports success/failure.
"""

import math
import sys
sys.path.insert(0, ".")

from rf_bench.koolertron import MHS5200A, Waveform

def main():
    print("Connecting to MHS-5200A on /dev/ttyUSB0...")

    try:
        gen = MHS5200A(port="/dev/ttyUSB0")
    except Exception as e:
        print(f"ERROR: Could not connect: {e}")
        return 1

    with gen:
        print(f"Connected: {gen.identify()}")
        print(f"Port: {gen.port}")

        # Create sine wave
        print("\nCreating sine wave (1024 samples)...")
        sine = [math.sin(2 * math.pi * i / 1024) for i in range(1024)]

        # Upload to slot 0
        print("Uploading to slot 0...")
        try:
            gen.upload_arb_normalized(0, sine)
            print("✓ Upload successful!")
        except Exception as e:
            print(f"✗ Upload failed: {e}")
            return 1

        # Try to select it
        print("\nSetting waveform to ARB0 on channel 1...")
        try:
            gen.set_waveform(1, Waveform.ARB0)
            print("✓ Waveform selection successful!")
        except Exception as e:
            print(f"✗ Waveform selection failed: {e}")
            return 1

        # Verify it was set
        print("\nReading back waveform setting...")
        try:
            wf = gen.get_waveform(1)
            if wf == Waveform.ARB0:
                print(f"✓ Waveform readback correct: {wf} (ARB0={Waveform.ARB0})")
            else:
                print(f"✗ Waveform readback mismatch: got {wf}, expected {Waveform.ARB0}")
                return 1
        except Exception as e:
            print(f"✗ Waveform readback failed: {e}")
            return 1

        print("\n" + "="*60)
        print("SUCCESS: Arbitrary waveform upload working correctly!")
        print("="*60)

    return 0

if __name__ == "__main__":
    sys.exit(main())
