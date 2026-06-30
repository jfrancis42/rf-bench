# Examples

Example scripts demonstrating the MHS-5200A driver capabilities.

## arbitrary_waveform.py

Demonstrates creating and uploading custom waveforms to the device's 16 arbitrary waveform slots (ARB0-ARB15).

**What it shows:**
- Single-cycle sine wave
- Multi-cycle waveforms (frequency multiplication)
- Pulse trains and bursts
- AM modulation envelope
- Pseudo-random noise
- Exponential decay (RC simulation)
- Custom sensor waveforms (ECG-like)
- Sawtooth bursts

**Usage:**
```bash
python3 arbitrary_waveform.py
```

This uploads 8 different waveforms to slots 0-7. After running, you can use them with:
```python
gen.set_waveform(1, Waveform.ARB0)  # or ARB1, ARB2, etc.
```

**Requirements:**
- MHS-5200A connected on default port (auto-detected)
- `rf-bench-drivers-koolertron` installed

**Note:** This script only uploads the waveforms; it doesn't output them. To see the waveforms, connect the device output to an oscilloscope and use `set_waveform()` to select which one to play.
