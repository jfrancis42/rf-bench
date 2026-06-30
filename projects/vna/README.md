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
| [`return-loss-pdf/`](return-loss-pdf/) | 🧪 | S11 → return-loss-dB PDF with equivalent-VSWR axis. |
| [`cable-loss-pdf/`](cable-loss-pdf/) | 🧪 | S21 THRU → cable insertion-loss PDF; optional dB/100ft panel with manufacturer overlay. |
| [`filter-pdf/`](filter-pdf/) | 🧪 | S21 → filter response with auto-detected -3/-6/-20/-40/-60 dB bandwidths, ripple, shape factor, stopband floor. **Optional `--phase` and `--group-delay` panels.** |
| [`group-delay-pdf/`](group-delay-pdf/) | 🧪 | Standalone S21 group-delay tool for amplifiers / cables / matching networks (\|S21\| + ∠S21 + τ_g panels). |
| [`impedance-pdf/`](impedance-pdf/) | 🧪 | Full one-port diagnostic: R + jX, \|Z\| + phase, VSWR, Smith locus, optional X=0 resonance hunter. **Supersedes** legacy `antenna/` and `impedance/`. |
| [`tline-pdf/`](tline-pdf/) | 🧪 | Transmission-line characterisation: VF, loss/m, and (with `--method osl-s11`) Z₀(f). Supersedes legacy `tline/`. |
| [`sparams-pdf/`](sparams-pdf/) | 🧪 | Full 2-port S-parameters PDF + Touchstone .s2p export. NanoVNA via DUT-reversal; HP 8712B native. Supersedes legacy `sparams/`. |
| [`choke-pdf/`](choke-pdf/) | 🧪 | CM-choke series-through |Z| / R / X PDF (DX-Engineering / K6JCA method). |
| [`resonance-finder/`](resonance-finder/) | 🧪 | Auto-find S11 dips, fit -3 dB BW, report loaded Q. PDF + CSV. |
| [`balun-pdf/`](balun-pdf/) | 🧪 | Two-pass balun characterisation: RL + insertion loss + amplitude/phase balance. |
| [`connector-check/`](connector-check/) | 🧪 | Per-amateur-band PASS/FAIL return-loss check; PDF + JSON; non-zero exit on FAIL. |
| [`toroid-sniff/`](toroid-sniff/) | 🧪 | Wound-toroid L, Al, Q vs frequency + mix-consistency hint. |
| [`tdr-pdf/`](tdr-pdf/) | 🧪 | Host-side IFFT TDR (step + impulse) with cable-VF presets and fault auto-classification. |
| [`antenna/`](antenna/) | 🧪 *(legacy, superseded)* | Full feed-point impedance: VSWR + R+X + Smith. Superseded by [`impedance-pdf/`](impedance-pdf/). Kept only for historical reference. |
| `filter/` | ❌ *(legacy, superseded)* | Older HP-only filter-sweep stub. Use [`filter-pdf/`](filter-pdf/) (with optional `--phase` / `--group-delay`). |
| `group-delay/` | ❌ *(legacy, superseded)* | Use [`group-delay-pdf/`](group-delay-pdf/) (standalone) or [`filter-pdf/ --group-delay`](filter-pdf/). |
| `impedance/` | ❌ *(legacy, superseded)* | Use [`impedance-pdf/`](impedance-pdf/). |
| `sparams/` | ❌ *(legacy, superseded)* | Use [`sparams-pdf/`](sparams-pdf/) (handles the NanoVNA DUT-reversal trick automatically). |
| `tline/` | ❌ *(legacy, superseded)* | Use [`tline-pdf/`](tline-pdf/). |
| `transistor/` | ❌ | RF transistor S-parameter extraction. Still HP-only — the DUT-reversal trick is impractical for bias-swept measurements. |

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
