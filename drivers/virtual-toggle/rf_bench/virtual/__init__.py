"""rf_bench.virtual — Virtual SCPI instrument drivers"""

from .toggle import VirtualToggle, VirtualToggleError

__all__ = ["VirtualToggle", "VirtualToggleError"]
