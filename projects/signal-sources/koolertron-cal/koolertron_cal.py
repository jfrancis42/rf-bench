#!/usr/bin/env python3
"""
koolertron_cal.py — Calibrate the Koolertron / MHinstek MHS-5200A series DDS.

Uses a single Siglent SDS2504X Plus oscilloscope as both reference and
measurement instrument:

    amp-cal  Wiring: MHS CH1 → scope CH1 (input, 50 Ω termination)
             The scope's calibrated Vpp measurement gives the actual
             delivered amplitude at each cal frequency. No external pad
             required, no SSA dynamic-range limitations.

    freq-cal Wiring: scope AWG output → MHS EXT IN
             The scope's built-in arbitrary waveform generator drives
             the MHS frequency counter. The MHS reports the measured
             frequency; comparing against the commanded value yields
             the ppm offset. (The scope's AWG has its own TCXO at
             roughly ±2 ppm; for absolute frequency reference, use a
             GPS-disciplined source instead.)

Output: ~/.koolertron_mhs5200_cal.json — picked up automatically by
`rf_bench.koolertron.MHS5200A` at construction time. With no cal file
the driver still works using the unit's built-in (factory) calibration.

Usage::

    # Both calibrations in one run (with cable-swap prompt between them):
    python koolertron_cal.py both

    # Only amplitude calibration:
    python koolertron_cal.py amp-cal

    # Only frequency calibration:
    python koolertron_cal.py freq-cal

    # Only CH1 (skip CH2 cable swap):
    python koolertron_cal.py amp-cal --channels 1

    # Custom freq grid:
    python koolertron_cal.py amp-cal --freq-start 1e3 --freq-stop 1e7 --points 16
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

from rf_bench.koolertron import (
    MHS5200A, Waveform, Atten, Gate, CounterMode, DEFAULT_CAL_FILE,
)
from rf_bench.siglent import SDS2000X


# ---------------------------------------------------------------------------
# Bench defaults
# ---------------------------------------------------------------------------

DEFAULT_SCOPE_HOST   = "10.1.1.58"
DEFAULT_SDG_HOST     = "10.1.1.51"   # current bench address

DEFAULT_LEVELS_DBM   = "0.0"           # target level in dBm into 50 Ω
DEFAULT_FREQ_START   = 1_000.0          # 1 kHz — the scope works fine down here
DEFAULT_FREQ_STOP    = 25_000_000.0     # 25 MHz — top of MHS-5225A
DEFAULT_FREQ_POINTS  = 12

# MHS+scope settle time after frequency or amplitude change
SETTLE_S             = 0.4

# Frequency grid for freq-cal — small (each point takes ~5 s with the 1 s gate)
# The TCXO error is constant across all output frequencies (one master clock
# divider) so a single, reliable measurement at one frequency suffices. We
# use 10 MHz with a 10 s gate window — empirically that combination locks
# repeatably to within ~0.01 ppm spread across multiple trials. The 1 s
# gate is unreliable below ~10 MHz on this firmware.
DEFAULT_FREQ_CAL_GRID = "10e6"
COUNTER_SETTLE_GATES  = 2   # 2 gate periods (= 20 s with 10 s gate) is plenty
DEFAULT_FREQ_CAL_GATE = 10.0   # 10 s gate (Gate.S10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def vpp_50_to_dbm(vpp: float) -> float:
    if vpp <= 0:
        return float("-inf")
    return 10.0 * math.log10((vpp ** 2) / (8.0 * 50.0) * 1000.0)


def merge_cal(path: str, updates: dict) -> dict:
    """Load existing cal (if any), merge in updates, write back atomically."""
    cur: dict = {}
    if os.path.exists(path):
        try:
            with open(path) as fh:
                cur = json.load(fh) or {}
        except (OSError, ValueError) as e:
            print(f"  warning: existing cal {path!r} unreadable ({e}); starting fresh.")
            cur = {}

    for key, value in updates.items():
        if key == "amplitude" and isinstance(value, dict):
            cur.setdefault("amplitude", {}).update(value)
        else:
            cur[key] = value

    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cur, fh, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)
    return cur


def setup_scope_for_amp_cal(scope: SDS2000X) -> None:
    """Configure scope CH1 for 50 Ω amplitude measurements."""
    s = scope._sock
    s.sendall(b":CHANnel1:IMPedance FIFTy\n"); time.sleep(0.1)
    s.sendall(b":CHANnel1:SWITch ON\n"); time.sleep(0.1)
    s.sendall(b":TRIGger:EDGE:SOURce C1\n"); time.sleep(0.1)
    scope.run()
    time.sleep(0.3)


def restore_scope(scope: SDS2000X) -> None:
    """Return scope to safe defaults (1 MΩ input)."""
    try:
        scope._sock.sendall(b":CHANnel1:IMPedance ONEMeg\n")
        time.sleep(0.1)
    except Exception:
        pass


def measure_vpp_at_freq(scope: SDS2000X, freq_hz: float, target_vpp: float) -> float:
    """Set scope timebase appropriate for freq, autoscale vertical, return Vpp."""
    # 5 cycles per screen at 14 divisions visible -> 5/14 ≈ 0.36 cycles per div
    # period = 1/freq, so /div = period * 0.36
    s_per_div = max(1.0 / freq_hz * 0.36, 1e-9)
    scope._sock.sendall(f":TIMebase:SCALe {s_per_div:.3e}\n".encode())
    time.sleep(0.2)
    # Initial vertical scale guess: target_vpp/4 per div
    vdiv_init = max(target_vpp / 4.0, 0.005)
    scope._sock.sendall(f":CHANnel1:SCALe {vdiv_init:.4f}\n".encode())
    time.sleep(SETTLE_S)
    # Now let the driver autoscale further
    scope.autoscale_vdiv(1, target_divisions=4.0)
    time.sleep(0.4)
    return scope.measure_vpp(1)


# ---------------------------------------------------------------------------
# amp-cal
# ---------------------------------------------------------------------------

def cmd_amp_cal(args) -> int:
    levels_dbm = [float(x) for x in args.levels.split(",")]
    freqs_hz = np.geomspace(args.freq_start, args.freq_stop, args.points)
    channels = [int(c) for c in args.channels.split(",")]

    print(f"\n[amp-cal] target levels: {levels_dbm} dBm")
    print(f"          freq grid    : {freqs_hz[0]:g} → {freqs_hz[-1]:g} Hz "
          f"({args.points} log-spaced)")
    print(f"          channels     : {channels}")
    print(f"          scope        : {args.scope_host} (CH1, 50 Ω)")
    print(f"          MHS port     : auto-detect (or set --mhs-port)")

    print("\nWiring: MHS CHx → scope CH1 (no pad).")

    # Open MHS with calibration disabled so we measure the bare instrument
    print("\nOpening instruments...")
    mhs = MHS5200A(port=args.mhs_port, calibration=False)
    scope = SDS2000X(args.scope_host)
    print(f"  MHS  : {mhs.identify()}")
    print(f"  scope: {scope.identify()}")
    setup_scope_for_amp_cal(scope)

    amplitude_block: dict = {}

    try:
        for ch_idx, ch in enumerate(channels):
            if ch_idx > 0:
                print(f"\n  ⚠  CABLE SWAP: move scope CH1 input from MHS CH{channels[ch_idx-1]} "
                      f"to MHS CH{ch}, then press Enter.")
                if not args.no_prompt:
                    input("  > ")

            print(f"\n  --- CH{ch} sweep ---")
            mhs.set_waveform(ch, Waveform.SINE)
            mhs.set_attenuator(ch, Atten.ZERO_DB)
            for other in (1, 2):
                if other != ch:
                    mhs.set_amplitude(other, 0.0)
            mhs.output_on()

            rows = []
            for level_dbm in levels_dbm:
                # Convert target dBm to nominal Vpp into 50 Ω
                target_vpp = math.sqrt(10**(level_dbm/10.0) * 1e-3 * 8 * 50)
                for f in freqs_hz:
                    mhs.set_frequency(ch, float(f))
                    mhs.set_amplitude_dbm(ch, float(f), float(level_dbm))
                    time.sleep(SETTLE_S)
                    measured_vpp = measure_vpp_at_freq(scope, float(f), target_vpp)
                    measured_dbm = vpp_50_to_dbm(measured_vpp)
                    correction_db = float(level_dbm) - measured_dbm
                    cmd_vpp = mhs.get_amplitude(ch)
                    rows.append({
                        "freq_hz": float(f),
                        "commanded_dbm": float(level_dbm),
                        "commanded_v": float(cmd_vpp),
                        "measured_vpp": float(measured_vpp),
                        "measured_dbm": float(measured_dbm),
                        "correction_db": float(correction_db),
                    })
                    print(f"    {f:>12.0f} Hz  cmd {level_dbm:+5.1f} dBm "
                          f"({cmd_vpp:.3f} Vpp_50)  meas {measured_vpp:.3f} Vpp = "
                          f"{measured_dbm:+6.2f} dBm  corr {correction_db:+5.2f} dB")

            mhs.output_off()
            mhs.set_amplitude(ch, 0.0)
            amplitude_block[str(ch)] = rows

            corr_arr = np.array([r["correction_db"] for r in rows])
            print(f"  CH{ch} correction range: {corr_arr.min():+.2f} to {corr_arr.max():+.2f} dB "
                  f"(p-p {corr_arr.max() - corr_arr.min():.2f} dB)")

    finally:
        try:
            mhs.output_off()
        except Exception:
            pass
        mhs.close()
        restore_scope(scope)
        scope.close()

    cal = merge_cal(args.cal_file, {
        "instrument": "MHS-5200A",
        "raw_model": mhs.raw_model,
        "model": mhs.model,
        "calibrated_at": now_iso(),
        "scope_used": args.scope_host,
        "amplitude": amplitude_block,
    })
    print(f"\nWrote calibration to {args.cal_file}")
    print(f"  amplitude_channels: {sorted(int(k) for k in (cal.get('amplitude') or {}).keys())}")
    print(f"  freq_ppm_offset   : {cal.get('frequency_ppm_offset', 'not yet calibrated — run freq-cal')}")
    return 0


# ---------------------------------------------------------------------------
# freq-cal — uses the scope's AWG as the reference signal source
# ---------------------------------------------------------------------------

def cmd_freq_cal(args) -> int:
    grid = [float(x) for x in args.grid.split(",")]
    print(f"\n[freq-cal] grid (Hz): {grid}")
    print(f"           gate     : {args.gate} s, settle gates: {COUNTER_SETTLE_GATES}")

    if args.method == "self":
        print(f"           method   : self-loop (MHS CH1 drives MHS Ext.IN)")
        print(f"\nWiring: MHS CH1 → short BNC cable → MHS Ext.IN (front).")
        print("\nThis measures the MHS DDS-vs-counter offset (both share the same")
        print("master clock). No external instrument required.")
    elif args.method == "sdg":
        print(f"           SDG      : {args.sdg_host} (drives MHS EXT IN)")
        print(f"\nWiring: SDG CH1 → MHS EXT IN.")
    else:  # scope
        print(f"           scope    : {args.scope_host} AWG (drives MHS EXT IN)")
        print(f"\nWiring: scope AWG output (front 'Gen Out' BNC) → MHS EXT IN.")

    mhs = MHS5200A(port=args.mhs_port, calibration=False)
    print(f"\n  MHS: {mhs.identify()}")

    gate_enum = {1.0: Gate.S1, 10.0: Gate.S10, 0.1: Gate.S0_1, 0.01: Gate.S0_01}.get(args.gate)
    if gate_enum is None:
        print(f"  warning: gate={args.gate}s is non-standard; using S1.")
        gate_enum = Gate.S1

    sdg = None
    scope = None
    if args.method == "sdg":
        from rf_bench.siglent import SDG1000X
        sdg = SDG1000X(args.sdg_host)
        print(f"  SDG at {args.sdg_host}")
    elif args.method == "scope":
        scope = SDS2000X(args.scope_host)
        print(f"  scope: {scope.identify()}")
        scope.set_awg_load(50)

    rows = []
    try:
        # Set source amplitude once
        if args.method == "self":
            mhs.output_off()
            mhs.set_waveform(1, Waveform.SINE)
            mhs.set_amplitude(1, 2.5)
        elif sdg:
            sdg.output_off(1)
        elif scope:
            scope.awg_output_off()

        for freq in grid:
            if args.method == "self":
                mhs.set_frequency(1, float(freq))
                mhs.output_on()
            elif sdg:
                sdg.set_sine(1, float(freq), 13.0)
                sdg.output_on(1)
            elif scope:
                # 2.0 Vpp into 50 Ω = ~+10 dBm; well above counter threshold
                scope.set_awg_sine(freq_hz=float(freq), amplitude_vpp=2.0,
                                   offset_v=0.0)
            time.sleep(1.0)   # let source settle on new frequency

            # measure_frequency_hz polls until the counter stabilises rather
            # than waiting a fixed time. This handles the MHS counter's
            # 4-8 gate-cycle settle behaviour at any frequency.
            measured = mhs.measure_frequency_hz(
                gate=gate_enum, settle_gates=COUNTER_SETTLE_GATES,
                timeout_s=60.0,
            )
            err_ppm = (measured - freq) / freq * 1e6 if freq > 0 else 0.0
            rows.append({
                "commanded_hz": float(freq),
                "measured_hz": float(measured),
                "error_ppm": float(err_ppm),
            })
            print(f"    {freq:>12.0f} Hz   meas {measured:>14.1f} Hz   err {err_ppm:+.2f} ppm")

            if args.method == "self":
                mhs.output_off()
            elif sdg:
                sdg.output_off(1)
            elif scope:
                scope.awg_output_off()

        ppms = np.array([r["error_ppm"] for r in rows])
        median_ppm = float(np.median(ppms))
        mean_ppm = float(np.mean(ppms))
        std_ppm = float(np.std(ppms))
        print(f"\n  median {median_ppm:+.2f} ppm  |  mean {mean_ppm:+.2f} ppm  |  σ {std_ppm:.2f} ppm")
        print("  (median is the value the driver applies as the inverse correction)")

    finally:
        try:
            mhs.counter_stop()
        except Exception:
            pass
        try:
            mhs.output_off()
        except Exception:
            pass
        if sdg:
            try:
                sdg.output_off(1)
            except Exception:
                pass
            sdg.close()
        if scope:
            try:
                scope.awg_output_off()
            except Exception:
                pass
            scope.close()
        mhs.close()

    if args.method == "self":
        source_str = "MHS CH1 self-loop"
    elif args.method == "sdg":
        source_str = f"SDG1000X @ {args.sdg_host}"
    else:
        source_str = f"SDS2000X AWG @ {args.scope_host}"
    cal = merge_cal(args.cal_file, {
        "instrument": "MHS-5200A",
        "raw_model": mhs.raw_model,
        "model": mhs.model,
        "freq_calibrated_at": now_iso(),
        "frequency_ppm_offset": median_ppm,
        "freq_source": source_str,
        "freq_cal_grid": rows,
    })
    print(f"\nWrote calibration to {args.cal_file}")
    print(f"  frequency_ppm_offset: {cal.get('frequency_ppm_offset'):+.2f} ppm")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cal-file", default=DEFAULT_CAL_FILE,
                        help=f"Output JSON path (default: {DEFAULT_CAL_FILE})")
    common.add_argument("--mhs-port", default=None,
                        help="MHS-5200A serial port (default: auto-detect)")
    common.add_argument("--scope-host", default=DEFAULT_SCOPE_HOST)

    a = sub.add_parser("amp-cal", parents=[common],
                       help="Calibrate amplitude vs freq vs channel using the scope")
    a.add_argument("--levels", default=DEFAULT_LEVELS_DBM,
                   help="Comma-separated target levels in dBm into 50 Ω (e.g. '0' or '0,5,10')")
    a.add_argument("--freq-start", type=float, default=DEFAULT_FREQ_START)
    a.add_argument("--freq-stop", type=float, default=DEFAULT_FREQ_STOP)
    a.add_argument("--points", type=int, default=DEFAULT_FREQ_POINTS)
    a.add_argument("--channels", default="1,2",
                   help="Channels to calibrate, comma-separated (default '1,2'). "
                        "When more than one is given, the script will pause and "
                        "prompt for a cable swap between channels.")
    a.add_argument("--no-prompt", action="store_true",
                   help="Skip the cable-swap prompt")
    a.set_defaults(func=cmd_amp_cal)

    f = sub.add_parser("freq-cal", parents=[common],
                       help="Calibrate the MHS frequency reference")
    f.add_argument("--method", choices=("self", "sdg", "scope"), default="self",
                   help="Reference: 'self' (MHS CH1 → MHS Ext.IN, no external "
                        "instrument required); 'sdg' (Siglent SDG drives MHS "
                        "Ext.IN, uses SDG's TCXO as reference); 'scope' (Siglent "
                        "SDS2000X+ AWG drives MHS Ext.IN, uses scope's TCXO as "
                        "reference). Default: self.")
    f.add_argument("--sdg-host", default=DEFAULT_SDG_HOST,
                   help=f"SDG IP for --method sdg (default: {DEFAULT_SDG_HOST})")
    f.add_argument("--grid", default=DEFAULT_FREQ_CAL_GRID,
                   help=f"Comma-separated frequencies in Hz (default: {DEFAULT_FREQ_CAL_GRID})")
    f.add_argument("--gate", type=float, default=DEFAULT_FREQ_CAL_GATE,
                   help=f"Counter gate time in seconds: 10.0 (recommended, "
                        f"reliable from 10 kHz up) or 1.0 (faster but only "
                        f"reliable at ≥ 10 MHz on this firmware). "
                        f"Default: {DEFAULT_FREQ_CAL_GATE}")
    f.set_defaults(func=cmd_freq_cal)

    b = sub.add_parser("both", parents=[common],
                       help="Run amp-cal then freq-cal, in that order")
    b.add_argument("--method", choices=("self", "sdg", "scope"), default="self",
                   help="Frequency-cal reference (default: self)")
    b.add_argument("--sdg-host", default=DEFAULT_SDG_HOST)
    b.add_argument("--levels", default=DEFAULT_LEVELS_DBM)
    b.add_argument("--freq-start", type=float, default=DEFAULT_FREQ_START)
    b.add_argument("--freq-stop", type=float, default=DEFAULT_FREQ_STOP)
    b.add_argument("--points", type=int, default=DEFAULT_FREQ_POINTS)
    b.add_argument("--channels", default="1,2")
    b.add_argument("--no-prompt", action="store_true")
    b.add_argument("--grid", default=DEFAULT_FREQ_CAL_GRID)
    b.add_argument("--gate", type=float, default=DEFAULT_FREQ_CAL_GATE)
    def _both(args):
        rc = cmd_amp_cal(args)
        if rc != 0:
            return rc
        print("\n" + "─" * 60)
        print("  amp-cal complete. Move the cable now:")
        if args.method == "self":
            print("    From: MHS CHx → scope CH1 input")
            print("    To:   MHS CH1 → MHS Ext.IN (front, short BNC patch)")
        else:
            print("    From: MHS CHx → scope CH1 input")
            print("    To:   SDG CH1 → MHS Ext.IN")
        if not args.no_prompt:
            input("  Press Enter when ready... > ")
        return cmd_freq_cal(args)
    b.set_defaults(func=_both)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
