"""Fluke 80i-400 AC current clamp — read via a generic bench DMM.

The 80i-400 is a *passive current transformer*. It has no digital interface,
no battery, and no display of its own. Clamp it around a conductor and it
outputs an AC current into a meter's current (mA) jacks at a fixed ratio of
**1 mA per amp** (a 1000:1 division ratio). Whatever milliamp value the meter
reads is therefore the conductor current in amps.

    conductor_amps = meter_reading_A * 1000        # meter set to A range
    conductor_amps = meter_reading_mA * 1          # meter set to mA range

This module provides the conversion, the datasheet accuracy model, and an
optional live-read helper that composes with any rf-bench DMM driver exposing
an ``measure_iac()`` method that returns amperes (e.g.
``rf_bench.siglent.SDM3045X``).

IMPORTANT wiring notes (this trips people up):
  * The probe MUST be plugged into the meter's **current (A / mA) input**, not
    the volts input. It is a current source; on a volts range it reads ~zero.
  * Set the meter to **AC current**, true-RMS preferred.
  * At 400 A the probe delivers 400 mA. Verify the meter's mA range and fuse
    are rated for that.

Datasheet (Fluke 80i-400):
  * Ratio:      1 mA/A  (1000:1)
  * Range:      1 A – 400 A AC
  * Frequency:  48 Hz – 1000 Hz
  * Accuracy:   ±(3 % of reading + 0.4 A), 48 Hz – 1 kHz
  * Power:      none (passive CT)

Author: Jeff Francis (N0GQ) <gjfrancis@protonmail.com>
License: GPL-3.0-or-later
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# --- Fixed device constants (from the Fluke 80i-400 datasheet) --------------

RATIO_MA_PER_A = 1.0          # milliamps of output per amp of conductor current
DIVISION_RATIO = 1000.0       # meter reads 1/1000th of the conductor current
RANGE_MIN_A = 1.0             # below this the probe is unspecified
RANGE_MAX_A = 400.0           # above this the probe saturates / is out of spec
FREQ_MIN_HZ = 48.0
FREQ_MAX_HZ = 1000.0
ACC_PERCENT = 3.0             # % of reading
ACC_FLOOR_A = 0.4             # additive term, amperes


@dataclass
class ClampReading:
    """One current measurement through the 80i-400.

    Attributes:
        amps:        Conductor current (A), true-RMS AC.
        uncertainty: ± absolute uncertainty (A) from the datasheet accuracy
                     spec, or None if outside the specified 1–400 A range.
        in_range:    True if ``amps`` is within the specified 1–400 A range.
        meter_ma:    The raw meter reading in milliamps (== amps, since 1 mA/A).
    """

    amps: float
    uncertainty: Optional[float]
    in_range: bool
    meter_ma: float


class Fluke80i400:
    """Fluke 80i-400 AC current clamp used with an external DMM.

    Two ways to use it:

    1. Pure conversion (no instrument coupling)::

           clamp = Fluke80i400()
           amps = clamp.amps_from_milliamps(240.0)     # -> 240.0 A
           amps = clamp.amps_from_meter_amps(0.240)    # meter on A range -> 240 A
           acc  = clamp.accuracy(amps)                 # -> ± amps

    2. Live read through an rf-bench DMM driver::

           from rf_bench.siglent import SDM3045X
           dmm   = SDM3045X("10.1.0.50")
           clamp = Fluke80i400(dmm=dmm)
           r     = clamp.read()                        # -> ClampReading
           print(f"{r.amps:.1f} +/- {r.uncertainty:.1f} A")

    The DMM object need only provide ``measure_iac()`` (AC amps) — and, if you
    call ``read(dc=True)``, ``measure_idc()``. Any driver matching that shape
    works; the clamp does not care which meter it is.
    """

    RATIO_MA_PER_A = RATIO_MA_PER_A
    DIVISION_RATIO = DIVISION_RATIO
    RANGE_MIN_A = RANGE_MIN_A
    RANGE_MAX_A = RANGE_MAX_A

    def __init__(self, dmm=None):
        """
        Args:
            dmm: Optional bench DMM driver instance exposing ``measure_iac()``
                 (and optionally ``measure_idc()``) returning amperes. If given,
                 :meth:`read` will drive it directly. Omit for pure conversion.
        """
        self.dmm = dmm

    # --- Pure conversion helpers -------------------------------------------

    @staticmethod
    def amps_from_milliamps(meter_ma: float) -> float:
        """Convert a meter reading in **milliamps** to conductor amps.

        1 mA/A ratio, so the value is numerically unchanged (240 mA -> 240 A).
        Kept explicit so intent is clear at the call site.
        """
        return meter_ma * RATIO_MA_PER_A

    @staticmethod
    def amps_from_meter_amps(meter_a: float) -> float:
        """Convert a meter reading in **amps** to conductor amps.

        Use when the meter displays the clamp's output on its A range
        (e.g. 0.240 A). Multiplies by the 1000:1 division ratio -> 240 A.
        """
        return meter_a * DIVISION_RATIO

    @staticmethod
    def accuracy(amps: float) -> Optional[float]:
        """Return the ± absolute uncertainty (A) at a given conductor current.

        ±(3 % of reading + 0.4 A) per the datasheet. Returns None if the
        current is outside the specified 1–400 A range, where accuracy is
        not characterized.
        """
        if not (RANGE_MIN_A <= abs(amps) <= RANGE_MAX_A):
            return None
        return abs(amps) * (ACC_PERCENT / 100.0) + ACC_FLOOR_A

    @staticmethod
    def in_range(amps: float) -> bool:
        """True if ``amps`` is within the specified 1–400 A measuring range."""
        return RANGE_MIN_A <= abs(amps) <= RANGE_MAX_A

    def reading_from_milliamps(self, meter_ma: float) -> ClampReading:
        """Build a full :class:`ClampReading` from a raw milliamp value."""
        amps = self.amps_from_milliamps(meter_ma)
        return ClampReading(
            amps=amps,
            uncertainty=self.accuracy(amps),
            in_range=self.in_range(amps),
            meter_ma=meter_ma,
        )

    # --- Scope / burden-resistor front-end ---------------------------------
    #
    # A scope is high-impedance; the clamp is a current source. To read the
    # clamp on a scope, put a burden resistor across the clamp leads and sense
    # the voltage across it. The clamp sources 1 mA/A, so through R ohms:
    #     v_burden = (amps / 1000) * R      => amps = v_burden * 1000 / R
    # A 1 Ω burden gives a convenient 1 mV/A (400 A -> 400 mV).

    @staticmethod
    def burden_mv_per_amp(burden_ohms: float) -> float:
        """Scope sensitivity (mV per conductor amp) for a given burden resistor.

        e.g. 1 Ω -> 1.0 mV/A, 10 Ω -> 10.0 mV/A. Pick the burden so the full
        expected current stays on-screen and within the resistor's power
        rating (P = (amps/1000)^2 * R).
        """
        if burden_ohms <= 0:
            raise ValueError("burden_ohms must be positive")
        # 1 mA/A through R ohms -> R mV per amp.
        return burden_ohms

    @staticmethod
    def amps_from_burden_volts(v_burden: float, burden_ohms: float) -> float:
        """Convert a burden-resistor voltage (V) to conductor amps.

        amps = v_burden * 1000 / burden_ohms  (clamp sources 1 mA/A).
        """
        if burden_ohms <= 0:
            raise ValueError("burden_ohms must be positive")
        return v_burden * 1000.0 / burden_ohms

    def amps_from_burden_waveform(self, v_burden, burden_ohms: float):
        """Convert an array of burden voltages to an array of conductor amps.

        Accepts any numpy-array-like; returns element-wise
        ``v * 1000 / burden_ohms``. Kept dependency-free (no numpy import) so
        the driver stays lightweight — numpy arrays support the arithmetic
        natively, and plain lists work via a comprehension fallback.
        """
        if burden_ohms <= 0:
            raise ValueError("burden_ohms must be positive")
        scale = 1000.0 / burden_ohms
        try:
            return v_burden * scale          # numpy array / scalar fast path
        except TypeError:
            return [v * scale for v in v_burden]

    # --- Live read via a composed DMM driver -------------------------------

    def read(self, dc: bool = False, **measure_kwargs) -> ClampReading:
        """Read conductor current live through the attached DMM.

        Args:
            dc: If True, call the meter's ``measure_idc()`` (DC current) instead
                of ``measure_iac()``. Note the 80i-400 is an AC current
                transformer and is *not* specified for DC — this option exists
                only for meters/probes used off-label; results are not
                guaranteed by the datasheet.
            **measure_kwargs: Passed through to the meter's measure method
                (e.g. ``range_a=0.4`` to pin the mA range).

        Returns:
            ClampReading.

        Raises:
            RuntimeError: if no DMM was attached at construction.
        """
        if self.dmm is None:
            raise RuntimeError(
                "No DMM attached. Construct Fluke80i400(dmm=<driver>) or use "
                "the amps_from_* / reading_from_milliamps conversion helpers."
            )
        meter_a = (self.dmm.measure_idc(**measure_kwargs) if dc
                   else self.dmm.measure_iac(**measure_kwargs))
        # DMM drivers return amperes. On the mA range the probe's 1 mA/A output
        # reads as e.g. 0.240 A, i.e. milliamps/1000, so amps = reading * 1000.
        meter_ma = meter_a * 1000.0
        return self.reading_from_milliamps(meter_ma)

    def __repr__(self) -> str:
        coupled = f", dmm={self.dmm!r}" if self.dmm is not None else ""
        return f"Fluke80i400(1 mA/A, 1-400 A, 48-1000 Hz{coupled})"
