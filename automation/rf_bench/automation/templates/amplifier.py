"""
Amplifier Measurement Templates

Common amplifier characterization measurements.
"""

import numpy as np
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

from ..sequence import MeasurementSequence


@dataclass
class AmplifierGainResult:
    """Result from amplifier gain sweep."""
    seq: MeasurementSequence
    frequencies_hz: np.ndarray
    gains_db: np.ndarray
    input_power_dbm: float
    mean_gain_db: float
    std_gain_db: float
    flatness_db: float


def amplifier_gain_sweep(
    sdg,
    ssa,
    freq_start_hz: float = 100e6,
    freq_stop_hz: float = 1e9,
    num_points: int = 50,
    input_level_dbm: float = -20.0,
    operator: str = "",
    dut_info: Optional[Dict[str, Any]] = None
) -> AmplifierGainResult:
    """
    Measure amplifier gain vs frequency.

    Args:
        sdg: Signal generator instance (SDG1000X)
        ssa: Spectrum analyzer instance (SSA3000X)
        freq_start_hz: Start frequency (Hz)
        freq_stop_hz: Stop frequency (Hz)
        num_points: Number of measurement points
        input_level_dbm: Input power level (dBm)
        operator: Operator name/callsign
        dut_info: Device under test metadata

    Returns:
        AmplifierGainResult with data and statistics
    """

    # Create measurement sequence
    seq = MeasurementSequence("Amplifier Gain vs Frequency")

    seq.metadata(
        operator=operator or 'Unknown',
        dut=dut_info.get('model', 'Unknown') if dut_info else 'Unknown',
        input_level_dbm=input_level_dbm,
        freq_start_mhz=freq_start_hz / 1e6,
        freq_stop_mhz=freq_stop_hz / 1e6,
        num_points=num_points,
        tags=['amplifier', 'gain', 'sweep']
    )

    # Define measurement steps
    @seq.step("Configure Signal Generator")
    def setup_sdg(sdg):
        freq = seq.context['freq_hz']
        sdg.set_sine(1, freq_hz=freq, level_dbm=input_level_dbm)
        sdg.output_on(1)
        time.sleep(0.1)

    @seq.step("Measure Output Power", retry_on_error=True)
    def measure_output(ssa):
        freq = seq.context['freq_hz']
        ssa.set_center_span(freq, 100e3)
        ssa.peak_search()
        _, power_dbm = ssa.get_peak()

        gain_db = power_dbm - input_level_dbm

        return {
            'freq_hz': freq,
            'output_dbm': power_dbm,
            'gain_db': gain_db
        }

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

    # Extract data
    gains_db = np.array([r['gain_db'] for r in results])

    # Calculate statistics
    mean_gain = np.mean(gains_db)
    std_gain = np.std(gains_db)
    flatness = np.max(gains_db) - np.min(gains_db)

    return AmplifierGainResult(
        seq=seq,
        frequencies_hz=frequencies,
        gains_db=gains_db,
        input_power_dbm=input_level_dbm,
        mean_gain_db=mean_gain,
        std_gain_db=std_gain,
        flatness_db=flatness
    )


@dataclass
class AmplifierP1dBResult:
    """Result from 1dB compression point measurement."""
    seq: MeasurementSequence
    p1db_dbm: float
    output_power_dbm: float
    small_signal_gain_db: float
    compressed_gain_db: float


def amplifier_p1db(
    sdg,
    ssa,
    freq_hz: float = 1e9,
    power_start_dbm: float = -30.0,
    power_stop_dbm: float = 10.0,
    num_points: int = 40,
    operator: str = "",
    dut_info: Optional[Dict[str, Any]] = None
) -> AmplifierP1dBResult:
    """
    Find 1dB compression point.

    Sweeps input power and finds where gain drops by 1 dB.

    Args:
        sdg: Signal generator instance
        ssa: Spectrum analyzer instance
        freq_hz: Test frequency (Hz)
        power_start_dbm: Start input power (dBm)
        power_stop_dbm: Stop input power (dBm)
        num_points: Number of measurement points
        operator: Operator name/callsign
        dut_info: Device under test metadata

    Returns:
        AmplifierP1dBResult with P1dB and gain data
    """

    # Create measurement sequence
    seq = MeasurementSequence("Amplifier 1dB Compression Point")

    seq.metadata(
        operator=operator or 'Unknown',
        dut=dut_info.get('model', 'Unknown') if dut_info else 'Unknown',
        freq_mhz=freq_hz / 1e6,
        power_start_dbm=power_start_dbm,
        power_stop_dbm=power_stop_dbm,
        num_points=num_points,
        tags=['amplifier', 'compression', 'p1db']
    )

    # Define measurement steps
    @seq.step("Configure and Measure")
    def measure(sdg, ssa):
        input_dbm = seq.context['input_dbm']

        sdg.set_sine(1, freq_hz=freq_hz, level_dbm=input_dbm)
        sdg.output_on(1)
        time.sleep(0.1)

        ssa.set_center_span(freq_hz, 100e3)
        ssa.peak_search()
        _, output_dbm = ssa.get_peak()

        gain_db = output_dbm - input_dbm

        return {
            'input_dbm': input_dbm,
            'output_dbm': output_dbm,
            'gain_db': gain_db
        }

    # Run power sweep
    input_powers = np.linspace(power_start_dbm, power_stop_dbm, num_points)

    results = seq.sweep(
        parameter='input_dbm',
        values=input_powers,
        instruments={'sdg': sdg, 'ssa': ssa}
    )

    # Cleanup
    sdg.output_off(1)

    # Find P1dB
    gains = np.array([r['gain_db'] for r in results])
    inputs = np.array([r['input_dbm'] for r in results])
    outputs = np.array([r['output_dbm'] for r in results])

    # Small-signal gain = average of first 5 points
    small_signal_gain = np.mean(gains[:5])

    # Find where gain drops by 1 dB
    compressed_gain = small_signal_gain - 1.0

    # Interpolate to find exact P1dB
    idx = np.where(gains < compressed_gain)[0]

    if len(idx) > 0:
        # Found compression point
        p1db_idx = idx[0]
        p1db_input = inputs[p1db_idx]
        p1db_output = outputs[p1db_idx]
        p1db_gain = gains[p1db_idx]
    else:
        # Didn't reach compression
        p1db_input = power_stop_dbm
        p1db_output = outputs[-1]
        p1db_gain = gains[-1]

    return AmplifierP1dBResult(
        seq=seq,
        p1db_dbm=p1db_input,
        output_power_dbm=p1db_output,
        small_signal_gain_db=small_signal_gain,
        compressed_gain_db=p1db_gain
    )


@dataclass
class AmplifierHarmonicsResult:
    """Result from harmonic distortion measurement."""
    seq: MeasurementSequence
    fundamental_dbm: float
    second_harmonic_dbm: float
    third_harmonic_dbm: float
    h2_dbc: float
    h3_dbc: float


def amplifier_harmonics(
    sdg,
    ssa,
    freq_hz: float = 100e6,
    input_level_dbm: float = -10.0,
    operator: str = "",
    dut_info: Optional[Dict[str, Any]] = None
) -> AmplifierHarmonicsResult:
    """
    Measure harmonic distortion.

    Measures fundamental, 2nd, and 3rd harmonics.

    Args:
        sdg: Signal generator instance
        ssa: Spectrum analyzer instance
        freq_hz: Test frequency (Hz)
        input_level_dbm: Input power level (dBm)
        operator: Operator name/callsign
        dut_info: Device under test metadata

    Returns:
        AmplifierHarmonicsResult with harmonic levels
    """

    # Create measurement sequence
    seq = MeasurementSequence("Amplifier Harmonic Distortion")

    seq.metadata(
        operator=operator or 'Unknown',
        dut=dut_info.get('model', 'Unknown') if dut_info else 'Unknown',
        freq_mhz=freq_hz / 1e6,
        input_level_dbm=input_level_dbm,
        tags=['amplifier', 'harmonics', 'distortion']
    )

    # Configure signal generator
    sdg.set_sine(1, freq_hz=freq_hz, level_dbm=input_level_dbm)
    sdg.output_on(1)
    time.sleep(0.2)

    # Measure fundamental
    ssa.set_center_span(freq_hz, 100e3)
    ssa.peak_search()
    _, fundamental_dbm = ssa.get_peak()

    # Measure 2nd harmonic
    ssa.set_center_span(2 * freq_hz, 100e3)
    ssa.peak_search()
    _, h2_dbm = ssa.get_peak()

    # Measure 3rd harmonic
    ssa.set_center_span(3 * freq_hz, 100e3)
    ssa.peak_search()
    _, h3_dbm = ssa.get_peak()

    # Cleanup
    sdg.output_off(1)

    # Calculate dBc (relative to carrier)
    h2_dbc = h2_dbm - fundamental_dbm
    h3_dbc = h3_dbm - fundamental_dbm

    # Log data
    seq._log.append({
        'fundamental_dbm': fundamental_dbm,
        'h2_dbm': h2_dbm,
        'h3_dbm': h3_dbm,
        'h2_dbc': h2_dbc,
        'h3_dbc': h3_dbc
    })

    return AmplifierHarmonicsResult(
        seq=seq,
        fundamental_dbm=fundamental_dbm,
        second_harmonic_dbm=h2_dbm,
        third_harmonic_dbm=h3_dbm,
        h2_dbc=h2_dbc,
        h3_dbc=h3_dbc
    )
