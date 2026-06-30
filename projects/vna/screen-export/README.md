# screen-export — NanoVNA LCD screenshot to PNG

Grabs the NanoVNA's screen framebuffer via the shell `capture`
command and decodes it to a PNG.

**Untested against hardware.** The `capture` command's exact
behaviour varies by firmware author (Deepelec / DiSlord / hugen79
all produce slightly different byte layouts). If the script fails,
the fallback is to use the device's built-in USB-mass-storage
screenshot feature on a long-press of the screen.

## Usage

```bash
python screen_export.py --port /dev/ttyACM1 --output screen.png
```

For NanoVNA-H or -H4 (smaller LCD):

```bash
python screen_export.py --port /dev/ttyACM1 --width 320 --height 240 \
    --output screen.png
```

## Requires

`pip install pillow --break-system-packages`

## Notes

- Only supports the ASCII-shell NanoVNA family (NanoVNA-F, -H,
  -H4). NanoVNA-V2 and LiteVNA use binary protocols not handled
  here.
- If the capture decode produces garbage colours, the firmware may
  emit little-endian RGB565 (the script assumes big-endian). Swap
  the byte order in `rgb565_to_rgb888` if needed.
