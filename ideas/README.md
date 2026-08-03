# rf-bench — Reference and Project Index

The single reference for the bench: what hardware is here, which drivers exist and what state they're in, which projects are built vs planned, and the bugs and quirks that matter when using any of it.

This documentation is intentionally exhaustive. If something contradicts a per-driver or per-project README, the README wins — those track the code, this tracks the design intent and the cross-cutting context.

---

## Documentation Structure

| File | Contents |
|------|----------|
| **[status-legend.md](status-legend.md)** | Status markers used throughout docs (✅ 🔶 🧪 ❌ 💭) |
| **[hardware.md](hardware.md)** | Complete hardware inventory with specs, IPs, connections |
| **[drivers.md](drivers.md)** | Driver package status and PyPI publication state |
| **[virtual-panels.md](virtual-panels.md)** | Virtual instrument panel GUI tools |
| **[projects-built.md](projects-built.md)** | Completed projects organized by domain |
| **[projects-pending.md](projects-pending.md)** | Projects blocked on hardware acquisition |
| **[projects-future.md](projects-future.md)** | Future project ideas (12 categories, 100+ projects) |
| **[traceability.md](traceability.md)** | Bench-internal calibration chain plan |
| **[bugs-quirks.md](bugs-quirks.md)** | Cross-cutting instrument bugs and workarounds |
| **[shuttlexpress.md](shuttlexpress.md)** | ShuttleXpress jog/shuttle controller application ideas |
| **[kestrel.md](kestrel.md)** | Kestrel 5500L weather meter application ideas |
| **[fluke-80i400-projects.md](fluke-80i400-projects.md)** | Fluke 80i-400 AC current clamp — project ideas (3 built current-only, 1 built safety-gated power analyzer, 1 deferred), front-ends, "wrong tool" list |
| **[mqtt.md](mqtt.md)** | MQTT publish/subscribe bus — architecture, topic schema, 26 bridges, dual-broker infrastructure (internal + public with auth), implementation status |
| **[solsdr.md](solsdr.md)** | **solsdr** — standalone SunSDR2 PRO SDR (ExpertSDR3-free, raw UDP). Fully-integrated bench capability with a superpower nothing else here has: **transmit arbitrary IQ** (TCI cannot). Compares against the `rf_bench.sunsdr` TCI driver |
| **[solsdr-projects.md](solsdr-projects.md)** | Project ideas on solsdr's bidirectional IQ + audio — standalone and integrated with the bench (SSA/SDG/NanoVNA/DC load/MQTT/GPSDO) |

---

## Quick Links

**Start here:**
- New to the bench? Read [hardware.md](hardware.md) for inventory
- Looking for a project? Browse [projects-built.md](projects-built.md) or [projects-future.md](projects-future.md)
- Need arbitrary-waveform HF **transmit** (or a headless SunSDR2)? See [solsdr.md](solsdr.md) — the one radio here that can TX raw IQ
- Hit a bug? Check [bugs-quirks.md](bugs-quirks.md)

**By task:**
- Install a driver: [drivers.md](drivers.md)
- Find instrument IP: [hardware.md](hardware.md) → Hardware inventory table
- Check project status: [status-legend.md](status-legend.md) for marker meanings
- Plan calibration: [traceability.md](traceability.md)

---

## Status Legend

See [status-legend.md](status-legend.md) for full definitions.

| Marker | Meaning |
|--------|---------|
| ✅ | Built, tested against hardware, working well |
| 🔶 | Built, tested, has known limitations or is partially exercised |
| 🧪 | Code complete, limited or no hardware testing |
| 🔨 | Built to documentation, untested |
| ❌ | Hardware not present yet — code may exist, but is unverified |
| 💭 | Idea only — no code in the tree |

---

## Contributing

When adding new projects or hardware:
1. Add to appropriate file ([hardware.md](hardware.md), [projects-built.md](projects-built.md), [projects-future.md](projects-future.md))
2. Use correct status marker (see [status-legend.md](status-legend.md))
3. Update table of contents if adding new categories
4. Keep cross-references up to date (hardware → drivers → projects)

When documenting bugs:
- Add to [bugs-quirks.md](bugs-quirks.md)
- Link from affected project docs
- Include workarounds, not just problem descriptions
