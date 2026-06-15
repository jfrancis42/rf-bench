#!/usr/bin/env python3
"""
Amplifier Gain vs Frequency Measurement

Demonstrates the rf_bench.automation framework for multi-instrument measurements.

Hardware required:
  - Siglent SDG1062X (signal generator)
  - Siglent SSA3032X Plus (spectrum analyzer)
  - Amplifier under test

Connections:
  SDG CH1 → Amplifier input
  Amplifier output → SSA RF input
"""

import sys
import numpy as np

# Add automation module to path (until installed via pip)
sys.path.insert(0, '/home/jfrancis/Dropbox/build/rf-bench/automation')

from rf_bench.automation import MeasurementSequence
from rf_bench.siglent import SDG1000X, SSA3000X


def main():
    # Connect to instruments
    print("Connecting to instruments...")
    sdg = SDG1000X('10.1.1.55')
    ssa = SSA3000X('10.1.1.60')

    # Create measurement sequence
    seq = MeasurementSequence(
        name="Amplifier Gain vs Frequency",
        description="Measure small-signal gain from 1 MHz to 1 GHz"
    )

    # Add metadata
    seq.metadata(
        operator='N0GQ',
        dut='Amplifier XYZ',
        input_level_dbm=-20,
        tags=['gain', 'amplifier', 'characterization']
    )

    # Define measurement steps
    @seq.step("Configure Signal Generator")
    def setup_sdg(sdg):
        freq = seq.context['freq_hz']
        sdg.set_sine(1, freq_hz=freq, level_dbm=-20)
        sdg.output_on(1)

    @seq.step("Configure Spectrum Analyzer")
    def setup_ssa(ssa):
        freq = seq.context['freq_hz']
        ssa.set_center_span(freq, 100e3)
        ssa.set_rbw(1000)
        ssa.autoscale()

    @seq.step("Measure Output Power", retry_on_error=True, retry_attempts=3)
    def measure_output(ssa):
        ssa.peak_search()
        peak_freq, peak_power = ssa.get_peak()

        # Calculate gain (output - input)
        gain_db = peak_power - (-20)  # input was -20 dBm

        return {
            'output_dbm': peak_power,
            'gain_db': gain_db
        }

    # Run frequency sweep
    print("\nStarting frequency sweep...")
    print("=" * 60)

    frequencies = np.logspace(6, 9, 50)  # 1 MHz to 1 GHz, 50 points

    results = seq.sweep(
        parameter='freq_hz',
        values=frequencies,
        instruments={'sdg': sdg, 'ssa': ssa}
    )

    # Save results
    output_path = seq.save()
    print(f"\nResults saved to: {output_path}")

    # Print summary
    print("\nSummary:")
    print(f"  Frequency range: {frequencies[0]/1e6:.1f} MHz to {frequencies[-1]/1e9:.1f} GHz")
    print(f"  Data points: {len(results)}")

    if results:
        gains = [r['gain_db'] for r in results]
        print(f"  Gain range: {min(gains):.1f} dB to {max(gains):.1f} dB")
        print(f"  Mean gain: {np.mean(gains):.1f} dB")

    # Cleanup
    print("\nCleaning up...")
    sdg.output_off(1)
    sdg.close()
    ssa.close()

    print("Done!")


if __name__ == '__main__':
    main()
