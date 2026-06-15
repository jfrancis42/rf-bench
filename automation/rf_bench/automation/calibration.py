"""
Calibration Management System

Store and apply calibration data for instruments and accessories.

Use cases:
- Cable loss compensation (frequency-dependent)
- Antenna factor correction
- Instrument amplitude flatness
- Power meter linearity
- DMM accuracy correction

Example:
    from rf_bench.automation import CalibrationManager

    # Load calibration files
    cal = CalibrationManager()
    cal.load('cables/lmr400_10ft.yaml')
    cal.load('antennas/dipole_2m.yaml')

    # Apply correction
    cable_loss = cal.get('lmr400_10ft')
    measured_power_dbm = ssa.get_peak_power()
    corrected_power_dbm = cable_loss.apply(measured_power_dbm, freq_hz=146e6)

    # Or use as context manager
    with cal.apply('lmr400_10ft', freq_hz=146e6) as correction:
        measured = ssa.get_peak_power()
        corrected = correction(measured)
"""

import yaml
import csv
from pathlib import Path
from typing import Dict, List, Optional, Union, Callable
from dataclasses import dataclass
import numpy as np


@dataclass
class CalibrationPoint:
    """Single calibration data point."""
    frequency_hz: float
    correction: float  # dB, linear factor, or other unit
    units: str = "dB"


class Calibration:
    """
    Single calibration curve or correction factor.

    Supports:
    - Frequency-dependent corrections (cable loss, antenna factor)
    - Constant corrections (fixed offset)
    - Linear interpolation between points
    """

    def __init__(
        self,
        name: str,
        cal_type: str,
        data: List[CalibrationPoint],
        description: str = "",
        date: str = "",
        valid_until: str = "",
        interpolation: str = "linear"
    ):
        """
        Initialize calibration.

        Args:
            name: Unique calibration identifier
            cal_type: Type (cable_loss, antenna_factor, amplitude_cal, etc.)
            data: List of calibration points
            description: Human-readable description
            date: Calibration date (ISO format)
            valid_until: Expiration date (ISO format)
            interpolation: 'linear', 'cubic', or 'nearest'
        """
        self.name = name
        self.cal_type = cal_type
        self.data = sorted(data, key=lambda p: p.frequency_hz)
        self.description = description
        self.date = date
        self.valid_until = valid_until
        self.interpolation = interpolation

        # Build interpolator if frequency-dependent
        if len(self.data) > 1:
            self._freqs = np.array([p.frequency_hz for p in self.data])
            self._corrections = np.array([p.correction for p in self.data])
            self._interp_method = interpolation
        else:
            # Single point = constant correction
            self._freqs = None
            self._corrections = None
            self._interp_method = None

    def get_correction(self, freq_hz: float) -> float:
        """
        Get correction factor at specified frequency.

        Args:
            freq_hz: Frequency in Hz

        Returns:
            Correction value (units depend on cal_type)
        """
        if self._freqs is None:
            # Constant correction (single point)
            return self.data[0].correction

        # Use numpy.interp for linear interpolation
        if self._interp_method == 'linear':
            return float(np.interp(freq_hz, self._freqs, self._corrections))
        elif self._interp_method == 'nearest':
            # Find nearest frequency
            idx = np.argmin(np.abs(self._freqs - freq_hz))
            return float(self._corrections[idx])
        elif self._interp_method == 'cubic':
            # Use numpy polyfit for cubic interpolation
            # For small datasets, use linear instead
            if len(self._freqs) < 4:
                return float(np.interp(freq_hz, self._freqs, self._corrections))

            # Fit cubic polynomial
            coeffs = np.polyfit(self._freqs, self._corrections, min(3, len(self._freqs) - 1))
            poly = np.poly1d(coeffs)
            return float(poly(freq_hz))
        else:
            raise ValueError(f"Unknown interpolation: {self._interp_method}")

    def apply(self, value: float, freq_hz: float, inverse: bool = False) -> float:
        """
        Apply correction to a measured value.

        For cable loss and similar corrections in dB:
        - Forward (inverse=False): corrected = measured + correction
        - Inverse (inverse=True): corrected = measured - correction

        Args:
            value: Measured value
            freq_hz: Frequency in Hz
            inverse: If True, apply correction in reverse

        Returns:
            Corrected value
        """
        correction = self.get_correction(freq_hz)

        if inverse:
            return value - correction
        else:
            return value + correction

    def apply_batch(
        self,
        values: List[float],
        freqs_hz: List[float],
        inverse: bool = False
    ) -> List[float]:
        """
        Apply correction to multiple values at different frequencies.

        Args:
            values: List of measured values
            freqs_hz: Corresponding frequencies in Hz
            inverse: If True, apply correction in reverse

        Returns:
            List of corrected values
        """
        return [
            self.apply(v, f, inverse=inverse)
            for v, f in zip(values, freqs_hz)
        ]

    def __call__(self, value: float, freq_hz: float, inverse: bool = False) -> float:
        """Allow calibration to be called as a function."""
        return self.apply(value, freq_hz, inverse=inverse)

    def __repr__(self):
        return f"Calibration(name='{self.name}', type='{self.cal_type}', points={len(self.data)})"


class CalibrationManager:
    """
    Manages calibration data files and applies corrections.

    Calibrations are stored in ~/.rf-bench/calibrations/ by default.
    """

    def __init__(self, cal_dir: Optional[Union[str, Path]] = None):
        """
        Initialize calibration manager.

        Args:
            cal_dir: Directory containing calibration files
                     (default: ~/.rf-bench/calibrations/)
        """
        if cal_dir is None:
            self.cal_dir = Path.home() / '.rf-bench' / 'calibrations'
        else:
            self.cal_dir = Path(cal_dir).expanduser()

        self.cal_dir.mkdir(parents=True, exist_ok=True)

        self._calibrations: Dict[str, Calibration] = {}

    def load(self, path: Union[str, Path]) -> Calibration:
        """
        Load calibration from file.

        Supports YAML (.yaml, .yml) and CSV (.csv) formats.

        Args:
            path: Path to calibration file (relative to cal_dir or absolute)

        Returns:
            Loaded Calibration object
        """
        path = Path(path).expanduser()

        # Try relative to cal_dir first
        if not path.is_absolute():
            full_path = self.cal_dir / path
            if full_path.exists():
                path = full_path

        if not path.exists():
            raise FileNotFoundError(f"Calibration file not found: {path}")

        # Load based on file extension
        if path.suffix in ['.yaml', '.yml']:
            cal = self._load_yaml(path)
        elif path.suffix == '.csv':
            cal = self._load_csv(path)
        else:
            raise ValueError(f"Unknown calibration format: {path.suffix}")

        # Store in registry
        self._calibrations[cal.name] = cal

        return cal

    def _load_yaml(self, path: Path) -> Calibration:
        """Load calibration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        # Parse calibration points
        points = []
        for item in data['data']:
            # Handle various frequency units
            if 'freq_hz' in item:
                freq_hz = item['freq_hz']
            elif 'freq_mhz' in item:
                freq_hz = item['freq_mhz'] * 1e6
            elif 'freq_ghz' in item:
                freq_hz = item['freq_ghz'] * 1e9
            elif 'freq_khz' in item:
                freq_hz = item['freq_khz'] * 1e3
            else:
                raise ValueError(f"No frequency field in data point: {item}")

            # Get correction value (field name depends on type)
            correction_fields = ['correction', 'loss_db', 'factor_db', 'offset_db', 'value']
            correction = None
            for field in correction_fields:
                if field in item:
                    correction = item[field]
                    break

            if correction is None:
                raise ValueError(f"No correction field in data point: {item}")

            units = item.get('units', 'dB')

            points.append(CalibrationPoint(
                frequency_hz=freq_hz,
                correction=correction,
                units=units
            ))

        return Calibration(
            name=data['name'],
            cal_type=data.get('type', 'unknown'),
            data=points,
            description=data.get('description', ''),
            date=data.get('date', ''),
            valid_until=data.get('valid_until', ''),
            interpolation=data.get('interpolation', 'linear')
        )

    def _load_csv(self, path: Path) -> Calibration:
        """Load calibration from CSV file."""
        # Read metadata from comments
        metadata = {}
        with open(path) as f:
            for line in f:
                if not line.startswith('#'):
                    break
                if ':' in line:
                    key, value = line[1:].split(':', 1)
                    metadata[key.strip()] = value.strip()

        # Read data
        points = []
        with open(path) as f:
            reader = csv.DictReader(f, delimiter=',')
            for row in reader:
                # Parse frequency
                if 'freq_hz' in row:
                    freq_hz = float(row['freq_hz'])
                elif 'freq_mhz' in row:
                    freq_hz = float(row['freq_mhz']) * 1e6
                elif 'frequency_hz' in row:
                    freq_hz = float(row['frequency_hz'])
                else:
                    raise ValueError(f"No frequency column in CSV: {list(row.keys())}")

                # Parse correction
                if 'correction' in row:
                    correction = float(row['correction'])
                elif 'loss_db' in row:
                    correction = float(row['loss_db'])
                elif 'value' in row:
                    correction = float(row['value'])
                else:
                    raise ValueError(f"No correction column in CSV: {list(row.keys())}")

                units = row.get('units', metadata.get('units', 'dB'))

                points.append(CalibrationPoint(
                    frequency_hz=freq_hz,
                    correction=correction,
                    units=units
                ))

        return Calibration(
            name=metadata.get('name', path.stem),
            cal_type=metadata.get('type', 'unknown'),
            data=points,
            description=metadata.get('description', ''),
            date=metadata.get('date', ''),
            valid_until=metadata.get('valid_until', ''),
            interpolation=metadata.get('interpolation', 'linear')
        )

    def get(self, name: str) -> Calibration:
        """
        Get loaded calibration by name.

        Args:
            name: Calibration name

        Returns:
            Calibration object

        Raises:
            KeyError: If calibration not loaded
        """
        if name not in self._calibrations:
            raise KeyError(f"Calibration '{name}' not loaded. Use load() first.")

        return self._calibrations[name]

    def list(self) -> List[str]:
        """List all loaded calibrations."""
        return list(self._calibrations.keys())

    def available(self) -> List[Path]:
        """List all calibration files in cal_dir."""
        yaml_files = list(self.cal_dir.glob('*.yaml')) + list(self.cal_dir.glob('*.yml'))
        csv_files = list(self.cal_dir.glob('*.csv'))
        return sorted(yaml_files + csv_files)

    def save(self, calibration: Calibration, path: Optional[Union[str, Path]] = None):
        """
        Save calibration to file.

        Args:
            calibration: Calibration to save
            path: Output path (default: cal_dir/<name>.yaml)
        """
        if path is None:
            path = self.cal_dir / f"{calibration.name}.yaml"
        else:
            path = Path(path).expanduser()

        # Build YAML structure
        data = {
            'name': calibration.name,
            'type': calibration.cal_type,
            'description': calibration.description,
            'date': calibration.date,
            'valid_until': calibration.valid_until,
            'interpolation': calibration.interpolation,
            'data': []
        }

        for point in calibration.data:
            data['data'].append({
                'freq_mhz': point.frequency_hz / 1e6,
                'correction': point.correction,
                'units': point.units
            })

        # Write YAML
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        print(f"✓ Calibration saved: {path}")

    def create_cable_loss(
        self,
        name: str,
        frequencies_hz: List[float],
        losses_db: List[float],
        description: str = "",
        date: str = ""
    ) -> Calibration:
        """
        Create cable loss calibration.

        Args:
            name: Cable identifier (e.g., 'lmr400_10ft')
            frequencies_hz: List of frequencies
            losses_db: Corresponding losses in dB
            description: Cable description
            date: Calibration date

        Returns:
            Calibration object
        """
        points = [
            CalibrationPoint(freq, loss, 'dB')
            for freq, loss in zip(frequencies_hz, losses_db)
        ]

        cal = Calibration(
            name=name,
            cal_type='cable_loss',
            data=points,
            description=description,
            date=date
        )

        self._calibrations[name] = cal
        return cal

    def create_antenna_factor(
        self,
        name: str,
        frequencies_hz: List[float],
        factors_db: List[float],
        description: str = "",
        date: str = ""
    ) -> Calibration:
        """
        Create antenna factor calibration.

        Antenna factor converts dBμV/m to dBm.

        Args:
            name: Antenna identifier
            frequencies_hz: List of frequencies
            factors_db: Corresponding antenna factors in dB(1/m)
            description: Antenna description
            date: Calibration date

        Returns:
            Calibration object
        """
        points = [
            CalibrationPoint(freq, factor, 'dB(1/m)')
            for freq, factor in zip(frequencies_hz, factors_db)
        ]

        cal = Calibration(
            name=name,
            cal_type='antenna_factor',
            data=points,
            description=description,
            date=date
        )

        self._calibrations[name] = cal
        return cal


def apply_cable_loss_correction(
    power_dbm: float,
    freq_hz: float,
    cable_cal: Calibration
) -> float:
    """
    Apply cable loss correction to measured power.

    Args:
        power_dbm: Measured power at instrument input (dBm)
        freq_hz: Measurement frequency (Hz)
        cable_cal: Cable loss calibration

    Returns:
        Corrected power at cable input (dBm)
    """
    loss_db = cable_cal.get_correction(freq_hz)
    return power_dbm + loss_db  # Add loss to compensate


def apply_antenna_factor(
    field_strength_dbuv_m: float,
    freq_hz: float,
    antenna_cal: Calibration
) -> float:
    """
    Convert field strength to received power using antenna factor.

    Args:
        field_strength_dbuv_m: Field strength in dBμV/m
        freq_hz: Frequency (Hz)
        antenna_cal: Antenna factor calibration

    Returns:
        Received power in dBm
    """
    antenna_factor_db = antenna_cal.get_correction(freq_hz)

    # Formula: P(dBm) = E(dBμV/m) - AF(dB/m) - 90 dB
    # (90 dB accounts for unit conversion μV → mW and m² → antenna aperture)
    power_dbm = field_strength_dbuv_m - antenna_factor_db - 90.0

    return power_dbm
