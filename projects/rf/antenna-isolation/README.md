> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-antenna-isolation

**GitHub:** https://github.com/jfrancis42/rf-bench-antenna-isolation

Measures isolation between two antenna systems using two IC-7300 radios.
Radio 1 transmits CW through a fixed attenuator; Radio 2 reads S-meter.

⚠️ **ALWAYS specify --atten** — the script will abort if the estimated
receive level exceeds -20 dBm to protect Radio 2's front end.

## Usage

```bash
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200 -t 4532 &
rigctld -m 3073 -r /dev/ttyUSB1 -s 115200 -t 4533 &
python antenna_isolation.py --atten 60 --rig1-port 4532 --rig2-port 4533
```

| Flag | Description |
|------|-------------|
| `--atten DB` | **Required** — TX path attenuation in dB |
| `--rig1-port N` | TX radio rigctld port (default 4532) |
| `--rig2-port N` | RX radio rigctld port (default 4533) |
| `--power W` | TX power in watts (default 1.0) |
| `--bands LIST` | Comma-sep bands (default: all HF) |
| `--plot FILE` | Output PNG |
