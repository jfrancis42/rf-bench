#!/usr/bin/env python3
"""
Yertai ET5406A+ functionality test.
Source: Siglent SPD3303X CH1 @ 13.8 V / 3.2 A (hardware-limited).
Load:   Yertai ET5406A+ via /dev/ttyUSB0.
Wire limit: 5 A — SPD CH1 maxes at 3.2 A, so safe.

Run on greybox (10.1.0.16):
    python3 /home/jfrancis/Dropbox/build/rf-bench/yertai_test.py
"""

import sys
import time

from rf_bench.siglent import SPD3303X
from rf_bench.yertai import ET5406A

PSU_IP    = "10.1.1.56"
LOAD_PORT = "/dev/ttyUSB0"
VIN       = 13.8
I_LIMIT   = 3.2   # SPD CH1 hardware max


def hdr(title):
    print()
    print("=" * 62)
    print(f"  {title}")
    print("=" * 62)


def chk(label, val, lo, hi, failures):
    ok = lo <= val <= hi
    tag = "PASS" if ok else "FAIL"
    print(f"    [{tag}] {label} = {val:.4f}  (expected {lo:.3f}–{hi:.3f})")
    if not ok:
        failures.append(f"{label}: got {val:.4f}, expected {lo:.3f}–{hi:.3f}")
    return ok


def measure_both(psu, load):
    v, i, p, r = load.read_all()
    pm = psu.measure_all(1)
    print(f"    Yertai : V={v:.4f} V  I={i:.4f} A  P={p:.4f} W  R={r:.4f} Ω")
    print(f"    PSU CH1: {pm['voltage_v']:.3f} V  {pm['current_a']:.4f} A  "
          f"{pm['power_w']:.4f} W  mode={psu.get_mode(1)}")
    return v, i, p, r, pm


def main():
    failures = []

    # ── STEP 1: Connect ──────────────────────────────────────────────────
    hdr("STEP 1: Connect instruments")
    psu = SPD3303X(PSU_IP)
    print(f"  PSU IDN : {psu.identify()}")
    psu.disable_all()
    psu.set_tracking("INDEP")
    psu.set_voltage(1, VIN)
    psu.set_current(1, I_LIMIT)
    print(f"  PSU CH1 setpoint: {psu.get_voltage_setpoint(1):.3f} V, "
          f"{psu.get_current_setpoint(1):.3f} A limit")

    load = ET5406A(LOAD_PORT)
    print(f"  Load    : {load!r}")
    load.off()

    # ── STEP 2: Safety limits ────────────────────────────────────────────
    hdr("STEP 2: Set Yertai safety limits")
    load.OCP = 3.1      # just above max test current; SPD also clamps at 3.2 A
    load.OPP = 50.0     # 3 A × 13.8 V = 41.4 W; 50 W gives headroom
    print(f"  OCP set → readback: {load.OCP:.3f} A")
    print(f"  OPP set → readback: {load.OPP:.3f} W")
    load.beep()
    print("  Beep: OK")

    # ── STEP 3: Enable PSU, baseline ─────────────────────────────────────
    hdr("STEP 3: Enable PSU CH1 — baseline with load OFF")
    psu.enable(1)
    time.sleep(0.5)
    load.CC_mode(0.001)       # near-zero preset so first ON is safe
    v, i, p, r, pm = measure_both(psu, load)
    chk("idle PSU current < 0.05 A", pm["current_a"], 0.0, 0.05, failures)
    print(f"  Protection: {load.protection}")

    # ── STEP 4: CC mode sweep ────────────────────────────────────────────
    for target_a in [0.5, 1.0, 2.0, 3.0]:
        hdr(f"STEP 4: CC mode — {target_a:.1f} A")
        load.CC_mode(target_a)
        time.sleep(0.1)
        load.on()
        time.sleep(1.2)
        v, i, p, r, pm = measure_both(psu, load)
        print(f"  Protection: {load.protection}")
        tol = max(0.08, 0.06 * target_a)
        chk(f"CC {target_a:.1f} A current (Yertai)", i, target_a - tol, target_a + tol, failures)
        chk(f"CC {target_a:.1f} A current (PSU)",    pm["current_a"],
            target_a - tol - 0.05, target_a + tol + 0.05, failures)
        load.off()
        time.sleep(0.5)

    # ── STEP 5: CC — individual vs all readback consistency ──────────────
    hdr("STEP 5: CC 1.5 A — compare individual vs read_all()")
    load.CC_mode(1.5)
    load.on()
    time.sleep(1.2)
    v_all, i_all, p_all, r_all = load.read_all()
    v_ind = load.read_voltage()
    i_ind = load.read_current()
    p_ind = load.read_power()
    r_ind = load.read_resistance()
    print(f"    read_all()    : V={v_all:.4f}  I={i_all:.4f}  P={p_all:.4f}  R={r_all:.4f}")
    print(f"    individual    : V={v_ind:.4f}  I={i_ind:.4f}  P={p_ind:.4f}  R={r_ind:.4f}")
    chk("read_all V vs individual V", abs(v_all - v_ind), 0.0, 0.2, failures)
    chk("read_all I vs individual I", abs(i_all - i_ind), 0.0, 0.1, failures)
    load.off()
    time.sleep(0.5)

    # ── STEP 6: CR mode ──────────────────────────────────────────────────
    hdr("STEP 6: CR mode — 5 Ω  (~2.76 A @ 13.8 V)")
    load.CR_mode(5.0)
    time.sleep(0.1)
    load.on()
    time.sleep(1.2)
    v, i, p, r, pm = measure_both(psu, load)
    print(f"  CR_resistance readback: {load.CR_resistance:.3f} Ω")
    print(f"  Protection: {load.protection}")
    chk("CR setpoint readback",    load.CR_resistance, 4.9,  5.1,  failures)
    chk("CR measured resistance",  r,                  4.0,  6.5,  failures)
    chk("CR measured current",     i,                  2.0,  3.2,  failures)
    load.off()
    time.sleep(0.5)

    # ── STEP 7: CP mode ──────────────────────────────────────────────────
    hdr("STEP 7: CP mode — 20 W")
    load.CP_mode(20.0)
    time.sleep(0.1)
    load.on()
    time.sleep(1.2)
    v, i, p, r, pm = measure_both(psu, load)
    print(f"  CP_power readback: {load.CP_power:.3f} W")
    print(f"  Protection: {load.protection}")
    chk("CP setpoint readback", load.CP_power, 19.5, 20.5, failures)
    chk("CP measured power",    p,             16.0, 24.0, failures)
    load.off()
    time.sleep(0.5)

    # ── STEP 8: CV mode — above supply voltage (safe test) ───────────────
    hdr("STEP 8: CV mode — 14.5 V setpoint (above 13.8 V supply → load draws 0 A)")
    # With CV > supply voltage the terminal V is already below setpoint, so
    # the load draws no current.  This verifies CV mode round-trip without
    # triggering OCP.  Driving CV below supply voltage with a stiff PSU
    # would ramp current to OCP (expected behavior, not a bug).
    load.CV_mode(14.5)
    time.sleep(0.1)
    load.on()
    time.sleep(1.2)
    v, i, p, r, pm = measure_both(psu, load)
    print(f"  CV_voltage readback: {load.CV_voltage:.3f} V")
    print(f"  Protection: {load.protection}")
    chk("CV setpoint readback",       load.CV_voltage, 14.4, 14.6, failures)
    chk("CV current (should be ~0)",  i,               0.0,  0.15, failures)
    chk("CV PSU current (~0)",        pm["current_a"], 0.0,  0.10, failures)
    load.off()
    time.sleep(0.5)

    # ── STEP 9: State / query checks ─────────────────────────────────────
    hdr("STEP 9: State and query checks (load OFF)")
    load.CC_mode(1.0)
    print(f"  mode property   : {load.mode!r}")
    print(f"  input property  : {load.input!r}")
    print(f"  CC_current      : {load.CC_current:.3f} A")
    print(f"  OCP             : {load.OCP:.3f} A")
    print(f"  OPP             : {load.OPP:.3f} W")
    print(f"  protection      : {load.protection!r}")
    print(f"  fan             : {load.fan()!r}")

    # mode property round-trip
    load.mode = "CR"
    m = load.mode
    ok = (m == "CR")
    print(f"  mode setter CR  → getter: {m!r}  {'[PASS]' if ok else '[FAIL]'}")
    if not ok:
        failures.append(f"mode setter round-trip: set CR, got {m!r}")
    load.mode = "CC"

    # input property round-trip
    load.input = "ON"
    time.sleep(0.3)
    s = load.input
    ok = (s == "ON")
    print(f"  input setter ON → getter: {s!r}  {'[PASS]' if ok else '[FAIL]'}")
    if not ok:
        failures.append(f"input setter ON: got {s!r}")
    load.input = "OFF"
    time.sleep(0.2)

    # ── STEP 10: Cleanup ──────────────────────────────────────────────────
    hdr("STEP 10: Cleanup")
    load.off()
    load.close()
    psu.disable_all()
    psu.close()
    print("  Load OFF, PSU CH1 OFF, connections closed")

    # ── Summary ───────────────────────────────────────────────────────────
    hdr("SUMMARY")
    if failures:
        print(f"  FAILED — {len(failures)} issue(s):")
        for f in failures:
            print(f"    x  {f}")
        sys.exit(1)
    else:
        print("  ALL TESTS PASSED")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        hdr("FATAL ERROR")
        print(f"  {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
