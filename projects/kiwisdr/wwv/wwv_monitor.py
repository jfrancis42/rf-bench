#!/usr/bin/env -S python3 -u
"""
WWV / WWVH Propagation Monitor

Monitors WWV and WWVH time signal stations on 2.5, 5, 10, 15, 20, and 25 MHz
simultaneously, measuring signal-to-noise ratio on each frequency every
--interval seconds.  Tracks which HF bands are currently open to Fort Collins, CO
(WWV) and Kauai, HI (WWVH) and logs historical S/N data to SQLite for
propagation analysis.

Optionally adds NCDXF/IARU beacon frequencies (14.100, 18.110, 21.150, 24.930,
28.200 MHz) for cross-band correlation.

Uses one KiwiSDR channel per frequency, cycling through all frequencies with
up to --max-channels simultaneous connections.  Each measurement thread captures
IQ, computes power spectral density, and estimates S/N by comparing the carrier
bin to the surrounding noise floor.

Because WWV/WWVH are both on the same frequencies, only signal presence can be
determined (not which station is stronger) without DSB demodulation and carrier
phase analysis.

Usage:
    python wwv_monitor.py --host kiwisdr.local
    python wwv_monitor.py --host 192.168.1.100 --interval 120 --max-channels 4
    python wwv_monitor.py --host 192.168.1.100 --beacons --log propagation.db
"""

import argparse
import signal
import sqlite3
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Optional

import numpy as np

from rf_bench.kiwisdr import KiwiSDR, KiwiSDRError, KiwiSDRBusyError, SAMPLE_RATE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HOST        = "kiwisdr.local"
DEFAULT_PORT        = 8073
DEFAULT_MAX_CHANNELS = 4
DEFAULT_INTERVAL    = 60       # seconds between sweeps
DEFAULT_SAMPLES     = 12_000   # 1 second at 12 kHz
DEFAULT_DB          = "wwv.db"
DEFAULT_PASSBAND    = 5_000    # ±5 kHz around carrier

# WWV/WWVH carrier frequencies (Hz)
# Both stations share 2.5, 5, 10, 15 MHz; WWV only at 20 and 25 MHz
WWV_FREQS = {
    "WWV/WWVH 2.5 MHz":   2_500_000,
    "WWV/WWVH 5 MHz":     5_000_000,
    "WWV/WWVH 10 MHz":   10_000_000,
    "WWV/WWVH 15 MHz":   15_000_000,
    "WWV 20 MHz":        20_000_000,
    "WWV 25 MHz":        25_000_000,
}

# NCDXF/IARU International Beacon Project frequencies (Hz)
BEACON_FREQS = {
    "NCDXF 14.100":  14_100_000,
    "NCDXF 18.110":  18_110_000,
    "NCDXF 21.150":  21_150_000,
    "NCDXF 24.930":  24_930_000,
    "NCDXF 28.200":  28_200_000,
}

# S/N thresholds for usability ratings
SNR_GOOD      = 20.0   # dB — strong, usable for comms on that band
SNR_MARGINAL  = 10.0   # dB — receivable but may have QSB
SNR_POOR      =  3.0   # dB — barely above noise

# Trend window: last N readings to determine trend direction
TREND_WINDOW  = 5

# ANSI colour codes
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_GREEN  = "\033[32m"
_CYAN   = "\033[36m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"
_CLEAR  = "\033[H\033[J"   # cursor home + clear screen

_running = True


def _sigint(_sig, _frame):
    global _running
    _running = False


signal.signal(signal.SIGINT, _sigint)

# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc      TEXT    NOT NULL,
    ts_unix     REAL    NOT NULL,
    freq_hz     INTEGER NOT NULL,
    label       TEXT,
    snr_db      REAL,
    power_dbfs  REAL
);

CREATE INDEX IF NOT EXISTS readings_freq ON readings(freq_hz);
CREATE INDEX IF NOT EXISTS readings_time ON readings(ts_unix);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(CREATE_SQL)
    conn.commit()
    return conn


def log_reading(conn: sqlite3.Connection, db_lock: threading.Lock,
                freq_hz: int, label: str, snr_db: float, power_dbfs: float) -> None:
    now = time.time()
    ts  = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db_lock:
        conn.execute(
            "INSERT INTO readings(ts_utc, ts_unix, freq_hz, label, snr_db, power_dbfs) "
            "VALUES(?,?,?,?,?,?)",
            (ts, now, freq_hz, label, snr_db, power_dbfs)
        )
        conn.commit()

# ---------------------------------------------------------------------------
# S/N measurement
# ---------------------------------------------------------------------------

def measure_snr(host: str, port: int, password: str,
                freq_hz: int, num_samples: int) -> tuple[float, float]:
    """
    Open one KiwiSDR channel, capture IQ, and return (snr_db, power_dbfs).

    SNR is estimated by comparing the peak power in the carrier bin to the
    median power of the surrounding bins (noise floor proxy).

    Returns (-999.0, -999.0) on error.
    """
    try:
        kiwi = KiwiSDR(host=host, port=port, password=password,
                       passband_hz=DEFAULT_PASSBAND)
        kiwi.set_center_freq(freq_hz)
        time.sleep(0.05)   # let FPGA downsampler settle after retune

        iq = kiwi.capture_iq(num_samples)
        kiwi.close()
    except KiwiSDRBusyError:
        return (-888.0, -888.0)    # sentinel: all channels busy
    except KiwiSDRError:
        return (-999.0, -999.0)    # sentinel: connection error

    freq_arr, pwr_arr = _power_spectrum(iq)

    # Find the carrier bin (nearest to DC since we tuned to the carrier)
    centre_bin = np.argmin(np.abs(freq_arr - freq_hz))

    # Peak power around carrier (±10 bins)
    lo = max(0, centre_bin - 10)
    hi = min(len(pwr_arr) - 1, centre_bin + 10)
    signal_db = float(np.max(pwr_arr[lo:hi]))

    # Noise floor: median of bins outside the ±100 Hz carrier region
    # (avoids being pulled up by the carrier or its sidebands)
    noise_mask = np.abs(freq_arr - freq_hz) > 200
    if noise_mask.sum() < 10:
        noise_db = signal_db - 3.0   # fallback: assume 3 dB S/N
    else:
        noise_db = float(np.median(pwr_arr[noise_mask]))

    snr_db     = signal_db - noise_db
    power_dbfs = signal_db   # already in dBFS (0 dB = full scale)

    return snr_db, power_dbfs


def _power_spectrum(iq: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute power spectrum using Welch's method (numpy only, no scipy).

    Returns (freq_hz_absolute, power_dbfs) arrays.  Because each KiwiSDR
    instance knows its own center frequency, and we pass iq captured from
    a tuned receiver, this function returns relative frequencies here and
    callers map to absolute Hz.

    Actually returns relative frequencies centred at 0 Hz; callers add
    the carrier frequency to find the absolute carrier bin.
    """
    nperseg = min(len(iq), 512)
    step    = nperseg // 2
    window  = np.hanning(nperseg).astype(np.float32)
    win_pow = float(np.sum(window ** 2))

    segs = []
    pos  = 0
    while pos + nperseg <= len(iq):
        seg  = iq[pos:pos + nperseg] * window
        spec = np.fft.fft(seg, n=nperseg)
        segs.append(np.abs(spec) ** 2)
        pos += step

    if not segs:
        segs = [np.abs(np.fft.fft(iq * window[:len(iq)])) ** 2]

    psd   = np.fft.fftshift(np.mean(segs, axis=0) / win_pow)
    freqs = np.fft.fftshift(np.fft.fftfreq(nperseg, d=1.0 / SAMPLE_RATE))

    psd_db = 10.0 * np.log10(psd + 1e-30)
    return freqs.astype(np.float32), psd_db.astype(np.float32)

# ---------------------------------------------------------------------------
# Trend tracking
# ---------------------------------------------------------------------------

class FreqTracker:
    """Tracks SNR history for one frequency and derives trend/rating."""

    def __init__(self, freq_hz: int, label: str):
        self.freq_hz  = freq_hz
        self.label    = label
        self.history  = deque(maxlen=TREND_WINDOW)
        self.snr_db   = None
        self.power_db = None
        self.ts       = None

    def update(self, snr_db: float, power_dbfs: float) -> None:
        self.snr_db   = snr_db
        self.power_db = power_dbfs
        self.ts       = time.time()
        if snr_db > -900:      # exclude error sentinels
            self.history.append(snr_db)

    def trend(self) -> str:
        if len(self.history) < 2:
            return "?"
        delta = self.history[-1] - self.history[0]
        if delta >  2.0:
            return "rising"
        if delta < -2.0:
            return "falling"
        return "stable"

    def rating(self) -> str:
        if self.snr_db is None or self.snr_db < -900:
            return "error"
        if self.snr_db == -888.0:
            return "busy"
        if self.snr_db < SNR_POOR:
            return "absent"
        if self.snr_db < SNR_MARGINAL:
            return "poor"
        if self.snr_db < SNR_GOOD:
            return "marginal"
        return "good"

    def rating_colour(self) -> str:
        r = self.rating()
        if r == "good":
            return _GREEN
        if r == "marginal":
            return _YELLOW
        return _RED

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def render_table(trackers: list, sweep_count: int, next_sweep_s: float) -> None:
    """Print a full-screen ANSI table of all monitored frequencies."""
    lines = [_CLEAR]
    lines.append(f"{_BOLD}WWV / WWVH Propagation Monitor{_RESET}  "
                 f"(sweeps: {sweep_count}  next in: {max(0, int(next_sweep_s))}s  Ctrl-C to stop)")
    lines.append("")
    hdr = (f"{'Frequency':<22}  {'S/N (dB)':>9}  {'Power (dBFS)':>13}  "
           f"{'Trend':>8}  {'Rating':<10}  {'Age':>6}")
    lines.append(_BOLD + hdr + _RESET)
    lines.append("-" * 80)

    for t in trackers:
        age_s = int(time.time() - t.ts) if t.ts else 0
        snr_str   = f"{t.snr_db:+7.1f}" if (t.snr_db is not None and t.snr_db > -900) else "  -----"
        pwr_str   = f"{t.power_db:+8.1f}" if (t.power_db is not None and t.power_db > -900) else "  -----"
        age_str   = f"{age_s}s"
        colour    = t.rating_colour()
        trend_str = t.trend()
        rating    = t.rating()

        lines.append(
            f"{colour}{t.label:<22}{_RESET}  "
            f"{snr_str}  "
            f"{pwr_str}  "
            f"{trend_str:>8}  "
            f"{colour}{rating:<10}{_RESET}  "
            f"{age_str:>6}"
        )

    lines.append("")
    lines.append(f"{_CYAN}Good: S/N ≥ {SNR_GOOD:.0f} dB  |  "
                 f"Marginal: ≥ {SNR_MARGINAL:.0f} dB  |  "
                 f"Poor: ≥ {SNR_POOR:.0f} dB  |  "
                 f"Absent: < {SNR_POOR:.0f} dB{_RESET}")

    print("\n".join(lines), end="", flush=True)

# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

def measure_worker(host: str, port: int, password: str,
                   freq_hz: int, num_samples: int,
                   result_queue: Queue) -> None:
    """Thread target: measure one frequency and put result onto queue."""
    snr, pwr = measure_snr(host, port, password, freq_hz, num_samples)
    result_queue.put((freq_hz, snr, pwr))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_freq_list(args) -> dict:
    """Return {label: freq_hz} dict based on CLI args."""
    if args.freqs:
        freqs = {}
        for raw in args.freqs.split(","):
            raw = raw.strip()
            try:
                hz = int(raw)
                freqs[f"{hz/1e6:.3f} MHz"] = hz
            except ValueError:
                print(f"WARNING: ignoring invalid frequency: {raw!r}", file=sys.stderr)
        return freqs

    freqs = dict(WWV_FREQS)
    if args.beacons:
        freqs.update(BEACON_FREQS)
    return freqs


def main():
    ap = argparse.ArgumentParser(
        description="WWV/WWVH propagation monitor via KiwiSDR"
    )
    ap.add_argument("--host",         default=DEFAULT_HOST,
                    help="KiwiSDR hostname or IP (default: %(default)s)")
    ap.add_argument("--port",         type=int, default=DEFAULT_PORT,
                    help="KiwiSDR port (default: %(default)s)")
    ap.add_argument("--password",     default="",
                    help="KiwiSDR password (default: empty)")
    ap.add_argument("--freqs",        default=None,
                    help="Override frequency list (Hz, comma-separated)")
    ap.add_argument("--max-channels", type=int, default=DEFAULT_MAX_CHANNELS,
                    help="Max simultaneous KiwiSDR connections (default: %(default)s)")
    ap.add_argument("--interval",     type=int, default=DEFAULT_INTERVAL,
                    help="Seconds between measurement sweeps (default: %(default)s)")
    ap.add_argument("--samples",      type=int, default=DEFAULT_SAMPLES,
                    help="IQ samples per measurement (default: %(default)s = 1 s)")
    ap.add_argument("--log",          default=DEFAULT_DB, metavar="FILE",
                    help="SQLite log path (default: %(default)s)")
    ap.add_argument("--beacons",      action="store_true",
                    help="Add NCDXF/IARU beacon frequencies")
    args = ap.parse_args()

    freq_map = build_freq_list(args)
    if not freq_map:
        print("No frequencies to monitor.", file=sys.stderr)
        sys.exit(1)

    # Build per-frequency tracker objects (ordered by frequency)
    trackers_by_freq: dict[int, FreqTracker] = {}
    ordered: list[FreqTracker] = []
    for label, hz in sorted(freq_map.items(), key=lambda kv: kv[1]):
        t = FreqTracker(hz, label)
        trackers_by_freq[hz] = t
        ordered.append(t)

    conn    = open_db(args.log)
    db_lock = threading.Lock()

    freqs_list  = [t.freq_hz for t in ordered]
    sweep_count = 0
    last_sweep  = 0.0

    print(f"Monitoring {len(freqs_list)} frequencies | "
          f"max {args.max_channels} channels | "
          f"interval {args.interval}s")
    print(f"Log: {args.log}")
    print("Press Ctrl-C to stop.\n")

    try:
        while _running:
            now = time.time()
            time_to_next = last_sweep + args.interval - now

            # Update display while waiting
            if sweep_count > 0:
                render_table(ordered, sweep_count, time_to_next)

            if time_to_next > 0:
                time.sleep(min(1.0, time_to_next))
                continue

            # Run a measurement sweep
            last_sweep  = time.time()
            sweep_count += 1
            result_q    = Queue()

            # Process in batches of max_channels
            batch_size = max(1, args.max_channels)
            for batch_start in range(0, len(freqs_list), batch_size):
                if not _running:
                    break
                batch = freqs_list[batch_start:batch_start + batch_size]

                threads = []
                for hz in batch:
                    t = threading.Thread(
                        target=measure_worker,
                        args=(args.host, args.port, args.password,
                              hz, args.samples, result_q),
                        daemon=True
                    )
                    t.start()
                    threads.append(t)

                for thr in threads:
                    thr.join(timeout=args.samples / SAMPLE_RATE + 30.0)

            # Drain results
            while not result_q.empty():
                try:
                    freq_hz, snr_db, power_dbfs = result_q.get_nowait()
                except Empty:
                    break
                if freq_hz in trackers_by_freq:
                    trackers_by_freq[freq_hz].update(snr_db, power_dbfs)
                if snr_db > -900:
                    lbl = trackers_by_freq[freq_hz].label if freq_hz in trackers_by_freq else str(freq_hz)
                    log_reading(conn, db_lock, freq_hz, lbl, snr_db, power_dbfs)

            render_table(ordered, sweep_count, args.interval)

    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
        print(f"\nDone. {sweep_count} sweeps completed. Log: {args.log}")


if __name__ == "__main__":
    main()
