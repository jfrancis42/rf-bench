#!/usr/bin/env python3
"""
Phase Noise Measurement — Siglent SSA3000X (zero-span technique)

Measures single-sideband (SSB) phase noise L(f) in dBc/Hz at each specified
offset frequency.  Uses the SSA in zero-span mode to measure the noise floor
at each offset, then normalises to the carrier power and RBW.

Source options:
  --source sdg   Use SDG1000X as the carrier source (default)
  --source ext   Use an external source already connected to the SSA RF input

Connection (SDG mode):
    SDG CH1 OUT → SSA RF In

Connection (external source mode):
    External oscillator / radio TX → SSA RF In
    (Use appropriate attenuation to keep carrier well within SSA input range;
     −10 to −20 dBm at the SSA input is ideal for phase noise work.)

Usage:
    python phase_noise.py --freq 14000
    python phase_noise.py --freq 10000 --source sdg --carrier-level -10
    python phase_noise.py --freq 28000 --offsets 10,30,100,300,1000,3000,10000,100000
    python phase_noise.py --freq 14000 --averages 10
"""

import argparse
import json
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.siglent import SSA3000X, SDG1000X                            # noqa: E402
from rf_bench.utils import (                                                # noqa: E402
    format_freq, format_freq_short, nearest_rbw, phase_noise_dbchz,
)
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SSA_HOST   = None  # Now uses inventory
DEFAULT_SDG_HOST   = None  # Now uses inventory
DEFAULT_INSTRUMENT_PORT = 5025
DEFAULT_FREQ_KHZ   = 10_000.0     # kHz → 10 MHz
DEFAULT_CARRIER_DBM = -10.0       # SDG output level for source=sdg
DEFAULT_AVERAGES   = 5
DEFAULT_OFFSETS_HZ = [10, 30, 100, 300, 1_000, 3_000,
                      10_000, 30_000, 100_000, 300_000, 1_000_000]

# Carrier measurement: wide span to capture the peak cleanly
CARRIER_SPAN_HZ  = 100_000     # 100 kHz span for carrier measurement
CARRIER_RBW_HZ   = 30_000      # 30 kHz RBW for carrier power measurement
CARRIER_POINTS   = 201

# Zero-span: after measurement, restore to this span so the display is sane
RESTORE_SPAN_HZ  = 100_000


# ---------------------------------------------------------------------------
# RBW selection for noise measurement
# ---------------------------------------------------------------------------

def _noise_rbw(offset_hz: float, rbw_override: int | None) -> int:
    """
    Choose an appropriate RBW for measuring noise at the given offset.

    Auto selection: RBW ≈ 30% of offset, clamped to [10, 10000] Hz and
    snapped to a Siglent 1-3-10 series value.
    """
    if rbw_override is not None:
        return rbw_override
    target = max(10.0, min(10_000.0, offset_hz * 0.3))
    return nearest_rbw(target)


# ---------------------------------------------------------------------------
# Carrier power measurement
# ---------------------------------------------------------------------------

def measure_carrier(ssa: SSA3000X, carrier_hz: float) -> float:
    """
    Measure the carrier level at the SSA input (dBm).

    Configures a 100 kHz span around the carrier, runs a single sweep,
    and returns the peak value.
    """
    start_hz = max(9_000, int(carrier_hz - CARRIER_SPAN_HZ / 2))
    stop_hz  = int(carrier_hz + CARRIER_SPAN_HZ / 2)
    ssa.setup_band(start_hz, stop_hz, CARRIER_POINTS)

    # Override RBW to 30 kHz for a clean carrier peak
    ssa._send(f":SENS:BAND:RES {CARRIER_RBW_HZ}")
    ssa._send(f":SENS:BAND:VID {CARRIER_RBW_HZ}")

    ssa.single_sweep()
    trace = ssa.get_trace()
    return float(np.max(trace))


# ---------------------------------------------------------------------------
# Zero-span noise measurement — see run_phase_noise() for the main measurement loop.
# This helper is kept for standalone use / unit testing.


# ---------------------------------------------------------------------------
# Restore SSA to a sensible state after zero-span
# ---------------------------------------------------------------------------

def restore_ssa(ssa: SSA3000X, carrier_hz: float) -> None:
    """Restore SSA from zero-span back to a normal continuous sweep."""
    try:
        ssa._send(f":FREQ:CENT {int(carrier_hz)}")
        ssa._send(f":FREQ:SPAN {RESTORE_SPAN_HZ}")
        ssa._send(":TRAC:TYPE WRIT")
        ssa._send(":INIT:CONT ON")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The query helper needed for zero-span OPC wait when averaging
# ---------------------------------------------------------------------------
# The SSA3000X driver exposes _send and _recv but not _query as a public method.
# Add a small helper that wraps _send + _recv together.

def _ssa_query(ssa: SSA3000X, cmd: str, timeout: float = 120.0) -> str:
    """Send cmd and return response — thin wrapper on SSA internals."""
    ssa._send(cmd)
    ssa._sock.settimeout(timeout)
    buf = bytearray()
    while True:
        try:
            chunk = ssa._sock.recv(65536)
            if not chunk:
                break
            buf.extend(chunk)
            if buf[-1:] in (b"\n", b">"):
                break
        except Exception:
            break
    return buf.decode("ascii", errors="replace").strip()


# ---------------------------------------------------------------------------
# Full phase noise sweep
# ---------------------------------------------------------------------------

def run_phase_noise(ssa: SSA3000X, sdg: SDG1000X | None,
                    carrier_hz: float,
                    offsets_hz: list[float],
                    averages: int,
                    rbw_override: int | None,
                    source: str,
                    carrier_dbm: float) -> dict:
    """
    Run the full phase noise measurement.

    Returns a dict with all data needed for plotting and saving.
    """
    # --- Set up source ---
    if source == 'sdg' and sdg is not None:
        print(f"\n[SOURCE] SDG CH1 → {format_freq_short(carrier_hz)} "
              f"at {carrier_dbm:+.1f} dBm")
        sdg.set_sine(1, carrier_hz, carrier_dbm)
        sdg.output_on(1)
        time.sleep(0.3)

    # --- Measure carrier power ---
    print(f"\n[CARRIER] Measuring carrier power at {format_freq_short(carrier_hz)} ...")
    ssa.disable_tracking_generator()

    # Restore to a normal span first
    start = max(9_000, int(carrier_hz - CARRIER_SPAN_HZ / 2))
    stop  = int(carrier_hz + CARRIER_SPAN_HZ / 2)
    ssa.setup_band(start, stop, CARRIER_POINTS)
    ssa._send(f":SENS:BAND:RES {CARRIER_RBW_HZ}")
    ssa._send(f":SENS:BAND:VID {CARRIER_RBW_HZ}")
    ssa.single_sweep()

    p_carrier_dbm = measure_carrier(ssa, carrier_hz)
    print(f"  Carrier level: {p_carrier_dbm:+.2f} dBm")

    if np.isnan(p_carrier_dbm):
        raise RuntimeError("Carrier measurement returned NaN — check source and connection.")
    if p_carrier_dbm < -60.0:
        print("  WARNING: carrier level very low (<−60 dBm); results may be unreliable.")
    if p_carrier_dbm > 10.0:
        print("  WARNING: carrier level >+10 dBm; add attenuation to protect SSA input.")

    # --- Per-offset noise measurement ---
    print(f"\n[PHASE NOISE] Measuring {len(offsets_hz)} offset frequencies "
          f"(averages={averages}) ...")
    print(f"  {'Offset':>12}  {'RBW':>8}  {'Noise floor':>12}  {'L(f) dBc/Hz':>14}")
    print("  " + "-" * 56)

    results = []
    for offset_hz in sorted(offsets_hz):
        rbw_hz = _noise_rbw(offset_hz, rbw_override)

        # Zero-span: configure and measure
        centre_hz = int(carrier_hz + offset_hz)
        ssa._send(f":FREQ:CENT {centre_hz}")
        ssa._send(":FREQ:SPAN 0")
        ssa._send(f":SENS:BAND:RES {rbw_hz}")
        ssa._send(f":SENS:BAND:VID {rbw_hz}")

        if averages > 1:
            ssa._send(f":TRAC:AVER:COUN {averages}")
            ssa._send(":TRAC:TYPE AVER")
        else:
            ssa._send(":TRAC:TYPE WRIT")

        ssa._send(":INIT:CONT OFF")
        ssa._send(":INIT:IMM")

        # Wait for completion
        opc = _ssa_query(ssa, "*OPC?", timeout=120.0)
        if opc.strip() != "1":
            print(f"    WARNING: *OPC? returned '{opc}' at {format_freq_short(offset_hz)} offset")

        trace = ssa.get_trace()
        if len(trace) == 0:
            print(f"  {format_freq_short(offset_hz):>12}  {'N/A':>8}  {'empty trace':>12}")
            results.append({
                'offset_hz':     offset_hz,
                'rbw_hz':        rbw_hz,
                'noise_dbm':     float('nan'),
                'phase_noise':   float('nan'),
            })
            continue

        # Convert to linear power, average, back to dBm
        p_lin  = 10.0 ** (trace / 10.0)
        p_mean = float(np.mean(p_lin))
        if p_mean <= 0:
            p_noise_dbm = float('nan')
        else:
            p_noise_dbm = 10.0 * np.log10(p_mean)

        l_f = phase_noise_dbchz(p_noise_dbm, p_carrier_dbm, rbw_hz)

        print(f"  {format_freq_short(offset_hz):>12}  {rbw_hz:>6} Hz  "
              f"{p_noise_dbm:>+12.1f}  {l_f:>+14.1f} dBc/Hz",
              flush=True)

        results.append({
            'offset_hz':     offset_hz,
            'rbw_hz':        rbw_hz,
            'noise_dbm':     p_noise_dbm,
            'phase_noise':   l_f,
        })

    return {
        'carrier_hz':     carrier_hz,
        'carrier_dbm':    p_carrier_dbm,
        'source':         source,
        'averages':       averages,
        'offsets':        results,
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_phase_noise(data: dict, output_prefix: str) -> str:
    """
    Generate a phase noise plot (L(f) vs. offset frequency on a log X axis).
    Returns the saved PNG path.
    """
    carrier_hz  = data['carrier_hz']
    carrier_dbm = data['carrier_dbm']
    offsets     = data['offsets']

    valid = [(r['offset_hz'], r['phase_noise'])
             for r in offsets if not np.isnan(r['phase_noise'])]
    if not valid:
        print("  No valid phase noise data — plot skipped.")
        return ""

    off_hz = np.array([v[0] for v in valid])
    l_f    = np.array([v[1] for v in valid])

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.semilogx(off_hz, l_f, 'o-', color='#1f77b4', markersize=6, linewidth=1.5)

    # Annotate each point
    for ox, ly in zip(off_hz, l_f):
        ax.annotate(f"{ly:.1f}", (ox, ly),
                    textcoords='offset points', xytext=(5, 4),
                    fontsize=7, color='#333333')

    # Reference lines: typical oscillator benchmarks
    ax.axhline(-100, color='green',     linestyle=':', linewidth=0.8, alpha=0.6,
               label='−100 dBc/Hz')
    ax.axhline(-120, color='orange',    linestyle=':', linewidth=0.8, alpha=0.6,
               label='−120 dBc/Hz')
    ax.axhline(-140, color='darkgreen', linestyle=':', linewidth=0.8, alpha=0.6,
               label='−140 dBc/Hz')

    carrier_mhz = carrier_hz / 1e6
    ax.set_xlabel('Offset Frequency (Hz)', fontsize=10)
    ax.set_ylabel('L(f)  (dBc/Hz)', fontsize=10)
    ax.set_title(
        f"Phase Noise  —  {carrier_mhz:.4f} MHz\n"
        f"Carrier: {carrier_dbm:+.2f} dBm  |  "
        f"Source: {data['source'].upper()}  |  "
        f"Averages: {data['averages']}  |  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=10,
    )
    ax.grid(True, which='both', alpha=0.35)
    ax.legend(fontsize=8, loc='upper right')
    ax.tick_params(labelsize=9, which='both')

    # Y-axis: typical range for phase noise plots
    if len(l_f) > 0:
        ymin = max(float(np.min(l_f)) - 10.0, -170.0)
        ymax = min(float(np.max(l_f)) + 15.0,  -40.0)
        if ymax > ymin:
            ax.set_ylim(ymin, ymax)

    plt.tight_layout()
    path = f"{output_prefix}_phase_noise.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def save_phase_noise_txt(data: dict, output_prefix: str) -> str:
    """Write phase noise text report.  Returns path."""
    path = f"{output_prefix}_phase_noise.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 68

    lines = [
        sep,
        "  PHASE NOISE MEASUREMENT REPORT",
        f"  Generated  : {ts}",
        f"  Carrier    : {format_freq(data['carrier_hz'])}",
        f"  Carrier lvl: {data['carrier_dbm']:+.2f} dBm (at SSA input)",
        f"  Source     : {data['source'].upper()}",
        f"  Averages   : {data['averages']}",
        sep,
        "",
        f"  {'Offset':>12}  {'RBW':>8}  {'Noise floor':>12}  {'L(f) dBc/Hz':>14}",
        "  " + "-" * 54,
    ]

    valid_l = []
    for r in data['offsets']:
        if np.isnan(r['phase_noise']):
            lines.append(f"  {format_freq_short(r['offset_hz']):>12}  "
                         f"{r['rbw_hz']:>6} Hz  {'N/A':>12}  {'N/A':>14}")
        else:
            lines.append(
                f"  {format_freq_short(r['offset_hz']):>12}  "
                f"{r['rbw_hz']:>6} Hz  "
                f"{r['noise_dbm']:>+12.1f}  "
                f"{r['phase_noise']:>+14.1f} dBc/Hz"
            )
            valid_l.append(r['phase_noise'])

    if valid_l:
        lines += [
            "",
            f"  Best  (lowest noise): {min(valid_l):+.1f} dBc/Hz  "
            f"(at highest offset)",
            f"  Worst (closest-in)  : {max(valid_l):+.1f} dBc/Hz  "
            f"(at lowest offset)",
        ]

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase Noise Measurement — SSA3000X zero-span technique",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Technique:
  1. Measure carrier power with a 100 kHz span / 30 kHz RBW.
  2. For each offset, configure the SSA in zero-span at carrier+offset,
     set RBW to ~30%% of offset, and measure the mean noise floor.
  3. Compute: L(f) = P_noise_dBm - P_carrier_dBm - 10*log10(RBW_Hz)

Connection (SDG source mode, default):
  SDG CH1 OUT → SSA RF In
  Typical: set carrier level to −10 dBm (good SNR without overloading SSA).

Connection (external source mode):
  External oscillator → SSA RF In
  Use attenuator to keep carrier at −10 to −20 dBm at SSA input.

Limitations:
  - SSA noise floor limits useful range; typical floor on SSA3032X Plus
    is around −110 to −130 dBm/Hz.  Offsets below 10 Hz are unreliable.
  - Phase noise below the SSA noise floor cannot be measured.
  - For very close-in offsets (<30 Hz), the RBW gets very narrow and
    sweep times increase dramatically.

Examples:
  python phase_noise.py --freq 14000
  python phase_noise.py --freq 10000 --source sdg --carrier-level -10
  python phase_noise.py --freq 28000 --offsets 10,30,100,300,1000,3000,10000,100000
  python phase_noise.py --freq 14000 --averages 10 --output vcxo_14mhz
""",
    )

    parser.add_argument("--freq",    type=float, default=DEFAULT_FREQ_KHZ, metavar="KHZ",
                        help=f"Carrier frequency in kHz (default {DEFAULT_FREQ_KHZ})")
    parser.add_argument("--ssa",     default=DEFAULT_SSA_HOST, metavar="HOST",
                        help=f"SSA IP address (default {DEFAULT_SSA_HOST})")
    parser.add_argument("--sdg",     default=DEFAULT_SDG_HOST, metavar="HOST",
                        help=f"SDG IP address (default {DEFAULT_SDG_HOST})")
    parser.add_argument("--source",  choices=["sdg", "ext"], default="sdg",
                        help="Carrier source: sdg (SDG1000X, default) or ext (external)")
    parser.add_argument("--carrier-level", type=float, default=DEFAULT_CARRIER_DBM,
                        metavar="DBM",
                        help=f"SDG output level in dBm (source=sdg only; default {DEFAULT_CARRIER_DBM})")
    parser.add_argument("--offsets", default=None, metavar="HZ_LIST",
                        help="Comma-separated offset frequencies in Hz "
                             "(default: 10,30,100,300,1k,3k,10k,30k,100k,300k,1M)")
    parser.add_argument("--rbw",     type=int, default=None, metavar="HZ",
                        help="Fixed RBW in Hz for all offsets (default: auto, ~30%% of offset)")
    parser.add_argument("--averages", type=int, default=DEFAULT_AVERAGES, metavar="N",
                        help=f"Trace averages per offset point (default {DEFAULT_AVERAGES})")
    parser.add_argument("--output",  default=None, metavar="PREFIX",
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        freq_str = f"{args.freq:.0f}khz"
        args.output = f"phase_noise_{freq_str}_{ts}"

    carrier_hz = args.freq * 1_000.0

    if args.offsets is not None:
        try:
            offsets_hz = [float(x.strip()) for x in args.offsets.split(",")
                          if x.strip()]
        except ValueError as exc:
            print(f"Error parsing --offsets: {exc}")
            sys.exit(1)
    else:
        offsets_hz = list(DEFAULT_OFFSETS_HZ)

    if not offsets_hz:
        print("Error: no offset frequencies specified.")
        sys.exit(1)

    if args.averages < 1:
        print("Error: --averages must be at least 1.")
        sys.exit(1)

    ssa = None
    sdg = None

    try:
        print(f"Connecting to SSA via inventory ...")
        ssa = connect(args.ssa or 'ssa')
        print(f"  {ssa.identify()}")
        ssa.disable_tracking_generator()

        if args.source == 'sdg':
            print(f"Connecting to SDG via inventory ...")
            sdg = connect(args.sdg or 'sdg')
            print(f"  {sdg.identify()}")

        print(f"\nSetup:")
        print(f"  Carrier    : {format_freq_short(carrier_hz)}")
        print(f"  Source     : {args.source.upper()}")
        if args.source == 'sdg':
            print(f"  SDG level  : {args.carrier_level:+.1f} dBm")
        print(f"  Offsets    : {', '.join(format_freq_short(o) for o in sorted(offsets_hz))}")
        print(f"  RBW        : {'auto' if args.rbw is None else f'{args.rbw} Hz'}")
        print(f"  Averages   : {args.averages}")

        # Run the measurement
        data = run_phase_noise(
            ssa         = ssa,
            sdg         = sdg if args.source == 'sdg' else None,
            carrier_hz  = carrier_hz,
            offsets_hz  = offsets_hz,
            averages    = args.averages,
            rbw_override = args.rbw,
            source      = args.source,
            carrier_dbm = args.carrier_level,
        )

        # --- Save outputs ---
        print("\n[SAVING RESULTS]")

        txt_path = save_phase_noise_txt(data, args.output)
        print(f"Text   → {txt_path}")

        # JSON
        json_path = f"{args.output}_phase_noise.json"
        json_data = {
            'timestamp':    datetime.now().isoformat(),
            'ssa_host':     args.ssa,
            'sdg_host':     args.sdg if args.source == 'sdg' else None,
            'source':       data['source'],
            'carrier_hz':   data['carrier_hz'],
            'carrier_dbm':  data['carrier_dbm'],
            'averages':     data['averages'],
            'offsets': [
                {
                    'offset_hz':   r['offset_hz'],
                    'rbw_hz':      r['rbw_hz'],
                    'noise_dbm':   None if np.isnan(r['noise_dbm'])   else r['noise_dbm'],
                    'phase_noise': None if np.isnan(r['phase_noise']) else r['phase_noise'],
                }
                for r in data['offsets']
            ],
        }
        with open(json_path, "w") as jf:
            json.dump(json_data, jf, indent=2)
        print(f"JSON   → {json_path}")

        try:
            png_path = plot_phase_noise(data, args.output)
            if png_path:
                print(f"Plot   → {png_path}")
        except Exception as exc:
            print(f"Plot failed: {exc}")

        # Print summary
        valid = [r for r in data['offsets'] if not np.isnan(r['phase_noise'])]
        if valid:
            print(f"\nSummary:")
            for r in valid:
                print(f"  {format_freq_short(r['offset_hz']):>10}  "
                      f"{r['phase_noise']:+.1f} dBc/Hz")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to instrument: {exc}")
        print("Verify instruments are powered on and SCPI/LAN is enabled.")
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
        # Always restore the SSA to a sensible continuous-sweep state
        if ssa is not None:
            try:
                restore_ssa(ssa, carrier_hz if 'carrier_hz' in dir() else 10_000_000)
            except Exception:
                pass
            try:
                ssa.disable_tracking_generator()
                ssa.disconnect()
            except Exception:
                pass
        if sdg is not None:
            try:
                sdg.output_off_all()
                sdg.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
