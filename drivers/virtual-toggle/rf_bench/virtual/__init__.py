"""rf_bench.virtual — Virtual SCPI instrument drivers"""

from .toggle import VirtualToggle, VirtualToggleError

from .toggle_multi import VirtualToggleMulti, VirtualToggleMultiError
__all__ = ["VirtualToggleMulti", "VirtualToggleMultiError", "VirtualToggle", "VirtualToggleError"]
