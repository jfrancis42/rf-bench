#!/usr/bin/env python3
"""
ESP32-Combo Bode Plotter — Multi-DUT + Multi-Point Automated Testing

Extends the scope/bode-plotter with ESP32 automation:
- scpi-relay: Switch between up to 4 DUTs without cable swaps
- scpi-mux: Probe multiple points on a single DUT (multi-stage amplifier)
- SDS2504X Plus: Oscilloscope for amplitude/phase measurement
- SDG1062X: Function generator for frequency sweep

Generates overlaid Bode plots for all DUTs and saves per-DUT CSV files.

Usage:
  python bode_plot.py                          # Single DUT, no relay/mux
  python bode_plot.py --esp-relay 10.1.1.42    # 4 DUTs via relay
  python bode_plot.py --esp-mux 10.1.1.43 \
      --mux-points 0,2,4,6                     # Multi-point on one DUT
  python bode_plot.py --esp-relay 10.1.1.42 \
      --duts 1,2,3 --start 100 --stop 100e3    # Compare 3 filters

Cable setup (single DUT, no relay/mux):
  SDG CH1 ──┬─── Scope CH1 (reference)
            └─── DUT input
                   DUT output ─── Scope CH2

Cable setup (with scpi-relay for multi-DUT):
  SDG CH1 ──┬─── Scope CH1 (reference)
            └─── scpi-relay COM
                   Relay 1 ─── DUT1 ─── Relay 5 (return) ──┬─── Scope CH2
                   Relay 2 ─── DUT2 ─── Relay 6 (return) ──┤
                   Relay 3 ─── DUT3 ─── Relay 7 (return) ──┤
                   Relay 4 ─── DUT4 ─── Relay 8 (return) ──┘

Cable setup (with scpi-mux for multi-point on single DUT):
  SDG CH1 ──┬─── Scope CH1 (reference)
            └─── DUT input
                   DUT stage1 ─── scpi-mux CH0
                   DUT stage2 ─── scpi-mux CH1
                   DUT stage3 ─── scpi-mux CH2
                   DUT output ─── scpi-mux CH3
                   scpi-mux COM ─── Scope CH2
"""

import argparse
import csv as csv_module
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.siglent import SDG1000X, SDS2000X
from rf_bench.utils import (
    gain_phase_from_fft, format_freq, format_freq_short,
    dbm_to_vpp, vpp_to_dbm,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SDG_HOST         = "10.1.1.55"
SCOPE_HOST       = "10.1.1.58"
DEFAULT_POINTS   = 100
DEFAULT_LEVEL_DBM = -10.0

# ---------------------------------------------------------------------------
# SCPI helper for ESP32 devices (relay, mux)
# ---------------------------------------------------------------------------

def scpi_command(ip: str, port: int, command: str) -> str | None:
    """Send SCPI command to ESP32 device. Returns response if query, else None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect((ip, port))
            s.sendall((command + '\n').encode())
            if '?' in command:
                response = s.recv(1024).decode().strip()
                return response
    except (ConnectionRefusedError, OSError, socket.timeout) as exc:
        print(f"Error communicating with {ip}:{port}: {exc}")
        raise
    return None


# ---------------------------------------------------------------------------
# Relay control
# ---------------------------------------------------------------------------

class RelayController:
    """Wrapper for ESP32 scpi-relay."""
    def __init__(self, ip: str, port: int = 5025):
        self.ip = ip
        self.port = port
        # Verify connection
        idn = scpi_command(ip, port, '*IDN?')
        if 'SCPI-Relay' not in idn:
            raise RuntimeError(f"Device at {ip} is not a scpi-relay: {idn}")

    def close_relay(self, channel: int):
        """Close (energize) relay channel (1-4)."""
        scpi_command(self.ip, self.port, f'ROUTE:CLOSE (@{channel})')

    def open_relay(self, channel: int):
        """Open (de-energize) relay channel (1-4)."""
        scpi_command(self.ip, self.port, f'ROUTE:OPEN (@{channel})')

    def open_all(self):
        """Open all relays (safe state)."""
        scpi_command(self.ip, self.port, 'ROUTE:OPEN:ALL')


# ---------------------------------------------------------------------------
# Mux control
# ---------------------------------------------------------------------------

class MuxController:
    """Wrapper for ESP32 scpi-mux."""
    def __init__(self, ip: str, port: int = 5025):
        self.ip = ip
        self.port = port
        idn = scpi_command(ip, port, '*IDN?')
        if 'SCPI-MUX' not in idn:
            raise RuntimeError(f"Device at {ip} is not a scpi-mux: {idn}")

    def select_channel(self, channel: int):
        """Select mux channel (0-15 for CD4067, 0-7 for CD4051)."""
        scpi_command(self.ip, self.port, f'MUX:CHAN,{channel}')

    def enable(self):
        """Enable mux (connect selected channel)."""
        scpi_command(self.ip, self.port, 'MUX:EN,1')

    def disable(self):
        """Disable mux (disconnect all channels)."""
        scpi_command(self.ip, self.port, 'MUX:EN,0')


# ---------------------------------------------------------------------------
# Frequency array helpers
# ---------------------------------------------------------------------------

def make_freq_array(start_hz: float, stop_hz: float,
                    n: int, log_spaced: bool) -> np.ndarray:
    """Return an array of n frequencies between start_hz and stop_hz."""
    if log_spaced:
        return np.logspace(np.log10(start_hz), np.log10(stop_hz), n)
    else:
        return np.linspace(start_hz, stop_hz, n)


# ---------------------------------------------------------------------------
# Capture duration heuristic
# ---------------------------------------------------------------------------

def capture_duration(freq_hz: float, min_cycles: int = 20,
                     max_s: float = 5.0) -> float:
    """
    Return a capture duration (seconds) that gives at least min_cycles at freq_hz.

    Floor: 0.02 s (so the scope can settle after arm)
    Ceiling: max_s (avoids multi-minute captures at very low frequencies)
    """
    t = max(0.02, min_cycles / freq_hz)
    return min(t, max_s)


# ---------------------------------------------------------------------------
# Core measurement loop (single DUT or mux point)
# ---------------------------------------------------------------------------

def run_sweep(
    scope: SDS2000X,
    sdg: SDG1000X,
    freqs_hz: np.ndarray,
    level_dbm: float,
    ch_ref: int,
    ch_dut: int,
    fixed_duration_s: "float | None" = None,
) -> tuple[list[float], list[float], list[float]]:
    """
    Sweep *freqs_hz*, measure gain and phase at each point.

    Returns (measured_freqs, gain_db_list, phase_deg_list).

    Skipped points (capture failure) are represented by NaN.
    """
    amplitude_vpp = dbm_to_vpp(level_dbm)

    measured_freqs = []
    gains_db       = []
    phases_deg     = []

    total = len(freqs_hz)
    for i, f in enumerate(freqs_hz):
        # Set SDG frequency
        sdg.set_sine(1, freq_hz=f, level_dbm=level_dbm)

        # Settling time
        settle_s = min(0.1, 2.0 / f)
        time.sleep(settle_s)

        # Capture both channels
        dur = fixed_duration_s if fixed_duration_s is not None else capture_duration(f)
        try:
            ch1_v, sr = scope.capture_audio(channel=ch_ref,  duration_s=dur)
            ch2_v, _  = scope.capture_audio(channel=ch_dut,  duration_s=dur)
        except RuntimeError as exc:
            print(f"  [{i+1:3d}/{total}] {format_freq_short(f):>10}  SKIP ({exc})")
            measured_freqs.append(f)
            gains_db.append(float("nan"))
            phases_deg.append(float("nan"))
            continue

        # FFT-based gain and phase
        gain_db, phase_deg = gain_phase_from_fft(ch1_v, ch2_v, sr, freq_hz=f)

        print(f"  [{i+1:3d}/{total}] {format_freq_short(f):>10}  "
              f"gain={gain_db:+7.2f} dB  phase={phase_deg:+7.1f}°")

        measured_freqs.append(f)
        gains_db.append(gain_db)
        phases_deg.append(phase_deg)

    return measured_freqs, gains_db, phases_deg


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_csv(freqs: list[float], gains_db: list[float],
              phases_deg: list[float], prefix: str) -> str:
    path = f"{prefix}_bode.csv"
    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["freq_hz", "gain_db", "phase_deg"])
        for freq, g, p in zip(freqs, gains_db, phases_deg):
            w.writerow([f"{freq:.6f}", f"{g:.4f}", f"{p:.3f}"])
    return path


def write_summary(freqs: list[float], gains_db: list[float],
                  phases_deg: list[float], level_dbm: float,
                  prefix: str, label: str = "") -> str:
    path = f"{prefix}_bode.txt"

    g = np.array(gains_db, dtype=float)
    valid = ~np.isnan(g)

    with open(path, "w") as fh:
        fh.write("=" * 72 + "\n")
        fh.write(f"  BODE PLOT SUMMARY — {label}\n")
        fh.write(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        fh.write(f"  Source    : SDG1062X\n")
        fh.write(f"  Drive     : {level_dbm:+.1f} dBm"
                 f"  ({dbm_to_vpp(level_dbm)*1000:.1f} mVpp into 50 Ω)\n")
        fh.write(f"  Sweep     : {format_freq(freqs[0])} – {format_freq(freqs[-1])}\n")
        fh.write(f"  Points    : {len(freqs)} ({np.sum(valid)} valid)\n")
        fh.write("=" * 72 + "\n\n")

        if np.sum(valid) > 0:
            gv = g[valid]
            fh.write(f"  Passband gain (approx) : {np.percentile(gv, 75):+.2f} dB"
                     f"  (75th percentile)\n")
            fh.write(f"  Gain range             : {np.nanmin(g):+.2f} dB"
                     f" – {np.nanmax(g):+.2f} dB\n")

    return path


# ---------------------------------------------------------------------------
# Plot generation (overlaid multi-DUT/multi-point)
# ---------------------------------------------------------------------------

def generate_plot(all_results: list[tuple[str, list[float], list[float], list[float]]],
                  level_dbm: float, prefix: str) -> str:
    """
    Generate overlaid Bode plot for all DUTs/mux points.

    all_results: list of (label, freqs, gains_db, phases_deg)
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig.suptitle(
        f"Multi-DUT Bode Plot — {ts}\n"
        f"Drive: {level_dbm:+.0f} dBm",
        fontsize=11,
    )

    colors = plt.cm.tab10(np.linspace(0, 1, len(all_results)))

    for (label, freqs, gains_db, phases_deg), color in zip(all_results, colors):
        fa = np.array(freqs, dtype=float)
        ga = np.array(gains_db, dtype=float)
        pa = np.array(phases_deg, dtype=float)

        # Gain panel
        ax1.semilogx(fa, ga, color=color, linewidth=1.8, label=label, alpha=0.85)

        # Phase panel
        ax2.semilogx(fa, pa, color=color, linewidth=1.8, label=label, alpha=0.85)

    # Gain panel formatting
    ax1.axhline(0.0, color="gray", linestyle="--", linewidth=0.9, alpha=0.5)
    ax1.axhline(-3.0, color="darkorange", linestyle=":", linewidth=0.9, alpha=0.5)
    ax1.set_ylabel("Gain (dB)", fontsize=10)
    ax1.grid(True, which="both", alpha=0.30)
    ax1.legend(fontsize=8, loc="best")
    ax1.tick_params(labelsize=9)

    # Phase panel formatting
    ax2.axhline(  0.0, color="gray",       linestyle="--", linewidth=0.9, alpha=0.5)
    ax2.axhline( 90.0, color="lightgray",  linestyle=":",  linewidth=0.7, alpha=0.5)
    ax2.axhline(-90.0, color="lightgray",  linestyle=":",  linewidth=0.7, alpha=0.5)
    ax2.set_ylabel("Phase (°)", fontsize=10)
    ax2.set_xlabel("Frequency (Hz)", fontsize=10)
    ax2.set_ylim(-180, 180)
    ax2.set_yticks([-180, -90, 0, 90, 180])
    ax2.grid(True, which="both", alpha=0.30)
    ax2.legend(fontsize=8, loc="best")
    ax2.tick_params(labelsize=9)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    path = f"{prefix}_bode.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ESP32-Combo Bode Plotter — Multi-DUT + Multi-Point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bode_plot.py                            # Single DUT, no automation
  python bode_plot.py --esp-relay 10.1.1.42 \
      --duts 1,2,3,4                             # 4 DUTs via relay
  python bode_plot.py --esp-mux 10.1.1.43 \
      --mux-points 0,1,2,3                       # 4-point probe on single DUT
  python bode_plot.py --start 100 --stop 100e3 \
      --points 200 --level -20                   # 200-pt sweep, -20 dBm
""",
    )

    inst_grp = parser.add_argument_group("instruments")
    inst_grp.add_argument("--sdg-host", default=SDG_HOST, metavar="HOST",
                          help=f"SDG1062X IP [default: {SDG_HOST}]")
    inst_grp.add_argument("--scope-host", default=SCOPE_HOST, metavar="HOST",
                          help=f"SDS2504X IP [default: {SCOPE_HOST}]")

    esp_grp = parser.add_argument_group("ESP32 automation")
    esp_grp.add_argument("--esp-relay", default=None, metavar="IP",
                         help="ESP32 scpi-relay IP for multi-DUT switching")
    esp_grp.add_argument("--esp-mux", default=None, metavar="IP",
                         help="ESP32 scpi-mux IP for multi-point probing")
    esp_grp.add_argument("--duts", default="1", metavar="LIST",
                         help="Comma-separated relay channels for DUTs [default: 1]")
    esp_grp.add_argument("--mux-points", default="0", metavar="LIST",
                         help="Comma-separated mux channels for probing [default: 0]")

    sweep_grp = parser.add_argument_group("sweep")
    sweep_grp.add_argument("--start", type=float, default=10.0, metavar="HZ",
                           help="Start frequency in Hz [default: 10]")
    sweep_grp.add_argument("--stop",  type=float, default=1_000_000.0,  metavar="HZ",
                           help="Stop frequency in Hz [default: 1 MHz]")
    sweep_grp.add_argument("--points", type=int, default=DEFAULT_POINTS, metavar="N",
                           help=f"Number of sweep points [default: {DEFAULT_POINTS}]")
    sweep_grp.add_argument("--level", type=float, default=DEFAULT_LEVEL_DBM,
                           metavar="DBM",
                           help=f"Source level in dBm [default: {DEFAULT_LEVEL_DBM}]")

    spacing_grp = parser.add_mutually_exclusive_group()
    spacing_grp.add_argument("--log-freq", action="store_true", default=True,
                              help="Log-spaced frequency points (default)")
    spacing_grp.add_argument("--lin-freq", action="store_true", default=False,
                              help="Linear-spaced frequency points")

    chan_grp = parser.add_argument_group("channels")
    chan_grp.add_argument("--ch-ref", type=int, default=1, metavar="N",
                          help="Scope channel for reference (CH1 default)")
    chan_grp.add_argument("--ch-dut", type=int, default=2, metavar="N",
                          help="Scope channel for DUT output (CH2 default)")

    out_grp = parser.add_argument_group("output")
    out_grp.add_argument("--output", default=None, metavar="PREFIX",
                         help="Output filename prefix [default: bode_YYYYMMDD_HHMMSS]")
    out_grp.add_argument("--duration-s", type=float, default=None, metavar="S",
                         help="Fixed capture duration per point (overrides auto)")

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"bode_{ts}"

    if args.start <= 0 or args.start >= args.stop:
        print("Error: --start must be > 0 and < --stop")
        sys.exit(1)

    # Parse DUT/mux lists
    dut_channels = [int(x.strip()) for x in args.duts.split(',')]
    mux_channels = [int(x.strip()) for x in args.mux_points.split(',')]

    # Validate channel ranges
    if args.esp_relay:
        if any(ch < 1 or ch > 4 for ch in dut_channels):
            print("Error: scpi-relay channels must be 1-4")
            sys.exit(1)
    if args.esp_mux:
        if any(ch < 0 or ch > 15 for ch in mux_channels):
            print("Error: scpi-mux channels must be 0-15 (CD4067)")
            sys.exit(1)

    # Build frequency array
    log_spaced = not args.lin_freq
    freqs_hz = make_freq_array(args.start, args.stop, args.points, log_spaced)

    # Print setup summary
    spacing_label = "log-spaced" if log_spaced else "linear-spaced"
    print(f"\n[ESP32-COMBO BODE PLOTTER]")
    print(f"  Source    : SDG1062X ({args.sdg_host})")
    print(f"  Scope     : SDS2504X ({args.scope_host})")
    if args.esp_relay:
        print(f"  Relay     : scpi-relay ({args.esp_relay}) — DUTs: {dut_channels}")
    if args.esp_mux:
        print(f"  Mux       : scpi-mux ({args.esp_mux}) — Points: {mux_channels}")
    print(f"  Sweep     : {format_freq(args.start)} – {format_freq(args.stop)}  "
          f"({args.points} pts, {spacing_label})")
    print(f"  Drive     : {args.level:+.1f} dBm  "
          f"({dbm_to_vpp(args.level)*1000:.1f} mVpp into 50 Ω)")
    print(f"  CH ref    : CH{args.ch_ref}   CH DUT: CH{args.ch_dut}")
    print(f"  Output    : {args.output}_*.{{png,csv,txt}}")
    print()

    # Connect instruments
    print("Connecting to scope ...", end=" ", flush=True)
    try:
        scope = SDS2000X(args.scope_host)
    except (ConnectionRefusedError, OSError) as exc:
        print(f"\nCannot connect to scope at {args.scope_host}: {exc}")
        sys.exit(1)
    print(f"OK  ({scope.identify().split(',')[1].strip()})")

    print("Connecting to SDG ...", end=" ", flush=True)
    try:
        sdg = SDG1000X(args.sdg_host)
    except (ConnectionRefusedError, OSError) as exc:
        print(f"\nCannot connect to SDG at {args.sdg_host}: {exc}")
        scope.close()
        sys.exit(1)
    print(f"OK  ({sdg.identify().split(',')[1].strip()})")
    sdg.output_on(1)

    relay = None
    if args.esp_relay:
        print("Connecting to scpi-relay ...", end=" ", flush=True)
        try:
            relay = RelayController(args.esp_relay)
            relay.open_all()  # Safe state
        except Exception as exc:
            print(f"\nCannot connect to scpi-relay at {args.esp_relay}: {exc}")
            sdg.output_off_all()
            sdg.close()
            scope.close()
            sys.exit(1)
        print("OK")

    mux = None
    if args.esp_mux:
        print("Connecting to scpi-mux ...", end=" ", flush=True)
        try:
            mux = MuxController(args.esp_mux)
            mux.disable()  # Safe state
        except Exception as exc:
            print(f"\nCannot connect to scpi-mux at {args.esp_mux}: {exc}")
            if relay:
                relay.open_all()
            sdg.output_off_all()
            sdg.close()
            scope.close()
            sys.exit(1)
        print("OK")

    all_results = []

    try:
        # Multi-DUT mode (relay switching)
        if args.esp_relay:
            for dut_ch in dut_channels:
                label = f"DUT{dut_ch}"
                print(f"\n=== Sweeping {label} (Relay Channel {dut_ch}) ===")
                relay.close_relay(dut_ch)
                time.sleep(0.1)  # Relay settle

                freqs_out, gains_out, phases_out = run_sweep(
                    scope=scope,
                    sdg=sdg,
                    freqs_hz=freqs_hz,
                    level_dbm=args.level,
                    ch_ref=args.ch_ref,
                    ch_dut=args.ch_dut,
                    fixed_duration_s=args.duration_s,
                )

                relay.open_relay(dut_ch)

                # Save per-DUT CSV and summary
                csv_path = write_csv(freqs_out, gains_out, phases_out,
                                     f"{args.output}_{label}")
                txt_path = write_summary(freqs_out, gains_out, phases_out,
                                         args.level, f"{args.output}_{label}", label)
                print(f"  CSV     → {csv_path}")
                print(f"  Summary → {txt_path}")

                all_results.append((label, freqs_out, gains_out, phases_out))

        # Multi-point mode (mux probing)
        elif args.esp_mux:
            for mux_ch in mux_channels:
                label = f"Point{mux_ch}"
                print(f"\n=== Sweeping {label} (Mux Channel {mux_ch}) ===")
                mux.select_channel(mux_ch)
                mux.enable()
                time.sleep(0.01)  # Mux settle

                freqs_out, gains_out, phases_out = run_sweep(
                    scope=scope,
                    sdg=sdg,
                    freqs_hz=freqs_hz,
                    level_dbm=args.level,
                    ch_ref=args.ch_ref,
                    ch_dut=args.ch_dut,
                    fixed_duration_s=args.duration_s,
                )

                mux.disable()

                # Save per-point CSV and summary
                csv_path = write_csv(freqs_out, gains_out, phases_out,
                                     f"{args.output}_{label}")
                txt_path = write_summary(freqs_out, gains_out, phases_out,
                                         args.level, f"{args.output}_{label}", label)
                print(f"  CSV     → {csv_path}")
                print(f"  Summary → {txt_path}")

                all_results.append((label, freqs_out, gains_out, phases_out))

        # Single DUT mode (no automation)
        else:
            label = "DUT"
            print(f"\n=== Sweeping {label} ===")

            freqs_out, gains_out, phases_out = run_sweep(
                scope=scope,
                sdg=sdg,
                freqs_hz=freqs_hz,
                level_dbm=args.level,
                ch_ref=args.ch_ref,
                ch_dut=args.ch_dut,
                fixed_duration_s=args.duration_s,
            )

            # Save CSV and summary
            csv_path = write_csv(freqs_out, gains_out, phases_out, args.output)
            txt_path = write_summary(freqs_out, gains_out, phases_out,
                                     args.level, args.output, label)
            print(f"  CSV     → {csv_path}")
            print(f"  Summary → {txt_path}")

            all_results.append((label, freqs_out, gains_out, phases_out))

    except KeyboardInterrupt:
        print("\nInterrupted — saving partial results ...")

    # Restore safe state
    if relay:
        relay.open_all()
    if mux:
        mux.disable()
    sdg.output_off_all()
    sdg.close()
    scope.run()
    scope.close()

    if not all_results:
        print("No data collected.")
        sys.exit(1)

    # Generate overlaid plot
    print("\n[RESULTS]")
    try:
        png_path = generate_plot(all_results, args.level, args.output)
        print(f"  Plot    → {png_path}")
    except Exception as exc:
        print(f"  Plot generation failed: {exc}")

    print("\nComplete.")


if __name__ == "__main__":
    main()
