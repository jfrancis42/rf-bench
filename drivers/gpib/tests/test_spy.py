"""
Spy-mode decoder tests.

The sample streams below were hand-constructed from the format description in
User Guide Rev 2.13 §12 — no real capture existed when these were written.  They
pin the decoder's behaviour so that when a real capture arrives, any format
surprise shows up as a specific failing assertion rather than a vague "the
output looks wrong".
"""

import pytest

from rf_bench.gpib.spy import (
    GPIB_COMMANDS,
    classify_command_byte,
    decode,
    decode_ascii,
    decode_hex,
)
from rf_bench.gpib import SPY_ASCII, SPY_HEX


# ---------------------------------------------------------------------------
# Command-byte classification (IEEE-488.1, independent of KISS-488)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,mnemonic,address",
    [
        (0x01, "GTL", None),
        (0x04, "SDC", None),
        (0x08, "GET", None),
        (0x11, "LLO", None),
        (0x14, "DCL", None),
        (0x18, "SPE", None),
        (0x19, "SPD", None),
        (0x3F, "UNL", None),
        (0x5F, "UNT", None),
        (0x20, "LAG", 0),
        (0x30, "LAG", 16),
        (0x36, "LAG", 22),
        (0x40, "TAG", 0),
        (0x50, "TAG", 16),
        (0x56, "TAG", 22),
        (0x60, "SCG", 0),
    ],
)
def test_command_byte_classification(value, mnemonic, address):
    mnem, addr, _desc = classify_command_byte(value)
    assert (mnem, addr) == (mnemonic, address)


def test_unl_and_unt_win_over_their_address_groups():
    """0x3F and 0x5F fall inside LAG/TAG ranges but are the group escapes."""
    assert classify_command_byte(0x3F)[0] == "UNL"
    assert classify_command_byte(0x5F)[0] == "UNT"


def test_our_bench_addresses_round_trip():
    """HP 8712B = 16, Solartron 7151 = 22."""
    assert classify_command_byte(0x20 + 16)[1] == 16
    assert classify_command_byte(0x40 + 22)[1] == 22


# ---------------------------------------------------------------------------
# ASCII mode (++spy 1)
# ---------------------------------------------------------------------------

def test_ascii_decodes_command_and_data():
    stream = "!UNL!LAG 16*IDN?]\r\n"
    t = decode_ascii(stream)
    cmds = [(e.mnemonic, e.address) for e in t.commands()]
    assert cmds == [("UNL", None), ("LAG", 16)]
    assert t.messages() == ["*IDN?"]


def test_ascii_non_printables_become_bracketed_hex():
    t = decode_ascii("AB<1F>C]\r\n")
    assert t.data()[0].text == "AB\x1fC"
    assert t.data()[0].data == b"AB\x1fC"


def test_ascii_eoi_terminates_a_message():
    t = decode_ascii("!TAG 22+ 2.798450 V DC]\r\n!UNT")
    assert t.messages() == ["+ 2.798450 V DC"]
    assert t.data()[0].eoi is True


def test_ascii_multiple_messages():
    stream = "!LAG 16*IDN?]\r\n!TAG 16HEWLETT PACKARD,8712B]\r\n"
    t = decode_ascii(stream)
    assert t.messages() == ["*IDN?", "HEWLETT PACKARD,8712B"]
    assert t.addressed() == [16]


def test_ascii_tracks_both_instruments():
    stream = "!LAG 16*IDN?]\r\n!UNL!LAG 22E]\r\n"
    assert decode_ascii(stream).addressed() == [16, 22]


def test_ascii_unknown_mnemonic_does_not_raise():
    t = decode_ascii("!ZZZ data]\r\n")
    assert t.commands()[0].mnemonic == "ZZZ"


def test_ascii_empty_stream():
    assert len(decode_ascii("")) == 0


# ---------------------------------------------------------------------------
# Hex mode (++spy 2)
# ---------------------------------------------------------------------------

def test_hex_decodes_command_and_data():
    # [3F = UNL, [30 = LAG 16, then "*IDN?" with EOI on the last byte
    stream = "[3F [30 2A 49 44 4E 3F]\r\n"
    t = decode_hex(stream)
    assert [(e.mnemonic, e.address) for e in t.commands()] == [("UNL", None), ("LAG", 16)]
    assert t.messages() == ["*IDN?"]


def test_hex_renders_non_printables():
    t = decode_hex("41 1F 42]\r\n")
    assert t.data()[0].text == "A<1F>B"
    assert t.data()[0].data == b"A\x1fB"


def test_hex_talk_address_for_solartron():
    t = decode_hex("[56 2B 20 31 2E 32]\r\n")
    assert t.commands()[0].mnemonic == "TAG"
    assert t.commands()[0].address == 22
    assert t.messages() == ["+ 1.2"]


def test_hex_is_case_insensitive():
    assert decode_hex("[3f 4a]\r\n").commands()[0].mnemonic == "UNL"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def test_decode_dispatch():
    assert decode("!UNL", SPY_ASCII).commands()[0].mnemonic == "UNL"
    assert decode("[3F", SPY_HEX).commands()[0].mnemonic == "UNL"
    with pytest.raises(ValueError):
        decode("x", 0)


def test_pretty_output_is_readable():
    text = decode_ascii("!UNL!LAG 16*IDN?]\r\n").pretty()
    assert "!UNL" in text and "!LAG 16" in text


# ---------------------------------------------------------------------------
# Live session against the emulator
# ---------------------------------------------------------------------------

def test_spy_session_captures_and_decodes():
    from rf_bench.gpib import KISS488
    from rf_bench.gpib.spy import spy_session
    from rf_bench.gpib.testing import FakeInstrument, FakeLink

    link = FakeLink()
    link.add_instrument(16, FakeInstrument({"*IDN?": "X"}))
    gpib = KISS488(link)
    try:
        link.spy_stream = "!UNL!LAG 16*IDN?]\r\n"
        with spy_session(gpib) as spy:
            transcript = spy.capture(seconds=0.3, idle=0.05)
        assert transcript.messages() == ["*IDN?"]
        assert transcript.addressed() == [16]
        assert not gpib.spying
    finally:
        gpib.close_now()


def test_command_table_covers_the_documented_universals():
    for mnem in ("GTL", "SDC", "GET", "LLO", "DCL", "SPE", "SPD", "UNL", "UNT"):
        assert any(v[0] == mnem for v in GPIB_COMMANDS.values())
