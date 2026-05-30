"""
XL9535 16-bit I2C I/O port expander driver for relay board control.

Compatible with XL9535, PCA9535, and TCA9535 (identical register maps).

Register map:
    0x00  Input Port 0  (read)
    0x01  Input Port 1  (read)
    0x02  Output Port 0 (write; bit=1 → output pin high)
    0x03  Output Port 1 (write)
    0x04  Polarity Inversion 0
    0x05  Polarity Inversion 1
    0x06  Configuration Port 0 (bit=0 → output, bit=1 → input; default 0xFF)
    0x07  Configuration Port 1 (same)

I2C address range: 0x20–0x27 (set by A0/A1/A2 pins on the board).
"""

# XL9535 register addresses
_REG_INPUT_P0  = 0x00
_REG_INPUT_P1  = 0x01
_REG_OUTPUT_P0 = 0x02
_REG_OUTPUT_P1 = 0x03
_REG_CONFIG_P0 = 0x06
_REG_CONFIG_P1 = 0x07


class XL9535Error(RuntimeError):
    """Raised on XL9535 usage errors (invalid relay index, etc.)."""


class XL9535:
    """
    XL9535 16-bit I2C I/O port expander driver for relay board control.

    Most relay boards using ULN2803 are active-HIGH (active_high=True, default):
    writing 1 to an output pin energizes the relay coil.
    Boards using direct NPN drivers may be active-LOW; set active_high=False.

    Supports 4, 8, or 16 relay boards.  num_relays limits which relay indices
    are accessible and guards against accidentally toggling spare GPIO pins.

    Parameters
    ----------
    bp : BusPirate
        Bus Pirate instance, already configured for I2C
        (``bp.i2c_configure()`` must have been called).
    i2c_addr : int
        7-bit I2C address of the XL9535 (0x20–0x27).  Determined by the
        A0/A1/A2 jumper pins on the relay board.
    active_high : bool
        True  — output bit 1 energizes relay (ULN2803-based boards).
        False — output bit 0 energizes relay (direct NPN driver boards).
    num_relays : int
        Number of relays present (4, 8, or 16).  Relay indices are
        0 .. num_relays-1.  set() raises XL9535Error for out-of-range indices.

    Usage
    -----
    Preferred: use as a context manager so all_off() is called on exit::

        with XL9535(bp, i2c_addr=0x20, num_relays=16) as relay:
            relay.set(0, True)
            relay.close_only(3)

    The Bus Pirate I2C mode must be entered before constructing XL9535, and
    should be exited after::

        bp.i2c_configure(speed_hz=100_000)
        relay = XL9535(bp)
        ...
        relay.all_off()
        bp.i2c_exit()
    """

    def __init__(self, bp, i2c_addr: int = 0x20,
                 active_high: bool = True, num_relays: int = 16):
        if not (0x20 <= i2c_addr <= 0x27):
            raise XL9535Error(
                f"Invalid I2C address 0x{i2c_addr:02X}: "
                "XL9535 addresses are 0x20–0x27"
            )
        if num_relays not in (4, 8, 16):
            raise XL9535Error(
                f"num_relays must be 4, 8, or 16 (got {num_relays})"
            )
        self._bp = bp
        self._addr = i2c_addr
        self._active_high = active_high
        self._num_relays = num_relays
        self._mask = (1 << num_relays) - 1  # valid bit mask
        self._state = 0                     # 16-bit logical relay state (1 = energized)
        self.configure_outputs()
        self.all_off()

    # ------------------------------------------------------------------
    # Low-level register I/O
    # ------------------------------------------------------------------

    def _write_outputs(self) -> None:
        """Write current logical state to both Output Port registers."""
        # Port 0 = bits 0-7; Port 1 = bits 8-15
        lo = self._state & 0xFF
        hi = (self._state >> 8) & 0xFF
        if not self._active_high:
            # Invert so that logical 1 (energized) drives the output LOW
            lo = (~lo) & 0xFF
            hi = (~hi) & 0xFF
        # Single I2C transaction: reg=0x02, data=[port0, port1]
        self._bp.i2c_write(self._addr, [_REG_OUTPUT_P0, lo, hi])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def configure_outputs(self) -> None:
        """Configure all I/O pins as outputs (write 0x00 to both Config registers).

        Called automatically by __init__.  Call again if the chip has been
        power-cycled without reinitialising the XL9535 object.
        """
        # Single transaction: reg=0x06, data=[config_p0=0x00, config_p1=0x00]
        self._bp.i2c_write(self._addr, [_REG_CONFIG_P0, 0x00, 0x00])

    def all_off(self) -> None:
        """De-energize all relays (safe state).

        Sets the internal state to 0 and writes to both output registers.
        Also called automatically by __exit__.
        """
        self._state = 0
        self._write_outputs()

    def set(self, relay_num: int, energize: bool) -> None:
        """Set one relay.

        Parameters
        ----------
        relay_num : int
            Relay index, 0 .. num_relays-1.
        energize : bool
            True to energize (close) the relay; False to de-energize (open).

        Raises
        ------
        XL9535Error
            If relay_num is outside the valid range.
        """
        if not (0 <= relay_num < self._num_relays):
            raise XL9535Error(
                f"relay_num {relay_num} out of range "
                f"[0, {self._num_relays - 1}]"
            )
        if energize:
            self._state |= (1 << relay_num)
        else:
            self._state &= ~(1 << relay_num)
        self._state &= self._mask
        self._write_outputs()

    def set_all(self, bitmask: int) -> None:
        """Set all relays from a 16-bit bitmask.

        Bit N = 1 energizes relay N; bit N = 0 de-energizes relay N.
        Bits above num_relays-1 are masked off (ignored).

        Parameters
        ----------
        bitmask : int
            16-bit relay state, LSB = relay 0.
        """
        self._state = bitmask & self._mask
        self._write_outputs()

    def close_only(self, relay_num: int) -> None:
        """De-energize all relays, then energize exactly one.

        Useful for relay-matrix or multiplexer applications where only
        one relay should be closed at a time.

        Parameters
        ----------
        relay_num : int
            Relay index, 0 .. num_relays-1.

        Raises
        ------
        XL9535Error
            If relay_num is outside the valid range.
        """
        if not (0 <= relay_num < self._num_relays):
            raise XL9535Error(
                f"relay_num {relay_num} out of range "
                f"[0, {self._num_relays - 1}]"
            )
        self._state = (1 << relay_num) & self._mask
        self._write_outputs()

    def get_all(self) -> int:
        """Return the current logical relay state as a 16-bit bitmask.

        Returns the driver's internal state (no I2C read-back).
        Bit N = 1 means relay N is currently energized.

        Returns
        -------
        int
            16-bit bitmask, LSB = relay 0.
        """
        return self._state

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.all_off()
