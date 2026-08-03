# MQTT Map — ShuttleXpress Jog/Shuttle Controller

**Prefix:** `bench/shuttle`

## Published topics

| Topic | Type | Retain | Description |
|-------|------|--------|-------------|
| `bench/shuttle/jog` | int | no | Jog wheel step (+1 or -1 per detent) |
| `bench/shuttle/shuttle` | int | yes | Shuttle ring position (-7 to +7, spring-return) |
| `bench/shuttle/button/<n>` | bool | no | Button press event (buttons 1-5) |

## Command topics

None — the ShuttleXpress is an input-only device.

## Notes

- **Event-driven:** Messages publish on input events, not on a poll cycle.
- Jog events are NOT retained (relative encoder — no absolute position).
- Shuttle position IS retained (absolute position, spring returns to 0).
- Button events are NOT retained (momentary press, no hold state).

**Bridge script:** `drivers/mqtt/bridges/bridge_shuttlexpress.py`
