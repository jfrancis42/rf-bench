#!/usr/bin/env python3
"""
PSU Accuracy Sweep with Automation Framework

Automated characterization of SPD3303X power supply accuracy:
- Sweeps voltage from 1V to 30V
- Sweeps current limit from 0.1A to 3A
- Measures actual output with SDM3045X
- Calculates set vs measured error
- Displays live results on virtual instruments
- Logs data with metadata for later analysis

This demonstrates the automation framework on a multi-instrument task.

Hardware setup:
  SPD3303X CH1+ → SDM3045X VΩ input (red) → 10Ω power resistor → CH1-
  SDM3303X CH1- → SDM3045X COM (black)

  10Ω resistor provides load for current testing

BenchView virtual instruments:
  - Bar graph: Shows voltage error in real-time
  - Numeric display: Current voltage reading
  - LED: Indicates measurement in progress

Usage:
  1. Start BenchView with psu-accuracy-sweep.yaml
  2. Run this script
  3. Open browser to http://localhost:8200 to watch live
  4. Results saved to ~/.rf-bench/data/
"""

import sys
import time
import yaml
import numpy as np
from pathlib import Path

from rf_bench.instruments import Registry
from rf_bench.automation import MeasurementSequence


def main():
    print("=" * 70)
    print("PSU Accuracy Sweep - Automation Framework Demo")
    print("=" * 70)
    print()

    # Load BenchView port assignments
    ports_file = Path(__file__).parent / "psu-accuracy-sweep_ports.yaml"

    # If BenchView not running, can still do measurement without display
    use_display = ports_file.exists()

    if use_display:
        with open(ports_file) as f:
            ports_data = yaml.safe_load(f)

        bar_port = ports_data['instruments']['error-bar']['scpi_port']
        display_port = ports_data['instruments']['voltage-display']['scpi_port']
        led_port = ports_data['instruments']['status-led']['scpi_port']

        print("BenchView display detected:")
        print(f"  Bar graph:  port {bar_port}")
        print(f"  Display:    port {display_port}")
        print(f"  Status LED: port {led_port}")
        print()

        # Import virtual instrument drivers
        from rf_bench.virtual import VirtualBarGraphMulti, VirtualNumericDisplayMulti, VirtualLEDMulti

        bar = VirtualBarGraphMulti('localhost', port=bar_port)
        display = VirtualNumericDisplayMulti('localhost', port=display_port)
        led = VirtualLEDMulti('localhost', port=led_port)

        # Configure display
        display.set_style(1, 'NIXIE')
        display.set_color(1, '#00ff00')
        display.set_precision(1, 3)
        display.set_units(1, 'V')

        # Configure bar graph (±1V error range)
        bar.set_min(1, -1.0)
        bar.set_max(1, 1.0)
        bar.set_label(1, 'Voltage Error')
        bar.set_units(1, 'V')

        # LED off initially
        led.off(1)
    else:
        print("BenchView display not detected (optional)")
        print("Measurement will proceed without live display")
        print()

    # Connect to physical instruments via registry
    print("Connecting to instruments...")
    registry = Registry()

    try:
        psu = registry.get('power-supply')
        dmm = registry.get('multimeter')
        print(f"  ✓ PSU: {psu.identify()}")
        print(f"  ✓ DMM: {dmm.identify()}")
    except Exception as e:
        print(f"ERROR: Failed to connect to instruments: {e}")
        print("Check that SPD3303X and SDM3045X are powered on and in registry.")
        sys.exit(1)

    print()

    # Create measurement sequence
    seq = MeasurementSequence(
        name="SPD3303X Accuracy Characterization",
        description="Voltage and current accuracy vs setpoint"
    )

    # Add metadata
    seq.metadata(
        operator='N0GQ',
        dut='SPD3303X-E CH1',
        dmm='SDM3045X',
        load='10 ohm power resistor',
        temperature_c=23.5,
        tags=['power-supply', 'accuracy', 'calibration']
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

        time.sleep(0.1)  # Settling time

    @seq.step("Measure Voltage")
    def measure_voltage(dmm):
        """Measure actual output voltage with DMM."""
        if use_display:
            led.on(1)  # Indicate measurement in progress

        dmm.configure_vdc()
        time.sleep(0.05)  # DMM settling

        voltage_measured = dmm.read()

        return {'voltage_measured': voltage_measured}

    @seq.step("Measure Current")
    def measure_current(psu):
        """Read actual current draw from PSU."""
        # PSU measures output current
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

        # Update display
        if use_display:
            display.set_value(1, voltage_measured)
            bar.set_value(1, voltage_error)
            led.off(1)

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
    print("This will take about 2 minutes")
    print()

    if use_display:
        print("Watch the live display at http://localhost:8200")
        print()

    # Sweep voltages from 1V to 30V (20 points)
    voltages = np.linspace(1.0, 30.0, 20)
    current_limit = 0.5  # 500mA constant current limit

    results_voltage = []

    for voltage in voltages:
        # Update context
        seq.context['voltage_set'] = voltage
        seq.context['current_limit'] = current_limit

        # Run measurement steps
        step_results = seq.run_steps(
            instruments={'psu': psu, 'dmm': dmm},
            skip_steps=[]
        )

        # Collect results
        result = {
            'voltage_set': voltage,
            'current_limit': current_limit,
            'voltage_measured': step_results['measure_voltage']['voltage_measured'],
            'current_measured': step_results['measure_current']['current_measured'],
            **step_results['calculate_metrics']
        }

        results_voltage.append(result)

        # Pass context forward
        seq.context['voltage_measured'] = result['voltage_measured']
        seq.context['current_measured'] = result['current_measured']

    # Add voltage sweep results to log
    for result in results_voltage:
        seq.log.append(result)

    # Save voltage sweep
    voltage_sweep_path = seq.save(filename='psu_accuracy_voltage_sweep')
    print(f"\n✓ Voltage sweep complete: {voltage_sweep_path}")

    # Now sweep current at fixed voltage
    print("\nStarting current sweep...")

    # New sequence for current sweep
    seq2 = MeasurementSequence(
        name="SPD3303X Current Accuracy",
        description="Current limit accuracy vs setpoint"
    )

    seq2.metadata(
        operator='N0GQ',
        dut='SPD3303X-E CH1',
        dmm='SDM3045X',
        load='10 ohm power resistor',
        temperature_c=23.5,
        tags=['power-supply', 'accuracy', 'current']
    )

    # Reuse the same steps (they're bound to seq, need to rebind)
    # For simplicity, just run inline here

    voltage_set = 10.0  # Fixed 10V
    currents = np.linspace(0.1, 3.0, 15)

    results_current = []

    for current in currents:
        psu.set_voltage(1, voltage_set)
        psu.set_current(1, current)
        psu.enable(1)
        time.sleep(0.1)

        if use_display:
            led.on(1)

        voltage_measured = dmm.read()
        current_measured = psu.measure_current(1)

        if use_display:
            display.set_value(1, voltage_measured)
            led.off(1)

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

    # Save current sweep
    current_sweep_path = seq2.save(filename='psu_accuracy_current_sweep')
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

    # Cleanup
    print("\n" + "=" * 70)
    print("Cleaning up...")
    psu.set_voltage(1, 0.0)
    psu.disable(1)
    psu.close()
    dmm.close()

    if use_display:
        led.off(1)
        display.set_value(1, 0.0)
        bar.set_value(1, 0.0)

    print("Done!")
    print()
    print("Data saved to:")
    print(f"  {voltage_sweep_path}")
    print(f"  {current_sweep_path}")
    print()
    print("Search your measurements:")
    print("  rf-bench-data search --tags power-supply")
    print()


if __name__ == "__main__":
    main()
