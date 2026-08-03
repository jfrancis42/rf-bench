"""
Adapter-level tests: protocol correctness, shared-bus safety, lifecycle.

These run against the FakeLink emulator — no hardware.  They verify the things
that must be right *before* the KISS-488 arrives, especially the shared-bus
invariants that the previous one-socket-per-driver design got wrong.
"""

import threading

import pytest

from rf_bench.gpib import (
    EOS_LF,
    GPIBError,
    KISS488,
    QUERY_AUTO,
    QUERY_EXPLICIT_READ,
    SPY_ASCII,
    SPY_OFF,
)
from rf_bench.gpib.testing import FakeInstrument, FakeLink


@pytest.fixture
def link():
    lk = FakeLink()
    lk.add_instrument(16, FakeInstrument({"*IDN?": "VNA,8712B,0,1"}, name="vna"))
    lk.add_instrument(22, FakeInstrument({"E": "SETTINGS"}, default="+ 1.234567 V DC",
                                         name="dmm"))
    return lk


@pytest.fixture
def gpib(link):
    adapter = KISS488(link)
    yield adapter
    adapter.close_now()


# ---------------------------------------------------------------------------
# Init sequence
# ---------------------------------------------------------------------------

def test_init_sequence_matches_manual(link):
    gpib = KISS488(link, eoi=True, eos=EOS_LF)
    try:
        sent = link.commands("++")
        assert "++savecfg 0" in sent, "must not rewrite adapter NVM by default"
        assert "++eoi 1" in sent
        assert "++eos 2" in sent
        assert "++auto 0" in sent, "explicit-read strategy requires auto off"
        # savecfg must come first, or the settings that follow land in NVM.
        assert sent.index("++savecfg 0") < sent.index("++eoi 1")
    finally:
        gpib.close_now()


def test_signon_banner_is_discarded(link):
    gpib = KISS488(link)
    try:
        # The banner emitted at connect must not be mistaken for a reply.
        assert gpib.device(16).query("*IDN?") == "VNA,8712B,0,1"
    finally:
        gpib.close_now()


def test_rst_is_refused_with_reason(gpib):
    with pytest.raises(NotImplementedError, match=r"\+\+rst"):
        gpib.reset()


def test_serial_poll_is_refused_with_reason(gpib):
    with pytest.raises(NotImplementedError, match="serial-poll"):
        gpib.serial_poll(16)
    with pytest.raises(NotImplementedError):
        gpib.device(22).serial_poll()


# ---------------------------------------------------------------------------
# Addressing — the shared-bus invariant
# ---------------------------------------------------------------------------

def test_every_transaction_selects_its_address(gpib, link):
    vna, dmm = gpib.device(16), gpib.device(22)
    vna.query("*IDN?")
    dmm.query("E")
    vna.query("*IDN?")
    addr_lines = [c for c in link.written if c.startswith("++addr")]
    assert addr_lines == ["++addr 16", "++addr 22", "++addr 16"]


def test_address_precedes_its_command(gpib, link):
    gpib.device(22).query("E")
    i_addr = link.written.index("++addr 22")
    i_cmd = link.written.index("E")
    assert i_addr < i_cmd, "address must be selected before the command goes out"


def test_traffic_reaches_the_right_instrument(gpib, link):
    gpib.device(16).query("*IDN?")
    gpib.device(22).query("E")
    assert link.instrument(16).received == ["*IDN?"]
    assert link.instrument(22).received == ["E"]


def test_address_is_reissued_even_when_unchanged(gpib, link):
    """Default cache_address=False: the web UI or a second session can move it."""
    dev = gpib.device(16)
    dev.query("*IDN?")
    dev.query("*IDN?")
    assert link.commands("++addr").count("++addr 16") == 2


def test_address_caching_is_opt_in(link):
    gpib = KISS488(link, cache_address=True)
    try:
        dev = gpib.device(16)
        dev.query("*IDN?")
        dev.query("*IDN?")
        assert link.commands("++addr").count("++addr 16") == 1
    finally:
        gpib.close_now()


@pytest.mark.parametrize("bad", [-1, 31, 99])
def test_address_range_is_enforced(gpib, bad):
    with pytest.raises(ValueError, match="0..30"):
        gpib.device(bad)


def test_address_type_is_enforced(gpib):
    with pytest.raises(TypeError):
        gpib.device("16")


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

def test_concurrent_devices_do_not_interleave(gpib, link):
    """
    The failure this whole design exists to prevent: two instruments on one bus
    whose address selection and data transfer get interleaved.
    """
    errors = []

    def hammer(address, command, expected):
        dev = gpib.device(address)
        try:
            for _ in range(40):
                got = dev.query(command)
                if got != expected:
                    errors.append((address, got))
        except Exception as e:  # pragma: no cover
            errors.append((address, repr(e)))

    threads = [
        threading.Thread(target=hammer, args=(16, "*IDN?", "VNA,8712B,0,1")),
        threading.Thread(target=hammer, args=(22, "E", "SETTINGS")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # And every command was preceded by its own address selection.
    for i, cmd in enumerate(link.written):
        if cmd == "*IDN?":
            assert link.written[i - 1] == "++addr 16"
        elif cmd == "E":
            assert link.written[i - 1] == "++addr 22"


def test_explicit_transaction_holds_the_bus(gpib, link):
    dev = gpib.device(16)
    with dev.transaction():
        dev.write("A")
        dev.write("B")
    between = link.written[link.written.index("A") : link.written.index("B")]
    assert not any(c.startswith("++addr 22") for c in between)


# ---------------------------------------------------------------------------
# Terminator semantics (User Guide §9)
# ---------------------------------------------------------------------------

def test_write_without_reply_uses_lf(link):
    """CR would make KISS-488 address the instrument to talk and hang."""
    gpib = KISS488(link)
    try:
        gpib.device(16).write("*CLS")
        raw = _raw_for(link, "*CLS")
        assert raw.endswith(b"\n") and not raw.endswith(b"\r\n")
    finally:
        gpib.close_now()


def test_auto_strategy_uses_cr_and_no_explicit_read(link):
    gpib = KISS488(link, query_strategy=QUERY_AUTO)
    try:
        assert "++auto 1" in link.commands("++")
        assert gpib.device(16).query("*IDN?") == "VNA,8712B,0,1"
        assert "++read" not in link.commands("++")
    finally:
        gpib.close_now()


def test_explicit_read_strategy_issues_read(gpib, link):
    assert gpib.device(16).query("*IDN?") == "VNA,8712B,0,1"
    assert "++read" in link.commands("++")


def test_read_until_eoi(gpib, link):
    link.instrument(16).queue("DATA")
    assert gpib.device(16).read(until="EOI") == "DATA"
    assert "++read EOI" in link.commands("++")


def test_read_until_character(gpib, link):
    link.instrument(16).queue("DATA")
    gpib.device(16).read(until="\n")
    assert "++read 10" in link.commands("++")


# ---------------------------------------------------------------------------
# Silent timeout
# ---------------------------------------------------------------------------

def test_empty_output_buffer_yields_empty_string(gpib, link):
    """A null Timeout String produces a silent timeout, not an exception (§5)."""
    link.add_instrument(5, FakeInstrument(name="mute"))
    assert gpib.device(5).read(timeout=0.05) == ""


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------

def test_read_timeout_ceiling_is_enforced(gpib):
    gpib.set_read_timeout_ms(3000)
    with pytest.raises(ValueError, match="3000"):
        gpib.set_read_timeout_ms(3001)
    with pytest.raises(ValueError):
        gpib.set_read_timeout_ms(0)


def test_read_timeout_error_names_the_workaround(gpib):
    with pytest.raises(ValueError, match="Timeout String"):
        gpib.set_read_timeout_ms(30000)


def test_eos_validation(gpib):
    for code in (0, 1, 2, 3):
        gpib.set_eos(code)
    with pytest.raises(ValueError):
        gpib.set_eos(4)     # "Other" is reply-only


def test_spy_mode_validation(gpib):
    with pytest.raises(ValueError):
        gpib.spy(3)


# ---------------------------------------------------------------------------
# Adapter identity
# ---------------------------------------------------------------------------

def test_version_ip_mac(gpib):
    assert "2.65" in gpib.version()
    assert gpib.ip_address() == "10.1.1.70"
    assert gpib.mac_address() == "00:04:A3:0B:00:2A"
    assert gpib.firmware_revision() == pytest.approx(2.65)


def test_get_address_queries_the_adapter(gpib, link):
    gpib.set_address(22)
    assert gpib.get_address() == 22


# ---------------------------------------------------------------------------
# Spy mode
# ---------------------------------------------------------------------------

def test_spy_mode_blocks_bus_control(gpib):
    gpib.spy(SPY_ASCII)
    assert gpib.spying
    with pytest.raises(GPIBError, match="spy mode"):
        gpib.device(16).query("*IDN?")
    gpib.spy(SPY_OFF)
    assert gpib.device(16).query("*IDN?") == "VNA,8712B,0,1"


def test_spy_session_always_turns_spy_off(gpib, link):
    from rf_bench.gpib.spy import spy_session

    with pytest.raises(RuntimeError):
        with spy_session(gpib):
            raise RuntimeError("boom")
    assert link.commands("++")[-1] == "++spy 0"
    assert not gpib.spying


def test_teardown_turns_spy_off(link):
    """Spy is nonvolatile from fw 2.65 — leaving it on wedges the next session."""
    gpib = KISS488(link)
    gpib.spy(SPY_ASCII)
    gpib.close_now()
    assert "++spy 0" in link.commands("++")


# ---------------------------------------------------------------------------
# Lifecycle — the two-session limit
# ---------------------------------------------------------------------------

def test_shared_returns_one_adapter_per_host(monkeypatch):
    made = []

    def fake_tcp(host, port):
        lk = FakeLink()
        lk.add_instrument(16, FakeInstrument({"*IDN?": "X"}))
        lk.add_instrument(22, FakeInstrument({"*IDN?": "Y"}))
        made.append(lk)
        return lk

    monkeypatch.setattr("rf_bench.gpib.kiss488.TcpLink", fake_tcp)
    a = KISS488.shared("10.1.1.70")
    b = KISS488.shared("10.1.1.70")
    try:
        assert a is b, "two drivers must share one socket (only 2 sessions exist)"
        assert len(made) == 1
    finally:
        a.close()
        b.close()


def test_refcount_defers_teardown(monkeypatch):
    links = []

    def fake_tcp(host, port):
        lk = FakeLink()
        lk.add_instrument(16, FakeInstrument({"*IDN?": "X"}))
        links.append(lk)
        return lk

    monkeypatch.setattr("rf_bench.gpib.kiss488.TcpLink", fake_tcp)
    a = KISS488.shared("10.1.1.70")
    b = KISS488.shared("10.1.1.70")
    dev = a.device(16)
    a.close()
    assert not links[0].closed, "link must survive while another holder remains"
    assert dev.query("*IDN?") == "X"
    b.close()
    assert links[0].closed


def test_close_sends_quit_first(link):
    """§9: dropping without ++quit wedges a session until the adapter is reset."""
    gpib = KISS488(link)
    gpib.close_now()
    assert link.written[-1] == "++quit"
    assert link.closed


def test_device_close_releases_the_adapter(monkeypatch):
    links = []

    def fake_tcp(host, port):
        lk = FakeLink()
        lk.add_instrument(16, FakeInstrument({"*IDN?": "X"}))
        links.append(lk)
        return lk

    monkeypatch.setattr("rf_bench.gpib.kiss488.TcpLink", fake_tcp)
    gpib = KISS488.shared("10.1.1.70")
    with gpib.device(16) as dev:
        assert dev.query("*IDN?") == "X"
    assert links[0].closed


def test_use_after_close_is_an_error(gpib):
    dev = gpib.device(16)
    dev.close()
    with pytest.raises(IOError):
        dev.query("*IDN?")


# ---------------------------------------------------------------------------
# Bus control
# ---------------------------------------------------------------------------

def test_device_clear_trigger_local(gpib, link):
    dev = gpib.device(16)
    dev.clear()
    dev.trigger()
    dev.local()
    dev.local_lockout()
    inst = link.instrument(16)
    assert (inst.cleared, inst.triggered, inst.local_calls, inst.lockout_calls) == (1, 1, 1, 1)


def test_interface_clear_invalidates_address_cache(link):
    gpib = KISS488(link, cache_address=True)
    try:
        gpib.device(16).query("*IDN?")
        gpib.interface_clear()
        gpib.device(16).query("*IDN?")
        assert link.commands("++addr").count("++addr 16") == 2
    finally:
        gpib.close_now()


def _raw_for(link: FakeLink, command: str) -> bytes:
    """Reconstruct the exact bytes the host wrote for ``command``."""
    # FakeLink records stripped lines; re-derive the terminator from the
    # emulator's view by checking which branch ran.  Simpler: sniff the raw
    # stream captured by a wrapping link.
    return _RawSniffer.last_for(command)


class _RawSniffer:
    """Records raw bytes per command so terminator assertions are possible."""

    _records = {}

    @classmethod
    def last_for(cls, command):
        return cls._records.get(command, b"")


@pytest.fixture(autouse=True)
def _sniff_raw(monkeypatch):
    """Capture the exact terminator bytes used for each host line."""
    original = FakeLink._send_bytes
    buffer = bytearray()

    def patched(self, data):
        buffer.extend(data)
        while True:
            idx = next((i for i, b in enumerate(buffer) if b in (0x0A, 0x0D)), None)
            if idx is None:
                break
            line = bytes(buffer[: idx + 1])
            del buffer[: idx + 1]
            _RawSniffer._records[line[:-1].decode("ascii", "replace").strip("\r")] = line
        return original(self, data)

    monkeypatch.setattr(FakeLink, "_send_bytes", patched)
    yield
    _RawSniffer._records.clear()
