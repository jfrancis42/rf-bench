# solsdr — SunSDR2 PRO, ExpertSDR3-free (companion project)

**solsdr is a standalone project, not part of the rf-bench codebase**, but it is
considered a **fully integrated bench capability**: it fits the rf-bench model
(a network-attached RF instrument you drive from Python/other tools) and unlocks
things no other instrument here can do. Treat it as a first-class member of the
bench that happens to live in its own repo.

- **Location:** `~/Dropbox/build/solsdr/`
- **Repo:** `github.com/jfrancis42/solsdr` (public, GPLv2)
- **Author:** Jeff Francis, N0GQ
- **Status:** alpha; **RX and TX both hardware-verified on HF** (PRO).

---

## What it is, and why it matters to rf-bench

solsdr is a pure-Python SDR for the **Expert Electronics SunSDR2 PRO** that talks
the radio's **raw UDP protocol directly** — it **does not need ExpertSDR3 running
at all**. It wakes/powers-on the radio, tunes, streams RX IQ, demodulates, and
(TX) modulates audio→IQ *or* transmits **raw IQ** you hand it, all over the wire.

### solsdr vs. the existing `rf_bench.sunsdr` (TCI) driver — read this

rf-bench already has `rf_bench.sunsdr`, which drives the SunSDR2 over **ExpertSDR3's
TCI WebSocket**. The two are **not** redundant — solsdr is a strict superset for
the PRO:

| | `rf_bench.sunsdr` (TCI) | **solsdr** |
|---|---|---|
| Needs ExpertSDR3 running | **Yes** (TCI is an ExpertSDR3 feature) | **No** — talks the radio directly |
| RX IQ | ✅ (48/96/192 kS/s) | ✅ (39.0625 / 78.125 / 156.25 / 312.5 kS/s) |
| **TX IQ (arbitrary waveform out the antenna)** | ❌ **impossible over TCI** | ✅ **hardware-verified** |
| TX audio (SSB/AM/FM voice/data) | ✅ (audio sidecar) | ✅ (modulator) |
| Dual RX | ✅ | ✅ (RX2, phase-coherent γ²≈0.999) |
| Hardware-verified | 🧪 written to spec, untested | ✅ RX+TX on HF, on real hardware |

**The decisive point: TCI cannot transmit IQ.** Neither the TCI protocol, the
sidecar, nor ExpertSDR3 will accept raw IQ samples for transmit — TCI TX is
limited to the radio's own modulators (voice/data audio). solsdr transmits raw
complex baseband IQ straight out the antenna, verified into a dummy load
(2026-07-08). Any project needing **arbitrary-waveform HF transmit** — a custom
modem, a two-tone IMD test signal, an arbitrary-waveform RF source, a
transmit-side channel simulator — **must** use solsdr, not the TCI driver.

Rule of thumb:
- Want RX IQ and already run ExpertSDR3, or want the 192 kS/s rate → either works;
  `rf_bench.sunsdr` if ExpertSDR3 is up, solsdr if you want it headless.
- Want **TX IQ**, a **headless/no-GUI** setup, or **verified** behavior → **solsdr**.

---

## Network surface (how the bench talks to it)

solsdr is driven entirely over the network (no GUI, by design), which is exactly
the rf-bench interaction model:

| Service | Default port | Direction | Notes |
|---|---|---|---|
| Radio control (UDP) | 50001 | ↔ radio | client MUST bind source port 50001 |
| RX + TX IQ (UDP) | 50002 | ↔ radio | TX `0xFD` frames replace RX `0xFE` while keyed |
| **CAT via real Hamlib `rigctld`** | 4532 | client → | dummy backend; solsdr mirrors freq/mode/PTT to the radio |
| Text control API (TCP) | 5556 | client → | `freq/mode/ptt/power/preamp/rit/agc/nr/sql/smeter/status` |
| **RX IQ server (TCP)** | 5555 | → client | raw `complex64` + one-line header; **on by default**; GNU Radio TCP Source / `clients/panadapter.py` |
| RX2 IQ server (TCP) | 5557 | → client | second receiver, same format |
| **TX IQ server (TCP)** | 5558 | client → | client sends `complex64`; radio transmits it verbatim |
| Digital-mode audio bridge | (PulseAudio) | ↔ | virtual `solsdr-rx` / `solsdr-tx` sinks for JS8Call/WSJT-X/fldigi |

So a bench script can: read IQ from :5555, push IQ to transmit on :5558, set
frequency/mode/PTT via rigctld :4532 or the text API :5556, and (for voice/data)
move audio through the virtual sinks — all without ExpertSDR3.

**rf-bench client (in this tree):** `rf_bench.solsdr.SolSDR`
(`drivers/solsdr/`) is a network client of the servers above — RX IQ,
arbitrary-waveform TX IQ, control, S-meter, spectrum, dual RX — API-compatible
with the IC-7300/FT-891/TCI-SunSDR method names. MQTT bridge:
`drivers/mqtt/bridges/bridge_solsdr.py`. The driver needs **no solsdr changes**;
it only speaks the existing network protocol.

**Verified PRO facts** (see solsdr's `ARTEMISSDR.md`): DDC offset 0; Q-first
24-bit IQ; bidirectional keepalive on 50002; ~6–17 W across HF (per-band
wattmeter-calibrated); **transmits out of band** (no firmware band lock — the
operator is responsible for legality); RX2 stops during a key-down (single 50002
link carries TX, not RX). Protocol reverse-engineering originates with K0KOZ's
ArtemisSDR; solsdr contributes PRO corrections back.

---

## Integration caveats to respect

- **It transmits — including out of band — and has no authentication.** The RX
  IQ server binds all interfaces; the control + TX servers default to loopback
  but have no auth. On a shared bench LAN, treat the TX/control ports as
  privileged; don't expose them without a deliberate bind + your own gate.
- **Calibration is per-installation.** Absolute TX watts depend on the specific
  bench (tap/atten, coax, radio). solsdr ships example cal in `reference/cal/`
  (author's bench, ~6–17 W); recalibrate for any other setup.
- **PRO only, verified.** The DX profile is coded from ArtemisSDR but unrun.
- **TX pacing wants Linux** (`timerfd`; `SCHED_FIFO` needs `CAP_SYS_NICE`).

---

## Bench-integration project ideas

See **[solsdr-projects.md](solsdr-projects.md)** — projects that exploit
solsdr's unique **bidirectional IQ + bidirectional audio** to combine the
SunSDR2 PRO with the rest of the bench (SSA, SDG, NanoVNA, DC load, MQTT bus,
GPSDO, IC-9700, RTL-SDR, etc.).
