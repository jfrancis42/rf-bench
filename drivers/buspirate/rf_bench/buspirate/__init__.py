"""
rf_bench.buspirate — Bus Pirate v3/v4/v5 driver for bench automation.

Supported hardware:
  Bus Pirate v3 (all PCB revisions), v4 — USB CDC serial → /dev/ttyUSB*
  Bus Pirate v5 (RP2040) — connect to the binary port → /dev/ttyACM1

For v5, use the BINARY port (not the terminal port).  Use
``BusPirate.find_devices()`` to locate the correct port automatically.

Typical usage::

    from rf_bench.buspirate import BusPirate, BusPirateError

    # v3/v4
    with BusPirate("/dev/ttyUSB1") as bp:
        bp.spi_configure(speed_hz=1_000_000, cpol=0, cpha=0)
        rx = bp.spi_transfer([0x40, 0x00, 0x00])
        bp.spi_exit()

    # v5 — connect to binary port
    with BusPirate("/dev/ttyACM1") as bp:
        bp.spi_configure(speed_hz=1_000_000, cpol=0, cpha=0)
        rx = bp.spi_transfer([0x40, 0x00, 0x00])
        bp.spi_exit()

    # Auto-detect any Bus Pirate
    for dev in BusPirate.find_devices():
        if dev['role'] in ('binary', 'combined'):
            with BusPirate(dev['port']) as bp:
                print(bp.identify())
"""

from .buspirate import BusPirate, BusPirateError, BusPirateVersionError

__all__ = ["BusPirate", "BusPirateError", "BusPirateVersionError"]
