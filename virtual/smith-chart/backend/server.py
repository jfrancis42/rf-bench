#!/usr/bin/env python3
"""
Virtual Smith Chart — SCPI TCP Server + WebSocket + MQTT bridge

Complex impedance visualization for antenna tuning, VNA measurements, and
matching network design. Plots normalized impedance on Smith chart grid with
constant resistance circles and reactance arcs.

Exposes:
- SCPI TCP server on port 5025 (IEEE 488.2 standard instrument port)
- HTTP server on port 8011 (serves static frontend)
- WebSocket server on port 8011/ws (real-time chart updates)
- MQTT subscriber (listens to configured topic for impedance data)

SCPI Commands:
  *IDN?                      → "N0GQ,Virtual-Smith-Chart,1.0,2026"
  *RST                       → Reset to defaults
  SYST:ERR?                  → Query error queue
  SMIT:POIN <real>,<imag>    → Add impedance point (rectangular, normalized)
  SMIT:POIN?                 → Query most recent point
  SMIT:POIN:POL <mag>,<ang>  → Add point (polar: magnitude, angle degrees)
  SMIT:Z0 <ohms>             → Set reference impedance (default 50)
  SMIT:Z0?                   → Query reference impedance
  SMIT:TRAC <1-4>            → Select active trace
  SMIT:TRAC?                 → Query active trace
  SMIT:TRAC:CLE              → Clear active trace
  SMIT:TRAC:ALL:CLE          → Clear all traces
  SMIT:TRAC:COL <color>      → Set active trace color (hex)
  SMIT:TRAC:COL?             → Query active trace color
  SMIT:TRAC:LAB <string>     → Set active trace label
  SMIT:TRAC:LAB?             → Query active trace label
  SMIT:MARK:FREQ <Hz>        → Add frequency marker at last point
  SMIT:MARK:FREQ?            → Query last frequency marker
  SMIT:SWR <ratio>           → Draw SWR circle (1.0-10.0)
  SMIT:SWR?                  → Query SWR circle value
  SMIT:MODE <IMPED|ADMIT>    → Switch impedance/admittance view
  SMIT:MODE?                 → Query current mode
  SMIT:GRID <ON|OFF>         → Show/hide grid
  SMIT:GRID?                 → Query grid state
  CONF:TITLE <string>        → Set chart title
  CONF:TITLE?                → Query chart title
  MQTT:CONF <host>,<topic>   → Configure MQTT broker and topic
  MQTT:CONF?                 → Query MQTT configuration

Example usage:
  echo "SMIT:Z0 50" | nc localhost 5025
  echo "SMIT:TRAC 1" | nc localhost 5025
  echo "SMIT:POIN 0.5,0.3" | nc localhost 5025      # Z = 0.5+0.3j (normalized)
  echo "SMIT:MARK:FREQ 14.2e6" | nc localhost 5025  # Label point "14.2 MHz"
  echo "SMIT:SWR 2.0" | nc localhost 5025           # Draw SWR=2.0 circle
"""

import asyncio
import json
import sys
import time
import math
import cmath
from collections import deque
from pathlib import Path
from typing import List, Optional, Dict, Tuple

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    import uvicorn
except ImportError:
    print("ERROR: FastAPI and uvicorn are required.", file=sys.stderr)
    print("Install with: pip install fastapi uvicorn websockets --break-system-packages", file=sys.stderr)
    sys.exit(1)

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    print("WARNING: paho-mqtt not installed. MQTT features disabled.", file=sys.stderr)
    print("Install with: pip install paho-mqtt --break-system-packages", file=sys.stderr)

# Global state
app = FastAPI()
event_loop = None
websocket_clients = []

# Instrument state
state = {
    'z0': 50.0,                    # Reference impedance (Ohms)
    'active_trace': 1,             # Currently selected trace (1-4)
    'traces': {                    # Trace data
        1: {'points': [], 'color': '#00ff00', 'label': 'Trace 1'},
        2: {'points': [], 'color': '#ff00ff', 'label': 'Trace 2'},
        3: {'points': [], 'color': '#00ffff', 'label': 'Trace 3'},
        4: {'points': [], 'color': '#ffff00', 'label': 'Trace 4'},
    },
    'swr_circle': None,            # SWR circle ratio (None or float)
    'mode': 'IMPED',               # 'IMPED' or 'ADMIT'
    'grid': True,                  # Grid visibility
    'title': 'Smith Chart',        # Chart title
    'last_freq': None,             # Last frequency marker (Hz)
}

# MQTT state
mqtt_client = None
mqtt_config = {'host': None, 'topic': None}

# Error queue (IEEE 488.2 standard)
error_queue = deque(maxlen=10)


def add_error(code: int, message: str):
    """Add error to queue"""
    error_queue.append(f"{code},{message}")


def rect_to_polar(real: float, imag: float) -> Tuple[float, float]:
    """Convert rectangular to polar (magnitude, angle_degrees)"""
    z = complex(real, imag)
    return abs(z), math.degrees(cmath.phase(z))


def polar_to_rect(mag: float, angle_deg: float) -> Tuple[float, float]:
    """Convert polar to rectangular (real, imag)"""
    z = cmath.rect(mag, math.radians(angle_deg))
    return z.real, z.imag


def impedance_to_reflection(z_norm: complex) -> complex:
    """Convert normalized impedance to reflection coefficient (Γ)"""
    return (z_norm - 1) / (z_norm + 1)


def reflection_to_impedance(gamma: complex) -> complex:
    """Convert reflection coefficient to normalized impedance"""
    return (1 + gamma) / (1 - gamma)


def calculate_swr(gamma: complex) -> float:
    """Calculate SWR from reflection coefficient"""
    mag = abs(gamma)
    if mag >= 1.0:
        return float('inf')
    return (1 + mag) / (1 - mag)


async def broadcast_state():
    """Send current state to all WebSocket clients"""
    if not websocket_clients:
        return

    # Build message
    msg = {
        'z0': state['z0'],
        'active_trace': state['active_trace'],
        'traces': state['traces'],
        'swr_circle': state['swr_circle'],
        'mode': state['mode'],
        'grid': state['grid'],
        'title': state['title'],
        'timestamp': time.time()
    }

    dead_clients = []
    for client in websocket_clients:
        try:
            await client.send_json(msg)
        except:
            dead_clients.append(client)

    for client in dead_clients:
        websocket_clients.remove(client)


def handle_scpi_command(cmd: str) -> str:
    """Parse and execute SCPI command"""
    cmd = cmd.strip()
    if not cmd:
        return ""

    # IEEE 488.2 common commands
    if cmd == "*IDN?":
        return "N0GQ,Virtual-Smith-Chart,1.0,2026"

    elif cmd == "*RST":
        state['z0'] = 50.0
        state['active_trace'] = 1
        for tid in state['traces']:
            state['traces'][tid]['points'] = []
        state['swr_circle'] = None
        state['mode'] = 'IMPED'
        state['grid'] = True
        state['title'] = 'Smith Chart'
        state['last_freq'] = None
        error_queue.clear()
        asyncio.create_task(broadcast_state())
        return ""

    elif cmd == "SYST:ERR?":
        if error_queue:
            return error_queue.popleft()
        return "0,No error"

    # Smith chart commands
    elif cmd.startswith("SMIT:POIN "):
        parts = cmd[10:].split(',')
        if len(parts) != 2:
            add_error(-102, "Invalid number of parameters")
            return ""
        try:
            real = float(parts[0])
            imag = float(parts[1])
            tid = state['active_trace']
            state['traces'][tid]['points'].append({
                'real': real,
                'imag': imag,
                'freq': state['last_freq']
            })
            state['last_freq'] = None  # Reset after use
            asyncio.create_task(broadcast_state())
            return ""
        except ValueError:
            add_error(-104, "Data type error")
            return ""

    elif cmd == "SMIT:POIN?":
        tid = state['active_trace']
        points = state['traces'][tid]['points']
        if not points:
            return "0,0"
        last = points[-1]
        return f"{last['real']},{last['imag']}"

    elif cmd.startswith("SMIT:POIN:POL "):
        parts = cmd[15:].split(',')
        if len(parts) != 2:
            add_error(-102, "Invalid number of parameters")
            return ""
        try:
            mag = float(parts[0])
            angle = float(parts[1])
            real, imag = polar_to_rect(mag, angle)
            tid = state['active_trace']
            state['traces'][tid]['points'].append({
                'real': real,
                'imag': imag,
                'freq': state['last_freq']
            })
            state['last_freq'] = None
            asyncio.create_task(broadcast_state())
            return ""
        except ValueError:
            add_error(-104, "Data type error")
            return ""

    elif cmd.startswith("SMIT:Z0 "):
        try:
            z0 = float(cmd[8:])
            if z0 <= 0:
                add_error(-222, "Data out of range")
                return ""
            state['z0'] = z0
            asyncio.create_task(broadcast_state())
            return ""
        except ValueError:
            add_error(-104, "Data type error")
            return ""

    elif cmd == "SMIT:Z0?":
        return str(state['z0'])

    elif cmd.startswith("SMIT:TRAC "):
        try:
            tid = int(cmd[10:])
            if tid not in [1, 2, 3, 4]:
                add_error(-222, "Data out of range")
                return ""
            state['active_trace'] = tid
            return ""
        except ValueError:
            add_error(-104, "Data type error")
            return ""

    elif cmd == "SMIT:TRAC?":
        return str(state['active_trace'])

    elif cmd == "SMIT:TRAC:CLE":
        tid = state['active_trace']
        state['traces'][tid]['points'] = []
        asyncio.create_task(broadcast_state())
        return ""

    elif cmd == "SMIT:TRAC:ALL:CLE":
        for tid in state['traces']:
            state['traces'][tid]['points'] = []
        asyncio.create_task(broadcast_state())
        return ""

    elif cmd.startswith("SMIT:TRAC:COL "):
        color = cmd[14:].strip()
        if not color.startswith('#') or len(color) != 7:
            add_error(-104, "Invalid color format")
            return ""
        tid = state['active_trace']
        state['traces'][tid]['color'] = color
        asyncio.create_task(broadcast_state())
        return ""

    elif cmd == "SMIT:TRAC:COL?":
        tid = state['active_trace']
        return state['traces'][tid]['color']

    elif cmd.startswith("SMIT:TRAC:LAB "):
        label = cmd[14:].strip()
        tid = state['active_trace']
        state['traces'][tid]['label'] = label
        asyncio.create_task(broadcast_state())
        return ""

    elif cmd == "SMIT:TRAC:LAB?":
        tid = state['active_trace']
        return state['traces'][tid]['label']

    elif cmd.startswith("SMIT:MARK:FREQ "):
        try:
            freq = float(cmd[15:])
            state['last_freq'] = freq
            return ""
        except ValueError:
            add_error(-104, "Data type error")
            return ""

    elif cmd == "SMIT:MARK:FREQ?":
        if state['last_freq'] is None:
            return "0"
        return str(state['last_freq'])

    elif cmd.startswith("SMIT:SWR "):
        try:
            swr = float(cmd[9:])
            if swr < 1.0 or swr > 10.0:
                add_error(-222, "SWR out of range (1.0-10.0)")
                return ""
            state['swr_circle'] = swr
            asyncio.create_task(broadcast_state())
            return ""
        except ValueError:
            add_error(-104, "Data type error")
            return ""

    elif cmd == "SMIT:SWR?":
        if state['swr_circle'] is None:
            return "0"
        return str(state['swr_circle'])

    elif cmd.startswith("SMIT:MODE "):
        mode = cmd[10:].strip().upper()
        if mode not in ['IMPED', 'ADMIT']:
            add_error(-108, "Parameter not allowed")
            return ""
        state['mode'] = mode
        asyncio.create_task(broadcast_state())
        return ""

    elif cmd == "SMIT:MODE?":
        return state['mode']

    elif cmd.startswith("SMIT:GRID "):
        val = cmd[10:].strip().upper()
        if val == "ON":
            state['grid'] = True
        elif val == "OFF":
            state['grid'] = False
        else:
            add_error(-108, "Parameter not allowed")
            return ""
        asyncio.create_task(broadcast_state())
        return ""

    elif cmd == "SMIT:GRID?":
        return "ON" if state['grid'] else "OFF"

    elif cmd.startswith("CONF:TITLE "):
        state['title'] = cmd[11:].strip()
        asyncio.create_task(broadcast_state())
        return ""

    elif cmd == "CONF:TITLE?":
        return state['title']

    elif cmd.startswith("MQTT:CONF "):
        if not MQTT_AVAILABLE:
            add_error(-113, "MQTT not available")
            return ""
        parts = cmd[10:].split(',')
        if len(parts) != 2:
            add_error(-102, "Invalid number of parameters")
            return ""
        host = parts[0].strip()
        topic = parts[1].strip()
        mqtt_config['host'] = host
        mqtt_config['topic'] = topic
        asyncio.create_task(setup_mqtt())
        return ""

    elif cmd == "MQTT:CONF?":
        if mqtt_config['host'] is None:
            return "NOT_CONFIGURED"
        return f"{mqtt_config['host']},{mqtt_config['topic']}"

    else:
        add_error(-113, "Undefined header")
        return ""


class SCPIServer:
    """IEEE 488.2 SCPI command parser and TCP server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 5025):
        self.host = host
        self.port = port
        self.server: Optional[asyncio.Server] = None

    async def start(self):
        """Start the SCPI TCP server"""
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        print(f"SCPI TCP server listening on {self.host}:{self.port}")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle SCPI client connection"""
        addr = writer.get_extra_info('peername')

        try:
            while True:
                data = await reader.readline()
                if not data:
                    break

                cmd = data.decode('utf-8', errors='ignore').strip()
                if not cmd:
                    continue

                response = handle_scpi_command(cmd)
                if response:
                    writer.write(f"{response}\n".encode('utf-8'))
                    await writer.drain()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"SCPI client error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()


async def setup_mqtt():
    """Setup MQTT client"""
    global mqtt_client

    if not MQTT_AVAILABLE or not mqtt_config['host'] or not mqtt_config['topic']:
        return

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print(f"MQTT connected to {mqtt_config['host']}")
            client.subscribe(mqtt_config['topic'])
        else:
            print(f"MQTT connection failed: {rc}")

    def on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode('utf-8')
            data = json.loads(payload)

            # Expected format: {"z": [real, imag]} or {"z": [mag, angle], "polar": true}
            if 'z' in data and len(data['z']) == 2:
                if data.get('polar', False):
                    real, imag = polar_to_rect(data['z'][0], data['z'][1])
                else:
                    real, imag = data['z'][0], data['z'][1]

                tid = state['active_trace']
                state['traces'][tid]['points'].append({
                    'real': real,
                    'imag': imag,
                    'freq': data.get('freq', None)
                })
                asyncio.run_coroutine_threadsafe(broadcast_state(), event_loop)

        except Exception as e:
            print(f"MQTT message parse error: {e}")

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    try:
        mqtt_client.connect(mqtt_config['host'], 1883, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"MQTT connection error: {e}")


@app.get("/")
async def root():
    """Serve Smith chart frontend"""
    html_path = Path(__file__).parent.parent / "frontend" / "index.html"
    with open(html_path) as f:
        return HTMLResponse(content=f.read())


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    websocket_clients.append(websocket)

    # Send initial state
    await websocket.send_json({
        'z0': state['z0'],
        'active_trace': state['active_trace'],
        'traces': state['traces'],
        'swr_circle': state['swr_circle'],
        'mode': state['mode'],
        'grid': state['grid'],
        'title': state['title'],
        'timestamp': time.time()
    })

    try:
        while True:
            data = await websocket.receive_text()
            # Echo back for debugging
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        websocket_clients.remove(websocket)


async def main(scpi_port: int = 5025, http_port: int = 8011):
    """Start both SCPI TCP server and FastAPI HTTP/WebSocket server"""
    global event_loop
    event_loop = asyncio.get_running_loop()

    scpi_server = SCPIServer(port=scpi_port)
    await scpi_server.start()

    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=http_port,
        log_level="info"
    )
    server = uvicorn.Server(config)

    print("Virtual Smith Chart ready:")
    print(f"  - SCPI:      tcp://0.0.0.0:{scpi_port}")
    print(f"  - HTTP:      http://0.0.0.0:{http_port}")
    print(f"  - WebSocket: ws://0.0.0.0:{http_port}/ws")
    print("  - MQTT:      Use MQTT:CONF command to configure")

    await server.serve()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Virtual Smith Chart SCPI Server")
    parser.add_argument('--scpi-port', type=int, default=5025, help="SCPI TCP port (default: 5025)")
    parser.add_argument('--http-port', type=int, default=8011, help="HTTP/WebSocket port (default: 8011)")
    args = parser.parse_args()

    try:
        asyncio.run(main(scpi_port=args.scpi_port, http_port=args.http_port))
    except KeyboardInterrupt:
        print("\nShutdown.")
