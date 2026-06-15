#!/usr/bin/env python3
"""
psrr.py — Power Supply Rejection Ratio Measurement

Measures PSRR (dB) vs frequency for voltage regulators and LDOs.

IMPORTANT — HARDWARE SAFETY:
    The AWG output MUST NOT be connected directly to a live DC rail.
    You need an AC injection circuit:
        AWG "Gen Out" ──[C_coupling 10µF]──[L_inject 10µH]──── Regulator Vin
    The capacitor blocks DC from the AWG; the inductor prevents the DC supply
    from shorting the AWG AC signal to ground.

Physical setup:
    AWG "Gen Out" ──[C 10µF]──[L 10µH]──┐
                                          ├── Regulator Vin ── CH1 (ripple sense)
                                          │
                                  DC supply (e.g. SPD3303X)

    Regulator Vout ── CH2 (output ripple)
    Regulator GND  ── Scope GND

    PSRR(f) = 20 × log10(Vrms_input / Vrms_output)   [higher = better]

Source: Built-in AWG only (scope and scope AWG share ground — minimises
        ground loop in the injection path).

Usage examples:
    python psrr.py                        # 100 Hz – 1 MHz, default
    python psrr.py --stop-hz 500000       # sweep to 500 kHz
    python psrr.py --level-vpp 0.05       # lower injection (quiet regulator)
    python psrr.py --points 120           # more frequency resolution
"""

import argparse
import csv as csv_module
import math
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from rf_bench.siglent import SDS2000X                    # noqa: E402
from rf_bench.utils import gain_phase_from_fft, format_freq, format_freq_short  # noqa: E402
from rf_bench import connect

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SCOPE_HOST  = None  # Now uses inventory
DEFAULT_START_HZ    = 100
DEFAULT_STOP_HZ     = 1_000_000
DEFAULT_POINTS      = 80
DEFAULT_LEVEL_VPP   = 0.1    # small — stay in linear region of regulator
DEFAULT_CH_INPUT    = 1      # CH1 = Vin ripple
DEFAULT_CH_OUTPUT   = 2      # CH2 = Vout ripple

# PSRR reference lines on the plot (dB)
PSRR_REFERENCE_LINES = [20, 40, 60, 80]


# ---------------------------------------------------------------------------
# Frequency sweep
# ---------------------------------------------------------------------------

def log_freqs(start_hz: float, stop_hz: float, n: int) -> np.ndarray:
    """Return n log-spaced frequencies between start_hz and stop_hz."""
    return np.logspace(math.log10(start_hz), math.log10(stop_hz), n)


# ---------------------------------------------------------------------------
# Amplitude extraction
# ---------------------------------------------------------------------------

def vrms_at_freq(wave: np.ndarray, sample_rate_hz: float, freq_hz: float) -> float:
    """
    Compute the RMS amplitude at a specific frequency using FFT.

    Single-sided FFT, one bin nearest to freq_hz.
    Returns Vrms (not Vpp).
    """
    n     = len(wave)
    fft   = np.fft.rfft(wave)
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate_hz)
    idx   = int(np.argmin(np.abs(freqs - freq_hz)))
    # Single-sided FFT: bin amplitude = 2 × complex magnitude / N (for non-DC bins)
    # Vrms = amp_peak / √2
    vrms  = float(np.abs(fft[idx])) * math.sqrt(2.0) / n
    return vrms


# ---------------------------------------------------------------------------
# Waveform capture helper
# ---------------------------------------------------------------------------

def capture_both_channels(scope: SDS2000X, ch_input: int, ch_output: int,
                           duration_s: float,
                           vdiv_in: float = 0.05,
                           vdiv_out: float = 0.002) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Capture the input and output channels simultaneously.

    Uses AC coupling on both channels (we measure AC ripple, not DC level).
    Returns (wave_input, wave_output, sample_rate_hz).
    """
    scope.stop()
    time.sleep(0.05)

    scope._cmd(f"C{ch_input}:CPL A1M")     # AC coupling
    scope._cmd(f"C{ch_input}:VDIV {vdiv_in:.4f}V")
    scope._cmd(f"C{ch_output}:CPL A1M")
    scope._cmd(f"C{ch_output}:VDIV {vdiv_out:.4f}V")

    tdiv = duration_s / 10.0
    scope._cmd(f"TDIV {tdiv:.6f}S")
    scope._cmd("TRMD AUTO")
    scope.run()
    time.sleep(duration_s + 0.5)
    scope.stop()
    time.sleep(0.15)

    waves = {}
    sr    = 0.0
    for ch in (ch_input, ch_output):
        ch_str = f"C{ch}"
        scope._cmd(f":WAVeform:SOURce {ch_str}")
        scope._cmd(":WAVeform:FORMat BYTE")
        scope._cmd(":WAVeform:POINt MAX")
        pre = scope._read_binary_block(":WAVeform:PREamble?")
        horiz_interval, vgain, voffset = scope._parse_wavedesc(pre)
        raw = scope._read_binary_block(":WAVeform:DATA?")
        if not raw:
            raise RuntimeError(f"Waveform data empty on CH{ch}")
        counts = np.frombuffer(raw, dtype=np.int8).astype(np.float64)
        waves[ch] = counts * vgain - voffset
        if sr == 0.0 and horiz_interval > 0:
            sr = 1.0 / horiz_interval

    # Trim to equal length
    min_len = min(len(waves[ch_input]), len(waves[ch_output]))
    return waves[ch_input][:min_len], waves[ch_output][:min_len], sr


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def crossover_frequency(freqs_hz: list[float], psrr_db: list[float],
                         threshold_db: float = 3.0) -> float | None:
    """
    Return the frequency where PSRR first drops below threshold_db.

    This is the −3 dB roll-off point by default.
    Returns None if PSRR never reaches that level.
    """
    for i in range(len(psrr_db) - 1):
        if psrr_db[i] >= threshold_db and psrr_db[i + 1] < threshold_db:
            # Interpolate
            f_lo, f_hi = freqs_hz[i], freqs_hz[i + 1]
            p_lo, p_hi = psrr_db[i], psrr_db[i + 1]
            frac = (threshold_db - p_lo) / (p_hi - p_lo)
            return f_lo + frac * (f_hi - f_lo)
    return None


def average_psrr_in_band(freqs_hz: list[float], psrr_db: list[float],
                          flo: float, fhi: float) -> float | None:
    """Return average PSRR (dB) for points within [flo, fhi] Hz."""
    vals = [p for f, p in zip(freqs_hz, psrr_db) if flo <= f <= fhi]
    return float(np.mean(vals)) if vals else None


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_csv(prefix: str, freqs_hz: list[float],
              psrr_db: list[float], phases: list[float]) -> str:
    path = f"{prefix}_psrr.csv"
    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["freq_hz", "psrr_db", "phase_deg"])
        for freq, psrr, phase in zip(freqs_hz, psrr_db, phases):
            w.writerow([f"{freq:.2f}", f"{psrr:.3f}", f"{phase:.2f}"])
    return path


def write_text(prefix: str, freqs_hz: list[float],
               psrr_db: list[float], phases: list[float],
               level_vpp: float, ch_input: int, ch_output: int) -> str:
    path = f"{prefix}_psrr.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Summary statistics
    bands = [
        ("100 Hz – 1 kHz",   100,    1_000),
        ("1 kHz – 100 kHz",  1_000,  100_000),
        ("100 kHz – 1 MHz",  100_000, 1_000_000),
    ]

    # Crossover where PSRR first drops below 40 dB (useful practical threshold)
    xover_40 = crossover_frequency(freqs_hz, psrr_db, threshold_db=40.0)
    # Also find where PSRR first drops below 20 dB
    xover_20 = crossover_frequency(freqs_hz, psrr_db, threshold_db=20.0)

    with open(path, "w") as f:
        f.write(f"PSRR REPORT — {ts}\n")
        f.write("=" * 60 + "\n")
        f.write(f"  Source     : AWG (SDS2504X Plus built-in)\n")
        f.write(f"  Injection  : {level_vpp*1000:.0f} mVpp AC on Vin\n")
        f.write(f"  CH{ch_input}: Vin ripple (input)\n")
        f.write(f"  CH{ch_output}: Vout ripple (output)\n")
        f.write(f"  Frequency  : "
                f"{format_freq(freqs_hz[0])} – {format_freq(freqs_hz[-1])}\n")
        f.write(f"  Points     : {len(freqs_hz)}\n")
        f.write("\n")
        f.write("SUMMARY\n")
        f.write("-" * 60 + "\n")
        if xover_40 is not None:
            f.write(f"  PSRR < 40 dB above  : {format_freq(xover_40)}\n")
        else:
            f.write(f"  PSRR > 40 dB across full sweep\n")
        if xover_20 is not None:
            f.write(f"  PSRR < 20 dB above  : {format_freq(xover_20)}\n")

        f.write("\n")
        f.write("AVERAGE PSRR BY BAND\n")
        f.write("-" * 60 + "\n")
        for band_name, flo, fhi in bands:
            avg = average_psrr_in_band(freqs_hz, psrr_db, flo, fhi)
            if avg is not None:
                f.write(f"  {band_name:<22}: {avg:6.1f} dB\n")
            else:
                f.write(f"  {band_name:<22}: N/A (outside sweep range)\n")
        f.write("\n")
    return path


def generate_plot(prefix: str, freqs_hz: list[float],
                  psrr_db: list[float], level_vpp: float) -> str:
    fig, ax = plt.subplots(figsize=(10, 6))

    # Reference grid lines
    for ref in PSRR_REFERENCE_LINES:
        if min(psrr_db) - 10 <= ref <= max(psrr_db) + 10:
            ax.axhline(ref, color="gray", linestyle=":", linewidth=0.8, alpha=0.5)
            ax.text(freqs_hz[0] * 1.05, ref + 0.5, f"{ref} dB",
                    fontsize=7, color="gray", va="bottom")

    # PSRR curve
    ax.semilogx(freqs_hz, psrr_db, color="#2ca02c", linewidth=1.8, label="PSRR")

    # Shade area above 40 dB (good PSRR)
    psrr_arr = np.array(psrr_db)
    freqs_arr = np.array(freqs_hz)
    ax.fill_between(freqs_arr, 40, np.clip(psrr_arr, 40, None),
                    alpha=0.15, color="green", label="_nolegend_")

    ax.set_xlabel("Frequency (Hz)", fontsize=10)
    ax.set_ylabel("PSRR (dB)", fontsize=10)
    ax.set_title(
        f"Power Supply Rejection Ratio\n"
        f"Injection: {level_vpp*1000:.0f} mVpp  —  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=11,
    )
    ax.set_xlim(freqs_hz[0], freqs_hz[-1])

    # Y axis: range 0 to max PSRR + 10 dB margin, minimum 80 dB top
    ymin = max(0, min(psrr_db) - 5)
    ymax = max(80, max(psrr_db) + 10)
    ax.set_ylim(ymin, ymax)

    ax.grid(True, which="both", alpha=0.25)
    ax.legend(fontsize=9)
    ax.tick_params(labelsize=9)

    plt.tight_layout()
    path = f"{prefix}_psrr.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="PSRR Measurement — power supply rejection ratio vs frequency",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
IMPORTANT — HARDWARE SAFETY:
  The AWG output MUST NOT be connected directly to the DC rail.
  You need a passive AC injection circuit:

    AWG "Gen Out" ──[C 10µF]──[L 10µH]── Regulator Vin

  The capacitor blocks DC from the AWG; the inductor prevents the DC supply
  from shorting the AWG through to the low-impedance DC source.

Physical setup:
    AWG "Gen Out" ──[C 10µF]──[L 10µH]──┐
                                          ├── Regulator Vin
    CH1 (scope) ─────────────────────────┘
    CH2 (scope) ─────────────── Regulator Vout
    Scope GND ─────────────────────────── Common GND

Examples:
  python psrr.py
  python psrr.py --stop-hz 500000 --points 100
  python psrr.py --level-vpp 0.05 --ch-input 3 --ch-output 4
""",
    )

    parser.add_argument("--start-hz", type=float, default=DEFAULT_START_HZ,
                        help=f"Start frequency in Hz (default: {DEFAULT_START_HZ})")
    parser.add_argument("--stop-hz", type=float, default=DEFAULT_STOP_HZ,
                        help=f"Stop frequency in Hz (default: {DEFAULT_STOP_HZ:,})")
    parser.add_argument("--points", type=int, default=DEFAULT_POINTS,
                        help=f"Number of frequency points (default: {DEFAULT_POINTS})")
    parser.add_argument("--level-vpp", type=float, default=DEFAULT_LEVEL_VPP,
                        help=f"AWG injection amplitude in Vpp "
                             f"(default: {DEFAULT_LEVEL_VPP:.2f})")
    parser.add_argument("--ch-input", type=int, default=DEFAULT_CH_INPUT,
                        metavar="N",
                        help=f"Scope channel for Vin ripple (default: {DEFAULT_CH_INPUT})")
    parser.add_argument("--ch-output", type=int, default=DEFAULT_CH_OUTPUT,
                        metavar="N",
                        help=f"Scope channel for Vout ripple (default: {DEFAULT_CH_OUTPUT})")
    parser.add_argument("--scope-host", default=DEFAULT_SCOPE_HOST,
                        help=f"SDS2504X Plus IP address (default: {DEFAULT_SCOPE_HOST})")
    parser.add_argument("--output", default=None,
                        help="Output filename prefix (default: psrr_YYYYMMDD_HHMMSS)")

    args = parser.parse_args()

    if args.stop_hz > 25e6:
        print("Warning: AWG max is 25 MHz — clamping stop frequency.")
        args.stop_hz = 25e6

    if args.ch_input == args.ch_output:
        print("Error: --ch-input and --ch-output must be different channels.")
        sys.exit(1)

    if args.output is None:
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"psrr_{ts}"

    freqs_hz = log_freqs(args.start_hz, args.stop_hz, args.points).tolist()

    print(f"PSRR — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Source      : AWG (SDS2504X Plus built-in)")
    print(f"  Injection   : {args.level_vpp*1000:.0f} mVpp")
    print(f"  Vin ripple  : CH{args.ch_input}")
    print(f"  Vout ripple : CH{args.ch_output}")
    print(f"  Frequency   : {format_freq(args.start_hz)} – {format_freq(args.stop_hz)}")
    print(f"  Points      : {args.points}")
    print()
    print("  NOTE: Ensure the AC injection circuit (10µF cap + 10µH inductor)")
    print("  is in place before connecting the AWG output to the Vin rail.")
    print()

    scope = None

    try:
        print(f"Connecting to scope via inventory'} ...", end=" ", flush=True)
        scope = connect(args.scope_host or 'sds')
        print(f"OK  [{scope.identify().split(',')[1].strip()}]")

        scope.stop()
        scope.set_awg_sine(freqs_hz[0], amplitude_vpp=args.level_vpp)
        scope.awg_output_on()
        time.sleep(0.2)

        print()

        psrr_db  = []
        phases   = []
        n        = len(freqs_hz)

        for idx, f in enumerate(freqs_hz):
            scope.set_awg_sine(f, amplitude_vpp=args.level_vpp)
            time.sleep(0.05)

            # Capture duration: at least 20 cycles, minimum 5 ms
            duration_s = max(0.005, 20.0 / f)

            # V/div for input channel: slightly above injection level
            vdiv_in  = max(0.002, args.level_vpp / 3.0)
            # V/div for output channel: start small — good regulators have
            # very low output ripple.  Use 2 mV/div (scope minimum).
            vdiv_out = 0.002

            ch_in, ch_out, sr = capture_both_channels(
                scope, args.ch_input, args.ch_output,
                duration_s, vdiv_in=vdiv_in, vdiv_out=vdiv_out,
            )

            # FFT-based amplitude at stimulus frequency
            vrms_in  = vrms_at_freq(ch_in,  sr, f)
            vrms_out = vrms_at_freq(ch_out, sr, f)

            if vrms_in < 1e-9 or vrms_out < 1e-9:
                # Below noise floor — flag this point
                psrr = float('nan')
                phase = float('nan')
            else:
                psrr  = 20.0 * math.log10(vrms_in / vrms_out)
                # Phase: input → output at the stimulus frequency
                _gain_db, phase = gain_phase_from_fft(ch_in, ch_out, sr, freq_hz=f)

            psrr_db.append(psrr)
            phases.append(phase)

            # Progress
            bar_filled = int((idx + 1) / n * 20)
            bar        = "█" * bar_filled + "░" * (20 - bar_filled)
            psrr_str   = f"{psrr:6.1f} dB" if not math.isnan(psrr) else "  --- dB"
            print(f"\r  [{bar}] {idx+1:3d}/{n}  "
                  f"{format_freq_short(f):>10}  "
                  f"PSRR={psrr_str}",
                  end="", flush=True)

        print()  # newline after progress bar

        scope.awg_output_off()

        # Replace NaN with nearest valid value for output (avoid holes in plot)
        psrr_clean = []
        for i, p in enumerate(psrr_db):
            if math.isnan(p):
                # Fill with preceding valid value, or 0 if first
                psrr_clean.append(psrr_clean[-1] if psrr_clean else 0.0)
            else:
                psrr_clean.append(p)

        phases_clean = [0.0 if math.isnan(p) else p for p in phases]

        # Summary
        valid  = [p for p in psrr_db if not math.isnan(p)]
        if valid:
            print(f"\nSummary:")
            print(f"  Peak PSRR   : {max(valid):.1f} dB  "
                  f"@ {format_freq(freqs_hz[psrr_db.index(max(valid))])}")
            print(f"  Min PSRR    : {min(valid):.1f} dB  "
                  f"@ {format_freq(freqs_hz[psrr_db.index(min(valid))])}")

        # Write outputs
        csv_path = write_csv(args.output, freqs_hz, psrr_clean, phases_clean)
        txt_path = write_text(args.output, freqs_hz, psrr_clean, phases_clean,
                              args.level_vpp, args.ch_input, args.ch_output)
        png_path = generate_plot(args.output, freqs_hz, psrr_clean,
                                 args.level_vpp)

        print(f"\nOutput:")
        print(f"  PNG  → {png_path}")
        print(f"  CSV  → {csv_path}")
        print(f"  TXT  → {txt_path}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nConnection refused: {exc}")
        print("Verify the scope is powered on and SCPI/LAN is enabled.")
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
        if scope is not None:
            try:
                scope.awg_output_off()
                scope.run()
                scope.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
