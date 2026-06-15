"""
rf_bench.automation — High-level measurement automation framework

Provides abstractions for building multi-instrument measurement sequences:
- MeasurementSequence: organize steps and handle errors
- Parameter sweeps with progress reporting
- Automatic data logging
- Retry logic and error recovery

Example::

    from rf_bench.automation import MeasurementSequence
    import numpy as np

    seq = MeasurementSequence("Amplifier Gain vs Frequency")

    @seq.step("Configure Signal Generator")
    def setup_sdg(sdg):
        sdg.set_sine(1, freq_hz=1e6, level_dbm=-20)
        sdg.output_on(1)

    @seq.step("Measure Output Power")
    def measure_output(ssa):
        ssa.set_center_span(seq.sweep_var('freq_hz'), 100e3)
        ssa.peak_search()
        freq, power = ssa.get_peak()
        return {'output_dbm': power}

    # Run frequency sweep
    results = seq.sweep(
        parameter='freq_hz',
        values=np.logspace(6, 9, 50),
        instruments={'sdg': sdg, 'ssa': ssa}
    )

    # Save results
    seq.save('amplifier_gain.csv')
"""

from .sequence import MeasurementSequence
from .sweep import sweep, sweep_grid
from .logging import MeasurementLog
from .retry import retry, RetryError
from .search import (
    search_measurements,
    recent_measurements,
    find_by_tag,
    find_by_operator,
    summary_stats
)
from .testing import (
    TestSuite,
    TestReport,
    TestResult,
    TestAssertionError,
    test
)
from .calibration import (
    CalibrationManager,
    Calibration,
    CalibrationPoint,
    apply_cable_loss_correction,
    apply_antenna_factor
)
from .robust import (
    RobustConnection,
    robust_instrument,
    with_retry,
    connection_health_check,
    reconnect_if_needed
)

__all__ = [
    'MeasurementSequence',
    'sweep',
    'sweep_grid',
    'MeasurementLog',
    'retry',
    'RetryError',
    'search_measurements',
    'recent_measurements',
    'find_by_tag',
    'find_by_operator',
    'summary_stats',
    'TestSuite',
    'TestReport',
    'TestResult',
    'TestAssertionError',
    'test',
    'CalibrationManager',
    'Calibration',
    'CalibrationPoint',
    'apply_cable_loss_correction',
    'apply_antenna_factor',
    'RobustConnection',
    'robust_instrument',
    'with_retry',
    'connection_health_check',
    'reconnect_if_needed',
]
