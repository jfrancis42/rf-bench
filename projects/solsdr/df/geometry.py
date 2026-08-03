"""
geometry.py — two-element interferometer geometry: phase difference <-> bearing.

Pure math, no hardware, no solsdr. Fully unit-tested (test_df.py). This is the
layer that turns a CALIBRATED inter-channel phase difference Δφ into an arrival
angle, and is honest about the ambiguities a single baseline cannot resolve.

Model
-----
Two identical antennas separated by baseline vector of length `d` metres. A plane
wave of wavelength λ arriving from angle θ (measured from the baseline axis)
reaches the two antennas with a path-length difference d·cos(θ), hence an
electrical phase difference:

    Δφ = (2π d / λ) · cos(θ)                     [radians]

Solve for θ:

    cos(θ) = Δφ · λ / (2π d)  =  Δφ / (2π d/λ)

Definitions used here:
  * d, λ in metres (λ = c / f).
  * "electrical spacing"  D = d/λ  (baseline in wavelengths). D drives everything.
  * θ ("cone angle") is measured FROM THE BASELINE AXIS, 0..180°.
    θ=90° is broadside (wave arrives perpendicular to the baseline, Δφ=0).

Fundamental ambiguities of ONE baseline (stated plainly, not hidden):
  1. cos(θ) gives the same value for +θ and −θ: a two-element baseline cannot
     tell which SIDE of the baseline the signal is on (mirror ambiguity). The
     result is really a CONE of possible directions around the baseline axis.
  2. If D = d/λ > 0.5, |Δφ| can exceed π and wraps: multiple θ map to the same
     measured (wrapped) Δφ — SPATIAL ALIASING / grating lobes. Unambiguous only
     for D ≤ 0.5 (d ≤ λ/2).
  3. Sensitivity dθ/dΔφ ∝ 1/sin(θ): near endfire (θ→0 or 180°) a given phase
     error blows up into a huge angle error. Best accuracy is at broadside.

Resolving these needs a second (orthogonal) baseline, a third element, or a
sense antenna / crossed loops (Watson-Watt) — see df-proposal.md. This module
reports the cone angle(s) and flags ambiguity; the caller layers on the second
baseline later.
"""
import math

C = 299_792_458.0


def wavelength(freq_hz):
    return C / float(freq_hz)


def electrical_spacing(baseline_m, freq_hz):
    """Baseline in wavelengths, D = d/λ. D>0.5 => phase-ambiguous."""
    return baseline_m / wavelength(freq_hz)


def max_unambiguous_phase_deg(baseline_m, freq_hz):
    """The |Δφ| beyond which θ solutions alias, = 360·D (deg)."""
    return 360.0 * electrical_spacing(baseline_m, freq_hz)


def phase_for_angle_deg(theta_deg, baseline_m, freq_hz):
    """Forward model: cone angle θ (from baseline axis) -> Δφ in degrees.
    Not wrapped — can exceed ±180 for D>0.5 (that's the aliasing)."""
    D = electrical_spacing(baseline_m, freq_hz)
    return 360.0 * D * math.cos(math.radians(theta_deg))


def angle_for_phase_deg(dphi_deg, baseline_m, freq_hz):
    """Inverse model: measured Δφ (deg) -> cone angle θ (deg, 0..180) from the
    baseline axis.

    Returns a dict:
      ok:        bool — False if |Δφ| implies |cos θ|>1 (out of range / bad cal)
      theta_deg: the cone angle (0..180); the mirror twin is simply -theta / the
                 same cone on the other side (see 'mirror' note in module doc)
      cos_theta: the raw cosine (for diagnostics)
      aliased:   bool — True if D>0.5, i.e. other θ also produce this wrapped Δφ
      D:         electrical spacing
    Note: this treats Δφ as ALREADY UNWRAPPED / within the unambiguous range.
    For D>0.5 the caller must resolve the wrap (2nd baseline) before trusting θ.
    """
    D = electrical_spacing(baseline_m, freq_hz)
    if D == 0:
        return {"ok": False, "reason": "zero baseline", "D": 0.0}
    cos_theta = (dphi_deg / 360.0) / D
    aliased = D > 0.5
    if abs(cos_theta) > 1.0:
        # Physically impossible for a real arrival at this D — means the phase is
        # out of the unambiguous window (aliasing) or the calibration is off.
        return {"ok": False, "reason": "|cos θ|>1 (phase out of range / "
                "uncalibrated / aliased)", "cos_theta": cos_theta,
                "aliased": aliased, "D": D}
    theta = math.degrees(math.acos(cos_theta))
    return {"ok": True, "theta_deg": theta, "cos_theta": cos_theta,
            "aliased": aliased, "D": D}


def theta_error_deg(dphi_std_deg, theta_deg, baseline_m, freq_hz):
    """Propagate a Δφ measurement std into a cone-angle std at this θ.
    θ_err ≈ |dθ/dΔφ|·Δφ_err, with dθ/dΔφ = 1/(2π D sin θ)  (Δφ in radians)."""
    D = electrical_spacing(baseline_m, freq_hz)
    s = abs(math.sin(math.radians(theta_deg)))
    if s < 1e-6 or D == 0:
        return float("inf")
    dtheta_rad = math.radians(dphi_std_deg) / (2 * math.pi * D * s)
    return math.degrees(dtheta_rad)


def two_baseline_bearing(dphi_x_deg, dphi_y_deg, baseline_m, freq_hz):
    """Full 0..360° azimuth from TWO ORTHOGONAL baselines (X = along 0°/East,
    Y = along 90°/North), each measuring the phase of the SAME signal.

    For a wave from azimuth ψ (measured from the X axis, CCW), the direction
    cosines onto the two baselines are cos(ψ) and sin(ψ), so:
        Δφ_x = 360 D cos(ψ),   Δφ_y = 360 D sin(ψ)
    Hence ψ = atan2(Δφ_y, Δφ_x) — the two baselines resolve the mirror ambiguity
    of each single baseline, giving unambiguous azimuth (still subject to
    per-baseline aliasing if D>0.5).

    Returns dict: ok, azimuth_deg (0..360), D, aliased, and |Δφ| magnitude ratio
    check (should be ≈ 360 D if the model holds — a data-quality indicator)."""
    D = electrical_spacing(baseline_m, freq_hz)
    az = math.degrees(math.atan2(dphi_y_deg, dphi_x_deg)) % 360.0
    mag = math.hypot(dphi_x_deg, dphi_y_deg)
    expected = 360.0 * D
    return {"ok": True, "azimuth_deg": az, "D": D, "aliased": D > 0.5,
            "phase_mag_deg": mag, "expected_mag_deg": expected,
            "mag_ratio": (mag / expected if expected else float("inf"))}
