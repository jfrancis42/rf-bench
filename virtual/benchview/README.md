# BenchView - Virtual Instrument Grid Layout

**Domain:** benchview.org (planned)  
**Status:** v2.0 - Simple iframe-based grid

Web-based grid layout manager for composing instrument panels from existing standalone virtual instruments.

## Architecture

BenchView is a **layout manager** — it arranges existing instruments in a grid using iframes. Each instrument:
- Keeps its own backend (SCPI server, MQTT subscriber)
- Keeps its own frontend (HTML/CSS/JS)
- Runs independently in its own iframe

BenchView just:
- Reads a YAML config file
- Generates an HTML grid layout
- Serves the instrument files as static content
- Each instrument's backend runs on its configured SCPI port

## Quick Start

```bash
# Start BenchView with a config
cd backend
python3 benchview.py configs/demo_2x2.yaml

# Open browser
xdg-open http://localhost:8200
```

Each instrument in the grid runs its own backend automatically (SCPI + MQTT).

## Config Format

```yaml
panel:
  name: "Panel Name"
  description: "Optional description"
  
  grid:
    columns: 2
    rows: 2
    gap: 10px
  
  instruments:
    - id: widget_id          # Unique ID
      path: numeric-display/frontend/index.html  # Path to instrument HTML
      position: {row: 0, col: 0}   # Grid position (0-indexed)
      span: {rows: 1, cols: 1}     # Grid span
      scpi_port: 5000              # SCPI port for this instance
      mqtt_topic: bench/topic      # MQTT topic to subscribe
      
      config:                      # Instrument-specific config (passed as query params)
        label: "Frequency"
        units: "MHz"
        precision: 3
```

## Available Instruments

All instruments in `virtual/` directory can be used:

| Instrument | Path | Description |
|------------|------|-------------|
| numeric-display | `numeric-display/frontend/index.html` | Large numeric readout |
| analog-meter | `analog-meter/frontend/index.html` | Circular gauge with needle |
| gauge-cluster | `gauge-cluster/frontend/index.html` | Multi-gauge dashboard |
| led | `led/frontend/index.html` | Binary indicator light |
| text-lcd | `text-lcd/frontend/index.html` | Multi-line text display |
| line-chart | `line-chart/frontend/index.html` | Scrolling time-series chart |
| xy-plot | `xy-plot/frontend/index.html` | 2D scatter/line plot |
| bar-graph | `bar-graph/frontend/index.html` | Horizontal/vertical bars |
| waterfall | `waterfall/frontend/index.html` | Spectrum waterfall |
| compass | `compass/frontend/index.html` | Directional compass |
| toggle | `toggle/frontend/index.html` | On/off switch |
| button | `button/frontend/index.html` | Momentary button |
| slider | `slider/frontend/index.html` | Linear slider |
| knob | `knob/frontend/index.html` | Rotary knob |
| text-input | `text-input/frontend/index.html` | Text entry field |

## Example Configs

### Basic 2×2 Panel

```yaml
panel:
  name: "Basic 2×2"
  grid: {columns: 2, rows: 2, gap: 10px}
  instruments:
    - id: freq
      path: numeric-display/frontend/index.html
      position: {row: 0, col: 0}
      span: {rows: 1, cols: 1}
      scpi_port: 5000
      mqtt_topic: bench/freq
      config: {label: "Frequency", units: "MHz"}
```

### Spanning Widgets

```yaml
panel:
  name: "Chart Panel"
  grid: {columns: 3, rows: 2, gap: 10px}
  instruments:
    - id: chart
      path: line-chart/frontend/index.html
      position: {row: 0, col: 0}
      span: {rows: 2, cols: 2}    # Takes 2×2 area
      scpi_port: 5010
      mqtt_topic: bench/chart
    
    - id: power
      path: analog-meter/frontend/index.html
      position: {row: 0, col: 2}
      span: {rows: 1, cols: 1}
      scpi_port: 5011
      mqtt_topic: bench/power
```

## Testing

Use the demo data generators in `backend/`:

```bash
# For demo_2x2.yaml
python3 demo_data.py

# For demo_flight.yaml
python3 demo_flight.py
```

Or publish MQTT directly:

```bash
mosquitto_pub -h localhost -t bench/freq -m "14.257"
```

Or use SCPI:

```bash
echo "MEAS:VAL 14.257" | nc localhost 5000
```

Each instrument runs its own backend, so all SCPI/MQTT features work exactly as in standalone mode.

## How It Works

1. BenchView reads the YAML config
2. Generates an HTML page with CSS Grid layout
3. Mounts all `virtual/*/` directories as static file servers
4. Each iframe loads an instrument's HTML with config as query params
5. Each instrument's backend (Python server) starts when the page loads
6. Instruments communicate via MQTT (subscribe to topics) and SCPI (TCP servers)

## Advantages Over Custom Widgets

- **No duplicate code** — instruments are written once, used everywhere
- **Zero integration work** — any instrument can be dropped into any grid
- **Independent testing** — each instrument works standalone
- **Simple config** — just paths and positions, no custom backend code
- **Full feature parity** — iframe instruments have all their original features

## Roadmap

- [ ] Responsive breakpoints (desktop/tablet/mobile)
- [ ] Config editor UI (drag-and-drop layout builder)
- [ ] Multiple configs (tabs or dropdown)
- [ ] Save/load layouts from browser localStorage
- [ ] Deploy to benchview.org

## File Structure

```
benchview/
├── backend/
│   ├── benchview.py         # Main server (simple iframe layout generator)
│   ├── requirements.txt     # FastAPI + uvicorn + PyYAML
│   ├── demo_data.py         # Demo data for 2×2 panel
│   ├── demo_flight.py       # Demo data for flight panel
│   └── configs/
│       ├── demo_2x2.yaml    # Basic 2×2 example
│       └── demo_flight.yaml # Flight instruments example
├── frontend/
│   └── (not used - HTML is generated by backend)
└── README.md
```

## Dependencies

- **Python 3.11+**
- `fastapi` — Web framework
- `uvicorn` — ASGI server
- `pyyaml` — YAML config parser

## License

Part of rf-bench project.
