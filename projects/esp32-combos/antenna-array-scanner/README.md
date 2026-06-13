# ESP32+RTL-SDR Antenna Array Scanner

**Status:** 🔨 In Development

Wideband RF antenna array scanner combining ESP32-based instruments (scpi-relay, scpi-gps) with RTL-SDR for automated antenna pattern characterization.

## What It Does

Automates multi-antenna RF surveys by:
1. Switching between up to 4 antennas via scpi-relay (XL9535 relay board)
2. Capturing power spectrum with RTL-SDR across user-defined frequency range
3. GPS timestamping via scpi-gps for mobile surveys
4. Logging frequency/power/antenna/GPS to SQLite
5. Generating comparative antenna pattern plots (power vs frequency, normalized gain)

## Hardware Requirements

### Required
- **scpi-relay** — ESP32 with XL9535 I2C relay board (4 channels for antenna switching)
- **RTL-SDR** — USB DVB-T dongle (Rafael Micro R820T/R820T2 tuner)
- **Antennas** — 2-4 antennas to compare (dipole, vertical, loop, Yagi, etc.)

### Optional
- **scpi-gps** — ESP32 with u-blox GPS module (for mobile surveys, position logging)
- **scpi-rotator** — ESP32 with azimuth rotator control (future: automated 3D antenna patterns)

## Installation

### Python Dependencies

```bash
pip install rf-bench-drivers-rtlsdr rf-bench-drivers-gpsd matplotlib numpy requests
```

### RTL-SDR Driver Setup

#### Debian/Ubuntu
```bash
sudo apt install rtl-sdr librtlsdr-dev
```

#### Fedora
```bash
sudo dnf install rtl-sdr
```

### Blacklist DVB-T Driver
Prevent kernel from claiming RTL-SDR as a TV tuner:

```bash
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf
sudo rmmod dvb_usb_rtl28xxu  # unload if currently loaded
```

### PPM Calibration
RTL-SDR oscillators drift. Calibrate your dongle's frequency error:

```bash
# Tune to known VHF station (e.g. NOAA weather radio 162.550 MHz)
rtl_test -p

# Adjust until on-frequency:
rtl_test -p -P 56  # example: 56 ppm correction
```

Pass the calibrated value to `antenna_scan.py --ppm <value>`.

## Usage

### Basic VHF Antenna Comparison

Compare 4 antennas on 2m band (144-148 MHz):

```bash
./antenna_scan.py \
  --esp-relay 10.1.0.100 \
  --freq-start 144 \
  --freq-stop 148 \
  --step-khz 25 \
  --antennas 1 2 3 4
```

### Mobile Survey with GPS

Drive test with GPS position logging:

```bash
./antenna_scan.py \
  --esp-relay 10.1.0.100 \
  --esp-gps 10.1.0.101 \
  --freq-start 144 \
  --freq-stop 148 \
  --step-khz 50 \
  --antennas 1 2 \
  --db mobile_survey.db \
  --output-dir ./survey_plots/
```

### HF Antenna Survey

Compare HF antennas on 40m band (7.0-7.3 MHz):

```bash
./antenna_scan.py \
  --esp-relay 10.1.0.100 \
  --freq-start 7.0 \
  --freq-stop 7.3 \
  --step-khz 10 \
  --antennas 1 2 3 \
  --ppm 56
```

### Arguments

```
--esp-relay IP        scpi-relay ESP32 IP address (required)
--relay-port PORT     scpi-relay port (default: 80)
--esp-gps IP          scpi-gps ESP32 IP address (optional)
--gps-port PORT       scpi-gps port (default: 80)

--freq-start MHZ      Start frequency in MHz (required)
--freq-stop MHZ       Stop frequency in MHz (required)
--step-khz KHZ        Step size in kHz (default: 25)

--antennas CH [CH..] Antenna relay channels to scan, 1-4 (required)

--ppm VALUE           RTL-SDR frequency correction in ppm (default: 0)
--gain DB             RTL-SDR gain in dB (default: 30)

--db PATH             SQLite database path (default: antenna_scan.db)
--output-dir PATH     Output directory for plots (default: .)
```

## Use Cases

### Antenna Shootout
Compare 4 antennas (dipole, vertical, ground plane, J-pole) across 2m band to determine best performer for base station.

### Mobile VHF/UHF Survey
Drive test with GPS logging to map coverage of local repeaters with different mobile antennas.

### HF DX Antenna Comparison
Compare horizontal loop vs vertical vs dipole on 40m/20m to determine best antenna for DX propagation.

### Filter/Amplifier Insertion Loss
Use antenna 1 as reference, antenna 2 with filter/amplifier inline. Normalized plot shows insertion loss/gain across band.

### EMI/RFI Hunting
Compare directional antennas (Yagi, loop) at different orientations to locate interference source via null steering.

## Output

### SQLite Database
`antenna_scan.db` contains table `scans`:

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | TEXT | ISO 8601 UTC timestamp |
| `freq_hz` | INTEGER | Frequency in Hz |
| `power_dbfs` | REAL | Received power in dBFS |
| `antenna` | INTEGER | Antenna relay channel (1-4) |
| `gps_lat` | REAL | GPS latitude (if available) |
| `gps_lon` | REAL | GPS longitude (if available) |
| `gps_alt` | REAL | GPS altitude in meters (if available) |
| `gps_sat` | INTEGER | GPS satellite count (if available) |

### Plots

#### `antenna_patterns.png`
Power vs frequency for each antenna (dBFS). Shows absolute received power across band.

#### `antenna_patterns_normalized.png`
Relative gain in dB (normalized to best antenna at each frequency). Shows comparative performance — 0 dB = best antenna at that frequency.

## Integration with Other Projects

### `~/rf-bench/projects/rtlsdr/survey/`
Complements the general-purpose RTL-SDR survey tool by adding automated antenna switching and comparative analysis.

### `~/rf-bench/projects/rtlsdr/classify/`
Can be extended to run signal classifier on each antenna and compare detection rates/SNR.

### `~/rf-bench/projects/relay/`
Uses same scpi-relay hardware as SOLT calibration and filter bank projects.

## Future Enhancements

### Automated Azimuth Sweeps
Add `--esp-rotator IP` support to automate 360° azimuth scans. Generate 3D antenna patterns (gain vs frequency vs azimuth).

### Elevation Patterns
Combine scpi-rotator azimuth + elevation to generate full 3D spherical antenna patterns.

### Real-Time Plotting
Live matplotlib animation showing spectrum updates as scan progresses.

### Signal-Specific Analysis
Instead of broadband power, use demodulators to measure SNR/signal quality of specific stations (FM RDS, NOAA weather, etc.).

### Power Calibration
Use known-power beacon (e.g. WSPR, NIST WWV) to convert dBFS → dBm. Requires one-time calibration with signal generator.

### Correlation with Propagation
Cross-reference scan results with propagation reports (HamQSL, PSK Reporter) to determine if antenna differences are real or propagation-related.

## Troubleshooting

### RTL-SDR not found
```
ERROR: rf_bench.rtlsdr not found
```
Install driver: `pip install rf-bench-drivers-rtlsdr`

### USB permission denied
```
usb_open error -3
```
Add udev rule:
```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/20-rtlsdr.rules
sudo udevadm control --reload-rules
```
Unplug/replug RTL-SDR.

### Antenna relay not switching
Check scpi-relay reachability:
```bash
curl "http://10.1.0.100/scpi?cmd=*IDN%3F"
```
Should return `ESP32-SCPI-RELAY,XL9535,1.0`.

### GPS data unavailable
Check scpi-gps status:
```bash
curl "http://10.1.0.101/scpi?cmd=GPS%3ASAT%3F"
```
If `0`, GPS has no fix. Move to clear sky view, wait 1-2 minutes for cold start.

### Frequency error / signals off-center
RTL-SDR oscillator drift. Calibrate with `rtl_test -p`, then pass `--ppm <value>`.

## References

- **scpi-relay** — `~/Dropbox/build/rf-bench/projects/esp32-only/scpi-relay/`
- **scpi-gps** — `~/Dropbox/build/rf-bench/projects/esp32-only/scpi-gps/`
- **RTL-SDR driver** — `~/Dropbox/build/rf-bench/drivers/rtlsdr/`
- **RTL-SDR projects** — `~/Dropbox/build/rf-bench/projects/rtlsdr/`

## License

MIT
