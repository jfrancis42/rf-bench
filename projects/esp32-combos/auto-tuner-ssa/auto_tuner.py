#!/usr/bin/env python3
"""
Automated antenna tuner using ESP32 SCPI modules + SSA3032X tracking generator.

Orchestrates three ESP32 SCPI devices:
- scpi-tuner: stepper-driven L/C network
- scpi-ptt: TX sequencing and relay control
- scpi-swr: AD8307-based forward/reflected power measurement

Plus SSA3032X spectrum analyzer with tracking generator for calibrated RF source.

Algorithm: grid search (coarse then fine) to minimize SWR at target frequency.
"""

import argparse
import socket
import time
import csv
import sys
from datetime import datetime
from typing import Tuple, Optional

try:
    from rf_bench.siglent import SSA3000X
from rf_bench import connect
except ImportError:
    print("ERROR: rf_bench.siglent not found. Install with:")
    print("  pip install rf-bench-drivers-siglent")
    sys.exit(1)


class ESP32Device:
    """Generic ESP32 SCPI device connection."""

    def __init__(self, host: str, port: int = 5025, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        """Establish socket connection."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))

    def close(self):
        """Close socket connection."""
        if self.sock:
            self.sock.close()
            self.sock = None

    def query(self, cmd: str) -> str:
        """Send SCPI query and return response."""
        if not self.sock:
            raise RuntimeError("Not connected")
        self.sock.sendall(f"{cmd}\n".encode())
        return self.sock.recv(4096).decode().strip()

    def write(self, cmd: str):
        """Send SCPI command (no response expected)."""
        if not self.sock:
            raise RuntimeError("Not connected")
        self.sock.sendall(f"{cmd}\n".encode())


class TunerController:
    """Controls scpi-tuner stepper motor L/C network."""

    def __init__(self, esp: ESP32Device):
        self.esp = esp
        self.l_min = 0
        self.l_max = 200  # Will query actual limits on connect
        self.c_min = 0
        self.c_max = 200

    def connect(self):
        """Connect and query tuner capabilities."""
        self.esp.connect()
        # Query actual stepper limits
        try:
            self.l_max = int(self.esp.query("TUNER:L:MAX?"))
            self.c_max = int(self.esp.query("TUNER:C:MAX?"))
        except Exception as e:
            print(f"WARNING: Could not query tuner limits: {e}")
            print("Using defaults: L_MAX=200, C_MAX=200")

    def set_position(self, l_pos: int, c_pos: int):
        """Set L and C stepper positions (0-indexed steps)."""
        self.esp.write(f"TUNER:L {l_pos}")
        time.sleep(0.1)
        self.esp.write(f"TUNER:C {c_pos}")

    def get_position(self) -> Tuple[int, int]:
        """Query current L and C positions."""
        l_pos = int(self.esp.query("TUNER:L?"))
        c_pos = int(self.esp.query("TUNER:C?"))
        return l_pos, c_pos

    def save_memory(self, slot: int, l_pos: int, c_pos: int):
        """Save L/C position to non-volatile memory slot."""
        self.esp.write(f"TUNER:MEM:SAVE {slot},{l_pos},{c_pos}")

    def recall_memory(self, slot: int) -> Tuple[int, int]:
        """Recall L/C position from memory slot."""
        response = self.esp.query(f"TUNER:MEM:RECALL? {slot}")
        l_pos, c_pos = map(int, response.split(','))
        self.set_position(l_pos, c_pos)
        return l_pos, c_pos


class PTTController:
    """Controls scpi-ptt TX sequencing."""

    def __init__(self, esp: ESP32Device):
        self.esp = esp

    def connect(self):
        self.esp.connect()

    def key(self):
        """Key transmitter (close PTT relay)."""
        self.esp.write("PTT:STATE ON")

    def unkey(self):
        """Unkey transmitter (open PTT relay)."""
        self.esp.write("PTT:STATE OFF")

    def get_state(self) -> bool:
        """Query PTT state. Returns True if keyed."""
        state = self.esp.query("PTT:STATE?")
        return state.upper() == "ON"


class SWRMeter:
    """Reads scpi-swr forward/reflected power and calculates SWR."""

    def __init__(self, esp: ESP32Device):
        self.esp = esp

    def connect(self):
        self.esp.connect()

    def read_power(self) -> Tuple[float, float]:
        """Read forward and reflected power in dBm."""
        fwd_dbm = float(self.esp.query("POWER:FWD?"))
        ref_dbm = float(self.esp.query("POWER:REF?"))
        return fwd_dbm, ref_dbm

    def read_swr(self) -> float:
        """Read calculated SWR."""
        swr = float(self.esp.query("SWR?"))
        return swr


class AutoTuner:
    """Closed-loop antenna tuner orchestrator."""

    def __init__(self,
                 tuner: TunerController,
                 ptt: PTTController,
                 swr: SWRMeter,
                 ssa: SSA3000X,
                 freq_mhz: float,
                 max_iter: int = 20,
                 target_swr: float = 1.5,
                 coarse_step: int = 10,
                 fine_step: int = 2):
        self.tuner = tuner
        self.ptt = ptt
        self.swr = swr
        self.ssa = ssa
        self.freq_mhz = freq_mhz
        self.max_iter = max_iter
        self.target_swr = target_swr
        self.coarse_step = coarse_step
        self.fine_step = fine_step
        self.history = []  # (iteration, l_pos, c_pos, swr)

    def setup_ssa_tracking_gen(self):
        """Configure SSA tracking generator at target frequency."""
        print(f"Configuring SSA tracking generator at {self.freq_mhz} MHz...")

        # Set TG frequency
        self.ssa.write(f":TG:FREQ {self.freq_mhz}MHz")

        # Set TG output level (adjust as needed for your setup)
        self.ssa.write(":TG:LEV -10dBm")

        # Enable TG
        self.ssa.write(":TG:STATE ON")

        # Set analyzer center/span to see reflected power
        self.ssa.write(f":FREQ:CENT {self.freq_mhz}MHz")
        self.ssa.write(":FREQ:SPAN 1MHz")

        time.sleep(0.5)
        print("SSA tracking generator enabled.")

    def measure_swr(self) -> float:
        """Key PTT, measure SWR, unkey. Returns SWR."""
        self.ptt.key()
        time.sleep(0.2)  # Allow system to settle

        swr_value = self.swr.read_swr()

        time.sleep(0.1)
        self.ptt.unkey()
        time.sleep(0.5)  # Cool-down between measurements

        return swr_value

    def grid_search_coarse(self) -> Tuple[int, int, float]:
        """Coarse grid search across full L/C range."""
        print(f"\nCoarse grid search (step={self.coarse_step})...")

        best_swr = float('inf')
        best_l = 0
        best_c = 0

        for l_pos in range(self.tuner.l_min, self.tuner.l_max + 1, self.coarse_step):
            for c_pos in range(self.tuner.c_min, self.tuner.c_max + 1, self.coarse_step):
                self.tuner.set_position(l_pos, c_pos)
                time.sleep(0.3)  # Allow steppers to settle

                swr = self.measure_swr()
                self.history.append((len(self.history), l_pos, c_pos, swr))

                print(f"  L={l_pos:3d} C={c_pos:3d} SWR={swr:.2f}", end='')

                if swr < best_swr:
                    best_swr = swr
                    best_l = l_pos
                    best_c = c_pos
                    print(" <- BEST")
                else:
                    print()

                if best_swr <= self.target_swr:
                    print(f"Target SWR {self.target_swr} reached during coarse search!")
                    return best_l, best_c, best_swr

                if len(self.history) >= self.max_iter:
                    print(f"Max iterations {self.max_iter} reached.")
                    return best_l, best_c, best_swr

        return best_l, best_c, best_swr

    def grid_search_fine(self, center_l: int, center_c: int) -> Tuple[int, int, float]:
        """Fine grid search around a center point."""
        print(f"\nFine grid search around L={center_l}, C={center_c} (step={self.fine_step})...")

        best_swr = float('inf')
        best_l = center_l
        best_c = center_c

        # Search window: ±(coarse_step) around center
        l_min = max(self.tuner.l_min, center_l - self.coarse_step)
        l_max = min(self.tuner.l_max, center_l + self.coarse_step)
        c_min = max(self.tuner.c_min, center_c - self.coarse_step)
        c_max = min(self.tuner.c_max, center_c + self.coarse_step)

        for l_pos in range(l_min, l_max + 1, self.fine_step):
            for c_pos in range(c_min, c_max + 1, self.fine_step):
                self.tuner.set_position(l_pos, c_pos)
                time.sleep(0.3)

                swr = self.measure_swr()
                self.history.append((len(self.history), l_pos, c_pos, swr))

                print(f"  L={l_pos:3d} C={c_pos:3d} SWR={swr:.2f}", end='')

                if swr < best_swr:
                    best_swr = swr
                    best_l = l_pos
                    best_c = c_pos
                    print(" <- BEST")
                else:
                    print()

                if best_swr <= self.target_swr:
                    print(f"Target SWR {self.target_swr} reached!")
                    return best_l, best_c, best_swr

                if len(self.history) >= self.max_iter:
                    print(f"Max iterations {self.max_iter} reached.")
                    return best_l, best_c, best_swr

        return best_l, best_c, best_swr

    def tune(self) -> Tuple[int, int, float]:
        """Run full tuning sequence: coarse then fine search."""
        print(f"\n{'='*60}")
        print(f"Auto-tuning at {self.freq_mhz} MHz")
        print(f"Target SWR: {self.target_swr}")
        print(f"Max iterations: {self.max_iter}")
        print(f"{'='*60}")

        self.setup_ssa_tracking_gen()

        # Coarse search
        l_coarse, c_coarse, swr_coarse = self.grid_search_coarse()
        print(f"\nCoarse result: L={l_coarse}, C={c_coarse}, SWR={swr_coarse:.2f}")

        if swr_coarse <= self.target_swr or len(self.history) >= self.max_iter:
            return l_coarse, c_coarse, swr_coarse

        # Fine search around coarse result
        l_fine, c_fine, swr_fine = self.grid_search_fine(l_coarse, c_coarse)
        print(f"\nFine result: L={l_fine}, C={c_fine}, SWR={swr_fine:.2f}")

        return l_fine, c_fine, swr_fine

    def save_log(self, filename: str):
        """Save tuning history to CSV."""
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['iteration', 'l_position', 'c_position', 'swr'])
            writer.writerows(self.history)
        print(f"\nTuning log saved to {filename}")


def main():
    parser = argparse.ArgumentParser(
        description="Automated antenna tuner using ESP32 SCPI modules + SSA3032X",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-tune on 7.200 MHz
  %(prog)s --esp-tuner 10.1.0.100 --esp-ptt 10.1.0.101 --esp-swr 10.1.0.102 \\
           --ssa 10.1.0.50 --freq 7.200

  # Tune with higher iteration limit and tighter target
  %(prog)s --esp-tuner 10.1.0.100 --esp-ptt 10.1.0.101 --esp-swr 10.1.0.102 \\
           --ssa 10.1.0.50 --freq 14.200 --max-iter 50 --target-swr 1.3

  # Save result to memory slot 3
  %(prog)s --esp-tuner 10.1.0.100 --esp-ptt 10.1.0.101 --esp-swr 10.1.0.102 \\
           --ssa 10.1.0.50 --freq 3.750 --memory-slot 3
        """
    )

    parser.add_argument('--esp-tuner', required=True, help="IP address of scpi-tuner ESP32")
    parser.add_argument('--esp-ptt', required=True, help="IP address of scpi-ptt ESP32")
    parser.add_argument('--esp-swr', required=True, help="IP address of scpi-swr ESP32")
    parser.add_argument('--ssa', required=True, help="IP address of SSA3032X analyzer")
    parser.add_argument('--freq', type=float, required=True, help="Frequency in MHz")
    parser.add_argument('--max-iter', type=int, default=20, help="Max tuning iterations (default: 20)")
    parser.add_argument('--target-swr', type=float, default=1.5, help="Target SWR threshold (default: 1.5)")
    parser.add_argument('--coarse-step', type=int, default=10, help="Coarse search step size (default: 10)")
    parser.add_argument('--fine-step', type=int, default=2, help="Fine search step size (default: 2)")
    parser.add_argument('--memory-slot', type=int, help="Save final position to tuner memory slot (0-9)")
    parser.add_argument('--log', default=None, help="CSV log filename (default: auto_tuner_TIMESTAMP.csv)")

    args = parser.parse_args()

    # Generate log filename if not specified
    if args.log is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.log = f"auto_tuner_{timestamp}.csv"

    # Connect to all devices
    print("Connecting to devices...")

    tuner_esp = ESP32Device(args.esp_tuner)
    ptt_esp = ESP32Device(args.esp_ptt)
    swr_esp = ESP32Device(args.esp_swr)

    tuner = TunerController(tuner_esp)
    ptt = PTTController(ptt_esp)
    swr_meter = SWRMeter(swr_esp)
    ssa = connect(args.ssa or 'ssa')

    try:
        tuner.connect()
        print(f"  Tuner connected: {args.esp_tuner}")
        print(f"    L range: 0-{tuner.l_max}")
        print(f"    C range: 0-{tuner.c_max}")

        ptt.connect()
        print(f"  PTT connected: {args.esp_ptt}")

        swr_meter.connect()
        print(f"  SWR meter connected: {args.esp_swr}")

        ssa.connect()
        print(f"  SSA connected: {args.ssa}")

        # Create tuner instance
        auto_tuner = AutoTuner(
            tuner=tuner,
            ptt=ptt,
            swr=swr_meter,
            ssa=ssa,
            freq_mhz=args.freq,
            max_iter=args.max_iter,
            target_swr=args.target_swr,
            coarse_step=args.coarse_step,
            fine_step=args.fine_step
        )

        # Run tuning
        final_l, final_c, final_swr = auto_tuner.tune()

        # Summary
        print(f"\n{'='*60}")
        print(f"TUNING COMPLETE")
        print(f"{'='*60}")
        print(f"Frequency: {args.freq} MHz")
        print(f"Final position: L={final_l}, C={final_c}")
        print(f"Final SWR: {final_swr:.2f}")
        print(f"Iterations: {len(auto_tuner.history)}")

        if final_swr <= args.target_swr:
            print(f"✓ Target SWR {args.target_swr} achieved!")
        else:
            print(f"✗ Target SWR {args.target_swr} NOT achieved.")

        # Save to memory if requested
        if args.memory_slot is not None:
            print(f"\nSaving to memory slot {args.memory_slot}...")
            tuner.save_memory(args.memory_slot, final_l, final_c)
            print("Saved.")

        # Save log
        auto_tuner.save_log(args.log)

        # Disable SSA tracking generator
        print("\nDisabling SSA tracking generator...")
        ssa.write(":TG:STATE OFF")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        ptt.unkey()
        ssa.write(":TG:STATE OFF")
        sys.exit(1)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        ptt.unkey()
        ssa.write(":TG:STATE OFF")
        sys.exit(1)

    finally:
        # Clean shutdown
        ptt.unkey()
        tuner_esp.close()
        ptt_esp.close()
        swr_esp.close()
        ssa.close()


if __name__ == '__main__':
    main()
