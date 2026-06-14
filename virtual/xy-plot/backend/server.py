#!/usr/bin/env python3
"""
Virtual XY Plot — SCPI TCP Server + WebSocket + MQTT bridge

Scatter plot or line plot with configurable axes, point styling, and grid.

Exposes:
- SCPI TCP server on port 5030 (IEEE 488.2 standard instrument port)
- HTTP server on port 8006 (serves static frontend)
- WebSocket server on port 8006/ws (real-time plot updates)
- MQTT subscriber (listens to configured topic for XY pairs)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-XY-Plot,1.0,2026"
  *RST                     → Reset to defaults, clear data
  SYST:ERR?                → Query error queue
  MEAS:XY <x>,<y>          → Add XY data point
  MEAS:XY?                 → Query number of points
  MEAS:CLEAR               → Clear all data points
  CONF:XMIN <float>        → Set X-axis minimum (default: auto)
  CONF:XMIN?               → Query X-axis minimum
  CONF:XMAX <float>        → Set X-axis maximum (default: auto)
  CONF:XMAX?               → Query X-axis maximum
  CONF:YMIN <float>        → Set Y-axis minimum (default: auto)
  CONF:YMIN?               → Query Y-axis minimum
  CONF:YMAX <float>        → Set Y-axis maximum (default: auto)
  CONF:YMAX?               → Query Y-axis maximum
  CONF:XLABEL <string>     → Set X-axis label
  CONF:XLABEL?             → Query X-axis label
  CONF:YLABEL <string>     → Set Y-axis label
  CONF:YLABEL?             → Query Y-axis label
  CONF:TITLE <string>      → Set plot title
  CONF:TITLE?              → Query plot title
  CONF:STYLE <SCATTER|LINE> → Set plot style (default SCATTER)
  CONF:STYLE?              → Query plot style
  CONF:COL <color>         → Set point/line color (hex, e.g., "#00ff00")
  CONF:COL?                → Query color
  MQTT:CONF <host>,<topic> → Configure MQTT broker and topic (expects "x,y" messages)
  MQTT:CONF?               → Query MQTT configuration

Example usage:
  echo "CONF:TITLE Smith Chart" | nc localhost 5030
  echo "CONF:XLABEL Resistance" | nc localhost 5030
  echo "CONF:YLABEL Reactance" | nc localhost 5030
  echo "MEAS:XY 50,0" | nc localhost 5030
  echo "MEAS:XY 75,25" | nc localhost 5030
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

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


class XYPlotState:
    """Instrument state and configuration"""

    def __init__(self):
        self.data_points: List[Tuple[float, float]] = []
        self.x_min: Optional[float] = None
        self.x_max: Optional[float] = None
        self.y_min: Optional[float] = None
        self.y_max: Optional[float] = None
        self.x_label: str = "X"
        self.y_label: str = "Y"
        self.title: str = "XY Plot"
        self.style: str = "SCATTER"  # SCATTER or LINE
        self.color: str = "#00ff00"
        self.error_queue: List[str] = []
        # MQTT configuration
        self.mqtt_host: Optional[str] = None
        self.mqtt_topic: Optional[str] = None

    def add_point(self, x: float, y: float):
        """Add an XY data point"""
        self.data_points.append((x, y))

    def clear_points(self):
        """Clear all data points"""
        self.data_points = []

    def to_dict(self) -> dict:
        """Serialize state for WebSocket broadcast"""
        return {
            'dataPoints': self.data_points,
            'xMin': self.x_min,
            'xMax': self.x_max,
            'yMin': self.y_min,
            'yMax': self.y_max,
            'xLabel': self.x_label,
            'yLabel': self.y_label,
            'title': self.title,
            'style': self.style,
            'color': self.color
        }


# Global state
state = XYPlotState()
websocket_clients: List[WebSocket] = []
mqtt_client: Optional[mqtt.Client] = None
event_loop: Optional[asyncio.AbstractEventLoop] = None

# FastAPI app
app = FastAPI(title="Virtual XY Plot")


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
            content="<html><body><h1>Virtual XY Plot</h1>"
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
    """Callback when MQTT message received (expects "x,y" format)"""
    try:
        payload = msg.payload.decode().strip()
        x_str, y_str = payload.split(',')
        x = float(x_str)
        y = float(y_str)
        state.add_point(x, y)
        print(f"MQTT received: {msg.topic} = ({x}, {y})")
        if event_loop:
            asyncio.run_coroutine_threadsafe(broadcast_state(), event_loop)
    except (ValueError, IndexError) as e:
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

    def __init__(self, host: str = "0.0.0.0", port: int = 5005):
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
            return "N0GQ,Virtual-XY-Plot,1.0,2026"

        if cmd_upper == "*RST":
            global state
            state = XYPlotState()
            asyncio.create_task(broadcast_state())
            return None

        if cmd_upper == "SYST:ERR?":
            if state.error_queue:
                return state.error_queue.pop(0)
            else:
                return "0,No error"

        # Measurement commands
        if cmd_upper.startswith("MEAS:XY"):
            if "?" in cmd_upper:
                return str(len(state.data_points))
            else:
                try:
                    params = cmd_original.split(maxsplit=1)[1].split(',')
                    x = float(params[0].strip())
                    y = float(params[1].strip())
                    state.add_point(x, y)
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid XY: {e}")
                    return None

        if cmd_upper == "MEAS:CLEAR":
            state.clear_points()
            asyncio.create_task(broadcast_state())
            return None

        # Configuration commands
        if cmd_upper.startswith("CONF:XMIN"):
            if "?" in cmd_upper:
                return str(state.x_min) if state.x_min is not None else "AUTO"
            else:
                try:
                    state.x_min = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid xmin: {e}")
                    return None

        if cmd_upper.startswith("CONF:XMAX"):
            if "?" in cmd_upper:
                return str(state.x_max) if state.x_max is not None else "AUTO"
            else:
                try:
                    state.x_max = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid xmax: {e}")
                    return None

        if cmd_upper.startswith("CONF:YMIN"):
            if "?" in cmd_upper:
                return str(state.y_min) if state.y_min is not None else "AUTO"
            else:
                try:
                    state.y_min = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid ymin: {e}")
                    return None

        if cmd_upper.startswith("CONF:YMAX"):
            if "?" in cmd_upper:
                return str(state.y_max) if state.y_max is not None else "AUTO"
            else:
                try:
                    state.y_max = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid ymax: {e}")
                    return None

        if cmd_upper.startswith("CONF:XLABEL"):
            if "?" in cmd_upper:
                return state.x_label
            else:
                try:
                    state.x_label = cmd.split(maxsplit=1)[1].strip('"')
                    asyncio.create_task(broadcast_state())
                    return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        if cmd_upper.startswith("CONF:YLABEL"):
            if "?" in cmd_upper:
                return state.y_label
            else:
                try:
                    state.y_label = cmd.split(maxsplit=1)[1].strip('"')
                    asyncio.create_task(broadcast_state())
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

        if cmd_upper.startswith("CONF:STYLE"):
            if "?" in cmd_upper:
                return state.style
            else:
                try:
                    style = cmd.split()[1].strip('"').upper()
                    if style in ["SCATTER", "LINE"]:
                        state.style = style
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Style must be SCATTER or LINE")
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
        port=8005,
        log_level="info"
    )
    server = uvicorn.Server(config)

    print("Virtual XY Plot ready:")
    print("  - SCPI:      tcp://0.0.0.0:5005")
    print("  - HTTP:      http://0.0.0.0:8005")
    print("  - WebSocket: ws://0.0.0.0:8005/ws")
    print("  - MQTT:      Use MQTT:CONF command to configure")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
