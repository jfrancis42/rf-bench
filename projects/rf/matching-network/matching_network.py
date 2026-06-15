#!/usr/bin/env python3
"""
Matching Network Designer — with optional impedance measurement and verification

Computes L, pi, and T matching network component values for any source/load
impedance at a target frequency.  Optionally measures impedance using the
scope's series-injection circuit.  Optionally verifies the result after
building the network.

For complex impedances Z = R + jX, the reactive part is resonated out first
(series or shunt element), then the remaining real parts are matched.

Usage:
  python matching_network.py --z-source 50 --z-load 200 --freq 14200
  python matching_network.py --z-source 50 --z-load "12+8j" --freq 7200
  python matching_network.py --z-source 200 --z-load 50 --freq 14200 --q 3,5,10
  python matching_network.py --measure --freq 14200
  python matching_network.py --verify --freq 14200
"""

import argparse
import cmath
import json
import math
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Shared drivers
# ---------------------------------------------------------------------------

from rf_bench.siglent import SDG1000X, SDS2000X          # noqa: E402
from rf_bench.utils import (                              # noqa: E402
    format_freq, format_freq_short,
    complex_impedance_series,
    l_network, pi_network, t_network,
    capacitive_reactance, inductive_reactance,
    l_from_resonant, c_from_resonant,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SCOPE_HOST    = None  # Now uses inventory
DEFAULT_SDG_HOST      = None  # Now uses inventory
DEFAULT_FREQ_KHZ      = 14_200
DEFAULT_Z_SOURCE      = 50.0
DEFAULT_Z_REF_OHM     = 50.0
DEFAULT_MEAS_LEVEL_VPP = 0.2         # small-signal excitation for impedance measurement
MEAS_DURATION_S       = 2.0          # capture duration per measurement
MEAS_MIN_CYCLES       = 20


# ---------------------------------------------------------------------------
# Parse complex impedance from string
# ---------------------------------------------------------------------------

def parse_complex_z(s: str) -> complex:
    """
    Parse a complex impedance string.
    Accepts: '50', '200', '12+8j', '50-10j', '12+8J', etc.
    Returns complex (real-only strings have imag=0).
    """
    s = s.strip().replace(' ', '')
    try:
        return complex(float(s))
    except ValueError:
        pass
    # Python's complex() handles '12+8j' directly
    try:
        return complex(s)
    except ValueError:
        raise ValueError(f"Cannot parse impedance: '{s}' — use '50' or '50+10j'")


# ---------------------------------------------------------------------------
# Smith chart
# ---------------------------------------------------------------------------

def draw_smith_chart(ax: plt.Axes,
                     z_source_norm: complex,
                     z_load_norm: complex) -> None:
    """
    Draw a normalized Smith chart with constant-R and constant-X circles,
    then plot z_source_norm and z_load_norm as colored markers.

    Normalization: Z_norm = Z / Z0 (Z0 = 50 Ω typically)
    Reflection coefficient: Γ = (Z_norm − 1) / (Z_norm + 1)
    """

    def z_to_gamma(z_norm: complex) -> complex:
        """Convert normalized impedance to reflection coefficient Γ."""
        if abs(z_norm + 1.0) < 1e-12:
            return complex(1.0, 0.0)
        return (z_norm - 1.0) / (z_norm + 1.0)

    def r_circle_params(r: float) -> tuple[float, float, float]:
        """
        Centre and radius of constant-R circle in Γ plane.
        Centre: (r/(r+1), 0),  radius: 1/(r+1)
        """
        return r / (r + 1.0), 0.0, 1.0 / (r + 1.0)

    def x_circle_params(x: float) -> tuple[float, float, float]:
        """
        Centre and radius of constant-X circle in Γ plane.
        Centre: (1, 1/x),  radius: 1/|x|
        """
        if abs(x) < 1e-12:
            return 1.0, 0.0, 1e6  # degenerate — the real axis
        return 1.0, 1.0 / x, 1.0 / abs(x)

    theta = np.linspace(0, 2 * math.pi, 400)

    ax.set_aspect('equal')
    ax.set_xlim(-1.15, 1.15)
    ax.set_ylim(-1.15, 1.15)
    ax.axis('off')

    # Outer unit circle (|Γ| = 1, pure reactance boundary)
    ax.plot(np.cos(theta), np.sin(theta), 'k-', linewidth=1.2)

    # Constant-R circles
    r_values = [0.0, 0.5, 1.0, 2.0, 5.0]
    for r in r_values:
        cx, cy, rad = r_circle_params(r)
        # Clip to |Γ| ≤ 1
        t = np.linspace(0, 2 * math.pi, 400)
        xpts = cx + rad * np.cos(t)
        ypts = cy + rad * np.sin(t)
        mask = xpts ** 2 + ypts ** 2 <= 1.0 + 1e-6
        # Draw as a continuous line (gaps where outside unit circle are fine)
        ax.plot(xpts, ypts, color='#aaaaaa', linewidth=0.6)
        if r in (0.0, 1.0):
            ax.plot(xpts, ypts, color='#888888', linewidth=0.9)
        # Label R circle at top of circle (positive X side)
        label_x = cx + rad * math.cos(math.pi / 4) * 0.85
        label_y = cy + rad * math.sin(math.pi / 4) * 0.85
        if label_x ** 2 + label_y ** 2 < 1.0:
            ax.text(label_x, label_y,
                    f'R={r:.0f}' if r >= 1 else f'R={r}',
                    fontsize=5.5, ha='center', va='center', color='#666666')

    # Constant-X arcs (both positive and negative)
    x_values = [0.5, 1.0, 2.0, 5.0]
    for x in x_values:
        for sign in (+1, -1):
            xv = sign * x
            cx, cy, rad = x_circle_params(xv)
            t    = np.linspace(0, 2 * math.pi, 800)
            xpts = cx + rad * np.cos(t)
            ypts = cy + rad * np.sin(t)
            mask = (xpts ** 2 + ypts ** 2 <= 1.0 + 1e-4)
            if np.any(mask):
                # Only draw the segments inside the unit circle
                ax.plot(xpts[mask], ypts[mask], color='#aaaaaa', linewidth=0.6)

    # Real axis
    ax.plot([-1.0, 1.0], [0.0, 0.0], color='#888888', linewidth=0.7)

    # Plot source and load impedance points
    g_src = z_to_gamma(z_source_norm)
    g_ld  = z_to_gamma(z_load_norm)

    ax.plot(g_src.real, g_src.imag, 'bs', markersize=9, zorder=5,
            label=f'Source  Z={z_source_norm.real:.1f}{z_source_norm.imag:+.1f}j Ω')
    ax.plot(g_ld.real,  g_ld.imag,  'r^', markersize=9, zorder=5,
            label=f'Load    Z={z_load_norm.real:.1f}{z_load_norm.imag:+.1f}j Ω')

    ax.legend(fontsize=7, loc='lower left')
    ax.set_title("Smith Chart (Z₀ = 50 Ω normalized)", fontsize=9)


# ---------------------------------------------------------------------------
# Impedance measurement via scope series injection
# ---------------------------------------------------------------------------

def measure_impedance(scope: SDS2000X, sdg: SDG1000X,
                      freq_hz: float,
                      z_ref_ohm: float,
                      label: str = "DUT") -> complex:
    """
    Measure complex impedance using the series injection circuit:

        SDG CH1 → z_ref_ohm → DUT → GND
                CH1 ↑        CH2 ↑

    Returns complex Z in ohms.
    """
    from rf_bench.utils import vpp_to_dbm
from rf_bench import connect

    level_vpp = DEFAULT_MEAS_LEVEL_VPP
    level_dbm = vpp_to_dbm(level_vpp)

    # Capture duration: enough cycles for FFT resolution
    dur_s = max(0.02, MEAS_MIN_CYCLES / freq_hz)
    dur_s = min(dur_s, 5.0)

    sdg.set_sine(1, freq_hz, level_dbm)
    sdg.output_on(1)
    time.sleep(0.1)

    print(f"  Measuring {label} @ {format_freq_short(freq_hz)} "
          f"(Vpp={level_vpp:.3f}, dur={dur_s:.3f} s) ...", end=' ', flush=True)

    ch1_v, sr = scope.capture_audio(channel=1, duration_s=dur_s)
    ch2_v, _  = scope.capture_audio(channel=2, duration_s=dur_s)

    Z = complex_impedance_series(ch1_v, ch2_v, sr, z_ref_ohm=z_ref_ohm,
                                  freq_hz=freq_hz)
    print(f"Z = {Z.real:.2f}{Z.imag:+.2f}j Ω  |Z| = {abs(Z):.2f} Ω")
    return Z


# ---------------------------------------------------------------------------
# Resonance-cancel for complex Z
# ---------------------------------------------------------------------------

def cancel_reactance(z: complex, freq_hz: float) -> tuple[dict, float, float]:
    """
    For a complex impedance Z = R + jX, compute the series or shunt
    element needed to cancel the reactance, leaving only R.

    Returns:
        (cancel_info dict, r_effective, x_cancel)

    cancel_info keys:
        type         : 'series_C', 'series_L', 'shunt_C', 'shunt_L', or 'none'
        value_f_or_h : component value (Farads or Henries)
        value_str    : human-readable string
    """
    r = z.real
    x = z.imag
    omega = 2.0 * math.pi * freq_hz

    if abs(x) < 1e-6:
        return {'type': 'none', 'value_f_or_h': 0.0, 'value_str': 'none'}, r, 0.0

    # Series cancel: add -jX in series
    if x > 0:
        # Series inductive → cancel with series C
        c_val = 1.0 / (omega * x)
        val_str = f"series C = {c_val * 1e12:.2f} pF"
        info = {'type': 'series_C', 'value_f_or_h': c_val, 'value_str': val_str}
    else:
        # Series capacitive → cancel with series L
        l_val = -x / omega
        val_str = f"series L = {l_val * 1e9:.2f} nH"
        info = {'type': 'series_L', 'value_f_or_h': l_val, 'value_str': val_str}

    return info, r, x


# ---------------------------------------------------------------------------
# Design all topologies
# ---------------------------------------------------------------------------

def design_networks(z_source: complex,
                    z_load: complex,
                    freq_hz: float,
                    q_values: list[float]) -> dict:
    """
    Design L, pi, and T networks for the given impedances.

    For complex Z, the reactive part is cancelled first with a series element,
    then the real parts are matched.

    Returns a dict with keys: 'l', 'pi', 't', 'z_source', 'z_load',
    'freq_hz', 'cancel_source', 'cancel_load'.
    """
    cancel_src, r_src, x_src = cancel_reactance(z_source, freq_hz)
    cancel_ld,  r_ld,  x_ld  = cancel_reactance(z_load,   freq_hz)

    result = {
        'z_source': z_source,
        'z_load':   z_load,
        'freq_hz':  freq_hz,
        'r_source': r_src,
        'r_load':   r_ld,
        'cancel_source': cancel_src,
        'cancel_load':   cancel_ld,
        'l':   None,
        'pi':  [],
        't':   [],
    }

    # L-network — Q is determined by impedance ratio; cannot choose Q freely
    if abs(r_src - r_ld) > 0.1:
        try:
            result['l'] = l_network(r_src, r_ld, freq_hz)
        except ValueError as exc:
            result['l'] = {'error': str(exc)}
    else:
        result['l'] = {'error': 'Source and load resistances are equal — '
                                 'no L-network needed (use direct connection or pi/T with Q)'}

    # Q_min for pi and T networks
    if r_src > 0 and r_ld > 0:
        r_high  = max(r_src, r_ld)
        r_low   = min(r_src, r_ld)
        q_min   = math.sqrt(r_high / r_low - 1.0) if r_high != r_low else 0.0

        if not q_values:
            # Auto Q values: q_min × [1.5, 2, 3, 5, 10]
            q_values = sorted(set([
                round(q_min * m, 2)
                for m in [1.5, 2.0, 3.0, 5.0, 10.0]
                if q_min * m > q_min + 0.01
            ]))
            if not q_values:
                q_values = [max(2.0, q_min * 1.5)]

        for q in q_values:
            if q <= q_min:
                result['pi'].append({'q': q, 'error': f'Q={q:.2f} ≤ Q_min={q_min:.2f}'})
                result['t'].append({'q': q, 'error': f'Q={q:.2f} ≤ Q_min={q_min:.2f}'})
                continue
            try:
                pi = pi_network(r_src, r_ld, freq_hz, q)
                pi['q_requested'] = q
                result['pi'].append(pi)
            except ValueError as exc:
                result['pi'].append({'q': q, 'error': str(exc)})
            try:
                t = t_network(r_src, r_ld, freq_hz, q)
                t['q_requested'] = q
                result['t'].append(t)
            except ValueError as exc:
                result['t'].append({'q': q, 'error': str(exc)})

    return result


# ---------------------------------------------------------------------------
# Format component tables
# ---------------------------------------------------------------------------

def format_networks(result: dict) -> str:
    """Return a human-readable string of all network designs."""
    freq_hz  = result['freq_hz']
    z_src    = result['z_source']
    z_ld     = result['z_load']
    r_src    = result['r_source']
    r_ld     = result['r_load']
    c_src    = result['cancel_source']
    c_ld     = result['cancel_load']

    sep   = '=' * 72
    lines = [
        sep,
        '  MATCHING NETWORK DESIGN',
        f'  Generated  : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'  Frequency  : {format_freq(freq_hz)}',
        f'  Z source   : {z_src.real:.2f}{z_src.imag:+.2f}j Ω',
        f'  Z load     : {z_ld.real:.2f}{z_ld.imag:+.2f}j Ω',
        sep,
    ]

    # Reactance cancellation notice
    if c_src['type'] != 'none':
        lines += [
            '',
            f'  Note: Source reactance X_source = {z_src.imag:+.2f} Ω',
            f'        Cancel with: {c_src["value_str"]}',
            f'        Effective source R = {r_src:.2f} Ω',
        ]
    if c_ld['type'] != 'none':
        lines += [
            '',
            f'  Note: Load reactance X_load = {z_ld.imag:+.2f} Ω',
            f'        Cancel with: {c_ld["value_str"]}',
            f'        Effective load R = {r_ld:.2f} Ω',
        ]

    # ----- L-network -----
    lines += ['', sep, '']
    net_l = result['l']
    if net_l is None:
        lines.append('  L-NETWORK: not computed')
    elif 'error' in net_l:
        lines.append(f'  L-NETWORK: {net_l["error"]}')
    else:
        q      = net_l['q']
        r_high = net_l['r_high']
        r_low  = net_l['r_low']
        port   = net_l['high_z_port']
        lp     = net_l['low_pass']
        hp     = net_l['high_pass']
        lines += [
            f'  L-NETWORK  (Q = {q:.2f})',
            f'  High-Z port: {port}   R_high={r_high:.1f} Ω   R_low={r_low:.1f} Ω',
            '',
            f'  Low-pass:   Shunt C  = {lp["shunt_c_f"] * 1e12:8.2f} pF'
            f'     Series L  = {lp["series_l_h"] * 1e9:8.2f} nH',
            f'  High-pass:  Shunt L  = {hp["shunt_l_h"] * 1e9:8.2f} nH'
            f'     Series C  = {hp["series_c_f"] * 1e12:8.2f} pF',
        ]

    # ----- Pi-networks -----
    if result['pi']:
        lines += ['', sep, '']
        for pi in result['pi']:
            if 'error' in pi:
                lines.append(f'  PI-NETWORK  Q={pi["q"]:.1f}: {pi["error"]}')
                continue
            q     = pi['q_requested']
            q_min = pi['q_min']
            lp    = pi['low_pass']
            hp    = pi['high_pass']
            lines += [
                f'  PI-NETWORK  Q = {q:.1f}  (Q_min = {q_min:.2f})',
                '',
                f'  Low-pass:   C_source = {lp["shunt_source_c_f"] * 1e12:8.2f} pF'
                f'   L = {lp["series_l_h"] * 1e9:8.2f} nH'
                f'   C_load = {lp["shunt_load_c_f"] * 1e12:8.2f} pF',
                f'  High-pass:  L_source = {hp["shunt_source_l_h"] * 1e9:8.2f} nH'
                f'   C = {hp["series_c_f"] * 1e12:8.2f} pF'
                f'   L_load = {hp["shunt_load_l_h"] * 1e9:8.2f} nH',
                '',
            ]

    # ----- T-networks -----
    if result['t']:
        lines += ['', sep, '']
        for t in result['t']:
            if 'error' in t:
                lines.append(f'  T-NETWORK  Q={t["q"]:.1f}: {t["error"]}')
                continue
            q     = t['q_requested']
            q_min = t['q_min']
            lp    = t['low_pass']
            hp    = t['high_pass']
            lines += [
                f'  T-NETWORK  Q = {q:.1f}  (Q_min = {q_min:.2f})',
                '',
                f'  Low-pass:   L_source = {lp["series_source_l_h"] * 1e9:8.2f} nH'
                f'   C = {lp["shunt_c_f"] * 1e12:8.2f} pF'
                f'   L_load = {lp["series_load_l_h"] * 1e9:8.2f} nH',
                f'  High-pass:  C_source = {hp["series_source_c_f"] * 1e12:8.2f} pF'
                f'   L = {hp["shunt_l_h"] * 1e9:8.2f} nH'
                f'   C_load = {hp["series_load_c_f"] * 1e12:8.2f} pF',
                '',
            ]

    lines.append(sep)
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Plotting: Smith chart + component table
# ---------------------------------------------------------------------------

def generate_plot(result: dict, output_prefix: str) -> str:
    """Generate Smith chart + component text panel.  Returns saved file path."""
    z_src    = result['z_source']
    z_ld     = result['z_load']
    freq_hz  = result['freq_hz']
    z0       = 50.0  # normalization impedance

    z_src_norm = z_src / z0
    z_ld_norm  = z_ld  / z0

    fig = plt.figure(figsize=(14, 8))
    fig.suptitle(
        f"Matching Network Design  —  {format_freq_short(freq_hz)}  "
        f"—  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=12,
    )

    # Smith chart on the left
    ax_smith = fig.add_axes([0.02, 0.05, 0.45, 0.88])
    draw_smith_chart(ax_smith, z_src_norm, z_ld_norm)

    # Component table on the right as text panel
    ax_text = fig.add_axes([0.50, 0.05, 0.48, 0.88])
    ax_text.axis('off')

    table_text = format_networks(result)
    ax_text.text(
        0.0, 1.0, table_text,
        transform=ax_text.transAxes,
        fontsize=6.5,
        verticalalignment='top',
        horizontalalignment='left',
        fontfamily='monospace',
        wrap=False,
    )

    path = f"{output_prefix}.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# JSON serialization helper
# ---------------------------------------------------------------------------

def result_to_json(result: dict, output_prefix: str) -> str:
    """Serialize design result to JSON.  Returns path."""

    def _complex_str(z: complex) -> str:
        return f"{z.real:.4f}{z.imag:+.4f}j"

    def _net_or_none(n):
        if n is None:
            return None
        if 'error' in n:
            return {'error': n['error']}
        return n  # already plain dict with floats

    # Convert complex values to strings for JSON
    data = {
        'timestamp':    datetime.now().isoformat(),
        'freq_hz':      result['freq_hz'],
        'z_source':     _complex_str(result['z_source']),
        'z_load':       _complex_str(result['z_load']),
        'r_source_eff': result['r_source'],
        'r_load_eff':   result['r_load'],
        'cancel_source': result['cancel_source'],
        'cancel_load':   result['cancel_load'],
        'l_network':    _net_or_none(result['l']),
        'pi_networks':  result['pi'],
        't_networks':   result['t'],
    }

    path = f"{output_prefix}.json"
    with open(path, 'w') as fh:
        json.dump(data, fh, indent=2, default=str)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Matching Network Designer — L, pi, T topologies with Smith chart",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Physical impedance measurement circuit:
  SDG CH1 → z_ref (50 Ω) → DUT → GND
         CH1 ↑         CH2 ↑

For complex impedances (R+jX), the reactive part is resonated out with a
series or shunt element first; the remaining real parts are then matched.

Examples:
  python matching_network.py --z-source 50 --z-load 200 --freq 14200
  python matching_network.py --z-source 50 --z-load "12+8j" --freq 7200
  python matching_network.py --z-source 200 --z-load 50 --freq 14200 --q 3,5,10
  python matching_network.py --measure --freq 14200
  python matching_network.py --verify --freq 14200
""",
    )

    imp_grp = parser.add_argument_group("impedances")
    imp_grp.add_argument('--z-source', default='50', metavar='Z',
                         help="Source impedance in ohms; real or complex e.g. '50' or '50+10j' "
                              "(default 50)")
    imp_grp.add_argument('--z-load', default=None, metavar='Z',
                         help="Load impedance in ohms; real or complex e.g. '200' or '12-8j' "
                              "(required unless --measure)")
    imp_grp.add_argument('--freq', type=float, default=DEFAULT_FREQ_KHZ, metavar='KHZ',
                         help=f'Operating frequency in kHz (default {DEFAULT_FREQ_KHZ})')
    imp_grp.add_argument('--q', default=None, metavar='Q1,Q2,...',
                         help='Comma-separated Q values for pi/T networks '
                              '(default: auto, Q_min × [1.5, 2, 3, 5, 10])')

    meas_grp = parser.add_argument_group("measurement")
    meas_grp.add_argument('--scope', default=DEFAULT_SCOPE_HOST, metavar='HOST',
                          help=f'SDS2000X IP (default {DEFAULT_SCOPE_HOST})')
    meas_grp.add_argument('--sdg', default=DEFAULT_SDG_HOST, metavar='HOST',
                          help=f'SDG IP (default {DEFAULT_SDG_HOST})')
    meas_grp.add_argument('--z-ref', type=float, default=DEFAULT_Z_REF_OHM, metavar='OHM',
                          help=f'Series reference resistor in ohms (default {DEFAULT_Z_REF_OHM})')
    meas_grp.add_argument('--measure', action='store_true',
                          help='Measure load impedance first using scope+SDG series injection')
    meas_grp.add_argument('--verify', action='store_true',
                          help='Measure load Z, design network, prompt to build, re-measure')

    out_grp = parser.add_argument_group("output")
    out_grp.add_argument('--output', default=None, metavar='PREFIX',
                         help='Output filename prefix (default: timestamped)')

    args = parser.parse_args()

    if args.output is None:
        ts_str      = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.output = f"matching_network_{ts_str}"

    freq_hz = args.freq * 1_000.0

    # Parse Q values
    q_values: list[float] = []
    if args.q is not None:
        for tok in args.q.split(','):
            try:
                qv = float(tok.strip())
                if qv > 0:
                    q_values.append(qv)
            except ValueError:
                print(f"Warning: ignoring invalid Q value '{tok}'")

    # Parse source impedance
    try:
        z_source = parse_complex_z(args.z_source)
    except ValueError as exc:
        print(f"Error: --z-source: {exc}")
        sys.exit(1)

    # -------------------------------------------------------------------------
    # Instrument connection (only if measurement needed)
    # -------------------------------------------------------------------------

    scope = sdg = None
    needs_instruments = args.measure or args.verify

    if needs_instruments:
        print(f"\nConnecting to scope via inventory'} ...")
        try:
            scope = connect(args.scope or 'sds')
            print(f"  {scope.identify()}")
        except (ConnectionRefusedError, OSError) as exc:
            print(f"Cannot connect to scope: {exc}")
            sys.exit(1)

        print(f"Connecting to SDG via inventory'} ...")
        try:
            sdg = connect(args.sdg or 'sdg')
            print(f"  {sdg.identify()}")
        except (ConnectionRefusedError, OSError) as exc:
            print(f"Cannot connect to SDG: {exc}")
            if scope is not None:
                scope.close()
            sys.exit(1)

    # -------------------------------------------------------------------------
    # Determine load impedance
    # -------------------------------------------------------------------------

    try:
        if args.measure or args.verify:
            # Measure load impedance
            print(f"\n[MEASURING LOAD IMPEDANCE @ {format_freq_short(freq_hz)}]")
            z_load_meas = measure_impedance(
                scope, sdg, freq_hz, args.z_ref, label="Load"
            )
            z_load = z_load_meas
            print(f"  Measured Z_load = {z_load.real:.3f}{z_load.imag:+.3f}j Ω"
                  f"  |Z| = {abs(z_load):.3f} Ω"
                  f"  phase = {math.degrees(cmath.phase(z_load)):+.1f}°")
        elif args.z_load is not None:
            z_load = parse_complex_z(args.z_load)
        else:
            print("Error: --z-load is required unless --measure or --verify is used.")
            sys.exit(1)
    except (ValueError, RuntimeError) as exc:
        print(f"Error determining load impedance: {exc}")
        sys.exit(1)
    finally:
        # Turn off SDG after measurement (leave scope running for possible verify)
        if sdg is not None and needs_instruments:
            try:
                sdg.output_off_all()
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Design networks
    # -------------------------------------------------------------------------

    print(f"\n[DESIGNING MATCHING NETWORKS]")
    print(f"  Z_source = {z_source.real:.3f}{z_source.imag:+.3f}j Ω")
    print(f"  Z_load   = {z_load.real:.3f}{z_load.imag:+.3f}j Ω")
    print(f"  Frequency = {format_freq_short(freq_hz)}")

    result = design_networks(z_source, z_load, freq_hz, q_values)

    # Print network table to stdout
    table_str = format_networks(result)
    print()
    print(table_str)

    # -------------------------------------------------------------------------
    # Save outputs
    # -------------------------------------------------------------------------

    print("\n[SAVING RESULTS]")

    txt_path = f"{args.output}.txt"
    with open(txt_path, 'w') as fh:
        fh.write(table_str + '\n')
    print(f"Text  → {txt_path}")

    json_path = result_to_json(result, args.output)
    print(f"JSON  → {json_path}")

    try:
        png_path = generate_plot(result, args.output)
        print(f"Plot  → {png_path}")
    except Exception as exc:
        print(f"Plot failed: {exc}")

    # -------------------------------------------------------------------------
    # Verify mode: prompt user to build network, then re-measure
    # -------------------------------------------------------------------------

    if args.verify and scope is not None and sdg is not None:
        print()
        print("=" * 72)
        print("  VERIFY MODE")
        print("  Build the matching network using the values above.")
        print("  Connect the NETWORK OUTPUT to the measurement circuit CH2 side.")
        input("  Press Enter when ready to re-measure ...")
        print()
        print(f"[RE-MEASURING @ {format_freq_short(freq_hz)}]")
        try:
            z_verified = measure_impedance(
                scope, sdg, freq_hz, args.z_ref, label="Network output"
            )
            # The verified impedance should ideally equal z_source
            delta_r = abs(z_verified.real - z_source.real)
            delta_x = abs(z_verified.imag - z_source.imag)
            print(f"\n  Target Z_source = {z_source.real:.3f}{z_source.imag:+.3f}j Ω")
            print(f"  Measured (with network) = {z_verified.real:.3f}{z_verified.imag:+.3f}j Ω")
            print(f"  ΔR = {delta_r:.3f} Ω   ΔX = {delta_x:.3f} Ω")
        except Exception as exc:
            print(f"  Verification measurement failed: {exc}")

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    if sdg is not None:
        try:
            sdg.output_off_all()
            sdg.close()
        except Exception:
            pass
    if scope is not None:
        try:
            scope.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
