#!/usr/bin/env python3
"""Quick 30-second BenchView demo with realistic animations"""

import socket
import time
import math

def scpi_send(host, port, commands):
    """Send SCPI commands with timeout"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect((host, port))
            for cmd in commands:
                s.sendall(f"{cmd}\n".encode())
            time.sleep(0.01)
    except Exception as e:
        print(f"Error on port {port}: {e}")

# Configure all instruments
print("Configuring instruments...")

# Power meters (5100)
scpi_send('localhost', 5100, [
    'CONF1:MIN 0', 'CONF1:MAX 100', 'CONF1:UNIT W', 'CONF1:LAB TX Power',
    'CONF2:MIN 0', 'CONF2:MAX 15', 'CONF2:UNIT V', 'CONF2:LAB Supply'
])

# LEDs (5101)
scpi_send('localhost', 5101, [
    'CONF1:LAB TX', 'CONF1:ONCOL #ff0000',
    'CONF2:LAB RX', 'CONF2:ONCOL #00ff00',
    'CONF3:LAB GPS', 'CONF3:ONCOL #4488ff',
    'CONF4:LAB ERR', 'CONF4:ONCOL #ff8800'
])

# Signal bars (5102)
scpi_send('localhost', 5102, [
    'CONF1:MIN -120', 'CONF1:MAX -30', 'CONF1:UNIT dBm', 'CONF1:LAB 20m',
    'CONF2:MIN -120', 'CONF2:MAX -30', 'CONF2:UNIT dBm', 'CONF2:LAB 40m',
    'CONF3:MIN -120', 'CONF3:MAX -30', 'CONF3:UNIT dBm', 'CONF3:LAB 80m'
])

# Frequency displays (5103)
scpi_send('localhost', 5103, [
    'CONF1:PREC 3', 'CONF1:UNIT MHz', 'CONF1:LAB VFO A', 'CONF1:COL #ff0000',
    'CONF2:PREC 3', 'CONF2:UNIT MHz', 'CONF2:LAB VFO B', 'CONF2:COL #ff0000'
])

# Volume knob (5104)
scpi_send('localhost', 5104, [
    'CONF1:MIN 0', 'CONF1:MAX 100', 'CONF1:UNIT %', 'CONF1:LAB Volume'
])

print("Running 30-second demo...\n")

# Animation state
power_base = 45.0
voltage_base = 13.8
freq_a_base = 14.074
freq_b_base = 14.236
sig1_base = -85.0
sig2_base = -90.0
sig3_base = -95.0

start_time = time.time()

while (time.time() - start_time) < 30:
    t = time.time() - start_time

    # Smooth power variation (40-60W)
    power = power_base + 8 * math.sin(t * 0.5)
    scpi_send('localhost', 5100, [f'MEAS1:VAL {power:.1f}'])

    # Supply voltage ripple (13.6-14.0V)
    voltage = voltage_base + 0.2 * math.sin(t * 2)
    scpi_send('localhost', 5100, [f'MEAS2:VAL {voltage:.2f}'])

    # TX/RX LED toggle every 3 seconds
    tx_on = int(t) % 6 < 3
    scpi_send('localhost', 5101, [
        f'STAT1:VAL {1 if tx_on else 0}',
        f'STAT2:VAL {0 if tx_on else 1}',
        'STAT3:VAL 1',  # GPS always locked
        f'STAT4:VAL {1 if (int(t * 2) % 10 == 0) else 0}'  # Occasional error blink
    ])

    # Signal levels (smooth band noise)
    sig1 = sig1_base + 10 * math.sin(t * 0.3)
    sig2 = sig2_base + 8 * math.cos(t * 0.4)
    sig3 = sig3_base + 12 * math.sin(t * 0.25 + 1.5)
    scpi_send('localhost', 5102, [
        f'MEAS1:VAL {sig1:.1f}',
        f'MEAS2:VAL {sig2:.1f}',
        f'MEAS3:VAL {sig3:.1f}'
    ])

    # Frequency drift (±1 kHz)
    freq_a = freq_a_base + 0.001 * math.sin(t * 0.1)
    freq_b = freq_b_base + 0.0005 * math.cos(t * 0.15)
    scpi_send('localhost', 5103, [
        f'MEAS1:VAL {freq_a:.3f}',
        f'MEAS2:VAL {freq_b:.3f}'
    ])

    time.sleep(0.1)

print("\nDemo complete!")
print("Instruments remain configured. Refresh browser to see final state.")
