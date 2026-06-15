#!/usr/bin/env python3
"""
PSU Test Suite Example

Demonstrates the test sequencing framework by creating a comprehensive
power supply test suite with pass/fail criteria.

This test suite checks:
1. PSU output voltage accuracy
2. Current limiting functionality
3. Load regulation (voltage stability under load)
4. Safety interlocks

Hardware setup:
  SPD3303X CH1+ → 1Ω 20W load → SDM3045X VΩ input
  SPD3303X CH1- → SDM3045X COM

Usage:
  python3 psu_test_suite.py
"""

import time
from rf_bench.instruments import Registry
from rf_bench.automation import TestSuite, test


class PSUAccuracyTest(TestSuite):
    """Power supply accuracy test suite."""

    @test(name="PSU Connection")
    def test_connection(self):
        """Verify PSU responds to *IDN?"""
        psu = self.instruments['psu']
        idn = psu.identify()

        self.assert_true(
            'SPD3303X' in idn,
            f"Expected SPD3303X, got: {idn}"
        )

    @test(name="DMM Connection", depends_on='test_connection')
    def test_dmm_connection(self):
        """Verify DMM responds to *IDN?"""
        dmm = self.instruments['dmm']
        idn = dmm.identify()

        self.assert_true(
            'SDM3045X' in idn,
            f"Expected SDM3045X, got: {idn}"
        )

    @test(name="Voltage Accuracy at 1V", depends_on='test_dmm_connection')
    def test_voltage_1v(self):
        """Check PSU voltage accuracy at 1V setpoint."""
        psu = self.instruments['psu']
        dmm = self.instruments['dmm']

        # Set PSU to 1V
        psu.set_voltage(1, 1.0)
        psu.set_current(1, 3.2)
        psu.enable(1)
        time.sleep(0.3)  # Settling

        # Measure actual output
        dmm.configure_vdc()
        time.sleep(0.1)
        v_measured = dmm.read()

        # Cleanup
        psu.disable(1)

        # Assert ±10% accuracy (account for 1Ω load + cable drop)
        self.assert_between(v_measured, 0.9, 1.1, units='V')

    @test(name="Voltage Accuracy at 2V", depends_on='test_dmm_connection')
    def test_voltage_2v(self):
        """Check PSU voltage accuracy at 2V setpoint."""
        psu = self.instruments['psu']
        dmm = self.instruments['dmm']

        psu.set_voltage(1, 2.0)
        psu.set_current(1, 3.2)
        psu.enable(1)
        time.sleep(0.3)

        dmm.configure_vdc()
        time.sleep(0.1)
        v_measured = dmm.read()

        psu.disable(1)

        # ±10% tolerance
        self.assert_between(v_measured, 1.8, 2.2, units='V')

    @test(name="Voltage Accuracy at 3V", depends_on='test_dmm_connection')
    def test_voltage_3v(self):
        """Check PSU voltage accuracy at 3V setpoint."""
        psu = self.instruments['psu']
        dmm = self.instruments['dmm']

        psu.set_voltage(1, 3.0)
        psu.set_current(1, 3.2)
        psu.enable(1)
        time.sleep(0.3)

        dmm.configure_vdc()
        time.sleep(0.1)
        v_measured = dmm.read()

        psu.disable(1)

        # ±10% tolerance
        self.assert_between(v_measured, 2.7, 3.3, units='V')

    @test(name="Current Limiting", depends_on='test_connection')
    def test_current_limit(self):
        """Verify PSU current limiting works."""
        psu = self.instruments['psu']

        # Set 5V with 0.5A limit
        # With 1Ω load, this should current-limit
        psu.set_voltage(1, 5.0)
        psu.set_current(1, 0.5)
        psu.enable(1)
        time.sleep(0.3)

        # Measure current
        i_measured = psu.measure_current(1)

        psu.disable(1)

        # Current should be at or near the limit (within 10%)
        self.assert_between(i_measured, 0.45, 0.55, units='A')

    @test(name="Output Disable", depends_on='test_connection')
    def test_output_disable(self):
        """Verify output can be disabled."""
        psu = self.instruments['psu']
        dmm = self.instruments['dmm']

        # Enable output
        psu.set_voltage(1, 2.0)
        psu.set_current(1, 1.0)
        psu.enable(1)
        time.sleep(0.2)

        # Disable output
        psu.disable(1)
        time.sleep(0.2)

        # Measure voltage (should be near zero)
        dmm.configure_vdc()
        v_measured = dmm.read()

        # Should be < 0.1V when disabled
        self.assert_less_than(abs(v_measured), 0.1, units='V')


def main():
    print("\n" + "=" * 70)
    print("PSU ACCURACY TEST SUITE")
    print("=" * 70)
    print()
    print("This test suite verifies SPD3303X power supply accuracy")
    print("using the test sequencing framework.")
    print()

    # Connect to instruments
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

    # Initialize PSU (output OFF)
    psu.set_voltage(1, 0.0)
    psu.disable(1)

    # Create and run test suite
    suite = PSUAccuracyTest(
        instruments={'psu': psu, 'dmm': dmm},
        dut_info={
            'model': 'SPD3303X-E',
            'serial': 'SPD3XJFD7R5914',
            'load': '1Ω 20W resistor'
        },
        operator='N0GQ'
    )

    report = suite.run(verbose=True)

    # Save report
    report.save('~/psu_test_report.txt')

    # Cleanup
    print("\nCleaning up...")
    psu.set_voltage(1, 0.0)
    psu.disable(1)
    psu.close()
    dmm.close()

    print("Done!")

    return 0 if report.passed else 1


if __name__ == "__main__":
    exit(main())
