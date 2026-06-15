# rf-bench-automation

Production-ready test automation framework for rf-bench. Provides complete workflow from measurement to verification with automatic error handling, calibration management, and structured reporting.

## Features

### Tier 1: Core Automation
- **MeasurementSequence**: Organize measurements into reusable steps
- **Parameter sweeps**: 1D and multi-dimensional sweeps with progress bars
- **Automatic logging**: Structured data storage (CSV/HDF5) with metadata
- **Data search**: Query historical measurements by tags, operator, date
- **Instrument registry**: Automatic connection management
- **Retry logic**: Handle transient failures automatically

### Tier 2: Production Features
- **Test Sequencing**: TestSuite with pass/fail criteria and reports
- **Calibration Management**: Frequency-dependent corrections (cable loss, antenna factors)
- **Measurement Templates**: Pre-built sequences for common measurements
- **Robust Connections**: Automatic retry and reconnection on network errors

## Installation

```bash
cd ~/Dropbox/build/rf-bench/automation
pip install -e .
```

For HDF5 support:

```bash
pip install -e ".[hdf5]"
```

## Quick Start

### Simple Measurement

```python
from rf_bench.automation import MeasurementSequence

seq = MeasurementSequence("PSU Voltage Test")

@seq.step("Configure PSU")
def setup(psu):
    psu.set_voltage(1, 5.0)
    psu.enable(1)

@seq.step("Measure Voltage")
def measure(dmm):
    voltage = dmm.read()
    return {'voltage_v': voltage}

# Run the sequence
results = seq.run_steps(instruments={'psu': psu, 'dmm': dmm})
```

### Frequency Sweep

```python
from rf_bench.automation import MeasurementSequence
import numpy as np

seq = MeasurementSequence("Amplifier Gain vs Frequency")

@seq.step("Configure Signal Generator")
def setup_sdg(sdg):
    # Use seq.context to access sweep parameters
    freq = seq.context['freq_hz']
    sdg.set_sine(1, freq_hz=freq, level_dbm=-20)
    sdg.output_on(1)

@seq.step("Measure Output Power")
def measure_output(ssa):
    freq = seq.context['freq_hz']
    ssa.set_center_span(freq, 100e3)
    ssa.peak_search()
    _, power = ssa.get_peak()
    return {'output_dbm': power, 'gain_db': power - (-20)}

# Run frequency sweep (1 MHz to 1 GHz, 50 points)
results = seq.sweep(
    parameter='freq_hz',
    values=np.logspace(6, 9, 50),
    instruments={'sdg': sdg, 'ssa': ssa}
)

# Save results with metadata
seq.metadata(operator='N0GQ', dut='Amplifier XYZ', temp_c=23.5)
path = seq.save()  # Auto-saves to ~/.rf-bench/data/
print(f"Results saved to {path}")
```

### 2D Grid Sweep

```python
from rf_bench.automation import MeasurementSequence

seq = MeasurementSequence("Compression Test")

@seq.step("Configure and Measure")
def measure(sdg, ssa):
    freq = seq.context['freq_hz']
    power = seq.context['input_dbm']
    
    sdg.set_sine(1, freq_hz=freq, level_dbm=power)
    ssa.set_center_span(freq, 100e3)
    ssa.peak_search()
    _, output_power = ssa.get_peak()
    
    return {'output_dbm': output_power}

# Sweep both frequency and input power
results = seq.sweep_grid(
    parameters={
        'freq_hz': [1e6, 10e6, 100e6, 1e9],
        'input_dbm': [-30, -20, -10, 0]
    },
    instruments={'sdg': sdg, 'ssa': ssa}
)

# 16 measurements total (4 frequencies × 4 power levels)
seq.save()
```

### Using Standalone Sweep Functions

```python
from rf_bench.automation import sweep
import numpy as np

def measure_gain(freq_hz):
    sdg.set_frequency(1, freq_hz)
    ssa.set_center_freq(freq_hz)
    _, power = ssa.get_peak()
    return {'output_dbm': power, 'gain_db': power - (-20)}

# Simple sweep without MeasurementSequence
results = sweep(
    parameter='freq_hz',
    values=np.logspace(6, 9, 50),
    measure_func=measure_gain,
    description='Quick frequency sweep'
)

# Manually save with MeasurementLog
from rf_bench.automation import MeasurementLog

log = MeasurementLog('quick_sweep')
log.extend(results)
log.metadata(operator='N0GQ')
log.save()
```

### Retry Logic

```python
from rf_bench.automation import retry

@retry(attempts=3, delay=1.0, backoff=2.0)
def measure_voltage(dmm):
    return dmm.read()

# Will retry up to 3 times with delays of 1s, 2s, 4s
voltage = measure_voltage(dmm)
```

### Error Handling in Sequences

```python
seq = MeasurementSequence("Robust Measurement")

@seq.step("Flaky measurement", retry_on_error=True, retry_attempts=5)
def measure(dmm):
    # This step will automatically retry up to 5 times on error
    return {'voltage': dmm.read()}
```

## Data Storage

Results are saved to `~/.rf-bench/data/` by default. CSV format includes metadata as YAML-style comments:

```csv
# Measurement Data
# name: Amplifier Gain vs Frequency
# timestamp: 2026-06-15T14:30:22Z
# operator: N0GQ
# dut: Amplifier XYZ
# temperature_c: 23.5
#
freq_hz,output_dbm,gain_db
1000000.0,-43.2,23.2
1258925.4,-42.8,22.8
...
```

## Loading Saved Data

```python
from rf_bench.automation.logging import load_csv

metadata, data = load_csv('amplifier_gain_20260615_143022.csv')

print(f"Operator: {metadata['operator']}")
print(f"Data points: {len(data)}")

# data is a list of dicts
for point in data:
    print(f"{point['freq_hz']} Hz: {point['gain_db']} dB")
```

## API Reference

### MeasurementSequence

- `__init__(name, description='')` - Create new sequence
- `metadata(**kwargs)` - Add metadata
- `@step(description, retry_on_error=False, retry_attempts=3)` - Register step
- `run_steps(instruments, skip_steps=[])` - Execute all steps
- `sweep(parameter, values, instruments, show_progress=True)` - 1D sweep
- `sweep_grid(parameters, instruments, show_progress=True)` - Grid sweep
- `save(filename=None, format='csv')` - Save results

### MeasurementLog

- `__init__(name, data_dir=None)` - Create log
- `metadata(**kwargs)` - Add metadata
- `append(data_point)` - Add single data point
- `extend(data_points)` - Add multiple data points
- `save(filename=None, format='csv')` - Save to file

### sweep()

- `sweep(parameter, values, measure_func, show_progress=True, description=None)` - 1D parameter sweep

### sweep_grid()

- `sweep_grid(parameters, measure_func, show_progress=True, description=None)` - Multi-dimensional sweep

### @retry()

- `@retry(attempts=3, delay=1.0, backoff=2.0, exceptions=(Exception,))` - Retry decorator

## Test Sequencing

```python
from rf_bench.automation import TestSuite, test

class PSUTest(TestSuite):
    @test(name="Voltage Accuracy")
    def test_voltage(self):
        psu = self.instruments['psu']
        dmm = self.instruments['dmm']
        
        psu.set_voltage(1, 5.0)
        psu.enable(1)
        v = dmm.read()
        psu.disable(1)
        
        # Quantitative assertion with units
        self.assert_between(v, 4.9, 5.1, units='V')

# Run test suite
suite = PSUTest(
    instruments={'psu': psu, 'dmm': dmm},
    dut_info={'model': 'SPD3303X', 'serial': 'S-001'},
    operator='N0GQ'
)

report = suite.run()
report.save('psu_test_report.txt')
```

See `TESTING.md` for complete documentation.

## Calibration Management

```python
from rf_bench.automation import CalibrationManager

# Load cable loss calibration
cal = CalibrationManager()
cable = cal.load('cables/lmr400_10ft.yaml')

# Apply correction
loss_db = cable.get_correction(146e6)  # 0.19 dB at 146 MHz
corrected_power = measured_power + loss_db

# Batch correction for sweep data
corrected_powers = cable.apply_batch(powers, frequencies)
```

## Measurement Templates

```python
from rf_bench.automation.templates import amplifier_gain_sweep

# Pre-built amplifier gain measurement
result = amplifier_gain_sweep(
    sdg=sdg,
    ssa=ssa,
    freq_start_hz=100e6,
    freq_stop_hz=1e9,
    num_points=50,
    input_level_dbm=-20,
    operator='N0GQ'
)

print(f"Mean gain: {result.mean_gain_db:.2f} dB")
print(f"Flatness: {result.flatness_db:.2f} dB")
result.seq.save('amplifier_gain.csv')
```

Available templates:
- `amplifier_gain_sweep`, `amplifier_p1db`, `amplifier_harmonics`
- `power_supply_accuracy`, `power_supply_ripple`, `power_supply_load_regulation`
- `signal_generator_accuracy`, `signal_generator_flatness`

## Robust Connections

```python
from rf_bench.automation import RobustConnection
from rf_bench.siglent import SDM3045X

# Wrap connection with automatic retry
with RobustConnection(SDM3045X, '10.1.1.63', retry_attempts=3) as dmm:
    voltage = dmm.read()  # Auto-retries on network glitch
```

## Data Search

```python
from rf_bench.automation import search_measurements

# Find measurements by criteria
results = search_measurements(
    tags=['amplifier', 'gain'],
    operator='N0GQ',
    date_after='2026-06-01'
)

# Or use CLI tool
# rf-bench-data search --tags amplifier --operator N0GQ
```

## Examples

See `examples/` directory for complete working examples:

**Basic automation:**
- `amplifier_gain_sweep.py` - MeasurementSequence with frequency sweep

**Test sequencing:**
- `psu_test_suite.py` - Real hardware test with pass/fail
- `amplifier_test_suite.py` - Simulated amplifier test

**Calibration:**
- `calibration_demo.py` - Load/apply/create calibrations

## Documentation

- `README.md` - This file (quick start)
- `TESTING.md` - Complete test sequencing documentation
- `local/tier2-complete.md` - Full Tier 2 feature documentation
- `local/automation-framework-complete.md` - Complete framework documentation

## Requirements

- Python 3.8+
- numpy
- tqdm (for progress bars)
- h5py (optional, for HDF5 format)
- pyyaml (for calibration files)

## License

MIT
