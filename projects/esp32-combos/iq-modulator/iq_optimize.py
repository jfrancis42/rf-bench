#!/usr/bin/env python3
"""
IQ Modulator Optimization using scpi-dac + MHS-5225A + SSA3032X

Dual-channel IQ modulator with automated DAC correction to achieve high
carrier suppression and sideband balance.

Workflow:
1. MHS-5225A generates I/Q carriers at target frequency with 90° phase offset
2. scpi-dac (MCP4728) provides I/Q DC offset trim + gain adjustment
3. External resistive combiner sums I/Q → RF output
4. SSA measures carrier suppression and sideband symmetry
5. Optimize scpi-dac settings via gradient descent or grid search
6. Save optimal DAC settings to EEPROM for future use

Target performance:
- Carrier suppression: >40 dB
- Sideband imbalance: <1 dB
"""

import argparse
import time
import numpy as np
from typing import Tuple, Dict
import sys

try:
    from rf_bench.koolertron import MHS5200A
    from rf_bench.siglent import SSA3032X
    import socket
except ImportError as e:
    print(f"Error: Missing required driver package: {e}")
    print("Install with: pip install rf-bench-drivers-koolertron rf-bench-drivers-siglent")
    sys.exit(1)


class SCPIDac:
    """Simple SCPI client for ESP32 scpi-dac (MCP4728)"""

    def __init__(self, host: str, port: int = 5025):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self):
        """Connect to scpi-dac"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        self.sock.connect((self.host, self.port))

    def disconnect(self):
        """Close connection"""
        if self.sock:
            self.sock.close()
            self.sock = None

    def send(self, cmd: str):
        """Send SCPI command"""
        self.sock.sendall(f"{cmd}\n".encode('ascii'))

    def query(self, cmd: str) -> str:
        """Send SCPI query and read response"""
        self.send(cmd)
        return self.sock.recv(4096).decode('ascii').strip()

    def set_voltage(self, channel: int, voltage: float):
        """Set DAC channel voltage (0-5V)"""
        if not 0 <= channel <= 3:
            raise ValueError("Channel must be 0-3")
        if not 0 <= voltage <= 5.0:
            raise ValueError("Voltage must be 0-5V")
        self.send(f"VOLT {voltage:.4f},(@{channel})")

    def get_voltage(self, channel: int) -> float:
        """Read DAC channel voltage"""
        resp = self.query(f"VOLT? (@{channel})")
        return float(resp)

    def save_eeprom(self):
        """Save current settings to EEPROM"""
        self.send("*SAV 0")


class IQOptimizer:
    """IQ modulator optimization engine"""

    def __init__(self, dac: SCPIDac, mhs: MHS5200A, ssa: SSA3032X):
        self.dac = dac
        self.mhs = mhs
        self.ssa = ssa

        # DAC channel assignments
        self.CH_I_OFFSET = 0  # I-channel DC offset
        self.CH_I_GAIN = 1    # I-channel gain (0-5V → 0-1x gain)
        self.CH_Q_OFFSET = 2  # Q-channel DC offset
        self.CH_Q_GAIN = 3    # Q-channel gain

    def setup_generators(self, carrier_freq_mhz: float, mod_freq_khz: float):
        """Configure MHS-5225A for IQ generation"""
        carrier_hz = int(carrier_freq_mhz * 1e6)
        mod_hz = int(mod_freq_khz * 1e3)

        print(f"Configuring MHS-5225A:")
        print(f"  Carrier: {carrier_freq_mhz} MHz")
        print(f"  Modulation: {mod_freq_khz} kHz")

        # CH1: I-channel (0° reference)
        self.mhs.set_frequency(1, carrier_hz)
        self.mhs.set_waveform(1, 'sine')
        self.mhs.set_amplitude(1, 5.0)  # 5Vpp
        self.mhs.set_phase(1, 0.0)
        self.mhs.set_output(1, True)

        # CH2: Q-channel (90° phase shift)
        self.mhs.set_frequency(2, carrier_hz)
        self.mhs.set_waveform(2, 'sine')
        self.mhs.set_amplitude(2, 5.0)  # 5Vpp
        self.mhs.set_phase(2, 90.0)
        self.mhs.set_output(2, True)

        print("✓ Generators configured")

    def setup_analyzer(self, carrier_freq_mhz: float, span_khz: float = 100):
        """Configure SSA3032X for measurement"""
        carrier_hz = carrier_freq_mhz * 1e6
        span_hz = span_khz * 1e3

        print(f"Configuring SSA3032X:")
        print(f"  Center: {carrier_freq_mhz} MHz")
        print(f"  Span: {span_khz} kHz")

        self.ssa.set_center_frequency(carrier_hz)
        self.ssa.set_span(span_hz)
        self.ssa.set_rbw(100)  # 100 Hz RBW for accurate measurement
        self.ssa.set_vbw(100)
        self.ssa.set_reference_level(0)  # 0 dBm reference
        self.ssa.auto_tune()

        print("✓ Analyzer configured")

    def measure_iq_quality(self, carrier_freq_mhz: float, mod_freq_khz: float) -> Dict[str, float]:
        """
        Measure IQ modulator quality metrics

        Returns:
            dict with keys:
                - carrier_suppression_db: how much carrier is suppressed
                - usb_level_dbm: upper sideband level
                - lsb_level_dbm: lower sideband level
                - sideband_imbalance_db: |USB - LSB|
        """
        carrier_hz = carrier_freq_mhz * 1e6
        mod_hz = mod_freq_khz * 1e3

        # Set markers at carrier and sidebands
        self.ssa.set_marker(1, carrier_hz)  # Carrier
        self.ssa.set_marker(2, carrier_hz + mod_hz)  # USB
        self.ssa.set_marker(3, carrier_hz - mod_hz)  # LSB

        time.sleep(0.5)  # Let measurement settle

        carrier_dbm = self.ssa.get_marker_level(1)
        usb_dbm = self.ssa.get_marker_level(2)
        lsb_dbm = self.ssa.get_marker_level(3)

        # Carrier suppression = how much lower carrier is than sidebands
        avg_sideband = (usb_dbm + lsb_dbm) / 2
        carrier_suppression = avg_sideband - carrier_dbm

        # Sideband imbalance = difference between USB and LSB
        sideband_imbalance = abs(usb_dbm - lsb_dbm)

        return {
            'carrier_suppression_db': carrier_suppression,
            'usb_level_dbm': usb_dbm,
            'lsb_level_dbm': lsb_dbm,
            'sideband_imbalance_db': sideband_imbalance,
            'carrier_level_dbm': carrier_dbm
        }

    def set_iq_corrections(self, i_offset: float, i_gain: float, q_offset: float, q_gain: float):
        """Apply IQ correction voltages to DAC"""
        self.dac.set_voltage(self.CH_I_OFFSET, i_offset)
        self.dac.set_voltage(self.CH_I_GAIN, i_gain)
        self.dac.set_voltage(self.CH_Q_OFFSET, q_offset)
        self.dac.set_voltage(self.CH_Q_GAIN, q_gain)
        time.sleep(0.2)  # Let analog circuit settle

    def optimize_grid_search(self, carrier_freq_mhz: float, mod_freq_khz: float,
                            resolution: int = 5) -> Tuple[Dict[str, float], Dict[str, float]]:
        """
        Optimize IQ corrections via grid search

        Args:
            resolution: number of steps per parameter (5 = 625 total combinations)

        Returns:
            (best_params, best_metrics)
        """
        print(f"\nStarting grid search optimization (resolution={resolution})")
        print("This will take a few minutes...")

        # Search ranges
        offset_range = np.linspace(2.3, 2.7, resolution)  # Around mid-scale
        gain_range = np.linspace(2.3, 2.7, resolution)

        best_score = -np.inf
        best_params = None
        best_metrics = None

        total_iterations = resolution ** 4
        iteration = 0

        for i_offset in offset_range:
            for i_gain in gain_range:
                for q_offset in offset_range:
                    for q_gain in gain_range:
                        iteration += 1

                        # Apply corrections
                        self.set_iq_corrections(i_offset, i_gain, q_offset, q_gain)

                        # Measure quality
                        metrics = self.measure_iq_quality(carrier_freq_mhz, mod_freq_khz)

                        # Score: prioritize carrier suppression, then sideband balance
                        score = metrics['carrier_suppression_db'] - 0.5 * metrics['sideband_imbalance_db']

                        if score > best_score:
                            best_score = score
                            best_params = {
                                'i_offset': i_offset,
                                'i_gain': i_gain,
                                'q_offset': q_offset,
                                'q_gain': q_gain
                            }
                            best_metrics = metrics

                        if iteration % 50 == 0:
                            progress = 100 * iteration / total_iterations
                            print(f"  Progress: {progress:.1f}% (best carrier suppression: {best_metrics['carrier_suppression_db']:.1f} dB)")

        print(f"\n✓ Grid search complete ({iteration} iterations)")
        return best_params, best_metrics

    def optimize_gradient_descent(self, carrier_freq_mhz: float, mod_freq_khz: float,
                                 initial_params: Dict[str, float] = None,
                                 learning_rate: float = 0.01,
                                 max_iterations: int = 100) -> Tuple[Dict[str, float], Dict[str, float]]:
        """
        Optimize IQ corrections via gradient descent

        Args:
            initial_params: starting point (if None, use mid-scale)
            learning_rate: step size for gradient descent
            max_iterations: max number of iterations

        Returns:
            (best_params, best_metrics)
        """
        print(f"\nStarting gradient descent optimization")
        print(f"  Learning rate: {learning_rate}")
        print(f"  Max iterations: {max_iterations}")

        # Initialize parameters
        if initial_params is None:
            params = {
                'i_offset': 2.5,
                'i_gain': 2.5,
                'q_offset': 2.5,
                'q_gain': 2.5
            }
        else:
            params = initial_params.copy()

        best_score = -np.inf
        best_params = params.copy()
        best_metrics = None

        for iteration in range(max_iterations):
            # Current score
            self.set_iq_corrections(params['i_offset'], params['i_gain'],
                                   params['q_offset'], params['q_gain'])
            metrics = self.measure_iq_quality(carrier_freq_mhz, mod_freq_khz)
            score = metrics['carrier_suppression_db'] - 0.5 * metrics['sideband_imbalance_db']

            if score > best_score:
                best_score = score
                best_params = params.copy()
                best_metrics = metrics

            # Numerical gradient estimation (finite differences)
            delta = 0.05  # Small voltage step
            gradients = {}

            for param_name in params.keys():
                # Perturb parameter
                params_plus = params.copy()
                params_plus[param_name] += delta

                # Clamp to valid range
                params_plus[param_name] = np.clip(params_plus[param_name], 0, 5)

                # Measure score with perturbation
                self.set_iq_corrections(params_plus['i_offset'], params_plus['i_gain'],
                                       params_plus['q_offset'], params_plus['q_gain'])
                metrics_plus = self.measure_iq_quality(carrier_freq_mhz, mod_freq_khz)
                score_plus = metrics_plus['carrier_suppression_db'] - 0.5 * metrics_plus['sideband_imbalance_db']

                # Gradient = (f(x+delta) - f(x)) / delta
                gradients[param_name] = (score_plus - score) / delta

            # Update parameters
            for param_name in params.keys():
                params[param_name] += learning_rate * gradients[param_name]
                params[param_name] = np.clip(params[param_name], 0, 5)

            if (iteration + 1) % 10 == 0:
                print(f"  Iteration {iteration + 1}/{max_iterations}: "
                      f"carrier suppression = {best_metrics['carrier_suppression_db']:.1f} dB, "
                      f"sideband imbalance = {best_metrics['sideband_imbalance_db']:.1f} dB")

            # Early stopping if we've achieved target performance
            if best_metrics['carrier_suppression_db'] > 40 and best_metrics['sideband_imbalance_db'] < 1.0:
                print(f"✓ Target performance achieved at iteration {iteration + 1}")
                break

        print(f"\n✓ Gradient descent complete")
        return best_params, best_metrics


def main():
    parser = argparse.ArgumentParser(
        description="IQ Modulator Optimization using scpi-dac + MHS-5225A + SSA3032X",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Optimize 10 MHz carrier with 10 kHz modulation
  %(prog)s --esp-dac 10.1.0.100 --mhs-port /dev/ttyUSB0 --ssa 10.1.0.101 \\
           --carrier-freq-mhz 10 --mod-freq-khz 10

  # Use gradient descent (faster)
  %(prog)s --esp-dac 10.1.0.100 --mhs-port /dev/ttyUSB0 --ssa 10.1.0.101 \\
           --carrier-freq-mhz 10 --mod-freq-khz 10 --method gradient

  # Coarse grid search then fine gradient descent
  %(prog)s --esp-dac 10.1.0.100 --mhs-port /dev/ttyUSB0 --ssa 10.1.0.101 \\
           --carrier-freq-mhz 10 --mod-freq-khz 10 --method hybrid
        """
    )

    parser.add_argument('--esp-dac', required=True,
                       help='scpi-dac IP address')
    parser.add_argument('--mhs-port', required=True,
                       help='MHS-5225A serial port (e.g., /dev/ttyUSB0)')
    parser.add_argument('--ssa', required=True,
                       help='SSA3032X IP address')
    parser.add_argument('--carrier-freq-mhz', type=float, required=True,
                       help='Carrier frequency in MHz')
    parser.add_argument('--mod-freq-khz', type=float, required=True,
                       help='Modulation frequency in kHz')
    parser.add_argument('--method', choices=['grid', 'gradient', 'hybrid'], default='hybrid',
                       help='Optimization method (default: hybrid)')
    parser.add_argument('--save-eeprom', action='store_true',
                       help='Save optimal settings to DAC EEPROM')

    args = parser.parse_args()

    print("=" * 60)
    print("IQ Modulator Optimization")
    print("=" * 60)

    # Connect to instruments
    print("\nConnecting to instruments...")

    dac = SCPIDac(args.esp_dac)
    dac.connect()
    print(f"✓ Connected to scpi-dac at {args.esp_dac}")

    mhs = MHS5200A(args.mhs_port)
    print(f"✓ Connected to MHS-5225A at {args.mhs_port}")

    ssa = SSA3032X(args.ssa)
    print(f"✓ Connected to SSA3032X at {args.ssa}")

    # Create optimizer
    optimizer = IQOptimizer(dac, mhs, ssa)

    # Setup instruments
    optimizer.setup_generators(args.carrier_freq_mhz, args.mod_freq_khz)
    optimizer.setup_analyzer(args.carrier_freq_mhz, span_khz=5 * args.mod_freq_khz)

    # Measure baseline (no correction)
    print("\nBaseline measurement (no correction):")
    optimizer.set_iq_corrections(2.5, 2.5, 2.5, 2.5)  # Mid-scale
    baseline = optimizer.measure_iq_quality(args.carrier_freq_mhz, args.mod_freq_khz)
    print(f"  Carrier suppression: {baseline['carrier_suppression_db']:.1f} dB")
    print(f"  Sideband imbalance: {baseline['sideband_imbalance_db']:.1f} dB")

    # Optimize
    if args.method == 'grid':
        best_params, best_metrics = optimizer.optimize_grid_search(
            args.carrier_freq_mhz, args.mod_freq_khz, resolution=5
        )
    elif args.method == 'gradient':
        best_params, best_metrics = optimizer.optimize_gradient_descent(
            args.carrier_freq_mhz, args.mod_freq_khz
        )
    else:  # hybrid
        # Coarse grid search
        print("\nPhase 1: Coarse grid search")
        grid_params, grid_metrics = optimizer.optimize_grid_search(
            args.carrier_freq_mhz, args.mod_freq_khz, resolution=3
        )

        # Fine gradient descent from grid result
        print("\nPhase 2: Fine gradient descent")
        best_params, best_metrics = optimizer.optimize_gradient_descent(
            args.carrier_freq_mhz, args.mod_freq_khz,
            initial_params=grid_params,
            learning_rate=0.01
        )

    # Apply and verify optimal settings
    print("\n" + "=" * 60)
    print("OPTIMAL SETTINGS")
    print("=" * 60)
    optimizer.set_iq_corrections(
        best_params['i_offset'], best_params['i_gain'],
        best_params['q_offset'], best_params['q_gain']
    )

    print("\nDAC Voltages:")
    print(f"  I-channel offset: {best_params['i_offset']:.3f} V")
    print(f"  I-channel gain:   {best_params['i_gain']:.3f} V")
    print(f"  Q-channel offset: {best_params['q_offset']:.3f} V")
    print(f"  Q-channel gain:   {best_params['q_gain']:.3f} V")

    print("\nPerformance:")
    print(f"  Carrier suppression: {best_metrics['carrier_suppression_db']:.1f} dB")
    print(f"  Sideband imbalance:  {best_metrics['sideband_imbalance_db']:.1f} dB")
    print(f"  USB level:           {best_metrics['usb_level_dbm']:.1f} dBm")
    print(f"  LSB level:           {best_metrics['lsb_level_dbm']:.1f} dBm")

    improvement = best_metrics['carrier_suppression_db'] - baseline['carrier_suppression_db']
    print(f"\nImprovement: {improvement:+.1f} dB carrier suppression")

    # Check if we met goals
    print("\nGoals:")
    if best_metrics['carrier_suppression_db'] > 40:
        print("  ✓ Carrier suppression >40 dB: PASS")
    else:
        print(f"  ✗ Carrier suppression >40 dB: FAIL ({best_metrics['carrier_suppression_db']:.1f} dB)")

    if best_metrics['sideband_imbalance_db'] < 1.0:
        print("  ✓ Sideband imbalance <1 dB: PASS")
    else:
        print(f"  ✗ Sideband imbalance <1 dB: FAIL ({best_metrics['sideband_imbalance_db']:.1f} dB)")

    # Save to EEPROM if requested
    if args.save_eeprom:
        print("\nSaving settings to EEPROM...")
        dac.save_eeprom()
        print("✓ Settings saved")

    # Cleanup
    dac.disconnect()
    mhs.close()
    ssa.close()

    print("\n✓ Done")


if __name__ == '__main__':
    main()
