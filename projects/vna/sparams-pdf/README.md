# sparams-pdf — Full 2-port S-parameters PDF + Touchstone .s2p

All four S-parameters (S11, S21, S12, S22) with magnitude and phase,
in a single PDF and a Touchstone .s2p file. Two ways to capture them:

- **NanoVNA path (default):** the NanoVNA is a 1.5-port VNA — S11 +
  S21 in one shot, S22 + S12 require **physically reversing the
  DUT** between two passes. The script prompts between passes.
- **HP 8712B path:** the HP is full 2-port; one capture, all four
  S-parameters, no DUT flip. Selected automatically with `--vna hp`.

The two paths produce the same output format (`.pdf` and `.s2p`) so
downstream tools (scikit-rf, AWR / ADS, QUCS, Sonnet, etc.) don't
care which VNA the data came from.

## Why the DUT-reversal trick works

Reciprocity: a passive, linear, time-invariant DUT has S12 = S21 (and
S22 = S11 only if it's symmetric, which most DUTs aren't). For
**active or non-reciprocal** DUTs (amplifiers, isolators, circulators)
the two are different; the only way to measure both with a 1.5-port
VNA is to physically reverse the DUT.

When you reverse the DUT, what was "input" becomes "output" and vice
versa, so:
- The new S11 (port-1 reflection) is the original DUT's port-2
  reflection = **S22**.
- The new S21 (port-1 → port-2) is the original DUT's port-2 → port-1
  transmission = **S12**.

The script remaps automatically.

## Setup

```
Pass A:  VNA Port 1 ── DUT (forward orientation) ── VNA Port 2
Pass B:  VNA Port 1 ── DUT (REVERSED) ────────── VNA Port 2
```

**Critical rule for the swap:** physically flip the DUT only. Do
**not** move the port-1 or port-2 cables. If you have to reroute
cabling (a heavy / bolt-down DUT), the calibration is no longer
valid in both orientations — you'll see a discontinuity at the
S11/S22 boundary that doesn't really exist.

Run a full SOLT (or at minimum 1-port OSL on both ports + a THRU)
calibration over the same sweep range first and save it to a flash
slot before measuring.

Works with either of the swappable VNA drivers:

- `rf_bench.nanovna.NanoVNA` — **default**, USB CDC at `/dev/ttyACM1`
- `rf_bench.hp.HP8712B` — KISS-488 Ethernet-GPIB at `10.1.1.70`

## Usage

```bash
# Bandpass filter on the NanoVNA — interactive two-pass
python sparams_pdf.py --start 100 --stop 200 \
    --label "2 m bandpass filter" --output 2m_bpf.pdf
# Console prompts: "Connect forward, press Enter" → captures.
# Console prompts: "Reverse the DUT, press Enter" → captures, writes both files.

# Same filter on the HP — single pass (when HP is online)
python sparams_pdf.py --vna hp --start 100 --stop 200 \
    --label "2 m bandpass filter" --output 2m_bpf_hp.pdf

# Two sessions: capture pass A today, pass B tomorrow
python sparams_pdf.py --start 1 --stop 30 --save-A passA.npz \
    --label "Tank circuit" --output ignored.pdf
# ... swap DUT, come back tomorrow ...
python sparams_pdf.py --start 1 --stop 30 --load-A passA.npz \
    --label "Tank circuit" --output tank.pdf
```

Optional flags:

- `--vna {nanovna,hp}` — driver selection (default nanovna)
- `--port /dev/ttyACM1` — NanoVNA serial path
- `--host 10.1.1.70` — HP KISS-488 host
- `--points N` — sweep points (NanoVNA max 401, HP max 801; default 401)
- `--average N` — software-average N sweeps (default 2)
- `--power DBM` — HP source power; ignored on NanoVNA
- `--save-A FILE.npz` / `--load-A FILE.npz` — NanoVNA path only.
  Capture pass A, save, run again later with `--load-A` after the swap.
- `--no-prompt` — skip the "press Enter" pauses (use only when the
  DUT is swapped via relays).
- `--touchstone FILE.s2p` — explicit Touchstone output path; defaults
  to the PDF's basename with `.s2p`.

## Output

**PDF:** 4 × 2 grid of panels — one row per S-parameter (S11, S21,
S12, S22), magnitude in dB on the left, unwrapped phase in degrees
on the right. Each row is colour-coded; X axis is shared. The title
records which method was used (DUT-reversal vs native HP).

**Touchstone .s2p:** standard format, magnitude-angle, Z₀ = 50 Ω. The
file header notes the DUT label, sweep parameters, and the IDN of
the VNA used. Column order is the Touchstone v1 convention:

```
# Hz S MA R 50
f  |S11| ∠S11  |S21| ∠S21  |S12| ∠S12  |S22| ∠S22
```

(Yes, that's S21 / S12 — not S12 / S21. It's the convention; tools
like scikit-rf, ADS, AWR, QUCS, etc. expect it that way.)

## NanoVNA vs HP — sparams-specific notes

- **HP is much faster.** Native 2-port capture on the HP takes one
  trip through the calibration cycle. The NanoVNA path requires you
  to physically flip the DUT and wait through two captures and an
  operator prompt. For one-off measurements either is fine; for
  parametric sweeps (e.g. transistor S-params at 20 bias points) the
  HP is the only practical choice.
- **HP dynamic range is higher.** ~100 dB on the HP vs ~50–70 dB on
  the NanoVNA. For deeply-isolating DUTs (high-loss attenuators,
  filters past −60 dB) the NanoVNA hits its noise floor and S21 / S12
  read as random complex noise. The HP keeps going.
- **HP calibration is "real".** The HP applies an error-correction
  matrix that includes directivity, source-match, and load-match.
  The NanoVNA's calibration does the same in principle but with
  noticeably worse directivity (~30 dB vs ~40 dB). Above a Γ of about
  0.95 the NanoVNA gets visibly less accurate.
- **NanoVNA path is non-reciprocal for active DUTs.** When you have
  an amplifier or any non-reciprocal device, the DUT-reversal method
  here gives you the true S12 (reverse isolation). If you instead
  *assumed* S12 = S21 and skipped the swap, an amplifier with 20 dB
  forward gain and 40 dB reverse isolation would look like it had
  20 dB reverse isolation. The swap matters.
- **NanoVNA-F frequency range extends past the HP's top end.** Up to
  1.5 GHz fundamental (HP stops at 1.3 GHz). Useful for filters and
  amplifiers in the L-band that the HP can't reach.

## Notes

- This project supersedes the legacy `../sparams/` directory (HP-only
  stub). When the HP is online, this script runs against it unchanged
  with the `--vna hp` flag.
- For symmetric passive DUTs (most filters, attenuators, baluns past
  the input), the two-pass method really is twice as slow as needed —
  the reverse measurement should match the forward measurement to
  within calibration error. Use that as a sanity check: |S11 − S22|
  should be near zero across the band for a symmetric DUT.
- The auto-generated Touchstone filename uses the PDF basename. Pass
  `--touchstone` to override; this is useful when you want the .s2p
  in a different directory or under a different name than the PDF.
