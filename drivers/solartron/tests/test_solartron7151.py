"""
Solartron 7151 driver tests against the KISS-488 emulator — no hardware.

Scope: plumbing, command encoding, reading parsing, and the DMM parity surface.
The 7151 command language was reconstructed from an OCR'd 1985 manual plus the
s7150 reference driver; these tests pin what the driver *emits*, not what the
instrument accepts.
"""

import pytest

from rf_bench.gpib import KISS488
from rf_bench.gpib.testing import FakeInstrument, FakeLink, fake_solartron7151
from rf_bench.solartron import Solartron7151
from rf_bench.solartron.solartron7151 import (
    DEFAULT_GPIB_ADDR,
    DEFAULT_KISS_PORT,
    DEFAULT_PORT,
    MODE_IAC,
    MODE_KOHM,
    MODE_VDC,
    RANGE_AUTO,
)


@pytest.fixture
def link():
    lk = FakeLink()
    lk.add_instrument(22, fake_solartron7151())
    return lk


@pytest.fixture
def dmm(link):
    gpib = KISS488(link)
    # initialise=False skips the 2 s DCL settle; the init sequence is covered
    # by its own test below.
    instrument = Solartron7151(gpib.device(22), initialise=False)
    yield instrument
    instrument.close()
    gpib.close_now()


# ---------------------------------------------------------------------------
# Defaults — port and address bugs
# ---------------------------------------------------------------------------

def test_default_port_is_telnet_23_not_prologix_1234():
    assert DEFAULT_PORT == 23
    assert DEFAULT_KISS_PORT == 23


def test_default_address_is_22_to_avoid_the_hp():
    """Both meters ship at 16 and share one KISS-488; the 7151 moves to 22."""
    assert DEFAULT_GPIB_ADDR == 22
    assert Solartron7151.DEFAULT_GPIB_ADDR == 22


# ---------------------------------------------------------------------------
# ++spoll removal
# ---------------------------------------------------------------------------

def test_serial_poll_refuses_with_an_explanation(dmm):
    """KISS-488 has no ++spoll; the old driver issued one and would have hung."""
    with pytest.raises(NotImplementedError, match="serial-poll"):
        dmm.serial_poll()


def test_no_spoll_ever_reaches_the_wire(dmm, link):
    dmm.set_mode("VDC")
    dmm.read_value(timeout=0.05)
    try:
        dmm.serial_poll()
    except NotImplementedError:
        pass
    assert not any("spoll" in line for line in link.written)


def test_get_error_uses_the_instrument_status_command(dmm, link):
    code, message = dmm.get_error()
    assert "!" in link.instrument(22).received
    assert (code, message) == (0, "OK")


def test_wait_for_reading_replaces_the_srq_wait(dmm):
    assert dmm.wait_for_reading(timeout=1.0) == pytest.approx(2.798450)


def test_wait_for_reading_times_out_cleanly(link):
    link.add_instrument(9, FakeInstrument(name="mute"))
    gpib = KISS488(link)
    try:
        instrument = Solartron7151(gpib.device(9), initialise=False)
        with pytest.raises(TimeoutError, match="TRACK mode"):
            instrument.wait_for_reading(timeout=0.2, interval=0.05)
    finally:
        gpib.close_now()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_construct_from_device_handle(link):
    gpib = KISS488(link)
    try:
        instrument = Solartron7151(gpib.device(22), initialise=False)
        assert instrument.gpib_addr == 22
        assert instrument.identify() == "M0 R0 I3 T1 U7 N0 D0 Y0 Z0 K0 Q0"
    finally:
        gpib.close_now()


def test_construct_from_positional_host(monkeypatch, link):
    """bridge_solartron.py does Solartron7151("10.1.1.70")."""
    monkeypatch.setattr("rf_bench.gpib.kiss488.TcpLink", lambda h, p: link)
    instrument = Solartron7151("10.1.1.70", initialise=False)
    try:
        assert instrument.host == "10.1.1.70"
        assert instrument.port == 23
        assert instrument.gpib_addr == 22
    finally:
        instrument.close()


def test_init_sequence_matches_s7150_reference(link):
    gpib = KISS488(link)
    try:
        instrument = Solartron7151(gpib.device(22), initialise=False)
        instrument.connect()
        received = link.instrument(22).received
        assert received[0] == "A", "DCL first"
        assert "U7N0T1" in received, "CR delimiter, literals on, tracking on"
        assert received.index("A") < received.index("U7N0T1")
    finally:
        gpib.close_now()


def test_close_restores_default_state(link):
    gpib = KISS488(link)
    try:
        instrument = Solartron7151(gpib.device(22), initialise=False)
        instrument.close()
        assert link.instrument(22).received[-2:] == ["DC1", "A"]
    finally:
        gpib.close_now()


def test_use_after_close_raises(link):
    gpib = KISS488(link)
    try:
        instrument = Solartron7151(gpib.device(22), initialise=False)
        instrument.close()
        with pytest.raises(IOError):
            instrument.identify()
    finally:
        gpib.close_now()


# ---------------------------------------------------------------------------
# Command encoding
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "mode,expected",
    [("VDC", "M0"), ("DCV", "M0"), ("VAC", "M1"), ("KOHM", "M2"),
     ("IDC", "M3"), ("IAC", "M4"), (0, "M0"), (4, "M4")],
)
def test_set_mode_encoding(dmm, link, mode, expected):
    dmm.set_mode(mode)
    assert link.instrument(22).last() == expected


def test_set_mode_rejects_nonsense(dmm):
    with pytest.raises(ValueError):
        dmm.set_mode("VOLTS")
    with pytest.raises(ValueError):
        dmm.set_mode(9)


def test_range_and_integration_encoding(dmm, link):
    dmm.set_range_auto()
    assert link.instrument(22).last() == "R0"
    dmm.set_integration(3)
    assert link.instrument(22).last() == "I3"
    with pytest.raises(ValueError):
        dmm.set_range(7)
    with pytest.raises(ValueError):
        dmm.set_integration(6)


def test_track_and_trigger_encoding(dmm, link):
    dmm.set_track(True)
    assert link.instrument(22).last() == "T1"
    dmm.set_track(False)
    assert link.instrument(22).last() == "T0"
    dmm.trigger_single()
    assert link.instrument(22).last() == "G"


def test_literals_display_delimiter_encoding(dmm, link):
    dmm.set_literals(False)
    assert link.instrument(22).last() == "N1"
    dmm.set_display(False)
    assert link.instrument(22).last() == "D1"     # D1 disables — counter-intuitive
    dmm.set_delimiter(7)
    assert link.instrument(22).last() == "U7"


def test_drift_null_srq_lock_encoding(dmm, link):
    dmm.set_drift_correct(2)
    assert link.instrument(22).last() == "Y2"
    dmm.set_null(1)
    assert link.instrument(22).last() == "Z1"
    dmm.set_srq(2)
    assert link.instrument(22).last() == "Q2"
    dmm.set_lock(True)
    assert link.instrument(22).last() == "K1"


def test_calibration_encoding(dmm, link):
    dmm.calibrate_on()
    assert link.instrument(22).last() == "C1"
    dmm.cal_hi(200000)
    assert link.instrument(22).last() == "H200000"
    dmm.cal_lo(0)
    assert link.instrument(22).last() == "L0"
    dmm.cal_write()
    assert link.instrument(22).last() == "W"
    dmm.calibrate_off()
    assert link.instrument(22).last() == "C0"


def test_cal_count_range_enforced(dmm):
    with pytest.raises(ValueError):
        dmm.cal_hi(1000000)


# ---------------------------------------------------------------------------
# Reading parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+ 2.798450 V DC 01.15.00 DAY 5", 2.798450),   # literals on
        ("+2.798450", 2.798450),                        # literals off
        ("- 0.000123 V DC", -0.000123),
        ("-1.5", -1.5),
    ],
)
def test_parse_reading(raw, expected):
    assert Solartron7151._parse_reading(raw) == pytest.approx(expected)


def test_overload_flag_raises():
    with pytest.raises(OverflowError, match="overload"):
        Solartron7151._parse_reading("+ 9.999999! V DC")


def test_unparseable_reading_raises():
    with pytest.raises(ValueError, match="could not parse"):
        Solartron7151._parse_reading("TIMEOUT")


def test_read_value_end_to_end(dmm):
    assert dmm.read_value() == pytest.approx(2.798450)


# ---------------------------------------------------------------------------
# DMM parity surface (rf_bench.siglent.SDM3000X compatible)
# ---------------------------------------------------------------------------

def test_parity_methods_exist():
    """projects/dmm/* --dmm flag and Fluke80i400(dmm=...) rely on these."""
    for name in ("measure_vdc", "measure_vac", "measure_idc",
                 "measure_iac", "measure_resistance"):
        assert callable(getattr(Solartron7151, name)), f"missing {name}"


def test_measure_vdc_selects_mode_and_reads(dmm, link):
    assert dmm.measure_vdc(settle=0) == pytest.approx(2.798450)
    assert "M0" in link.instrument(22).received


def test_measure_iac_selects_mode(dmm, link):
    dmm.measure_iac(settle=0)
    assert "M4" in link.instrument(22).received


def test_measure_with_explicit_range(dmm, link):
    dmm.measure_vdc(range_code=RANGE_AUTO, settle=0)
    assert "R0" in link.instrument(22).received


def test_fluke_80i400_composition():
    """rf_bench.fluke.Fluke80i400 composes with any DMM exposing measure_iac()."""
    import inspect

    sig = inspect.signature(Solartron7151.measure_iac)
    assert list(sig.parameters)[0] == "self"
    # callable with no required arguments beyond self
    assert all(
        p.default is not inspect.Parameter.empty
        for name, p in sig.parameters.items() if name != "self"
    )


# -- resistance unit scaling ------------------------------------------------

@pytest.mark.parametrize(
    "reading,scale",
    [
        ("+ 1.234567 K OHM", 1e3),
        ("+ 1.234567 KOHM", 1e3),
        ("+ 1.234567 M OHM", 1e6),
        ("+ 1.234567 OHM", 1.0),
        ("+ 2.798450 V DC", 1.0),
        ("+ 1.000000 MV DC", 1e-3),
        ("+ 1.000000 MA AC", 1e-3),
        ("+ 1.000000 A AC", 1.0),
    ],
)
def test_unit_scale_detection(reading, scale):
    assert Solartron7151._unit_scale(reading) == pytest.approx(scale)


def test_unit_scale_prefers_longest_match():
    """'K OHM' must win over the 'OHM' substring inside it."""
    assert Solartron7151._unit_scale("+ 1.0 K OHM") == pytest.approx(1e3)


def test_unit_scale_rejects_unknown_units():
    with pytest.raises(ValueError, match="no recognised unit"):
        Solartron7151._unit_scale("+ 1.0 FURLONGS")


def test_measure_resistance_scales_kohm_to_ohms(link):
    link.add_instrument(
        7, FakeInstrument(default=lambda c: "+ 1.234567 K OHM", name="r")
    )
    gpib = KISS488(link)
    try:
        instrument = Solartron7151(gpib.device(7), initialise=False)
        assert instrument.measure_resistance(settle=0) == pytest.approx(1234.567)
        assert "M2" in link.instrument(7).received
    finally:
        gpib.close_now()


def test_measure_resistance_refuses_to_guess_without_literals(dmm):
    """Better to raise than silently return a value 1000x off."""
    dmm.set_literals(False)
    with pytest.raises(RuntimeError, match="LITERALS ON"):
        dmm.measure_resistance(settle=0)


def test_mode_constants_match_manual():
    assert (MODE_VDC, MODE_KOHM, MODE_IAC) == (0, 2, 4)


# ---------------------------------------------------------------------------
# Bus sharing
# ---------------------------------------------------------------------------

def test_dmm_and_vna_share_one_adapter(link):
    link.add_instrument(16, FakeInstrument({"*IDN?": "HEWLETT PACKARD,8712B"}))
    gpib = KISS488(link)
    try:
        instrument = Solartron7151(gpib.device(22), initialise=False)
        vna_dev = gpib.device(16)
        assert instrument.read_value() == pytest.approx(2.798450)
        assert vna_dev.query("*IDN?").startswith("HEWLETT")
        assert instrument.read_value() == pytest.approx(2.798450)
    finally:
        gpib.close_now()


def test_context_manager(link):
    gpib = KISS488(link)
    try:
        with Solartron7151(gpib.device(22), initialise=False) as instrument:
            assert instrument.read_value() == pytest.approx(2.798450)
    finally:
        gpib.close_now()
