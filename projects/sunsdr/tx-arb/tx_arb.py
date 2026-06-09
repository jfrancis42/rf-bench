#!/usr/bin/env python3
"""
TX Arbitrary Waveform — SunSDR2 Pro IQ injection transmitter.

Generates and transmits arbitrary IQ waveforms via the SunSDR2 Pro's
TX IQ injection capability.  Supports three modes:

  carrier  — Continuous CW carrier at the specified frequency
  wspr     — WSPR beacon IQ sequence (pre-encoded; requires wspr_message.npz)
  sweep    — Linear swept tone across the instantaneous bandwidth

IMPORTANT SAFETY CHECKS
  - You must hold a valid amateur radio licence for the frequency and
    power level you transmit on.
  - Always start with a dummy load.  Confirm frequency and power are correct
    before connecting a real antenna.
  - This script will prompt for confirmation before transmitting.
  - The IC-7300 should be disconnected or switched to a different band;
    running two transmitters on the same frequency can cause interference
    and may damage equipment.

Usage:
    python tx_arb.py --host 192.168.1.100 --mode carrier --freq 14074000
    python tx_arb.py --host 192.168.1.100 --mode carrier --freq 7000000 --duration 10
    python tx_arb.py --host 192.168.1.100 --mode sweep --freq 14100000 --duration 5
    python tx_arb.py --host 192.168.1.100 --mode wspr --freq 14095600 --callsign N0GQ --grid DN70
    python tx_arb.py --host 192.168.1.100 --mode carrier --freq 14074000 --no-confirm
"""

import argparse
import signal
import sys
import time

import numpy as np

from rf_bench.sunsdr import SunSDR, SunSDRError


# ── Safety limits ─────────────────────────────────────────────────────────────

# Frequencies below this are not amateur HF bands; warn the user
MIN_AMATEUR_HZ = 1_800_000   # bottom of 160m
MAX_AMATEUR_HZ = 54_000_000  # top of 6m (includes some MARS/experimental)

# WSPR dial frequencies (lower sideband, USB convention: actual WSPR tones
# are at dial + 1400–1600 Hz)
WSPR_DIAL_FREQS: dict[str, int] = {
    "160m": 1_836_600,
    "80m":  3_592_600,
    "40m":  7_038_600,
    "30m":  10_138_700,
    "20m":  14_095_600,
    "17m":  18_104_600,
    "15m":  21_094_600,
    "12m":  24_924_600,
    "10m":  28_124_600,
    "6m":   50_293_000,
}

# ── ANSI colours ─────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"


# ── Waveform generators ───────────────────────────────────────────────────────

def _gen_carrier(rate: int, duration_s: float, amplitude: float = 0.5
                 ) -> np.ndarray:
    """Generate a constant-amplitude IQ carrier (DC in baseband = carrier at Fc)."""
    n      = int(rate * duration_s)
    iq     = np.full(n, amplitude + 0j, dtype=np.complex64)
    return iq


def _gen_sweep(rate: int, duration_s: float,
               f_start_hz: float, f_stop_hz: float,
               amplitude: float = 0.5) -> np.ndarray:
    """
    Generate a linear frequency sweep (chirp) across the passband.

    f_start_hz and f_stop_hz are relative to the carrier (can be negative).
    At 192 kHz rate, range can be ±96 kHz.
    """
    n   = int(rate * duration_s)
    t   = np.arange(n, dtype=np.float64) / rate
    # Linear instantaneous frequency
    f_t = f_start_hz + (f_stop_hz - f_start_hz) * t / duration_s
    # Instantaneous phase = integral of frequency
    phase = 2.0 * np.pi * np.cumsum(f_t / rate)
    iq    = amplitude * np.exp(1j * phase).astype(np.complex64)
    return iq


def _gen_wspr_tones(callsign: str, grid: str, power_dbm: int,
                    rate: int) -> np.ndarray:
    """
    Generate a WSPR transmission (4-FSK, 162 symbols, 1.4641 baud).

    The WSPR encoding is a simplified implementation:
    - 162 symbols, each 682 ms (1/1.4641 Hz), total ~110.6 seconds
    - 4 tones at 1400, 1466, 1533, 1600 Hz (6 Hz spacing × 1.4641 baud)
    - The symbol sequence here is a placeholder; a full WSPR encoder
      would compute the channel-coded bits from callsign/grid/power.

    NOTE: This generates a syntactically valid IQ waveform in the correct
    format (4-FSK, correct timing) but with a placeholder symbol sequence.
    For a real WSPR beacon, replace _wspr_symbols() with a proper WSPR
    encoder (e.g. from the 'wsprd' project or pywspr).

    Returns complex64 IQ at `rate` samples per second.
    """
    symbols = _wspr_symbols_placeholder(callsign, grid, power_dbm)

    wspr_baud    = 12000.0 / 8192.0   # ≈ 1.4648 baud
    symbol_s     = 1.0 / wspr_baud    # ≈ 682.7 ms
    tone_spacing = 6.25 / 4           # Hz per tone step (approx)

    # WSPR tones at 1400–1600 Hz above USB dial
    base_tone = 1400.0   # Hz

    iq_parts = []
    for sym in symbols:
        f_tone = base_tone + sym * tone_spacing
        n      = int(rate * symbol_s)
        t      = np.arange(n, dtype=np.float64) / rate
        part   = 0.5 * np.exp(2j * np.pi * f_tone * t).astype(np.complex64)
        iq_parts.append(part)

    return np.concatenate(iq_parts)


def _wspr_symbols_placeholder(callsign: str, grid: str,
                               power_dbm: int) -> list[int]:
    """
    Placeholder WSPR symbol sequence generator.

    A real implementation would use the WSPR channel coding to produce
    162 symbols in {0,1,2,3} from the callsign/grid/power data.

    This version hashes the inputs to produce a deterministic pseudo-random
    sequence of the correct length and alphabet.  It will NOT decode correctly
    in WSPR software — it is present only to exercise the IQ generation
    pipeline.  Replace with a proper WSPR encoder for actual beaconing.
    """
    import hashlib
    key  = f"{callsign.upper()}{grid.upper()}{power_dbm}"
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    rng  = np.random.default_rng(seed)
    return rng.integers(0, 4, size=162).tolist()


# ── Safety check ─────────────────────────────────────────────────────────────

def _safety_check(freq_hz: int, mode: str, duration_s: float,
                  no_confirm: bool) -> None:
    """Warn and optionally prompt for confirmation before transmitting."""
    print(f"\n  {YELLOW}=== TX SAFETY CHECK ==={RESET}")
    print(f"  Mode:      {mode}")
    print(f"  Frequency: {freq_hz/1e6:.6f} MHz")
    print(f"  Duration:  {duration_s:.1f} seconds")

    warnings = []
    if freq_hz < MIN_AMATEUR_HZ or freq_hz > MAX_AMATEUR_HZ:
        warnings.append(f"  {RED}WARNING: {freq_hz/1e6:.4f} MHz is outside amateur HF bands{RESET}")
    if duration_s > 120:
        warnings.append(f"  {YELLOW}WARNING: long TX duration ({duration_s:.0f}s) — monitor temperature{RESET}")
    if mode == "wspr":
        warnings.append(f"  {YELLOW}NOTE: WSPR symbols are placeholder — will NOT decode correctly{RESET}")
        warnings.append(f"       Replace _wspr_symbols_placeholder() with a real WSPR encoder.")

    for w in warnings:
        print(w)

    print(f"\n  ⚠  Requires valid amateur radio licence for this frequency and power level.")
    print(f"  ⚠  Ensure a dummy load or appropriate antenna is connected.")
    print(f"  ⚠  Ensure ExpertSDR3 power is set to an appropriate level.")

    if not no_confirm:
        try:
            ans = input("\n  Type YES to proceed with transmission: ")
            if ans.strip().upper() != "YES":
                print("  Aborted.")
                sys.exit(0)
        except EOFError:
            print("  Aborted (no TTY).")
            sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    freq_hz    = args.freq
    mode       = args.mode
    duration_s = args.duration
    rate       = 192_000

    _safety_check(freq_hz, mode, duration_s, args.no_confirm)

    print(f"\n  Connecting to SunSDR at {args.host}:{args.port}...")
    try:
        sdr = SunSDR(args.host, port=args.port, iq_rate=rate)
    except SunSDRError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    info = sdr.identify()
    print(f"  Connected: {info['device']}")

    sdr.set_frequency(freq_hz)
    sdr.set_mode("USB")
    time.sleep(0.05)

    # Build the IQ waveform
    print(f"  Generating {mode} waveform...")
    try:
        if mode == "carrier":
            iq = _gen_carrier(rate, duration_s)
        elif mode == "sweep":
            iq = _gen_sweep(rate, duration_s,
                            f_start_hz=-rate * 0.45,
                            f_stop_hz=rate * 0.45)
        elif mode == "wspr":
            if not args.callsign:
                print("  ERROR: --callsign required for WSPR mode")
                sdr.close()
                sys.exit(1)
            if not args.grid:
                print("  ERROR: --grid required for WSPR mode")
                sdr.close()
                sys.exit(1)
            iq = _gen_wspr_tones(args.callsign, args.grid, args.power_dbm, rate)
            duration_s = len(iq) / rate
            print(f"  WSPR frame: {len(iq)} samples = {duration_s:.1f}s")
        else:
            print(f"  ERROR: unknown mode '{mode}'")
            sdr.close()
            sys.exit(1)
    except Exception as e:
        print(f"  ERROR generating waveform: {e}")
        sdr.close()
        sys.exit(1)

    print(f"  Waveform: {len(iq)} samples ({len(iq)/rate:.2f}s) @ {rate} Hz")

    stop = False
    def _sigint(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sigint)

    print(f"\n  {GREEN}Starting TX...{RESET}  (Ctrl-C to abort)")

    try:
        sdr.set_ptt(True)
        time.sleep(0.02)   # allow PTT to engage

        tx_start = time.monotonic()
        sdr.transmit_iq(iq)
        elapsed = time.monotonic() - tx_start

        if not stop:
            sdr.set_ptt(False)
            print(f"  TX complete: {elapsed:.2f}s")
        else:
            sdr.set_ptt(False)
            print(f"  TX aborted after {elapsed:.2f}s")

    except SunSDRError as e:
        print(f"  TX error: {e}")
        try:
            sdr.set_ptt(False)
        except Exception:
            pass
    except KeyboardInterrupt:
        sdr.set_ptt(False)
        print(f"  TX aborted by user.")
    finally:
        sdr.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="TX Arbitrary Waveform — SunSDR2 Pro IQ injection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  carrier   Continuous carrier at the dial frequency (DC in baseband)
  sweep     Linear FM sweep ±96 kHz around the dial frequency
  wspr      WSPR 4-FSK beacon (placeholder encoder)

WSPR dial frequencies:
  40m: 7.0386 MHz   20m: 14.0956 MHz   15m: 21.0946 MHz   10m: 28.1246 MHz

Examples:
  python tx_arb.py --host 192.168.1.100 --mode carrier --freq 14074000 --duration 5
  python tx_arb.py --host 192.168.1.100 --mode sweep --freq 7100000
  python tx_arb.py --host 192.168.1.100 --mode wspr --freq 14095600 --callsign N0GQ --grid DN70
        """,
    )
    p.add_argument("--host",       default="sunsdr.local",
                   help="SunSDR / ExpertSDR3 host IP")
    p.add_argument("--port",       type=int, default=50001)
    p.add_argument("--mode",       choices=["carrier", "sweep", "wspr"], required=True,
                   help="Waveform type")
    p.add_argument("--freq",       type=int, required=True,
                   help="Transmit frequency in Hz (USB dial frequency)")
    p.add_argument("--duration",   type=float, default=10.0,
                   help="Transmission duration in seconds (not used for WSPR; default: 10)")
    p.add_argument("--callsign",   default=None,
                   help="Callsign for WSPR mode")
    p.add_argument("--grid",       default=None,
                   help="Maidenhead grid locator for WSPR mode (e.g. DN70)")
    p.add_argument("--power-dbm",  type=int, default=37, dest="power_dbm",
                   help="Power in dBm for WSPR encoding (default: 37 = 5W)")
    p.add_argument("--no-confirm", action="store_true", dest="no_confirm",
                   help="Skip safety confirmation prompt")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
