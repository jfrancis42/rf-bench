# Better Carrier Suppression — Mixer Upgrade Options for the HF Phasing Exciter

Where to go if the AD831's carrier suppression (measured ~21 dB on this bench)
isn't good enough. Companion to `carrier-fix.md` (the carrier defect) and
`iq-balance-trim.md` (the image defect, already solved in software to >65 dB).

> **Confidence note:** part numbers, isolation figures, and availability below
> are from training-data knowledge, not live listings or datasheets pulled
> today. Every spec that matters to a purchase (especially IF-port DC coupling)
> is flagged "verify before buying." Treat the numbers as design-guidance
> ballparks, not extracted datasheet values.

---

## 0. FIRST: is the mixer even the problem? (Do this before spending a cent.)

The DC-injection test already proved the carrier is **LO leakage, not mixer DC
offset** (injecting DC at the RF inputs, separately and together, moved the
7200 kHz spike *zero*). But "leakage" has two possible homes, and only one of
them is fixed by a better mixer:

1. **Inside the AD831** — its 30 dB LO-to-IF isolation spec. *A better mixer
   fixes this.*
2. **On the board / from the Si5351** — LO trace coupling into the
   output/combiner node, or the Si5351's square-wave clock radiating directly
   to the output. *A better mixer does nothing for this.*

We measured **~21 dB**, which is **worse** than the AD831's own 30 dB spec (and
the chip is usually better than spec at 7 MHz than at its 100 MHz test point).
Getting worse than the chip's isolation is a strong tell that **board/clock
coupling already dominates**. If so, a new mixer is wasted money.

**The test:** kill the mixer's supply, leave the Si5351 running. Look at
7200 kHz at the antenna/output.

- **Carrier still there** → it's board/clock coupling. Buy nothing. Fix layout
  and shielding: shorten and separate the LO traces, keep them away from the
  resistive combiner and output node, shield the combiner, add series
  resistance / a low-pass on the Si5351 clock feed. (A square-wave clock is a
  ferocious radiator of its own fundamental.)
- **Carrier gone** → the mixer really is passing the leakage, and the upgrade
  options below are worth it.

---

## 1. The HF reality: you cannot just buy a "better AD831"

Every **integrated I/Q modulator chip** — AD8345, AD8349, ADL5375, LTC5588,
TRF370317 — has a **lower frequency limit of ~250 MHz to ~1 GHz**. None of them
reach 7 MHz. Direct quadrature-modulator ICs are fundamentally a VHF-and-up
product category; there is no drop-in HF replacement chip for the AD831.
*(Confidence: high — consistent across that entire product class.)*

So at HF the realistic upgrade paths are only two:

- **A. Passive double-balanced diode mixer (DBM)** — easy modules, ~40–45 dB.
- **B. Tayloe / QSE switching mixer** — the modern SDR answer, >50 dB.

---

## 2. Option A — Passive double-balanced diode mixer (the easy-module answer)

Mini-Circuits **ADE-1**, **SBL-1**, **SRA-1** (Level-7 class, ~+7 dBm LO).
Widely sold on eBay/Amazon as solder cans and as breakout modules.

**Why it helps:**
- **LO-to-IF isolation ~40–50 dB at HF** vs. the AD831's 30 dB — a genuine
  10–20 dB improvement in the exact term that's hurting you.
- **IF port is DC-coupled** on the ADE-1/SBL-1 (DC–500 MHz), so it passes your
  baseband audio — mandatory for a direct upconverter. **⚠ Verify the exact
  part's IF spec before buying:** a transformer-coupled IF port that only starts
  at, say, 5 MHz will block your audio and be useless here.

**Catches:**
- **Passive:** ~7 dB conversion loss, no gain. You'll need more audio drive or a
  post-amp.
- **Needs +7 dBm LO drive** (a diode-ring mixer wants a healthy LO). The Si5351
  can do this into a matched load, possibly with a small buffer.
- **You need the whole phasing pair:** two matched mixers + a **quadrature LO**
  + a combiner. Good news — your **Si5351 generates the 90° LO for free** via its
  per-output phase-offset register (set two outputs to the same divider, one
  offset 90°). Phase accuracy depends on the divider value; it's fine at 7 MHz.
- You'll **still** add a DC carrier-null trim (like `carrier-fix.md`) — but now
  it actually works, because the mixer's own leakage no longer swamps the trim.

**Realistic outcome:** ~**40–45 dB** carrier suppression — carrier inaudible,
meets typical commercial-rig spec.

---

## 3. Option B — The Tayloe detector / QSE (the right answer for HF SDR)

This is what SoftRock, the HPSDR/Hermes boards, the QRP Labs QDX/QSX, and
essentially every modern direct-conversion HF SDR transmitter actually use. It
is not one Amazon module — it's a small, well-understood board — but it is the
architecturally correct choice, and it's cheap.

### 3.1 What it is

The **Tayloe detector** (Dan Tayloe, N7VE, ~2001) is a **sampling / commutating
mixer**: instead of *multiplying* by a sine LO (what the AD831 diode/Gilbert
core does), it **switches the signal path** among several capacitors in
sequence, timed by the LO. Used forwards it's a superb quadrature *downconverter*
(RX); run backwards — driving the switch from your I/Q baseband — it's a
**Quadrature Sampling Exciter (QSE)** for TX.

The core is almost absurdly simple: a **4:1 analog multiplexer/switch**
(a 74HC4052 or, better, an FST3253 bus switch) plus four capacitors and an
op-amp. No diode ring, no transformer, no Gilbert cell.

### 3.2 How it works

**The clock.** Feed the switch a clock at **4× the LO frequency**. A divide-by-4
counter (or the switch's own 2-bit sequencer) produces four non-overlapping
phases at 0°, 90°, 180°, 270° — each switch closed for exactly one quarter of
the LO period. So for a 7200 kHz LO you clock at **28.8 MHz** and the four
sample gates open in sequence at 7200 kHz.

**RX view (to build intuition).** In a downconverter, each of the four caps
samples the RF at a different 90° point of every LO cycle and integrates. The
0°/180° caps differenced give **I**; the 90°/270° caps differenced give **Q**.
Because each cap is connected for a full quarter-cycle (not a brief impulse),
the switch acts as an **integrate-and-dump** — this is why the Tayloe detector
has famously low conversion loss (~**0.9 dB** ideal, vs. ~7 dB for a diode ring)
and superb noise figure.

**TX view (what you'd build — the QSE).** Run it in reverse: drive the four
switch inputs from your baseband **I, −I, Q, −Q** (the differential pairs), and
the commutating switch **up-converts** them onto the LO, summing to a
single-sideband RF output at the switch common. The sideband you get (USB vs.
LSB) is set by the **phase sequence** of I and Q — which you already control
in software.

### 3.3 Why it gives dramatically better carrier suppression

This is the key point for your problem:

- **The carrier term is a DC offset problem, and the QSE makes DC offset small
  and, crucially, *trimmable to a real null*.** In the AD831 your carrier was
  dominated by LO-to-IF *leakage* you couldn't trim away. In a switching mixer
  there is **no LO multiplication path to leak** in the same way — the LO only
  operates switches; it isn't a signal that couples through a nonlinear core to
  the output. The residual carrier is set by (a) switch charge injection and (b)
  the DC balance of your I/−I, Q/−Q drive, **both of which a DC-offset trim
  actually nulls.**
- **Balanced, differential drive** (I vs −I, Q vs −Q) means the static offsets
  subtract. SoftRock-class QSEs routinely hit **>50 dB carrier suppression** and
  >45 dB opposite-sideband with a simple offset trim.
- **Inherent, accurate quadrature** from the ÷4 digital clock — the 90° comes
  from counting, not from analog phase-shift networks, so it's exact and
  frequency-independent. (Your image suppression gets easier too.)
- **Works to DC** — no low-frequency limit, unlike every integrated modulator.

**Realistic outcome:** **>50 dB carrier**, >45 dB image, ~1 dB conversion loss.
This is a genuine generational jump over both the AD831 and a diode ring.

### 3.4 The tradeoff, honestly

- **It's a board, not a plug-in module.** You build (or buy a kit for) a small
  switch + op-amp + clock-divider circuit. More work than soldering a Mini-
  Circuits can, but it's a well-trodden, forgiving design with decades of
  reference material.
- **Needs a 4× clock** (28.8 MHz for 7200 kHz) *or* an on-board ÷4. The Si5351
  can output 28.8 MHz directly, so you drive the ÷4 divider (a 74AC74 dual
  flip-flop) from one Si5351 clock — or clock the FST3253's sequencer at 4× and
  let it divide. Either way the Si5351 is already the right LO source.
- **Output is low-level** — you feed a low-pass filter and a PA chain, same as
  now.
- Ultimate carrier floor is still set by switch charge injection + op-amp offset
  (~50–60 dB range); beating that needs active carrier cancellation. But 50+ dB
  is already far past "inaudible."

### 3.5 Specific parts

**The switch (the heart of it):**
- **FST3253 / 74CBT3253** (dual 4:1 mux/demux, e.g. Fairchild/TI). **The** part
  used by SoftRock and most QSE/QSD designs. Very low on-resistance (~4 Ω), fast,
  cheap, and its 2-bit select behaves as the phase sequencer. **First choice.**
  Available on eBay/AliExpress as bare ICs and on SoftRock-style breakout boards.
- **74HC4052** — the classic textbook Tayloe switch (dual 4:1). Higher Ron than
  the FST3253 (more loss), but the most-documented "understand it first" part.
  Fine for HF at these levels.

**The clock divider (to make the 4 phases from a 4× clock):**
- **74AC74** or **74HC74** dual D flip-flop, wired as a Johnson/÷4 counter to
  generate the 0/90/180/270 gate timing. Use the **AC** family for clean fast
  edges at 28.8 MHz.

**The LO:** **you already own it** — the **Si5351A** clock generator (`Si5351.pdf`
is already in this directory). Output 28.8 MHz (= 4 × 7200 kHz) to the divider,
or use two phase-offset outputs if you drive the switch phases directly.

**The baseband op-amp (differencing/summing + drive):**
- A decent dual/quad audio op-amp: **NE5532** (cheap, low-noise, classic
  SoftRock choice), or **OPA1642 / OPA2134 / LM4562** for lower distortion.

**The easy path — buy the kit instead of breadboarding:**
- **SoftRock RXTX / SoftRock Ensemble** kits (Tony Parks / Five Dash, when in
  stock) — a complete QSD+QSE at HF, well-documented, the canonical learning
  platform. **⚠ Verify current availability — these go in and out of stock.**
- **QRP Labs** boards (QDX/QSX and the older polyphase/QSE experiments) —
  actively sold, excellent docs, cheap. Not a raw QSE breakout but the closest
  actively-produced ecosystem.
- Generic **"FST3253 quadrature sampling mixer" / "Tayloe mixer" breakout
  boards** appear on eBay/AliExpress. **⚠ Confirm the board is wired for TX
  (QSE) or is symmetric** — many are RX-only QSD boards. A QSD board can often
  be run in reverse, but check before buying.

### 3.6 How it plugs into *this* project

The beautiful part: **your software doesn't change.** `play-usb-iq.py` already
emits complex I/Q as soundcard L/R, and `iq_balance_trim.py` already nulls the
image via `Q' = g*Q + p*I`. A QSE takes the same I/Q differential baseband. You'd
swap the AD831 board for the QSE board, point the Si5351 at 4× (or add the ÷4),
re-run `iq_balance_trim.py` to re-null the image for the new hardware, and add a
small DC-offset trim on the I/−I, Q/−Q drive for the carrier. The whole
DSP/tooling investment carries straight over.

---

## 4. Recommendation

1. **Run the mixer-off / Si5351-on test (§0) first.** If the carrier is board/
   clock coupling, the fix is layout and shielding — buy nothing.
2. **If you want the low-effort win** and the carrier really is the AD831's
   internal leakage: a **Mini-Circuits ADE-1/SBL-1 diode DBM pair** with the
   Si5351 supplying the 90° LO gets you to ~40–45 dB. Verify IF-port DC coupling
   before ordering.
3. **If you want the right architecture and best result:** build or buy a
   **FST3253-based Tayloe QSE** (SoftRock/QRP Labs ecosystem). >50 dB carrier,
   >45 dB image, ~1 dB loss, exact digital quadrature, works to DC, and your
   existing software drives it unchanged.
4. **Any direct-conversion exciter is ultimately floor-limited** (~40–50 dB for
   the diode ring, ~50–60 dB for the QSE) by DC offset and residual coupling.
   Beyond that means a superhet or active carrier-nulling — a much larger
   project than swapping a mixer.

## Reference

- `carrier-fix.md` — the carrier (LO-frequency) spur and the DC-null trim.
- `iq-balance-trim.md` — the image spur, solved in software (>65 dB).
- `Si5351.pdf` (this dir) — the LO/clock source for every option above.
- `AD831APZ.PDF` (this dir) — the current mixer; 30 dB LO-IF isolation is the
  ceiling we're trying to beat.
- Dan Tayloe N7VE, "Product detector and method therefor" (US Patent 6,230,000)
  and the QEX / SoftRock literature for the canonical Tayloe/QSE derivation.
