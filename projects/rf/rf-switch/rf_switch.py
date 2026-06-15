#!/usr/bin/env python3
"""
RF Switch Characterizer

Programs a digital RF switch (PE43602, HMC307) via Bus Pirate SPI.
Measures insertion loss and port isolation at each state using SSA tracking gen.
Produces pass/fail against user-specified limits.

Usage:
    python rf_switch.py --ssa 10.1.1.60 --bp /dev/ttyUSB1 --chip PE43602
    python rf_switch.py --ssa 10.1.1.60 --bp /dev/ttyUSB1 --max-loss 1 --min-iso 40
"""

import argparse
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.siglent import SSA3000X
from rf_bench.buspirate import BusPirate
from rf_bench.utils import format_freq
from rf_bench import connect

DEFAULT_SSA    = "10.1.1.60"
DEFAULT_BP     = "/dev/ttyUSB1"
TEST_FREQS_HZ  = [1e6, 10e6, 50e6, 100e6, 500e6, 1e9]

# Chip SPI word builders
CHIP_WORDS = {
    "PE43602": lambda state: [(state & 0x7F) | 0x00],  # 7-bit attenuation code
    "HMC307":  lambda state: [state & 0x07],            # 3-bit state
    "RFSA3013": lambda state: [(state & 0x7F) | 0x00],
}


def measure_power(ssa, freq_hz):
    """Measure peak power at freq_hz using SSA in narrow-span mode."""
    span = 2_000_000
    ssa.setup_band(freq_hz - span // 2, freq_hz + span // 2)
    ssa.single_sweep()
    trace  = ssa.get_trace()
    return float(np.max(trace))


def main():
    ap = argparse.ArgumentParser(description="RF switch characterizer")
    ap.add_argument("--ssa",       default=DEFAULT_SSA)
    ap.add_argument("--bp",        default=DEFAULT_BP, help="Bus Pirate port")
    ap.add_argument("--chip",      default="PE43602", choices=list(CHIP_WORDS.keys()))
    ap.add_argument("--states",    type=int, default=2,
                    help="Number of switch states to test (default 2)")
    ap.add_argument("--freqs",     default="1,10,100,500,1000",
                    help="Comma-sep test frequencies in MHz")
    ap.add_argument("--max-loss",  type=float, default=2.0,
                    help="Max insertion loss dB (pass criterion)")
    ap.add_argument("--min-iso",   type=float, default=30.0,
                    help="Min isolation dB (pass criterion)")
    ap.add_argument("--plot",      metavar="FILE", default="rf_switch.png")
    args = ap.parse_args()

    freqs_hz = [float(f) * 1e6 for f in args.freqs.split(",")]
    word_fn  = CHIP_WORDS[args.chip]

    print(f"RF Switch: {args.chip}  {args.states} states  "
          f"freqs: {args.freqs} MHz")
    print(f"Pass criteria: loss ≤ {args.max_loss} dB, isolation ≥ {args.min_iso} dB\n")

    results = {}   # state → {freq_hz: (insertion_loss_db, isolation_db)}

    with SSA3000X(args.ssa) as ssa, BusPirate(args.bp) as bp:
        bp.spi_configure(speed_hz=1_000_000, cpol=0, cpha=0)

        # Reference: through path (state 0, switch "on")
        print("Measuring reference (through)...")
        bp.spi_write(word_fn(0))
        time.sleep(0.1)
        ssa.enable_tracking_generator(dbm=0)
        ref_levels = {}
        for f_hz in freqs_hz:
            ref_levels[f_hz] = measure_power(ssa, f_hz)
            print(f"  {format_freq(f_hz)}: {ref_levels[f_hz]:.1f} dBm (ref)")

        print()
        for state in range(args.states):
            print(f"State {state}:")
            bp.spi_write(word_fn(state))
            time.sleep(0.1)
            state_results = {}
            for f_hz in freqs_hz:
                p_on  = measure_power(ssa, f_hz)
                ins_loss = ref_levels[f_hz] - p_on

                # Measure isolation: switch to complement state
                comp_state = 1 - state if args.states == 2 else (state + 1) % args.states
                bp.spi_write(word_fn(comp_state))
                time.sleep(0.05)
                p_off  = measure_power(ssa, f_hz)
                iso    = p_on - p_off
                bp.spi_write(word_fn(state))
                time.sleep(0.05)

                state_results[f_hz] = (ins_loss, iso)
                ok_loss = ins_loss <= args.max_loss
                ok_iso  = iso >= args.min_iso
                status  = "PASS" if (ok_loss and ok_iso) else "FAIL"
                print(f"  {format_freq(f_hz):12s}  loss={ins_loss:5.1f} dB  "
                      f"iso={iso:5.1f} dB  [{status}]")
            results[state] = state_results

        ssa.disable_tracking_generator()
        bp.spi_exit()

    # Plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    for state, sr in results.items():
        f = [x/1e6 for x in sr]
        ax1.semilogx(f, [sr[x][0] for x in sr], label=f"State {state}")
        ax2.semilogx(f, [sr[x][1] for x in sr], label=f"State {state}")
    ax1.axhline(args.max_loss, color="red", linestyle="--", label="Pass limit")
    ax1.set_xlabel("Freq (MHz)"); ax1.set_ylabel("Insertion Loss (dB)")
    ax1.set_title(f"{args.chip} Insertion Loss"); ax1.legend(); ax1.grid(True)
    ax2.axhline(args.min_iso, color="red", linestyle="--", label="Pass limit")
    ax2.set_xlabel("Freq (MHz)"); ax2.set_ylabel("Isolation (dB)")
    ax2.set_title(f"{args.chip} Isolation"); ax2.legend(); ax2.grid(True)
    plt.tight_layout()
    plt.savefig(args.plot, dpi=150)
    print(f"\nPlot saved: {args.plot}")


if __name__ == "__main__":
    main()
