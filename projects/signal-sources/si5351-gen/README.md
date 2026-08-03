# rf-bench-si5351-gen

Two UIs available — the original curses TUI (`si5351_gen.py`) and a new
Tkinter graphical panel (`si5351_panel.py`).

## Tkinter panel

```bash
python si5351_panel.py                   # auto-detect Bus Pirate
python si5351_panel.py --bp /dev/ttyACM1 # explicit port
python si5351_panel.py --xtal 26e6       # 26 MHz crystal
python si5351_panel.py --ssa 10.1.1.60   # enable SSA measure button
python si5351_panel.py --demo            # no hardware needed
```

Features: three-channel frequency/drive/enable display, Set Frequency dialog,
preset save/load (`~/.si5351_presets.json`), SSA measurement button, PLL-B
contention warning when CLK1 and CLK2 are both active.

---
# rf-bench-si5351-gen

Cheap multi-channel frequency generator using the Si5351A I2C clock chip.
Three independent outputs from ~3 kHz to ~200 MHz via a $5 breakout board.

Interactive curses TUI or CLI mode. Controlled through a Bus Pirate I2C master.

## Hardware required

| Item | Notes |
|------|-------|
| Bus Pirate v3, v4, or v5 | I2C master; v5: use `/dev/ttyACM1` (see below) |
| Si5351A breakout | Adafruit #2045 or generic clone — 25 MHz crystal, 3.3V |

The Si5351A has three clock outputs (CLK0–CLK2). Each can be set independently
from ~3 kHz to 200 MHz. Output level is software-selectable at 2/4/6/8 mA into 50 Ω.

**PLL-B is shared between CLK1 and CLK2.** If both are enabled with different
frequencies, only the last-set one is actually accurate — the TUI warns you.
CLK0 has its own dedicated PLL-A.

## Wiring

```
Bus Pirate +3.3V  →  Si5351 VIN
Bus Pirate GND    →  Si5351 GND
Bus Pirate SDA    →  Si5351 SDA
Bus Pirate SCL    →  Si5351 SCL
```

Si5351A default I2C address: **0x60** (ADDR pin low).
Tie ADDR pin high for address **0x61**.

CLK0, CLK1, CLK2 are 3.3V LVCMOS outputs. Add a DC-blocking cap for AC-coupled
loads; add a 50 Ω series resistor for matched impedance driving.

## Bus Pirate v5 — one-time setup

```
screen /dev/ttyACM0 115200
# at the prompt: binmode → 2. BPIO2 flatbuffer interface → save as default
```

BPIO2 persists across reboots. Then connect to `/dev/ttyACM1` (binary port).

## Usage

### Interactive TUI

```bash
# Bus Pirate at default port, 25 MHz crystal
python3 si5351_gen.py

# Specify port and crystal frequency (27 MHz crystal boards exist)
python3 si5351_gen.py --bp /dev/ttyACM1 --xtal 27e6

# Non-default I2C address
python3 si5351_gen.py --addr 0x61
```

### CLI mode

```bash
# Set CLK0 to 10 MHz, CLK1 to 14.2 MHz, exit (outputs stay on)
python3 si5351_gen.py --cli --clk0 10e6 --clk1 14.2MHz

# All three outputs; hold until Ctrl-C then disable
python3 si5351_gen.py --cli --clk0 10e6 --clk1 3.579545MHz --clk2 32768 --stay

# Turn everything off
python3 si5351_gen.py --off
```

Frequency formats accepted: `10e6`, `10MHz`, `10000kHz`, `10000000` (Hz).

### Quadrature (I/Q) mode

Two outputs locked 90° apart — the front end of a direct-conversion / Tayloe
receiver or a phasing-type transmitter. CLK0 = I, CLK1 = Q.

```bash
# 40m quadrature pair, upper sideband (Q lags I) — usb is the default
python3 si5351_gen.py --quad 7.074MHz --stay

# same, stated explicitly
python3 si5351_gen.py --quad 7.074MHz --sideband usb --stay

# 20m, lower sideband (Q leads I)
python3 si5351_gen.py --quad 14.010MHz --sideband lsb --stay

# 30m quadrature, hold until Ctrl-C
python3 si5351_gen.py --quad 10.136MHz --sideband usb --stay
```

From Python:

```python
from si5351_gen import Si5351
from rf_bench.buspirate import BusPirate

gen = Si5351(BusPirate('/dev/ttyUSB0'))
gen.set_quadrature(7_074_000)                    # 40m, CLK0=I, CLK1=Q, USB
gen.enable(0, True); gen.enable(1, True)

gen.set_quadrature(14_010_000, sideband='lsb')   # 20m, swap I/Q lead → LSB
```

#### What `--sideband` (usb / lsb) actually changes

The **only** difference between the two modes is **which output carries the 90°
phase-offset register value** — everything else (frequency, amplitude, divider)
is identical on both outputs. The Si5351 phase-offset register *delays* a
clock's edges, so the output holding the larger value **lags**:

| `--sideband` | CLK0 (I) offset | CLK1 (Q) offset | Phase relationship |
|--------------|-----------------|-----------------|--------------------|
| `usb` (default) | 0 | 90° | **Q lags I** by 90° |
| `lsb`           | 90° | 0 | **Q leads I** by 90° (I lags Q) |

So the flag simply flips the sign of the I↔Q quadrant relationship (±90°).

In a quadrature (Tayloe / phasing / image-reject) mixer, swapping which output
leads is exactly what selects the sideband — it moves the image to the other
side of the LO. **Which physical result (USB vs LSB) you actually get depends on
your downstream wiring** (phasing-network polarity, summing/differencing
convention, how I/Q feed the mixer). The labels here follow the common
convention but are not guaranteed for an arbitrary circuit: if the sidebands
come out backwards on your bench, just swap `usb`↔`lsb` (or physically swap the
I and Q leads) — a one-flag fix. What the code *does* guarantee is a clean 90°
between the two outputs; which direction maps to which sideband is a convention
you lock down once, with your hardware.

**Usable range ≈ 4.762 MHz .. 112.5 MHz** (40m through 6m). Frequency accuracy
is sub-0.02 ppm — a fractional PLL hits the target almost exactly while the
output divider stays a fixed even integer (required for the phase lock).

**Drive strength defaults to 2 mA** (the lowest) in quadrature mode, at both
the CLI (`--drive {2,4,6,8}`) and the API (`drive_ma=`). The Si5351 output is a
~3.3 V CMOS square; when driving an **AD831 mixer LO**, higher drive overdrives
the AD831's ±1 V LO input, so 2 mA (highest output Z, smallest swing) is the
safe starting point. Bump it up only if a specific load needs more level:

```bash
python3 si5351_gen.py --quad 7.2MHz --drive 8 --stay   # hotter output
```

**80m and 160m cannot be done with the Si5351 alone** (the output divider would
exceed the phase register's range). `--quad` reports an error for those bands.
The standard workaround is an external ÷4 Johnson counter (74AC74): generate 4×
the target on one output and divide down in hardware to recover quadrature.

## TUI key bindings

| Key | Action |
|-----|--------|
| ↑ / ↓ | Select channel |
| SPACE | Toggle output on/off |
| f | Enter frequency |
| d | Cycle drive strength (2→4→6→8→2 mA) |
| a | Enable all outputs |
| z | Disable all outputs |
| p | Save preset to `~/.si5351_presets.json` |
| l | Load preset |
| q / ESC | Quit (all outputs disabled on exit) |

## Output

The TUI shows for each channel:

- Requested frequency
- Actual synthesized frequency (may differ by a few ppm due to integer PLL constraints)
- Drive strength
- Enabled/disabled status
- PLL-B sharing warning (`*`) when CLK1 and CLK2 are both active

## Notes

- **Crystal frequency:** Most Si5351A breakouts use a 25 MHz crystal. Some boards
  (notably some generic Chinese ones) use 27 MHz. Measure with a frequency counter
  or check the marking on the crystal can if output is off.
- **Phase noise:** The Si5351 is not a precision instrument. Expect −100 to −110 dBc/Hz
  at 10 kHz offset. Fine for testing logic circuits, not for receiver noise-figure work.
- **CLK1 / CLK2 shared PLL:** Both channels share PLL-B. They can be independent
  only if you accept that setting one changes the other's actual VCO. The UI shows
  actual synthesized frequency for each. For truly independent outputs, use CLK0
  (PLL-A) for one frequency and either CLK1 or CLK2 (not both) for another.
- **Frequency range:** 3 kHz–200 MHz typical. The chip can theoretically go lower
  with maximum R divider but accuracy degrades. Outputs above 150 MHz show increased
  harmonic content.
- **Outputs after exit (CLI mode):** Unless `--stay` is used, the script exits
  immediately after setting frequencies. The Si5351 retains its state; outputs remain
  active until the chip is power-cycled or `--off` is run.
