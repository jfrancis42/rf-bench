"""rf_bench.siglent — Siglent instrument drivers (SCPI over raw TCP, port 5025)"""

from .ssa3000x import SSA3000X
from .sdg1000x import SDG1000X, DBM_MIN, DBM_MAX
from .sds2000x import SDS2000X
from .sdm3000x import SDM3000X, RANGE_AUTO as SDM_RANGE_AUTO
from .spd3303x import (
    SPD3303X,
    TRACKING_INDEPENDENT, TRACKING_SERIES, TRACKING_PARALLEL,
)

__all__ = [
    # Spectrum analyzer
    "SSA3000X",
    # Function generator
    "SDG1000X", "DBM_MIN", "DBM_MAX",
    # Oscilloscope
    "SDS2000X",
    # Bench multimeter
    "SDM3000X", "SDM_RANGE_AUTO",
    # Triple-output power supply
    "SPD3303X", "TRACKING_INDEPENDENT", "TRACKING_SERIES", "TRACKING_PARALLEL",
]
