#!/usr/bin/env python3
"""
CLI tool for searching and managing measurement data.

Commands:
  search    - Search measurements by criteria
  recent    - List recent measurements
  stats     - Show summary statistics
  inspect   - Show detailed info about a measurement
"""

import sys
import argparse
from pathlib import Path
from .search import (
    search_measurements,
    recent_measurements,
    summary_stats
)
from .logging import load_csv


def cmd_search(args):
    """Search measurements by criteria."""
    results = search_measurements(
        name_pattern=args.name,
        tags=args.tags.split(',') if args.tags else None,
        operator=args.operator,
        date_after=args.after,
        date_before=args.before,
        sort_by=args.sort
    )

    if not results:
        print("No measurements found.")
        return 1

    print(f"\nFound {len(results)} measurement(s):\n")

    for i, m in enumerate(results, 1):
        print(f"{i}. {m['name']}")
        print(f"   Date: {m['timestamp']}")
        print(f"   Operator: {m['operator']}")

        if m['tags']:
            tags_str = ', '.join(m['tags']) if isinstance(m['tags'], list) else m['tags']
            print(f"   Tags: {tags_str}")

        print(f"   File: {m['path']}")
        print(f"   Size: {m['size_bytes'] / 1024:.1f} KB")
        print()

    return 0


def cmd_recent(args):
    """List recent measurements."""
    results = recent_measurements(days=args.days)

    if not results:
        print(f"No measurements found in last {args.days} days.")
        return 1

    print(f"\nMeasurements from last {args.days} days ({len(results)} total):\n")

    for m in results[:args.limit]:
        print(f"• {m['timestamp']}: {m['name']}")
        print(f"  Operator: {m['operator']}")

        if m['tags']:
            tags_str = ', '.join(m['tags']) if isinstance(m['tags'], list) else m['tags']
            print(f"  Tags: {tags_str}")

        print()

    if len(results) > args.limit:
        print(f"... and {len(results) - args.limit} more")

    return 0


def cmd_stats(args):
    """Show summary statistics."""
    stats = summary_stats()

    if stats['total_count'] == 0:
        print("No measurements found.")
        return 1

    print(f"\n{'='*60}")
    print("Measurement Database Statistics")
    print(f"{'='*60}\n")

    print(f"Total measurements: {stats['total_count']}")
    print(f"Total size: {stats['total_size_mb']:.1f} MB")
    print(f"Date range: {stats['oldest_date']} to {stats['newest_date']}")
    print()

    if stats['operators']:
        print(f"Operators ({len(stats['operators'])}):")
        for op in stats['operators']:
            print(f"  • {op}")
        print()

    if stats['tags']:
        print(f"Tags ({len(stats['tags'])}):")
        for tag in sorted(stats['by_tag'].items(), key=lambda x: x[1], reverse=True):
            print(f"  • {tag[0]}: {tag[1]} measurement(s)")
        print()

    return 0


def cmd_inspect(args):
    """Show detailed info about a measurement."""
    csv_path = Path(args.file)

    if not csv_path.exists():
        print(f"Error: File not found: {args.file}")
        return 1

    # Load metadata and data
    metadata, data = load_csv(str(csv_path))

    print(f"\n{'='*60}")
    print(f"Measurement: {metadata.get('name', 'Unknown')}")
    print(f"{'='*60}\n")

    print("Metadata:")
    for key, value in sorted(metadata.items()):
        if key == 'tags' and isinstance(value, list):
            value = ', '.join(value)
        print(f"  {key}: {value}")

    print(f"\nData:")
    print(f"  Rows: {len(data)}")

    if data:
        print(f"  Columns: {', '.join(data[0].keys())}")

        # Show first few rows
        print(f"\nFirst {min(5, len(data))} rows:")
        for i, row in enumerate(data[:5], 1):
            print(f"  {i}. {row}")

    print()

    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='rf-bench measurement data management',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # search command
    parser_search = subparsers.add_parser('search', help='Search measurements')
    parser_search.add_argument('--name', help='Name pattern (regex)')
    parser_search.add_argument('--tags', help='Comma-separated tags (all must match)')
    parser_search.add_argument('--operator', help='Operator name')
    parser_search.add_argument('--after', help='Date after (YYYY-MM-DD)')
    parser_search.add_argument('--before', help='Date before (YYYY-MM-DD)')
    parser_search.add_argument('--sort', default='date', choices=['date', 'name', 'operator'],
                              help='Sort by (default: date)')

    # recent command
    parser_recent = subparsers.add_parser('recent', help='List recent measurements')
    parser_recent.add_argument('--days', type=int, default=7, help='Days to look back (default: 7)')
    parser_recent.add_argument('--limit', type=int, default=20, help='Max results to show (default: 20)')

    # stats command
    parser_stats = subparsers.add_parser('stats', help='Show summary statistics')

    # inspect command
    parser_inspect = subparsers.add_parser('inspect', help='Inspect measurement file')
    parser_inspect.add_argument('file', help='Path to CSV file')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Dispatch to command handler
    if args.command == 'search':
        return cmd_search(args)
    elif args.command == 'recent':
        return cmd_recent(args)
    elif args.command == 'stats':
        return cmd_stats(args)
    elif args.command == 'inspect':
        return cmd_inspect(args)
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
