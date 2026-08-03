"""
geiger.py — MightyOhm Geiger Counter driver

MightyOhm Geiger Counter kit with FTDI USB serial interface.
Supports various GM tubes (SBM-20, LND-712, etc.).

The device outputs CSV data once per second:
    CPS, #####, CPM, #####, uSv/hr, ###.##, SLOW|FAST|INST

Usage::

    from rf_bench.mightyohm import MightyOhmGeiger

    with MightyOhmGeiger() as geiger:         # auto-detect FTDI
        reading = geiger.read()
        print(f"CPM: {reading['cpm']}, Dose: {reading['dose_usv_hr']:.2f} µSv/hr")

        # Streaming mode with callback
        def handle_reading(reading):
            print(f"{reading['cpm']} CPM")

        geiger.stream(callback=handle_reading, duration=60)

    geiger = MightyOhmGeiger("/dev/ttyUSB1")  # explicit port
"""

import re
import time
import serial
import serial.tools.list_ports
from typing import Optional, Callable, Dict, Any


class MightyOhmGeigerError(Exception):
    pass


class MightyOhmGeiger:
    """MightyOhm Geiger Counter driver.

    Read-only monitoring of radiation levels via USB serial interface.
    The device outputs CSV data once per second.
    """

    # Tube conversion factors (CPM to µSv/hr, scaled by 10000)
    # From MightyOhm firmware and community data
    TUBE_FACTORS = {
        'SBM-20': 57,        # Default in firmware (Russian tube)
        'LND-712': 108,      # Popular US alpha/beta/gamma tube
        'SI-29BG': 57,       # Similar to SBM-20
        'J305': 153,         # Chinese beta/gamma tube
        'SI-22G': 57,        # Russian beta/gamma tube
    }

    def __init__(self, port: Optional[str] = None,
                 baudrate: int = 9600,
                 timeout: float = 5.0,
                 tube_type: str = 'SBM-20'):
        """Initialize MightyOhm Geiger Counter.

        Args:
            port: Serial port path. If None, auto-detects FTDI.
            baudrate: Serial baud rate (default 9600)
            timeout: Serial read timeout in seconds (default 5.0)
            tube_type: GM tube type for conversion factor (default 'SBM-20')
                      Options: SBM-20, LND-712, SI-29BG, J305, SI-22G
        """
        if port is None:
            port = self._find_port()

        if tube_type not in self.TUBE_FACTORS:
            raise MightyOhmGeigerError(
                f"Unknown tube type: {tube_type}. "
                f"Valid types: {', '.join(self.TUBE_FACTORS.keys())}"
            )

        self.port = port
        self.tube_type = tube_type
        self.conversion_factor = self.TUBE_FACTORS[tube_type]

        try:
            self._serial = serial.Serial(
                port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout
            )
            # Clear any buffered data
            self._serial.reset_input_buffer()
        except Exception as e:
            raise MightyOhmGeigerError(f"Failed to open {port}: {e}")

    @staticmethod
    def _find_port() -> str:
        """Return the first FTDI serial port found."""
        for p in serial.tools.list_ports.comports():
            vid_pid = f"{p.vid:04x}:{p.pid:04x}" if p.vid and p.pid else ""
            # FTDI FT232R VID:PID
            if vid_pid == "0403:6001" or "FTDI" in (p.manufacturer or ""):
                return p.device
        raise MightyOhmGeigerError(
            "No MightyOhm Geiger Counter found (no FTDI adapter detected). "
            "Pass port= explicitly, e.g. MightyOhmGeiger('/dev/ttyUSB1')."
        )

    @classmethod
    def find_device(cls) -> Optional['MightyOhmGeiger']:
        """Return a MightyOhmGeiger connected to the first detected device, or None."""
        try:
            return cls()
        except MightyOhmGeigerError:
            return None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        """Close serial connection."""
        if hasattr(self, '_serial') and self._serial.is_open:
            self._serial.close()

    def __repr__(self):
        return f"MightyOhmGeiger(port={self.port!r}, tube_type={self.tube_type!r})"

    def _parse_line(self, line: str) -> Dict[str, Any]:
        """Parse a CSV line from the Geiger counter.

        Format: CPS, #####, CPM, #####, uSv/hr, ###.##, SLOW|FAST|INST

        Args:
            line: CSV line string

        Returns:
            Dict with keys: cps, cpm, dose_usv_hr, mode, raw

        Raises:
            MightyOhmGeigerError: If line cannot be parsed
        """
        line = line.strip()
        # Filter out null bytes and other garbage
        line = ''.join(c for c in line if c.isprintable() or c.isspace())
        line = line.strip()

        if not line:
            raise MightyOhmGeigerError("Empty line received")

        # Parse CSV format
        # Expected: CPS, #####, CPM, #####, uSv/hr, ###.##, SLOW|FAST|INST
        pattern = r'CPS,\s*(\d+),\s*CPM,\s*(\d+),\s*uSv/hr,\s*([\d.]+),\s*(SLOW|FAST|INST)'
        match = re.match(pattern, line)

        if not match:
            raise MightyOhmGeigerError(f"Invalid data format: {line!r}")

        cps = int(match.group(1))
        cpm = int(match.group(2))
        dose = float(match.group(3))
        mode = match.group(4)

        return {
            'cps': cps,
            'cpm': cpm,
            'dose_usv_hr': dose,
            'mode': mode,
            'raw': line,
            'timestamp': time.time()
        }

    def read(self) -> Dict[str, Any]:
        """Read one measurement from the Geiger counter.

        Blocks until a complete line is received (up to 1 second typically).

        Returns:
            Dict with keys:
                - cps: Counts per second (int)
                - cpm: Counts per minute (int)
                - dose_usv_hr: Dose in microsieverts per hour (float)
                - mode: Averaging mode - 'SLOW' (60s), 'FAST' (5s), or 'INST' (instant)
                - raw: Original CSV string
                - timestamp: Unix timestamp (float)

        Raises:
            MightyOhmGeigerError: On timeout or parse error
        """
        # Retry on parse errors (common at startup with buffer garbage)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                line = self._serial.readline().decode('ascii', errors='ignore')
                if not line:
                    raise MightyOhmGeigerError("Timeout waiting for data")
                return self._parse_line(line)
            except MightyOhmGeigerError as e:
                if attempt == max_retries - 1:
                    raise
                # Retry on parse errors (likely garbage in buffer)
                continue
            except serial.SerialException as e:
                raise MightyOhmGeigerError(f"Serial read error: {e}")

    def stream(self,
               callback: Optional[Callable[[Dict[str, Any]], None]] = None,
               duration: Optional[float] = None,
               count: Optional[int] = None) -> list:
        """Stream readings from the Geiger counter.

        Args:
            callback: Optional function to call for each reading.
                     Signature: callback(reading: Dict)
            duration: Optional time limit in seconds
            count: Optional maximum number of readings

        Returns:
            List of all readings collected (empty if callback is provided and consumes them)

        Raises:
            MightyOhmGeigerError: On read errors

        Examples:
            # Collect 10 readings
            readings = geiger.stream(count=10)

            # Stream for 60 seconds with callback
            def print_reading(r):
                print(f"{r['cpm']} CPM")
            geiger.stream(callback=print_reading, duration=60)
        """
        readings = []
        start_time = time.time()
        reading_count = 0

        try:
            while True:
                # Check termination conditions
                if duration and (time.time() - start_time) >= duration:
                    break
                if count and reading_count >= count:
                    break

                # Read one measurement
                reading = self.read()
                reading_count += 1

                if callback:
                    callback(reading)
                else:
                    readings.append(reading)

        except KeyboardInterrupt:
            pass  # Allow clean exit on Ctrl+C

        return readings

    @property
    def cps(self) -> int:
        """Current counts per second."""
        return self.read()['cps']

    @property
    def cpm(self) -> int:
        """Current counts per minute (averaged)."""
        return self.read()['cpm']

    @property
    def dose_usv_hr(self) -> float:
        """Current dose rate in microsieverts per hour."""
        return self.read()['dose_usv_hr']

    @property
    def mode(self) -> str:
        """Current averaging mode: SLOW, FAST, or INST."""
        return self.read()['mode']

    def get_statistics(self, duration: float = 60.0) -> Dict[str, Any]:
        """Collect statistics over a time period.

        Args:
            duration: Collection period in seconds (default 60)

        Returns:
            Dict with min, max, mean, and std for cps, cpm, dose_usv_hr
        """
        readings = self.stream(duration=duration)

        if not readings:
            raise MightyOhmGeigerError("No readings collected")

        import statistics

        cps_values = [r['cps'] for r in readings]
        cpm_values = [r['cpm'] for r in readings]
        dose_values = [r['dose_usv_hr'] for r in readings]

        return {
            'duration': duration,
            'count': len(readings),
            'cps': {
                'min': min(cps_values),
                'max': max(cps_values),
                'mean': statistics.mean(cps_values),
                'stdev': statistics.stdev(cps_values) if len(cps_values) > 1 else 0
            },
            'cpm': {
                'min': min(cpm_values),
                'max': max(cpm_values),
                'mean': statistics.mean(cpm_values),
                'stdev': statistics.stdev(cpm_values) if len(cpm_values) > 1 else 0
            },
            'dose_usv_hr': {
                'min': min(dose_values),
                'max': max(dose_values),
                'mean': statistics.mean(dose_values),
                'stdev': statistics.stdev(dose_values) if len(dose_values) > 1 else 0
            }
        }
