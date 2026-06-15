#!/usr/bin/env python3
"""
Demo data generator for flight instruments panel.
Simulates a small aircraft flight profile.
"""

import time
import random
import math
import json
import paho.mqtt.client as mqtt


def main():
    """Generate flight demo data"""
    client = mqtt.Client()
    client.connect('localhost', 1883, 60)
    client.loop_start()

    print("Publishing flight demo data to MQTT...")
    print("Topics:")
    print("  flight/airspeed - Airspeed in knots (0-200)")
    print("  flight/cluster  - Gauge cluster (altitude, VSI, heading, RPM)")
    print("  flight/lcd      - Text LCD (4×20 status display)")
    print("  flight/chart    - Altitude history chart")
    print("\nPress Ctrl+C to stop\n")

    # Flight state
    phase = 'ground'  # ground, takeoff, climb, cruise, descent, landing
    airspeed = 0.0
    altitude = 0.0
    vsi = 0.0
    heading = 90.0  # East
    rpm = 800.0
    counter = 0
    phase_time = 0

    # Flight profile phases
    phases = {
        'ground': {'duration': 30, 'next': 'takeoff'},
        'takeoff': {'duration': 20, 'next': 'climb'},
        'climb': {'duration': 60, 'next': 'cruise'},
        'cruise': {'duration': 120, 'next': 'descent'},
        'descent': {'duration': 60, 'next': 'landing'},
        'landing': {'duration': 20, 'next': 'ground'},
    }

    try:
        while True:
            # Phase transitions
            if phase_time >= phases[phase]['duration'] * 5:  # 5 updates per second
                phase = phases[phase]['next']
                phase_time = 0
                print(f"\n=== Phase: {phase.upper()} ===")

            # Update flight parameters based on phase
            if phase == 'ground':
                airspeed = 0.0 + random.uniform(-1, 1)
                altitude = 0.0
                vsi = 0.0
                heading += random.uniform(-0.5, 0.5)
                rpm = 800.0 + random.uniform(-50, 50)

            elif phase == 'takeoff':
                airspeed = min(80.0, airspeed + 2.0) + random.uniform(-2, 2)
                altitude = max(0.0, altitude + 3.0)
                vsi = 300.0 + random.uniform(-50, 50)
                heading += random.uniform(-0.2, 0.2)
                rpm = 2700.0 + random.uniform(-100, 100)

            elif phase == 'climb':
                airspeed = 85.0 + random.uniform(-3, 3)
                altitude = min(5000.0, altitude + 10.0)
                vsi = 500.0 + random.uniform(-50, 50)
                heading += random.uniform(-0.1, 0.1)
                rpm = 2500.0 + random.uniform(-50, 50)

            elif phase == 'cruise':
                airspeed = 120.0 + random.uniform(-5, 5)
                altitude = 5000.0 + random.uniform(-50, 50)
                vsi = 0.0 + random.uniform(-20, 20)
                heading += random.uniform(-0.2, 0.2)
                rpm = 2300.0 + random.uniform(-50, 50)

            elif phase == 'descent':
                airspeed = 100.0 + random.uniform(-3, 3)
                altitude = max(0.0, altitude - 8.0)
                vsi = -400.0 + random.uniform(-50, 50)
                heading += random.uniform(-0.1, 0.1)
                rpm = 1800.0 + random.uniform(-50, 50)

            elif phase == 'landing':
                airspeed = max(0.0, airspeed - 3.0) + random.uniform(-2, 2)
                altitude = max(0.0, altitude - 5.0)
                vsi = -200.0 if altitude > 0 else 0.0
                heading += random.uniform(-0.3, 0.3)
                rpm = max(800.0, rpm - 50.0) + random.uniform(-50, 50)

            # Clamp values
            airspeed = max(0.0, min(200.0, airspeed))
            altitude = max(0.0, min(10000.0, altitude))
            vsi = max(-2000.0, min(2000.0, vsi))
            heading = heading % 360.0
            rpm = max(0.0, min(3000.0, rpm))

            # Publish airspeed (analog meter)
            client.publish("flight/airspeed", f"{airspeed:.1f}")

            # Publish gauge cluster (JSON)
            cluster_data = {
                'alt': altitude,
                'vsi': vsi,
                'heading': heading,
                'rpm': rpm
            }
            client.publish("flight/cluster", json.dumps(cluster_data))

            # Publish LCD text (pipe-separated lines)
            lcd_lines = [
                f"Phase: {phase.upper():14s}",
                f"Airspeed: {airspeed:6.1f} kts",
                f"Altitude: {altitude:6.0f} ft",
                f"RPM:      {rpm:6.0f}    "
            ]
            client.publish("flight/lcd", '|'.join(lcd_lines))

            # Publish altitude to chart (JSON with timestamp)
            chart_data = {
                'timestamp': time.time(),
                'value': altitude
            }
            client.publish("flight/chart", json.dumps(chart_data))

            # Status line
            print(f"[{phase:8s}] AS:{airspeed:6.1f} kts  ALT:{altitude:6.0f} ft  VSI:{vsi:5.0f} fpm  HDG:{heading:5.1f}°  RPM:{rpm:5.0f}", end='\r')

            counter += 1
            phase_time += 1
            time.sleep(0.2)  # 5 Hz update rate

    except KeyboardInterrupt:
        print("\n\nStopping flight demo...")
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
