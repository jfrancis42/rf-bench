"""rf_bench.hp — HP instrument drivers (GPIB via KISS-488 Ethernet adapter)"""

from .hp8712b import HP8712B

__all__ = [
    "HP8712B",
]
