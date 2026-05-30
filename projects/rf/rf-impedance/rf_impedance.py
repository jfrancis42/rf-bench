#!/usr/bin/env python3
"""
rf_impedance.py — RF Impedance Analyzer

Measures component impedance (Z, R+jX, |Z|, phase) vs frequency from
100 kHz to 60 MHz.  Useful for:
  - Finding self-resonant frequency (SRF) of RF inductors
  - Measuring capacitor ESR at RF frequencies
  - Characterising ferrite beads and common-mode chokes

Physical circuit (series injection):

    Source → R_ref (50 Ω) → DUT → GND
         CH1 ↑         CH2 ↑

CH1 measures the voltage at the top of R_ref (source side).
CH2 measures the voltage across the DUT.

Current through DUT: I = (V_CH1 - V_CH2) / R_ref
DUT impedance: Z = V_CH2 / I

Build R_ref from a precision 50 Ω metal-film resistor (0.1% or better) in a
small PCB or BNC test fixture.  Keep the fixture leads very short.

Usage examples:
    python rf_impedance.py --component inductor    # 100 kHz – 30 MHz
    python rf_impedance.py --component capacitor --stop-khz 10000
    python rf_impedance.py --source awg --stop-khz 25000
    python rf_impedance.py --start-khz 500 --stop-khz 60000 --points 300
"""

import argparse
import cmath
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

from rf_bench.siglent import SDG1000X, SDS2000X          # noqa: E402
from rf_bench.utils import (                             # noqa: E402
    complex_impedance_series, format_freq, format_freq_short,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SDG_HOST   = "10.1.1.55"
DEFAULT_SCOPE_HOST = "10.1.1.58"
DEFAULT_START_KHZ  = 100
DEFAULT_STOP_KHZ   = 30_000
DEFAULT_POINTS     = 200
DEFAULT_ZREF_OHM   = 50.0
DEFAULT_LEVEL_VPP  = 0.2    # small signal — avoids inductor self-heating
SCOPE_CH_SRC       = 1      # CH1 = source side of R_ref
SCOPE_CH_DUT       = 2      # CH2 = DUT side of R_ref


# ---------------------------------------------------------------------------
# Frequency sweep helper
# ---------------------------------------------------------------------------

def log_freqs(start_hz: float, stop_hz: float, n: int) -> np.ndarray:
    """Return n log-spaced frequencies between start_hz and stop_hz."""
    return np.logspace(math.log10(start_hz), math.log10(stop_hz), n)


# ---------------------------------------------------------------------------
# Level helpers
# ---------------------------------------------------------------------------

def vpp_to_dbm_50(vpp: float) -> float:
    """Vpp → dBm into 50 Ω (sine wave)."""
    # P = Vpp² / (8 × R) ; P_dBm = 10 × log10(P / 1e-3)
    p_w = vpp ** 2 / (8.0 * 50.0)
    return 10.0 * math.log10(p_w / 1e-3)


# ---------------------------------------------------------------------------
# Impedance analysis and derived quantities
# ---------------------------------------------------------------------------

def inductor_params(freqs_hz: list[float], z_list: list[complex]) -> dict:
    """
    Extract inductor parameters from impedance data.

    Returns: nominal_L_h, Q_at_1mhz, srf_hz (or None), L_values_h (list)
    """
    L_values = []
    for f, Z in zip(freqs_hz, z_list):
        if f > 0 and Z.imag > 0:
            L_values.append(Z.imag / (2.0 * math.pi * f))
        else:
            L_values.append(float('nan'))

    # Nominal L at 1 MHz (or nearest available frequency)
    target_f = 1e6
    idx_1mhz = min(range(len(freqs_hz)),
                   key=lambda i: abs(freqs_hz[i] - target_f))
    Z_1mhz   = z_list[idx_1mhz]
    nom_L    = L_values[idx_1mhz]
    Q        = abs(Z_1mhz.imag) / max(Z_1mhz.real, 1e-15)

    # SRF: first zero-crossing of Im(Z) from positive (inductive) to negative
    srf_hz = None
    for i in range(len(z_list) - 1):
        if z_list[i].imag > 0 and z_list[i + 1].imag <= 0:
            # Linear interpolation
            f_lo, f_hi = freqs_hz[i], freqs_hz[i + 1]
            x_lo, x_hi = z_list[i].imag, z_list[i + 1].imag
            frac  = x_lo / (x_lo - x_hi)
            srf_hz = f_lo + frac * (f_hi - f_lo)
            break

    return {
        "nominal_L_h":  nom_L,
        "Q_at_1mhz":    Q,
        "srf_hz":       srf_hz,
        "L_values_h":   L_values,
    }


def capacitor_params(freqs_hz: list[float], z_list: list[complex]) -> dict:
    """
    Extract capacitor parameters from impedance data.

    Returns: nominal_C_f, esr_ohm_at_srf, srf_hz (or None), C_values_f (list)
    """
    C_values = []
    for f, Z in zip(freqs_hz, z_list):
        if f > 0 and Z.imag < 0:
            C_values.append(-1.0 / (2.0 * math.pi * f * Z.imag))
        else:
            C_values.append(float('nan'))

    # Nominal C at 10 kHz (or nearest available)
    target_f  = 10e3
    idx_10khz = min(range(len(freqs_hz)),
                    key=lambda i: abs(freqs_hz[i] - target_f))
    nom_C = C_values[idx_10khz]

    # SRF: impedance minimum (capacitive resonance)
    z_mags = [abs(Z) for Z in z_list]
    srf_idx = int(np.argmin(z_mags))
    srf_hz  = freqs_hz[srf_idx]
    esr     = z_list[srf_idx].real

    return {
        "nominal_C_f":  nom_C,
        "esr_ohm":      esr,
        "srf_hz":       srf_hz,
        "C_values_f":   C_values,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_csv(prefix: str, rows: list[dict]) -> str:
    path = f"{prefix}_impedance.csv"
    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["freq_hz", "z_mag_ohm", "z_real_ohm", "z_imag_ohm",
                    "phase_deg", "L_uh", "C_pf"])
        for r in rows:
            w.writerow([
                f"{r['freq_hz']:.2f}",
                f"{r['z_mag']:.6f}",
                f"{r['z_real']:.6f}",
                f"{r['z_imag']:.6f}",
                f"{r['phase_deg']:.3f}",
                f"{r.get('L_uh', ''):.6f}" if r.get('L_uh') is not None else "",
                f"{r.get('C_pf', ''):.4f}" if r.get('C_pf') is not None else "",
            ])
    return path


def write_text(prefix: str, component: str, rows: list[dict],
               ind_params: dict | None, cap_params: dict | None,
               zref_ohm: float, source: str) -> str:
    path = f"{prefix}_impedance.txt"
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "w") as f:
        f.write(f"RF IMPEDANCE REPORT — {ts}\n")
        f.write("=" * 60 + "\n")
        f.write(f"  Component type : {component}\n")
        f.write(f"  Source         : {source.upper()}\n")
        f.write(f"  R_ref          : {zref_ohm:.1f} Ω\n")
        f.write(f"  Frequency range: "
                f"{format_freq(rows[0]['freq_hz'])} – "
                f"{format_freq(rows[-1]['freq_hz'])}\n")
        f.write(f"  Points         : {len(rows)}\n")
        f.write("\n")

        if ind_params is not None:
            L_uh = ind_params['nominal_L_h'] * 1e6
            f.write(f"INDUCTOR SUMMARY\n")
            f.write("-" * 60 + "\n")
            f.write(f"  Nominal inductance (@ 1 MHz): {L_uh:.3f} µH\n")
            f.write(f"  Q factor (@ 1 MHz)          : {ind_params['Q_at_1mhz']:.1f}\n")
            if ind_params['srf_hz'] is not None:
                f.write(f"  Self-resonant frequency      : "
                        f"{format_freq(ind_params['srf_hz'])}\n")
            else:
                f.write(f"  Self-resonant frequency      : not found in sweep range\n")

        if cap_params is not None:
            C_pf = cap_params['nominal_C_f'] * 1e12
            f.write(f"CAPACITOR SUMMARY\n")
            f.write("-" * 60 + "\n")
            f.write(f"  Nominal capacitance (@ 10 kHz): {C_pf:.2f} pF\n")
            f.write(f"  ESR at SRF                    : {cap_params['esr_ohm']:.3f} Ω\n")
            if cap_params['srf_hz'] is not None:
                f.write(f"  Self-resonant frequency       : "
                        f"{format_freq(cap_params['srf_hz'])}\n")
            else:
                f.write(f"  Self-resonant frequency       : not found in sweep range\n")

        if component in ("ferrite", "generic"):
            z_mags = [r['z_mag'] for r in rows]
            idx_max = int(np.argmax(z_mags))
            f.write(f"GENERIC / FERRITE SUMMARY\n")
            f.write("-" * 60 + "\n")
            f.write(f"  Peak |Z|: {z_mags[idx_max]:.1f} Ω "
                    f"@ {format_freq(rows[idx_max]['freq_hz'])}\n")

        f.write("\n")
    return path


def generate_plot(prefix: str, rows: list[dict], component: str,
                  ind_params: dict | None, cap_params: dict | None) -> str:
    freqs_hz  = [r['freq_hz'] for r in rows]
    z_mags    = [r['z_mag']   for r in rows]
    phases    = [r['phase_deg'] for r in rows]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
    fig.suptitle(
        f"RF Impedance — {component.capitalize()}\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=12,
    )

    # --- |Z| panel ---
    ax1.loglog(freqs_hz, z_mags, color="#1f77b4", linewidth=1.5, label="|Z| measured")

    # Theoretical overlay for inductors
    if ind_params is not None and not math.isnan(ind_params['nominal_L_h']):
        L = ind_params['nominal_L_h']
        xl_theory = [2.0 * math.pi * f * L for f in freqs_hz]
        ax1.loglog(freqs_hz, xl_theory, color="orange", linewidth=1.0,
                   linestyle="--", alpha=0.8, label=f"Ideal Xₗ = 2πfL "
                   f"(L={L*1e6:.3f} µH)")
        if ind_params.get('srf_hz') is not None:
            ax1.axvline(ind_params['srf_hz'], color="red", linestyle=":",
                        linewidth=1.0, label=f"SRF = {format_freq_short(ind_params['srf_hz'])}")

    # Theoretical overlay for capacitors
    if cap_params is not None and not math.isnan(cap_params.get('nominal_C_f', float('nan'))):
        C = cap_params['nominal_C_f']
        xc_theory = [1.0 / (2.0 * math.pi * f * C) for f in freqs_hz]
        ax1.loglog(freqs_hz, xc_theory, color="orange", linewidth=1.0,
                   linestyle="--", alpha=0.8, label=f"Ideal Xc = 1/(2πfC) "
                   f"(C={C*1e12:.1f} pF)")
        if cap_params.get('srf_hz') is not None:
            ax1.axvline(cap_params['srf_hz'], color="red", linestyle=":",
                        linewidth=1.0, label=f"SRF = {format_freq_short(cap_params['srf_hz'])}")

    ax1.set_xlabel("Frequency (Hz)", fontsize=9)
    ax1.set_ylabel("|Z| (Ω)", fontsize=9)
    ax1.grid(True, which="both", alpha=0.3)
    ax1.legend(fontsize=8)
    ax1.tick_params(labelsize=8)
    ax1.set_xlim(freqs_hz[0], freqs_hz[-1])

    # --- Phase panel ---
    ax2.semilogx(freqs_hz, phases, color="#d62728", linewidth=1.5)
    ax2.axhline(0, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax2.axhline(90,  color="green", linestyle=":", linewidth=0.8, alpha=0.5)
    ax2.axhline(-90, color="green", linestyle=":", linewidth=0.8, alpha=0.5)
    ax2.set_xlabel("Frequency (Hz)", fontsize=9)
    ax2.set_ylabel("Phase (°)", fontsize=9)
    ax2.set_ylim(-100, 100)
    ax2.grid(True, which="both", alpha=0.3)
    ax2.tick_params(labelsize=8)
    ax2.set_xlim(freqs_hz[0], freqs_hz[-1])

    plt.tight_layout()
    path = f"{prefix}_impedance.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Waveform capture helper
# ---------------------------------------------------------------------------

def capture_both_channels(scope: SDS2000X, duration_s: float,
                           vdiv: float = 0.05) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Capture CH1 and CH2 simultaneously.

    Both channels are set to AC coupling (appropriate for the sine stimulus).
    Returns (ch1_wave, ch2_wave, sample_rate_hz).
    """
    scope.stop()
    time.sleep(0.05)

    for ch in (1, 2):
        scope._cmd(f"C{ch}:CPL A1M")     # AC coupling, 1 MΩ
        scope._cmd(f"C{ch}:VDIV {vdiv:.4f}V")

    tdiv = duration_s / 10.0
    scope._cmd(f"TDIV {tdiv:.6f}S")
    scope._cmd("TRMD AUTO")
    scope.run()
    time.sleep(duration_s + 0.5)
    scope.stop()
    time.sleep(0.15)

    waves = []
    sr    = 0.0
    for ch in (1, 2):
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
        waves.append(counts * vgain - voffset)
        if sr == 0.0 and horiz_interval > 0:
            sr = 1.0 / horiz_interval

    # Trim to equal length
    min_len = min(len(waves[0]), len(waves[1]))
    return waves[0][:min_len], waves[1][:min_len], sr


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="RF Impedance Analyzer — measure Z, R+jX, phase vs frequency",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Physical circuit (series injection):

    Source ─── R_ref (50 Ω) ─── DUT ─── GND
           CH1 ↑           CH2 ↑

Build R_ref from a precision 50 Ω metal-film resistor in a short-lead fixture.

Source options:
  SDG (default) — 100 kHz to 60 MHz, best accuracy at high frequency
  AWG           — 100 kHz to 25 MHz, phase-coherent with scope

Examples:
  python rf_impedance.py --component inductor
  python rf_impedance.py --component capacitor --start-khz 10 --stop-khz 50000
  python rf_impedance.py --component ferrite --stop-khz 60000
  python rf_impedance.py --source awg --stop-khz 25000
""",
    )

    parser.add_argument("--source", choices=["sdg", "awg"], default="sdg",
                        help="Signal source (default: sdg — wider range)")
    parser.add_argument("--start-khz", type=float, default=DEFAULT_START_KHZ,
                        help=f"Start frequency in kHz (default: {DEFAULT_START_KHZ})")
    parser.add_argument("--stop-khz", type=float, default=DEFAULT_STOP_KHZ,
                        help=f"Stop frequency in kHz (default: {DEFAULT_STOP_KHZ})")
    parser.add_argument("--points", type=int, default=DEFAULT_POINTS,
                        help=f"Number of frequency points (default: {DEFAULT_POINTS})")
    parser.add_argument("--zref", type=float, default=DEFAULT_ZREF_OHM,
                        help=f"Reference resistor value in Ω (default: {DEFAULT_ZREF_OHM:.0f})")
    parser.add_argument("--level-vpp", type=float, default=DEFAULT_LEVEL_VPP,
                        help=f"Source amplitude in Vpp (default: {DEFAULT_LEVEL_VPP:.2f})")
    parser.add_argument("--component",
                        choices=["inductor", "capacitor", "ferrite", "generic"],
                        default="generic",
                        help="Component type for plot annotations (default: generic)")
    parser.add_argument("--sdg-host", default=DEFAULT_SDG_HOST,
                        help=f"SDG1062X IP address (default: {DEFAULT_SDG_HOST})")
    parser.add_argument("--scope-host", default=DEFAULT_SCOPE_HOST,
                        help=f"SDS2504X Plus IP address (default: {DEFAULT_SCOPE_HOST})")
    parser.add_argument("--output", default=None,
                        help="Output filename prefix (default: rfz_YYYYMMDD_HHMMSS)")

    args = parser.parse_args()

    if args.output is None:
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"rfz_{ts}"

    start_hz = args.start_khz * 1e3
    stop_hz  = args.stop_khz  * 1e3

    # Validate frequency range against source
    if args.source == "awg" and stop_hz > 25e6:
        print(f"Warning: AWG max is 25 MHz — clamping stop frequency.")
        stop_hz = 25e6

    if args.source == "sdg" and stop_hz > 60e6:
        print(f"Warning: SDG max is 60 MHz — clamping stop frequency.")
        stop_hz = 60e6

    freqs_hz = log_freqs(start_hz, stop_hz, args.points)
    level_dbm = vpp_to_dbm_50(args.level_vpp)

    print(f"RF Impedance — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Component   : {args.component}")
    print(f"  Source      : {args.source.upper()}")
    print(f"  Frequency   : {format_freq(start_hz)} – {format_freq(stop_hz)}")
    print(f"  Points      : {args.points}")
    print(f"  R_ref       : {args.zref:.1f} Ω")
    print(f"  Level       : {args.level_vpp:.3f} Vpp  ({level_dbm:.1f} dBm)")
    print()

    scope = None
    sdg   = None

    try:
        print(f"Connecting to scope @ {args.scope_host} ...", end=" ", flush=True)
        scope = SDS2000X(args.scope_host)
        print(f"OK  [{scope.identify().split(',')[1].strip()}]")

        if args.source == "sdg":
            print(f"Connecting to SDG @ {args.sdg_host} ...", end=" ", flush=True)
            sdg = SDG1000X(args.sdg_host)
            print(f"OK  [{sdg.identify().split(',')[1].strip()}]")

        print()

        rows = []
        n    = len(freqs_hz)

        for idx, f in enumerate(freqs_hz):
            # Set source frequency
            if args.source == "sdg":
                sdg.set_sine(1, f, level_dbm=level_dbm)
                sdg.output_on(1)
            else:
                scope.set_awg_sine(f, amplitude_vpp=args.level_vpp)
                scope.awg_output_on()

            time.sleep(0.05)

            # Capture duration: at least 10 cycles, minimum 1 ms
            duration_s = max(0.001, 10.0 / f)

            # V/div: rough estimate based on level; CH1 will have ~full swing,
            # CH2 will be smaller across the DUT.
            vdiv = max(0.002, args.level_vpp / 4.0)

            ch1, ch2, sr = capture_both_channels(scope, duration_s, vdiv=vdiv)

            Z         = complex_impedance_series(ch1, ch2, sr,
                                                 z_ref_ohm=args.zref, freq_hz=f)
            z_mag     = abs(Z)
            z_real    = Z.real
            z_imag    = Z.imag
            phase_deg = math.degrees(cmath.phase(Z))

            # Derived quantities
            L_uh = None
            C_pf = None
            if args.component == "inductor" and z_imag > 0 and f > 0:
                L_uh = z_imag / (2.0 * math.pi * f) * 1e6
            elif args.component == "capacitor" and z_imag < 0 and f > 0:
                C_pf = -1.0 / (2.0 * math.pi * f * z_imag) * 1e12

            rows.append({
                "freq_hz":   f,
                "z_mag":     z_mag,
                "z_real":    z_real,
                "z_imag":    z_imag,
                "phase_deg": phase_deg,
                "L_uh":      L_uh,
                "C_pf":      C_pf,
            })

            # Progress
            bar_filled = int((idx + 1) / n * 20)
            bar        = "█" * bar_filled + "░" * (20 - bar_filled)
            print(f"\r  [{bar}] {idx+1:3d}/{n}  "
                  f"{format_freq_short(f):>10}  "
                  f"|Z|={z_mag:8.2f} Ω  "
                  f"∠{phase_deg:+7.1f}°",
                  end="", flush=True)

        print()  # newline after progress bar

        # Turn off source
        if args.source == "sdg":
            sdg.output_off_all()
        else:
            scope.awg_output_off()

        # Compute component-specific parameters
        z_list     = [complex(r['z_real'], r['z_imag']) for r in rows]
        freqs_list = [r['freq_hz'] for r in rows]

        ind_params = None
        cap_params = None

        if args.component == "inductor":
            ind_params = inductor_params(freqs_list, z_list)
            L_uh = ind_params['nominal_L_h'] * 1e6
            print(f"\nInductor summary:")
            print(f"  Nominal L   : {L_uh:.3f} µH  (at 1 MHz)")
            print(f"  Q factor    : {ind_params['Q_at_1mhz']:.1f}  (at 1 MHz)")
            if ind_params['srf_hz'] is not None:
                print(f"  SRF         : {format_freq(ind_params['srf_hz'])}")
            else:
                print(f"  SRF         : not found in sweep range")

        elif args.component == "capacitor":
            cap_params = capacitor_params(freqs_list, z_list)
            C_pf = cap_params['nominal_C_f'] * 1e12
            print(f"\nCapacitor summary:")
            print(f"  Nominal C   : {C_pf:.2f} pF  (at 10 kHz)")
            print(f"  ESR at SRF  : {cap_params['esr_ohm']:.3f} Ω")
            if cap_params['srf_hz'] is not None:
                print(f"  SRF         : {format_freq(cap_params['srf_hz'])}")
            else:
                print(f"  SRF         : not found in sweep range")

        else:
            z_mags  = [r['z_mag'] for r in rows]
            idx_max = int(np.argmax(z_mags))
            print(f"\n{args.component.capitalize()} summary:")
            print(f"  Peak |Z|    : {z_mags[idx_max]:.1f} Ω "
                  f"@ {format_freq(rows[idx_max]['freq_hz'])}")

        # Write outputs
        csv_path = write_csv(args.output, rows)
        txt_path = write_text(args.output, args.component, rows,
                              ind_params, cap_params, args.zref, args.source)
        png_path = generate_plot(args.output, rows, args.component,
                                 ind_params, cap_params)

        print(f"\nOutput:")
        print(f"  PNG  → {png_path}")
        print(f"  CSV  → {csv_path}")
        print(f"  TXT  → {txt_path}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ConnectionRefusedError as exc:
        print(f"\nConnection refused: {exc}")
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
        if sdg is not None:
            try:
                sdg.output_off_all()
                sdg.close()
            except Exception:
                pass
        if scope is not None:
            try:
                scope.awg_output_off()
                scope.run()
                scope.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
