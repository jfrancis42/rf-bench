# Font Installation Guide

The Virtual Numeric Display supports multiple display styles including Nixie tubes and VFD displays. Due to licensing restrictions, the Analog Digits font packs cannot be redistributed with this application.

## Required Fonts (for Nixie and VFD styles)

**Analog Digits Font Pack v1.1** - Contains:
- `reNix-Regular.woff2` - Nixie tube font (used for `NIXIE` style)
- `fluoWrite-Regular.woff2` - VFD font (used for `VFD` style)
- `nimoType-Regular.woff2` - Bonus display font

**Download:** https://speakthesky.itch.io/typeface-analog-digits-pack

**Analog Digits Font Pack Volume 2 v1.0** (optional) - Contains:
- `reLix-Regular.woff2` - Tube display
- `cursiv8-Regular.woff2` - Cursive style
- `tEggst-*.woff2` - 7-segment LCD variants

**Download:** https://speakthesky.itch.io/typeface-analog-digits-pack-2

Both packs are **pay-what-you-want** (free/$0 is okay).

## Automated Installation

Run the installer script:

```bash
cd ~/Dropbox/build/rf-bench/virtual/numeric-display
python3 install_fonts.py
```

The script will:
1. Show download instructions with itch.io URLs
2. Prompt you for the path to each downloaded ZIP file
3. Extract the required .woff2 files to `frontend/fonts/`
4. Confirm successful installation

**Windows users:**
```cmd
cd C:\path\to\rf-bench\virtual\numeric-display
python install_fonts.py
```

## Manual Installation

If you prefer manual installation:

1. Download both ZIP files from the itch.io links above
2. Extract the ZIP files
3. Copy these files to `virtual/numeric-display/frontend/fonts/`:
   - From Pack 1 `woff2 files/` directory:
     - `reNix-Regular.woff2`
     - `fluoWrite-Regular.woff2`
     - `nimoType-Regular.woff2`
   - From Pack 2 `woff2 files/` directory (optional):
     - `reLix-Regular.woff2`
     - `cursiv8-Regular.woff2`
     - `tEggst-Regular.woff2`
     - `tEggst-Bold.woff2`
     - `tEggst-Light.woff2`

4. Restart the backend server

## Available Display Styles

After installing the fonts:

| SCPI Command | Font | Color | Description |
|--------------|------|-------|-------------|
| `CONF:STYLE NIXIE` | reNix | Orange (#ff8833) | Classic Nixie tube glow, fixed-width |
| `CONF:STYLE VFD` | fluoWrite | Cyan (#00ffcc) | Vacuum Fluorescent Display, fixed-width |
| `CONF:STYLE 7SEG` | DSEG7 | Green (#00ff00) | 7-segment LCD (built-in, no install needed) |
| `CONF:STYLE LED` | DSEG7 | Red (#ff3333) | LED display (built-in, no install needed) |
| `CONF:STYLE PLAIN` | Orbitron | Green (#00ff00) | Modern sans-serif (built-in, no install needed) |

## Usage Example

```python
from rf_bench.virtual import VirtualNumericDisplay

display = VirtualNumericDisplay("localhost", port=5000)
display.set_style("NIXIE")   # Orange Nixie tube font
display.set_color("#ff6600")
display.set_value(13.8)

# Or use VFD style
display.set_style("VFD")     # Cyan VFD font
display.set_color("#00ffcc")
```

Or via raw SCPI:
```bash
echo "CONF:STYLE NIXIE" | nc localhost 5000
echo "CONF:COL #ff6600" | nc localhost 5000
echo "MEAS:VAL 13.8" | nc localhost 5000
```

## License Information

**Analog Digits Font Packs** by SpeakTheSky (https://speakthesky.itch.io/)

- ✅ **Allowed:** Use in commercial and personal projects
- ✅ **Allowed:** Use in web, print, video, games, applications
- ❌ **Not allowed:** Redistribute the font files themselves
- ❌ **Not allowed:** Resell or repackage the fonts

Users of this application must download the fonts themselves from the official itch.io page.

## Troubleshooting

**Q: The fonts aren't showing up after installation**
- Restart the backend server: `pkill -f numeric-display.*server.py`
- Hard refresh your browser: Ctrl + Shift + R
- Check that .woff2 files are in `frontend/fonts/`
- Check browser console (F12) for 404 errors

**Q: I don't see reNix or fluoWrite in the ZIP**
- Look in the `woff2 files/` subdirectory within the ZIP
- Pack 1 and Pack 2 are separate downloads from different itch.io pages

**Q: Can I use OTF fonts instead of WOFF2?**
- The backend only serves WOFF2 for web browsers
- WOFF2 files are in the ZIPs alongside OTF

**Q: Do I need Pack 2?**
- No, Pack 1 is sufficient for Nixie and VFD styles
- Pack 2 is optional (additional display fonts)

## See Also

- `README.md` - Main virtual numeric display documentation
- `/drivers/virtual-numeric-display/README.md` - Python driver API
