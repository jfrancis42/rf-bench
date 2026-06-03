#!/usr/bin/env python3
"""
Inrush Current Capture — SPD3303X + SDS2000X

Captures inrush current transient when a DUT powers on.  SPD3303X enables
the output; scope CH1 captures voltage across a sense resistor → I = V/R.
Computes peak inrush current, duration above 10% of peak, and I²t integral.
Repeat mode overlays N captures.

Usage:
  python inrush.py --voltage 5.0 --captures 1 --plot inrush.png
  python inrush.py --voltage 12.0 --sense-ohm 0.01 --captures 5 --plot overlay.png
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))

from rf_bench.siglent import SDS2000X, SPD3303X  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PSU_HOST   = "10.1.1.56"
DEFAULT_SCOPE_HOST = "10.1.1.58"
DEFAULT_CHANNEL    = 1
DEFAULT_SENSE_OHM  = 0.1
DEFAULT_CAPTURES   = 1
CAPTURE_WINDOW_S   = 0.05   # 50 ms capture window
PSU_CH             = 1

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C received — stopping ...]")


signal.signal(signal.SIGINT, _sigint_handler)

# ---------------------------------------------------------------------------
# Inrush analysis
# ---------------------------------------------------------------------------

def analyse_inrush(t: np.ndarray, i: np.ndarray) -> dict:
    """
    Compute inrush metrics from a current waveform.
    Returns: peak_a, peak_t_s, duration_s, i2t_a2s.
    """
    peak_a   = float(np.max(i))
    peak_idx = int(np.argmax(i))
    peak_t_s = float(t[peak_idx])

    threshold_10pct = 0.1 * peak_a
    above = i > threshold_10pct
    if np.any(above):
        first_above = int(np.argmax(above))
        last_above  = int(len(above) - 1 - np.argmax(above[::-1]))
        duration_s  = float(t[last_above] - t[first_above])
    else:
        duration_s = 0.0

    i2t = float(np.trapz(i ** 2, t))

    return {
        'peak_a':     peak_a,
        'peak_t_s':   peak_t_s,
        'duration_s': duration_s,
        'i2t_a2s':    i2t,
    }


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def save_plot(captures: list, metrics: list, sense_ohm: float,
              voltage_v: float, output_path: str) -> None:
    """Plot overlay of all inrush current captures."""
    fig, ax = plt.subplots(figsize=(10, 5))

    for idx, (t, i) in enumerate(captures):
        t_ms  = t * 1000.0
        alpha = max(0.2, 1.0 / len(captures))
        label = f"Run {idx+1}" if len(captures) <= 5 else None
        ax.plot(t_ms, i, linewidth=1, alpha=alpha, label=label)

    mean_peak = float(np.mean([m['peak_a'] for m in metrics]))
    ax.axhline(mean_peak, color='cyan', linewidth=0.8, linestyle='--',
               label=f"Mean peak: {mean_peak:.2f} A")
    ax.axhline(0.1 * mean_peak, color='yellow', linewidth=0.6, linestyle=':',
               label="10% threshold")

    mean_dur_ms = float(np.mean([m['duration_s'] for m in metrics])) * 1000.0
    mean_i2t    = float(np.mean([m['i2t_a2s'] for m in metrics]))

    ax.set_xlabel("Time (ms)", fontsize=10)
    ax.set_ylabel("Current (A)", fontsize=10)
    ax.set_title(
        f"Inrush Current — {voltage_v:.1f} V supply  "
        f"R_sense={sense_ohm:.4f} Ω  N={len(captures)}\n"
        f"Peak: {mean_peak:.3f} A   "
        f"Duration: {mean_dur_ms:.2f} ms   "
        f"I²t: {mean_i2t*1000:.4f} A²·ms",
        fontsize=10,
    )
    if len(captures) <= 5:
        ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Inrush current capture — SPD3303X + SDS2000X",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup:
  Insert a low-value sense resistor (0.1Ω) in series with DUT supply return.
  Connect scope CH1 across the sense resistor (+ toward supply, - toward GND).
  I = V_sense / R_sense.

Examples:
  python inrush.py --voltage 5.0
  python inrush.py --voltage 12.0 --sense-ohm 0.01 --captures 10 --plot inrush.png
""",
    )
    parser.add_argument("--psu",       default=DEFAULT_PSU_HOST, metavar="HOST",
                        help=f"SPD3303X IP address (default {DEFAULT_PSU_HOST})")
    parser.add_argument("--scope",     default=DEFAULT_SCOPE_HOST, metavar="HOST",
                        help=f"SDS2000X IP address (default {DEFAULT_SCOPE_HOST})")
    parser.add_argument("--channel",   type=int, default=DEFAULT_CHANNEL, metavar="N",
                        help=f"Scope channel for sense voltage (default {DEFAULT_CHANNEL})")
    parser.add_argument("--sense-ohm", type=float, default=DEFAULT_SENSE_OHM, metavar="R",
                        help=f"Sense resistor in Ω (default {DEFAULT_SENSE_OHM})")
    parser.add_argument("--voltage",   type=float, required=True, metavar="V",
                        help="DUT supply voltage (required)")
    parser.add_argument("--captures",  type=int, default=DEFAULT_CAPTURES, metavar="N",
                        help=f"Number of captures (default {DEFAULT_CAPTURES})")
    parser.add_argument("--plot",      default=None, metavar="FILE",
                        help="Output PNG path (default: timestamped)")

    args = parser.parse_args()

    trigger_v = args.sense_ohm * 0.01   # trigger at ~10 mA

    if args.plot is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.plot = f"inrush_{ts}_{args.voltage:.1f}V.png"

    psu = scope = None
    try:
        print(f"Connecting to SPD3303X @ {args.psu} ...")
        psu = SPD3303X(args.psu)
        print(f"  {psu.identify()}")

        print(f"Connecting to SDS2000X @ {args.scope} ...")
        scope = SDS2000X(args.scope)
        print(f"  {scope.identify()}")

        psu.output_off(PSU_CH)
        psu.set_voltage(PSU_CH, args.voltage)
        psu.set_current(PSU_CH, 5.0)   # 5A to capture full inrush

        timebase_s = CAPTURE_WINDOW_S / 10.0
        scope.set_timebase(timebase_s)
        scope.set_trigger_edge(f"C{args.channel}", trigger_v, slope='rising')

        print(f"\n  Voltage  : {args.voltage:.2f} V")
        print(f"  Sense R  : {args.sense_ohm:.4f} Ω")
        print(f"  Trigger  : {trigger_v*1000:.3f} mV (≈ 10 mA)")
        print(f"  Captures : {args.captures}")
        print(f"  Output   : {args.plot}")

        all_captures: list = []
        all_metrics:  list = []

        for n in range(1, args.captures + 1):
            if not _running:
                break

            print(f"\n  Capture {n}/{args.captures} — arming scope ...", end='', flush=True)
            scope.arm_trigger()
            psu.output_on(PSU_CH)

            t_arm = time.time()
            triggered = False
            while _running:
                status = scope.get_trigger_status()
                if status in ('STOP', 'TD'):
                    triggered = True
                    break
                if time.time() - t_arm > 5.0:
                    break
                time.sleep(0.02)

            if not triggered:
                print(" [no trigger — skipping]")
                psu.output_off(PSU_CH)
                continue

            wave, sr = scope.capture_waveform(args.channel)
            t_arr = np.arange(len(wave)) / sr
            i_arr = wave / args.sense_ohm

            m = analyse_inrush(t_arr, i_arr)
            all_captures.append((t_arr, i_arr))
            all_metrics.append(m)

            print(f" done  peak={m['peak_a']:.3f} A  "
                  f"dur={m['duration_s']*1000:.2f} ms  "
                  f"I2t={m['i2t_a2s']*1000:.4f} A2ms")

            psu.output_off(PSU_CH)
            if n < args.captures:
                time.sleep(2.0)   # allow DUT caps to discharge

        if all_captures:
            save_plot(all_captures, all_metrics, args.sense_ohm, args.voltage, args.plot)
            print(f"\n  Plot saved → {args.plot}")
        else:
            print("\n  No captures recorded.")

    except ConnectionRefusedError as exc:
        print(f"\nCannot connect: {exc}")
        sys.exit(1)
    except OSError as exc:
        print(f"\nNetwork error: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        if psu is not None:
            try:
                psu.output_off(PSU_CH)
            except Exception:
                pass
        for inst in (psu, scope):
            if inst is not None:
                try:
                    inst.disconnect()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
