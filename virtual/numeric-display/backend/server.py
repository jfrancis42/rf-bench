#!/usr/bin/env python3
"""
Virtual Numeric Display — SCPI TCP Server + WebSocket + MQTT bridge

Exposes:
- SCPI TCP server on port 5025 (IEEE 488.2 standard instrument port)
- HTTP server on port 8000 (serves static frontend)
- WebSocket server on port 8001 (real-time display value updates)
- MQTT subscriber (listens to configured topic for value updates)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-Numeric-Display,1.0,2026"
  *RST                     → Reset to defaults
  SYST:ERR?                → Query error queue
  MEAS:VAL <float>         → Set displayed value
  MEAS:VAL?                → Query current value
  CONF:PREC <int>          → Set decimal precision (0-6, default 2)
  CONF:PREC?               → Query decimal precision
  CONF:DIG <int>           → Set total digit count (4-12, default 8)
  CONF:DIG?                → Query digit count
  CONF:UNIT <string>       → Set display units (e.g., "MHz", "V", "A", "°C")
  CONF:UNIT?               → Query display units
  CONF:SIZE <int>          → Set font size (20-120, default 80)
  CONF:SIZE?               → Query font size
  CONF:COL <color>         → Set text color (hex, e.g., "#00ff00")
  CONF:COL?                → Query text color
  CONF:STYLE <string>      → Set display style: "7SEG", "PLAIN", "LED", or "NIXIE" (default 7SEG)
  CONF:STYLE?              → Query display style
  MQTT:CONF <host>,<topic> → Configure MQTT broker and topic to subscribe
  MQTT:CONF?               → Query MQTT configuration

Example usage:
  echo "*IDN?" | nc localhost 5025
  echo "MEAS:VAL 14.257" | nc localhost 5025
  echo "MQTT:CONF 10.1.0.20,bench/display/value" | nc localhost 5025
  mosquitto_pub -h 10.1.0.20 -t bench/display/value -m "14.257"
"""

import asyncio
import json
import socket
import sys
from pathlib import Path
from typing import List, Optional

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


class NumericDisplayState:
    """Instrument state and configuration"""

    def __init__(self):
        self.value: float = 0.0
        self.precision: int = 2           # Decimal places (0-6)
        self.digits: int = 8              # Total digit count (4-12, default 8)
        self.units: str = ""
        self.font_size: int = 80          # Pixels (20-120)
        self.color: str = "#00ff00"       # Hex color
        self.style: str = "7SEG"          # "7SEG", "PLAIN", "LED", "NIXIE"
        self.error_queue: List[str] = []
        # MQTT configuration
        self.mqtt_host: Optional[str] = None
        self.mqtt_topic: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize state for WebSocket broadcast"""
        return {
            'value': self.value,
            'precision': self.precision,
            'digits': self.digits,
            'units': self.units,
            'fontSize': self.font_size,
            'color': self.color,
            'style': self.style
        }


# Global state
state = NumericDisplayState()
websocket_clients: List[WebSocket] = []
mqtt_client: Optional[mqtt.Client] = None
event_loop: Optional[asyncio.AbstractEventLoop] = None

# FastAPI app
app = FastAPI(title="Virtual Numeric Display")


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
            content="<html><body><h1>Virtual Numeric Display</h1>"
                    "<p>Frontend not found. See README.md</p></body></html>"
        )


# Mount static files if frontend build exists
frontend_build = Path(__file__).parent.parent / "frontend" / "build"
if frontend_build.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_build)), name="static")

# Mount fonts directory
frontend_fonts = Path(__file__).parent.parent / "frontend" / "fonts-DSEG_v046"
if frontend_fonts.exists():
    app.mount("/fonts-DSEG_v046", StaticFiles(directory=str(frontend_fonts)), name="fonts")


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

    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
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
        cmd_upper = cmd.upper().strip()

        # IEEE 488.2 common commands
        if cmd_upper == "*IDN?":
            return "N0GQ,Virtual-Numeric-Display,1.0,2026"

        if cmd_upper == "*RST":
            global state
            state = NumericDisplayState()
            asyncio.create_task(broadcast_state())
            return None

        if cmd_upper == "SYST:ERR?":
            if state.error_queue:
                return state.error_queue.pop(0)
            else:
                return "0,No error"

        # Measurement value
        if cmd_upper.startswith("MEAS:VAL"):
            if "?" in cmd_upper:
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
        if cmd_upper.startswith("CONF:PREC"):
            if "?" in cmd_upper:
                return str(state.precision)
            else:
                try:
                    prec = int(cmd.split()[1])
                    if 0 <= prec <= 6:
                        state.precision = prec
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Precision must be 0-6")
                        return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid precision: {e}")
                    return None

        if cmd_upper.startswith("CONF:DIG"):
            if "?" in cmd_upper:
                return str(state.digits)
            else:
                try:
                    digits = int(cmd.split()[1])
                    if 4 <= digits <= 12:
                        state.digits = digits
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Digits must be 4-12")
                        return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid digit count: {e}")
                    return None

        if cmd_upper.startswith("CONF:UNIT"):
            if "?" in cmd_upper:
                return state.units
            else:
                try:
                    state.units = cmd.split(maxsplit=1)[1].strip('"')
                    asyncio.create_task(broadcast_state())
                    return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        if cmd_upper.startswith("CONF:SIZE"):
            if "?" in cmd_upper:
                return str(state.font_size)
            else:
                try:
                    size = int(cmd.split()[1])
                    if 20 <= size <= 120:
                        state.font_size = size
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Font size must be 20-120")
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
                    # Validate hex color format
                    if color.startswith('#') and len(color) in [4, 7]:
                        state.color = color
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Invalid color format (use #RGB or #RRGGBB)")
                        return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        if cmd_upper.startswith("CONF:STYLE"):
            if "?" in cmd_upper:
                return state.style
            else:
                try:
                    style = cmd.split()[1].strip('"').upper()
                    if style in ["7SEG", "PLAIN", "LED", "NIXIE"]:
                        state.style = style
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Style must be 7SEG, PLAIN, LED, or NIXIE")
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
        port=8000,
        log_level="info"
    )
    server = uvicorn.Server(config)

    print("Virtual Numeric Display ready:")
    print("  - SCPI:      tcp://0.0.0.0:5000")
    print("  - HTTP:      http://0.0.0.0:8000")
    print("  - WebSocket: ws://0.0.0.0:8000/ws")
    print("  - MQTT:      Use MQTT:CONF command to configure")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
