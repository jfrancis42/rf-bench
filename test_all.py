#!/usr/bin/env python3
"""Comprehensive live test of all five Siglent drivers."""

import sys, os, time, math, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rf_bench.siglent import SDG1000X, SDS2000X, SDM3000X, SPD3303X, SSA3000X

PASS = "✓"
FAIL = "✗"

def ok(label, value=""):
    print(f"  {PASS} {label}" + (f" → {value}" if value != "" else ""))

# ─── SDG1062X ────────────────────────────────────────────────────────────────
print("\n=== SDG1062X (10.1.1.55) ===")
sdg = SDG1000X("10.1.1.55")
ok("identify", sdg.identify())

sdg.set_sine(1, 1000, -10.0)
sdg.output_on(1)
time.sleep(0.2)
ok("set_sine(1, 1000 Hz, -10 dBm) + output_on")

sdg.set_sine(2, 5000, -20.0)
sdg.output_on(2)
time.sleep(0.2)
ok("set_sine(2, 5000 Hz, -20 dBm) + output_on")

state = sdg.query_output_state(1)
ok(f"query_output_state(1)", state)
assert state is True

ch1 = sdg.query_channel(1)
ok(f"query_channel(1)", ch1)
assert abs(ch1['freq_hz'] - 1000.0) < 1.0, f"freq wrong: {ch1['freq_hz']}"
assert abs(ch1['amp_dbm'] - (-10.0)) < 0.5, f"level wrong: {ch1['amp_dbm']}"

sdg.set_frequency(1, 2000)
ch1b = sdg.query_channel(1)
ok(f"set_frequency(1, 2000) → re-query", f"freq={ch1b['freq_hz']:.0f} Hz")
assert abs(ch1b['freq_hz'] - 2000.0) < 1.0, f"freq not updated: {ch1b['freq_hz']}"

sdg.set_level(1, -20.0)
ok("set_level(1, -20 dBm)")

# Restore CH1 to 1 kHz, -10 dBm for scope tests below
sdg.set_sine(1, 1000, -10.0)
sdg.output_on(1)
time.sleep(0.2)
ok("restore CH1 to 1 kHz, -10 dBm")
print("  SDG: ALL PASS")

# ─── SDS2504X Plus ───────────────────────────────────────────────────────────
print("\n=== SDS2504X Plus (10.1.1.58) — CH1 = 1 kHz, -10 dBm ===")
# NOTE: SDG is still open and CH1 is outputting 1 kHz at -10 dBm
scope = SDS2000X("10.1.1.58")
ok("identify", scope.identify())

print("  --- capture round 1 (-10 dBm) ---")
volts1, sr1 = scope.capture_audio(channel=1, duration_s=1.0)
ok(f"capture_audio → {len(volts1):,} samples @ {sr1/1e6:.2f} MHz")
assert len(volts1) >= 1_000_000, f"too few samples: {len(volts1)}"

fft1 = np.abs(np.fft.rfft(volts1))
freqs1 = np.fft.rfftfreq(len(volts1), 1.0/sr1)
peak_idx1 = np.argmax(fft1)
peak_freq1 = freqs1[peak_idx1]
peak_amp1 = float(np.percentile(np.abs(volts1), 99))
ok(f"FFT peak frequency", f"{peak_freq1:.1f} Hz")
ok(f"Peak amplitude", f"{peak_amp1*1000:.1f} mVpk")
assert abs(peak_freq1 - 1000.0) < 5.0, f"FFT peak wrong: {peak_freq1:.1f} Hz (expected ~1000 Hz)"

print("  --- PAVA measurements (CH1 = 1 kHz, -10 dBm) ---")
rms1 = scope.measure_rms(1)
vpp1 = scope.measure_vpp(1)
freq1 = scope.measure_freq(1)
ok(f"measure_rms(1)", f"{rms1*1000:.1f} mVrms")
ok(f"measure_vpp(1)", f"{vpp1*1000:.1f} mVpp")
ok(f"measure_freq(1)", f"{freq1:.1f} Hz")
assert abs(freq1 - 1000.0) < 10.0, f"PAVA freq wrong: {freq1:.1f} Hz"

print("  --- PAVA measurements (CH2 = 5 kHz, -20 dBm) ---")
volts_ch2, sr_ch2 = scope.capture_audio(channel=2, duration_s=1.0)
ok(f"capture_audio(CH2) → {len(volts_ch2):,} samples @ {sr_ch2/1e6:.2f} MHz")
assert len(volts_ch2) >= 1_000_000, f"too few samples: {len(volts_ch2)}"

rms2 = scope.measure_rms(2)
vpp2 = scope.measure_vpp(2)
freq2 = scope.measure_freq(2)
ok(f"measure_rms(2)", f"{rms2*1000:.1f} mVrms")
ok(f"measure_vpp(2)", f"{vpp2*1000:.1f} mVpp")
ok(f"measure_freq(2)", f"{freq2:.1f} Hz")
assert abs(freq2 - 5000.0) < 50.0, f"PAVA freq wrong on CH2: {freq2:.1f} Hz"

print("  --- capture round 2 (-20 dBm) ---")
sdg.set_level(1, -20.0)
time.sleep(0.3)

volts2, sr2 = scope.capture_audio(channel=1, duration_s=1.0)
ok(f"capture_audio (-20 dBm) → {len(volts2):,} samples @ {sr2/1e6:.2f} MHz")
assert len(volts2) >= 1_000_000, f"too few samples: {len(volts2)}"

peak_amp2 = float(np.percentile(np.abs(volts2), 99))
ok(f"Peak amplitude (-20 dBm)", f"{peak_amp2*1000:.1f} mVpk")

ratio_db = 20.0 * math.log10(peak_amp1 / peak_amp2) if peak_amp2 > 0 else float('nan')
ok(f"Level ratio (-10 vs -20 dBm)", f"{ratio_db:.1f} dB (expected 10.0 dB)")
assert abs(ratio_db - 10.0) < 1.0, f"wrong ratio: {ratio_db:.2f} dB"

print("  --- AWG (built-in function generator) → CH4 ---")
scope.set_awg_sine(freq_hz=5000.0, amplitude_vpp=1.0)
time.sleep(0.3)
ok("set_awg_sine(5000 Hz, 1.0 Vpp)")

awg_state = scope.get_awg_state()
ok("get_awg_state()", awg_state)
assert awg_state["output_on"] is True, f"AWG not on: {awg_state}"
assert abs(awg_state["freq_hz"] - 5000.0) < 1.0, f"AWG freq wrong: {awg_state['freq_hz']}"
assert abs(awg_state["amplitude_vpp"] - 1.0) < 0.05, f"AWG amp wrong: {awg_state['amplitude_vpp']}"

volts_awg, sr_awg = scope.capture_audio(channel=4, duration_s=0.5)
ok(f"capture_audio(CH4) → {len(volts_awg):,} samples @ {sr_awg/1e6:.2f} MHz")
assert len(volts_awg) >= 500_000, f"too few samples: {len(volts_awg)}"

fft_awg = np.abs(np.fft.rfft(volts_awg))
freqs_awg = np.fft.rfftfreq(len(volts_awg), 1.0/sr_awg)
peak_freq_awg = freqs_awg[np.argmax(fft_awg)]
peak_amp_awg = float(np.percentile(np.abs(volts_awg), 99))
ok(f"AWG FFT peak frequency", f"{peak_freq_awg:.1f} Hz")
ok(f"AWG peak amplitude", f"{peak_amp_awg*1000:.1f} mVpk")
assert abs(peak_freq_awg - 5000.0) < 10.0, f"AWG FFT peak wrong: {peak_freq_awg:.1f} Hz"

scope.awg_output_off()
ok("awg_output_off()")

scope.close()
print("  SDS: ALL PASS")

# Done with scope tests — now restore and close SDG
sdg.set_level(1, -10.0)
sdg.close()

# ─── SDM3045X ────────────────────────────────────────────────────────────────
print("\n=== SDM3045X (10.1.1.63) — DMM probe on PSU CH1 output ===")
psu_for_dmm = SPD3303X("10.1.1.56")
psu_for_dmm.set_voltage(1, 5.0)
psu_for_dmm.set_current(1, 0.5)
psu_for_dmm.enable(1)
time.sleep(0.5)

dmm = SDM3000X("10.1.1.63")
ok("identify", dmm.identify())

vdc = dmm.measure_vdc()
ok(f"measure_vdc", f"{vdc:.4f} V")
assert abs(vdc - 5.0) < 0.1, f"voltage wrong: {vdc}"

stats = dmm.measure_stats(20)
ok(f"measure_stats(20)", f"mean={stats['mean']:.6f} V, stdev={stats['stdev']*1e6:.1f} µV")
assert stats['mean'] is not None

dmm.configure_vdc(range_v=5)
samples = dmm.read_multiple(20, settle_s=0.05)
ok(f"read_multiple(20)", f"mean={np.mean(samples):.4f} V, std={np.std(samples)*1e6:.1f} µV")

psu_for_dmm.close()
dmm.close()
print("  SDM: ALL PASS")

# ─── SPD3303X-E ──────────────────────────────────────────────────────────────
print("\n=== SPD3303X-E (10.1.1.56) ===")
psu = SPD3303X("10.1.1.56")
ok("identify", psu.identify())

psu.set_voltage(1, 5.0)
psu.set_current(1, 0.5)
psu.enable(1)
time.sleep(0.3)
v = psu.measure_voltage(1)
ok(f"set 5.0 V + enable + measure", f"{v:.4f} V")
assert abs(v - 5.0) < 0.1, f"voltage wrong: {v}"

psu.set_voltage(1, 3.3)
psu.wait_settled(1, timeout_s=5.0)
v2 = psu.measure_voltage(1)
ok(f"set_voltage(3.3) + wait_settled", f"{v2:.4f} V")
assert abs(v2 - 3.3) < 0.05, f"voltage wrong: {v2}"

psu.ramp_voltage(1, 5.0, step_v=0.2, delay_s=0.05)
time.sleep(0.2)
v3 = psu.measure_voltage(1)
ok(f"ramp_voltage(5.0)", f"{v3:.4f} V")
assert abs(v3 - 5.0) < 0.1, f"voltage wrong after ramp: {v3}"

enabled = psu.is_enabled(1)
ok(f"is_enabled(1)", enabled)
assert enabled is True

status = psu.get_status()
ok(f"get_status()", status)
assert status['ch1_on'] is True, f"ch1_on not True: {status}"

psu.disable_all()
ok("disable_all")

psu.close()
print("  SPD: ALL PASS")

# ─── SSA3032X Plus ───────────────────────────────────────────────────────────
print("\n=== SSA3032X Plus (10.1.1.60) ===")
ssa = SSA3000X("10.1.1.60")
ok("identify", ssa.identify())

ok("enable_tracking_generator(0)", ssa.enable_tracking_generator(0))

rbw = ssa.setup_band(900_000_000, 950_000_000, points=1001)
actual_pts = ssa.get_sweep_points()
ok(f"setup_band(900–950 MHz)", f"RBW = {rbw/1000:.0f} kHz, {actual_pts} points")

ok("single_sweep", ssa.single_sweep())

trace = ssa.get_trace()
ok(f"get_trace()", f"{len(trace)} points, min={trace.min():.1f} dBm, max={trace.max():.1f} dBm")
assert len(trace) == actual_pts, f"trace length {len(trace)} != queried points {actual_pts}"
assert len(trace) >= 100, f"too few trace points: {len(trace)}"

peak_freq, peak_dbm = ssa.get_peak()
ok(f"get_peak()", f"{peak_freq/1e6:.3f} MHz, {peak_dbm:.1f} dBm")

ssa.set_ref_level(0)
ok("set_ref_level(0)")

ssa.set_input_attenuation(10)
ok("set_input_attenuation(10)")

ssa.enable_averaging(10)
ok("enable_averaging(10)")

ssa.disable_averaging()
ok("disable_averaging()")

ssa.disable_tracking_generator()
ok("disable_tracking_generator()")

ssa.continuous_sweep()
ok("continuous_sweep()")

ssa.close()
print("  SSA: ALL PASS")

print("\n=== ALL INSTRUMENTS PASS ===\n")
