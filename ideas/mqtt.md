# MQTT as the rf-bench Nervous System

## The Problem Today

Every rf-bench project is a point-to-point polling script. The SSA project
talks to the SSA. The PSU project talks to the PSU. If you want to correlate
SSA spectrum with PSU current, you write a third script that polls both.
Five instruments × five correlations = combinatorial explosion. Nothing
remembers what happened 10 minutes ago unless the specific project logged it.

## The Model Change

MQTT moves the bench from **point-to-point polling** to **publish/subscribe**.
Every instrument gets a thin bridge daemon that publishes its state to topics.
Any number of subscribers — dashboards, alert engines, databases, automation
scripts, phone apps — consume the data without touching instrument drivers.

The broker is the single integration point. Adding a new instrument makes it
visible to every existing consumer automatically, with zero per-combination
wiring.

---

## Topic Schema

Convention: `bench/<instrument>/<channel>/<measurement>`

```
bench/ssa/marker1/freq_hz          → 14.200e6
bench/ssa/marker1/level_dbm        → -42.3
bench/ssa/sweep_complete           → (timestamp)
bench/sdg/ch1/frequency_hz        → 1000000
bench/sdg/ch1/amplitude_vpp       → 1.0
bench/sdg/ch1/output              → 1
bench/scope/ch1/vpp               → 3.34
bench/scope/trigger/rate_hz       → 1000.0
bench/psu/ch1/voltage             → 13.82
bench/psu/ch1/current             → 2.14
bench/psu/ch1/output              → 1
bench/dmm/function                → VDC
bench/dmm/value                   → 4.9987
bench/dmm/range                   → 10V
bench/load/mode                   → CC
bench/load/voltage                → 12.04
bench/load/current                → 2.00
bench/load/power_w                → 24.1
bench/ic7300/frequency_hz         → 14200000
bench/ic7300/mode                 → USB
bench/ic7300/s_meter_dbm          → -73
bench/ic9700/frequency_hz         → 145900000
bench/ic9700/s_meter_dbm          → -85
bench/ft891/frequency_hz          → 7074000
bench/kestrel/temperature_c       → 24.6
bench/kestrel/relative_humidity   → 35.2
bench/kestrel/wind_speed_ms       → 2.4
bench/kestrel/pressure_mbar       → 795.3
bench/kestrel/altitude_ft         → 6570
bench/kestrel/rf_refractivity     → 312.4
bench/kestrel/density_altitude_ft → 7840
bench/kestrel/battery_percent     → 82
bench/rtlsdr/center_freq_hz      → 144390000
bench/rtlsdr/peak_power_dbfs     → -23.1
bench/nanovna/s11_db              → -18.4
bench/nanovna/vswr                → 1.28
bench/relay/ch1                   → 1
bench/relay/ch2                   → 0
bench/relay/ch3                   → 0
bench/relay/ch4                   → 0
bench/rotator/azimuth_deg        → 247
bench/rotator/elevation_deg      → 12
bench/gps/lat                    → 39.7392
bench/gps/lon                    → -104.9903
bench/gps/alt_m                  → 2003.0
bench/gps/speed_kmh              → 0.0
bench/phone/lat                  → 39.7401
bench/phone/lon                  → -104.9887
bench/phone/audio_dbfs           → -34.2
bench/mhs5225/ch1/frequency_hz   → 1000000
bench/mhs5225/counter/freq_hz    → 9999987.3
```

### Command topics (write-side)

Append `/set` to command an instrument. The bridge subscribes to these and
translates to driver calls:

```
bench/psu/ch1/voltage/set         ← 13.8
bench/psu/ch1/output/set          ← 1
bench/relay/ch1/set               ← 1
bench/ic7300/frequency_hz/set     ← 14250000
bench/ic7300/mode/set             ← USB
bench/rotator/azimuth_deg/set     ← 180
bench/sdg/ch1/frequency_hz/set   ← 5000000
bench/load/mode/set               ← CC
bench/load/current/set            ← 2.0
```

### Metadata topics

Each bridge publishes identity on connect:

```
bench/ssa/$model                  → SSA3032X Plus
bench/ssa/$ip                     → 10.1.1.60
bench/ssa/$driver                 → rf_bench.siglent.SSA3000X
bench/ssa/$poll_interval_ms       → 2000
bench/ssa/$online                 → 1  (retained; 0 = LWT on disconnect)
```

### Retained messages

All measurement topics use retained messages so new subscribers immediately
get the last known state without waiting for the next poll cycle. The `$online`
topic uses MQTT Last Will and Testament (LWT) to auto-publish `0` if the bridge
crashes.

### QoS

- Measurements: QoS 0 (fire and forget, high rate, loss acceptable)
- Commands (`/set`): QoS 1 (at least once delivery)
- Metadata (`$online`, `$model`): QoS 1, retained

---

## What This Enables

### 1. Cross-Instrument Correlation Without New Code

A generic time-series subscriber writes `bench/#` to InfluxDB or SQLite with
timestamps. Now you can query:

- "What was the PSU current when the SSA saw that spur?"
- "Does ambient temperature correlate with oscillator drift?"
- "Did the relay open before or after the SWR spike?"
- "What was the wind speed during each antenna pattern data point?"

Post-hoc analysis of anything against anything, without having written a
project for that specific correlation.

### 2. Triggering / Reactive Automation

Subscribe to one instrument, command another. Each trigger is ~10 lines:

- SSA detects signal above threshold → command RTL-SDR to record IQ
- SWR exceeds 2:1 → kill TX via relay, send SMS alert
- Kestrel refractivity rises above 350 → start VHF beacon logger
- Battery voltage drops below cutoff → open relay, alert
- IC-7300 frequency changes → re-aim antenna rotator
- Temperature exceeds limit → kill heater, page operator
- GPS enters geofence → start spectrum survey
- Oscillator drift exceeds 1 ppm → flag calibration needed

### 3. Distributed Measurement Synchronization

Multiple instruments on multiple machines (greybox at 10.1.0.16, NUC at
10.1.0.10, ESP32s on 10.1.1.x) all publish to one broker. A project that
needs coordinated timing doesn't need to poll three IPs — it subscribes to
three topics and messages arrive with LAN-level latency (~1 ms).

Timestamp alignment: each bridge publishes `<topic>/$timestamp` alongside
the value, using `time.time_ns()` from the host. Consumers align by
timestamp, not by arrival order.

### 4. Dashboards for Free

Grafana has native MQTT input (via the MQTT data source plugin). Virtual
instrument panels subscribe to topics instead of polling SCPI. The phone
app subscribes. Any new visualization built later gets all data — historical
via the time-series DB, live via MQTT subscription — without touching drivers.

Existing `virtual/` instruments could adopt MQTT as a second input mode
alongside their current SCPI TCP interface.

### 5. The Phone Becomes a First-Class Bench Node

The phone simultaneously **publishes** (GPS, mic level, camera lux,
accelerometer) and **subscribes** (alerts, instrument state for remote
monitoring). A single MQTT app with three screens — publish, subscribe,
alerts — covers all use cases.

### 6. Test Sequence Engine Becomes Trivial

The `projects-future.md` YAML workflow engine? With MQTT it's: subscribe to
trigger topic → publish commands → subscribe to result topics. The orchestrator
doesn't import any instrument drivers. It just publishes and subscribes to
topics. The bridges handle the driver layer.

```yaml
sequence:
  - subscribe: bench/ssa/marker1/level_dbm
    wait_until: value < -80
    timeout: 10s
  - publish: bench/relay/ch1/set = 1
  - publish: bench/psu/ch1/voltage/set = 13.8
  - subscribe: bench/load/voltage
    wait_until: value > 13.0
    timeout: 5s
  - publish: bench/ic7300/frequency_hz/set = 14200000
```

### 7. ESP32 Projects Gain Upstream Context

ESP32 SCPI controllers already speak TCP. Adding MQTT is trivial on ESP32
(PubSubClient library, ~20 lines). An ESP32 scpi-heater could subscribe to
`bench/kestrel/temperature_c` for ambient feedforward compensation. The
scpi-rotator could subscribe to `bench/satellite/azimuth_target` for real-time
satellite tracking without a host-side control loop.

### 8. Multi-User / Multi-Site

MQTT brokers support authentication and ACLs. A remote user on the VPN could
subscribe to `bench/#` read-only for monitoring, or be granted write access
to specific `/set` topics for remote operation. The eu.n0gq.org server could
bridge selected topics for low-latency remote access from Europe.

---

## Implementation

### Infrastructure

| Component | What | Effort |
|-----------|------|--------|
| Mosquitto broker | `apt install mosquitto` on 10.1.0.10 or dmz | 5 minutes |
| Broker config | Listeners, auth, ACLs, WebSocket port for web clients | 30 min |
| `rf_bench.mqtt` | New driver package: connection helper, topic builder, base bridge class | Half day |
| Topic schema doc | This document (done) | — |

### Bridge Daemons (one per instrument)

Each bridge is ~50–100 lines: instantiate driver, poll in a loop, publish.
Subscribe to `/set` topics, translate to driver commands.

| Bridge | Instrument | Poll interval | Notes |
|--------|-----------|---------------|-------|
| `mqtt-bridge-ssa` | SSA3032X | 2 s | Marker values, peak, span |
| `mqtt-bridge-sdg` | SDG1062X | 5 s | Frequency, amplitude, output state |
| `mqtt-bridge-psu` | SPD3303X-E | 1 s | V/I/P per channel, output state |
| `mqtt-bridge-dmm` | SDM3045X | 1 s | Measurement value, function, range |
| `mqtt-bridge-scope` | SDS2504X | 2 s | Vpp per channel, trigger rate |
| `mqtt-bridge-load` | ET5406A+ | 2 s | V/I/P/R, mode, protection |
| `mqtt-bridge-ic7300` | IC-7300 | 500 ms | Frequency, mode, S-meter |
| `mqtt-bridge-ic9700` | IC-9700 | 500 ms | Frequency, mode, S-meter, VFO |
| `mqtt-bridge-ft891` | FT-891 | 500 ms | Frequency, mode, S-meter |
| `mqtt-bridge-kestrel` | Kestrel 5500L | 4 s (BLE push) | All sensors + derived |
| `mqtt-bridge-rtlsdr` | RTL-SDR | 1 s | Center freq, peak power |
| `mqtt-bridge-nanovna` | NanoVNA-F | on-demand | S11, VSWR after sweep |
| `mqtt-bridge-gps` | gpsd | 1 s | Position, speed, heading |
| `mqtt-bridge-relay` | Arduino relay | 500 ms | Channel states |
| `mqtt-bridge-mhs5225` | MHS-5225A | 2 s | Frequency, counter |
| `mqtt-bridge-koolertron` | (alias for above) | — | — |
| `mqtt-bridge-rotator` | ESP32 scpi-rotator | 500 ms | Az/el |
| `mqtt-bridge-phone` | Android app | varies | GPS, mic, sensors |

Each bridge runs as a systemd service. Template unit file:
```
[Service]
ExecStart=/usr/bin/python3 /path/to/mqtt-bridge-<name>.py
Restart=always
RestartSec=5
```

### Subscribers / Consumers

| Consumer | What | Effort |
|----------|------|--------|
| Time-series logger | Subscribe `bench/#`, write to SQLite/InfluxDB | ~100 lines |
| Alert daemon | Threshold rules (YAML config), SMS via voipms | ~150 lines |
| Grafana | Native MQTT data source plugin, zero code | Config only |
| Phone app | Paho MQTT Android client, subscribe + publish | App project |
| Virtual instruments | Optional MQTT input alongside SCPI | ~20 lines/panel |
| Trigger scripts | Ad-hoc subscribe → action scripts | ~10 lines each |

### Base Bridge Class (`rf_bench.mqtt`)

```python
from rf_bench.mqtt import Bridge

class SSABridge(Bridge):
    prefix = "bench/ssa"
    poll_interval = 2.0

    def setup(self):
        self.ssa = SSA3000X("10.1.1.60")
        self.meta(model="SSA3032X Plus", ip="10.1.1.60",
                  driver="rf_bench.siglent.SSA3000X")

    def poll(self):
        self.publish("marker1/freq_hz", self.ssa.get_marker_freq(1))
        self.publish("marker1/level_dbm", self.ssa.get_marker_level(1))

    def on_command(self, subtopic, value):
        if subtopic == "marker1/freq_hz/set":
            self.ssa.set_marker(float(value), marker=1)
```

The base class handles: MQTT connection/reconnection, LWT, retained messages,
poll loop, `/set` subscription routing, graceful shutdown, systemd notify.

---

## Implementation Status

### ✅ Phase 1 — Foundation (COMPLETE, 2026-07-02)

- Mosquitto broker on **10.1.0.20** (dmz) — `allow_anonymous true`, always-on
- `rf_bench.mqtt` package built: `MQTTClient` (paho-mqtt wrapper, JSON envelope,
  retained messages, LWT), `Bridge` base class (poll loop, `/set` routing,
  `$online` LWT, graceful shutdown), `BridgeConfig` (CLI arg parsing)
- `DEFAULT_BROKER = "10.1.0.20"`, `DEFAULT_PORT = 1883`
- **26 bridges built** — all bench instruments covered
- Time-series logger (`subscribers/timeseries_logger.py`) — SQLite
- Alert daemon (`subscribers/alert_daemon.py`) — threshold rules (YAML) → SMS/log
- Round-trip verified: instruments → internal broker → bridge → public broker → phone

### ✅ Phase 2 — Core Bench Instruments (COMPLETE)

- Bridges for SSA, SDG, scope, DMM, load, IC-7300, IC-9700, FT-891, Kestrel,
  GPS, MHS-5225A, NanoVNA, relay, RTL-SDR, ShuttleXpress, KiwiSDR, SunSDR,
  Bus Pirate, Flipper, HP 8712B (HW pending), Solartron (HW pending), XL9535 (HW pending)
- Alert daemon with SMS via voipms proxy (`https://voip.n0gq.org`)

### ✅ Phase 2.5 — Public Access + Security (COMPLETE, 2026-07-02)

- Public broker on `us.n0gq.org:1883` — password auth, Mosquitto
- `mqtt.n0gq.org` CNAME → `us.n0gq.org` (DNSimple, Ansible-managed)
- Bidirectional bridge to internal broker (`topic # both 0`, WireGuard,
  `try_private false`, `bridge_protocol_version mqttv311`)
- fail2ban mosquitto jail: multiline regex, pyinotify backend, port-scoped
  banning (1883 only), 1-week ban, 5 retries in 10 minutes
- UFW allow TCP 1883 on us
- All infrastructure in Ansible (`~/skynet/ansible/configure.yml`, tag `[mqtt]`)
- Credential docs at `~/skynet/mqtt-credentials.md`
- Phone (IoT MQTT Panel) connects to public broker with user/password

### Phase 3 — Consumers and Automation (IN PROGRESS)

- ✅ Phone subscribes to bench topics via IoT MQTT Panel on `us.n0gq.org`
- ✅ `~/mqtt-relay.py` + `projects/relay/mqtt-relay/` — subscribes `/test/switch/{one,two,three,four}`, controls 4 Arduino relays
- ✅ `~/Dropbox/bin/key.py` — publishes random 6-digit key to `/test/key` every 60s
- 💭 Virtual instrument MQTT mode (subscribe instead of SCPI TCP)
- 💭 First trigger scripts (SWR protection, ducting alert)
- 💭 ESP32 projects subscribe to relevant topics

### Phase 4 — Advanced (FUTURE)

- YAML sequence engine
- Multi-site topic federation (eu.n0gq.org bridge)
- Correlation query engine (InfluxDB Flux or custom)
- Grafana dashboard

---

## What Stays the Same

Existing projects continue to work. SCPI polling is fine for single-instrument
scripts that run, measure, and exit. MQTT is additive — projects can optionally
subscribe to the bus for context ("what's the ambient temperature right now?")
without refactoring their core communication.

The benefit is **compounding**: every new instrument added to the bench
automatically becomes available to every existing dashboard, alert rule,
correlation query, and automation script. Zero integration work per new
combination.

---

## Dependencies

- `paho-mqtt>=2.0` — Python MQTT client (installed)
- `pyyaml` — alert daemon config only (installed)
- Mosquitto — MQTT broker (installed on 10.1.0.20 and us.n0gq.org)
- Optional: InfluxDB + Grafana for time-series visualization

---

## Resolved Questions

- **Broker placement:** dmz (10.1.0.20) — always-on, good network position,
  already a service host. Public access via us.n0gq.org bridge.
- **Topic value encoding:** JSON `{"value": <val>, "ts": <unix_float>}` for all
  bridge-published messages. External clients (IoT MQTT Panel) may send bare
  values; subscribers handle both.
- **Sweep/trace data:** Derived values on MQTT (peaks, markers, scalars). Raw
  traces stay on direct SCPI connections.
- **Poll rate vs event-driven:** Bridge base class supports both — `poll()` for
  SCPI instruments, override with async event loop for push-based (Kestrel BLE,
  ShuttleXpress evdev).
