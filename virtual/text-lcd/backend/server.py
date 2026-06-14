#!/usr/bin/env python3
"""
Virtual Text LCD — SCPI TCP Server + WebSocket + MQTT bridge

Streaming text terminal display with configurable scrollback buffer, color,
and terminal-style formatting.

Exposes:
- SCPI TCP server on port 5031 (IEEE 488.2 standard instrument port)
- HTTP server on port 8007 (serves static frontend)
- WebSocket server on port 8007/ws (real-time text updates)
- MQTT subscriber (listens to configured topic for text messages)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-Text-LCD,1.0,2026"
  *RST                     → Reset to defaults, clear buffer
  SYST:ERR?                → Query error queue
  DISP:TEXT <string>       → Append text line to display
  DISP:TEXT?               → Query number of lines in buffer
  DISP:CLEAR               → Clear all text
  CONF:LINES <int>         → Set scrollback buffer (10-1000, default 50)
  CONF:LINES?              → Query scrollback lines
  CONF:SIZE <int>          → Set font size (10-24, default 14)
  CONF:SIZE?               → Query font size
  CONF:COL <color>         → Set text color (hex, e.g., "#00ff00")
  CONF:COL?                → Query text color
  CONF:TITLE <string>      → Set terminal title
  CONF:TITLE?              → Query title
  MQTT:CONF <host>,<topic> → Configure MQTT broker and topic
  MQTT:CONF?               → Query MQTT configuration

Example usage:
  echo "DISP:TEXT System initialized" | nc localhost 5031
  echo "DISP:TEXT Temperature: 25.3°C" | nc localhost 5031
  echo "DISP:CLEAR" | nc localhost 5031
"""

import asyncio
import json
import sys
import time
from collections import deque
from pathlib import Path
from typing import List, Optional

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse, FileResponse
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


class TextLCDState:
    """Instrument state and configuration"""

    def __init__(self):
        self.max_lines: int = 50
        self.text_lines: deque = deque(maxlen=50)
        self.font_size: int = 14
        self.color: str = "#000000"
        self.title: str = "Terminal"
        self.error_queue: List[str] = []
        # MQTT configuration
        self.mqtt_host: Optional[str] = None
        self.mqtt_topic: Optional[str] = None

    def add_line(self, text: str):
        """Add a text line with timestamp"""
        timestamp = time.strftime("%H:%M:%S")
        self.text_lines.append(f"[{timestamp}] {text}")

    def set_max_lines(self, lines: int):
        """Change scrollback buffer size"""
        self.max_lines = lines
        new_lines = deque(self.text_lines, maxlen=lines)
        self.text_lines = new_lines

    def clear_lines(self):
        """Clear all text"""
        self.text_lines.clear()

    def to_dict(self) -> dict:
        """Serialize state for WebSocket broadcast"""
        return {
            'lines': list(self.text_lines),
            'maxLines': self.max_lines,
            'fontSize': self.font_size,
            'color': self.color,
            'title': self.title
        }


# Global state
state = TextLCDState()
websocket_clients: List[WebSocket] = []
mqtt_client: Optional[mqtt.Client] = None
event_loop: Optional[asyncio.AbstractEventLoop] = None

# FastAPI app
app = FastAPI(title="Virtual Text LCD")

# Mount frontend directory for static files (font)
frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


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
            content="<html><body><h1>Virtual Text LCD</h1>"
                    "<p>Frontend not found. See README.md</p></body></html>"
        )


@app.get("/test")
async def test_route():
    """Test route"""
    return {"message": "test works"}


@app.get("/DotMatrix.TTF")
async def get_font():
    """Serve the Dot Matrix font"""
    font_path = Path(__file__).parent.parent / "frontend" / "DotMatrix.TTF"
    print(f"Font requested. Path: {font_path}, Exists: {font_path.exists()}")
    if font_path.exists():
        return FileResponse(font_path, media_type="font/ttf")
    else:
        print(f"Font NOT FOUND at {font_path}")
        return HTMLResponse(content=f"Font not found at {font_path}", status_code=404)


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
        text = msg.payload.decode()
        state.add_line(text)
        print(f"MQTT received: {msg.topic} = {text}")
        if event_loop:
            asyncio.run_coroutine_threadsafe(broadcast_state(), event_loop)
    except Exception as e:
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

    def __init__(self, host: str = "0.0.0.0", port: int = 5006):
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
            return "N0GQ,Virtual-Text-LCD,1.0,2026"

        if cmd_upper == "*RST":
            global state
            state = TextLCDState()
            asyncio.create_task(broadcast_state())
            return None

        if cmd_upper == "SYST:ERR?":
            if state.error_queue:
                return state.error_queue.pop(0)
            else:
                return "0,No error"

        # Display commands
        if cmd_upper.startswith("DISP:TEXT"):
            if "?" in cmd_upper:
                return str(len(state.text_lines))
            else:
                try:
                    text = cmd_original.split(maxsplit=1)[1].strip('"')
                    state.add_line(text)
                    asyncio.create_task(broadcast_state())
                    return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        if cmd_upper == "DISP:CLEAR":
            state.clear_lines()
            asyncio.create_task(broadcast_state())
            return None

        # Configuration commands
        if cmd_upper.startswith("CONF:LINES"):
            if "?" in cmd_upper:
                return str(state.max_lines)
            else:
                try:
                    lines = int(cmd.split()[1])
                    if 10 <= lines <= 1000:
                        state.set_max_lines(lines)
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Lines must be 10-1000")
                        return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid lines: {e}")
                    return None

        if cmd_upper.startswith("CONF:SIZE"):
            if "?" in cmd_upper:
                return str(state.font_size)
            else:
                try:
                    size = int(cmd.split()[1])
                    if 10 <= size <= 24:
                        state.font_size = size
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Size must be 10-24")
                        return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid size: {e}")
                    return None

        if cmd_upper.startswith("CONF:COL"):
            if "?" in cmd_upper:
                return state.color
            else:
                try:
                    color = cmd.split(maxsplit=1)[1].strip('"')
                    if color.startswith('#') and len(color) in [4, 7]:
                        state.color = color
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Invalid color format")
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
        port=8006,
        log_level="info"
    )
    server = uvicorn.Server(config)

    print("Virtual Text LCD ready:")
    print("  - SCPI:      tcp://0.0.0.0:5006")
    print("  - HTTP:      http://0.0.0.0:8006")
    print("  - WebSocket: ws://0.0.0.0:8006/ws")
    print("  - MQTT:      Use MQTT:CONF command to configure")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
