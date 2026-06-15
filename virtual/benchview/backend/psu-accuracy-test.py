#!/usr/bin/env python3
"""
PSU Accuracy Test - Automation Framework Demo

Simple voltage accuracy test that sweeps the PSU from 1V to 3V
and measures actual output with the DMM.

Shows how the automation framework reduces boilerplate and
provides automatic logging with metadata.

Hardware setup:
  SPD3303X CH1+ → 1Ω 20W load → SDM3045X VΩ input
  SPD3303X CH1- → SDM3045X COM

Load: 1Ω, 20W max (√20 = 4.47A max, but PSU limited to 3.2A)
Max safe: 3.2V @ 3.2A = 10.24W

Usage:
  python3 psu-accuracy-test.py
"""

import time
import numpy as np
from rf_bench.instruments import Registry
from rf_bench.automation import MeasurementSequence


def main():
    print("\n" + "=" * 70)
    print("PSU Accuracy Test - Automation Framework Demo")
    print("=" * 70)
    print()

    # Connect to instruments via registry
    print("Connecting to instruments...")
    registry = Registry()

    try:
        psu = registry.get('power-supply')
        dmm = registry.get('multimeter')
        print(f"  ✓ PSU: {psu.identify()}")
        print(f"  ✓ DMM: {dmm.identify()}")
    except Exception as e:
        print(f"ERROR: Failed to connect: {e}")
        return 1

    # Initialize PSU - start with output OFF
    print("\nInitializing PSU...")
    psu.set_voltage(1, 0.0)
    psu.set_current(1, 3.2)  # Max current for 1Ω load (10.24W at 3.2V)
    psu.disable(1)
    print("  ✓ PSU CH1 initialized (output OFF)")
    print()

    # Create measurement sequence
    seq = MeasurementSequence(
        name="SPD3303X Voltage Accuracy Test",
        description="Measure PSU output accuracy from 1V to 12V"
    )

    # Add metadata
    seq.metadata(
        operator='N0GQ',
        dut='SPD3303X-E CH1',
        dmm='SDM3045X',
        load='1 ohm 20W resistor',
        current_limit='3.2A',
        max_power='10.24W at 3.2V',
        temperature_c=23.5,
        tags=['power-supply', 'accuracy', 'voltage', '1ohm-load']
    )

    # Define measurement steps
    @seq.step("Configure PSU")
    def setup_psu(psu):
        """Set PSU to specified voltage."""
        v_set = seq.context['voltage_set']
        psu.set_voltage(1, v_set)
        psu.set_current(1, 3.2)  # Max current (3.2A into 1Ω = 10.24W, safe for 20W resistor)
        psu.enable(1)
        time.sleep(0.2)  # Settling time

    @seq.step("Measure Voltage")
    def measure_voltage(dmm):
        """Measure actual voltage with DMM."""
        dmm.configure_vdc()
        time.sleep(0.1)
        v_measured = dmm.read()
        return {'voltage_measured': v_measured}

    # Run voltage sweep (limited by 1Ω load and 20W resistor rating)
    # Max safe: 3.2V @ 3.2A = 10.24W (well under 20W limit)
    print("Sweeping voltage from 1V to 3V (20 points)...")
    print("Load: 1Ω, 20W resistor  |  Current limit: 3.2A  |  Max power: 10.24W")
    print()
    print(f"{'Point':>6}  {'Set V':>7}  {'Measured V':>10}  {'Error V':>9}  {'Error %':>9}")
    print("-" * 70)

    voltages = np.linspace(1.0, 3.0, 20)
    results = []

    for i, v_set in enumerate(voltages, 1):
        # Set sweep parameter in context
        seq.context['voltage_set'] = v_set

        # Run measurement steps
        step_results = seq.run_steps(instruments={'psu': psu, 'dmm': dmm})

        # Extract measured value
        v_measured = step_results['measure_voltage']['voltage_measured']

        # Calculate error
        v_error = v_measured - v_set
        v_error_pct = (v_error / v_set) * 100

        # Store result
        result = {
            'voltage_set': v_set,
            'voltage_measured': v_measured,
            'voltage_error': v_error,
            'voltage_error_pct': v_error_pct
        }
        results.append(result)

        # Print progress
        print(f"{i:6d}  {v_set:7.2f}  {v_measured:10.4f}  {v_error:+9.4f}  {v_error_pct:+9.3f}%")

        # Add to measurement log
        seq._log.append(result)

    # Save results
    print()
    print("Saving results...")
    path = seq.save()
    print(f"✓ Data saved: {path}")

    # Calculate and display statistics
    print()
    print("=" * 70)
    print("Summary Statistics")
    print("=" * 70)

    v_errors = [r['voltage_error'] for r in results]
    v_errors_pct = [r['voltage_error_pct'] for r in results]

    print(f"\nVoltage Accuracy (1V to 3V with 1Ω load):")
    print(f"  Mean error:       {np.mean(v_errors):+.5f} V  ({np.mean(v_errors_pct):+.3f}%)")
    print(f"  Std deviation:     {np.std(v_errors):.5f} V  ({np.std(v_errors_pct):.3f}%)")
    print(f"  Max error:         {np.max(np.abs(v_errors)):.5f} V  ({np.max(np.abs(v_errors_pct)):.3f}%)")
    print(f"  RMS error:         {np.sqrt(np.mean(np.array(v_errors)**2)):.5f} V")

    # Find best and worst points
    best_idx = np.argmin(np.abs(v_errors))
    worst_idx = np.argmax(np.abs(v_errors))

    print(f"\n  Best accuracy:     {results[best_idx]['voltage_set']:.2f}V "
          f"(error: {results[best_idx]['voltage_error']:+.5f}V)")
    print(f"  Worst accuracy:    {results[worst_idx]['voltage_set']:.2f}V "
          f"(error: {results[worst_idx]['voltage_error']:+.5f}V)")

    # Cleanup - turn off PSU output
    print()
    print("=" * 70)
    print("Cleaning up...")
    psu.set_voltage(1, 0.0)
    psu.set_current(1, 0.1)
    psu.disable(1)
    print("  ✓ PSU CH1 output disabled")
    psu.close()
    dmm.close()

    print("Done!")
    print()
    print("=" * 70)
    print("Next steps:")
    print()
    print("  # View recent measurements")
    print("  rf-bench-data recent")
    print()
    print("  # Search for power supply tests")
    print("  rf-bench-data search --tags power-supply")
    print()
    print("  # Show database statistics")
    print("  rf-bench-data stats")
    print()
    print("  # Inspect this measurement")
    print(f"  rf-bench-data inspect {path}")
    print("=" * 70)
    print()

    return 0


if __name__ == "__main__":
    exit(main())
