#!/usr/bin/env python3
"""
RF/Signal Relay Router

Software-defined N×M RF/signal routing matrix. Controls an XL9535 16-bit I2C
relay board (via Bus Pirate) to connect any of N sources to any of M destinations
under full software control. Eliminates manual cable changes between measurements.

Usage:
    python relay_router.py --connect SRC DST [options]
    python relay_router.py --disconnect SRC [options]
    python relay_router.py --all-off [options]
    python relay_router.py --status [options]
    python relay_router.py --list [options]
    python relay_router.py --ping [options]

Options:
    --bp PORT          Bus Pirate port (default /dev/ttyUSB1)
    --addr ADDR        XL9535 I2C address (default 0x20)
    --config FILE      Router config JSON (default: bench-router.json in script dir)
    --force            Allow connecting even if destination already has a source
    --quiet            Suppress output

Examples:
    python relay_router.py --connect antenna-hf ssa-in
    python relay_router.py --connect ssa-tg ic7300
    python relay_router.py --status
    python relay_router.py --all-off
"""

import argparse
import json
import os
import sys
import time

DEFAULT_BP      = "/dev/ttyUSB1"
DEFAULT_ADDR    = 0x20
DEFAULT_CONFIG  = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "bench-router.json")
STATE_FILE      = os.path.expanduser("~/.relay_router_state.json")

# ── path bootstrap (allows running directly without pip install) ──────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'rf-bench'))

from rf_bench.buspirate import BusPirate
from rf_bench.relay import XL9535


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_state():
    """Load persisted connection state from disk. Returns {} if absent/corrupt."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state):
    """Persist connection state to disk."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _load_config(path):
    """Load and validate router config JSON."""
    with open(path) as f:
        cfg = json.load(f)
    for key in ("sources", "destinations"):
        if key not in cfg:
            raise ValueError(f"Config missing '{key}' section")
    for name, entry in cfg["sources"].items():
        if "relay" not in entry:
            raise ValueError(f"Source '{name}' missing 'relay' field")
    for name, entry in cfg["destinations"].items():
        if "relay" not in entry:
            raise ValueError(f"Destination '{name}' missing 'relay' field")
    return cfg


# ── SignalRouter class ─────────────────────────────────────────────────────────

class SignalRouter:
    """
    Software-defined N×M signal routing matrix.

    Uses an XL9535 16-bit I2C relay board (via Bus Pirate) to connect any
    configured source to any configured destination. Connection state is
    persisted to ~/.relay_router_state.json so --status works across invocations.

    Parameters
    ----------
    bp : BusPirate
        Bus Pirate instance with I2C already configured (100 kHz, pullups enabled).
    config_file : str
        Path to the router configuration JSON file.
    i2c_addr : int
        7-bit I2C address of the XL9535 (default 0x20).
    """

    def __init__(self, bp, config_file=DEFAULT_CONFIG, i2c_addr=DEFAULT_ADDR):
        self._bp   = bp
        self._cfg  = _load_config(config_file)
        self._rl   = XL9535(bp, i2c_addr=i2c_addr, active_high=True, num_relays=16)
        # Connection state: src_name → dst_name (or None if only src is hot)
        # and dst_name → src_name (or None if only dst is hot)
        self._connections = _load_state()

    # ── public API ────────────────────────────────────────────────────────────

    def connect(self, src_name, dst_name, force=False):
        """
        Connect source *src_name* to destination *dst_name*.

        With exclusive_sources=True (default), any previously connected source
        for *dst_name* is disconnected first.  With exclusive_destinations=True
        (default), any previously connected destination for *src_name* is
        disconnected first.

        Parameters
        ----------
        src_name : str
            Name of the source as defined in the config file.
        dst_name : str
            Name of the destination as defined in the config file.
        force : bool
            If True, suppress exclusivity checks (allow parallel connections).
        """
        src_entry = self._get_source(src_name)
        dst_entry = self._get_destination(dst_name)

        exc_src = self._cfg.get("exclusive_sources", True)
        exc_dst = self._cfg.get("exclusive_destinations", True)

        if not force:
            # Disconnect any existing source that is connected to this destination
            if exc_src:
                prev_src = self._connections.get(f"dst:{dst_name}")
                if prev_src and prev_src != src_name:
                    self._open_source_relay(prev_src)
                    del self._connections[f"dst:{dst_name}"]
                    self._connections.pop(f"src:{prev_src}", None)

            # Disconnect any existing destination this source is wired to
            if exc_dst:
                prev_dst = self._connections.get(f"src:{src_name}")
                if prev_dst and prev_dst != dst_name:
                    self._open_destination_relay(prev_dst)
                    del self._connections[f"src:{src_name}"]
                    self._connections.pop(f"dst:{prev_dst}", None)

        # Close both relays
        self._rl.set(src_entry["relay"], True)
        self._rl.set(dst_entry["relay"], True)

        # Record connection
        self._connections[f"src:{src_name}"] = dst_name
        self._connections[f"dst:{dst_name}"] = src_name
        _save_state(self._connections)

    def disconnect_source(self, src_name):
        """
        Open the source relay for *src_name* and remove it from connection state.

        The corresponding destination relay is left as-is (since another source
        could be routed to it).
        """
        self._get_source(src_name)  # validate name
        self._open_source_relay(src_name)
        dst_name = self._connections.pop(f"src:{src_name}", None)
        if dst_name:
            # If the destination's back-reference still points here, clear it
            if self._connections.get(f"dst:{dst_name}") == src_name:
                del self._connections[f"dst:{dst_name}"]
        _save_state(self._connections)

    def disconnect_destination(self, dst_name):
        """
        Open the destination relay for *dst_name* and remove from state.
        """
        self._get_destination(dst_name)
        self._open_destination_relay(dst_name)
        src_name = self._connections.pop(f"dst:{dst_name}", None)
        if src_name:
            if self._connections.get(f"src:{src_name}") == dst_name:
                del self._connections[f"src:{src_name}"]
        _save_state(self._connections)

    def all_off(self):
        """Open all relays and clear persisted state."""
        self._rl.all_off()
        self._connections.clear()
        _save_state(self._connections)

    def status(self):
        """
        Return the current connection state as a dict.

        Returns
        -------
        dict with keys:
            "connections" : list of {"source": name, "destination": name}
            "sources_active" : list of source names with closed relays
            "destinations_active" : list of destination names with closed relays
        """
        connections = []
        seen_pairs = set()
        for key, val in self._connections.items():
            if key.startswith("src:"):
                src = key[4:]
                dst = val
                pair = (src, dst)
                if pair not in seen_pairs:
                    connections.append({"source": src, "destination": dst})
                    seen_pairs.add(pair)

        src_active  = [k[4:] for k in self._connections if k.startswith("src:")]
        dst_active  = [k[4:] for k in self._connections if k.startswith("dst:")]

        return {
            "connections":          connections,
            "sources_active":       src_active,
            "destinations_active":  dst_active,
        }

    def ping(self, quiet=False):
        """
        Self-test: cycle each relay on then off, one at a time.

        Does NOT save state (ends with all relays off).
        """
        all_relays = []
        for name, entry in self._cfg["sources"].items():
            all_relays.append((f"src:{name}", entry["relay"],
                               entry.get("description", "")))
        for name, entry in self._cfg["destinations"].items():
            all_relays.append((f"dst:{name}", entry["relay"],
                               entry.get("description", "")))

        all_relays.sort(key=lambda x: x[1])  # sort by relay number

        if not quiet:
            print(f"Ping: cycling {len(all_relays)} relays...")

        for label, relay_num, desc in all_relays:
            if not quiet:
                print(f"  relay {relay_num:2d}  {label:30s}  {desc}")
            self._rl.set(relay_num, True)
            time.sleep(0.1)
            self._rl.set(relay_num, False)
            time.sleep(0.05)

        if not quiet:
            print("Ping complete — all relays open.")

    def close(self):
        """Close the XL9535 context (opens all relays)."""
        self._rl.all_off()

    # ── internal helpers ──────────────────────────────────────────────────────

    def _get_source(self, name):
        if name not in self._cfg["sources"]:
            avail = ", ".join(self._cfg["sources"])
            raise KeyError(f"Unknown source '{name}'. Available: {avail}")
        return self._cfg["sources"][name]

    def _get_destination(self, name):
        if name not in self._cfg["destinations"]:
            avail = ", ".join(self._cfg["destinations"])
            raise KeyError(f"Unknown destination '{name}'. Available: {avail}")
        return self._cfg["destinations"][name]

    def _open_source_relay(self, src_name):
        if src_name in self._cfg["sources"]:
            self._rl.set(self._cfg["sources"][src_name]["relay"], False)

    def _open_destination_relay(self, dst_name):
        if dst_name in self._cfg["destinations"]:
            self._rl.set(self._cfg["destinations"][dst_name]["relay"], False)

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_status(router, cfg, quiet):
    if quiet:
        return
    st = router.status()
    print(f"Router: {cfg.get('name', '(unnamed)')}")
    if not st["connections"]:
        print("  No active connections.")
    else:
        for conn in st["connections"]:
            src_desc = cfg["sources"].get(conn["source"], {}).get("description", "")
            dst_desc = cfg["destinations"].get(conn["destination"], {}).get("description", "")
            print(f"  {conn['source']:20s}  →  {conn['destination']:20s}"
                  f"   ({src_desc} → {dst_desc})")


def _print_list(cfg):
    print(f"Router: {cfg.get('name', '(unnamed)')}")
    print(f"\nSources ({len(cfg['sources'])}):")
    for name, entry in cfg["sources"].items():
        desc = entry.get("description", "")
        print(f"  relay {entry['relay']:2d}  {name:20s}  {desc}")
    print(f"\nDestinations ({len(cfg['destinations'])}):")
    for name, entry in cfg["destinations"].items():
        desc = entry.get("description", "")
        print(f"  relay {entry['relay']:2d}  {name:20s}  {desc}")
    exc_src = cfg.get("exclusive_sources", True)
    exc_dst = cfg.get("exclusive_destinations", True)
    print(f"\nexclusive_sources={exc_src}  exclusive_destinations={exc_dst}")


def main():
    ap = argparse.ArgumentParser(
        description="Software-defined N×M relay routing matrix",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python relay_router.py --connect antenna-hf ssa-in
  python relay_router.py --connect ssa-tg ic7300
  python relay_router.py --disconnect antenna-hf
  python relay_router.py --status
  python relay_router.py --list
  python relay_router.py --all-off
  python relay_router.py --ping
""")

    # Mutually-exclusive actions
    action = ap.add_mutually_exclusive_group(required=True)
    action.add_argument("--connect",     nargs=2, metavar=("SRC", "DST"),
                        help="Connect source to destination")
    action.add_argument("--disconnect",  metavar="SRC",
                        help="Open source relay (disconnect source)")
    action.add_argument("--all-off",     action="store_true",
                        help="Open all relays")
    action.add_argument("--status",      action="store_true",
                        help="Show current connections")
    action.add_argument("--list",        action="store_true",
                        help="List all configured sources and destinations")
    action.add_argument("--ping",        action="store_true",
                        help="Cycle all relays as self-test")

    ap.add_argument("--bp",     default=DEFAULT_BP,
                    help=f"Bus Pirate port (default {DEFAULT_BP})")
    ap.add_argument("--addr",   default=DEFAULT_ADDR, type=lambda x: int(x, 0),
                    help=f"XL9535 I2C address (default 0x{DEFAULT_ADDR:02X})")
    ap.add_argument("--config", default=DEFAULT_CONFIG, metavar="FILE",
                    help="Router config JSON (default: bench-router.json)")
    ap.add_argument("--force",  action="store_true",
                    help="Allow connecting even if destination already has a source")
    ap.add_argument("--quiet",  action="store_true",
                    help="Suppress output")

    args = ap.parse_args()

    # --list and --status for status-only can be handled without hardware if
    # there is no active hardware.  But for simplicity we always open the Bus
    # Pirate so that relay state can be synchronised.

    try:
        cfg = _load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error loading config '{args.config}': {e}", file=sys.stderr)
        sys.exit(1)

    if args.list:
        _print_list(cfg)
        return

    if args.status:
        # Status can be served from persisted state without touching hardware
        connections = _load_state()

        class _FakeRouter:
            def __init__(self):
                self._connections = connections
            def status(self):
                conns = []
                seen = set()
                for key, val in self._connections.items():
                    if key.startswith("src:"):
                        pair = (key[4:], val)
                        if pair not in seen:
                            conns.append({"source": key[4:], "destination": val})
                            seen.add(pair)
                return {"connections": conns,
                        "sources_active":      [k[4:] for k in self._connections if k.startswith("src:")],
                        "destinations_active": [k[4:] for k in self._connections if k.startswith("dst:")]}

        _print_status(_FakeRouter(), cfg, args.quiet)
        return

    # All other actions require hardware
    try:
        with BusPirate(args.bp) as bp:
            bp.set_pullups(True)
            bp.i2c_configure(speed_hz=100_000)

            with SignalRouter(bp, config_file=args.config,
                              i2c_addr=args.addr) as router:

                if args.connect:
                    src, dst = args.connect
                    try:
                        router.connect(src, dst, force=args.force)
                    except KeyError as e:
                        print(f"Error: {e}", file=sys.stderr)
                        sys.exit(1)
                    if not args.quiet:
                        print(f"Connected: {src}  →  {dst}")
                        _print_status(router, cfg, quiet=False)

                elif args.disconnect:
                    try:
                        router.disconnect_source(args.disconnect)
                    except KeyError as e:
                        print(f"Error: {e}", file=sys.stderr)
                        sys.exit(1)
                    if not args.quiet:
                        print(f"Disconnected source: {args.disconnect}")

                elif args.all_off:
                    router.all_off()
                    if not args.quiet:
                        print("All relays open.")

                elif args.ping:
                    router.ping(quiet=args.quiet)

            bp.i2c_exit()

    except Exception as e:
        print(f"Hardware error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
