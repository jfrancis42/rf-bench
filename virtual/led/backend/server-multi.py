#!/usr/bin/env python3
"""
Virtual LED Indicator — Multi-instance SCPI Server

Supports 1-4 LEDs with 1-based SCPI addressing.

SCPI Commands (1-based indexing):
  STAT<n>:VAL <0|1|ON|OFF>     → Set LED N state (N=1-4)
  STAT<n>:VAL?                 → Query LED N state
  CONF<n>:LAB <string>         → Set label
  CONF<n>:ONCOL <color>        → Set on color (hex)
  CONF<n>:OFFCOL <color>       → Set off color (hex)

  INST:COUNT <int>             → Set number of LEDs (1-4, default 1)
  INST:COUNT?                  → Query LED count
  INST:LAY <string>            → Set layout: ROW, COL, 2X2 (default ROW)
  INST:LAY?                    → Query layout

Example:
  INST:COUNT 2
  INST:LAY ROW
  STAT1:VAL 1
  CONF1:LAB PTT
  CONF1:ONCOL #ff0000
  STAT2:VAL 0
  CONF2:LAB LOCK
"""

import asyncio
import json
import sys
from pathlib import Path

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse
    import uvicorn
except ImportError:
    print("ERROR: FastAPI/uvicorn required. Install: pip install fastapi uvicorn", file=sys.stderr)
    sys.exit(1)


# ==============================================================================
# State
# ==============================================================================

class LEDState:
    """State for one LED"""
    def __init__(self, index: int):
        self.index = index
        self.state = False
        self.label = ""
        self.on_color = "#00ff00"
        self.off_color = "#404040"

    def to_dict(self):
        return {
            'index': self.index,
            'state': self.state,
            'label': self.label,
            'on_color': self.on_color,
            'off_color': self.off_color
        }


class InstrumentState:
    """Global instrument state"""
    def __init__(self):
        self.count = 1
        self.layout = "ROW"
        self.leds = {1: LEDState(1)}
        self.error_queue = []

    def set_count(self, count: int):
        """Set number of LEDs (1-4)"""
        count = max(1, min(4, count))
        self.count = count
        for i in range(1, count + 1):
            if i not in self.leds:
                self.leds[i] = LEDState(i)


state = InstrumentState()
connected_clients = []
event_loop = None


# ==============================================================================
# WebSocket broadcast
# ==============================================================================

async def broadcast_state(index: int):
    """Broadcast LED state to all connected WebSocket clients"""
    if index not in state.leds:
        return

    message = json.dumps(state.leds[index].to_dict())
    for client in connected_clients[:]:
        try:
            await client.send_text(message)
        except:
            connected_clients.remove(client)


# ==============================================================================
# SCPI Server
# ==============================================================================

class SCPIServer:
    """SCPI TCP server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 5003):
        self.host = host
        self.port = port
        self.server = None

    async def start(self):
        """Start SCPI server"""
        self.server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )
        print(f"SCPI TCP server listening on {self.host}:{self.port}")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle SCPI client connection"""
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

                response = await self.process_command(command)
                if response:
                    writer.write(f"{response}\n".encode())
                    await writer.drain()

        except Exception as e:
            print(f"SCPI client error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            print(f"SCPI client disconnected: {addr}")

    async def process_command(self, cmd: str) -> str:
        """Process SCPI command"""
        cmd_original = cmd
        cmd_upper = cmd.strip().upper()

        # IEEE 488.2 common commands
        if cmd_upper == "*IDN?":
            return f"N0GQ,Virtual-LED-Multi,1.0,2026"
        elif cmd_upper == "*RST":
            state.__init__()
            for i in range(1, state.count + 1):
                await broadcast_state(i)
            return None
        elif cmd_upper == "SYST:ERR?":
            if state.error_queue:
                return state.error_queue.pop(0)
            return "0,No error"

        # Instrument configuration commands
        if cmd_upper.startswith("INST:COUNT"):
            if "?" in cmd_upper:
                return str(state.count)
            else:
                try:
                    count = int(cmd_upper.split()[1])
                    state.set_count(count)
                    return None
                except (IndexError, ValueError):
                    state.error_queue.append("-220,Parameter error: invalid count")
                    return None

        elif cmd_upper.startswith("INST:LAY"):
            if "?" in cmd_upper:
                return state.layout
            else:
                try:
                    layout = cmd_original.split(maxsplit=1)[1].strip().upper()
                    if layout in ["ROW", "COL", "2X2"]:
                        state.layout = layout
                        return None
                    else:
                        state.error_queue.append(f"-220,Parameter error: invalid layout {layout}")
                        return None
                except IndexError:
                    state.error_queue.append("-220,Parameter error: missing layout")
                    return None

        # Parse LED index from command (STAT<n>:VAL, CONF<n>:LAB, etc.)
        import re
        match = re.match(r'(STAT|CONF)(\d+):(.*)', cmd_upper)
        if match:
            cmd_type = match.group(1)
            index = int(match.group(2))
            subcmd = match.group(3)

            if index < 1 or index > state.count:
                state.error_queue.append(f"-220,Parameter error: index {index} out of range 1-{state.count}")
                return None

            if index not in state.leds:
                state.leds[index] = LEDState(index)

            led = state.leds[index]

            # STAT commands
            if cmd_type == "STAT":
                if subcmd.startswith("VAL"):
                    if "?" in subcmd:
                        return "1" if led.state else "0"
                    else:
                        try:
                            val_str = cmd_original.split(maxsplit=1)[1].upper()
                            if val_str in ["1", "ON", "TRUE", "YES"]:
                                led.state = True
                            elif val_str in ["0", "OFF", "FALSE", "NO"]:
                                led.state = False
                            else:
                                state.error_queue.append(f"-220,Parameter error: invalid state {val_str}")
                                return None
                            await broadcast_state(index)
                            return None
                        except IndexError:
                            state.error_queue.append("-220,Parameter error: missing value")
                            return None

            # CONF commands
            elif cmd_type == "CONF":
                if subcmd.startswith("LAB"):
                    if "?" in subcmd:
                        return led.label
                    else:
                        led.label = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else ""
                        await broadcast_state(index)
                        return None

                elif subcmd.startswith("ONCOL"):
                    if "?" in subcmd:
                        return led.on_color
                    else:
                        led.on_color = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else "#00ff00"
                        await broadcast_state(index)
                        return None

                elif subcmd.startswith("OFFCOL"):
                    if "?" in subcmd:
                        return led.off_color
                    else:
                        led.off_color = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else "#404040"
                        await broadcast_state(index)
                        return None

        # Unknown command
        state.error_queue.append(f"-113,Undefined header: {cmd}")
        return None


# ==============================================================================
# FastAPI app
# ==============================================================================

app = FastAPI()

# Serve frontend
frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

@app.get("/")
async def root():
    """Serve multi-instance HTML"""
    html_path = frontend_dir / "index-multi.html"
    with open(html_path) as f:
        return HTMLResponse(content=f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for LED updates"""
    await websocket.accept()
    connected_clients.append(websocket)

    try:
        # Send initial state for all LEDs
        for i in range(1, state.count + 1):
            if i in state.leds:
                await websocket.send_text(json.dumps(state.leds[i].to_dict()))

        # Keep connection alive
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


# ==============================================================================
# Main
# ==============================================================================

async def main():
    """Start both SCPI and FastAPI servers"""
    # Parse command-line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Virtual LED Indicator (Multi-instance)')
    parser.add_argument('--scpi-port', type=int, default=5003, help='SCPI TCP port (default: 5003)')
    parser.add_argument('--http-port', type=int, default=8003, help='HTTP/WebSocket port (default: 8003)')
    parser.add_argument('--count', type=int, default=1, help='Initial LED count 1-4 (default: 1)')
    parser.add_argument('--layout', type=str, default='ROW', help='Initial layout: ROW, COL, 2X2 (default: ROW)')
    args = parser.parse_args()

    # Initialize state
    state.set_count(max(1, min(4, args.count)))
    if args.layout.upper() in ['ROW', 'COL', '2X2']:
        state.layout = args.layout.upper()

    global event_loop
    event_loop = asyncio.get_running_loop()

    # Start SCPI server
    scpi_server = SCPIServer(port=args.scpi_port)
    await scpi_server.start()

    # Start FastAPI server
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=args.http_port,
        log_level="info"
    )
    server = uvicorn.Server(config)

    print("Virtual LED Indicator (Multi) ready:")
    print(f"  - SCPI:      tcp://0.0.0.0:{args.scpi_port}")
    print(f"  - HTTP:      http://0.0.0.0:{args.http_port}")
    print(f"  - WebSocket: ws://0.0.0.0:{args.http_port}/ws")
    print(f"  - LEDs:      {state.count} (1-{state.count}, 1-based indexing)")
    print(f"  - Layout:    {state.layout}")
    print("\nSCPI Indexing: 1-based (STAT1, STAT2, STAT3, STAT4)")
    print("Query count:   INST:COUNT?")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
