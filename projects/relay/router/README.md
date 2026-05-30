> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-relay-router

GitHub: https://github.com/jfrancis42/rf-bench-relay-router

Software-defined N×M RF/signal routing matrix. Controls an XL9535 16-bit I2C
relay board via Bus Pirate to connect any configured source (antenna, instrument
output) to any configured destination (instrument input). Eliminates manual cable
changes during bench automation sequences.

## Hardware

| Instrument | Role |
|-----------|------|
| Bus Pirate v3/v4/v5 (/dev/ttyUSB1) | I2C master for XL9535 relay board |
| XL9535 relay board (8- or 16-relay) | Drives relay coils via ULN2803 or NPN transistors |
| RF relays (Omron G6Y-1 etc.) | Actual signal switching — XL9535 drives the coils |

The XL9535 board controls the coil drive transistors. The actual RF signal path
runs through external RF relays mounted close to the connectors.

## Wiring topology (4×2 example)

```
                  ┌────────────────────────────────┐
                  │       XL9535 relay board        │
                  │                                 │
  antenna-hf ────►│RL0──┐                           │
  antenna-vhf ───►│RL1──┤                           │
  ssa-tg ─────── ►│RL2──┤──[shared RF bus]──┬──RL4─►│── ssa-in
  sdg-ch1 ────── ►│RL3──┘                   ├──RL5─►│── ic7300
                  │                         ├──RL6─►│── rtlsdr
                  │                         └──RL7─►│── hp8712-p1
                  └────────────────────────────────┘

Each source relay (RL0–RL3) gates its source onto the shared RF bus.
Each destination relay (RL4–RL7) gates the shared bus to its instrument input.
exclusive_sources=true ensures only one source relay is closed at a time.
exclusive_destinations=true ensures only one destination is connected per source.
```

For a proper matrix wiring use RF T-splitters or a matrix PCB with controlled-impedance
traces. For bench use a star-topology with short coax stubs works at HF/VHF.

Use RF relays (Omron G6Y-1/G6Y-2, TE OAR series, Axicom IM series) for the signal
path — the cheap HK19F/SRD relay contacts on the breakout board are not suitable
for RF above ~5 MHz.

## Config file format

```json
{
  "name": "bench-router",
  "sources": {
    "antenna-hf":  {"relay": 0, "description": "HF antenna (160m-6m)"},
    "ssa-tg":      {"relay": 2, "description": "SSA tracking generator output"}
  },
  "destinations": {
    "ssa-in":  {"relay": 4, "description": "SSA RF input"},
    "ic7300":  {"relay": 5, "description": "IC-7300 antenna port"}
  },
  "exclusive_sources": true,
  "exclusive_destinations": true
}
```

- **sources** / **destinations** — named ports with a relay number (0–15) and optional description.
- **exclusive_sources** — if true, connecting a new source to a destination automatically disconnects
  the previous source from that destination. Default: true.
- **exclusive_destinations** — if true, connecting a source to a new destination automatically
  disconnects the source from its previous destination. Default: true.

The relay number is the logical relay index (0–15) as used by the XL9535 driver.
Sources and destinations may share the same XL9535 board; relay numbers must not overlap.

## Bus Pirate wiring

```
Bus Pirate    →    XL9535 board
MOSI (SDA)    →    SDA
CLK  (SCL)    →    SCL
+3.3V or +5V  →    VCC (logic supply — check board)
GND           →    GND
```

Enable pull-ups on the Bus Pirate. The relay coil supply must come from an external
5 V source — the Bus Pirate's +5V rail cannot drive coils directly.

## CLI usage

```
python relay_router.py --connect SRC DST [options]
python relay_router.py --disconnect SRC [options]
python relay_router.py --all-off [options]
python relay_router.py --status [options]
python relay_router.py --list [options]
python relay_router.py --ping [options]

Options:
  --bp PORT        Bus Pirate port (default /dev/ttyUSB1)
  --addr ADDR      XL9535 I2C address (default 0x20)
  --config FILE    Router config JSON (default: bench-router.json in script dir)
  --force          Skip exclusivity enforcement
  --quiet          Suppress output
```

Examples:

```bash
# Connect HF antenna to SSA input
python relay_router.py --connect antenna-hf ssa-in

# Route tracking generator output to IC-7300 (auto-disconnects antenna-hf from ssa-in
# if exclusive_sources is set, since ic7300 is a different destination)
python relay_router.py --connect ssa-tg ic7300

# Check what is currently routed
python relay_router.py --status

# List all configured ports
python relay_router.py --list

# Open all relays (safe state)
python relay_router.py --all-off

# Cycle every relay as a wiring self-test
python relay_router.py --ping
```

## Python API

```python
from rf_bench.buspirate import BusPirate
from relay_router import SignalRouter

with BusPirate("/dev/ttyUSB1") as bp:
    bp.set_pullups(True)
    bp.i2c_configure(speed_hz=100_000)

    with SignalRouter(bp, config_file="bench-router.json") as router:
        # Connect HF antenna to SSA input
        router.connect("antenna-hf", "ssa-in")

        # Switch to tracking generator (automatically disconnects antenna-hf)
        router.connect("ssa-tg", "ssa-in")

        # Check current state
        st = router.status()
        # → {"connections": [{"source": "ssa-tg", "destination": "ssa-in"}], ...}

        # Disconnect a source
        router.disconnect_source("ssa-tg")

        # Open everything
        router.all_off()

    bp.i2c_exit()
```

## State persistence

Connection state is stored in `~/.relay_router_state.json`. The `--status` command
reads this file directly without touching hardware, so you can check what is routed
even between script runs.

## Notes

- The relay board drives coil transistors only. Actual signal flow depends entirely
  on the external RF relay wiring topology.
- The exclusivity logic is software-only — the XL9535 does not enforce it in hardware.
  A power cycle of the relay board will open all relays; the state file will be
  out of sync until the next connect/disconnect/all-off command.
- For RF work at VHF/UHF use proper 50 Ω coaxial RF relays with SMA connectors.
  The standard reed or SPDT contacts on cheap breakout boards are only suitable
  for audio/low-frequency DC signal routing.
