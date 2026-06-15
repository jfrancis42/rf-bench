# Virtual Instruments Font Installation

This document explains how to install third-party fonts for rf-bench virtual instruments.

## Why Manual Installation?

Most virtual instruments use the **DSEG7** font family (included with rf-bench under the OFL license). However, two proprietary fonts cannot be redistributed due to licensing restrictions:

- **Analog Digits** (Nixie/VFD styles) by SpeakTheSky
- **Dot Matrix** (LCD style) by Moonbase Press

Both are **free to download and use**, but you must obtain them from the original creators.

## Quick Start

```bash
cd virtual
python3 install_fonts.py
```

The installer will guide you through:
1. Downloading fonts from the original sources
2. Extracting them to the correct locations
3. Verifying successful installation

**Windows:**
```cmd
cd virtual
python install_fonts.py
```

## Fonts Included (No Installation Required)

### DSEG 7-Segment Font Family

**Creator:** keshikan  
**License:** SIL Open Font License 1.1 (OFL)  
**Download:** https://github.com/keshikan/DSEG/releases  
**Used by:** Virtual Numeric Display (default 7SEG and LED styles)

**Font files included:**
- `DSEG7Classic-Regular.ttf` / `.woff` / `.woff2`

This font is redistributed with rf-bench under the OFL license. No installation needed.

---

## Fonts Requiring Manual Installation

### Virtual Numeric Display

**Analog Digits Font Packs** by SpeakTheSky

Provides Nixie tube and VFD display styles.

- **Pack 1:** https://speakthesky.itch.io/typeface-analog-digits-pack
  - `reNix-Regular.woff2` (Nixie tube style)
  - `fluoWrite-Regular.woff2` (VFD style)
  - `nimoType-Regular.woff2` (bonus)

- **Pack 2** (optional): https://speakthesky.itch.io/typeface-analog-digits-pack-2
  - Additional display fonts

**License:** Free (pay-what-you-want, $0 okay); use in projects allowed; cannot redistribute fonts

### Virtual Text LCD

**Dot Matrix Font** by Moonbase Press

Provides classic dot-matrix LCD display style.

- **Download:** http://www.pickafont.com/fonts/dot-matrix
  - `DotMatrix.TTF`

**License:** Free to use

## Display Styles Available

### After Installing Fonts:

**Numeric Display:**
- `CONF:STYLE NIXIE` — Orange Nixie tube glow (reNix font)
- `CONF:STYLE VFD` — Cyan VFD glow (fluoWrite font)

**Text LCD:**
- Automatically uses DotMatrix.TTF when installed

### Built-in (No Installation):

**Numeric Display:**
- `CONF:STYLE 7SEG` — Green 7-segment LCD (DSEG7 font)
- `CONF:STYLE LED` — Red LED display (DSEG7 font)
- `CONF:STYLE PLAIN` — Modern sans-serif (Orbitron font)

## Usage Examples

### Numeric Display with Nixie Font

```python
from rf_bench.virtual import VirtualNumericDisplay

display = VirtualNumericDisplay("localhost", port=5000)
display.set_style("NIXIE")
display.set_color("#ff6600")
display.set_precision(4)
display.set_value(13.8000)
```

### Numeric Display with VFD Font

```python
display.set_style("VFD")
display.set_color("#00ffcc")
display.set_value(42.1234)
```

## Troubleshooting

**Q: Fonts not showing after installation**
- Restart the backend server
- Hard refresh browser (Ctrl + Shift + R)
- Check browser console (F12) for 404 errors

**Q: Installer can't find fonts in ZIP**
- Make sure you downloaded the correct ZIP file
- Check the ZIP isn't corrupted (try unzipping manually)
- Verify you're providing the full path to the ZIP

**Q: Where should I save the downloaded ZIPs?**
- Anywhere you can find them (Desktop, Downloads, etc.)
- The installer will ask for the path
- Optional: save to `~/Dropbox/build/rf-bench/fonts/` for easy access

## License Compliance

These fonts are used under their respective licenses:

- **DSEG7 (keshikan):** SIL Open Font License 1.1 — redistributed with rf-bench
- **Analog Digits (SpeakTheSky):** Commercial use allowed, cannot redistribute font files
- **Dot Matrix (Moonbase Press):** Free to use, see pickafont.com for terms

**DSEG7** is included in the repository. **Analog Digits** and **Dot Matrix** must be downloaded by users from the original sources. The `install_fonts.py` script helps automate the extraction and placement, but does not distribute proprietary fonts.

## For Developers

Font files are excluded from git via `.gitignore`:
- `virtual/numeric-display/.gitignore` — Analog Digits fonts
- `virtual/text-lcd/.gitignore` — Dot Matrix font
- Root `.gitignore` — `fonts/` directory (local archive)

The `fonts/` directory in the rf-bench root is for local storage only and is not pushed to GitHub.

## See Also

- `virtual/numeric-display/FONTS.md` — Detailed Analog Digits installation
- `virtual/numeric-display/README.md` — Numeric Display documentation
- `virtual/text-lcd/README.md` — Text LCD documentation
