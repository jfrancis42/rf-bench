#!/usr/bin/env python3
"""
Test script for Virtual Gauge Cluster driver.

Prerequisites:
1. Backend server must be running:
   cd ~/Dropbox/build/rf-bench/virtual/gauge-cluster/backend
   python3 server.py

2. Adjust host/port if needed (default: localhost:5025)

Usage:
    python3 test_driver.py
"""

import sys
import time
import math

# Add local package to path for testing
sys.path.insert(0, '.')

from rf_bench.virtual import VirtualGaugeCluster, VirtualGaugeClusterError


def test_basic_connection():
    """Test connection and IEEE 488.2 commands."""
    print("=" * 60)
    print("Test 1: Basic Connection and IEEE 488.2")
    print("=" * 60)

    try:
        cluster = VirtualGaugeCluster("localhost", port=5025)
        print(f"✓ Connected to {cluster.host}:{cluster.port}")

        idn = cluster.idn()
        print(f"✓ *IDN? → {idn}")

        error = cluster.get_error()
        print(f"✓ SYST:ERR? → {error}")

        cluster.reset()
        print("✓ *RST executed")

        cluster.close()
        print("✓ Connection closed")
        return True
    except VirtualGaugeClusterError as e:
        print(f"✗ Connection failed: {e}")
        return False


def test_layout():
    """Test layout configuration."""
    print("\n" + "=" * 60)
    print("Test 2: Layout Configuration")
    print("=" * 60)

    with VirtualGaugeCluster("localhost", port=5025) as cluster:
        cluster.set_layout(4)
        layout = cluster.get_layout()
        print(f"✓ Set layout to 4, read back: {layout}")

        cluster.set_layout(2)
        layout = cluster.get_layout()
        print(f"✓ Set layout to 2, read back: {layout}")

        cluster.set_layout(4)  # Restore to 4
        print("✓ Restored layout to 4")


def test_gauge_config():
    """Test gauge configuration."""
    print("\n" + "=" * 60)
    print("Test 3: Gauge Configuration")
    print("=" * 60)

    with VirtualGaugeCluster("localhost", port=5025) as cluster:
        cluster.configure_gauge(1, "Voltage", "V", 0, 15, "#00ff00")

        label = cluster.get_label(1)
        units = cluster.get_units(1)
        min_val = cluster.get_min(1)
        max_val = cluster.get_max(1)
        color = cluster.get_color(1)

        print(f"✓ Gauge 1 configured:")
        print(f"    Label: {label}")
        print(f"    Units: {units}")
        print(f"    Range: {min_val} to {max_val}")
        print(f"    Color: {color}")


def test_value_updates():
    """Test value updates."""
    print("\n" + "=" * 60)
    print("Test 4: Value Updates")
    print("=" * 60)

    with VirtualGaugeCluster("localhost", port=5025) as cluster:
        cluster.configure_gauge(1, "Test", "Units", 0, 100)

        cluster.set_value(1, 50.0)
        value = cluster.get_value(1)
        print(f"✓ Set value 50.0, read back: {value}")

        cluster.update(1, 75.5)
        value = cluster.get_value(1)
        print(f"✓ Update to 75.5, read back: {value}")


def test_multi_gauge():
    """Test multi-gauge configuration and updates."""
    print("\n" + "=" * 60)
    print("Test 5: Multi-Gauge Dashboard")
    print("=" * 60)

    with VirtualGaugeCluster("localhost", port=5025) as cluster:
        cluster.set_layout(4)

        cluster.configure_gauge(1, "Voltage", "V", 0, 15, "#00ff00")
        cluster.configure_gauge(2, "Current", "A", 0, 10, "#0088ff")
        cluster.configure_gauge(3, "Power", "W", 0, 150, "#ff8800")
        cluster.configure_gauge(4, "Temperature", "°C", 0, 100, "#ff0000")

        print("✓ Configured 4 gauges")

        # Update all at once
        cluster.update_all({1: 13.8, 2: 8.2, 3: 113.2, 4: 45.3})
        print("✓ Updated all gauges with dict")

        # Update all with list
        cluster.update_all([13.5, 8.0, 108.0, 43.0])
        print("✓ Updated all gauges with list")


def test_animation():
    """Test smooth animation."""
    print("\n" + "=" * 60)
    print("Test 6: Animation (3 seconds)")
    print("=" * 60)

    with VirtualGaugeCluster("localhost", port=5025) as cluster:
        cluster.set_layout(4)

        cluster.configure_gauge(1, "Sine Wave", "", -1, 1, "#00ff00")
        cluster.configure_gauge(2, "Cosine Wave", "", -1, 1, "#0088ff")
        cluster.configure_gauge(3, "Triangle", "", 0, 100, "#ff8800")
        cluster.configure_gauge(4, "Random", "", 0, 100, "#ff0000")

        print("✓ Animating gauges...")

        import random
        for t in range(60):
            cluster.set_value(1, math.sin(t * 0.2))
            cluster.set_value(2, math.cos(t * 0.2))
            cluster.set_value(3, 50 + 50 * math.sin(t * 0.1))
            cluster.set_value(4, random.uniform(20, 80))
            time.sleep(0.05)

        print("✓ Animation complete")


def test_error_handling():
    """Test error handling."""
    print("\n" + "=" * 60)
    print("Test 7: Error Handling")
    print("=" * 60)

    # Test invalid gauge index
    with VirtualGaugeCluster("localhost", port=5025) as cluster:
        try:
            cluster.set_value(5, 100)
            print("✗ Should have raised ValueError for index 5")
        except ValueError as e:
            print(f"✓ Caught expected ValueError: {e}")

        try:
            cluster.set_layout(3)
            print("✗ Should have raised ValueError for layout 3")
        except ValueError as e:
            print(f"✓ Caught expected ValueError: {e}")


def main():
    """Run all tests."""
    print("\nVirtual Gauge Cluster Driver Test Suite")
    print("Make sure backend server is running on localhost:5025")
    print("")

    if not test_basic_connection():
        print("\n✗ Connection test failed. Is the backend server running?")
        print("  Start with: cd virtual/gauge-cluster/backend && python3 server.py")
        sys.exit(1)

    test_layout()
    test_gauge_config()
    test_value_updates()
    test_multi_gauge()
    test_animation()
    test_error_handling()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
