"""
HP 8712B driver tests against the KISS-488 emulator — no hardware.

Scope: these prove the *plumbing* — construction paths, transport wiring, bus
sharing, data parsing.  They cannot prove that any given SCPI mnemonic is what
an HP 8712B accepts; the ones marked "Verify against HP 8712B manual" in the
driver remain unverified until a real instrument or a Spy-mode capture says
otherwise, and are deliberately NOT asserted here.
"""

import numpy as np
import pytest

from rf_bench.gpib import KISS488
from rf_bench.gpib.testing import FakeInstrument, FakeLink, fake_hp8712b
from rf_bench.hp import HP8712B
from rf_bench.hp.hp8712b import DEFAULT_GPIB_ADDR, DEFAULT_KISS_PORT, DEFAULT_PORT


@pytest.fixture
def link():
    lk = FakeLink()
    lk.add_instrument(16, fake_hp8712b())
    return lk


@pytest.fixture
def vna(link):
    gpib = KISS488(link)
    instrument = HP8712B(gpib.device(16))
    yield instrument
    instrument.close()
    gpib.close_now()


# ---------------------------------------------------------------------------
# Defaults — the port bug that motivated this work
# ---------------------------------------------------------------------------

def test_default_port_is_telnet_23_not_prologix_1234():
    assert DEFAULT_PORT == 23
    assert DEFAULT_KISS_PORT == 23, "deprecated alias must not still say 1234"
    assert HP8712B.DEFAULT_PORT == 23


def test_default_address_is_16():
    assert DEFAULT_GPIB_ADDR == 16


# ---------------------------------------------------------------------------
# Construction paths
# ---------------------------------------------------------------------------

def test_construct_from_device_handle(link):
    gpib = KISS488(link)
    try:
        instrument = HP8712B(gpib.device(16))
        assert instrument.identify().startswith("HEWLETT PACKARD,8712B")
        assert instrument.gpib_addr == 16
    finally:
        gpib.close_now()


def test_construct_from_positional_host(monkeypatch, link):
    """bridge_hp8712b.py does HP8712B("10.1.1.70") — must keep working."""
    monkeypatch.setattr("rf_bench.gpib.kiss488.TcpLink", lambda h, p: link)
    instrument = HP8712B("10.1.1.70")
    try:
        assert instrument.host == "10.1.1.70"
        assert instrument.port == 23
        assert instrument.identify().startswith("HEWLETT PACKARD")
    finally:
        instrument.close()


def test_construct_from_keyword_host(monkeypatch, link):
    """Every projects/vna/* script does HP8712B(host=args.host)."""
    monkeypatch.setattr("rf_bench.gpib.kiss488.TcpLink", lambda h, p: link)
    instrument = HP8712B(host="10.1.1.70")
    try:
        assert instrument.identify().startswith("HEWLETT PACKARD")
    finally:
        instrument.close()


def test_conflicting_hosts_rejected():
    with pytest.raises(ValueError, match="conflicting hosts"):
        HP8712B("10.1.1.70", host="10.1.1.71")


def test_deprecated_kiss_port_still_accepted(monkeypatch, link):
    captured = {}

    def fake_tcp(host, port):
        captured["port"] = port
        return link

    monkeypatch.setattr("rf_bench.gpib.kiss488.TcpLink", fake_tcp)
    instrument = HP8712B("10.1.1.70", kiss_port=1234)
    try:
        assert captured["port"] == 1234
        assert instrument.port == 1234
    finally:
        instrument.close()


def test_connect_is_a_harmless_noop(vna):
    vna.connect()
    assert vna.identify().startswith("HEWLETT PACKARD")


def test_use_after_close_raises(link):
    gpib = KISS488(link)
    try:
        instrument = HP8712B(gpib.device(16))
        instrument.close()
        with pytest.raises(IOError):
            instrument.identify()
    finally:
        gpib.close_now()


# ---------------------------------------------------------------------------
# Bus sharing — the reason the transport layer exists
# ---------------------------------------------------------------------------

def test_vna_and_dmm_share_one_adapter(link):
    link.add_instrument(22, FakeInstrument({"E": "SETTINGS"}, default="+ 1.0 V DC"))
    gpib = KISS488(link)
    try:
        vna = HP8712B(gpib.device(16))
        dmm_dev = gpib.device(22)
        assert vna.identify().startswith("HEWLETT PACKARD")
        assert dmm_dev.query("E") == "SETTINGS"
        assert vna.identify().startswith("HEWLETT PACKARD")
        assert link.instrument(16).received == ["*IDN?", "*IDN?"]
        assert link.instrument(22).received == ["E"]
    finally:
        gpib.close_now()


def test_each_query_is_address_scoped(vna, link):
    vna.identify()
    idx = link.written.index("*IDN?")
    assert link.written[idx - 1] == "++addr 16"


# ---------------------------------------------------------------------------
# Command emission
# ---------------------------------------------------------------------------

def test_setup_sweep_emits_start_stop_points(vna, link):
    vna.setup_sweep(1e6, 1.3e9, points=401)
    sent = link.instrument(16).received
    assert ":SENS:FREQ:STAR 1000000.0" in sent
    assert ":SENS:FREQ:STOP 1300000000.0" in sent
    assert ":SENS:SWE:POIN 401" in sent


def test_setup_sweep_rejects_out_of_range_points(vna):
    with pytest.raises(ValueError, match="1–801"):
        vna.setup_sweep(1e6, 1e9, points=802)


def test_set_format_validates(vna):
    vna.set_format("MLOG")
    with pytest.raises(ValueError):
        vna.set_format("BOGUS")


def test_set_parameter_validates(vna):
    vna.set_parameter("S21")
    assert vna.get_parameter() == "S21"
    with pytest.raises(ValueError):
        vna.set_parameter("S33")


def test_averaging_off_and_on(vna, link):
    vna.set_averaging(1)
    assert ":SENS:AVER:STAT OFF" in link.instrument(16).received
    vna.set_averaging(8)
    assert ":SENS:AVER:COUN 8" in link.instrument(16).received


def test_no_reply_commands_use_the_quiescent_path(vna, link):
    """A CR-terminated *CLS would hang for the full timeout (User Guide §9)."""
    vna.set_format("MLOG")
    assert "++read" not in link.written[-2:]


# ---------------------------------------------------------------------------
# Data readout
# ---------------------------------------------------------------------------

def test_get_frequencies(vna):
    vna.setup_sweep(1e6, 201e6, points=201)
    freqs = vna.get_frequencies()
    assert isinstance(freqs, np.ndarray)
    assert len(freqs) == 201
    assert freqs[0] == pytest.approx(1e6)


def test_get_trace_db(vna):
    vna.setup_sweep(1e6, 201e6, points=201)
    db = vna.get_trace_db()
    assert len(db) == 201
    assert db[0] == pytest.approx(0.0)
    assert db[10] == pytest.approx(-1.0)


def test_get_s_data_returns_complex(vna):
    vna.setup_sweep(1e6, 11e6, points=11)
    s = vna.get_s_data()
    assert s.dtype == np.complex128
    assert len(s) == 11
    assert s[0] == pytest.approx(1.0 + 0.0j)
    assert s[5] == pytest.approx(0.995 + 0.01j)


def test_get_s_data_rejects_odd_value_count(link):
    link.add_instrument(9, FakeInstrument({":CALC:DATA:SDAT?": "1.0 2.0 3.0"}))
    gpib = KISS488(link)
    try:
        instrument = HP8712B(gpib.device(9))
        with pytest.raises(ValueError, match="odd number"):
            instrument.get_s_data()
    finally:
        gpib.close_now()


def test_single_sweep_reports_completion(vna):
    assert vna.single_sweep() is True


def test_get_trace_db_at_picks_nearest_point(vna):
    vna.setup_sweep(1e6, 201e6, points=201)
    assert vna.get_trace_db_at(11e6) == pytest.approx(-1.0)


def test_average_s_data_shape(vna):
    vna.setup_sweep(1e6, 11e6, points=11)
    avg = vna.average_s_data(3)
    assert len(avg) == 11
    assert avg[0] == pytest.approx(1.0 + 0.0j)


def test_average_s_data_rejects_zero(vna):
    with pytest.raises(ValueError):
        vna.average_s_data(0)


def test_marker_value(vna):
    assert vna.get_marker_value() == pytest.approx(-12.345)


def test_marker_number_validated(vna):
    with pytest.raises(ValueError):
        vna.set_marker(1e6, marker=9)


def test_correction_state(vna):
    assert vna.is_correction_on() is True


# ---------------------------------------------------------------------------
# NanoVNA parity surface
# ---------------------------------------------------------------------------

def test_shared_vna_api_surface_present():
    """Method names projects/vna/* rely on for --vna {nanovna,hp}."""
    for name in (
        "setup_sweep", "set_parameter", "get_parameter", "set_format",
        "single_sweep", "pause", "resume", "hold", "continuous",
        "get_frequencies", "get_s_data", "get_trace_db", "get_trace_phase",
        "get_trace_db_at", "get_s11", "get_s21", "set_marker",
        "get_marker_value", "marker_off", "correction_on", "correction_off",
        "cal_on", "cal_off", "is_correction_on", "average_s_data", "close",
    ):
        assert callable(getattr(HP8712B, name)), f"missing {name}"


def test_context_manager(link):
    gpib = KISS488(link)
    try:
        with HP8712B(gpib.device(16)) as instrument:
            assert instrument.identify().startswith("HEWLETT PACKARD")
    finally:
        gpib.close_now()
