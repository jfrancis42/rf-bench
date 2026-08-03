# IQ-over-IP Protocol Specification

**Protocol name:** IONO (IQ-over-IP simulated-ionosphere protocol)
**Wire version:** 1
**Status:** DRAFT — not yet implemented. Subject to change until v1 is
frozen. Once frozen, `version = 1` is immutable and changes go to
`version = 2`.

This is the **normative** specification. An implementation that follows
this document will interoperate with any other conforming client and
with the ionosphere hub. The companion **[`iq-over-ip.md`](iq-over-ip.md)**
explains the rationale; where they disagree, **this document wins.**

The keywords **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and
**MAY** are used per RFC 2119.

---

## 1. Overview

IONO carries complex-baseband **IQ** over UDP between **stations**. A
station is either:

- an **endpoint** (a client: a human's radio), or
- the **ionosphere** (an optional central hub that aggregates many
  endpoints, mixes them per-frequency, applies channel effects, and
  returns a per-listener stream).

The same packet format is used in both **peer mode** (two endpoints,
direct) and **hub mode** (endpoints ↔ ionosphere). A conforming client
MUST implement the wire format identically regardless of peer.

**Radio semantics that shape the protocol:**

- Communication is **100% half-duplex**: a station is transmitting XOR
  receiving. A transmitting station does not receive.
- Every station has a **frequency** (a dial setting, in Hz). Signals are
  positioned on the band by a baseband frequency shift equal to the
  difference between transmit and receive dials. Interference between
  nearby frequencies is emergent, not special-cased (see §9).
- There is **no content encryption.** The simulated medium is public by
  design — anyone may listen, and nothing transmitted is secret. Do not
  add content secrecy; it is out of scope.
- **Authentication is separate from secrecy, and optional.** In peer mode
  there is no authentication at all. In hub mode the hub MAY require
  accounts (§18) so operators can be identified and troublemakers
  removed. This authenticates *who* a station is via challenge–response —
  passwords never travel and no IQ is ever encrypted — so the "no
  secrecy" property is preserved. Anonymous, receive-only listening MAY
  still be allowed even when transmitting requires an account.

---

## 2. Transport

- **Protocol:** UDP. TCP MUST NOT be used (head-of-line blocking breaks
  real-time audio).
- **Default port:** **57372** (`0xE01C`). Clients MAY use any port; the
  hub listens on 57372 unless configured otherwise.
- **Datagram = packet:** every UDP datagram contains exactly one IONO
  packet. Packets MUST NOT span datagrams; datagrams MUST NOT contain
  more than one packet.
- **MTU:** a packet including all headers and IP/UDP overhead SHOULD fit
  in 1400 bytes to avoid IP fragmentation. Senders MUST size DATA
  payloads accordingly (see §7.3).
- **Byte order:** all multi-byte integer fields are **big-endian
  (network byte order)**. IQ sample bytes follow the rules in §8.
- **Alignment:** the header is packed with no implicit padding. Fields
  are at the fixed offsets given below.

---

## 2.1 Protocol versioning and negotiation

The protocol will change over time. Every station MUST be able to
determine, definitively, what version its peer is speaking, and the hub
MUST have an unambiguous accept/reject decision.

### Version numbers

- The 1-byte header `version` (§3) is the **major** version. It changes
  **only** on a wire-incompatible change (field layout, semantics that a
  prior implementation would mis-handle). This document defines major
  version **1**.
- A finer-grained **minor** version is carried in the handshake
  (`HELLO`/`WELCOME`, §6.1/§6.2) as `minor_version`. Minor bumps are
  **backward-compatible** additions only (new optional packet types, new
  reserved-range values, new capability bits) that an older peer can
  safely ignore. Minor version is informational/telemetry; it MUST NOT
  change the meaning of any existing field.
- Rule of thumb: **if an old client would misinterpret it, bump major;
  if an old client can ignore it, bump minor.** New `ptype`,
  `mode`, `flags`, and `caps` values are deliberately designed to be
  ignorable (§4, §5, §11, §13), so most evolution is a minor bump.

### The definitive check (handshake)

Major version is negotiated **explicitly at the handshake**, not left to
per-packet guessing:

1. `HELLO` carries the client's `version` (header) and `min_version` /
   `max_version` it can speak (§6.1). This states a *range*, so a client
   that implements v1 and v2 can talk to either a v1 or v2 hub.
2. The hub picks the highest major version in the intersection of its own
   range and the client's. If the intersection is empty, the hub MUST
   reply `MODERATE` with `action = version-unsupported` (§18.4) carrying
   the hub's supported range in the reason, and MUST NOT create a
   session. The client SHOULD surface "server needs protocol vX–Y" to
   the operator.
3. On success, `WELCOME` echoes the **chosen** major `version` (header)
   and `minor_version` (§6.2). **All subsequent packets in the session
   MUST use the chosen major version.** The hub tags each session with
   its negotiated version and interprets that session's packets
   accordingly.

### Per-packet enforcement (post-handshake)

- A received packet whose header `version` differs from the session's
  negotiated major version MUST be dropped (it is a spoof, a stale
  datagram from a prior session, or a bug) — not reinterpreted.
- Outside a session (a stray packet from an unknown peer), a receiver
  MUST validate `magic` then `version`; an unknown major version is
  dropped without processing the body. Only during the explicit
  `HELLO` handshake does a version mismatch produce the negotiation /
  rejection reply above rather than a silent drop.

### Peer mode

Each endpoint sends its `min_version`/`max_version` in HELLO; both pick
the highest common major version. If there is no overlap, each SHOULD
report the mismatch to its operator and abort — there is no hub to send a
`MODERATE` rejection.

---

## 3. Common packet header

Every packet begins with this 8-byte fixed prefix:

| Offset | Size | Field    | Type | Description |
|-------:|-----:|----------|------|-------------|
| 0 | 2 | `magic`   | u16 | Constant `0x494F` (ASCII "IO"). Non-matching packets MUST be dropped. |
| 2 | 1 | `version` | u8  | Protocol **major** version. This spec = `1`. Present on **every** packet so a receiver can identify the sender's version from any datagram. A receiver MUST NOT process the body of a packet whose major version it does not implement (see §2.1 for the negotiation and rejection rules — do not just silently drop during the handshake). |
| 3 | 1 | `ptype`   | u8  | Packet type (§4). |
| 4 | 1 | `flags`   | u8  | Bit flags (§5). |
| 5 | 1 | `rsvd`    | u8  | Reserved. Senders MUST set 0; receivers MUST ignore. |
| 6 | 2 | `length`  | u16 | Total packet length in bytes, including this header. |

The remaining bytes (`length − 8`) are the type-specific body defined in
§6–§7.

---

## 4. Packet types (`ptype`)

| Value | Name | Direction | Purpose |
|------:|------|-----------|---------|
| 0 | `HELLO`    | endpoint → peer/hub | Join / announce presence; negotiate. |
| 1 | `WELCOME`  | hub → endpoint      | Accept; assign `stream_id`; report server caps. |
| 2 | `TUNE`     | endpoint → peer/hub | Set receive dial, key state, passband, mode. |
| 3 | `DATA`     | any → any           | One block of IQ samples. |
| 4 | `ID`       | endpoint → peer/hub | Beacon: callsign + human metadata. |
| 5 | `SPECTRUM` | hub → endpoint      | Band-activity spectrum for a waterfall. |
| 6 | `BYE`      | any → any           | Graceful leave. |
| 7 | `PING`     | any → any           | Keepalive / RTT probe. |
| 8 | `PONG`     | any → any           | Reply to `PING` (echoes its `nonce`). |
| 9 | `AUTH_CHALLENGE` | hub → endpoint | Challenge nonce + allowed auth methods (§18). |
| 10 | `AUTH_RESPONSE` | endpoint → hub | Challenge response (HMAC over nonce) (§18). |
| 11 | `MODERATE` | hub → endpoint     | Moderation notice: muted / kicked / banned + reason (§18). |
| 12 | `CHAN_LIST`  | any → any        | Request (empty) / reply (list of channels) (§19). |
| 13 | `JOIN`       | endpoint → hub   | Join a channel (§19). |
| 14 | `PART`       | endpoint → hub   | Leave the current channel (§19). |
| 15 | `CHAN_EVENT` | hub → endpoint   | Channel notice: joined / parted / kicked / op-changed (§19). |
| 16 | `DEMERIT`    | endpoint → hub   | Flag another station for abuse (§20). |

Values 17–255 are reserved. Receivers MUST ignore packets of unknown
`ptype` (forward compatibility).

---

## 5. Flags (`flags` bitfield)

| Bit | Mask | Name | Meaning |
|----:|-----:|------|---------|
| 0 | 0x01 | `KEYED`        | Sender is transmitting (PTT down). On DATA/TUNE. |
| 1 | 0x02 | `FX_APPLIED`   | Channel effects already applied upstream; a receiving endpoint MUST NOT apply effects again (§10). |
| 2 | 0x04 | `END_OF_TX`    | This is the final DATA packet of a transmission (unkey). Lets receivers close the stream promptly. |
| 3 | 0x08 | `CARRIER`      | Payload is a steady carrier (CW key-down / AM carrier) rather than voice; a hint for heterodyne rendering and waterfall. |
| 4–7 | — | reserved | Senders MUST set 0; receivers MUST ignore. |

---

## 6. Control packets

All string fields are **UTF-8**, **length-prefixed** with a single u8
length unless a fixed width is stated. `callsign` is the exception: a
fixed 12-byte ASCII field, null-padded, uppercase recommended.

### 6.1 HELLO (ptype 0)

Sent by an endpoint to a peer or the hub on startup, and retransmitted
every 1 s until a WELCOME (hub) or first DATA/PONG (peer) is received,
up to 10 attempts.

| Field | Type | Description |
|-------|------|-------------|
| `callsign` | char[12] | Station callsign. |
| `min_version` | u8 | Lowest **major** protocol version this client can speak (§2.1). |
| `max_version` | u8 | Highest major version this client can speak. The header `version` of the HELLO itself SHOULD equal `max_version`. |
| `minor_version` | u8 | Client's minor version for its `max_version` (informational; §2.1). |
| `caps` | u16 | Capability bits (§11). |
| `formats` | u8 | Bitmask of supported sample formats (bit0=cf32, bit1=ci16, bit2=ci8). |
| `preferred_rate` | u24 | Preferred IQ sample rate in Hz (e.g. 8000). |
| `intent` | u8 | Session intent (§18): 0 = anonymous/receive-only, 1 = authenticate (will send credentials). |

The hub MUST resolve the major version per §2.1 before anything else: if
its supported range does not overlap `[min_version, max_version]`, it
replies `MODERATE` (`action = version-unsupported`) and creates no
session.

If the hub requires accounts and `intent = 1`, the hub responds with
`AUTH_CHALLENGE` (not WELCOME) to begin the handshake (§18). If the hub
allows anonymous listening and `intent = 0`, it MAY respond with WELCOME
directly, granting a receive-only session. Peers ignore `intent`.

### 6.2 WELCOME (ptype 1)

Hub → endpoint, on a successful (possibly anonymous) join. Peers do not
send WELCOME.

| Field | Type | Description |
|-------|------|-------------|
| `version` | (header) | The **chosen** major version for this session (echoed in the WELCOME header per §2.1). All later session packets MUST use it. |
| `minor_version` | u8 | Hub's minor version for the chosen major (informational; §2.1). |
| `stream_id` | u32 | Identity assigned to this endpoint for the session. Endpoints MUST use it in all subsequent DATA. |
| `server_caps` | u16 | Hub capability bits (§11). |
| `chosen_format` | u8 | Sample format the hub will send/accept (0/1/2). |
| `chosen_rate` | u24 | IQ sample rate the hub operates at (Hz). |
| `band_low` | u32 | Lowest tunable frequency, Hz. |
| `band_high` | u32 | Highest tunable frequency, Hz. |
| `clock_epoch` | u32 | Hub's `timestamp` value "now"; endpoints discipline to this (§12). |
| `session_token` | u8[16] | Random session token bound to this session (and account, if authenticated). Zero-filled for a session with no token. See §18. |
| `role` | u8 | Granted role (§18): 0 = anonymous, 1 = user, 2 = op, 3 = admin. |
| `privs` | u8 | Privilege bits: bit0 = may transmit. An anonymous receive-only session has bit0 = 0. |

In **peer mode** there is no WELCOME, no token, and no roles. Each
endpoint self-assigns a random non-zero `stream_id` and picks the
format/rate from the intersection of both HELLOs' `formats`/
`preferred_rate` (lowest common format bit; matching rate required, else
abort).

### 6.3 TUNE (ptype 2)

Sets the sender's receive dial and state. Sent on any change and
repeated at least every 5 s (also serves as keepalive).

| Field | Type | Description |
|-------|------|-------------|
| `callsign` | char[12] | Sender. |
| `rx_frequency` | u32 | Receive dial, Hz. |
| `passband_low` | u16 | Demod passband low edge, Hz (e.g. 300). |
| `passband_high` | u16 | Demod passband high edge, Hz (e.g. 2700). |
| `mode` | u8 | Receiver's mode (§13). Informational for the hub/waterfall. |
| `key_state` | u8 | 0 = receiving, 1 = transmitting. (Mirrors `KEYED` flag; authoritative for control.) |
| `grid` | char[6] | Maidenhead locator, ASCII, null-padded. The station's **authoritative** location for path modeling (§21). A 4-char grid (e.g. `DM79`) uses the first 4 bytes; 6-char is accepted. Empty (all-null) = location unknown; the hub then MUST fall back to distance-agnostic behavior (§21). |
| `tx_power_w` | u16 | Transmit power in **watts** (e.g. 5, 20, 100, 500, 1500). 0 = unknown/default. Feeds the link budget (§22). |
| `antenna` | u8 | Antenna type (§22 registry): 0 = isotropic/unknown, 1 = vertical, 2 = dipole, 3 = beam/Yagi, 4 = end-fed/random wire, 5 = loop, 6 = mag-loop, 7 = mobile whip. |
| `ant_heading` | u16 | Antenna azimuth in degrees (0–359): boresight for a beam, wire-broadside for a dipole/loop. `0xFFFF` = omnidirectional / not applicable. |
| `ant_height_m` | u8 | Antenna height above ground in metres (0 = unknown). **Advisory**; a hub MAY use it to bias takeoff angle (§22). |
| `motion` | u8 | Mobility state (§22.6): 0 = fixed/stationary, 1 = mobile in motion, 2 = mobile stopped. Client-derived from GPS if available; 0 if no GPS. |

The hub uses `rx_frequency` + passband + mode to decide which
transmitters to mix for this listener and how wide a window to render,
and uses `grid`, `tx_power_w`, `antenna`, `ant_heading`, and
`ant_height_m` (this listener's versus each transmitter's) to model the
RF path and link budget between them (§21, §22). These are all carried
here — in the authoritative, repeated per-station state — rather than
only in the ID beacon, so the hub always has fresh, trusted values even
if an ID packet was lost.

`tx_power_w` is transmit-only (it matters when this station is keyed).
But **`antenna` and `ant_heading` describe one physical antenna used for
BOTH transmit and receive** — by reciprocity a beam has the same pattern
and points the same way whether you're talking or listening. So a
station's `ant_heading` is its RX antenna aim while receiving *and* its
TX aim while keyed. A station MAY update these at any time (change power,
rotate the beam); the change takes effect on the next mix. See §22.2 —
this is why a beam pointed the wrong way makes you deaf, not just quiet.

### 6.4 ID / beacon (ptype 4)

Human-readable metadata. Sent on join and every 30 s while connected.

| Field | Type | Description |
|-------|------|-------------|
| `callsign` | char[12] | Station. |
| `name` | u8-prefixed UTF-8 | Operator name. |
| `grid` | u8-prefixed UTF-8 | Maidenhead locator, for display/roster. This is the human-facing copy; the **authoritative** grid used for path modeling is the fixed field in TUNE (§6.3, §21). They SHOULD match; if they differ the hub uses the TUNE value. |
| `rig` | u8-prefixed UTF-8 | Rig / client description. |
| `notes` | u8-prefixed UTF-8 | Free text. |

Receivers and the hub build a live roster keyed by `callsign`. Loss of
an ID packet is harmless (callsign is also in every DATA packet).

### 6.5 BYE (ptype 6)

Body: `callsign` (char[12]). Best-effort; a station that vanishes is
also reaped by timeout (§12).

### 6.6 PING / PONG (ptypes 7 / 8)

Body: `nonce` (u32). PONG echoes the PING's `nonce`. Used for keepalive
and RTT/jitter estimation. Either side MAY send PING at any time; the
receiver MUST reply with PONG promptly.

---

## 7. DATA packet (ptype 3)

The workhorse. Header (§3) followed by this body, then the IQ payload.

### 7.1 DATA body layout

| Offset* | Size | Field | Type | Description |
|--------:|-----:|-------|------|-------------|
| 8  | 4  | `stream_id`   | u32 | Sending station's identity. |
| 12 | 4  | `seq`         | u32 | Per-`stream_id` packet counter; increments by 1 per DATA; wraps mod 2³². |
| 16 | 4  | `timestamp`   | u32 | Sample-clock time of the **first** sample in this packet, in samples since session start; wraps mod 2³². |
| 20 | 12 | `callsign`    | char[12] | Sender callsign (redundant with roster; always present). |
| 32 | 4  | `frequency`   | u32 | Sender's **transmit** dial, Hz. |
| 36 | 1  | `sample_fmt`  | u8  | 0=cf32, 1=ci16, 2=ci8 (§8). |
| 37 | 3  | `sample_rate` | u24 | IQ sample rate, Hz. Defines the receiver window width (±rate/2). |
| 40 | 1  | `mode`        | u8  | Sender's modulation mode (§13). Advisory (label/waterfall); demod is the receiver's choice. |
| 41 | 1  | `nchan`       | u8  | 1 = mono IQ stream (only value defined in v1). |
| 42 | 2  | `nsamples`    | u16 | Number of complex IQ samples in the payload. |

\* Offsets are from the start of the packet (header occupies 0–7).
DATA body header = 36 bytes; total fixed header = 44 bytes.

### 7.2 IQ payload

Immediately follows the DATA body at offset 44. Contains `nsamples`
complex samples, interleaved **I, Q, I, Q, …**, each component encoded
per `sample_fmt` (§8). Payload byte length = `nsamples × 2 ×
bytes_per_component`.

`length` (§3) MUST equal `44 + payload_bytes`.

### 7.3 Sizing

Choose `nsamples` so the whole datagram ≤ 1400 bytes:

| `sample_fmt` | bytes/sample (I+Q) | max `nsamples` @1400B | block ms @8kHz |
|--------------|-------------------:|----------------------:|---------------:|
| cf32 | 8 | 169 | 21 ms |
| ci16 | 4 | 339 | 42 ms |
| ci8  | 2 | 678 | 85 ms |

**Recommended:** 256 samples/packet (32 ms at 8 kHz) — a good
latency/overhead balance for all formats. Senders SHOULD keep a fixed
`nsamples` for the life of a transmission.

---

## 8. Sample formats

| `sample_fmt` | Name | Component | Range | Notes |
|-------------:|------|-----------|-------|-------|
| 0 | `cf32` | IEEE-754 float32 | nominal ±1.0 | **Little-endian** (matches numpy `complex64`, x86, `rtl` tooling). |
| 1 | `ci16` | signed int16 | −32768…32767 | **Little-endian.** Full-scale = ±32767 ≙ ±1.0. **Default/recommended.** |
| 2 | `ci8`  | signed int8  | −128…127 | Full-scale = ±127 ≙ ±1.0. For constrained links. |

**Endianness note (important):** the *protocol header* is big-endian
(§2), but **IQ sample components are little-endian.** This is
deliberate: sample data is bulk-copied to/from numpy/`libsoapy`/`rtl`
buffers that are natively little-endian on all target platforms, and
byte-swapping every sample would be wasteful. Header integers are rare
and benefit from network-standard big-endian. Implementers MUST honor
this split.

Conversion between formats is a scale: `ci16 = round(cf32 × 32767)`,
`ci8 = round(cf32 × 127)`, clamped to range.

---

## 9. Frequency and interference model

The IQ payload is complex baseband centered at 0 Hz. A receiver tuned to
`rx_frequency` renders a transmitter on `frequency` by shifting:

```
Δf      = tx.frequency − rx.rx_frequency          # Hz, may be ±
shifted = tx_iq[n] × exp(j · 2π · Δf · (t0 + n) / sample_rate)
rx_sum += shifted                                  # sum all audible tx
```

where `t0` is the receiver's sample index at the start of the block
(derived from `timestamp`, so the phase is continuous across packets —
implementations MUST maintain phase continuity or heterodynes will
click).

- A transmitter is **audible** iff `|Δf| < sample_rate/2`. Others MUST
  be discarded (they're outside the window).
- After summing all audible transmitters, the receiver runs its chosen
  **mode** demod (§13) over `[passband_low, passband_high]`.
- **Interference is emergent:** two carriers `Δf` apart produce a beat
  note at `Δf` Hz; two SSB voices in the passband sum into co-channel
  QRM; a slightly-off dial pitch-shifts a voice. No special-case code —
  it falls out of shift-and-sum.
- **Peer mode:** the single receiving endpoint performs this shift-and-
  sum for the one incoming stream (still gives mistuning/heterodyne
  between the two stations).
- **Hub mode:** the ionosphere performs it **per listener**, summing all
  transmitters near that listener's dial, weighting each by the
  grid-square path model between that transmitter and this listener
  (§21), then applies per-link effects (§10), then sends one DATA stream
  to that listener. This per-listener, per-pair rendering is why the hub
  exists.

Optional realism: the hub MAY apply an adjacent-channel gain taper
`gain(Δf)` (e.g. rolloff beyond the passband) and MAY add the explicit
`hf-static.py` effects on top. These are quality knobs, not required for
interoperability.

---

## 10. Effects and double-application

Channel effects (fading, QRN, Watterson, etc.) are an IQ→IQ transform.
They MAY run at the transmitting endpoint, the receiving endpoint, or the
hub — but **exactly once**.

- If a sender or hub has already applied effects to the IQ in a DATA
  packet, it MUST set the `FX_APPLIED` flag.
- A receiver that sees `FX_APPLIED` MUST NOT apply its own channel
  effects (it MAY still do frequency shift-and-sum and demod).
- In hub mode the hub normally owns effects and sets `FX_APPLIED` on all
  DATA it emits; endpoints behind a hub run with local effects disabled.

Effects parameters/negotiation are **out of scope** for v1 wire format
(they're a hub/endpoint local concern). The only wire contract is the
`FX_APPLIED` flag.

---

## 11. Capability bits (`caps` / `server_caps`)

| Bit | Mask | Name | Meaning |
|----:|-----:|------|---------|
| 0 | 0x0001 | `EFFECTS`    | Can apply channel effects. |
| 1 | 0x0002 | `SPECTRUM`   | Can produce (hub) / consume (endpoint) SPECTRUM. |
| 2 | 0x0004 | `MULTI_FREQ` | Hub renders true per-listener multi-transmitter mixing. |
| 3 | 0x0008 | `RELAY`      | Hub will relay for both-behind-NAT peers. |
| 4 | 0x0010 | `ACCOUNTS`   | Hub requires an account to transmit (§18). If set, an endpoint intending to transmit MUST authenticate; anonymous sessions are receive-only. |
| 5 | 0x0020 | `ANON_LISTEN`| Hub permits anonymous receive-only sessions. If clear, every session MUST authenticate. |
| 6 | 0x0040 | `CHANNELS`   | Hub organizes stations into channels (§19). If set, a station MUST JOIN a channel before transmitting. |
| 7 | 0x0080 | `DEMERITS`   | Hub accepts community demerit flags (§20). |
| 8 | 0x0100 | `EDGE_RENDER`| Hub (server_caps) can, / endpoint (caps) wants to, offload per-pair mixing to the client: hub forwards raw per-transmitter DATA + metadata and the client does shift-and-sum + link budget locally (§23). |
| 9–15 | — | reserved | Set 0; ignore unknown. |

Capabilities are advisory: a client MUST degrade gracefully if a peer
lacks a capability (e.g. no SPECTRUM → no waterfall, still works).

---

## 12. Session lifecycle, keepalive, and timeout

**Join (hub, anonymous):** endpoint sends HELLO with `intent = 0` →
hub replies WELCOME (with `role = 0`, `privs` bit0 = 0 if listen-only) →
endpoint sends first TUNE and ID → normal operation.

**Join (hub, authenticated):** endpoint sends HELLO with `intent = 1` →
hub replies `AUTH_CHALLENGE` → endpoint sends `AUTH_RESPONSE` → on success
hub replies WELCOME (with `session_token`, `role`, `privs`); on failure
hub replies `MODERATE` (reason = auth failed / banned) and closes. See
§18 for the handshake.

**Join (peer):** each endpoint sends HELLO until it receives the other's
HELLO or first DATA/PONG; both self-assign `stream_id`; formats/rate
resolved from the HELLO intersection. No auth, no token, no roles.

**Keepalive:** while connected, a station MUST send *something* at least
every **5 s** even when receiving and idle — a TUNE (preferred, carries
state) or a PING. This keeps NAT mappings alive and proves liveness.

**Timeout:** a station that sends nothing for **15 s** is considered
gone; peers/hub MUST reap it (as if BYE) and stop rendering it.

**Sequence & reordering:** receivers track `seq` per `stream_id`. A gap
indicates loss → conceal by inserting `nsamples` of zero-IQ (§14). A
`seq` older than the current playout point (late/reordered) MUST be
dropped. `seq` and `timestamp` both wrap mod 2³²; comparisons MUST use
serial-number arithmetic (RFC 1982 style).

**Clock discipline:** `timestamp` counts IQ samples. In hub mode
endpoints slave to the hub's `clock_epoch`/`timestamp`. The receiver's
playout is driven by its jitter buffer fill level (§14); it does not
assume the sender's clock equals its own.

---

## 13. Mode registry (extensibility for AM/FM/CW/…)

The `mode` byte (in DATA and TUNE) labels the **modulation** a station
is using. **Modulation and demodulation happen entirely at the
endpoints on plain IQ** — the wire carries only baseband IQ plus this
tag. The tag lets receivers auto-select a matching demod and lets the
waterfall/roster label signals. A receiver MAY demod with a different
mode than the sender's tag (e.g. copy an AM signal in SSB); the tag is
advisory, never mandatory.

**Registered modes (v1):**

| Value | Mode | Notes |
|------:|------|-------|
| 0 | `UNKNOWN`/unspecified | Treat as raw IQ; receiver chooses. |
| 1 | `USB` | Upper sideband. |
| 2 | `LSB` | Lower sideband. |
| 3 | `AM`  | Amplitude modulation (carrier + both sidebands). |
| 4 | `FM`  | Narrowband FM (default deviation 2500 Hz, see note). |
| 5 | `CW`  | On-off-keyed carrier; senders SHOULD set the `CARRIER` flag on key-down blocks. |
| 6 | `DATA-SSB` | Digital modes carried as SSB audio (FT8, PSK31, JS8, …). Tag only; the audio is opaque. |

**Values 7–199** are reserved for future assignment in later revisions
of this spec. **Values 200–255** are **experimental/vendor-private**: two
cooperating clients MAY use them for custom modes without registration.
An implementation encountering an unknown `mode` MUST treat it as
`UNKNOWN` (demod as raw IQ / its default) and MUST still render the
signal — an unknown mode never causes a drop.

**Adding a new standard mode** (process): the modulation is defined
purely in client code (how audio ↔ IQ is done). To make it
interoperable and labelable, a value from the reserved range is assigned
here with: the human name, the expected occupied bandwidth, any required
`flags` behavior (as CW requires `CARRIER`), and reference
modulate/demodulate parameters. No wire-format change is needed — which
is the point of keeping modes out of the transport.

---

## 14. Real-time maintenance (jitter buffer, loss, clock skew)

Conforming receivers MUST maintain real-time playout using a jitter
buffer with drop/insert, as follows (this is normative behavior, not
just guidance, because it affects what a sender can assume):

- **Buffer target:** 2–3 packets (≈60–90 ms at 256-sample blocks).
  Clients MAY tune this; larger = smoother + more latency.
- **Loss / gap:** on a missing `seq`, insert one packet of **zero IQ**
  of the expected `nsamples` at the correct `timestamp` slot. This reads
  as a brief fade — acceptable and thematically correct on simulated HF.
- **Clock skew — overflow:** if buffer fill exceeds the high-water mark
  (sender faster than local playout), **drop** one whole packet.
- **Clock skew — underflow:** if fill drops below the low-water mark
  (local playout faster / starving), **insert** one zero-IQ packet.
- Drop/insert is expected to fire rarely — at 8 kHz and 50 ppm skew,
  about once per ~10 minutes with 256-sample packets — and is
  effectively inaudible. A resampler-based discipline is a permitted
  higher-quality alternative.

A sender MUST NOT assume the receiver plays every packet at the sender's
exact rate; the receiver owns real-time and will drop/insert as needed.

---

## 15. SPECTRUM packet (ptype 5) — waterfall (optional)

Reserved and defined so a waterfall can be added without a protocol
break. Hub → endpoint, low rate (e.g. 5–15 Hz), one per listener,
covering the listener's current band window.

| Field | Type | Description |
|-------|------|-------------|
| `center_freq` | u32 | Window center, Hz (usually the listener's dial). |
| `span` | u32 | Total width covered, Hz. |
| `nbins` | u16 | Number of magnitude bins. |
| `ref_dbfs` | i16 | dBFS value that bin=255 maps to (scaling). |
| `bins` | u8[nbins] | Magnitudes, 0–255, linear in dB between floor and `ref_dbfs`. |

Clients without the `SPECTRUM` capability ignore these. A client MAY map
click-to-tune on the waterfall to a TUNE packet.

---

## 16. Reference constants

```
MAGIC          = 0x494F            # "IO"
VERSION_MAJOR  = 1                 # header byte; wire-incompatible bumps only
VERSION_MINOR  = 0                 # handshake; backward-compatible additions
DEFAULT_PORT   = 57372             # 0xE01C
KEEPALIVE_SEC  = 5
TIMEOUT_SEC    = 15
ID_BEACON_SEC  = 30
HELLO_RETRY    = 1 s, up to 10 tries
REC_NSAMPLES   = 256               # recommended block size
REC_FORMAT     = 1 (ci16)
REC_RATE       = 8000              # Hz
MAX_DATAGRAM   = 1400              # bytes, to avoid fragmentation
CALLSIGN_LEN   = 12                # fixed, null-padded ASCII
TOKEN_LEN      = 16                # session token bytes
NONCE_LEN      = 32                # auth challenge nonce bytes
AUTH_ALGO      = "HMAC-SHA256 over nonce, key = argon2id(password,salt)"
```

---

## 17. Conformance checklist (minimum viable client)

A minimal but conforming endpoint:

1. Sends HELLO with `min_version`/`max_version`; negotiates the major
   version per §2.1 (handles a `version-unsupported` `MODERATE` reply).
   In hub mode waits for WELCOME and uses the chosen version plus the
   assigned `stream_id`, format, and rate. If the hub sets `ACCOUNTS` and
   the client intends to transmit, completes the §18 challenge-response
   and stores the `session_token`; otherwise MAY join anonymously
   receive-only when the hub sets `ANON_LISTEN`.
2. Sends TUNE on change and ≥ every 5 s (including `rx_frequency`,
   `key_state`, `grid`, and — if it wants link-budget modeling —
   `tx_power_w`/`antenna`/`ant_heading`); sends ID on join and every
   30 s. Honors `MODERATE` notices (mute/kick/ban) and surfaces the
   reason to the operator. MAY send defaults (100 W, vertical, omni) and
   an empty grid and still interoperate.
3. Transmits (when keyed) DATA packets with correct header (session's
   negotiated `version`), `seq`, `timestamp`, `callsign`, `frequency`,
   `sample_fmt`, `sample_rate`, `mode`, `nsamples`, and little-endian IQ;
   sets `KEYED`; sets `END_OF_TX` on unkey.
4. Receives (when unkeyed): validates `magic` then `version` (drops
   packets not matching the session's negotiated major version), does
   frequency shift-and-sum (§9) with phase continuity, demods per its
   mode, and plays through a jitter buffer with drop/insert (§14).
5. Honors `FX_APPLIED` (§10). Honors half-duplex (no TX while RX and vice
   versa). Reaps peers after 15 s silence.
6. Ignores unknown `ptype`, unknown `mode` (→ UNKNOWN), and unknown
   `flags`/`caps` bits without dropping otherwise-valid packets.

Everything else — effects (§10), spectrum/waterfall (§15), multi-freq hub
mixing (§9), relay, accounts (§18), channels (§19), demerits (§20),
grid-square path modeling (§21), power/antenna link budget (§22), and
edge-render offload (§23) — is optional and negotiated via capabilities.
A minimal client runs SERVER_MIX only, MAY send an empty `grid` and
default power/antenna, and MAY ignore CHAN_*/SPECTRUM packets, and still
interoperates.

---

## 18. Accounts, authentication, and moderation (hub only)

Accounts exist so a hub operator can identify stations and remove
troublemakers. They are a **hub-mode-only** feature; **peer mode has no
accounts, no auth, and no roles.** Accounts add *authentication* (proving
identity), not *confidentiality* — no IQ is ever encrypted, and passwords
never travel (§18.2). A hub advertises account policy via the `ACCOUNTS`
and `ANON_LISTEN` capability bits (§11).

### 18.1 Identity binding and anti-spoofing

- A **callsign is owned by an account.** After a session authenticates,
  the hub binds `{account, callsign, stream_id, session_token,
  ip:port}`.
- The hub MUST reject any DATA/TUNE/ID whose `callsign` or `stream_id`
  does not match an active authenticated binding (silently drop, or reply
  `MODERATE` with an "identity mismatch" reason). This is what prevents a
  removed user from returning under someone else's callsign.
- Anonymous receive-only sessions get a `stream_id` but MUST NOT be
  granted transmit privilege (`privs` bit0 = 0). A hub MUST drop DATA
  from a session without transmit privilege.

### 18.2 Challenge–response handshake

Triggered when a client sends HELLO with `intent = 1` (or when a hub with
`ANON_LISTEN` clear requires auth from everyone).

**AUTH_CHALLENGE (ptype 9), hub → endpoint:**

| Field | Type | Description |
|-------|------|-------------|
| `nonce` | u8[32] | Random, single-use challenge. |
| `algo` | u8 | Auth algorithm id: 1 = HMAC-SHA256 with key = argon2id(password, salt). |
| `salt` | u8-prefixed bytes | Per-account KDF salt (so the client derives the same key the server stored). |

**AUTH_RESPONSE (ptype 10), endpoint → hub:**

| Field | Type | Description |
|-------|------|-------------|
| `callsign` | char[12] | Account/callsign being claimed. |
| `mac` | u8[32] | `HMAC-SHA256(key, nonce)`, `key = argon2id(password, salt)`. |

Rules:

- The password itself is **never transmitted**, in any form. The server
  stores only the argon2id material and verifies the `mac` against the
  challenge. A captured exchange cannot be replayed (nonce is one-time)
  and does not reveal the password.
- On success the hub sends WELCOME with a fresh random 16-byte
  `session_token`, the account's `role`, and `privs`.
- On failure (bad mac, unknown callsign, banned account) the hub sends
  `MODERATE` with the reason and does not create a session.
- This authenticates *identity only*. It provides no content secrecy —
  by design. If the login exchange itself must be protected from an
  active on-path attacker, run the whole protocol inside the optional
  WireGuard overlay; the wire protocol itself adds none.

### 18.3 Session token

- WELCOME carries a 16-byte `session_token` bound to the session.
- A hub MAY require the token to be echoed in a small fixed field on
  privileged control packets (e.g. TUNE while keyed) as a cheap
  anti-hijack check; per-DATA tokens are NOT required (the
  `stream_id`+ip:port binding covers the fast path).
- Tokens are session-scoped and invalidated on BYE, timeout, kick, or
  ban.

### 18.4 MODERATE packet (ptype 11), hub → endpoint

Notifies a client of a moderation action so it can react and tell the
operator *why* (rather than failing silently).

| Field | Type | Description |
|-------|------|-------------|
| `action` | u8 | 0 = info, 1 = muted, 2 = unmuted, 3 = kicked, 4 = banned, 5 = auth-failed, 6 = rate-limited, 7 = identity-mismatch, 8 = version-unsupported (reason carries the hub's supported major range). |
| `until` | u32 | Unix time the action expires (0 = permanent / not applicable). |
| `reason` | u8-prefixed UTF-8 | Human-readable reason string. |

On `kicked`/`banned`/`auth-failed` the hub also drops the session; the
client MUST stop transmitting and SHOULD surface the reason.

### 18.5 Roles and moderation actions

Roles (in WELCOME `role`): 0 = anonymous, 1 = user, 2 = op, 3 = admin.

| Action | Effect | Min role |
|--------|--------|----------|
| Mute (temp) | Hub refuses to fold the target's TX into any mix; target may still listen and self-monitor locally | op |
| Unmute | Clears a mute | op |
| Kick | Terminate session; token invalidated; re-login required | op |
| Ban | Account marked banned; future logins refused; active session killed | admin |
| Rate-limit | Automatic per-session cap on packets/s and TX duty cycle | (automatic) |
| IP block | Temporary drop of an ip/subnet; flood/DoS defense only, NOT the primary ban tool | admin |

Because half-duplex TX is explicit (`KEYED` / `key_state`), **muting is
clean**: the hub simply omits the muted account from every listener's
mix. The muted operator still sees themselves keying (local self-monitor
works) but no one hears them.

**Ban by account, not IP.** IPs churn (CGNAT, mobile, VPN); the durable
handle is the account. IP blocks are a secondary, temporary tool.

### 18.6 Registration (out of band)

Account creation is **not** part of the wire protocol — it happens via a
separate channel (a small web signup or admin CLI). The account store is
tiny at this scale (SQLite is sufficient). A hub MAY gate signup behind
admin approval or invite codes to curb throwaway accounts.

**Callsign-authenticity verification is OPTIONAL and undecided.** A hub
MAY verify a claimed callsign against an external registry (e.g. the
`govt-data` FCC `/callsigns` API) at signup. Note this is **not a legal
requirement** — this system simulates HF radio but is **not** radio, so
no licensing rule applies. Its only purpose would be to raise the cost of
sockpuppets and keep out some bad actors, at the cost of excluding
non-US and unlicensed participants. Left to hub-operator policy; the wire
protocol neither requires nor assumes it.

---

## 19. Channels (hub only, optional)

**Status: design-stage, not frozen.** Gated by the `CHANNELS` capability
(§11). Channels are the primary moderation tier (see `iq-over-ip.md`,
"Moderation model"). Peer mode has no channels.

### 19.1 Model

A **channel is an independent simulated band.** Each channel has its own
frequency space and its own set of stations; the frequency shift-and-sum
and interference model (§9) runs **independently within each channel** —
a station only hears, and only interferes with, stations in the *same*
channel. A station is in **exactly one channel at a time**.

- If the hub sets `CHANNELS`, a station MUST `JOIN` a channel before it
  may transmit. Until joined, it MAY receive nothing (or a lobby channel,
  hub's choice).
- Each channel has zero or more **channel ops**. Ops are scoped to their
  channel; a kick (§19.5) removes a station from *that channel only*, not
  the hub. The channel creator is op by default; the hub admin may grant
  op.
- `band_low`/`band_high` from WELCOME apply *per channel* unless a
  CHAN_EVENT overrides them for a specific channel.

### 19.2 CHAN_LIST (ptype 12)

Request (empty body) from endpoint → hub, or a hub → endpoint reply:

| Field | Type | Description |
|-------|------|-------------|
| `count` | u16 | Number of channel entries following. |
| `channels` | count × entry | See entry layout. |

Channel entry:

| Field | Type | Description |
|-------|------|-------------|
| `channel_id` | u32 | Stable channel identifier. |
| `name` | u8-prefixed UTF-8 | Channel name (e.g. "40m-ragchew"). |
| `n_stations` | u16 | Current occupancy. |
| `flags` | u8 | bit0 = requires op invite, bit1 = moderated (only ops TX), bit2 = private/unlisted. |
| `topic` | u8-prefixed UTF-8 | Short description / topic. |

### 19.3 JOIN (ptype 13), endpoint → hub

| Field | Type | Description |
|-------|------|-------------|
| `channel_id` | u32 | Channel to join. 0 = "create by name". |
| `name` | u8-prefixed UTF-8 | Used when `channel_id = 0` to create/find by name. |

The hub replies with a `CHAN_EVENT` (joined, with the resolved
`channel_id`) on success, or `MODERATE`/`CHAN_EVENT` with a refusal
reason (full, invite-only, banned from channel). Joining a new channel
implicitly PARTs the current one.

### 19.4 PART (ptype 14), endpoint → hub

Body: none (parts the current channel). Hub replies `CHAN_EVENT`
(parted). A parted station may not transmit until it JOINs again.

### 19.5 CHAN_EVENT (ptype 15), hub → endpoint

| Field | Type | Description |
|-------|------|-------------|
| `event` | u8 | 0 = joined, 1 = parted, 2 = kicked-from-channel, 3 = op-granted, 4 = op-revoked, 5 = topic-changed, 6 = refused. |
| `channel_id` | u32 | Channel the event concerns. |
| `target` | char[12] | Callsign the event concerns (self, or another for op/kick notices). |
| `until` | u32 | For kick: Unix time the channel-kick expires (0 = until reconnect). |
| `reason` | u8-prefixed UTF-8 | Human-readable reason / topic text. |

A **channel kick** (event 2) removes the target from that channel only.
The target MUST stop transmitting there and MAY JOIN a different channel
immediately. Contrast with §18 kick/ban, which are hub-global.

### 19.6 Ops vs. roles

The global `role` byte (§18.5) still governs hub-wide power (admin). A
**channel op** is a per-channel grant tracked by the hub and surfaced via
CHAN_EVENT (op-granted/op-revoked); it is *not* a global role change. An
op may kick within their channel; only a hub admin (`role = 3`) may
account-ban (§18).

---

## 20. Demerits (hub only, optional)

**Status: design-stage, not frozen.** Gated by the `DEMERITS` capability
(§11). Demerits are a *community signal to moderators*, not an automatic
sentence — see `iq-over-ip.md` "Moderation model, Tier 2" for the
rationale and anti-brigading design. Peer mode has no demerits.

### 20.1 DEMERIT (ptype 16), endpoint → hub

| Field | Type | Description |
|-------|------|-------------|
| `target` | char[12] | Callsign being flagged. |
| `category` | u8 | 0 = other, 1 = harassment, 2 = spam/flooding, 3 = deliberate QRM, 4 = hate speech. |
| `reason` | u8-prefixed UTF-8 | Optional free-text context. |

The hub records the demerit against the target account, attributed to the
*giver's* account. The giver is always known (authenticated session), so
demerits are attributable and auditable.

### 20.2 Required hub-side handling (anti-brigading)

A conforming hub that advertises `DEMERITS` MUST NOT act on raw counts.
It MUST:

- **De-duplicate by giver:** repeated demerits from the same account
  against the same target within a window count once.
- **Rate-limit per giver:** cap demerits a single account may issue per
  unit time.
- **Decay over time:** demerits age out (older ones weigh less / expire).
- **Weight by distinct accountability:** N demerits from one clique MUST
  count for less than N from unrelated accounts.
- **Prefer surfacing to ops over auto-action.** Automatic consequences
  (the *n-demerits-in-t → suspend-x-days* rule) are permitted only above
  a high, hard-to-brigade weighted threshold, and MUST be logged with an
  audit trail an op/admin can review and reverse.

Exact thresholds, weights, and decay curves are **hub policy** and out of
scope for the wire format. The wire contract is only the DEMERIT packet;
everything else is server-side and tunable.

### 20.3 Consequence ladder (recommended, not normative)

```
weighted demerits rising   → surface target to channel ops (CHAN_EVENT/MODERATE info)
op discretion             → warn / mute / channel-kick (§19)
very high weighted total  → automatic time-boxed suspension (MODERATE action=banned, until=now+x days), logged + reversible
```

Suspension reuses the §18 `MODERATE` machinery (`action = banned` with a
non-zero `until`); demerits add no new enforcement packet, only the input
signal.

---

## 21. Grid-square path modeling (hub only, optional)

**Status: design-stage, not frozen.** Uses the authoritative `grid`
field in TUNE (§6.3). Peer mode MAY apply a simplified two-station
version, but the interesting per-pair modeling is a hub feature.

### 21.1 Purpose

Each station reports a Maidenhead locator (4-char, e.g. `DM79`, is
enough; 6-char accepted). The hub uses the **pair of grids** — the
transmitter's and the listener's — to model how well the simulated RF
path between them works, and folds that into the per-listener mix (§9).
This is what makes distance matter: a station two grids away comes in
strong; one on the far side of the (simulated) world is weak, fluttery,
or absent.

### 21.2 Path is PER PAIR, not per frequency

**Critical: the path model is computed for every (transmitter → listener)
pair independently — there is no single "condition" for a frequency.**
With more than two stations on a frequency, one blanket model is wrong:
if A, B, and C are all near the same dial, the A→B path, A→C path, and
B→C path are all different (different distances, bearings, and therefore
different gain and fading). The correct structure is an **N×N path
matrix**, evaluated as the natural inner term of the per-listener sum
in §9:

```
for each listener L (unkeyed):
    L_sum = 0
    for each audible transmitter T near L's dial (T ≠ L):
        d        = grid_distance(T.grid, L.grid)      # great-circle km
        bearing  = grid_bearing(T.grid, L.grid)
        path     = path_quality(d, bearing, T.frequency, time_of_day, …)
        shifted  = shift(T_iq, T.freq − L.rx_freq)
        L_sum   += path.gain · effects(shifted, path)  # per-PAIR gain+effects
    send L_sum to L
```

So for a frequency with K co-channel stations, the hub evaluates up to
K·(K−1) directed paths — each listener hears a *different* blend because
each hears every other station over that station's own path to them.
This falls straight out of the §9 per-listener sum; path modeling only
adds the `path_quality` weight to each term. **A conforming hub MUST NOT
collapse this to a single per-frequency model** when more than two
stations share a frequency.

- **Asymmetry is fine and correct.** A→B need not equal B→A if the model
  isn't reciprocal (e.g. different local noise at each end); computing
  per directed pair preserves that naturally.
- **Cost:** the work is O(listeners × co-channel transmitters), which the
  §9 windowing already bounds — only stations within ±sample_rate/2 of a
  listener's dial enter that listener's sum, so the matrix is sparse in
  practice (most stations are on unrelated frequencies). See the
  scaling note in `iq-over-ip.md`.

`grid_distance` / `grid_bearing`: standard Maidenhead → lat/lon →
great-circle math (the `~/aviation-formulary/` routines or any
equivalent). 4-char grid resolves to ~1° × 2° — plenty for path
modeling.

`path_quality` is the **simulation knob** and is entirely hub-side policy
(out of scope for the wire format). It MAY consider distance (skip-zone
dead zones, multi-hop loss), the station's `frequency` (a "band" that
favors certain distances), a simulated time-of-day / solar model, and
feed distance-dependent parameters into the existing `hf-static.py`
effects (more Doppler spread / longer delay / deeper fading with
distance).

### 21.3 Emergent realism this enables

- **Skip / dead zones:** a `path_quality` that dips at short range on a
  given "band" reproduces the HF skip zone — nearby stations can't hear
  each other while distant ones can.
- **Distance-graded signal strength and fading:** far stations are
  weaker and more fluttery via distance-scaled effects, near ones solid.
- **Grey-line / time-of-day** enhancement if the hub runs a solar model.
- **Per-pair asymmetry** stays correct because it's computed per
  (T → L) term — A hearing B can differ from B hearing A.

### 21.4 Missing or bogus grids

- Empty `grid` (all-null) → the hub MUST fall back to a
  distance-agnostic path (e.g. flat gain, generic effects); a station
  with no location is simply "somewhere," not silenced.
- The hub SHOULD sanity-check grid syntax (`[A-R]{2}[0-9]{2}` for
  4-char) and treat malformed values as empty.
- Grid is **self-reported and unverified** by design — consistent with
  "zero secrecy." It's a simulation input, not a security claim; a user
  spoofing their grid only changes how their own simulated path behaves.

### 21.5 Client display

Clients MAY show each heard station's grid, distance, and bearing (the
roster already has the data). A future SPECTRUM/waterfall or map view
MAY plot stations by grid. None of this is required for interoperability.

---

## 22. Power and antennas — the link budget (hub only, optional)

**Status: design-stage, not frozen.** Uses `tx_power_w`, `antenna`,
`ant_heading`, `ant_height_m` from TUNE (§6.3). This extends §21's path
model into a full **link budget**, which is much of the educational
payoff: it lets the sim show *why* 5 W to a vertical struggles where
100 W to a beam gets through.

### 22.1 The link budget per pair

For each (transmitter T → listener L) term of the §9 / §21 sum, the
per-pair gain becomes a signal-strength budget in dB:

```
S(T→L) [dB] = P_tx(T)                       # 10·log10(tx_power_w) — QRP vs QRO
            + G_ant_tx(T, bearing T→L)       # TX antenna gain toward L (directional!)
            + G_ant_rx(L, bearing L→T)       # RX antenna gain toward T (directional!)
            − L_path(distance, freq, tod)    # §21 path loss / skip / absorption
            (− noise / + effects as in §21)
```

The linear gain applied to T's IQ in L's mix is `10^(S/20)`, clamped to
a sensible floor (below the noise floor → inaudible). Everything except
the two antenna terms is already in §21; power and antennas add the rest.

### 22.2 Antennas are directional — inherently per-pair

**This is the key reason power/antenna data lives per-pair, not
per-station.** A beam pointed at B provides gain toward B and little
toward C at a different bearing. So the TX antenna gain
`G_ant_tx(T, bearing T→L)` depends on the *bearing from T to L*, which is
exactly the `grid_bearing` already computed in §21. The same beam yields
different gains to different listeners in the same mix — which falls
straight out of the N×N matrix (§21.2) and cannot be collapsed to one
number per transmitter.

- **Vertical / isotropic / loop (omni-ish):** gain ≈ flat with azimuth;
  `ant_heading` ignored.
- **Dipole:** broadside gain, nulls off the ends; a smooth pattern
  keyed off `ant_heading` (wire orientation) vs. bearing.
- **Beam/Yagi:** forward gain + front-to-back ratio; strong function of
  `ant_heading` vs. bearing. This is where pointing matters and where
  rotating the beam (updating `ant_heading` in TUNE) visibly changes who
  hears you.

Exact antenna patterns are **hub-side policy** (out of scope for the
wire format) — from crude (a cosine lobe + fixed F/B) to elaborate
(modeled elevation patterns using `ant_height_m` for takeoff angle). The
protocol only carries the inputs.

### 22.2a A beam is not magic — you must point it (reciprocity)

The link-budget equation (§22.1) has **two** antenna terms:
`G_ant_tx` (the transmitter's aim toward the listener) **and**
`G_ant_rx` (the *listener's* own antenna aim toward the transmitter).
The RX term is not optional flavor — it means a directional antenna is
directional **on receive too**. A hub implementing §22 MUST apply the
listener's own `antenna`/`ant_heading` to every incoming term, so:

- A beam pointed the wrong way makes you **deaf** to signals off its
  sides/back — not merely quieter on transmit. If you're beaming Europe,
  the station behind you is down by the front-to-back ratio in your
  received mix.
- To work a station you must point at it on **both** ends — the classic
  "we're not pointed at each other" miss. Turning your rotator to hear
  someone is a modeled, audible action.
- An omni antenna (vertical/isotropic) hears all bearings equally — the
  tradeoff for its lack of gain. This makes the beam-vs-vertical choice a
  real decision: gain-but-must-aim vs. hears-everything-but-weak.

This is the same reciprocity that already makes antennas per-pair
(§22.2): one physical antenna, one heading, applied to both the transmit
term when keyed and the receive term when listening.

### 22.3 Antenna type registry (`antenna` byte)

| Value | Type | Azimuth pattern (suggested) |
|------:|------|------------------------------|
| 0 | isotropic / unknown | flat (0 dBi reference) |
| 1 | vertical | omni, low gain, low takeoff angle (DX-favoring) |
| 2 | dipole | broadside lobes, end nulls; `ant_heading` = wire azimuth |
| 3 | beam / Yagi | forward gain + F/B; `ant_heading` = boresight |
| 4 | end-fed / random wire | near-omni, modest, some ragged lobes |
| 5 | loop (full-wave) | mild directivity broadside to the loop plane |
| 6 | mag-loop | deep nulls broadside; sharp, orientation-sensitive |
| 7 | mobile whip | omni, poor efficiency (short/loaded); the mobile default (§22.6) |

Values 8–199 reserved for future assignment; 200–255
experimental/vendor-private. An unknown `antenna` value MUST be treated
as 0 (isotropic), never dropped.

### 22.4 Educational payoff and defaults

- Makes **link budget** tangible: power in dB (5 W→7 dBW, 100 W→20 dBW,
  1500 W→~32 dBW — only ~25 dB spans the whole QRP-to-legal-limit range,
  a great "power isn't everything" lesson), antenna gain, and path loss
  all add up to whether you're copyable.
- Rewards **pointing the beam** and shows the vertical's DX/NVIS
  tradeoff — real operating skills, learned safely.
- **Defaults for a minimal client:** `tx_power_w = 100`, `antenna = 1`
  (vertical), `ant_heading = 0xFFFF` (omni). A hub MUST render sensibly
  when a station supplies only defaults.

### 22.5 Honesty and abuse

Power/antenna are **self-reported and unverified** (like grid, and
consistent with "zero secrecy"). Yes, everyone can claim 1500 W and a
beam — and that's fine: if everyone's loud, the *relative* budget still
produces differences via distance and antenna pointing, and a hub MAY
optionally cap or normalize power per channel (policy, not protocol) if
an operator wants a QRP-only channel or a level playing field. The point
is pedagogical modeling, not enforcement.

### 22.6 Mobile operation (motion-limited power/antenna)

A phone/tablet client with GPS SHOULD report a `motion` state in TUNE
(0 fixed, 1 in-motion, 2 mobile-stopped), derived from GPS speed (e.g.
in-motion above a few km/h with hysteresis to avoid flapping at stop
lights). This lets the sim enforce the physical reality that **you can't
run a beam and a kilowatt from a moving vehicle**:

- When `motion = 1` (in motion), a hub applying §22 MUST clamp the
  station to **mobile-realistic** limits: capped power (e.g. ≤ 100 W)
  and an omnidirectional **mobile whip** (`antenna = 7`), regardless of
  the `tx_power_w`/`antenna` the client requested. `ant_heading` is
  ignored (whip is omni).
- When `motion = 2` (stopped — parked, a "mobile stationary" operation)
  the hub MAY relax toward the station's declared setup, or hold mobile
  limits until `motion = 0`; hub policy.
- `motion = 0` (fixed) or no GPS → the station's declared power/antenna
  apply normally. Absence of GPS is not penalized (desktop clients are
  simply fixed).

Exact thresholds and caps are **hub policy** (out of scope for the wire
format); the wire contract is only the `motion` byte. This is
self-reported like everything else — a user could lie — but honest
clients get a fun, realistic constraint: your grid also drifts as you
drive, so a mobile station's path budget changes in real time. The GPS
that supplies `motion` can equally update the `grid` field live (§21),
making genuine mobile/portable operation a first-class, dynamic activity.

---

## 23. Rendering modes: server-mix vs. edge-render (optional)

**Status: design-stage, not frozen.** Gated by the `EDGE_RENDER`
capability (§11). This addresses the O(N²) hot-frequency cost (§9, §21.2)
by letting clients do the per-pair math.

### 23.1 The two modes

- **SERVER_MIX (default, mandatory baseline).** The hub does everything:
  per-listener shift-and-sum, per-pair path + link budget (§21, §22),
  effects. It sends each listener **one** finished DATA stream. Simple
  client, heavier hub, minimal downstream bandwidth. Every conforming
  hub MUST support this.

- **EDGE_RENDER (optional).** For a listener that advertises
  `EDGE_RENDER` (and whose hub supports it), the hub does **not** mix.
  Instead it forwards the **raw per-transmitter DATA** of each co-channel
  station near that listener's dial, unmixed, each carrying the sender's
  authoritative `frequency`, `grid`, `tx_power_w`, `antenna`,
  `ant_heading` (available from that sender's TUNE). The **client** then
  performs the §9 shift-and-sum, the §21 path model, and the §22 link
  budget locally, using its own dial/grid/antenna as the RX side.

### 23.2 Why (and why not)

- **Moves the N² to the edge.** In a K-station pileup, SERVER_MIX makes
  the hub compute K·(K−1) directed paths; EDGE_RENDER pushes each
  listener's K−1 paths onto that listener's own CPU. The hub's job drops
  to *fan-out* (copy each transmitter's packets to the co-channel
  listeners) — cheap and parallel — instead of DSP.
- **Cost: downstream bandwidth.** Instead of one mixed stream, an
  EDGE_RENDER listener receives up to K−1 raw streams. At `ci16`/8 kHz
  that's ~256 kbps each — fine for a handful of co-channel stations on a
  desktop/LAN, punishing for many stations on mobile/cellular. So it's a
  **CPU-for-bandwidth trade**, chosen per listener.
- **Consistency knob.** Because effects have a random component
  (fading/QRN), pure client-side effects would make every listener's
  "band" diverge. To keep a shared reality where it matters, the hub MAY
  still stamp shared per-transmitter channel state (e.g. a fading seed or
  precomputed fading envelope) in an edge-render metadata field so all
  clients reproduce the *same* fade for a given transmitter; the
  bearing-dependent antenna + path gain is then computed locally. This
  keeps QSOs coherent while still offloading the heavy per-pair math.

### 23.3 Hybrid / adaptive

The mode is **per listener**, negotiated at join and changeable, so a hub
MAY:

- Use SERVER_MIX by default and switch a listener to EDGE_RENDER only
  when its co-channel count crosses a threshold (the exact case that
  strains the hub), if that client advertised `EDGE_RENDER` and has the
  bandwidth.
- Keep low-bandwidth/mobile clients on SERVER_MIX and offload only
  capable desktop clients.
- Cap raw forwarded streams (nearest/strongest few) to bound both hub
  fan-out and client work — the capture-effect mitigation from §21.2,
  applied to the forwarding path.

### 23.4 Requirements

- A client advertising `EDGE_RENDER` MUST implement the full §9/§21/§22
  math locally and MUST still accept SERVER_MIX (the hub may decline to
  offload).
- Raw forwarded DATA keeps the original sender's header fields intact
  (its `stream_id`, `frequency`, `callsign`, `sample_rate`); the client
  keys its per-transmitter jitter buffers on `stream_id` exactly as in
  peer/hub receive.
- `FX_APPLIED` (§10) still governs double-application: if the hub
  pre-applied shared effects before forwarding, it sets the flag and the
  client applies only the bearing/gain math it owns; if not, the client
  owns effects too.
- SERVER_MIX remains the interop floor: a minimal client implements only
  SERVER_MIX and never sets `EDGE_RENDER`.
