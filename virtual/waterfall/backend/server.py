#!/usr/bin/env python3
"""
Virtual Waterfall Display — SCPI TCP Server + WebSocket + MQTT bridge

Spectrum/time waterfall display for frequency-domain data visualization.
Accepts spectrum traces (array of power values across frequency bins) and
displays them as a scrolling waterfall with color-coded intensity.

Exposes:
- SCPI TCP server on port 5032 (IEEE 488.2 standard instrument port)
- HTTP server on port 8008 (serves static frontend)
- WebSocket server on port 8008/ws (real-time waterfall updates)
- MQTT subscriber (listens to configured topic for spectrum arrays)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-Waterfall,1.0,2026"
  *RST                     → Reset to defaults, clear waterfall
  SYST:ERR?                → Query error queue
  MEAS:SPEC <csv>          → Add spectrum trace (comma-separated power values)
  MEAS:SPEC?               → Query number of traces in history
  MEAS:CLEAR               → Clear waterfall history
  CONF:HIST <int>          → Set history depth (10-500, default 100)
  CONF:HIST?               → Query history depth
  CONF:FSTART <float>      → Set start frequency in MHz (default 0)
  CONF:FSTART?             → Query start frequency
  CONF:FSTOP <float>       → Set stop frequency in MHz (default 100)
  CONF:FSTOP?              → Query stop frequency
  CONF:PMIN <float>        → Set power minimum in dBm (default -100)
  CONF:PMIN?               → Query power minimum
  CONF:PMAX <float>        → Set power maximum in dBm (default -20)
  CONF:PMAX?               → Query power maximum
  CONF:TITLE <string>      → Set display title
  CONF:TITLE?              → Query title
  MQTT:CONF <host>,<topic> → Configure MQTT broker and topic (expects CSV arrays)
  MQTT:CONF?               → Query MQTT configuration

Example usage:
  # Send a 10-point spectrum
  echo "MEAS:SPEC -80,-75,-70,-65,-60,-65,-70,-75,-80,-85" | nc localhost 5032
"""

import asyncio
import json
import sys
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


class WaterfallState:
    """Instrument state and configuration"""

    def __init__(self):
        self.history_depth: int = 100
        self.traces: deque = deque(maxlen=100)  # List of spectrum arrays
        self.freq_start: float = 0.0  # MHz
        self.freq_stop: float = 100.0  # MHz
        self.power_min: float = -100.0  # dBm
        self.power_max: float = -20.0  # dBm
        self.title: str = "Waterfall"
        self.error_queue: List[str] = []
        # MQTT configuration
        self.mqtt_host: Optional[str] = None
        self.mqtt_topic: Optional[str] = None

    def add_trace(self, spectrum: List[float]):
        """Add a spectrum trace"""
        self.traces.append(spectrum)

    def set_history_depth(self, depth: int):
        """Change history depth"""
        self.history_depth = depth
        new_traces = deque(self.traces, maxlen=depth)
        self.traces = new_traces

    def clear_traces(self):
        """Clear all traces"""
        self.traces.clear()

    def to_dict(self) -> dict:
        """Serialize state for WebSocket broadcast"""
        return {
            'traces': [list(trace) for trace in self.traces],
            'historyDepth': self.history_depth,
            'freqStart': self.freq_start,
            'freqStop': self.freq_stop,
            'powerMin': self.power_min,
            'powerMax': self.power_max,
            'title': self.title
        }


# Global state
state = WaterfallState()
websocket_clients: List[WebSocket] = []
mqtt_client: Optional[mqtt.Client] = None
event_loop: Optional[asyncio.AbstractEventLoop] = None

# FastAPI app
app = FastAPI(title="Virtual Waterfall")


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
            content="<html><body><h1>Virtual Waterfall</h1>"
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
    """Callback when MQTT message received (expects CSV floats)"""
    try:
        payload = msg.payload.decode().strip()
        spectrum = [float(x.strip()) for x in payload.split(',')]
        state.add_trace(spectrum)
        print(f"MQTT received: {msg.topic} = spectrum ({len(spectrum)} points)")
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

    def __init__(self, host: str = "0.0.0.0", port: int = 5007):
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
            return "N0GQ,Virtual-Waterfall,1.0,2026"

        if cmd_upper == "*RST":
            global state
            state = WaterfallState()
            asyncio.create_task(broadcast_state())
            return None

        if cmd_upper == "SYST:ERR?":
            if state.error_queue:
                return state.error_queue.pop(0)
            else:
                return "0,No error"

        # Measurement commands
        if cmd_upper.startswith("MEAS:SPEC"):
            if "?" in cmd_upper:
                return str(len(state.traces))
            else:
                try:
                    csv_data = cmd_original.split(maxsplit=1)[1]
                    spectrum = [float(x.strip()) for x in csv_data.split(',')]
                    state.add_trace(spectrum)
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid spectrum: {e}")
                    return None

        if cmd_upper == "MEAS:CLEAR":
            state.clear_traces()
            asyncio.create_task(broadcast_state())
            return None

        # Configuration commands
        if cmd_upper.startswith("CONF:HIST"):
            if "?" in cmd_upper:
                return str(state.history_depth)
            else:
                try:
                    depth = int(cmd.split()[1])
                    if 10 <= depth <= 500:
                        state.set_history_depth(depth)
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,History must be 10-500")
                        return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid history: {e}")
                    return None

        if cmd_upper.startswith("CONF:FSTART"):
            if "?" in cmd_upper:
                return str(state.freq_start)
            else:
                try:
                    state.freq_start = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid freq: {e}")
                    return None

        if cmd_upper.startswith("CONF:FSTOP"):
            if "?" in cmd_upper:
                return str(state.freq_stop)
            else:
                try:
                    state.freq_stop = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid freq: {e}")
                    return None

        if cmd_upper.startswith("CONF:PMIN"):
            if "?" in cmd_upper:
                return str(state.power_min)
            else:
                try:
                    state.power_min = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid power: {e}")
                    return None

        if cmd_upper.startswith("CONF:PMAX"):
            if "?" in cmd_upper:
                return str(state.power_max)
            else:
                try:
                    state.power_max = float(cmd.split()[1])
                    asyncio.create_task(broadcast_state())
                    return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid power: {e}")
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

async def main(scpi_port: int = 5007, http_port: int = 8007):
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

    print("Virtual Waterfall ready:")
    print(f"  - SCPI:      tcp://0.0.0.0:{scpi_port}")
    print(f"  - HTTP:      http://0.0.0.0:{http_port}")
    print(f"  - WebSocket: ws://0.0.0.0:{http_port}/ws")
    print("  - MQTT:      Use MQTT:CONF command to configure")

    await server.serve()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Virtual Waterfall SCPI Server")
    parser.add_argument('--scpi-port', type=int, default=5007, help="SCPI TCP port (default: 5007)")
    parser.add_argument('--http-port', type=int, default=8007, help="HTTP/WebSocket port (default: 8007)")
    args = parser.parse_args()

    try:
        asyncio.run(main(scpi_port=args.scpi_port, http_port=args.http_port))
    except KeyboardInterrupt:
        print("\nShutdown.")
