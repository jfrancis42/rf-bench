"""
rf_bench.relay — XL9535 16-bit I2C relay board driver for bench automation.

Compatible with XL9535, PCA9535, and TCA9535 I/O expanders.

Typical usage::

    from rf_bench.buspirate import BusPirate
    from rf_bench.relay import XL9535

    with BusPirate("/dev/ttyUSB1") as bp:
        bp.set_pullups(True)
        bp.i2c_configure(speed_hz=100_000)
        with XL9535(bp, i2c_addr=0x20, num_relays=16) as relay:
            relay.set(0, True)       # energize relay 0
            relay.close_only(3)      # all off, then close relay 3
            relay.all_off()          # de-energize all
        bp.i2c_exit()
"""

from .relay import XL9535, XL9535Error

__all__ = ["XL9535", "XL9535Error"]
