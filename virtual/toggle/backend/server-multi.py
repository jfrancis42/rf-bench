#!/usr/bin/env python3
"""
Virtual Toggle Switch — Multi-instance SCPI Server

Supports 1-4 toggles with 1-based SCPI addressing.

SCPI Commands (1-based indexing):
  STAT<n>:VAL <0|1|ON|OFF>   → Set toggle N state (N=1-4)
  STAT<n>:VAL?               → Query toggle N state
  CONF<n>:LAB <string>       → Set label

  INST:COUNT <int>           → Set number of toggles (1-4, default 1)
  INST:LAY <string>          → Set layout: ROW, COL, 2X2
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


class ToggleState:
    def __init__(self, index: int):
        self.index = index
        self.state = False
        self.label = ""

    def to_dict(self):
        return {'index': self.index, 'state': self.state, 'label': self.label}


class InstrumentState:
    def __init__(self):
        self.count = 1
        self.layout = "ROW"
        self.toggles = {1: ToggleState(1)}
        self.error_queue = []

    def set_count(self, count: int):
        count = max(1, min(4, count))
        self.count = count
        for i in range(1, count + 1):
            if i not in self.toggles:
                self.toggles[i] = ToggleState(i)


state = InstrumentState()
connected_clients = []


async def broadcast_state(index: int):
    if index not in state.toggles:
        return
    message = json.dumps(state.toggles[index].to_dict())
    for client in connected_clients[:]:
        try:
            await client.send_text(message)
        except:
            connected_clients.remove(client)


class SCPIServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 5006):
        self.host = host
        self.port = port

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
            return "N0GQ,Virtual-Toggle-Multi,1.0,2026"
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
            try:
                state.set_count(int(cmd_upper.split()[1]))
                return None
            except:
                state.error_queue.append("-220,Parameter error")
                return None

        elif cmd_upper.startswith("INST:LAY"):
            if "?" in cmd_upper:
                return state.layout
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
        match = re.match(r'(STAT|CONF)(\d+):(.*)', cmd_upper)
        if match:
            cmd_type = match.group(1)
            index = int(match.group(2))
            subcmd = match.group(3)

            if index < 1 or index > state.count:
                state.error_queue.append(f"-220,Index out of range")
                return None

            if index not in state.toggles:
                state.toggles[index] = ToggleState(index)

            toggle = state.toggles[index]

            if cmd_type == "STAT" and subcmd.startswith("VAL"):
                if "?" in subcmd:
                    return "1" if toggle.state else "0"
                try:
                    val = cmd_original.split(maxsplit=1)[1].upper()
                    if val in ["1", "ON", "TRUE"]:
                        toggle.state = True
                    elif val in ["0", "OFF", "FALSE"]:
                        toggle.state = False
                    else:
                        state.error_queue.append("-220,Invalid state")
                        return None
                    await broadcast_state(index)
                    return None
                except:
                    state.error_queue.append("-220,Parameter error")
                    return None

            elif cmd_type == "CONF" and subcmd.startswith("LAB"):
                if "?" in subcmd:
                    return toggle.label
                toggle.label = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else ""
                await broadcast_state(index)
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
            if i in state.toggles:
                await websocket.send_text(json.dumps(state.toggles[i].to_dict()))
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if 'index' in msg and 'state' in msg:
                index = msg['index']
                if 1 <= index <= state.count and index in state.toggles:
                    state.toggles[index].state = msg['state']
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


async def main():
    # Parse command-line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Virtual Toggle Switch (Multi-instance)')
    parser.add_argument('--scpi-port', type=int, default=5006, help='SCPI TCP port (default: 5006)')
    parser.add_argument('--http-port', type=int, default=8006, help='HTTP/WebSocket port (default: 8006)')
    parser.add_argument('--count', type=int, default=1, help='Initial toggle count 1-4 (default: 1)')
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
    print("Virtual Toggle (Multi) ready:")
    print(f"  - SCPI:      tcp://0.0.0.0:{args.scpi_port}")
    print(f"  - HTTP:      http://0.0.0.0:{args.http_port}")
    print(f"  - WebSocket: ws://0.0.0.0:{args.http_port}/ws")
    print(f"  - Toggles:   {state.count} (1-{state.count}, 1-based indexing)")
    print(f"  - Layout:    {state.layout}")
    print("\nSCPI Indexing: 1-based (STAT1, STAT2, STAT3, STAT4)")
    print("Query count:   INST:COUNT?")
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
