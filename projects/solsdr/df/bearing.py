"""
bearing.py — the DF engine: calibrated cross-phase -> bearing + confidence.

Ties the pieces together (no hardware; the live radio front-end is df.py):
  measured Δφ  --(remove session offset φ0)-->  Δφ_geo  --(geometry.py)-->  angle

Two modes:
  * single baseline  -> cone angle θ (from the baseline axis) + mirror ambiguity
  * two baselines    -> unambiguous 0..360° azimuth

Calibration philosophy (mirrors solsdr's TX-safety interlock): a Calibration
object must be established for the session before bearings are trusted; an
uncalibrated engine refuses to emit a bearing. φ0 is the scalar inter-channel
offset measured by pointing both receivers at a common signal of KNOWN geometry
(a reference tone split to both antennas => θ known; or a beacon of known
bearing). Phase 0 + phasecal.py established that φ0 is a single scalar per
session (flat vs frequency), so one number per baseline suffices.
"""
from dataclasses import dataclass, field
from typing import Optional

import geometry as geo


@dataclass
class Calibration:
    """Per-session inter-channel offset(s), in degrees. One per baseline.

    phi0 is subtracted from the measured Δφ to leave the pure geometric phase.
    Established by measure_offset() against a signal of known geometry, or set
    directly if known. `valid` gates the engine (refuse-until-calibrated)."""
    phi0_x_deg: float = 0.0
    phi0_y_deg: float = 0.0
    valid: bool = False
    note: str = ""

    @staticmethod
    def from_reference(dphi_meas_deg, known_geo_phase_deg=0.0):
        """φ0 = measured Δφ − expected geometric Δφ, for a reference of known
        geometry. Common case: a tone split equally to both antennas has zero
        path difference => known_geo_phase_deg=0, so φ0 = measured Δφ."""
        return dphi_meas_deg - known_geo_phase_deg


@dataclass
class BearingResult:
    ok: bool
    baseline_m: float
    freq_hz: float
    dphi_meas_deg: float = 0.0
    dphi_geo_deg: float = 0.0
    theta_deg: Optional[float] = None       # single-baseline cone angle
    azimuth_deg: Optional[float] = None      # two-baseline azimuth
    theta_err_deg: Optional[float] = None
    aliased: bool = False
    mirror_ambiguous: bool = False
    reason: str = ""
    extra: dict = field(default_factory=dict)


class BearingEngine:
    """Single-baseline DF engine."""

    def __init__(self, baseline_m, freq_hz, calibration: Optional[Calibration] = None):
        self.baseline_m = float(baseline_m)
        self.freq_hz = float(freq_hz)
        self.cal = calibration or Calibration()

    def calibrate(self, dphi_meas_deg, known_geo_phase_deg=0.0, note="reference"):
        self.cal.phi0_x_deg = Calibration.from_reference(dphi_meas_deg,
                                                         known_geo_phase_deg)
        self.cal.valid = True
        self.cal.note = note
        return self.cal.phi0_x_deg

    def bearing(self, dphi_meas_deg, dphi_std_deg=0.0):
        """Measured Δφ (deg) -> BearingResult. Refuses if not calibrated."""
        if not self.cal.valid:
            return BearingResult(ok=False, baseline_m=self.baseline_m,
                                 freq_hz=self.freq_hz, dphi_meas_deg=dphi_meas_deg,
                                 reason="NOT CALIBRATED — establish the session "
                                 "offset first (refuse-until-calibrated)")
        # The measured cross-phase uses the Fa·conj(Fb) convention, which is the
        # NEGATIVE of the geometric inter-antenna phase (verified: measured =
        # -1×geometric). Removing the calibration offset (itself measured in the
        # same convention) leaves -(geometric), so negate to get Δφ_geo.
        dphi_geo = _wrap180(-(dphi_meas_deg - self.cal.phi0_x_deg))
        sol = geo.angle_for_phase_deg(dphi_geo, self.baseline_m, self.freq_hz)
        if not sol["ok"]:
            return BearingResult(ok=False, baseline_m=self.baseline_m,
                                 freq_hz=self.freq_hz, dphi_meas_deg=dphi_meas_deg,
                                 dphi_geo_deg=dphi_geo, aliased=sol.get("aliased", False),
                                 reason=sol.get("reason", "no solution"))
        theta = sol["theta_deg"]
        terr = geo.theta_error_deg(dphi_std_deg, theta, self.baseline_m,
                                   self.freq_hz) if dphi_std_deg else None
        return BearingResult(
            ok=True, baseline_m=self.baseline_m, freq_hz=self.freq_hz,
            dphi_meas_deg=dphi_meas_deg, dphi_geo_deg=dphi_geo, theta_deg=theta,
            theta_err_deg=terr, aliased=sol["aliased"], mirror_ambiguous=True,
            extra={"cos_theta": sol["cos_theta"], "D": sol["D"]})


class DualBaselineEngine:
    """Two orthogonal baselines -> unambiguous azimuth. X along 0°, Y along 90°."""

    def __init__(self, baseline_m, freq_hz, calibration: Optional[Calibration] = None):
        self.baseline_m = float(baseline_m)
        self.freq_hz = float(freq_hz)
        self.cal = calibration or Calibration()

    def calibrate(self, dphi_x_meas_deg, dphi_y_meas_deg,
                  known_x_deg=0.0, known_y_deg=0.0, note="reference"):
        self.cal.phi0_x_deg = dphi_x_meas_deg - known_x_deg
        self.cal.phi0_y_deg = dphi_y_meas_deg - known_y_deg
        self.cal.valid = True
        self.cal.note = note
        return self.cal.phi0_x_deg, self.cal.phi0_y_deg

    def bearing(self, dphi_x_meas_deg, dphi_y_meas_deg):
        if not self.cal.valid:
            return BearingResult(ok=False, baseline_m=self.baseline_m,
                                 freq_hz=self.freq_hz,
                                 reason="NOT CALIBRATED (both baselines)")
        # negate to undo the Fa·conj(Fb) sign convention (see BearingEngine)
        gx = _wrap180(-(dphi_x_meas_deg - self.cal.phi0_x_deg))
        gy = _wrap180(-(dphi_y_meas_deg - self.cal.phi0_y_deg))
        sol = geo.two_baseline_bearing(gx, gy, self.baseline_m, self.freq_hz)
        return BearingResult(
            ok=True, baseline_m=self.baseline_m, freq_hz=self.freq_hz,
            azimuth_deg=sol["azimuth_deg"], aliased=sol["aliased"],
            mirror_ambiguous=False,
            extra={"dphi_geo_x": gx, "dphi_geo_y": gy,
                   "mag_ratio": sol["mag_ratio"], "D": sol["D"]})


def _wrap180(deg):
    """Wrap to (-180, 180]."""
    d = (deg + 180.0) % 360.0 - 180.0
    return d if d != -180.0 else 180.0
