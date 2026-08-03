# IQ-over-IP — design notes

*Rationale and plan for turning the
`modulate.py | hf-static.py | demodulate.py` chain into a real IQ-over-IP
system: a two-node peer link over the internet that scales to a central
"ionosphere" server aggregating many stations, giving them
**frequencies**, **locations**, **power**, and **antennas**, and letting
them **interfere** — a genuine simulated HF band you can learn on.*

> **This document is the "why" and the plan.** The **normative,
> byte-exact protocol** lives in **[`PROTOCOL.md`](PROTOCOL.md)** — packet
> layouts, endianness, the session state machine, timing rules, the mode
> registry, and every optional feature's wire contract. Where the two
> disagree, **`PROTOCOL.md` wins.** This file explains the reasoning and
> sequencing; it does **not** restate byte layouts.

---

## 1. Assumptions (locked)

Design constraints, not options to reconsider:

1. **IQ is the payload.** Complex baseband over the wire, not compressed
   audio. The IQ *is* the point — effects, the frequency model, and the
   link budget all operate on IQ.
2. **Zero content secrecy — by design.** This simulates HF, an open
   medium. Anyone may listen; nothing transmitted is encrypted. Identity,
   however, can be *authenticated* (that's separate from secrecy — see
   §8) so a hub can remove troublemakers. Every station IDs in the clear
   with a callsign.
3. **100% half-duplex, like real HF.** A station is transmitting XOR
   receiving — keying up makes you deaf to the band. One concession: a
   client MAY locally let the operator hear themselves (self-monitor /
   sidetone) — a local loopback, never a network feature.
4. **Frequency is first-class.** Every station has a dial (kHz). You hear
   what's near your dial and transmit on it. Nearby frequencies
   interfere — that's the fun.
5. **Location, power, and antennas are first-class.** Stations report a
   Maidenhead grid, TX power, and antenna type/heading; the path between
   any two is modeled as a real link budget.
6. **The transport is the open internet.** Assume loss, jitter,
   reordering. May or may not run inside WireGuard (addressing
   convenience only, not secrecy).
7. **Two topologies, one endpoint codebase.** Peer mode (two nodes, no
   server) and hub mode (many nodes → central *ionosphere*). Same wire
   format either way.
8. **Real-time audio survives clock skew by dropping/inserting packets.**
   On simulated HF a dropped packet sounds like a fade — so the fix is
   aesthetically free (§7).

---

## 2. The frequency model — what makes it a band

The heart of the design, and it falls out of one fact: **the IQ is
complex baseband centered at 0 Hz.** A signal's position on the band is
just a frequency *offset* applied by multiplying by a complex exponential.

A receiver tuned to dial `f_rx` renders a transmitter on `f_tx` by
shifting its baseband IQ by `Δf = f_tx − f_rx`, then summing:

```
rx_iq += tx_iq × exp(j·2π·Δf·t)      # frequency-translate, then sum
```

The receiver's normal USB/LSB/AM/FM/CW demod then runs on the summed
baseband. **Everything interesting emerges from this one shift-and-sum**
— no special-case interference code:

- **Δf = 0:** clean copy.
- **Δf = a few hundred Hz:** mistuned SSB — the classic pitch-shifted
  "Donald Duck" sound.
- **Δf = an audio tone from a carrier/CW station:** a **heterodyne
  whistle** at exactly `Δf` Hz. Real physics, for free.
- **Two SSB voices in the passband:** they sum into co-channel QRM, like
  a crowded 40 m evening.
- **|Δf| beyond ±(sample_rate/2):** inaudible (outside the window). At
  8 kSa/s complex you hear ±4 kHz around your dial.

**Consequences:** the dial roams a whole band; only stations within the
±(sample_rate/2) window are rendered (which conveniently bounds the hub's
per-listener work); frequency is carried per-packet and stateless; units
are Hz on the wire, kHz for display. Peer mode still has frequency — two
mistuned nodes heterodyne each other — but full adjacent-channel crowding
needs many stations, i.e. the hub.

---

## 3. Half-duplex, PTT, and self-monitor

- **Keyed (PTT down):** you transmit IQ on your dial and do **not** hear
  the band. In hub mode the hub stops sending you a mix while keyed (you're
  deaf anyway — saves bandwidth) and folds your signal into everyone
  else's mix at your frequency.
- **Unkeyed:** you receive; you send only keepalive + periodic ID. The
  handset PTT button (`modulate.py --ptt`, already built) is the natural
  key.
- **Self-monitor (optional, local, off by default):** loop your own
  modulate → demodulate back to your speaker to hear yourself while
  transmitting. Never touches the network.

Half-duplex is not just authentic — it's a load-bearing simplification.
It avoids echo cancellation and full-duplex audio routing entirely (a
huge win on mobile, §12), and it means a link only ever carries traffic
one direction at a time.

---

## 4. Grid-square path modeling — distance matters

Each station reports a Maidenhead grid (4-char, e.g. `DM79`, is plenty).
The hub uses the **pair** of grids — transmitter's and listener's — to
model how well the RF path between them works: a station two grids over
booms in; one on the far side of the simulated world is weak, fluttery,
or gone. Formal spec: `PROTOCOL.md` §21.

### It is per-pair, not per-frequency (the crux)

**You cannot apply one blanket "condition" to a frequency.** With A, B, C
near the same dial, A→B, A→C, and B→C are three different paths. The
correct model is an **N×N path matrix** — and it isn't a bolt-on, it's
just the inner term of the per-listener mix from §2:

```
for each listener L:
    L_mix = Σ over co-channel transmitters T≠L:  path(T→L).gain · effects( shift(T), path(T→L) )
```

Each listener hears a *different* blend, because each hears every other
station over that station's own path **to them** (up to K·(K−1) directed
paths for K co-channel stations; asymmetry A→B ≠ B→A is fine and free).
**The hub must never collapse a shared frequency to a single model.**

### Why it stays affordable

Sparse in practice: the ±(sample_rate/2) window means a transmitter only
enters a listener's sum if it's near that listener's dial, so each inner
loop is over the *handful* of co-channel stations, not everyone online.
Cost is O(listeners × co-channel-neighbors). The pathological case is
**everyone piled on one frequency** → O(N²); that's the load to
stress-test, mitigated by capping rendered co-channel stations per
listener (capture effect) or sharding a hot frequency — or by pushing the
work to clients (§11).

### The simulation knob

`path_quality(distance, bearing, frequency, time-of-day, …)` is entirely
hub-side policy — the protocol carries only the grids. That's where the
fun lives: distance-based **skip/dead zones**, distance-graded fading,
grey-line/time-of-day enhancement, per-band distance preferences — all
feeding distance-dependent parameters into the existing `hf-static.py`
effects. Grid is self-reported and unverified (consistent with zero
secrecy); spoofing it only changes your own simulated path.

---

## 5. Power and antennas — the link budget

Path loss is only half the story. Each station declares **transmit
power** (QRP 5 W → 20 W → 100 W → 500 W → legal-limit 1500 W) and an
**antenna** (vertical, dipole, beam/Yagi, end-fed, loop, mag-loop, mobile
whip) with a **heading**, turning the per-pair gain into a full link
budget:

```
signal(T→L) [dB] = P_tx  +  G_tx(bearing T→L)  +  G_rx(bearing L→T)  −  path_loss  (+ effects/noise)
```

Formal spec: `PROTOCOL.md` §22. This is where the project earns
"educational" — link budget is *the* core concept of practical radio, and
here it's audible.

### A beam is not magic — you must point it (reciprocity)

The link budget has **two** antenna terms: the transmitter's aim toward
the listener **and** the listener's own antenna aim toward the
transmitter. By reciprocity a directional antenna is directional on
**receive** too — one physical antenna, one heading, applied both ways:

- A beam pointed the wrong way makes you **deaf** to signals off its
  sides/back, not merely quieter on transmit.
- To work someone you must point at them on **both** ends — the classic
  "we're not pointed at each other" miss. Turning the rotator to hear a
  station is a modeled, audible action.
- An omni (vertical) hears all bearings equally — the tradeoff for its
  lack of gain. Beam-vs-vertical becomes a real decision: gain-but-aim
  vs. hears-everything-but-weak.

This is the same reciprocity that makes antennas inherently **per-pair**:
the bearing driving the gain is the `grid_bearing` already computed for
path modeling, so the antenna term is nearly free once grids are in play.

### The lessons it teaches

- **Power isn't everything:** 5 W→1500 W spans only ~25 dB, while antenna
  gain + pointing or a good-vs-dead path swing more. QRP-to-a-beam beats
  QRO-to-a-dud-antenna — made tangible.
- **Antenna choice and pointing matter:** vertical's low-angle DX vs.
  dipole's broadside pattern vs. beam's gain-and-nulls.
- Antenna patterns are a hub-side knob (crude cosine-lobe+F/B to elaborate
  elevation models using height). Protocol carries only the inputs.

Self-reported and unverified like grid. Everyone *will* claim 1500 W and a
beam — fine: the *relative* budget still differentiates via distance and
pointing, and a hub can optionally cap/normalize power per channel (e.g. a
QRP-only channel) as policy.

### Mobile operation (motion-limited, GPS-driven)

A phone/tablet client with GPS reports a **motion** state (fixed /
in-motion / stopped) derived from GPS speed. This enforces the physical
reality that **you can't run a beam and a kilowatt from a moving
vehicle**: while in motion the hub clamps the station to mobile-realistic
limits — capped power and an omni **mobile whip** — regardless of what it
requested (`PROTOCOL.md` §22.6). Bonus: the same GPS updates the `grid`
live as you drive, so a mobile station's path budget changes in real
time, making genuine mobile/portable operation a dynamic, first-class
activity. Desktop clients (no GPS) are simply "fixed" and unpenalized.

---

## 6. Where the effects run

The `hf-static.py` effects (Watterson / QRN / fading / …) are a
**pluggable IQ→IQ stage** usable in three places, but computed **once**:

- **Same code** on an endpoint (peer mode) or in the hub — keep the
  processing importable, not just a CLI pipe stage.
- **Interference is emergent** from the §2 shift-and-sum; the explicit
  heterodyne/splatter effects add flavor but aren't what creates
  adjacent-channel QRM.
- **Hub effects are per-listener / per-pair** — the whole reason the hub
  exists (§4).
- **Never twice:** a `FX_APPLIED` flag marks "effects already applied
  upstream" so a client behind a hub doesn't re-run them
  (`PROTOCOL.md` §10).

---

## 7. Engineering realities

### NAT — mostly a non-issue (one keepalive timer)

- **Hub mode:** clients dial *out* to the ionosphere's public address; the
  hub replies to the source ip:port it saw. That return path traverses
  essentially every consumer NAT with no STUN or hole-punching. Only need:
  a keepalive every ~15–20 s so the mapping doesn't age out.
- **Peer mode, one end reachable** (public IP, port-forward, or on the
  WireGuard overlay): equally trivial, same keepalive.
- **Peer mode, both behind NAT, no server:** the *only* hard case and an
  explicit **non-goal** — use the hub as a relay, or put one end on the
  VPN / a VPS / a forwarded port.

WireGuard, with secrecy off the table, is now *only* an addressing
convenience (stable `10.x` addresses). Build on bare UDP; lean on the
overlay when present; never require it.

### Clock skew — the sleeper bug, solved by drop/insert

Not NAT, not loss — **clock skew** separates a 30-second demo from an
hour-long QSO. Sound cards don't run at exactly 8000 Hz; the receive
buffer slowly drifts toward underrun or overflow. Fix: drive off buffer
fill and **drop/insert whole packets** (no resampler required, though one
is a cleaner upgrade):

- Target buffer ≈ 2–3 packets (~60–90 ms).
- Above high-water (sender faster) → **drop** a packet (sounds like a fade).
- Below low-water (starving) → **insert** a zero-IQ packet (also a fade).

At 8 kHz and a generous 50 ppm skew, drift is 0.4 samples/s — one packet
every ~10 minutes with 256-sample packets. Rare and essentially inaudible,
and thematically correct on simulated HF. In hub mode the ionosphere is
the clock master; in peer mode one end is nominated master. This is the
*same* mechanism as loss concealment: `seq`-gap or buffer management →
zero-fill → brief fade.

### Latency — VoIP class, hidden by half-duplex

Continental-US, `ci16`, ~256-sample (32 ms) packets:

```
capture/packetize 20–32 ms · modulate ~1 · network 15–50 (one-way)
· jitter buffer 40–60 (the knob) · shift+effects ~1–2 · demod ~1
· playback 20–32   →  ≈120–190 ms continental, ≈200–280 ms intercontinental
```

Fully usable, and half-duplex PTT hides it (you never talk over each
other). A few dropped packets cost ~nothing — the jitter buffer absorbs
them with zero added latency, and the artifact sounds like HF anyway.
Only *sustained* multi-percent loss forces a deeper buffer or coarser
format.

### Bandwidth — one direction, 8 kHz IQ

256-sample packets (31.25 pkt/s), IPv4:

| Format | Payload | Wire (app+UDP/IP) | + WireGuard |
|--------|---------|-------------------|-------------|
| `cf32` | 512 kbps | ~530 kbps | ~545 kbps |
| **`ci16`** | **256 kbps** | **~275 kbps** | **~290 kbps** |
| `ci8` | 128 kbps | ~150 kbps | ~165 kbps |

Half-duplex means a link peaks at the single-direction number. Framing
overhead is ~7%; the callsign/frequency/grid fields are ~1% — not worth
optimizing. **Recommendation (working well > low bandwidth): `ci16`.**
Audibly indistinguishable from `cf32`, half the bytes, trivial for any
broadband/VPN. `ci8` is the mobile/starved-link default.

---

## 8. Accounts, identity, and moderation

### Why accounts, given "zero secrecy"?

Moderation needs **accountable identity**, which is separate from content
secrecy. Assumption #2 keeps content open; it does **not** say anyone may
*claim to be* anyone. To kick and ban troublemakers you must bind each
session to a durable account and stop callsign spoofing — neither
encrypts a single IQ sample.

### Authenticate identity without encrypting content

A SCRAM-flavored **challenge–response** proves who a user is with no
content crypto (`PROTOCOL.md` §18):

- The password is **never sent**. The server stores a salted argon2id
  hash; at login it sends a nonce, the client returns `HMAC(key, nonce)`.
  A captured login can't be replayed and reveals no password.
- On success the hub issues a session **token** bound to the account +
  `stream_id`; later packets are checked against that binding — no
  per-packet crypto.

This adds authentication while adding zero confidentiality — exactly the
split the project wants. (If the login itself must resist an active
on-path attacker, run it inside WireGuard; the wire protocol adds none.)

### Accounts are hub-only

The ionosphere owns the account DB, authenticates logins, binds
`stream_id`+callsign to an account, and enforces moderation. **Peer mode
has no accounts** — you already chose who to connect to; "moderation" is
disconnecting. Accounts bolt onto the HELLO→WELCOME handshake; the DATA
path is unchanged.

- **Callsign is owned by an account** — this kills spoofing. The hub
  rejects any DATA whose callsign/`stream_id` doesn't match the
  authenticated binding, so a removed user can't return as someone else.
- **Anonymous receive-only listening** is allowed by default (listening
  is public); an account is required to **transmit**. Open to lurkers,
  accountable for anyone keying up.
- **Ban by account, not IP.** IPs churn; the account is the durable
  handle. IP/subnet blocks are a secondary flood-defense tool only.

### The three-tier moderation model

Moderation stacks three mechanisms, cheapest-social to heaviest — they're
complementary. All hub-only, all optional/capability-gated, all
design-stage (thresholds tuned against real behavior).

**Tier 1 — Channels + ops (primary, IRC-like).** The lightest, most
forgiving layer, and it maps onto the frequency concept: **a channel is
an independent band**, with its own frequency space, stations, and op(s);
the §2/§4 model runs independently inside each. A station is in one
channel at a time. Ops kick from *their* channel only — a kicked user
just moves elsewhere rather than being globally banned. This is how
healthy IRC/Discord communities self-govern; most "conflict" is really
"wrong room" and solves itself. (`PROTOCOL.md` §19. The alternative —
channel = a fuzzy frequency neighborhood — is rejected for unclear edge
ownership.)

**Tier 2 — Demerits (community signal, optional).** Since identity is
always known, users can flag abuse; enough weighted demerits triggers a
consequence. **The dominant risk is brigading**, so it's designed as a
*signal to human moderators, not an automatic sentence*
(`PROTOCOL.md` §20). Required safeguards: weight by distinct
accountability (a clique ≠ unrelated strangers), rate-limit per giver,
decay over time, reciprocity damping, and auto-action only at a high,
hard-to-brigade threshold with an audit trail. Sockpuppet amplification
is exactly why the FCC-verification question (below) matters — cheap
accounts make demerits cheap. Consequence ladder: rising demerits →
surface to ops → op discretion (warn/mute/kick) → only a very high total
auto-suspends (the *n-in-t → x-days* rule), logged and reversible.

**Tier 3 — Account ban (backstop, admin-only).** The durable hammer: by
account, permanent or time-boxed, for genuine bad actors who survive the
first two tiers. Used rarely.

```
wrong room / minor friction   → Tier 1: move channels, or op kick (local, instant)
pattern of abuse across users → Tier 2: weighted demerits surface it to ops
genuine bad actor             → Tier 3: admin account ban (global, durable)
```

Muting is clean because TX is explicit (the `KEYED` flag): the hub simply
omits a muted account from every listener's mix — the operator still sees
themselves keying (self-monitor works) but no one hears them.

### Registration and admin

Lightweight for a hobby service: self-serve signup (callsign + password),
optionally gated by admin approval or invite codes; callsign uniqueness
enforced; a small admin CLI/web console for mute/kick/ban and the roster.
The account DB is tiny (SQLite suffices).

**FCC callsign verification — OPTIONAL, UNDECIDED.** A hub *could* verify
a claimed callsign against the `govt-data` FCC `/callsigns` API at signup.
This is **not a legal requirement** — the system simulates HF but is *not*
radio, so no licensing rule applies. Its only value would be raising the
cost of sockpuppets, traded against excluding non-US and unlicensed
participants. Left to hub-operator policy; assumed nowhere in the protocol.

---

## 9. The wire format (conceptual — see `PROTOCOL.md` for bytes)

The protocol is **UDP, one packet per datagram**, each with an 8-byte
common header (magic, version, type, flags, length). Integer fields are
big-endian; **IQ sample bytes are little-endian** (they bulk-copy to/from
numpy/rtl buffers — byte-swapping every sample would be wasteful). Packet
types, at a glance:

- **DATA** — one block of IQ + its sender's stream_id, seq, timestamp,
  callsign, frequency, format/rate, mode.
- **TUNE** — the sender's authoritative per-station state: dial, key
  state, passband, mode, **grid, power, antenna+heading, motion**. Sent on
  change and ≥ every 5 s (doubles as keepalive).
- **ID** — periodic human beacon (name, grid, rig, notes) → roster.
- **HELLO / WELCOME** — join + version negotiation + capability/format
  exchange + (hub) account auth and session token.
- **AUTH_CHALLENGE / AUTH_RESPONSE / MODERATE** — the account and
  moderation layer (§8).
- **CHAN_LIST / JOIN / PART / CHAN_EVENT** — channels (§8 Tier 1).
- **DEMERIT** — community flag (§8 Tier 2).
- **SPECTRUM** — band-activity spectrum for a waterfall (§13).
- **PING / PONG / BYE** — keepalive/RTT and graceful leave.

Two identity choices worth calling out: the **callsign rides in every
DATA packet** (stateless — a receiver knows who a stream is from any
packet; ~3 kbps against a ~256 kbps payload), and the **authoritative
grid/power/antenna live in TUNE** (repeated, trusted state the hub keys
mixing on) rather than only in the human ID beacon.

**Versioning is explicit** (`PROTOCOL.md` §2.1): the header byte is the
*major* version; HELLO/WELCOME negotiate the highest common major and
carry a *minor* for backward-compatible additions. A hub with no version
overlap rejects with a `MODERATE(version-unsupported)`. New packet types,
modes, flags, and capability bits are all designed to be *ignorable* by
older peers, so most evolution is a minor bump.

---

## 10. The ionosphere hub — language and scaling

**Recommendation: write the hub in Python (numpy); you'll almost
certainly never need to leave it.** The "C++ for performance" instinct
aims at the wrong constraint — the DSP is not the bottleneck.

*(Numbers below are estimated/inferred — nothing is built or measured.
Treat as "hundreds vs. thousands," not precise.)*

**What bottlenecks the hub (not the DSP):** the shift-and-sum and effects
are cheap (numpy runs them as vectorized C). The real limit is **per-packet
Python glue + the GIL** — for each of ~31 pkt/s per listener there's
interpreter overhead, and the GIL pins one process to ≈ one core for it.
The **half-duplex windfall** helps enormously: only keyed stations are
sources (~1–5% at once), so cost is dominated by outbound mixing to
listeners ≈ `N_listeners × co-channel-transmitters`. The pathological case
is everyone on one frequency → O(N²) (see §4, §11).

| Approach | Simultaneous users (est.) | Limited by |
|----------|---------------------------|------------|
| Python, single asyncio process | ~100–300 | GIL / per-packet glue (1 core) |
| Python, multiprocessing (shard across 4 cores) | ~400–900 | per-packet glue × 4 |
| C/C++ | ~few thousand → then the **NIC** | bandwidth, not CPU |

At ~290 kbps/listener a 1 Gbps NIC caps near **~3,400 listeners**
regardless of language, so C++ mostly buys "CPU stops mattering before the
network does." The *ordering* is solid; the specific numbers are
order-of-magnitude.

**Why Python wins here:** experimentation is the hub's whole point (you'll
iterate endlessly on the frequency/path/effects model), hundreds of users
is far past realistic hobby demand, and there's a clean escape hatch — the
client's portable `libiono` C++ core (§11, §12) can be called from the hub
via pybind11 to drop *one* hot stage to C++ without rewriting the control
plane. Listeners are independent, so multiprocessing shards cleanly and
Python 3.13+ free-threading relaxes the GIL. Keep the DSP vectorized (no
per-sample Python loops); reach for C++ only if profiling ever demands it.

---

## 11. Pushing the N² to the edge (server-mix vs. edge-render)

The O(N²) hot-frequency cost needn't live on the hub. Two rendering
modes, chosen **per listener** and negotiable (`PROTOCOL.md` §23):

- **Server-mix (default, mandatory floor):** the hub does all the per-pair
  path + link-budget + effects math and sends each listener **one**
  finished stream. Simple clients, tiny downstream bandwidth, but the hub
  eats the N² in a pileup.
- **Edge-render (optional):** the hub stops mixing for a capable listener
  and **forwards the raw per-transmitter streams** plus each sender's
  frequency/grid/power/antenna metadata. The *client* does the
  shift-and-sum, path model, and link budget locally.

**It's a CPU-for-bandwidth trade.** Edge-render turns the hub's job into
cheap fan-out and moves the K−1 per-pair calculations onto the machine
that cares about the result — at the cost of pulling up to K−1 raw streams
(~256 kbps each). Great on a desktop/LAN; punishing on cellular.

Natural fit because **the client already has the DSP**: `libiono` *is* the
shift-and-sum + path + effects engine, and peer mode already renders an
incoming stream — edge-render is "do that for K streams." The sweet spot
is **adaptive hybrid**: default everyone to server-mix; auto-switch a
listener to edge-render only when its co-channel count crosses the
hub-straining threshold *and* it advertised the capability *and* has
bandwidth; keep mobile on server-mix; cap forwarded streams to the
nearest/strongest few (capture effect).

**One subtlety — shared reality.** Effects are random (fading/QRN); if each
client rolled its own, everyone's band would diverge and a QSO wouldn't
sound coherent. Fix: the hub stamps a shared per-transmitter fading
seed/envelope in the edge-render metadata so all clients reproduce the
*same* fade, while each computes its own bearing-dependent antenna+path
gain locally. Shared reality where it matters, offloaded math where it
counts.

---

## 12. Clients

### Cross-platform desktop (Mac / Windows / Linux)

**Not hard, and ~90–95% of the code is shared** — the same shape as the
existing Qt6 + PortAudio + `Qt-cross` radio apps (JF8Call, CodeMonkey,
OTA). The bulk of the work is porting the Python DSP to C++ and tuning
real-time audio, **not** anything platform-specific.

| Component | Portable | How | Rough LOC |
|-----------|:--------:|-----|----------:|
| IONO protocol codec | 100% | plain C++ | 800–1200 |
| DSP: AM/FM/USB/LSB/CW mod+demod, Hilbert, resample, AGC | 100% | port from `modulate.py`/`demodulate.py` | 2000–3500 |
| Frequency shift-and-sum + phase continuity | 100% | plain C++ | ~300 |
| Jitter buffer + clock-skew drop/insert | 100% | plain C++ | 400–600 |
| Session state machine + version negotiation | 100% | plain C++ | 600–1000 |
| Path model + link budget (grid/power/antenna) | 100% | plain C++ | 400–800 |
| Ionosphere effects (optional; port `hf-static.py`) | 100% | plain C++ + KissFFT | 1500–2500 |
| Networking (UDP) | ~100% | **QUdpSocket** → zero `#ifdef` | 200–400 |
| Audio I/O | ~100% | **PortAudio** (prebuilt in `Qt-cross`) | 300–500 |
| PTT / HID button | ~95% | **hidapi** (one lib, three backends) | 200–400 |
| GUI: waterfall, dial, roster, S-meter | 100% | **Qt6** | 2000–4000 |

**≈ 9,000–15,000 lines C++, ~90–95% shared.** The three choices that
collapse platform code to ~nothing: `QUdpSocket` (no Winsock `#ifdef`),
PortAudio (one API over CoreAudio/WASAPI/ALSA-PipeWire), and hidapi (the
only OS-divergent piece — wraps hidraw/IOKit/SetupAPI, so `ptt.py`'s logic
becomes ~200 shared lines).

What's actually hard is *not* portability: (1) DSP correctness —
phase-continuous frequency shift across packet boundaries (a MUST — clicks
if wrong), the jitter buffer, clock-skew drop/insert — written once,
shared, with the Python as the reference oracle; (2) glitch-free real-time
audio across three stacks (PortAudio abstracts the API, not the latency
behavior — budget tuning time, especially Windows WASAPI); (3)
packaging/signing (macOS notarization, Windows Authenticode, Linux
AppImage — annoyance, already solved for skyclock).

**Structure:** a portable **`libiono/`** static lib (protocol + DSP +
jitter/skew + session + path + effects — zero Qt, zero OS calls, KissFFT
only; a `gfsk8-modem-clean` sibling), a Qt6 GUI app linking it +
PortAudio + hidapi, built with the `Qt-cross` toolchains. Build a
**headless CLI `libiono`** regardless — it's the spec's reference client,
runs in CI, and proves `PROTOCOL.md` is implementable.

### Android and iPhone

**Viable; the hard part is already solved** — the protocol + DSP +
jitter/skew + session + path core is `libiono`, reused byte-for-byte. Only
audio plumbing, UI, and PTT gesture are new per platform. This is the same
split that already works for `android-aprs` (Kotlin UI over a shared
engine).

| Layer | Android | iOS | Reuse |
|-------|---------|-----|-------|
| `libiono` core | C++ via NDK/JNI | C++ via Obj-C++ bridge | **100% shared** |
| Audio I/O | **Oboe** | **AVAudioEngine** / Audio Units | thin, per-platform |
| PTT | touch button | touch button | trivial |
| UI | Compose / Canvas | SwiftUI / Metal | per-platform |

The one real constraint is **mobile audio**, and it's manageable — and
**half-duplex is a gift**: TX-xor-RX means you never run mic and speaker
together, sidestepping acoustic echo cancellation and full-duplex routing
entirely; PTT is touch-and-hold. Latency budgets are fine (Oboe / Audio
Units); mobile jitter dominates, so size the buffer a bit larger. Real
per-platform work is lifecycle plumbing (calls, backgrounding,
audio-focus).

Mobile also unlocks the **GPS motion feature** (§5): the phone knows when
it's moving and reports `motion`, so the hub applies mobile power/antenna
limits and updates the grid live. Watch **constant-bitrate IQ on
cellular** — `ci8` (~150 kbps) is the sensible mobile default (the header
already carries the format); it's an active-use activity, not a background
daemon. **Android is the lighter lift** (NDK + Oboe, sideload-friendly);
iOS is equally feasible modulo the Apple account / Mac-build / App Store
tax (be clear in the listing it's a simulation, not RF). A Flutter/RN
shell over a `libiono` FFI plugin could share UI too, but for a real-time
audio app, native audio + shared C++ core is the more reliable path. Ship
Android first.

---

## 13. Roadmap (build order — each stage independently useful)

1. **Framed peer link.** `ci16`, callsign+frequency in header, half-duplex
   PTT, no effects. mod → UDP send → UDP recv + jitter buffer → demod →
   speaker; one keepalive timer; optional self-monitor. Proves the wire
   format, jitter buffer, and half-duplex. Works on LAN/VPN/one-end-
   reachable today.
2. **Frequency shift-and-sum on RX + effects stage** (`--effects
   rx|tx|none`). Two mistuned nodes heterodyne/pitch-shift and can run
   `hf-static.py`. A band exists, for two.
3. **Clock-skew drop/insert + zero-fill loss concealment** (one
   mechanism). Survives a long QSO, not just a demo.
4. **Ionosphere hub: the frequency-aware per-listener mixer.** Ingests
   many stations, shift-and-sums those near each dial, per-pair effects,
   one stream per unkeyed listener. Endpoints don't change; the hub
   doubles as the reachability relay. Anonymous sessions first. Adjacent-
   frequency QRM comes alive here.
5. **Grid + link budget.** Add grid/power/antenna to TUNE and the per-pair
   path model + link budget (§4, §5), including beam reciprocity. Distance,
   power, and antennas now matter.
6. **Accounts + moderation.** Challenge-response login, token binding,
   spoof rejection; then channels (Tier 1), MODERATE notices, and demerits
   (Tier 2). Guest-listen/account-to-transmit is a policy toggle.
7. **Waterfall + roster + version negotiation polish.** SPECTRUM frames
   (§13-waterfall) driving a waterfall with click-to-tune; live roster
   from ID beacons.
8. **Edge-render, mobile apps, adaptive scaling** as demand warrants
   (§11, §12).

**Waterfall / "see other users":** the SPECTRUM packet is reserved now so
it can be added without a protocol break. The hub already knows every
station's frequency and level (it's summing them), so it can cheaply emit
compact band-activity spectrum frames (a few hundred bins, a few times a
second) as a separate low-rate stream — driving a waterfall with
click-to-tune, no wideband IQ needed.

---

## 14. Prior art worth stealing from (not adopting wholesale)

- **`rtl_tcp`** — ~200-line reference for uint8 IQ over the network.
  Format inspiration; it's TCP (head-of-line blocking) — use UDP.
- **ka9q-radio** — multicast IQ, RTP-style framing, real clock discipline;
  closest thing to an "ionosphere hub." Study its timestamp/packet
  handling and clock recovery.
- **SoapyRemote** — network transport under SoapySDR; format-negotiation
  pattern.
- **WebSDR / KiwiSDR / OpenWebRX** — the waterfall + click-to-tune UX and
  "many listeners on one band" model are exactly the frontend we'd want.
- **RTP** — don't adopt (audio-codec-shaped), but its
  sequence/timestamp/jitter-buffer design is the canonical reference our
  header mirrors. (We skip SRTP — see "zero secrecy.")
```
