#!/usr/bin/env python3
"""
arbitrary_waveform.py — Examples of arbitrary waveform generation.

Demonstrates creating and uploading custom waveforms to the MHS-5200A's
16 arbitrary waveform slots (ARB0-ARB15). Each slot stores 1024 samples
at 8-bit resolution (0-255 or normalized -1.0 to +1.0).

Examples:
  - Pure sine waves at various frequencies
  - Multi-cycle waveforms (e.g., 5 cycles of sine in 1024 samples)
  - Pulse trains and bursts
  - Noise (pseudo-random samples)
  - AM modulation envelope
  - Custom sensor simulation waveforms

Hardware requirement: MHS-5200A on default port (auto-detected).
"""

import math
import random
import sys

from rf_bench.koolertron import MHS5200A, Waveform


def example_sine_wave(gen: MHS5200A, slot: int = 0):
    """Upload a single-cycle sine wave."""
    print(f"Example 1: Single-cycle sine wave → slot {slot}")

    sine = [math.sin(2 * math.pi * i / 1024) for i in range(1024)]
    gen.upload_arb_normalized(slot, sine)

    print(f"  Uploaded. Use: gen.set_waveform(ch, Waveform.ARB{slot})")


def example_multi_cycle_sine(gen: MHS5200A, slot: int = 1, cycles: int = 5):
    """Upload multiple cycles of a sine wave in one 1024-sample buffer."""
    print(f"Example 2: {cycles}-cycle sine wave → slot {slot}")

    sine = [math.sin(2 * math.pi * i * cycles / 1024) for i in range(1024)]
    gen.upload_arb_normalized(slot, sine)

    print(f"  Uploaded. When played at 1 kHz, this produces {cycles} kHz.")


def example_pulse_train(gen: MHS5200A, slot: int = 2, pulse_width: int = 50):
    """Upload a pulse train (narrow pulses)."""
    print(f"Example 3: Pulse train (width={pulse_width} samples) → slot {slot}")

    # 10 pulses, each `pulse_width` samples wide, separated by 52 samples
    pulse_period = 102  # ~10 pulses in 1024 samples
    samples = []
    for i in range(1024):
        phase = i % pulse_period
        samples.append(1.0 if phase < pulse_width else -1.0)

    gen.upload_arb_normalized(slot, samples)

    print(f"  Uploaded. Outputs narrow pulses at ~1/10 of set frequency.")


def example_am_envelope(gen: MHS5200A, slot: int = 3, carrier_cycles: int = 50):
    """Upload an AM-modulated carrier (carrier × envelope)."""
    print(f"Example 4: AM envelope ({carrier_cycles} carrier cycles) → slot {slot}")

    # Carrier: high-frequency sine
    # Envelope: low-frequency sine (modulation)
    samples = []
    for i in range(1024):
        carrier = math.sin(2 * math.pi * i * carrier_cycles / 1024)
        envelope = 0.5 + 0.5 * math.sin(2 * math.pi * i / 1024)  # 0 to 1
        samples.append(carrier * envelope)

    gen.upload_arb_normalized(slot, samples)

    print(f"  Uploaded. Simulates amplitude modulation.")


def example_noise(gen: MHS5200A, slot: int = 4):
    """Upload pseudo-random noise."""
    print(f"Example 5: Pseudo-random noise → slot {slot}")

    random.seed(42)  # reproducible noise
    noise = [random.uniform(-1.0, 1.0) for _ in range(1024)]
    gen.upload_arb_normalized(slot, noise)

    print(f"  Uploaded. Outputs band-limited pseudo-random noise.")


def example_sawtooth_burst(gen: MHS5200A, slot: int = 5, burst_count: int = 3):
    """Upload a burst of sawtooth waves."""
    print(f"Example 6: {burst_count} sawtooth bursts → slot {slot}")

    samples = []
    samples_per_burst = 1024 // (burst_count * 2)  # half-period for burst, half for silence

    for burst_idx in range(burst_count):
        # Rising sawtooth
        for i in range(samples_per_burst):
            samples.append(2.0 * i / samples_per_burst - 1.0)
        # Silence
        samples.extend([0.0] * samples_per_burst)

    # Pad to 1024 if needed
    while len(samples) < 1024:
        samples.append(0.0)

    gen.upload_arb_normalized(slot, samples[:1024])

    print(f"  Uploaded. Outputs {burst_count} sawtooth bursts per cycle.")


def example_exponential_decay(gen: MHS5200A, slot: int = 6, tau: float = 0.3):
    """Upload an exponential decay waveform (e.g., RC discharge)."""
    print(f"Example 7: Exponential decay (tau={tau}) → slot {slot}")

    samples = []
    for i in range(1024):
        t = i / 1024.0
        value = math.exp(-t / tau)  # 0 to 1 range, decaying
        # Normalize to -1 to +1
        samples.append(2 * value - 1)

    gen.upload_arb_normalized(slot, samples)

    print(f"  Uploaded. Simulates exponential decay (e.g., capacitor discharge).")


def example_custom_sensor_signal(gen: MHS5200A, slot: int = 7):
    """Upload a custom sensor waveform (e.g., ECG-like or audio envelope)."""
    print(f"Example 8: Custom sensor signal (ECG-like) → slot {slot}")

    # Simplified ECG-like waveform: P wave, QRS complex, T wave
    samples = [0.0] * 1024

    # P wave (small sine bump)
    for i in range(100, 200):
        t = (i - 100) / 100.0
        samples[i] = 0.2 * math.sin(math.pi * t)

    # QRS complex (sharp spike)
    for i in range(300, 320):
        t = (i - 310) / 10.0
        samples[i] = math.exp(-(t ** 2))  # Gaussian spike

    # T wave (wider sine bump)
    for i in range(400, 600):
        t = (i - 400) / 200.0
        samples[i] = 0.3 * math.sin(math.pi * t)

    gen.upload_arb_normalized(slot, samples)

    print(f"  Uploaded. Simulates a custom sensor waveform.")


def main():
    print("=" * 70)
    print("MHS-5200A Arbitrary Waveform Examples")
    print("=" * 70)

    try:
        gen = MHS5200A()
    except Exception as e:
        print(f"\nERROR: Could not connect: {e}")
        return 1

    with gen:
        print(f"\nConnected: {gen.identify()}\n")

        # Upload all example waveforms to slots 0-7
        example_sine_wave(gen, slot=0)
        example_multi_cycle_sine(gen, slot=1, cycles=5)
        example_pulse_train(gen, slot=2, pulse_width=50)
        example_am_envelope(gen, slot=3, carrier_cycles=50)
        example_noise(gen, slot=4)
        example_sawtooth_burst(gen, slot=5, burst_count=3)
        example_exponential_decay(gen, slot=6, tau=0.3)
        example_custom_sensor_signal(gen, slot=7)

        print("\n" + "=" * 70)
        print("All examples uploaded successfully")
        print("=" * 70)
        print("\nTo use these waveforms:")
        print("  gen.set_waveform(1, Waveform.ARB0)  # sine")
        print("  gen.set_waveform(1, Waveform.ARB1)  # 5-cycle sine")
        print("  gen.set_waveform(1, Waveform.ARB2)  # pulse train")
        print("  ... etc (ARB0 through ARB7)")
        print("\nSlots 8-15 are still available for your own waveforms.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
