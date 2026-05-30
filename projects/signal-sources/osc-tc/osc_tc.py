#!/usr/bin/env python3
"""
Oscillator Temperature Coefficient — rf-bench-osc-tc

Measures oscillator frequency vs. temperature simultaneously.  Bus Pirate reads
a cheap I2C temperature sensor ($3 MCP9808/LM75/BMP280); SSA3032X Plus tracks
the carrier in zero-span centroid mode.  Logs both streams and produces a ppm
vs. °C plot with linear and polynomial TC fits.

This measurement is impossible with the Siglent instruments alone — none of them
can read a digital thermometer IC.  The Bus Pirate + I2C sensor fills that gap.

Usage:
    # Run for 1 hour, MCP9808 sensor, 10-second intervals
    python3 osc_tc.py --bp /dev/ttyUSB1 --carrier 14.000e6

    # Run indefinitely until Ctrl-C
    python3 osc_tc.py --bp /dev/ttyUSB1 --carrier 10e6 --duration 0

    # Re-plot from saved CSV
    python3 osc_tc.py --plot osc_tc_20260527_120000.csv

    # Specify BMP280 sensor at non-default address
    python3 osc_tc.py --sensor bmp280 --sensor-addr 0x77 --carrier 14e6
"""

import argparse
import csv
import os
import struct
import sys
import time
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
for _rel in ('..', '../rf-bench-drivers-buspirate',
             '../rf-bench-drivers-siglent', '../rf-bench-drivers-utils'):
    _p = os.path.normpath(os.path.join(_HERE, _rel))
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rf_bench.buspirate import BusPirate
from rf_bench.siglent   import SSA3000X
from rf_bench.utils     import format_freq

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ── defaults ─────────────────────────────────────────────────────────────────
SSA_HOST_DEFAULT = '10.1.1.60'
BP_PORT_DEFAULT  = '/dev/ttyUSB1'

# ─────────────────────────────────────────────────────────────────────────────
# Temperature sensor drivers
# Each returns temperature in °C (float).
# ─────────────────────────────────────────────────────────────────────────────

# ── MCP9808 ──────────────────────────────────────────────────────────────────
# I2C address: 0x18–0x1F (default 0x18, most breakouts jumper to 0x18)
# Register 0x05 = ambient temperature (2 bytes)
# Resolution: 0.0625°C, accuracy ±0.5°C
MCP9808_REG_TEMP = 0x05
MCP9808_ADDR_DEFAULT = 0x18


def mcp9808_read(bp: BusPirate, addr: int = MCP9808_ADDR_DEFAULT) -> float:
    """Read MCP9808 ambient temperature in °C."""
    raw = bp.i2c_read(addr, MCP9808_REG_TEMP, 2)
    # Upper byte: [7]=sign-extension, [6:5]=limit flags, [4:0]=T[11:8]
    # Lower byte: T[7:0]
    # T is a 13-bit 2's complement value in units of 1/16 °C
    msb, lsb = raw[0] & 0x1F, raw[1]
    temp = (msb << 8 | lsb) / 16.0
    if raw[0] & 0x10:           # sign bit
        temp -= 256.0
    return temp


# ── LM75 ─────────────────────────────────────────────────────────────────────
# I2C address: 0x48–0x4F (default 0x48)
# Register 0x00 = temperature (2 bytes, MSB first)
# Resolution: 0.5°C, accuracy ±2°C
LM75_REG_TEMP   = 0x00
LM75_ADDR_DEFAULT = 0x48


def lm75_read(bp: BusPirate, addr: int = LM75_ADDR_DEFAULT) -> float:
    """Read LM75 temperature in °C (0.5°C resolution)."""
    raw = bp.i2c_read(addr, LM75_REG_TEMP, 2)
    # MSB: T[8:1] with sign; bit 7 of LSB = T[0] (0.5°C)
    val = (raw[0] << 8 | raw[1]) >> 5   # 11-bit signed
    if val & 0x400:
        val -= 0x800
    return val * 0.125   # 0.125°C resolution (LM75B)


# ── BMP280 ────────────────────────────────────────────────────────────────────
# I2C address: 0x76 (SDO low) or 0x77 (SDO high)
# Requires reading calibration coefficients first, then raw ADC, then applying
# the Bosch compensation formula.
BMP280_ADDR_DEFAULT = 0x76
BMP280_REG_ID       = 0xD0
BMP280_REG_RESET    = 0xE0
BMP280_REG_CTRL     = 0xF4
BMP280_REG_CALIB    = 0x88   # 24 bytes of calibration data
BMP280_REG_TEMP_MSB = 0xFA


def bmp280_init(bp: BusPirate, addr: int = BMP280_ADDR_DEFAULT) -> dict:
    """
    Initialise BMP280: set normal mode + read calibration coefficients.
    Returns calibration dict {'T1':…, 'T2':…, 'T3':…}.
    """
    chip_id = bp.i2c_read(addr, BMP280_REG_ID, 1)[0]
    if chip_id not in (0x56, 0x57, 0x58, 0x60):
        raise RuntimeError(f"BMP280: unexpected chip ID 0x{chip_id:02X}")
    # ctrl_meas: osrs_t=001 (1x oversample), osrs_p=000 (skip), mode=11 (normal)
    bp.i2c_write(addr, [BMP280_REG_CTRL, 0b00100011])
    time.sleep(0.1)
    # Read 6 calibration bytes for temperature: dig_T1, dig_T2, dig_T3
    raw_cal = bp.i2c_read(addr, BMP280_REG_CALIB, 6)
    T1 = (raw_cal[1] << 8 | raw_cal[0])                    # unsigned
    T2 = struct.unpack('<h', bytes(raw_cal[2:4]))[0]        # signed
    T3 = struct.unpack('<h', bytes(raw_cal[4:6]))[0]        # signed
    return {'T1': T1, 'T2': T2, 'T3': T3}


def bmp280_read(bp: BusPirate, cal: dict,
                addr: int = BMP280_ADDR_DEFAULT) -> float:
    """Read BMP280 temperature using Bosch compensation formula.  Returns °C."""
    raw = bp.i2c_read(addr, BMP280_REG_TEMP_MSB, 3)
    adc_T = (raw[0] << 12) | (raw[1] << 4) | (raw[2] >> 4)
    T1, T2, T3 = cal['T1'], cal['T2'], cal['T3']
    var1 = (adc_T / 16384.0 - T1 / 1024.0) * T2
    var2 = ((adc_T / 131072.0 - T1 / 8192.0) ** 2) * T3
    t_fine = var1 + var2
    return t_fine / 5120.0


# ─────────────────────────────────────────────────────────────────────────────
# SSA carrier frequency measurement (zero-span centroid)
# ─────────────────────────────────────────────────────────────────────────────
_CARRIER_SPAN_HZ = 5_000   # narrow span for centroid tracking


def ssa_carrier_hz(ssa: SSA3000X, nominal_hz: float) -> float:
    """
    Measure carrier frequency via narrow-span SSA sweep centroid.
    Returns measured frequency in Hz.
    """
    start = nominal_hz - _CARRIER_SPAN_HZ / 2
    stop  = nominal_hz + _CARRIER_SPAN_HZ / 2
    ssa.setup_band(start, stop)
    ssa.single_sweep()
    trace = ssa.get_trace()
    if trace is None or len(trace) == 0:
        return nominal_hz
    freqs    = np.linspace(start, stop, len(trace))
    peak_idx = int(np.argmax(trace))
    lo, hi   = max(0, peak_idx-2), min(len(trace)-1, peak_idx+2)
    weights  = np.maximum(trace[lo:hi+1] - (np.min(trace) - 1.0), 0)
    if weights.sum() == 0:
        return float(freqs[peak_idx])
    return float(np.average(freqs[lo:hi+1], weights=weights))


# ─────────────────────────────────────────────────────────────────────────────
# Plotting
# ─────────────────────────────────────────────────────────────────────────────

def plot_tc(rows: list, nominal_hz: float, output_base: str) -> None:
    """
    Plot temperature coefficient curves from measurement rows.
    rows: list of dicts with keys: timestamp, elapsed_s, temp_c, freq_hz, ppm
    """
    if len(rows) < 3:
        print("Not enough data to plot (need at least 3 points).")
        return

    temps  = np.array([r['temp_c'] for r in rows])
    ppms   = np.array([r['ppm']    for r in rows])
    times  = np.array([r['elapsed_s'] for r in rows])

    fig = plt.figure(figsize=(12, 9))
    fig.suptitle(f"Oscillator TC — {format_freq(nominal_hz)} — "
                 f"{datetime.now():%Y-%m-%d %H:%M}", fontsize=13)
    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35)

    # Time series: temperature
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(times / 3600, temps, 'b-', lw=0.8)
    ax1.set_xlabel('Time (hours)'); ax1.set_ylabel('Temperature (°C)')
    ax1.set_title('Temperature vs. Time'); ax1.grid(True, alpha=0.3)

    # Time series: frequency deviation
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(times / 3600, ppms, 'g-', lw=0.8)
    ax2.axhline(0, color='k', lw=0.5, ls='--')
    ax2.set_xlabel('Time (hours)'); ax2.set_ylabel('Δf (ppm)')
    ax2.set_title('Frequency Deviation vs. Time'); ax2.grid(True, alpha=0.3)

    # TC scatter + fit
    ax3 = fig.add_subplot(gs[1, :])
    ax3.scatter(temps, ppms, s=8, alpha=0.5, c='b', label='Measured')
    t_range = np.linspace(temps.min(), temps.max(), 200)
    # Linear fit
    c1 = np.polyfit(temps, ppms, 1)
    ax3.plot(t_range, np.polyval(c1, t_range), 'r-', lw=1.5,
             label=f'Linear: {c1[0]:+.3f} ppm/°C')
    # 3rd-order polynomial fit (AT-cut crystal S-curve)
    if len(rows) >= 6:
        c3 = np.polyfit(temps, ppms, 3)
        ax3.plot(t_range, np.polyval(c3, t_range), 'm--', lw=1.2,
                 label=f'3rd order poly')
    ax3.set_xlabel('Temperature (°C)'); ax3.set_ylabel('Δf (ppm)')
    ax3.set_title('Frequency Deviation vs. Temperature (TC curve)')
    ax3.legend(fontsize=9); ax3.grid(True, alpha=0.3)

    t_ref   = temps.mean()
    ppm_ref = np.polyval(c1, t_ref)
    tc_ppm  = c1[0]
    ax3.text(0.02, 0.97, f"TC = {tc_ppm:+.3f} ppm/°C  (at T_ref = {t_ref:.1f}°C)",
             transform=ax3.transAxes, fontsize=9,
             verticalalignment='top',
             bbox=dict(facecolor='white', alpha=0.8, edgecolor='gray'))

    png = output_base + '.png'
    fig.savefig(png, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Plot saved: {png}")

    print(f"\nTemperature coefficient: {tc_ppm:+.4f} ppm/°C")
    print(f"Temperature range measured: {temps.min():.1f} – {temps.max():.1f} °C "
          f"(span {temps.max()-temps.min():.1f} °C)")
    print(f"Frequency deviation range: {ppms.min():+.2f} – {ppms.max():+.2f} ppm")


# ─────────────────────────────────────────────────────────────────────────────
# Main measurement loop
# ─────────────────────────────────────────────────────────────────────────────

def run_measurement(bp: BusPirate, ssa: SSA3000X,
                    carrier_hz: float, sensor: str, sensor_addr: int,
                    interval_s: float, duration_s: float,
                    csv_path: str) -> list:
    """Run continuous temperature + frequency logging loop."""

    # Initialise temperature sensor
    bp.set_pullups(True)
    bp.i2c_configure(speed_hz=100_000)
    bmp_cal = None
    if sensor == 'bmp280':
        bmp_cal = bmp280_init(bp, sensor_addr)
        print(f"BMP280 init OK (cal T1={bmp_cal['T1']}, T2={bmp_cal['T2']}, "
              f"T3={bmp_cal['T3']})")
    else:
        # Verify sensor responds
        devs = bp.i2c_scan()
        if sensor_addr not in devs:
            raise RuntimeError(
                f"{sensor.upper()} not found at 0x{sensor_addr:02X}. "
                f"Devices on bus: {[hex(a) for a in devs]}")
        print(f"{sensor.upper()} found at 0x{sensor_addr:02X}")
    bp.i2c_exit()

    # SSA setup
    ssa.preset()
    ssa.disable_tracking_generator()

    rows   = []
    t0     = time.monotonic()
    n      = 0
    print(f"\nLogging to {csv_path}  (Ctrl-C to stop)")
    print(f"{'Elapsed':>8}  {'Temp(°C)':>9}  {'Freq(Hz)':>15}  {'ppm':>8}")
    print("-" * 50)

    with open(csv_path, 'w', newline='') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(['timestamp', 'elapsed_s', 'temp_c', 'freq_hz', 'ppm'])

        try:
            while True:
                elapsed = time.monotonic() - t0
                if duration_s > 0 and elapsed >= duration_s:
                    break

                # Read temperature
                bp.set_pullups(True)
                bp.i2c_configure(speed_hz=100_000)
                try:
                    if sensor == 'mcp9808':
                        temp_c = mcp9808_read(bp, sensor_addr)
                    elif sensor == 'lm75':
                        temp_c = lm75_read(bp, sensor_addr)
                    else:  # bmp280
                        temp_c = bmp280_read(bp, bmp_cal, sensor_addr)
                except Exception as e:
                    print(f"  [WARN] Temp read failed: {e}")
                    temp_c = float('nan')
                bp.i2c_exit()

                # Measure carrier frequency
                freq_hz = ssa_carrier_hz(ssa, carrier_hz)
                ppm     = (freq_hz - carrier_hz) / carrier_hz * 1e6

                ts  = datetime.now().isoformat(timespec='seconds')
                row = dict(timestamp=ts, elapsed_s=elapsed,
                           temp_c=temp_c, freq_hz=freq_hz, ppm=ppm)
                rows.append(row)
                writer.writerow([ts, f"{elapsed:.1f}", f"{temp_c:.4f}",
                                 f"{freq_hz:.3f}", f"{ppm:.4f}"])
                csvf.flush()
                n += 1

                print(f"{elapsed:>7.0f}s  {temp_c:>9.3f}  {freq_hz:>15.3f}  {ppm:>+8.4f}")
                time.sleep(interval_s)

        except KeyboardInterrupt:
            print("\nStopped by user.")

    print(f"\n{n} samples written to {csv_path}")
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description='Oscillator temperature coefficient measurement')
    ap.add_argument('--bp',     default=BP_PORT_DEFAULT, metavar='PORT',
                    help=f'Bus Pirate port (default: {BP_PORT_DEFAULT})')
    ap.add_argument('--ssa',    default=SSA_HOST_DEFAULT, metavar='HOST',
                    help=f'SSA host (default: {SSA_HOST_DEFAULT})')
    ap.add_argument('--carrier', type=float, required=False,
                    metavar='HZ', help='Nominal carrier frequency in Hz (e.g. 14e6)')
    ap.add_argument('--sensor', default='mcp9808',
                    choices=['mcp9808', 'lm75', 'bmp280'],
                    help='I2C temperature sensor type (default: mcp9808)')
    ap.add_argument('--sensor-addr', default=None, type=lambda s: int(s, 0),
                    metavar='ADDR',
                    help='I2C address (hex OK, e.g. 0x18); default per sensor')
    ap.add_argument('--interval', type=float, default=10.0,
                    metavar='SEC', help='Measurement interval in seconds (default: 10)')
    ap.add_argument('--duration', type=float, default=3600.0,
                    metavar='SEC', help='Total run duration in seconds; 0 = run until Ctrl-C (default: 3600)')
    ap.add_argument('--output', default=None, metavar='BASE',
                    help='Output file base name (default: auto-timestamped)')
    ap.add_argument('--plot', default=None, metavar='CSV',
                    help='Re-plot from existing CSV file')
    args = ap.parse_args()

    # Re-plot mode
    if args.plot:
        rows = []
        with open(args.plot) as f:
            for r in csv.DictReader(f):
                rows.append(dict(
                    elapsed_s=float(r['elapsed_s']),
                    temp_c=float(r['temp_c']),
                    freq_hz=float(r['freq_hz']),
                    ppm=float(r['ppm']),
                ))
        carrier_hz = rows[0]['freq_hz'] if rows else 0
        base = args.plot.replace('.csv', '')
        plot_tc(rows, carrier_hz, base)
        return

    if not args.carrier:
        ap.error('--carrier is required unless --plot is specified')

    # Default sensor addresses
    sensor_defaults = {'mcp9808': 0x18, 'lm75': 0x48, 'bmp280': 0x76}
    sensor_addr = args.sensor_addr or sensor_defaults[args.sensor]

    ts   = datetime.now().strftime('%Y%m%d_%H%M%S')
    base = args.output or f"osc_tc_{ts}"
    csv_path = base + '.csv'

    print(f"Oscillator TC measurement")
    print(f"  Bus Pirate : {args.bp}")
    print(f"  SSA        : {args.ssa}")
    print(f"  Carrier    : {format_freq(args.carrier)}")
    print(f"  Sensor     : {args.sensor.upper()} at 0x{sensor_addr:02X}")
    print(f"  Interval   : {args.interval:.0f} s")
    print(f"  Duration   : {'∞ (Ctrl-C to stop)' if args.duration == 0 else f'{args.duration:.0f} s'}")
    print()

    with SSA3000X(args.ssa) as ssa, BusPirate(args.bp) as bp:
        rows = run_measurement(bp, ssa,
                               carrier_hz  = args.carrier,
                               sensor      = args.sensor,
                               sensor_addr = sensor_addr,
                               interval_s  = args.interval,
                               duration_s  = args.duration,
                               csv_path    = csv_path)

    if len(rows) >= 3:
        plot_tc(rows, args.carrier, base)
    else:
        print("Too few samples for TC plot.")


if __name__ == '__main__':
    main()
