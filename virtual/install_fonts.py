#!/usr/bin/env python3
"""
Font Installer for Virtual Instruments (rf-bench)

This script helps you install third-party fonts for virtual instruments.

IMPORTANT: Due to licensing restrictions, these fonts cannot be redistributed
with this application. You must download them yourself.

Fonts installed:
- Analog Digits Pack 1 & 2 (for numeric-display: Nixie & VFD styles)
- Dot Matrix (for text-lcd: LCD display style)

Author: Jeff Francis (N0GQ) <gjfrancis@protonmail.com>
License: GPL-3.0-or-later
"""

import os
import sys
import zipfile
import shutil
from pathlib import Path


def print_header():
    """Print welcome message"""
    print("=" * 70)
    print("Virtual Instruments Font Installer")
    print("rf-bench")
    print("=" * 70)
    print()


def print_instructions():
    """Print download instructions"""
    print("FONT DOWNLOAD INSTRUCTIONS")
    print("=" * 70)
    print()
    print("This installer will help you download and install fonts for:")
    print()
    print("  1. Virtual Numeric Display (Nixie & VFD styles)")
    print("  2. Virtual Text LCD (Dot Matrix style)")
    print()
    print("All fonts are free to use but cannot be redistributed with this")
    print("application due to licensing restrictions.")
    print()
    print("=" * 70)
    print()


def print_analog_instructions():
    """Print Analog Digits download instructions"""
    print("ANALOG DIGITS FONT PACKS (for Numeric Display)")
    print("-" * 70)
    print()
    print("These fonts provide Nixie tube and VFD display styles.")
    print()
    print("  Pack 1 (Nixie & VFD fonts):")
    print("  https://speakthesky.itch.io/typeface-analog-digits-pack")
    print()
    print("  Pack 2 (Additional display fonts - OPTIONAL):")
    print("  https://speakthesky.itch.io/typeface-analog-digits-pack-2")
    print()
    print("Both packs are FREE (pay-what-you-want, $0 is okay).")
    print("Download the ZIP files and save them to a location you can find.")
    print()
    print("=" * 70)
    print()


def print_dotmatrix_instructions():
    """Print Dot Matrix download instructions"""
    print("DOT MATRIX FONT (for Text LCD)")
    print("-" * 70)
    print()
    print("This font provides the classic dot-matrix LCD display look.")
    print()
    print("  Download from:")
    print("  http://www.pickafont.com/fonts/dot-matrix")
    print()
    print("  Creator: Moonbase Press")
    print()
    print("Click 'Info & Download' on the page and download 'Dot Matrix.zip'.")
    print("This font is free to use.")
    print()
    print("=" * 70)
    print()


def get_zip_path(pack_name: str, expected_filename: str) -> Path:
    """Prompt user for ZIP file path"""
    while True:
        print(f"Enter the path to {pack_name}:")
        print(f"(Expected filename: {expected_filename})")
        print("(or press Enter to skip)")
        path_str = input("> ").strip()

        if not path_str:
            return None  # User chose to skip

        # Expand ~ and environment variables
        path_str = os.path.expanduser(path_str)
        path_str = os.path.expandvars(path_str)

        # Remove quotes if user pasted path with quotes
        path_str = path_str.strip('"').strip("'")

        path = Path(path_str)

        if not path.exists():
            print(f"ERROR: File not found: {path}")
            print("Please check the path and try again.\n")
            continue

        if not path.is_file():
            print(f"ERROR: Not a file: {path}\n")
            continue

        if path.suffix.lower() != '.zip':
            print(f"ERROR: Not a ZIP file: {path}")
            print("Please provide the .zip file you downloaded.\n")
            continue

        return path


def extract_fonts(zip_path: Path, target_dir: Path, font_list: list) -> list:
    """
    Extract specific font files from ZIP to target directory.
    Returns list of (font_name, success, message) tuples.
    """
    results = []

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # List all font files in the archive
            font_files = [f for f in zf.namelist()
                         if f.endswith(('.woff2', '.ttf', '.TTF', '.otf'))]

            for font_name in font_list:
                # Find the font in the archive (case-insensitive)
                matching = [f for f in font_files
                           if font_name.lower() in f.lower()]

                if not matching:
                    results.append((font_name, False, "Not found in ZIP"))
                    continue

                # Extract the first match
                zip_member = matching[0]

                try:
                    # Read from ZIP
                    font_data = zf.read(zip_member)

                    # Write to target (preserve original filename from request)
                    target_path = target_dir / font_name
                    target_path.write_bytes(font_data)

                    results.append((font_name, True, f"Installed {len(font_data)} bytes"))

                except Exception as e:
                    results.append((font_name, False, f"Extract failed: {e}"))

    except zipfile.BadZipFile:
        print(f"ERROR: Invalid ZIP file: {zip_path}")
        return [(fn, False, "Bad ZIP file") for fn in font_list]
    except Exception as e:
        print(f"ERROR: Failed to read ZIP: {e}")
        return [(fn, False, str(e)) for fn in font_list]

    return results


def install_analog_fonts(script_dir: Path):
    """Install Analog Digits fonts for numeric display"""
    print("\nSTEP 1: Install Analog Digits Fonts (Numeric Display)")
    print("=" * 70)

    print_analog_instructions()

    numeric_display_dir = script_dir / "numeric-display"
    fonts_dir = numeric_display_dir / "frontend" / "fonts"

    if not numeric_display_dir.exists():
        print(f"WARNING: numeric-display directory not found: {numeric_display_dir}")
        print("Skipping Analog Digits fonts.\n")
        return

    fonts_dir.mkdir(parents=True, exist_ok=True)
    print(f"Target font directory: {fonts_dir}\n")

    # Pack 1: Nixie and VFD fonts
    print("ANALOG DIGITS PACK 1")
    print("-" * 70)
    pack1_path = get_zip_path(
        "Analog Digits font pack v1_1.zip",
        "Analog Digits font pack v1_1.zip"
    )

    if pack1_path:
        print(f"Found: {pack1_path}\n")

        pack1_fonts = [
            "reNix-Regular.woff2",      # Nixie tube font
            "fluoWrite-Regular.woff2",  # VFD font
            "nimoType-Regular.woff2"    # Bonus font
        ]

        print("Extracting fonts from Pack 1...")
        results1 = extract_fonts(pack1_path, fonts_dir, pack1_fonts)

        for font_name, success, message in results1:
            status = "✓" if success else "✗"
            print(f"  {status} {font_name}: {message}")
        print()
    else:
        print("Skipped Pack 1.\n")

    # Pack 2: Additional display fonts (optional)
    print("ANALOG DIGITS PACK 2 (OPTIONAL)")
    print("-" * 70)
    print("Pack 2 contains additional display fonts. Skip if you only want")
    print("Nixie (reNix) and VFD (fluoWrite) styles.\n")

    pack2_path = get_zip_path(
        "Analog Digits font pack volume 2 v1_0.zip",
        "Analog Digits font pack volume 2 v1_0.zip"
    )

    if pack2_path:
        print(f"Found: {pack2_path}\n")

        pack2_fonts = [
            "reLix-Regular.woff2",      # Tube display
            "cursiv8-Regular.woff2",    # Cursive style
            "tEggst-Regular.woff2",     # 7-segment LCD
            "tEggst-Bold.woff2",
            "tEggst-Light.woff2"
        ]

        print("Extracting fonts from Pack 2...")
        results2 = extract_fonts(pack2_path, fonts_dir, pack2_fonts)

        for font_name, success, message in results2:
            status = "✓" if success else "✗"
            print(f"  {status} {font_name}: {message}")
        print()
    else:
        print("Skipped Pack 2.\n")


def install_dotmatrix_font(script_dir: Path):
    """Install Dot Matrix font for text LCD"""
    print("\nSTEP 2: Install Dot Matrix Font (Text LCD)")
    print("=" * 70)

    print_dotmatrix_instructions()

    text_lcd_dir = script_dir / "text-lcd"
    frontend_dir = text_lcd_dir / "frontend"

    if not text_lcd_dir.exists():
        print(f"WARNING: text-lcd directory not found: {text_lcd_dir}")
        print("Skipping Dot Matrix font.\n")
        return

    frontend_dir.mkdir(parents=True, exist_ok=True)
    print(f"Target directory: {frontend_dir}\n")

    dotmatrix_path = get_zip_path(
        "Dot Matrix.zip",
        "Dot Matrix.zip"
    )

    if dotmatrix_path:
        print(f"Found: {dotmatrix_path}\n")

        fonts = ["DotMatrix.TTF"]

        print("Extracting Dot Matrix font...")
        results = extract_fonts(dotmatrix_path, frontend_dir, fonts)

        for font_name, success, message in results:
            status = "✓" if success else "✗"
            print(f"  {status} {font_name}: {message}")
        print()
    else:
        print("Skipped Dot Matrix font.\n")


def print_summary():
    """Print installation summary"""
    print("=" * 70)
    print("Installation complete!")
    print("=" * 70)
    print()
    print("Installed fonts are now available in:")
    print()
    print("  NUMERIC DISPLAY:")
    print("    CONF:STYLE NIXIE  → reNix font (orange Nixie tube glow)")
    print("    CONF:STYLE VFD    → fluoWrite font (cyan VFD glow)")
    print()
    print("  TEXT LCD:")
    print("    Uses DotMatrix.TTF automatically")
    print()
    print("Restart the backend servers to load the new fonts.")
    print()
    print("License reminder:")
    print("  - Analog Digits: May be used in projects, cannot redistribute fonts")
    print("  - Dot Matrix: Free to use, check pickafont.com for full terms")
    print()


def main():
    """Main installer flow"""
    print_header()
    print_instructions()

    # Determine script directory (virtual/)
    script_dir = Path(__file__).parent
    print(f"Installation directory: {script_dir}\n")

    # Install fonts for each instrument
    install_analog_fonts(script_dir)
    install_dotmatrix_font(script_dir)

    # Summary
    print_summary()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInstallation cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
