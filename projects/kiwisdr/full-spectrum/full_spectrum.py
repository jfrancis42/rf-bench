#!/usr/bin/env python3
"""
Full-Spectrum Scanner — simultaneous HF + VHF/UHF coverage via KiwiSDR + RTL-SDR.

Runs a KiwiSDR HF scanner (0–30 MHz) and an RTL-SDR VHF/UHF scanner simultaneously
in separate daemon threads.  Both log to a unified SQLite detections table.  A shared
queue carries Detection namedtuples from scanner threads to the main display loop.

Usage:
    python full_spectrum.py
    python full_spectrum.py --kiwi-host 10.1.0.5 --vhf-squelch 8
    python full_spectrum.py --no-hf                  # RTL-SDR only
    python full_spectrum.py --no-vhf                 # KiwiSDR HF only
    python full_spectrum.py --hf-bands 40m,20m --vhf-start 144000000 --vhf-stop 148000000

Output:
    full_spectrum.db  — SQLite log (default path)
"""

import argparse
import os
import queue
import signal
import sqlite3
import sys
import threading
import time
from collections import deque, namedtuple
from datetime import datetime, timezone

import numpy as np

from rf_bench.kiwisdr import KiwiSDR, KiwiSDRError, SAMPLE_RATE as KIWI_SR
from rf_bench.rtlsdr  import RTLSDR

# RTL-SDR constants
RTL_SAMPLE_RATE = 2_400_000
RTL_FFT_SIZE    = 131_072      # ~55 ms at 2.4 MSPS; ~18 Hz/bin
RTL_VHF_GAIN    = 30.0         # dB, starting gain for VHF scans

# KiwiSDR HF band definitions
HF_BANDS: dict[str, tuple[int, int]] = {
    "160m": (1_800_000,  2_000_000),
    "80m":  (3_500_000,  4_000_000),
    "40m":  (7_000_000,  7_300_000),
    "20m":  (14_000_000, 14_350_000),
    "17m":  (18_068_000, 18_168_000),
    "15m":  (21_000_000, 21_450_000),
    "12m":  (24_890_000, 24_990_000),
    "10m":  (28_000_000, 29_700_000),
}
DEFAULT_HF_BANDS = ["40m", "20m", "15m", "10m"]

# ── Detection record ──────────────────────────────────────────────────────────

Detection = namedtuple("Detection",
                       ["ts_unix", "freq_hz", "snr_db", "power_dbfs", "source", "band"])

# ── ANSI colours ──────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"
BLUE   = "\033[94m"
WHITE  = "\033[97m"

SOURCE_COLOR = {"HF": CYAN, "VHF": YELLOW}


def _bar(snr: float, lo: float = 0.0, hi: float = 40.0, width: int = 10) -> str:
    frac = max(0.0, min(1.0, (snr - lo) / (hi - lo)))
    return "█" * int(frac * width) + "░" * (width - int(frac * width))


# ── SQLite ────────────────────────────────────────────────────────────────────

def _open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT NOT NULL,
            ts_unix     REAL NOT NULL,
            freq_hz     INTEGER NOT NULL,
            freq_mhz    REAL,
            band        TEXT,
            source      TEXT,
            snr_db      REAL,
            power_dbfs  REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts     ON detections (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_freq   ON detections (freq_hz)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON detections (source)")
    conn.commit()
    return conn


def _log_detection(conn: sqlite3.Connection, d: Detection) -> None:
    now_utc = datetime.fromtimestamp(d.ts_unix, tz=timezone.utc)
    conn.execute(
        "INSERT INTO detections "
        "(ts_utc, ts_unix, freq_hz, freq_mhz, band, source, snr_db, power_dbfs) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (now_utc.isoformat(), d.ts_unix,
         d.freq_hz, round(d.freq_hz / 1e6, 6),
         d.band, d.source,
         round(d.snr_db, 2), round(d.power_dbfs, 2)),
    )
    conn.commit()


# ── HF Scanner (KiwiSDR) ──────────────────────────────────────────────────────

class HFScanner(threading.Thread):
    """
    Continuously sweeps configured HF amateur bands using the KiwiSDR.
    Pushes Detection namedtuples into the shared queue.
    """

    def __init__(self,
                 out_q: queue.Queue,
                 host: str,
                 port: int,
                 password: str,
                 bands: list[str],
                 squelch_db: float,
                 step_hz: int = 10_000,
                 dwell_samples: int = 2_048) -> None:
        super().__init__(daemon=True, name="HFScanner")
        self.out_q        = out_q
        self.host         = host
        self.port         = port
        self.password     = password
        self.bands        = bands
        self.squelch_db   = squelch_db
        self.step_hz      = step_hz
        self.dwell_samples = dwell_samples

        self.running      = True
        self.error: str | None = None
        self.cycle_count  = 0
        self.det_count    = 0

    def stop(self) -> None:
        self.running = False

    def run(self) -> None:
        try:
            kiwi = KiwiSDR(self.host, port=self.port, password=self.password,
                           channel=0, passband_hz=5000)
        except KiwiSDRError as e:
            self.error = str(e)
            return

        try:
            while self.running:
                self.cycle_count += 1
                for band in self.bands:
                    if not self.running:
                        break
                    lo, hi = HF_BANDS[band]
                    freq = lo
                    while freq <= hi and self.running:
                        try:
                            kiwi.set_center_freq(freq)
                            time.sleep(0.04)
                            iq = kiwi.capture_iq(self.dwell_samples)
                        except KiwiSDRError:
                            freq += self.step_hz
                            continue

                        n = len(iq)
                        win     = np.hanning(n).astype(np.float32)
                        fft_raw = np.fft.fftshift(np.fft.fft(iq * win))
                        psd_db  = 10.0 * np.log10(
                            np.maximum(np.abs(fft_raw) ** 2 / np.sum(win ** 2), 1e-30)
                        )
                        noise = float(np.median(psd_db))
                        peak  = float(np.max(psd_db))
                        snr   = peak - noise

                        if snr >= self.squelch_db:
                            d = Detection(
                                ts_unix=time.time(),
                                freq_hz=freq,
                                snr_db=round(snr, 1),
                                power_dbfs=round(peak, 1),
                                source="HF",
                                band=band,
                            )
                            try:
                                self.out_q.put_nowait(d)
                            except queue.Full:
                                pass
                            self.det_count += 1

                        freq += self.step_hz
        finally:
            kiwi.close()


# ── VHF/UHF Scanner (RTL-SDR) ────────────────────────────────────────────────

class VHFScanner(threading.Thread):
    """
    Scans a configurable VHF/UHF range using the RTL-SDR.

    Tunes to a center frequency covering the range (or steps if the range is wider
    than the 2.4 MHz RTL-SDR bandwidth), captures RTL_FFT_SIZE samples, computes a
    Hanning-windowed FFT, finds peaks above the local noise floor, and pushes
    Detection namedtuples into the shared queue.
    """

    def __init__(self,
                 out_q: queue.Queue,
                 serial: str | None,
                 ppm: int,
                 start_hz: int,
                 stop_hz: int,
                 squelch_db: float,
                 gain_db: float = RTL_VHF_GAIN) -> None:
        super().__init__(daemon=True, name="VHFScanner")
        self.out_q      = out_q
        self.serial     = serial
        self.ppm        = ppm
        self.start_hz   = start_hz
        self.stop_hz    = stop_hz
        self.squelch_db = squelch_db
        self.gain_db    = gain_db

        self.running    = True
        self.error: str | None = None
        self.cycle_count  = 0
        self.det_count    = 0

    def stop(self) -> None:
        self.running = False

    def _scan_group(self, sdr: RTLSDR, center_hz: int) -> list[tuple[int, float, float]]:
        """
        Capture RTL_FFT_SIZE samples at center_hz and return list of
        (freq_hz, power_dbfs, snr_db) for peaks above squelch.
        """
        sdr.set_center_freq(center_hz)
        time.sleep(0.05)
        iq = sdr.capture_iq(RTL_FFT_SIZE)

        n = len(iq)
        win     = np.hanning(n).astype(np.float32)
        fft_raw = np.fft.fftshift(np.fft.fft(iq * win))
        psd_db  = 10.0 * np.log10(
            np.maximum(np.abs(fft_raw) ** 2 / np.sum(win ** 2), 1e-30)
        )
        noise  = float(np.median(psd_db))
        bin_hz = RTL_SAMPLE_RATE / n

        # Find bins that exceed squelch
        peaks: list[tuple[int, float, float]] = []
        above = psd_db - noise
        # Look for local maxima above threshold
        for i in range(1, n - 1):
            if above[i] >= self.squelch_db and psd_db[i] >= psd_db[i-1] and psd_db[i] >= psd_db[i+1]:
                offset_hz = (i - n // 2) * bin_hz
                freq_hz   = int(center_hz + offset_hz)
                # Only report if within scan range
                if self.start_hz <= freq_hz <= self.stop_hz:
                    peaks.append((freq_hz, float(psd_db[i]), float(above[i])))

        return peaks

    def run(self) -> None:
        try:
            sdr = RTLSDR(serial=self.serial, ppm_correction=self.ppm)
            sdr.set_sample_rate(RTL_SAMPLE_RATE)
            sdr.set_gain(self.gain_db)
        except Exception as e:
            self.error = str(e)
            return

        # Build list of center frequencies to step through
        # RTL-SDR usable bandwidth is ~80% of sample rate = ~1.92 MHz
        bw = int(RTL_SAMPLE_RATE * 0.80)
        span = self.stop_hz - self.start_hz
        if span <= bw:
            centers = [self.start_hz + span // 2]
        else:
            step = bw
            centers = list(range(self.start_hz + bw // 2,
                                  self.stop_hz + bw // 2,
                                  step))

        try:
            while self.running:
                self.cycle_count += 1
                for center_hz in centers:
                    if not self.running:
                        break
                    try:
                        peaks = self._scan_group(sdr, center_hz)
                    except Exception:
                        continue

                    for freq_hz, power_dbfs, snr_db in peaks:
                        d = Detection(
                            ts_unix=time.time(),
                            freq_hz=freq_hz,
                            snr_db=round(snr_db, 1),
                            power_dbfs=round(power_dbfs, 1),
                            source="VHF",
                            band=f"{self.start_hz/1e6:.0f}–{self.stop_hz/1e6:.0f} MHz",
                        )
                        try:
                            self.out_q.put_nowait(d)
                        except queue.Full:
                            pass
                        self.det_count += 1
        finally:
            sdr.close()


# ── Display ───────────────────────────────────────────────────────────────────

def _format_detection(d: Detection, use_color: bool) -> str:
    ts_str = datetime.fromtimestamp(d.ts_unix).strftime("%H:%M:%S")
    mhz    = d.freq_hz / 1e6
    bar    = _bar(d.snr_db)
    if use_color:
        col = SOURCE_COLOR.get(d.source, "")
        return (f"{DIM}[{ts_str}]{RESET} "
                f"{col}{BOLD}{d.source:<3}{RESET} "
                f"{d.band:<18} "
                f"{mhz:10.4f} MHz  "
                f"SNR {d.snr_db:+5.1f} dB  "
                f"pwr {d.power_dbfs:+6.1f} dBFS  "
                f"{col}{bar}{RESET}")
    return (f"[{ts_str}] {d.source:<3} {d.band:<18} "
            f"{mhz:10.4f} MHz  SNR {d.snr_db:+5.1f} dB  "
            f"pwr {d.power_dbfs:+6.1f} dBFS  {bar}")


def _print_status(use_color: bool,
                  hf_scanner: "HFScanner | None",
                  vhf_scanner: "VHFScanner | None",
                  recent: deque,
                  total: int) -> None:
    if use_color:
        os.system("clear")
    else:
        print("\033[H\033[J", end="")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hdr = f"Full-Spectrum Scanner" if not use_color else f"{BOLD}Full-Spectrum Scanner{RESET}"
    print(f"\n  {hdr}  —  {ts}  |  detections: {total}")
    print(f"  {'─'*76}")

    # Status of each scanner
    def _status(scanner, name: str, color: str) -> None:
        if scanner is None:
            print(f"  {DIM if use_color else ''}{name:<6}  disabled{RESET if use_color else ''}")
        elif scanner.error:
            err_c = RED if use_color else ""
            rst   = RESET if use_color else ""
            print(f"  {err_c}{name:<6}  ERROR: {scanner.error}{rst}")
        else:
            col = color if use_color else ""
            rst = RESET if use_color else ""
            print(f"  {col}{name:<6}  cycle #{scanner.cycle_count:<6}  "
                  f"detections: {scanner.det_count}{rst}")

    _status(hf_scanner,  "HF",  CYAN)
    _status(vhf_scanner, "VHF", YELLOW)

    print(f"  {'─'*76}")

    if recent:
        for line in recent:
            print(f"  {line}")
    else:
        print(f"  {DIM}(no activity yet){RESET}" if use_color else "  (no activity yet)")

    print(f"\n  Press Ctrl-C to stop.\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    if args.no_hf and args.no_vhf:
        print("ERROR: both --no-hf and --no-vhf specified; nothing to do")
        sys.exit(1)

    # Validate HF bands
    hf_bands: list[str] = []
    if not args.no_hf:
        hf_bands = [b.strip() for b in args.hf_bands.split(",")]
        invalid  = [b for b in hf_bands if b not in HF_BANDS]
        if invalid:
            print(f"ERROR: unknown HF bands: {', '.join(invalid)}")
            print(f"  Valid: {', '.join(HF_BANDS.keys())}")
            sys.exit(1)

    conn   = _open_db(args.log)
    det_q: queue.Queue = queue.Queue(maxsize=500)
    recent: deque      = deque(maxlen=args.tail)
    total  = 0
    stop   = False

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    print(f"\n  Full-Spectrum Scanner")
    print(f"  HF: {args.kiwi_host}:{args.kiwi_port}  bands: {' '.join(hf_bands) or 'disabled'}")
    print(f"  VHF: RTL-SDR serial={args.rtl_serial or 'auto'}  "
          f"range: {args.vhf_start/1e6:.1f}–{args.vhf_stop/1e6:.1f} MHz")
    print(f"  HF squelch: {args.hf_squelch} dB  VHF squelch: {args.vhf_squelch} dB")
    print(f"  Log: {args.log}  |  tail: {args.tail}")
    print(f"  Starting scanners...")

    hf_scanner: HFScanner | None = None
    vhf_scanner: VHFScanner | None = None

    if not args.no_hf:
        hf_scanner = HFScanner(
            out_q=det_q,
            host=args.kiwi_host, port=args.kiwi_port, password=args.kiwi_password,
            bands=hf_bands, squelch_db=args.hf_squelch,
        )
        hf_scanner.start()

    if not args.no_vhf:
        vhf_scanner = VHFScanner(
            out_q=det_q,
            serial=args.rtl_serial, ppm=args.rtl_ppm,
            start_hz=args.vhf_start, stop_hz=args.vhf_stop,
            squelch_db=args.vhf_squelch,
        )
        vhf_scanner.start()

    print(f"  Running.  Press Ctrl-C to stop.\n")

    last_display = 0.0
    DISPLAY_INTERVAL = 0.5   # seconds

    try:
        while not stop:
            # Drain queue
            try:
                while True:
                    d = det_q.get_nowait()
                    _log_detection(conn, d)
                    line = _format_detection(d, use_color)
                    recent.append(line)
                    total += 1
            except queue.Empty:
                pass

            now = time.monotonic()
            if now - last_display >= DISPLAY_INTERVAL:
                _print_status(use_color, hf_scanner, vhf_scanner, recent, total)
                last_display = now

            time.sleep(0.05)

    except Exception as e:
        print(f"\n  Error: {e}")
    finally:
        if hf_scanner:
            hf_scanner.stop()
        if vhf_scanner:
            vhf_scanner.stop()
        conn.close()

    print(f"\n  Stopped.  Total detections: {total}")
    print(f"  Database: {args.log}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Full-Spectrum Scanner — KiwiSDR HF + RTL-SDR VHF/UHF simultaneous",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
HF bands: 160m 80m 40m 20m 17m 15m 12m 10m

Examples:
  python full_spectrum.py
  python full_spectrum.py --no-vhf                   # HF only
  python full_spectrum.py --no-hf                    # VHF only
  python full_spectrum.py --hf-bands 40m,20m --hf-squelch 10
  python full_spectrum.py --vhf-start 144000000 --vhf-stop 148000000
        """,
    )

    # KiwiSDR
    p.add_argument("--kiwi-host",     default="kiwisdr.local", dest="kiwi_host",
                   help="KiwiSDR hostname or IP (default: kiwisdr.local)")
    p.add_argument("--kiwi-port",     type=int, default=8073, dest="kiwi_port",
                   help="KiwiSDR port (default: 8073)")
    p.add_argument("--kiwi-password", default="", dest="kiwi_password",
                   help="KiwiSDR password (default: empty)")

    # RTL-SDR
    p.add_argument("--rtl-serial", default=None, dest="rtl_serial",
                   help="RTL-SDR serial number (default: first device)")
    p.add_argument("--rtl-ppm",    type=int, default=0, dest="rtl_ppm",
                   help="RTL-SDR frequency correction in PPM (default: 0)")

    # Band selection
    p.add_argument("--hf-bands",    default=",".join(DEFAULT_HF_BANDS), dest="hf_bands",
                   help="HF bands to sweep (default: 40m,20m,15m,10m)")
    p.add_argument("--vhf-start",   type=int, default=144_000_000, dest="vhf_start",
                   help="VHF/UHF scan start in Hz (default: 144000000)")
    p.add_argument("--vhf-stop",    type=int, default=148_000_000, dest="vhf_stop",
                   help="VHF/UHF scan stop in Hz (default: 148000000)")

    # Squelch
    p.add_argument("--hf-squelch",  type=float, default=12.0, dest="hf_squelch",
                   help="HF squelch in dB above noise (default: 12)")
    p.add_argument("--vhf-squelch", type=float, default=10.0, dest="vhf_squelch",
                   help="VHF squelch in dB above noise (default: 10)")

    # Disable halves
    p.add_argument("--no-hf",  action="store_true", dest="no_hf",
                   help="Disable KiwiSDR HF scanner")
    p.add_argument("--no-vhf", action="store_true", dest="no_vhf",
                   help="Disable RTL-SDR VHF/UHF scanner")

    # Output
    p.add_argument("--log",  default="full_spectrum.db",
                   help="SQLite output path (default: full_spectrum.db)")
    p.add_argument("--tail", type=int, default=30,
                   help="Recent detections in rolling display (default: 30)")
    p.add_argument("--no-color", action="store_true", dest="no_color",
                   help="Disable ANSI colours")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
