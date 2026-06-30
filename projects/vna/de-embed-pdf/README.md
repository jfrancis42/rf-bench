# de-embed-pdf — Mathematically remove a fixture from a measurement

Take a Touchstone .s2p of `fixture + DUT` cascaded, plus a separate
Touchstone .s2p of the fixture alone, and return a clean .s2p (and
side-by-side PDF) of the DUT by itself.

This is one of the highest-leverage VNA tricks. It moves the
reference plane from "at the SMA jack on the test fixture" to "at
the chip pad of the DUT." Every commercial VNA's "fixture
compensation" / "port extension" feature is built on this exact
math.

Pure post-processor — no hardware connection. Works identically with
`.s2p` files produced by either VNA (NanoVNA via the DUT-reversal
trick in `../sparams-pdf/`, or HP 8712B native).

## Topology assumption

The fixture sits as a **cascade** around the DUT:

```
[Port 1]──[Fixture in]──[DUT]──[Fixture out]──[Port 2]
```

The script supports two ways to describe the fixture:

### `--topology symmetric` (default)

You characterise one half of the fixture by replacing the DUT with a
THRU (or by some other half-jig method) and capturing those S-params
as a single .s2p. The script assumes the output-side fixture is the
**port-reversed mirror** of the input side. This is correct for any
fixture made of two identical launches.

```bash
de_embed_pdf.py --measurement filter_in_jig.s2p \
                --fixture jig_thru.s2p \
                --output filter_alone.pdf
```

### `--topology asymmetric --fixture-out OUT.s2p`

You characterise both sides of the fixture independently and pass
two .s2p files. Use this when the input launch and output launch
genuinely differ (different connector, different trace, an extra
attenuator on one side, etc.).

```bash
de_embed_pdf.py --measurement amp_in_jig.s2p \
                --fixture jig_in.s2p \
                --topology asymmetric --fixture-out jig_out.s2p \
                --output amp_alone.pdf
```

## How to characterise a fixture

The classic recipe — "OPEN, SHORT, LOAD on the DUT pads" — is a
1-port calibration, which doesn't give a full fixture .s2p. For the
2-port de-embed used here, the simplest practical approach is:

1. Build the fixture with the connector launch you intend to use, but
   with the DUT pads bridged by a precision THRU (a 0-Ω resistor at
   appropriate frequencies, or a precision SMD jumper).
2. Capture `--vna nanovna` (or `--vna hp`) two-port S-parameters
   through that THRU-fixture using
   [`../sparams-pdf/`](../sparams-pdf/). Save the resulting `.s2p`.
3. Now solder the real DUT in, capture the fixture+DUT cascade with
   the same VNA setup, save that as a second `.s2p`.
4. Feed both into this project; out comes the DUT alone.

For very-high-precision work, build separate OPEN / SHORT / LOAD
calibration standards on the fixture and use TRL (which a future
project will support). For amateur-grade work, the THRU method
above is fine and within a few dB across HF/VHF.

## The math, in 5 lines

```
T = s_to_t(S)
T_meas = T_fix_in · T_dut · T_fix_out
T_dut = inv(T_fix_in) · T_meas · inv(T_fix_out)
S_dut = t_to_s(T_dut)
```

Where T is the 2×2 scattering-transfer (a.k.a. T-parameter / ABCD-
like) matrix. T-parameters chain by matrix multiplication exactly
where S-parameters don't, which is why the algorithm goes
S → T → multiply → S. The S↔T conversion formulas are in the
docstring.

## Usage

```bash
# Common case: symmetric fixture, one .s2p describes both launches
python de_embed_pdf.py \
    --measurement filter_in_jig.s2p \
    --fixture jig_thru.s2p \
    --label "BAW filter at chip pad" \
    --output filter_at_pad.pdf
# → Wrote DUT.s2p alongside DUT.pdf (filter_at_pad.s2p)

# Asymmetric fixture (different input vs output launch)
python de_embed_pdf.py \
    --topology asymmetric \
    --measurement amp_full.s2p \
    --fixture amp_input.s2p \
    --fixture-out amp_output.s2p \
    --label "MMIC at die" \
    --output mmic_die.pdf
```

Flags:

- `--measurement MEAS.s2p` — **required**; the fixture + DUT cascade
- `--fixture FIX.s2p` — **required**; input-side fixture (or the
  only fixture file in `--topology symmetric`)
- `--fixture-out OUT.s2p` — required when `--topology asymmetric`
- `--topology {symmetric,asymmetric}` — fixture model (default
  `symmetric`)
- `--label TEXT` — chart title text
- `--output FILE.pdf` — **required**; PDF path
- `--touchstone FILE.s2p` — optional explicit Touchstone path
  (defaults to `<output-basename>.s2p`)

## Output

**PDF** — 4 × 2 grid: one row per S-parameter (S11, S21, S12, S22).
Each row shows magnitude (dB) on the left and unwrapped phase (°) on
the right, with the **measured** trace as a dashed grey line and the
**de-embedded DUT** trace as a solid colour line. The difference is
exactly what the fixture was hiding.

**Touchstone .s2p** — standard Touchstone v1, magnitude-angle
format, Z₀ = 50 Ω. Header comments note which measurement and
fixture files it was derived from and what topology was used.
Loadable into scikit-rf, ADS, AWR, QUCS, Sonnet, and LTspice (with
an s-parameter behavioural source).

## Verification

The math has been verified end-to-end with a synthetic round-trip:
construct known fixture S-params and known DUT S-params, cascade
them to make a synthetic measurement, run this script, compare the
recovered DUT to the original. Round-trips to machine precision
(~1e-16) on a 6 dB pad behind a lossy delay-line fixture.

For real captures the limiting factor is **fixture characterisation
noise** — a fixture .s2p that's noisier than the DUT effect you're
trying to extract will just amplify that noise. Use enough sweep
averaging on the fixture cal to drive its trace noise well below
the DUT's expected S-param levels.

## NanoVNA vs HP — de-embed-specific notes

- Pure post-processing. Both VNAs feed identical .s2p shapes into
  the script and get identical math back.
- The **practical** noise floor on a NanoVNA de-embed is set by the
  NanoVNA's dynamic range (~50–70 dB). If the fixture loss makes the
  measured signal hit −50 dB, the de-embedded DUT trace will be
  swamped by noise above whatever the DUT is doing.
- For deep stopband work (e.g., de-embedding a 70 dB filter behind a
  lossy launch), the HP 8712B's ~100 dB dynamic range is the only
  way to get a usable DUT trace.

## Notes

- The "fixture cascade" model assumes the fixture is two-port
  reciprocal at the de-embed reference planes. If your fixture
  contains a non-reciprocal element (an amplifier, a circulator),
  the .s2p file captures that correctly but the inverted T-matrix
  may be ill-conditioned. Real ham-grade fixtures are always
  reciprocal.
- For one-port DUTs (an antenna, a load), de-embedding is much
  simpler: take the fixture's S11 / S22 from your fixture .s2p and
  rotate the measured Γ on the Smith chart. That tool is a separate
  project, not this one.
- The frequency grid of the measurement and the fixture .s2p must
  match exactly (same sweep parameters). Interpolation is **not**
  done — the script errors out instead of producing silently-wrong
  results.
