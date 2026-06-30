# tline-pdf — Transmission-line characterisation PDF

Extract velocity factor (VF), characteristic impedance Z₀ (one of the
methods), and matched-line loss per unit length from a sample of
transmission line of known length.

Different from [`../cable-loss-pdf/`](../cable-loss-pdf/), which only
plots loss vs frequency: this script *derives the constants* of the
line (VF, loss/m, Z₀) for a sample whose properties you don't know
yet — including unknown-Z lines like twinlead, open-wire, or a PCB
microstrip.

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Two methods

### `--method s21` (default — fast, needs both ports)

```
VNA Port 1 ── tline ── VNA Port 2
```

One capture. Yields VF and loss/m. **Z₀ is ASSUMED = 50 Ω** (the
script reports it as "assumed" so you don't forget). This is fine for
RG-58 / RG-213 / LMR-400 / etc. where you already know Z₀ and only
want VF and loss numbers.

### `--method osl-s11` (slower, only one port, Z₀-yielding)

```
VNA Port 1 ── tline, far end OPEN     (capture 1)
VNA Port 1 ── tline, far end SHORT    (capture 2)
```

Two captures with a prompt between them. Yields **Z₀(f)**, VF, and
loss/m. Use this for anything whose Z₀ is unknown (twinlead,
ladder line, homebrew PCB stripline, salvage cable from the junk
box).

The math is the classical open-then-shorted method:

```
Z_open(f)  = Z₀_ref · (1 + Γ_open ) / (1 - Γ_open )
Z_short(f) = Z₀_ref · (1 + Γ_short) / (1 - Γ_short)
Z₀(f)      = sqrt(Z_open · Z_short)
γ(f)·L     = atanh(sqrt(Z_short / Z_open))
α(f)       = Re γ        Np/m  → ÷L for matched-line loss
β(f)       = Im γ        rad/m → VF = ω / (β · c₀)
```

A `β·L` phase-unwrap is applied past the quarter-wave fold.

## Setup gotcha — connectors dominate short samples

The "tline" sample is just the line, not a connectorised patch lead.
Connector reactance dominates short samples; use a sample at least
**5 wavelengths long at the highest swept frequency**. For 144 MHz
that's ~10 m of coax; for 1 GHz, ~1.5 m. Loss numbers from a 1-foot
sample of RG-58 are not believable above 500 MHz, even with
calibration.

Calibrate THRU (`s21`) or 1-port OSL (`osl-s11`) over the same sweep
range first.

## Usage

```bash
# 50 ft RG-58, fast method
python tline_pdf.py --start 1 --stop 500 --length-ft 50 \
    --label "50 ft RG-58 sample" --output rg58.pdf

# Unknown-Z twinlead — needs osl-s11
python tline_pdf.py --start 1 --stop 100 --length-m 6.0 \
    --method osl-s11 --label "6 m TV twinlead" --output twinlead.pdf

# Open-wire ladder line, 8 ft sample
python tline_pdf.py --start 0.5 --stop 50 --length-ft 8 \
    --method osl-s11 --label "8 ft 600-Ω ladder line" --output ladder.pdf

# Report loss in feet
python tline_pdf.py --start 1 --stop 1500 --length-m 10 --feet \
    --label "10 m LMR-400" --output lmr400.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--method {s21,osl-s11}` — see above; default `s21`
- `--length-m M` or `--length-ft FT` — **required**; sample length
- `--feet` — report loss as dB/100 ft (default dB/100 m)
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps (default 2)
- `--power DBM` — HP source power; ignored on NanoVNA
- `--no-prompt` — skip the OPEN/SHORT prompts in osl-s11 mode (use
  only when relays do the switching)

## Output

Two- or three-panel single-page PDF:

1. **Velocity factor vs frequency** — should be roughly flat for a
   normal line. A constant horizontal trace at, say, 0.66 is RG-58
   working as advertised. A trace that swings wildly is either a
   bad fixture or a dispersive line.
2. **Matched-line loss** in dB/100 m (or dB/100 ft with `--feet`).
3. **Z₀(f)** with |Z₀|, Re Z₀, Im Z₀ — only with `--method osl-s11`.

## NanoVNA vs HP — transmission-line specific notes

- **Z₀ extraction (osl-s11) noise:** Z₀ is derived from a square-root
  of two complex numbers, so any error in either capture propagates
  to Z₀. The NanoVNA's slightly higher trace noise shows up as
  ±2–5 Ω wobble on Z₀ traces. The HP's tighter calibration gives
  ±0.5–1 Ω. Either is fine for "is this a 50 Ω cable or a 75 Ω
  cable" decisions; for precision impedance work, prefer the HP
  once it's online.
- **VF accuracy:** both VNAs give VF to within ±0.005 for cables
  with stable dielectric. The s21 method uses a *group* velocity
  approximation (good to ~0.1 % for low-loss lines); for very lossy
  lines (RG-58 above 1 GHz, twinlead in rain), use osl-s11 where
  the math gives β directly.
- **Frequency range above 1.3 GHz:** the NanoVNA-F reaches 1.5 GHz
  fundamental; the HP 8712B stops at 1.3 GHz. For UHF and 23 cm
  band line characterisation, the NanoVNA is the only choice.

## Why no `--method osl-s11` with Z₀ assumption

A "single-pass open-only" or "single-pass short-only" measurement is
possible and is what cheap antenna analyzers do, but it does **not**
yield Z₀; it conflates VF, length, and Z₀ into one ambiguous answer.
The two-pass OSL method exists exactly because that ambiguity is
unresolvable with one capture.

## Notes

- This project effectively supersedes the legacy `../tline/` directory
  (HP-only stub). Once the HP is online, this script will run against
  it unchanged.
- The `cable-loss-pdf` project remains useful for the common case of
  "here is a 50 ft length of RG-58, plot dB/100 ft vs frequency
  against the published curve." This one is for "what kind of line
  is this even?"
