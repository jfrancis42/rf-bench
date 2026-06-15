"""
search.py — Measurement data search and query

Provides search/query API for finding measurements by:
  - Date range
  - Tags
  - Operator
  - DUT name
  - Metadata fields
"""

import os
import re
import yaml
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable


def search_measurements(
    data_dir: Optional[str] = None,
    name_pattern: Optional[str] = None,
    tags: Optional[List[str]] = None,
    operator: Optional[str] = None,
    date_after: Optional[str] = None,
    date_before: Optional[str] = None,
    metadata_filter: Optional[Dict[str, Any]] = None,
    sort_by: str = 'date',
    reverse: bool = True
) -> List[Dict[str, Any]]:
    """
    Search for measurements matching criteria.

    Args:
        data_dir: Directory to search (default: ~/.rf-bench/data/)
        name_pattern: Regex pattern for measurement name
        tags: List of tags (all must match)
        operator: Operator name
        date_after: ISO date string (YYYY-MM-DD)
        date_before: ISO date string (YYYY-MM-DD)
        metadata_filter: Dict of metadata key:value pairs to match
        sort_by: Sort field ('date', 'name', 'operator')
        reverse: Sort descending (newest first) if True

    Returns:
        List of dicts with keys:
            - path: Path to data file
            - name: Measurement name
            - timestamp: ISO timestamp
            - metadata: Full metadata dict
            - tags: List of tags
            - operator: Operator name
            - size_bytes: File size

    Example:

        # Find all amplifier tests from last month
        results = search_measurements(
            tags=['amplifier'],
            date_after='2026-05-15'
        )

        # Find measurements by specific operator
        results = search_measurements(
            operator='N0GQ',
            date_after='2026-06-01',
            date_before='2026-06-15'
        )

        # Find by DUT name
        results = search_measurements(
            metadata_filter={'dut': 'Amplifier XYZ'}
        )
    """
    if data_dir is None:
        data_dir = Path.home() / '.rf-bench' / 'data'
    else:
        data_dir = Path(data_dir)

    if not data_dir.exists():
        return []

    # Parse date filters
    date_after_dt = None
    date_before_dt = None

    if date_after:
        date_after_dt = datetime.fromisoformat(date_after)

    if date_before:
        date_before_dt = datetime.fromisoformat(date_before)

    # Compile name pattern
    name_re = None
    if name_pattern:
        name_re = re.compile(name_pattern, re.IGNORECASE)

    # Scan all CSV files
    results = []

    for csv_file in data_dir.glob('*.csv'):
        # Load metadata from CSV header
        metadata = _load_metadata(csv_file)

        if not metadata:
            continue

        # Apply filters
        if name_re and not name_re.search(metadata.get('name', '')):
            continue

        if operator and metadata.get('operator') != operator:
            continue

        if tags:
            file_tags = metadata.get('tags', [])
            if isinstance(file_tags, str):
                file_tags = [t.strip() for t in file_tags.split(',')]
            if not all(tag in file_tags for tag in tags):
                continue

        if metadata_filter:
            match = True
            for key, value in metadata_filter.items():
                if metadata.get(key) != value:
                    match = False
                    break
            if not match:
                continue

        # Parse timestamp
        timestamp_str = metadata.get('timestamp', '')
        timestamp_dt = None

        if timestamp_str:
            try:
                # Handle various timestamp formats
                for fmt in ['%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']:
                    try:
                        timestamp_dt = datetime.strptime(timestamp_str, fmt)
                        break
                    except ValueError:
                        continue
            except:
                pass

        # Date range filter
        if timestamp_dt:
            if date_after_dt and timestamp_dt < date_after_dt:
                continue
            if date_before_dt and timestamp_dt > date_before_dt:
                continue

        # Build result entry
        results.append({
            'path': str(csv_file),
            'name': metadata.get('name', 'Unknown'),
            'timestamp': timestamp_str,
            'metadata': metadata,
            'tags': metadata.get('tags', []),
            'operator': metadata.get('operator', 'Unknown'),
            'size_bytes': csv_file.stat().st_size
        })

    # Sort results
    if sort_by == 'date':
        results.sort(key=lambda x: x['timestamp'], reverse=reverse)
    elif sort_by == 'name':
        results.sort(key=lambda x: x['name'].lower(), reverse=reverse)
    elif sort_by == 'operator':
        results.sort(key=lambda x: x['operator'].lower(), reverse=reverse)

    return results


def _load_metadata(csv_file: Path) -> Dict[str, Any]:
    """
    Load metadata from CSV header comments.

    CSV files have YAML-style metadata in # comments at the top.

    Example:
        # Measurement Data
        # name: Amplifier Gain
        # timestamp: 2026-06-15T14:30:22Z
        # operator: N0GQ
        # tags: amplifier, gain
    """
    metadata = {}

    try:
        with open(csv_file, 'r') as f:
            for line in f:
                line = line.strip()

                # Stop at first non-comment line
                if not line.startswith('#'):
                    break

                # Skip header line
                if 'Measurement Data' in line:
                    continue

                # Parse key: value
                if ':' in line:
                    line = line.lstrip('#').strip()
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()

                    # Parse common types
                    if key == 'tags':
                        # Try to parse as JSON array first
                        if value.startswith('[') and value.endswith(']'):
                            try:
                                import json
                                value = json.loads(value)
                            except:
                                # Fall back to comma-separated
                                value = [t.strip() for t in value.split(',')]
                        elif ',' in value:
                            value = [t.strip() for t in value.split(',')]
                    elif value.lower() in ('true', 'false'):
                        value = value.lower() == 'true'
                    elif value.replace('.', '').replace('-', '').isdigit():
                        try:
                            value = float(value) if '.' in value else int(value)
                        except:
                            pass

                    metadata[key] = value

    except (IOError, OSError):
        return {}

    return metadata


def recent_measurements(
    days: int = 7,
    data_dir: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get measurements from last N days.

    Args:
        days: Number of days to look back
        data_dir: Directory to search

    Returns:
        List of measurement dicts, newest first

    Example:

        # Get last week's measurements
        recent = recent_measurements(days=7)

        for m in recent:
            print(f"{m['timestamp']}: {m['name']}")
    """
    date_after = (datetime.now() - timedelta(days=days)).date().isoformat()

    return search_measurements(
        data_dir=data_dir,
        date_after=date_after,
        sort_by='date',
        reverse=True
    )


def find_by_tag(
    tag: str,
    data_dir: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Find all measurements with a specific tag.

    Args:
        tag: Tag to search for
        data_dir: Directory to search

    Returns:
        List of measurement dicts, newest first

    Example:

        amplifier_tests = find_by_tag('amplifier')
    """
    return search_measurements(
        data_dir=data_dir,
        tags=[tag],
        sort_by='date',
        reverse=True
    )


def find_by_operator(
    operator: str,
    data_dir: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Find all measurements by a specific operator.

    Args:
        operator: Operator name
        data_dir: Directory to search

    Returns:
        List of measurement dicts, newest first

    Example:

        my_tests = find_by_operator('N0GQ')
    """
    return search_measurements(
        data_dir=data_dir,
        operator=operator,
        sort_by='date',
        reverse=True
    )


def summary_stats(
    data_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get summary statistics about all measurements.

    Args:
        data_dir: Directory to scan

    Returns:
        Dict with keys:
            - total_count: Total number of measurements
            - total_size_mb: Total size in MB
            - oldest_date: Oldest measurement date
            - newest_date: Newest measurement date
            - operators: List of unique operators
            - tags: List of unique tags
            - by_tag: Count of measurements per tag

    Example:

        stats = summary_stats()
        print(f"Total measurements: {stats['total_count']}")
        print(f"Tags: {', '.join(stats['tags'])}")
    """
    if data_dir is None:
        data_dir = Path.home() / '.rf-bench' / 'data'
    else:
        data_dir = Path(data_dir)

    if not data_dir.exists():
        return {
            'total_count': 0,
            'total_size_mb': 0,
            'oldest_date': None,
            'newest_date': None,
            'operators': [],
            'tags': [],
            'by_tag': {}
        }

    all_measurements = search_measurements(data_dir=str(data_dir))

    if not all_measurements:
        return {
            'total_count': 0,
            'total_size_mb': 0,
            'oldest_date': None,
            'newest_date': None,
            'operators': [],
            'tags': [],
            'by_tag': {}
        }

    # Gather stats
    total_size = sum(m['size_bytes'] for m in all_measurements)
    operators = set()
    all_tags = set()
    tag_counts = {}

    for m in all_measurements:
        if m['operator']:
            operators.add(m['operator'])

        tags = m['tags']
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(',')]

        for tag in tags:
            if tag:
                all_tags.add(tag)
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Sort by date
    sorted_by_date = sorted(all_measurements, key=lambda x: x['timestamp'])

    return {
        'total_count': len(all_measurements),
        'total_size_mb': total_size / (1024 * 1024),
        'oldest_date': sorted_by_date[0]['timestamp'] if sorted_by_date else None,
        'newest_date': sorted_by_date[-1]['timestamp'] if sorted_by_date else None,
        'operators': sorted(list(operators)),
        'tags': sorted(list(all_tags)),
        'by_tag': tag_counts
    }
