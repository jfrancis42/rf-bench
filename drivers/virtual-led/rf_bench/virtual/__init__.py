"""Virtual LED Indicator driver."""

from .led import VirtualLED, VirtualLEDError
from .led_multi import VirtualLEDMulti, VirtualLEDMultiError

__all__ = ["VirtualLED", "VirtualLEDError", "VirtualLEDMulti", "VirtualLEDMultiError"]
