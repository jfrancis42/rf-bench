"""
registry.py — Instrument discovery and connection management

Handles:
  - TCP/IP SCPI instruments (static IP)
  - USB serial devices (auto-discovery via VID:PID)
  - GPIB instruments (via Ethernet-GPIB adapter, when available)
  - Virtual instruments (dynamic port assignment via BenchView)
"""

import os
import yaml
import glob
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


class InstrumentNotFoundError(Exception):
    """Raised when requested instrument is not available."""
    pass


@dataclass
class InstrumentConfig:
    """Configuration for a single instrument."""

    # Identity
    role: str                   # e.g. 'signal-generator', 'spectrum-analyzer', 'gps'
    name: str                   # User-friendly name
    driver_class: str           # e.g. 'rf_bench.siglent.SDG1000X'

    # Connection (one of these is set)
    tcp_ip: Optional[str] = None         # IP address for TCP/SCPI
    tcp_port: int = 5025                 # Port for TCP/SCPI
    usb_vid: Optional[str] = None        # USB vendor ID (hex, e.g. '1a86')
    usb_pid: Optional[str] = None        # USB product ID (hex, e.g. '7523')
    usb_path: Optional[str] = None       # Explicit serial port (e.g. /dev/ttyUSB0)
    baud_rate: int = 115200              # Serial baud rate
    gpib_address: Optional[int] = None   # GPIB primary address (1-30)
    gpib_adapter_ip: Optional[str] = None  # KISS-488 adapter IP

    # Metadata
    tags: List[str] = field(default_factory=list)  # e.g. ['bench', 'portable', 'calibrated']
    idn_signature: Optional[str] = None  # Expected *IDN? response (substring match)
    location: Optional[str] = None       # Physical location note

    def connection_type(self) -> str:
        """Return connection type: 'tcp', 'usb', 'gpib', or 'unknown'."""
        if self.tcp_ip:
            return 'tcp'
        elif self.usb_vid or self.usb_path:
            return 'usb'
        elif self.gpib_address is not None:
            return 'gpib'
        else:
            return 'unknown'


class Registry:
    """
    Instrument registry with auto-discovery.

    Loads instrument definitions from ~/.rf-bench/instruments.yaml and
    matches them to available hardware.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize registry.

        Args:
            config_path: Path to instruments.yaml (default: ~/.rf-bench/instruments.yaml)
        """
        if config_path is None:
            config_path = Path.home() / '.rf-bench' / 'instruments.yaml'

        self.config_path = Path(config_path)
        self.instruments: Dict[str, InstrumentConfig] = {}
        self._usb_device_cache: Optional[List[Dict[str, str]]] = None

        # Load instrument definitions
        if self.config_path.exists():
            self._load_config()

    def _load_config(self):
        """Load instrument definitions from YAML."""
        with open(self.config_path, 'r') as f:
            data = yaml.safe_load(f)

        if not data or 'instruments' not in data:
            return

        for item in data['instruments']:
            config = InstrumentConfig(
                role=item['role'],
                name=item['name'],
                driver_class=item['driver_class'],
                tcp_ip=item.get('tcp_ip'),
                tcp_port=item.get('tcp_port', 5025),
                usb_vid=item.get('usb_vid'),
                usb_pid=item.get('usb_pid'),
                usb_path=item.get('usb_path'),
                baud_rate=item.get('baud_rate', 115200),
                gpib_address=item.get('gpib_address'),
                gpib_adapter_ip=item.get('gpib_adapter_ip'),
                tags=item.get('tags', []),
                idn_signature=item.get('idn_signature'),
                location=item.get('location')
            )

            # Register by role (multiple instruments can share a role)
            if config.role not in self.instruments:
                self.instruments[config.role] = []
            self.instruments[config.role].append(config)

    def _scan_usb_devices(self) -> List[Dict[str, str]]:
        """
        Scan /dev/tty* for USB serial devices.

        Returns list of dicts with keys: 'path', 'vid', 'pid'

        Uses /sys/class/tty/*/device/../uevent to read VID:PID.
        """
        if self._usb_device_cache is not None:
            return self._usb_device_cache

        devices = []

        # Scan all tty devices
        tty_paths = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*')

        for tty_path in tty_paths:
            tty_name = os.path.basename(tty_path)

            # Read uevent file to get VID:PID
            uevent_path = f'/sys/class/tty/{tty_name}/device/../uevent'

            if not os.path.exists(uevent_path):
                # Try alternative path (for ACM devices)
                uevent_path = f'/sys/class/tty/{tty_name}/device/../../uevent'

            if not os.path.exists(uevent_path):
                continue

            try:
                with open(uevent_path, 'r') as f:
                    uevent_data = f.read()

                # Parse PRODUCT=vid/pid/version line
                vid = None
                pid = None

                for line in uevent_data.splitlines():
                    if line.startswith('PRODUCT='):
                        parts = line.split('=')[1].split('/')
                        if len(parts) >= 2:
                            vid = parts[0]
                            pid = parts[1]
                            break

                if vid and pid:
                    devices.append({
                        'path': tty_path,
                        'vid': vid,
                        'pid': pid
                    })

            except (IOError, OSError):
                pass

        self._usb_device_cache = devices
        return devices

    def _match_usb_device(self, config: InstrumentConfig) -> Optional[str]:
        """
        Find USB device matching the config.

        Returns device path (/dev/ttyUSB*) or None.
        """
        # If explicit path is set, use it
        if config.usb_path:
            if os.path.exists(config.usb_path):
                return config.usb_path
            else:
                return None

        # Otherwise, scan for VID:PID match
        if not config.usb_vid or not config.usb_pid:
            return None

        devices = self._scan_usb_devices()

        for dev in devices:
            if dev['vid'] == config.usb_vid and dev['pid'] == config.usb_pid:
                return dev['path']

        return None

    def get(self, role: str, serial: Optional[str] = None, tag: Optional[str] = None) -> Any:
        """
        Get instrument driver instance by role.

        Args:
            role: Instrument role (e.g. 'gps', 'signal-generator')
            serial: Optional serial port path for USB devices
            tag: Optional tag filter (e.g. 'calibrated', 'portable')

        Returns:
            Instrument driver instance (connected and ready)

        Raises:
            InstrumentNotFoundError: If no matching instrument is available

        Example:

            # Get any GPS
            gps = registry.get('gps')

            # Get GPS on specific port
            gps = registry.get('gps', serial='/dev/ttyUSB0')

            # Get calibrated spectrum analyzer
            ssa = registry.get('spectrum-analyzer', tag='calibrated')
        """
        if role not in self.instruments:
            raise InstrumentNotFoundError(f"No instruments with role '{role}' in registry")

        candidates = self.instruments[role]

        # Filter by tag if specified
        if tag:
            candidates = [c for c in candidates if tag in c.tags]

        # Filter by serial port if specified
        if serial:
            candidates = [c for c in candidates if c.usb_path == serial or c.connection_type() != 'usb']

        if not candidates:
            raise InstrumentNotFoundError(
                f"No matching instruments for role='{role}', serial={serial}, tag={tag}"
            )

        # Try each candidate until one connects
        for config in candidates:
            try:
                driver = self._connect(config)
                if driver:
                    return driver
            except Exception:
                continue

        raise InstrumentNotFoundError(
            f"Could not connect to any instrument with role '{role}'"
        )

    def _connect(self, config: InstrumentConfig) -> Any:
        """
        Instantiate and connect to instrument.

        Returns driver instance or None.
        """
        # Import driver class
        module_path, class_name = config.driver_class.rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        driver_class = getattr(module, class_name)

        # Connect based on type
        conn_type = config.connection_type()

        if conn_type == 'tcp':
            # TCP/IP SCPI instrument
            return driver_class(host=config.tcp_ip, port=config.tcp_port)

        elif conn_type == 'usb':
            # USB serial device
            device_path = self._match_usb_device(config)

            if not device_path:
                return None

            # Most USB drivers take device path and baud rate
            return driver_class(device=device_path, baud=config.baud_rate)

        elif conn_type == 'gpib':
            # GPIB instrument (via Ethernet-GPIB adapter)
            if not config.gpib_adapter_ip:
                return None

            # GPIB drivers take adapter IP and GPIB address
            return driver_class(
                adapter_ip=config.gpib_adapter_ip,
                gpib_address=config.gpib_address
            )

        else:
            return None

    def list_available(self, role: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all available instruments.

        Args:
            role: Optional role filter

        Returns:
            List of dicts with keys: role, name, connection_type, connected, location
        """
        results = []

        roles_to_check = [role] if role else self.instruments.keys()

        for r in roles_to_check:
            if r not in self.instruments:
                continue

            for config in self.instruments[r]:
                conn_type = config.connection_type()

                # Check if device is present
                connected = False

                if conn_type == 'tcp':
                    # For TCP, assume available (could ping but that's slow)
                    connected = True

                elif conn_type == 'usb':
                    device_path = self._match_usb_device(config)
                    connected = device_path is not None

                elif conn_type == 'gpib':
                    # Can't check without hardware
                    connected = False

                results.append({
                    'role': config.role,
                    'name': config.name,
                    'connection_type': conn_type,
                    'connected': connected,
                    'location': config.location or 'Unknown',
                    'tags': config.tags
                })

        return results

    def list_usb_devices(self) -> List[Dict[str, str]]:
        """
        List all detected USB serial devices.

        Returns:
            List of dicts with keys: path, vid, pid

        Useful for discovering new devices to add to the registry.
        """
        return self._scan_usb_devices()

    def invalidate_cache(self):
        """Invalidate USB device cache (force re-scan on next access)."""
        self._usb_device_cache = None
