"""
rf_bench.virtual — Python clients for the virtual SCPI instruments.

Each widget is a browser-rendered instrument panel (HTML5 Canvas front end,
FastAPI back end) that speaks SCPI over TCP port 5025 and pushes live state to
the browser over a WebSocket.  The classes here are the automation-side clients:
they connect to a panel's SCPI port and drive it like any other bench
instrument.

::

    from rf_bench.virtual import VirtualLED, VirtualBarGraphMulti

    led = VirtualLED("127.0.0.1")
    led.on()

Panels come in two flavours.  ``VirtualX`` drives a single instrument;
``VirtualXMulti`` drives a panel hosting several sub-instruments, addressed by
a 1-based index.

Packaging note
--------------
This was originally 16 separate distributions (``rf-bench-drivers-virtual-led``,
``-knob``, ``-waterfall``, …), each shipping its own
``rf_bench/virtual/__init__.py``.  Since only one file can occupy that path,
installing any two of them silently clobbered the first one's re-exports and
made its widget unimportable — and a statement like
``from rf_bench.virtual import VirtualBarGraphMulti, VirtualNumericDisplayMulti,
VirtualLEDMulti`` could never succeed.  They were merged into this single
distribution on 2026-08-03.  Import paths are unchanged.
"""

from .analog_meter import VirtualAnalogMeter
from .analog_meter_multi import VirtualAnalogMeterMulti, VirtualAnalogMeterMultiError
from .bar_graph import VirtualBarGraph, VirtualBarGraphError
from .bar_graph_multi import VirtualBarGraphMulti, VirtualBarGraphMultiError
from .button import VirtualButton, VirtualButtonError
from .button_multi import VirtualButtonMulti, VirtualButtonMultiError
from .compass import VirtualCompass
from .gauge_cluster import VirtualGaugeCluster, VirtualGaugeClusterError
from .knob import VirtualKnob, VirtualKnobError
from .knob_multi import VirtualKnobMulti, VirtualKnobMultiError
from .led import VirtualLED, VirtualLEDError
from .led_multi import VirtualLEDMulti, VirtualLEDMultiError
from .line_chart import VirtualLineChart
from .numeric_display import VirtualNumericDisplay, VirtualNumericDisplayError
from .numeric_display_multi import (
    VirtualNumericDisplayMulti,
    VirtualNumericDisplayMultiError,
)
from .slider import VirtualSlider, VirtualSliderError
from .slider_multi import VirtualSliderMulti, VirtualSliderMultiError
from .smith_chart import (
    SmithChartCommandError,
    SmithChartConnectionError,
    SmithChartError,
    VirtualSmithChart,
)
from .text_input import VirtualTextInput
from .text_input_multi import VirtualTextInputMulti
from .text_lcd import VirtualTextLCD
from .toggle import VirtualToggle, VirtualToggleError
from .toggle_multi import VirtualToggleMulti, VirtualToggleMultiError
from .waterfall import VirtualWaterfall
from .xy_plot import VirtualXYPlot

__version__ = "0.1.0"

__all__ = [
    # analog meter
    "VirtualAnalogMeter",
    "VirtualAnalogMeterMulti",
    "VirtualAnalogMeterMultiError",
    # bar graph
    "VirtualBarGraph",
    "VirtualBarGraphError",
    "VirtualBarGraphMulti",
    "VirtualBarGraphMultiError",
    # button
    "VirtualButton",
    "VirtualButtonError",
    "VirtualButtonMulti",
    "VirtualButtonMultiError",
    # compass
    "VirtualCompass",
    # gauge cluster
    "VirtualGaugeCluster",
    "VirtualGaugeClusterError",
    # knob
    "VirtualKnob",
    "VirtualKnobError",
    "VirtualKnobMulti",
    "VirtualKnobMultiError",
    # LED
    "VirtualLED",
    "VirtualLEDError",
    "VirtualLEDMulti",
    "VirtualLEDMultiError",
    # line chart
    "VirtualLineChart",
    # numeric display
    "VirtualNumericDisplay",
    "VirtualNumericDisplayError",
    "VirtualNumericDisplayMulti",
    "VirtualNumericDisplayMultiError",
    # slider
    "VirtualSlider",
    "VirtualSliderError",
    "VirtualSliderMulti",
    "VirtualSliderMultiError",
    # Smith chart
    "VirtualSmithChart",
    "SmithChartError",
    "SmithChartConnectionError",
    "SmithChartCommandError",
    # text input
    "VirtualTextInput",
    "VirtualTextInputMulti",
    # text LCD
    "VirtualTextLCD",
    # toggle
    "VirtualToggle",
    "VirtualToggleError",
    "VirtualToggleMulti",
    "VirtualToggleMultiError",
    # waterfall
    "VirtualWaterfall",
    # XY plot
    "VirtualXYPlot",
    "__version__",
]
