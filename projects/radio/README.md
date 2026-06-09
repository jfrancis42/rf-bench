# Radio Projects

Receiver and transmitter measurement automation for the **Icom IC-7300**,
**Icom IC-9700**, and **Yaesu FT-891** via Hamlib rigctld.

## Project index

| Project | Instruments | What it measures |
|---------|-------------|-----------------|
| [`receiver-test/`](receiver-test/) | IC-7300 or FT-891 + SDG1062X + SDS2504X | HF MDS, noise figure, S-meter calibration, two-tone IMD/IP3, blocking, selectivity |
| [`transmitter-test/`](transmitter-test/) | IC-7300, FT-891, or IC-9700 + SSA3032X | TX power vs frequency, harmonic content, ALC compression, SSB carrier suppression |
| [`coverage/`](coverage/) | IC-7300, IC-9700, or FT-891 + optional GPS | S-meter vs position; drive-test / antenna pattern; CSV + GPX |
| [`doppler/`](doppler/) | IC-7300, IC-9700, or FT-891 + GPS | Real-time Doppler VFO correction for satellite operation |
| [`satellite/`](satellite/) | IC-9700 + optional GPS | Pass prediction + live Doppler tracking; IC-9700 cross-band duplex |
| [`phase-noise/`](phase-noise/) | IC-7300 or FT-891 + SSA3032X | Close-in phase noise: dBc/Hz vs offset from 10 Hz to 1 MHz |
| [`noise-figure/`](noise-figure/) | IC-7300 or FT-891 + SSA3032X + noise source | Y-factor noise figure; de-embeds SSA own NF |
| [`beacon-logger/`](beacon-logger/) | IC-9700 + optional GPS | VHF/UHF propagation / beacon signal-strength logger; SQLite + live HTTP |
| [`vhf-receiver-test/`](vhf-receiver-test/) | IC-9700 + SSA3032X | MDS + S-meter calibration on 2m / 70cm / 23cm using SSA tracking generator |
| [`fm-deviation/`](fm-deviation/) | IC-9700 + SSA3032X | FM transmitter deviation; Carson's rule from −26 dB bandwidth |
| [`rx-crosscheck/`](rx-crosscheck/) | IC-9700 + RTL-SDR + optional SSA | Cross-calibrates RTL-SDR dBFS readings against IC-9700 S-meter (dBm) |
| [`aprs-igate/`](aprs-igate/) | IC-9700 (USB audio) + direwolf | APRS receive igate; callsign enrichment; optional APRS-IS gating |
| [`dstar-monitor/`](dstar-monitor/) | IC-9700 | D-STAR digital voice activity monitor; logs callsigns and messages |

## Common setup

```bash
# IC-7300 (USB):
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 &

# IC-9700 (USB):
rigctld -m 3081 -r /dev/ttyUSB0 -s 115200 &

# FT-891 (USB):
rigctld -m 1036 -r /dev/ttyUSB0 -s 38400 &
```

All scripts default to `--rig-host localhost --rig-port 4532`.

## IC-9700 notes

- VHF/UHF S-meter reference: **S9 = −73 dBm** (ITU VHF standard — not the HF −93 dBm)
- USB audio device: `plughw:IC-9700,0` (set IC-9700 menu: USB AF Output = AF)
- D-STAR CAT support requires Hamlib ≥ 4.3 (`rigctld -m 3081`)
