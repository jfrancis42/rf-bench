#!/usr/bin/env python3
"""
Band Occupancy Monitor and Spectrum Waterfall Logger

Runs the SSA in a continuous loop, logging spectrum data to disk and generating
waterfall plots.  Shows band activity patterns over time.

Usage:
  python band_occupancy.py --band 40m --duration 3600
  python band_occupancy.py --band 20m --duration 7200 --threshold -80
  python band_occupancy.py --bands 40m 20m 15m --multi-band --dwell 30
  python band_occupancy.py --plot band_occupancy_20260527_120000_40m.npz
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

from rf_bench.siglent import SSA3000X                     # noqa: E402
from rf_bench.utils import format_freq, format_freq_short  # noqa: E402

# ---------------------------------------------------------------------------
# Band definitions  (Hz)
# ---------------------------------------------------------------------------

BANDS = {
    '160m': (1_800_000,   2_000_000),
    '80m':  (3_500_000,   4_000_000),
    '60m':  (5_330_500,   5_403_500),
    '40m':  (7_000_000,   7_300_000),
    '30m':  (10_100_000,  10_150_000),
    '20m':  (14_000_000,  14_350_000),
    '17m':  (18_068_000,  18_168_000),
    '15m':  (21_000_000,  21_450_000),
    '12m':  (24_890_000,  24_990_000),
    '10m':  (28_000_000,  29_700_000),
    '6m':   (50_000_000,  54_000_000),
    '2m':   (144_000_000, 148_000_000),
    '70cm': (420_000_000, 450_000_000),
    'fm':   (88_000_000,  108_000_000),
    'air':  (118_000_000, 137_000_000),
}

SWEEP_POINTS       = 751     # resolution points per sweep
DEFAULT_THRESHOLD  = -80.0   # dBm; signals above this count as "active"
DEFAULT_DWELL      = 60      # seconds per band in multi-band cycling
SAVE_INTERVAL      = 100     # sweeps between .npz saves
DEFAULT_SSA_HOST   = "10.1.1.60"

# Global flag set by SIGINT handler so loops can exit cleanly
_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C received — finishing current sweep and saving ...]")


signal.signal(signal.SIGINT, _sigint_handler)


# ---------------------------------------------------------------------------
# Data I/O
# ---------------------------------------------------------------------------

def save_npz(path: str, times: list, sweeps: list, start_hz: float,
             stop_hz: float, band_name: str) -> None:
    """Save accumulated sweep data to a compressed numpy archive."""
    if not sweeps:
        return
    metadata = json.dumps({
        "band":        band_name,
        "start_hz":    start_hz,
        "stop_hz":     stop_hz,
        "saved_at":    datetime.now().isoformat(),
    })
    np.savez_compressed(
        path,
        times=np.array(times),
        traces=np.array(sweeps),
        freqs=np.linspace(start_hz, stop_hz, len(sweeps[0])),
        metadata=metadata,
    )


def load_npz(path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """
    Load a saved .npz file.

    Returns (times, traces, freqs, metadata_dict).
    """
    data     = np.load(path, allow_pickle=False)
    times    = data['times']
    traces   = data['traces']
    freqs    = data['freqs']
    try:
        meta = json.loads(str(data['metadata']))
    except Exception:
        meta = {}
    return times, traces, freqs, meta


# ---------------------------------------------------------------------------
# Waterfall plot
# ---------------------------------------------------------------------------

def generate_waterfall(times: np.ndarray, traces: np.ndarray, freqs: np.ndarray,
                       meta: dict, output_prefix: str, threshold: float = DEFAULT_THRESHOLD,
                       show: bool = False) -> str:
    """
    Generate a waterfall (spectrogram) image from sweep data.

    X-axis: frequency (MHz)
    Y-axis: elapsed time (hours from first sweep) or clock time
    Color : dBm (inferno colormap)

    Returns the saved PNG path.
    """
    if len(traces) == 0:
        print("  No sweeps to plot.")
        return ""

    band_name  = meta.get('band', 'unknown')
    start_hz   = meta.get('start_hz', float(freqs[0]))
    stop_hz    = meta.get('stop_hz',  float(freqs[-1]))
    freqs_mhz  = freqs / 1e6

    # Time axis: hours elapsed from first sweep
    t0       = times[0]
    t_hours  = (times - t0) / 3600.0
    t_start  = datetime.fromtimestamp(t0).strftime('%Y-%m-%d %H:%M:%S')
    t_end    = datetime.fromtimestamp(times[-1]).strftime('%H:%M:%S')

    # Dynamic range for colormap — clip to useful range
    vmin = max(float(np.nanpercentile(traces, 2)),  -130.0)
    vmax = min(float(np.nanpercentile(traces, 99)),   20.0)

    fig, ax = plt.subplots(figsize=(12, 6))

    # pcolormesh — traces rows, freqs columns
    # extent [left, right, bottom, top]
    im = ax.pcolormesh(
        freqs_mhz, t_hours, traces,
        cmap='inferno', vmin=vmin, vmax=vmax,
        shading='auto',
    )

    cbar = fig.colorbar(im, ax=ax, pad=0.01)
    cbar.set_label("Power (dBm)", fontsize=9)
    cbar.ax.tick_params(labelsize=8)

    ax.set_xlabel("Frequency (MHz)", fontsize=10)
    ax.set_ylabel("Elapsed Time (hours)", fontsize=10)
    ax.set_title(
        f"Band Occupancy Waterfall — {band_name.upper()}  "
        f"({format_freq_short(start_hz)} – {format_freq_short(stop_hz)})\n"
        f"Start: {t_start}  End: {t_end}  "
        f"Sweeps: {len(traces)}  Threshold: {threshold:+.0f} dBm",
        fontsize=10,
    )
    ax.tick_params(labelsize=9)
    ax.set_xlim(freqs_mhz[0], freqs_mhz[-1])
    ax.set_ylim(t_hours[0], t_hours[-1])

    # Mark signals above threshold on the colorbar
    cbar.ax.axhline((threshold - vmin) / (vmax - vmin), color='cyan',
                    linewidth=1.5, linestyle='--')

    plt.tight_layout()
    path = f"{output_prefix}_waterfall.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    if show:
        plt.show()
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Summary text report
# ---------------------------------------------------------------------------

def save_summary_txt(times: np.ndarray, traces: np.ndarray, freqs: np.ndarray,
                     meta: dict, output_prefix: str,
                     threshold: float) -> str:
    """Write a plain-text run summary."""
    path     = f"{output_prefix}.txt"
    band     = meta.get('band', 'unknown')
    start_hz = meta.get('start_hz', float(freqs[0]))
    stop_hz  = meta.get('stop_hz',  float(freqs[-1]))
    ts_now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_sweeps = len(traces)
    sep      = "=" * 72

    t_start_str = (datetime.fromtimestamp(times[0]).strftime('%Y-%m-%d %H:%M:%S')
                   if n_sweeps else "—")
    t_end_str   = (datetime.fromtimestamp(times[-1]).strftime('%Y-%m-%d %H:%M:%S')
                   if n_sweeps else "—")
    duration_s  = (times[-1] - times[0]) if n_sweeps > 1 else 0.0

    lines = [
        sep,
        "  BAND OCCUPANCY RUN SUMMARY",
        f"  Generated  : {ts_now}",
        f"  Band       : {band.upper()}  "
        f"({format_freq_short(start_hz)} – {format_freq_short(stop_hz)})",
        f"  Start time : {t_start_str}",
        f"  End time   : {t_end_str}",
        f"  Duration   : {duration_s/3600:.2f} h  ({int(duration_s)} s)",
        f"  Sweeps     : {n_sweeps}",
        f"  Threshold  : {threshold:+.0f} dBm",
        sep,
    ]

    if n_sweeps > 0:
        all_traces = np.array(traces) if not isinstance(traces, np.ndarray) else traces
        peak_dbm   = float(np.nanmax(all_traces))
        peak_bin   = int(np.unravel_index(np.nanargmax(all_traces), all_traces.shape)[1])
        peak_freq  = float(freqs[peak_bin])
        peak_time  = (datetime.fromtimestamp(times[np.nanargmax(all_traces) // len(freqs)])
                      .strftime('%H:%M:%S') if n_sweeps > 1 else t_start_str)

        occupied_mask   = all_traces > threshold
        pct_time_active = 100.0 * float(np.any(occupied_mask, axis=1).mean())
        pct_freq_active = 100.0 * float(np.any(occupied_mask, axis=0).mean())

        lines += [
            "",
            f"  Peak power  : {peak_dbm:+.1f} dBm  @ {format_freq(peak_freq)}  (approx {peak_time})",
            f"  Occupancy (time)  : {pct_time_active:.1f}% of sweeps had signal above threshold",
            f"  Occupancy (freq)  : {pct_freq_active:.1f}% of bins exceeded threshold at some point",
            "",
        ]

        # Top-5 most active frequencies
        activity_per_bin = np.sum(occupied_mask, axis=0)
        top5_bins = np.argsort(activity_per_bin)[::-1][:5]
        lines.append("  Most active frequencies (signal above threshold):")
        for b in top5_bins:
            if activity_per_bin[b] > 0:
                lines.append(f"    {format_freq(float(freqs[b])):>14}  "
                              f"{activity_per_bin[b]:5d} / {n_sweeps} sweeps "
                              f"({100*activity_per_bin[b]/n_sweeps:.1f}%)")

    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# Triggered narrow sweep
# ---------------------------------------------------------------------------

def triggered_narrow_sweep(ssa: SSA3000X, peak_freq_hz: float,
                            band_span_hz: float, output_prefix: str,
                            sweep_num: int) -> None:
    """
    Perform a high-resolution narrow sweep around peak_freq_hz.

    Span = 1/10 of band span.  Saved as a separate .npz file.
    """
    narrow_span = band_span_hz / 10.0
    narrow_start = max(0, peak_freq_hz - narrow_span / 2.0)
    narrow_stop  = narrow_start + narrow_span

    ssa.setup_band(int(narrow_start), int(narrow_stop), SWEEP_POINTS)
    ssa.single_sweep()
    trace = ssa.get_trace()

    path = f"{output_prefix}_triggered_{sweep_num:06d}.npz"
    times  = [time.time()]
    sweeps = [trace.tolist()]
    save_npz(path, times, sweeps, narrow_start, narrow_stop,
             band_name=f"triggered@{format_freq_short(peak_freq_hz)}")
    print(f"    [TRIGGER] narrow sweep saved → {path}  "
          f"peak={np.max(trace):.1f} dBm @ {format_freq_short(peak_freq_hz)}")


# ---------------------------------------------------------------------------
# Single-band collection loop
# ---------------------------------------------------------------------------

def collect_band(ssa: SSA3000X, band_name: str, start_hz: int, stop_hz: int,
                 duration_s: float, threshold: float, triggered: bool,
                 output_prefix: str) -> tuple[list, list]:
    """
    Main data collection loop for a single band.

    Returns (times_list, sweeps_list).
    """
    global _running

    band_span_hz = stop_hz - start_hz
    times:  list[float]     = []
    sweeps: list[list]      = []

    print(f"\n[COLLECTING {band_name.upper()}]  "
          f"{format_freq_short(start_hz)} – {format_freq_short(stop_hz)}  "
          f"duration={'forever' if duration_s == 0 else f'{duration_s:.0f} s'}")

    ssa.setup_band(start_hz, stop_hz, SWEEP_POINTS)

    sweep_num   = 0
    t_start     = time.time()
    npz_path    = f"{output_prefix}.npz"

    while _running:
        # Check duration limit
        elapsed = time.time() - t_start
        if duration_s > 0 and elapsed >= duration_s:
            break

        ok    = ssa.single_sweep()
        trace = ssa.get_trace()
        ts    = time.time()

        times.append(ts)
        sweeps.append(trace.tolist())
        sweep_num += 1

        # Status line
        peak_dbm = float(np.max(trace))
        peak_bin = int(np.argmax(trace))
        peak_hz  = start_hz + (stop_hz - start_hz) * peak_bin / (len(trace) - 1)
        print(f"  sweep {sweep_num:5d}  elapsed {elapsed:6.0f}s  "
              f"peak {peak_dbm:+5.1f} dBm @ {format_freq_short(peak_hz)}",
              end='\r', flush=True)

        # Triggered capture
        if triggered and peak_dbm >= threshold:
            triggered_narrow_sweep(ssa, peak_hz, float(band_span_hz),
                                   output_prefix, sweep_num)
            # Re-setup band after narrow detour
            ssa.setup_band(start_hz, stop_hz, SWEEP_POINTS)

        # Periodic save
        if sweep_num % SAVE_INTERVAL == 0:
            print()  # newline after \r status
            save_npz(npz_path, times, sweeps, float(start_hz), float(stop_hz), band_name)
            print(f"  [autosave] {sweep_num} sweeps → {npz_path}", flush=True)

    print()  # newline after the \r status line
    return times, sweeps


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Band Occupancy Monitor and Spectrum Waterfall Logger",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available bands: {', '.join(sorted(BANDS.keys(), key=lambda b: BANDS[b][0]))}

Examples:
  python band_occupancy.py --band 40m --duration 3600
  python band_occupancy.py --band 20m --duration 7200 --threshold -80
  python band_occupancy.py --bands 40m 20m 15m --multi-band --dwell 30
  python band_occupancy.py --band 40m --triggered --threshold -75
  python band_occupancy.py --plot band_occupancy_20260527_120000_40m.npz
""",
    )

    parser.add_argument("--ssa",        default=DEFAULT_SSA_HOST, metavar="HOST",
                        help=f"SSA IP address (default {DEFAULT_SSA_HOST})")
    parser.add_argument("--band",       default=None, metavar="BAND",
                        help="Single band to monitor (e.g. '40m', '20m', '2m')")
    parser.add_argument("--bands",      nargs="+", default=None, metavar="BAND",
                        help="Multiple bands for multi-band cycling (space-separated)")
    parser.add_argument("--multi-band", action="store_true",
                        help="Cycle through --bands list with --dwell seconds each")
    parser.add_argument("--dwell",      type=float, default=DEFAULT_DWELL,
                        metavar="SEC",  help=f"Seconds per band in multi-band mode "
                                            f"(default {DEFAULT_DWELL})")
    parser.add_argument("--duration",   type=float, default=3600,
                        metavar="SEC",  help="Total run duration in seconds (0 = forever, "
                                            "default 3600)")
    parser.add_argument("--threshold",  type=float, default=DEFAULT_THRESHOLD,
                        metavar="DBM",  help=f"Trigger threshold in dBm "
                                            f"(default {DEFAULT_THRESHOLD})")
    parser.add_argument("--triggered",  action="store_true",
                        help="Save a narrow-band detail sweep when threshold is exceeded")
    parser.add_argument("--plot",       default=None, metavar="FILE",
                        help="Load a saved .npz file and generate waterfall plot (no SSA needed)")
    parser.add_argument("--output",     default=None, metavar="PREFIX",
                        help="Output filename prefix (default: timestamped)")

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"band_occupancy_{ts}"

    # -----------------------------------------------------------------------
    # --plot  (offline mode: load .npz and regenerate waterfall)
    # -----------------------------------------------------------------------
    if args.plot:
        print(f"Loading {args.plot} ...")
        times, traces, freqs, meta = load_npz(args.plot)
        print(f"  {len(traces)} sweeps  band={meta.get('band')}  "
              f"freqs {format_freq_short(freqs[0])}–{format_freq_short(freqs[-1])}")

        base = os.path.splitext(args.plot)[0]
        png  = generate_waterfall(times, traces, freqs, meta, base,
                                  threshold=args.threshold, show=False)
        txt  = save_summary_txt(times, traces, freqs, meta, base, args.threshold)
        print(f"Waterfall → {png}")
        print(f"Summary   → {txt}")
        return

    # -----------------------------------------------------------------------
    # Validate band selection
    # -----------------------------------------------------------------------
    if args.multi_band:
        if not args.bands:
            print("Error: --multi-band requires --bands <band1> <band2> ...")
            sys.exit(1)
        band_list = args.bands
        for b in band_list:
            if b not in BANDS:
                print(f"Error: unknown band '{b}'.  "
                      f"Available: {', '.join(sorted(BANDS.keys()))}")
                sys.exit(1)
    elif args.band:
        if args.band not in BANDS:
            print(f"Error: unknown band '{args.band}'.  "
                  f"Available: {', '.join(sorted(BANDS.keys()))}")
            sys.exit(1)
        band_list = [args.band]
    else:
        print("Error: specify --band BAND or --bands BAND [BAND ...] --multi-band")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Connect to SSA
    # -----------------------------------------------------------------------
    ssa = None
    try:
        print(f"Connecting to SSA @ {args.ssa} ...")
        ssa = SSA3000X(args.ssa)
        print(f"  {ssa.identify()}")

        t_run_start = time.time()
        all_band_data: dict[str, tuple[list, list]] = {}

        if args.multi_band:
            # ---------------------------------------------------------------
            # Multi-band cycling mode
            # ---------------------------------------------------------------
            print(f"\n[MULTI-BAND MODE]  bands={band_list}  dwell={args.dwell}s  "
                  f"total={args.duration:.0f}s")

            while _running:
                elapsed_total = time.time() - t_run_start
                if args.duration > 0 and elapsed_total >= args.duration:
                    break

                for band_name in band_list:
                    if not _running:
                        break
                    elapsed_total = time.time() - t_run_start
                    if args.duration > 0 and elapsed_total >= args.duration:
                        break

                    start_hz, stop_hz = BANDS[band_name]
                    time_left = (args.duration - elapsed_total
                                 if args.duration > 0 else float('inf'))
                    dwell = min(args.dwell, time_left)

                    npz_path = f"{args.output}_{band_name}.npz"

                    # Load any existing data for this band from this run
                    existing_times:  list = []
                    existing_sweeps: list = []
                    if band_name in all_band_data:
                        existing_times, existing_sweeps = all_band_data[band_name]

                    new_times, new_sweeps = collect_band(
                        ssa, band_name, start_hz, stop_hz,
                        duration_s=dwell,
                        threshold=args.threshold,
                        triggered=args.triggered,
                        output_prefix=f"{args.output}_{band_name}",
                    )

                    combined_times  = existing_times  + new_times
                    combined_sweeps = existing_sweeps + new_sweeps
                    all_band_data[band_name] = (combined_times, combined_sweeps)

                    if combined_sweeps:
                        save_npz(npz_path, combined_times, combined_sweeps,
                                 float(start_hz), float(stop_hz), band_name)

        else:
            # ---------------------------------------------------------------
            # Single-band mode
            # ---------------------------------------------------------------
            band_name        = band_list[0]
            start_hz, stop_hz = BANDS[band_name]
            npz_path         = f"{args.output}_{band_name}.npz"

            times, sweeps = collect_band(
                ssa, band_name, start_hz, stop_hz,
                duration_s=args.duration,
                threshold=args.threshold,
                triggered=args.triggered,
                output_prefix=f"{args.output}_{band_name}",
            )
            all_band_data[band_name] = (times, sweeps)

            if sweeps:
                save_npz(npz_path, times, sweeps,
                         float(start_hz), float(stop_hz), band_name)

        # -------------------------------------------------------------------
        # Final save + plot for all bands
        # -------------------------------------------------------------------
        print("\n[SAVING FINAL RESULTS]")
        for band_name, (times, sweeps) in all_band_data.items():
            if not sweeps:
                print(f"  {band_name}: no data collected.")
                continue

            start_hz, stop_hz = BANDS[band_name]
            times_arr  = np.array(times)
            sweeps_arr = np.array(sweeps)
            freqs_arr  = np.linspace(start_hz, stop_hz, sweeps_arr.shape[1])
            meta       = {"band": band_name, "start_hz": start_hz, "stop_hz": stop_hz}

            prefix = f"{args.output}_{band_name}"
            npz_path = f"{prefix}.npz"
            save_npz(npz_path, times, sweeps, float(start_hz), float(stop_hz), band_name)
            print(f"  Data  → {npz_path}  ({len(sweeps)} sweeps)")

            try:
                png = generate_waterfall(times_arr, sweeps_arr, freqs_arr, meta,
                                         prefix, threshold=args.threshold)
                print(f"  Plot  → {png}")
            except Exception as exc:
                print(f"  Waterfall plot failed: {exc}")

            try:
                txt = save_summary_txt(times_arr, sweeps_arr, freqs_arr, meta,
                                       prefix, args.threshold)
                print(f"  Text  → {txt}")
            except Exception as exc:
                print(f"  Summary text failed: {exc}")

    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to SSA: {exc}")
        print("Verify the SSA is powered on and SCPI/LAN is enabled.")
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
        if ssa is not None:
            try:
                ssa._send(':INIT:CONT ON')
                ssa.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
