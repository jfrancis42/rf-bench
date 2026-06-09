"""rf_bench.koolertron — Koolertron / MHinstek MHS-5200A series DDS signal generator drivers.

The MHS-5200A is widely rebranded — KKmoon, AliExpress "200MSa/s 12Bit DDS",
various Chinese eBay listings — but the hardware and protocol are common to
all of them under the OEM name (MHinstek, sold internationally by Koolertron).

This driver was written from scratch against the public protocol document
listed in the README under "Protocol reference and credits". It does not
incorporate code from any other implementation.
"""

from .mhs5200a import (
    MHS5200A,
    MHS5200AError,
    CalibrationError,
    DEFAULT_CAL_FILE,
    Waveform,
    CounterMode,
    Gate,
    SweepShape,
    Atten,
)

__all__ = [
    "MHS5200A",
    "MHS5200AError",
    "CalibrationError",
    "DEFAULT_CAL_FILE",
    "Waveform",
    "CounterMode",
    "Gate",
    "SweepShape",
    "Atten",
]
