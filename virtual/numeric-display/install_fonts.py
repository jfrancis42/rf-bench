#!/usr/bin/env python3
"""
Analog Digits Font Pack Installer for Virtual Numeric Display

This script helps you install the Analog Digits font packs (Nixie and VFD styles)
for use with the Virtual Numeric Display instrument.

IMPORTANT: Due to licensing restrictions, these fonts cannot be redistributed
with this application. You must download them yourself from itch.io.

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
    print("Analog Digits Font Pack Installer")
    print("Virtual Numeric Display - rf-bench")
    print("=" * 70)
    print()


def print_instructions():
    """Print download instructions"""
    print("STEP 1: Download the font packs")
    print("-" * 70)
    print()
    print("These fonts are licensed and cannot be redistributed with this")
    print("application. You must download them yourself from itch.io:")
    print()
    print("  Pack 1 (Nixie & VFD fonts):")
    print("  https://speakthesky.itch.io/typeface-analog-digits-pack")
    print()
    print("  Pack 2 (Additional display fonts):")
    print("  https://speakthesky.itch.io/typeface-analog-digits-pack-2")
    print()
    print("Both packs are FREE (pay-what-you-want, $0 is okay).")
    print()
    print("Download both ZIP files and save them to a location you can find.")
    print("You can enter $0 at checkout to download for free.")
    print()
    print("=" * 70)
    print()


def get_zip_path(pack_name: str, expected_filename: str) -> Path:
    """Prompt user for ZIP file path"""
    while True:
        print(f"Enter the path to {pack_name}:")
        print(f"(Expected filename: {expected_filename})")
        path_str = input("> ").strip()

        if not path_str:
            print("ERROR: No path entered. Try again.\n")
            continue

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
    Returns list of (font_name, success) tuples.
    """
    results = []

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # List all woff2 files in the archive
            woff2_files = [f for f in zf.namelist() if f.endswith('.woff2')]

            for font_name in font_list:
                # Find the font in the archive
                matching = [f for f in woff2_files if font_name in f]

                if not matching:
                    results.append((font_name, False, "Not found in ZIP"))
                    continue

                # Extract the first match
                zip_member = matching[0]

                try:
                    # Read from ZIP
                    font_data = zf.read(zip_member)

                    # Write to target
                    target_path = target_dir / font_name
                    target_path.write_bytes(font_data)

                    results.append((font_name, True, f"Installed {len(font_data)} bytes"))

                except Exception as e:
                    results.append((font_name, False, f"Extract failed: {e}"))

    except zipfile.BadZipFile:
        print(f"ERROR: Invalid ZIP file: {zip_path}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to read ZIP: {e}")
        sys.exit(1)

    return results


def main():
    """Main installer flow"""
    print_header()
    print_instructions()

    # Determine target directory (same directory as this script)
    script_dir = Path(__file__).parent
    frontend_dir = script_dir / "frontend"
    fonts_dir = frontend_dir / "fonts"

    if not frontend_dir.exists():
        print(f"ERROR: Frontend directory not found: {frontend_dir}")
        print("This script must be run from the virtual/numeric-display/ directory.")
        sys.exit(1)

    # Create fonts directory if it doesn't exist
    fonts_dir.mkdir(exist_ok=True)
    print(f"Target font directory: {fonts_dir}")
    print()

    # Pack 1: Nixie and VFD fonts
    print("STEP 2: Install Pack 1 (Nixie & VFD fonts)")
    print("-" * 70)
    pack1_path = get_zip_path(
        "Analog Digits font pack v1_1.zip",
        "Analog Digits font pack v1_1.zip"
    )
    print(f"Found: {pack1_path}")
    print()

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

    # Pack 2: Additional display fonts (optional)
    print("STEP 3: Install Pack 2 (Additional fonts) [OPTIONAL]")
    print("-" * 70)
    print("Pack 2 contains additional display fonts. You can skip this if you")
    print("only want Nixie (reNix) and VFD (fluoWrite) styles.")
    print()

    skip = input("Skip Pack 2? (y/N): ").strip().lower()

    if skip == 'y':
        print("Skipping Pack 2.")
    else:
        pack2_path = get_zip_path(
            "Analog Digits font pack volume 2 v1_0.zip",
            "Analog Digits font pack volume 2 v1_0.zip"
        )
        print(f"Found: {pack2_path}")
        print()

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

    # Summary
    print("=" * 70)
    print("Installation complete!")
    print("=" * 70)
    print()
    print("The following styles are now available:")
    print()
    print("  CONF:STYLE NIXIE  → reNix font (orange Nixie tube glow)")
    print("  CONF:STYLE VFD    → fluoWrite font (cyan VFD glow)")
    print("  CONF:STYLE 7SEG   → DSEG7 font (green LCD, built-in)")
    print("  CONF:STYLE LED    → DSEG7 font (red LED, built-in)")
    print("  CONF:STYLE PLAIN  → Orbitron font (modern, built-in)")
    print()
    print("Restart the virtual-numeric-display backend server to load the fonts.")
    print()
    print("Usage example:")
    print('  echo "CONF:STYLE NIXIE" | nc localhost 5000')
    print('  echo "CONF:STYLE VFD" | nc localhost 5000')
    print()
    print("License reminder: These fonts may be used in your projects, but you")
    print("may not redistribute the font files themselves. Users must download")
    print("them from itch.io.")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInstallation cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: {e}")
        sys.exit(1)
