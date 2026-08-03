"""
simulate.py — synthesize sample-aligned two-channel IQ for a known arrival.

No hardware. Generates the complex baseband IQ that two coherent receivers WOULD
produce for a plane wave arriving from a known bearing on a known antenna
baseline, so the entire DF pipeline (cross-phase -> calibration -> geometry ->
bearing) can be built and regression-tested before the antennas go up. It stays
afterward as the ground-truth fixture: feed a known bearing in, confirm the
bearing comes back out.

What it models:
  * a signal (CW tone or band-limited noise) at a chosen baseband offset,
  * the geometric inter-antenna phase Δφ = 360·(d/λ)·cos(θ) for a single
    baseline, or the pair (Δφ_x, Δφ_y) for two orthogonal baselines,
  * the fixed inter-channel receiver offset φ0 (the scalar we measured: ~-33°),
  * independent thermal noise per channel (sets the coherence / phase jitter),
  * optional small per-channel gain imbalance.

It does NOT model skywave/multipath/polarization — those are the physical
reasons real HF bearings are hard (see df-proposal.md). This is the clean,
best-case fixture: if the pipeline can't recover a bearing here, it never will
on the air.
"""
import numpy as np

C = 299_792_458.0


def _source(n, rate, tone_hz, kind="tone", seed=0):
    """Baseband source signal (complex64), unit-ish amplitude."""
    rng = np.random.default_rng(seed)
    if kind == "tone":
        t = np.arange(n) / rate
        return np.exp(2j * np.pi * tone_hz * t).astype(np.complex64)
    if kind == "noise":
        # band-limited-ish: white complex noise (flat across the band)
        return (rng.standard_normal(n) + 1j * rng.standard_normal(n)
                ).astype(np.complex64) / np.sqrt(2)
    raise ValueError(f"unknown source kind {kind!r}")


def simulate_pair(*, n=131072, rate=39062.5, freq_hz=14_074_000,
                  theta_deg=90.0, baseline_m=10.0, tone_hz=1000.0,
                  kind="tone", snr_db=40.0, phi0_deg=-32.77,
                  gain_imbalance_db=0.0, seed=0):
    """Return (a, b): two complex64 arrays, RX1 and RX2, for a single baseline.

    The signal arrives at cone angle theta_deg from the baseline axis, so the
    inter-antenna geometric phase is Δφ_geo = 360·(d/λ)·cos(θ). Channel B (RX2)
    carries that geometric phase PLUS the fixed receiver offset φ0. Cross-phase
    angle(FFT_a·conj(FFT_b)) then recovers -(Δφ_geo + φ0) by the usual sign
    convention — the pipeline calibrates φ0 out and inverts the geometry.
    """
    lam = C / freq_hz
    D = baseline_m / lam
    dphi_geo = 360.0 * D * np.cos(np.radians(theta_deg))     # degrees
    return _pair_from_phase(dphi_geo, n, rate, tone_hz, kind, snr_db,
                            phi0_deg, gain_imbalance_db, seed)


def simulate_pair_azimuth(*, n=131072, rate=39062.5, freq_hz=14_074_000,
                          az_deg=0.0, baseline_m=10.0, **kw):
    """Two orthogonal baselines (X along 0°, Y along 90°) for a wave from
    azimuth az_deg. Returns (ax, bx, ay, by): the RX pairs for each baseline.
    Uses the SAME source realization scaled onto each baseline's geometry.
    """
    lam = C / freq_hz
    D = baseline_m / lam
    dphi_x = 360.0 * D * np.cos(np.radians(az_deg))
    dphi_y = 360.0 * D * np.sin(np.radians(az_deg))
    seed = kw.pop("seed", 0)
    ax, bx = _pair_from_phase(dphi_x, n, rate, seed=seed, **kw)
    ay, by = _pair_from_phase(dphi_y, n, rate, seed=seed + 1, **kw)
    return ax, bx, ay, by


def _pair_from_phase(dphi_geo_deg, n, rate, tone_hz=1000.0, kind="tone",
                     snr_db=40.0, phi0_deg=-32.77, gain_imbalance_db=0.0,
                     seed=0):
    sig = _source(n, rate, tone_hz, kind, seed)
    total_phase = np.radians(dphi_geo_deg + phi0_deg)
    a = sig.copy()
    b = (sig * np.exp(1j * total_phase)).astype(np.complex64)
    # per-channel independent noise sets coherence / phase jitter
    sig_p = np.mean(np.abs(sig) ** 2)
    npow = sig_p / (10 ** (snr_db / 10.0))
    rng = np.random.default_rng(seed + 777)
    for ch in (a, b):
        noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)
                 ) * np.sqrt(npow / 2)
        ch += noise.astype(np.complex64)
    if gain_imbalance_db:
        b *= 10 ** (gain_imbalance_db / 20.0)
    return a.astype(np.complex64), b.astype(np.complex64)
