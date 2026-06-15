"""
FX2LAFW Logic Analyzer Driver

Supports "24MHz 8CH" Saleae-compatible logic analyzers using fx2lafw firmware.
Uses libsigrok via subprocess for capture and protocol decode.

Hardware specs:
  - 8 digital channels
  - 24 MHz max sample rate
  - USB 2.0 (Cypress FX2)
  - Typically VID=08a9 PID=0014 (Saleae compatible)

Compatible with sigrok-cli and libsigrok.
"""

import subprocess
import tempfile
import struct
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import numpy as np


class FX2LAFWError(Exception):
    """Base exception for FX2LAFW driver errors."""
    pass


class FX2LAFWNotFoundError(FX2LAFWError):
    """Raised when no logic analyzer is found."""
    pass


class FX2LAFWCaptureError(FX2LAFWError):
    """Raised when capture fails."""
    pass


class FX2LAFWLogicAnalyzer:
    """
    Driver for FX2LAFW-based 8-channel logic analyzers.

    Uses sigrok-cli for capture and protocol decode.

    Example:
        la = FX2LAFWLogicAnalyzer()

        # Capture 1M samples at 24 MHz on channels 0-3
        samples = la.capture(
            channels=[0, 1, 2, 3],
            sample_rate=24e6,
            num_samples=1_000_000
        )

        # Decode SPI on channels 0-3 (CLK, MOSI, MISO, CS)
        decoded = la.decode_spi(
            samples,
            clk=0, mosi=1, miso=2, cs=3
        )

        # Save to VCD
        la.save_vcd('capture.vcd', samples)
    """

    # Supported sample rates (Hz)
    SAMPLE_RATES = [
        1e6, 2e6, 3e6, 4e6, 6e6, 8e6, 12e6, 16e6, 24e6
    ]

    def __init__(self, device: Optional[str] = None):
        """
        Initialize logic analyzer.

        Args:
            device: Optional device string (e.g., 'fx2lafw:conn=1.2').
                   If None, uses first detected fx2lafw device.

        Raises:
            FX2LAFWNotFoundError: If no device found
            FX2LAFWError: If sigrok-cli not installed
        """
        # Check for sigrok-cli
        if not self._check_sigrok():
            raise FX2LAFWError(
                "sigrok-cli not found. Install with: sudo apt-get install sigrok-cli"
            )

        # Find device if not specified
        if device is None:
            device = self._find_device()
            if device is None:
                raise FX2LAFWNotFoundError(
                    "No fx2lafw device found. Check USB connection."
                )

        self.device = device
        self._last_capture: Optional[Dict[str, np.ndarray]] = None

    def _check_sigrok(self) -> bool:
        """Check if sigrok-cli is installed."""
        try:
            result = subprocess.run(
                ['sigrok-cli', '--version'],
                capture_output=True,
                timeout=1.0
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _find_device(self) -> Optional[str]:
        """
        Find first fx2lafw device.

        Returns:
            Device string or None if not found.
        """
        try:
            result = subprocess.run(
                ['sigrok-cli', '--scan'],
                capture_output=True,
                text=True,
                timeout=5.0
            )

            # Parse output for fx2lafw device
            for line in result.stdout.splitlines():
                if 'fx2lafw' in line.lower():
                    # Extract device string
                    # Example: "fx2lafw - Saleae Logic with 8 channels"
                    return 'fx2lafw'

            return None

        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def capture(
        self,
        channels: List[int],
        sample_rate: float = 24e6,
        num_samples: Optional[int] = None,
        duration: Optional[float] = None
    ) -> Dict[int, np.ndarray]:
        """
        Capture logic analyzer data.

        Args:
            channels: List of channel numbers (0-7)
            sample_rate: Sample rate in Hz (default: 24 MHz)
            num_samples: Number of samples to capture
            duration: Duration in seconds (alternative to num_samples)

        Returns:
            Dict mapping channel number to numpy bool array

        Raises:
            FX2LAFWCaptureError: If capture fails

        Example:
            # Capture 1 second on channels 0-3
            samples = la.capture([0,1,2,3], sample_rate=8e6, duration=1.0)

            # samples[0] is a numpy array of bools for channel 0
        """
        if not channels:
            raise ValueError("Must specify at least one channel")

        for ch in channels:
            if ch < 0 or ch > 7:
                raise ValueError(f"Channel {ch} out of range (0-7)")

        # Validate sample rate
        if sample_rate not in self.SAMPLE_RATES:
            valid_rates_str = ', '.join(f'{int(r/1e6)} MHz' for r in self.SAMPLE_RATES)
            raise ValueError(
                f"Sample rate {sample_rate/1e6:.0f} MHz not supported. "
                f"Valid rates: {valid_rates_str}"
            )

        # Calculate capture parameters
        if num_samples is None and duration is None:
            raise ValueError("Must specify either num_samples or duration")

        if num_samples is not None and duration is not None:
            raise ValueError("Cannot specify both num_samples and duration")

        if duration is not None:
            num_samples = int(sample_rate * duration)

        # Build sigrok-cli command
        channel_str = ','.join(str(ch) for ch in channels)

        with tempfile.NamedTemporaryFile(mode='wb', suffix='.bin', delete=False) as f:
            output_file = f.name

        try:
            cmd = [
                'sigrok-cli',
                '--driver', self.device,
                '--config', f'samplerate={int(sample_rate)}',
                '--channels', channel_str,
                '--samples', str(num_samples),
                '--output-file', output_file,
                '--output-format', 'binary'
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(30, duration * 2 if duration else 30)
            )

            if result.returncode != 0:
                raise FX2LAFWCaptureError(
                    f"Capture failed: {result.stderr}"
                )

            # Read binary data
            with open(output_file, 'rb') as f:
                data = f.read()

            # Parse binary data (packed bits, 8 channels per byte)
            samples_dict = {}

            for ch in channels:
                # Extract bit for this channel from each byte
                channel_data = np.frombuffer(data, dtype=np.uint8)
                channel_bits = (channel_data >> ch) & 1
                samples_dict[ch] = channel_bits.astype(bool)

            self._last_capture = samples_dict
            return samples_dict

        finally:
            # Clean up temp file
            try:
                os.unlink(output_file)
            except:
                pass

    def decode_uart(
        self,
        samples: Dict[int, np.ndarray],
        channel: int,
        baud: int = 115200,
        data_bits: int = 8,
        parity: str = 'none',
        stop_bits: float = 1.0
    ) -> List[Dict[str, Union[int, str, float]]]:
        """
        Decode UART protocol.

        Args:
            samples: Sample dict from capture()
            channel: Channel number with UART data
            baud: Baud rate
            data_bits: Data bits (5-9)
            parity: Parity ('none', 'even', 'odd', 'mark', 'space')
            stop_bits: Stop bits (1.0, 1.5, 2.0)

        Returns:
            List of decoded frames, each a dict with keys:
                - 'byte': Received byte value (int)
                - 'char': ASCII character (if printable)
                - 'timestamp': Time in seconds

        Example:
            decoded = la.decode_uart(samples, channel=0, baud=115200)
            for frame in decoded:
                print(f"{frame['timestamp']:.6f}s: 0x{frame['byte']:02X} '{frame['char']}'")
        """
        # TODO: Implement UART decode using sigrok-cli protocol decoder
        # For now, return empty list
        raise NotImplementedError("UART decode not yet implemented")

    def decode_spi(
        self,
        samples: Dict[int, np.ndarray],
        clk: int,
        mosi: int,
        miso: int,
        cs: int,
        cpol: int = 0,
        cpha: int = 0,
        bit_order: str = 'msb-first'
    ) -> List[Dict[str, Union[int, str, float]]]:
        """
        Decode SPI protocol.

        Args:
            samples: Sample dict from capture()
            clk: Clock channel
            mosi: Master-out-slave-in channel
            miso: Master-in-slave-out channel
            cs: Chip select channel
            cpol: Clock polarity (0 or 1)
            cpha: Clock phase (0 or 1)
            bit_order: Bit order ('msb-first' or 'lsb-first')

        Returns:
            List of decoded transfers

        Example:
            decoded = la.decode_spi(samples, clk=0, mosi=1, miso=2, cs=3)
        """
        # TODO: Implement SPI decode
        raise NotImplementedError("SPI decode not yet implemented")

    def decode_i2c(
        self,
        samples: Dict[int, np.ndarray],
        scl: int,
        sda: int
    ) -> List[Dict[str, Union[int, str, float]]]:
        """
        Decode I2C protocol.

        Args:
            samples: Sample dict from capture()
            scl: Clock channel
            sda: Data channel

        Returns:
            List of decoded transfers (start, address, data, ack, stop)

        Example:
            decoded = la.decode_i2c(samples, scl=0, sda=1)
        """
        # TODO: Implement I2C decode
        raise NotImplementedError("I2C decode not yet implemented")

    def save_vcd(
        self,
        filename: str,
        samples: Dict[int, np.ndarray],
        sample_rate: float = 24e6
    ):
        """
        Save capture to VCD (Value Change Dump) format.

        VCD files can be opened in GTKWave, PulseView, etc.

        Args:
            filename: Output filename (.vcd extension)
            samples: Sample dict from capture()
            sample_rate: Sample rate used for capture

        Example:
            samples = la.capture([0,1,2,3], duration=1.0)
            la.save_vcd('capture.vcd', samples)
        """
        with open(filename, 'w') as f:
            # VCD header
            f.write("$date\n")
            f.write("  rf-bench fx2lafw capture\n")
            f.write("$end\n")
            f.write("$version\n")
            f.write("  rf_bench.fx2lafw 0.1.0\n")
            f.write("$end\n")
            f.write(f"$timescale\n")
            f.write(f"  {int(1e12/sample_rate)} ps\n")  # Convert to picoseconds
            f.write("$end\n")

            # Declare variables (channels)
            f.write("$scope module logic $end\n")
            for ch in sorted(samples.keys()):
                # Use ASCII characters as identifiers (!, ", #, etc.)
                var_id = chr(33 + ch)
                f.write(f"$var wire 1 {var_id} CH{ch} $end\n")
            f.write("$upscope $end\n")
            f.write("$enddefinitions $end\n")

            # Initial values
            f.write("#0\n")
            for ch in sorted(samples.keys()):
                var_id = chr(33 + ch)
                val = '1' if samples[ch][0] else '0'
                f.write(f"{val}{var_id}\n")

            # Value changes
            for i in range(1, len(next(iter(samples.values())))):
                timestamp = i
                changes = []

                for ch in sorted(samples.keys()):
                    if samples[ch][i] != samples[ch][i-1]:
                        var_id = chr(33 + ch)
                        val = '1' if samples[ch][i] else '0'
                        changes.append(f"{val}{var_id}")

                if changes:
                    f.write(f"#{timestamp}\n")
                    for change in changes:
                        f.write(f"{change}\n")

    def close(self):
        """Close connection (no-op for sigrok-cli based driver)."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
