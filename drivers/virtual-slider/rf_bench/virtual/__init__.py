"""Virtual instrument drivers for rf-bench."""

from .slider import VirtualSlider, VirtualSliderError

from .slider_multi import VirtualSliderMulti, VirtualSliderMultiError
__all__ = ["VirtualSliderMulti", "VirtualSliderMultiError", 'VirtualSlider', 'VirtualSliderError']
