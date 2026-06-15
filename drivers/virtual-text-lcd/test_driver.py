#!/usr/bin/env python3
"""
Quick test script for Virtual Text LCD driver.
Run the backend server first:
  cd ~/Dropbox/build/rf-bench/virtual/text-lcd/backend && python3 server.py
"""

import sys
sys.path.insert(0, '.')

from rf_bench.virtual import VirtualTextLCD

# Test connection
try:
    lcd = VirtualTextLCD("localhost")
    print(f"✓ Connected to: {lcd.idn()}")

    # Test IEEE 488.2 commands
    print(f"✓ Error queue: {lcd.get_error()}")

    # Test configuration
    lcd.configure(title="Test Terminal", color="#00ff00", font_size=14, max_lines=100)
    print(f"✓ Title: {lcd.get_title()}")
    print(f"✓ Color: {lcd.get_color()}")
    print(f"✓ Font size: {lcd.get_font_size()}")
    print(f"✓ Max lines: {lcd.get_max_lines()}")

    # Test text display
    lcd.clear()
    lcd.write("System initialized")
    lcd.writeln("Temperature: 25.3°C")
    lcd.write("Pressure: 1013 hPa")
    print(f"✓ Line count: {lcd.get_line_count()}")

    # Test batch output
    lines = [f"Test message {i}" for i in range(5)]
    lcd.print_lines(lines)
    print(f"✓ After batch: {lcd.get_line_count()} lines")

    lcd.close()
    print("\n✓ All tests passed!")

except Exception as e:
    print(f"✗ Test failed: {e}")
    sys.exit(1)
