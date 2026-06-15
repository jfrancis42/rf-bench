#!/usr/bin/env python3
"""
Convert rf-bench projects to use the inventory system.

Replaces hardcoded imports and connections with inventory.connect().
"""

import re
import sys
from pathlib import Path

# Mapping of old imports to inventory aliases
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

# Patterns to detect hardcoded IPs
IP_PATTERNS = [
    (r'DEFAULT_SSA_HOST\s*=\s*["\']10\.1\.1\.60["\']', 'DEFAULT_SSA_HOST = None  # Now uses inventory'),
    (r'DEFAULT_SDG_HOST\s*=\s*["\']10\.1\.1\.55["\']', 'DEFAULT_SDG_HOST = None  # Now uses inventory'),
    (r'DEFAULT_SDS_HOST\s*=\s*["\']10\.1\.1\.58["\']', 'DEFAULT_SDS_HOST = None  # Now uses inventory'),
    (r'DEFAULT_SDM_HOST\s*=\s*["\']10\.1\.1\.63["\']', 'DEFAULT_SDM_HOST = None  # Now uses inventory'),
    (r'DEFAULT_SPD_HOST\s*=\s*["\']10\.1\.1\.56["\']', 'DEFAULT_SPD_HOST = None  # Now uses inventory'),
]


def convert_file(path: Path, dry_run: bool = False) -> bool:
    """Convert a single Python file to use inventory system.

    Returns:
        True if file was modified, False otherwise
    """
    try:
        content = path.read_text()
    except:
        return False

    original = content
    modified = False

    # Check if file already uses inventory
    if 'from rf_bench import connect' in content:
        return False

    # Check if file uses any target instruments
    uses_instruments = any(cls in content for cls in INSTRUMENT_MAP.keys())
    if not uses_instruments:
        return False

    # Add inventory import at top (after existing rf_bench imports)
    if 'from rf_bench' in content and 'from rf_bench import connect' not in content:
        # Find last rf_bench import
        lines = content.split('\n')
        insert_pos = -1
        for i, line in enumerate(lines):
            if line.strip().startswith('from rf_bench'):
                insert_pos = i

        if insert_pos >= 0:
            # Insert after last rf_bench import
            lines.insert(insert_pos + 1, 'from rf_bench import connect')
            content = '\n'.join(lines)
            modified = True

    # Replace hardcoded IP defaults
    for pattern, replacement in IP_PATTERNS:
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
            modified = True

    # Replace instrument instantiation patterns
    # SSA3000X(host) -> connect('ssa')
    for cls, alias in INSTRUMENT_MAP.items():
        # Pattern: ssa = SSA3000X("10.1.1.60")
        pattern = rf'{cls}\s*\(\s*["\'][0-9.]+["\']\s*(?:,\s*\w+\s*=\s*[^)]+)?\)'
        if re.search(pattern, content):
            replacement = f"connect('{alias}')"
            content = re.sub(pattern, replacement, content)
            modified = True

        # Pattern: ssa = SSA3000X(args.ssa_host)
        pattern = rf'{cls}\s*\(\s*args\.\w+\s*(?:,\s*\w+\s*=\s*[^)]+)?\)'
        if re.search(pattern, content):
            # Keep variable construction, just change the call
            # This is harder to automate safely, skip for now
            pass

    if modified and not dry_run:
        path.write_text(content)
        return True

    return modified


def main():
    if len(sys.argv) < 2:
        print("Usage: convert_to_inventory.py <file_or_directory> [--dry-run]")
        sys.exit(1)

    target = Path(sys.argv[1])
    dry_run = '--dry-run' in sys.argv

    if target.is_file():
        files = [target]
    else:
        files = list(target.rglob('*.py'))

    converted = []
    for f in files:
        if convert_file(f, dry_run=dry_run):
            converted.append(f)
            status = "[DRY RUN]" if dry_run else "[CONVERTED]"
            print(f"{status} {f}")

    print(f"\nTotal: {len(converted)} files {'would be' if dry_run else 'were'} modified")


if __name__ == '__main__':
    main()
