> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-rf-switch

GitHub: https://github.com/jfrancis42/rf-bench-rf-switch

RF switch characterizer using Bus Pirate SPI programming + SSA tracking generator.
Programs a digital RF switch (PE43602, HMC307, or RFSA3013) via SPI, measures
insertion loss at each state using the SSA, and produces a pass/fail report against
user limits.

## Hardware

| Instrument | Role |
|-----------|------|
| Siglent SSA3032X Plus (10.1.1.60) | Spectrum analyzer with tracking generator |
| Bus Pirate v3/v4/v5 (/dev/ttyUSB1) | SPI master for switch programming |
| RF switch DUT | PE43602, HMC307, or RFSA3013 |

Connect Bus Pirate SPI (MOSI, CLK, CS/LE) to the switch's SPI pins.
Connect SSA tracking generator output through the switch to the SSA RF input.

## Usage

python rf_switch.py --chip CHIP [options]

Options:
  --ssa HOST (10.1.1.60): SSA IP
  --bp-port PORT (/dev/ttyUSB1): Bus Pirate serial port
  --chip PE43602|HMC307|RFSA3013 (PE43602): Chip type
  --states N (4): Number of states to test
  --freqs LIST (1,10,100,500,1000): Test frequencies in MHz
  --max-loss DBM (3.0): Max insertion loss for PASS
  --min-isolation DBM (40.0): Min isolation for PASS
  --plot FILE (timestamped): Output PNG

## Supported chips

PE43602: 7-bit SPI step attenuator (used as binary switch at codes 0x00 and 0x7F)
HMC307: SP4T RF switch, one-hot state encoding
RFSA3013: 7-bit SPI step attenuator, 0.25 dB/step

## Notes

The reference level for insertion loss is measured with the switch in state 0
(through path). All subsequent states are measured relative to this reference.
