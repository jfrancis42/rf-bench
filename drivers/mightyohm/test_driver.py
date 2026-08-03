#!/usr/bin/env python3
"""Test script for MightyOhm Geiger Counter driver."""

import sys
import time
from rf_bench.mightyohm import MightyOhmGeiger, MightyOhmGeigerError


def test_basic():
    """Test basic connection and reading."""
    print("=" * 60)
    print("TEST 1: Basic Connection and Single Reading")
    print("=" * 60)

    try:
        geiger = MightyOhmGeiger()
        print(f"✓ Device found: {geiger}")

        reading = geiger.read()
        print(f"✓ Reading successful:")
        print(f"  CPS: {reading['cps']}")
        print(f"  CPM: {reading['cpm']}")
        print(f"  Dose: {reading['dose_usv_hr']:.2f} µSv/hr")
        print(f"  Mode: {reading['mode']}")
        print(f"  Raw: {reading['raw']}")

        geiger.close()
        return True
    except MightyOhmGeigerError as e:
        print(f"✗ Error: {e}")
        return False


def test_properties():
    """Test property access."""
    print("\n" + "=" * 60)
    print("TEST 2: Property Access")
    print("=" * 60)

    try:
        with MightyOhmGeiger() as geiger:
            print(f"CPS: {geiger.cps}")
            print(f"CPM: {geiger.cpm}")
            print(f"Dose: {geiger.dose_usv_hr:.2f} µSv/hr")
            print(f"Mode: {geiger.mode}")
            print("✓ All properties accessible")
        return True
    except MightyOhmGeigerError as e:
        print(f"✗ Error: {e}")
        return False


def test_streaming():
    """Test streaming mode."""
    print("\n" + "=" * 60)
    print("TEST 3: Streaming Mode (10 readings)")
    print("=" * 60)

    try:
        with MightyOhmGeiger() as geiger:
            readings = geiger.stream(count=10)
            print(f"✓ Collected {len(readings)} readings")

            if readings:
                avg_cpm = sum(r['cpm'] for r in readings) / len(readings)
                avg_dose = sum(r['dose_usv_hr'] for r in readings) / len(readings)
                print(f"  Average CPM: {avg_cpm:.1f}")
                print(f"  Average Dose: {avg_dose:.2f} µSv/hr")

                print("\n  Last 5 readings:")
                for r in readings[-5:]:
                    print(f"    {r['cps']:3d} CPS, {r['cpm']:4d} CPM, "
                          f"{r['dose_usv_hr']:5.2f} µSv/hr, {r['mode']}")
        return True
    except MightyOhmGeigerError as e:
        print(f"✗ Error: {e}")
        return False


def test_callback():
    """Test callback mode."""
    print("\n" + "=" * 60)
    print("TEST 4: Callback Mode (5 readings)")
    print("=" * 60)

    count = [0]  # Mutable counter for closure

    def callback(reading):
        count[0] += 1
        print(f"  Reading {count[0]}: {reading['cpm']} CPM, "
              f"{reading['dose_usv_hr']:.2f} µSv/hr")

    try:
        with MightyOhmGeiger() as geiger:
            geiger.stream(callback=callback, count=5)
            print(f"✓ Callback invoked {count[0]} times")
        return True
    except MightyOhmGeigerError as e:
        print(f"✗ Error: {e}")
        return False


def test_statistics():
    """Test statistics collection."""
    print("\n" + "=" * 60)
    print("TEST 5: Statistics Collection (20 seconds)")
    print("=" * 60)

    try:
        with MightyOhmGeiger() as geiger:
            print("Collecting data (this will take 20 seconds)...")
            stats = geiger.get_statistics(duration=20)

            print(f"✓ Collected {stats['count']} readings over {stats['duration']} seconds")
            print("\nCPS Statistics:")
            print(f"  Min:  {stats['cps']['min']}")
            print(f"  Max:  {stats['cps']['max']}")
            print(f"  Mean: {stats['cps']['mean']:.1f}")
            print(f"  StDev: {stats['cps']['stdev']:.1f}")

            print("\nCPM Statistics:")
            print(f"  Min:  {stats['cpm']['min']}")
            print(f"  Max:  {stats['cpm']['max']}")
            print(f"  Mean: {stats['cpm']['mean']:.1f}")
            print(f"  StDev: {stats['cpm']['stdev']:.1f}")

            print("\nDose Statistics (µSv/hr):")
            print(f"  Min:  {stats['dose_usv_hr']['min']:.2f}")
            print(f"  Max:  {stats['dose_usv_hr']['max']:.2f}")
            print(f"  Mean: {stats['dose_usv_hr']['mean']:.2f}")
            print(f"  StDev: {stats['dose_usv_hr']['stdev']:.2f}")
        return True
    except MightyOhmGeigerError as e:
        print(f"✗ Error: {e}")
        return False


def main():
    """Run all tests."""
    print("\nMightyOhm Geiger Counter Driver Test Suite")
    print("=" * 60)
    print("Testing with uranium glass source nearby...")
    print()

    tests = [
        test_basic,
        test_properties,
        test_streaming,
        test_callback,
        test_statistics,
    ]

    results = []
    for test in tests:
        results.append(test())
        time.sleep(1)  # Brief pause between tests

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("\n✓ All tests passed!")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
