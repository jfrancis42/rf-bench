#!/usr/bin/env python3
"""
Automated battery discharge tester combining scpi-load (or ET5406A+ via rf_bench.yertai)
with scpi-temp and scpi-adc for comprehensive cell characterization.

Monitors terminal voltage, temperature, and current during discharge. Logs data at 1 Hz
to SQLite and CSV. Integrates current for mAh/Wh capacity. Terminates at cutoff voltage
or temperature limit. Generates capacity curve plot (V vs mAh).

Supports two load options:
  - ESP32 MOSFET load (scpi-load): low power (<50W), portable
  - ET5406A+ DC load: high power (200W), on greybox at 10.1.0.16

Multi-cell testing via scpi-mux for parallel discharge testing.
"""

import argparse
import time
import socket
import sqlite3
import csv
import sys
from datetime import datetime
from pathlib import Path

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    PLOTTING_AVAILABLE = True
except ImportError:
    PLOTTING_AVAILABLE = False
    print("WARNING: matplotlib not available - plotting disabled", file=sys.stderr)


class SCPIDevice:
    """Generic SCPI device interface over TCP."""

    def __init__(self, host, port=5025, timeout=2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        """Establish connection to device."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))

    def disconnect(self):
        """Close connection."""
        if self.sock:
            self.sock.close()
            self.sock = None

    def write(self, cmd):
        """Send SCPI command."""
        if not self.sock:
            raise RuntimeError("Not connected")
        self.sock.sendall(f"{cmd}\n".encode())

    def query(self, cmd):
        """Send SCPI query and return response."""
        if not self.sock:
            raise RuntimeError("Not connected")
        self.sock.sendall(f"{cmd}\n".encode())
        response = self.sock.recv(4096).decode().strip()
        return response

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


class ET5406ADevice:
    """ET5406A+ DC load interface via rf_bench.yertai driver."""

    def __init__(self, port):
        try:
            from rf_bench.yertai import ET5406A
        except ImportError:
            raise ImportError("rf-bench-drivers-yertai not installed. Install with: pip install rf-bench-drivers-yertai")

        self.device = ET5406A(port)

    def connect(self):
        """Open serial connection."""
        self.device.connect()

    def disconnect(self):
        """Close serial connection."""
        self.device.disconnect()

    def set_current(self, amps):
        """Set constant current mode and value."""
        self.device.set_mode('CC')
        self.device.set_current(amps)

    def enable(self):
        """Enable load."""
        self.device.enable()

    def disable(self):
        """Disable load."""
        self.device.disable()

    def get_voltage(self):
        """Read terminal voltage."""
        return self.device.get_voltage()

    def get_current(self):
        """Read load current."""
        return self.device.get_current()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disable()
        self.disconnect()


class BatteryDischargeTester:
    """Automated battery discharge test coordinator."""

    def __init__(self, load, temp_device, adc_device, current_a, cutoff_v,
                 temp_limit_c, output_dir):
        self.load = load
        self.temp = temp_device
        self.adc = adc_device
        self.target_current = current_a
        self.cutoff_voltage = cutoff_v
        self.temp_limit = temp_limit_c
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Data storage
        self.timestamp_start = datetime.now()
        self.db_path = self.output_dir / f"discharge_{self.timestamp_start.strftime('%Y%m%d_%H%M%S')}.db"
        self.csv_path = self.output_dir / f"discharge_{self.timestamp_start.strftime('%Y%m%d_%H%M%S')}.csv"
        self.plot_path = self.output_dir / f"discharge_{self.timestamp_start.strftime('%Y%m%d_%H%M%S')}.png"

        self._init_database()
        self._init_csv()

    def _init_database(self):
        """Create SQLite database for logged data."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE discharge_log (
                timestamp REAL,
                elapsed_s REAL,
                voltage_v REAL,
                current_a REAL,
                temperature_c REAL,
                capacity_mah REAL,
                energy_wh REAL
            )
        ''')
        c.execute('''
            CREATE TABLE test_parameters (
                start_time TEXT,
                target_current_a REAL,
                cutoff_voltage_v REAL,
                temp_limit_c REAL,
                end_time TEXT,
                end_reason TEXT,
                total_capacity_mah REAL,
                total_energy_wh REAL
            )
        ''')
        conn.commit()
        conn.close()

    def _init_csv(self):
        """Create CSV file with headers."""
        with open(self.csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'elapsed_s', 'voltage_v', 'current_a',
                           'temperature_c', 'capacity_mah', 'energy_wh'])

    def _log_data(self, elapsed_s, voltage_v, current_a, temp_c, capacity_mah, energy_wh):
        """Log data point to database and CSV."""
        timestamp = time.time()

        # SQLite
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT INTO discharge_log VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (timestamp, elapsed_s, voltage_v, current_a, temp_c, capacity_mah, energy_wh))
        conn.commit()
        conn.close()

        # CSV
        with open(self.csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, elapsed_s, voltage_v, current_a, temp_c,
                           capacity_mah, energy_wh])

    def _save_parameters(self, end_reason, total_capacity_mah, total_energy_wh):
        """Save test parameters and results to database."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT INTO test_parameters VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            self.timestamp_start.isoformat(),
            self.target_current,
            self.cutoff_voltage,
            self.temp_limit,
            datetime.now().isoformat(),
            end_reason,
            total_capacity_mah,
            total_energy_wh
        ))
        conn.commit()
        conn.close()

    def _generate_plot(self):
        """Generate capacity curve plot (V vs mAh)."""
        if not PLOTTING_AVAILABLE:
            print("Skipping plot generation - matplotlib not available")
            return

        # Read data from database
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT capacity_mah, voltage_v, temperature_c FROM discharge_log ORDER BY elapsed_s')
        rows = c.fetchall()
        conn.close()

        if not rows:
            print("No data to plot")
            return

        capacity = [r[0] for r in rows]
        voltage = [r[1] for r in rows]
        temperature = [r[2] for r in rows]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

        # Voltage vs capacity
        ax1.plot(capacity, voltage, 'b-', linewidth=2)
        ax1.set_ylabel('Voltage (V)', fontsize=12)
        ax1.set_title(f'Battery Discharge Test - {self.target_current}A to {self.cutoff_voltage}V',
                     fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.axhline(y=self.cutoff_voltage, color='r', linestyle='--',
                   label=f'Cutoff ({self.cutoff_voltage}V)')
        ax1.legend()

        # Temperature vs capacity
        ax2.plot(capacity, temperature, 'r-', linewidth=2)
        ax2.set_xlabel('Capacity (mAh)', fontsize=12)
        ax2.set_ylabel('Temperature (°C)', fontsize=12)
        ax2.grid(True, alpha=0.3)
        if self.temp_limit:
            ax2.axhline(y=self.temp_limit, color='r', linestyle='--',
                       label=f'Limit ({self.temp_limit}°C)')
            ax2.legend()

        plt.tight_layout()
        plt.savefig(self.plot_path, dpi=150)
        print(f"\nPlot saved to {self.plot_path}")

    def run(self):
        """Execute discharge test."""
        print(f"Starting discharge test at {self.timestamp_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Target current: {self.target_current}A")
        print(f"Cutoff voltage: {self.cutoff_voltage}V")
        print(f"Temperature limit: {self.temp_limit}°C" if self.temp_limit else "Temperature limit: None")
        print(f"Output directory: {self.output_dir}")
        print()

        # Set load current and enable
        if hasattr(self.load, 'set_current'):
            self.load.set_current(self.target_current)
            self.load.enable()
        else:
            # ESP32 scpi-load
            self.load.write(f"CURR {self.target_current}")
            self.load.write("OUTP ON")

        start_time = time.time()
        last_voltage = None
        last_current = None
        last_time = start_time
        capacity_mah = 0.0
        energy_wh = 0.0
        end_reason = "unknown"

        print("Time(s)  Voltage(V)  Current(A)  Temp(°C)  Capacity(mAh)  Energy(Wh)")
        print("-" * 75)

        try:
            while True:
                current_time = time.time()
                elapsed_s = current_time - start_time

                # Read measurements
                if hasattr(self.load, 'get_voltage'):
                    # ET5406A+ has built-in voltage measurement
                    voltage_v = self.load.get_voltage()
                    current_a = self.load.get_current()
                else:
                    # ESP32 load + separate ADC
                    voltage_v = float(self.adc.query("MEAS:VOLT?"))
                    current_a = float(self.load.query("MEAS:CURR?"))

                temp_c = float(self.temp.query("MEAS:TEMP?"))

                # Integrate capacity and energy (trapezoidal method)
                if last_voltage is not None and last_current is not None:
                    dt_h = (current_time - last_time) / 3600.0  # Convert to hours
                    avg_current = (current_a + last_current) / 2.0
                    avg_voltage = (voltage_v + last_voltage) / 2.0
                    capacity_mah += avg_current * dt_h * 1000.0  # mAh
                    energy_wh += avg_voltage * avg_current * dt_h  # Wh

                last_voltage = voltage_v
                last_current = current_a
                last_time = current_time

                # Log data
                self._log_data(elapsed_s, voltage_v, current_a, temp_c, capacity_mah, energy_wh)

                # Display status
                print(f"{elapsed_s:7.1f}  {voltage_v:10.3f}  {current_a:10.3f}  "
                      f"{temp_c:8.1f}  {capacity_mah:13.1f}  {energy_wh:10.3f}")

                # Check termination conditions
                if voltage_v <= self.cutoff_voltage:
                    end_reason = "cutoff_voltage"
                    print(f"\nCutoff voltage {self.cutoff_voltage}V reached - stopping")
                    break

                if self.temp_limit and temp_c >= self.temp_limit:
                    end_reason = "temp_limit"
                    print(f"\nTemperature limit {self.temp_limit}°C reached - stopping")
                    break

                time.sleep(1.0)  # 1 Hz sampling

        except KeyboardInterrupt:
            end_reason = "user_abort"
            print("\n\nTest aborted by user")

        finally:
            # Disable load
            if hasattr(self.load, 'disable'):
                self.load.disable()
            else:
                self.load.write("OUTP OFF")

            # Save parameters
            self._save_parameters(end_reason, capacity_mah, energy_wh)

            print()
            print("=" * 75)
            print(f"Test complete - {end_reason}")
            print(f"Total capacity: {capacity_mah:.1f} mAh")
            print(f"Total energy: {energy_wh:.3f} Wh")
            print(f"Duration: {elapsed_s:.1f} seconds ({elapsed_s/60:.1f} minutes)")
            print(f"Data saved to: {self.db_path}")
            print(f"CSV saved to: {self.csv_path}")

            # Generate plot
            self._generate_plot()


def main():
    parser = argparse.ArgumentParser(
        description="Automated battery discharge tester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discharge 18650 lithium cell at 1A to 2.5V cutoff using ESP32 load
  battery_discharge.py --load-type esp32 --esp-load 10.1.0.100 \\
    --esp-temp 10.1.0.101 --esp-adc 10.1.0.102 \\
    --current-a 1.0 --cutoff-v 2.5 --temp-limit-c 50

  # Discharge NiMH cell at 0.5A to 1.0V using ET5406A+ load on greybox
  battery_discharge.py --load-type et5406a --et5406a-port /dev/ttyUSB0 \\
    --esp-temp 10.1.0.101 --current-a 0.5 --cutoff-v 1.0 --temp-limit-c 45
        """
    )

    parser.add_argument('--load-type', required=True, choices=['esp32', 'et5406a'],
                       help='Load type: esp32 (scpi-load) or et5406a (ET5406A+ on greybox)')
    parser.add_argument('--esp-load', help='ESP32 scpi-load IP address (required if --load-type esp32)')
    parser.add_argument('--et5406a-port', help='ET5406A+ serial port (required if --load-type et5406a)')
    parser.add_argument('--esp-temp', required=True, help='ESP32 scpi-temp IP address')
    parser.add_argument('--esp-adc', help='ESP32 scpi-adc IP address (not needed for ET5406A+)')
    parser.add_argument('--current-a', type=float, required=True, help='Discharge current in amperes')
    parser.add_argument('--cutoff-v', type=float, required=True, help='Cutoff voltage in volts')
    parser.add_argument('--temp-limit-c', type=float, help='Temperature limit in Celsius (optional)')
    parser.add_argument('--output-dir', default='./discharge_data',
                       help='Output directory for data files (default: ./discharge_data)')

    args = parser.parse_args()

    # Validate arguments
    if args.load_type == 'esp32':
        if not args.esp_load:
            parser.error("--esp-load required when --load-type is esp32")
        if not args.esp_adc:
            parser.error("--esp-adc required when --load-type is esp32 (no built-in voltage measurement)")
    elif args.load_type == 'et5406a':
        if not args.et5406a_port:
            parser.error("--et5406a-port required when --load-type is et5406a")

    # Create device connections
    try:
        if args.load_type == 'esp32':
            load = SCPIDevice(args.esp_load)
            load.connect()
            adc = SCPIDevice(args.esp_adc)
            adc.connect()
        else:  # et5406a
            load = ET5406ADevice(args.et5406a_port)
            load.connect()
            adc = None  # ET5406A+ has built-in voltage measurement

        temp = SCPIDevice(args.esp_temp)
        temp.connect()

        # Run test
        tester = BatteryDischargeTester(
            load=load,
            temp_device=temp,
            adc_device=adc,
            current_a=args.current_a,
            cutoff_v=args.cutoff_v,
            temp_limit_c=args.temp_limit_c,
            output_dir=args.output_dir
        )
        tester.run()

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Cleanup connections
        if args.load_type == 'esp32':
            if load and load.sock:
                load.disconnect()
            if adc and adc.sock:
                adc.disconnect()
        else:
            if load:
                load.disconnect()
        if temp and temp.sock:
            temp.disconnect()


if __name__ == '__main__':
    main()
