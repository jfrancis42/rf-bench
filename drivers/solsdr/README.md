# rf-bench-drivers-solsdr

Python driver for the **SunSDR2 PRO** via the **solsdr** appliance — the
ExpertSDR3-free, pure-UDP SDR (github.com/jfrancis42/solsdr). Unlike
`rf-bench-drivers-sunsdr` (which drives the radio through ExpertSDR3's TCI
WebSocket and **cannot transmit IQ**), this driver needs no ExpertSDR3 and can
**transmit arbitrary complex-baseband IQ straight out the antenna** —
hardware-verified in solsdr.

## How it works — network client, not a hardware driver

**solsdr is a separate appliance process** that owns the radio and exposes TCP
servers. This driver is a *client* of those servers; it does not import solsdr
and does not touch the radio directly. Start solsdr on the host wired to the
SunSDR2, then point this driver at that host.

```
     SunSDR2 PRO ── UDP ──▶ solsdr appliance ──┬── control API  :5556 ─┐
                                               ├── RX IQ server :5555 ─┤ ← this driver
                                               ├── RX2 IQ       :5557 ─┤   (rf_bench.solsdr)
                                               └── TX IQ server :5558 ─┘
```

Launch solsdr with the servers you need:

```bash
# RX only, no RF possible (RX IQ server is on by default):
solsdr 14074 --control-api
# RX + control + arbitrary-waveform TX, armed to actually radiate:
solsdr 14074 --control-api --iq-tx-server --tx-arm
```
(The RX IQ server on :5555 is enabled by default; pass `--no-iq-server` to
disable it. The TX IQ server is opt-in with `--iq-tx-server`.)

## Status

🧪 **First release.** Protocol verified against solsdr's real server classes
(`drivers/solsdr/test_solsdr.py`) with a fake radio — control API
(freq/mode/preamp/rit/agc/nr/squelch/smeter/status), RX IQ capture/stream/
spectrum, and **TX-IQ** (samples accepted by solsdr's `IQTXServer`). Not yet
exercised end-to-end against a live SunSDR2 through this driver (solsdr's own
RX and TX are hardware-verified).

## Install

```bash
pip install -e drivers/solsdr --break-system-packages     # from the rf-bench tree
```

Depends only on `numpy`. (solsdr itself is a separate project on the radio host.)

## API

```python
from rf_bench.solsdr import SolSDR

with SolSDR("10.1.2.50") as sdr:          # host running solsdr
    sdr.set_frequency(14_074_000)          # Hz (range-checked 0.1–65 MHz)
    sdr.set_mode("USB")                    # USB LSB AM FM CW
    sdr.set_rf_gain(-10)                   # dB → nearest preamp/att step
    sdr.set_rit(250); sdr.set_agc("off"); sdr.set_nr(0.3); sdr.set_squelch(0.2)

    print(sdr.get_strength(), "dBFS")      # solsdr IQ S-meter (dBFS, not dBm)
    iq = sdr.capture_iq(65_536)            # complex64 from the RX IQ server
    freq_hz, power_db = sdr.power_spectrum(iq, rbw_hz=500)   # relative dB
    hits = sdr.scan_activity(threshold_db=20)
    for block in sdr.stream_iq(65_536):    # continuous blocks
        ...; sdr.stop_stream()

# Second receiver (solsdr launched with --rx2):
rx2 = SolSDR("10.1.2.50", rx=1)            # reads the :5557 IQ server

# Arbitrary-waveform transmit — the capability TCI can't do:
import numpy as np
with SolSDR("10.1.2.50") as sdr:
    fs = sdr.sample_rate                   # wire rate (from the IQ header)
    tone = 0.5*np.exp(2j*np.pi*1000*np.arange(int(fs))/fs).astype(np.complex64)
    sdr.transmit_iq(tone)                  # ⚠ solsdr must be --iq-tx-server --tx-arm
```

### Shared radio-API compatibility

`set_frequency`, `get_frequency`, `set_mode`, `get_mode`, `set_rf_gain`,
`get_strength`, `get_strength_settled`, `set_agc`, `close`, and the context
manager match the IC-7300 / FT-891 / TCI-SunSDR method names, so bench scripts
that target those radios run here unchanged.

### Deliberate `NotImplementedError`s (capability mismatch, not silent fallback)

- `set_sample_rate()` — solsdr's IQ rate is fixed at launch (`--rate`
  39062.5 / 78125 / 156250 / 312500). Read it via the `.sample_rate` property.
- `set_ptt()` — solsdr keys by *connecting* to the TX-IQ server; use
  `transmit_iq()`, which keys and unkeys automatically.

## Notes / gotchas

- **S-meter is dBFS, not dBm** — solsdr RX has no absolute power cal. `power_spectrum`
  power is relative (0 dB = peak bin). Use the SSA for absolute amplitude.
- **freq/mode readback is a driver shadow** — solsdr's control API tracks what
  was set *through* it, not the radio's live tuning. Set frequency via the
  driver and readback is exact.
- **TX rate must match the wire rate** — no resampler on the TX path. Feed
  `transmit_iq()` complex64 at `.sample_rate`.
- **TX radiates only if solsdr was started with `--tx-arm`** — otherwise the
  chain runs with no RF (safe wiring test). solsdr will transmit out of band and
  enforces nothing legal: dummy load or licence + antenna.

## See also

- `drivers/sunsdr/` — the TCI/ExpertSDR3 driver (RX + TX **audio**; no TX IQ).
- `ideas/solsdr.md`, `ideas/solsdr-projects.md` — the companion-project writeup
  and integrated project ideas.
- `drivers/mqtt/bridges/bridge_solsdr.py` — MQTT bridge for this driver.
