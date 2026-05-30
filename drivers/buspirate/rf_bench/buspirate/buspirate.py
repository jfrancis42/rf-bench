"""
Bus Pirate v3/v4/v5 binary-mode driver for rf-bench.

Supported:
  Bus Pirate v3 (all PCB revisions), v4
    Single USB CDC serial port via FTDI/PIC; appears as /dev/ttyUSB* on Linux.
    Uses BBIO1 legacy binary protocol.

  Bus Pirate v5 (RP2040)
    Exposes two USB CDC ACM ports:
      /dev/ttyACM0  terminal (text commands)
      /dev/ttyACM1  binary   (BPIO2 or legacy BBIO1)
    This driver uses the native BPIO2 FlatBuffers protocol on v5 which supports
    full I2C, SPI, and UART.  Connect BusPirate() to the binary port (ttyACM1).
    Use BusPirate.find_devices() to locate the correct port automatically.

Protocol references:
  BBIO1 (v3/v4):  https://docs.buspirate.com/docs/binmode-reference/
  BPIO2 (v5):     https://github.com/DangerousPrototypes/BusPirate5-firmware
"""

import math
import re
import struct
import time

import serial


# ── USB device identity constants ─────────────────────────────────────────────

_BP5_VID  = 0x1209
_BP5_PIDS = {0x7331, 0x7332}

# ── BBIO1 tokens ──────────────────────────────────────────────────────────────
_BBIO1 = b'BBIO1'
_SPI1  = b'SPI1'
_I2C1  = b'I2C1'
_ART1  = b'ART1'

_SPI_SPEEDS  = [30_000, 125_000, 250_000, 1_000_000,
                2_000_000, 2_600_000, 4_000_000, 8_000_000]
_I2C_SPEEDS  = [5_000, 50_000, 100_000, 400_000]
_UART_BAUDS  = [300, 1200, 2400, 4800, 9600, 19200, 31250, 38400, 57600, 115200]

# ── BPIO2 union type constants ────────────────────────────────────────────────
# Matches the union indices in bpio.fbs
_BPIO2_STATUS  = 1   # StatusRequest / StatusResponse
_BPIO2_CONFIG  = 2   # ConfigurationRequest / ConfigurationResponse
_BPIO2_DATA    = 3   # DataRequest / DataResponse


# ── exceptions ────────────────────────────────────────────────────────────────

class BusPirateError(RuntimeError):
    """Raised on protocol errors or unexpected Bus Pirate responses."""


class BusPirateVersionError(BusPirateError):
    """Raised when connected firmware is incompatible with this driver."""


# ─────────────────────────────────────────────────────────────────────────────
# BPIO2 PROTOCOL IMPLEMENTATION (Bus Pirate v5 native)
# ─────────────────────────────────────────────────────────────────────────────
#
# Wire format:
#   Each message is a FlatBuffer serialised with COBS framing.
#   Send:    cobs.encode(flatbuffer_bytes) + b'\x00'
#   Receive: read bytes until 0x00, then cobs.decode(bytes_without_zero)
#
# FlatBuffers schema:  bpio.fbs in DangerousPrototypes/BusPirate5-firmware
# RequestPacket:  { version_major=2, minimum_version_minor=2, contents (union) }
# ResponsePacket: { error?, contents (union) }
# ─────────────────────────────────────────────────────────────────────────────

def _bpio2_encode(fb_bytes: bytes) -> bytes:
    """Wrap FlatBuffer bytes in COBS framing (includes trailing 0x00 delimiter)."""
    from cobs import cobs
    return cobs.encode(fb_bytes) + b'\x00'


def _bpio2_decode(cobs_frame: bytes) -> bytes:
    """Decode a COBS frame (without the trailing 0x00 delimiter)."""
    from cobs import cobs
    return cobs.decode(cobs_frame)


# ── FlatBuffer builder helpers ────────────────────────────────────────────────

def _fb_status_request() -> bytes:
    """Build a StatusRequest packet (queries all status)."""
    import flatbuffers
    b = flatbuffers.Builder(64)
    b.StartObject(1)               # StatusRequest: 1 field (query vector)
    # skip query → firmware returns all status by default
    status_req = b.EndObject()
    _fb_finish_request(b, _BPIO2_STATUS, status_req)
    return bytes(b.Output())


def _fb_config_request(
    mode: str | None = None,
    speed: int | None = None,
    clock_polarity: bool = False,
    clock_phase: bool = False,
    bitorder_msb: bool = True,
    pullup_enable: bool = False,
    pullup_disable: bool = False,
    psu_enable: bool = False,
    psu_disable: bool = False,
) -> bytes:
    """Build a ConfigurationRequest packet."""
    import flatbuffers
    b = flatbuffers.Builder(256)

    mode_str_off  = b.CreateString(mode) if mode else None
    mode_cfg_off  = None
    if speed is not None or clock_polarity or clock_phase:
        # ModeConfiguration table (13 fields in schema order)
        # slot 0: speed(uint32=20000), 1: data_bits(uint8=8), 2: parity(bool),
        # 3: stop_bits(uint8=1), 4: flow_control(bool), 5: signal_inversion(bool),
        # 6: clock_stretch(bool), 7: clock_polarity(bool), 8: clock_phase(bool),
        # 9: chip_select_idle(bool=true), 10: submode(uint8), 11: tx_mod(uint32),
        # 12: rx_sensor(uint8)
        b.StartObject(13)
        if speed is not None:
            b.PrependUint32Slot(0, speed, 20000)
        if clock_polarity:
            b.PrependBoolSlot(7, True, False)
        if clock_phase:
            b.PrependBoolSlot(8, True, False)
        mode_cfg_off = b.EndObject()

    # ConfigurationRequest (20 fields in schema order)
    # 0:mode 1:mode_cfg 2:bitorder_msb 3:bitorder_lsb 4:psu_disable 5:psu_enable
    # 6:psu_set_mv 7:psu_set_ma 8:pullup_disable 9:pullup_enable
    # 10:io_dir_mask 11:io_dir 12:io_val_mask 13:io_val
    # 14:led_resume 15:led_color 16:print_string 17:hw_bootloader
    # 18:hw_reset 19:hw_selftest
    b.StartObject(20)
    if mode_str_off is not None:
        b.PrependUOffsetTRelativeSlot(0, mode_str_off, 0)
    if mode_cfg_off is not None:
        b.PrependUOffsetTRelativeSlot(1, mode_cfg_off, 0)
    if bitorder_msb and mode:
        b.PrependBoolSlot(2, True, False)
    if psu_disable:
        b.PrependBoolSlot(4, True, False)
    if psu_enable:
        b.PrependBoolSlot(5, True, False)
    if pullup_disable:
        b.PrependBoolSlot(8, True, False)
    if pullup_enable:
        b.PrependBoolSlot(9, True, False)
    config_req = b.EndObject()

    _fb_finish_request(b, _BPIO2_CONFIG, config_req)
    return bytes(b.Output())


def _fb_data_request(
    start_main:  bool  = False,
    start_alt:   bool  = False,
    data_write:  bytes = b'',
    bytes_read:  int   = 0,
    stop_main:   bool  = False,
    stop_alt:    bool  = False,
) -> bytes:
    """Build a DataRequest packet (I2C/SPI/UART transaction)."""
    import flatbuffers
    b = flatbuffers.Builder(len(data_write) + 64)

    write_vec_off = None
    if data_write:
        b.StartVector(1, len(data_write), 1)
        for byte in reversed(data_write):
            b.PrependByte(byte)
        write_vec_off = b.EndVector()

    # DataRequest: slot 0:start_main 1:start_alt 2:data_write 3:bytes_read
    #              4:stop_main 5:stop_alt
    b.StartObject(6)
    if start_main:
        b.PrependBoolSlot(0, True, False)
    if start_alt:
        b.PrependBoolSlot(1, True, False)
    if write_vec_off is not None:
        b.PrependUOffsetTRelativeSlot(2, write_vec_off, 0)
    if bytes_read:
        b.PrependUint16Slot(3, bytes_read, 0)
    if stop_main:
        b.PrependBoolSlot(4, True, False)
    if stop_alt:
        b.PrependBoolSlot(5, True, False)
    data_req = b.EndObject()

    _fb_finish_request(b, _BPIO2_DATA, data_req)
    return bytes(b.Output())


def _fb_finish_request(b, union_type: int, content_off: int) -> None:
    """Wrap a content table in a RequestPacket and finish the FlatBuffer.

    RequestPacket fields:
      slot 0: version_major (uint8)
      slot 1: minimum_version_minor (uint16)
      slot 2: contents_type (byte, union discriminant)
      slot 3: contents (UOffset to content table)
    """
    b.StartObject(4)
    b.PrependUint8Slot(0, 2, 0)                              # version_major = 2
    b.PrependUint16Slot(1, 2, 0)                             # min_version_minor = 2
    b.PrependByteSlot(2, union_type, 0)                      # union type
    b.PrependUOffsetTRelativeSlot(3, content_off, 0)         # union value
    root = b.EndObject()
    b.Finish(root)


# ── FlatBuffer response reader ────────────────────────────────────────────────

class _FBReader:
    """Minimal FlatBuffers reader for a BPIO2 ResponsePacket."""

    def __init__(self, data: bytes):
        self._buf = data
        root_off = struct.unpack_from('<I', data, 0)[0]
        self._root = root_off
        self._vt, self._vs = self._vtable(root_off)

    def _vtable(self, tab):
        soffset = struct.unpack_from('<i', self._buf, tab)[0]
        vt = tab - soffset
        vs = struct.unpack_from('<H', self._buf, vt)[0]
        return vt, vs

    def _foff(self, tab, vt, vs, slot):
        """Vtable field offset for slot N in table at tab."""
        idx = 4 + 2 * slot
        if idx >= vs:
            return 0
        return struct.unpack_from('<H', self._buf, vt + idx)[0]

    def _byte(self, tab, vt, vs, slot, default=0):
        off = self._foff(tab, vt, vs, slot)
        return struct.unpack_from('<B', self._buf, tab + off)[0] if off else default

    def _uint16(self, tab, vt, vs, slot, default=0):
        off = self._foff(tab, vt, vs, slot)
        return struct.unpack_from('<H', self._buf, tab + off)[0] if off else default

    def _uint32(self, tab, vt, vs, slot, default=0):
        off = self._foff(tab, vt, vs, slot)
        return struct.unpack_from('<I', self._buf, tab + off)[0] if off else default

    def _string(self, tab, vt, vs, slot):
        off = self._foff(tab, vt, vs, slot)
        if not off:
            return None
        fp = tab + off
        sp = fp + struct.unpack_from('<I', self._buf, fp)[0]
        sl = struct.unpack_from('<I', self._buf, sp)[0]
        return self._buf[sp+4:sp+4+sl].decode('utf-8', errors='replace')

    def _bytes_vec(self, tab, vt, vs, slot):
        off = self._foff(tab, vt, vs, slot)
        if not off:
            return b''
        fp = tab + off
        vp = fp + struct.unpack_from('<I', self._buf, fp)[0]
        vl = struct.unpack_from('<I', self._buf, vp)[0]
        return bytes(self._buf[vp+4:vp+4+vl])

    def _nested(self, tab, vt, vs, slot):
        """Return (tab, vt, vs) for a nested table field, or None if absent."""
        off = self._foff(tab, vt, vs, slot)
        if not off:
            return None
        fp = tab + off
        nt = fp + struct.unpack_from('<I', self._buf, fp)[0]
        nvt, nvs = self._vtable(nt)
        return nt, nvt, nvs

    # ── ResponsePacket fields ─────────────────────────────────────────────────
    # slot 0: error (string)
    # slot 1: contents_type (byte, union discriminant)
    # slot 2: contents (nested table)

    @property
    def error(self) -> str | None:
        return self._string(self._root, self._vt, self._vs, 0)

    @property
    def contents_type(self) -> int:
        return self._byte(self._root, self._vt, self._vs, 1, 0)

    def _contents(self):
        return self._nested(self._root, self._vt, self._vs, 2)

    # ── ConfigurationResponse ─────────────────────────────────────────────────
    # slot 0: error (string)

    @property
    def config_error(self) -> str | None:
        ct = self._contents()
        if ct is None:
            return None
        return self._string(*ct, 0)

    # ── DataResponse ─────────────────────────────────────────────────────────
    # slot 0: error (string)
    # slot 1: data_read ([ubyte])
    # slot 2: is_async (bool)

    @property
    def data_error(self) -> str | None:
        ct = self._contents()
        if ct is None:
            return None
        return self._string(*ct, 0)

    @property
    def data_read(self) -> bytes:
        ct = self._contents()
        if ct is None:
            return b''
        return self._bytes_vec(*ct, 1)

    # ── StatusResponse ────────────────────────────────────────────────────────
    # slot 0: error
    # slot 5: version_firmware_major (uint8)
    # slot 6: version_firmware_minor (uint8)
    # slot 7: version_firmware_git_hash (string)
    # slot 10: mode_current (string)

    @property
    def status_error(self) -> str | None:
        ct = self._contents()
        if ct is None:
            return None
        return self._string(*ct, 0)

    @property
    def firmware_major(self) -> int:
        ct = self._contents()
        return self._byte(*ct, 5) if ct else 0

    @property
    def firmware_minor(self) -> int:
        ct = self._contents()
        return self._byte(*ct, 6) if ct else 0

    @property
    def firmware_git_hash(self) -> str | None:
        ct = self._contents()
        return self._string(*ct, 7) if ct else None

    @property
    def mode_current(self) -> str | None:
        ct = self._contents()
        return self._string(*ct, 10) if ct else None


# ── BPIO2 session ─────────────────────────────────────────────────────────────

class _BPIO2Session:
    """
    Bus Pirate v5 BPIO2 (DirtyProto) protocol session.

    Activated via the terminal port (ttyACM0) and communicates on the binary
    port (ttyACM1) using FlatBuffers-over-COBS framing.

    Exposes the same high-level interface as the BBIO1 path in BusPirate:
    set_pullups, set_power, i2c_configure / write / read / scan / exit,
    spi_configure / transfer / exit.
    """

    def __init__(self, binary_port: str, timeout: float = 2.0):
        self._binary_port = binary_port
        self._timeout     = timeout
        self._mode        = 'idle'   # 'idle' | 'i2c' | 'spi' | 'uart'

        self._ser = serial.Serial(binary_port, baudrate=115200, timeout=timeout)

        if not self._probe():
            self._ser.close()
            # Infer the terminal port name for the error message (ttyACM1 → ttyACM0)
            m = re.match(r'^(.*?)(\d+)$', binary_port)
            term = (m.group(1) + str(int(m.group(2)) - 1)) if (m and int(m.group(2)) > 0) else '?'
            raise BusPirateError(
                f"BPIO2 not active on {binary_port!r}.\n"
                "One-time setup required:\n"
                f"  1. Connect to the terminal port:  screen {term} 115200\n"
                "  2. Type: binmode  then select '2. BPIO2 flatbuffer interface'\n"
                "  3. Save as default when prompted\n"
                "  4. Re-run this script (BPIO2 persists across reboots)"
            )

    # ── probe ─────────────────────────────────────────────────────────────────

    def _probe(self) -> bool:
        """Return True if BPIO2 is responding on the binary port."""
        try:
            self._ser.reset_input_buffer()
            self._ser.write(_bpio2_encode(_fb_status_request()))
            raw = self._ser.read_until(b'\x00', size=2048)
            if raw and raw[-1:] == b'\x00':
                data = _bpio2_decode(raw[:-1])
                reader = _FBReader(data)
                return reader.contents_type in (_BPIO2_STATUS, _BPIO2_CONFIG, _BPIO2_DATA)
        except Exception:
            pass
        return False

    # ── packet I/O ────────────────────────────────────────────────────────────

    def _send_recv(self, fb_bytes: bytes) -> _FBReader:
        """Send a FlatBuffer packet and return the parsed response."""
        self._ser.write(_bpio2_encode(fb_bytes))
        raw = self._ser.read_until(b'\x00', size=2048)
        if not raw or raw[-1:] != b'\x00':
            raise BusPirateError("BPIO2: response timeout (no terminator received)")
        data = _bpio2_decode(raw[:-1])
        return _FBReader(data)

    def _transact(self, start_main=False, start_alt=False,
                  data_write=b'', bytes_read=0,
                  stop_main=False, stop_alt=False) -> bytes:
        """Execute a DataRequest and return read bytes (raises on device error)."""
        resp = self._send_recv(_fb_data_request(
            start_main=start_main, start_alt=start_alt,
            data_write=data_write, bytes_read=bytes_read,
            stop_main=stop_main, stop_alt=stop_alt,
        ))
        if resp.contents_type != _BPIO2_DATA:
            raise BusPirateError(
                f"BPIO2: unexpected response type {resp.contents_type} "
                f"(expected DATA={_BPIO2_DATA})")
        err = resp.data_error
        if err:
            raise BusPirateError(f"BPIO2 transaction error: {err}")
        return resp.data_read

    def _configure(self, **kwargs) -> None:
        """Send a ConfigurationRequest and raise on error."""
        resp = self._send_recv(_fb_config_request(**kwargs))
        if resp.contents_type != _BPIO2_CONFIG:
            raise BusPirateError(
                f"BPIO2: unexpected response type {resp.contents_type} "
                f"(expected CONFIG={_BPIO2_CONFIG})")
        err = resp.config_error
        if err:
            raise BusPirateError(f"BPIO2 configuration error: {err}")

    # ── identification ────────────────────────────────────────────────────────

    def identify(self) -> str:
        try:
            resp = self._send_recv(_fb_status_request())
            if resp.contents_type == _BPIO2_STATUS:
                major = resp.firmware_major
                minor = resp.firmware_minor
                h = resp.firmware_git_hash or ''
                return f'Bus Pirate v5 fw{major}.{minor}' + (f' ({h[:7]})' if h else '')
        except Exception:
            pass
        return 'Bus Pirate v5'

    # ── peripheral control ────────────────────────────────────────────────────

    def set_pullups(self, on: bool) -> None:
        self._configure(pullup_enable=on, pullup_disable=not on)

    def set_power(self, on: bool) -> None:
        self._configure(psu_enable=on, psu_disable=not on)

    # ── I2C ───────────────────────────────────────────────────────────────────

    def i2c_configure(self, speed_hz: int = 100_000) -> None:
        """Configure I2C mode at the given clock speed."""
        self._configure(mode='i2c', speed=speed_hz, bitorder_msb=True)
        self._mode = 'i2c'

    def i2c_write(self, addr: int, data) -> None:
        """Write bytes to an I2C device (START → addr_W → data → STOP)."""
        write_bytes = bytes([addr << 1]) + bytes(data)
        self._transact(start_main=True, data_write=write_bytes, stop_main=True)

    def i2c_read(self, addr: int, reg: int, length: int) -> bytes:
        """Read bytes from register via I2C combined write/read transaction.

        Two-packet sequence required for BPIO2:
          Packet 1: START → addr_W → reg  (no STOP — holds bus)
          Packet 2: START (RESTART) → addr_R → data[N] → STOP
        """
        self._transact(start_main=True,
                       data_write=bytes([addr << 1, reg]),
                       stop_main=False)
        return self._transact(start_main=True,
                              data_write=bytes([addr << 1 | 1]),
                              bytes_read=length,
                              stop_main=True)

    def i2c_read_raw(self, addr: int, length: int) -> bytes:
        """Read bytes from an I2C device without writing a register address."""
        return self._transact(start_main=True,
                              data_write=bytes([addr << 1 | 1]),
                              bytes_read=length,
                              stop_main=True)

    def i2c_scan(self) -> list:
        """Scan I2C bus; return list of 7-bit addresses that responded with ACK."""
        found = []
        for addr in range(0x08, 0x78):
            try:
                self._transact(start_main=True,
                               data_write=bytes([addr << 1]),
                               stop_main=True)
                found.append(addr)
            except BusPirateError:
                pass  # NACK = no device at this address
        return found

    def i2c_exit(self) -> None:
        self._mode = 'idle'

    # ── SPI ───────────────────────────────────────────────────────────────────

    def spi_configure(self, speed_hz: int = 1_000_000,
                      cpol: int = 0, cpha: int = 0,
                      output_pushpull: bool = True) -> None:
        """Configure SPI mode."""
        self._configure(
            mode='spi', speed=speed_hz,
            clock_polarity=bool(cpol), clock_phase=bool(cpha),
            bitorder_msb=True,
        )
        self._mode = 'spi'

    def spi_transfer(self, data) -> list:
        """Assert CS, transfer data full-duplex, deassert CS."""
        tx = bytes(data)
        rx = self._transact(
            start_main=True, data_write=tx, bytes_read=len(tx), stop_main=True,
        )
        return list(rx)

    def spi_write(self, data) -> None:
        self.spi_transfer(data)

    def spi_cs_low(self) -> None:
        self._transact(start_main=True)

    def spi_cs_high(self) -> None:
        self._transact(stop_main=True)

    def spi_raw_transfer(self, data) -> list:
        return list(self._transact(data_write=bytes(data), bytes_read=len(data)))

    def spi_exit(self) -> None:
        self._mode = 'idle'

    # ── UART ──────────────────────────────────────────────────────────────────

    def uart_configure(self, baud: int = 9600, data_bits: int = 8,
                       parity: str = 'N', stop_bits: int = 1,
                       output_pushpull: bool = True) -> None:
        """Configure UART mode."""
        self._configure(mode='uart', speed=baud, bitorder_msb=True)
        self._mode = 'uart'

    def uart_write(self, data: bytes) -> None:
        self._transact(data_write=bytes(data))

    def uart_read(self, length: int, timeout_s: float = 1.0) -> bytes:
        old = self._ser.timeout
        self._ser.timeout = timeout_s
        try:
            return self._transact(bytes_read=length)
        finally:
            self._ser.timeout = old

    def uart_exit(self) -> None:
        self._mode = 'idle'

    # ── cleanup ───────────────────────────────────────────────────────────────

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC BusPirate CLASS
# ─────────────────────────────────────────────────────────────────────────────

class BusPirate:
    """
    Bus Pirate v3/v4/v5 driver over USB CDC serial (pyserial).

    For v3/v4: uses the legacy BBIO1 binary protocol on a single USB serial port.

    For v5: uses the native BPIO2 (DirtyProto) FlatBuffers protocol on the binary
    port (ttyACM1).  BPIO2 is activated automatically via the terminal port
    (ttyACM0); connect BusPirate() to the binary port only.

    Context manager usage::

        with BusPirate("/dev/ttyUSB1") as bp:          # v3/v4
            bp.spi_configure(speed_hz=1_000_000)
            rx = bp.spi_transfer([0x40, 0x00, 0x00])

        with BusPirate("/dev/ttyACM1") as bp:          # v5 — binary port
            bp.set_pullups(True)
            bp.i2c_configure(speed_hz=100_000)
            bp.i2c_write(0x60, [0x03, 0x00])
            data = bp.i2c_read(0x60, reg=0x00, length=2)

    Use :meth:`find_devices` to locate the correct port automatically::

        devs = BusPirate.find_devices()
        binary = next(d for d in devs if d['role'] in ('binary', 'combined'))
        with BusPirate(binary['port']) as bp:
            ...
    """

    DEFAULT_PORT    = '/dev/ttyUSB1'   # v3/v4 default
    DEFAULT_PORT_V5 = '/dev/ttyACM1'   # v5 binary port default
    DEFAULT_BAUD    = 115200
    DEFAULT_TIMEOUT = 2.0

    def __init__(self, port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD,
                 timeout: float = DEFAULT_TIMEOUT):
        """
        Args:
            port:    Serial port path.  For v5 use the binary port (ttyACM1).
            baud:    Baud rate (ignored for v5 CDC ACM; included for compat).
            timeout: Serial read timeout in seconds.
        """
        self._port          = port
        self._baud          = baud
        self._timeout       = timeout
        self._mode          = None
        self._periph        = 0x00
        self._hw_version    = self._detect_hw_version(port)
        self._bpio2: _BPIO2Session | None = None

        if self._hw_version == 5:
            self._bpio2 = _BPIO2Session(port, timeout)
            self._mode  = 'bpio2'
            self._ser   = self._bpio2._ser   # share the serial handle
        else:
            self._ser = serial.Serial(port, baudrate=baud, timeout=timeout)
            self._enter_bbio()

    # ── hardware version detection ────────────────────────────────────────────

    @staticmethod
    def _detect_hw_version(port: str) -> int | None:
        try:
            from serial.tools import list_ports
            for info in list_ports.comports():
                if info.device == port:
                    if (getattr(info, 'vid', None) == _BP5_VID and
                            getattr(info, 'pid', None) in _BP5_PIDS):
                        return 5
                    break
        except Exception:
            pass
        return None

    @classmethod
    def find_devices(cls) -> list:
        """
        Scan all serial ports and return a list of dicts for each Bus Pirate found.

        Each dict has keys: ``port``, ``model``, ``role``
        (``'binary'``, ``'terminal'``, ``'combined'``, or ``'unknown'``).

        For v5, connect to the ``'binary'`` port.
        For v3/v4, the single port has role ``'combined'``.
        """
        try:
            from serial.tools import list_ports
        except ImportError:
            return []

        devices = []
        for info in list_ports.comports():
            vid = getattr(info, 'vid', None)
            pid = getattr(info, 'pid', None)

            if vid == _BP5_VID and pid in _BP5_PIDS:
                desc_upper = (info.description or '').upper()
                if 'BIN' in desc_upper:
                    role = 'binary'
                elif 'CDC' in desc_upper or 'TERMINAL' in desc_upper:
                    role = 'terminal'
                else:
                    loc  = getattr(info, 'location', '') or ''
                    role = ('binary'   if ':1.2' in loc else
                            'terminal' if ':1.0' in loc else 'unknown')
                devices.append({'port': info.device, 'model': 'Bus Pirate v5', 'role': role})
            elif vid is not None:
                desc = (info.description or '').lower()
                if 'bus pirate' in desc:
                    devices.append({
                        'port':  info.device,
                        'model': info.description or 'Bus Pirate v3/v4',
                        'role':  'combined',
                    })

        devices.sort(key=lambda d: 0 if d['role'] in ('binary', 'combined') else 1)
        return devices

    # ── BBIO1 entry (v3/v4 only) ──────────────────────────────────────────────

    def _enter_bbio(self) -> None:
        self._ser.write(b'\x0f')
        time.sleep(0.1)
        self._ser.reset_input_buffer()

        buf = b''
        for _ in range(25):
            self._ser.write(b'\x00')
            time.sleep(0.01)
            buf += self._ser.read(self._ser.in_waiting or 0)
            if _BBIO1 in buf:
                self._mode = 'bbio'
                time.sleep(0.05)
                self._ser.reset_input_buffer()
                return

        raise BusPirateError(
            f"Cannot enter binary mode on {self._port!r}. "
            "Verify the Bus Pirate is connected and not in use. "
            "For v5, connect to the binary port (ttyACM1), not ttyACM0."
        )

    def _assert_bbio(self) -> None:
        if self._mode != 'bbio':
            raise BusPirateError(
                f"Must be in BBIO mode (currently '{self._mode}'). "
                "Call the appropriate exit() method first."
            )

    def _assert_mode(self, required: str) -> None:
        if self._mode != required:
            raise BusPirateError(
                f"Must be in {required!r} mode (currently {self._mode!r})."
            )

    # ── identification ────────────────────────────────────────────────────────

    def identify(self) -> str:
        """Return the firmware version string, e.g. ``'Bus Pirate v3.6'``."""
        if self._bpio2:
            return self._bpio2.identify()

        self._ser.write(b'\x0f')
        time.sleep(0.2)
        self._ser.reset_input_buffer()
        self._ser.write(b'i\r\n')
        time.sleep(0.3)
        raw  = self._ser.read(self._ser.in_waiting or 0)
        text = raw.decode('ascii', errors='replace')
        self._mode = None
        self._enter_bbio()
        for line in text.splitlines():
            s = line.strip()
            if 'Bus Pirate' in s:
                return s
        return text.strip()[:80] or 'Bus Pirate (version unknown)'

    # ── peripheral control ────────────────────────────────────────────────────

    def set_power(self, on: bool) -> None:
        """Enable or disable the on-board 3.3V and 5V power supplies."""
        if self._bpio2:
            self._bpio2.set_power(on)
        else:
            self._set_periph_bit(3, on)

    def set_pullups(self, on: bool) -> None:
        """Enable or disable the on-board I2C pull-up resistors."""
        if self._bpio2:
            self._bpio2.set_pullups(on)
        else:
            self._set_periph_bit(2, on)

    def set_aux(self, high: bool) -> None:
        """Drive the AUX pin high (True) or low (False)."""
        if self._bpio2:
            raise BusPirateError(
                "set_aux() is not yet implemented for Bus Pirate v5 BPIO2. "
                "Use io_direction/io_value ConfigurationRequest fields directly."
            )
        self._set_periph_bit(1, high)

    def _set_periph_bit(self, bit: int, value: bool) -> None:
        self._assert_bbio()
        if value:
            self._periph |= (1 << bit)
        else:
            self._periph &= ~(1 << bit) & 0x0F
        cmd = 0x40 | (self._periph & 0x0F)
        self._ser.write(bytes([cmd]))
        ack = self._ser.read(1)
        if ack != b'\x01':
            raise BusPirateError(f"Peripheral control failed: expected 0x01, got {ack!r}")

    # ── SPI ───────────────────────────────────────────────────────────────────

    def spi_configure(self, speed_hz: int = 1_000_000,
                      cpol: int = 0, cpha: int = 0,
                      output_pushpull: bool = True) -> None:
        """
        Enter SPI mode and configure clock speed and polarity.

        Args:
            speed_hz:        Clock rate.  v3/v4: snapped to 30k/125k/250k/1M/2M/
                             2.6M/4M/8MHz.  v5: arbitrary (firmware selects nearest).
            cpol:            Clock polarity: 0=idle low, 1=idle high.
            cpha:            Clock phase: 0=leading, 1=trailing.
            output_pushpull: True=3.3V push-pull; False=HiZ open-drain (v3/v4 only).
        """
        if self._bpio2:
            self._bpio2.spi_configure(speed_hz, cpol, cpha, output_pushpull)
            self._mode = 'spi'
            return

        self._assert_bbio()
        self._ser.write(b'\x01')
        resp = self._ser.read(4)
        if resp != _SPI1:
            raise BusPirateError(f"SPI mode entry failed: expected b'SPI1', got {resp!r}")
        self._mode = 'spi'

        code = min(range(len(_SPI_SPEEDS)), key=lambda i: abs(_SPI_SPEEDS[i] - speed_hz))
        self._ser.write(bytes([0x60 | code]))
        if self._ser.read(1) != b'\x01':
            raise BusPirateError("SPI speed configuration failed")

        cfg  = 0x80
        cfg |= 0x08 if output_pushpull else 0x00
        cfg |= 0x04 if cpol            else 0x00
        cfg |= 0x00 if cpha            else 0x02
        self._ser.write(bytes([cfg]))
        if self._ser.read(1) != b'\x01':
            raise BusPirateError("SPI configuration failed")

    def spi_transfer(self, data) -> list:
        """Assert CS, transfer bytes full-duplex, deassert CS."""
        if self._bpio2:
            return self._bpio2.spi_transfer(data)

        self._assert_mode('spi')
        tx  = bytes(data)
        n   = len(tx)
        cmd = bytes([0x04]) + struct.pack('>HH', n, n) + tx
        self._ser.write(cmd)
        ack = self._ser.read(1)
        if ack != b'\x01':
            raise BusPirateError(f"SPI transfer failed (ack={ack!r})")
        return list(self._ser.read(n))

    def spi_write(self, data) -> None:
        """Assert CS, write bytes, deassert CS.  Received bytes discarded."""
        if self._bpio2:
            self._bpio2.spi_write(data)
        else:
            self.spi_transfer(data)

    def spi_cs_low(self) -> None:
        """Manually assert CS."""
        if self._bpio2:
            self._bpio2.spi_cs_low()
        else:
            self._assert_mode('spi')
            self._ser.write(b'\x01')
            if self._ser.read(1) != b'\x01':
                raise BusPirateError("CS-low command failed")

    def spi_cs_high(self) -> None:
        """Manually deassert CS."""
        if self._bpio2:
            self._bpio2.spi_cs_high()
        else:
            self._assert_mode('spi')
            self._ser.write(b'\x02')
            if self._ser.read(1) != b'\x01':
                raise BusPirateError("CS-high command failed")

    def spi_raw_transfer(self, data) -> list:
        """Transfer bytes without toggling CS."""
        if self._bpio2:
            return self._bpio2.spi_raw_transfer(data)

        self._assert_mode('spi')
        tx  = list(data)
        rx  = []
        for i in range(0, len(tx), 16):
            chunk = tx[i:i + 16]
            n     = len(chunk)
            self._ser.write(bytes([0x10 | (n - 1)] + chunk))
            resp  = self._ser.read(1 + n)
            if resp[:1] != b'\x01':
                raise BusPirateError(f"SPI bulk write failed: {resp!r}")
            rx.extend(resp[1:])
        return rx

    def spi_exit(self) -> None:
        """Return to BBIO mode (v3/v4) or idle mode (v5)."""
        if self._bpio2:
            self._bpio2.spi_exit()
            self._mode = 'bpio2'
            return
        if self._mode == 'spi':
            self._ser.write(b'\x00')
            resp = self._ser.read(5)
            if resp == _BBIO1:
                self._mode = 'bbio'
            else:
                raise BusPirateError(f"SPI exit failed: {resp!r}")

    # ── I2C ───────────────────────────────────────────────────────────────────

    def i2c_configure(self, speed_hz: int = 100_000) -> None:
        """
        Enter I2C mode at the given clock speed.

        Args:
            speed_hz: Clock rate.  v3/v4: snapped to 5k/50k/100k/400kHz.
                      v5 BPIO2: arbitrary (firmware selects nearest).

        Note:
            For v3/v4, call ``set_pullups(True)`` before this while still in
            BBIO mode.  For v5, pull-ups are configured via ``set_pullups(True)``
            which can be called at any time.
        """
        if self._bpio2:
            self._bpio2.i2c_configure(speed_hz)
            self._mode = 'i2c'
            return

        self._assert_bbio()
        self._ser.write(b'\x02')
        resp = self._ser.read(4)
        if resp != _I2C1:
            raise BusPirateError(f"I2C mode entry failed: expected b'I2C1', got {resp!r}")
        self._mode = 'i2c'

        code = min(range(len(_I2C_SPEEDS)), key=lambda i: abs(_I2C_SPEEDS[i] - speed_hz))
        self._ser.write(bytes([0x60 | code]))
        if self._ser.read(1) != b'\x01':
            raise BusPirateError("I2C speed configuration failed")

    def _i2c_start(self) -> None:
        self._ser.write(b'\x02')
        if self._ser.read(1) != b'\x01':
            raise BusPirateError("I2C START failed")

    def _i2c_stop(self) -> None:
        self._ser.write(b'\x03')
        if self._ser.read(1) != b'\x01':
            raise BusPirateError("I2C STOP failed")

    def _i2c_write_byte(self, byte: int) -> bool:
        self._ser.write(bytes([0x10, byte & 0xFF]))
        resp = self._ser.read(2)
        if len(resp) < 2 or resp[0] != 0x01:
            raise BusPirateError(f"I2C write-byte command failed: {resp!r}")
        return resp[1] == 0x00

    def _i2c_read_byte(self, ack: bool = True) -> int:
        self._ser.write(b'\x04')
        val = self._ser.read(1)
        if not val:
            raise BusPirateError("I2C read byte: no data returned")
        self._ser.write(b'\x06' if ack else b'\x07')
        self._ser.read(1)
        return val[0]

    def i2c_write(self, addr: int, data) -> None:
        """
        Write bytes to an I2C device.

        Generates START, writes 7-bit *addr* (write), writes *data* bytes, STOP.
        Raises on any NACK.
        """
        if self._bpio2:
            self._bpio2.i2c_write(addr, data)
            return

        self._assert_mode('i2c')
        self._i2c_start()
        if not self._i2c_write_byte(addr << 1):
            self._i2c_stop()
            raise BusPirateError(f"I2C NACK on address 0x{addr:02X} (write)")
        for b in bytes(data):
            if not self._i2c_write_byte(b):
                self._i2c_stop()
                raise BusPirateError(f"I2C NACK writing 0x{b:02X} to device 0x{addr:02X}")
        self._i2c_stop()

    def i2c_read(self, addr: int, reg: int, length: int) -> bytes:
        """
        Read *length* bytes from register *reg* of I2C device at *addr*.

        Sequence: START → addr(W) → reg → RESTART → addr(R) → N bytes → STOP.
        """
        if self._bpio2:
            return self._bpio2.i2c_read(addr, reg, length)

        self._assert_mode('i2c')
        if length < 1:
            raise ValueError("length must be ≥ 1")
        self._i2c_start()
        if not self._i2c_write_byte(addr << 1):
            self._i2c_stop()
            raise BusPirateError(f"I2C NACK on addr 0x{addr:02X} (write phase)")
        if not self._i2c_write_byte(reg):
            self._i2c_stop()
            raise BusPirateError(f"I2C NACK on reg 0x{reg:02X} at 0x{addr:02X}")
        self._i2c_start()
        if not self._i2c_write_byte((addr << 1) | 0x01):
            self._i2c_stop()
            raise BusPirateError(f"I2C NACK on addr 0x{addr:02X} (read phase)")
        result = bytearray()
        for i in range(length):
            result.append(self._i2c_read_byte(ack=(i < length - 1)))
        self._i2c_stop()
        return bytes(result)

    def i2c_read_raw(self, addr: int, length: int) -> bytes:
        """Read *length* bytes without writing a register address."""
        if self._bpio2:
            return self._bpio2.i2c_read_raw(addr, length)

        self._assert_mode('i2c')
        self._i2c_start()
        if not self._i2c_write_byte((addr << 1) | 0x01):
            self._i2c_stop()
            raise BusPirateError(f"I2C NACK on addr 0x{addr:02X} (raw read)")
        result = bytearray()
        for i in range(length):
            result.append(self._i2c_read_byte(ack=(i < length - 1)))
        self._i2c_stop()
        return bytes(result)

    def i2c_scan(self) -> list:
        """Scan I2C bus; return list of 7-bit addresses that ACK'd."""
        if self._bpio2:
            return self._bpio2.i2c_scan()

        self._assert_mode('i2c')
        found = []
        for addr in range(0x08, 0x78):
            self._i2c_start()
            acked = self._i2c_write_byte(addr << 1)
            self._i2c_stop()
            if acked:
                found.append(addr)
        return found

    def i2c_exit(self) -> None:
        """Return to BBIO mode (v3/v4) or idle mode (v5)."""
        if self._bpio2:
            self._bpio2.i2c_exit()
            self._mode = 'bpio2'
            return
        if self._mode == 'i2c':
            self._ser.write(b'\x00')
            resp = self._ser.read(5)
            if resp == _BBIO1:
                self._mode = 'bbio'
            else:
                raise BusPirateError(f"I2C exit failed: {resp!r}")

    # ── UART ──────────────────────────────────────────────────────────────────

    def uart_configure(self, baud: int = 9600, data_bits: int = 8,
                       parity: str = 'N', stop_bits: int = 1,
                       output_pushpull: bool = True) -> None:
        """
        Enter UART mode and configure framing.

        Args:
            baud:           Target baud rate.  v3/v4: snapped to a supported value.
                            v5: arbitrary.
            data_bits:      8 or 9 (v3/v4 only for 9).
            parity:         'N' (none), 'E' (even), 'O' (odd), or 'M' (mark).
            stop_bits:      1 or 2.
            output_pushpull: 3.3V push-pull TX (v3/v4 only).
        """
        if self._bpio2:
            self._bpio2.uart_configure(baud, data_bits, parity, stop_bits, output_pushpull)
            self._mode = 'uart'
            return

        self._assert_bbio()
        self._ser.write(b'\x03')
        resp = self._ser.read(4)
        if resp != _ART1:
            raise BusPirateError(f"UART mode entry failed: expected b'ART1', got {resp!r}")
        self._mode = 'uart'

        code = min(range(len(_UART_BAUDS)), key=lambda i: abs(_UART_BAUDS[i] - baud))
        self._ser.write(bytes([0x60 | code]))
        if self._ser.read(1) != b'\x01':
            raise BusPirateError("UART baud rate configuration failed")

        parity_code = {'N': 0, 'E': 1, 'O': 2, 'M': 3}.get(parity.upper(), 0)
        fmt = (0x80
               | (0x10 if output_pushpull else 0x00)
               | (0x08 if stop_bits == 2  else 0x00)
               | ((parity_code & 0x03) << 1)
               | (0x01 if data_bits == 9  else 0x00))
        self._ser.write(bytes([fmt]))
        if self._ser.read(1) != b'\x01':
            raise BusPirateError("UART frame format configuration failed")

    def uart_write(self, data: bytes) -> None:
        """Write bytes to UART TX."""
        if self._bpio2:
            self._bpio2.uart_write(data)
            return
        self._assert_mode('uart')
        for i in range(0, len(data), 16):
            chunk = list(data[i:i + 16])
            n     = len(chunk)
            self._ser.write(bytes([0x10 | (n - 1)] + chunk))
            if self._ser.read(1) != b'\x01':
                raise BusPirateError("UART write failed")

    def uart_read(self, length: int, timeout_s: float = 1.0) -> bytes:
        """Read up to *length* bytes from UART RX within *timeout_s* seconds."""
        if self._bpio2:
            return self._bpio2.uart_read(length, timeout_s)
        self._assert_mode('uart')
        old = self._ser.timeout
        self._ser.timeout = timeout_s
        data = self._ser.read(length)
        self._ser.timeout = old
        return data

    def uart_exit(self) -> None:
        """Return to BBIO mode (v3/v4) or idle mode (v5)."""
        if self._bpio2:
            self._bpio2.uart_exit()
            self._mode = 'bpio2'
            return
        if self._mode == 'uart':
            self._ser.write(b'\x00')
            resp = self._ser.read(5)
            if resp == _BBIO1:
                self._mode = 'bbio'
            else:
                raise BusPirateError(f"UART exit failed: {resp!r}")

    # ── cleanup ───────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Return to interactive text terminal mode (v3/v4 only)."""
        if self._bpio2:
            return
        try:
            self._ser.write(b'\x0f')
            time.sleep(0.1)
        except Exception:
            pass
        self._mode = 'text'

    def close(self) -> None:
        """Close the connection."""
        if self._bpio2:
            self._bpio2.close()
        else:
            self.reset()
            try:
                self._ser.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self) -> str:
        hw = f'v{self._hw_version}' if self._hw_version else 'v3/v4'
        proto = 'BPIO2' if self._bpio2 else 'BBIO1'
        return f"BusPirate(port={self._port!r}, hw={hw}, proto={proto}, mode={self._mode!r})"
