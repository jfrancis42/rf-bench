## Test Sequencing Framework

**Module:** `rf_bench.automation.testing`

Provides structured test procedures with pass/fail criteria, conditional execution, and report generation.

---

## Overview

The test sequencing framework transforms measurement scripts into **production test suites** with:

- **Pass/fail criteria** — Quantitative assertions with units
- **Test dependencies** — Skip tests if prerequisites fail
- **Report generation** — Text summaries with DUT metadata
- **Structured workflow** — pytest-inspired API for RF/hardware testing

---

## Quick Start

```python
from rf_bench.automation import TestSuite, test

class PSUTest(TestSuite):
    @test(name="Voltage Accuracy")
    def test_voltage(self):
        psu = self.instruments['psu']
        dmm = self.instruments['dmm']
        
        psu.set_voltage(1, 5.0)
        psu.enable(1)
        
        v_measured = dmm.read()
        
        # Assert voltage is within ±2%
        self.assert_between(v_measured, 4.9, 5.1, units='V')

# Run the test
suite = PSUTest(
    instruments={'psu': psu, 'dmm': dmm},
    dut_info={'model': 'PSU-123'},
    operator='N0GQ'
)

report = suite.run()
report.save('psu_test_report.txt')
```

---

## Core Classes

### `TestSuite`

Base class for all test suites. Subclass this and add `@test`-decorated methods.

**Constructor:**
```python
TestSuite(
    instruments: Dict[str, Any],      # Instrument instances
    dut_info: Dict[str, Any] = {},    # Device under test metadata
    operator: str = ""                # Operator name/callsign
)
```

**Methods:**
- `run(verbose=True) -> TestReport` — Run all tests, return report
- `assert_between(value, min, max, units="")` — Assert value in range
- `assert_greater_than(value, threshold, units="")` — Assert value > threshold
- `assert_less_than(value, threshold, units="")` — Assert value < threshold
- `assert_equal(value, expected, tolerance=0, units="")` — Assert value ≈ expected
- `assert_true(condition, message="")` — Assert condition is True
- `assert_false(condition, message="")` — Assert condition is False

---

### `@test` Decorator

Marks a method as a test.

**Signature:**
```python
@test(name: str, depends_on: Optional[str] = None)
```

**Parameters:**
- `name` — Human-readable test name (shown in report)
- `depends_on` — Method name this test depends on (skip if that fails)

**Example:**
```python
@test(name="Power Output", depends_on="test_setup")
def test_power(self):
    ...
```

---

### `TestReport`

Contains results from a test suite run.

**Properties:**
- `passed: bool` — True if all non-skipped tests passed
- `num_passed: int` — Number of passed tests
- `num_failed: int` — Number of failed tests
- `num_skipped: int` — Number of skipped tests
- `num_total: int` — Total number of tests

**Methods:**
- `summary() -> str` — Generate text summary
- `save(path: str)` — Save report to file

---

### `TestResult`

Result of a single test.

**Fields:**
- `name: str` — Test name
- `passed: bool` — True if test passed
- `duration_s: float` — Time taken (seconds)
- `value: Optional[float]` — Measured value (for quantitative tests)
- `units: Optional[str]` — Measurement units
- `expected_min: Optional[float]` — Expected minimum value
- `expected_max: Optional[float]` — Expected maximum value
- `skipped: bool` — True if test was skipped
- `skip_reason: str` — Why test was skipped
- `error: Optional[str]` — Exception message (if error occurred)

---

## Assertions

All assertion methods follow the pattern:

```python
self.assert_<condition>(value, ..., units="")
```

### `assert_between(value, min_val, max_val, units="")`

Assert value is in range [min, max] inclusive.

**Example:**
```python
gain_db = 22.3
self.assert_between(gain_db, 20.0, 24.0, units='dB')
# PASS: 22.3 dB is between 20.0 and 24.0
```

**Failure message:**
```
22.3000 dB not in range [20.0000, 24.0000]
```

---

### `assert_greater_than(value, threshold, units="")`

Assert value > threshold.

**Example:**
```python
p1db_dbm = 10.5
self.assert_greater_than(p1db_dbm, 10.0, units='dBm')
# PASS: 10.5 > 10.0
```

---

### `assert_less_than(value, threshold, units="")`

Assert value < threshold.

**Example:**
```python
h2_dbc = -45.2
self.assert_less_than(h2_dbc, -40.0, units='dBc')
# PASS: -45.2 < -40.0
```

---

### `assert_equal(value, expected, tolerance=0, units="")`

Assert value equals expected (within tolerance).

**Example:**
```python
freq_mhz = 100.003
self.assert_equal(freq_mhz, 100.0, tolerance=0.01, units='MHz')
# PASS: |100.003 - 100.0| = 0.003 < 0.01
```

---

### `assert_true(condition, message="")` / `assert_false(condition, message="")`

Assert boolean condition.

**Example:**
```python
self.assert_true('SDM3045X' in idn, f"Expected SDM, got: {idn}")
```

---

## Test Dependencies

Use `depends_on` to create test chains. If a dependency fails, dependent tests are skipped.

**Example:**
```python
class AmplifierTest(TestSuite):
    @test(name="Connection Check")
    def test_connection(self):
        idn = self.instruments['amp'].identify()
        self.assert_true('AMP' in idn)
    
    @test(name="Gain", depends_on='test_connection')
    def test_gain(self):
        # Only runs if test_connection passed
        ...
    
    @test(name="Compression", depends_on='test_gain')
    def test_compression(self):
        # Only runs if test_gain passed
        ...
```

**Dependency chain:**
```
test_connection → test_gain → test_compression
```

If `test_connection` fails:
- `test_gain` is **skipped** (reason: "Dependency 'test_connection' failed")
- `test_compression` is **skipped** (reason: "Dependency 'test_gain' failed")

---

## Passing Data Between Tests

Store results in instance variables (`self._<name>`) to use in later tests.

**Example:**
```python
@test(name="Measure Gain at 1 GHz")
def test_gain_1ghz(self):
    gain = measure_gain(1e9)
    self._gain_1ghz = gain  # Store for later
    self.assert_between(gain, 20, 24, units='dB')

@test(name="Measure Gain at 2 GHz")
def test_gain_2ghz(self):
    gain = measure_gain(2e9)
    self._gain_2ghz = gain  # Store for later
    self.assert_between(gain, 20, 24, units='dB')

@test(name="Check Gain Flatness", depends_on='test_gain_2ghz')
def test_flatness(self):
    flatness = abs(self._gain_1ghz - self._gain_2ghz)
    self.assert_less_than(flatness, 1.5, units='dB')
```

---

## Report Format

### Text Report

```
======================================================================
TEST REPORT: PSUAccuracyTest
======================================================================
Timestamp: 2026-06-15T16:23:35.525328
Duration: 9.0s
Operator: N0GQ

Device Under Test:
  model: SPD3303X-E
  serial: SPD3XJFD7R5914
  load: 1Ω 20W resistor

----------------------------------------------------------------------
TEST RESULTS
----------------------------------------------------------------------
PASS: PSU Connection - OK (0.24s)
PASS: Current Limiting - OK (0.37s)
PASS: Voltage Accuracy at 1V - OK (2.36s)
PASS: Voltage Accuracy at 2V - OK (1.35s)
FAIL: Voltage Accuracy at 3V - 3.5000 V not in range [2.7000, 3.3000] (1.52s)
SKIP: Output Disable - Dependency 'test_voltage_3v' failed

======================================================================
SUMMARY
======================================================================
Overall: FAIL
Passed:  4/6
Failed:  1/6
Skipped: 1/6
======================================================================
```

---

## Complete Example: PSU Test Suite

```python
from rf_bench.automation import TestSuite, test
from rf_bench.instruments import Registry
import time

class PSUAccuracyTest(TestSuite):
    """Power supply accuracy verification."""

    @test(name="PSU Connection")
    def test_connection(self):
        """Verify PSU responds to *IDN?"""
        psu = self.instruments['psu']
        idn = psu.identify()
        self.assert_true('SPD3303X' in idn, f"Expected SPD3303X, got: {idn}")

    @test(name="Voltage Accuracy at 1V", depends_on='test_connection')
    def test_voltage_1v(self):
        """Check PSU voltage accuracy at 1V setpoint."""
        psu = self.instruments['psu']
        dmm = self.instruments['dmm']

        psu.set_voltage(1, 1.0)
        psu.set_current(1, 3.2)
        psu.enable(1)
        time.sleep(0.3)

        dmm.configure_vdc()
        v_measured = dmm.read()

        psu.disable(1)

        # ±10% tolerance
        self.assert_between(v_measured, 0.9, 1.1, units='V')

    @test(name="Current Limiting", depends_on='test_connection')
    def test_current_limit(self):
        """Verify PSU current limiting works."""
        psu = self.instruments['psu']

        psu.set_voltage(1, 5.0)
        psu.set_current(1, 0.5)
        psu.enable(1)
        time.sleep(0.3)

        i_measured = psu.measure_current(1)
        psu.disable(1)

        # Current should be at or near limit
        self.assert_between(i_measured, 0.45, 0.55, units='A')


# Connect to instruments
registry = Registry()
psu = registry.get('power-supply')
dmm = registry.get('multimeter')

# Run test suite
suite = PSUAccuracyTest(
    instruments={'psu': psu, 'dmm': dmm},
    dut_info={'model': 'SPD3303X-E', 'serial': 'SPD3XJFD7R5914'},
    operator='N0GQ'
)

report = suite.run()
report.save('psu_test_report.txt')

# Cleanup
psu.disable(1)
psu.close()
dmm.close()
```

---

## Comparison to pytest

| Feature | pytest | rf_bench.testing |
|---------|--------|------------------|
| Test definition | `def test_*()` | `@test(name="...")` |
| Assertions | `assert x > 0` | `self.assert_greater_than(x, 0)` |
| Setup/teardown | `@pytest.fixture` | Manual in `__init__` or test |
| Test dependencies | `@pytest.mark.depends` (plugin) | `depends_on=` (built-in) |
| Reports | Text/HTML via plugins | `TestReport.save()` |
| Target | Software testing | Hardware/RF testing |
| Quantitative units | No | Yes (dB, dBm, V, A, etc.) |

**Key difference:** rf_bench.testing is designed for **quantitative measurements with units**, not just pass/fail boolean checks.

---

## Design Rationale

### Why not pytest?

pytest is excellent for software testing but lacks features needed for RF/hardware work:

1. **No unit support** — RF measurements need dB, dBm, dBc, V, A, etc.
2. **No quantitative assertions** — `assert_between(gain, 20, 24, units='dB')` vs manual `assert 20 <= gain <= 24`
3. **No DUT metadata** — Hardware tests need serial numbers, cal dates, etc.
4. **Complex fixture system** — Instruments are passed directly, not via dependency injection

### Why class-based?

Hardware tests naturally group by **device** (amplifier, PSU, antenna), not by function. Class-based suites make it easy to:

- Share instrument handles across tests (`self.instruments`)
- Pass data between tests (`self._gain_1ghz`)
- Organize related tests in one file
- Generate reports per DUT

---

## Integration with MeasurementSequence

The test framework **complements** `MeasurementSequence` — use both together:

**MeasurementSequence** for:
- Data collection (sweeps, parameter variation)
- Automatic logging
- Progress reporting

**TestSuite** for:
- Pass/fail verification
- Production test automation
- Report generation

**Example: Amplifier sweep + test:**

```python
from rf_bench.automation import MeasurementSequence, TestSuite, test
import numpy as np

# 1. Collect data with MeasurementSequence
seq = MeasurementSequence("Amplifier Gain Sweep")

@seq.step("Measure Gain")
def measure(sdg, ssa):
    freq = seq.context['freq_hz']
    gain = measure_gain(sdg, ssa, freq)
    return {'gain_db': gain}

results = seq.sweep(
    parameter='freq_hz',
    values=np.logspace(8, 9, 20),  # 100 MHz - 1 GHz
    instruments={'sdg': sdg, 'ssa': ssa}
)

seq.save()  # Log sweep data

# 2. Verify specs with TestSuite
class AmplifierVerify(TestSuite):
    @test(name="Gain Specification")
    def test_gain_spec(self):
        """Check all gains are within spec."""
        for result in results:
            gain = result['gain_db']
            freq = result['freq_hz']
            
            # Spec: 20-24 dB gain across band
            self.assert_between(gain, 20, 24, units='dB')

suite = AmplifierVerify(instruments={}, dut_info={'sweep_points': len(results)})
report = suite.run()
report.save('amplifier_verification.txt')
```

---

## Best Practices

### 1. One assertion per test

```python
# Good
@test(name="Gain at 1 GHz")
def test_gain_1ghz(self):
    gain = measure_gain(1e9)
    self.assert_between(gain, 20, 24, units='dB')

@test(name="Gain at 2 GHz")
def test_gain_2ghz(self):
    gain = measure_gain(2e9)
    self.assert_between(gain, 20, 24, units='dB')

# Bad - multiple assertions in one test
@test(name="All Gains")
def test_all_gains(self):
    self.assert_between(measure_gain(1e9), 20, 24, units='dB')
    self.assert_between(measure_gain(2e9), 20, 24, units='dB')  # Never runs if first fails
```

### 2. Use dependencies to build test chains

```python
# Good - skip compression if gain fails
@test(name="Gain")
def test_gain(self):
    ...

@test(name="Compression", depends_on='test_gain')
def test_compression(self):
    ...  # Only runs if gain passed
```

### 3. Include units in assertions

```python
# Good
self.assert_between(gain_db, 20, 24, units='dB')

# Bad
self.assert_between(gain_db, 20, 24)  # What units?
```

### 4. Provide DUT metadata

```python
# Good
suite = PSUTest(
    instruments={'psu': psu},
    dut_info={
        'model': 'SPD3303X-E',
        'serial': 'SPD3XJFD7R5914',
        'cal_date': '2026-01-15',
        'load': '1Ω 20W'
    },
    operator='N0GQ'
)

# Bad
suite = PSUTest(instruments={'psu': psu})  # No traceability
```

---

## Examples

See `automation/examples/`:
- `psu_test_suite.py` — PSU accuracy verification (real hardware)
- `amplifier_test_suite.py` — Amplifier characterization (simulated)

---

## Future Enhancements

Planned features (not yet implemented):

- **PDF report generation** — `report.save_pdf('report.pdf')`
- **Parallel test execution** — Run independent tests concurrently
- **Test fixtures** — Setup/teardown hooks
- **Test discovery** — Auto-find test suites in directory
- **HTML reports** — Web-based test results
- **Historical tracking** — Compare results over time
- **Pass/fail trends** — Track quality metrics

---

## API Reference

See inline docstrings in `rf_bench.automation.testing` for complete API documentation.
