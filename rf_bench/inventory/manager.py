"""Instrument inventory manager."""

import os
import socket
import importlib
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import yaml


class Inventory:
    """Instrument inventory manager.

    Auto-loads from:
        1. $RF_BENCH_INVENTORY
        2. ~/.rf-bench/inventory.yaml
        3. ./inventory.yaml

    Example:
        >>> inv = Inventory()
        >>> sdg = inv.connect('sdg')
        >>> info = inv.get('ssa-main')
    """

    def __init__(self, path: Optional[str] = None):
        """Load inventory from YAML file.

        Args:
            path: Explicit path to inventory.yaml. If None, auto-discovers.
        """
        self.path = path or self._find_inventory()
        self.data = self._load()
        self.instruments = self.data.get('instruments', {})
        self.aliases = self.data.get('aliases', {})
        self.defaults = self.data.get('defaults', {})

    def _find_inventory(self) -> str:
        """Find inventory file in standard locations."""
        candidates = [
            os.environ.get('RF_BENCH_INVENTORY'),
            str(Path.home() / '.rf-bench' / 'inventory.yaml'),
            './inventory.yaml',
            str(Path(__file__).parent.parent.parent / 'inventory.yaml'),
        ]

        for path in candidates:
            if path and Path(path).exists():
                return path

        # No inventory found - return default location for creation
        return str(Path.home() / '.rf-bench' / 'inventory.yaml')

    def _load(self) -> Dict[str, Any]:
        """Load YAML inventory file."""
        path = Path(self.path)

        if not path.exists():
            # Start with empty inventory
            return {
                'version': 1,
                'instruments': {},
                'aliases': {},
                'defaults': {
                    'scpi_ports': [5025, 5024, 111],
                    'scpi_timeout': 1.0,
                    'discovery_enabled': True,
                    'auto_save_discovered': 'prompt',
                }
            }

        with open(path) as f:
            return yaml.safe_load(f) or {}

    def save(self):
        """Save inventory to YAML file."""
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w') as f:
            yaml.dump(self.data, f, default_flow_style=False, sort_keys=False)

    def resolve_alias(self, name: str) -> str:
        """Resolve alias to canonical instrument name.

        Args:
            name: Instrument name or alias

        Returns:
            Canonical instrument name
        """
        return self.aliases.get(name, name)

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """Get instrument info by name or alias.

        Args:
            name: Instrument name or alias

        Returns:
            Instrument info dict, or None if not found
        """
        name = self.resolve_alias(name)
        return self.instruments.get(name)

    def list(self, tags: Optional[List[str]] = None) -> List[str]:
        """List all instrument names.

        Args:
            tags: Optional tag filter (returns instruments with ANY of these tags)

        Returns:
            List of instrument names
        """
        names = list(self.instruments.keys())

        if tags:
            names = [
                name for name in names
                if any(tag in self.instruments[name].get('tags', []) for tag in tags)
            ]

        return sorted(names)

    def add(self, name: str, info: Dict[str, Any]):
        """Add or update instrument.

        Args:
            name: Instrument name (canonical, not alias)
            info: Instrument info dict
        """
        self.instruments[name] = info
        self.data['instruments'] = self.instruments

    def _update_last_seen(self, name: str):
        """Update last_seen timestamp for instrument."""
        name = self.resolve_alias(name)
        if name in self.instruments:
            self.instruments[name]['last_seen'] = datetime.utcnow().isoformat() + 'Z'
            self.save()

    def _import_driver(self, driver_path: str):
        """Import driver class dynamically.

        Args:
            driver_path: Full path like 'rf_bench.siglent.SSA3000X'

        Returns:
            Driver class
        """
        module_path, class_name = driver_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    def connect(self, name: str, **kwargs) -> Any:
        """Connect to instrument by name or alias.

        Args:
            name: Instrument name or alias
            **kwargs: Override connection parameters

        Returns:
            Connected instrument driver instance

        Raises:
            KeyError: Instrument not found in inventory
            ImportError: Driver module not found
            ConnectionError: Failed to connect

        Example:
            >>> inv = Inventory()
            >>> sdg = inv.connect('sdg')
            >>> ssa = inv.connect('ssa-main', port=5026)  # override port
        """
        info = self.get(name)

        if not info:
            # Instrument not in inventory - try discovery
            if self.defaults.get('discovery_enabled', True):
                print(f"Instrument '{name}' not in inventory. Running discovery...")
                discovered = self._discover_by_name(name)

                if discovered:
                    auto_save = self.defaults.get('auto_save_discovered', 'prompt')

                    if auto_save == 'prompt':
                        resp = input(f"Add '{name}' to inventory? [Y/n] ").strip().lower()
                        if resp in ['', 'y', 'yes']:
                            self.add(name, discovered)
                            self.save()
                            print(f"Added '{name}' to {self.path}")
                            info = discovered
                    elif auto_save == 'always':
                        self.add(name, discovered)
                        self.save()
                        info = discovered

            if not info:
                raise KeyError(f"Instrument '{name}' not found in inventory and discovery failed")

        # Import driver class
        driver_path = info.get('driver')
        if not driver_path:
            raise ValueError(f"Instrument '{name}' has no 'driver' field in inventory")

        DriverClass = self._import_driver(driver_path)

        # Build connection arguments
        conn = info.get('connection', {})
        protocol = conn.get('protocol')

        # Merge inventory params with kwargs overrides
        params = {}

        if protocol in ['scpi-tcp', 'scpi']:
            params['host'] = kwargs.get('host', conn.get('host'))
            params['port'] = kwargs.get('port', conn.get('port', 5025))
        elif protocol == 'hamlib':
            params['host'] = kwargs.get('host', conn.get('host', 'localhost'))
            params['port'] = kwargs.get('port', conn.get('port', 4532))
        elif protocol == 'serial':
            # Serial instruments typically need host SSH + device path
            # For now, just pass device if local, otherwise raise
            host = conn.get('host', 'localhost')
            if host in ['localhost', '127.0.0.1']:
                params['port'] = kwargs.get('port', conn.get('device'))
            else:
                raise NotImplementedError(
                    f"Remote serial not yet supported for {name} on {host}. "
                    "TODO: SSH tunnel support (Phase 2)"
                )
        elif protocol == 'libusb':
            # RTL-SDR and similar
            params['device_index'] = kwargs.get('device_index', conn.get('device_index', 0))
            params['serial'] = kwargs.get('serial', conn.get('serial'))
        elif protocol in ['websocket', 'websocket-tci']:
            params['host'] = kwargs.get('host', conn.get('host'))
            params['port'] = kwargs.get('port', conn.get('port'))
            if 'trx' in conn:
                params['trx'] = kwargs.get('trx', conn['trx'])
        elif protocol == 'json-tcp':
            # gpsd
            params['host'] = kwargs.get('host', conn.get('host', 'localhost'))
            params['port'] = kwargs.get('port', conn.get('port', 2947))
        else:
            raise ValueError(f"Unknown protocol '{protocol}' for instrument '{name}'")

        # Instantiate driver
        try:
            # Most drivers: DriverClass(host, port=...)
            # Some: DriverClass(device_index=...)
            # Figure out the signature
            inst = DriverClass(**params)

            # Update last_seen timestamp
            self._update_last_seen(name)

            return inst

        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to '{name}' ({info.get('type')}): {e}"
            ) from e

    def _discover_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Attempt to discover instrument by parsing name.

        Args:
            name: Instrument name (e.g., 'sdg', 'ssa-main', 'ic7300')

        Returns:
            Instrument info dict if found, else None
        """
        # Simple heuristic: check if name contains known type prefixes
        type_map = {
            'ssa': ('SSA3000X', 'rf_bench.siglent.SSA3000X', 5025),
            'sdg': ('SDG1062X', 'rf_bench.siglent.SDG1000X', 5025),
            'sds': ('SDS2504X', 'rf_bench.siglent.SDS2000X', 5025),
            'sdm': ('SDM3045X', 'rf_bench.siglent.SDM3000X', 5025),
            'spd': ('SPD3303X', 'rf_bench.siglent.SPD3303X', 5025),
            'ic7300': ('IC7300', 'rf_bench.icom.IC7300', 4532),
            'ic9700': ('IC9700', 'rf_bench.icom.IC9700', 4532),
        }

        for prefix, (inst_type, driver, port) in type_map.items():
            if name.lower().startswith(prefix):
                # Found a match - try network discovery
                discovered = self._discover_scpi(port)
                if discovered:
                    return {
                        'type': inst_type,
                        'driver': driver,
                        'connection': {
                            'protocol': 'hamlib' if 'ic' in prefix else 'scpi-tcp',
                            'host': discovered['host'],
                            'port': port,
                        },
                        'tags': ['discovered'],
                        'notes': f"Auto-discovered on {datetime.utcnow().strftime('%Y-%m-%d')}",
                    }

        return None

    def _discover_scpi(self, port: int = 5025) -> Optional[Dict[str, str]]:
        """Scan local network for SCPI instruments.

        Args:
            port: SCPI port to check

        Returns:
            Dict with 'host' and '*IDN?' response, or None
        """
        # Simple scan: check common IPs on the subnet
        # TODO: Full subnet scan in Phase 2

        import subprocess

        # Get local IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except:
            local_ip = "10.1.1.1"

        # Extract subnet
        subnet = '.'.join(local_ip.split('.')[:-1])

        # Scan common host IPs in the subnet
        for last_octet in range(50, 70):  # Common instrument range
            host = f"{subnet}.{last_octet}"

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                sock.connect((host, port))

                # Try *IDN?
                sock.sendall(b'*IDN?\n')
                resp = sock.recv(1024).decode().strip()
                sock.close()

                if resp and not resp.startswith('ERROR'):
                    return {'host': host, '*IDN?': resp}

            except:
                pass

        return None


# Module-level singleton for convenience
_inventory = None


def connect(name: str, **kwargs) -> Any:
    """Connect to instrument by name (convenience function).

    Uses global inventory singleton. Auto-loads on first call.

    Args:
        name: Instrument name or alias
        **kwargs: Override connection parameters

    Returns:
        Connected instrument driver instance

    Example:
        >>> from rf_bench import connect
        >>> sdg = connect('sdg')
        >>> ssa = connect('ssa-main', port=5026)
    """
    global _inventory

    if _inventory is None:
        _inventory = Inventory()

    return _inventory.connect(name, **kwargs)
