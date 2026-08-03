#!/usr/bin/env python3
"""
FM Band Monitor and Waterfall Logger — SSA3032X Plus

Sweeps 87.5–108 MHz continuously, detects FM stations as power peaks,
logs peak frequency/power vs. time, and generates a waterfall image.
Optionally sends an SMS alert when a new carrier appears on a previously
empty channel.

Usage:
  python ssa_fm_monitor.py --duration 3600
  python ssa_fm_monitor.py --threshold -65 --interval 10 --alert
  python ssa_fm_monitor.py --plot fm_monitor_20260527_120000.npz
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))

from rf_bench.siglent import SSA3000X              # noqa: E402
from rf_bench.utils import format_freq, watts_to_dbm  # noqa: E402
from rf_bench import connect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FM_START_HZ       = 87_500_000
FM_STOP_HZ        = 108_000_000
FM_SPAN_MHZ       = (FM_STOP_HZ - FM_START_HZ) / 1e6
SWEEP_POINTS      = 751
DEFAULT_SSA_HOST  = None  # Now uses inventory
DEFAULT_THRESHOLD = -70.0   # dBm — below this is "empty"
DEFAULT_INTERVAL  = 5.0     # seconds between sweeps
DEFAULT_DURATION  = 3600    # total run time in seconds
SAVE_INTERVAL     = 50      # sweeps between autosaves

# US FM channel spacing is 200 kHz; min peak separation for peak detection
PEAK_MIN_SEP_HZ   = 150_000  # 150 kHz — slightly under 200 kHz spacing

_running = True


def _sigint_handler(sig, frame):
    global _running
    _running = False
    print("\n  [Ctrl+C received — finishing sweep and saving ...]")


signal.signal(signal.SIGINT, _sigint_handler)

# ---------------------------------------------------------------------------
# Peak detection
# ---------------------------------------------------------------------------

def detect_peaks(trace: np.ndarray, freqs_hz: np.ndarray,
                 threshold_dbm: float) -> list[dict]:
    """
    Find FM station carriers as local maxima above threshold.

    Returns list of dicts: {freq_hz, freq_mhz, power_dbm}.
    """
    freq_res_hz   = (freqs_hz[-1] - freqs_hz[0]) / (len(freqs_hz) - 1)
    min_sep_bins  = max(1, int(PEAK_MIN_SEP_HZ / freq_res_hz))
    peak_indices, _ = find_peaks(trace, height=threshold_dbm,
                                  distance=min_sep_bins)
    stations = []
    for idx in peak_indices:
        stations.append({
            'freq_hz':  float(freqs_hz[idx]),
            'freq_mhz': float(freqs_hz[idx]) / 1e6,
            'power_dbm': float(trace[idx]),
        })
    return stations


# ---------------------------------------------------------------------------
# Data persistence
# ---------------------------------------------------------------------------

def save_npz(path: str, times: list, sweeps: list,
             freqs_hz: np.ndarray, metadata: dict) -> None:
    """Save sweep data to compressed numpy archive."""
    if not sweeps:
        return
    meta_str = json.dumps(metadata)
    np.savez_compressed(
        path,
        times=np.array(times),
        traces=np.array(sweeps),
        freqs=freqs_hz,
        metadata=meta_str,
    )


def load_npz(path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    data   = np.load(path, allow_pickle=False)
    times  = data['times']
    traces = data['traces']
    freqs  = data['freqs']
    try:
        meta = json.loads(str(data['metadata']))
    except Exception:
        meta = {}
    return times, traces, freqs, meta


# ---------------------------------------------------------------------------
# Waterfall plot
# ---------------------------------------------------------------------------

def generate_waterfall(times: np.ndarray, traces: np.ndarray, freqs: np.ndarray,
                       meta: dict, output_prefix: str,
                       threshold: float = DEFAULT_THRESHOLD) -> str:
    """Generate FM waterfall image.  Returns PNG path."""
    if len(traces) == 0:
        return ""

    freqs_mhz = freqs / 1e6
    t0        = times[0]
    t_min     = (times - t0) / 60.0   # elapsed minutes

    vmin = max(float(np.nanpercentile(traces, 2)), -120.0)
    vmax = min(float(np.nanpercentile(traces, 99)),  10.0)

    fig, ax = plt.subplots(figsize=(12, 6))
    im = ax.pcolormesh(freqs_mhz, t_min, traces,
                       cmap='inferno', vmin=vmin, vmax=vmax, shading='auto')

    cbar = fig.colorbar(im, ax=ax, pad=0.01)
    cbar.set_label("Power (dBm)", fontsize=9)
    cbar.ax.axhline((threshold - vmin) / max(vmax - vmin, 1e-6),
                    color='cyan', linewidth=1.2, linestyle='--')

    ax.set_xlabel("Frequency (MHz)", fontsize=10)
    ax.set_ylabel("Elapsed Time (min)", fontsize=10)
    t_start = datetime.fromtimestamp(times[0]).strftime('%Y-%m-%d %H:%M:%S')
    ax.set_title(
        f"FM Band Monitor — 87.5–108 MHz\n"
        f"Start: {t_start}   Sweeps: {len(traces)}   Threshold: {threshold:+.0f} dBm",
        fontsize=10,
    )
    ax.set_xlim(freqs_mhz[0], freqs_mhz[-1])
    ax.tick_params(labelsize=9)

    plt.tight_layout()
    png = f"{output_prefix}_waterfall.png"
    plt.savefig(png, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return png


# ---------------------------------------------------------------------------
# SMS alert
# ---------------------------------------------------------------------------

def send_sms(message: str) -> None:
    """Send SMS via voipms proxy.  Non-fatal on failure."""
    try:
        import urllib.request
        import base64
        import pathlib

        creds_file = pathlib.Path.home() / "Dropbox/build/creds/voipms-rest.txt"
        if not creds_file.exists():
            return
        lines = creds_file.read_text().strip().splitlines()
        if len(lines) < 3:
            return
        url, user, password = lines[0].strip(), lines[1].strip(), lines[2].strip()

        import json as _json
        payload = _json.dumps({"to": user, "message": message}).encode()
        req = urllib.request.Request(
            f"{url}/sms", data=payload,
            headers={'Content-Type': 'application/json'}, method='POST',
        )
        cred = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header('Authorization', f'Basic {cred}')
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"  [SMS: {resp.status}]")
    except Exception as exc:
        print(f"  [SMS failed: {exc}]")


# ---------------------------------------------------------------------------
# Main collection loop
# ---------------------------------------------------------------------------

def run_monitor(ssa: SSA3000X, args: argparse.Namespace) -> None:
    """FM band sweep and logging loop."""
    freqs_hz  = np.linspace(FM_START_HZ, FM_STOP_HZ, SWEEP_POINTS)
    times:  list[float] = []
    sweeps: list[list]  = []

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.outdir:
        os.makedirs(args.outdir, exist_ok=True)
        prefix = os.path.join(args.outdir, f"fm_monitor_{ts}")
    else:
        prefix = f"fm_monitor_{ts}"

    npz_path = f"{prefix}.npz"
    meta     = {"start_hz": FM_START_HZ, "stop_hz": FM_STOP_HZ, "threshold": args.threshold}

    # Track known stations for new-station detection
    known_freqs: set[float] = set()  # MHz, rounded to nearest 100 kHz

    ssa.setup_band(FM_START_HZ, FM_STOP_HZ, SWEEP_POINTS)

    print(f"\n  Range     : 87.5 – 108.0 MHz")
    print(f"  Threshold : {args.threshold:+.0f} dBm")
    print(f"  Interval  : {args.interval} s")
    print(f"  Duration  : {args.duration} s")
    print(f"  Output    : {npz_path}")
    print()

    t_start  = time.time()
    sweep_n  = 0

    while _running:
        elapsed = time.time() - t_start
        if elapsed >= args.duration:
            break

        loop_t = time.time()
        ssa.single_sweep()
        trace = ssa.get_trace()
        ts_now = time.time()

        times.append(ts_now)
        sweeps.append(trace.tolist())
        sweep_n += 1

        stations = detect_peaks(trace, freqs_hz, args.threshold)
        station_str = ", ".join(f"{s['freq_mhz']:.1f}" for s in stations)
        print(f"  [{sweep_n:5d}]  {datetime.fromtimestamp(ts_now).strftime('%H:%M:%S')}  "
              f"{len(stations):2d} stations  [{station_str}]",
              end='\r', flush=True)

        # New-station alert
        if args.alert:
            for s in stations:
                rounded = round(s['freq_mhz'] * 10) / 10.0  # 0.1 MHz grid
                if rounded not in known_freqs:
                    known_freqs.add(rounded)
                    if known_freqs and len(known_freqs) > len(stations):
                        msg = (f"FM monitor: new station detected {rounded:.1f} MHz "
                               f"{s['power_dbm']:+.1f} dBm")
                        print(f"\n  [NEW STATION] {rounded:.1f} MHz  {s['power_dbm']:+.1f} dBm")
                        send_sms(msg)

        # Autosave
        if sweep_n % SAVE_INTERVAL == 0:
            print()
            save_npz(npz_path, times, sweeps, freqs_hz, meta)
            print(f"  [autosave] {sweep_n} sweeps → {npz_path}", flush=True)

        # Wait for next interval
        sleep_s = args.interval - (time.time() - loop_t)
        if sleep_s > 0 and _running:
            time.sleep(sleep_s)

    print()
    save_npz(npz_path, times, sweeps, freqs_hz, meta)
    print(f"  Data → {npz_path}  ({len(sweeps)} sweeps)")

    if sweeps:
        png = generate_waterfall(
            np.array(times), np.array(sweeps), freqs_hz, meta,
            prefix, threshold=args.threshold,
        )
        print(f"  Plot → {png}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="FM band monitor and waterfall logger — SSA3032X Plus",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ssa_fm_monitor.py --duration 3600
  python ssa_fm_monitor.py --threshold -65 --interval 10 --alert
  python ssa_fm_monitor.py --plot fm_monitor_20260527_120000.npz
""",
    )
    parser.add_argument("--ssa",       default=DEFAULT_SSA_HOST, metavar="HOST",
                        help=f"SSA IP address (default {DEFAULT_SSA_HOST})")
    parser.add_argument("--duration",  type=float, default=DEFAULT_DURATION, metavar="S",
                        help=f"Run duration in seconds (default {DEFAULT_DURATION})")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, metavar="DBM",
                        help=f"Peak detection threshold in dBm (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--interval",  type=float, default=DEFAULT_INTERVAL, metavar="S",
                        help=f"Sweep interval in seconds (default {DEFAULT_INTERVAL})")
    parser.add_argument("--alert",     action="store_true",
                        help="Send SMS when a new carrier appears on a previously empty channel")
    parser.add_argument("--outdir",    default=None, metavar="DIR",
                        help="Output directory (default: current directory)")
    parser.add_argument("--plot",      default=None, metavar="FILE.npz",
                        help="Offline: load .npz and regenerate waterfall (no SSA needed)")

    args = parser.parse_args()

    # Offline replot mode
    if args.plot:
        print(f"Loading {args.plot} ...")
        times, traces, freqs, meta = load_npz(args.plot)
        print(f"  {len(traces)} sweeps")
        prefix = os.path.splitext(args.plot)[0]
        png = generate_waterfall(times, traces, freqs, meta, prefix, args.threshold)
        print(f"  Waterfall → {png}")
        return

    print(f"Connecting to SSA via inventory ...")
    ssa = None
    try:
        ssa = connect(args.ssa or 'ssa')
        print(f"  {ssa.identify()}")
        run_monitor(ssa, args)
    except ConnectionRefusedError as exc:
        print(f"\nCannot connect to SSA: {exc}")
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
