"""
rf_bench.rtlsdr — RTL-SDR receiver driver for bench automation.

Supported hardware:
  RTL-SDR Blog v3 (R820T2 tuner), RTL-SDR Blog v4 (R828D tuner, 1 PPM TCXO,
  bias tee), and most generic RTL2832U-based dongles.

Typical usage::

    from rf_bench.rtlsdr import RTLSDR, RTLSDRError

    with RTLSDR() as sdr:
        sdr.set_center_freq(144_390_000)
        sdr.set_sample_rate(2_400_000)
        sdr.set_gain(30)
        iq = sdr.capture_iq(262_144)
        freq_hz, power_db = sdr.power_spectrum(iq, rbw_hz=1000)

    # Streaming
    with RTLSDR() as sdr:
        sdr.set_center_freq(1_090_000_000)
        sdr.set_sample_rate(2_000_000)
        for block in sdr.stream_iq(block_size=65_536):
            decode(block)
            if done:
                break
        sdr.stop_stream()

    # Device enumeration
    for dev in RTLSDR.find_devices():
        print(dev)   # {'index': 0, 'serial': '00000001', 'name': '...'}
"""

from .rtlsdr import RTLSDR, RTLSDRError, RTLSDRBusyError

__all__ = ["RTLSDR", "RTLSDRError", "RTLSDRBusyError"]
