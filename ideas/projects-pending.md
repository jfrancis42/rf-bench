## Hardware-pending projects

### HP 8712B VNA

(`projects/vna/` — all ❌, blocked on KISS-488 adapter.)

The HP 8712B adds **phase** to every measurement that the SSA scalar VNA
already does, plus full SOLT calibration.

| Project | Notes |
|---------|-------|
| `sparams/` | Full S11/S21/S12/S22 magnitude + phase; Touchstone .s2p export. |
| `group-delay/` | τ_g(f) = −dφ/dω from S21 phase; built-in `GDELAY` mode for cross-check. |
| `impedance/` | Z = R + jX from calibrated S11; Smith chart + Cartesian R/X plots. |
| `transistor/` | S-parameters + MAG / K-factor / stability circles / unilateral figure of merit. |
| `tline/` | Velocity factor, Z₀, attenuation α(f), propagation constant — from open-then-shorted S11 measurements at known length. |
| `filter/` | Filter passband ripple / stopband / shape factor / group delay; pass-fail mask. |
| `antenna/` | Feed-point Z = R + jX vs frequency; replaces the SSA scalar antenna analyzer for everything but its passband range. |

**Bring-up plan** — once KISS-488 is installed:
1. Set HP 8712B GPIB address ≠ 16 (Solartron defaults to 16 too).
2. `*IDN?` smoke test through the KISS-488.
3. Single-frequency S11 spot measurement before attempting a sweep.
4. Run a SOLT cal sequence (manual, no automation yet).
5. Save cal to `~/.8712b_cal.json`.
6. Run `sparams/` against a known good filter as a regression test.

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

