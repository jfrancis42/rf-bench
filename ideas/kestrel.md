# Kestrel 5500L Application Ideas

The Kestrel 5500L provides real-time atmospheric data every ~4 seconds:
- **Primary sensors:** temperature, relative humidity, wind speed, barometric pressure
- **On-device derived:** altitude, dew point, wet bulb, heat index
- **Driver-computed:** air density, density altitude, RF refractivity, vapor pressure,
  virtual temperature, speed of sound, cloud base AGL, wind chill, QNH, true altitude

Driver: `rf_bench.kestrel`

---

## Standalone Projects

### RF Refractivity Monitor / Ducting Alert

`projects/kestrel/refractivity-monitor/` — 💭 not started.

Continuously logs RF refractivity (N-units) and alerts when conditions favor
tropospheric ducting (N > 350 or strong negative gradient dN/dh). Ducting
enables VHF/UHF DX — knowing when it's happening in real time is actionable.

**Output:**
- SQLite time-series: N, T, RH, P, dew point, every 4 seconds
- Matplotlib trend plot (24h rolling) with ducting-threshold line
- SMS/email alert via `~/voipms/` when N exceeds configurable threshold
- Optional: compute N-gradient if two Kestrel units at different heights

**Why the Kestrel specifically:** It measures all three variables that enter the
refractivity equation (P, T, e) in a single portable package. No bench power,
no wiring, battery lasts weeks.

---

### Long-Term Weather Logger

`projects/kestrel/weather-logger/` — 💭 not started.

Unattended data collection to SQLite. Designed to run for days/weeks on a
Raspberry Pi with BLE adapter, logging every 4 seconds. Web UI (Flask or
FastAPI) serves last-24h/7d/30d plots. systemd service with auto-reconnect
(toggle BLE on the Kestrel via `scpi-relay` if available, or just retry).

**Schema:** timestamp, temperature_c, relative_humidity, wind_speed_ms,
station_pressure_mbar, altitude_m, dew_point_c, wet_bulb_c, heat_index_c,
density_altitude_m, rf_refractivity, air_density, vapor_pressure_mbar

**Output:**
- SQLite DB (append-only, ~50 MB/year at 4s interval)
- HTTP endpoint: `/api/latest`, `/api/history?hours=24`
- PNG plots: T, RH, wind, pressure, refractivity (multi-panel)

---

### Density Altitude Display

`projects/kestrel/density-altitude/` — 💭 not started.

Real-time density altitude for aviation use. Large terminal display (or virtual
instrument panel via `rf_bench.virtual`) showing DA in feet, pressure altitude,
temperature, and the deviation from standard atmosphere. Color-coded: green
(DA < PA), yellow (DA 500–2000 ft above PA), red (DA > 2000 ft above PA).

**Aviation context:** At the user's elevation (~6570 ft), density altitude
commonly exceeds 8000–9000 ft on hot summer days. Directly affects takeoff
distance and rate of climb.

**Bonus:** Compute and display Koch chart equivalent — percent increase in
takeoff distance and percent decrease in rate of climb vs standard day.

---

### Wet Bulb Globe Temperature (WBGT) Estimator

`projects/kestrel/wbgt/` — 💭 not started.

Estimate WBGT from temperature, humidity, and wind speed (Liljegren model or
the simpler Bernard approximation). The Kestrel 5400 series computes this
on-device; the 5500L does not (no globe thermometer). But the outdoor WBGT can
be estimated from temperature + humidity + wind + solar radiation (assumed clear
sky from time-of-day and lat/lon, or measured via a separate sensor).

**Output:** WBGT estimate with OSHA/military activity-level recommendations
(unrestricted / caution / moderate risk / high risk / extreme).

**Limitation:** Without globe temperature, accuracy is ±2°C in direct sun.
Acceptable for planning; not for regulatory compliance.

---

### Speed of Sound Calibrator

`projects/kestrel/speed-of-sound/` — 💭 not started.

Use the temperature-and-humidity-corrected speed of sound to calibrate acoustic
distance measurements (e.g., `scpi-distance` HC-SR04 ultrasonic sensor, or
time-of-flight audio ranging). At 6500 ft altitude, 35°C, 10% RH, the speed
of sound differs by ~5% from the standard 343 m/s — enough to cause 15 cm
error at 3 m range.

**Integration:** Publish corrected speed_of_sound_ms to MQTT or expose via
HTTP; ESP32 `scpi-distance` queries it before computing range.

---

## Combined with RTL-SDR

### Tropospheric Ducting Detector

`projects/kestrel/tropo-ducting/` — 💭 not started.

Correlates Kestrel refractivity with actual VHF/UHF signal strength from
RTL-SDR. Monitors a distant FM broadcast station or VHF beacon; logs both
signal strength (dBFS) and atmospheric refractivity simultaneously.
Generates scatter plot: signal strength vs N-units.

**Hardware:** Kestrel 5500L + RTL-SDR + VHF antenna

**Method:**
1. Kestrel streams N every 4s
2. RTL-SDR measures beacon power at known frequency (e.g., distant FM station
   at 100+ km, or NOAA weather radio)
3. Log both to SQLite with common timestamp
4. Plot and compute correlation coefficient

**Value:** Empirically calibrates the refractivity → ducting relationship for
your specific location and path. The textbook says N > 350 = ducting; your
local terrain may shift that threshold.

**Supersedes:** The `projects/rf/tropo-ducting/` future idea that called for
scpi-temp + barometer + hygrometer as separate sensors. Kestrel does all three
in one device.

---

### Weather-Correlated FM DX Logger

`projects/kestrel/fm-dx-weather/` — 💭 not started.

Extends `projects/rtlsdr/fm-rds/` with synchronized weather data. The FM+RDS
monitor already detects distant stations (via PI code / call sign). Adding
Kestrel data timestamps each DX event with refractivity, temperature inversion
strength (T + dew point spread), and humidity. Over weeks of logging, builds a
predictive model: "when N > X and T-Td spread < Y, expect FM DX from Z
direction."

**Hardware:** Kestrel 5500L + RTL-SDR + FM antenna

**Output:** SQLite with DX events + weather columns. Matplotlib: detection
count vs N-units histogram, detection probability vs hour-of-day × season.

---

## Combined with Radios / Beacon Monitoring

### Propagation-Weather Correlation Logger

`projects/kestrel/propagation-weather/` — 💭 not started.

Combines Kestrel weather data with IC-9700 (or KiwiSDR) beacon S-meter readings
to build a local propagation model. Monitors VHF/UHF beacons 24/7 and logs
signal strength alongside atmospheric conditions.

**Hardware:** Kestrel 5500L + IC-9700 (via Hamlib) or KiwiSDR (via WebSocket)

**Beacons:** NCDXF 50 MHz, local 2m/70cm beacons, NOAA weather radio

**Analysis:**
- Signal strength vs refractivity (ducting detection)
- Signal strength vs temperature (thermal inversion)
- Signal strength vs humidity (water vapor absorption at UHF)
- Signal strength vs wind speed (antenna sway at remote beacon?)
- Seasonal and diurnal patterns

**Integration:** Extends `projects/radio/beacon-logger/` with weather columns.

---

## Combined with VNA / Field Measurements

### Temperature-Corrected Cable Measurements

`projects/kestrel/cable-temp-correction/` — 💭 not started.

Cable velocity factor and loss vary with temperature (~50 ppm/°C for VF,
~0.2%/°C for loss in typical coax). When doing field antenna sweeps with the
NanoVNA, log ambient temperature from the Kestrel and apply correction factors
to VF and loss measurements for comparison against manufacturer specs (which
are at 20°C/68°F).

**Hardware:** Kestrel 5500L + NanoVNA-F

**Implementation:**
- Capture temperature at time of VNA sweep
- Apply correction: VF_corrected = VF_measured × (1 + α×(T - 20°C))
- Apply loss correction: loss_corrected = loss_measured × (1 + β×(T - 20°C))
- α ≈ 50 ppm/°C (PE dielectric), β ≈ 0.2%/°C (copper conductor)
- Annotate PDF output with ambient temperature and correction applied

**Why it matters:** At -10°C (winter field day), VF shifts enough to make a
cable look 0.3% longer — enough to confuse electrical-length measurements for
phasing harnesses.

---

### Wind-Load Antenna Pattern Correction

`projects/kestrel/wind-antenna/` — 💭 not started.

When measuring antenna patterns outdoors (via `projects/vna/antenna-pattern/`
+ scpi-rotator), wind deforms wire antennas and causes Yagis to flex. Log wind
speed and direction during the pattern measurement; flag data points taken
during gusts > threshold; optionally discard or mark them in the output.

**Hardware:** Kestrel 5500L + NanoVNA + scpi-rotator + antenna under test

**Value:** Without wind data, an outdoor antenna pattern has unknown error bars.
With it, you can either wait for calm or quantify the uncertainty.

---

## Combined with GPS

### Altitude Profile Logger (Mountain/Balloon)

`projects/kestrel/altitude-profile/` — 💭 not started.

Drive up a mountain (or fly a balloon) logging Kestrel pressure altitude vs
GPS altitude. The difference reveals local pressure bias and non-standard lapse
rate. Generates a local atmosphere profile: temperature, pressure, humidity,
density altitude, refractivity as a function of true altitude.

**Hardware:** Kestrel 5500L + `rf_bench.gpsd` (USB GPS)

**Output:**
- CSV: gps_alt_m, pressure_alt_m, temperature_c, rh, pressure_mbar, N
- Matplotlib: multi-panel altitude profile
- Computed: local lapse rate (°C/km), refractivity gradient (N-units/km)

**RF application:** A measured refractivity gradient (dN/dh) is far more
useful for VHF propagation prediction than a single surface measurement.
Standard atmosphere assumes -40 N-units/km; real values vary from -20 (super-
refraction) to -157 (trapping duct).

---

### QNH Cross-Check / Altimeter Calibration

`projects/kestrel/qnh-crosscheck/` — 💭 not started.

Given GPS altitude (true altitude) and Kestrel station pressure, compute QNH.
Compare against local METAR/ATIS altimeter setting (fetched via NOAA API or
AVWX). Difference reveals local pressure anomalies or Kestrel calibration drift.

**Hardware:** Kestrel 5500L + GPS + internet (METAR fetch)

**Output:** Real-time display: Kestrel QNH vs METAR QNH, difference in mbar
and feet of altitude error. Alert if difference > 1 mbar (30 ft).

---

## Combined with ShuttleXpress

### Portable Weather Station Display

`projects/kestrel/shuttle-display/` — 💭 not started.

ShuttleXpress jog wheel scrolls through Kestrel readings on a terminal or
virtual instrument panel. Shuttle ring adjusts display update rate. Buttons
select display pages: page 1 = primary (T/RH/wind), page 2 = pressure/alt,
page 3 = derived (DA, refractivity, air density), page 4 = history sparklines.

**Hardware:** Kestrel 5500L + ShuttleXpress

**Why:** Hands-free field weather station where the operator is doing something
else (antenna work, radio operating) and wants quick glances at weather without
touching a laptop keyboard.

---

## Combined with Soundcard DSP

### Weather-Modulated Ambient Audio

`projects/kestrel/weather-audio/` — 💭 not started.

Feeds Kestrel data into the vocoder-nature or ambient-forest soundcard projects
as real-time modulation sources. Temperature controls formant frequency, humidity
controls reverb wet/dry, wind speed drives white noise amplitude and a band-pass
filter sweep (simulating actual wind sound), pressure changes trigger low rumbles.

**Hardware:** Kestrel 5500L + soundcard output

**Artistic/practical use:** Generative ambient soundscape that reflects actual
outdoor conditions. Place Kestrel outside, run indoors — the audio environment
mirrors the weather without looking at a screen.

---

## Combined with ESP32

### Wireless Weather Relay (MQTT Bridge)

`projects/kestrel/mqtt-bridge/` — 💭 not started.

Python daemon subscribes to Kestrel BLE notifications, publishes all fields to
MQTT topics. Any ESP32 project, virtual instrument panel, or home automation
system can then subscribe without needing BLE capability.

**Topics:**
```
bench/kestrel/temperature_c
bench/kestrel/relative_humidity
bench/kestrel/wind_speed_ms
bench/kestrel/station_pressure_mbar
bench/kestrel/rf_refractivity
bench/kestrel/density_altitude_ft
...
```

**Integration:** Virtual instrument panels (gauge cluster showing weather),
ESP32 scpi-heater (outdoor temperature as feedforward), alert systems.

---

### Environmental Chamber Cross-Reference

`projects/kestrel/chamber-crossref/` — 💭 not started.

Place the Kestrel inside or adjacent to a DIY thermal chamber controlled by
`scpi-heater`. Use the Kestrel as an independent temperature/humidity reference
to validate the DS18B20 sensors the ESP32 uses for PID control. Quantifies
DS18B20 bias and response time lag vs the calibrated Kestrel sensor (±0.5°C
manufacturer spec).

**Hardware:** Kestrel 5500L + ESP32 scpi-heater + DS18B20 array

**Output:** DS18B20 error vs Kestrel reference, plotted against temperature.
Generates per-sensor correction coefficients.

---

## Combined with SSA / Spectrum Analyzer

### Atmospheric Absorption Measurement

`projects/kestrel/atmospheric-absorption/` — 💭 not started.

At UHF and above, water vapor absorbs RF energy. The Kestrel provides the vapor
pressure needed to compute the ITU-R P.676 specific attenuation (dB/km) for any
frequency. Compare the computed absorption against actual path loss measured by
the SSA tracking generator over a known outdoor path.

**Hardware:** Kestrel 5500L + SSA3032X (TG on) + two antennas at known separation

**Frequencies of interest:**
- 22.235 GHz (water vapor resonance) — not reachable with this SSA
- 1–3.2 GHz (SSA range): absorption is tiny (<0.01 dB/km) but measurable
  over long paths in high humidity

**Realistic application:** Compute and log the expected atmospheric contribution
to path loss for any `projects/radio/coverage/` drive test. Even at 2m/70cm,
0.005 dB/km × 100 km = 0.5 dB — not negligible for EME or troposcatter budgets.

---

## Data Analysis / Science

### Microclimate Mapper

`projects/kestrel/microclimate/` — 💭 not started.

Walk around a site (antenna farm, building, hilltop) carrying the Kestrel + GPS.
Log position + weather every 4 seconds. Map spatial variation in temperature,
wind, and humidity. Identifies thermal updrafts, wind shadows, cold air pools.

**Hardware:** Kestrel 5500L + GPS

**Output:** GeoJSON + Leaflet map showing spatial weather variation. Overlay on
`maps.n0gq.org` tile server.

**RF application:** Thermal gradients near the ground cause near-surface
refraction that affects VHF propagation from low-mounted antennas. A 5°C
temperature difference across 100 m causes measurable beam bending at 144 MHz.

---

### Evaporation Duct Height Estimator

`projects/kestrel/evap-duct/` — 💭 not started.

Near bodies of water, evaporation ducts form in the first 0–40 m above the
surface. The duct height can be estimated from surface temperature, humidity,
wind speed, and sea surface temperature (SST). The Kestrel provides all
atmospheric inputs; SST comes from a water temperature probe or NOAA buoy data.

**Relevance:** Evaporation ducts enable beyond-line-of-sight propagation at
microwave frequencies (3–30 GHz). Even at UHF (300–3000 MHz), ducts enhance
signals by 10–20 dB over water paths. Predicting duct height helps schedule
VHF/UHF DX attempts across lakes or coastal paths.

**Model:** Paulus-Jeske (1985) or the newer AREPS/DMAN (US Navy) simplified
equations. Inputs: air temperature, RH, wind speed, SST, height above water.
Output: estimated duct height (m) and modified refractivity profile M(z).
