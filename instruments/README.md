# rf-bench-instruments

Instrument registry and discovery for rf-bench. Provides unified access to instruments across TCP/IP, USB serial, and GPIB connections.

## Features

- **Unified registry** — Single YAML file defines all lab instruments
- **Auto-discovery** — USB serial device scanning via VID:PID
- **Network scanning** — Find SCPI instruments by IP range
- **Multi-device support** — Handle multiple identical USB devices (e.g., 4 GPS receivers)
- **Dynamic connections** — Instruments can move between USB ports or get new DHCP addresses
- **GPIB support** — Framework ready for GPIB-Ethernet adapters (hardware pending)

## Installation

```bash
cd ~/Dropbox/build/rf-bench/instruments
pip install -e .
```

## Quick Start

### Using the Registry in Code

```python
from rf_bench.instruments import Registry

registry = Registry()

# Get any available GPS
gps = registry.get('gps')

# Get specific instrument by role
ssa = registry.get('spectrum-analyzer')
sdg = registry.get('signal-generator')

# Get USB device on specific port
load = registry.get('dc-load', serial='/dev/ttyUSB0')

# Get instrument by tag
ssa = registry.get('spectrum-analyzer', tag='calibrated')
```

### CLI Commands

List all registered instruments:
```bash
rf-bench-instruments list
```

Scan for USB serial devices:
```bash
rf-bench-instruments scan-usb
```

Scan network for SCPI instruments:
```bash
rf-bench-instruments scan-network 10.1.1.0/24
```

Scan and update registry (fix DHCP address changes):
```bash
rf-bench-instruments scan-network 10.1.1.0/24 --update
```

Scan and auto-add new instruments:
```bash
rf-bench-instruments scan-network 10.1.1.0/24 --auto-add
```

Test connection to specific instrument:
```bash
rf-bench-instruments test spectrum-analyzer
```

## Configuration

Instruments are defined in `~/.rf-bench/instruments.yaml`:

```yaml
instruments:
  - role: spectrum-analyzer
    name: SSA3032X Plus
    driver_class: rf_bench.siglent.SSA3000X
    tcp_ip: 10.1.1.60
    tcp_port: 5025
    tags: [bench, calibrated, primary]
    idn_signature: "Siglent Technologies,SSA3032X"
    location: "Main bench, right side"

  - role: gps
    name: NEO-6M GPS #1
    driver_class: rf_bench.gpsd.GPSD
    usb_vid: "1546"  # u-blox
    usb_pid: "01a6"
    baud_rate: 9600
    tags: [portable, primary-gps]
    location: "Portable kit"

  - role: dc-load
    name: Yertai ET5406A+
    driver_class: rf_bench.yertai.ET5406A
    usb_path: /dev/ttyUSB0
    baud_rate: 9600
    tags: [power, greybox]
    location: "greybox workstation"
```

### Connection Types

**TCP/IP instruments:**
- Set `tcp_ip` and `tcp_port`
- Most SCPI instruments use port 5025

**USB serial devices:**
- Set `usb_vid` and `usb_pid` for auto-discovery
- Or set `usb_path` for explicit port (e.g., /dev/ttyUSB0)
- Set `baud_rate` (default: 115200)

**GPIB instruments (future):**
- Set `gpib_address` (1-30)
- Set `gpib_adapter_ip` (KISS-488 Ethernet-GPIB adapter)

### Tags

Use tags to organize instruments:
- `bench`, `portable` — Location
- `calibrated` — Instruments with valid calibration
- `primary`, `backup` — Preference order
- `hf`, `vhf`, `uhf` — Frequency range

Get instruments by tag:
```python
ssa = registry.get('spectrum-analyzer', tag='calibrated')
gps = registry.get('gps', tag='primary-gps')
```

### Multiple Identical Devices

For multiple USB devices with the same VID:PID (e.g., 4 GPS receivers), list each separately:

```yaml
instruments:
  - role: gps
    name: NEO-6M GPS #1
    driver_class: rf_bench.gpsd.GPSD
    usb_vid: "1546"
    usb_pid: "01a6"
    tags: [primary-gps]

  - role: gps
    name: NEO-7M GPS #2
    driver_class: rf_bench.gpsd.GPSD
    usb_vid: "1546"
    usb_pid: "01a7"
    tags: [backup-gps]
```

The registry returns the first available match:
```python
# Returns first available GPS (primary if available, backup otherwise)
gps = registry.get('gps')

# Or get specific one by tag
gps = registry.get('gps', tag='primary-gps')
```

## Network Scanning

### Basic Scan

Find all SCPI instruments on the network:
```bash
rf-bench-instruments scan-network 10.1.1.0/24
```

Output:
```
Found 5 instrument(s):

IP:       10.1.1.55
Port:     5025
*IDN?:    Siglent Technologies,SDG1062X,SDG1XDAD2R0123,2.01.01.20R3

IP:       10.1.1.60
Port:     5025
*IDN?:    Siglent Technologies,SSA3032X,SSA3XDAD1R0234,1.3.7
```

### Update Existing Instruments

After DHCP gives instruments new addresses:
```bash
rf-bench-instruments scan-network 10.1.1.0/24 --update
```

The scanner matches by `idn_signature` and updates the `tcp_ip` field:
```
✓ Updated 2 instrument(s):
  SDG1062X: 10.1.1.55 → 10.1.1.57
  SSA3032X Plus: 10.1.1.60 → 10.1.1.62
```

### Auto-Add New Instruments

Automatically add newly discovered instruments:
```bash
rf-bench-instruments scan-network 10.1.1.0/24 --auto-add
```

New instruments are added with:
- `role: unknown` (you must edit this)
- `driver_class: NEEDS_DRIVER_CLASS` (you must set this)
- `tags: [auto-discovered]`
- Parsed manufacturer/model from *IDN?

Edit `~/.rf-bench/instruments.yaml` afterward to complete the configuration.

## USB Device Discovery

### List USB Serial Devices

```bash
rf-bench-instruments scan-usb
```

Output:
```
USB Serial Devices (3 detected)

Device:  /dev/ttyUSB0
VID:PID: 1a86:7523

Device:  /dev/ttyACM0
VID:PID: 1546:01a6

Device:  /dev/ttyACM1
VID:PID: 0483:5740
```

Use the VID:PID values in your `instruments.yaml`:

```yaml
- role: signal-generator
  name: MHS-5225A
  driver_class: rf_bench.koolertron.MHS5200A
  usb_vid: "1a86"
  usb_pid: "7523"
  baud_rate: 57600
```

## API Reference

### Registry

```python
from rf_bench.instruments import Registry

registry = Registry(config_path='~/.rf-bench/instruments.yaml')
```

**Methods:**

- `get(role, serial=None, tag=None)` — Get instrument driver instance
- `list_available(role=None)` — List all available instruments
- `list_usb_devices()` — List detected USB serial devices
- `invalidate_cache()` — Force USB device re-scan

### NetworkScanner

```python
from rf_bench.instruments.scanner import NetworkScanner

scanner = NetworkScanner()
```

**Methods:**

- `scan(network, port=5025, timeout=0.5, show_progress=True)` — Scan IP range
- `scan_ports(ip, ports=None, timeout=0.5)` — Scan multiple ports on one IP
- `identify(ip, port=5025, timeout=1.0)` — Quick *IDN? query
- `update_registry(instruments, registry_path=None, auto_add=False)` — Update YAML

## Usage Patterns

### Pattern 1: Get Any Available Instrument

```python
from rf_bench.instruments import Registry

registry = Registry()

# Get any spectrum analyzer
ssa = registry.get('spectrum-analyzer')

# Get any GPS
gps = registry.get('gps')
```

### Pattern 2: Multi-Instrument Measurement

```python
from rf_bench.instruments import Registry
from rf_bench.automation import MeasurementSequence

registry = Registry()

# Get instruments
sdg = registry.get('signal-generator')
ssa = registry.get('spectrum-analyzer')
dmm = registry.get('multimeter')

# Use in measurement sequence
seq = MeasurementSequence("Multi-Instrument Test")

@seq.step("Configure")
def setup(sdg, ssa):
    sdg.set_sine(1, freq_hz=1e6, level_dbm=-20)
    ssa.set_center_span(1e6, 100e3)

results = seq.run_steps(instruments={'sdg': sdg, 'ssa': ssa})
```

### Pattern 3: Portable vs Bench Instruments

```python
# Get bench instruments (high-end, calibrated)
ssa = registry.get('spectrum-analyzer', tag='bench')
sdg = registry.get('signal-generator', tag='bench')

# Get portable instruments (field use)
gps = registry.get('gps', tag='portable')
radio = registry.get('hf-radio', tag='portable')
```

### Pattern 4: Network Scan and Update

```python
from rf_bench.instruments.scanner import NetworkScanner

scanner = NetworkScanner()

# Scan lab network
instruments = scanner.scan('10.1.1.0/24')

# Update registry with new addresses
results = scanner.update_registry(instruments, auto_add=False)

print(f"Updated: {len(results['updated'])}")
print(f"Added: {len(results['added'])}")
```

## GPIB Support (Future)

When the KISS-488 Ethernet-GPIB adapter is installed:

```yaml
- role: vna
  name: HP 8712B
  driver_class: rf_bench.hp.HP8712B
  gpib_address: 16
  gpib_adapter_ip: 10.1.1.70
  tags: [vna, gpib, hpib]
  idn_signature: "HEWLETT-PACKARD,8712B"
```

Access the same way:
```python
vna = registry.get('vna')
```

## Requirements

- Python 3.8+
- pyyaml

## License

MIT
