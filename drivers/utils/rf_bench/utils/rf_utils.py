"""
rf_utils.py — Shared RF / measurement math utilities

Pure Python + NumPy.  No instrument-specific code; no side effects.
Safe to import anywhere.

Conventions:
  - Impedance defaults to 50 Ω throughout
  - dBm: power relative to 1 mW
  - Vpp: peak-to-peak voltage across the load impedance
  - Vrms: RMS voltage across the load impedance (Vpp / (2√2) for a sine wave)
  - Return loss: positive dB = good match (e.g. 20 dB RL ≈ 1.22:1 VSWR)
  - VSWR: always ≥ 1.0; perfect match = 1.0:1
  - Frequencies: Hz throughout; use format_freq() for display

Sections:
  1.  Constants
  2.  Power / voltage conversions        (dBm ↔ W / Vrms / Vpp / µV)
  3.  Power ratio helpers                (dB ↔ linear, dBm ↔ dBW / dBµV)
  4.  Impedance / reflection math        (RL ↔ VSWR ↔ Γ)
  5.  Noise and dynamic range            (thermal noise, NF, MDS, IP3, SFDR, Friis)
  6.  Propagation and antenna            (wavelength, FSPL)
  7.  Passive components                 (Xc, Xl, LC, Q, parallel R, voltage divider, skin depth)
  8.  Attenuator design                  (π-pad, T-pad)
  9.  Intermodulation products           (two-tone IM product frequencies)
  10. S-meter calibration                (ITU S-unit ↔ dBm)
  11. Frequency formatting               (format_freq, format_freq_short)
  12. Standard value series              (E12 / E24 / E48 / E96, Siglent RBW)
  13. Two-channel measurement math       (FFT gain/phase, complex impedance)
  14. Phase noise                        (dBc/Hz from SSA noise measurement)
  15. Allan deviation                    (ADEV at multiple tau values)
  16. Matching network synthesis         (L, pi, T networks for real impedance matching)
  17. CC1101 / Sub-GHz helpers           (RSSI raw→dBm, band detection, ISM band name)
"""

import math
import numpy as np


# ---------------------------------------------------------------------------
# 1. Constants
# ---------------------------------------------------------------------------

SPEED_OF_LIGHT = 299_792_458.0  # m/s  (exact SI definition)

# ITU S-meter reference levels (from the S-unit standard)
S9_HF_DBM  = -73.0   # S9 at HF (< 30 MHz): -73 dBm
S9_VHF_DBM = -93.0   # S9 at VHF/UHF (≥ 30 MHz): -93 dBm


# ---------------------------------------------------------------------------
# 2. Power / voltage conversions
# ---------------------------------------------------------------------------

def dbm_to_watts(dbm: float) -> float:
    """dBm → watts."""
    return 1e-3 * 10 ** (dbm / 10.0)


def watts_to_dbm(w: float) -> float:
    """Watts → dBm."""
    return 10.0 * math.log10(w / 1e-3)


def dbm_to_vrms(dbm: float, impedance: float = 50.0) -> float:
    """dBm → Vrms (sine wave into impedance Ω)."""
    return math.sqrt(dbm_to_watts(dbm) * impedance)


def vrms_to_dbm(vrms: float, impedance: float = 50.0) -> float:
    """Vrms (sine wave into impedance Ω) → dBm."""
    return watts_to_dbm(vrms ** 2 / impedance)


def dbm_to_vpp(dbm: float, impedance: float = 50.0) -> float:
    """
    dBm → Vpp (peak-to-peak, sine wave into impedance Ω).

    Vpp = 2√2 · Vrms    (P = Vpp²/8R — correct formula)

    Examples::

        dbm_to_vpp(-20)  →  0.0632 V  (63.2 mVpp)
        dbm_to_vpp(0)    →  0.4000 V  (400 mVpp ≈ 0 dBm into 50 Ω)
    """
    return 2.0 * math.sqrt(2.0) * dbm_to_vrms(dbm, impedance)


def vpp_to_dbm(vpp: float, impedance: float = 50.0) -> float:
    """Vpp (peak-to-peak, sine wave into impedance Ω) → dBm."""
    return vrms_to_dbm(vpp / (2.0 * math.sqrt(2.0)), impedance)


def dbm_to_uv(dbm: float, impedance: float = 50.0) -> float:
    """dBm → microvolts RMS."""
    return dbm_to_vrms(dbm, impedance) * 1e6


def uv_to_dbm(uv: float, impedance: float = 50.0) -> float:
    """Microvolts RMS → dBm."""
    return vrms_to_dbm(uv * 1e-6, impedance)


# ---------------------------------------------------------------------------
# 3. Power ratio helpers and extended dB units
# ---------------------------------------------------------------------------

def db_to_linear(db: float) -> float:
    """Power ratio from dB.  10^(dB/10).

    Examples::

        db_to_linear(3)   → 1.995   (~2× power)
        db_to_linear(10)  → 10.0
        db_to_linear(-3)  → 0.501
    """
    return 10.0 ** (db / 10.0)


def linear_to_db(ratio: float) -> float:
    """dB from power ratio.  10·log10(ratio).

    Examples::

        linear_to_db(2)    → 3.010 dB
        linear_to_db(0.5)  → -3.010 dB
    """
    return 10.0 * math.log10(ratio)


def db_to_voltage_ratio(db: float) -> float:
    """Voltage (or current) ratio from dB.  10^(dB/20).

    Examples::

        db_to_voltage_ratio(6)   → 1.995   (~2× voltage)
        db_to_voltage_ratio(20)  → 10.0
    """
    return 10.0 ** (db / 20.0)


def voltage_ratio_to_db(ratio: float) -> float:
    """dB from voltage (or current) ratio.  20·log10(ratio).

    Examples::

        voltage_ratio_to_db(2)   → 6.021 dB
        voltage_ratio_to_db(10)  → 20.0 dB
    """
    return 20.0 * math.log10(ratio)


def dbm_to_dbw(dbm: float) -> float:
    """dBm → dBW.  dBW = dBm − 30."""
    return dbm - 30.0


def dbw_to_dbm(dbw: float) -> float:
    """dBW → dBm.  dBm = dBW + 30."""
    return dbw + 30.0


def dbm_to_dbuv(dbm: float, impedance: float = 50.0) -> float:
    """dBm → dBµV (microvolts RMS, relative to 1 µV).

    dBµV is the standard unit for receiver sensitivity specifications (EMC, broadcast).
    At 50 Ω: 0 dBm = 107.0 dBµV.

    Args:
        dbm:       Signal level in dBm.
        impedance: Reference impedance (Ω), default 50 Ω.
    """
    uv = dbm_to_uv(dbm, impedance)
    return 20.0 * math.log10(uv)


def dbuv_to_dbm(dbuv: float, impedance: float = 50.0) -> float:
    """dBµV → dBm.

    Args:
        dbuv:      Signal level in dBµV.
        impedance: Reference impedance (Ω), default 50 Ω.
    """
    uv = 10.0 ** (dbuv / 20.0)
    return uv_to_dbm(uv, impedance)


# ---------------------------------------------------------------------------
# 4. Impedance / reflection math
# ---------------------------------------------------------------------------

def rl_to_vswr(rl_db: float) -> float:
    """
    Return loss (positive dB) → VSWR.

    RL = 0 dB  → perfect reflection → VSWR = ∞ (clamped to 999)
    RL = 9.54  → gamma = 0.333     → VSWR = 2.0:1
    RL = 20    → gamma = 0.1       → VSWR = 1.22:1
    RL = ∞     → gamma = 0         → VSWR = 1.0:1
    """
    if rl_db <= 0.0:
        return 999.0
    gamma = 10.0 ** (-rl_db / 20.0)
    if gamma >= 1.0:
        return 999.0
    return (1.0 + gamma) / (1.0 - gamma)


def vswr_to_rl(vswr: float) -> float:
    """VSWR → return loss (positive dB)."""
    if vswr <= 1.0:
        return float("inf")
    gamma = (vswr - 1.0) / (vswr + 1.0)
    return -20.0 * math.log10(gamma)


def gamma_to_vswr(gamma: float) -> float:
    """Reflection coefficient magnitude (0–1) → VSWR."""
    gamma = abs(gamma)
    if gamma >= 1.0:
        return 999.0
    return (1.0 + gamma) / (1.0 - gamma)


def vswr_to_gamma(vswr: float) -> float:
    """VSWR → reflection coefficient magnitude (0–1)."""
    if vswr <= 1.0:
        return 0.0
    return (vswr - 1.0) / (vswr + 1.0)


def rl_to_gamma(rl_db: float) -> float:
    """Return loss (positive dB) → reflection coefficient magnitude."""
    return 10.0 ** (-rl_db / 20.0)


def gamma_to_rl(gamma: float) -> float:
    """Reflection coefficient magnitude → return loss (positive dB)."""
    gamma = abs(gamma)
    if gamma <= 0.0:
        return float("inf")
    return -20.0 * math.log10(gamma)


# Vectorized versions for numpy arrays
rl_to_vswr_v    = np.vectorize(rl_to_vswr)
vswr_to_rl_v    = np.vectorize(vswr_to_rl)
gamma_to_vswr_v = np.vectorize(gamma_to_vswr)


# ---------------------------------------------------------------------------
# 5. Noise and dynamic range
# ---------------------------------------------------------------------------

def thermal_noise_floor(bw_hz: float, temp_k: float = 290.0) -> float:
    """
    Thermal noise power in dBm for bandwidth bw_hz at temperature temp_k.

    kTB = 10·log10(k · T · BW / 1e-3)
        ≈ −174 + 10·log10(BW)  dBm  (at 290 K; uses exact Boltzmann constant)

    Args:
        bw_hz:  Noise bandwidth in Hz.
        temp_k: Temperature in Kelvin (default 290 K ≈ room temperature).

    Returns: kTB in dBm.
    """
    k = 1.380649e-23   # Boltzmann constant, J/K (exact, 2019 SI redefinition)
    return 10.0 * math.log10(k * temp_k * bw_hz / 1e-3)


def noise_figure_from_mds(mds_dbm: float, bw_hz: float,
                           temp_k: float = 290.0) -> float:
    """
    Compute noise figure (dB) from measured MDS and noise bandwidth.

    NF = MDS − kTB = MDS − (−174 + 10·log10(BW))  at 290 K

    Args:
        mds_dbm: Minimum Discernible Signal level in dBm.
        bw_hz:   Receiver noise bandwidth in Hz.
        temp_k:  Reference temperature (default 290 K).
    """
    return mds_dbm - thermal_noise_floor(bw_hz, temp_k)


def mds_from_noise_figure(nf_db: float, bw_hz: float,
                           temp_k: float = 290.0) -> float:
    """
    Compute theoretical MDS (dBm) from noise figure and bandwidth.

    MDS = kTB + NF
    """
    return thermal_noise_floor(bw_hz, temp_k) + nf_db


def ip3_from_imd(p_signal_dbm: float, p_imd_dbm: float,
                  p_in_dbm: float | None = None) -> float:
    """
    Compute third-order intercept point (IP3) from two-tone IMD measurement.

    For an amplifier (OIP3):
        OIP3 = P_out_signal + (P_out_signal − P_out_imd) / 2

    For a receiver (IIP3), pass p_in_dbm = input level at the antenna port:
        IIP3 = P_in + (P_out_signal − P_out_imd) / 2

    Args:
        p_signal_dbm: Signal tone level (output or audio, dBm or dBV).
        p_imd_dbm:    IMD product level at the same reference point.
        p_in_dbm:     Input signal level at receiver antenna port; if given,
                      returns IIP3 (input-referred); otherwise returns the
                      output-referred intercept at the signal level.

    Returns: IP3 in the same units as the input arguments.
    """
    delta = (p_signal_dbm - p_imd_dbm) / 2.0
    if p_in_dbm is not None:
        return p_in_dbm + delta          # IIP3
    return p_signal_dbm + delta          # OIP3


def ip3_to_dynamic_range(ip3_dbm: float, noise_floor_dbm: float) -> float:
    """
    Spurious-free dynamic range from IIP3 and noise floor.

    SFDR = (2/3) · (IIP3 − noise_floor)
    """
    return (2.0 / 3.0) * (ip3_dbm - noise_floor_dbm)


def cascaded_noise_figure(stages: list[tuple[float, float]]) -> float:
    """
    Compute total system noise figure (dB) for a cascade of stages (Friis' formula).

    F_total = F1 + (F2−1)/G1 + (F3−1)/(G1·G2) + …

    Args:
        stages: Ordered list of (gain_db, nf_db) tuples.
                For a passive element with loss L_dB, pass (−L_dB, L_dB).
                Example: a 2 dB cable → (−2, 2).

    Returns: Cascaded noise figure in dB.

    Examples::

        # Cable → preamp → IF amp: NF dominated by cable + preamp
        cascaded_noise_figure([(-2, 2), (20, 3), (10, 5)])  → ~5.06 dB

        # Preamp first (best practice for low NF):
        cascaded_noise_figure([(20, 3), (-2, 2), (10, 5)])  → ~3.05 dB

        # Single LNA: NF = its own noise figure
        cascaded_noise_figure([(15, 1.5)])  → 1.5 dB
    """
    if not stages:
        raise ValueError("At least one stage required")
    f_total = 1.0
    g_product = 1.0   # product of all gains BEFORE the current stage
    for gain_db, nf_db in stages:
        f = 10.0 ** (nf_db / 10.0)
        f_total += (f - 1.0) / g_product
        g_product *= 10.0 ** (gain_db / 10.0)
    return 10.0 * math.log10(f_total)


def noise_temp_to_nf(t_noise_k: float, t_ref_k: float = 290.0) -> float:
    """
    Convert noise temperature to noise figure (dB).

    NF = 10·log10(1 + T_noise / T_ref)

    Args:
        t_noise_k: Noise temperature in Kelvin.
        t_ref_k:   Reference temperature (default 290 K, IEEE standard).

    Examples::

        noise_temp_to_nf(290)  → 3.01 dB   (290 K = 3 dB NF)
        noise_temp_to_nf(58)   → 0.83 dB   (LNA noise temperature spec)
    """
    return 10.0 * math.log10(1.0 + t_noise_k / t_ref_k)


def nf_to_noise_temp(nf_db: float, t_ref_k: float = 290.0) -> float:
    """
    Convert noise figure (dB) to noise temperature (Kelvin).

    T_noise = T_ref · (10^(NF/10) − 1)

    Args:
        nf_db:   Noise figure in dB.
        t_ref_k: Reference temperature (default 290 K).

    Examples::

        nf_to_noise_temp(3.0)  → 288.5 K
        nf_to_noise_temp(0.5)  → 35.4 K   (excellent LNA)
    """
    return t_ref_k * (10.0 ** (nf_db / 10.0) - 1.0)


# ---------------------------------------------------------------------------
# 6. Propagation and antenna
# ---------------------------------------------------------------------------

def wavelength(freq_hz: float, velocity_factor: float = 1.0) -> float:
    """
    Compute wavelength (meters) from frequency.

    Args:
        freq_hz:         Frequency in Hz.
        velocity_factor: Velocity factor of the medium (1.0 = free space,
                         0.66 = typical coax, 0.95 = open-wire line).

    Returns: Wavelength in meters.

    Examples::

        wavelength(14_200_000)        → 21.11 m  (20-metre band)
        wavelength(14_200_000, 0.66)  → 13.93 m  (electrical length in coax)
        wavelength(2_400_000_000)     →  0.125 m (2.4 GHz Wi-Fi)
    """
    return (SPEED_OF_LIGHT * velocity_factor) / freq_hz


def quarter_wave(freq_hz: float, velocity_factor: float = 1.0) -> float:
    """
    Quarter-wavelength (meters).

    Useful for: quarter-wave verticals, stubs, matching transformers.

    Examples::

        quarter_wave(7_000_000)       → 10.71 m  (40 m quarter-wave)
        quarter_wave(144_000_000)     →  0.52 m  (2 m quarter-wave)
    """
    return wavelength(freq_hz, velocity_factor) / 4.0


def half_wave(freq_hz: float, velocity_factor: float = 1.0) -> float:
    """
    Half-wavelength (meters).

    Useful for: half-wave dipoles, folded dipoles, feed line stubs.

    Examples::

        half_wave(14_200_000)   → 10.56 m  (20 m half-wave dipole)
        half_wave(144_000_000)  →  1.04 m  (2 m half-wave dipole)
    """
    return wavelength(freq_hz, velocity_factor) / 2.0


def freespace_path_loss(dist_m: float, freq_hz: float) -> float:
    """
    Free-space path loss (FSPL) in dB.

    FSPL = 20·log10(4π·d·f / c)

    Args:
        dist_m:  Distance in metres.
        freq_hz: Frequency in Hz.

    Returns: FSPL in dB (positive value; larger = more loss).

    Examples::

        freespace_path_loss(1000, 1e9)   → 92.4 dB  (1 km at 1 GHz)
        freespace_path_loss(1e6, 14e6)   → 55.4 dB  (1 Mm at 14 MHz — HF)
    """
    return 20.0 * math.log10(
        4.0 * math.pi * dist_m * freq_hz / SPEED_OF_LIGHT
    )


# ---------------------------------------------------------------------------
# 7. Passive components and circuit analysis
# ---------------------------------------------------------------------------

def capacitive_reactance(freq_hz: float, c_f: float) -> float:
    """
    Capacitive reactance Xc = 1 / (2π·f·C) in ohms.

    Args:
        freq_hz: Frequency in Hz.
        c_f:     Capacitance in farads.

    Examples::

        capacitive_reactance(1e6, 100e-12)  → 1592 Ω  (100 pF at 1 MHz)
        capacitive_reactance(7e6, 1e-9)     →  22.7 Ω (1 nF at 7 MHz)
    """
    return 1.0 / (2.0 * math.pi * freq_hz * c_f)


def inductive_reactance(freq_hz: float, l_h: float) -> float:
    """
    Inductive reactance Xl = 2π·f·L in ohms.

    Args:
        freq_hz: Frequency in Hz.
        l_h:     Inductance in henries.

    Examples::

        inductive_reactance(1e6, 10e-6)   → 62.8 Ω  (10 µH at 1 MHz)
        inductive_reactance(14e6, 2.5e-6) → 220 Ω   (2.5 µH at 14 MHz)
    """
    return 2.0 * math.pi * freq_hz * l_h


def lc_resonant_freq(l_h: float, c_f: float) -> float:
    """
    Resonant frequency of an LC circuit: f = 1 / (2π√(LC)) in Hz.

    Args:
        l_h: Inductance in henries.
        c_f: Capacitance in farads.

    Examples::

        lc_resonant_freq(2.5e-6, 100e-12)  → 10.07 MHz
        lc_resonant_freq(1e-6, 470e-12)    →  7.33 MHz
    """
    return 1.0 / (2.0 * math.pi * math.sqrt(l_h * c_f))


def l_from_resonant(freq_hz: float, c_f: float) -> float:
    """
    Inductance (H) required to resonate with c_f at freq_hz.

    L = 1 / (4π²·f²·C)
    """
    return 1.0 / (4.0 * math.pi ** 2 * freq_hz ** 2 * c_f)


def c_from_resonant(freq_hz: float, l_h: float) -> float:
    """
    Capacitance (F) required to resonate with l_h at freq_hz.

    C = 1 / (4π²·f²·L)
    """
    return 1.0 / (4.0 * math.pi ** 2 * freq_hz ** 2 * l_h)


def q_factor(center_hz: float, bw_hz: float) -> float:
    """
    Q factor from center frequency and 3 dB bandwidth.

    Q = f0 / BW

    Args:
        center_hz: Resonant / centre frequency in Hz.
        bw_hz:     3 dB bandwidth in Hz.

    Examples::

        q_factor(7_100_000, 200_000)  → 35.5   (typical tank circuit)
        q_factor(455_000, 8_000)      → 56.9   (IF crystal filter)
    """
    return center_hz / bw_hz


def bw_from_q(center_hz: float, q: float) -> float:
    """
    3 dB bandwidth (Hz) from center frequency and Q factor.

    BW = f0 / Q
    """
    return center_hz / q


def parallel_resistance(*r_values: float) -> float:
    """
    Parallel combination of two or more resistances (Ω).

    R_parallel = 1 / Σ(1/Rᵢ)

    Args:
        *r_values: Two or more resistance values in ohms.

    Examples::

        parallel_resistance(100, 100)       → 50.0
        parallel_resistance(50, 50, 50)     → 16.67
        parallel_resistance(1000, 2000)     → 666.7
    """
    if not r_values:
        raise ValueError("At least one resistance required")
    return 1.0 / sum(1.0 / r for r in r_values)


def voltage_divider(vin: float, r1: float, r2: float) -> float:
    """
    Output voltage of a two-resistor voltage divider.

    Vout = Vin · R2 / (R1 + R2)

    R1 is the top resistor (connected to Vin), R2 is the bottom resistor
    (connected to GND).  Assumes no load on Vout.

    Args:
        vin: Input voltage (V).
        r1:  Top resistor (Ω).
        r2:  Bottom resistor (Ω).

    Examples::

        voltage_divider(5.0, 10000, 3300)  → 1.241 V
        voltage_divider(3.3, 100, 100)     → 1.65 V
    """
    return vin * r2 / (r1 + r2)


def skin_depth(freq_hz: float, conductivity: float = 5.8e7,
               mu_r: float = 1.0) -> float:
    """
    Skin depth (metres) in a conductor at the given frequency.

    δ = 1 / √(π · f · μ₀ · μᵣ · σ)

    Args:
        freq_hz:      Frequency in Hz.
        conductivity: Electrical conductivity in S/m.
                      Defaults: copper = 5.8×10⁷ S/m,
                                aluminium ≈ 3.5×10⁷ S/m,
                                silver ≈ 6.3×10⁷ S/m.
        mu_r:         Relative permeability (1.0 for non-ferrous metals;
                      ~100–1000 for iron/steel — increases losses dramatically).

    Returns: Skin depth in metres.

    Examples::

        skin_depth(1e6)     → 66.1e-6 m  (66 µm — copper at 1 MHz)
        skin_depth(14e6)    → 17.6e-6 m  (17.6 µm — copper at 14 MHz)
        skin_depth(2.4e9)   →  1.35e-6 m (1.35 µm — copper at 2.4 GHz)
    """
    mu0 = 4.0e-7 * math.pi  # H/m
    return 1.0 / math.sqrt(math.pi * freq_hz * mu0 * mu_r * conductivity)


# ---------------------------------------------------------------------------
# 8. Attenuator design
# ---------------------------------------------------------------------------

def pi_attenuator(atten_db: float, z0: float = 50.0) -> dict:
    """
    Resistor values for a symmetric π (shunt-series-shunt) attenuator.

    The π topology has two equal shunt resistors and one series resistor::

        o---+---[R_series]---+---o
            |                |
         [R_shunt]        [R_shunt]
            |                |
           GND              GND

    Both ports are matched to z0.

    Args:
        atten_db: Desired attenuation in dB (positive, e.g. 6 for 6 dB).
        z0:       Reference impedance (Ω), default 50 Ω.

    Returns:
        dict with keys:
            'r_shunt'  (Ω) — the two equal shunt resistors
            'r_series' (Ω) — the series resistor

    Examples::

        pi_attenuator(6)   → {'r_shunt': 150.5, 'r_series': 37.35}
        pi_attenuator(10)  → {'r_shunt': 96.25, 'r_series': 71.15}
        pi_attenuator(20)  → {'r_shunt': 61.11, 'r_series': 247.5}

    Note: Use nearest_value(r, E96_SERIES) to find the closest standard resistor.
    """
    if atten_db <= 0:
        raise ValueError(f"atten_db must be positive (got {atten_db!r})")
    a = 10.0 ** (atten_db / 20.0)   # voltage attenuation ratio
    r_shunt  = z0 * (a + 1.0) / (a - 1.0)
    r_series = z0 * (a ** 2 - 1.0) / (2.0 * a)
    return {"r_shunt": r_shunt, "r_series": r_series}


def t_attenuator(atten_db: float, z0: float = 50.0) -> dict:
    """
    Resistor values for a symmetric T (series-shunt-series) attenuator.

    The T topology has two equal series resistors and one shunt resistor::

        o---[R_series]---+---[R_series]---o
                         |
                      [R_shunt]
                         |
                        GND

    Both ports are matched to z0.

    Args:
        atten_db: Desired attenuation in dB (positive).
        z0:       Reference impedance (Ω), default 50 Ω.

    Returns:
        dict with keys:
            'r_series' (Ω) — the two equal series resistors
            'r_shunt'  (Ω) — the shunt resistor

    Examples::

        t_attenuator(6)   → {'r_series': 16.61, 'r_shunt': 66.93}
        t_attenuator(10)  → {'r_series': 25.97, 'r_shunt': 35.14}
        t_attenuator(20)  → {'r_series': 40.91, 'r_shunt': 10.10}

    Note: Use nearest_value(r, E96_SERIES) to find the closest standard resistor.
    """
    if atten_db <= 0:
        raise ValueError(f"atten_db must be positive (got {atten_db!r})")
    a = 10.0 ** (atten_db / 20.0)   # voltage attenuation ratio
    r_series = z0 * (a - 1.0) / (a + 1.0)
    r_shunt  = z0 * 2.0 * a / (a ** 2 - 1.0)
    return {"r_series": r_series, "r_shunt": r_shunt}


# ---------------------------------------------------------------------------
# 9. Intermodulation products
# ---------------------------------------------------------------------------

def intermod_products(f1_hz: float, f2_hz: float,
                      max_order: int = 9) -> list[dict]:
    """
    Compute near-carrier two-tone intermodulation product frequencies.

    Returns the close-in IM products of the form:

        (k+1)·f1 − k·f2   and   (k+1)·f2 − k·f1

    for odd orders 3, 5, 7, … up to max_order.  These are the products
    that fall closest to the original tones and are most dangerous for
    receiver dynamic range.  Only positive frequencies are returned.

    Even-order, harmonic, and far-off-frequency products are not included.

    Args:
        f1_hz:     First tone frequency in Hz.  Internally sorted so f1 < f2.
        f2_hz:     Second tone frequency in Hz.
        max_order: Highest odd order to compute (default 9).

    Returns:
        List of dicts sorted by frequency:
            'order'   (int):   IM order (3, 5, 7, …)
            'freq_hz' (float): product frequency in Hz
            'label'   (str):   e.g. '2f1-f2', '3f2-2f1'

    Examples::

        # HF SSB two-tone test: carrier 14.001 MHz, tones at +1 kHz, +1.5 kHz
        f1, f2 = 14_002_000, 14_002_500
        prods = intermod_products(f1, f2)
        # IM3:  2f1-f2 = 14_001_500 Hz  (audio 500 Hz),
        #       2f2-f1 = 14_003_000 Hz  (audio 2000 Hz)
        # IM5:  3f1-2f2 = 14_001_000 Hz (audio 0 Hz — at the carrier),
        #       3f2-2f1 = 14_003_500 Hz (audio 2500 Hz)
    """
    if f1_hz > f2_hz:
        f1_hz, f2_hz = f2_hz, f1_hz

    products = []
    for order in range(3, max_order + 1, 2):   # odd orders only
        k = (order - 1) // 2    # k=1 for IM3, k=2 for IM5, k=3 for IM7, ...

        # (k+1)·f1 − k·f2  → lower sideband product
        freq_lo = (k + 1) * f1_hz - k * f2_hz
        if freq_lo > 0:
            lo_lbl = f"{k+1}f1-{k}f2" if k > 1 else "2f1-f2"
            products.append({"order": order, "freq_hz": freq_lo, "label": lo_lbl})

        # (k+1)·f2 − k·f1  → upper sideband product
        freq_hi = (k + 1) * f2_hz - k * f1_hz
        if freq_hi > 0:
            hi_lbl = f"{k+1}f2-{k}f1" if k > 1 else "2f2-f1"
            products.append({"order": order, "freq_hz": freq_hi, "label": hi_lbl})

    return sorted(products, key=lambda p: p["freq_hz"])


# ---------------------------------------------------------------------------
# 10. S-meter calibration (ITU / ham radio)
# ---------------------------------------------------------------------------

def s_unit_to_dbm(s_unit: float, vhf: bool = False) -> float:
    """
    Convert an ITU S-meter reading to an absolute signal level (dBm).

    ITU standard S-meter scale:
        HF  (< 30 MHz): S9 = −73 dBm, each S-unit = 6 dB
        VHF (≥ 30 MHz): S9 = −93 dBm, each S-unit = 6 dB

    S-unit values above 9 (e.g. 9.5 for "S9+3 dB") are valid.
    Fractional S-units are accepted.

    Args:
        s_unit: S-meter reading (1.0–9.0 standard; > 9.0 for above S9).
        vhf:    If True, use the VHF/UHF reference (S9 = −93 dBm).

    Examples::

        s_unit_to_dbm(9)         → -73.0 dBm  (S9, HF)
        s_unit_to_dbm(7)         → -85.0 dBm  (S7, HF)
        s_unit_to_dbm(1)         → -121.0 dBm (S1, HF)
        s_unit_to_dbm(9, vhf=True)  → -93.0 dBm (S9, VHF)
        s_unit_to_dbm(9.167)     → -72.0 dBm  (≈ S9 + 1 dB)
    """
    s9_dbm = S9_VHF_DBM if vhf else S9_HF_DBM
    return s9_dbm + (s_unit - 9.0) * 6.0


def dbm_to_s_unit(dbm: float, vhf: bool = False) -> float:
    """
    Convert an absolute signal level (dBm) to ITU S-meter units.

    Returns a float; values > 9 indicate above S9 (e.g. 9.5 = S9+3 dB).
    Values below S1 (−121 dBm HF) are clamped to S1 since S0 is not defined.

    Args:
        dbm: Signal level in dBm.
        vhf: If True, use the VHF/UHF reference (S9 = −93 dBm).

    Examples::

        dbm_to_s_unit(-73)        → 9.0    (S9, HF)
        dbm_to_s_unit(-85)        → 7.0    (S7, HF)
        dbm_to_s_unit(-121)       → 1.0    (S1, HF)
        dbm_to_s_unit(-53)        → 12.33  (S9+20 dB)
        dbm_to_s_unit(-93, vhf=True)  → 9.0 (S9, VHF)
    """
    s9_dbm = S9_VHF_DBM if vhf else S9_HF_DBM
    s_unit = 9.0 + (dbm - s9_dbm) / 6.0
    return max(1.0, s_unit)


# ---------------------------------------------------------------------------
# 11. Frequency formatting
# ---------------------------------------------------------------------------

def format_freq(hz: float) -> str:
    """
    Format a frequency value for human-readable display.

    Ranges and decimal places:
        ≥ 1 GHz → GHz, 4 decimal places
        ≥ 1 MHz → MHz, 4 decimal places
        ≥ 1 kHz → kHz, 3 decimal places
         < 1 kHz → Hz, no decimal places

    Examples::

        format_freq(3_200_000_000)  →  '3.2000 GHz'
        format_freq(14_200_000)     →  '14.2000 MHz'
        format_freq(475_000)        →  '475.000 kHz'
        format_freq(1_000)          →  '1.000 kHz'
        format_freq(600)            →  '600 Hz'
    """
    if hz >= 1_000_000_000.0:
        return f"{hz / 1e9:.4f} GHz"
    if hz >= 1_000_000.0:
        return f"{hz / 1e6:.4f} MHz"
    if hz >= 1_000.0:
        return f"{hz / 1e3:.3f} kHz"
    return f"{hz:.0f} Hz"


def format_freq_short(hz: float) -> str:
    """
    Compact frequency string with trailing zeros trimmed.

    Examples::

        format_freq_short(3_200_000_000)  →  '3.2 GHz'
        format_freq_short(14_200_000)     →  '14.2 MHz'
        format_freq_short(7_000_000)      →  '7 MHz'
        format_freq_short(475_000)        →  '475 kHz'
        format_freq_short(600)            →  '600 Hz'
    """
    if hz >= 1_000_000_000.0:
        s = f"{hz / 1e9:.4f}".rstrip("0").rstrip(".")
        return f"{s} GHz"
    if hz >= 1_000_000.0:
        s = f"{hz / 1e6:.4f}".rstrip("0").rstrip(".")
        return f"{s} MHz"
    if hz >= 1_000.0:
        s = f"{hz / 1e3:.3f}".rstrip("0").rstrip(".")
        return f"{s} kHz"
    return f"{hz:.0f} Hz"


# ---------------------------------------------------------------------------
# 12. Standard value series lookup
# ---------------------------------------------------------------------------

# Siglent SSA RBW/VBW values (Hz), 1-3-10 sequence
SIGLENT_RBW_SERIES = [
    10, 30, 100, 300, 1_000, 3_000, 10_000, 30_000,
    100_000, 300_000, 1_000_000, 3_000_000,
]

# Standard resistor / capacitor value series (one decade, multiply by 10^n)
E12_SERIES = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]

E24_SERIES = [
    1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
    3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1,
]

E48_SERIES = [
    1.00, 1.05, 1.10, 1.15, 1.21, 1.27, 1.33, 1.40,
    1.47, 1.54, 1.62, 1.69, 1.78, 1.87, 1.96, 2.05,
    2.15, 2.26, 2.37, 2.49, 2.61, 2.74, 2.87, 3.01,
    3.16, 3.32, 3.48, 3.65, 3.83, 4.02, 4.22, 4.42,
    4.64, 4.87, 5.11, 5.36, 5.62, 5.90, 6.19, 6.49,
    6.81, 7.15, 7.50, 7.87, 8.25, 8.66, 9.09, 9.53,
]

E96_SERIES = [
    1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18,
    1.21, 1.24, 1.27, 1.30, 1.33, 1.37, 1.40, 1.43,
    1.47, 1.50, 1.54, 1.58, 1.62, 1.65, 1.69, 1.74,
    1.78, 1.82, 1.87, 1.91, 1.96, 2.00, 2.05, 2.10,
    2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55,
    2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09,
    3.16, 3.24, 3.32, 3.40, 3.48, 3.57, 3.65, 3.74,
    3.83, 3.92, 4.02, 4.12, 4.22, 4.32, 4.42, 4.53,
    4.64, 4.75, 4.87, 4.99, 5.11, 5.23, 5.36, 5.49,
    5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65,
    6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06,
    8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53, 9.76,
]


def nearest_value(target: float, series: list[float]) -> float:
    """
    Return the value in `series` closest to `target`.

    Works for any sorted or unsorted list.  Useful for snapping to the nearest
    standard resistor, capacitor, or instrument setting.

    Examples::

        nearest_value(2500, SIGLENT_RBW_SERIES)  →  3000
        nearest_value(4.5,  E12_SERIES)          →  4.7
        nearest_value(97.0, E96_SERIES)          →  9.76  (one decade: ×10)
    """
    return min(series, key=lambda x: abs(x - target))


def nearest_rbw(target_hz: float) -> int:
    """
    Return the Siglent SSA RBW/VBW setting (Hz) closest to target_hz.

    Convenience wrapper around nearest_value(target_hz, SIGLENT_RBW_SERIES).
    """
    return int(nearest_value(target_hz, SIGLENT_RBW_SERIES))


# ---------------------------------------------------------------------------
# 13. Two-channel measurement math  (scope CH1 = reference, CH2 = DUT)
# ---------------------------------------------------------------------------
#
# These functions work on numpy arrays returned by SDS2000X.capture_audio().
# All use FFT-based analysis so they are accurate for periodic signals.
# Minimum recommended waveform length: ~10 complete cycles at the target freq.
# ---------------------------------------------------------------------------

def dominant_frequency(wave: np.ndarray, sample_rate_hz: float) -> float:
    """Return the dominant non-DC frequency (Hz) from an FFT of *wave*.

    Skips the DC bin (index 0).  Useful when the stimulus frequency is
    unknown (e.g. auto-detection in Bode plotter or crystal extractor).

    Example::

        f = dominant_frequency(scope_ch1, sample_rate_hz)
    """
    freqs = np.fft.rfftfreq(len(wave), d=1.0 / sample_rate_hz)
    magnitudes = np.abs(np.fft.rfft(wave))
    magnitudes[0] = 0.0  # suppress DC
    return float(freqs[np.argmax(magnitudes)])


def gain_phase_from_fft(
    ref_wave: np.ndarray,
    dut_wave: np.ndarray,
    sample_rate_hz: float,
    freq_hz: "float | None" = None,
) -> "tuple[float, float]":
    """Compute gain (dB) and phase shift (°) of *dut_wave* relative to *ref_wave*.

    Uses FFT-based phasor extraction at *freq_hz*.  If *freq_hz* is None the
    dominant frequency of *ref_wave* is used.

    Phase convention: positive = DUT output leads the reference.
    Phase range: (−180, +180].

    Typical two-channel Bode / transfer-function setup::

        SDG/AWG ──┬── CH1 (ref)
                  └── DUT ── CH2 (dut)

        gain_db, phase_deg = gain_phase_from_fft(ch1, ch2, sr, freq_hz=f)

    Returns:
        (gain_db, phase_deg)  — both floats; gain_db = −inf if ref is zero.
    """
    n = len(ref_wave)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)

    fft_ref = np.fft.rfft(ref_wave)
    fft_dut = np.fft.rfft(dut_wave)

    if freq_hz is None:
        mags = np.abs(fft_ref).copy()
        mags[0] = 0.0
        idx = int(np.argmax(mags))
    else:
        idx = int(np.argmin(np.abs(freqs - freq_hz)))

    amp_ref = float(np.abs(fft_ref[idx]))
    amp_dut = float(np.abs(fft_dut[idx]))

    gain_db = 20.0 * math.log10(amp_dut / amp_ref) if amp_ref > 1e-15 else float("-inf")

    phase_rad = float(np.angle(fft_dut[idx]) - np.angle(fft_ref[idx]))
    phase_deg = math.degrees(phase_rad)
    # Wrap to (−180, +180]
    phase_deg = (phase_deg + 180.0) % 360.0 - 180.0

    return gain_db, phase_deg


def complex_impedance_series(
    ch1_wave: np.ndarray,
    ch2_wave: np.ndarray,
    sample_rate_hz: float,
    z_ref_ohm: float = 50.0,
    freq_hz: "float | None" = None,
) -> complex:
    """Compute the complex impedance of a series DUT from a two-channel capture.

    Circuit (series injection, standard impedance analyser topology)::

        Source ──── z_ref ──── DUT ──── GND
              CH1 ↑        CH2 ↑

        CH1 = voltage on the source side of z_ref
        CH2 = voltage on the DUT side of z_ref (= across the DUT to GND)

    Current through DUT::

        I = (V_CH1 − V_CH2) / z_ref_ohm

    DUT impedance::

        Z = V_CH2 / I = z_ref_ohm × V_CH2 / (V_CH1 − V_CH2)

    All quantities are complex phasors at *freq_hz* (or dominant frequency).

    Returns:
        Complex impedance in ohms.  Returns ``inf+0j`` if CH1 ≈ CH2
        (open circuit or z_ref too small).

    Example::

        Z = complex_impedance_series(ch1, ch2, sr, z_ref_ohm=50.0, freq_hz=f)
        R, X = Z.real, Z.imag
        magnitude_ohm = abs(Z)
        phase_deg = math.degrees(cmath.phase(Z))
    """
    n = len(ch1_wave)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)

    fft1 = np.fft.rfft(ch1_wave)
    fft2 = np.fft.rfft(ch2_wave)

    if freq_hz is None:
        mags = np.abs(fft1).copy()
        mags[0] = 0.0
        idx = int(np.argmax(mags))
    else:
        idx = int(np.argmin(np.abs(freqs - freq_hz)))

    V1 = complex(fft1[idx])
    V2 = complex(fft2[idx])

    denom = V1 - V2
    if abs(denom) < 1e-15:
        return complex(float("inf"), 0.0)

    return complex(z_ref_ohm * V2 / denom)


# ---------------------------------------------------------------------------
# 14. Phase noise
# ---------------------------------------------------------------------------

def phase_noise_dbchz(
    p_noise_dbm: float,
    p_carrier_dbm: float,
    rbw_hz: float,
) -> float:
    """Convert a noise floor measurement to phase noise L(f) in dBc/Hz.

    Formula::

        L(f) = P_noise_dBm − P_carrier_dBm − 10·log10(RBW_hz)

    This gives the single-sideband (SSB) phase noise, which is the standard
    convention in oscillator data sheets and phase noise plots.

    Args:
        p_noise_dbm:   SSA average noise power at the offset frequency (dBm).
        p_carrier_dbm: SSA carrier power at the centre frequency (dBm).
        rbw_hz:        SSA resolution bandwidth used for the noise floor measurement (Hz).

    Returns:
        Phase noise in dBc/Hz (typically −80 to −145 dBc/Hz for good oscillators).

    Example::

        # Carrier at −3 dBm; noise floor −110 dBm in 100 Hz RBW at 1 kHz offset
        phase_noise_dbchz(-110, -3, 100)  →  −127.0 dBc/Hz
    """
    return p_noise_dbm - p_carrier_dbm - 10.0 * math.log10(rbw_hz)


# ---------------------------------------------------------------------------
# 15. Allan deviation
# ---------------------------------------------------------------------------

def adev_multi_tau(
    freq_samples_hz: "np.ndarray | list[float]",
    f_nominal_hz: float,
    sample_interval_s: float,
) -> "tuple[np.ndarray, np.ndarray]":
    """Compute the two-sample (non-overlapping) Allan deviation at all valid tau values.

    ADEV(τ) is the standard metric for oscillator frequency stability.
    Different slopes on a log–log ADEV plot identify noise types:

      slope −1:  white phase noise (dominates at short τ)
      slope −½:  flicker phase noise
      slope  0:  white frequency noise (Allan floor)
      slope +½:  flicker frequency / random walk frequency
      slope +1:  random walk (crystal aging, drift)

    Args:
        freq_samples_hz:   Array of N measured frequencies (Hz).
        f_nominal_hz:      Nominal oscillator frequency (Hz); used to compute
                           fractional frequency deviations y_k = (f_k − f0)/f0.
        sample_interval_s: Measurement interval between consecutive samples (s).

    Returns:
        ``(taus, adevs)`` — two equal-length numpy arrays.
        *taus*  — averaging time τ in seconds (τ = m·sample_interval_s, m = 1, 2, …).
        *adevs* — Allan deviation σ_y(τ) (dimensionless fractional frequency).
        Both arrays are empty when fewer than 4 samples are provided.

    Algorithm (non-overlapping):
        y_k = (f_k − f_nominal) / f_nominal
        For each m (samples per group):
            M = floor(N / m)
            y_bar_j = mean(y[j·m : (j+1)·m])     for j = 0 … M−1
            ADEV²(τ) = (1/(2·(M−1))) · Σ_{j=0}^{M−2} (y_bar_{j+1} − y_bar_j)²

    At least M = 4 groups are required (giving 3 differences) per tau value.

    Example::

        taus, adevs = adev_multi_tau(freq_readings, 10e6, 1.0)
        for tau, sigma in zip(taus, adevs):
            print(f"τ = {tau:.0f} s  σ_y = {sigma:.2e}")
    """
    y = (np.asarray(freq_samples_hz, dtype=float) - f_nominal_hz) / f_nominal_hz
    n = len(y)
    if n < 4:
        return np.array([]), np.array([])

    taus_out: list[float] = []
    adevs_out: list[float] = []
    m = 1
    while True:
        big_m = n // m
        if big_m < 4:
            break
        y_bar = np.array(
            [float(np.mean(y[j * m : (j + 1) * m])) for j in range(big_m)]
        )
        diff_sq = (y_bar[1:] - y_bar[:-1]) ** 2
        adev = math.sqrt(0.5 * float(np.mean(diff_sq)))
        taus_out.append(m * sample_interval_s)
        adevs_out.append(adev)
        m += 1

    return np.array(taus_out), np.array(adevs_out)


# ---------------------------------------------------------------------------
# 16. Matching network synthesis  (real impedance, single frequency)
# ---------------------------------------------------------------------------

def l_network(r_source: float, r_load: float, freq_hz: float) -> dict:
    """Compute both L-network topologies for real-impedance matching.

    An L-network uses two reactive elements (one shunt, one series) to
    transform *r_source* to *r_load*.  The loaded Q is determined by the
    impedance ratio and cannot be chosen freely.

    The shunt element always connects at the HIGH-impedance port; the series
    element is in-line between the two ports.

    Args:
        r_source: Source (input) resistance in ohms.
        r_load:   Load (output) resistance in ohms.
        freq_hz:  Operating frequency in Hz.

    Returns:
        Dict::

            {
              'q':          float,   # loaded Q = sqrt(R_high/R_low − 1)
              'r_high':     float,   # max(r_source, r_load)
              'r_low':      float,   # min(r_source, r_load)
              'high_z_port': str,    # 'source' or 'load' — which port has the shunt
              'low_pass':  {'shunt_c_f': C (F), 'series_l_h': L (H)},
              'high_pass': {'shunt_l_h': L (H), 'series_c_f': C (F)},
            }

    Raises:
        ValueError: if r_source == r_load or any argument is non-positive.

    Example::

        net = l_network(200, 50, 14.2e6)
        lp = net['low_pass']
        print(f"Q = {net['q']:.2f}")
        print(f"Shunt C = {lp['shunt_c_f']*1e12:.1f} pF  at {net['high_z_port']} port")
        print(f"Series L = {lp['series_l_h']*1e9:.1f} nH")
    """
    if r_source <= 0 or r_load <= 0 or freq_hz <= 0:
        raise ValueError("r_source, r_load, and freq_hz must all be positive")
    if r_source == r_load:
        raise ValueError("r_source == r_load: no matching needed")

    r_high = max(r_source, r_load)
    r_low  = min(r_source, r_load)
    q      = math.sqrt(r_high / r_low - 1.0)
    omega  = 2.0 * math.pi * freq_hz
    x_p    = r_high / q     # shunt element reactance at high-Z port
    x_s    = r_low  * q     # series element reactance

    return {
        "q": q,
        "r_high": r_high,
        "r_low": r_low,
        "high_z_port": "source" if r_source >= r_load else "load",
        "low_pass":  {"shunt_c_f":  1.0 / (omega * x_p), "series_l_h": x_s / omega},
        "high_pass": {"shunt_l_h":  x_p  / omega,         "series_c_f": 1.0 / (omega * x_s)},
    }


def pi_network(
    r_source: float, r_load: float, freq_hz: float, q: float
) -> dict:
    """Compute pi-network (shunt–series–shunt) matching component values.

    The pi network is decomposed into two back-to-back L-sections sharing a
    virtual intermediate resistance R_v = R_high / (Q² + 1), which is lower
    than both source and load.  *Q* is the loaded Q of the HIGH-impedance
    section and must exceed Q_min = sqrt(R_high/R_low − 1).

    Args:
        r_source: Source resistance (Ω).
        r_load:   Load resistance (Ω).
        freq_hz:  Operating frequency (Hz).
        q:        Desired loaded Q of the high-impedance section
                  (must be > sqrt(max/min − 1)).

    Returns:
        Dict::

            {
              'q_min':    float,   # minimum Q for this impedance ratio
              'q_high':   float,   # Q of the high-Z section (= q)
              'q_low':    float,   # Q of the low-Z section (derived)
              'r_virtual': float,  # virtual intermediate resistance (Ω)
              'low_pass':  {
                  'shunt_source_c_f': C (F),
                  'series_l_h':       L (H),
                  'shunt_load_c_f':   C (F),
              },
              'high_pass': {
                  'shunt_source_l_h': L (H),
                  'series_c_f':       C (F),
                  'shunt_load_l_h':   L (H),
              },
            }

    Raises:
        ValueError: if q ≤ q_min or any argument is non-positive.

    Example::

        net = pi_network(50, 50, 7.2e6, q=10)
        lp = net['low_pass']
        print(f"C1={lp['shunt_source_c_f']*1e12:.1f}pF  "
              f"L={lp['series_l_h']*1e9:.1f}nH  "
              f"C2={lp['shunt_load_c_f']*1e12:.1f}pF")
    """
    if r_source <= 0 or r_load <= 0 or freq_hz <= 0 or q <= 0:
        raise ValueError("All arguments must be positive")

    r_high = max(r_source, r_load)
    r_low  = min(r_source, r_load)
    q_min  = math.sqrt(r_high / r_low - 1.0) if r_high != r_low else 0.0
    if q <= q_min:
        raise ValueError(
            f"Q must be > {q_min:.4f} for r_high={r_high:.1f} Ω, r_low={r_low:.1f} Ω"
        )

    omega = 2.0 * math.pi * freq_hz
    r_v   = r_high / (q ** 2 + 1.0)
    q_l   = math.sqrt(r_low / r_v - 1.0)

    if r_source >= r_load:
        c_src = q   / (omega * r_source);  l_src = r_source / (omega * q)
        c_ld  = q_l / (omega * r_load);    l_ld  = r_load   / (omega * q_l)
    else:
        c_src = q_l / (omega * r_source);  l_src = r_source / (omega * q_l)
        c_ld  = q   / (omega * r_load);    l_ld  = r_load   / (omega * q)

    l_ser = (q + q_l) * r_v / omega
    c_ser = 1.0 / (omega * (q + q_l) * r_v)

    return {
        "q_min": q_min,
        "q_high": q,
        "q_low": q_l,
        "r_virtual": r_v,
        "low_pass":  {"shunt_source_c_f": c_src, "series_l_h": l_ser, "shunt_load_c_f": c_ld},
        "high_pass": {"shunt_source_l_h": l_src, "series_c_f": c_ser, "shunt_load_l_h": l_ld},
    }


def t_network(
    r_source: float, r_load: float, freq_hz: float, q: float
) -> dict:
    """Compute T-network (series–shunt–series) matching component values.

    The T network is decomposed into two L-sections sharing a virtual
    intermediate resistance R_v = R_source × (Q² + 1), which is HIGHER than
    both source and load.  *Q* is the loaded Q of the source section.

    Args:
        r_source: Source resistance (Ω).
        r_load:   Load resistance (Ω).
        freq_hz:  Operating frequency (Hz).
        q:        Desired loaded Q of the source section.
                  Must be > sqrt(r_load/r_source − 1) when r_load > r_source.

    Returns:
        Dict::

            {
              'q_min':    float,   # min Q to keep R_virtual > r_load
              'q_source': float,   # Q of the source section (= q)
              'q_load':   float,   # Q of the load section (derived)
              'r_virtual': float,  # virtual intermediate resistance (Ω)
              'low_pass':  {
                  'series_source_l_h': L (H),
                  'shunt_c_f':         C (F),
                  'series_load_l_h':   L (H),
              },
              'high_pass': {
                  'series_source_c_f': C (F),
                  'shunt_l_h':         L (H),
                  'series_load_c_f':   C (F),
              },
            }

    Raises:
        ValueError: if q ≤ q_min (when r_load > r_source) or any argument ≤ 0.

    Example::

        net = t_network(50, 200, 14.2e6, q=5)
        lp = net['low_pass']
        print(f"L1={lp['series_source_l_h']*1e9:.1f}nH  "
              f"C={lp['shunt_c_f']*1e12:.1f}pF  "
              f"L2={lp['series_load_l_h']*1e9:.1f}nH")
    """
    if r_source <= 0 or r_load <= 0 or freq_hz <= 0 or q <= 0:
        raise ValueError("All arguments must be positive")

    q_min = math.sqrt(max(0.0, r_load / r_source - 1.0))
    if r_load > r_source and q <= q_min:
        raise ValueError(
            f"Q must be > {q_min:.4f} for r_source={r_source:.1f} Ω, r_load={r_load:.1f} Ω"
        )

    omega = 2.0 * math.pi * freq_hz
    r_v   = r_source * (q ** 2 + 1.0)
    q_l   = math.sqrt(r_v / r_load - 1.0)

    l_src   = q   * r_source / omega
    l_ld    = q_l * r_load   / omega
    c_shunt = (q + q_l) / (omega * r_v)

    c_src   = 1.0 / (omega * q   * r_source)
    c_ld    = 1.0 / (omega * q_l * r_load)
    l_shunt = r_v / (omega * (q + q_l))

    return {
        "q_min": q_min,
        "q_source": q,
        "q_load": q_l,
        "r_virtual": r_v,
        "low_pass":  {"series_source_l_h": l_src, "shunt_c_f": c_shunt, "series_load_l_h": l_ld},
        "high_pass": {"series_source_c_f": c_src, "shunt_l_h": l_shunt, "series_load_c_f": c_ld},
    }


# ---------------------------------------------------------------------------
# 17. CC1101 / Sub-GHz helpers
# ---------------------------------------------------------------------------

def cc1101_rssi_to_dbm(rssi_raw: int) -> float:
    """
    Convert a raw CC1101 RSSI register byte to dBm.

    The CC1101 RSSI register is an 8-bit signed value with an offset of 74 dB
    and 0.5 dB resolution.  Formula from the CC1101 datasheet (section 17.3):

        RSSI_dBm = (RSSI_raw / 2) − 74          if RSSI_raw < 128
        RSSI_dBm = ((RSSI_raw − 256) / 2) − 74  if RSSI_raw ≥ 128

    Args:
        rssi_raw: 8-bit unsigned RSSI register value (0–255).

    Returns:
        RSSI in dBm (float).

    Examples::

        cc1101_rssi_to_dbm(74)   → −37.0 dBm   (strong signal)
        cc1101_rssi_to_dbm(200)  → −102.0 dBm  (weak signal)
    """
    if rssi_raw >= 128:
        return (rssi_raw - 256) / 2.0 - 74.0
    return rssi_raw / 2.0 - 74.0


def cc1101_band(freq_hz: float) -> int:
    """
    Return the CC1101 frequency band number for a given frequency.

    The CC1101 supports three frequency bands:
      Band 1: 300–348 MHz
      Band 2: 387–464 MHz
      Band 3: 779–928 MHz

    Args:
        freq_hz: Frequency in Hz.

    Returns:
        1, 2, or 3 for a valid frequency.

    Raises:
        ValueError: If freq_hz falls outside all supported bands.

    Examples::

        cc1101_band(315e6)    → 1
        cc1101_band(433.92e6) → 2
        cc1101_band(868e6)    → 3
        cc1101_band(915e6)    → 3
    """
    if 300e6 <= freq_hz <= 348e6:
        return 1
    if 387e6 <= freq_hz <= 464e6:
        return 2
    if 779e6 <= freq_hz <= 928e6:
        return 3
    raise ValueError(
        f"Frequency {freq_hz/1e6:.3f} MHz is outside all CC1101 bands "
        "(300–348 MHz, 387–464 MHz, 779–928 MHz)"
    )


# ISM band centre frequencies (Hz) → conventional name
_ISM_BANDS = [
    (315e6,    10e6, "315"),
    (433.92e6, 5e6,  "433"),
    (868e6,    10e6, "868"),
    (915e6,    15e6, "915"),
]


def ism_band_name(freq_hz: float) -> str:
    """
    Return the common ISM band name nearest to freq_hz.

    Recognises the four common Sub-GHz ISM bands used in consumer devices
    and the Flipper Zero:
      315 MHz  (North American garage doors, OOK remotes)
      433 MHz  (European/worldwide OOK/FSK devices)
      868 MHz  (European SRD band)
      915 MHz  (North American ISM band)

    Args:
        freq_hz: Frequency in Hz.

    Returns:
        Band name string: '315', '433', '868', or '915'.
        Returns the nearest band name even if freq_hz is outside the window.

    Examples::

        ism_band_name(433_920_000) → '433'
        ism_band_name(868_350_000) → '868'
        ism_band_name(914_000_000) → '915'
    """
    best_name = _ISM_BANDS[0][2]
    best_dist = abs(freq_hz - _ISM_BANDS[0][0])
    for centre, _half, name in _ISM_BANDS[1:]:
        dist = abs(freq_hz - centre)
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name
