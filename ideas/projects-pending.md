## Hardware-pending projects

### HP 8712B VNA

**Status changed 2026-06-30 (revised):** the swappable VNA API is now
exercised by **fifteen** projects that run today on the NanoVNA-F.
See [`projects-built.md`](projects-built.md) for the current list:

- One-port S11: `swr-pdf`, `smith-pdf`, `return-loss-pdf`,
  `connector-check`, `resonance-finder`, **`impedance-pdf`**
- Two-port S21: `cable-loss-pdf`, `filter-pdf` (now with optional
  `--phase` / `--group-delay`), **`group-delay-pdf`**, `choke-pdf`,
  `toroid-sniff`, `balun-pdf`, **`tline-pdf`**, **`sparams-pdf`**
- Time-domain: `tdr-pdf`

(Bold = added on the 2026-06-30 second-pass port. See per-project
READMEs for "NanoVNA vs HP" capability/limitation notes.)

Each will gain HP support automatically once the KISS-488 adapter
arrives — the scripts are written against the shared method set. The
two-pass NanoVNA-specific workflows (`sparams-pdf` DUT-reversal,
`balun-pdf` leg-swap, `tline-pdf` osl-s11 open/short) collapse to
single-pass captures on the HP via `--vna hp`.

**Still genuinely HP-only:**

The only legacy project the swappable API can't subsume cleanly:

| Project | Why HP-only |
|---------|-------------|
| `transistor/` | Parametric S-param sweeps at every bias point. The DUT-reversal trick that gives the NanoVNA full 2-port operation in `sparams-pdf/` is impractical at every bias point of a bias sweep (an operator would have to flip the DUT 20×). HP captures all four natively, makes the bias sweep feasible. |

The remaining legacy directories (`antenna/`, `filter/`,
`group-delay/`, `impedance/`, `sparams/`, `tline/`) are **superseded**
by their `*-pdf/` equivalents above. They're kept on disk only for
historical reference and to remind us not to invest more time in
them.

**HP-vs-NanoVNA limitations callouts** are now part of every
swappable-API project's README. Per-project sections (search for
"NanoVNA vs HP" in each README) call out where one VNA is better:
dynamic range, calibration directivity, native S12/S22, hardware
averaging, phase noise, frequency range. The HP wins on dynamic
range / accuracy / measurement speed; the NanoVNA wins on
portability, top-end frequency reach (1.5 GHz fundamental vs 1.3 GHz),
low-end frequency reach (50 kHz vs 300 kHz), and cost.

**Bring-up plan** — once KISS-488 is installed:
1. Set HP 8712B GPIB address ≠ 16 (Solartron defaults to 16 too).
2. `*IDN?` smoke test through the KISS-488.
3. Single-frequency S11 spot measurement before attempting a sweep.
4. Run a SOLT cal sequence (manual, no automation yet).
5. Save cal to `~/.8712b_cal.json`.
6. Run `sparams-pdf/ --vna hp` against a known good filter as a
   regression test; verify the .s2p matches a NanoVNA `--vna nanovna`
   capture of the same filter (after the DUT-reversal step) to within
   the expected dynamic-range delta.

### Solartron 7151

(❌ blocked on KISS-488 adapter; code in `drivers/solartron/`.)

**Bring-up plan:**
1. Set GPIB DIP switches to a non-conflicting address (e.g. 5).
2. `++mode 1` / `++addr 5` / `A` (DCL) / wait 2 s for the RESTART message.
3. Switch to `U7N0T1` (CR delimiter, literals on, tracking on).
4. `M0R0I3` (DCV, autorange, 5.5 digits) → first reading.
5. Verify reader handles both `LITERALS ON` and `LITERALS OFF` reading
   formats and that the `!` overload flag is detected.

Once verified, the projects that benefit live in
[future Solartron applications](#future-solartron) below — voltage-reference
drift logger, TCR bridge, contact-resistance tester, micro-ohm battery IR,
log-detector linearity, and the cross-cal-with-SDM service.

### XL9535 relay

(❌ board ordered 2026-06-03; `projects/relay/` exists with code.)

| Project | Notes |
|---------|-------|
| `multidut/` | Multi-DUT routing for batch component characterization (crystal sort, capacitor bin, diode Vf match). On-board HK19F relays are fine here — DC/audio only. |
| `solt/` | Automated SOLT calibration fixture for the HP 8712B. **Use reed relays** in the RF path, not the on-board HK19F. |
| `filterbank/` | Band-switched LPF / BPF bank for transmitter / receiver test automation. **External RF-rated relays** driven by XL9535 outputs. |
| `router/` | N×M antenna / source / instrument router. **External coaxial relays.** |
| `normalize/` | 2-relay focused tool for source/DUT/through switching in scalar measurements. **External RF relays.** |

### KiwiSDR (pending)

See [projects/kiwisdr](#projectskiwisdr) — all 🧪 until IP is assigned and
the unit is bench-tested.

### SunSDR (pending)

See [projects/sunsdr](#projectssunsdr) — all 🧪 until ExpertSDR3 is online.
The TCI constraints in [cross-cutting bugs](#cross-cutting-bugs) are
mandatory reading before the first connection; in particular: ONE TCI
client at a time, audio defaults always come back as 48 000/float32/2
regardless of what was requested, and ExpertSDR3 has no TCI audio settings
other than on/off and port number.

---

