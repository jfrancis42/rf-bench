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
