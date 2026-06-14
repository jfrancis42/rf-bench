#!/usr/bin/env python3
"""
Virtual Line Chart — SCPI TCP Server + WebSocket + MQTT bridge

Time-series scrolling line chart with configurable history length, auto-scaling,
and color-coded threshold zones.

Exposes:
- SCPI TCP server on port 5029 (IEEE 488.2 standard instrument port)
- HTTP server on port 8005 (serves static frontend)
- WebSocket server on port 8005/ws (real-time chart updates)
- MQTT subscriber (listens to configured topic for value updates)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-Line-Chart,1.0,2026"
  *RST                     → Reset to defaults
  SYST:ERR?                → Query error queue
  MEAS:VAL <float>         → Add data point to chart
  MEAS:VAL?                → Query most recent value
  CONF:HIST <int>          → Set history length in samples (default 100)
  CONF:HIST?               → Query history length
  CONF:MIN <float>         → Set Y-axis minimum (default: auto)
  CONF:MIN?                → Query Y-axis minimum
  CONF:MAX <float>         → Set Y-axis maximum (default: auto)
  CONF:MAX?                → Query Y-axis maximum
  CONF:AUTO <ON|OFF>       → Enable/disable auto-scaling (default ON)
  CONF:AUTO?               → Query auto-scaling state
  CONF:UNIT <string>       → Set display units (e.g., "dBm", "V", "°C")
  CONF:UNIT?               → Query display units
  CONF:COL <color>         → Set line color (hex, e.g., "#00ff00")
  CONF:COL?                → Query line color
  CONF:TITLE <string>      → Set chart title
  CONF:TITLE?              → Query chart title
  MQTT:CONF <host>,<topic> → Configure MQTT broker and topic to subscribe
  MQTT:CONF?               → Query MQTT configuration

Example usage:
  echo "CONF:HIST 200" | nc localhost 5029
  echo "CONF:TITLE Temperature Monitor" | nc localhost 5029
  echo "MEAS:VAL 25.3" | nc localhost 5029
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


class LineChartState:
    """Instrument state and configuration"""

    def __init__(self):
        self.history_length: int = 100
        self.data_points: deque = deque(maxlen=100)
        self.timestamps: deque = deque(maxlen=100)
        self.min_value: Optional[float] = None
        self.max_value: Optional[float] = None
        self.auto_scale: bool = True
        self.units: str = ""
        self.color: str = "#00ff00"
        self.title: str = "Time Series"
        self.error_queue: List[str] = []
        # MQTT configuration
        self.mqtt_host: Optional[str] = None
        self.mqtt_topic: Optional[str] = None

    def add_data_point(self, value: float):
        """Add a new data point with timestamp"""
        self.data_points.append(value)
        self.timestamps.append(time.time())

    def set_history_length(self, length: int):
        """Change history length and resize buffers"""
        self.history_length = length
        # Create new deques with updated maxlen
        new_data = deque(self.data_points, maxlen=length)
        new_times = deque(self.timestamps, maxlen=length)
        self.data_points = new_data
        self.timestamps = new_times

    def to_dict(self) -> dict:
        """Serialize state for WebSocket broadcast"""
        # Convert timestamps to relative seconds (most recent = 0)
        if self.timestamps:
            latest = self.timestamps[-1]
            relative_times = [t - latest for t in self.timestamps]
        else:
            relative_times = []

        return {
            'dataPoints': list(self.data_points),
            'timestamps': relative_times,
            'historyLength': self.history_length,
            'min': self.min_value,
            'max': self.max_value,
            'autoScale': self.auto_scale,
            'units': self.units,
            'color': self.color,
            'title': self.title
        }


# Global state
state = LineChartState()
websocket_clients: List[WebSocket] = []
mqtt_client: Optional[mqtt.Client] = None
event_loop: Optional[asyncio.AbstractEventLoop] = None

# FastAPI app
app = FastAPI(title="Virtual Line Chart")


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
            content="<html><body><h1>Virtual Line Chart</h1>"
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
        value = float(msg.payload.decode())
        state.add_data_point(value)
        print(f"MQTT received: {msg.topic} = {value}")
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

    def __init__(self, host: str = "0.0.0.0", port: int = 5004):
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
            return "N0GQ,Virtual-Line-Chart,1.0,2026"

        if cmd_upper == "*RST":
            global state
            state = LineChartState()
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
                if state.data_points:
                    return str(state.data_points[-1])
                else:
                    return "0.0"
            else:
                try:
                    val = float(cmd.split()[1])
                    state.add_data_point(val)
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Data out of range: {e}")
                    return None

        # Configuration commands
        if cmd_upper.startswith("CONF:HIST"):
            if "?" in cmd_upper:
                return str(state.history_length)
            else:
                try:
                    length = int(cmd.split()[1])
                    if 10 <= length <= 1000:
                        state.set_history_length(length)
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,History must be 10-1000")
                        return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid history: {e}")
                    return None

        if cmd_upper.startswith("CONF:MIN"):
            if "?" in cmd_upper:
                return str(state.min_value) if state.min_value is not None else "AUTO"
            else:
                try:
                    state.min_value = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid min: {e}")
                    return None

        if cmd_upper.startswith("CONF:MAX"):
            if "?" in cmd_upper:
                return str(state.max_value) if state.max_value is not None else "AUTO"
            else:
                try:
                    state.max_value = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid max: {e}")
                    return None

        if cmd_upper.startswith("CONF:AUTO"):
            if "?" in cmd_upper:
                return "ON" if state.auto_scale else "OFF"
            else:
                try:
                    auto = cmd.split()[1].strip('"').upper()
                    if auto in ["ON", "OFF"]:
                        state.auto_scale = (auto == "ON")
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Auto must be ON or OFF")
                        return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
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
        port=8004,
        log_level="info"
    )
    server = uvicorn.Server(config)

    print("Virtual Line Chart ready:")
    print("  - SCPI:      tcp://0.0.0.0:5004")
    print("  - HTTP:      http://0.0.0.0:8004")
    print("  - WebSocket: ws://0.0.0.0:8004/ws")
    print("  - MQTT:      Use MQTT:CONF command to configure")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
