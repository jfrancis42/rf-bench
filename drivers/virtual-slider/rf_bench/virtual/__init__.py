"""Virtual instrument drivers for rf-bench."""

from .slider import VirtualSlider, VirtualSliderError

__all__ = ['VirtualSlider', 'VirtualSliderError']
