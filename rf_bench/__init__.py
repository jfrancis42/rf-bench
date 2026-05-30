"""
rf_bench — Python drivers and RF utilities for bench instrument automation

Drivers connect via raw TCP/SCPI (Siglent instruments, port 5025) or Hamlib
rigctld (radios, port 4532). No NI-VISA or pyvisa required.

Subpackages::

    rf_bench.siglent   — SSA3000X, SDG1000X, SDS2000X, SDM3000X, SPD3303X
    rf_bench.icom      — IC7300
    rf_bench.yaesu     — FT891
    rf_bench.utils     — RF math: conversions, noise, impedance, propagation,
                         passive components, attenuators, IM products, S-meter

All public symbols are re-exported here for convenience::

    from rf_bench import SDG1000X, SPD3303X, IC7300, FT891, dbm_to_vpp, format_freq

Or import from subpackages directly::

    from rf_bench.siglent import SSA3000X, SDG1000X, SDM3000X, SPD3303X
    from rf_bench.icom import IC7300
    from rf_bench.utils import thermal_noise_floor, cascaded_noise_figure, pi_attenuator
"""

# Instrument classes
from .siglent import (
    SSA3000X, SDG1000X, SDS2000X, DBM_MIN, DBM_MAX,
    SDM3000X, SDM_RANGE_AUTO,
    SPD3303X, TRACKING_INDEPENDENT, TRACKING_SERIES, TRACKING_PARALLEL,
)
from .icom   import IC7300
from .yaesu  import FT891, PREAMP_OFF, PREAMP_AMP1

# RF utilities — re-exported flat for convenience
from .utils import (
    # Constants
    SPEED_OF_LIGHT, S9_HF_DBM, S9_VHF_DBM,
    # Power / voltage
    dbm_to_vpp, vpp_to_dbm,
    dbm_to_vrms, vrms_to_dbm,
    dbm_to_watts, watts_to_dbm,
    dbm_to_uv, uv_to_dbm,
    # Power ratio / extended dB
    db_to_linear, linear_to_db,
    db_to_voltage_ratio, voltage_ratio_to_db,
    dbm_to_dbw, dbw_to_dbm,
    dbm_to_dbuv, dbuv_to_dbm,
    # Impedance / reflection
    rl_to_vswr, vswr_to_rl,
    gamma_to_vswr, vswr_to_gamma,
    rl_to_gamma, gamma_to_rl,
    rl_to_vswr_v, vswr_to_rl_v, gamma_to_vswr_v,
    # Noise and dynamic range
    thermal_noise_floor,
    noise_figure_from_mds, mds_from_noise_figure,
    ip3_from_imd, ip3_to_dynamic_range,
    cascaded_noise_figure,
    noise_temp_to_nf, nf_to_noise_temp,
    # Propagation / antenna
    wavelength, quarter_wave, half_wave,
    freespace_path_loss,
    # Passive components
    capacitive_reactance, inductive_reactance,
    lc_resonant_freq, l_from_resonant, c_from_resonant,
    q_factor, bw_from_q,
    parallel_resistance, voltage_divider,
    skin_depth,
    # Attenuator design
    pi_attenuator, t_attenuator,
    # IM products
    intermod_products,
    # S-meter
    s_unit_to_dbm, dbm_to_s_unit,
    # Formatting
    format_freq, format_freq_short,
    # Standard value series
    nearest_rbw, nearest_value,
    SIGLENT_RBW_SERIES, E12_SERIES, E24_SERIES, E48_SERIES, E96_SERIES,
    # Two-channel measurement math
    dominant_frequency,
    gain_phase_from_fft,
    complex_impedance_series,
)

__version__ = "0.2.0"

__all__ = [
    # Siglent instruments
    "SSA3000X",
    "SDG1000X", "DBM_MIN", "DBM_MAX",
    "SDS2000X",
    "SDM3000X", "SDM_RANGE_AUTO",
    "SPD3303X", "TRACKING_INDEPENDENT", "TRACKING_SERIES", "TRACKING_PARALLEL",
    # Icom
    "IC7300",
    # Yaesu
    "FT891", "PREAMP_OFF", "PREAMP_AMP1",
    # Constants
    "SPEED_OF_LIGHT", "S9_HF_DBM", "S9_VHF_DBM",
    # Power / voltage
    "dbm_to_vpp", "vpp_to_dbm",
    "dbm_to_vrms", "vrms_to_dbm",
    "dbm_to_watts", "watts_to_dbm",
    "dbm_to_uv", "uv_to_dbm",
    # Power ratio / extended dB
    "db_to_linear", "linear_to_db",
    "db_to_voltage_ratio", "voltage_ratio_to_db",
    "dbm_to_dbw", "dbw_to_dbm",
    "dbm_to_dbuv", "dbuv_to_dbm",
    # Impedance / reflection
    "rl_to_vswr", "vswr_to_rl",
    "gamma_to_vswr", "vswr_to_gamma",
    "rl_to_gamma", "gamma_to_rl",
    "rl_to_vswr_v", "vswr_to_rl_v", "gamma_to_vswr_v",
    # Noise and dynamic range
    "thermal_noise_floor",
    "noise_figure_from_mds", "mds_from_noise_figure",
    "ip3_from_imd", "ip3_to_dynamic_range",
    "cascaded_noise_figure",
    "noise_temp_to_nf", "nf_to_noise_temp",
    # Propagation / antenna
    "wavelength", "quarter_wave", "half_wave",
    "freespace_path_loss",
    # Passive components
    "capacitive_reactance", "inductive_reactance",
    "lc_resonant_freq", "l_from_resonant", "c_from_resonant",
    "q_factor", "bw_from_q",
    "parallel_resistance", "voltage_divider",
    "skin_depth",
    # Attenuator design
    "pi_attenuator", "t_attenuator",
    # IM products
    "intermod_products",
    # S-meter
    "s_unit_to_dbm", "dbm_to_s_unit",
    # Formatting
    "format_freq", "format_freq_short",
    # Standard value series
    "nearest_rbw", "nearest_value",
    "SIGLENT_RBW_SERIES", "E12_SERIES", "E24_SERIES", "E48_SERIES", "E96_SERIES",
    # Two-channel measurement math
    "dominant_frequency",
    "gain_phase_from_fft",
    "complex_impedance_series",
]
