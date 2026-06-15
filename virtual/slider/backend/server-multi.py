#!/usr/bin/env python3
"""
Virtual Slider — Multi-instance SCPI Server

Supports 1-4 sliders with 1-based SCPI addressing.

SCPI Commands (1-based indexing):
  SOUR<n>:VAL <float>      → Set slider N value (N=1-4)
  SOUR<n>:VAL?             → Query slider N value
  CONF<n>:MIN <float>      → Set minimum value
  CONF<n>:MAX <float>      → Set maximum value
  CONF<n>:UNIT <string>    → Set units
  CONF<n>:LAB <string>     → Set label
  CONF<n>:COL <color>      → Set color

  INST:COUNT <int>         → Set number of sliders (1-4, default 1)
  INST:LAY <string>        → Set layout: ROW, COL, 2X2
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
    print("ERROR: FastAPI/uvicorn required", file=sys.stderr)
    sys.exit(1)


class SliderState:
    def __init__(self, index: int):
        self.index = index
        self.value = 0.0
        self.min = 0.0
        self.max = 100.0
        self.step = 1.0
        self.label = ""
        self.units = ""
        self.color = "#00ff88"

    def to_dict(self):
        return {
            'index': self.index,
            'value': self.value,
            'min_val': self.min,  # Frontend expects min_val
            'max_val': self.max,  # Frontend expects max_val
            'step': self.step,
            'label': self.label,
            'units': self.units,
            'color': self.color,
            'orientation': 'VERT'  # Default to vertical
        }


class InstrumentState:
    def __init__(self):
        self.count = 1
        self.layout = "ROW"
        self.sliders = {1: SliderState(1)}
        self.error_queue = []

    def set_count(self, count: int):
        count = max(1, min(4, count))
        self.count = count
        for i in range(1, count + 1):
            if i not in self.sliders:
                self.sliders[i] = SliderState(i)


state = InstrumentState()
connected_clients = []


async def broadcast_state(index: int):
    if index not in state.sliders:
        return
    message = json.dumps(state.sliders[index].to_dict())
    for client in connected_clients[:]:
        try:
            await client.send_text(message)
        except:
            connected_clients.remove(client)


class SCPIServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 5005):
        self.host = host
        self.port = port
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        print(f"SCPI TCP server listening on {self.host}:{self.port}")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
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
        finally:
            writer.close()
            await writer.wait_closed()

    async def process_command(self, cmd: str) -> str:
        cmd_original = cmd
        cmd_upper = cmd.strip().upper()

        if cmd_upper == "*IDN?":
            return "N0GQ,Virtual-Slider-Multi,1.0,2026"
        elif cmd_upper == "*RST":
            state.__init__()
            for i in range(1, state.count + 1):
                await broadcast_state(i)
            return None
        elif cmd_upper == "SYST:ERR?":
            return state.error_queue.pop(0) if state.error_queue else "0,No error"

        if cmd_upper.startswith("INST:COUNT"):
            if "?" in cmd_upper:
                return str(state.count)
            else:
                try:
                    state.set_count(int(cmd_upper.split()[1]))
                    return None
                except:
                    state.error_queue.append("-220,Parameter error")
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
                except:
                    pass
                state.error_queue.append("-220,Parameter error")
                return None

        import re
        match = re.match(r'(SOUR|CONF)(\d+):(.*)', cmd_upper)
        if match:
            cmd_type = match.group(1)
            index = int(match.group(2))
            subcmd = match.group(3)

            if index < 1 or index > state.count:
                state.error_queue.append(f"-220,Index out of range")
                return None

            if index not in state.sliders:
                state.sliders[index] = SliderState(index)

            slider = state.sliders[index]

            if cmd_type == "SOUR" and subcmd.startswith("VAL"):
                if "?" in subcmd:
                    return str(slider.value)
                else:
                    try:
                        slider.value = float(cmd_original.split(maxsplit=1)[1])
                        await broadcast_state(index)
                        return None
                    except:
                        state.error_queue.append("-220,Parameter error")
                        return None

            elif cmd_type == "CONF":
                if subcmd.startswith("MIN"):
                    if "?" in subcmd:
                        return str(slider.min)
                    try:
                        slider.min = float(cmd_upper.split()[1])
                        await broadcast_state(index)
                        return None
                    except:
                        state.error_queue.append("-220,Parameter error")
                        return None

                elif subcmd.startswith("MAX"):
                    if "?" in subcmd:
                        return str(slider.max)
                    try:
                        slider.max = float(cmd_upper.split()[1])
                        await broadcast_state(index)
                        return None
                    except:
                        state.error_queue.append("-220,Parameter error")
                        return None

                elif subcmd.startswith("UNIT"):
                    if "?" in subcmd:
                        return slider.units
                    slider.units = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else ""
                    await broadcast_state(index)
                    return None

                elif subcmd.startswith("LAB"):
                    if "?" in subcmd:
                        return slider.label
                    slider.label = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else ""
                    await broadcast_state(index)
                    return None

                elif subcmd.startswith("COL"):
                    if "?" in subcmd:
                        return slider.color
                    slider.color = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else "#00ff88"
                    await broadcast_state(index)
                    return None

                elif subcmd.startswith("STEP"):
                    if "?" in subcmd:
                        return str(slider.step)
                    try:
                        slider.step = float(cmd_upper.split()[1])
                        await broadcast_state(index)
                        return None
                    except:
                        state.error_queue.append("-220,Parameter error")
                        return None

        state.error_queue.append(f"-113,Undefined header")
        return None


app = FastAPI()
frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

@app.get("/")
async def root():
    with open(frontend_dir / "index-multi.html") as f:
        return HTMLResponse(content=f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        for i in range(1, state.count + 1):
            if i in state.sliders:
                await websocket.send_text(json.dumps(state.sliders[i].to_dict()))
        while True:
            data = await websocket.receive_text()
            # Handle slider changes from frontend
            try:
                msg = json.loads(data)
                # Frontend sends {type: 'value_change', value: float, index?: int}
                # If no index specified, assume index 1 (single slider mode)
                if msg.get('type') == 'value_change' and 'value' in msg:
                    index = msg.get('index', 1)
                    if 1 <= index <= state.count and index in state.sliders:
                        state.sliders[index].value = float(msg['value'])
                        # Broadcast to other clients
                        await broadcast_state(index)
            except (json.JSONDecodeError, ValueError):
                pass  # Ignore malformed messages
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


async def main():
    # Parse command-line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Virtual Slider (Multi-instance)')
    parser.add_argument('--scpi-port', type=int, default=5005, help='SCPI TCP port (default: 5005)')
    parser.add_argument('--http-port', type=int, default=8005, help='HTTP/WebSocket port (default: 8005)')
    parser.add_argument('--count', type=int, default=1, help='Initial slider count 1-4 (default: 1)')
    parser.add_argument('--layout', type=str, default='ROW', help='Initial layout: ROW, COL, 2X2 (default: ROW)')
    args = parser.parse_args()

    # Initialize state
    state.set_count(max(1, min(4, args.count)))
    if args.layout.upper() in ['ROW', 'COL', '2X2']:
        state.layout = args.layout.upper()

    scpi_server = SCPIServer(port=args.scpi_port)
    await scpi_server.start()
    config = uvicorn.Config(app=app, host="0.0.0.0", port=args.http_port, log_level="info")
    server = uvicorn.Server(config)
    print("Virtual Slider (Multi) ready:")
    print(f"  - SCPI:      tcp://0.0.0.0:{args.scpi_port}")
    print(f"  - HTTP:      http://0.0.0.0:{args.http_port}")
    print(f"  - WebSocket: ws://0.0.0.0:{args.http_port}/ws")
    print(f"  - Sliders:   {state.count} (1-{state.count}, 1-based indexing)")
    print(f"  - Layout:    {state.layout}")
    print("\nSCPI Indexing: 1-based (SOUR1, SOUR2, SOUR3, SOUR4)")
    print("Query count:   INST:COUNT?")
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
