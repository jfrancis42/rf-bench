#!/usr/bin/env python3
"""
vna_transistor.py — HP 8712B Transistor S-Parameter Characterization

Requires HP 8712B VNA and rf-bench-drivers-hp. The HP 8712B is not currently
connected — requires KISS-488 Ethernet-GPIB adapter.

Optionally requires SPD3303X to provide Vcc and bias voltage to the transistor
fixture. Run with --no-bias to skip the SPD entirely (use an external supply).

Measures all four S-parameters (S11, S21, S12, S22) at the transistor's bias
point, then computes:

  - Maximum Available Gain (MAG) — when K >= 1 (unconditionally stable)
  - Maximum Stable Gain (MSG) — when K < 1 (potentially unstable)
  - Rollett stability factor K and auxiliary condition |Δ| < 1
  - Unilateral Figure of Merit (U) — validity of unilateral gain approximation
  - Source and load stability circles on the Smith chart

Stability formulas (Pozar, Microwave Engineering):
  Δ   = S11·S22 − S12·S21
  K   = (1 − |S11|² − |S22|² + |Δ|²) / (2·|S21·S12|)
  MAG = |S21/S12| · (K − √(K²−1))   [when K ≥ 1]
  MSG = |S21/S12|                     [when K < 1]
  U   = |S12·S21·S11·S22| / ((1−|S11|²)·(1−|S22|²))

  Source stability circle: centre = conj(S11 − Δ·conj(S22)) / (|S11|² − |Δ|²)
                           radius  = |S12·S21| / ||S11|² − |Δ|²|
  Load stability circle:   centre = conj(S22 − Δ·conj(S11)) / (|S22|² − |Δ|²)
                           radius  = |S12·S21| / ||S22|² − |Δ|²|

Outputs:
  {prefix}.png    — 4 S-param magnitudes + MAG/MSG/K vs freq + Smith chart with
                    stability circles at the selected analysis frequency
  {prefix}.txt    — tabulated freq / S-params / K / MAG or MSG
  {prefix}.json   — all data in JSON

Usage:
  python vna_transistor.py
  python vna_transistor.py --vcc 12.0 --vbias 0.7 --ch-vcc 1 --ch-bias 2
  python vna_transistor.py --no-bias --use-cal --output 2n5109_14mhz
  python vna_transistor.py --start 1000 --stop 500000 --points 401 --no-bias
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

from rf_bench.hp import HP8712B

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_VNA_HOST    = "10.1.1.70"
DEFAULT_SPD_HOST    = None  # Now uses inventory
DEFAULT_START_KHZ   = 300
DEFAULT_STOP_KHZ    = 1_300_000
DEFAULT_POINTS      = 401
DEFAULT_POWER_DBM   = -10.0
DEFAULT_AVERAGES    = 4
DEFAULT_VCC_V       = 12.0
DEFAULT_VBIAS_V     = 0.7
DEFAULT_VCC_CH      = 1
DEFAULT_BIAS_CH     = 2
DEFAULT_CURRENT_A   = 0.1    # 100 mA compliance
Z0 = 50.0


# ---------------------------------------------------------------------------
# SPD3303X bias control
# ---------------------------------------------------------------------------

def setup_bias(spd_host, vcc_ch, bias_ch, vcc_v, vbias_v, i_limit_a):
    from rf_bench.siglent import SPD3303X
from rf_bench import connect
    psu = SPD3303X(spd_host)
    psu.set_voltage(vcc_ch,  0.0)
    psu.set_voltage(bias_ch, 0.0)
    psu.set_current(vcc_ch,  i_limit_a)
    psu.set_current(bias_ch, i_limit_a)
    psu.enable(vcc_ch)
    psu.enable(bias_ch)
    time.sleep(0.2)
    psu.set_voltage(bias_ch, vbias_v)
    time.sleep(0.1)
    psu.set_voltage(vcc_ch,  vcc_v)
    time.sleep(0.3)
    v  = psu.measure_voltage(vcc_ch)
    i  = psu.measure_current(vcc_ch)
    vb = psu.measure_voltage(bias_ch)
    print(f"  Vcc  CH{vcc_ch}:  {v:.3f} V  {i*1000:.1f} mA")
    print(f"  Vbias CH{bias_ch}: {vb:.3f} V")
    return psu


def teardown_bias(psu, vcc_ch, bias_ch):
    if psu is None:
        return
    try:
        psu.set_voltage(vcc_ch,  0.0)
        psu.set_voltage(bias_ch, 0.0)
        time.sleep(0.1)
        psu.disable(vcc_ch)
        psu.disable(bias_ch)
        psu.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# S-parameter measurements
# ---------------------------------------------------------------------------

def measure_sparams(vna, params, start_hz, stop_hz, points, power_dbm, averages):
    vna.setup_sweep(start_hz, stop_hz, points)
    vna.set_power(power_dbm)
    vna.set_averaging(averages)
    print(f"  Sweep: {start_hz/1e6:.3f} – {stop_hz/1e6:.3f} MHz  {points} pts")

    # Fetch frequency axis on first sweep
    vna.set_parameter("S11")
    vna.set_format("MLOG")
    vna.single_sweep()
    freqs = vna.get_frequencies()

    result = {'freqs': freqs}
    for param in params:
        print(f"  Measuring {param}...")
        vna.set_parameter(param)
        vna.set_format("MLOG")
        vna.single_sweep()
        result[param] = vna.get_s_data()

    return result


# ---------------------------------------------------------------------------
# Stability analysis
# ---------------------------------------------------------------------------

def stability_analysis(s11, s21, s12, s22):
    delta    = s11 * s22 - s12 * s21
    a_s11    = np.abs(s11)
    a_s22    = np.abs(s22)
    a_s21    = np.abs(s21)
    a_s12    = np.abs(s12)
    a_delta  = np.abs(delta)

    denom    = 2.0 * a_s21 * a_s12
    safe_d   = np.where(denom > 1e-12, denom, np.nan)
    K        = (1 - a_s11**2 - a_s22**2 + a_delta**2) / safe_d

    # MAG / MSG in dB
    ratio    = a_s21 / np.where(a_s12 > 1e-15, a_s12, np.nan)
    Kcl      = np.clip(K, 1.0, None)
    mag      = ratio * (Kcl - np.sqrt(np.clip(Kcl**2 - 1, 0, None)))
    gain_db  = np.where(
        K >= 1,
        10.0 * np.log10(np.where(mag   > 1e-15, mag,   np.nan)),
        10.0 * np.log10(np.where(ratio > 1e-15, ratio, np.nan)))

    # Unilateral figure of merit
    U = (a_s12 * a_s21 * a_s11 * a_s22) / (
        (1 - a_s11**2) * (1 - a_s22**2))

    # Stability circle centres and radii
    ds   = a_s11**2 - a_delta**2
    safe_ds = np.where(np.abs(ds) > 1e-15, ds, np.nan)
    c_s  = np.conj(s11 - delta * np.conj(s22)) / safe_ds
    r_s  = a_s12 * a_s21 / np.abs(safe_ds)

    dl   = a_s22**2 - a_delta**2
    safe_dl = np.where(np.abs(dl) > 1e-15, dl, np.nan)
    c_l  = np.conj(s22 - delta * np.conj(s11)) / safe_dl
    r_l  = a_s12 * a_s21 / np.abs(safe_dl)

    return {
        'K': K, 'abs_delta': a_delta, 'gain_db': gain_db, 'U': U,
        'c_s': c_s, 'r_s': r_s,
        'c_l': c_l, 'r_l': r_l,
    }


# ---------------------------------------------------------------------------
# Smith chart helpers
# ---------------------------------------------------------------------------

def draw_smith_grid(ax):
    theta = np.linspace(0, 2 * np.pi, 360)
    ax.plot(np.cos(theta), np.sin(theta), '#888888', lw=0.8)
    for R in [0, 0.5, 1, 2, 5]:
        cx  = R / (1 + R)
        rad = 1 / (1 + R)
        ax.plot(cx + rad * np.cos(theta), rad * np.sin(theta), '#aaaaaa', lw=0.5)
    for X in [0.5, 1, 2, 5]:
        for sign in [+1, -1]:
            cy  = sign / X
            rad = 1.0 / X
            xp  = 1 + rad * np.cos(theta)
            yp  = cy + rad * np.sin(theta)
            mask = xp**2 + yp**2 <= 1.01
            xp[~mask] = np.nan
            yp[~mask] = np.nan
            ax.plot(xp, yp, '#aaaaaa', lw=0.5)
    ax.axhline(0, color='#aaaaaa', lw=0.5)
    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-1.3, 1.3)
    ax.set_aspect('equal')
    ax.axis('off')


def draw_stability_circle(ax, center, radius, color, label):
    theta = np.linspace(0, 2 * np.pi, 360)
    xp = center.real + radius * np.cos(theta)
    yp = center.imag + radius * np.sin(theta)
    ax.plot(xp, yp, color=color, lw=1.5, label=label)


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def make_plots(freqs, data, stab, analysis_idx, output_prefix, args):
    mhz = freqs / 1e6
    K   = stab['K']

    fig = plt.figure(figsize=(17, 10))
    fig.suptitle(
        f"Transistor S-Parameters  {freqs[0]/1e6:.3f}–{freqs[-1]/1e6:.3f} MHz"
        f"  Vcc={args.vcc:.1f}V  Vbias={args.vbias:.2f}V",
        fontsize=11)

    # Panel 1: S11 / S22
    ax1 = fig.add_subplot(2, 3, 1)
    for p, c in [('S11', 'C0'), ('S22', 'C1')]:
        if p in data:
            db = 20 * np.log10(np.clip(np.abs(data[p]), 1e-15, None))
            ax1.plot(mhz, db, c, lw=1.2, label=p)
    ax1.axhline(-10, color='gray', lw=0.7, ls='--')
    ax1.set(ylabel='Magnitude (dB)', xlabel='Frequency (MHz)', title='S11 / S22 Reflection')
    ax1.legend(fontsize=8); ax1.grid(True, alpha=0.4)

    # Panel 2: S21 / S12
    ax2 = fig.add_subplot(2, 3, 2)
    for p, c in [('S21', 'C2'), ('S12', 'C3')]:
        if p in data:
            db = 20 * np.log10(np.clip(np.abs(data[p]), 1e-15, None))
            ax2.plot(mhz, db, c, lw=1.2, label=p)
    ax2.axhline(0, color='gray', lw=0.7, ls='--')
    ax2.set(ylabel='Magnitude (dB)', xlabel='Frequency (MHz)',
            title='S21 Forward / S12 Reverse')
    ax2.legend(fontsize=8); ax2.grid(True, alpha=0.4)

    # Panel 3: K and |Δ|
    ax3 = fig.add_subplot(2, 3, 3)
    valid = np.isfinite(K)
    ax3.plot(mhz[valid], K[valid], 'C4', lw=1.2, label='K (Rollett)')
    ax3.plot(mhz[valid], stab['abs_delta'][valid], 'C5--', lw=1.0, label='|Δ|')
    ax3.axhline(1.0, color='gray', lw=0.8, ls='--')
    ax3.fill_between(mhz, 0, 1, alpha=0.07, color='red')
    ax3.set_ylim(0, min(10, max(3, float(np.nanmax(K[valid])) * 1.1)))
    ax3.set(ylabel='Value', xlabel='Frequency (MHz)',
            title='Rollett K  (shaded = potentially unstable)')
    ax3.legend(fontsize=8); ax3.grid(True, alpha=0.4)

    # Panel 4: MAG / MSG
    ax4 = fig.add_subplot(2, 3, 4)
    gdb = stab['gain_db']
    mag_m = (K >= 1) & np.isfinite(gdb)
    msg_m = (K <  1) & np.isfinite(gdb)
    if np.any(mag_m):
        ax4.plot(mhz[mag_m], gdb[mag_m], 'C2', lw=1.4, label='MAG (stable)')
    if np.any(msg_m):
        ax4.plot(mhz[msg_m], gdb[msg_m], 'C3--', lw=1.4, label='MSG (unstable)')
    ax4.axhline(0, color='gray', lw=0.7, ls='--')
    ax4.set(ylabel='Gain (dB)', xlabel='Frequency (MHz)',
            title='Max Available / Stable Gain')
    ax4.legend(fontsize=8); ax4.grid(True, alpha=0.4)

    # Panel 5: S21 phase
    ax5 = fig.add_subplot(2, 3, 5)
    if 'S21' in data:
        ax5.plot(mhz, np.degrees(np.angle(data['S21'])), 'C2', lw=1.2)
    ax5.axhline(0, color='gray', lw=0.7, ls='--')
    ax5.set_ylim(-190, 190)
    ax5.set(ylabel='Phase (°)', xlabel='Frequency (MHz)', title='S21 Phase')
    ax5.grid(True, alpha=0.4)

    # Panel 6: Smith chart + stability circles
    ax6 = fig.add_subplot(2, 3, 6)
    draw_smith_grid(ax6)
    ax6.set_title(f'Stability Circles @ {freqs[analysis_idx]/1e6:.3f} MHz'
                  f'  K={K[analysis_idx]:.3f}', fontsize=9)
    if 'S11' in data:
        g = data['S11']
        ax6.plot(g.real, g.imag, 'C0', lw=0.8, alpha=0.6, label='S11 locus')

    cs = stab['c_s'][analysis_idx]; rs = stab['r_s'][analysis_idx]
    cl = stab['c_l'][analysis_idx]; rl = stab['r_l'][analysis_idx]
    if np.isfinite(cs.real) and np.isfinite(rs):
        draw_stability_circle(ax6, cs, rs, 'C3', 'Source stab. circle')
    if np.isfinite(cl.real) and np.isfinite(rl):
        draw_stability_circle(ax6, cl, rl, 'C5', 'Load stab. circle')
    ax6.legend(fontsize=7, loc='lower right')

    plt.tight_layout()
    path = output_prefix + '.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Text and JSON outputs
# ---------------------------------------------------------------------------

def write_text(path, freqs, data, stab):
    cols = [p for p in ['S11', 'S21', 'S12', 'S22'] if p in data]
    with open(path, 'w') as f:
        hdr = f"{'Freq_MHz':>12}" + ''.join(f"  {p+'_dB':>10}" for p in cols)
        hdr += f"  {'K':>10}  {'|Delta|':>10}  {'Gain_dB':>10}"
        f.write(hdr + '\n' + '-' * len(hdr) + '\n')
        for i, freq in enumerate(freqs):
            row = f"{freq/1e6:12.6f}"
            for p in cols:
                row += f"  {20*np.log10(max(abs(data[p][i]), 1e-15)):10.3f}"
            K = stab['K'][i]; d = stab['abs_delta'][i]; g = stab['gain_db'][i]
            row += (f"  {K if np.isfinite(K) else float('nan'):10.4f}"
                    f"  {d if np.isfinite(d) else float('nan'):10.4f}"
                    f"  {g if np.isfinite(g) else float('nan'):10.3f}")
            f.write(row + '\n')


def write_json(path, freqs, data, stab, args):
    def clean(arr):
        return [x if np.isfinite(x) else None for x in arr.tolist()]
    obj = {
        'start_hz': float(freqs[0]), 'stop_hz': float(freqs[-1]),
        'points': len(freqs), 'power_dbm': args.power,
        'vcc_v': args.vcc, 'vbias_v': args.vbias,
        'freqs_hz': freqs.tolist(),
        'K': clean(stab['K']),
        'abs_delta': clean(stab['abs_delta']),
        'gain_db': clean(stab['gain_db']),
    }
    for p in ['S11', 'S21', 'S12', 'S22']:
        if p in data:
            obj[p + '_real'] = data[p].real.tolist()
            obj[p + '_imag'] = data[p].imag.tolist()
    with open(path, 'w') as f:
        json.dump(obj, f, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--host',        default=DEFAULT_VNA_HOST)
    p.add_argument('--spd-host',    default=DEFAULT_SPD_HOST)
    p.add_argument('--start',       type=float, default=DEFAULT_START_KHZ,  metavar='KHZ')
    p.add_argument('--stop',        type=float, default=DEFAULT_STOP_KHZ,   metavar='KHZ')
    p.add_argument('--points',      type=int,   default=DEFAULT_POINTS)
    p.add_argument('--power',       type=float, default=DEFAULT_POWER_DBM,  metavar='DBM')
    p.add_argument('--averages',    type=int,   default=DEFAULT_AVERAGES)
    p.add_argument('--vcc',         type=float, default=DEFAULT_VCC_V,      metavar='V')
    p.add_argument('--vbias',       type=float, default=DEFAULT_VBIAS_V,    metavar='V')
    p.add_argument('--ch-vcc',      type=int,   default=DEFAULT_VCC_CH,     metavar='CH')
    p.add_argument('--ch-bias',     type=int,   default=DEFAULT_BIAS_CH,    metavar='CH')
    p.add_argument('--ilimit',      type=float, default=DEFAULT_CURRENT_A,  metavar='A')
    p.add_argument('--no-bias',     action='store_true')
    p.add_argument('--use-cal',     action='store_true')
    p.add_argument('--params',      default='S11,S21,S12,S22')
    p.add_argument('--analysis-mhz', type=float, default=None, metavar='MHZ')
    p.add_argument('--output',      default=None)
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    if args.output is None:
        args.output = datetime.now().strftime('transistor_%Y%m%d_%H%M%S')

    params = [p.strip().upper() for p in args.params.split(',')]
    for p in params:
        if p not in ('S11', 'S21', 'S12', 'S22'):
            print(f"ERROR: unknown parameter {p!r}", file=sys.stderr)
            sys.exit(1)

    start_hz = args.start * 1e3
    stop_hz  = args.stop  * 1e3
    psu = None
    vna = None

    try:
        if not args.no_bias:
            print("[SPD3303X bias]")
            psu = setup_bias(args.spd_host, args.ch_vcc, args.ch_bias,
                             args.vcc, args.vbias, args.ilimit)
            time.sleep(0.5)

        print("[HP 8712B]")
        vna = HP8712B(args.host)
        print(f"  ID: {vna.identify()}")

        if args.use_cal:
            vna.correction_on()
            print("  Calibration: ON")
        else:
            vna.correction_off()
            print("  Calibration: OFF")

        data  = measure_sparams(vna, params, start_hz, stop_hz,
                                args.points, args.power, args.averages)
        freqs = data.pop('freqs')

        all_present = all(p in data for p in ('S11', 'S21', 'S12', 'S22'))
        if all_present:
            print("[Stability analysis]")
            stab = stability_analysis(data['S11'], data['S21'], data['S12'], data['S22'])
            K    = stab['K']
            n    = int(np.sum((K >= 1) & (stab['abs_delta'] < 1) & np.isfinite(K)))
            print(f"  Unconditionally stable: {n}/{len(freqs)} points")

            if args.analysis_mhz is not None:
                aidx = int(np.argmin(np.abs(freqs - args.analysis_mhz * 1e6)))
            elif 'S21' in data:
                aidx = int(np.argmax(np.abs(data['S21'])))
            else:
                aidx = len(freqs) // 2

            Ki = K[aidx]; di = stab['abs_delta'][aidx]; gi = stab['gain_db'][aidx]
            stable_str = 'stable' if (Ki >= 1 and di < 1) else 'POTENTIALLY UNSTABLE'
            print(f"  Analysis: {freqs[aidx]/1e6:.3f} MHz  K={Ki:.3f}  |Δ|={di:.3f}  {stable_str}")
            if np.isfinite(gi):
                label = "MAG" if Ki >= 1 else "MSG"
                print(f"  {label}: {gi:.2f} dB  U={stab['U'][aidx]:.4f}")

            print("[Outputs]")
            png = make_plots(freqs, data, stab, aidx, args.output, args)
            print(f"  {png}")
            txt = args.output + '.txt'
            write_text(txt, freqs, data, stab)
            print(f"  {txt}")
            js = args.output + '.json'
            write_json(js, freqs, data, stab, args)
            print(f"  {js}")
        else:
            print("[Outputs] (stability skipped — not all 4 params measured)")
            js = args.output + '.json'
            obj = {'freqs_hz': freqs.tolist()}
            for p in params:
                if p in data:
                    obj[p + '_real'] = data[p].real.tolist()
                    obj[p + '_imag'] = data[p].imag.tolist()
            with open(js, 'w') as f:
                json.dump(obj, f, indent=2)
            print(f"  {js}")

        print("Done.")

    finally:
        if vna is not None:
            try:
                vna.marker_off()
                vna.close()
            except Exception:
                pass
        teardown_bias(psu, args.ch_vcc, args.ch_bias)


if __name__ == '__main__':
    main()
