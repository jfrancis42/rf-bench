#!/usr/bin/env python3
"""
Virtual Rotary Knob — SCPI TCP Server + WebSocket + MQTT (Bidirectional)

Phase 2 interactive control: Rotary knob with continuous or stepped rotation.

Exposes:
- SCPI TCP server on port 5103 (IEEE 488.2 standard instrument port)
- HTTP server on port 8103 (serves static frontend)
- WebSocket server on port 8103/ws (real-time bidirectional updates)
- MQTT subscriber (listens to configured topic for value updates)
- MQTT publisher (publishes value changes from user interaction)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-Knob,1.0,2026"
  *RST                     → Reset to defaults
  SYST:ERR?                → Query error queue
  MEAS:VAL <float>         → Set knob value
  MEAS:VAL?                → Query current value
  CONF:MIN <float>         → Set minimum value (default 0)
  CONF:MIN?                → Query minimum value
  CONF:MAX <float>         → Set maximum value (default 100)
  CONF:MAX?                → Query maximum value
  CONF:STEP <float>        → Set step size (0 = continuous, default 1)
  CONF:STEP?               → Query step size
  CONF:WRAP <bool>         → Enable/disable wrap-around (default 0)
  CONF:WRAP?               → Query wrap setting
  CONF:LABEL <string>      → Set knob label
  CONF:LABEL?              → Query knob label
  CONF:UNIT <string>       → Set display units
  CONF:UNIT?               → Query display units
  CONF:COL <color>         → Set knob color (hex, e.g., "#00ff88")
  CONF:COL?                → Query knob color
  CONF:SIZE <int>          → Set knob size in pixels (100-250, default 150)
  CONF:SIZE?               → Query knob size
  MQTT:CONF <host>,<sub_topic>[,<pub_topic>] → Configure MQTT
  MQTT:CONF?               → Query MQTT configuration

Bidirectional flow:
  1. User rotates knob in browser → WebSocket → backend → SCPI clients notified
  2. SCPI client sends MEAS:VAL → backend → WebSocket → browser updates
  3. MQTT message arrives → backend → WebSocket → browser updates
  4. User rotates knob → backend publishes to MQTT pub_topic

Example usage:
  echo "*IDN?" | nc localhost 5103
  echo "MEAS:VAL 75.5" | nc localhost 5103
  echo "CONF:MIN -10" | nc localhost 5103
  echo "CONF:MAX 10" | nc localhost 5103
  echo "CONF:STEP 0.5" | nc localhost 5103
  echo "CONF:LABEL Gain" | nc localhost 5103
  echo "CONF:UNIT dB" | nc localhost 5103
"""

import asyncio
import json
import socket
import sys
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, asdict

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse
    import uvicorn
except ImportError:
    print("Error: Missing dependencies. Install with:")
    print("  pip install fastapi uvicorn websockets --break-system-packages")
    sys.exit(1)

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None
    print("Warning: paho-mqtt not installed. MQTT support disabled.")
    print("  pip install paho-mqtt --break-system-packages")


# ============================================================================
# State Management
# ============================================================================

@dataclass
class KnobState:
    """Knob configuration and current value"""
    value: float = 50.0
    min_val: float = 0.0
    max_val: float = 100.0
    step: float = 1.0
    wrap: bool = False
    label: str = "Knob"
    units: str = ""
    color: str = "#00ff88"
    size: int = 150


knob_state = KnobState()
error_queue: List[str] = []
connected_websockets: List[WebSocket] = []

# MQTT state
mqtt_client: Optional[mqtt.Client] = None
mqtt_config = {
    "host": None,
    "sub_topic": None,
    "pub_topic": None
}


# ============================================================================
# MQTT Support
# ============================================================================

def on_mqtt_connect(client, userdata, flags, rc):
    """MQTT connection callback"""
    if rc == 0:
        print(f"MQTT connected to {mqtt_config['host']} with result code {mqtt.connack_string(rc)}")
        if mqtt_config['sub_topic']:
            client.subscribe(mqtt_config['sub_topic'])
            print(f"MQTT subscribed to topic: {mqtt_config['sub_topic']}")
    else:
        print(f"MQTT connection failed: {mqtt.connack_string(rc)}")


def on_mqtt_message(client, userdata, msg):
    """MQTT message callback - updates knob value"""
    try:
        payload = msg.payload.decode()
        value = float(payload)

        # Apply wrap or clamp
        if knob_state.wrap:
            # Wrap around
            range_size = knob_state.max_val - knob_state.min_val
            value = ((value - knob_state.min_val) % range_size) + knob_state.min_val
        else:
            # Clamp to range
            value = max(knob_state.min_val, min(knob_state.max_val, value))

        # Apply step if configured
        if knob_state.step > 0:
            value = round(value / knob_state.step) * knob_state.step

        knob_state.value = value
        print(f"MQTT received: {msg.topic} = {value}")

        # Broadcast to WebSocket clients
        asyncio.create_task(broadcast_state())

    except ValueError as e:
        print(f"MQTT message parse error: {e}")


async def setup_mqtt():
    """Initialize MQTT client if configured"""
    global mqtt_client

    if not mqtt or not mqtt_config['host']:
        return

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message

    try:
        mqtt_client.connect(mqtt_config['host'], 1883, 60)
        mqtt_client.loop_start()
        print(f"MQTT client started for {mqtt_config['host']}")
    except Exception as e:
        print(f"MQTT connection error: {e}")
        mqtt_client = None


def publish_mqtt_value(value: float):
    """Publish value change to MQTT pub_topic"""
    if mqtt_client and mqtt_config['pub_topic']:
        try:
            mqtt_client.publish(mqtt_config['pub_topic'], str(value))
            print(f"MQTT published: {mqtt_config['pub_topic']} = {value}")
        except Exception as e:
            print(f"MQTT publish error: {e}")


# ============================================================================
# WebSocket Broadcast
# ============================================================================

async def broadcast_state():
    """Send current state to all connected WebSocket clients"""
    if not connected_websockets:
        return

    message = json.dumps(asdict(knob_state))

    # Send to all connected clients
    for ws in connected_websockets[:]:
        try:
            await ws.send_text(message)
        except:
            connected_websockets.remove(ws)


# ============================================================================
# SCPI Command Handler
# ============================================================================

class SCPIServer:
    """IEEE 488.2 SCPI command parser and TCP server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 5103):
        self.host = host
        self.port = port
        self.server: Optional[asyncio.Server] = None

    async def start(self):
        """Start the SCPI TCP server"""
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        addr = self.server.sockets[0].getsockname()
        print(f"SCPI TCP server listening on {addr[0]}:{addr[1]}")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a single SCPI client connection"""
        addr = writer.get_extra_info('peername')
        print(f"SCPI client connected: {addr}")

        try:
            while True:
                data = await reader.readline()
                if not data:
                    break

                command = data.decode().strip()
                if not command:
                    continue

                print(f"SCPI RX: {command}")
                response = self.process_command(command)

                if response:
                    writer.write(f"{response}\n".encode())
                    await writer.drain()
                    print(f"SCPI TX: {response}")

                # Broadcast state changes to WebSocket clients
                await broadcast_state()

        except Exception as e:
            print(f"SCPI client error: {e}")

        finally:
            writer.close()
            await writer.wait_closed()
            print(f"SCPI client disconnected: {addr}")

    def process_command(self, command: str) -> Optional[str]:
        """Process a single SCPI command and return response"""
        cmd_upper = command.upper().strip()

        # IEEE 488.2 Common Commands
        if cmd_upper == "*IDN?":
            return "N0GQ,Virtual-Knob,1.0,2026"

        elif cmd_upper == "*RST":
            global knob_state
            knob_state = KnobState()
            return None

        elif cmd_upper == "SYST:ERR?":
            if error_queue:
                return error_queue.pop(0)
            return "0,No error"

        # Measurement commands
        elif cmd_upper.startswith("MEAS:VAL"):
            if "?" in cmd_upper:
                return str(knob_state.value)
            else:
                try:
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        value = float(parts[1])

                        # Apply wrap or clamp
                        if knob_state.wrap:
                            range_size = knob_state.max_val - knob_state.min_val
                            value = ((value - knob_state.min_val) % range_size) + knob_state.min_val
                        else:
                            value = max(knob_state.min_val, min(knob_state.max_val, value))

                        # Apply step if configured
                        if knob_state.step > 0:
                            value = round(value / knob_state.step) * knob_state.step

                        knob_state.value = value
                        # Publish to MQTT if configured
                        publish_mqtt_value(value)
                    return None
                except (ValueError, IndexError) as e:
                    error_queue.append(f"-100,Invalid parameter: {e}")
                    return None

        # Configuration commands
        elif cmd_upper.startswith("CONF:MIN"):
            if "?" in cmd_upper:
                return str(knob_state.min_val)
            else:
                try:
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        knob_state.min_val = float(parts[1])
                    return None
                except (ValueError, IndexError) as e:
                    error_queue.append(f"-100,Invalid parameter: {e}")
                    return None

        elif cmd_upper.startswith("CONF:MAX"):
            if "?" in cmd_upper:
                return str(knob_state.max_val)
            else:
                try:
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        knob_state.max_val = float(parts[1])
                    return None
                except (ValueError, IndexError) as e:
                    error_queue.append(f"-100,Invalid parameter: {e}")
                    return None

        elif cmd_upper.startswith("CONF:STEP"):
            if "?" in cmd_upper:
                return str(knob_state.step)
            else:
                try:
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        knob_state.step = float(parts[1])
                    return None
                except (ValueError, IndexError) as e:
                    error_queue.append(f"-100,Invalid parameter: {e}")
                    return None

        elif cmd_upper.startswith("CONF:WRAP"):
            if "?" in cmd_upper:
                return "1" if knob_state.wrap else "0"
            else:
                try:
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        value = parts[1].strip().upper()
                        if value in ['1', 'TRUE', 'ON', 'YES']:
                            knob_state.wrap = True
                        elif value in ['0', 'FALSE', 'OFF', 'NO']:
                            knob_state.wrap = False
                        else:
                            error_queue.append(f"-100,Invalid boolean: {value}")
                    return None
                except (ValueError, IndexError) as e:
                    error_queue.append(f"-100,Invalid parameter: {e}")
                    return None

        elif cmd_upper.startswith("CONF:LABEL"):
            if "?" in cmd_upper:
                return knob_state.label
            else:
                parts = command.split(maxsplit=1)
                if len(parts) == 2:
                    knob_state.label = parts[1].strip()
                return None

        elif cmd_upper.startswith("CONF:UNIT"):
            if "?" in cmd_upper:
                return knob_state.units
            else:
                parts = command.split(maxsplit=1)
                if len(parts) == 2:
                    knob_state.units = parts[1].strip()
                return None

        elif cmd_upper.startswith("CONF:COL"):
            if "?" in cmd_upper:
                return knob_state.color
            else:
                parts = command.split(maxsplit=1)
                if len(parts) == 2:
                    knob_state.color = parts[1].strip()
                return None

        elif cmd_upper.startswith("CONF:SIZE"):
            if "?" in cmd_upper:
                return str(knob_state.size)
            else:
                try:
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        size = int(parts[1])
                        if 100 <= size <= 250:
                            knob_state.size = size
                        else:
                            error_queue.append("-100,Size must be 100-250")
                    return None
                except (ValueError, IndexError) as e:
                    error_queue.append(f"-100,Invalid parameter: {e}")
                    return None

        # MQTT configuration
        elif cmd_upper.startswith("MQTT:CONF"):
            if "?" in cmd_upper:
                if mqtt_config['host']:
                    sub = mqtt_config['sub_topic'] or ""
                    pub = mqtt_config['pub_topic'] or ""
                    return f"{mqtt_config['host']},{sub},{pub}"
                return "Not configured"
            else:
                parts = command.split(maxsplit=1)
                if len(parts) == 2:
                    tokens = [t.strip() for t in parts[1].split(',')]
                    if len(tokens) >= 2:
                        mqtt_config['host'] = tokens[0]
                        mqtt_config['sub_topic'] = tokens[1]
                        mqtt_config['pub_topic'] = tokens[2] if len(tokens) >= 3 else None
                        asyncio.create_task(setup_mqtt())
                return None

        else:
            error_queue.append(f"-113,Undefined header: {command}")
            return None


# ============================================================================
# FastAPI Web Server
# ============================================================================

app = FastAPI()

# Serve static frontend
frontend_path = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=frontend_path), name="static")


@app.get("/")
async def root():
    """Serve the main HTML page"""
    index_file = frontend_path / "index.html"
    with open(index_file) as f:
        return HTMLResponse(content=f.read())


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for bidirectional real-time updates"""
    await websocket.accept()
    connected_websockets.append(websocket)
    print(f"WebSocket client connected (total: {len(connected_websockets)})")

    try:
        # Send initial state
        await websocket.send_text(json.dumps(asdict(knob_state)))

        # Listen for messages from client (user interaction)
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get('type') == 'value_change':
                value = float(message['value'])

                # Apply wrap or clamp
                if knob_state.wrap:
                    range_size = knob_state.max_val - knob_state.min_val
                    value = ((value - knob_state.min_val) % range_size) + knob_state.min_val
                else:
                    value = max(knob_state.min_val, min(knob_state.max_val, value))

                # Apply step if configured
                if knob_state.step > 0:
                    value = round(value / knob_state.step) * knob_state.step

                knob_state.value = value
                print(f"WebSocket value change: {value}")

                # Publish to MQTT if configured
                publish_mqtt_value(value)

                # Broadcast to all other WebSocket clients
                await broadcast_state()

    except WebSocketDisconnect:
        connected_websockets.remove(websocket)
        print(f"WebSocket client disconnected (total: {len(connected_websockets)})")


# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    """Start all servers"""
    # Start SCPI server
    scpi_server = SCPIServer()
    await scpi_server.start()

    # Start FastAPI server in background
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=8103,
        log_level="info"
    )
    server = uvicorn.Server(config)

    print("Virtual Rotary Knob ready:")
    print("  - SCPI:      tcp://0.0.0.0:5103")
    print("  - HTTP:      http://0.0.0.0:8103")
    print("  - WebSocket: ws://0.0.0.0:8103/ws")
    print("  - MQTT:      Use MQTT:CONF command to configure")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
