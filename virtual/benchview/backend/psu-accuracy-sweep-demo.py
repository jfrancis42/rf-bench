#!/usr/bin/env python3
"""
PSU Accuracy Sweep - Demo Mode (Simulated Instruments)

This is a demonstration version that simulates the PSU and DMM
to show how the automation framework works without hardware.

The simulated instruments add realistic measurement errors:
- Voltage: ±0.5% + 5mV offset
- Current: ±1%
- Random noise: ±2mV

This produces realistic-looking data that shows the framework capabilities.
"""

import time
import numpy as np
from pathlib import Path

from rf_bench.automation import MeasurementSequence


class SimulatedPSU:
    """Simulated SPD3303X power supply."""

    def __init__(self):
        self._voltage = [0.0, 0.0, 0.0]
        self._current = [0.0, 0.0, 0.0]
        self._enabled = [False, False, False]
        self._load_resistance = 10.0  # 10 ohm load

    def identify(self):
        return "Siglent Technologies,SPD3303X-E,SPD3XDEMO,1.01"

    def set_voltage(self, channel, voltage):
        self._voltage[channel-1] = voltage

    def set_current(self, channel, current):
        self._current[channel-1] = current

    def enable(self, channel):
        self._enabled[channel-1] = True

    def disable(self, channel):
        self._enabled[channel-1] = False

    def measure_current(self, channel):
        """Simulate current measurement (V/R with some error)."""
        if not self._enabled[channel-1]:
            return 0.0

        voltage = self._voltage[channel-1]
        current_limit = self._current[channel-1]

        # Ohm's law with load
        ideal_current = voltage / self._load_resistance

        # Current limited?
        actual_current = min(ideal_current, current_limit)

        # Add measurement error (±1%)
        error = actual_current * 0.01 * np.random.randn()

        return max(0, actual_current + error)

    def close(self):
        pass


class SimulatedDMM:
    """Simulated SDM3045X multimeter."""

    def __init__(self, psu):
        self._psu = psu
        self._mode = 'VDC'

    def identify(self):
        return "Siglent Technologies,SDM3045X,SDM3XDEMO,1.0"

    def configure_vdc(self):
        self._mode = 'VDC'

    def read(self):
        """Simulate voltage measurement with realistic errors."""
        # Get actual PSU voltage (simulated output)
        voltage = self._psu._voltage[0]  # Channel 1

        if not self._psu._enabled[0]:
            return 0.0

        # Add realistic measurement errors:
        # - Accuracy: ±0.5% of reading
        # - Offset: ±5mV
        # - Noise: ±2mV

        accuracy_error = voltage * 0.005 * np.random.randn()
        offset_error = 0.005 * np.random.randn()
        noise = 0.002 * np.random.randn()

        measured = voltage + accuracy_error + offset_error + noise

        return max(0, measured)

    def close(self):
        pass


def main():
    print("=" * 70)
    print("PSU Accuracy Sweep - DEMO MODE (Simulated Instruments)")
    print("=" * 70)
    print()
    print("NOTE: This is a demonstration using simulated instruments.")
    print("      The data generated is realistic but not from real hardware.")
    print()

    # Create simulated instruments
    print("Creating simulated instruments...")
    psu = SimulatedPSU()
    dmm = SimulatedDMM(psu)
    print(f"  ✓ PSU: {psu.identify()}")
    print(f"  ✓ DMM: {dmm.identify()}")
    print()

    # Create measurement sequence
    seq = MeasurementSequence(
        name="SPD3303X Accuracy Characterization (Demo)",
        description="Voltage and current accuracy vs setpoint - simulated data"
    )

    # Add metadata
    seq.metadata(
        operator='N0GQ',
        dut='SPD3303X-E CH1 (Simulated)',
        dmm='SDM3045X (Simulated)',
        load='10 ohm power resistor',
        temperature_c=23.5,
        tags=['power-supply', 'accuracy', 'demo', 'simulated']
    )

    # Define measurement steps
    @seq.step("Configure PSU")
    def setup_psu(psu):
        """Configure PSU channel 1 with setpoints from context."""
        voltage = seq.context['voltage_set']
        current = seq.context['current_limit']

        psu.set_voltage(1, voltage)
        psu.set_current(1, current)
        psu.enable(1)

        time.sleep(0.01)  # Settling time (faster for demo)

    @seq.step("Measure Voltage")
    def measure_voltage(dmm):
        """Measure actual output voltage with DMM."""
        dmm.configure_vdc()
        time.sleep(0.005)  # DMM settling (faster for demo)

        voltage_measured = dmm.read()

        return {'voltage_measured': voltage_measured}

    @seq.step("Measure Current")
    def measure_current(psu):
        """Read actual current draw from PSU."""
        current_measured = psu.measure_current(1)

        return {'current_measured': current_measured}

    @seq.step("Calculate Metrics")
    def calculate_metrics():
        """Calculate error and power."""
        voltage_set = seq.context['voltage_set']
        voltage_measured = seq.context['voltage_measured']
        current_limit = seq.context['current_limit']
        current_measured = seq.context['current_measured']

        # Voltage error
        voltage_error = voltage_measured - voltage_set
        voltage_error_percent = (voltage_error / voltage_set) * 100 if voltage_set > 0 else 0

        # Current error
        current_error = current_measured - current_limit

        # Power
        power_set = voltage_set * current_limit
        power_measured = voltage_measured * current_measured
        power_error = power_measured - power_set
        power_error_percent = (power_error / power_set) * 100 if power_set > 0 else 0

        return {
            'voltage_error_v': voltage_error,
            'voltage_error_pct': voltage_error_percent,
            'current_error_a': current_error,
            'power_set_w': power_set,
            'power_measured_w': power_measured,
            'power_error_w': power_error,
            'power_error_pct': power_error_percent
        }

    # Run voltage sweep at fixed current
    print("Starting voltage sweep...")
    print("(Demo mode: faster than real hardware)")
    print()

    # Sweep voltages from 1V to 30V (20 points)
    voltages = np.linspace(1.0, 30.0, 20)
    current_limit = 0.5  # 500mA constant current limit

    results_voltage = []

    for i, voltage in enumerate(voltages, 1):
        # Update context
        seq.context['voltage_set'] = voltage
        seq.context['current_limit'] = current_limit

        # Run measurement steps
        step_results = seq.run_steps(
            instruments={'psu': psu, 'dmm': dmm},
            skip_steps=[]
        )

        # Pass measurements to context for calculate step
        seq.context['voltage_measured'] = step_results['measure_voltage']['voltage_measured']
        seq.context['current_measured'] = step_results['measure_current']['current_measured']

        # Collect results
        result = {
            'voltage_set': voltage,
            'current_limit': current_limit,
            'voltage_measured': step_results['measure_voltage']['voltage_measured'],
            'current_measured': step_results['measure_current']['current_measured'],
            **step_results['calculate_metrics']
        }

        results_voltage.append(result)

        # Progress indicator
        if i % 5 == 0 or i == len(voltages):
            print(f"  Progress: {i}/{len(voltages)} points")

    # Add voltage sweep results to log
    for result in results_voltage:
        seq.log.append(result)

    # Save voltage sweep
    voltage_sweep_path = seq.save(filename='psu_accuracy_voltage_sweep_demo')
    print(f"\n✓ Voltage sweep complete: {voltage_sweep_path}")

    # Now sweep current at fixed voltage
    print("\nStarting current sweep...")

    # New sequence for current sweep
    seq2 = MeasurementSequence(
        name="SPD3303X Current Accuracy (Demo)",
        description="Current limit accuracy vs setpoint - simulated data"
    )

    seq2.metadata(
        operator='N0GQ',
        dut='SPD3303X-E CH1 (Simulated)',
        dmm='SDM3045X (Simulated)',
        load='10 ohm power resistor',
        temperature_c=23.5,
        tags=['power-supply', 'accuracy', 'current', 'demo', 'simulated']
    )

    voltage_set = 10.0  # Fixed 10V
    currents = np.linspace(0.1, 3.0, 15)

    results_current = []

    for i, current in enumerate(currents, 1):
        psu.set_voltage(1, voltage_set)
        psu.set_current(1, current)
        psu.enable(1)
        time.sleep(0.01)

        voltage_measured = dmm.read()
        current_measured = psu.measure_current(1)

        # Calculate metrics
        current_error = current_measured - current
        power_set = voltage_set * current
        power_measured = voltage_measured * current_measured
        power_error = power_measured - power_set

        result = {
            'voltage_set': voltage_set,
            'current_limit': current,
            'voltage_measured': voltage_measured,
            'current_measured': current_measured,
            'current_error_a': current_error,
            'power_set_w': power_set,
            'power_measured_w': power_measured,
            'power_error_w': power_error
        }

        results_current.append(result)
        seq2.log.append(result)

        # Progress indicator
        if i % 5 == 0 or i == len(currents):
            print(f"  Progress: {i}/{len(currents)} points")

    # Save current sweep
    current_sweep_path = seq2.save(filename='psu_accuracy_current_sweep_demo')
    print(f"✓ Current sweep complete: {current_sweep_path}")

    # Print summary statistics
    print("\n" + "=" * 70)
    print("Summary Statistics")
    print("=" * 70)

    voltage_errors = [r['voltage_error_v'] for r in results_voltage]
    power_errors = [r['power_error_w'] for r in results_voltage]

    print("\nVoltage Accuracy (1V to 30V):")
    print(f"  Mean error:   {np.mean(voltage_errors):+.4f} V")
    print(f"  Std dev:      {np.std(voltage_errors):.4f} V")
    print(f"  Max error:    {np.max(np.abs(voltage_errors)):.4f} V")
    print(f"  RMS error:    {np.sqrt(np.mean(np.array(voltage_errors)**2)):.4f} V")

    print("\nPower Accuracy (voltage sweep):")
    print(f"  Mean error:   {np.mean(power_errors):+.4f} W")
    print(f"  Max error:    {np.max(np.abs(power_errors)):.4f} W")

    current_errors = [r['current_error_a'] for r in results_current]

    print("\nCurrent Accuracy (0.1A to 3.0A):")
    print(f"  Mean error:   {np.mean(current_errors):+.4f} A")
    print(f"  Std dev:      {np.std(current_errors):.4f} A")
    print(f"  Max error:    {np.max(np.abs(current_errors)):.4f} A")

    # Show sample data points
    print("\n" + "=" * 70)
    print("Sample Data Points (first 5 from voltage sweep)")
    print("=" * 70)
    print(f"\n{'Set V':>7}  {'Meas V':>7}  {'Error V':>8}  {'Set W':>7}  {'Meas W':>7}  {'Error W':>8}")
    print("-" * 70)

    for r in results_voltage[:5]:
        print(f"{r['voltage_set']:>7.2f}  {r['voltage_measured']:>7.3f}  "
              f"{r['voltage_error_v']:>+8.3f}  {r['power_set_w']:>7.2f}  "
              f"{r['power_measured_w']:>7.3f}  {r['power_error_w']:>+8.3f}")

    # Cleanup
    print("\n" + "=" * 70)
    print("Cleaning up...")
    psu.set_voltage(1, 0.0)
    psu.disable(1)
    psu.close()
    dmm.close()

    print("Done!")
    print()
    print("=" * 70)
    print("Data saved to:")
    print(f"  {voltage_sweep_path}")
    print(f"  {current_sweep_path}")
    print()
    print("Try these commands:")
    print("  # View recent measurements")
    print("  rf-bench-data recent")
    print()
    print("  # Search for power supply tests")
    print("  rf-bench-data search --tags power-supply")
    print()
    print("  # Show database statistics")
    print("  rf-bench-data stats")
    print()
    print("  # Inspect a specific measurement")
    print(f"  rf-bench-data inspect {voltage_sweep_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
