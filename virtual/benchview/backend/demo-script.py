#!/usr/bin/env python3
"""
BenchView Demo Script

Animates the demo panel with realistic RF bench instrument behavior.
Reads port assignments from demo-panel_ports.yaml and controls all instruments via SCPI.

Run after starting BenchView with demo-panel.yaml.
"""

import socket
import time
import yaml
import math
import random
from pathlib import Path


class SCPIInstrument:
    """Simple SCPI client wrapper"""
    def __init__(self, host: str, port: int, name: str):
        self.host = host
        self.port = port
        self.name = name
        self.sock = None
        self._connect()

    def _connect(self):
        """Connect to SCPI server"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            print(f"Connected: {self.name} @ {self.host}:{self.port}")
        except Exception as e:
            print(f"Failed to connect {self.name}: {e}")
            self.sock = None

    def send(self, cmd: str):
        """Send SCPI command"""
        if not self.sock:
            return
        try:
            self.sock.sendall(f"{cmd}\n".encode())
        except Exception as e:
            print(f"Error sending to {self.name}: {e}")

    def query(self, cmd: str) -> str:
        """Send SCPI query and read response"""
        if not self.sock:
            return ""
        try:
            self.sock.sendall(f"{cmd}\n".encode())
            return self.sock.recv(1024).decode().strip()
        except Exception as e:
            print(f"Error querying {self.name}: {e}")
            return ""

    def close(self):
        """Close connection"""
        if self.sock:
            self.sock.close()


def load_port_config(config_path: str) -> dict:
    """Load port assignments from output YAML"""
    with open(config_path) as f:
        return yaml.safe_load(f)


def setup_instruments(instruments: dict) -> dict:
    """Connect to all instruments and configure labels/ranges"""
    clients = {}

    # Power meters (analog-meter, 2 instances)
    if 'power-meter' in instruments:
        cfg = instruments['power-meter']
        meter = SCPIInstrument('localhost', cfg['scpi_port'], 'power-meter')
        meter.send('CONF1:MIN 0')
        meter.send('CONF1:MAX 100')
        meter.send('CONF1:UNIT W')
        meter.send('CONF1:LAB TX Power')
        meter.send('CONF2:MIN 0')
        meter.send('CONF2:MAX 15')
        meter.send('CONF2:UNIT V')
        meter.send('CONF2:LAB Supply')
        clients['power-meter'] = meter

    # PTT LEDs (4 LEDs in 2x2)
    if 'ptt-led' in instruments:
        cfg = instruments['ptt-led']
        led = SCPIInstrument('localhost', cfg['scpi_port'], 'ptt-led')
        led.send('CONF1:LAB TX')
        led.send('CONF1:ONCOL #ff0000')
        led.send('CONF2:LAB RX')
        led.send('CONF2:ONCOL #00ff00')
        led.send('CONF3:LAB GPS')
        led.send('CONF3:ONCOL #4488ff')
        led.send('CONF4:LAB ERR')
        led.send('CONF4:ONCOL #ff8800')
        clients['ptt-led'] = led

    # Signal bars (3 bars)
    if 'signal-bars' in instruments:
        cfg = instruments['signal-bars']
        bars = SCPIInstrument('localhost', cfg['scpi_port'], 'signal-bars')
        bars.send('CONF1:MIN -120')
        bars.send('CONF1:MAX -30')
        bars.send('CONF1:UNIT dBm')
        bars.send('CONF1:LAB 14.074')
        bars.send('CONF2:MIN -120')
        bars.send('CONF2:MAX -30')
        bars.send('CONF2:UNIT dBm')
        bars.send('CONF2:LAB 7.074')
        bars.send('CONF3:MIN -120')
        bars.send('CONF3:MAX -30')
        bars.send('CONF3:UNIT dBm')
        bars.send('CONF3:LAB 3.573')
        clients['signal-bars'] = bars

    # Frequency displays (2 numeric displays)
    if 'freq-display' in instruments:
        cfg = instruments['freq-display']
        disp = SCPIInstrument('localhost', cfg['scpi_port'], 'freq-display')
        disp.send('CONF1:PREC 3')
        disp.send('CONF1:UNIT MHz')
        disp.send('CONF1:LAB VFO A')
        disp.send('CONF2:PREC 3')
        disp.send('CONF2:UNIT MHz')
        disp.send('CONF2:LAB VFO B')
        clients['freq-display'] = disp

    # Volume knob (1 knob)
    if 'volume-knob' in instruments:
        cfg = instruments['volume-knob']
        knob = SCPIInstrument('localhost', cfg['scpi_port'], 'volume-knob')
        knob.send('CONF1:MIN 0')
        knob.send('CONF1:MAX 100')
        knob.send('CONF1:UNIT %')
        knob.send('CONF1:LAB Volume')
        knob.send('SOUR1:VAL 50')
        clients['volume-knob'] = knob

    return clients


def animate_demo(clients: dict):
    """Run animation loop"""
    print("\n=== Demo Running ===")
    print("Watch the instruments animate in your browser!")
    print("Press Ctrl+C to stop.\n")

    t = 0.0
    tx_state = False
    tx_timer = 0.0

    try:
        while True:
            # TX power sweep (0-100W with noise)
            if 'power-meter' in clients:
                power = 50 + 40 * math.sin(t * 0.5) + random.gauss(0, 3)
                clients['power-meter'].send(f'MEAS1:VAL {power:.1f}')

                # Supply voltage (13.8V nominal with ripple)
                voltage = 13.8 + 0.2 * math.sin(t * 3) + random.gauss(0, 0.1)
                clients['power-meter'].send(f'MEAS2:VAL {voltage:.2f}')

            # PTT LED cycle
            if 'ptt-led' in clients:
                tx_timer += 0.1
                if tx_timer > 2.0:
                    tx_state = not tx_state
                    tx_timer = 0.0
                    clients['ptt-led'].send(f'STAT1:VAL {1 if tx_state else 0}')
                    clients['ptt-led'].send(f'STAT2:VAL {0 if tx_state else 1}')

                # GPS always locked
                clients['ptt-led'].send('STAT3:VAL 1')

                # Random error blink
                if random.random() < 0.05:
                    clients['ptt-led'].send('STAT4:VAL 1')
                else:
                    clients['ptt-led'].send('STAT4:VAL 0')

            # Signal bars (simulated band noise)
            if 'signal-bars' in clients:
                s1 = -90 + 20 * math.sin(t * 0.3) + random.gauss(0, 5)
                s2 = -85 + 15 * math.cos(t * 0.4) + random.gauss(0, 5)
                s3 = -95 + 25 * math.sin(t * 0.2 + 1) + random.gauss(0, 5)
                clients['signal-bars'].send(f'MEAS1:VAL {s1:.1f}')
                clients['signal-bars'].send(f'MEAS2:VAL {s2:.1f}')
                clients['signal-bars'].send(f'MEAS3:VAL {s3:.1f}')

            # Frequency displays (slow drift)
            if 'freq-display' in clients:
                freq_a = 14.074 + 0.001 * math.sin(t * 0.1)
                freq_b = 14.236 + 0.0005 * math.cos(t * 0.15)
                clients['freq-display'].send(f'MEAS1:VAL {freq_a:.3f}')
                clients['freq-display'].send(f'MEAS2:VAL {freq_b:.3f}')

            t += 0.1
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n\n=== Demo Stopped ===")

    finally:
        for client in clients.values():
            client.close()


def main():
    """Main entry point"""
    # Load port configuration
    config_path = Path(__file__).parent / "configs" / "demo-panel_ports.yaml"

    if not config_path.exists():
        print(f"ERROR: Port config not found: {config_path}")
        print("Make sure BenchView is running with demo-panel.yaml first!")
        return 1

    print("Loading port configuration...")
    config = load_port_config(config_path)

    print(f"Panel: {config['panel']}")
    print(f"Instruments: {len(config['instruments'])}")

    # Connect and configure
    print("\nConnecting to instruments...")
    clients = setup_instruments(config['instruments'])

    if not clients:
        print("ERROR: No instruments connected!")
        return 1

    print(f"Connected to {len(clients)} instruments")

    # Run animation
    time.sleep(1)
    animate_demo(clients)

    return 0


if __name__ == "__main__":
    exit(main())
