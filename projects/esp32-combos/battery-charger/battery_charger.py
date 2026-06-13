#!/usr/bin/env python3
"""
Multi-chemistry battery charger using ESP32 instruments + bench PSU/DMM.

Combines scpi-temp (DS18B20), scpi-relay (safety cutoff), scpi-adc (terminal voltage),
SPD3303X PSU (CC/CV source), and SDM3045X DMM (precision voltage/current monitoring).

Supports:
- Lead-acid: 3-stage (bulk CC → absorption CV → float)
- LiFePO4: CC/CV with 4.2V absorption
- Li-ion: CC/CV taper to 0.05C
- NiMH: CC with -ΔV termination

Safety: temperature monitoring, voltage limits, relay gating, emergency cutoff.
"""

import argparse
import sys
import time
import sqlite3
import csv
from datetime import datetime
from enum import Enum
from dataclasses import dataclass
from typing import Optional
import pyvisa


class Chemistry(Enum):
    LEAD_ACID = "lead-acid"
    LIFEPO4 = "lifepo4"
    LIION = "li-ion"
    NIMH = "nimh"


class ChargeState(Enum):
    IDLE = "idle"
    BULK = "bulk"           # CC phase
    ABSORPTION = "absorption"  # CV phase
    FLOAT = "float"         # Maintenance (lead-acid only)
    TAPER = "taper"         # CV taper to cutoff current (lithium)
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class ChemistryProfile:
    """Charging parameters per chemistry."""
    bulk_voltage: float      # V - CC phase voltage limit
    absorption_voltage: float  # V - CV target
    float_voltage: Optional[float]  # V - maintenance voltage (lead-acid)
    bulk_current_c: float    # C-rate for bulk phase
    absorption_end_c: float  # C-rate to end absorption (switch to float or complete)
    taper_end_c: float       # C-rate to end taper (lithium)
    max_temp_c: float        # °C - emergency cutoff
    min_temp_c: float        # °C - emergency cutoff
    delta_v_mv: Optional[float]  # mV - negative delta-V termination (NiMH)
    delta_v_window: int      # samples for -ΔV detection


# Chemistry profiles (1-cell nominal voltages; scale for multi-cell)
PROFILES = {
    Chemistry.LEAD_ACID: ChemistryProfile(
        bulk_voltage=14.4,
        absorption_voltage=14.4,
        float_voltage=13.6,
        bulk_current_c=0.2,
        absorption_end_c=0.05,
        taper_end_c=0.0,  # unused
        max_temp_c=50.0,
        min_temp_c=0.0,
        delta_v_mv=None,
        delta_v_window=0,
    ),
    Chemistry.LIFEPO4: ChemistryProfile(
        bulk_voltage=3.65,
        absorption_voltage=3.65,
        float_voltage=None,
        bulk_current_c=0.5,
        absorption_end_c=0.05,
        taper_end_c=0.05,
        max_temp_c=45.0,
        min_temp_c=0.0,
        delta_v_mv=None,
        delta_v_window=0,
    ),
    Chemistry.LIION: ChemistryProfile(
        bulk_voltage=4.2,
        absorption_voltage=4.2,
        float_voltage=None,
        bulk_current_c=0.5,
        absorption_end_c=0.0,
        taper_end_c=0.05,
        max_temp_c=45.0,
        min_temp_c=0.0,
        delta_v_mv=None,
        delta_v_window=0,
    ),
    Chemistry.NIMH: ChemistryProfile(
        bulk_voltage=1.5,  # per cell; actual cutoff is -ΔV
        absorption_voltage=0.0,  # unused
        float_voltage=None,
        bulk_current_c=0.5,
        absorption_end_c=0.0,  # unused
        taper_end_c=0.0,  # unused
        max_temp_c=45.0,
        min_temp_c=0.0,
        delta_v_mv=5.0,  # -5 mV per cell typical
        delta_v_window=5,  # look at 5-sample window
    ),
}


class BatteryCharger:
    """Multi-chemistry battery charger state machine."""

    def __init__(
        self,
        esp_temp_ip: str,
        esp_relay_ip: str,
        esp_adc_ip: str,
        psu_ip: str,
        dmm_ip: str,
        chemistry: Chemistry,
        capacity_ah: float,
        charge_rate_c: float,
        cell_count: int = 1,
        use_esp_adc: bool = True,
    ):
        self.esp_temp_ip = esp_temp_ip
        self.esp_relay_ip = esp_relay_ip
        self.esp_adc_ip = esp_adc_ip
        self.psu_ip = psu_ip
        self.dmm_ip = dmm_ip
        self.chemistry = chemistry
        self.capacity_ah = capacity_ah
        self.charge_rate_c = charge_rate_c
        self.cell_count = cell_count
        self.use_esp_adc = use_esp_adc

        self.profile = PROFILES[chemistry]
        self.charge_current_a = capacity_ah * charge_rate_c

        # Scale voltages for cell count
        self.bulk_v = self.profile.bulk_voltage * cell_count
        self.absorption_v = self.profile.absorption_voltage * cell_count
        self.float_v = self.profile.float_voltage * cell_count if self.profile.float_voltage else None

        self.state = ChargeState.IDLE
        self.start_time = None
        self.ah_charged = 0.0
        self.last_sample_time = None

        # -ΔV detection for NiMH
        self.voltage_history = []
        self.delta_v_detected = False

        # VISA resources
        self.rm = pyvisa.ResourceManager()
        self.temp_sensor = None
        self.relay = None
        self.adc = None
        self.psu = None
        self.dmm = None

        # SQLite logging
        self.db_path = f"battery_charge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        self.csv_path = f"battery_charge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self._init_db()
        self._init_csv()

    def _init_db(self):
        """Create SQLite database for charge log."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE charge_log (
                timestamp REAL,
                state TEXT,
                voltage_v REAL,
                current_a REAL,
                temp_c REAL,
                ah_charged REAL
            )
            """
        )
        conn.commit()
        conn.close()

    def _init_csv(self):
        """Create CSV header."""
        with open(self.csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "state", "voltage_v", "current_a", "temp_c", "ah_charged"])

    def _log_sample(self, voltage: float, current: float, temp: float):
        """Log a sample to SQLite and CSV."""
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "INSERT INTO charge_log VALUES (?, ?, ?, ?, ?, ?)",
            (now, self.state.value, voltage, current, temp, self.ah_charged),
        )
        conn.commit()
        conn.close()

        with open(self.csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([now, self.state.value, voltage, current, temp, self.ah_charged])

    def connect(self):
        """Open VISA connections to all instruments."""
        print(f"Connecting to scpi-temp at {self.esp_temp_ip}...")
        self.temp_sensor = self.rm.open_resource(f"TCPIP::{self.esp_temp_ip}::5025::SOCKET")
        self.temp_sensor.read_termination = "\n"
        self.temp_sensor.write_termination = "\n"
        print(f"  {self.temp_sensor.query('*IDN?')}")

        print(f"Connecting to scpi-relay at {self.esp_relay_ip}...")
        self.relay = self.rm.open_resource(f"TCPIP::{self.esp_relay_ip}::5025::SOCKET")
        self.relay.read_termination = "\n"
        self.relay.write_termination = "\n"
        print(f"  {self.relay.query('*IDN?')}")

        if self.use_esp_adc:
            print(f"Connecting to scpi-adc at {self.esp_adc_ip}...")
            self.adc = self.rm.open_resource(f"TCPIP::{self.esp_adc_ip}::5025::SOCKET")
            self.adc.read_termination = "\n"
            self.adc.write_termination = "\n"
            print(f"  {self.adc.query('*IDN?')}")

        print(f"Connecting to SPD3303X PSU at {self.psu_ip}...")
        self.psu = self.rm.open_resource(f"TCPIP::{self.psu_ip}::INSTR")
        self.psu.read_termination = "\n"
        self.psu.write_termination = "\n"
        print(f"  {self.psu.query('*IDN?')}")

        print(f"Connecting to SDM3045X DMM at {self.dmm_ip}...")
        self.dmm = self.rm.open_resource(f"TCPIP::{self.dmm_ip}::INSTR")
        self.dmm.read_termination = "\n"
        self.dmm.write_termination = "\n"
        print(f"  {self.dmm.query('*IDN?')}")

    def disconnect(self):
        """Close all VISA connections."""
        if self.temp_sensor:
            self.temp_sensor.close()
        if self.relay:
            self.relay.close()
        if self.adc:
            self.adc.close()
        if self.psu:
            self.psu.close()
        if self.dmm:
            self.dmm.close()
        self.rm.close()

    def setup_instruments(self):
        """Configure PSU and relay for charging."""
        # PSU: channel 1, CC mode initially
        self.psu.write("INST CH1")
        self.psu.write(f"VOLT {self.bulk_v:.3f}")
        self.psu.write(f"CURR {self.charge_current_a:.3f}")
        self.psu.write("OUTP OFF")  # relay will gate output

        # DMM: DC voltage measurement (for current, we'll use PSU readback)
        self.dmm.write("FUNC 'VOLT:DC'")
        self.dmm.write("VOLT:DC:RANG:AUTO ON")

        # Relay: open initially (safety)
        self.relay.write("ROUT:CLOS (@1)")  # normally open relay on channel 1
        print("Relay OPEN (PSU output disconnected)")

    def read_temperature(self) -> float:
        """Read battery temperature in °C."""
        temp_str = self.temp_sensor.query("MEAS:TEMP?")
        return float(temp_str)

    def read_voltage(self) -> float:
        """Read battery terminal voltage in V."""
        if self.use_esp_adc:
            v_str = self.adc.query("MEAS:VOLT?")
            return float(v_str)
        else:
            v_str = self.dmm.query("MEAS:VOLT:DC?")
            return float(v_str)

    def read_current(self) -> float:
        """Read charge current in A (from PSU output)."""
        self.psu.write("INST CH1")
        i_str = self.psu.query("MEAS:CURR?")
        return float(i_str)

    def set_psu_voltage(self, voltage: float):
        """Set PSU voltage limit."""
        self.psu.write("INST CH1")
        self.psu.write(f"VOLT {voltage:.3f}")

    def set_psu_current(self, current: float):
        """Set PSU current limit."""
        self.psu.write("INST CH1")
        self.psu.write(f"CURR {current:.3f}")

    def enable_output(self):
        """Close relay to connect PSU to battery."""
        self.relay.write("ROUT:OPEN (@1)")
        self.psu.write("INST CH1")
        self.psu.write("OUTP ON")
        print("Relay CLOSED (PSU connected to battery)")

    def disable_output(self):
        """Open relay to disconnect PSU from battery."""
        self.psu.write("INST CH1")
        self.psu.write("OUTP OFF")
        self.relay.write("ROUT:CLOS (@1)")
        print("Relay OPEN (PSU disconnected from battery)")

    def check_safety(self, temp: float, voltage: float) -> bool:
        """Check temperature and voltage limits. Return True if safe."""
        if temp > self.profile.max_temp_c:
            print(f"ERROR: Temperature {temp:.1f}°C exceeds maximum {self.profile.max_temp_c:.1f}°C")
            self.state = ChargeState.ERROR
            return False
        if temp < self.profile.min_temp_c:
            print(f"ERROR: Temperature {temp:.1f}°C below minimum {self.profile.min_temp_c:.1f}°C")
            self.state = ChargeState.ERROR
            return False

        # Overvoltage check (10% margin above absorption voltage)
        if voltage > self.absorption_v * 1.1:
            print(f"ERROR: Voltage {voltage:.3f}V exceeds safe limit {self.absorption_v * 1.1:.3f}V")
            self.state = ChargeState.ERROR
            return False

        return True

    def detect_negative_delta_v(self, voltage: float) -> bool:
        """
        NiMH -ΔV detection: voltage drops by delta_v_mv after peak.
        Returns True if termination detected.
        """
        if self.chemistry != Chemistry.NIMH:
            return False

        self.voltage_history.append(voltage)
        if len(self.voltage_history) < self.profile.delta_v_window:
            return False

        # Keep only the window
        if len(self.voltage_history) > self.profile.delta_v_window:
            self.voltage_history.pop(0)

        # Find peak in window
        peak_v = max(self.voltage_history)
        current_v = self.voltage_history[-1]
        delta_mv = (peak_v - current_v) * 1000.0

        if delta_mv >= self.profile.delta_v_mv:
            print(f"-ΔV detected: peak {peak_v:.3f}V, current {current_v:.3f}V, delta {delta_mv:.1f} mV")
            return True

        return False

    def update_ah_charged(self, current: float):
        """Update Ah counter based on current and time delta."""
        now = time.time()
        if self.last_sample_time is not None:
            dt_h = (now - self.last_sample_time) / 3600.0
            self.ah_charged += current * dt_h
        self.last_sample_time = now

    def run_bulk(self, voltage: float, current: float, temp: float):
        """Bulk CC phase: charge at constant current until voltage reaches absorption target."""
        if self.state == ChargeState.IDLE:
            print(f"Entering BULK phase: {self.charge_current_a:.2f}A CC, target {self.absorption_v:.2f}V")
            self.state = ChargeState.BULK
            self.start_time = time.time()
            self.enable_output()

        # NiMH: check for -ΔV termination
        if self.chemistry == Chemistry.NIMH:
            if self.detect_negative_delta_v(voltage):
                self.delta_v_detected = True
                print("NiMH charge complete: -ΔV termination")
                self.state = ChargeState.COMPLETE
                self.disable_output()
                return

        # Transition to absorption/taper when voltage reaches target
        if voltage >= self.absorption_v:
            if self.chemistry == Chemistry.LEAD_ACID:
                print(f"Transition to ABSORPTION: CV at {self.absorption_v:.2f}V")
                self.state = ChargeState.ABSORPTION
                self.set_psu_voltage(self.absorption_v)
            elif self.chemistry in [Chemistry.LIFEPO4, Chemistry.LIION]:
                print(f"Transition to TAPER: CV at {self.absorption_v:.2f}V")
                self.state = ChargeState.TAPER
                self.set_psu_voltage(self.absorption_v)

    def run_absorption(self, voltage: float, current: float, temp: float):
        """Absorption CV phase (lead-acid): hold voltage until current drops to absorption_end_c."""
        current_c = current / self.capacity_ah
        if current_c <= self.profile.absorption_end_c:
            if self.float_v is not None:
                print(f"Transition to FLOAT: {self.float_v:.2f}V maintenance")
                self.state = ChargeState.FLOAT
                self.set_psu_voltage(self.float_v)
            else:
                print("Charge complete")
                self.state = ChargeState.COMPLETE
                self.disable_output()

    def run_float(self, voltage: float, current: float, temp: float):
        """Float maintenance phase (lead-acid): hold float voltage indefinitely."""
        # Run forever until user stops; could add a time limit
        pass

    def run_taper(self, voltage: float, current: float, temp: float):
        """Taper CV phase (lithium): hold voltage until current drops to taper_end_c."""
        current_c = current / self.capacity_ah
        if current_c <= self.profile.taper_end_c:
            print("Charge complete: taper current reached")
            self.state = ChargeState.COMPLETE
            self.disable_output()

    def run_cycle(self):
        """One iteration of the charge state machine."""
        voltage = self.read_voltage()
        current = self.read_current()
        temp = self.read_temperature()

        if not self.check_safety(temp, voltage):
            self.disable_output()
            return False  # abort

        self.update_ah_charged(current)
        self._log_sample(voltage, current, temp)

        elapsed_s = time.time() - self.start_time if self.start_time else 0
        elapsed_h = elapsed_s / 3600.0
        current_c = current / self.capacity_ah

        print(
            f"[{elapsed_h:.2f}h] {self.state.value.upper()}: "
            f"V={voltage:.3f}V I={current:.3f}A ({current_c:.2f}C) "
            f"T={temp:.1f}°C Ah={self.ah_charged:.3f}"
        )

        if self.state == ChargeState.IDLE or self.state == ChargeState.BULK:
            self.run_bulk(voltage, current, temp)
        elif self.state == ChargeState.ABSORPTION:
            self.run_absorption(voltage, current, temp)
        elif self.state == ChargeState.FLOAT:
            self.run_float(voltage, current, temp)
        elif self.state == ChargeState.TAPER:
            self.run_taper(voltage, current, temp)
        elif self.state == ChargeState.COMPLETE:
            return False  # done
        elif self.state == ChargeState.ERROR:
            return False  # abort

        return True  # continue

    def run(self):
        """Main charge loop."""
        try:
            self.connect()
            self.setup_instruments()

            print(
                f"\nCharging {self.capacity_ah:.1f}Ah {self.chemistry.value} battery "
                f"({self.cell_count} cells) at {self.charge_rate_c:.2f}C ({self.charge_current_a:.2f}A)"
            )
            print(f"Profile: bulk={self.bulk_v:.2f}V, absorption={self.absorption_v:.2f}V, float={self.float_v}")
            print(f"Temp limits: {self.profile.min_temp_c:.1f}°C to {self.profile.max_temp_c:.1f}°C")
            print(f"Logging to {self.db_path} and {self.csv_path}\n")

            input("Press Enter to start charging...")

            while True:
                if not self.run_cycle():
                    break
                time.sleep(5)  # 5-second sample interval

            print(f"\nCharge {self.state.value}: {self.ah_charged:.3f} Ah delivered")

        except KeyboardInterrupt:
            print("\n\nCharge interrupted by user")
            self.disable_output()
        except Exception as e:
            print(f"\n\nERROR: {e}")
            self.disable_output()
        finally:
            self.disconnect()


def main():
    parser = argparse.ArgumentParser(
        description="Multi-chemistry battery charger using ESP32 + bench instruments"
    )
    parser.add_argument("--esp-temp", required=True, help="scpi-temp ESP32 IP address")
    parser.add_argument("--esp-relay", required=True, help="scpi-relay ESP32 IP address")
    parser.add_argument("--esp-adc", required=True, help="scpi-adc ESP32 IP address")
    parser.add_argument("--psu", required=True, help="SPD3303X PSU IP address")
    parser.add_argument("--dmm", required=True, help="SDM3045X DMM IP address")
    parser.add_argument(
        "--chemistry",
        required=True,
        choices=["lead-acid", "lifepo4", "li-ion", "nimh"],
        help="Battery chemistry",
    )
    parser.add_argument("--capacity-ah", type=float, required=True, help="Battery capacity in Ah")
    parser.add_argument(
        "--charge-rate-c",
        type=float,
        default=0.2,
        help="Charge rate in C (default: 0.2C)",
    )
    parser.add_argument(
        "--cell-count",
        type=int,
        default=1,
        help="Number of cells in series (default: 1)",
    )
    parser.add_argument(
        "--use-dmm-voltage",
        action="store_true",
        help="Use SDM3045X for voltage measurement instead of scpi-adc",
    )

    args = parser.parse_args()

    chemistry = Chemistry(args.chemistry)

    charger = BatteryCharger(
        esp_temp_ip=args.esp_temp,
        esp_relay_ip=args.esp_relay,
        esp_adc_ip=args.esp_adc,
        psu_ip=args.psu,
        dmm_ip=args.dmm,
        chemistry=chemistry,
        capacity_ah=args.capacity_ah,
        charge_rate_c=args.charge_rate_c,
        cell_count=args.cell_count,
        use_esp_adc=not args.use_dmm_voltage,
    )

    charger.run()


if __name__ == "__main__":
    main()
