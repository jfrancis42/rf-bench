"""
rf_bench.flipper — Flipper Zero USB driver for bench automation.

Supports Sub-GHz (CC1101), IR, LF RFID, NFC (all via CLI), and GPIO (via RPC).

Typical usage::

    from rf_bench.flipper import FlipperZero, FlipperError

    # Auto-detect connected Flipper
    with FlipperZero() as fz:
        print(fz.identify())

        # Sub-GHz carrier
        fz.subghz_tx_carrier(433_920_000)
        time.sleep(1)
        fz.subghz_stop()

        # RSSI measurement
        readings = fz.subghz_get_rssi(433_920_000, duration_s=0.5)

        # GPIO
        fz.gpio_set_mode("PA4", "output")
        fz.gpio_write("PA4", 1)
        fz.gpio_set_mode("PA6", "input")
        val = fz.gpio_read("PA6")

    # Or connect to a known port
    fz = FlipperZero("/dev/ttyACM0")
"""

from .flipper import FlipperZero, FlipperError, FlipperTimeoutError, FlipperProtocolError

__all__ = ["FlipperZero", "FlipperError", "FlipperTimeoutError", "FlipperProtocolError"]
