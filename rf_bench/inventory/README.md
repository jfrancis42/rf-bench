# Instrument Inventory System

Centralized connection management for all rf-bench instruments.

## Quick Start

```python
from rf_bench import connect

sdg = connect('sdg')
ssa = connect('ssa-main')
```

That's it. The inventory system:
1. Auto-loads `inventory.yaml` from standard locations
2. Looks up connection info (IP, port, protocol)
3. Imports the correct driver
4. Connects and returns a ready-to-use instrument instance
5. Updates `last_seen` timestamp

## Inventory File Locations

The inventory system searches for `inventory.yaml` in this order:

1. `$RF_BENCH_INVENTORY` (environment variable)
2. `~/.rf-bench/inventory.yaml` (user config)
3. `./inventory.yaml` (project local)
4. `~/Dropbox/build/rf-bench/inventory.yaml` (repo default)

The first file found is used.

## Creating Your Inventory

Copy the example:
```bash
cp inventory.example.yaml ~/.rf-bench/inventory.yaml
```

Edit with your instrument IPs:
```yaml
instruments:
  ssa-main:
    type: SSA3000X
    driver: rf_bench.siglent.SSA3000X
    connection:
      protocol: scpi-tcp
      host: 10.1.1.60
      port: 5025
    location: "Main bench, left side"
    calibration:
      last: 2026-01-15
      due: 2027-01-15
      notes: "Factory cal cert #12345"
    tags: [spectrum, rf, calibrated]

aliases:
  ssa: ssa-main
```

## Basic Usage

### Connect by name or alias
```python
from rf_bench import connect

# By alias (short name)
sdg = connect('sdg')
sdg.set_waveform(1, 'sine', 1e6, 1.0)

# By canonical name
ssa = connect('ssa-main')
trace = ssa.get_trace()

# Override connection parameters
dmm = connect('sdm', port=5026)
```

### List instruments
```python
from rf_bench.inventory import Inventory

inv = Inventory()

# List all
for name in inv.list():
    print(name)

# List by tag
for name in inv.list(tags=['calibrated']):
    info = inv.get(name)
    print(f"{name}: cal due {info['calibration']['due']}")
```

### Get instrument info
```python
from rf_bench.inventory import Inventory

inv = Inventory()
info = inv.get('ssa-main')

print(f"Type: {info['type']}")
print(f"Host: {info['connection']['host']}")
print(f"Last seen: {info['last_seen']}")
print(f"Cal due: {info['calibration']['due']}")
```

## Auto-Discovery

If you try to connect to an instrument not in your inventory, the system will attempt network discovery:

```python
from rf_bench import connect

# 'new-sdg' not in inventory.yaml
sdg = connect('new-sdg')
# Output:
#   Instrument 'new-sdg' not in inventory. Running discovery...
#   Found SDG1062X at 10.1.1.51
#   Add 'new-sdg' to inventory? [Y/n]
```

Discovery behavior is controlled by `defaults` in `inventory.yaml`:
```yaml
defaults:
  discovery_enabled: true
  auto_save_discovered: prompt  # prompt, always, never
```

## Calibration Tracking

Track calibration dates in the inventory:
```yaml
instruments:
  ssa-main:
    calibration:
      last: 2026-01-15
      due: 2027-01-15
      notes: "Factory cal cert #12345"
```

Query in code:
```python
inv = Inventory()
info = inv.get('ssa-main')

last = info['calibration']['last']
due = info['calibration']['due']
notes = info['calibration']['notes']

# Check if cal is due
from datetime import datetime
if due and datetime.fromisoformat(due) < datetime.now():
    print(f"WARNING: {name} calibration is overdue!")
```

## Supported Protocols

### SCPI over TCP (most Siglent instruments)
```yaml
connection:
  protocol: scpi-tcp
  host: 10.1.1.60
  port: 5025
```

### Hamlib rigctld (Icom/Yaesu radios)
```yaml
connection:
  protocol: hamlib
  host: 10.1.1.52
  port: 4532
  rigctld_args: "-m 3073 -r /dev/ttyUSB0 -s 115200"
```

### WebSocket (KiwiSDR, SunSDR)
```yaml
connection:
  protocol: websocket
  host: 192.168.1.100
  port: 8073
```

### WebSocket TCI (SunSDR/ExpertSDR3)
```yaml
connection:
  protocol: websocket-tci
  host: 10.1.1.54
  port: 50001
  trx: 0  # receiver index
```

### libusb (RTL-SDR)
```yaml
connection:
  protocol: libusb
  host: 10.1.1.52
  serial: "00000001"
  device_index: 0
```

### JSON over TCP (gpsd)
```yaml
connection:
  protocol: json-tcp
  host: localhost
  port: 2947
```

### Serial (future - Phase 2)
```yaml
connection:
  protocol: serial
  host: 10.1.0.16
  device: /dev/ttyUSB0
  baud: 9600
  serial: "5461234567"
```

## Tags

Organize instruments with tags:
```yaml
instruments:
  ssa-main:
    tags: [spectrum, rf, calibrated, bench-1]

  ic7300-hf:
    tags: [radio, hf, transceiver]
```

Query by tag:
```python
inv = Inventory()

# All calibrated instruments
for name in inv.list(tags=['calibrated']):
    ...

# All radios
for name in inv.list(tags=['radio']):
    ...
```

## Multi-Lab Setup

Each lab/workstation can have its own inventory:

**Lab 1:** `~/.rf-bench/inventory.yaml`
```yaml
instruments:
  ssa-main:
    connection:
      host: 10.1.1.60
```

**Lab 2:** `~/.rf-bench/inventory.yaml`
```yaml
instruments:
  ssa-main:
    connection:
      host: 192.168.1.60
```

Same code works in both locations:
```python
from rf_bench import connect
ssa = connect('ssa')  # Connects to correct IP for this lab
```

## Environment Variable

Override inventory location:
```bash
export RF_BENCH_INVENTORY=/path/to/my-lab-inventory.yaml
python my_script.py
```

## Programmatic Inventory Management

### Add instrument
```python
from rf_bench.inventory import Inventory

inv = Inventory()

inv.add('new-dmm', {
    'type': 'SDM3045X',
    'driver': 'rf_bench.siglent.SDM3000X',
    'connection': {
        'protocol': 'scpi-tcp',
        'host': '10.1.1.65',
        'port': 5025,
    },
    'tags': ['dmm', 'new'],
})

inv.save()
```

### Update calibration
```python
inv = Inventory()
info = inv.get('ssa-main')
info['calibration']['last'] = '2026-06-15'
info['calibration']['due'] = '2027-06-15'
inv.save()
```

## Last Seen Timestamps

The system automatically updates `last_seen` on successful connection:

```python
from rf_bench import connect
sdg = connect('sdg')  # Connects, updates last_seen to current UTC time
```

Query last-seen:
```python
inv = Inventory()
info = inv.get('sdg-main')
print(f"Last seen: {info['last_seen']}")  # "2026-06-15T14:30:00Z"
```

## Phase 2 Features (TODO)

- USB serial discovery and connection
- Automatic SSH tunnel creation for remote USB instruments
- Full subnet scanning for network discovery
- Web UI for inventory management
- Instrument health checks and monitoring
- Automated calibration reminders

## See Also

- `inventory.example.yaml` — Full example with all instrument types
- `inventory.yaml` — Your local inventory (git-ignored)
- `drivers/*/README.md` — Driver-specific documentation

## Phase 2: USB Instruments (NEW!)

### USB Serial Devices

Flipper Zero, Bus Pirate, and other USB serial instruments are now supported:

```yaml
instruments:
  flipper-main:
    type: FlipperZero
    driver: rf_bench.flipper.FlipperZero
    connection:
      protocol: serial
      host: localhost
      device: /dev/ttyACM0
      baud: 115200
    tags: [usb, sub-ghz, ir]
```

Usage:
```python
from rf_bench import connect

flipper = connect('flipper')
flipper.subghz_transmit_ook(433920000, [1000, 500, 1000, 500])
```

### RTL-SDR (libusb)

RTL-SDR dongles via librtlsdr:

```yaml
instruments:
  rtlsdr-1:
    type: RTLSDR
    driver: rf_bench.rtlsdr.RTLSDR
    connection:
      protocol: libusb
      host: localhost
      serial: "00000001"  # USB serial number
      device_index: 0     # Or use index if no serial
      ppm_correction: 1
    tags: [usb, sdr]
```

Usage:
```python
from rf_bench import connect

rtl = connect('rtl')
iq = rtl.capture_iq(1024000, duration=1.0)
```

### USB Discovery

Discover all connected USB instruments:

```python
from rf_bench.inventory import Inventory

inv = Inventory()
devices = inv.discover_all()

print("USB Serial:")
for dev in devices['usb_serial']:
    print(f"  {dev['device']}: {dev['vendor']} {dev['product']}")

print("\nRTL-SDR:")
for dev in devices['rtlsdr']:
    print(f"  Index {dev['device_index']}: Serial {dev['serial']}")
```

### Remote USB via SSH Tunnel (TODO)

For USB instruments on remote machines:

```yaml
instruments:
  et5406a-load:
    type: ET5406A
    driver: rf_bench.yertai.ET5406A
    connection:
      protocol: serial
      host: 10.1.0.16  # greybox
      device: /dev/ttyUSB0
      baud: 9600
      ssh_tunnel: true  # Auto-create SSH tunnel
```

**Note:** SSH tunnel support is stubbed. For now, manually create tunnels:
```bash
# On remote host:
socat TCP-LISTEN:9999,reuseaddr,fork FILE:/dev/ttyUSB0,b9600,raw

# On local machine:
ssh -L 9999:localhost:9999 10.1.0.16

# In inventory:
device: socket://localhost:9999
```

## Phase 3: BenchView Integration (NEW!)

### Dynamic Virtual Instruments

BenchView automatically writes inventory overlays when launching virtual instruments:

```bash
# Start BenchView with your panel config
cd virtual/benchview/backend
python benchview.py my-panel.yaml
```

BenchView writes `~/.rf-bench/benchview_my-panel_ports.yaml`:
```yaml
panel: "Flight Instruments"
instruments:
  display-freq:
    type: VirtualNumericDisplay
    driver: rf_bench.virtual.VirtualNumericDisplay
    connection:
      protocol: scpi-tcp
      host: localhost
      port: 5100
      http_port: 8100
    tags: [virtual, benchview]
```

The inventory system automatically loads these overlays:

```python
from rf_bench import connect

# BenchView must be running
display = connect('display-freq')  # Connects to dynamic port 5100
display.set_value(14.257)
```

### Multi-Instance Instruments

BenchView supports multiple instances (e.g., 4 analog meters):

```yaml
# In BenchView config
instruments:
  - name: meters
    type: VirtualAnalogMeter
    count: 4  # Creates 4 meters
    layout: ROW
```

BenchView assigns:
- SCPI port 5100 for all 4 meters
- Sub-addressing via 1-based indexing: `INST:SEL 1`, `INST:SEL 2`, etc.

```python
from rf_bench import connect

meters = connect('meters')

# Set meter 1
meters.write('INST:SEL 1')
meters.write('MEAS:VAL 13.8')

# Set meter 2
meters.write('INST:SEL 2')
meters.write('MEAS:VAL 5.0')
```

### Overlay Precedence

Inventory loads files in this order:
1. `$RF_BENCH_INVENTORY` or `~/.rf-bench/inventory.yaml` (main)
2. `~/.rf-bench/benchview_*_ports.yaml` (BenchView overlays)
3. `~/.rf-bench/*.yaml` (other overlays)

Overlays **update** existing instruments or **add** new ones.

### Cleanup

BenchView overlay files persist after BenchView exits. To clean up:

```bash
rm ~/.rf-bench/benchview_*_ports.yaml
```

Or let them accumulate - they're only active when BenchView is running on those ports.

