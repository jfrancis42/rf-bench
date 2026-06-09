#!/usr/bin/env python3
"""
HF Spectrum Comparison — KiwiSDR vs SunSDR2 Pro simultaneous band scan.

Sweeps both the KiwiSDR and SunSDR2 Pro over the same HF band(s) simultaneously.
Compares:
  - Signal detections: present on one receiver but not the other
  - Relative signal strengths: level difference between receivers
  - Noise floor: per-band noise floor comparison

Useful for:
  - Antenna A/B comparison (different antenna on each receiver)
  - Verifying SunSDR driver amplitude accuracy vs. KiwiSDR's GPS-referenced signal path
  - Identifying local interference visible on one antenna/receiver but not the other

Usage:
    python hf_compare.py --sdr-host 192.168.1.100 --kiwi-host kiwisdr.local --bands 40m,20m
    python hf_compare.py --sdr-host 192.168.1.100 --kiwi-host 10.1.0.5 --bands all
    python hf_compare.py --sdr-host 192.168.1.100 --kiwi-host 10.1.0.5 --loop
"""

import argparse
import sys
import time
from collections import defaultdict

import numpy as np

from rf_bench.kiwisdr import KiwiSDR, KiwiSDRError
from rf_bench.sunsdr import SunSDR, SunSDRError


# ── Band definitions ──────────────────────────────────────────────────────────

AMATEUR_BANDS: dict[str, tuple[int, int]] = {
    "160m": (1_800_000,  2_000_000),
    "80m":  (3_500_000,  4_000_000),
    "40m":  (7_000_000,  7_300_000),
    "30m":  (10_100_000, 10_150_000),
    "20m":  (14_000_000, 14_350_000),
    "17m":  (18_068_000, 18_168_000),
    "15m":  (21_000_000, 21_450_000),
    "12m":  (24_890_000, 24_990_000),
    "10m":  (28_000_000, 29_700_000),
}

KIWI_RATE    = 12_000
SUNSDR_RATE  = 192_000
KIWI_SAMPLES = 4_096    # ~340 ms per KiwiSDR step
SUNSDR_STEP  = 192_000  # Hz step for SunSDR (one IQ bandwidth width)
KIWI_STEP    = 10_000   # Hz step for KiwiSDR (one passband width)
SQUELCH_DB   = 10.0

# ── ANSI colours ─────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"


# ── IQ analysis ───────────────────────────────────────────────────────────────

def _scan_step(iq: np.ndarray, center_hz: int, rate: int,
               squelch_db: float) -> tuple[list[dict], float]:
    """Detect signals and return (detections, noise_dbfs)."""
    n      = len(iq)
    window = np.hanning(n).astype(np.float32)
    fft_db = 10.0 * np.log10(
        np.maximum(np.abs(np.fft.fftshift(np.fft.fft(iq * window))) ** 2
                   / np.sum(window ** 2), 1e-30)
    ).astype(np.float32)
    freq_r = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / rate))
    noise  = float(np.median(fft_db))
    above  = (fft_db - noise) >= squelch_db
    freq_a = freq_r + center_hz

    signals = []
    in_sig, start = False, 0
    for i, flag in enumerate(above):
        if flag and not in_sig:
            start, in_sig = i, True
        elif not flag and in_sig:
            mid = (start + i) // 2
            signals.append({
                "freq_hz": int(freq_a[mid]),
                "snr_db":  round(float(fft_db[mid]) - noise, 2),
            })
            in_sig = False
    if in_sig:
        mid = (start + len(above)) // 2
        signals.append({
            "freq_hz": int(freq_a[mid]),
            "snr_db":  round(float(fft_db[mid]) - noise, 2),
        })
    return signals, noise


def _scan_band_sdr(sdr: SunSDR, lo: int, hi: int,
                   squelch_db: float) -> tuple[list[dict], list[float]]:
    """Sweep band with SunSDR, return (all_detections, noise_samples)."""
    all_det = []
    noises  = []
    freq    = lo
    while freq <= hi:
        try:
            sdr.set_frequency(freq)
            time.sleep(0.025)
            iq   = sdr.capture_iq(48_000)   # 250 ms
            hits, noise = _scan_step(iq, freq, SUNSDR_RATE, squelch_db)
            all_det.extend(hits)
            noises.append(noise)
        except SunSDRError:
            pass
        freq += SUNSDR_STEP
    return all_det, noises


def _scan_band_kiwi(kiwi: KiwiSDR, lo: int, hi: int,
                    squelch_db: float) -> tuple[list[dict], list[float]]:
    """Sweep band with KiwiSDR, return (all_detections, noise_samples)."""
    all_det = []
    noises  = []
    freq    = lo
    while freq <= hi:
        try:
            kiwi.set_center_freq(freq)
            time.sleep(0.04)
            iq   = kiwi.capture_iq(KIWI_SAMPLES)
            hits, noise = _scan_step(iq, freq, KIWI_RATE, squelch_db)
            all_det.extend(hits)
            noises.append(noise)
        except KiwiSDRError:
            pass
        freq += KIWI_STEP
    return all_det, noises


# ── Comparison analysis ───────────────────────────────────────────────────────

def _cluster_signals(signals: list[dict], cluster_hz: int = 5_000
                     ) -> dict[int, float]:
    """Cluster signals by frequency proximity.  Returns {rounded_freq_hz: max_snr}."""
    clusters: dict[int, float] = {}
    for sig in sorted(signals, key=lambda x: x["freq_hz"]):
        f = sig["freq_hz"]
        # Find nearest cluster
        best_key = None
        best_dist = cluster_hz + 1
        for k in clusters:
            dist = abs(k - f)
            if dist < best_dist:
                best_dist = dist
                best_key = k
        if best_key is not None and best_dist <= cluster_hz:
            clusters[best_key] = max(clusters[best_key], sig["snr_db"])
        else:
            clusters[f] = sig["snr_db"]
    return clusters


def _compare(sdr_sigs: dict[int, float], kiwi_sigs: dict[int, float],
             tolerance_hz: int = 10_000) -> dict:
    """Produce comparison report."""
    both:      list[dict] = []
    sdr_only:  list[dict] = []
    kiwi_only: list[dict] = []

    matched_kiwi = set()
    for sf, ss in sorted(sdr_sigs.items()):
        match = None
        for kf in kiwi_sigs:
            if abs(kf - sf) <= tolerance_hz and kf not in matched_kiwi:
                match = kf
                break
        if match is not None:
            both.append({
                "freq_hz":    sf,
                "sdr_snr":    ss,
                "kiwi_snr":   kiwi_sigs[match],
                "diff_db":    round(ss - kiwi_sigs[match], 1),
            })
            matched_kiwi.add(match)
        else:
            sdr_only.append({"freq_hz": sf, "snr_db": ss})

    for kf, ks in sorted(kiwi_sigs.items()):
        if kf not in matched_kiwi:
            kiwi_only.append({"freq_hz": kf, "snr_db": ks})

    return {"both": both, "sdr_only": sdr_only, "kiwi_only": kiwi_only}


# ── Display ───────────────────────────────────────────────────────────────────

def _print_band_report(band_name: str, cmp: dict,
                       sdr_noise: float, kiwi_noise: float,
                       use_color: bool) -> None:
    rst  = RESET if use_color else ""
    bold = BOLD  if use_color else ""
    dim  = DIM   if use_color else ""

    print(f"\n  {bold}=== {band_name} ==={rst}")
    print(f"  Noise floor  SunSDR: {sdr_noise:+.1f} dBFS  "
          f"KiwiSDR: {kiwi_noise:+.1f} dBFS  "
          f"diff: {sdr_noise - kiwi_noise:+.1f} dB")

    n_both  = len(cmp["both"])
    n_sonly = len(cmp["sdr_only"])
    n_konly = len(cmp["kiwi_only"])
    print(f"  Signals: {n_both} on both, "
          f"{n_sonly} SunSDR-only, "
          f"{n_konly} KiwiSDR-only")

    if cmp["both"]:
        print(f"\n  Seen on both receivers:")
        print(f"  {'Freq (MHz)':>11}  {'SunSDR SNR':>12}  {'KiwiSDR SNR':>12}  {'Diff':>7}")
        print(f"  {'─'*46}")
        for s in sorted(cmp["both"], key=lambda x: x["freq_hz"]):
            col = YELLOW if use_color and abs(s["diff_db"]) > 10 else ""
            print(f"  {col}{s['freq_hz']/1e6:>11.4f}  "
                  f"{s['sdr_snr']:>+11.1f}  "
                  f"{s['kiwi_snr']:>+11.1f}  "
                  f"{s['diff_db']:>+7.1f}{rst}")

    if cmp["sdr_only"]:
        col = GREEN if use_color else ""
        print(f"\n  {col}SunSDR only:{rst}")
        for s in sorted(cmp["sdr_only"], key=lambda x: x["freq_hz"]):
            print(f"    {s['freq_hz']/1e6:.4f} MHz  SNR {s['snr_db']:+.1f} dB")

    if cmp["kiwi_only"]:
        col = CYAN if use_color else ""
        print(f"\n  {col}KiwiSDR only:{rst}")
        for s in sorted(cmp["kiwi_only"], key=lambda x: x["freq_hz"]):
            print(f"    {s['freq_hz']/1e6:.4f} MHz  SNR {s['snr_db']:+.1f} dB")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    use_color = not args.no_color and sys.stdout.isatty()

    if args.bands == "all":
        band_list = list(AMATEUR_BANDS.keys())
    else:
        band_list = [b.strip().lower() for b in args.bands.split(",")]
        for name in band_list:
            if name not in AMATEUR_BANDS:
                print(f"Unknown band: {name}")
                sys.exit(1)

    print(f"\n  HF Spectrum Comparison — KiwiSDR vs SunSDR2 Pro")
    print(f"  SunSDR:  {args.sdr_host}:{args.sdr_port}")
    print(f"  KiwiSDR: {args.kiwi_host}:{args.kiwi_port}")
    print(f"  Bands: {', '.join(band_list)}")
    print(f"  Squelch: +{args.squelch:.0f} dB")
    print()

    print(f"  Connecting to KiwiSDR...")
    try:
        kiwi = KiwiSDR(args.kiwi_host, port=args.kiwi_port, channel=0,
                       passband_hz=10_000)
        print(f"  KiwiSDR connected.")
    except KiwiSDRError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    print(f"  Connecting to SunSDR...")
    try:
        sdr = SunSDR(args.sdr_host, port=args.sdr_port, iq_rate=SUNSDR_RATE)
        print(f"  SunSDR connected: {sdr.identify()['device']}")
    except SunSDRError as e:
        print(f"  ERROR: {e}")
        kiwi.close()
        sys.exit(1)

    sdr.set_mode("USB")
    cycle = 0

    try:
        while True:
            cycle += 1
            print(f"\n  Cycle {cycle}  —  {__import__('datetime').datetime.now().strftime('%H:%M:%S')}")

            for band_name in band_list:
                lo, hi = AMATEUR_BANDS[band_name]
                print(f"  Scanning {band_name} ({lo/1e6:.3f}–{hi/1e6:.3f} MHz)...", end="", flush=True)

                # Scan both receivers
                sdr_det, sdr_noises  = _scan_band_sdr(sdr, lo, hi, args.squelch)
                kiwi_det, kiwi_noises = _scan_band_kiwi(kiwi, lo, hi, args.squelch)
                print(f" done.")

                # Cluster and compare
                sdr_clusters  = _cluster_signals(sdr_det)
                kiwi_clusters = _cluster_signals(kiwi_det)
                cmp           = _compare(sdr_clusters, kiwi_clusters)

                sdr_noise_avg  = float(np.mean(sdr_noises))  if sdr_noises  else float("nan")
                kiwi_noise_avg = float(np.mean(kiwi_noises)) if kiwi_noises else float("nan")

                _print_band_report(band_name, cmp, sdr_noise_avg, kiwi_noise_avg, use_color)

            if not args.loop:
                break
            print(f"\n  Waiting {args.interval}s before next cycle...")
            time.sleep(args.interval)

    except KeyboardInterrupt:
        pass
    finally:
        kiwi.close()
        sdr.close()

    print(f"\n  Completed {cycle} sweep cycles.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="HF Spectrum Comparison — KiwiSDR vs SunSDR2 Pro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python hf_compare.py --sdr-host 192.168.1.100 --kiwi-host kiwisdr.local --bands 40m,20m
  python hf_compare.py --sdr-host 192.168.1.100 --kiwi-host 10.1.0.5 --bands all
  python hf_compare.py --sdr-host 192.168.1.100 --kiwi-host 10.1.0.5 --bands 40m --loop
        """,
    )
    p.add_argument("--sdr-host",   required=True, dest="sdr_host")
    p.add_argument("--sdr-port",   type=int, default=50001, dest="sdr_port")
    p.add_argument("--kiwi-host",  required=True, dest="kiwi_host")
    p.add_argument("--kiwi-port",  type=int, default=8073, dest="kiwi_port")
    p.add_argument("--bands",      default="40m,20m",
                   help="Comma-separated band names or 'all' (default: 40m,20m)")
    p.add_argument("--squelch",    type=float, default=SQUELCH_DB,
                   help=f"SNR threshold in dB (default: {SQUELCH_DB})")
    p.add_argument("--loop",       action="store_true",
                   help="Repeat sweeps continuously until Ctrl-C")
    p.add_argument("--interval",   type=float, default=30.0,
                   help="Pause between loop cycles in seconds (default: 30)")
    p.add_argument("--no-color",   action="store_true", dest="no_color")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
