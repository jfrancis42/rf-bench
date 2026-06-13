#!/usr/bin/env python3
"""
Automated satellite pass recorder combining scpi-rotator + scpi-gps + IC-9700.

Predicts satellite passes, tracks antenna position, applies Doppler correction,
and records audio for the duration of the pass.
"""

import argparse
import sys
import time
import socket
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import requests
import numpy as np
from skyfield.api import load, wgs84, EarthSatellite
from skyfield.toposlib import GeographicPosition
import sounddevice as sd
import soundfile as sf


SPEED_OF_LIGHT = 299792458.0  # m/s


class SCPIDevice:
    """Generic SCPI command/query over TCP."""
    def __init__(self, host, port=5025, timeout=5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self._connect()

    def _connect(self):
        """Open TCP connection."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))

    def write(self, cmd):
        """Send SCPI command."""
        self.sock.sendall((cmd + '\n').encode('ascii'))

    def query(self, cmd):
        """Send SCPI query, return response."""
        self.write(cmd)
        resp = self.sock.recv(4096).decode('ascii').strip()
        return resp

    def close(self):
        """Close connection."""
        if self.sock:
            self.sock.close()
            self.sock = None


class Rotator:
    """SCPI rotator control."""
    def __init__(self, host):
        self.dev = SCPIDevice(host)

    def set_position(self, azimuth, elevation):
        """Set antenna position (degrees)."""
        self.dev.write(f'ROT:AZ {azimuth:.2f}')
        self.dev.write(f'ROT:EL {elevation:.2f}')

    def get_position(self):
        """Get current antenna position."""
        az = float(self.dev.query('ROT:AZ?'))
        el = float(self.dev.query('ROT:EL?'))
        return az, el

    def close(self):
        self.dev.close()


class GPS:
    """SCPI GPS receiver."""
    def __init__(self, host):
        self.dev = SCPIDevice(host)

    def get_position(self):
        """Get observer position (lat, lon, alt_m)."""
        lat = float(self.dev.query('GPS:LAT?'))
        lon = float(self.dev.query('GPS:LON?'))
        alt = float(self.dev.query('GPS:ALT?'))
        return lat, lon, alt

    def close(self):
        self.dev.close()


class Radio:
    """Hamlib rigctld control for IC-9700."""
    def __init__(self, host='localhost', port=4532):
        self.host = host
        self.port = port
        self.sock = None
        self._connect()

    def _connect(self):
        """Open TCP connection to rigctld."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        self.sock.connect((self.host, self.port))

    def _cmd(self, cmd):
        """Send rigctld command, return response."""
        self.sock.sendall((cmd + '\n').encode('ascii'))
        resp = self.sock.recv(4096).decode('ascii')
        return resp.strip()

    def set_frequency(self, freq_hz):
        """Set VFO frequency (Hz)."""
        self._cmd(f'F {int(freq_hz)}')

    def get_frequency(self):
        """Get current VFO frequency (Hz)."""
        resp = self._cmd('f')
        return int(resp.split('\n')[0])

    def set_mode(self, mode='FM', width=15000):
        """Set mode and filter width."""
        self._cmd(f'M {mode} {width}')

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None


def fetch_tle(sat_name, source='AMSAT'):
    """
    Fetch TLE from AMSAT or SatNOGS API.

    Returns (line1, line2) tuple.
    """
    if source.upper() == 'AMSAT':
        # AMSAT provides a combined TLE file
        url = 'https://www.amsat.org/tle/current/nasabare.txt'
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        lines = resp.text.strip().split('\n')

        # Find satellite by name (case-insensitive)
        sat_name_upper = sat_name.upper()
        for i in range(0, len(lines), 3):
            if i+2 < len(lines) and sat_name_upper in lines[i].upper():
                return lines[i+1], lines[i+2]

        raise ValueError(f"Satellite '{sat_name}' not found in AMSAT TLE")

    elif source.upper() == 'SATNOGS':
        # SatNOGS DB API
        url = f'https://db.satnogs.org/api/tle/?search={sat_name}'
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data:
            raise ValueError(f"Satellite '{sat_name}' not found in SatNOGS DB")

        # Take first match
        tle = data[0]
        return tle['tle1'], tle['tle2']

    else:
        raise ValueError(f"Unknown TLE source: {source}")


def predict_pass(satellite, observer, start_time, min_elevation=10.0, max_days=7):
    """
    Find next satellite pass above min_elevation.

    Returns dict with:
        aos_time: acquisition of signal (skyfield Time)
        los_time: loss of signal (skyfield Time)
        tca_time: time of closest approach (skyfield Time)
        max_elevation: peak elevation (degrees)
        aos_az: azimuth at AOS (degrees)
        los_az: azimuth at LOS (degrees)

    Returns None if no pass found within max_days.
    """
    ts = load.timescale()
    t0 = start_time
    t_end = ts.from_datetime(t0.to_datetime() + timedelta(days=max_days))

    # Sample every 30 seconds
    times = ts.from_datetime([
        t0.to_datetime() + timedelta(seconds=i*30)
        for i in range(int(max_days * 24 * 60 * 2))
    ])

    # Compute altitude (elevation) at each sample
    difference = satellite - observer
    topos = difference.at(times)
    alt, az, distance = topos.altaz()

    # Find periods above horizon
    above = alt.degrees > min_elevation

    # Find rising edges (AOS) and falling edges (LOS)
    edges = np.diff(above.astype(int))
    aos_indices = np.where(edges == 1)[0] + 1
    los_indices = np.where(edges == -1)[0] + 1

    if len(aos_indices) == 0:
        return None

    # Take first pass
    aos_idx = aos_indices[0]

    # Find corresponding LOS
    los_idx = los_indices[los_indices > aos_idx][0] if len(los_indices[los_indices > aos_idx]) > 0 else len(times)-1

    # Find TCA (max elevation during pass)
    pass_slice = slice(aos_idx, los_idx+1)
    pass_elevations = alt.degrees[pass_slice]
    tca_offset = np.argmax(pass_elevations)
    tca_idx = aos_idx + tca_offset

    return {
        'aos_time': times[aos_idx],
        'los_time': times[los_idx],
        'tca_time': times[tca_idx],
        'max_elevation': alt.degrees[tca_idx],
        'aos_az': az.degrees[aos_idx],
        'los_az': az.degrees[los_idx],
    }


def compute_doppler(satellite, observer, time_obj, tx_freq_hz):
    """
    Compute Doppler shift for satellite at given time.

    Returns corrected_freq_hz (frequency to tune receiver to).

    Doppler shift = -f * (range_rate / c)
    where range_rate is positive when satellite is receding.
    """
    difference = satellite - observer
    topos = difference.at(time_obj)

    # Get range rate (km/s)
    range_rate_km_s = topos.velocity.km_per_s[2]  # radial component
    range_rate_m_s = range_rate_km_s * 1000.0

    # Doppler shift (negative when approaching, positive when receding)
    doppler_shift_hz = -tx_freq_hz * (range_rate_m_s / SPEED_OF_LIGHT)

    # Receiver should tune to (tx_freq - doppler_shift) to compensate
    corrected_freq_hz = tx_freq_hz - doppler_shift_hz

    return corrected_freq_hz


def record_pass(satellite, observer, pass_info, rotator, radio, tx_freq_hz,
                output_dir, sat_name, sample_rate=48000):
    """
    Track satellite pass with antenna + Doppler correction + audio recording.

    Returns path to recorded audio file.
    """
    ts = load.timescale()
    aos_time = pass_info['aos_time']
    los_time = pass_info['los_time']

    # Wait until AOS
    now_dt = datetime.now(timezone.utc)
    aos_dt = aos_time.to_datetime(timezone.utc)
    wait_seconds = (aos_dt - now_dt).total_seconds()

    if wait_seconds > 0:
        print(f"Waiting {wait_seconds:.1f}s until AOS at {aos_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}...")
        time.sleep(wait_seconds)

    # Start recording
    print(f"AOS - starting recording")
    audio_frames = []

    def audio_callback(indata, frames, time_info, status):
        """Capture audio frames."""
        if status:
            print(f"Audio status: {status}")
        audio_frames.append(indata.copy())

    stream = sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        callback=audio_callback,
        dtype='float32'
    )
    stream.start()

    # Tracking loop
    try:
        while True:
            now_dt = datetime.now(timezone.utc)
            now = ts.from_datetime(now_dt)

            # Check if pass is over
            if now.to_datetime(timezone.utc) > los_time.to_datetime(timezone.utc):
                print("LOS - ending recording")
                break

            # Compute satellite position
            difference = satellite - observer
            topos = difference.at(now)
            alt, az, distance = topos.altaz()

            # Aim antenna
            rotator.set_position(az.degrees, alt.degrees)

            # Apply Doppler correction
            corrected_freq = compute_doppler(satellite, observer, now, tx_freq_hz)
            radio.set_frequency(corrected_freq)

            # Status
            doppler_shift = corrected_freq - tx_freq_hz
            print(f"  El={alt.degrees:5.1f}° Az={az.degrees:5.1f}° "
                  f"Doppler={doppler_shift:+7.0f}Hz "
                  f"Tuned={corrected_freq/1e6:.6f}MHz")

            # Update every 1 second
            time.sleep(1.0)

    finally:
        stream.stop()
        stream.close()

    # Save audio
    audio_data = np.concatenate(audio_frames, axis=0)
    timestamp = aos_dt.strftime('%Y%m%d_%H%M%S')
    audio_file = output_dir / f"{sat_name.replace(' ', '_')}_{timestamp}.wav"
    sf.write(str(audio_file), audio_data, sample_rate)
    print(f"Saved audio: {audio_file}")

    # Save metadata
    meta_file = audio_file.with_suffix('.json')
    metadata = {
        'satellite': sat_name,
        'tx_frequency_hz': tx_freq_hz,
        'aos_time': aos_dt.isoformat(),
        'los_time': los_time.to_datetime(timezone.utc).isoformat(),
        'tca_time': pass_info['tca_time'].to_datetime(timezone.utc).isoformat(),
        'max_elevation_deg': pass_info['max_elevation'],
        'aos_azimuth_deg': pass_info['aos_az'],
        'los_azimuth_deg': pass_info['los_az'],
        'sample_rate_hz': sample_rate,
    }
    with open(meta_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved metadata: {meta_file}")

    return audio_file


def main():
    parser = argparse.ArgumentParser(
        description='Automated satellite pass recorder with Doppler correction'
    )
    parser.add_argument('--esp-rotator', required=True,
                        help='scpi-rotator IP address')
    parser.add_argument('--esp-gps', required=True,
                        help='scpi-gps IP address')
    parser.add_argument('--rigctld-host', default='localhost',
                        help='rigctld hostname (default: localhost)')
    parser.add_argument('--rigctld-port', type=int, default=4532,
                        help='rigctld port (default: 4532)')
    parser.add_argument('--sat-name', required=True,
                        help='Satellite name (e.g. "ISS" or "NOAA 19")')
    parser.add_argument('--tx-freq', type=float, required=True,
                        help='Satellite downlink frequency (Hz)')
    parser.add_argument('--tle-source', default='AMSAT',
                        choices=['AMSAT', 'SatNOGS'],
                        help='TLE data source (default: AMSAT)')
    parser.add_argument('--min-elevation', type=float, default=10.0,
                        help='Minimum elevation for pass (degrees, default: 10)')
    parser.add_argument('--mode', default='FM',
                        help='Radio mode (default: FM)')
    parser.add_argument('--bandwidth', type=int, default=15000,
                        help='Filter bandwidth (Hz, default: 15000)')
    parser.add_argument('--output-dir', type=Path, default=Path.cwd(),
                        help='Output directory for recordings (default: current dir)')
    parser.add_argument('--sample-rate', type=int, default=48000,
                        help='Audio sample rate (Hz, default: 48000)')

    args = parser.parse_args()

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Satellite Pass Recorder ===")
    print(f"Satellite: {args.sat_name}")
    print(f"Frequency: {args.tx_freq/1e6:.6f} MHz")
    print(f"Min elevation: {args.min_elevation}°")
    print()

    # Connect to hardware
    print("Connecting to rotator...")
    rotator = Rotator(args.esp_rotator)

    print("Connecting to GPS...")
    gps = GPS(args.esp_gps)
    lat, lon, alt = gps.get_position()
    print(f"Observer position: {lat:.6f}°, {lon:.6f}°, {alt:.1f}m")

    print("Connecting to radio...")
    radio = Radio(args.rigctld_host, args.rigctld_port)
    radio.set_mode(args.mode, args.bandwidth)

    # Fetch TLE
    print(f"Fetching TLE from {args.tle_source}...")
    tle1, tle2 = fetch_tle(args.sat_name, args.tle_source)
    print(f"TLE Line 1: {tle1}")
    print(f"TLE Line 2: {tle2}")
    print()

    # Create skyfield objects
    ts = load.timescale()
    satellite = EarthSatellite(tle1, tle2, args.sat_name, ts)
    observer = wgs84.latlon(lat, lon, elevation_m=alt)

    # Predict next pass
    print("Predicting next pass...")
    now = ts.now()
    pass_info = predict_pass(satellite, observer, now, args.min_elevation)

    if pass_info is None:
        print(f"No passes above {args.min_elevation}° found in next 7 days.")
        return 1

    aos_dt = pass_info['aos_time'].to_datetime(timezone.utc)
    los_dt = pass_info['los_time'].to_datetime(timezone.utc)
    tca_dt = pass_info['tca_time'].to_datetime(timezone.utc)
    duration = (los_dt - aos_dt).total_seconds()

    print(f"Next pass:")
    print(f"  AOS: {aos_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (Az={pass_info['aos_az']:.1f}°)")
    print(f"  TCA: {tca_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (El={pass_info['max_elevation']:.1f}°)")
    print(f"  LOS: {los_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (Az={pass_info['los_az']:.1f}°)")
    print(f"  Duration: {duration/60:.1f} minutes")
    print()

    # Record the pass
    try:
        audio_file = record_pass(
            satellite, observer, pass_info, rotator, radio,
            args.tx_freq, args.output_dir, args.sat_name,
            args.sample_rate
        )
        print(f"\nRecording complete: {audio_file}")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 1

    finally:
        rotator.close()
        gps.close()
        radio.close()


if __name__ == '__main__':
    sys.exit(main())
