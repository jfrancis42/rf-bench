#!/usr/bin/env python3
"""
Virtual Analog Meter — SCPI TCP Server + WebSocket + MQTT bridge

Exposes:
- SCPI TCP server on port 5025 (IEEE 488.2 standard instrument port)
- HTTP server on port 8000 (serves static frontend)
- WebSocket server on port 8001 (real-time meter value updates)
- MQTT subscriber (listens to configured topic for value updates)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-Analog-Meter,1.0,2026"
  *RST                     → Reset to defaults
  SYST:ERR?                → Query error queue
  MEAS:VAL <float>         → Set displayed value
  MEAS:VAL?                → Query current value
  CONF:MIN <float>         → Set scale minimum
  CONF:MIN?                → Query scale minimum
  CONF:MAX <float>         → Set scale maximum
  CONF:MAX?                → Query scale maximum
  CONF:UNIT <string>       → Set display units (e.g., "dBm", "V", "A")
  CONF:UNIT?               → Query display units
  CONF:ZONE <id>,<v0>,<v1>,<color>  → Define colored zone (id 1-5)
  CONF:ZONE? <id>          → Query zone definition
  MQTT:CONF <host>,<topic> → Configure MQTT broker and topic to subscribe
  MQTT:CONF?               → Query MQTT configuration

Example usage:
  echo "*IDN?" | nc localhost 5025
  echo "MEAS:VAL 42.5" | nc localhost 5025
  echo "MQTT:CONF 10.1.0.20,bench/meter/value" | nc localhost 5025

  # Then publish to MQTT:
  mosquitto_pub -h 10.1.0.20 -t bench/meter/value -m "42.5"
"""

import asyncio
import json
import socket
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Try to import FastAPI/uvicorn; provide helpful error if missing
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse
    import uvicorn
except ImportError:
    print("ERROR: FastAPI and uvicorn are required.", file=sys.stderr)
    print("Install with: pip install fastapi uvicorn websockets --break-system-packages", file=sys.stderr)
    sys.exit(1)

# Try to import paho-mqtt; provide helpful error if missing
try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: paho-mqtt is required for MQTT support.", file=sys.stderr)
    print("Install with: pip install paho-mqtt --break-system-packages", file=sys.stderr)
    sys.exit(1)


class AnalogMeterState:
    """Instrument state and configuration"""

    def __init__(self):
        self.value: float = 0.0
        self.min_val: float = 0.0
        self.max_val: float = 100.0
        self.units: str = ""
        # Zones: {id: (v0, v1, color)}
        self.zones: Dict[int, Tuple[float, float, str]] = {
            1: (0.0, 33.0, '#226644'),   # Green: safe
            2: (33.0, 66.0, '#886600'),  # Yellow: caution
            3: (66.0, 100.0, '#882222'), # Red: danger
        }
        self.error_queue: List[str] = []
        # MQTT configuration
        self.mqtt_host: Optional[str] = None
        self.mqtt_topic: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize state for WebSocket broadcast"""
        return {
            'value': self.value,
            'min': self.min_val,
            'max': self.max_val,
            'units': self.units,
            'zones': [
                {'id': k, 'v0': v[0], 'v1': v[1], 'color': v[2]}
                for k, v in sorted(self.zones.items())
            ]
        }


# Global state
state = AnalogMeterState()
websocket_clients: List[WebSocket] = []
mqtt_client: Optional[mqtt.Client] = None
event_loop: Optional[asyncio.AbstractEventLoop] = None

# FastAPI app
app = FastAPI(title="Virtual Analog Meter")


# ==============================================================================
# WebSocket endpoint for real-time updates
# ==============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    websocket_clients.append(websocket)
    print(f"WebSocket client connected. Total clients: {len(websocket_clients)}")

    # Send initial state
    await websocket.send_json(state.to_dict())

    try:
        while True:
            # Keep connection alive; updates are pushed via broadcast
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_clients.remove(websocket)
        print(f"WebSocket client disconnected. Total clients: {len(websocket_clients)}")


async def broadcast_state():
    """Broadcast current state to all connected WebSocket clients"""
    if not websocket_clients:
        return

    message = json.dumps(state.to_dict())
    dead_clients = []

    for client in websocket_clients:
        try:
            await client.send_text(message)
        except Exception:
            dead_clients.append(client)

    # Clean up dead connections
    for client in dead_clients:
        websocket_clients.remove(client)


# ==============================================================================
# HTTP endpoint for simple web interface
# ==============================================================================

@app.get("/")
async def get_index():
    """Serve the web UI"""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return HTMLResponse(content=frontend_path.read_text())
    else:
        return HTMLResponse(
            content="<html><body><h1>Virtual Analog Meter</h1>"
                    "<p>Frontend not built. See README.md</p></body></html>"
        )


# Mount static files if frontend build exists
frontend_build = Path(__file__).parent.parent / "frontend" / "build"
if frontend_build.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_build)), name="static")


# ==============================================================================
# MQTT Client
# ==============================================================================

def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    """Callback when MQTT client connects"""
    print(f"MQTT connected to {state.mqtt_host} with result code {reason_code}")
    if state.mqtt_topic:
        client.subscribe(state.mqtt_topic)
        print(f"MQTT subscribed to topic: {state.mqtt_topic}")


def on_mqtt_message(client, userdata, msg):
    """Callback when MQTT message received"""
    try:
        value = float(msg.payload.decode())
        state.value = value
        print(f"MQTT received: {msg.topic} = {value}")
        # Broadcast to WebSocket clients - schedule in main event loop
        if event_loop:
            asyncio.run_coroutine_threadsafe(broadcast_state(), event_loop)
    except ValueError as e:
        print(f"MQTT parse error on {msg.topic}: {e}")


def start_mqtt_client(host: str, topic: str):
    """Start MQTT client in background (synchronous)"""
    global mqtt_client

    # Stop existing client if any
    if mqtt_client:
        try:
            mqtt_client.disconnect()
            mqtt_client.loop_stop()
        except:
            pass

    # Create new client (paho-mqtt v2.x API)
    mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message

    try:
        mqtt_client.connect(host, 1883, 60)
        mqtt_client.loop_start()
        print(f"MQTT client started for {host}:{1883}")
    except Exception as e:
        print(f"MQTT connection failed: {e}")
        state.error_queue.append(f"-221,MQTT connection failed: {e}")


# ==============================================================================
# SCPI TCP Server
# ==============================================================================

class SCPIServer:
    """IEEE 488.2 SCPI command parser and TCP server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 5002):
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

                command = data.decode('utf-8').strip()
                if not command:
                    continue

                print(f"SCPI RX: {command}")
                response = self.process_command(command)

                if response:
                    writer.write(f"{response}\n".encode('utf-8'))
                    await writer.drain()
                    print(f"SCPI TX: {response}")
        except Exception as e:
            print(f"SCPI client error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            print(f"SCPI client disconnected: {addr}")

    def process_command(self, cmd: str) -> Optional[str]:
        """Process a single SCPI command, return response string or None"""
        cmd_original = cmd.strip()
        cmd = cmd.upper().strip()

        # IEEE 488.2 common commands
        if cmd == "*IDN?":
            return "N0GQ,Virtual-Analog-Meter,1.0,2026"

        if cmd == "*RST":
            global state
            state = AnalogMeterState()
            asyncio.create_task(broadcast_state())
            return None

        if cmd == "SYST:ERR?":
            if state.error_queue:
                return state.error_queue.pop(0)
            else:
                return "0,No error"

        # Measurement value
        if cmd.startswith("MEAS:VAL"):
            if "?" in cmd:
                return str(state.value)
            else:
                try:
                    val = float(cmd.split()[1])
                    state.value = val
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Data out of range: {e}")
                    return None

        # Configuration commands
        if cmd.startswith("CONF:MIN"):
            if "?" in cmd:
                return str(state.min_val)
            else:
                try:
                    state.min_val = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Data out of range: {e}")
                    return None

        if cmd.startswith("CONF:MAX"):
            if "?" in cmd:
                return str(state.max_val)
            else:
                try:
                    state.max_val = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Data out of range: {e}")
                    return None

        if cmd.startswith("CONF:UNIT"):
            if "?" in cmd:
                return state.units
            else:
                try:
                    state.units = cmd.split(maxsplit=1)[1].strip('"')
                    asyncio.create_task(broadcast_state())
                    return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        if cmd.startswith("CONF:ZONE"):
            parts = cmd.split(maxsplit=1)
            if "?" in cmd:
                try:
                    zone_id = int(parts[1].strip("?"))
                    if zone_id in state.zones:
                        v0, v1, color = state.zones[zone_id]
                        return f"{v0},{v1},{color}"
                    else:
                        return "-220,Parameter error"
                except (IndexError, ValueError):
                    return "-220,Parameter error"
            else:
                try:
                    # Format: CONF:ZONE 1,0,50,#226644
                    params = parts[1].split(',')
                    zone_id = int(params[0])
                    v0 = float(params[1])
                    v1 = float(params[2])
                    color = params[3].strip()
                    state.zones[zone_id] = (v0, v1, color)
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-220,Parameter error: {e}")
                    return None

        # MQTT configuration
        if cmd.startswith("MQTT:CONF"):
            if "?" in cmd:
                if state.mqtt_host and state.mqtt_topic:
                    return f"{state.mqtt_host},{state.mqtt_topic}"
                else:
                    return "Not configured"
            else:
                try:
                    # Use original command to preserve case of parameters
                    params = cmd_original.split(maxsplit=1)[1].split(',')
                    mqtt_host = params[0].strip()
                    mqtt_topic = params[1].strip()

                    # Configure and start MQTT client
                    state.mqtt_host = mqtt_host
                    state.mqtt_topic = mqtt_topic
                    start_mqtt_client(mqtt_host, mqtt_topic)
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-220,MQTT config error: {e}")
                    return None

        # Unknown command
        state.error_queue.append(f"-113,Undefined header: {cmd}")
        return None


# ==============================================================================
# Main
# ==============================================================================

async def main():
    """Start both SCPI TCP server and FastAPI HTTP/WebSocket server"""
    global event_loop
    event_loop = asyncio.get_running_loop()

    # Start SCPI server
    scpi_server = SCPIServer()
    await scpi_server.start()

    # Start FastAPI server in background
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=8002,
        log_level="info"
    )
    server = uvicorn.Server(config)

    print("Virtual Analog Meter ready:")
    print("  - SCPI:      tcp://0.0.0.0:5002")
    print("  - HTTP:      http://0.0.0.0:8002")
    print("  - WebSocket: ws://0.0.0.0:8002/ws")
    print("  - MQTT:      Use MQTT:CONF command to configure")
    print("")
    print("Example MQTT setup:")
    print('  echo "MQTT:CONF 10.1.0.20,bench/meter/value" | nc localhost 5002')
    print('  mosquitto_pub -h 10.1.0.20 -t bench/meter/value -m "75.5"')

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
