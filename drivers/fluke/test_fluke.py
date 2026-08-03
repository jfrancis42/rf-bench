#!/usr/bin/env python3
"""Quick self-test of the Fluke 80i-400 conversion layer (no hardware needed).

Run: python3 test_fluke.py
"""

from rf_bench.fluke import Fluke80i400, ClampReading


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


def test_conversions():
    clamp = Fluke80i400()
    # 1 mA/A: mA value equals amps.
    assert approx(clamp.amps_from_milliamps(240.0), 240.0)
    # Meter on A range: ×1000.
    assert approx(clamp.amps_from_meter_amps(0.240), 240.0)
    print("conversions: OK")


def test_accuracy():
    clamp = Fluke80i400()
    # ±(3% + 0.4 A) at 100 A = 3.4 A.
    assert approx(clamp.accuracy(100.0), 3.4)
    # Out of range -> None.
    assert clamp.accuracy(0.5) is None
    assert clamp.accuracy(500.0) is None
    assert clamp.in_range(200.0) is True
    assert clamp.in_range(0.5) is False
    print("accuracy: OK")


def test_reading():
    clamp = Fluke80i400()
    r = clamp.reading_from_milliamps(240.0)
    assert isinstance(r, ClampReading)
    assert approx(r.amps, 240.0)
    assert approx(r.uncertainty, 240.0 * 0.03 + 0.4)  # 7.6
    assert r.in_range is True
    assert approx(r.meter_ma, 240.0)
    print(f"reading: OK  ({r.amps:.1f} +/- {r.uncertainty:.1f} A)")


def test_live_read_with_fake_dmm():
    """Compose with a stand-in DMM that returns amperes like the real drivers."""

    class FakeDMM:
        def measure_iac(self, **kw):
            return 0.240  # 240 mA on the mA range

    clamp = Fluke80i400(dmm=FakeDMM())
    r = clamp.read()
    assert approx(r.amps, 240.0), r.amps
    assert approx(r.meter_ma, 240.0)
    print(f"live read (fake DMM): OK  ({r.amps:.1f} A)")


if __name__ == "__main__":
    test_conversions()
    test_accuracy()
    test_reading()
    test_live_read_with_fake_dmm()
    print("\nAll Fluke 80i-400 tests passed.")
