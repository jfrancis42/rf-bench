#!/usr/bin/env python3
"""
Virtual LED Indicator — SCPI TCP Server + WebSocket bridge

Exposes:
- SCPI TCP server on port 5025 (IEEE 488.2 standard instrument port)
- HTTP server on port 8000 (serves static frontend)
- WebSocket server on port 8001 (real-time LED state updates)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-LED,1.0,2026"
  *RST                     → Reset to defaults
  SYST:ERR?                → Query error queue
  STAT:VAL <bool>          → Set LED state (0/1, OFF/ON, FALSE/TRUE)
  STAT:VAL?                → Query LED state
  CONF:ONCOL <color>       → Set ON color (hex, e.g., "#00ff00")
  CONF:ONCOL?              → Query ON color
  CONF:OFFCOL <color>      → Set OFF color (hex, e.g., "#333333")
  CONF:OFFCOL?             → Query OFF color
  CONF:BLINK <ms>          → Set blink rate (0 = no blink, >0 = blink period in ms)
  CONF:BLINK?              → Query blink rate
  CONF:SIZE <int>          → Set LED diameter (20-200 pixels, default 80)
  CONF:SIZE?               → Query LED diameter
  CONF:LABEL <string>      → Set text label below LED
  CONF:LABEL?              → Query text label

Example usage:
  echo "*IDN?" | nc localhost 5025
  echo "STAT:VAL 1" | nc localhost 5025
  echo "CONF:ONCOL #ff0000" | nc localhost 5025
  echo "CONF:LABEL PTT" | nc localhost 5025
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


class LEDState:
    """Instrument state and configuration"""

    def __init__(self):
        self.state: bool = False          # LED on/off
        self.on_color: str = "#00ff00"    # Green when ON
        self.off_color: str = "#333333"   # Dark gray when OFF
        self.blink_ms: int = 0            # 0 = no blink, >0 = blink period
        self.size: int = 80               # LED diameter in pixels
        self.label: str = ""              # Text label below LED
        self.error_queue: List[str] = []

    def to_dict(self) -> dict:
        """Serialize state for WebSocket broadcast"""
        return {
            'state': self.state,
            'onColor': self.on_color,
            'offColor': self.off_color,
            'blinkMs': self.blink_ms,
            'size': self.size,
            'label': self.label
        }


# Global state
state = LEDState()
websocket_clients: List[WebSocket] = []

# FastAPI app
app = FastAPI(title="Virtual LED Indicator")


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
            content="<html><body><h1>Virtual LED Indicator</h1>"
                    "<p>Frontend not found. See README.md</p></body></html>"
        )


# Mount static files if frontend build exists
frontend_build = Path(__file__).parent.parent / "frontend" / "build"
if frontend_build.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_build)), name="static")


# ==============================================================================
# SCPI TCP Server
# ==============================================================================

class SCPIServer:
    """IEEE 488.2 SCPI command parser and TCP server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 5025):
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
        cmd_upper = cmd.upper().strip()

        # IEEE 488.2 common commands
        if cmd_upper == "*IDN?":
            return "N0GQ,Virtual-LED,1.0,2026"

        if cmd_upper == "*RST":
            global state
            state = LEDState()
            asyncio.create_task(broadcast_state())
            return None

        if cmd_upper == "SYST:ERR?":
            if state.error_queue:
                return state.error_queue.pop(0)
            else:
                return "0,No error"

        # Status (LED state)
        if cmd_upper.startswith("STAT:VAL"):
            if "?" in cmd_upper:
                return "1" if state.state else "0"
            else:
                try:
                    val_str = cmd.split()[1].upper()
                    if val_str in ["1", "ON", "TRUE"]:
                        state.state = True
                    elif val_str in ["0", "OFF", "FALSE"]:
                        state.state = False
                    else:
                        state.error_queue.append(f"-222,Invalid state: {val_str}")
                        return None
                    asyncio.create_task(broadcast_state())
                    return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        # Configuration commands
        if cmd_upper.startswith("CONF:ONCOL"):
            if "?" in cmd_upper:
                return state.on_color
            else:
                try:
                    color = cmd.split(maxsplit=1)[1].strip('"')
                    # Validate hex color format
                    if color.startswith('#') and len(color) in [4, 7]:
                        state.on_color = color
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Invalid color format (use #RGB or #RRGGBB)")
                        return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        if cmd_upper.startswith("CONF:OFFCOL"):
            if "?" in cmd_upper:
                return state.off_color
            else:
                try:
                    color = cmd.split(maxsplit=1)[1].strip('"')
                    # Validate hex color format
                    if color.startswith('#') and len(color) in [4, 7]:
                        state.off_color = color
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Invalid color format (use #RGB or #RRGGBB)")
                        return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
                    return None

        if cmd_upper.startswith("CONF:BLINK"):
            if "?" in cmd_upper:
                return str(state.blink_ms)
            else:
                try:
                    blink = int(cmd.split()[1])
                    if blink >= 0:
                        state.blink_ms = blink
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Blink rate must be >= 0")
                        return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid blink rate: {e}")
                    return None

        if cmd_upper.startswith("CONF:SIZE"):
            if "?" in cmd_upper:
                return str(state.size)
            else:
                try:
                    size = int(cmd.split()[1])
                    if 20 <= size <= 200:
                        state.size = size
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Size must be 20-200")
                        return None
                except (IndexError, ValueError) as e:
                    state.error_queue.append(f"-222,Invalid size: {e}")
                    return None

        if cmd_upper.startswith("CONF:LABEL"):
            if "?" in cmd_upper:
                return state.label
            else:
                try:
                    state.label = cmd.split(maxsplit=1)[1].strip('"')
                    asyncio.create_task(broadcast_state())
                    return None
                except IndexError:
                    # Empty label is valid
                    state.label = ""
                    asyncio.create_task(broadcast_state())
                    return None

        # Unknown command
        state.error_queue.append(f"-113,Undefined header: {cmd}")
        return None


# ==============================================================================
# Main
# ==============================================================================

async def main():
    """Start both SCPI TCP server and FastAPI HTTP/WebSocket server"""
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

    print("Virtual LED Indicator ready:")
    print("  - SCPI:      tcp://0.0.0.0:5025")
    print("  - HTTP:      http://0.0.0.0:8000")
    print("  - WebSocket: ws://0.0.0.0:8000/ws")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
