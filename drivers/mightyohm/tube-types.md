# Geiger-Müller Tube Types for MightyOhm Geiger Counter

This document describes the various GM tubes compatible with the MightyOhm Geiger Counter board and their characteristics.

## Quick Reference Table

| Tube | Type | Conversion Factor | Sensitivity | Energy Range | Cost | Best For |
|------|------|-------------------|-------------|--------------|------|----------|
| **SBM-20** | β,γ | 57 | Standard | 0.05–3 MeV | $15–25 | General purpose (default) |
| **LND-712** | α,β,γ | 108 | High | 0.01–2 MeV | $75–100 | Alpha detection, accuracy |
| **SI-29BG** | β,γ | 57 | Standard+ | 0.05–3 MeV | $20–30 | SBM-20 upgrade |
| **SI-22G** | β,γ | 57 | Standard | 0.05–3 MeV | $15–25 | SBM-20 equivalent |
| **J305βγ** | β,γ | 153 | Very High | 0.03–3 MeV | $15–20 | Maximum sensitivity |

**Conversion Factor**: CPM → µSv/hr, scaled by 10,000 (as used in firmware)

---

## Detailed Tube Specifications

### SBM-20 (Soviet/Russian)
**Default tube for MightyOhm kit**

- **Manufacturer**: Sovtube / various Russian manufacturers
- **Type**: Halogen-quenched GM tube
- **Detection**: Beta (β) and Gamma (γ) radiation
- **Sensitivity**: 29 CPS per mR/hr (typical)
- **Conversion Factor**: 57 (CPM × 57 / 10000 = µSv/hr)
- **Dead Time**: ~190 µs
- **Operating Voltage**: 400V typical (350–475V range)
- **Dimensions**: 108mm × 11mm
- **Window**: Thin glass (~0.05mm steel equivalent)
- **Energy Range**: 0.05–3 MeV (gamma)
- **Lifespan**: ~10¹⁰ pulses
- **Temperature Range**: -40°C to +70°C
- **Cost**: $15–25

**Pros:**
- Inexpensive and readily available
- Reliable and well-characterized
- Good general-purpose detector
- Robust construction

**Cons:**
- No alpha detection (glass window blocks alphas)
- Lower sensitivity than premium tubes
- Russian quality control can vary

**Best for:** General radiation monitoring, educational use, hobbyist projects

---

### LND-712 (USA)
**Premium upgrade with alpha detection**

- **Manufacturer**: LND Inc. (USA)
- **Type**: Halogen-quenched GM tube with mica window
- **Detection**: Alpha (α), Beta (β), and Gamma (γ) radiation
- **Sensitivity**: 54 CPS per mR/hr (typical)
- **Conversion Factor**: 108 (CPM × 108 / 10000 = µSv/hr)
- **Dead Time**: ~90 µs (faster recovery than SBM-20)
- **Operating Voltage**: 500V typical (450–650V range)
- **Dimensions**: 89mm × 10mm
- **Window**: Mica end window (1.5–2.0 mg/cm²)
- **Alpha Detection**: Yes, through mica window
- **Energy Range**: 
  - Alpha: >2.5 MeV
  - Beta: >0.16 MeV
  - Gamma: 0.01–2 MeV (energy compensated)
- **Lifespan**: ~10¹¹ pulses
- **Temperature Range**: -40°C to +70°C
- **Cost**: $75–100

**Pros:**
- **Alpha particle detection** (unique among these tubes)
- Higher sensitivity than SBM-20
- Better quality control (US-made)
- Faster dead time = better at high count rates
- Energy compensated for more accurate dose measurement
- Excellent documentation and support

**Cons:**
- Expensive (3–4× cost of SBM-20)
- Mica window is fragile (can be damaged by handling)
- Requires higher operating voltage

**Best for:** 
- Alpha contamination detection (uranium, plutonium, radon, thorium)
- Professional/laboratory use
- Accurate environmental dose measurement
- Detecting uranium glass (emits alpha particles)

**Note on Alpha Detection:** 
The mica window allows alpha particles to enter the tube. This is critical for detecting alpha emitters like uranium-238 in uranium glass, radon decay products, and contamination from plutonium or americium. The SBM-20's glass window completely blocks alpha particles.

---

### SI-29BG (Soviet/Russian)
**Improved SBM-20 alternative**

- **Manufacturer**: Sovtube
- **Type**: Halogen-quenched GM tube
- **Detection**: Beta (β) and Gamma (γ) radiation
- **Sensitivity**: ~30 CPS per mR/hr (slightly better than SBM-20)
- **Conversion Factor**: 57 (same as SBM-20)
- **Dead Time**: ~190 µs
- **Operating Voltage**: 400V typical (350–475V range)
- **Dimensions**: 108mm × 11mm (same as SBM-20)
- **Window**: Thin glass
- **Energy Range**: 0.05–3 MeV
- **Lifespan**: ~10¹⁰ pulses
- **Cost**: $20–30

**Pros:**
- Direct drop-in replacement for SBM-20
- Slightly better sensitivity
- Same conversion factor (no firmware change needed)
- Better QC than generic SBM-20

**Cons:**
- Still no alpha detection
- More expensive than SBM-20 with minimal improvement
- Harder to source than SBM-20

**Best for:** Those who want slightly better performance than SBM-20 without spending for LND-712

---

### SI-22G (Soviet/Russian)
**SBM-20 equivalent**

- **Manufacturer**: Sovtube
- **Type**: Halogen-quenched GM tube
- **Detection**: Beta (β) and Gamma (γ) radiation
- **Sensitivity**: ~29 CPS per mR/hr (equivalent to SBM-20)
- **Conversion Factor**: 57 (same as SBM-20)
- **Dead Time**: ~190 µs
- **Operating Voltage**: 400V typical (350–475V range)
- **Dimensions**: 108mm × 11mm
- **Window**: Thin glass
- **Energy Range**: 0.05–3 MeV
- **Lifespan**: ~10¹⁰ pulses
- **Cost**: $15–25

**Pros:**
- Direct SBM-20 replacement
- Same specifications and conversion factor
- Good quality control

**Cons:**
- No advantage over SBM-20
- No alpha detection

**Best for:** Direct SBM-20 replacement when SBM-20 is unavailable

---

### J305βγ (Chinese)
**High-sensitivity budget option**

- **Manufacturer**: North Optic (China) / various Chinese manufacturers
- **Type**: Halogen-quenched GM tube
- **Detection**: Beta (β) and Gamma (γ) radiation
- **Sensitivity**: ~90 CPS per mR/hr (3× more sensitive than SBM-20)
- **Conversion Factor**: 153 (CPM × 153 / 10000 = µSv/hr)
- **Dead Time**: ~300 µs (slower than SBM-20)
- **Operating Voltage**: 380V typical (350–450V range)
- **Dimensions**: 90mm × 10mm
- **Window**: Thin glass
- **Energy Range**: 0.03–3 MeV (lower energy threshold than SBM-20)
- **Lifespan**: ~10¹⁰ pulses
- **Cost**: $15–20

**Pros:**
- **Highest sensitivity** of the tubes listed (great for low-level detection)
- Inexpensive
- Detects lower energy gammas than SBM-20
- Good for contamination detection

**Cons:**
- Slower dead time (saturates at lower radiation levels)
- Chinese QC varies (test before relying on it)
- Physically smaller (may require mechanical adapter)
- No alpha detection

**Best for:** 
- Low-level contamination surveys
- Maximum detection sensitivity on a budget
- Finding weak sources
- Environmental monitoring

---

## Physical Compatibility

All tubes listed above are **electrically compatible** with the MightyOhm board:
- Operating voltage range: 350–650V (board provides adjustable HV)
- Pin spacing: Standard 2-pin configuration
- Anode/cathode polarity: Standard (cathode = body, anode = center pin)

**Mechanical fit:**
- **SBM-20, SI-29BG, SI-22G**: Direct drop-in, same size (108mm × 11mm)
- **LND-712**: Slightly smaller (89mm × 10mm), may need foam padding to secure
- **J305**: Smaller (90mm × 10mm), may need foam padding or 3D-printed adapter

The MightyOhm PCB has mounting clips for SBM-20-sized tubes. Smaller tubes can be secured with foam padding or custom 3D-printed tube holders.

---

## Firmware Configuration

### Default Firmware (SBM-20)

The MightyOhm firmware (v1.00) is **hardcoded** for the SBM-20 tube with this line in `geiger.c`:

```c
#define SCALE_FACTOR	57		// CPM to uSv/hr conversion factor (x10,000 to avoid float)
```

This conversion factor is compiled into the firmware and **cannot be changed at runtime**.

### Using Different Tubes: Two Approaches

#### **Option 1: Software Correction (Recommended)**

**No firmware rebuild required.** The Python driver handles the conversion.

The `rf_bench.mightyohm` driver supports all tube types via the `tube_type` parameter:

```python
from rf_bench.mightyohm import MightyOhmGeiger

# For LND-712 tube
geiger = MightyOhmGeiger(tube_type='LND-712')

# For J305 tube
geiger = MightyOhmGeiger(tube_type='J305')
```

**How it works:**
1. The device still reports dose using the SBM-20 factor (57)
2. The driver **ignores** the device's reported µSv/hr value
3. The driver **recalculates** dose from the CPM value using the correct factor
4. You get accurate dose readings without touching the firmware

**Supported tube types in driver:**
- `'SBM-20'` — Factor 57 (default)
- `'LND-712'` — Factor 108
- `'SI-29BG'` — Factor 57
- `'SI-22G'` — Factor 57
- `'J305'` — Factor 153

**Advantages:**
- No need to rebuild/reflash firmware
- Easy to switch between tubes
- Can compare tubes without hardware changes
- Works with stock MightyOhm kit

**Disadvantages:**
- Device's LCD/serial output still shows wrong µSv/hr
- Must use Python driver to get correct dose
- Can confuse users reading the raw serial output

---

#### **Option 2: Rebuild Firmware (Advanced)**

**For purists who want accurate readings from the device itself.**

If you want the device to report the correct dose directly, you must rebuild and reflash the firmware.

**Requirements:**
- AVR-GCC toolchain (`avr-gcc`, `avr-libc`, `avrdude`)
- ISP programmer (e.g., USBasp, Arduino as ISP)
- 6-pin ISP header connection to ATtiny2313

**Steps:**

1. **Extract and modify firmware:**

```bash
cd /tmp
unzip ~/Dropbox/geiger_counter_src.zip
cd geiger
```

2. **Edit the conversion factor in `geiger.c`:**

For **LND-712**:
```c
#define SCALE_FACTOR	108		// CPM to uSv/hr conversion factor (x10,000)
```

For **J305βγ**:
```c
#define SCALE_FACTOR	153		// CPM to uSv/hr conversion factor (x10,000)
```

For **SI-29BG** or **SI-22G** (same as SBM-20):
```c
#define SCALE_FACTOR	57		// No change needed
```

3. **Rebuild the firmware:**

```bash
make clean
make
```

This produces `geiger.hex`.

4. **Flash the ATtiny2313:**

Using USBasp programmer:
```bash
avrdude -c usbasp -p t2313 -U flash:w:geiger.hex
```

Or using Arduino as ISP:
```bash
avrdude -c avrisp -P /dev/ttyUSB0 -b 19200 -p t2313 -U flash:w:geiger.hex
```

5. **Verify:**

Power on the Geiger counter and verify readings with a known source.

**Advantages:**
- Device reports accurate dose directly
- No software correction needed
- Works with any serial monitor/logger

**Disadvantages:**
- Requires ISP programmer and AVR toolchain
- Permanent (must reflash to change tubes)
- Risk of bricking device if done incorrectly
- Voids warranty (if applicable)

**Warning:** 
The MightyOhm PCB has an ISP header, but it may not be populated. You may need to solder a 6-pin header or use pogo pins to connect the programmer.

---

## Tube Recommendations by Use Case

### **General Purpose / Hobbyist**
→ **SBM-20** (default)
- Best cost/performance ratio
- Reliable and well-documented
- Good for learning

### **Maximum Sensitivity / Contamination Detection**
→ **J305βγ**
- 3× more sensitive than SBM-20
- Great for finding weak sources
- Budget-friendly

### **Alpha Detection / Professional Use**
→ **LND-712**
- Only tube that detects alpha particles
- Best for uranium/radon/plutonium detection
- Higher quality (US-made)
- Better accuracy
- Worth the premium price if detecting alpha is important

### **Minor Upgrade Over SBM-20**
→ **SI-29BG**
- Slightly better than SBM-20
- Drop-in replacement
- Not a huge improvement for the price difference

### **SBM-20 Substitute**
→ **SI-22G**
- Exact SBM-20 equivalent
- Use when SBM-20 is unavailable

---

## Testing Uranium Glass with Different Tubes

Your uranium glass test is perfect for demonstrating tube differences:

### Expected Readings (approximate)

| Tube | Background CPM | Uranium Glass CPM | Ratio |
|------|----------------|-------------------|-------|
| SBM-20 | 20–30 | 140–160 | 5–7× |
| LND-712 | 40–60 | **300–400** | 7–10× |
| J305βγ | 60–90 | **400–500** | 6–8× |
| SI-29BG | 22–32 | 145–165 | 5–7× |

**Why LND-712 shows more counts:**
1. Higher sensitivity (54 vs 29 CPS/mR/hr)
2. **Detects alpha particles** that SBM-20 misses
3. Uranium glass emits both gamma and alpha radiation

The SBM-20's glass window blocks all alpha particles. The LND-712's mica window lets them through, so you see **both** the gamma rays **and** the alpha particles.

---

## Tube Energy Response

Different tubes have different energy response curves:

### Gamma Energy Response

| Energy (keV) | SBM-20 | LND-712 | J305 |
|--------------|--------|---------|------|
| 30 | 0.1 | **0.8** | **0.9** |
| 60 | 0.5 | **1.0** | **1.0** |
| 100 | 0.8 | **1.0** | 0.9 |
| 662 (Cs-137) | 1.0 | 1.0 | 1.0 |
| 1250 (Co-60) | 1.0 | 0.9 | 0.8 |
| 3000 | 0.7 | 0.7 | 0.6 |

**Note:** LND-712 has the most uniform energy response (energy compensated). J305 is better at low energies. SBM-20 under-responds to low-energy gammas.

---

## Where to Buy

### SBM-20 / SI-29BG / SI-22G
- eBay (search "SBM-20 geiger tube")
- AliExpress
- GQ Electronics
- Images SI

### LND-712
- LND Inc. (direct, minimum order may apply)
- GQ Electronics
- Images SI
- Spectrum Techniques

### J305βγ
- AliExpress (most common)
- GQ Electronics
- eBay

**Beware of counterfeits:** Test any tube with a known source before relying on it for measurements.

---

## Conversion Factor Reference

For manual calculations or custom firmware:

| Tube | Factor (×10⁴) | µSv/hr Formula |
|------|---------------|----------------|
| SBM-20 | 57 | CPM × 57 ÷ 10000 |
| LND-712 | 108 | CPM × 108 ÷ 10000 |
| SI-29BG | 57 | CPM × 57 ÷ 10000 |
| SI-22G | 57 | CPM × 57 ÷ 10000 |
| J305βγ | 153 | CPM × 153 ÷ 10000 |

**Example:** 
- **SBM-20** at 150 CPM = 150 × 57 ÷ 10000 = **0.86 µSv/hr**
- **LND-712** at 150 CPM = 150 × 108 ÷ 10000 = **1.62 µSv/hr**
- **J305** at 150 CPM = 150 × 153 ÷ 10000 = **2.30 µSv/hr**

These factors account for the different sensitivities of each tube to Cs-137 gamma radiation (the calibration standard).

---

## References

- [MightyOhm Geiger Counter](http://mightyohm.com/geiger)
- [LND Inc. Tube Specifications](https://www.lndinc.com/)
- [SBM-20 Datasheet](https://www.gstube.com/data/2398/)
- [J305 Tube Specifications](https://www.rhelectronics.store/geiger-mueller-tubes)
- Firmware source: `~/Dropbox/geiger_counter_src.zip`

---

## Summary

**If you just want better readings without hassle:**
- Use the Python driver with `tube_type='LND-712'` or `tube_type='J305'`
- No firmware rebuild needed
- Accurate dose calculations in software

**If you want the device itself to report accurate dose:**
- Rebuild firmware with the correct `SCALE_FACTOR`
- Requires AVR toolchain and ISP programmer
- More permanent solution

**Best upgrade for your uranium glass testing:**
- **LND-712** — detects the alpha particles your SBM-20 is missing
- You'd see much higher counts with the uranium glass due to alpha detection
