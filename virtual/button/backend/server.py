#!/usr/bin/env python3
"""
Virtual Push Button — SCPI TCP Server + WebSocket + MQTT (Bidirectional)

Phase 2 interactive control: Momentary push button (press and release).

Exposes:
- SCPI TCP server on port 5102 (IEEE 488.2 standard instrument port)
- HTTP server on port 8102 (serves static frontend)
- WebSocket server on port 8102/ws (real-time bidirectional updates)
- MQTT subscriber (listens to configured topic for button presses)
- MQTT publisher (publishes button press events)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-Button,1.0,2026"
  *RST                     → Reset to defaults
  SYST:ERR?                → Query error queue
  STAT:PRESS               → Trigger a button press (momentary)
  STAT:PRESS?              → Query if button is currently pressed (0 or 1)
  STAT:COUNT?              → Query total press count since startup
  STAT:COUNT:CLEAR         → Clear press count
  CONF:LABEL <string>      → Set button label
  CONF:LABEL?              → Query button label
  CONF:COL <color>         → Set button color (hex, e.g., "#00ff00")
  CONF:COL?                → Query button color
  CONF:PRESSCOL <color>    → Set pressed color (hex, default brighter)
  CONF:PRESSCOL?           → Query pressed color
  CONF:SIZE <int>          → Set button size in pixels (80-200, default 120)
  CONF:SIZE?               → Query button size
  MQTT:CONF <host>,<sub_topic>[,<pub_topic>] → Configure MQTT
  MQTT:CONF?               → Query MQTT configuration

Bidirectional flow:
  1. User clicks button in browser → WebSocket → backend → SCPI clients notified
  2. SCPI client sends STAT:PRESS → backend → WebSocket → browser shows press
  3. MQTT message arrives → backend → WebSocket → browser shows press
  4. User clicks button → backend publishes to MQTT pub_topic

Example usage:
  echo "*IDN?" | nc localhost 5102
  echo "STAT:PRESS" | nc localhost 5102          # Trigger button press
  echo "STAT:COUNT?" | nc localhost 5102         # Query press count
  echo "CONF:LABEL Sweep" | nc localhost 5102
  echo "CONF:COL #ff8800" | nc localhost 5102
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
class ButtonState:
    """Button configuration and current state"""
    pressed: bool = False
    press_count: int = 0
    label: str = "Button"
    color: str = "#4488ff"
    press_color: str = "#66aaff"
    size: int = 120


button_state = ButtonState()
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
    """MQTT message callback - triggers button press"""
    try:
        payload = msg.payload.decode().strip().upper()

        # Any non-zero message triggers press
        if payload in ['1', 'PRESS', 'CLICK', 'TRIGGER']:
            print(f"MQTT received: {msg.topic} = PRESS")
            asyncio.create_task(trigger_button_press())

    except Exception as e:
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


def publish_mqtt_press():
    """Publish button press event to MQTT pub_topic"""
    if mqtt_client and mqtt_config['pub_topic']:
        try:
            mqtt_client.publish(mqtt_config['pub_topic'], "1")
            print(f"MQTT published: {mqtt_config['pub_topic']} = 1")
        except Exception as e:
            print(f"MQTT publish error: {e}")


# ============================================================================
# Button Press Logic
# ============================================================================

async def trigger_button_press():
    """Trigger a momentary button press"""
    button_state.pressed = True
    button_state.press_count += 1
    print(f"Button pressed (count: {button_state.press_count})")

    # Broadcast press state
    await broadcast_state()

    # Publish to MQTT
    publish_mqtt_press()

    # Hold for 200ms (visual feedback)
    await asyncio.sleep(0.2)

    # Release
    button_state.pressed = False
    await broadcast_state()


# ============================================================================
# WebSocket Broadcast
# ============================================================================

async def broadcast_state():
    """Send current state to all connected WebSocket clients"""
    if not connected_websockets:
        return

    message = json.dumps(asdict(button_state))

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

    def __init__(self, host: str = "0.0.0.0", port: int = 5102):
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
                response = await self.process_command(command)

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

    async def process_command(self, command: str) -> Optional[str]:
        """Process a single SCPI command and return response"""
        cmd_upper = command.upper().strip()

        # IEEE 488.2 Common Commands
        if cmd_upper == "*IDN?":
            return "N0GQ,Virtual-Button,1.0,2026"

        elif cmd_upper == "*RST":
            global button_state
            button_state = ButtonState()
            return None

        elif cmd_upper == "SYST:ERR?":
            if error_queue:
                return error_queue.pop(0)
            return "0,No error"

        # State commands
        elif cmd_upper == "STAT:PRESS":
            # Trigger button press
            await trigger_button_press()
            return None

        elif cmd_upper == "STAT:PRESS?":
            return "1" if button_state.pressed else "0"

        elif cmd_upper == "STAT:COUNT?":
            return str(button_state.press_count)

        elif cmd_upper == "STAT:COUNT:CLEAR":
            button_state.press_count = 0
            return None

        # Configuration commands
        elif cmd_upper.startswith("CONF:LABEL"):
            if "?" in cmd_upper:
                return button_state.label
            else:
                parts = command.split(maxsplit=1)
                if len(parts) == 2:
                    button_state.label = parts[1].strip()
                return None

        elif cmd_upper.startswith("CONF:COL"):
            if "?" in cmd_upper:
                return button_state.color
            else:
                parts = command.split(maxsplit=1)
                if len(parts) == 2:
                    button_state.color = parts[1].strip()
                return None

        elif cmd_upper.startswith("CONF:PRESSCOL"):
            if "?" in cmd_upper:
                return button_state.press_color
            else:
                parts = command.split(maxsplit=1)
                if len(parts) == 2:
                    button_state.press_color = parts[1].strip()
                return None

        elif cmd_upper.startswith("CONF:SIZE"):
            if "?" in cmd_upper:
                return str(button_state.size)
            else:
                try:
                    parts = command.split(maxsplit=1)
                    if len(parts) == 2:
                        size = int(parts[1])
                        if 80 <= size <= 200:
                            button_state.size = size
                        else:
                            error_queue.append("-100,Size must be 80-200")
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
        await websocket.send_text(json.dumps(asdict(button_state)))

        # Listen for messages from client (user interaction)
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get('type') == 'press':
                print(f"WebSocket button press from user")
                await trigger_button_press()

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
        port=8102,
        log_level="info"
    )
    server = uvicorn.Server(config)

    print("Virtual Push Button ready:")
    print("  - SCPI:      tcp://0.0.0.0:5102")
    print("  - HTTP:      http://0.0.0.0:8102")
    print("  - WebSocket: ws://0.0.0.0:8102/ws")
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
