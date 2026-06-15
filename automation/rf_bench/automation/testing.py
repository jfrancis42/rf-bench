"""
Test Sequencing Framework

Provides structured test procedures with pass/fail criteria,
conditional execution, and report generation.

Example:
    from rf_bench.automation import TestSuite, test

    class AmplifierTest(TestSuite):
        @test(name="Gain at 1 GHz")
        def test_gain(self):
            result = measure_gain(self.instruments['sdg'],
                                  self.instruments['ssa'],
                                  freq_hz=1e9)
            self.assert_between(result, 20, 22, units='dB')

        @test(name="Compression Point", depends_on='test_gain')
        def test_compression(self):
            p1db = find_p1db(self.instruments['sdg'],
                            self.instruments['ssa'])
            self.assert_greater_than(p1db, 10, units='dBm')

    # Run test suite
    suite = AmplifierTest(
        instruments={'sdg': sdg, 'ssa': ssa},
        dut_info={'name': 'Amplifier XYZ', 'serial': '12345'}
    )

    report = suite.run()
    print(report.summary())
    report.save('amplifier_test_report.txt')
"""

import time
import functools
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from datetime import datetime
from pathlib import Path


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    passed: bool
    duration_s: float
    message: str = ""
    value: Optional[float] = None
    units: Optional[str] = None
    expected_min: Optional[float] = None
    expected_max: Optional[float] = None
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: str = ""

    def __str__(self):
        if self.skipped:
            return f"SKIP: {self.name} - {self.skip_reason}"

        status = "PASS" if self.passed else "FAIL"

        if self.value is not None:
            value_str = f"{self.value:.4f}"
            if self.units:
                value_str += f" {self.units}"

            if self.expected_min is not None and self.expected_max is not None:
                expected_str = f" (expected {self.expected_min:.4f}-{self.expected_max:.4f})"
            elif self.expected_min is not None:
                expected_str = f" (expected >{self.expected_min:.4f})"
            elif self.expected_max is not None:
                expected_str = f" (expected <{self.expected_max:.4f})"
            else:
                expected_str = ""

            return f"{status}: {self.name} = {value_str}{expected_str} ({self.duration_s:.2f}s)"

        return f"{status}: {self.name} - {self.message} ({self.duration_s:.2f}s)"


@dataclass
class TestReport:
    """Complete test suite report."""
    suite_name: str
    timestamp: str
    duration_s: float
    results: List[TestResult] = field(default_factory=list)
    dut_info: Dict[str, Any] = field(default_factory=dict)
    operator: str = ""

    @property
    def passed(self) -> bool:
        """True if all non-skipped tests passed."""
        return all(r.passed or r.skipped for r in self.results)

    @property
    def num_passed(self) -> int:
        return sum(1 for r in self.results if r.passed and not r.skipped)

    @property
    def num_failed(self) -> int:
        return sum(1 for r in self.results if not r.passed and not r.skipped)

    @property
    def num_skipped(self) -> int:
        return sum(1 for r in self.results if r.skipped)

    @property
    def num_total(self) -> int:
        return len(self.results)

    def summary(self) -> str:
        """Generate text summary."""
        lines = []
        lines.append("=" * 70)
        lines.append(f"TEST REPORT: {self.suite_name}")
        lines.append("=" * 70)
        lines.append(f"Timestamp: {self.timestamp}")
        lines.append(f"Duration: {self.duration_s:.1f}s")

        if self.operator:
            lines.append(f"Operator: {self.operator}")

        if self.dut_info:
            lines.append("\nDevice Under Test:")
            for key, value in self.dut_info.items():
                lines.append(f"  {key}: {value}")

        lines.append("\n" + "-" * 70)
        lines.append("TEST RESULTS")
        lines.append("-" * 70)

        for result in self.results:
            lines.append(str(result))

        lines.append("\n" + "=" * 70)
        lines.append("SUMMARY")
        lines.append("=" * 70)

        status = "PASS" if self.passed else "FAIL"
        lines.append(f"Overall: {status}")
        lines.append(f"Passed:  {self.num_passed}/{self.num_total}")

        if self.num_failed > 0:
            lines.append(f"Failed:  {self.num_failed}/{self.num_total}")

        if self.num_skipped > 0:
            lines.append(f"Skipped: {self.num_skipped}/{self.num_total}")

        lines.append("=" * 70)

        return "\n".join(lines)

    def save(self, path: Union[str, Path]):
        """Save report to text file."""
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w') as f:
            f.write(self.summary())

        print(f"\n✓ Report saved: {path}")


class TestAssertionError(AssertionError):
    """Custom exception for test assertions."""
    pass


def test(name: str, depends_on: Optional[str] = None):
    """
    Decorator to mark a method as a test.

    Args:
        name: Human-readable test name
        depends_on: Name of test method this depends on (skip if that fails)

    Example:
        @test(name="Power Output", depends_on="test_setup")
        def test_power(self):
            ...
    """
    def decorator(func: Callable) -> Callable:
        func._is_test = True
        func._test_name = name
        func._depends_on = depends_on
        return func
    return decorator


class TestSuite:
    """
    Base class for test suites.

    Subclass this and add @test-decorated methods.

    Example:
        class MyTest(TestSuite):
            @test(name="Gain Test")
            def test_gain(self):
                result = measure_gain()
                self.assert_between(result, 20, 22, units='dB')

        suite = MyTest(instruments={'sdg': sdg, 'ssa': ssa})
        report = suite.run()
    """

    def __init__(
        self,
        instruments: Optional[Dict[str, Any]] = None,
        dut_info: Optional[Dict[str, Any]] = None,
        operator: str = ""
    ):
        """
        Initialize test suite.

        Args:
            instruments: Dict mapping names to instrument instances
            dut_info: Device under test metadata (name, serial, etc.)
            operator: Name/callsign of operator
        """
        self.instruments = instruments or {}
        self.dut_info = dut_info or {}
        self.operator = operator
        self._results: List[TestResult] = []
        self._failed_tests: set = set()

    def run(self, verbose: bool = True) -> TestReport:
        """
        Run all @test methods in the suite.

        Args:
            verbose: Print progress messages

        Returns:
            TestReport with all results
        """
        start_time = time.time()
        timestamp = datetime.now().isoformat()

        if verbose:
            print("\n" + "=" * 70)
            print(f"TEST SUITE: {self.__class__.__name__}")
            print("=" * 70)
            if self.operator:
                print(f"Operator: {self.operator}")
            if self.dut_info:
                print("Device Under Test:")
                for key, value in self.dut_info.items():
                    print(f"  {key}: {value}")
            print()

        # Find all test methods
        test_methods = []
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if callable(attr) and hasattr(attr, '_is_test'):
                test_methods.append((attr_name, attr))

        # Sort tests by dependency (simple topological sort)
        sorted_methods = self._sort_by_dependency(test_methods)

        # Run each test
        for i, (method_name, method) in enumerate(sorted_methods, 1):
            test_name = method._test_name
            depends_on = method._depends_on

            # Check if dependency failed
            if depends_on and depends_on in self._failed_tests:
                result = TestResult(
                    name=test_name,
                    passed=False,
                    duration_s=0.0,
                    skipped=True,
                    skip_reason=f"Dependency '{depends_on}' failed"
                )
                self._results.append(result)

                if verbose:
                    print(f"[{i}/{len(sorted_methods)}] {result}")

                continue

            # Run the test
            if verbose:
                print(f"[{i}/{len(sorted_methods)}] Running: {test_name}...", end=" ", flush=True)

            test_start = time.time()

            try:
                method()

                # If we reach here, test passed
                test_duration = time.time() - test_start
                result = TestResult(
                    name=test_name,
                    passed=True,
                    duration_s=test_duration,
                    message="OK"
                )

                if verbose:
                    print(f"PASS ({test_duration:.2f}s)")

            except TestAssertionError as e:
                # Test failed (assertion)
                test_duration = time.time() - test_start
                result = TestResult(
                    name=test_name,
                    passed=False,
                    duration_s=test_duration,
                    message=str(e)
                )
                self._failed_tests.add(method_name)

                if verbose:
                    print(f"FAIL ({test_duration:.2f}s)")
                    print(f"    {e}")

            except Exception as e:
                # Test error (unexpected exception)
                test_duration = time.time() - test_start
                result = TestResult(
                    name=test_name,
                    passed=False,
                    duration_s=test_duration,
                    error=f"{type(e).__name__}: {e}"
                )
                self._failed_tests.add(method_name)

                if verbose:
                    print(f"ERROR ({test_duration:.2f}s)")
                    print(f"    {type(e).__name__}: {e}")

            self._results.append(result)

        total_duration = time.time() - start_time

        report = TestReport(
            suite_name=self.__class__.__name__,
            timestamp=timestamp,
            duration_s=total_duration,
            results=self._results,
            dut_info=self.dut_info,
            operator=self.operator
        )

        if verbose:
            print()
            print(report.summary())

        return report

    def _sort_by_dependency(self, test_methods):
        """Simple topological sort for test dependencies."""
        # Build dependency graph
        methods_by_name = {name: (name, method) for name, method in test_methods}

        sorted_methods = []
        visited = set()

        def visit(method_name):
            if method_name in visited:
                return

            visited.add(method_name)

            if method_name not in methods_by_name:
                return

            name, method = methods_by_name[method_name]

            # Visit dependencies first
            if hasattr(method, '_depends_on') and method._depends_on:
                visit(method._depends_on)

            sorted_methods.append((name, method))

        # Visit all methods
        for method_name, method in test_methods:
            visit(method_name)

        return sorted_methods

    # Assertion methods

    def assert_between(self, value: float, min_val: float, max_val: float, units: str = ""):
        """Assert value is between min and max (inclusive)."""
        if not (min_val <= value <= max_val):
            units_str = f" {units}" if units else ""
            raise TestAssertionError(
                f"{value:.4f}{units_str} not in range [{min_val:.4f}, {max_val:.4f}]"
            )

    def assert_greater_than(self, value: float, threshold: float, units: str = ""):
        """Assert value is greater than threshold."""
        if value <= threshold:
            units_str = f" {units}" if units else ""
            raise TestAssertionError(
                f"{value:.4f}{units_str} not greater than {threshold:.4f}"
            )

    def assert_less_than(self, value: float, threshold: float, units: str = ""):
        """Assert value is less than threshold."""
        if value >= threshold:
            units_str = f" {units}" if units else ""
            raise TestAssertionError(
                f"{value:.4f}{units_str} not less than {threshold:.4f}"
            )

    def assert_equal(self, value: float, expected: float, tolerance: float = 0.0, units: str = ""):
        """Assert value equals expected (within tolerance)."""
        if abs(value - expected) > tolerance:
            units_str = f" {units}" if units else ""
            tol_str = f" ±{tolerance:.4f}" if tolerance > 0 else ""
            raise TestAssertionError(
                f"{value:.4f}{units_str} != {expected:.4f}{tol_str}"
            )

    def assert_true(self, condition: bool, message: str = ""):
        """Assert condition is true."""
        if not condition:
            raise TestAssertionError(message or "Condition is False")

    def assert_false(self, condition: bool, message: str = ""):
        """Assert condition is false."""
        if condition:
            raise TestAssertionError(message or "Condition is True")
