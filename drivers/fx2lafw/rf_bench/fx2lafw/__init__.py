"""
rf_bench.fx2lafw — FX2LAFW-based logic analyzer driver

Supports "24MHz 8CH" Saleae-compatible logic analyzers using the fx2lafw firmware.
Uses libsigrok via subprocess (sigrok-cli) for capture and decode.

Example:
    from rf_bench.fx2lafw import FX2LAFWLogicAnalyzer

    la = FX2LAFWLogicAnalyzer()

    # Capture 1 second at 24 MHz, all 8 channels
    samples = la.capture(channels=[0,1,2,3,4,5,6,7],
                        sample_rate=24e6,
                        duration=1.0)

    # Decode UART on channel 0
    decoded = la.decode_uart(samples, channel=0, baud=115200)

    # Save capture
    la.save_vcd('capture.vcd', samples)
"""

from .fx2lafw import (
    FX2LAFWLogicAnalyzer,
    FX2LAFWError,
    FX2LAFWNotFoundError,
    FX2LAFWCaptureError
)

__all__ = [
    'FX2LAFWLogicAnalyzer',
    'FX2LAFWError',
    'FX2LAFWNotFoundError',
    'FX2LAFWCaptureError'
]
