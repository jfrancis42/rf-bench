#!/usr/bin/env python3
"""
Calibration Management Demo

Demonstrates how to:
1. Load calibration files (cable loss, antenna factors)
2. Apply corrections to measurements
3. Create new calibrations programmatically
4. Save calibrations to files

Usage:
  python3 calibration_demo.py
"""

import numpy as np
from rf_bench.automation import CalibrationManager


def demo_cable_loss():
    """Demonstrate cable loss correction."""
    print("\n" + "=" * 70)
    print("CABLE LOSS CORRECTION")
    print("=" * 70)

    # Create calibration manager
    cal = CalibrationManager()

    # Load cable loss calibration
    print("\nLoading cable calibration...")
    cable = cal.load('cables/lmr400_10ft.yaml')

    print(f"  Name: {cable.name}")
    print(f"  Type: {cable.cal_type}")
    print(f"  Description: {cable.description}")
    print(f"  Data points: {len(cable.data)}")
    print(f"  Calibration date: {cable.date}")
    print(f"  Valid until: {cable.valid_until}")

    # Show correction at various frequencies
    print("\n" + "-" * 70)
    print("Cable loss at various frequencies:")
    print("-" * 70)
    print(f"{'Frequency':>15s}  {'Loss (dB)':>10s}")
    print("-" * 70)

    test_freqs = [50e6, 146e6, 450e6, 1296e6, 2400e6]

    for freq in test_freqs:
        loss_db = cable.get_correction(freq)
        print(f"{freq/1e6:>12.0f} MHz  {loss_db:>10.3f} dB")

    # Example: measure power with cable, correct for loss
    print("\n" + "-" * 70)
    print("Example measurement with correction:")
    print("-" * 70)

    freq_mhz = 146
    freq_hz = freq_mhz * 1e6
    measured_power_dbm = -73.5  # What SSA measures at instrument input

    loss_db = cable.get_correction(freq_hz)
    corrected_power_dbm = measured_power_dbm + loss_db

    print(f"Frequency: {freq_mhz} MHz")
    print(f"Measured power (at SSA): {measured_power_dbm:.1f} dBm")
    print(f"Cable loss: {loss_db:.2f} dB")
    print(f"Corrected power (at antenna): {corrected_power_dbm:.1f} dBm")


def demo_batch_correction():
    """Demonstrate batch correction for frequency sweep data."""
    print("\n" + "=" * 70)
    print("BATCH CORRECTION FOR FREQUENCY SWEEP")
    print("=" * 70)

    cal = CalibrationManager()
    cable = cal.load('cables/lmr400_10ft.yaml')

    # Simulate a frequency sweep measurement
    print("\nSimulated frequency sweep (100-1000 MHz):")
    print("-" * 70)

    freqs_mhz = np.linspace(100, 1000, 10)
    freqs_hz = freqs_mhz * 1e6

    # Simulated power measurements (would come from SSA)
    measured_powers = [-70.0 + i * 0.5 for i in range(len(freqs_mhz))]

    # Apply cable loss correction to all points
    corrected_powers = cable.apply_batch(measured_powers, freqs_hz, inverse=False)

    print(f"{'Freq (MHz)':>12s}  {'Measured':>10s}  {'Loss':>10s}  {'Corrected':>10s}")
    print("-" * 70)

    for freq_mhz, meas, corr in zip(freqs_mhz, measured_powers, corrected_powers):
        loss = cable.get_correction(freq_mhz * 1e6)
        print(f"{freq_mhz:>12.0f}  {meas:>10.1f}  {loss:>10.3f}  {corr:>10.1f}")


def demo_create_calibration():
    """Demonstrate creating a calibration programmatically."""
    print("\n" + "=" * 70)
    print("CREATE CALIBRATION PROGRAMMATICALLY")
    print("=" * 70)

    cal = CalibrationManager()

    # Create a custom cable loss calibration
    print("\nCreating custom cable calibration...")

    frequencies_hz = [
        50e6, 146e6, 220e6, 450e6, 900e6, 1296e6, 2400e6
    ]

    # Simulated loss measurements (would come from VNA or cal lab)
    losses_db = [0.15, 0.23, 0.29, 0.42, 0.61, 0.75, 1.1]

    cable = cal.create_cable_loss(
        name='custom_cable_15ft',
        frequencies_hz=frequencies_hz,
        losses_db=losses_db,
        description='Custom cable, 15 feet, measured with VNA',
        date='2026-06-15'
    )

    print(f"  ✓ Created: {cable.name}")
    print(f"    Type: {cable.cal_type}")
    print(f"    Points: {len(cable.data)}")

    # Save to file
    print("\nSaving calibration...")
    cal.save(cable)

    print("  ✓ Saved to ~/.rf-bench/calibrations/custom_cable_15ft.yaml")


def demo_antenna_factor():
    """Demonstrate antenna factor correction."""
    print("\n" + "=" * 70)
    print("ANTENNA FACTOR CORRECTION")
    print("=" * 70)

    print("\nAntenna factors convert field strength (dBμV/m) to power (dBm)")
    print("Used in EMC testing and field measurements")
    print()

    cal = CalibrationManager()

    # Create a simple dipole antenna factor calibration
    # (These are example values - real antenna factors come from cal lab)
    frequencies_hz = [100e6, 200e6, 400e6, 800e6, 1000e6]
    factors_db = [8.5, 12.3, 15.2, 18.4, 19.8]  # dB(1/m)

    antenna = cal.create_antenna_factor(
        name='dipole_vhf',
        frequencies_hz=frequencies_hz,
        factors_db=factors_db,
        description='Half-wave dipole, VHF range',
        date='2026-06-15'
    )

    print(f"Created antenna factor calibration: {antenna.name}")
    print(f"  Type: {antenna.cal_type}")
    print(f"  Points: {len(antenna.data)}")
    print()

    # Example: convert field strength to received power
    print("-" * 70)
    print("Example: field strength to received power")
    print("-" * 70)

    freq_mhz = 146
    freq_hz = freq_mhz * 1e6
    field_strength_dbuv_m = 60.0  # Field strength in dBμV/m

    # Get antenna factor at this frequency
    af_db = antenna.get_correction(freq_hz)

    # Convert field strength to power
    # Formula: P(dBm) = E(dBμV/m) - AF(dB/m) - 90 dB
    power_dbm = field_strength_dbuv_m - af_db - 90.0

    print(f"Frequency: {freq_mhz} MHz")
    print(f"Field strength: {field_strength_dbuv_m:.1f} dBμV/m")
    print(f"Antenna factor: {af_db:.1f} dB(1/m)")
    print(f"Received power: {power_dbm:.1f} dBm")


def demo_list_calibrations():
    """List available calibrations."""
    print("\n" + "=" * 70)
    print("AVAILABLE CALIBRATIONS")
    print("=" * 70)

    cal = CalibrationManager()

    # List all calibration files
    available = cal.available()

    print(f"\nFound {len(available)} calibration file(s):")
    print("-" * 70)

    for path in available:
        rel_path = path.relative_to(cal.cal_dir)
        size_bytes = path.stat().st_size
        print(f"  {rel_path}  ({size_bytes} bytes)")

    print()


def main():
    print("\n" + "=" * 70)
    print("CALIBRATION MANAGEMENT DEMONSTRATION")
    print("=" * 70)
    print()
    print("This demonstrates the calibration management system:")
    print("  1. Loading calibration files")
    print("  2. Applying corrections to measurements")
    print("  3. Batch processing sweep data")
    print("  4. Creating calibrations programmatically")
    print("  5. Antenna factor conversions")
    print()

    demo_list_calibrations()
    demo_cable_loss()
    demo_batch_correction()
    demo_create_calibration()
    demo_antenna_factor()

    print("\n" + "=" * 70)
    print("KEY FEATURES DEMONSTRATED:")
    print("=" * 70)
    print()
    print("✓ Load calibrations from YAML/CSV files")
    print("✓ Frequency-dependent interpolation (linear/cubic/nearest)")
    print("✓ Apply corrections to single measurements")
    print("✓ Batch corrections for sweep data")
    print("✓ Create calibrations programmatically")
    print("✓ Save calibrations to files")
    print("✓ Cable loss compensation")
    print("✓ Antenna factor conversions")
    print()
    print("Calibration files stored in: ~/.rf-bench/calibrations/")
    print()

    return 0


if __name__ == "__main__":
    exit(main())
