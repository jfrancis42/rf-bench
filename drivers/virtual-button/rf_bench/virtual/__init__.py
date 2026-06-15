"""rf_bench.virtual - Virtual button driver."""

from .button import VirtualButton, VirtualButtonError

from .button_multi import VirtualButtonMulti, VirtualButtonMultiError
__all__ = ["VirtualButtonMulti", "VirtualButtonMultiError", 'VirtualButton', 'VirtualButtonError']
