# rf-bench-drivers-utils

Pure RF math utilities for bench instrument automation. Part of the `rf-bench-drivers` family of packages.

## Install

```
pip install rf-bench-drivers-utils
```

## Import

```python
from rf_bench.utils import dbm_to_vpp, thermal_noise_floor, format_freq
```

## What's in the box

`rf_bench.utils` is a single module (`rf_utils.py`) of pure functions. No instrument connections, no side effects, numpy is the only dependency.

| Category | Key functions |
|----------|--------------|
| Power / voltage | `dbm_to_vpp`, `vpp_to_dbm`, `dbm_to_vrms`, `vrms_to_dbm`, `dbm_to_watts`, `watts_to_dbm`, `dbm_to_uv`, `uv_to_dbm` |
| Power ratio / extended dB | `db_to_linear`, `linear_to_db`, `db_to_voltage_ratio`, `voltage_ratio_to_db`, `dbm_to_dbw`, `dbw_to_dbm`, `dbm_to_dbuv`, `dbuv_to_dbm` |
| Impedance / reflection | `rl_to_vswr`, `vswr_to_rl`, `gamma_to_vswr`, `vswr_to_gamma`, `rl_to_gamma`, `gamma_to_rl`, vectorized variants |
| Noise / dynamic range | `thermal_noise_floor`, `noise_figure_from_mds`, `mds_from_noise_figure`, `ip3_from_imd`, `ip3_to_dynamic_range`, `cascaded_noise_figure`, `noise_temp_to_nf`, `nf_to_noise_temp` |
| Propagation / antenna | `wavelength`, `quarter_wave`, `half_wave`, `freespace_path_loss` |
| Passive components | `capacitive_reactance`, `inductive_reactance`, `lc_resonant_freq`, `l_from_resonant`, `c_from_resonant`, `q_factor`, `bw_from_q`, `parallel_resistance`, `voltage_divider`, `skin_depth` |
| Attenuator design | `pi_attenuator`, `t_attenuator` |
| IM products | `intermod_products` |
| S-meter | `s_unit_to_dbm`, `dbm_to_s_unit` |
| Frequency formatting | `format_freq`, `format_freq_short` |
| Standard value series | `nearest_rbw`, `nearest_value`, `SIGLENT_RBW_SERIES`, `E12_SERIES`, `E24_SERIES`, `E48_SERIES`, `E96_SERIES` |
| Two-channel measurement | `dominant_frequency`, `gain_phase_from_fft`, `complex_impedance_series` |

All functions default to 50 Ω reference impedance where applicable. Frequencies are in Hz throughout; use `format_freq()` for human-readable display.

## Quick examples

```python
from rf_bench.utils import (
    dbm_to_vpp, thermal_noise_floor, rl_to_vswr,
    cascaded_noise_figure, pi_attenuator, format_freq,
)

# 0 dBm into 50 Ω
print(dbm_to_vpp(0))           # 0.6325 Vpp

# Thermal noise floor at 500 Hz bandwidth
print(thermal_noise_floor(500))  # -143.0 dBm (approx)

# Return loss to VSWR
print(rl_to_vswr(20))           # 1.222

# Cascaded noise figure: 2 dB cable -> 20 dB LNA (3 dB NF) -> IF amp
print(cascaded_noise_figure([(-2, 2), (20, 3), (10, 5)]))  # ~5.06 dB

# Pi attenuator values for 6 dB at 50 Ω
print(pi_attenuator(6))         # {'r_shunt': 150.5, 'r_series': 37.35}

# Frequency formatting
print(format_freq(14_200_000))  # '14.2000 MHz'
```

## Related packages

This package is one of four that together replace the original `rf-bench` monolith:

| Package | PyPI name | Import | Contents |
|---------|-----------|--------|----------|
| **rf-bench-drivers-utils** | `rf-bench-drivers-utils` | `rf_bench.utils` | RF math (this package) |
| Siglent drivers | `rf-bench-drivers-siglent` | `rf_bench.siglent` | SSA3000X, SDG1000X, SDS2000X, SDM3000X, SPD3303X |
| Icom drivers | `rf-bench-drivers-icom` | `rf_bench.icom` | IC7300 via Hamlib rigctld |
| Yaesu drivers | `rf-bench-drivers-yaesu` | `rf_bench.yaesu` | FT891 via Hamlib rigctld |

All four packages share the `rf_bench` namespace; install as many as you need.

## License

GPL-3.0-or-later
