# MQTT Map — solsdr (ExpertSDR3-free SunSDR2 PRO)

**Prefix:** `bench/solsdr`

Bridges the `rf_bench.solsdr` network driver, which reads a running **solsdr**
appliance's control API (default port 5556). solsdr must be launched with
`--control-api`. Point the bridge at the host running solsdr with `--host`.

> Run only ONE SunSDR2 bridge against a given radio — either this
> (`bridge_solsdr.py`, direct/UDP) or `bridge_sunsdr.py` (TCI/ExpertSDR3), not
> both.

## Published topics

| Topic | Type | Unit | Description |
|-------|------|------|-------------|
| `bench/solsdr/online` | bool | — | solsdr control API reachable |
| `bench/solsdr/frequency_hz` | int | Hz | Tuned frequency (driver shadow / solsdr status) |
| `bench/solsdr/mode` | str | — | USB / LSB / AM / FM / CW |
| `bench/solsdr/streaming` | int | — | 1 while the RX IQ pipeline runs |
| `bench/solsdr/s_meter_dbfs` | float | dBFS | RX signal level (NOT dBm) |
| `bench/solsdr/ptt` | bool | — | solsdr status PTT flag |

## Command topics

| Topic | Type | Description |
|-------|------|-------------|
| `bench/solsdr/frequency_hz/set` | int | Tune (Hz) |
| `bench/solsdr/mode/set` | str | Set mode (USB/LSB/AM/FM/CW) |
| `bench/solsdr/rf_gain/set` | float | RF gain dB → nearest preamp/att step |
| `bench/solsdr/preamp/set` | str | -20 / -10 / 0 / +10 / off / preamp |
| `bench/solsdr/rit/set` | float | RIT offset Hz (0 = off) |
| `bench/solsdr/agc/set` | str | auto / on / off / fixed:\<g\> |
| `bench/solsdr/squelch/set` | float | Squelch 0–1 |
| `bench/solsdr/nr/set` | float | Noise reduction 0–1 |

**Note:** Raw IQ (RX and TX) is NOT carried over MQTT — use the driver directly
(`capture_iq` / `stream_iq` / `transmit_iq`). MQTT carries control + status only.

**Poll interval:** 1 s
**Bridge script:** `drivers/mqtt/bridges/bridge_solsdr.py`
**Run:** `python3 bridge_solsdr.py --host <solsdr-host> [--broker 10.1.0.20]`
