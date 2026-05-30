"""
rf_bench.utils — RF math and general bench utilities

Currently contains:
    rf_utils  — pure RF math (power conversions, impedance, noise, IP3, formatting,
                attenuator design, propagation, passive components, S-meter)

Future candidates:
    scpi      — base TCP/SCPI connection class shared by Siglent drivers
    serial    — base serial/rigctld connection helpers
    data      — measurement logging and export utilities
"""

from .rf_utils import (
    # Constants
    SPEED_OF_LIGHT,
    S9_HF_DBM, S9_VHF_DBM,

    # 2. Power / voltage conversions
    dbm_to_vpp, vpp_to_dbm,
    dbm_to_vrms, vrms_to_dbm,
    dbm_to_watts, watts_to_dbm,
    dbm_to_uv, uv_to_dbm,

    # 3. Power ratio helpers and extended dB units
    db_to_linear, linear_to_db,
    db_to_voltage_ratio, voltage_ratio_to_db,
    dbm_to_dbw, dbw_to_dbm,
    dbm_to_dbuv, dbuv_to_dbm,

    # 4. Impedance / reflection math
    rl_to_vswr, vswr_to_rl,
    gamma_to_vswr, vswr_to_gamma,
    rl_to_gamma, gamma_to_rl,
    rl_to_vswr_v, vswr_to_rl_v, gamma_to_vswr_v,

    # 5. Noise and dynamic range
    thermal_noise_floor,
    noise_figure_from_mds, mds_from_noise_figure,
    ip3_from_imd, ip3_to_dynamic_range,
    cascaded_noise_figure,
    noise_temp_to_nf, nf_to_noise_temp,

    # 6. Propagation and antenna
    wavelength, quarter_wave, half_wave,
    freespace_path_loss,

    # 7. Passive components
    capacitive_reactance, inductive_reactance,
    lc_resonant_freq, l_from_resonant, c_from_resonant,
    q_factor, bw_from_q,
    parallel_resistance,
    voltage_divider,
    skin_depth,

    # 8. Attenuator design
    pi_attenuator, t_attenuator,

    # 9. Intermodulation products
    intermod_products,

    # 10. S-meter calibration
    s_unit_to_dbm, dbm_to_s_unit,

    # 11. Frequency formatting
    format_freq, format_freq_short,

    # 12. Standard value series
    nearest_rbw, nearest_value,
    SIGLENT_RBW_SERIES,
    E12_SERIES, E24_SERIES, E48_SERIES, E96_SERIES,

    # 13. Two-channel measurement math
    dominant_frequency,
    gain_phase_from_fft,
    complex_impedance_series,

    # 14. Phase noise
    phase_noise_dbchz,

    # 15. Allan deviation
    adev_multi_tau,

    # 16. Matching network synthesis
    l_network,
    pi_network,
    t_network,

    # 17. CC1101 / Sub-GHz helpers
    cc1101_rssi_to_dbm,
    cc1101_band,
    ism_band_name,
)

__all__ = [
    # Constants
    "SPEED_OF_LIGHT",
    "S9_HF_DBM", "S9_VHF_DBM",
    # Power / voltage
    "dbm_to_vpp", "vpp_to_dbm",
    "dbm_to_vrms", "vrms_to_dbm",
    "dbm_to_watts", "watts_to_dbm",
    "dbm_to_uv", "uv_to_dbm",
    # Power ratio helpers / extended dB
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
    "parallel_resistance",
    "voltage_divider",
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
    "SIGLENT_RBW_SERIES",
    "E12_SERIES", "E24_SERIES", "E48_SERIES", "E96_SERIES",
    # Two-channel measurement math
    "dominant_frequency",
    "gain_phase_from_fft",
    "complex_impedance_series",
    # Phase noise
    "phase_noise_dbchz",
    # Allan deviation
    "adev_multi_tau",
    # Matching network synthesis
    "l_network",
    "pi_network",
    "t_network",
    # CC1101 / Sub-GHz helpers
    "cc1101_rssi_to_dbm",
    "cc1101_band",
    "ism_band_name",
]
