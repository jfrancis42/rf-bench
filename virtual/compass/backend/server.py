#!/usr/bin/env python3
"""
Virtual Compass — SCPI TCP Server + WebSocket + MQTT bridge

Directional indicator displaying heading with compass rose, cardinal directions,
and optional customization.

Exposes:
- SCPI TCP server on port 5033 (IEEE 488.2 standard instrument port)
- HTTP server on port 8009 (serves static frontend)
- WebSocket server on port 8009/ws (real-time compass updates)
- MQTT subscriber (listens to configured topic for heading values)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-Compass,1.0,2026"
  *RST                     → Reset to defaults
  SYST:ERR?                → Query error queue
  MEAS:HEAD <float>        → Set heading in degrees (0-360, 0=North)
  MEAS:HEAD?               → Query current heading
  CONF:SIZE <int>          → Set compass size (200-600, default 350)
  CONF:SIZE?               → Query compass size
  CONF:COL <color>         → Set needle color (hex, e.g., "#ff0000")
  CONF:COL?                → Query needle color
  CONF:LABEL <ON|OFF>      → Enable/disable cardinal labels (default ON)
  CONF:LABEL?              → Query label state
  CONF:ROSE <ON|OFF>       → Enable/disable compass rose (default ON)
  CONF:ROSE?               → Query rose state
  CONF:TITLE <string>      → Set display title
  CONF:TITLE?              → Query title
  MQTT:CONF <host>,<topic> → Configure MQTT broker and topic
  MQTT:CONF?               → Query MQTT configuration

Example usage:
  echo "MEAS:HEAD 45.5" | nc localhost 5033  # NE
  echo "MEAS:HEAD 180" | nc localhost 5033   # S
  echo "CONF:COL #ff0000" | nc localhost 5033
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional

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
except ImportError:
    print("ERROR: paho-mqtt is required for MQTT support.", file=sys.stderr)
    print("Install with: pip install paho-mqtt --break-system-packages", file=sys.stderr)
    sys.exit(1)


class CompassState:
    """Instrument state and configuration"""

    def __init__(self):
        self.heading: float = 0.0  # degrees, 0=North
        self.size: int = 350  # pixels
        self.needle_color: str = "#ff0000"
        self.show_labels: bool = True
        self.show_rose: bool = True
        self.title: str = "Compass"
        self.error_queue: List[str] = []
        # MQTT configuration
        self.mqtt_host: Optional[str] = None
        self.mqtt_topic: Optional[str] = None

    def set_heading(self, heading: float):
        """Set heading with normalization to 0-360"""
        self.heading = heading % 360.0

    def to_dict(self) -> dict:
        """Serialize state for WebSocket broadcast"""
        return {
            'heading': self.heading,
            'size': self.size,
            'needleColor': self.needle_color,
            'showLabels': self.show_labels,
            'showRose': self.show_rose,
            'title': self.title
        }


# Global state
state = CompassState()
websocket_clients: List[WebSocket] = []
mqtt_client: Optional[mqtt.Client] = None
event_loop: Optional[asyncio.AbstractEventLoop] = None

# FastAPI app
app = FastAPI(title="Virtual Compass")


# ==============================================================================
# WebSocket endpoint
# ==============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    websocket_clients.append(websocket)
    print(f"WebSocket client connected. Total clients: {len(websocket_clients)}")

    await websocket.send_json(state.to_dict())

    try:
        while True:
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

    for client in dead_clients:
        websocket_clients.remove(client)


# ==============================================================================
# HTTP endpoint
# ==============================================================================

@app.get("/")
async def get_index():
    """Serve the web UI"""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return HTMLResponse(content=frontend_path.read_text())
    else:
        return HTMLResponse(
            content="<html><body><h1>Virtual Compass</h1>"
                    "<p>Frontend not found. See README.md</p></body></html>"
        )


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
        heading = float(msg.payload.decode())
        state.set_heading(heading)
        print(f"MQTT received: {msg.topic} = {heading}°")
        if event_loop:
            asyncio.run_coroutine_threadsafe(broadcast_state(), event_loop)
    except ValueError as e:
        print(f"MQTT parse error on {msg.topic}: {e}")


def start_mqtt_client(host: str, topic: str):
    """Start MQTT client in background"""
    global mqtt_client

    if mqtt_client:
        try:
            mqtt_client.disconnect()
            mqtt_client.loop_stop()
        except:
            pass

    mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message

    try:
        mqtt_client.connect(host, 1883, 60)
        mqtt_client.loop_start()
        print(f"MQTT client started for {host}:1883")
    except Exception as e:
        print(f"MQTT connection failed: {e}")
        state.error_queue.append(f"-221,MQTT connection failed: {e}")


# ==============================================================================
# SCPI TCP Server
# ==============================================================================

class SCPIServer:
    """IEEE 488.2 SCPI command parser and TCP server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 5033):
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
        """Process a single SCPI command"""
        cmd_original = cmd.strip()
        cmd_upper = cmd.upper().strip()

        # IEEE 488.2 common commands
        if cmd_upper == "*IDN?":
            return "N0GQ,Virtual-Compass,1.0,2026"

        if cmd_upper == "*RST":
            global state
            state = CompassState()
            asyncio.create_task(broadcast_state())
            return None

        if cmd_upper == "SYST:ERR?":
            if state.error_queue:
                return state.error_queue.pop(0)
            else:
                return "0,No error"

        # Measurement commands
        if cmd_upper.startswith("MEAS:HEAD"):
            if "?" in cmd_upper:
                return str(state.heading)
            else:
                try:
                    heading = float(cmd.split()[1])
                    state.set_heading(heading)
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid heading: {e}")
                    return None

        # Configuration commands
        if cmd_upper.startswith("CONF:SIZE"):
            if "?" in cmd_upper:
                return str(state.size)
            else:
                try:
                    size = int(cmd.split()[1])
                    if 200 <= size <= 600:
                        state.size = size
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Size must be 200-600")
                        return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid size: {e}")
                    return None

        if cmd_upper.startswith("CONF:COL"):
            if "?" in cmd_upper:
                return state.needle_color
            else:
                try:
                    color = cmd.split(maxsplit=1)[1].strip('"')
                    if color.startswith('#') and len(color) in [4, 7]:
                        state.needle_color = color
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Invalid color format")
                        return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        if cmd_upper.startswith("CONF:LABEL"):
            if "?" in cmd_upper:
                return "ON" if state.show_labels else "OFF"
            else:
                try:
                    setting = cmd.split()[1].strip('"').upper()
                    if setting in ["ON", "OFF"]:
                        state.show_labels = (setting == "ON")
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Label must be ON or OFF")
                        return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        if cmd_upper.startswith("CONF:ROSE"):
            if "?" in cmd_upper:
                return "ON" if state.show_rose else "OFF"
            else:
                try:
                    setting = cmd.split()[1].strip('"').upper()
                    if setting in ["ON", "OFF"]:
                        state.show_rose = (setting == "ON")
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Rose must be ON or OFF")
                        return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        if cmd_upper.startswith("CONF:TITLE"):
            if "?" in cmd_upper:
                return state.title
            else:
                try:
                    state.title = cmd.split(maxsplit=1)[1].strip('"')
                    asyncio.create_task(broadcast_state())
                    return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        # MQTT configuration
        if cmd_upper.startswith("MQTT:CONF"):
            if "?" in cmd_upper:
                if state.mqtt_host and state.mqtt_topic:
                    return f"{state.mqtt_host},{state.mqtt_topic}"
                else:
                    return "Not configured"
            else:
                try:
                    params = cmd_original.split(maxsplit=1)[1].split(',')
                    mqtt_host = params[0].strip()
                    mqtt_topic = params[1].strip()
                    state.mqtt_host = mqtt_host
                    state.mqtt_topic = mqtt_topic
                    start_mqtt_client(mqtt_host, mqtt_topic)
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-220,MQTT config error: {e}")
                    return None

        state.error_queue.append(f"-113,Undefined header: {cmd}")
        return None


# ==============================================================================
# Main
# ==============================================================================

async def main():
    """Start both SCPI TCP server and FastAPI HTTP/WebSocket server"""
    global event_loop
    event_loop = asyncio.get_running_loop()

    scpi_server = SCPIServer()
    await scpi_server.start()

    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=9001,
        log_level="info"
    )
    server = uvicorn.Server(config)

    print("Virtual Compass ready:")
    print("  - SCPI:      tcp://0.0.0.0:5033")
    print("  - HTTP:      http://0.0.0.0:8009")
    print("  - WebSocket: ws://0.0.0.0:8009/ws")
    print("  - MQTT:      Use MQTT:CONF command to configure")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
