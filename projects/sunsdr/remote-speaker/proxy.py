#!/usr/bin/env python3
"""
TCI WebSocket proxy + HTTP server for remote-speaker.

Runs a local HTTP server that:
  - Serves remote_speaker.html at /
  - Proxies WebSocket connections at /ws to ExpertSDR3 TCI

Use this when loading remote_speaker.html directly as a file:// URL fails
(some browsers block ws:// connections to non-localhost from file:// pages).

Usage:
    python proxy.py --tci-host 192.168.1.x [--tci-port 50001] [--port 8080]

In the browser:
    http://localhost:8080/
    Then set Host=localhost, Port=8080 in the page.

Or open directly:
    http://localhost:8080/?host=localhost&port=8080

The proxy is completely transparent — to the HTML page it looks like a TCI
server.  All text and binary frames pass through unmodified in both directions.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from aiohttp import web, WSMsgType, ClientSession, ClientWebSocketResponse

log = logging.getLogger("proxy")
HERE = Path(__file__).parent


# ── WebSocket proxy handler ───────────────────────────────────────────────────

async def ws_proxy(request: web.Request) -> web.WebSocketResponse:
    tci_host = request.app["tci_host"]
    tci_port = request.app["tci_port"]
    tci_url  = f"ws://{tci_host}:{tci_port}"

    browser_ws = web.WebSocketResponse()
    await browser_ws.prepare(request)

    log.info("Browser connected from %s, opening TCI → %s", request.remote, tci_url)

    async with ClientSession() as session:
        try:
            async with session.ws_connect(tci_url) as tci_ws:
                log.info("TCI connected")

                async def browser_to_tci():
                    async for msg in browser_ws:
                        if msg.type == WSMsgType.TEXT:
                            await tci_ws.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await tci_ws.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                            break
                    await tci_ws.close()

                async def tci_to_browser():
                    async for msg in tci_ws:
                        if browser_ws.closed:
                            break
                        if msg.type == WSMsgType.TEXT:
                            await browser_ws.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await browser_ws.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                            break
                    if not browser_ws.closed:
                        await browser_ws.close()

                await asyncio.gather(browser_to_tci(), tci_to_browser())

        except Exception as exc:
            log.error("TCI connection failed: %s", exc)
            if not browser_ws.closed:
                await browser_ws.close(message=f"TCI error: {exc}".encode())

    log.info("Session closed")
    return browser_ws


# ── HTML file server ──────────────────────────────────────────────────────────

async def serve_html(request: web.Request) -> web.Response:
    html_path = HERE / "remote_speaker.html"
    if not html_path.exists():
        raise web.HTTPNotFound(reason="remote_speaker.html not found")
    return web.Response(
        body=html_path.read_bytes(),
        content_type="text/html",
        charset="utf-8",
    )


# ── app factory ───────────────────────────────────────────────────────────────

def make_app(tci_host: str, tci_port: int) -> web.Application:
    app = web.Application()
    app["tci_host"] = tci_host
    app["tci_port"] = tci_port
    app.router.add_get("/",   serve_html)
    app.router.add_get("/ws", ws_proxy)
    return app


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TCI WebSocket proxy + HTTP server for remote_speaker.html",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--tci-host", required=True,
                        help="ExpertSDR3 host IP or hostname")
    parser.add_argument("--tci-port", type=int, default=50001,
                        help="ExpertSDR3 TCI WebSocket port")
    parser.add_argument("--port", type=int, default=8080,
                        help="Local HTTP/WS port to listen on")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Local bind address (use 0.0.0.0 to expose on LAN)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    app = make_app(args.tci_host, args.tci_port)

    print(f"\n  TCI Remote Speaker Proxy")
    print(f"  TCI server : ws://{args.tci_host}:{args.tci_port}")
    print(f"  Proxy URL  : http://{args.host}:{args.port}/")
    print(f"\n  Open http://localhost:{args.port}/ in your browser.")
    print(f"  Set Host=localhost, Port={args.port} in the page.\n")

    web.run_app(app, host=args.host, port=args.port, print=lambda _: None)


if __name__ == "__main__":
    main()
