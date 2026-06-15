"""
sweep.py — Parameter sweep utilities

Provides high-level sweep functions with progress reporting.
"""

import numpy as np
from typing import Callable, Dict, Any, List, Iterable
from tqdm import tqdm


def sweep(
    parameter: str,
    values: Iterable[float],
    measure_func: Callable[[float], Dict[str, Any]],
    show_progress: bool = True,
    description: str = None
) -> List[Dict[str, Any]]:
    """
    Sweep a single parameter and collect measurements.

    Args:
        parameter: Name of the parameter being swept
        values: Iterable of parameter values
        measure_func: Function that takes parameter value and returns dict of results
        show_progress: Show progress bar (default True)
        description: Description for progress bar

    Returns:
        List of measurement dictionaries with parameter value included

    Example::

        from rf_bench.automation import sweep
        import numpy as np

        def measure_gain(freq_hz):
            sdg.set_frequency(1, freq_hz)
            ssa.set_center_freq(freq_hz)
            _, power = ssa.get_peak()
            return {'output_dbm': power, 'gain_db': power - (-20)}

        results = sweep(
            parameter='freq_hz',
            values=np.logspace(6, 9, 50),
            measure_func=measure_gain,
            description='Frequency sweep'
        )

        # Each result includes {'freq_hz': ..., 'output_dbm': ..., 'gain_db': ...}
    """
    results = []
    values_list = list(values)

    iterator = tqdm(values_list, desc=description or f"{parameter} sweep",
                   disable=not show_progress)

    for value in iterator:
        # Call measurement function
        result = measure_func(value)

        # Add parameter value to result
        result[parameter] = value

        results.append(result)

        # Update progress bar with latest result
        if show_progress and result:
            # Show first numeric value in result
            for k, v in result.items():
                if isinstance(v, (int, float)) and k != parameter:
                    iterator.set_postfix({k: f"{v:.3g}"})
                    break

    return results


def sweep_grid(
    parameters: Dict[str, Iterable[float]],
    measure_func: Callable[[Dict[str, float]], Dict[str, Any]],
    show_progress: bool = True,
    description: str = None
) -> List[Dict[str, Any]]:
    """
    Sweep multiple parameters in a grid (all combinations).

    Args:
        parameters: Dict mapping parameter names to value lists
        measure_func: Function that takes dict of parameters and returns dict of results
        show_progress: Show progress bar (default True)
        description: Description for progress bar

    Returns:
        List of measurement dictionaries with all parameter values included

    Example::

        from rf_bench.automation import sweep_grid
        import numpy as np

        def measure_power(params):
            sdg.set_frequency(1, params['freq_hz'])
            sdg.set_level(1, params['input_dbm'])
            ssa.set_center_freq(params['freq_hz'])
            _, power = ssa.get_peak()
            return {'output_dbm': power}

        results = sweep_grid(
            parameters={
                'freq_hz': [1e6, 10e6, 100e6],
                'input_dbm': [-30, -20, -10]
            },
            measure_func=measure_power,
            description='2D sweep'
        )

        # 9 measurements total (3 frequencies × 3 power levels)
    """
    # Generate all combinations (Cartesian product)
    import itertools

    param_names = list(parameters.keys())
    param_values = [parameters[name] for name in param_names]
    combinations = list(itertools.product(*param_values))

    results = []

    iterator = tqdm(combinations, desc=description or "Grid sweep",
                   disable=not show_progress)

    for combo in iterator:
        # Build parameter dict for this combination
        params = dict(zip(param_names, combo))

        # Call measurement function
        result = measure_func(params)

        # Add all parameter values to result
        result.update(params)

        results.append(result)

        # Update progress bar
        if show_progress and result:
            # Show parameter values
            param_str = ', '.join(f"{k}={v:.3g}" for k, v in params.items())
            iterator.set_postfix_str(param_str)

    return results
