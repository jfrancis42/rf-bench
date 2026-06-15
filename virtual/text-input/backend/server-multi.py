#!/usr/bin/env python3
"""
Virtual Text Input — Multi-instance SCPI Server

Supports 1-4 text input fields with 1-based SCPI addressing.

SCPI Commands (1-based indexing):
  SOUR<n>:VAL <string>     → Set text input N value (N=1-4)
  SOUR<n>:VAL?             → Query text input N value
  CONF<n>:LAB <string>     → Set label
  CONF<n>:PLACEHOLDER <string> → Set placeholder text

  INST:COUNT <int>         → Set number of inputs (1-4, default 1)
  INST:COUNT?              → Query input count
  INST:LAY <string>        → Set layout: ROW, COL, 2X2 (default ROW)
  INST:LAY?                → Query layout

Example:
  INST:COUNT 2
  SOUR1:VAL 5.0
  SOUR2:VAL 12.5
"""

import argparse
import asyncio
import json
import sys
import re
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

class InputState:
    """State for one text input"""
    def __init__(self, index: int):
        self.index = index
        self.value = "0.0"  # Initialize with "0.0" instead of "" to avoid SCPI query timeouts
        self.label = ""
        self.placeholder = "Enter value..."

    def to_dict(self):
        return {
            'index': self.index,
            'value': self.value,
            'label': self.label,
            'placeholder': self.placeholder
        }


class InstrumentState:
    """Global instrument state"""
    def __init__(self):
        self.count = 1
        self.layout = "ROW"
        self.inputs = {1: InputState(1)}
        self.error_queue = []

    def set_count(self, count: int):
        """Set number of inputs (1-4)"""
        count = max(1, min(4, count))
        self.count = count
        for i in range(1, count + 1):
            if i not in self.inputs:
                self.inputs[i] = InputState(i)


state = InstrumentState()
connected_clients = []


# ==============================================================================
# WebSocket broadcast
# ==============================================================================

async def broadcast_state(index: int):
    """Broadcast input state to all connected WebSocket clients"""
    if index not in state.inputs:
        return

    message = json.dumps(state.inputs[index].to_dict())
    for client in connected_clients[:]:
        try:
            await client.send_text(message)
        except Exception as e:
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
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def process_command(self, cmd: str) -> str:
        """Process SCPI command"""
        cmd_original = cmd
        cmd_upper = cmd.strip().upper()

        # IEEE 488.2 common commands
        if cmd_upper == "*IDN?":
            return f"N0GQ,Virtual-TextInput-Multi,1.0,2026"
        elif cmd_upper == "*RST":
            state.__init__()
            for i in range(1, state.count + 1):
                await broadcast_state(i)
            return None
        elif cmd_upper == "SYST:ERR?":
            if state.error_queue:
                return state.error_queue.pop(0)
            return "0,No error"

        # Instrument configuration
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

        # Parse input index from command (SOUR<n>:VAL, CONF<n>:LAB, etc.)
        match = re.match(r'(SOUR|CONF)(\d+):(.*)', cmd_upper)
        if match:
            cmd_type = match.group(1)
            index = int(match.group(2))
            subcmd = match.group(3)

            if index < 1 or index > state.count:
                state.error_queue.append(f"-220,Parameter error: index {index} out of range 1-{state.count}")
                return None

            if index not in state.inputs:
                state.inputs[index] = InputState(index)

            inp = state.inputs[index]

            # SOUR commands
            if cmd_type == "SOUR":
                if subcmd.startswith("VAL"):
                    if "?" in subcmd:
                        return str(inp.value)
                    else:
                        try:
                            val_str = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else ""
                            inp.value = val_str
                            await broadcast_state(index)
                            return None
                        except (IndexError, ValueError) as e:
                            state.error_queue.append(f"-220,Parameter error: {e}")
                            return None

            # CONF commands
            elif cmd_type == "CONF":
                if subcmd.startswith("LAB"):
                    if "?" in subcmd:
                        return inp.label
                    else:
                        inp.label = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else ""
                        await broadcast_state(index)
                        return None

                elif subcmd.startswith("PLACEHOLDER"):
                    if "?" in subcmd:
                        return inp.placeholder
                    else:
                        inp.placeholder = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else ""
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
    """WebSocket for input updates"""
    await websocket.accept()
    connected_clients.append(websocket)

    try:
        # Send initial state for all inputs
        for i in range(1, state.count + 1):
            if i in state.inputs:
                await websocket.send_text(json.dumps(state.inputs[i].to_dict()))

        # Listen for user input from browser
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                # Frontend sends {type: 'value_change', value: string, index: int}
                if msg.get('type') == 'value_change' and 'value' in msg:
                    index = msg.get('index', 1)
                    if 1 <= index <= state.count and index in state.inputs:
                        state.inputs[index].value = str(msg['value'])
                        await broadcast_state(index)
            except (json.JSONDecodeError, ValueError):
                pass

    except WebSocketDisconnect:
        connected_clients.remove(websocket)


# ==============================================================================
# Main
# ==============================================================================

async def main():
    """Start both SCPI and FastAPI servers"""
    parser = argparse.ArgumentParser(description='Virtual Text Input (Multi-instance)')
    parser.add_argument('--scpi-port', type=int, default=5000, help='SCPI TCP port (default: 5000)')
    parser.add_argument('--http-port', type=int, default=8000, help='HTTP/WebSocket port (default: 8000)')
    parser.add_argument('--count', type=int, default=1, help='Initial input count 1-4 (default: 1)')
    parser.add_argument('--layout', type=str, default='ROW', help='Initial layout: ROW, COL, 2X2 (default: ROW)')
    args = parser.parse_args()

    # Initialize state
    state.set_count(max(1, min(4, args.count)))
    if args.layout.upper() in ['ROW', 'COL', '2X2']:
        state.layout = args.layout.upper()

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

    print("Virtual Text Input (Multi) ready:")
    print(f"  - SCPI:      tcp://0.0.0.0:{args.scpi_port}")
    print(f"  - HTTP:      http://0.0.0.0:{args.http_port}")
    print(f"  - WebSocket: ws://0.0.0.0:{args.http_port}/ws")
    print(f"  - Inputs:    {state.count} (1-{state.count}, 1-based indexing)")
    print(f"  - Layout:    {state.layout}")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
