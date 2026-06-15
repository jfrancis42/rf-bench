"""
rf_bench.instruments — Instrument registry and discovery

Provides unified access to instruments across different connection types:
  - TCP/IP (SCPI instruments, virtual instruments)
  - USB serial (GPS, radios, DC loads, function generators)
  - GPIB (via Ethernet-GPIB adapter when available)

Example:

    from rf_bench.instruments import Registry

    registry = Registry()

    # Get any available GPS
    gps = registry.get('gps')

    # Get specific instrument by role
    ssa = registry.get('spectrum-analyzer')
    sdg = registry.get('signal-generator')

    # Get specific USB device by path
    yertai = registry.get('dc-load', serial='/dev/ttyUSB0')
"""

from .registry import Registry, InstrumentNotFoundError, InstrumentConfig

__all__ = ['Registry', 'InstrumentNotFoundError', 'InstrumentConfig']
