#!/usr/bin/env python3
"""
Protocol self-test for rf_bench.solsdr against solsdr's REAL servers.

Stands up solsdr's actual ControlAPIServer and IQStreamServer (imported from
the solsdr tree) backed by a fake radio, then drives them through the
rf_bench.solsdr network driver — proving the wire protocol matches, with no
SunSDR2 hardware and no ExpertSDR3.

Run:  python3 drivers/solsdr/test_solsdr.py
Requires the solsdr project at ~/Dropbox/build/solsdr (for its server classes).
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_SOLSDR = os.path.expanduser("~/Dropbox/build/solsdr")
if _SOLSDR not in sys.path:
    sys.path.insert(0, _SOLSDR)

import numpy as np

from rf_bench.solsdr import SolSDR, SolSDRError

try:
    from solsdr.api.control_api import ControlAPIServer
    from solsdr.api.iq_server import IQStreamServer
    HAVE_SOLSDR = True
except Exception as e:  # noqa: BLE001
    HAVE_SOLSDR = False
    _IMPORT_ERR = e


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class FakeRadio:
    """Minimal control object matching what ControlAPIServer expects."""
    streaming = 1
    s_meter = -72.5

    def __init__(self):
        self.freq = None
        self.mode = None
        self.calls = []

    def set_frequency(self, hz):
        self.calls.append(("freq", hz)); self.freq = hz; return True

    def set_mode(self, mode):
        self.calls.append(("mode", mode)); self.mode = mode; return True

    def set_ptt(self, on):
        return False

    def set_preamp(self, s):
        self.calls.append(("preamp", s)); return True

    def set_rit(self, hz):
        self.calls.append(("rit", hz)); return True

    def set_squelch(self, l):
        self.calls.append(("sql", l)); return True

    def set_agc(self, m):
        self.calls.append(("agc", m)); return True

    def set_nr(self, l):
        self.calls.append(("nr", l)); return True


def test_control_protocol():
    radio = FakeRadio()
    port = _free_port()
    srv = ControlAPIServer(radio, host="127.0.0.1", port=port, verbose=False)
    srv.start()
    time.sleep(0.3)
    try:
        sdr = SolSDR("127.0.0.1", control_port=port)
        assert sdr.ping(), "ping failed"

        sdr.set_frequency(14_074_000)
        assert radio.freq == 14_074_000, radio.freq
        assert sdr.get_frequency() == 14_074_000        # driver shadow

        sdr.set_mode("USB")
        assert radio.mode == "USB"
        assert sdr.get_mode() == "USB"

        sdr.set_preamp("-10")
        sdr.set_rit(250)
        sdr.set_squelch(0.3)
        sdr.set_agc("off")
        sdr.set_nr(0.5)
        sdr.set_rf_gain(-12)                             # -> nearest step -10
        kinds = [c[0] for c in radio.calls]
        for want in ("freq", "mode", "preamp", "rit", "sql", "agc", "nr"):
            assert want in kinds, f"{want} not seen in {radio.calls}"

        s = sdr.get_strength()
        assert abs(s - (-72.5)) < 0.2, s

        st = sdr.status()
        assert st["streaming"] == 1 and st["ptt"] is False, st

        # out-of-range must raise (driver-side check)
        try:
            sdr.set_frequency(500_000_000)
            assert False, "expected out-of-range error"
        except SolSDRError:
            pass

        # set_ptt / set_sample_rate must raise NotImplementedError (documented)
        for fn in (lambda: sdr.set_ptt(True), lambda: sdr.set_sample_rate(48000)):
            try:
                fn(); assert False, "expected NotImplementedError"
            except NotImplementedError:
                pass

        sdr.close()
        print("PASS control protocol: freq/mode/gain/rit/agc/nr/smeter/status, "
              "range-check, PTT + sample-rate guards")
    finally:
        srv.stop()


def test_iq_protocol():
    radio = FakeRadio()
    iq_port = _free_port()
    # Feed the IQ server a known tone via its publish() callback.
    iqs = IQStreamServer(host="127.0.0.1", port=iq_port, verbose=False)
    iqs.start(rate=39062.5, freq=14_074_000)
    time.sleep(0.2)

    stop = threading.Event()

    def pump():
        n = 200
        ph = 0.0
        dphi = 2 * np.pi * 1000.0 / 39062.5
        while not stop.is_set():
            idx = np.arange(n)
            blk = (0.5 * np.exp(1j * (ph + dphi * idx))).astype(np.complex64)
            ph = (ph + dphi * n) % (2 * np.pi)
            iqs.publish(blk)
            time.sleep(0.005)
    t = threading.Thread(target=pump, daemon=True)
    t.start()
    try:
        sdr = SolSDR("127.0.0.1", iq_port=iq_port)
        iq = sdr.capture_iq(8192)
        assert iq.dtype == np.complex64 and len(iq) == 8192, (iq.dtype, len(iq))
        assert sdr.sample_rate == 39062.5, sdr.sample_rate

        # spectrum: the 1 kHz tone should peak near 14.074 MHz + 1 kHz
        freq_hz, pdb = sdr.power_spectrum(iq, rbw_hz=200)
        peak_hz = float(freq_hz[int(np.argmax(pdb))])
        assert abs(peak_hz - (14_074_000 + 1000)) < 500, peak_hz

        # streaming yields blocks
        got = 0
        for blk in sdr.stream_iq(2048):
            assert len(blk) == 2048
            got += 1
            if got >= 3:
                break
        sdr.stop_stream()
        sdr.close()
        print(f"PASS IQ protocol: capture 8192, rate=39062.5, tone peak "
              f"@ {peak_hz/1e6:.6f} MHz, streaming {got} blocks")
    finally:
        stop.set()
        iqs.stop()


def test_tx_iq_protocol():
    """Drive solsdr's real IQTXServer through the driver's transmit_iq().

    The server is UNARMED (no fake radio wired to actual TX), so no RF — but it
    still accepts the connection, reads the complex64 the driver sends, and
    counts samples. That exercises the exact wire path the driver uses to key.
    """
    try:
        from solsdr.api.iq_tx_server import IQTXServer
        from solsdr.protocol.profiles import PRO
    except Exception as e:  # noqa: BLE001
        print(f"SKIP TX test: {e}")
        return
    if not hasattr(os, "timerfd_create"):
        print("SKIP TX test: timerfd unavailable (needs the radio host / py3.13+)")
        return

    class TXFakeRadio:
        profile = PRO
        wire_rate = PRO.wire_rate
        radio_ip = "127.0.0.1"
        current_freq = 14_074_000
        current_mode = "USB"
        _tx_active = False
        rx_sock = None

        class _Ctrl:
            def set_frequency(self, f): return True
            def set_ptt(self, on): return True
            def set_drive(self, b): return True
            def set_pa(self, on): return True
            def set_config_block(self, tx): return True
        ctrl = _Ctrl()

    tx_port = _free_port()
    srv = IQTXServer(TXFakeRadio(), host="127.0.0.1", port=tx_port,
                     armed=False, verbose=False)   # armed=False => NO RF
    srv.start()
    time.sleep(0.3)
    try:
        sdr = SolSDR("127.0.0.1", tx_iq_port=tx_port)
        tone = (0.5 * np.exp(2j * np.pi * 1000 *
                np.arange(int(PRO.wire_rate // 2)) / PRO.wire_rate)
                ).astype(np.complex64)
        sdr.transmit_iq(tone, extra_settle_s=0.3, tx_sample_rate=PRO.wire_rate)
        time.sleep(0.3)
        assert srv.samples_received >= len(tone), \
            f"server got {srv.samples_received}/{len(tone)} samples"
        sdr.close()
        print(f"PASS TX-IQ protocol: sent {len(tone)} complex64, server "
              f"received {srv.samples_received} (unarmed, no RF)")
    finally:
        srv.stop()


if __name__ == "__main__":
    if not HAVE_SOLSDR:
        print(f"SKIP: solsdr project not importable ({_IMPORT_ERR}). "
              f"Clone it to ~/Dropbox/build/solsdr to run the protocol test.")
        sys.exit(0)
    test_control_protocol()
    test_iq_protocol()
    test_tx_iq_protocol()
    print("\nSOLSDR DRIVER PROTOCOL TESTS PASSED")
