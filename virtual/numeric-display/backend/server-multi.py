#!/usr/bin/env python3
"""
Virtual Numeric Display — Multi-instance SCPI Server

Supports 1-4 displays with 1-based SCPI addressing.

SCPI Commands (1-based indexing):
  MEAS<n>:VAL <float>      → Set display N value (N=1-4)
  MEAS<n>:VAL?             → Query display N value
  CONF<n>:PREC <int>       → Set precision (0-6 decimals)
  CONF<n>:UNIT <string>    → Set units
  CONF<n>:LAB <string>     → Set label
  CONF<n>:COL <color>      → Set color (hex)
  CONF<n>:STYLE <style>    → Set display style: 7SEG, PLAIN, LED, NIXIE, VFD

  INST:COUNT <int>         → Set number of displays (1-4, default 1)
  INST:COUNT?              → Query display count
  INST:LAY <string>        → Set layout: ROW, COL, 2X2 (default ROW)
  INST:LAY?                → Query layout

IMPORTANT: Sub-instances use 1-based indexing (N=1,2,3,4), NOT 0-based.

Example:
  INST:COUNT 2             # Two displays
  INST:LAY ROW             # Side by side
  MEAS1:VAL 14.257         # Display 1 (left)
  CONF1:UNIT MHz
  CONF1:LAB Frequency
  MEAS2:VAL 50.0           # Display 2 (right)
  CONF2:UNIT W
  CONF2:LAB Power
"""

import argparse
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

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: paho-mqtt required. Install: pip install paho-mqtt", file=sys.stderr)
    sys.exit(1)


# ==============================================================================
# State
# ==============================================================================

class DisplayState:
    """State for one display"""
    def __init__(self, index: int):
        self.index = index
        self.value = 0.0
        self.precision = 2
        self.units = ""
        self.label = ""
        self.color = "#00ff88"
        self.style = "7SEG"  # 7SEG, PLAIN, LED, NIXIE, VFD

    def to_dict(self):
        return {
            'index': self.index,
            'value': self.value,
            'precision': self.precision,
            'units': self.units,
            'label': self.label,
            'color': self.color,
            'style': self.style
        }


class InstrumentState:
    """Global instrument state"""
    def __init__(self):
        self.count = 1
        self.layout = "ROW"
        self.displays = {1: DisplayState(1)}
        self.error_queue = []
        self.mqtt_host = None
        self.mqtt_topic = None

    def set_count(self, count: int):
        """Set number of displays (1-4)"""
        count = max(1, min(4, count))
        self.count = count
        # Initialize displays if needed
        for i in range(1, count + 1):
            if i not in self.displays:
                self.displays[i] = DisplayState(i)


state = InstrumentState()
connected_clients = []
event_loop = None


# ==============================================================================
# WebSocket broadcast
# ==============================================================================

async def broadcast_state(index: int):
    """Broadcast display state to all connected WebSocket clients"""
    if index not in state.displays:
        return

    message = json.dumps(state.displays[index].to_dict())
    print(f"Broadcasting to {len(connected_clients)} clients: {message}", flush=True)
    for client in connected_clients[:]:
        try:
            await client.send_text(message)
            print(f"  Sent to client", flush=True)
        except Exception as e:
            print(f"  Failed to send: {e}", flush=True)
            connected_clients.remove(client)


# ==============================================================================
# SCPI Server
# ==============================================================================

class SCPIServer:
    """SCPI TCP server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
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
        print(f"SCPI RX: {cmd}", flush=True)
        """Process SCPI command"""
        cmd_original = cmd
        cmd_upper = cmd.strip().upper()

        # IEEE 488.2 common commands
        if cmd_upper == "*IDN?":
            return f"N0GQ,Virtual-Numeric-Display-Multi,1.0,2026"
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

        # Parse display index from command (MEAS<n>:VAL, CONF<n>:UNIT, etc.)
        # Extract index from command like "MEAS3:VAL" or "CONF2:UNIT"
        import re
        match = re.match(r'(MEAS|CONF)(\d+):(.*)', cmd_upper)
        if match:
            cmd_type = match.group(1)
            index = int(match.group(2))
            subcmd = match.group(3)

            if index < 1 or index > state.count:
                state.error_queue.append(f"-220,Parameter error: index {index} out of range 1-{state.count}")
                return None

            if index not in state.displays:
                state.displays[index] = DisplayState(index)

            disp = state.displays[index]

            # MEAS commands
            if cmd_type == "MEAS":
                if subcmd.startswith("VAL"):
                    if "?" in subcmd:
                        return str(disp.value)
                    else:
                        try:
                            val_str = cmd_original.split(maxsplit=1)[1]
                            disp.value = float(val_str)
                            await broadcast_state(index)
                            return None
                        except (IndexError, ValueError) as e:
                            state.error_queue.append(f"-220,Parameter error: {e}")
                            return None

            # CONF commands
            elif cmd_type == "CONF":
                if subcmd.startswith("PREC"):
                    if "?" in subcmd:
                        return str(disp.precision)
                    else:
                        try:
                            prec = int(cmd_upper.split()[1])
                            disp.precision = max(0, min(6, prec))
                            await broadcast_state(index)
                            return None
                        except (IndexError, ValueError):
                            state.error_queue.append("-220,Parameter error: invalid precision")
                            return None

                elif subcmd.startswith("UNIT"):
                    if "?" in subcmd:
                        return disp.units
                    else:
                        disp.units = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else ""
                        await broadcast_state(index)
                        return None

                elif subcmd.startswith("LAB"):
                    if "?" in subcmd:
                        return disp.label
                    else:
                        disp.label = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else ""
                        await broadcast_state(index)
                        return None

                elif subcmd.startswith("COL"):
                    if "?" in subcmd:
                        return disp.color
                    else:
                        disp.color = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else "#00ff88"
                        await broadcast_state(index)
                        return None

                elif subcmd.startswith("STYLE"):
                    if "?" in subcmd:
                        return disp.style
                    else:
                        style = cmd_upper.split(maxsplit=1)[1] if len(cmd_upper.split(maxsplit=1)) > 1 else "7SEG"
                        if style in ["7SEG", "PLAIN", "LED", "NIXIE", "VFD"]:
                            disp.style = style
                            await broadcast_state(index)
                            return None
                        else:
                            state.error_queue.append(f"-220,Invalid style: {style}")
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
    """WebSocket for display updates"""
    await websocket.accept()
    connected_clients.append(websocket)

    try:
        # Send initial state for all displays
        for i in range(1, state.count + 1):
            if i in state.displays:
                await websocket.send_text(json.dumps(state.displays[i].to_dict()))

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
    parser = argparse.ArgumentParser(description='Virtual Numeric Display (Multi-instance)')
    parser.add_argument('--scpi-port', type=int, default=5000, help='SCPI TCP port (default: 5000)')
    parser.add_argument('--http-port', type=int, default=8000, help='HTTP/WebSocket port (default: 8000)')
    parser.add_argument('--count', type=int, default=1, help='Initial display count 1-4 (default: 1)')
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

    print("Virtual Numeric Display (Multi) ready:")
    print(f"  - SCPI:      tcp://0.0.0.0:{args.scpi_port}")
    print(f"  - HTTP:      http://0.0.0.0:{args.http_port}")
    print(f"  - WebSocket: ws://0.0.0.0:{args.http_port}/ws")
    print(f"  - Displays:  {state.count} (1-{state.count}, 1-based indexing)")
    print(f"  - Layout:    {state.layout}")
    print("\nSCPI Indexing: 1-based (MEAS1, MEAS2, MEAS3, MEAS4)")
    print("Query count:   INST:COUNT?")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
