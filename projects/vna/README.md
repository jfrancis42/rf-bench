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
| [`return-loss-pdf/`](return-loss-pdf/) | 🧪 | S11 → return-loss-dB PDF with equivalent-VSWR axis. Author: 2026-06-30. |
| [`cable-loss-pdf/`](cable-loss-pdf/) | 🧪 | S21 THRU → cable insertion-loss PDF; optional dB/100ft panel with manufacturer overlay. |
| [`filter-pdf/`](filter-pdf/) | 🧪 | S21 → filter response with auto-detected -3/-6/-20/-40/-60 dB bandwidths, ripple, shape factor, stopband floor. |
| [`choke-pdf/`](choke-pdf/) | 🧪 | CM-choke series-through |Z| / R / X PDF (DX-Engineering / K6JCA method). |
| [`resonance-finder/`](resonance-finder/) | 🧪 | Auto-find S11 dips, fit -3 dB BW, report loaded Q. PDF + CSV. |
| [`balun-pdf/`](balun-pdf/) | 🧪 | Two-pass balun characterisation: RL + insertion loss + amplitude/phase balance. |
| [`connector-check/`](connector-check/) | 🧪 | Per-amateur-band PASS/FAIL return-loss check; PDF + JSON; non-zero exit on FAIL. |
| [`toroid-sniff/`](toroid-sniff/) | 🧪 | Wound-toroid L, Al, Q vs frequency + mix-consistency hint. |
| [`tdr-pdf/`](tdr-pdf/) | 🧪 | Host-side IFFT TDR (step + impulse) with cable-VF presets and fault auto-classification. |
| [`antenna/`](antenna/) | 🧪 | Full feed-point impedance: VSWR + R+X + Smith. Currently HP-only in code — porting to swappable API is a known TODO. |
| `filter/` | ❌ | Older HP-only filter-sweep stub. Use [`filter-pdf/`](filter-pdf/) instead. |
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
