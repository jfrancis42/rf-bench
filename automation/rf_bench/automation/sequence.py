"""
sequence.py — MeasurementSequence class for organizing multi-step measurements

Provides decorator-based step definition, automatic error handling,
progress reporting, and data logging.
"""

import time
import functools
from typing import Callable, Dict, Any, List, Optional, Iterable
from datetime import datetime
from .logging import MeasurementLog
from .sweep import sweep, sweep_grid
from .retry import retry


class MeasurementSequence:
    """
    High-level measurement sequence organizer.

    Provides a framework for building multi-instrument measurement workflows
    with automatic error handling, progress reporting, and data logging.

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
            ssa.set_center_span(seq.context['freq_hz'], 100e3)
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

    def __init__(self, name: str, description: str = ""):
        """
        Initialize measurement sequence.

        Args:
            name: Name of this measurement sequence
            description: Optional longer description
        """
        self.name = name
        self.description = description
        self._steps = []
        self._instruments = {}
        self.context = {}  # Shared context for sweep parameters
        self.results = []
        self._log = MeasurementLog(name)
        self._start_time = None
        self._metadata = {}

    def metadata(self, **kwargs):
        """
        Add metadata to this sequence.

        Args:
            **kwargs: Arbitrary metadata key-value pairs

        Example::

            seq.metadata(
                operator='N0GQ',
                dut='Amplifier XYZ',
                temperature_c=23.5
            )
        """
        self._metadata.update(kwargs)
        self._log.metadata(**kwargs)

    def step(self, description: str, retry_on_error: bool = False, retry_attempts: int = 3):
        """
        Decorator to register a measurement step.

        Args:
            description: Human-readable description of this step
            retry_on_error: Automatically retry if step fails (default False)
            retry_attempts: Number of retry attempts if retry_on_error=True

        Example::

            @seq.step("Configure PSU")
            def setup_psu(psu):
                psu.set_voltage(1, 5.0)
                psu.enable(1)

            @seq.step("Measure voltage", retry_on_error=True, retry_attempts=3)
            def measure_v(dmm):
                return {'voltage': dmm.read()}
        """
        def decorator(func: Callable) -> Callable:
            # Optionally wrap with retry
            if retry_on_error:
                func = retry(attempts=retry_attempts)(func)

            # Register step
            self._steps.append({
                'func': func,
                'description': description,
                'name': func.__name__
            })

            # Return original function (so it can still be called directly)
            return func

        return decorator

    def run_steps(self, instruments: Dict[str, Any] = None, skip_steps: List[str] = None):
        """
        Execute all registered steps in order.

        Args:
            instruments: Dict of instrument instances (keyed by name used in step functions)
            skip_steps: List of step names to skip

        Returns:
            Dict of results from each step (keyed by step name)

        Example::

            results = seq.run_steps(instruments={'psu': psu, 'dmm': dmm})
        """
        if instruments:
            self._instruments.update(instruments)

        skip_steps = skip_steps or []
        step_results = {}

        print(f"\n{'='*60}")
        print(f"Measurement Sequence: {self.name}")
        if self.description:
            print(f"Description: {self.description}")
        print(f"{'='*60}\n")

        for i, step_info in enumerate(self._steps, 1):
            step_name = step_info['name']
            step_desc = step_info['description']
            step_func = step_info['func']

            if step_name in skip_steps:
                print(f"[{i}/{len(self._steps)}] SKIP: {step_desc}")
                continue

            print(f"[{i}/{len(self._steps)}] {step_desc}...", end=' ', flush=True)

            try:
                start = time.time()

                # Call step function with only the instruments it expects
                import inspect
                sig = inspect.signature(step_func)
                params = sig.parameters

                # Build kwargs with only requested instruments
                step_kwargs = {}
                for param_name in params:
                    if param_name in self._instruments:
                        step_kwargs[param_name] = self._instruments[param_name]

                result = step_func(**step_kwargs)

                elapsed = time.time() - start

                print(f"✓ ({elapsed:.2f}s)")

                if result:
                    step_results[step_name] = result

            except Exception as e:
                print(f"✗ FAILED: {e}")
                raise

        print(f"\n{'='*60}")
        print(f"Sequence complete!")
        print(f"{'='*60}\n")

        return step_results

    def sweep(
        self,
        parameter: str,
        values: Iterable[float],
        instruments: Dict[str, Any] = None,
        show_progress: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Run all steps for each value of a swept parameter.

        Args:
            parameter: Name of parameter to sweep
            values: Iterable of parameter values
            instruments: Dict of instrument instances
            show_progress: Show progress bar

        Returns:
            List of result dicts (one per sweep point)

        Example::

            results = seq.sweep(
                parameter='freq_hz',
                values=np.logspace(6, 9, 50),
                instruments={'sdg': sdg, 'ssa': ssa}
            )
        """
        if instruments:
            self._instruments.update(instruments)

        if self._start_time is None:
            self._start_time = datetime.now()

        def measure_point(value):
            # Store sweep parameter in context (accessible via seq.context)
            self.context[parameter] = value

            # Run all steps
            try:
                result = self.run_steps(skip_steps=[])
                # Flatten results from all steps into one dict
                flat_result = {}
                for step_results in result.values():
                    if isinstance(step_results, dict):
                        flat_result.update(step_results)
                return flat_result
            except Exception as e:
                print(f"Error at {parameter}={value}: {e}")
                return {}

        # Use sweep utility
        results = sweep(
            parameter=parameter,
            values=values,
            measure_func=measure_point,
            show_progress=show_progress,
            description=f"{self.name}: {parameter} sweep"
        )

        # Store in log
        self._log.extend(results)
        self.results = results

        return results

    def sweep_grid(
        self,
        parameters: Dict[str, Iterable[float]],
        instruments: Dict[str, Any] = None,
        show_progress: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Run all steps for all combinations of multiple parameters (grid sweep).

        Args:
            parameters: Dict mapping parameter names to value lists
            instruments: Dict of instrument instances
            show_progress: Show progress bar

        Returns:
            List of result dicts (one per grid point)

        Example::

            results = seq.sweep_grid(
                parameters={
                    'freq_hz': [1e6, 10e6, 100e6],
                    'power_dbm': [-30, -20, -10]
                },
                instruments={'sdg': sdg, 'ssa': ssa}
            )
        """
        if instruments:
            self._instruments.update(instruments)

        if self._start_time is None:
            self._start_time = datetime.now()

        def measure_point(params: Dict[str, float]):
            # Store all sweep parameters in context
            self.context.update(params)

            # Run all steps
            try:
                result = self.run_steps(skip_steps=[])
                # Flatten results
                flat_result = {}
                for step_results in result.values():
                    if isinstance(step_results, dict):
                        flat_result.update(step_results)
                return flat_result
            except Exception as e:
                param_str = ', '.join(f"{k}={v}" for k, v in params.items())
                print(f"Error at {param_str}: {e}")
                return {}

        # Use sweep_grid utility
        results = sweep_grid(
            parameters=parameters,
            measure_func=measure_point,
            show_progress=show_progress,
            description=f"{self.name}: grid sweep"
        )

        # Store in log
        self._log.extend(results)
        self.results = results

        return results

    def save(self, filename: Optional[str] = None, format: str = 'csv'):
        """
        Save measurement results to file.

        Args:
            filename: Output filename (default: auto-generated)
            format: 'csv' or 'hdf5'

        Returns:
            Path to saved file

        Example::

            path = seq.save()
            print(f"Results saved to {path}")
        """
        # Add sequence metadata
        if self._start_time:
            elapsed = (datetime.now() - self._start_time).total_seconds()
            self._log.metadata(duration_seconds=elapsed)

        self._log.metadata(
            sequence_name=self.name,
            description=self.description,
            step_count=len(self._steps)
        )

        return self._log.save(filename=filename, format=format)

    def __repr__(self):
        return f"MeasurementSequence('{self.name}', {len(self._steps)} steps)"
