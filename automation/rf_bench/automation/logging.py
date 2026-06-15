"""
logging.py — Structured measurement data logging

Provides consistent data storage with metadata for traceability.
Supports CSV (simple) and HDF5 (multi-dimensional) formats.
"""

import csv
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import warnings


class MeasurementLog:
    """
    Structured measurement data logger with automatic metadata.

    Stores measurement results with contextual metadata (operator, conditions,
    instrument configuration) for traceability and reproducibility.

    Example::

        from rf_bench.automation import MeasurementLog

        log = MeasurementLog('amplifier_test')
        log.metadata(
            operator='N0GQ',
            dut='Amplifier XYZ',
            temperature_c=23.5,
            tags=['gain', 'amplifier', 'production']
        )

        # Log measurement points
        for freq in frequencies:
            result = measure_gain(freq)
            log.append({
                'freq_hz': freq,
                'input_dbm': -20,
                'output_dbm': result,
                'gain_db': result - (-20)
            })

        # Save to ~/.rf-bench/data/
        log.save()
    """

    def __init__(self, name: str, data_dir: Optional[Path] = None):
        """
        Initialize measurement log.

        Args:
            name: Name of this measurement (used in filename)
            data_dir: Directory to save data (default: ~/.rf-bench/data/)
        """
        self.name = name
        self.data_dir = data_dir or Path.home() / '.rf-bench' / 'data'
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._metadata = {
            'name': name,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'version': '1.0',
        }
        self._data = []
        self._columns = None

    def metadata(self, **kwargs):
        """
        Add metadata fields.

        Args:
            **kwargs: Arbitrary metadata key-value pairs

        Example::

            log.metadata(
                operator='N0GQ',
                dut='Device Under Test',
                temperature_c=23.5,
                tags=['production', 'qa']
            )
        """
        self._metadata.update(kwargs)

    def append(self, data_point: Dict[str, Any]):
        """
        Append a measurement data point.

        Args:
            data_point: Dictionary of measurement values

        Example::

            log.append({
                'freq_hz': 1e9,
                'power_dbm': -20.5,
                'vswr': 1.5
            })
        """
        # Track columns from first data point
        if self._columns is None:
            self._columns = list(data_point.keys())
        elif set(data_point.keys()) != set(self._columns):
            warnings.warn(
                f"Data point keys {set(data_point.keys())} don't match "
                f"expected columns {set(self._columns)}. Missing keys will be None."
            )

        self._data.append(data_point)

    def extend(self, data_points: List[Dict[str, Any]]):
        """
        Append multiple measurement data points.

        Args:
            data_points: List of dictionaries
        """
        for point in data_points:
            self.append(point)

    def save(self, filename: Optional[str] = None, format: str = 'csv') -> Path:
        """
        Save measurement data to file.

        Args:
            filename: Output filename (default: auto-generated from name + timestamp)
            format: 'csv' or 'hdf5' (default: csv)

        Returns:
            Path to saved file

        Example::

            path = log.save()
            print(f"Saved to {path}")
        """
        if not self._data:
            raise ValueError("No data to save. Call append() first.")

        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{self.name}_{timestamp}.{format}"

        output_path = self.data_dir / filename

        if format == 'csv':
            self._save_csv(output_path)
        elif format == 'hdf5':
            self._save_hdf5(output_path)
        else:
            raise ValueError(f"Unknown format: {format}. Use 'csv' or 'hdf5'.")

        return output_path

    def _save_csv(self, path: Path):
        """Save as CSV with YAML header."""
        with open(path, 'w', newline='') as f:
            # Write metadata as YAML-style comments
            f.write("# Measurement Data\n")
            for key, value in self._metadata.items():
                if isinstance(value, list):
                    f.write(f"# {key}: {json.dumps(value)}\n")
                else:
                    f.write(f"# {key}: {value}\n")
            f.write("#\n")

            # Write CSV data
            writer = csv.DictWriter(f, fieldnames=self._columns)
            writer.writeheader()
            writer.writerows(self._data)

        print(f"Saved {len(self._data)} data points to {path}")

    def _save_hdf5(self, path: Path):
        """Save as HDF5 (requires h5py)."""
        try:
            import h5py
            import numpy as np
        except ImportError:
            raise ImportError(
                "HDF5 format requires h5py. Install with: pip install h5py"
            )

        with h5py.File(path, 'w') as f:
            # Store metadata as attributes
            for key, value in self._metadata.items():
                if isinstance(value, (list, dict)):
                    f.attrs[key] = json.dumps(value)
                else:
                    f.attrs[key] = value

            # Store data as datasets
            data_group = f.create_group('data')
            for col in self._columns:
                values = [point.get(col) for point in self._data]
                data_group.create_dataset(col, data=np.array(values))

        print(f"Saved {len(self._data)} data points to {path}")

    def __len__(self):
        """Return number of data points."""
        return len(self._data)

    def __repr__(self):
        return f"MeasurementLog('{self.name}', {len(self._data)} points)"


def load_csv(path: Path) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Load a CSV file saved by MeasurementLog.

    Returns:
        (metadata, data_points) tuple

    Example::

        from rf_bench.automation.logging import load_csv

        metadata, data = load_csv('amplifier_test_20260615_143022.csv')
        print(f"Operator: {metadata['operator']}")
        print(f"Points: {len(data)}")
    """
    metadata = {}
    data = []

    with open(path, 'r') as f:
        # Read metadata from comments
        for line in f:
            if line.startswith('#'):
                if ':' in line:
                    key, value = line[1:].split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    # Try to parse JSON arrays
                    if value.startswith('['):
                        try:
                            value = json.loads(value)
                        except json.JSONDecodeError:
                            pass
                    metadata[key] = value
            else:
                # Found data, rewind to start of CSV
                f.seek(0)
                # Skip comment lines
                for line in f:
                    if not line.startswith('#'):
                        break
                # Now at header row
                reader = csv.DictReader(f)
                data = list(reader)
                break

    return metadata, data
