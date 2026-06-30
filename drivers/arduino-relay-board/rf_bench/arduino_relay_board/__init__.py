"""
rf_bench.arduino_relay_board — driver for the Arduino+W5500 network relay board.

Typical usage::

    from rf_bench.arduino_relay_board import ArduinoRelayBoard

    with ArduinoRelayBoard("192.168.1.177") as r:
        r.on(1)
        r.pulse_high(2, 250)
        bits = r.status()           # int bitmask, bit 0 = relay 1
        states = r.status_all()     # tuple(bool, bool, bool, bool)
        r.off(1)
        r.reset()
"""

from .arduino_relay_board import (
    ArduinoRelayBoard,
    ArduinoRelayBoardError,
    ArduinoRelayBoardTimeoutError,
)

__all__ = [
    "ArduinoRelayBoard",
    "ArduinoRelayBoardError",
    "ArduinoRelayBoardTimeoutError",
]
