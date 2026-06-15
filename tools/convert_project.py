#!/usr/bin/env python3
"""
Convert a single rf-bench project file to use inventory system.

Usage:
    python convert_project.py <file.py>
    python convert_project.py <file.py> --dry-run
"""

import re
import sys
from pathlib import Path


# Instrument class to inventory alias mapping
INSTRUMENT_MAP = {
    'SSA3000X': 'ssa',
    'SDG1000X': 'sdg',
    'SDS2000X': 'sds',
    'SDM3000X': 'sdm',
    'SPD3303X': 'spd',
    'IC7300': 'ic7300',
    'IC9700': 'ic9700',
    'FT891': 'ft891',
}

# IP address to alias mapping
IP_TO_ALIAS = {
    '10.1.1.60': 'ssa',
    '10.1.1.55': 'sdg',
    '10.1.1.51': 'sdg',  # Alternative SDG IP from ip.txt
    '10.1.1.58': 'sds',
    '10.1.1.63': 'sdm',
    '10.1.1.56': 'spd',
}


def convert_file(path: Path, dry_run: bool = False):
    """Convert file to use inventory system."""
    content = path.read_text()
    original = content
    lines = content.split('\n')

    # Check if already converted
    if 'from rf_bench import connect' in content:
        print(f"SKIP: {path} (already uses inventory)")
        return

    # Check if uses instruments
    uses_instruments = any(cls in content for cls in INSTRUMENT_MAP.keys())
    if not uses_instruments:
        print(f"SKIP: {path} (doesn't use target instruments)")
        return

    print(f"\nConverting: {path}")

    # 1. Add inventory import after last rf_bench import
    import_added = False
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith('from rf_bench.'):
            lines.insert(i + 1, 'from rf_bench import connect')
            import_added = True
            print("  ✓ Added inventory import")
            break

    # 2. Replace DEFAULT_*_HOST IP constants
    for i, line in enumerate(lines):
        for ip in IP_TO_ALIAS.keys():
            if f'= "{ip}"' in line and 'DEFAULT_' in line and '_HOST' in line:
                lines[i] = re.sub(r'=\s*"[0-9.]+"', '= None  # Now uses inventory', line)
                print(f"  ✓ Cleared hardcoded IP in line {i+1}")

    # 3. Replace instrument instantiation
    # Pattern: ssa = SSA3000X("10.1.1.60")  →  ssa = connect('ssa')
    # Pattern: ssa = SSA3000X(args.ssa_host)  →  ssa = connect(args.ssa or 'ssa')
    for i, line in enumerate(lines):
        for cls, alias in INSTRUMENT_MAP.items():
            # Direct IP instantiation
            match = re.search(rf'(\w+)\s*=\s*{cls}\s*\(\s*"([0-9.]+)"', line)
            if match:
                var_name = match.group(1)
                ip = match.group(2)
                inv_alias = IP_TO_ALIAS.get(ip, alias)
                lines[i] = re.sub(
                    rf'{cls}\s*\([^)]+\)',
                    f"connect('{inv_alias}')",
                    line
                )
                print(f"  ✓ Converted {cls} instantiation in line {i+1}")

            # args.* instantiation
            match = re.search(rf'(\w+)\s*=\s*{cls}\s*\(\s*args\.(\w+)', line)
            if match:
                var_name = match.group(1)
                arg_name = match.group(2)
                lines[i] = re.sub(
                    rf'{cls}\s*\([^)]+\)',
                    f"connect(args.{arg_name} or '{alias}')",
                    line
                )
                print(f"  ✓ Converted {cls} instantiation with args in line {i+1}")

    # 4. Update print statements about connections
    for i, line in enumerate(lines):
        if 'Connecting to' in line and '@' in line:
            # Change "@ IP" to "via inventory"
            lines[i] = re.sub(r'@\s*\{[^}]+\}', "via inventory'}", line)
            lines[i] = re.sub(r'@\s*[0-9.]+', "via inventory", lines[i])

    new_content = '\n'.join(lines)

    if dry_run:
        # Show diff
        if new_content != original:
            print("\n  Changes:")
            orig_lines = original.split('\n')
            new_lines = new_content.split('\n')
            for i, (o, n) in enumerate(zip(orig_lines, new_lines)):
                if o != n:
                    print(f"    {i+1:4d}: - {o}")
                    print(f"    {i+1:4d}: + {n}")
    else:
        # Save
        if new_content != original:
            path.write_text(new_content)
            print(f"  ✓ Saved changes")
        else:
            print(f"  No changes needed")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = Path(sys.argv[1])
    dry_run = '--dry-run' in sys.argv

    if not path.exists():
        print(f"ERROR: {path} not found")
        sys.exit(1)

    convert_file(path, dry_run=dry_run)


if __name__ == '__main__':
    main()
