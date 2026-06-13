#!/usr/bin/env python3
"""
Multi-point thermal profiling combining scpi-temp + scpi-heater + SDM3045X.

Spatial temperature mapping using 8-16 DS18B20 sensors in a grid, PID-controlled
chamber heating, and calibrated reference measurement from benchtop DMM.
"""

import argparse
import csv
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

try:
    from rf_bench.siglent import SDM3045X
except ImportError:
    print("ERROR: rf-bench-drivers-siglent not installed", file=sys.stderr)
    print("Install with: pip install rf-bench-drivers-siglent", file=sys.stderr)
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: requests library not installed", file=sys.stderr)
    print("Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


class ThermalProfiler:
    """Multi-point thermal profiler using ESP32 sensor arrays + DMM reference."""

    def __init__(self, esp_temp_ip: str, esp_heater_ip: str, dmm_ip: str,
                 setpoint_c: float, log_interval_sec: float):
        self.esp_temp_url = f"http://{esp_temp_ip}"
        self.esp_heater_url = f"http://{esp_heater_ip}"
        self.dmm_ip = dmm_ip
        self.setpoint_c = setpoint_c
        self.log_interval_sec = log_interval_sec

        self.dmm: Optional[SDM3045X] = None
        self.sensor_ids: List[str] = []
        self.start_time: Optional[float] = None

        # Thermal equilibrium detection
        self.equilibrium_window = deque(maxlen=int(300 / log_interval_sec))  # 5 min
        self.equilibrium_threshold_c = 1.0

    def connect(self):
        """Connect to all instruments and discover sensors."""
        print(f"Connecting to DMM at {self.dmm_ip}...")
        self.dmm = SDM3045X(self.dmm_ip)
        idn = self.dmm.query("*IDN?")
        print(f"  DMM: {idn.strip()}")

        # Configure DMM for temperature measurement
        self.dmm.write("CONF:TEMP")
        self.dmm.write("TEMP:TRAN FRTD")  # 4-wire RTD
        self.dmm.write("TEMP:UNIT C")

        print(f"\nDiscovering sensors on scpi-temp at {self.esp_temp_url}...")
        try:
            resp = requests.get(f"{self.esp_temp_url}/sensors", timeout=5)
            resp.raise_for_status()
            sensors = resp.json()
            self.sensor_ids = [s['id'] for s in sensors]
            print(f"  Found {len(self.sensor_ids)} DS18B20 sensors:")
            for i, sid in enumerate(self.sensor_ids, 1):
                print(f"    {i}. {sid}")
        except Exception as e:
            print(f"ERROR: Failed to discover sensors: {e}", file=sys.stderr)
            sys.exit(1)

        if len(self.sensor_ids) < 8:
            print(f"WARNING: Only {len(self.sensor_ids)} sensors found (expected 8-16)",
                  file=sys.stderr)

        print(f"\nConnecting to scpi-heater at {self.esp_heater_url}...")
        try:
            resp = requests.get(f"{self.esp_heater_url}/*IDN?", timeout=5)
            resp.raise_for_status()
            print(f"  Heater: {resp.text.strip()}")
        except Exception as e:
            print(f"ERROR: Failed to connect to heater: {e}", file=sys.stderr)
            sys.exit(1)

    def set_heater_setpoint(self, temp_c: float):
        """Set PID setpoint on scpi-heater."""
        try:
            resp = requests.get(f"{self.esp_heater_url}/TEMP:SETP {temp_c}", timeout=5)
            resp.raise_for_status()
            print(f"Heater setpoint: {temp_c}°C")
        except Exception as e:
            print(f"ERROR: Failed to set heater setpoint: {e}", file=sys.stderr)
            sys.exit(1)

    def enable_heater(self, enable: bool):
        """Enable/disable PID control."""
        state = "ON" if enable else "OFF"
        try:
            resp = requests.get(f"{self.esp_heater_url}/OUTP {state}", timeout=5)
            resp.raise_for_status()
            print(f"Heater output: {state}")
        except Exception as e:
            print(f"ERROR: Failed to set heater output: {e}", file=sys.stderr)
            sys.exit(1)

    def read_all_sensors(self) -> Dict[str, float]:
        """Read all DS18B20 sensors simultaneously."""
        try:
            resp = requests.get(f"{self.esp_temp_url}/temperatures", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            return {item['id']: item['temperature_c'] for item in data}
        except Exception as e:
            print(f"WARNING: Failed to read sensors: {e}", file=sys.stderr)
            return {}

    def read_reference(self) -> Optional[float]:
        """Read reference thermometer via DMM."""
        try:
            temp_str = self.dmm.query("READ?")
            return float(temp_str.strip())
        except Exception as e:
            print(f"WARNING: Failed to read DMM: {e}", file=sys.stderr)
            return None

    def check_equilibrium(self, sensor_temps: Dict[str, float]) -> bool:
        """
        Check if thermal equilibrium reached.

        Criteria: all sensors within 1°C of setpoint for 5 minutes.
        """
        temps = list(sensor_temps.values())
        if not temps:
            return False

        max_deviation = max(abs(t - self.setpoint_c) for t in temps)
        self.equilibrium_window.append(max_deviation)

        if len(self.equilibrium_window) < self.equilibrium_window.maxlen:
            return False  # Not enough samples yet

        return all(dev <= self.equilibrium_threshold_c
                   for dev in self.equilibrium_window)

    def compute_statistics(self, sensor_temps: Dict[str, float],
                          ref_temp: Optional[float]) -> Dict[str, float]:
        """Compute spatial statistics."""
        temps = list(sensor_temps.values())
        if not temps:
            return {}

        stats = {
            'mean': np.mean(temps),
            'std': np.std(temps),
            'min': np.min(temps),
            'max': np.max(temps),
            'range': np.max(temps) - np.min(temps),
            'max_deviation_from_setpoint': max(abs(t - self.setpoint_c) for t in temps),
        }

        if ref_temp is not None:
            stats['reference'] = ref_temp
            stats['mean_error_vs_reference'] = stats['mean'] - ref_temp

        return stats

    def log_data(self, writer, sensor_temps: Dict[str, float],
                 ref_temp: Optional[float]):
        """Log single row to CSV."""
        elapsed = time.time() - self.start_time
        timestamp = datetime.now().isoformat()

        row = {
            'timestamp': timestamp,
            'elapsed_sec': f"{elapsed:.1f}",
            'reference_c': f"{ref_temp:.3f}" if ref_temp is not None else "N/A",
        }

        for sid in self.sensor_ids:
            temp = sensor_temps.get(sid)
            row[f"sensor_{sid[:8]}"] = f"{temp:.3f}" if temp is not None else "N/A"

        writer.writerow(row)

    def generate_heatmap(self, csv_path: Path):
        """
        Generate spatial heatmap from final equilibrium data.

        Assumes sensors are arranged in a grid (user must manually specify
        grid layout in sensor order).
        """
        # Read last row of CSV (equilibrium state)
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                print("WARNING: No data in CSV, cannot generate heatmap")
                return
            last_row = rows[-1]

        # Extract sensor temperatures
        temps = []
        for sid in self.sensor_ids:
            key = f"sensor_{sid[:8]}"
            if key in last_row and last_row[key] != "N/A":
                temps.append(float(last_row[key]))
            else:
                temps.append(np.nan)

        # Infer grid size (assume square or rectangular)
        n_sensors = len(temps)
        if n_sensors == 8:
            grid_shape = (2, 4)
        elif n_sensors == 9:
            grid_shape = (3, 3)
        elif n_sensors == 12:
            grid_shape = (3, 4)
        elif n_sensors == 16:
            grid_shape = (4, 4)
        else:
            # Default to row layout
            grid_shape = (1, n_sensors)

        print(f"\nGenerating heatmap (grid: {grid_shape[0]}×{grid_shape[1]})...")

        # Reshape temperatures into grid
        temp_grid = np.array(temps).reshape(grid_shape)

        # Create figure
        fig, ax = plt.subplots(figsize=(10, 8))

        # Custom colormap: blue (cold) → white (setpoint) → red (hot)
        colors = ['blue', 'cyan', 'white', 'yellow', 'red']
        n_bins = 100
        cmap = LinearSegmentedColormap.from_list('thermal', colors, N=n_bins)

        # Plot heatmap
        im = ax.imshow(temp_grid, cmap=cmap, aspect='auto',
                      vmin=self.setpoint_c - 2, vmax=self.setpoint_c + 2)

        # Annotate cells with temperatures
        for i in range(grid_shape[0]):
            for j in range(grid_shape[1]):
                temp = temp_grid[i, j]
                if not np.isnan(temp):
                    text_color = 'white' if abs(temp - self.setpoint_c) > 0.5 else 'black'
                    ax.text(j, i, f"{temp:.2f}°C",
                           ha="center", va="center", color=text_color, fontsize=10)

        # Colorbar
        cbar = plt.colorbar(im, ax=ax)
        cbar.set_label('Temperature (°C)', rotation=270, labelpad=20)

        # Labels
        ax.set_title(f"Thermal Profile at {self.setpoint_c}°C Setpoint\n"
                    f"Mean: {np.nanmean(temps):.2f}°C, Std: {np.nanstd(temps):.3f}°C, "
                    f"Range: {np.nanmax(temps) - np.nanmin(temps):.3f}°C")
        ax.set_xlabel("Column")
        ax.set_ylabel("Row")
        ax.set_xticks(range(grid_shape[1]))
        ax.set_yticks(range(grid_shape[0]))

        # Save
        png_path = csv_path.with_suffix('.png')
        plt.tight_layout()
        plt.savefig(png_path, dpi=150)
        print(f"Heatmap saved: {png_path}")
        plt.close()

    def run_profile(self, duration_min: float, output_path: Path):
        """Run thermal profiling experiment."""
        self.start_time = time.time()
        duration_sec = duration_min * 60

        # Set up CSV logging
        fieldnames = ['timestamp', 'elapsed_sec', 'reference_c']
        fieldnames.extend([f"sensor_{sid[:8]}" for sid in self.sensor_ids])

        print(f"\nStarting thermal profile:")
        print(f"  Setpoint: {self.setpoint_c}°C")
        print(f"  Duration: {duration_min} min")
        print(f"  Log interval: {self.log_interval_sec} sec")
        print(f"  Output: {output_path}")
        print(f"  Sensors: {len(self.sensor_ids)}")
        print()

        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            equilibrium_reached = False
            last_log_time = time.time() - self.log_interval_sec  # Log immediately

            while (time.time() - self.start_time) < duration_sec:
                now = time.time()

                if (now - last_log_time) >= self.log_interval_sec:
                    # Read all sensors
                    sensor_temps = self.read_all_sensors()
                    ref_temp = self.read_reference()

                    # Log data
                    self.log_data(writer, sensor_temps, ref_temp)
                    f.flush()

                    # Compute statistics
                    stats = self.compute_statistics(sensor_temps, ref_temp)
                    elapsed = now - self.start_time

                    print(f"[{elapsed/60:6.2f} min] ", end='')
                    print(f"Mean: {stats.get('mean', 0):.2f}°C  ", end='')
                    print(f"Std: {stats.get('std', 0):.3f}°C  ", end='')
                    print(f"Range: {stats.get('range', 0):.3f}°C  ", end='')
                    if ref_temp is not None:
                        print(f"Ref: {ref_temp:.2f}°C  ", end='')

                    # Check equilibrium
                    if not equilibrium_reached and self.check_equilibrium(sensor_temps):
                        print("✓ EQUILIBRIUM", end='')
                        equilibrium_reached = True

                    print()

                    last_log_time = now

                time.sleep(0.1)  # Fast polling for timing accuracy

        print(f"\nProfile complete. Data saved to {output_path}")

        # Generate heatmap
        self.generate_heatmap(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Multi-point thermal profiler using ESP32 sensors + DMM reference",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--esp-temp', required=True,
                       help="IP address of scpi-temp ESP32")
    parser.add_argument('--esp-heater', required=True,
                       help="IP address of scpi-heater ESP32")
    parser.add_argument('--dmm', required=True,
                       help="IP address of SDM3045X DMM")
    parser.add_argument('--setpoint-c', type=float, required=True,
                       help="Target temperature (°C)")
    parser.add_argument('--duration-min', type=float, default=30,
                       help="Total profile duration (minutes)")
    parser.add_argument('--log-interval-sec', type=float, default=10,
                       help="Data logging interval (seconds)")
    parser.add_argument('--output', type=Path,
                       help="Output CSV file path (default: auto-generated)")

    args = parser.parse_args()

    # Auto-generate output filename if not specified
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = Path(f"thermal_profile_{args.setpoint_c}C_{timestamp}.csv")

    # Create profiler
    profiler = ThermalProfiler(
        esp_temp_ip=args.esp_temp,
        esp_heater_ip=args.esp_heater,
        dmm_ip=args.dmm,
        setpoint_c=args.setpoint_c,
        log_interval_sec=args.log_interval_sec
    )

    # Connect to instruments
    profiler.connect()

    # Set heater setpoint and enable
    profiler.set_heater_setpoint(args.setpoint_c)
    profiler.enable_heater(True)

    try:
        # Run profile
        profiler.run_profile(args.duration_min, args.output)
    except KeyboardInterrupt:
        print("\n\nProfile interrupted by user.")
    finally:
        # Disable heater
        print("\nDisabling heater...")
        profiler.enable_heater(False)
        print("Done.")


if __name__ == '__main__':
    main()
