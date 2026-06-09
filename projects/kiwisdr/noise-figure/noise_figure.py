#!/usr/bin/env python3
"""
Noise Figure Measurement — Y-factor method using KiwiSDR as the measurement receiver.

Steps through a list of HF test frequencies.  At each frequency, the user connects
the noise source in the OFF state (cold), captures IQ, then connects it in the ON
state (hot), captures again.  Computes Y = P_hot / P_cold and derives the noise
figure via the standard Y-factor formula.

ENR (Excess Noise Ratio) can be specified as a flat value (--enr) or loaded from a
two-column CSV file (--enr-file) with freq_hz, enr_db columns.

Usage:
    python noise_figure.py
    python noise_figure.py --freqs 7000000,14000000,21000000,28000000 --enr 15
    python noise_figure.py --enr-file my_noise_source.csv --samples 60000
    python noise_figure.py --auto   # automated noise source (no prompts)
    python noise_figure.py --csv    # also write noise_figure.csv

Output:
    noise_figure.db  — SQLite results (default path)
    noise_figure.csv — CSV results (with --csv)
"""

import argparse
import csv
import math
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone

import numpy as np

from rf_bench.kiwisdr import KiwiSDR, KiwiSDRError, SAMPLE_RATE


# ── Physical constants ────────────────────────────────────────────────────────

T_COLD_K  = 290.0      # Standard reference temperature (K), IEEE definition
T_HOT_K   = 10_000.0   # Nominal hot temperature for a typical noise source (K)
                        # A 15 dB ENR noise source has T_hot ≈ 9483 K; we use ENR
                        # directly so T_HOT_K is informational only.

# Default test frequencies (Hz): classic HF amateur bands
DEFAULT_FREQS = [3_500_000, 7_000_000, 14_000_000, 21_000_000, 28_000_000]

KIWI_MAX_HZ = 30_000_000


# ── ANSI colours ──────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"
WHITE  = "\033[97m"


# ── ENR table ─────────────────────────────────────────────────────────────────

def _load_enr_file(path: str) -> dict[int, float]:
    """
    Load ENR table from a two-column CSV: freq_hz (int), enr_db (float).
    Returns dict {freq_hz: enr_db}.
    """
    table: dict[int, float] = {}
    with open(path, newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if not row or row[0].strip().startswith("#"):
                continue
            if len(row) < 2:
                continue
            try:
                hz  = int(row[0].strip())
                enr = float(row[1].strip())
                table[hz] = enr
            except ValueError:
                if i == 0:
                    continue   # header row
                print(f"WARNING: skipping bad ENR row {i+1}: {row}")
    return table


def _lookup_enr(freq_hz: int, enr_table: dict[int, float],
                flat_enr: float) -> float:
    """
    Return ENR for a given frequency.  If table has data, interpolate linearly
    between the two closest entries; otherwise return the flat value.
    """
    if not enr_table:
        return flat_enr

    keys  = sorted(enr_table.keys())
    if freq_hz <= keys[0]:
        return enr_table[keys[0]]
    if freq_hz >= keys[-1]:
        return enr_table[keys[-1]]

    # Linear interpolation
    for i in range(len(keys) - 1):
        lo, hi = keys[i], keys[i + 1]
        if lo <= freq_hz <= hi:
            frac = (freq_hz - lo) / (hi - lo)
            return enr_table[lo] + frac * (enr_table[hi] - enr_table[lo])

    return flat_enr


# ── NF calculation ────────────────────────────────────────────────────────────

def _compute_nf(p_hot_dbfs: float, p_cold_dbfs: float, enr_db: float
                ) -> tuple[float, float, float]:
    """
    Y-factor noise figure calculation.

    Returns:
        y_db   — Y-factor in dB (= P_hot_dbfs - P_cold_dbfs)
        y_lin  — Y-factor linear
        nf_db  — noise figure in dB, or NaN if Y ≤ 1
    """
    y_db  = p_hot_dbfs - p_cold_dbfs
    y_lin = 10.0 ** (y_db / 10.0)

    if y_lin <= 1.0:
        # Y ≤ 1 means the hot measurement is not above cold — result is invalid.
        # This happens when the noise source ENR is too low for the DUT's NF,
        # or when the measurement is corrupted by external RFI.
        return y_db, y_lin, float("nan")

    nf_db = enr_db - 10.0 * math.log10(y_lin - 1.0)
    return y_db, y_lin, nf_db


def _compute_power_dbfs(iq: np.ndarray) -> float:
    """
    Compute mean power of IQ block in dBFS.
    P = mean(|I|^2 + |Q|^2)  normalized to full-scale.
    """
    power_lin = float(np.mean(np.abs(iq) ** 2))
    return 10.0 * math.log10(max(power_lin, 1e-30))


# ── SQLite ────────────────────────────────────────────────────────────────────

def _open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS measurements (
            id          INTEGER PRIMARY KEY,
            ts_utc      TEXT NOT NULL,
            ts_unix     REAL NOT NULL,
            freq_hz     INTEGER NOT NULL,
            freq_mhz    REAL,
            enr_db      REAL,
            p_cold_dbfs REAL,
            p_hot_dbfs  REAL,
            y_factor_db REAL,
            nf_db       REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts   ON measurements (ts_unix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_freq ON measurements (freq_hz)")
    conn.commit()
    return conn


def _log_measurement(conn: sqlite3.Connection,
                     freq_hz: int, enr_db: float,
                     p_cold: float, p_hot: float,
                     y_db: float, nf_db: float) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO measurements "
        "(ts_utc, ts_unix, freq_hz, freq_mhz, enr_db, p_cold_dbfs, p_hot_dbfs, y_factor_db, nf_db) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (now.isoformat(), now.timestamp(),
         freq_hz, round(freq_hz / 1e6, 6),
         round(enr_db, 2),
         round(p_cold, 3), round(p_hot, 3),
         round(y_db, 3),
         round(nf_db, 2) if not math.isnan(nf_db) else None),
    )
    conn.commit()


# ── CSV output ────────────────────────────────────────────────────────────────

def _write_csv(path: str, results: list[dict]) -> None:
    fields = ["freq_hz", "freq_mhz", "enr_db",
              "p_cold_dbfs", "p_hot_dbfs", "y_factor_db", "nf_db", "ts_utc"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)


# ── Prompt helpers ────────────────────────────────────────────────────────────

def _prompt(msg: str) -> None:
    """Print msg and wait for Enter.  Handles Ctrl-C gracefully."""
    try:
        input(msg)
    except EOFError:
        pass   # non-interactive stdin


def _capture_power(kiwi: KiwiSDR, freq_hz: int, n_samples: int,
                   label: str) -> float:
    """Tune to freq_hz, capture n_samples, return mean power in dBFS."""
    kiwi.set_center_freq(freq_hz)
    time.sleep(0.05)   # filter settle
    print(f"    Capturing {n_samples} samples ({n_samples / SAMPLE_RATE:.1f}s) "
          f"— {label}...")
    iq = kiwi.capture_iq(n_samples)
    power = _compute_power_dbfs(iq)
    print(f"    Power ({label}): {power:+.3f} dBFS")
    return power


# ── Display ───────────────────────────────────────────────────────────────────

def _print_summary(results: list[dict], use_color: bool) -> None:
    print()
    hdr = f"{BOLD}Noise Figure Results{RESET}" if use_color else "Noise Figure Results"
    print(f"  {hdr}")
    print(f"  {'─'*70}")
    print(f"  {'Frequency':<18}  {'ENR':>6}  {'P_cold':>8}  {'P_hot':>8}  "
          f"{'Y':>7}  {'NF':>7}")
    print(f"  {'─'*70}")
    for r in results:
        nf_str = f"{r['nf_db']:+7.2f}" if not math.isnan(r["nf_db"]) else "  INVALID"
        if use_color:
            if math.isnan(r["nf_db"]):
                nf_col = RED
            elif r["nf_db"] < 5.0:
                nf_col = GREEN
            elif r["nf_db"] < 15.0:
                nf_col = YELLOW
            else:
                nf_col = RED
            nf_display = f"{nf_col}{nf_str} dB{RESET}"
        else:
            nf_display = f"{nf_str} dB"

        print(f"  {r['freq_mhz']:10.3f} MHz    "
              f"{r['enr_db']:+5.1f} dB  "
              f"{r['p_cold_dbfs']:+7.2f} dB  "
              f"{r['p_hot_dbfs']:+7.2f} dB  "
              f"{r['y_factor_db']:+6.2f} dB  "
              f"{nf_display}")
    print(f"  {'─'*70}")

    valid_nf = [r["nf_db"] for r in results if not math.isnan(r["nf_db"])]
    if valid_nf:
        avg_nf = sum(valid_nf) / len(valid_nf)
        avg_str = f"{BOLD}{avg_nf:+.2f} dB{RESET}" if use_color else f"{avg_nf:+.2f} dB"
        print(f"\n  Mean NF ({len(valid_nf)} valid points): {avg_str}")

    invalid = len(results) - len(valid_nf)
    if invalid:
        warn = f"{RED}WARNING: {invalid} measurement(s) invalid (Y ≤ 1){RESET}" if use_color \
               else f"WARNING: {invalid} measurement(s) invalid (Y ≤ 1)"
        print(f"  {warn}")
        print(f"  {DIM}Invalid measurements mean Y ≤ 1 (noise source ENR too low,{RESET}" if use_color
              else f"  Invalid measurements mean Y ≤ 1 (noise source ENR too low,")
        print(f"  {'or external RFI contaminated the cold measurement).'}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    # Parse frequencies
    try:
        freqs = [int(f.strip()) for f in args.freqs.split(",")]
    except ValueError:
        print("ERROR: --freqs must be comma-separated integers in Hz")
        sys.exit(1)

    bad = [hz for hz in freqs if hz > KIWI_MAX_HZ]
    if bad:
        for hz in bad:
            print(f"WARNING: {hz} Hz exceeds KiwiSDR 30 MHz limit — skipping")
        freqs = [hz for hz in freqs if hz <= KIWI_MAX_HZ]
    if not freqs:
        print("ERROR: no valid test frequencies")
        sys.exit(1)

    # Load ENR table
    enr_table: dict[int, float] = {}
    if args.enr_file:
        try:
            enr_table = _load_enr_file(args.enr_file)
            print(f"  Loaded {len(enr_table)} ENR table entries from {args.enr_file}")
        except OSError as e:
            print(f"ERROR: cannot read ENR file: {e}")
            sys.exit(1)

    conn = _open_db(args.log)

    print(f"\n  Noise Figure Measurement — Y-factor method")
    print(f"  Host: {args.host}:{args.port}  |  samples: {args.samples} "
          f"({args.samples / SAMPLE_RATE:.1f}s)  |  flat ENR: {args.enr} dB")
    print(f"  Test frequencies: {', '.join(f'{hz/1e6:.3f} MHz' for hz in freqs)}")
    print(f"  SQLite: {args.log}")
    if args.auto:
        print(f"  Auto mode: no prompts (assumes hardware switching)")
    print()

    # Connect KiwiSDR
    print(f"  Connecting to KiwiSDR at {args.host}:{args.port}...")
    try:
        kiwi = KiwiSDR(args.host, port=args.port, password=args.password,
                       channel=0, passband_hz=5000)
    except KiwiSDRError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print(f"  Connected.\n")

    stop    = False
    results = []

    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    # ── Measurement loop ──────────────────────────────────────────────────────
    for i, freq_hz in enumerate(freqs):
        if stop:
            break

        enr_db   = _lookup_enr(freq_hz, enr_table, args.enr)
        freq_mhz = freq_hz / 1e6

        if use_color:
            print(f"  {BOLD}[{i+1}/{len(freqs)}] {freq_mhz:.3f} MHz{RESET}  "
                  f"ENR = {enr_db:.1f} dB")
        else:
            print(f"  [{i+1}/{len(freqs)}] {freq_mhz:.3f} MHz  ENR = {enr_db:.1f} dB")

        # Cold measurement
        if not args.auto:
            _prompt(f"  → Noise source OFF (cold).  Press Enter to capture: ")
        else:
            print(f"  → Cold measurement (noise source should be OFF)")

        try:
            p_cold = _capture_power(kiwi, freq_hz, args.samples, "cold")
        except KiwiSDRError as e:
            print(f"  ERROR capturing cold: {e}  — skipping frequency")
            continue
        if stop:
            break

        # Hot measurement
        if not args.auto:
            _prompt(f"  → Noise source ON  (hot).  Press Enter to capture: ")
        else:
            print(f"  → Hot measurement (noise source should be ON)")

        try:
            p_hot = _capture_power(kiwi, freq_hz, args.samples, "hot")
        except KiwiSDRError as e:
            print(f"  ERROR capturing hot: {e}  — skipping frequency")
            continue
        if stop:
            break

        # Calculate NF
        y_db, y_lin, nf_db = _compute_nf(p_hot, p_cold, enr_db)

        ts_utc = datetime.now(timezone.utc).isoformat()
        result = {
            "freq_hz":    freq_hz,
            "freq_mhz":   round(freq_mhz, 6),
            "enr_db":     round(enr_db, 2),
            "p_cold_dbfs": round(p_cold, 3),
            "p_hot_dbfs":  round(p_hot, 3),
            "y_factor_db": round(y_db, 3),
            "nf_db":       round(nf_db, 2) if not math.isnan(nf_db) else float("nan"),
            "ts_utc":      ts_utc,
        }
        results.append(result)
        _log_measurement(conn, freq_hz, enr_db, p_cold, p_hot, y_db, nf_db)

        # Per-frequency result
        if math.isnan(nf_db):
            nf_line = f"{RED}INVALID (Y={y_lin:.4f} ≤ 1){RESET}" if use_color \
                      else f"INVALID (Y={y_lin:.4f} ≤ 1)"
        else:
            nf_line = f"{GREEN}{nf_db:+.2f} dB{RESET}" if use_color else f"{nf_db:+.2f} dB"
        print(f"  Result: Y = {y_db:+.2f} dB  →  NF = {nf_line}")
        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    kiwi.close()
    conn.close()

    if results:
        _print_summary(results, use_color)

        if args.csv:
            csv_path = args.log.replace(".db", ".csv") if args.log.endswith(".db") \
                       else args.log + ".csv"
            try:
                _write_csv(csv_path, results)
                print(f"\n  CSV written: {csv_path}")
            except OSError as e:
                print(f"  WARNING: CSV write failed: {e}")

    print(f"\n  Database: {args.log}")
    if stop:
        print(f"  (interrupted)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Noise Figure Measurement — KiwiSDR Y-factor method",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Y-factor formula:
  Y_dB   = P_hot_dBFS - P_cold_dBFS
  NF_dB  = ENR_dB - 10*log10(10^(Y_dB/10) - 1)

Invalid result (Y ≤ 1) means:
  • Noise source ENR is too low for the DUT's noise figure
  • External RFI contaminated the cold measurement
  • Noise source not actually switching between measurements

ENR file format (CSV, no header needed):
  3500000,14.8
  7000000,15.1
  14000000,15.3
  21000000,15.2
  28000000,14.9

Examples:
  python noise_figure.py
  python noise_figure.py --enr 14.5 --freqs 7000000,14000000,28000000
  python noise_figure.py --enr-file noise_source_cal.csv --samples 60000
  python noise_figure.py --auto --csv
        """,
    )

    # Connection
    p.add_argument("--host",     default="kiwisdr.local",
                   help="KiwiSDR hostname or IP (default: kiwisdr.local)")
    p.add_argument("--port",     type=int, default=8073,
                   help="KiwiSDR port (default: 8073)")
    p.add_argument("--password", default="",
                   help="KiwiSDR password (default: empty)")

    # Test parameters
    default_freqs = ",".join(str(f) for f in DEFAULT_FREQS)
    p.add_argument("--freqs",    default=default_freqs,
                   help="Test frequencies in Hz, comma-separated "
                        "(default: 3.5/7/14/21/28 MHz)")
    p.add_argument("--enr",      type=float, default=15.0,
                   help="Flat ENR of noise source in dB (default: 15.0)")
    p.add_argument("--enr-file", default=None, dest="enr_file",
                   help="CSV file with freq_hz,enr_db columns (overrides --enr)")
    p.add_argument("--samples",  type=int, default=120_000,
                   help="IQ samples per measurement (default: 120000 = 10s)")
    p.add_argument("--auto",     action="store_true",
                   help="No user prompts; assume noise source already switching")

    # Output
    p.add_argument("--log",      default="noise_figure.db",
                   help="SQLite output path (default: noise_figure.db)")
    p.add_argument("--csv",      action="store_true",
                   help="Also write CSV (auto-named from --log path)")
    p.add_argument("--no-color", action="store_true", dest="no_color",
                   help="Disable ANSI colours")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
