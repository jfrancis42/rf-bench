# rf-bench-ook-link

One-way ASCII data link: Flipper Zero CC1101 transmits, RTL-SDR receives.

Uses 1200-baud OOK (On-Off Keying) with UART framing (8N1).  Each character
is sent as: start bit LOW, 8 data bits LSB-first, stop bit HIGH.  The CC1101
switches the carrier on/off to represent 1/0.

## Hardware

| Device | Role |
|--------|------|
| Flipper Zero | CC1101 transmitter at 433.92 MHz |
| RTL-SDR (any RTL2832U dongle) | Wideband receiver |
| Antenna | Any VHF/UHF antenna on both ends |

## Usage

**Terminal 1 — receive on RTL-SDR (start first):**
```bash
python ook_link.py rx
```

**Terminal 2 — transmit from Flipper:**
```bash
python ook_link.py tx "Hello World"
```

**Options:**
```bash
python ook_link.py tx "Hi" --repeat 5     # repeat 5 times
python ook_link.py rx --gain 30           # explicit gain
python ook_link.py rx --threshold 0.7     # raise threshold if noisy
python ook_link.py tx "Hello" --freq 315  # different frequency (MHz)
```

## How it works

**TX path:**
1. ASCII string → UART bytes (start + 8 data bits + stop per character)
2. Prepend 32-bit alternating preamble (AGC settle + clock sync)
3. Prepend 0xAA 0x55 sync word; append 0x04 (EOT)
4. Convert to OOK timing list (µs), write as Flipper `.sub` RAW file
5. Play via `subghz tx_from_file` (Momentum) or `subghz_transmit_raw` (official)

**RX path:**
1. RTL-SDR captures IQ at 240 kS/s centered on 433.92 MHz
2. `abs(IQ)` → AM envelope (OOK demodulation)
3. Adaptive threshold → binary signal
4. Falling edge detection → UART start bit candidates
5. Sample 8 data bits + stop bit, LSB first
6. Find 0xAA 0x55 sync word in byte stream
7. Extract payload up to 0x04 (EOT)

## Encoding detail

```
bit period = 833 µs  (1200 baud)
samples/bit = 200  (at 240 kS/s RTL-SDR rate)

carrier ON  = logic 1  (idle, stop bit)
carrier OFF = logic 0  (start bit, data 0)

Frame: [20-bit idle] [32-bit preamble] [4-bit idle]
       [0xAA][0x55][byte0][byte1]...[0x04]
```

## Tips

- Start the receiver **before** transmitting so the RTL-SDR's AGC has settled
- Use `--repeat 3` or more when signal conditions are uncertain
- Raise `--threshold` (e.g. 0.7) if the receiver prints garbage in a noisy environment
- Lower gain (`--gain 20`) if the signal is very strong (nearby, attenuator-free)
- Frequencies must be in the CC1101's supported ranges:
  300–348 MHz, 387–464 MHz, 779–928 MHz
- The RTL-SDR has a DC spike at the exact center frequency; tuning to 433.92 MHz
  is fine because the spike is at DC and the OOK envelope is wideband

## Limitations

- One-way only (Flipper TX → RTL-SDR RX)
- 1200 baud: ~100 chars/second, suitable for short messages
- No error correction; `--repeat` is the simplest reliability mechanism
- The Flipper must have an SD card for the .sub file
