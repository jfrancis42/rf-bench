"""
rf_bench.gpib — GPIB bus transport for the rf-bench instrument collection.

This package is the *bus*, not an instrument.  It exists because GPIB is the
first link on the bench where several instruments share one physical connection
and the adapter carries global mutable state that must be set per transaction.

::

    from rf_bench.gpib import KISS488
    from rf_bench.hp import HP8712B
    from rf_bench.solartron import Solartron7151

    gpib = KISS488.shared("10.1.1.70")     # one socket, refcounted
    vna  = HP8712B(gpib.device(16))
    dmm  = Solartron7151(gpib.device(22))

``KISS488`` (Hx Engineering KISS-488 Rev 2, Ethernet or USB serial) is the only
adapter implemented today.  Anything exposing the same surface — a Prologix
GPIB-ETHERNET, an AR488, a NI GPIB-USB-HS — can be dropped in without touching
an instrument driver.

Protocol reference: KISS-488 Rev 2 User Guide revision 2.13 (firmware 2.65),
cached locally under ``rf-bench/docs/`` (not published).  Design notes and
the list of items still to verify against hardware:
``rf-bench/docs/kiss-488-driver.md`` (local only).
"""

from .device import GPIBDevice
from .kiss488 import (
    ADDR_MAX,
    ADDR_MIN,
    EOS_CR,
    EOS_CRLF,
    EOS_LF,
    EOS_NONE,
    GPIBError,
    GPIBTimeout,
    KISS488,
    QUERY_AUTO,
    QUERY_EXPLICIT_READ,
    READ_TMO_MS_MAX,
    READ_TMO_MS_MIN,
    SPY_ASCII,
    SPY_HEX,
    SPY_OFF,
)
from .link import (
    DEFAULT_SERIAL_BAUD,
    DEFAULT_TELNET_PORT,
    Link,
    LinkError,
    SerialLink,
    TcpLink,
    open_link,
)

__version__ = "0.1.0"

__all__ = [
    # adapter
    "KISS488",
    "GPIBDevice",
    "GPIBError",
    "GPIBTimeout",
    # links
    "Link",
    "LinkError",
    "TcpLink",
    "SerialLink",
    "open_link",
    "DEFAULT_TELNET_PORT",
    "DEFAULT_SERIAL_BAUD",
    # protocol constants
    "EOS_CRLF",
    "EOS_CR",
    "EOS_LF",
    "EOS_NONE",
    "SPY_OFF",
    "SPY_ASCII",
    "SPY_HEX",
    "ADDR_MIN",
    "ADDR_MAX",
    "READ_TMO_MS_MIN",
    "READ_TMO_MS_MAX",
    "QUERY_EXPLICIT_READ",
    "QUERY_AUTO",
    "__version__",
]
