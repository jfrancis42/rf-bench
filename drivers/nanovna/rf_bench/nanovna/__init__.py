"""
rf_bench.nanovna — NanoVNA / NanoVNA-H / NanoVNA-H4 driver.

Targets the ASCII text protocol used by the original edy555 firmware and the
hugen79 NanoVNA-H / NanoVNA-H4 forks (and DiSlord's NanoVNA-H4 builds). Speaks
to the device over the on-board USB CDC ACM serial port — typically
``/dev/ttyACM0`` on Linux.

The NanoVNA-V2 / S-A-A-2 / LiteVNA / NanoVNA-F V2 use a *different* binary
protocol (and are not supported by this driver). Future enhancement.

Typical usage::

    from rf_bench.nanovna import NanoVNA

    with NanoVNA("/dev/ttyACM0") as vna:
        print(vna.identify())
        vna.setup_sweep(1e6, 900e6, points=101)
        freqs = vna.get_frequencies()        # numpy float64 Hz
        s11   = vna.get_s11()                # numpy complex128
        s21   = vna.get_s21()                # numpy complex128

Calibration::

    vna.setup_sweep(1e6, 900e6, points=101)
    vna.cal_reset()
    input("Connect OPEN to port 0, press Enter..."); vna.cal_open()
    input("Connect SHORT to port 0, press Enter..."); vna.cal_short()
    input("Connect LOAD  to port 0, press Enter..."); vna.cal_load()
    input("Connect ISOLN (LOAD on port 1), press Enter..."); vna.cal_isoln()
    input("Connect THRU  (port 0 → port 1), press Enter..."); vna.cal_thru()
    vna.cal_done()
    vna.save_cal(0)   # save to flash slot 0
"""

from .nanovna import (
    NanoVNA,
    NanoVNAError,
    NanoVNATimeoutError,
    NanoVNAProtocolError,
    DEFAULT_PORT,
    DEFAULT_BAUDRATE,
    MAX_POINTS,
    NOMINAL_FUNDAMENTAL_DBM_HW_V3_1,
    NOMINAL_FUNDAMENTAL_DBM_HW_V2_3,
    NOMINAL_FUNDAMENTAL_DBM_HW_V2_2,
)

__all__ = [
    "NanoVNA",
    "NanoVNAError",
    "NanoVNATimeoutError",
    "NanoVNAProtocolError",
    "DEFAULT_PORT",
    "DEFAULT_BAUDRATE",
    "MAX_POINTS",
    "NOMINAL_FUNDAMENTAL_DBM_HW_V3_1",
    "NOMINAL_FUNDAMENTAL_DBM_HW_V2_3",
    "NOMINAL_FUNDAMENTAL_DBM_HW_V2_2",
]
