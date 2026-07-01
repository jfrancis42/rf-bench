#!/usr/bin/env python3
"""
HF Channel Simulator — comprehensive propagation model for IQ pipe.

Sits between modulator and demodulator to add realistic HF propagation
effects to the complex baseband IQ stream:

    modulate.py --stdout | hf-static.py [OPTIONS] | demodulate.py --stdin --speaker

Input/output format: raw complex64 (float32 I + float32 Q) at 8000 Hz.

═══════════════════════════════════════════════════════════════════════
PROPAGATION EFFECTS MODELED
═══════════════════════════════════════════════════════════════════════

1. THERMAL NOISE (AWGN)
   Every receiver has a noise floor from electron motion in components.
   White Gaussian noise — equal power at all frequencies. Controlled by
   SNR in dB. A perfectly quiet channel might be 40+ dB; a typical HF
   signal is readable at 10-15 dB; below 5 dB is barely copyable.

2. ATMOSPHERIC STATIC (QRN)
   Lightning from thunderstorms (even thousands of miles away) creates
   broadband electromagnetic impulses. These arrive as sharp "crashes"
   or "pops" in the receiver. Worse on lower bands (160m, 80m, 40m)
   and during summer months. Modeled as a Poisson process of short
   exponentially-decaying bursts.

3. RAYLEIGH FADING (ionospheric multipath)
   HF signals reach the receiver via multiple ionospheric reflections
   (E-layer, F1, F2, ground wave). These paths have different lengths
   and change as the ionosphere moves. When paths add constructively,
   signal is strong; destructively, it fades to nearly zero. The
   envelope follows a Rayleigh distribution (no dominant path).
   Fading rate is characterized by Doppler spread — typically 0.1-1 Hz
   for mid-latitude HF (fades over 2-10 seconds).

4. WATTERSON CHANNEL MODEL (selective fading)
   The ITU/CCIR standard model for HF channels (ITU-R F.1487, originally
   Watterson 1970). Unlike flat fading, SELECTIVE fading means different
   frequencies within the passband fade independently. This is what makes
   SSB signals sound "hollow" or "underwater" during deep fades — the
   carrier frequency fades while sidebands don't, or vice versa.
   Modeled as a tapped delay line with 2 paths, each with independent
   Rayleigh-faded complex gains (Gaussian-shaped Doppler spectrum).

5. DOPPLER SPREAD
   Ionospheric reflections from a diffuse layer give each ray a slightly
   different Doppler shift. This spreads each spectral line in frequency.
   On a CW signal, a pure tone becomes a "smeared" tone. On SSB, it
   causes a subtle loss of clarity. Typical HF spread: 0.1-2 Hz.

6. MULTIPATH DELAY SPREAD
   Multiple ionospheric hops arrive at different times. Typical delays:
   - Near-vertical incidence: 0.5-2 ms between modes
   - Long-path/multi-hop: 2-7 ms
   This causes ISI (inter-symbol interference) and the "reverberant"
   quality of HF signals during disturbed conditions.

7. LONG-PATH ECHO
   Signals can propagate both the short way and the long way around the
   Earth. The long-path arrives ~100-200 ms later as a distinct echo.
   Most noticeable on very long paths (antipodal stations).

8. FLUTTER FADING
   Very rapid fading (5-50 Hz Doppler) caused by:
   - Auroral scatter (polar paths)
   - Aircraft reflection
   - Meteor scatter (very brief bursts)
   Sounds like a "buzz" or "flutter" on the signal. Common on trans-
   polar paths and during geomagnetic storms.

9. POWER LINE NOISE (QRN man-made)
   Arcing or corona discharge on power lines radiates broadband noise
   at 60 Hz intervals (50 Hz in some countries). Sounds like a harsh
   buzz. Dominant on lower HF bands in residential areas.

10. QRM (man-made interference)
    Other stations transmitting on or near the same frequency:
    - Heterodyne: a CW station nearby creates a steady tone (whistle)
    - Splatter: an overdriven SSB station creates wideband garbage
    - Broadcast: shortwave broadcast stations are extremely strong

11. IONOSPHERIC CHIRP
    Sudden ionospheric disturbances (solar flares, traveling ionospheric
    disturbances) cause the reflection height to change, producing a
    slow frequency drift on the received signal. Sounds like the
    signal's pitch slowly wanders up or down.

12. ABSORPTION (D-layer)
    The D-layer (lowest ionospheric layer, present only in daytime)
    absorbs HF signals. Absorption is strongest at lower frequencies
    and during solar events. Modeled as a slow gain variation with
    possible sudden ionospheric disturbance (SID) events.

13. GEOMAGNETIC STORM
    During storms: increased absorption, very rapid fading, elevated
    noise floor, and possible complete signal loss (blackout). This
    is a composite effect — it cranks up fading rate, noise, and
    absorption simultaneously.

═══════════════════════════════════════════════════════════════════════
"""

import argparse
import sys
import numpy as np
from scipy.signal import firwin, lfilter, lfilter_zi


# ─────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────

SAMPLE_RATE = 8000
BLOCK_SAMPLES = 512           # 64 ms per block
BLOCK_BYTES = BLOCK_SAMPLES * 8


# ═════════════════════════════════════════════════════════════════════
# EFFECT IMPLEMENTATIONS
# ═════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────
# 1. Thermal Noise (AWGN)
# ─────────────────────────────────────────────────────────────────────

class ThermalNoise:
    """
    Additive White Gaussian Noise.

    Every electronic system has thermal noise from random electron
    motion (Johnson-Nyquist noise). It's "white" because it has equal
    power at all frequencies, and "Gaussian" because the central limit
    theorem makes the sum of many independent noise sources converge
    to a Gaussian distribution.

    The noise is complex-valued (I and Q components are independent
    Gaussian processes) because a quadrature receiver has noise on
    both paths.
    """

    def __init__(self, snr_db):
        self.snr_db = snr_db

    def process(self, block):
        sig_power = np.mean(np.abs(block) ** 2)
        if sig_power < 1e-20:
            sig_power = 1e-6  # floor for silent passages

        snr_linear = 10.0 ** (self.snr_db / 10.0)
        noise_power = sig_power / snr_linear
        noise_std = np.sqrt(noise_power / 2.0)

        noise = noise_std * (
            np.random.randn(len(block)) + 1j * np.random.randn(len(block))
        )
        return block + noise.astype(np.complex64)


# ─────────────────────────────────────────────────────────────────────
# 2. Atmospheric Static (QRN)
# ─────────────────────────────────────────────────────────────────────

class AtmosphericStatic:
    """
    Impulsive noise from lightning.

    Thunderstorms produce electromagnetic pulses that propagate
    thousands of miles via ionospheric reflection. A single lightning
    stroke radiates across the entire HF spectrum. At the receiver,
    it appears as a sharp impulse (a "crash") lasting 1-10 ms with
    a fast attack and exponential decay.

    On 80m and 40m in summer, you can hear almost continuous crashing
    even when the nearest storm is 2000 miles away. Higher bands
    (20m, 15m, 10m) are progressively quieter because atmospheric
    noise power falls off with frequency.
    """

    def __init__(self, rate_per_sec=3.0, intensity=0.3):
        self.rate = rate_per_sec
        self.intensity = intensity

    def process(self, block):
        block_duration = len(block) / SAMPLE_RATE
        n_crashes = np.random.poisson(self.rate * block_duration)

        if n_crashes == 0:
            return block

        result = block.copy()
        sig_rms = np.sqrt(np.mean(np.abs(block) ** 2)) + 1e-10

        for _ in range(n_crashes):
            pos = np.random.randint(0, len(block))
            # Duration 1-8 ms (8-64 samples). Longer crashes = more
            # "rolling thunder" character vs short "tick" impulses.
            duration = np.random.randint(8, 64)
            end = min(pos + duration, len(block))
            crash_len = end - pos

            # Sharp attack, exponential decay (time constant ~2 ms)
            envelope = np.exp(-np.linspace(0, 5, crash_len))

            # Broadband noise burst — complex for both I and Q
            noise = np.random.randn(crash_len) + 1j * np.random.randn(crash_len)

            # Occasional "monster crash" — 3x normal intensity
            burst_intensity = self.intensity
            if np.random.random() < 0.05:
                burst_intensity *= 3.0

            result[pos:end] += (
                burst_intensity * sig_rms * envelope * noise
            ).astype(np.complex64)

        return result


# ─────────────────────────────────────────────────────────────────────
# 3. Rayleigh Fading
# ─────────────────────────────────────────────────────────────────────

class RayleighFader:
    """
    Flat Rayleigh fading (all frequencies fade together).

    When multiple scattered paths combine with no dominant line-of-sight
    component, the received envelope follows a Rayleigh distribution.
    This is the classic model for HF skywave propagation.

    The "Doppler spread" controls how fast the fading occurs:
    - 0.05 Hz: very slow, gentle fading (stable propagation)
    - 0.2 Hz:  typical mid-latitude HF (fades every few seconds)
    - 1.0 Hz:  fast fading (disturbed ionosphere)
    - 5+ Hz:   flutter (auroral, see FlutterFader)

    Implementation uses the Jakes model: sum of N complex sinusoids
    at different Doppler frequencies. The resulting process has a
    Rayleigh-distributed envelope and uniform phase.
    """

    def __init__(self, max_doppler_hz=0.2, n_paths=12):
        self.n_paths = n_paths
        # Jakes: uniformly spaced angles → cosine-distributed Dopplers
        angles = np.pi * (np.arange(n_paths) + 0.5) / n_paths
        self.dopplers = max_doppler_hz * np.cos(angles)
        self.phases = np.random.uniform(0, 2 * np.pi, n_paths)
        self.sample_counter = 0

    def process(self, block):
        n = len(block)
        t = (self.sample_counter + np.arange(n)) / SAMPLE_RATE

        # Sum complex sinusoids → complex Gaussian process
        fading = np.zeros(n, dtype=np.complex128)
        for i in range(self.n_paths):
            fading += np.exp(
                1j * (2 * np.pi * self.dopplers[i] * t + self.phases[i])
            )
        # Normalize for unity average power
        fading /= np.sqrt(self.n_paths)

        self.sample_counter += n
        return (block * fading.astype(np.complex64))


# ─────────────────────────────────────────────────────────────────────
# 4. Watterson Channel (Selective Fading)
# ─────────────────────────────────────────────────────────────────────

class WattersonChannel:
    """
    ITU-R F.1487 / Watterson (1970) HF channel model.

    The key insight: on HF, different frequencies within even a 3 kHz
    SSB passband can fade independently. This "selective fading" is
    what makes HF signals sound hollow, watery, or distorted during
    fades — it's not just getting quieter, the spectral shape changes.

    The model uses a tapped delay line with 2 propagation paths,
    each having:
    - A fixed differential delay (time difference between paths)
    - An independent complex fading process (Gaussian Doppler spectrum)

    Standard test channels defined by ITU/CCIR:
    - "Good" (CCIR Poor): 0.5 Hz spread, 1 ms delay
    - "Moderate": 1.0 Hz spread, 2 ms delay
    - "Disturbed": 2.0 Hz spread, 4 ms delay (near-impossible for
      narrowband modems)

    The Gaussian Doppler spectrum (vs Jakes' classical U-shaped) is
    more appropriate for HF because ionospheric scatter has many
    independent contributions without a dominant angle of arrival.
    """

    def __init__(self, doppler_spread_hz=0.5, delay_ms=1.0, path_ratio_db=0):
        """
        doppler_spread_hz: 2-sigma width of the Gaussian Doppler spectrum
                           for each path's fading process
        delay_ms: differential delay between the two paths
        path_ratio_db: power ratio between paths (0 = equal power,
                       which gives deepest selective fading)
        """
        self.delay_samples = int(delay_ms * SAMPLE_RATE / 1000.0)
        self.doppler = doppler_spread_hz

        # Power split between paths (linear)
        ratio_linear = 10.0 ** (path_ratio_db / 10.0)
        total = 1.0 + ratio_linear
        self.gain1 = np.sqrt(1.0 / total)
        self.gain2 = np.sqrt(ratio_linear / total)

        # Delay buffer for the second path
        self.delay_buffer = np.zeros(self.delay_samples, dtype=np.complex64)

        # Fading state for each path — low-pass filtered complex noise
        # gives a Gaussian Doppler spectrum
        self._init_fading_filters()

        self.sample_counter = 0

    def _init_fading_filters(self):
        """
        Create fading processes for each path using the Jakes sum-of-
        sinusoids method — simpler and numerically stable compared to
        filtering complex noise (which can blow up in float32).

        Each path gets its own set of sinusoid Dopplers/phases, giving
        independent Rayleigh-distributed fading with a Gaussian-like
        Doppler spectrum.
        """
        n_osc = 8  # oscillators per path — enough for Rayleigh stats

        # Path 1: random Doppler frequencies within the spread
        self.dopplers1 = self.doppler * np.random.uniform(-1, 1, n_osc)
        self.phases1 = np.random.uniform(0, 2 * np.pi, n_osc)

        # Path 2: independent set
        self.dopplers2 = self.doppler * np.random.uniform(-1, 1, n_osc)
        self.phases2 = np.random.uniform(0, 2 * np.pi, n_osc)

        self.n_osc = n_osc
        self.fade_counter = 0

    def _get_fade_values(self, n):
        """
        Generate n complex fading samples for each path.

        Sum-of-sinusoids → complex Gaussian process whose envelope
        is Rayleigh-distributed. Normalized to unity average power.
        """
        t = (self.fade_counter + np.arange(n)) / SAMPLE_RATE

        fade1 = np.zeros(n, dtype=np.complex128)
        fade2 = np.zeros(n, dtype=np.complex128)
        for i in range(self.n_osc):
            fade1 += np.exp(1j * (2 * np.pi * self.dopplers1[i] * t + self.phases1[i]))
            fade2 += np.exp(1j * (2 * np.pi * self.dopplers2[i] * t + self.phases2[i]))

        fade1 /= np.sqrt(self.n_osc)
        fade2 /= np.sqrt(self.n_osc)
        self.fade_counter += n

        return fade1.astype(np.complex64), fade2.astype(np.complex64)

    def process(self, block):
        n = len(block)

        # Get per-sample fading coefficients for both paths
        fade1, fade2 = self._get_fade_values(n)

        # Path 1: direct (faded)
        path1 = block * fade1 * self.gain1

        # Path 2: delayed + faded
        # Prepend delay buffer, take first n samples as the delayed signal
        extended = np.concatenate([self.delay_buffer, block])
        delayed = extended[:n]
        # Save new delay buffer (last delay_samples of input)
        if self.delay_samples > 0:
            self.delay_buffer = extended[n:n + self.delay_samples]

        path2 = delayed * fade2 * self.gain2

        self.sample_counter += n
        return (path1 + path2).astype(np.complex64)


# ─────────────────────────────────────────────────────────────────────
# 5. Flutter Fading (Auroral / Aircraft)
# ─────────────────────────────────────────────────────────────────────

class FlutterFader:
    """
    Rapid flutter fading from auroral or aircraft scatter.

    Auroral propagation: signals reflect off the aurora borealis,
    which is a turbulent curtain of ionized particles. The reflection
    point moves rapidly, causing Doppler shifts of 10-100 Hz. The
    signal develops a characteristic "buzz" or "growl" — still
    readable but with a raspy quality.

    Aircraft scatter: a passing aircraft briefly reflects the signal,
    creating a second path with rapidly changing delay. Causes a
    periodic flutter at the aircraft's Doppler rate (5-20 Hz) lasting
    10-30 seconds.

    Meteor scatter: extremely brief (0.1-2 second) bursts of signal
    reflected off meteor ionization trails. Very strong but fleeting.
    """

    def __init__(self, doppler_hz=15.0, depth=0.5):
        """
        doppler_hz: flutter rate (5-50 Hz typical for auroral)
        depth: modulation depth (0=none, 1=full cancellation possible)
        """
        # Multiple flutter components at slightly different rates
        # creates a more natural, less "mechanical" flutter
        n = 6
        self.freqs = doppler_hz * (0.7 + 0.6 * np.random.rand(n))
        self.phases = np.random.uniform(0, 2 * np.pi, n)
        self.depth = depth
        self.sample_counter = 0

    def process(self, block):
        n = len(block)
        t = (self.sample_counter + np.arange(n)) / SAMPLE_RATE

        # Sum of sinusoidal amplitude modulations
        flutter = np.zeros(n)
        for i in range(len(self.freqs)):
            flutter += np.cos(2 * np.pi * self.freqs[i] * t + self.phases[i])
        flutter /= len(self.freqs)

        # Convert to multiplicative gain: 1 - depth*flutter
        # When flutter=-1 and depth=1, gain = 2 (constructive)
        # When flutter=+1 and depth=1, gain = 0 (destructive)
        gain = (1.0 - self.depth * flutter).astype(np.float32)

        self.sample_counter += n
        return block * gain


# ─────────────────────────────────────────────────────────────────────
# 6. Long-Path Echo
# ─────────────────────────────────────────────────────────────────────

class LongPathEcho:
    """
    Long-path propagation echo.

    Radio signals can travel both the short path and the long path
    (the other way around the Earth) between two stations. The long
    path is ~40,000 km minus the short path distance. At the speed
    of light, this gives a differential delay of:

        delay = (40000 km - 2 * short_path_km) / 300000 km/s

    For antipodal stations (20000 km), both paths are equal and you
    get double-hop echoes at ~133 ms. For shorter paths, the echo
    delay is longer (up to ~133 ms maximum).

    The echo is typically 15-30 dB below the main signal (much
    weaker because the long path has more hops and absorption).
    """

    def __init__(self, delay_ms=100.0, attenuation_db=20.0):
        self.delay_samples = int(delay_ms * SAMPLE_RATE / 1000.0)
        self.attenuation = 10.0 ** (-attenuation_db / 20.0)
        self.buffer = np.zeros(self.delay_samples, dtype=np.complex64)

    def process(self, block):
        n = len(block)

        # Concatenate buffer + current block to extract delayed version
        extended = np.concatenate([self.buffer, block])
        delayed = extended[:n]

        # Update buffer with the tail
        self.buffer = extended[n:n + self.delay_samples]

        # Output = direct + attenuated echo
        return (block + delayed * np.float32(self.attenuation))


# ─────────────────────────────────────────────────────────────────────
# 7. Power Line Noise
# ─────────────────────────────────────────────────────────────────────

class PowerLineNoise:
    """
    Man-made noise from power line arcing.

    Degraded or dirty insulators on power lines create small arcs
    that radiate broadband RF noise. Because arcing recurs every
    half-cycle of the mains frequency, the noise has a distinctive
    "buzz" character with energy concentrated at harmonics of 60 Hz
    (or 50 Hz in other countries).

    On a receiver, it sounds like a harsh, raspy buzz that's constant
    regardless of band conditions. It's location-dependent — suburban
    and residential areas are worse than rural.

    Modeled as a comb of impulses at 60 Hz (one per half-cycle =
    120 Hz impulse rate) with some jitter and broadband character.
    """

    def __init__(self, intensity=0.2, mains_hz=60.0):
        self.intensity = intensity
        self.period_samples = SAMPLE_RATE / (2 * mains_hz)  # half-cycle
        self.phase = 0.0

    def process(self, block):
        n = len(block)
        result = block.copy()
        sig_rms = np.sqrt(np.mean(np.abs(block) ** 2)) + 1e-10

        # Generate impulses at twice mains frequency (each half-cycle)
        pos = self.phase
        while pos < n:
            idx = int(pos)
            if idx < n:
                # Each arc is a short burst (0.5-1 ms) of noise
                burst_len = min(np.random.randint(4, 10), n - idx)
                burst = np.random.randn(burst_len) + 1j * np.random.randn(burst_len)
                envelope = np.exp(-np.linspace(0, 3, burst_len))
                result[idx:idx + burst_len] += (
                    self.intensity * sig_rms * envelope * burst
                ).astype(np.complex64)

            # Next half-cycle (with jitter — real arcing isn't perfectly periodic)
            jitter = 1.0 + 0.05 * np.random.randn()
            pos += self.period_samples * jitter

        # Save fractional phase for continuity across blocks
        self.phase = pos - n
        return result


# ─────────────────────────────────────────────────────────────────────
# 8. QRM (Interference from other stations)
# ─────────────────────────────────────────────────────────────────────

class Heterodyne:
    """
    CW heterodyne — a steady tone from another station.

    When a CW (Morse code) or unmodulated carrier is present near
    your receive frequency, it appears as a constant whistle in your
    passband. The tone frequency = frequency offset from your tuning.

    On a crowded band, you might hear multiple heterodynes at
    different pitches — a "birdies" effect. This is especially common
    on 40m and 20m during contests.
    """

    def __init__(self, offset_hz=800.0, amplitude=0.15):
        """
        offset_hz: frequency of the interfering tone (as heard in passband)
        amplitude: relative to signal level
        """
        self.offset_hz = offset_hz
        self.amplitude = amplitude
        self.sample_counter = 0

    def process(self, block):
        n = len(block)
        sig_rms = np.sqrt(np.mean(np.abs(block) ** 2)) + 1e-10
        t = (self.sample_counter + np.arange(n)) / SAMPLE_RATE

        # Pure complex tone at the offset frequency
        tone = np.exp(1j * 2 * np.pi * self.offset_hz * t).astype(np.complex64)

        self.sample_counter += n
        return block + self.amplitude * sig_rms * tone


class Splatter:
    """
    SSB splatter — wideband interference from an overdriven transmitter.

    When a nearby station's audio is clipped or their amplifier is
    overdriven, the signal's bandwidth expands well beyond the normal
    3 kHz. This "splatter" or "splashing" sounds like distorted,
    unintelligible voice garbage that rises and falls with their speech.

    Modeled as band-limited noise whose amplitude is modulated at
    speech-like rates (2-4 Hz envelope, simulating syllable rhythm).
    """

    def __init__(self, offset_hz=2000.0, amplitude=0.2):
        self.offset_hz = offset_hz
        self.amplitude = amplitude
        self.sample_counter = 0
        self.envelope_phase = np.random.uniform(0, 2 * np.pi)

    def process(self, block):
        n = len(block)
        sig_rms = np.sqrt(np.mean(np.abs(block) ** 2)) + 1e-10
        t = (self.sample_counter + np.arange(n)) / SAMPLE_RATE

        # Speech-rate amplitude modulation (~3 Hz)
        envelope = 0.5 * (1 + np.cos(2 * np.pi * 3.0 * t + self.envelope_phase))

        # Noise at an offset frequency (shifted from our passband center)
        noise = np.random.randn(n) + 1j * np.random.randn(n)
        shifted = noise * np.exp(1j * 2 * np.pi * self.offset_hz * t)

        self.sample_counter += n
        return block + (
            self.amplitude * sig_rms * envelope * shifted
        ).astype(np.complex64)


# ─────────────────────────────────────────────────────────────────────
# 9. Ionospheric Chirp
# ─────────────────────────────────────────────────────────────────────

class IonosphericChirp:
    """
    Slow frequency drift from ionospheric disturbances.

    Traveling Ionospheric Disturbances (TIDs) are wave-like variations
    in ionospheric density that propagate horizontally at 100-300 m/s.
    As they pass over the reflection point, the effective path length
    changes, causing a Doppler shift that slowly varies — the signal's
    pitch wanders up and down by a few Hz over tens of seconds.

    Sudden Ionospheric Disturbances (SIDs) from solar flares cause a
    rapid one-time frequency shift as the ionosphere abruptly changes
    height.

    On SSB, this makes voices sound like they're slowly drifting in
    and out of tune. On CW, the tone wanders in pitch.
    """

    def __init__(self, max_drift_hz=3.0, rate_hz=0.05):
        """
        max_drift_hz: peak frequency excursion
        rate_hz: how fast the drift oscillates (0.02-0.1 Hz typical)
        """
        self.max_drift = max_drift_hz
        self.rate = rate_hz
        self.phase = np.random.uniform(0, 2 * np.pi)
        self.sample_counter = 0

    def process(self, block):
        n = len(block)
        t = (self.sample_counter + np.arange(n)) / SAMPLE_RATE

        # Slowly varying frequency offset (sinusoidal wandering)
        drift_hz = self.max_drift * np.sin(2 * np.pi * self.rate * t + self.phase)

        # Integrate frequency to get phase
        phase = 2 * np.pi * np.cumsum(drift_hz) / SAMPLE_RATE
        shift = np.exp(1j * phase).astype(np.complex64)

        self.sample_counter += n
        return block * shift


# ─────────────────────────────────────────────────────────────────────
# 10. Absorption (D-layer)
# ─────────────────────────────────────────────────────────────────────

class Absorption:
    """
    D-layer absorption and Sudden Ionospheric Disturbances.

    The D-layer (60-90 km altitude) is present only during the day.
    It absorbs HF signals passing through it — the lower the frequency,
    the more absorption. This is why 80m and 160m are "nighttime bands"
    (the D-layer disappears at night, removing the absorption).

    During solar flares, enhanced X-ray and UV radiation dramatically
    increases D-layer ionization, causing a Sudden Ionospheric
    Disturbance (SID). Signals can fade by 10-30 dB in minutes,
    sometimes causing a complete blackout.

    Modeled as a slowly-varying gain with occasional "SID events."
    """

    def __init__(self, base_loss_db=3.0, sid_probability=0.001):
        """
        base_loss_db: normal D-layer absorption (frequency/time dependent)
        sid_probability: chance of a SID event per block (~0.001 for occasional)
        """
        self.base_gain = 10.0 ** (-base_loss_db / 20.0)
        self.sid_prob = sid_probability
        self.current_gain = self.base_gain
        self.sid_recovery_rate = 0.001  # slow recovery

    def process(self, block):
        # Randomly trigger a SID (sudden deep absorption)
        if np.random.random() < self.sid_prob:
            # SID: 10-25 dB additional loss, sudden onset
            extra_loss_db = np.random.uniform(10, 25)
            self.current_gain = self.base_gain * 10.0 ** (-extra_loss_db / 20.0)

        # Slow recovery back to base level
        self.current_gain += (self.base_gain - self.current_gain) * self.sid_recovery_rate

        return block * np.float32(self.current_gain)


# ─────────────────────────────────────────────────────────────────────
# 11. Band Noise Profile
# ─────────────────────────────────────────────────────────────────────

class BandNoise:
    """
    Frequency-dependent background noise characteristics.

    Different HF bands have very different noise environments:
    - 160m (1.8 MHz): Dominated by atmospheric + man-made noise.
                       Noise floor 30-50 dB above thermal. Very crashy.
    - 80m (3.5 MHz):  Heavy atmospheric noise (summer), man-made (urban)
    - 40m (7 MHz):    Moderate atmospheric, busy with stations
    - 20m (14 MHz):   Galactic noise becomes significant, atmospheric less
    - 15m (21 MHz):   Quieter, galactic noise, less QRN
    - 10m (28 MHz):   Quietest HF band. Near thermal noise floor.
                       Main noise is man-made (computers, electronics).

    This module shapes the noise spectrum to match a selected band's
    character. Lower bands get more low-frequency rumble and impulsive
    character; higher bands get a flatter, quieter noise profile.
    """

    def __init__(self, band="40m"):
        # Band-specific noise coloring (relative LF boost in dB)
        band_profiles = {
            "160m": {"lf_boost": 12, "color_cutoff": 800},
            "80m":  {"lf_boost": 8,  "color_cutoff": 600},
            "40m":  {"lf_boost": 5,  "color_cutoff": 400},
            "20m":  {"lf_boost": 2,  "color_cutoff": 300},
            "15m":  {"lf_boost": 1,  "color_cutoff": 200},
            "10m":  {"lf_boost": 0,  "color_cutoff": 100},
        }
        profile = band_profiles.get(band, band_profiles["40m"])
        self.lf_boost = 10.0 ** (profile["lf_boost"] / 20.0)

        # Design a lowpass filter to create "colored" noise
        # that emphasizes low frequencies (rumble)
        cutoff = profile["color_cutoff"] / (SAMPLE_RATE / 2)
        cutoff = min(max(cutoff, 0.01), 0.99)
        self.color_fir = firwin(63, cutoff)
        self.color_zi = lfilter_zi(self.color_fir, 1.0) * 0

    def process(self, block):
        # Generate colored noise (LF-boosted)
        white = np.random.randn(len(block)) + 1j * np.random.randn(len(block))

        # Apply coloring filter (only to real part, keeps it simple)
        colored_r, self.color_zi = lfilter(
            self.color_fir, 1.0,
            white.real, zi=self.color_zi
        )
        colored = colored_r + 1j * white.imag

        # Mix colored (LF-boosted) noise with original signal
        sig_rms = np.sqrt(np.mean(np.abs(block) ** 2)) + 1e-10
        noise_level = 0.05 * self.lf_boost  # subtle coloring
        return block + (noise_level * sig_rms * colored).astype(np.complex64)


# ═════════════════════════════════════════════════════════════════════
# PRESETS — realistic composite channel conditions
# ═════════════════════════════════════════════════════════════════════

PRESETS = {
    "clear": {
        "description": "Strong signal, quiet band. Like 20m on a calm winter morning.",
        "snr": 30,
        "qrn_rate": 0.5, "qrn_intensity": 0.1,
        "fading_doppler": 0.05,
        "watterson": False,
        "flutter": False,
        "echo": False,
        "powerline": False,
        "heterodyne": False,
        "splatter": False,
        "chirp": False,
        "absorption": False,
        "offset_hz": 0,
        "band": "20m",
    },
    "moderate": {
        "description": "Typical daytime HF. 40m with some QRN and gentle fading.",
        "snr": 15,
        "qrn_rate": 3, "qrn_intensity": 0.3,
        "fading_doppler": 0.2,
        "watterson": True, "watt_doppler": 0.5, "watt_delay": 1.0,
        "flutter": False,
        "echo": False,
        "powerline": False,
        "heterodyne": False,
        "splatter": False,
        "chirp": True, "chirp_drift": 2.0,
        "absorption": False,
        "offset_hz": 5,
        "band": "40m",
    },
    "rough": {
        "description": "Disturbed conditions. Heavy QRN, deep fading, selective fading.",
        "snr": 8,
        "qrn_rate": 8, "qrn_intensity": 0.5,
        "fading_doppler": 0.8,
        "watterson": True, "watt_doppler": 1.5, "watt_delay": 3.0,
        "flutter": False,
        "echo": False,
        "powerline": True, "powerline_intensity": 0.15,
        "heterodyne": True, "het_offset": 700, "het_amplitude": 0.1,
        "splatter": False,
        "chirp": True, "chirp_drift": 5.0,
        "absorption": True, "absorption_loss": 5,
        "offset_hz": 20,
        "band": "40m",
    },
    "dx": {
        "description": "Weak DX signal. Deep fading, echo, barely readable.",
        "snr": 4,
        "qrn_rate": 4, "qrn_intensity": 0.3,
        "fading_doppler": 0.5,
        "watterson": True, "watt_doppler": 1.0, "watt_delay": 2.0,
        "flutter": False,
        "echo": True, "echo_delay": 120, "echo_atten": 18,
        "powerline": False,
        "heterodyne": False,
        "splatter": False,
        "chirp": True, "chirp_drift": 3.0,
        "absorption": True, "absorption_loss": 8,
        "offset_hz": 30,
        "band": "20m",
    },
    "aurora": {
        "description": "Auroral propagation. Rapid flutter, raspy signal, Doppler spread.",
        "snr": 10,
        "qrn_rate": 2, "qrn_intensity": 0.2,
        "fading_doppler": 2.0,
        "watterson": True, "watt_doppler": 3.0, "watt_delay": 1.5,
        "flutter": True, "flutter_rate": 20, "flutter_depth": 0.6,
        "echo": False,
        "powerline": False,
        "heterodyne": False,
        "splatter": False,
        "chirp": True, "chirp_drift": 8.0,
        "absorption": False,
        "offset_hz": 0,
        "band": "20m",
    },
    "contest": {
        "description": "Crowded contest band. Heterodynes, splatter, wall-to-wall signals.",
        "snr": 18,
        "qrn_rate": 1, "qrn_intensity": 0.15,
        "fading_doppler": 0.2,
        "watterson": True, "watt_doppler": 0.5, "watt_delay": 1.0,
        "flutter": False,
        "echo": False,
        "powerline": False,
        "heterodyne": True, "het_offset": 600, "het_amplitude": 0.2,
        "splatter": True, "splatter_offset": 2500, "splatter_amplitude": 0.25,
        "chirp": False,
        "absorption": False,
        "offset_hz": 0,
        "band": "20m",
    },
    "summer-80m": {
        "description": "80m in summer. Crushing atmospheric noise, heavy QRN.",
        "snr": 6,
        "qrn_rate": 15, "qrn_intensity": 0.7,
        "fading_doppler": 0.3,
        "watterson": True, "watt_doppler": 0.5, "watt_delay": 2.0,
        "flutter": False,
        "echo": False,
        "powerline": True, "powerline_intensity": 0.3,
        "heterodyne": False,
        "splatter": False,
        "chirp": False,
        "absorption": False,
        "offset_hz": 0,
        "band": "80m",
    },
    "geomagnetic-storm": {
        "description": "Major geomagnetic storm. Rapid fading, high absorption, near-blackout.",
        "snr": 3,
        "qrn_rate": 6, "qrn_intensity": 0.4,
        "fading_doppler": 3.0,
        "watterson": True, "watt_doppler": 4.0, "watt_delay": 5.0,
        "flutter": True, "flutter_rate": 10, "flutter_depth": 0.4,
        "echo": False,
        "powerline": False,
        "heterodyne": False,
        "splatter": False,
        "chirp": True, "chirp_drift": 15.0,
        "absorption": True, "absorption_loss": 15,
        "offset_hz": 50,
        "band": "40m",
    },
}


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="HF channel simulator — comprehensive propagation model for IQ pipe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Presets (use --preset NAME):
  clear              Strong signal, quiet band (like 20m winter morning)
  moderate           Typical daytime 40m (some QRN, gentle fading)
  rough              Disturbed conditions (deep fading, heavy QRN)
  dx                 Weak DX signal (long-path echo, deep fading)
  aurora             Auroral propagation (rapid flutter, raspy)
  contest            Crowded band (heterodynes, splatter)
  summer-80m         80m in summer (crushing atmospheric noise)
  geomagnetic-storm  Major storm (near-blackout conditions)

Examples:
  # Basic — moderate HF conditions (default)
  modulate.py --stdout | hf-static.py | demodulate.py --stdin --speaker

  # Specific preset
  modulate.py --stdout | hf-static.py --preset aurora | demodulate.py --stdin --speaker

  # Custom: very weak signal with echo
  modulate.py --stdout | hf-static.py --snr 3 --echo 150 --fading 1.0 | demodulate.py --stdin --speaker

  # Just noise and QRN, no fading
  modulate.py --stdout | hf-static.py --snr 10 --qrn 8 --no-fading | demodulate.py --stdin --speaker
""",
    )

    # Passthrough
    parser.add_argument(
        "--passthrough", action="store_true",
        help="Pass IQ data through unmodified (no effects). Useful for A/B comparison."
    )

    # Presets
    parser.add_argument(
        "--preset", choices=PRESETS.keys(), default=None,
        help="Channel condition preset (individual flags override)"
    )

    # Noise
    parser.add_argument("--snr", type=float, help="SNR in dB (default: 15)")
    parser.add_argument("--no-noise", action="store_true", help="Disable thermal noise")

    # Atmospheric
    parser.add_argument("--qrn", type=float, help="QRN crash rate per second")
    parser.add_argument("--qrn-intensity", type=float, help="QRN intensity (0-1)")
    parser.add_argument("--no-qrn", action="store_true", help="Disable atmospheric static")

    # Fading
    parser.add_argument("--fading", type=float, help="Rayleigh fading Doppler (Hz)")
    parser.add_argument("--no-fading", action="store_true", help="Disable Rayleigh fading")

    # Watterson
    parser.add_argument("--watterson", action="store_true", help="Enable Watterson selective fading")
    parser.add_argument("--no-watterson", action="store_true", help="Disable Watterson")
    parser.add_argument("--watt-doppler", type=float, help="Watterson Doppler spread (Hz)")
    parser.add_argument("--watt-delay", type=float, help="Watterson multipath delay (ms)")

    # Flutter
    parser.add_argument("--flutter", type=float, help="Flutter rate (Hz), enables flutter")
    parser.add_argument("--flutter-depth", type=float, help="Flutter depth (0-1)")
    parser.add_argument("--no-flutter", action="store_true", help="Disable flutter")

    # Echo
    parser.add_argument("--echo", type=float, help="Long-path echo delay (ms), enables echo")
    parser.add_argument("--echo-atten", type=float, help="Echo attenuation (dB)")
    parser.add_argument("--no-echo", action="store_true", help="Disable echo")

    # Power line
    parser.add_argument("--powerline", type=float, help="Power line noise intensity, enables it")
    parser.add_argument("--no-powerline", action="store_true", help="Disable power line noise")
    parser.add_argument("--mains", type=float, default=60.0, help="Mains frequency (default: 60)")

    # QRM
    parser.add_argument("--heterodyne", type=float, help="Heterodyne offset Hz, enables it")
    parser.add_argument("--het-amplitude", type=float, help="Heterodyne amplitude (0-1)")
    parser.add_argument("--no-heterodyne", action="store_true", help="Disable heterodyne")
    parser.add_argument("--splatter", type=float, help="Splatter offset Hz, enables it")
    parser.add_argument("--splatter-amplitude", type=float, help="Splatter amplitude (0-1)")
    parser.add_argument("--no-splatter", action="store_true", help="Disable splatter")

    # Chirp
    parser.add_argument("--chirp", type=float, help="Ionospheric chirp max drift (Hz)")
    parser.add_argument("--no-chirp", action="store_true", help="Disable chirp")

    # Absorption
    parser.add_argument("--absorption", type=float, help="D-layer absorption (dB)")
    parser.add_argument("--no-absorption", action="store_true", help="Disable absorption")

    # Frequency offset
    parser.add_argument("--offset", type=float, help="Frequency offset (Hz)")

    # Band character
    parser.add_argument("--band", choices=["160m", "80m", "40m", "20m", "15m", "10m"],
                        help="Band noise character")

    args = parser.parse_args()

    # ─── Passthrough mode ───────────────────────────────────────────

    if args.passthrough:
        print("HF Channel Simulator — PASSTHROUGH (no effects)", file=sys.stderr)
        stdin = sys.stdin.buffer
        stdout = sys.stdout.buffer
        block_count = 0
        try:
            while True:
                raw = stdin.read(BLOCK_BYTES)
                if not raw:
                    break
                stdout.write(raw)
                stdout.flush()
                block_count += 1
        except (BrokenPipeError, KeyboardInterrupt):
            pass
        duration = block_count * BLOCK_SAMPLES / SAMPLE_RATE
        print(f"\n  Passed through {block_count} blocks ({duration:.1f}s)", file=sys.stderr)
        return

    # ─── Build parameters from preset + overrides ───────────────────

    if args.preset:
        p = PRESETS[args.preset].copy()
    else:
        p = PRESETS["moderate"].copy()

    # Apply explicit overrides
    if args.snr is not None: p["snr"] = args.snr
    if args.qrn is not None: p["qrn_rate"] = args.qrn
    if args.qrn_intensity is not None: p["qrn_intensity"] = args.qrn_intensity
    if args.fading is not None: p["fading_doppler"] = args.fading
    if args.watterson: p["watterson"] = True
    if args.watt_doppler is not None: p["watt_doppler"] = args.watt_doppler; p["watterson"] = True
    if args.watt_delay is not None: p["watt_delay"] = args.watt_delay; p["watterson"] = True
    if args.flutter is not None: p["flutter"] = True; p["flutter_rate"] = args.flutter
    if args.flutter_depth is not None: p["flutter_depth"] = args.flutter_depth
    if args.echo is not None: p["echo"] = True; p["echo_delay"] = args.echo
    if args.echo_atten is not None: p["echo_atten"] = args.echo_atten
    if args.powerline is not None: p["powerline"] = True; p["powerline_intensity"] = args.powerline
    if args.heterodyne is not None: p["heterodyne"] = True; p["het_offset"] = args.heterodyne
    if args.het_amplitude is not None: p["het_amplitude"] = args.het_amplitude
    if args.splatter is not None: p["splatter"] = True; p["splatter_offset"] = args.splatter
    if args.splatter_amplitude is not None: p["splatter_amplitude"] = args.splatter_amplitude
    if args.chirp is not None: p["chirp"] = True; p["chirp_drift"] = args.chirp
    if args.absorption is not None: p["absorption"] = True; p["absorption_loss"] = args.absorption
    if args.offset is not None: p["offset_hz"] = args.offset
    if args.band is not None: p["band"] = args.band

    # Disable flags
    if args.no_noise: p["snr"] = 999
    if args.no_qrn: p["qrn_rate"] = 0
    if args.no_fading: p["fading_doppler"] = 0
    if args.no_watterson: p["watterson"] = False
    if args.no_flutter: p["flutter"] = False
    if args.no_echo: p["echo"] = False
    if args.no_powerline: p["powerline"] = False
    if args.no_heterodyne: p["heterodyne"] = False
    if args.no_splatter: p["splatter"] = False
    if args.no_chirp: p["chirp"] = False
    if args.no_absorption: p["absorption"] = False

    # ─── Build effect chain ─────────────────────────────────────────

    effects = []

    # Print configuration
    preset_name = args.preset or "moderate"
    print(f"HF Channel Simulator — preset: {preset_name}", file=sys.stderr)
    if args.preset and args.preset in PRESETS:
        print(f"  {PRESETS[args.preset]['description']}", file=sys.stderr)
    print(f"  Band character: {p.get('band', '40m')}", file=sys.stderr)

    # Order matters — effects are applied in propagation order:
    # signal leaves TX → ionosphere (chirp, fading, delay, absorption)
    #   → arrives at RX antenna (+ noise, QRN, QRM)

    # Ionospheric chirp (frequency drift during propagation)
    if p.get("chirp"):
        drift = p.get("chirp_drift", 2.0)
        effects.append(("Ionospheric chirp", IonosphericChirp(max_drift_hz=drift)))
        print(f"  Chirp: ±{drift} Hz drift", file=sys.stderr)

    # Frequency offset (tuning error / Doppler)
    offset_hz = p.get("offset_hz", 0)
    if offset_hz != 0:
        effects.append(("Freq offset", FrequencyOffset(offset_hz)))
        print(f"  Offset: {offset_hz} Hz", file=sys.stderr)

    # Watterson selective fading (multipath in the ionosphere)
    if p.get("watterson"):
        wd = p.get("watt_doppler", 0.5)
        wdel = p.get("watt_delay", 1.0)
        effects.append(("Watterson", WattersonChannel(wd, wdel)))
        print(f"  Watterson: {wd} Hz spread, {wdel} ms delay", file=sys.stderr)

    # Rayleigh flat fading
    if p.get("fading_doppler", 0) > 0:
        fd = p["fading_doppler"]
        effects.append(("Rayleigh fading", RayleighFader(fd)))
        print(f"  Rayleigh fading: {fd} Hz Doppler", file=sys.stderr)

    # Flutter fading (auroral/aircraft)
    if p.get("flutter"):
        fr = p.get("flutter_rate", 15)
        fdepth = p.get("flutter_depth", 0.5)
        effects.append(("Flutter", FlutterFader(fr, fdepth)))
        print(f"  Flutter: {fr} Hz, depth {fdepth}", file=sys.stderr)

    # D-layer absorption
    if p.get("absorption"):
        loss = p.get("absorption_loss", 5)
        effects.append(("Absorption", Absorption(loss)))
        print(f"  Absorption: {loss} dB base loss", file=sys.stderr)

    # Long-path echo
    if p.get("echo"):
        ed = p.get("echo_delay", 120)
        ea = p.get("echo_atten", 20)
        effects.append(("Echo", LongPathEcho(ed, ea)))
        print(f"  Echo: {ed} ms delay, -{ea} dB", file=sys.stderr)

    # Thermal noise
    snr = p.get("snr", 15)
    if snr < 100:
        effects.append(("AWGN", ThermalNoise(snr)))
        print(f"  SNR: {snr} dB", file=sys.stderr)

    # Band noise coloring
    band = p.get("band", "40m")
    effects.append(("Band noise", BandNoise(band)))

    # Atmospheric static
    qrn_rate = p.get("qrn_rate", 0)
    if qrn_rate > 0:
        qi = p.get("qrn_intensity", 0.3)
        effects.append(("QRN", AtmosphericStatic(qrn_rate, qi)))
        print(f"  QRN: {qrn_rate}/sec, intensity {qi}", file=sys.stderr)

    # Power line noise
    if p.get("powerline"):
        pli = p.get("powerline_intensity", 0.2)
        effects.append(("Power line", PowerLineNoise(pli, args.mains)))
        print(f"  Power line: intensity {pli}, {args.mains} Hz mains", file=sys.stderr)

    # Heterodyne (CW interference)
    if p.get("heterodyne"):
        ho = p.get("het_offset", 800)
        ha = p.get("het_amplitude", 0.15)
        effects.append(("Heterodyne", Heterodyne(ho, ha)))
        print(f"  Heterodyne: {ho} Hz, amplitude {ha}", file=sys.stderr)

    # Splatter
    if p.get("splatter"):
        so = p.get("splatter_offset", 2000)
        sa = p.get("splatter_amplitude", 0.2)
        effects.append(("Splatter", Splatter(so, sa)))
        print(f"  Splatter: {so} Hz offset, amplitude {sa}", file=sys.stderr)

    print(f"  Effects chain: {len(effects)} stages", file=sys.stderr)
    print(f"  Block: {BLOCK_SAMPLES} samples ({BLOCK_SAMPLES*1000/SAMPLE_RATE:.0f} ms)", file=sys.stderr)

    # ─── Processing loop ────────────────────────────────────────────

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    block_count = 0

    try:
        while True:
            raw = stdin.read(BLOCK_BYTES)
            if not raw:
                break
            if len(raw) < BLOCK_BYTES:
                raw = raw + b'\x00' * (BLOCK_BYTES - len(raw))

            block = np.frombuffer(raw, dtype=np.complex64).copy()

            # Apply all effects in order
            for name, effect in effects:
                block = effect.process(block)

            stdout.write(block.tobytes())
            stdout.flush()
            block_count += 1

    except (BrokenPipeError, KeyboardInterrupt):
        pass

    duration = block_count * BLOCK_SAMPLES / SAMPLE_RATE
    print(f"\n  Processed {block_count} blocks ({duration:.1f}s)", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────
# Simple frequency offset (stateful wrapper for pipe use)
# ─────────────────────────────────────────────────────────────────────

class FrequencyOffset:
    """
    Constant frequency shift (tuning error or bulk Doppler).

    Multiplying baseband IQ by exp(j*2*pi*f*t) shifts the spectrum
    by f Hz. This is the most fundamental operation in SDR — it's
    how receivers tune to different frequencies digitally.
    """

    def __init__(self, offset_hz):
        self.offset_hz = offset_hz
        self.sample_counter = 0

    def process(self, block):
        n = len(block)
        t = (self.sample_counter + np.arange(n)) / SAMPLE_RATE
        shift = np.exp(1j * 2 * np.pi * self.offset_hz * t).astype(np.complex64)
        self.sample_counter += n
        return block * shift


if __name__ == "__main__":
    main()
