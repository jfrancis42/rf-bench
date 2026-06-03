#!/usr/bin/env python3
"""
Yertai ET5406A+ manual functionality test.
Prerequisites:
  - Siglent SPD3303X CH1 set to 13.8V / 3.2A manually (front panel)
  - CH1 OUTPUT enabled manually
  - Yertai connected to CH1 output

Run on greybox (10.1.0.16):
    python3 /home/jfrancis/Dropbox/build/rf-bench/yertai_manual_test.py
"""

import sys
import time
from rf_bench.yertai import ET5406A

LOAD_PORT = "/dev/ttyUSB0"


def hdr(title):
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def measure(load):
    v, i, p, r = load.read_all()
    print(f"    Yertai: V={v:.4f} V  I={i:.4f} A  P={p:.4f} W  R={r:.4f} Ω")
    return v, i, p, r


def check(label, val, lo, hi, failures):
    ok = lo <= val <= hi
    tag = "PASS" if ok else "FAIL"
    print(f"    [{tag}] {label} = {val:.4f}  (expected {lo:.3f}–{hi:.3f})")
    if not ok:
        failures.append(f"{label}: got {val:.4f}, expected {lo:.3f}–{hi:.3f}")
    return ok


def main():
    failures = []

    # ── STEP 1: Connect ──────────────────────────────────────────────────
    hdr("STEP 1: Connect to ET5406A+")
    input("\nMANUAL SETUP: Set PSU CH1 to 13.8V / 3.2A and enable OUTPUT. Press ENTER when ready...")

    load = ET5406A(LOAD_PORT)
    print(f"  Load: {load!r}")
    load.off()
    print("  Input: OFF")

    # ── STEP 2: Safety limits ────────────────────────────────────────────
    hdr("STEP 2: Set safety limits")
    load.OCP = 3.1      # just above max test current
    load.OPP = 50.0     # 3 A × 13.8 V = 41.4 W; 50 W gives headroom
    print(f"  OCP: {load.OCP:.3f} A")
    print(f"  OPP: {load.OPP:.3f} W")
    load.beep()
    print("  Beep: OK")

    # ── STEP 3: Baseline with load OFF ──────────────────────────────────
    hdr("STEP 3: Baseline measurement (input OFF)")
    load.CC_mode(0.001)
    v, i, p, r = measure(load)
    check("No-load voltage > 12V", v, 12.0, 15.0, failures)
    print(f"  Protection: {load.protection}")

    # ── STEP 4: CC mode tests ────────────────────────────────────────────
    for target_a in [0.5, 1.0, 2.0, 3.0]:
        hdr(f"STEP 4: CC mode — {target_a:.1f} A")
        load.CC_mode(target_a)
        print(f"  CC setpoint: {load.CC_current:.3f} A")
        time.sleep(0.1)
        load.on()
        print("  Input: ON")
        time.sleep(1.5)
        v, i, p, r = measure(load)
        print(f"  Protection: {load.protection}")

        tol = max(0.08, 0.06 * target_a)
        check(f"CC {target_a:.1f} A current", i, target_a - tol, target_a + tol, failures)
        check(f"CC {target_a:.1f} A voltage", v, 12.5, 14.5, failures)

        load.off()
        print("  Input: OFF")
        time.sleep(0.5)

    # ── STEP 5: read_all() consistency ───────────────────────────────────
    hdr("STEP 5: read_all() vs individual measurements")
    load.CC_mode(1.5)
    load.on()
    time.sleep(1.5)

    v_all, i_all, p_all, r_all = load.read_all()
    v_ind = load.read_voltage()
    i_ind = load.read_current()
    p_ind = load.read_power()
    r_ind = load.read_resistance()

    print(f"    read_all():   V={v_all:.4f}  I={i_all:.4f}  P={p_all:.4f}  R={r_all:.4f}")
    print(f"    individual:   V={v_ind:.4f}  I={i_ind:.4f}  P={p_ind:.4f}  R={r_ind:.4f}")

    check("Voltage consistency", abs(v_all - v_ind), 0.0, 0.2, failures)
    check("Current consistency", abs(i_all - i_ind), 0.0, 0.1, failures)

    load.off()
    time.sleep(0.5)

    # ── STEP 6: CR mode ──────────────────────────────────────────────────
    hdr("STEP 6: CR mode — 5.0 Ω (expect ~2.76 A @ 13.8V)")
    load.CR_mode(5.0)
    print(f"  CR setpoint: {load.CR_resistance:.3f} Ω")
    time.sleep(0.1)
    load.on()
    print("  Input: ON")
    time.sleep(1.5)
    v, i, p, r = measure(load)
    print(f"  Protection: {load.protection}")

    check("CR setpoint readback", load.CR_resistance, 4.9, 5.1, failures)
    check("CR measured resistance", r, 4.0, 6.5, failures)
    check("CR measured current", i, 2.0, 3.2, failures)

    load.off()
    time.sleep(0.5)

    # ── STEP 7: CP mode ──────────────────────────────────────────────────
    hdr("STEP 7: CP mode — 20.0 W")
    load.CP_mode(20.0)
    print(f"  CP setpoint: {load.CP_power:.3f} W")
    time.sleep(0.1)
    load.on()
    print("  Input: ON")
    time.sleep(1.5)
    v, i, p, r = measure(load)
    print(f"  Protection: {load.protection}")

    check("CP setpoint readback", load.CP_power, 19.5, 20.5, failures)
    check("CP measured power", p, 16.0, 24.0, failures)

    load.off()
    time.sleep(0.5)

    # ── STEP 8: CV mode (above supply) ────────────────────────────────────
    hdr("STEP 8: CV mode — 14.5V (above supply, should draw ~0A)")
    load.CV_mode(14.5)
    print(f"  CV setpoint: {load.CV_voltage:.3f} V")
    time.sleep(0.1)
    load.on()
    print("  Input: ON")
    time.sleep(1.5)
    v, i, p, r = measure(load)
    print(f"  Protection: {load.protection}")

    check("CV setpoint readback", load.CV_voltage, 14.4, 14.6, failures)
    check("CV current (should be ~0)", i, 0.0, 0.15, failures)

    load.off()
    time.sleep(0.5)

    # ── STEP 9: State queries ─────────────────────────────────────────────
    hdr("STEP 9: State and property checks")
    load.CC_mode(1.0)
    print(f"  mode: {load.mode!r}")
    print(f"  input: {load.input!r}")
    print(f"  CC_current: {load.CC_current:.3f} A")
    print(f"  OCP: {load.OCP:.3f} A")
    print(f"  OPP: {load.OPP:.3f} W")
    print(f"  protection: {load.protection!r}")
    print(f"  fan: {load.fan()!r}")
    print(f"  Vrange: {load.Vrange!r}")
    print(f"  Crange: {load.Crange!r}")

    # Mode setter/getter round-trip
    load.mode = "CR"
    m = load.mode
    ok = (m == "CR")
    print(f"\n  Mode round-trip: set 'CR' → got '{m}'  {'[PASS]' if ok else '[FAIL]'}")
    if not ok:
        failures.append(f"Mode round-trip failed: set CR, got {m!r}")
    load.mode = "CC"

    # Input setter/getter round-trip
    load.input = "ON"
    time.sleep(0.3)
    s = load.input
    ok = (s == "ON")
    print(f"  Input round-trip: set 'ON' → got '{s}'  {'[PASS]' if ok else '[FAIL]'}")
    if not ok:
        failures.append(f"Input round-trip failed: set ON, got {s!r}")
    load.input = "OFF"
    time.sleep(0.2)

    # ── STEP 10: Cleanup ──────────────────────────────────────────────────
    hdr("STEP 10: Cleanup")
    load.off()
    load.close()
    print("  Load OFF, connection closed")
    print("\nMANUAL: You can now disable PSU CH1 OUTPUT")

    # ── Summary ───────────────────────────────────────────────────────────
    hdr("SUMMARY")
    if failures:
        print(f"  FAILED — {len(failures)} issue(s):")
        for f in failures:
            print(f"    ✗  {f}")
        sys.exit(1)
    else:
        print("  ✓ ALL TESTS PASSED")
        print("  The new yertai driver is working correctly!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(130)
    except Exception as e:
        hdr("FATAL ERROR")
        print(f"  {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
