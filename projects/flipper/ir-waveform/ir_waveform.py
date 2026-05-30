#!/usr/bin/env python3
"""
Flipper Zero IR LED Waveform Analyzer

Captures Flipper IR LED output via a Si photodiode on the scope. Measures:
  - Carrier frequency (FFT peak)
  - Duty cycle
  - NEC/SIRC protocol timing accuracy
  - (--map-rx) Scope AWG drives reference LED at various frequencies to map receiver bandpass

Usage:
  python ir_waveform.py --test carrier --protocol NEC
  python ir_waveform.py --test timing  --protocol NEC
  python ir_waveform.py --test all
  python ir_waveform.py --map-rx --scope 10.1.1.58
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))
from rf_bench.flipper import FlipperZero
from rf_bench.siglent import SDS2000X

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SCOPE_HOST = "10.1.1.58"
DEFAULT_SERIAL     = "/dev/ttyACM0"
NEC_BURST_US       = 9000
NEC_SPACE_US       = 4500
NEC_BIT_ONE_US     = 1687
NEC_BIT_ZERO_US    = 563
SIRC_LEAD_US       = 2400
SIRC_BIT_ONE_US    = 1200
SIRC_BIT_ZERO_US   = 600

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def capture_waveform(scope: SDS2000X, channel: int = 1,
                     time_div_ms: float = 0.5) -> tuple:
    """Capture one waveform. Returns (times_us, voltages) arrays."""
    scope.set_timebase(time_div_ms * 1e-3)
    scope.single_trigger()
    time.sleep(time_div_ms * 12e-3 + 0.2)
    times, volts = scope.get_waveform(channel)
    return np.array(times) * 1e6, np.array(volts)  # convert to us, keep V


def measure_carrier_fft(times_us: np.ndarray, volts: np.ndarray) -> dict:
    """Measure carrier frequency and duty cycle from captured waveform."""
    dt = float(np.mean(np.diff(times_us))) * 1e-6  # seconds
    N  = len(volts)
    freqs = np.fft.rfftfreq(N, d=dt)
    fft   = np.abs(np.fft.rfft(volts))
    peak_idx = int(np.argmax(fft[1:])) + 1
    carrier_hz = float(freqs[peak_idx])

    # Duty cycle: fraction of time above mid-point
    threshold = (float(np.max(volts)) + float(np.min(volts))) / 2.0
    duty_cycle = float(np.mean(volts > threshold))

    return {"carrier_hz": carrier_hz, "duty_cycle": duty_cycle}


def measure_timing(times_us: np.ndarray, volts: np.ndarray,
                   protocol: str) -> dict:
    """Extract burst/space timings and compare against protocol spec."""
    threshold = (float(np.max(volts)) + float(np.min(volts))) / 2.0
    above = volts > threshold

    # Find edges
    edges = np.diff(above.astype(int))
    rising  = np.where(edges > 0)[0]
    falling = np.where(edges < 0)[0]

    if len(rising) < 2 or len(falling) < 2:
        return {"error": "insufficient edges"}

    bursts = []
    spaces = []
    for i in range(min(len(rising), len(falling))):
        if falling[i] > rising[i]:
            bursts.append(float(times_us[falling[i]] - times_us[rising[i]]))
        if i + 1 < len(rising) and rising[i + 1] > falling[i]:
            spaces.append(float(times_us[rising[i + 1]] - times_us[falling[i]]))

    result = {
        "n_bursts": len(bursts),
        "burst_mean_us": float(np.mean(bursts)) if bursts else 0,
        "space_mean_us": float(np.mean(spaces)) if spaces else 0,
    }

    if protocol == "NEC" and len(bursts) >= 1:
        result["lead_burst_us"]   = bursts[0]
        result["lead_burst_err%"] = 100.0 * (bursts[0] - NEC_BURST_US) / NEC_BURST_US
        if len(spaces) >= 1:
            result["lead_space_us"]   = spaces[0]
            result["lead_space_err%"] = 100.0 * (spaces[0] - NEC_SPACE_US) / NEC_SPACE_US

    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_carrier(fz: FlipperZero, scope: SDS2000X, protocol: str,
                 output_prefix: str) -> dict:
    """Transmit NEC address 0x07 command 0x02, capture and analyze carrier."""
    print(f"\n[CARRIER TEST]  protocol={protocol}")
    print("  Transmitting IR burst, capturing on scope CH1 ...")

    fz.ir_transmit(protocol, 0x07, 0x02)
    times, volts = capture_waveform(scope, channel=1, time_div_ms=0.1)

    result = measure_carrier_fft(times, volts)
    print(f"  Carrier      : {result['carrier_hz']/1e3:.2f} kHz")
    print(f"  Duty cycle   : {result['duty_cycle']*100:.1f}%")
    print(f"  Expected     : 38.0 kHz, 33%")

    # Plot
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6))
    ax1.plot(times, volts)
    ax1.set_xlabel("Time (us)")
    ax1.set_ylabel("Voltage (V)")
    ax1.set_title(f"IR Waveform — {protocol}")
    ax1.set_xlim(0, min(200, times[-1]))
    ax1.grid(True, alpha=0.4)

    dt = float(np.mean(np.diff(times))) * 1e-6
    N  = len(volts)
    freqs = np.fft.rfftfreq(N, d=dt) / 1e3
    fft   = np.abs(np.fft.rfft(volts))
    ax2.plot(freqs[:len(freqs)//4], fft[:len(freqs)//4])
    ax2.set_xlabel("Frequency (kHz)")
    ax2.set_ylabel("Amplitude")
    ax2.set_title("FFT — Carrier Frequency")
    ax2.axvline(38, color='red', linestyle='--', label='38 kHz')
    ax2.legend()
    ax2.grid(True, alpha=0.4)

    plt.tight_layout()
    path = f"{output_prefix}_carrier.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Plot -> {path}")
    return result


def test_timing(fz: FlipperZero, scope: SDS2000X, protocol: str,
                output_prefix: str) -> dict:
    """Capture a full burst packet and check timing accuracy."""
    print(f"\n[TIMING TEST]  protocol={protocol}")
    print("  Transmitting and capturing full packet ...")

    fz.ir_transmit(protocol, 0x07, 0x02)
    times, volts = capture_waveform(scope, channel=1, time_div_ms=5.0)
    result = measure_timing(times, volts, protocol)

    for k, v in result.items():
        if isinstance(v, float):
            print(f"  {k:>24}: {v:.2f}")
        else:
            print(f"  {k:>24}: {v}")
    return result


def map_rx_response(fz: FlipperZero, scope: SDS2000X,
                    start_khz: float, stop_khz: float, step_khz: float,
                    output_prefix: str) -> list:
    """Sweep AWG carrier frequency; Flipper attempts NEC decode at each freq."""
    print(f"\n[RX BANDPASS MAP]  {start_khz:.1f}-{stop_khz:.1f} kHz step {step_khz:.1f} kHz")
    print("  Scope AWG drives IR LED -> Flipper RX")

    freqs = np.arange(start_khz * 1e3, stop_khz * 1e3 + 1, step_khz * 1e3)
    results = []

    for freq_hz in freqs:
        if not _running:
            break
        # Configure AWG to drive IR LED at this carrier
        scope.set_awg_frequency(1, float(freq_hz))
        scope.set_awg_duty_cycle(1, 33.0)
        scope.awg_output_on(1)
        time.sleep(0.1)

        # Send a NEC burst via AWG-modulated LED; check if Flipper decodes
        decoded = fz.ir_receive(timeout_s=1.0)
        success = decoded is not None and decoded.get("protocol") not in (None, "Unknown")
        results.append({"freq_hz": float(freq_hz), "decode_success": success})
        mark = "OK" if success else "--"
        print(f"  {freq_hz/1e3:6.1f} kHz  {mark}", end='\r', flush=True)

    scope.awg_output_off(1)
    print()

    # Plot
    freqs_khz = [r["freq_hz"] / 1e3 for r in results]
    success   = [1 if r["decode_success"] else 0 for r in results]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(freqs_khz, success, width=step_khz * 0.8, color='steelblue')
    ax.set_xlabel("Carrier Frequency (kHz)")
    ax.set_ylabel("Decode Success")
    ax.set_title("Flipper IR RX Bandpass — Decode Success vs. Carrier Frequency")
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Fail", "Pass"])
    ax.grid(True, axis='x', alpha=0.4)
    path = f"{output_prefix}_rx_bandpass.png"
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Plot -> {path}")
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze Flipper IR LED waveform via oscilloscope",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ir_waveform.py --test carrier --protocol NEC
  python ir_waveform.py --test all
  python ir_waveform.py --map-rx
""",
    )
    parser.add_argument("--scope",    default=DEFAULT_SCOPE_HOST, metavar="HOST",
                        help=f"Scope IP address (default {DEFAULT_SCOPE_HOST})")
    parser.add_argument("--serial",   default=DEFAULT_SERIAL, metavar="PORT",
                        help=f"Flipper serial port (default {DEFAULT_SERIAL})")
    parser.add_argument("--test",     default="all",
                        choices=["carrier", "timing", "all"],
                        help="Test to run (default: all)")
    parser.add_argument("--protocol", default="NEC",
                        choices=["NEC", "SIRC"],
                        help="IR protocol (default: NEC)")
    parser.add_argument("--map-rx",   action="store_true",
                        help="Map RX receiver bandpass using scope AWG")
    parser.add_argument("--output",   default=None, metavar="PREFIX",
                        help="Output filename prefix")

    args = parser.parse_args()
    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"ir_waveform_{ts}"

    try:
        print(f"Connecting to Flipper @ {args.serial} ...")
        fz = FlipperZero(args.serial)
        print(f"  {fz.identify()}")

        print(f"Connecting to scope @ {args.scope} ...")
        scope = SDS2000X(args.scope)
        print(f"  {scope.identify()}")

        run_all = args.test == "all"
        if _running and (run_all or args.test == "carrier"):
            test_carrier(fz, scope, args.protocol, args.output)
        if _running and (run_all or args.test == "timing"):
            test_timing(fz, scope, args.protocol, args.output)
        if _running and args.map_rx:
            map_rx_response(fz, scope, 30, 60, 0.5, args.output)

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        print(f"\nError: {exc}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
