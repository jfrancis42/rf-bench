# Inventory System - Remaining Work

## Phase 1 Complete ✅

- [x] Basic YAML inventory system
- [x] Module-level `connect()` function
- [x] Auto-loading from `$RF_BENCH_INVENTORY`, `~/.rf-bench/inventory.yaml`, `./inventory.yaml`
- [x] Alias support
- [x] Calibration tracking (dates, notes)
- [x] Tag filtering
- [x] Last-seen timestamps
- [x] Network discovery fallback (basic)
- [x] Converted 80+ projects to use inventory

## Phase 2 - USB Instruments (TODO)

### USB Serial Instruments
- [ ] Auto-discovery of USB serial devices (Bus Pirate, Flipper Zero, ET5406A)
- [ ] udev serial number tracking
- [ ] Persistent device naming via udev rules
- [ ] SSH tunnel support for remote USB instruments
- [ ] Auto-reconnect on USB disconnect/reconnect

**Affected instruments:**
- Flipper Zero (`/dev/ttyACM0`)
- Bus Pirate v5 (`/dev/ttyACM1`)
- ET5406A DC load (`/dev/ttyUSB0` on greybox 10.1.0.16)
- IC-7300, IC-9700, FT-891 (USB serial via rigctld)

**Implementation notes:**
```python
# Desired API
from rf_bench import connect

# Local USB
flipper = connect('flipper')  # Looks up /dev/ttyACM0 or serial number

# Remote USB via SSH tunnel
load = connect('et5406a')  # Inventory: host=10.1.0.16, device=/dev/ttyUSB0
# Should create SSH tunnel or use existing rigctld-style proxy
```

**Inventory schema for USB:**
```yaml
instruments:
  flipper-main:
    type: FlipperZero
    driver: rf_bench.flipper.FlipperZero
    connection:
      protocol: serial
      host: localhost  # or remote host for SSH
      device: /dev/ttyACM0
      baud: 115200
      serial: "FLIP123456"  # USB serial number for stable identification
    tags: [usb, sub-ghz, ir, rfid]

  et5406a-load:
    type: ET5406A
    driver: rf_bench.yertai.ET5406A
    connection:
      protocol: serial
      host: 10.1.0.16  # greybox
      device: /dev/ttyUSB0
      baud: 9600
      serial: "5461234567"
      ssh_tunnel: true  # Enable automatic SSH tunneling
    tags: [usb, electronic-load, remote]
```

### libusb Instruments
- [ ] RTL-SDR discovery via `librtlsdr`
- [ ] Device index vs serial number mapping
- [ ] Remote RTL-SDR support (rtl_tcp)

**Affected instruments:**
- RTL-SDR (`rf_bench.rtlsdr.RTLSDR`)

**Inventory schema:**
```yaml
instruments:
  rtlsdr-1:
    type: RTLSDR
    driver: rf_bench.rtlsdr.RTLSDR
    connection:
      protocol: libusb
      host: localhost
      serial: "00000001"
      device_index: 0
      ppm_correction: 1
    tags: [usb, sdr, receiver]
```

## Phase 3 - Virtual Instruments + BenchView (TODO)

### BenchView Dynamic Port Assignment

**Problem:**
- BenchView dynamically assigns ports to virtual instruments (5100+, 8100+)
- Each instrument instance gets unique SCPI + HTTP + WebSocket ports
- Multi-instance instruments (e.g., 4 analog meters) use 1-based sub-addressing
- Current inventory system expects static ports

**Solution options:**

**Option A: BenchView writes inventory fragment**
```bash
# User runs BenchView with config
benchview my-panel.yaml

# BenchView launches backends and writes
~/.rf-bench/benchview-ports.yaml:
  display-freq:
    connection:
      protocol: scpi-tcp
      host: localhost
      port: 5100
  meter-swr:
    connection:
      protocol: scpi-tcp
      host: localhost
      port: 5101

# Inventory manager auto-loads benchview-ports.yaml as overlay
```

**Option B: Inventory queries BenchView at runtime**
```python
from rf_bench import connect

# Inventory detects 'benchview://' protocol
display = connect('display-freq')  # → queries BenchView API for port
```

**Option C: Manual port specification in inventory**
```yaml
# User updates inventory after BenchView startup
instruments:
  display-freq:
    type: VirtualNumericDisplay
    driver: rf_bench.virtual.VirtualNumericDisplay
    connection:
      protocol: scpi-tcp
      host: localhost
      port: 5100  # From BenchView output
```

**Recommendation:** Option A (BenchView writes fragment)
- BenchView already outputs `*_ports.yaml` for glue scripts
- Inventory manager can glob-load `~/.rf-bench/*.yaml`
- Clean separation: BenchView manages its own namespace
- Zero manual config burden on user

### Implementation plan:

1. Inventory manager: support loading multiple YAML files from `~/.rf-bench/`
2. BenchView: write inventory-compatible fragment on startup
3. Inventory: precedence order: `inventory.yaml` > `benchview-*.yaml` > `*.yaml`
4. Virtual instrument drivers: accept runtime port discovery

## Phase 4 - Enhanced Discovery (TODO)

### Full Subnet Scanning
- [ ] Parallel SCPI *IDN? queries across /24 subnet
- [ ] Timeout optimization (asyncio)
- [ ] Cache discovered instruments
- [ ] Prompt user to add to inventory

### Vendor-Specific Discovery
- [ ] mDNS/Bonjour for instruments that support it
- [ ] VISA-compatible discovery (optional pyvisa integration)
- [ ] Manufacturer-specific protocols (Siglent, Rigol, etc.)

### Health Checks
- [ ] Periodic instrument reachability checks
- [ ] Automatic last-seen updates
- [ ] Warning on stale connections
- [ ] Auto-reconnect after network changes

## Phase 5 - Web UI (TODO)

### Inventory Management Dashboard
- [ ] Web interface at `http://localhost:8350/inventory`
- [ ] View all instruments, connection status, last-seen
- [ ] Edit connection parameters
- [ ] Trigger discovery scans
- [ ] View calibration due dates
- [ ] Export/import inventory YAML

### Features:
- Visual grid of instrument status (online/offline/stale)
- One-click connect/disconnect
- Real-time last-seen updates
- Calibration reminder alerts
- Tag-based filtering and search
- Bulk operations (tag multiple instruments, update groups)

## Phase 6 - Advanced Features (TODO)

### Instrument Groups
```yaml
groups:
  rf-cal-bench:
    - ssa-main
    - sdg-main
    - dmm-cal
  hf-station:
    - ic7300-hf
    - spd-main
    - display-freq
```

### Connection Profiles
```yaml
profiles:
  lab-bench:
    ssa: ssa-main
    sdg: sdg-main
  field-portable:
    ssa: ssa-remote
    sdg: sdg-portable
```

### Instrument Pooling
- Multiple instances of same instrument type
- Auto-allocate from pool on `connect()`
- Lock management (prevent concurrent access)
- Queue when all busy

### Automated Calibration Reminders
- Email/SMS alerts when cal is due
- Integration with calendar systems
- Calibration history tracking
- Calibration procedure lookup

## Migration Path for Existing Scripts

### Already Converted (Phase 1 complete)
- 80+ projects use `connect('alias')`
- Backward-compatible args (--ssa, --sdg still work)

### TODO: USB Instruments
All Flipper Zero, Bus Pirate, and RTL-SDR projects have:
```python
# TODO: Convert to inventory when USB support is added (Phase 2)
flipper = FlipperZero("/dev/ttyACM0")
```

When Phase 2 is ready:
```python
from rf_bench import connect
flipper = connect('flipper')
```

### TODO: Virtual Instruments
All virtual instrument usage currently:
```python
from rf_bench.virtual import VirtualNumericDisplay
display = VirtualNumericDisplay("localhost", port=5000)
```

When Phase 3 is ready:
```python
from rf_bench import connect
display = connect('display-freq')  # Port looked up from BenchView
```

## Testing Checklist

### Phase 2 Testing
- [ ] USB serial discovery on Linux
- [ ] USB serial discovery on macOS
- [ ] USB serial discovery on Windows
- [ ] SSH tunnel creation for remote USB
- [ ] udev rule generation
- [ ] Auto-reconnect after device unplug/replug
- [ ] RTL-SDR enumeration with multiple dongles
- [ ] RTL-SDR serial number matching

### Phase 3 Testing
- [ ] BenchView fragment generation
- [ ] Inventory overlay loading
- [ ] Multi-instance virtual instruments
- [ ] Dynamic port discovery
- [ ] Connection failover

### Phase 4 Testing
- [ ] Full /24 subnet scan performance
- [ ] mDNS discovery
- [ ] Health check accuracy
- [ ] Auto-reconnect reliability

### Phase 5 Testing
- [ ] Web UI functionality
- [ ] Multi-user access
- [ ] Export/import integrity
- [ ] Real-time status updates

## Documentation Updates Needed

- [ ] Update main README with Phase 2 USB support
- [ ] Update main README with Phase 3 BenchView integration
- [ ] Add USB troubleshooting guide
- [ ] Add SSH tunnel configuration guide
- [ ] Update all project READMEs that use USB instruments
- [ ] Create video walkthrough of inventory system
- [ ] Document udev rule creation process

## See Also

- `rf_bench/inventory/README.md` - Current inventory documentation
- `inventory.example.yaml` - Example with all instrument types
- `tools/convert_project.py` - Conversion tool for existing scripts
- `virtual/benchview/README.md` - BenchView documentation
