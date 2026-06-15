"""
Power Supply Measurement Templates

Common PSU characterization measurements.
"""

import numpy as np
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

from ..sequence import MeasurementSequence


@dataclass
class PowerSupplyAccuracyResult:
    """Result from PSU accuracy measurement."""
    seq: MeasurementSequence
    voltages_set: np.ndarray
    voltages_measured: np.ndarray
    errors_v: np.ndarray
    errors_pct: np.ndarray
    mean_error_v: float
    max_error_v: float
    rms_error_v: float


def power_supply_accuracy(
    psu,
    dmm,
    channel: int = 1,
    voltage_start_v: float = 1.0,
    voltage_stop_v: float = 12.0,
    num_points: int = 12,
    current_limit_a: float = 1.0,
    operator: str = "",
    dut_info: Optional[Dict[str, Any]] = None
) -> PowerSupplyAccuracyResult:
    """
    Measure PSU voltage accuracy.

    Sweeps voltage setpoint and measures actual output with DMM.

    Args:
        psu: Power supply instance (SPD3303X)
        dmm: Multimeter instance (SDM3045X)
        channel: PSU channel (1, 2, or 3)
        voltage_start_v: Start voltage (V)
        voltage_stop_v: Stop voltage (V)
        num_points: Number of measurement points
        current_limit_a: Current limit (A)
        operator: Operator name/callsign
        dut_info: Device under test metadata

    Returns:
        PowerSupplyAccuracyResult with accuracy data
    """

    # Create measurement sequence
    seq = MeasurementSequence("Power Supply Voltage Accuracy")

    seq.metadata(
        operator=operator or 'Unknown',
        dut=dut_info.get('model', 'Unknown') if dut_info else 'Unknown',
        channel=channel,
        voltage_range_v=f"{voltage_start_v}-{voltage_stop_v}",
        current_limit_a=current_limit_a,
        num_points=num_points,
        tags=['power-supply', 'accuracy', 'voltage']
    )

    # Define measurement steps
    @seq.step("Configure PSU")
    def setup_psu(psu):
        v_set = seq.context['voltage_set']
        psu.set_voltage(channel, v_set)
        psu.set_current(channel, current_limit_a)
        psu.enable(channel)
        time.sleep(0.3)  # Settling time

    @seq.step("Measure Voltage")
    def measure_voltage(dmm):
        dmm.configure_vdc()
        time.sleep(0.1)
        v_measured = dmm.read()
        return {'voltage_measured': v_measured}

    # Run voltage sweep
    voltages = np.linspace(voltage_start_v, voltage_stop_v, num_points)

    results = seq.sweep(
        parameter='voltage_set',
        values=voltages,
        instruments={'psu': psu, 'dmm': dmm}
    )

    # Cleanup
    psu.set_voltage(channel, 0.0)
    psu.disable(channel)

    # Calculate errors
    v_set = np.array([r['voltage_set'] for r in results])
    v_measured = np.array([r['voltage_measured'] for r in results])
    errors_v = v_measured - v_set
    errors_pct = (errors_v / v_set) * 100

    mean_error = np.mean(np.abs(errors_v))
    max_error = np.max(np.abs(errors_v))
    rms_error = np.sqrt(np.mean(errors_v ** 2))

    return PowerSupplyAccuracyResult(
        seq=seq,
        voltages_set=v_set,
        voltages_measured=v_measured,
        errors_v=errors_v,
        errors_pct=errors_pct,
        mean_error_v=mean_error,
        max_error_v=max_error,
        rms_error_v=rms_error
    )


@dataclass
class PowerSupplyRippleResult:
    """Result from PSU ripple measurement."""
    seq: MeasurementSequence
    voltage_v: float
    ripple_mv_pp: float
    ripple_mv_rms: float


def power_supply_ripple(
    psu,
    scope,
    channel: int = 1,
    voltage_v: float = 12.0,
    current_a: float = 1.0,
    operator: str = "",
    dut_info: Optional[Dict[str, Any]] = None
) -> PowerSupplyRippleResult:
    """
    Measure PSU output ripple.

    Uses oscilloscope to measure AC-coupled ripple.

    Args:
        psu: Power supply instance
        scope: Oscilloscope instance (SDS2000X)
        channel: PSU channel
        voltage_v: Output voltage (V)
        current_a: Load current (A)
        operator: Operator name/callsign
        dut_info: Device under test metadata

    Returns:
        PowerSupplyRippleResult with ripple data
    """

    # Create measurement sequence
    seq = MeasurementSequence("Power Supply Ripple")

    seq.metadata(
        operator=operator or 'Unknown',
        dut=dut_info.get('model', 'Unknown') if dut_info else 'Unknown',
        channel=channel,
        voltage_v=voltage_v,
        current_a=current_a,
        tags=['power-supply', 'ripple', 'ac']
    )

    # Configure PSU
    psu.set_voltage(channel, voltage_v)
    psu.set_current(channel, current_a)
    psu.enable(channel)
    time.sleep(0.5)  # Settling

    # Configure scope (AC coupled, 10mV/div scale)
    scope.set_channel_coupling(1, 'AC')
    scope.set_channel_scale(1, 0.01)  # 10 mV/div
    scope.set_timebase(0.001)  # 1 ms/div

    time.sleep(0.5)  # Let scope settle

    # Measure ripple
    vpp_v = scope.measure_vpp(1)
    vrms_v = scope.measure_vrms(1)

    ripple_pp_mv = vpp_v * 1000
    ripple_rms_mv = vrms_v * 1000

    # Cleanup
    psu.disable(channel)

    # Log data
    seq._log.append({
        'voltage_v': voltage_v,
        'current_a': current_a,
        'ripple_pp_mv': ripple_pp_mv,
        'ripple_rms_mv': ripple_rms_mv
    })

    return PowerSupplyRippleResult(
        seq=seq,
        voltage_v=voltage_v,
        ripple_mv_pp=ripple_pp_mv,
        ripple_mv_rms=ripple_rms_mv
    )


@dataclass
class PowerSupplyLoadRegulationResult:
    """Result from PSU load regulation measurement."""
    seq: MeasurementSequence
    currents_a: np.ndarray
    voltages_v: np.ndarray
    regulation_pct: float


def power_supply_load_regulation(
    psu,
    dmm,
    channel: int = 1,
    voltage_set_v: float = 12.0,
    current_min_a: float = 0.1,
    current_max_a: float = 3.0,
    num_points: int = 10,
    operator: str = "",
    dut_info: Optional[Dict[str, Any]] = None
) -> PowerSupplyLoadRegulationResult:
    """
    Measure PSU load regulation.

    Varies load current and measures voltage stability.

    Args:
        psu: Power supply instance
        dmm: Multimeter instance
        channel: PSU channel
        voltage_set_v: Set voltage (V)
        current_min_a: Minimum load current (A)
        current_max_a: Maximum load current (A)
        num_points: Number of measurement points
        operator: Operator name/callsign
        dut_info: Device under test metadata

    Returns:
        PowerSupplyLoadRegulationResult with regulation data
    """

    # Create measurement sequence
    seq = MeasurementSequence("Power Supply Load Regulation")

    seq.metadata(
        operator=operator or 'Unknown',
        dut=dut_info.get('model', 'Unknown') if dut_info else 'Unknown',
        channel=channel,
        voltage_set_v=voltage_set_v,
        current_range_a=f"{current_min_a}-{current_max_a}",
        num_points=num_points,
        tags=['power-supply', 'regulation', 'load']
    )

    # Define measurement steps
    @seq.step("Configure and Measure")
    def measure(psu, dmm):
        current_a = seq.context['current_a']

        psu.set_voltage(channel, voltage_set_v)
        psu.set_current(channel, current_a)
        psu.enable(channel)
        time.sleep(0.3)

        dmm.configure_vdc()
        v_measured = dmm.read()

        return {'voltage_measured': v_measured}

    # Run current sweep
    currents = np.linspace(current_min_a, current_max_a, num_points)

    results = seq.sweep(
        parameter='current_a',
        values=currents,
        instruments={'psu': psu, 'dmm': dmm}
    )

    # Cleanup
    psu.disable(channel)

    # Calculate regulation
    voltages = np.array([r['voltage_measured'] for r in results])
    v_min = np.min(voltages)
    v_max = np.max(voltages)
    regulation_pct = ((v_max - v_min) / voltage_set_v) * 100

    return PowerSupplyLoadRegulationResult(
        seq=seq,
        currents_a=currents,
        voltages_v=voltages,
        regulation_pct=regulation_pct
    )
