#!/usr/bin/env python3
"""
BenchView - Virtual Instrument Grid Layout Manager

Manages instrument backends with dynamic port assignment.
- Reads input YAML with instrument names
- Assigns unique SCPI and HTTP ports to each instrument
- Launches instrument backends with assigned ports
- Writes output YAML with port assignments for glue code
"""

import sys
import yaml
import subprocess
import atexit
import time
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn
import httpx
import websockets


class BenchView:
    """Grid layout manager with dynamic port assignment"""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = None
        self.backend_processes = []
        self.port_assignments = {}
        self.next_scpi_port = 5100  # Start at 5100 to avoid conflicts
        self.next_http_port = 8100  # Start at 8100

        self._load_config()
        self._assign_ports()

        # Create FastAPI app
        self.app = FastAPI(title="BenchView", version="2.0.0")
        self._setup_routes()

        # Register cleanup
        atexit.register(self._cleanup_backends)

    def _load_config(self):
        """Load YAML config"""
        with open(self.config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        panel = self.config['panel']
        print(f"Loaded panel: {panel['name']}")
        print(f"Grid: {panel['grid']['columns']}×{panel['grid']['rows']}")
        print(f"Instruments: {len(panel['instruments'])}")

        # Validate: each instrument must have a unique 'name'
        names = set()
        for instr in panel['instruments']:
            if 'name' not in instr:
                print(f"ERROR: Instrument {instr.get('id')} missing required 'name' field")
                sys.exit(1)
            if instr['name'] in names:
                print(f"ERROR: Duplicate instrument name: {instr['name']}")
                sys.exit(1)
            names.add(instr['name'])

    def _assign_ports(self):
        """Assign unique SCPI and HTTP ports to each instrument"""
        for instr in self.config['panel']['instruments']:
            name = instr['name']
            scpi_port = self.next_scpi_port
            http_port = self.next_http_port

            self.port_assignments[name] = {
                'scpi_port': scpi_port,
                'http_port': http_port,
                'ws_port': http_port,  # WebSocket on same port as HTTP
                'type': instr['type'],
                'count': instr.get('count', 1),
                'layout': instr.get('layout', 'ROW'),
                'indexing': '1-based'  # Document that sub-instances use 1-based indexing
            }

            self.next_scpi_port += 1
            self.next_http_port += 1

        print("\nPort assignments:")
        for name, ports in self.port_assignments.items():
            print(f"  {name}: SCPI={ports['scpi_port']}, HTTP={ports['http_port']}, count={ports['count']}, indexing={ports['indexing']}")

    def _write_output_yaml(self):
        """Write output YAML with port assignments.

        Writes both legacy format (for backward compat) and inventory overlay format.
        """
        # Legacy format (in same dir as config)
        legacy_path = Path(self.config_path).parent / f"{Path(self.config_path).stem}_ports.yaml"

        legacy_output = {
            'panel': self.config['panel']['name'],
            'instruments': {}
        }

        # Inventory overlay format (in ~/.rf-bench/)
        inventory_dir = Path.home() / '.rf-bench'
        inventory_dir.mkdir(exist_ok=True, parents=True)
        inventory_path = inventory_dir / f"benchview_{Path(self.config_path).stem}_ports.yaml"

        inventory_output = {
            'panel': self.config['panel']['name'],
            'instruments': {}
        }

        for name, ports in self.port_assignments.items():
            # Legacy format
            legacy_output['instruments'][name] = {
                'scpi_port': ports['scpi_port'],
                'http_port': ports['http_port'],
                'ws_port': ports['ws_port'],
                'type': ports['type'],
                'count': ports['count'],
                'layout': ports['layout'],
                'indexing': ports['indexing'],
                'scpi_query_count': 'INST:COUNT?',
                'scpi_index_range': f"1-{ports['count']}"
            }

            # Inventory overlay format - matches inventory schema
            inventory_output['instruments'][name] = {
                'type': ports['type'],
                'driver': f"rf_bench.virtual.{ports['type']}",
                'connection': {
                    'protocol': 'scpi-tcp',
                    'host': 'localhost',
                    'port': ports['scpi_port'],
                    'http_port': ports['http_port'],
                    'ws_port': ports['ws_port'],
                },
                'tags': ['virtual', 'benchview'],
                'notes': f"BenchView panel: {self.config['panel']['name']}, " +
                         f"count: {ports['count']}, indexing: {ports['indexing']}"
            }

        # Write both formats
        with open(legacy_path, 'w') as f:
            yaml.dump(legacy_output, f, default_flow_style=False, sort_keys=False)

        with open(inventory_path, 'w') as f:
            yaml.dump(inventory_output, f, default_flow_style=False, sort_keys=False)

        print(f"\nWrote port assignments:")
        print(f"  Legacy:    {legacy_path}")
        print(f"  Inventory: {inventory_path}")
        return legacy_path

    def _setup_routes(self):
        """Setup FastAPI routes"""

        @self.app.get("/")
        async def root():
            """Serve grid layout HTML"""
            return HTMLResponse(content=self._generate_html())

        @self.app.get("/config")
        async def get_config():
            """Return panel config as JSON"""
            return {
                'panel': self.config['panel'],
                'ports': self.port_assignments
            }

        @self.app.get("/test-ws")
        async def test_ws():
            """Serve WebSocket test page"""
            with open(Path(__file__).parent / "test-ws.html") as f:
                return HTMLResponse(content=f.read())

        @self.app.get("/simple-test")
        async def simple_test():
            """Serve simple standalone test page"""
            with open(Path(__file__).parent / "simple-test.html") as f:
                return HTMLResponse(content=f.read())

        # Proxy instrument HTTP requests (including fonts and static files)
        @self.app.get("/instrument/{name}/{path:path}")
        async def proxy_instrument(name: str, path: str, request: Request):
            """Proxy requests to instrument backends"""
            if name not in self.port_assignments:
                return Response(status_code=404, content=f"Instrument {name} not found")

            port = self.port_assignments[name]['http_port']
            url = f"http://localhost:{port}/{path}"

            # Forward query params
            if request.url.query:
                url += f"?{request.url.query}"

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, timeout=5.0)

                    # If HTML, inject WebSocket proxy rewrite script + iframe sizing fixes
                    content = response.content
                    if 'text/html' in response.headers.get('content-type', ''):
                        html = content.decode('utf-8')

                        # Fix font URLs to use /static/ prefix
                        html = html.replace("url('fonts-", f"url('/instrument/{name}/static/fonts-")
                        html = html.replace("url('fonts/", f"url('/instrument/{name}/static/fonts/")

                        # Rewrite WebSocket connection to use proxy path
                        injection = f"""
<style>
/* Fix sizing for iframe embedding */
html {{
    font-size: 16px; /* Base size for rem units */
}}
body {{
    overflow: hidden !important;
    position: relative;
}}

/* Red X overlay for disconnected state */
#disconnected-overlay {{
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    pointer-events: none;
    z-index: 9999;
    display: none;
}}

#disconnected-overlay.show {{
    display: block;
}}

#disconnected-overlay::before,
#disconnected-overlay::after {{
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    width: 141.42%;  /* sqrt(2) * 100% to span diagonally */
    height: 8px;
    background: #ff0000;
    box-shadow: 0 0 10px rgba(255, 0, 0, 0.8);
}}

#disconnected-overlay::before {{
    transform: translate(-50%, -50%) rotate(45deg);
}}

#disconnected-overlay::after {{
    transform: translate(-50%, -50%) rotate(-45deg);
}}

#grid {{
    padding: 8px !important;
    gap: 8px !important;
}}

/* Fix main value displays - scale with container */
.display-value {{
    font-size: clamp(1.5rem, 6vw, 3.5rem) !important;
    /* Don't override font-family - let style classes (nixie, vfd, etc.) control it */
    font-weight: 900;
}}
.display-label, .meter-label {{
    font-size: clamp(0.7rem, 2vw, 1rem) !important;
    min-height: 0.8em !important;
    margin-bottom: 3px !important;
    opacity: 1 !important;
    visibility: visible !important;
}}
.display-units {{
    font-size: clamp(0.8rem, 2.5vw, 1.2rem) !important;
    min-height: 1.2em !important;
    opacity: 1 !important;
    visibility: visible !important;
}}

/* Knob controls */
.knob-value {{
    font-size: clamp(1rem, 3.5vw, 1.5rem) !important;
}}
.knob-label {{
    font-size: clamp(0.7rem, 2vw, 1rem) !important;
    min-height: 1.2em !important;
    opacity: 1 !important;
    visibility: visible !important;
}}

/* LED labels */
.led-label {{
    font-size: clamp(0.7rem, 2vw, 1rem) !important;
    min-height: 1.2em !important;
    opacity: 1 !important;
    visibility: visible !important;
}}

/* Canvas elements (meters/gauges) - make them larger */
canvas {{
    max-width: 98% !important;
    max-height: 92% !important;
    width: auto !important;
    height: auto !important;
}}

/* All panels need uniform padding */
.display, .meter-panel, .bar-panel, .knob-panel {{
    padding: 8px !important;
}}

/* LED panels need different handling - less top padding, more bottom */
.led-panel {{
    padding: 8px !important;
    padding-top: 5px !important;
    padding-bottom: 20px !important;
}}

/* LED grid container inside panels */
.led-panel > #grid, .led-panel .grid {{
    padding: 5px !important;
    gap: 8px !important;
}}

/* Bar graph labels */
.bar-label {{
    font-size: clamp(0.7rem, 2vw, 1rem) !important;
    min-height: 1.2em !important;
    opacity: 1 !important;
    visibility: visible !important;
}}

/* Ensure all text elements are visible */
[class*="label"], [class*="units"] {{
    opacity: 1 !important;
    visibility: visible !important;
    display: block !important;
}}
</style>
<script>
(function() {{
    'use strict';

    // Override WebSocket IMMEDIATELY (runs synchronously before page body loads)
    const OriginalWebSocket = window.WebSocket;
    let overlayRef = null;

    window.WebSocket = function(url, protocols) {{
        // Rewrite ws://hostname:port/ws to relative proxy path
        if (url.includes('/ws')) {{
            url = '/instrument/{name}/ws';
            // Make it absolute with current origin
            const loc = window.location;
            url = loc.protocol.replace('http', 'ws') + '//' + loc.host + url;
        }}

        const ws = new OriginalWebSocket(url, protocols);

        // Track connection state for red X overlay
        ws.addEventListener('open', () => {{
            if (overlayRef) overlayRef.classList.remove('show');
        }});

        ws.addEventListener('close', () => {{
            if (overlayRef) overlayRef.classList.add('show');
        }});

        ws.addEventListener('error', () => {{
            if (overlayRef) overlayRef.classList.add('show');
        }});

        return ws;
    }};

    // Wait for DOM before creating red X overlay
    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', initOverlays);
    }} else {{
        initOverlays();
    }}

    function initOverlays() {{
        // Create disconnected overlay (red X)
        const overlay = document.createElement('div');
        overlay.id = 'disconnected-overlay';
        overlay.className = 'show';
        document.body.appendChild(overlay);
        overlayRef = overlay;
    }}
}})();
</script>
</head>"""
                        html = html.replace('</head>', injection)
                        content = html.encode('utf-8')

                    return Response(
                        content=content,
                        status_code=response.status_code,
                        media_type=response.headers.get('content-type', 'text/html'),
                        headers={
                            'Cache-Control': 'no-cache, no-store, must-revalidate',
                            'Pragma': 'no-cache',
                            'Expires': '0'
                        }
                    )
            except Exception as e:
                return Response(status_code=503, content=f"Backend error: {e}")

        # WebSocket proxy
        @self.app.websocket("/instrument/{name}/ws")
        async def proxy_websocket(websocket: WebSocket, name: str):
            """Proxy WebSocket to instrument backends"""
            await websocket.accept()

            if name not in self.port_assignments:
                await websocket.close(code=1008, reason="Instrument not found")
                return

            port = self.port_assignments[name]['ws_port']
            backend_uri = f"ws://localhost:{port}/ws"
            print(f"Connecting to backend WebSocket: {backend_uri}")

            try:
                async with websockets.connect(backend_uri) as backend_ws:
                    print(f"Backend WebSocket connected: {backend_uri}")
                    # Bidirectional proxy
                    import asyncio

                    async def forward_to_backend():
                        try:
                            while True:
                                data = await websocket.receive_text()
                                await backend_ws.send(data)
                        except Exception as e:
                            pass  # Ignore errors, keep connection open

                    async def forward_to_client():
                        try:
                            async for message in backend_ws:
                                await websocket.send_text(message)
                        except Exception as e:
                            pass

                    # Run both tasks independently
                    task1 = asyncio.create_task(forward_to_backend())
                    task2 = asyncio.create_task(forward_to_client())

                    # Wait for EITHER task to complete
                    done, pending = await asyncio.wait([task1, task2], return_when=asyncio.FIRST_COMPLETED)

                    # If forward_to_client exits (backend disconnected), we're done
                    if task2 in done:
                        task1.cancel()
                    else:
                        # forward_to_backend died (browser closed), but backend still sending - keep listening
                        await task2
            except Exception as e:
                await websocket.close(code=1011, reason=f"Backend error: {e}")

    def _generate_html(self) -> str:
        """Generate grid layout HTML with iframes"""
        panel = self.config['panel']
        grid = panel['grid']
        instruments = panel['instruments']

        grid_style = f"""
            grid-template-columns: repeat({grid['columns']}, 1fr);
            grid-template-rows: repeat({grid['rows']}, 1fr);
            gap: {grid.get('gap', '10px')};
        """

        iframe_html = []
        for instr in instruments:
            pos = instr['position']
            span = instr['span']
            name = instr['name']
            ports = self.port_assignments[name]

            # Build proxied URL (all requests go through BenchView)
            instr_type = instr['type']

            # Add query params for multi-instance config
            params = [
                f"count={ports['count']}",
                f"layout={ports['layout'].lower()}",
                f"ws_port={name}"  # Pass instrument name for WebSocket proxy
            ]
            url = f"/instrument/{name}/?{'&'.join(params)}"

            iframe_style = f"""
                grid-column: {pos['col'] + 1} / span {span['cols']};
                grid-row: {pos['row'] + 1} / span {span['rows']};
            """

            iframe_html.append(f"""
                <iframe
                    id="instr-{name}"
                    src="{url}"
                    style="{iframe_style}"
                    frameborder="0">
                </iframe>
            """)

        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{panel['name']}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ height: 100%; width: 100%; overflow: hidden; }}
    body {{
      background: #0a0a0f;
      color: #e0e0e0;
      font-family: 'Courier New', 'Consolas', monospace;
      display: flex;
      flex-direction: column;
    }}
    #header {{
      background: linear-gradient(135deg, #1a1a2a 0%, #0a0a15 100%);
      border-bottom: 2px solid #2a2a40;
      padding: 10px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-shrink: 0;
    }}
    #header h1 {{
      font-size: 18px;
      color: #6c9bd1;
      text-transform: uppercase;
      letter-spacing: 2px;
    }}
    #description {{
      font-size: 12px;
      color: #888;
    }}
    #grid-container {{
      flex: 1;
      display: grid;
      padding: 10px;
      {grid_style}
    }}
    iframe {{
      width: 100%;
      height: 100%;
      border: 2px solid #2a2a40;
      border-radius: 8px;
      background: #0a0a15;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.6);
    }}
  </style>
</head>
<body>
  <div id="header">
    <div>
      <h1>{panel['name']}</h1>
      <div id="description">{panel.get('description', '')}</div>
    </div>
  </div>
  <div id="grid-container">
    {''.join(iframe_html)}
  </div>
  <script>
    // Replace hostname placeholders with actual hostname
    document.addEventListener('DOMContentLoaded', function() {{
      const hostname = window.location.hostname;
      const iframes = document.querySelectorAll('iframe');
      iframes.forEach(iframe => {{
        const src = iframe.getAttribute('src');
        iframe.setAttribute('src', src.replace('HOSTNAME_PLACEHOLDER', hostname));
      }});
    }});
  </script>
</body>
</html>
        """
        return html

    def _start_backends(self):
        """Start backend servers for each instrument"""
        virtual_dir = Path(__file__).parent.parent.parent

        for instr in self.config['panel']['instruments']:
            name = instr['name']
            instr_type = instr['type']
            ports = self.port_assignments[name]

            backend_dir = virtual_dir / instr_type / 'backend'
            server_script = backend_dir / 'server-multi.py'

            if not server_script.exists():
                print(f"Warning: No multi-instance backend found for {instr_type}: {server_script}")
                continue

            # Build command
            cmd = [
                'python3',
                str(server_script),
                '--scpi-port', str(ports['scpi_port']),
                '--http-port', str(ports['http_port']),
                '--count', str(ports['count']),
                '--layout', ports['layout']
            ]

            # Start backend process
            try:
                print(f"Starting: {name} ({instr_type}) on SCPI={ports['scpi_port']}, HTTP={ports['http_port']}")
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(backend_dir)
                )
                self.backend_processes.append((name, proc))
            except Exception as e:
                print(f"Error starting backend for {name}: {e}")

    def _cleanup_backends(self):
        """Terminate all backend processes"""
        print("\nStopping instrument backends...")
        for name, proc in self.backend_processes:
            try:
                proc.terminate()
                proc.wait(timeout=2)
                print(f"  Stopped: {name}")
            except:
                proc.kill()
                print(f"  Killed: {name}")

    def run(self, host: str = "0.0.0.0", port: int = 8200):
        """Start server and instrument backends"""
        # Write port assignments
        output_yaml = self._write_output_yaml()

        # Start instrument backends
        self._start_backends()

        # Give backends time to start
        print("\nWaiting for backends to start...")
        time.sleep(3)

        print(f"\nBenchView ready:")
        print(f"  Web UI:        http://{host}:{port}")
        print(f"  Config:        {self.config_path}")
        print(f"  Port map:      {output_yaml}")
        print(f"  Backends:      {len(self.backend_processes)}")
        print(f"\nAll instruments use 1-based indexing (N=1,2,3,4)")
        print(f"Query count with: INST:COUNT?")

        try:
            uvicorn.run(self.app, host=host, port=port, log_level="info")
        finally:
            self._cleanup_backends()


def main():
    """Entry point"""
    import argparse
    parser = argparse.ArgumentParser(description='BenchView - Virtual Instrument Grid Manager')
    parser.add_argument('config', help='YAML configuration file')
    parser.add_argument('--port', type=int, default=8200, help='Web UI port (default: 8200)')
    parser.add_argument('--host', default='0.0.0.0', help='Web UI host (default: 0.0.0.0)')
    args = parser.parse_args()

    if not Path(args.config).exists():
        print(f"Error: Config file not found: {args.config}")
        sys.exit(1)

    benchview = BenchView(args.config)
    benchview.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
