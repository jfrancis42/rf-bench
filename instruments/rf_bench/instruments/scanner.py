"""
scanner.py — Network SCPI instrument discovery

Scans IP ranges for instruments responding to *IDN? queries.
Useful for:
  - Finding instruments after DHCP address change
  - Discovering new instruments on the network
  - Auditing lab inventory
"""

import socket
import ipaddress
import yaml
from pathlib import Path
from typing import List, Dict, Optional
from tqdm import tqdm


class NetworkScanner:
    """
    Scan network for SCPI instruments.

    Attempts TCP connection + *IDN? query on each IP.
    """

    def scan(
        self,
        network: str,
        port: int = 5025,
        timeout: float = 0.5,
        show_progress: bool = True
    ) -> List[Dict[str, str]]:
        """
        Scan network for SCPI instruments.

        Args:
            network: Network in CIDR notation (e.g., '10.1.1.0/24')
            port: SCPI port (default 5025)
            timeout: Connection timeout in seconds (default 0.5)
            show_progress: Show progress bar

        Returns:
            List of dicts with keys: ip, port, idn

        Example:

            scanner = NetworkScanner()
            instruments = scanner.scan('10.1.1.0/24')

            for inst in instruments:
                print(f"{inst['ip']}: {inst['idn']}")
        """
        # Parse network range
        net = ipaddress.ip_network(network, strict=False)
        hosts = list(net.hosts())

        results = []

        # Scan each host
        iterator = tqdm(hosts, desc="Scanning", disable=not show_progress)

        for ip in iterator:
            ip_str = str(ip)

            # Try to connect and query *IDN?
            idn = self._query_idn(ip_str, port, timeout)

            if idn:
                results.append({
                    'ip': ip_str,
                    'port': port,
                    'idn': idn
                })

                if show_progress:
                    iterator.set_postfix_str(f"Found: {ip_str}")

        return results

    def _query_idn(self, ip: str, port: int, timeout: float) -> str:
        """
        Attempt to connect to IP:port and query *IDN?.

        Returns IDN string or None if connection fails.
        """
        try:
            # Create socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)

            # Connect
            sock.connect((ip, port))

            # Send *IDN? command
            sock.sendall(b'*IDN?\n')

            # Read response (up to 1024 bytes)
            response = sock.recv(1024)

            sock.close()

            # Decode and strip whitespace
            idn = response.decode('utf-8', errors='ignore').strip()

            # Only return if we got a non-empty response
            if idn:
                return idn
            else:
                return None

        except (socket.timeout, socket.error, ConnectionRefusedError, OSError):
            return None

    def scan_ports(
        self,
        ip: str,
        ports: List[int] = None,
        timeout: float = 0.5
    ) -> List[Dict[str, any]]:
        """
        Scan multiple ports on a single IP.

        Args:
            ip: IP address to scan
            ports: List of ports (default: common SCPI ports)
            timeout: Connection timeout

        Returns:
            List of dicts with keys: port, idn

        Example:

            scanner = NetworkScanner()
            results = scanner.scan_ports('10.1.1.55')

            for r in results:
                print(f"Port {r['port']}: {r['idn']}")
        """
        if ports is None:
            # Common SCPI ports
            ports = [5025, 5024, 5023, 111, 1234, 4880, 8080]

        results = []

        for port in ports:
            idn = self._query_idn(ip, port, timeout)

            if idn:
                results.append({
                    'port': port,
                    'idn': idn
                })

        return results

    def identify(self, ip: str, port: int = 5025, timeout: float = 1.0) -> str:
        """
        Quick *IDN? query for a single instrument.

        Args:
            ip: IP address
            port: SCPI port (default 5025)
            timeout: Connection timeout

        Returns:
            IDN string or None

        Example:

            scanner = NetworkScanner()
            idn = scanner.identify('10.1.1.55')
            print(idn)  # "Siglent Technologies,SDG1062X,..."
        """
        return self._query_idn(ip, port, timeout)

    def update_registry(
        self,
        instruments: List[Dict[str, str]],
        registry_path: Optional[str] = None,
        auto_add: bool = False
    ) -> Dict[str, any]:
        """
        Update instruments.yaml with discovered instruments.

        Args:
            instruments: List of dicts from scan() (keys: ip, port, idn)
            registry_path: Path to instruments.yaml (default: ~/.rf-bench/instruments.yaml)
            auto_add: Automatically add new instruments (default: False)

        Returns:
            Dict with keys: updated (list), added (list), unchanged (list)

        Example:

            scanner = NetworkScanner()
            found = scanner.scan('10.1.1.0/24')
            results = scanner.update_registry(found, auto_add=True)

            print(f"Updated: {len(results['updated'])}")
            print(f"Added: {len(results['added'])}")
        """
        if registry_path is None:
            registry_path = Path.home() / '.rf-bench' / 'instruments.yaml'
        else:
            registry_path = Path(registry_path)

        # Load existing registry
        if registry_path.exists():
            with open(registry_path, 'r') as f:
                registry_data = yaml.safe_load(f)
        else:
            registry_data = {'instruments': []}

        if not registry_data or 'instruments' not in registry_data:
            registry_data = {'instruments': []}

        results = {
            'updated': [],
            'added': [],
            'unchanged': []
        }

        # Process each discovered instrument
        for inst in instruments:
            ip = inst['ip']
            port = inst['port']
            idn = inst['idn']

            # Try to match by IDN signature
            matched = False

            for reg_inst in registry_data['instruments']:
                # Match if IDN signature is present and matches
                if 'idn_signature' in reg_inst and reg_inst['idn_signature'] in idn:
                    # Update IP address if changed
                    if reg_inst.get('tcp_ip') != ip:
                        old_ip = reg_inst.get('tcp_ip', 'unknown')
                        reg_inst['tcp_ip'] = ip
                        reg_inst['tcp_port'] = port

                        results['updated'].append({
                            'name': reg_inst['name'],
                            'old_ip': old_ip,
                            'new_ip': ip,
                            'idn': idn
                        })
                    else:
                        results['unchanged'].append({
                            'name': reg_inst['name'],
                            'ip': ip
                        })

                    matched = True
                    break

            # If no match and auto_add is enabled, add as new instrument
            if not matched and auto_add:
                # Parse IDN to extract manufacturer and model
                idn_parts = idn.split(',')
                manufacturer = idn_parts[0] if len(idn_parts) > 0 else 'Unknown'
                model = idn_parts[1] if len(idn_parts) > 1 else 'Unknown'

                # Create new instrument entry
                new_instrument = {
                    'role': 'unknown',  # User must set this
                    'name': f'{manufacturer} {model}',
                    'driver_class': 'NEEDS_DRIVER_CLASS',  # User must set this
                    'tcp_ip': ip,
                    'tcp_port': port,
                    'tags': ['auto-discovered'],
                    'idn_signature': idn,
                    'location': 'Unknown'
                }

                registry_data['instruments'].append(new_instrument)

                results['added'].append({
                    'name': new_instrument['name'],
                    'ip': ip,
                    'idn': idn
                })

        # Write updated registry
        with open(registry_path, 'w') as f:
            yaml.dump(registry_data, f, default_flow_style=False, sort_keys=False)

        return results
