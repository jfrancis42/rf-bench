#!/usr/bin/env python3
"""
Amplifier Test Suite Example

Demonstrates advanced test sequencing features:
- Test dependencies (skip_if_failed)
- Quantitative assertions with units
- Multi-instrument coordination
- Production test report generation

This simulates an amplifier characterization test suite that would
measure gain, compression point, and harmonic distortion.

Since we don't have a real amplifier, this uses simulated measurements
to demonstrate the framework capabilities.

Usage:
  python3 amplifier_test_suite.py
"""

import numpy as np
from rf_bench.automation import TestSuite, test


# Simulated measurement functions
def measure_gain_simulated(freq_hz):
    """Simulate gain measurement (typical ~22 dB with variation)."""
    # Add realistic variation
    nominal_gain = 22.0
    freq_variation = -0.5 if freq_hz > 500e6 else 0.0
    noise = np.random.randn() * 0.3
    return nominal_gain + freq_variation + noise


def measure_p1db_simulated():
    """Simulate 1dB compression point measurement."""
    # Typical amplifier has P1dB around +10 dBm
    return 10.2 + np.random.randn() * 0.5


def measure_harmonics_simulated(freq_hz):
    """Simulate harmonic distortion measurement."""
    # Returns (fundamental_dbm, h2_dbc, h3_dbc)
    fundamental = -10.0 + np.random.randn() * 0.5
    h2 = -45.0 + np.random.randn() * 2.0  # 2nd harmonic, dBc
    h3 = -50.0 + np.random.randn() * 2.0  # 3rd harmonic, dBc
    return fundamental, h2, h3


def measure_noise_figure_simulated(freq_hz):
    """Simulate noise figure measurement."""
    # Typical NF around 3-4 dB
    return 3.5 + np.random.randn() * 0.3


class AmplifierTest(TestSuite):
    """Complete amplifier characterization test suite."""

    @test(name="Equipment Check")
    def test_equipment(self):
        """Verify all required instruments are connected."""
        required = ['sdg', 'ssa']

        for inst_name in required:
            self.assert_true(
                inst_name in self.instruments,
                f"Missing instrument: {inst_name}"
            )

        print("    All instruments present")

    @test(name="Gain at 100 MHz", depends_on='test_equipment')
    def test_gain_100mhz(self):
        """Measure small-signal gain at 100 MHz."""
        gain_db = measure_gain_simulated(100e6)

        # Store for later tests
        self._gain_100mhz = gain_db

        # Spec: 20-24 dB gain
        self.assert_between(gain_db, 20.0, 24.0, units='dB')

        print(f"    Measured: {gain_db:.2f} dB")

    @test(name="Gain at 500 MHz", depends_on='test_equipment')
    def test_gain_500mhz(self):
        """Measure small-signal gain at 500 MHz."""
        gain_db = measure_gain_simulated(500e6)

        # Store for later tests
        self._gain_500mhz = gain_db

        # Spec: 20-24 dB gain
        self.assert_between(gain_db, 20.0, 24.0, units='dB')

        print(f"    Measured: {gain_db:.2f} dB")

    @test(name="Gain at 1 GHz", depends_on='test_equipment')
    def test_gain_1ghz(self):
        """Measure small-signal gain at 1 GHz."""
        gain_db = measure_gain_simulated(1e9)

        # Store for later tests
        self._gain_1ghz = gain_db

        # Spec: 19-24 dB gain (allows some rolloff at high freq)
        self.assert_between(gain_db, 19.0, 24.0, units='dB')

        print(f"    Measured: {gain_db:.2f} dB")

    @test(name="Gain Flatness", depends_on='test_gain_1ghz')
    def test_gain_flatness(self):
        """Check gain flatness across frequency range."""
        gains = [self._gain_100mhz, self._gain_500mhz, self._gain_1ghz]

        max_gain = max(gains)
        min_gain = min(gains)
        flatness_db = max_gain - min_gain

        # Spec: ±1.5 dB flatness
        self.assert_less_than(flatness_db, 1.5, units='dB')

        print(f"    Flatness: {flatness_db:.2f} dB")

    @test(name="1dB Compression Point", depends_on='test_gain_100mhz')
    def test_compression(self):
        """Measure 1dB compression point."""
        p1db_dbm = measure_p1db_simulated()

        # Spec: P1dB > +8 dBm
        self.assert_greater_than(p1db_dbm, 8.0, units='dBm')

        print(f"    Measured: {p1db_dbm:+.1f} dBm")

    @test(name="2nd Harmonic Distortion", depends_on='test_gain_100mhz')
    def test_second_harmonic(self):
        """Measure 2nd harmonic distortion at 100 MHz."""
        fundamental, h2_dbc, h3_dbc = measure_harmonics_simulated(100e6)

        # Spec: H2 < -40 dBc
        self.assert_less_than(h2_dbc, -40.0, units='dBc')

        print(f"    H2: {h2_dbc:.1f} dBc")

    @test(name="3rd Harmonic Distortion", depends_on='test_gain_100mhz')
    def test_third_harmonic(self):
        """Measure 3rd harmonic distortion at 100 MHz."""
        fundamental, h2_dbc, h3_dbc = measure_harmonics_simulated(100e6)

        # Spec: H3 < -45 dBc
        self.assert_less_than(h3_dbc, -45.0, units='dBc')

        print(f"    H3: {h3_dbc:.1f} dBc")

    @test(name="Noise Figure", depends_on='test_gain_100mhz')
    def test_noise_figure(self):
        """Measure noise figure at 100 MHz."""
        nf_db = measure_noise_figure_simulated(100e6)

        # Spec: NF < 5 dB
        self.assert_less_than(nf_db, 5.0, units='dB')

        print(f"    NF: {nf_db:.1f} dB")


def main():
    print("\n" + "=" * 70)
    print("AMPLIFIER CHARACTERIZATION TEST SUITE")
    print("=" * 70)
    print()
    print("This demonstrates the test sequencing framework with:")
    print("  - Test dependencies (skip if prerequisite fails)")
    print("  - Quantitative assertions with units")
    print("  - Production test report generation")
    print()
    print("NOTE: Using simulated measurements (no real hardware)")
    print()

    # Simulated instrument placeholders
    instruments = {
        'sdg': 'SDG1062X (simulated)',
        'ssa': 'SSA3032X (simulated)'
    }

    # Create and run test suite
    suite = AmplifierTest(
        instruments=instruments,
        dut_info={
            'model': 'Amplifier XYZ',
            'serial': 'A-12345',
            'frequency_range': '50 MHz - 1 GHz',
            'typical_gain': '22 dB'
        },
        operator='N0GQ'
    )

    report = suite.run(verbose=True)

    # Save report
    report.save('~/amplifier_test_report.txt')

    print()
    print("=" * 70)
    print("TEST SUITE FEATURES DEMONSTRATED:")
    print("=" * 70)
    print()
    print("✓ Test dependencies:")
    print("  - Gain flatness depends on all gain tests")
    print("  - Compression/harmonics depend on basic gain test")
    print()
    print("✓ Quantitative assertions:")
    print("  - assert_between(value, min, max, units='dB')")
    print("  - assert_greater_than(value, threshold, units='dBm')")
    print("  - assert_less_than(value, threshold, units='dBc')")
    print()
    print("✓ Report generation:")
    print("  - Text summary with pass/fail")
    print("  - DUT metadata (model, serial, operator)")
    print("  - Individual test timing")
    print()
    print("✓ Conditional execution:")
    print("  - Tests skip if dependencies fail")
    print("  - Prevents cascading failures")
    print()

    return 0 if report.passed else 1


if __name__ == "__main__":
    exit(main())
