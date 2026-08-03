# rf-bench-drivers-virtual

Python clients for the [rf-bench](https://github.com/jfrancis42/rf-bench) **virtual
SCPI instruments** — browser-rendered instrument panels that behave like real
bench hardware.

Each panel is an HTML5 Canvas front end plus a FastAPI back end. It listens for
SCPI on TCP port 5025 and pushes live state to the browser over a WebSocket.
The classes in this package are the automation side: they connect to a panel's
SCPI port and drive it exactly like any other instrument in the collection.

```python
from rf_bench.virtual import VirtualLED, VirtualNumericDisplay, VirtualBarGraph

led  = VirtualLED("127.0.0.1")
disp = VirtualNumericDisplay("127.0.0.1", port=5026)
bar  = VirtualBarGraph("127.0.0.1", port=5027)

led.on()
disp.set_value(14.074)
bar.set_value(-93.2)
```

## Install

```bash
pip install rf-bench-drivers-virtual
```

No third-party dependencies — the clients are raw SCPI over TCP.

## Widgets

Every widget ships a single-instrument class. Most also ship a `…Multi`
variant that drives a panel hosting several sub-instruments, addressed by a
1-based index.

| Widget | Class | Multi variant | Detail |
|--------|-------|---------------|--------|
| Analog meter (270° arc, spring-damper needle) | `VirtualAnalogMeter` | `VirtualAnalogMeterMulti` | [widgets/analog-meter.md](widgets/analog-meter.md) |
| Bar graph / level meter | `VirtualBarGraph` | `VirtualBarGraphMulti` | [widgets/bar-graph.md](widgets/bar-graph.md) |
| Momentary push button | `VirtualButton` | `VirtualButtonMulti` | [widgets/button.md](widgets/button.md) |
| Compass / directional indicator | `VirtualCompass` | — | [widgets/compass.md](widgets/compass.md) |
| Gauge cluster (multi-meter dashboard) | `VirtualGaugeCluster` | — | [widgets/gauge-cluster.md](widgets/gauge-cluster.md) |
| Rotary knob | `VirtualKnob` | `VirtualKnobMulti` | [widgets/knob.md](widgets/knob.md) |
| LED indicator (on/off/blink) | `VirtualLED` | `VirtualLEDMulti` | [widgets/led.md](widgets/led.md) |
| Line chart (scrolling time series) | `VirtualLineChart` | — | [widgets/line-chart.md](widgets/line-chart.md) |
| 7-segment numeric display | `VirtualNumericDisplay` | `VirtualNumericDisplayMulti` | [widgets/numeric-display.md](widgets/numeric-display.md) |
| Linear slider | `VirtualSlider` | `VirtualSliderMulti` | [widgets/slider.md](widgets/slider.md) |
| Smith chart (4 traces) | `VirtualSmithChart` | — | [widgets/smith-chart.md](widgets/smith-chart.md) |
| Text input field | `VirtualTextInput` | `VirtualTextInputMulti` | [widgets/text-input.md](widgets/text-input.md) |
| Multi-line text LCD | `VirtualTextLCD` | — | [widgets/text-lcd.md](widgets/text-lcd.md) |
| Toggle switch | `VirtualToggle` | `VirtualToggleMulti` | [widgets/toggle.md](widgets/toggle.md) |
| Waterfall (spectrum history) | `VirtualWaterfall` | — | [widgets/waterfall.md](widgets/waterfall.md) |
| XY plot (2D scatter / parametric) | `VirtualXYPlot` | — | [widgets/xy-plot.md](widgets/xy-plot.md) |

Error types follow the same naming: `VirtualLEDError`, `VirtualKnobMultiError`,
and so on. The Smith chart uses `SmithChartError` /
`SmithChartConnectionError` / `SmithChartCommandError`.

The panels themselves (back ends, HTML, and the BenchView panel manager) live
under `virtual/` in the repository root, not in this package.

## Packaging history

This was originally **16 separate distributions** — `rf-bench-drivers-virtual-led`,
`-knob`, `-waterfall`, and so on. Each declared
`packages = ["rf_bench", "rf_bench.virtual"]` and shipped its own
`rf_bench/virtual/__init__.py`.

Only one file can occupy that path. Installing any two of them meant the second
wheel silently overwrote the first's `__init__.py`, so 15 of 16 widgets became
unimportable through their documented names, with no warning from pip. A
statement like

```python
from rf_bench.virtual import VirtualBarGraphMulti, VirtualNumericDisplayMulti, VirtualLEDMulti
```

drawing three names from three distributions could never succeed.

They were merged into this single distribution on 2026-08-03. **Import paths are
unchanged** — nothing that already said `from rf_bench.virtual import X` needs
editing. Per-widget documentation is preserved under `widgets/`.

`rf_bench` is a PEP 420 namespace package: this distribution ships **no**
top-level `rf_bench/__init__.py`, so it coexists with every other `rf_bench.*`
driver instead of shadowing them.

## License

GPL-3.0-or-later.
