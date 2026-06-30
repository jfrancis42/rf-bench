# VNA Projects

Vector-network-analyzer measurement projects. Scripts here target the
**swappable VNA API** shared by:

- `rf_bench.nanovna.NanoVNA` — NanoVNA-F (Deepelec) / -H / -H4 via USB CDC; **working today**
- `rf_bench.hp.HP8712B` — HP 8712B via KISS-488 Ethernet-GPIB; hardware pending

Pick the backend at runtime with the script's `--vna {nanovna,hp}` flag.

## Project status

| Project | Status | Notes |
|---------|--------|-------|
| [`swr-pdf/`](swr-pdf/) | ✅ | S11 → VSWR-vs-frequency single-page PDF. Tested 2026-06-30 against NanoVNA-F on 2 m, 70 cm, 3–30 MHz. |
| [`smith-pdf/`](smith-pdf/) | ✅ | S11 → Smith-chart single-page PDF. Tested 2026-06-30 against NanoVNA-F on 70 cm, 23 cm, and HF. |
| [`antenna/`](antenna/) | 🧪 | Full feed-point impedance: VSWR + R+X + Smith. Currently HP-only in code — porting to swappable API is a known TODO. |
| `filter/` | ❌ | Filter S21 + group delay sweep. HP 8712B pending. |
| `group-delay/` | ❌ | Group delay vs frequency. HP 8712B pending. |
| `impedance/` | ❌ | One-port impedance characterization. HP 8712B pending. |
| `sparams/` | ❌ | Full S-parameter capture (Touchstone export). HP 8712B pending. |
| `tline/` | ❌ | Transmission line characterization. HP 8712B pending. |
| `transistor/` | ❌ | RF transistor S-parameter extraction. HP 8712B pending. |

Status legend: ✅ tested · 🧪 limited testing · ❌ not yet run against hardware.

## Quick start (NanoVNA-F)

```bash
# 2m HT antenna VSWR sweep
python projects/vna/swr-pdf/swr_pdf.py \
    --start 144 --stop 148 --label "2m HT antenna" --output 2m.pdf

# HF antenna VSWR sweep (3–30 MHz)
python projects/vna/swr-pdf/swr_pdf.py \
    --start 3 --stop 30 --label "HF antenna" --output hf.pdf
```

See [`drivers/nanovna/README.md`](../../drivers/nanovna/README.md) for the
SOLT calibration walkthrough — antenna VSWR results are only as good as
the calibration that's loaded.
