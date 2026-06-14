#!/usr/bin/env python3
"""
Virtual Gauge Cluster — SCPI TCP Server + WebSocket + MQTT bridge

Multi-meter composite display showing multiple analog gauges in a dashboard layout.
Each gauge can display different values with independent configuration.

Exposes:
- SCPI TCP server on port 5034 (IEEE 488.2 standard instrument port)
- HTTP server on port 8010 (serves static frontend)
- WebSocket server on port 8010/ws (real-time gauge updates)
- MQTT subscriber (listens to configured topics for gauge values)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-Gauge-Cluster,1.0,2026"
  *RST                     → Reset all gauges to defaults
  SYST:ERR?                → Query error queue
  MEAS<n>:VAL <float>      → Set value for gauge N (1-4)
  MEAS<n>:VAL?             → Query gauge N value
  CONF<n>:MIN <float>      → Set gauge N minimum
  CONF<n>:MAX <float>      → Set gauge N maximum
  CONF<n>:UNIT <string>    → Set gauge N units
  CONF<n>:LABEL <string>   → Set gauge N label
  CONF<n>:COL <color>      → Set gauge N needle color
  CONF:LAYOUT <2|4>        → Set layout (2 or 4 gauges, default 4)
  CONF:LAYOUT?             → Query layout
  MQTT:CONF <n>,<host>,<topic> → Configure MQTT for gauge N
  MQTT:CONF?               → Query MQTT configuration

Example usage:
  # Configure gauge 1 (voltage)
  echo "CONF1:MIN 0" | nc localhost 5034
  echo "CONF1:MAX 15" | nc localhost 5034
  echo "CONF1:UNIT V" | nc localhost 5034
  echo "CONF1:LABEL Voltage" | nc localhost 5034
  echo "MEAS1:VAL 13.8" | nc localhost 5034
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

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


class Gauge:
    """Single gauge configuration and state"""

    def __init__(self, index: int):
        self.index = index
        self.value: float = 0.0
        self.min_value: float = 0.0
        self.max_value: float = 100.0
        self.units: str = ""
        self.label: str = f"Gauge {index}"
        self.color: str = "#00ff00"
        self.mqtt_topic: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize gauge state"""
        return {
            'value': self.value,
            'min': self.min_value,
            'max': self.max_value,
            'units': self.units,
            'label': self.label,
            'color': self.color
        }


class GaugeClusterState:
    """Instrument state and configuration"""

    def __init__(self):
        self.gauges: Dict[int, Gauge] = {
            1: Gauge(1),
            2: Gauge(2),
            3: Gauge(3),
            4: Gauge(4)
        }
        self.layout: int = 4  # 2 or 4 gauges
        self.error_queue: List[str] = []
        # MQTT configuration
        self.mqtt_host: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize state for WebSocket broadcast"""
        return {
            'gauges': {idx: gauge.to_dict() for idx, gauge in self.gauges.items()},
            'layout': self.layout
        }


# Global state
state = GaugeClusterState()
websocket_clients: List[WebSocket] = []
mqtt_clients: Dict[int, mqtt.Client] = {}  # One client per gauge
event_loop: Optional[asyncio.AbstractEventLoop] = None

# FastAPI app
app = FastAPI(title="Virtual Gauge Cluster")


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
            content="<html><body><h1>Virtual Gauge Cluster</h1>"
                    "<p>Frontend not found. See README.md</p></body></html>"
        )


# ==============================================================================
# MQTT Client
# ==============================================================================

def create_mqtt_callback(gauge_index: int):
    """Create MQTT message callback for specific gauge"""
    def on_message(client, userdata, msg):
        try:
            value = float(msg.payload.decode())
            state.gauges[gauge_index].value = value
            print(f"MQTT received for gauge {gauge_index}: {msg.topic} = {value}")
            if event_loop:
                asyncio.run_coroutine_threadsafe(broadcast_state(), event_loop)
        except ValueError as e:
            print(f"MQTT parse error on {msg.topic}: {e}")
    return on_message


def start_mqtt_client(gauge_index: int, host: str, topic: str):
    """Start MQTT client for specific gauge"""
    global mqtt_clients

    # Stop existing client if any
    if gauge_index in mqtt_clients:
        try:
            mqtt_clients[gauge_index].disconnect()
            mqtt_clients[gauge_index].loop_stop()
        except:
            pass

    # Create new client
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"MQTT gauge {gauge_index} connected with result code {reason_code}")
        client.subscribe(topic)
        print(f"MQTT gauge {gauge_index} subscribed to topic: {topic}")

    client.on_connect = on_connect
    client.on_message = create_mqtt_callback(gauge_index)

    try:
        client.connect(host, 1883, 60)
        client.loop_start()
        mqtt_clients[gauge_index] = client
        print(f"MQTT client started for gauge {gauge_index} at {host}:1883")
    except Exception as e:
        print(f"MQTT connection failed for gauge {gauge_index}: {e}")
        state.error_queue.append(f"-221,MQTT connection failed: {e}")


# ==============================================================================
# SCPI TCP Server
# ==============================================================================

class SCPIServer:
    """IEEE 488.2 SCPI command parser and TCP server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 5009):
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
            return "N0GQ,Virtual-Gauge-Cluster,1.0,2026"

        if cmd_upper == "*RST":
            global state
            state = GaugeClusterState()
            asyncio.create_task(broadcast_state())
            return None

        if cmd_upper == "SYST:ERR?":
            if state.error_queue:
                return state.error_queue.pop(0)
            else:
                return "0,No error"

        # Extract gauge number from command (MEAS1, CONF2, etc.)
        import re
        gauge_match = re.match(r'(MEAS|CONF)(\d+):(.+)', cmd_upper)

        if gauge_match:
            cmd_type = gauge_match.group(1)
            gauge_num = int(gauge_match.group(2))
            subcmd = gauge_match.group(3)

            if gauge_num not in state.gauges:
                state.error_queue.append(f"-222,Invalid gauge number: {gauge_num}")
                return None

            gauge = state.gauges[gauge_num]

            # Measurement commands
            if cmd_type == "MEAS" and subcmd.startswith("VAL"):
                if "?" in subcmd:
                    return str(gauge.value)
                else:
                    try:
                        val = float(cmd_original.split()[1])
                        gauge.value = val
                        asyncio.create_task(broadcast_state())
                        return None
                    except (IndexError, ValueError) as e:
                        state.error_queue.append(f"-222,Invalid value: {e}")
                        return None

            # Configuration commands
            if cmd_type == "CONF":
                if subcmd.startswith("MIN"):
                    if "?" in subcmd:
                        return str(gauge.min_value)
                    else:
                        try:
                            gauge.min_value = float(cmd_original.split()[1])
                            asyncio.create_task(broadcast_state())
                            return None
                        except (IndexError, ValueError) as e:
                            state.error_queue.append(f"-222,Invalid min: {e}")
                            return None

                elif subcmd.startswith("MAX"):
                    if "?" in subcmd:
                        return str(gauge.max_value)
                    else:
                        try:
                            gauge.max_value = float(cmd_original.split()[1])
                            asyncio.create_task(broadcast_state())
                            return None
                        except (IndexError, ValueError) as e:
                            state.error_queue.append(f"-222,Invalid max: {e}")
                            return None

                elif subcmd.startswith("UNIT"):
                    if "?" in subcmd:
                        return gauge.units
                    else:
                        try:
                            gauge.units = cmd_original.split(maxsplit=1)[1].strip('"')
                            asyncio.create_task(broadcast_state())
                            return None
                        except IndexError:
                            state.error_queue.append("-222,Missing parameter")
                            return None

                elif subcmd.startswith("LABEL"):
                    if "?" in subcmd:
                        return gauge.label
                    else:
                        try:
                            gauge.label = cmd_original.split(maxsplit=1)[1].strip('"')
                            asyncio.create_task(broadcast_state())
                            return None
                        except IndexError:
                            state.error_queue.append("-222,Missing parameter")
                            return None

                elif subcmd.startswith("COL"):
                    if "?" in subcmd:
                        return gauge.color
                    else:
                        try:
                            color = cmd_original.split(maxsplit=1)[1].strip('"')
                            if color.startswith('#') and len(color) in [4, 7]:
                                gauge.color = color
                                asyncio.create_task(broadcast_state())
                                return None
                            else:
                                state.error_queue.append("-222,Invalid color format")
                                return None
                        except IndexError:
                            state.error_queue.append("-222,Missing parameter")
                            return None

        # Layout configuration
        if cmd_upper.startswith("CONF:LAYOUT"):
            if "?" in cmd_upper:
                return str(state.layout)
            else:
                try:
                    layout = int(cmd.split()[1])
                    if layout in [2, 4]:
                        state.layout = layout
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Layout must be 2 or 4")
                        return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid layout: {e}")
                    return None

        # MQTT configuration
        if cmd_upper.startswith("MQTT:CONF"):
            if "?" in cmd_upper:
                configs = []
                for idx, gauge in state.gauges.items():
                    if gauge.mqtt_topic:
                        configs.append(f"{idx}:{state.mqtt_host},{gauge.mqtt_topic}")
                return "; ".join(configs) if configs else "Not configured"
            else:
                try:
                    params = cmd_original.split(maxsplit=1)[1].split(',')
                    gauge_num = int(params[0].strip())
                    mqtt_host = params[1].strip()
                    mqtt_topic = params[2].strip()

                    if gauge_num not in state.gauges:
                        state.error_queue.append(f"-222,Invalid gauge number: {gauge_num}")
                        return None

                    state.mqtt_host = mqtt_host
                    state.gauges[gauge_num].mqtt_topic = mqtt_topic
                    start_mqtt_client(gauge_num, mqtt_host, mqtt_topic)
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
        port=8009,
        log_level="info"
    )
    server = uvicorn.Server(config)

    print("Virtual Gauge Cluster ready:")
    print("  - SCPI:      tcp://0.0.0.0:5009")
    print("  - HTTP:      http://0.0.0.0:8009")
    print("  - WebSocket: ws://0.0.0.0:8009/ws")
    print("  - MQTT:      Use MQTT:CONF command to configure")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
