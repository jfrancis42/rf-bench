#!/usr/bin/env python3
"""
Virtual Analog Meter — Multi-instance SCPI Server

Supports 1-4 meters with 1-based SCPI addressing.

SCPI Commands (1-based indexing):
  MEAS<n>:VAL <float>      → Set meter N value (N=1-4)
  MEAS<n>:VAL?             → Query meter N value
  CONF<n>:MIN <float>      → Set minimum value
  CONF<n>:MAX <float>      → Set maximum value
  CONF<n>:UNIT <string>    → Set units
  CONF<n>:LAB <string>     → Set label
  CONF<n>:COL <color>      → Set needle/value color

  INST:COUNT <int>         → Set number of meters (1-4, default 1)
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


class MeterState:
    def __init__(self, index: int):
        self.index = index
        self.value = 0.0
        self.min = 0.0
        self.max = 100.0
        self.label = ""
        self.units = ""
        self.color = "#00ff88"

    def get_zones(self):
        """Calculate zones based on current min/max (70%, 85%, 100%)"""
        range_val = self.max - self.min
        return [
            {"min": self.min, "max": self.min + range_val * 0.70, "color": "#00ff00"},
            {"min": self.min + range_val * 0.70, "max": self.min + range_val * 0.85, "color": "#ffff00"},
            {"min": self.min + range_val * 0.85, "max": self.max, "color": "#ff0000"}
        ]

    def to_dict(self):
        return {
            'index': self.index,
            'value': self.value,
            'min': self.min,
            'max': self.max,
            'label': self.label,
            'units': self.units,
            'color': self.color,
            'zones': self.get_zones()
        }


class InstrumentState:
    def __init__(self):
        self.count = 1
        self.layout = "ROW"
        self.meters = {1: MeterState(1)}
        self.error_queue = []

    def set_count(self, count: int):
        count = max(1, min(4, count))
        self.count = count
        for i in range(1, count + 1):
            if i not in self.meters:
                self.meters[i] = MeterState(i)


state = InstrumentState()
connected_clients = []


async def broadcast_state(index: int):
    if index not in state.meters:
        return
    message = json.dumps(state.meters[index].to_dict())
    for client in connected_clients[:]:
        try:
            await client.send_text(message)
        except:
            connected_clients.remove(client)


class SCPIServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 5002):
        self.host = host
        self.port = port
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )
        print(f"SCPI TCP server listening on {self.host}:{self.port}")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
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

    async def process_command(self, cmd: str) -> str:
        cmd_original = cmd
        cmd_upper = cmd.strip().upper()

        if cmd_upper == "*IDN?":
            return "N0GQ,Virtual-Analog-Meter-Multi,1.0,2026"
        elif cmd_upper == "*RST":
            state.__init__()
            for i in range(1, state.count + 1):
                await broadcast_state(i)
            return None
        elif cmd_upper == "SYST:ERR?":
            if state.error_queue:
                return state.error_queue.pop(0)
            return "0,No error"

        if cmd_upper.startswith("INST:COUNT"):
            if "?" in cmd_upper:
                return str(state.count)
            else:
                try:
                    count = int(cmd_upper.split()[1])
                    state.set_count(count)
                    return None
                except (IndexError, ValueError):
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
                except IndexError:
                    pass
                state.error_queue.append("-220,Parameter error")
                return None

        import re
        match = re.match(r'(MEAS|CONF)(\d+):(.*)', cmd_upper)
        if match:
            cmd_type = match.group(1)
            index = int(match.group(2))
            subcmd = match.group(3)

            if index < 1 or index > state.count:
                state.error_queue.append(f"-220,Index {index} out of range")
                return None

            if index not in state.meters:
                state.meters[index] = MeterState(index)

            meter = state.meters[index]

            if cmd_type == "MEAS":
                if subcmd.startswith("VAL"):
                    if "?" in subcmd:
                        return str(meter.value)
                    else:
                        try:
                            val = float(cmd_original.split(maxsplit=1)[1])
                            meter.value = max(meter.min, min(meter.max, val))
                            await broadcast_state(index)
                            return None
                        except (IndexError, ValueError):
                            state.error_queue.append("-220,Parameter error")
                            return None

            elif cmd_type == "CONF":
                if subcmd.startswith("MIN"):
                    if "?" in subcmd:
                        return str(meter.min)
                    else:
                        try:
                            meter.min = float(cmd_upper.split()[1])
                            await broadcast_state(index)
                            return None
                        except (IndexError, ValueError):
                            state.error_queue.append("-220,Parameter error")
                            return None

                elif subcmd.startswith("MAX"):
                    if "?" in subcmd:
                        return str(meter.max)
                    else:
                        try:
                            meter.max = float(cmd_upper.split()[1])
                            await broadcast_state(index)
                            return None
                        except (IndexError, ValueError):
                            state.error_queue.append("-220,Parameter error")
                            return None

                elif subcmd.startswith("UNIT"):
                    if "?" in subcmd:
                        return meter.units
                    else:
                        meter.units = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else ""
                        await broadcast_state(index)
                        return None

                elif subcmd.startswith("LAB"):
                    if "?" in subcmd:
                        return meter.label
                    else:
                        meter.label = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else ""
                        await broadcast_state(index)
                        return None

                elif subcmd.startswith("COL"):
                    if "?" in subcmd:
                        return meter.color
                    else:
                        meter.color = cmd_original.split(maxsplit=1)[1] if len(cmd_original.split(maxsplit=1)) > 1 else "#00ff88"
                        await broadcast_state(index)
                        return None

        state.error_queue.append(f"-113,Undefined header: {cmd}")
        return None


app = FastAPI()

frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

@app.get("/")
async def root():
    html_path = frontend_dir / "index-multi.html"
    with open(html_path) as f:
        return HTMLResponse(content=f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)

    try:
        for i in range(1, state.count + 1):
            if i in state.meters:
                await websocket.send_text(json.dumps(state.meters[i].to_dict()))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


async def main():
    # Parse command-line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Virtual Analog Meter (Multi-instance)')
    parser.add_argument('--scpi-port', type=int, default=5002, help='SCPI TCP port (default: 5002)')
    parser.add_argument('--http-port', type=int, default=8002, help='HTTP/WebSocket port (default: 8002)')
    parser.add_argument('--count', type=int, default=1, help='Initial meter count 1-4 (default: 1)')
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

    print("Virtual Analog Meter (Multi) ready:")
    print(f"  - SCPI:      tcp://0.0.0.0:{args.scpi_port}")
    print(f"  - HTTP:      http://0.0.0.0:{args.http_port}")
    print(f"  - WebSocket: ws://0.0.0.0:{args.http_port}/ws")
    print(f"  - Meters:    {state.count} (1-{state.count}, 1-based indexing)")
    print(f"  - Layout:    {state.layout}")
    print("\nSCPI Indexing: 1-based (MEAS1, MEAS2, MEAS3, MEAS4)")
    print("Query count:   INST:COUNT?")

    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
