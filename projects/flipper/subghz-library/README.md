> ⚠️ **UNTESTED** — This implementation has not been verified against physical hardware.
> Code is complete but has not been bench-tested. Verify behavior before relying on output.

# rf-bench-flipper-subghz-library

**GitHub:** https://github.com/jfrancis42/rf-bench-flipper-subghz-library

Sub-GHz remote code library builder. Captures, labels, and exports 433/315 MHz
remote codes (garage doors, gate controllers, RF outlets) via Flipper Zero.

## Usage

```bash
python subghz_library.py capture --device "Garage Door" --remote "LiftMaster 371LM"
python subghz_library.py replay  --device "Garage Door" --button open
python subghz_library.py list
python subghz_library.py export --format flipper --out export.sub
```

## Exports

- JSON database (`subghz_library_db.json`)
- Flipper `.sub` format
