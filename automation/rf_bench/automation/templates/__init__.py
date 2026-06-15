"""
Measurement Templates

Pre-built measurement sequences for common RF/hardware tasks.

Available templates:
- amplifier_gain_sweep: Measure amplifier gain vs frequency
- amplifier_p1db: Find 1dB compression point
- cable_loss: Measure cable loss vs frequency
- antenna_vswr: Measure antenna VSWR vs frequency
- power_supply_accuracy: Measure PSU voltage/current accuracy
- signal_generator_accuracy: Measure SDG frequency/amplitude accuracy
- spectrum_analyzer_flatness: Measure SSA amplitude flatness
- receiver_sensitivity: Measure MDS and signal-to-noise ratio
- transmitter_power: Measure TX output power vs frequency
- harmonic_distortion: Measure 2nd/3rd harmonics

Usage:
    from rf_bench.automation.templates import amplifier_gain_sweep

    # Connect to instruments
    sdg = SDG1000X('10.1.1.55')
    ssa = SSA3000X('10.1.1.60')

    # Run template
    results = amplifier_gain_sweep(
        sdg=sdg,
        ssa=ssa,
        freq_start_hz=100e6,
        freq_stop_hz=1e9,
        num_points=50,
        input_level_dbm=-20
    )

    # Results include MeasurementSequence object with data
    results.seq.save('amplifier_gain.csv')
"""

from .amplifier import (
    amplifier_gain_sweep,
    amplifier_p1db,
    amplifier_harmonics
)

from .power_supply import (
    power_supply_accuracy,
    power_supply_ripple,
    power_supply_load_regulation
)

from .signal_generator import (
    signal_generator_accuracy,
    signal_generator_flatness
)

__all__ = [
    'amplifier_gain_sweep',
    'amplifier_p1db',
    'amplifier_harmonics',
    'power_supply_accuracy',
    'power_supply_ripple',
    'power_supply_load_regulation',
    'signal_generator_accuracy',
    'signal_generator_flatness',
]
