"""
Signal Generator Measurement Templates

Common signal generator characterization measurements.
"""

import numpy as np
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

from ..sequence import MeasurementSequence


@dataclass
class SignalGeneratorAccuracyResult:
    """Result from signal generator accuracy measurement."""
    seq: MeasurementSequence
    frequencies_set_hz: np.ndarray
    frequencies_measured_hz: np.ndarray
    errors_hz: np.ndarray
    errors_ppm: np.ndarray
    mean_error_ppm: float
    max_error_ppm: float


def signal_generator_accuracy(
    sdg,
    freq_counter,
    freq_start_hz: float = 1e6,
    freq_stop_hz: float = 60e6,
    num_points: int = 20,
    level_dbm: float = 0.0,
    operator: str = "",
    dut_info: Optional[Dict[str, Any]] = None
) -> SignalGeneratorAccuracyResult:
    """
    Measure signal generator frequency accuracy.

    Uses frequency counter to measure actual output frequency.

    Args:
        sdg: Signal generator instance
        freq_counter: Frequency counter instance
        freq_start_hz: Start frequency (Hz)
        freq_stop_hz: Stop frequency (Hz)
        num_points: Number of measurement points
        level_dbm: Output level (dBm)
        operator: Operator name/callsign
        dut_info: Device under test metadata

    Returns:
        SignalGeneratorAccuracyResult with frequency accuracy data
    """

    # Create measurement sequence
    seq = MeasurementSequence("Signal Generator Frequency Accuracy")

    seq.metadata(
        operator=operator or 'Unknown',
        dut=dut_info.get('model', 'Unknown') if dut_info else 'Unknown',
        freq_range_mhz=f"{freq_start_hz/1e6}-{freq_stop_hz/1e6}",
        level_dbm=level_dbm,
        num_points=num_points,
        tags=['signal-generator', 'accuracy', 'frequency']
    )

    # Define measurement steps
    @seq.step("Configure Generator")
    def setup_sdg(sdg):
        freq = seq.context['freq_set_hz']
        sdg.set_sine(1, freq_hz=freq, level_dbm=level_dbm)
        sdg.output_on(1)
        time.sleep(0.2)

    @seq.step("Measure Frequency")
    def measure_freq(freq_counter):
        freq_measured = freq_counter.measure_frequency()
        return {'freq_measured_hz': freq_measured}

    # Run frequency sweep
    frequencies = np.logspace(
        np.log10(freq_start_hz),
        np.log10(freq_stop_hz),
        num_points
    )

    results = seq.sweep(
        parameter='freq_set_hz',
        values=frequencies,
        instruments={'sdg': sdg, 'freq_counter': freq_counter}
    )

    # Cleanup
    sdg.output_off(1)

    # Calculate errors
    freq_set = np.array([r['freq_set_hz'] for r in results])
    freq_measured = np.array([r['freq_measured_hz'] for r in results])
    errors_hz = freq_measured - freq_set
    errors_ppm = (errors_hz / freq_set) * 1e6

    mean_error_ppm = np.mean(np.abs(errors_ppm))
    max_error_ppm = np.max(np.abs(errors_ppm))

    return SignalGeneratorAccuracyResult(
        seq=seq,
        frequencies_set_hz=freq_set,
        frequencies_measured_hz=freq_measured,
        errors_hz=errors_hz,
        errors_ppm=errors_ppm,
        mean_error_ppm=mean_error_ppm,
        max_error_ppm=max_error_ppm
    )


@dataclass
class SignalGeneratorFlatnessResult:
    """Result from signal generator amplitude flatness measurement."""
    seq: MeasurementSequence
    frequencies_hz: np.ndarray
    levels_dbm: np.ndarray
    flatness_db: float
    mean_level_dbm: float


def signal_generator_flatness(
    sdg,
    ssa,
    freq_start_hz: float = 1e6,
    freq_stop_hz: float = 60e6,
    num_points: int = 50,
    level_set_dbm: float = -10.0,
    operator: str = "",
    dut_info: Optional[Dict[str, Any]] = None
) -> SignalGeneratorFlatnessResult:
    """
    Measure signal generator amplitude flatness.

    Sweeps frequency and measures output level with spectrum analyzer.

    Args:
        sdg: Signal generator instance
        ssa: Spectrum analyzer instance
        freq_start_hz: Start frequency (Hz)
        freq_stop_hz: Stop frequency (Hz)
        num_points: Number of measurement points
        level_set_dbm: Set output level (dBm)
        operator: Operator name/callsign
        dut_info: Device under test metadata

    Returns:
        SignalGeneratorFlatnessResult with amplitude flatness data
    """

    # Create measurement sequence
    seq = MeasurementSequence("Signal Generator Amplitude Flatness")

    seq.metadata(
        operator=operator or 'Unknown',
        dut=dut_info.get('model', 'Unknown') if dut_info else 'Unknown',
        freq_range_mhz=f"{freq_start_hz/1e6}-{freq_stop_hz/1e6}",
        level_set_dbm=level_set_dbm,
        num_points=num_points,
        tags=['signal-generator', 'flatness', 'amplitude']
    )

    # Define measurement steps
    @seq.step("Configure and Measure")
    def measure(sdg, ssa):
        freq = seq.context['freq_hz']

        sdg.set_sine(1, freq_hz=freq, level_dbm=level_set_dbm)
        sdg.output_on(1)
        time.sleep(0.1)

        ssa.set_center_span(freq, 100e3)
        ssa.peak_search()
        _, power_dbm = ssa.get_peak()

        return {'power_dbm': power_dbm}

    # Run frequency sweep
    frequencies = np.logspace(
        np.log10(freq_start_hz),
        np.log10(freq_stop_hz),
        num_points
    )

    results = seq.sweep(
        parameter='freq_hz',
        values=frequencies,
        instruments={'sdg': sdg, 'ssa': ssa}
    )

    # Cleanup
    sdg.output_off(1)

    # Calculate flatness
    levels = np.array([r['power_dbm'] for r in results])
    flatness = np.max(levels) - np.min(levels)
    mean_level = np.mean(levels)

    return SignalGeneratorFlatnessResult(
        seq=seq,
        frequencies_hz=frequencies,
        levels_dbm=levels,
        flatness_db=flatness,
        mean_level_dbm=mean_level
    )
