#!/usr/bin/env python3
"""
Virtual Numeric Display — SCPI TCP Server + WebSocket bridge

Exposes:
- SCPI TCP server on port 5025 (IEEE 488.2 standard instrument port)
- HTTP server on port 8000 (serves static frontend)
- WebSocket server on port 8001 (real-time display value updates)

SCPI Commands:
  *IDN?                    → "N0GQ,Virtual-Numeric-Display,1.0,2026"
  *RST                     → Reset to defaults
  SYST:ERR?                → Query error queue
  MEAS:VAL <float>         → Set displayed value
  MEAS:VAL?                → Query current value
  CONF:PREC <int>          → Set decimal precision (0-6, default 2)
  CONF:PREC?               → Query decimal precision
  CONF:UNIT <string>       → Set display units (e.g., "MHz", "V", "A", "°C")
  CONF:UNIT?               → Query display units
  CONF:SIZE <int>          → Set font size (20-120, default 80)
  CONF:SIZE?               → Query font size
  CONF:COL <color>         → Set text color (hex, e.g., "#00ff00")
  CONF:COL?                → Query text color
  CONF:STYLE <string>      → Set display style: "7SEG" or "PLAIN" (default 7SEG)
  CONF:STYLE?              → Query display style

Example usage:
  echo "*IDN?" | nc localhost 5025
  echo "MEAS:VAL 14.257" | nc localhost 5025
  echo "CONF:UNIT MHz" | nc localhost 5025
  echo "CONF:PREC 3" | nc localhost 5025
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


class NumericDisplayState:
    """Instrument state and configuration"""

    def __init__(self):
        self.value: float = 0.0
        self.precision: int = 2           # Decimal places (0-6)
        self.units: str = ""
        self.font_size: int = 80          # Pixels (20-120)
        self.color: str = "#00ff00"       # Hex color
        self.style: str = "7SEG"          # "7SEG" or "PLAIN"
        self.error_queue: List[str] = []

    def to_dict(self) -> dict:
        """Serialize state for WebSocket broadcast"""
        return {
            'value': self.value,
            'precision': self.precision,
            'units': self.units,
            'fontSize': self.font_size,
            'color': self.color,
            'style': self.style
        }


# Global state
state = NumericDisplayState()
websocket_clients: List[WebSocket] = []

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
                    if style in ["7SEG", "PLAIN"]:
                        state.style = style
                        asyncio.create_task(broadcast_state())
                        return None
                    else:
                        state.error_queue.append("-222,Style must be 7SEG or PLAIN")
                        return None
                except IndexError:
                    state.error_queue.append("-222,Missing parameter")
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

    print("Virtual Numeric Display ready:")
    print("  - SCPI:      tcp://0.0.0.0:5025")
    print("  - HTTP:      http://0.0.0.0:8000")
    print("  - WebSocket: ws://0.0.0.0:8000/ws")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
