#!/usr/bin/env -S python3 -u
"""
OOK ASCII Link — Flipper Zero TX / RTL-SDR RX

Sends ASCII text from the Flipper Zero's CC1101 and decodes it on the RTL-SDR.
Uses 1200-baud OOK (On-Off Keying) with UART framing: one start bit, eight
data bits (LSB first), one stop bit per byte.

Encoding:
  carrier ON  = logic 1 (idle / stop bit)
  carrier OFF = logic 0 (start bit / data 0)
  bit period  = 833 µs at 1200 baud

Frame format (before each message):
  32-bit preamble of alternating 1/0 for receiver AGC and clock sync
  0xAA 0x55 sync word (reliable falling-edge pattern)
  ASCII payload bytes
  0x04 (EOT) terminator

Usage:
  python ook_link.py tx "Hello World"        # send via Flipper on /dev/ttyACM0
  python ook_link.py rx                      # receive on RTL-SDR
  python ook_link.py tx "Hi" --repeat 3     # repeat for reliability
  python ook_link.py rx --freq 433.92        # explicit frequency in MHz
"""

import argparse
import sys
import time
from typing import Optional

import numpy as np

BAUD        = 1200
BIT_US      = int(1_000_000 / BAUD)   # 833 µs
FREQ_HZ     = 433_920_000             # default ISM frequency
SAMPLE_RATE = 1_200_000               # RTL-SDR sample rate (240 kHz too low for R820T)
IF_OFFSET   = 200_000                 # Hz; tune SDR this far above carrier, mix down in SW
DECIMATE    = 100                     # 1.2 MS/s → 12 kS/s (20 dB noise bandwidth reduction)

SYNC_BYTES  = bytes([0xAA, 0x55])
EOT         = 0x04                    # end-of-transmission marker

# ---------------------------------------------------------------------------
# Encoding — convert text to OOK pulse timings for Flipper .sub RAW_Data
# ---------------------------------------------------------------------------

def _encode_byte(byte: int) -> list[tuple[bool, int]]:
    """Return (level, duration_µs) pairs for one UART byte."""
    bits = []
    bits.append((False, BIT_US))          # start bit (logic 0 = carrier off)
    for i in range(8):
        bits.append((bool(byte & (1 << i)), BIT_US))  # LSB first
    bits.append((True, BIT_US))           # stop bit (logic 1 = carrier on)
    return bits


def encode_message(text: str) -> list[int]:
    """
    Encode an ASCII string as OOK pulse timings (in µs) suitable for the
    Flipper .sub RAW_Data field.

    Returns a list of integers where positive = carrier ON and negative = OFF.
    """
    # Build a sequence of (level, duration) pairs
    pairs: list[tuple[bool, int]] = []

    # Idle high (carrier ON) before preamble — lets the RTL-SDR AGC settle
    pairs.append((True, BIT_US * 20))

    # 32-bit preamble: alternating 1/0 for clock synchronisation
    for i in range(32):
        pairs.append((bool(i % 2), BIT_US))

    # Idle
    pairs.append((True, BIT_US * 4))

    # Sync word + payload + EOT
    for byte in list(SYNC_BYTES) + [ord(c) for c in text] + [EOT]:
        pairs.extend(_encode_byte(byte))
        pairs.append((True, BIT_US))      # brief inter-byte idle

    # Tail idle
    pairs.append((True, BIT_US * 20))

    # Merge consecutive same-level spans into a single timing value
    timings: list[int] = []
    current_level, current_us = pairs[0]
    for level, us in pairs[1:]:
        if level == current_level:
            current_us += us
        else:
            timings.append(current_us if current_level else -current_us)
            current_level, current_us = level, us
    timings.append(current_us if current_level else -current_us)

    return timings


# ---------------------------------------------------------------------------
# TX — Flipper Zero
# ---------------------------------------------------------------------------

def transmit(text: str, serial: str, freq_hz: int, repeat: int) -> None:
    from rf_bench.flipper import FlipperZero, FlipperError

    timings = encode_message(text)
    total_us = sum(abs(t) for t in timings)
    n_bytes = len(text) + len(SYNC_BYTES) + 1  # +1 for EOT

    print(f"Encoding {len(text)} chars ({n_bytes} bytes including sync/EOT)")
    print(f"  {len(timings)} timing edges  {total_us/1e6:.3f} s per transmission")
    print(f"  Baud: {BAUD}  Bit period: {BIT_US} µs  Freq: {freq_hz/1e6:.3f} MHz")

    print(f"\nConnecting to Flipper @ {serial} ...")
    with FlipperZero(serial) as fz:
        print(f"  Firmware: {fz.firmware_fork}  ({fz.identify().get('firmware_version','?')})")
        if not fz.uses_carrier_commands:
            # Momentum/forks: use CLI tx_from_file path
            _transmit_via_cli(fz, text, freq_hz, repeat)
        else:
            for i in range(repeat):
                if repeat > 1:
                    print(f"\nTransmission {i+1}/{repeat} ...")
                fz.subghz_transmit_raw(freq_hz, timings, preset="ook650", repeat=1)
                print("  Sent.")
                if i < repeat - 1:
                    time.sleep(1.0)


def _transmit_via_cli(fz, text: str, freq_hz: int, repeat: int) -> None:
    """Write .sub file via RPC storage then play via CLI tx_from_file (Momentum)."""
    timings = encode_message(text)

    raw_vals = [abs(int(t)) if i % 2 == 0 else -abs(int(t))
                for i, t in enumerate(timings)]
    raw_str = " ".join(str(v) for v in raw_vals)

    preset_map = {
        "ook270": "FuriHalSubGhzPresetOok270Async",
        "ook650": "FuriHalSubGhzPresetOok650Async",
    }
    content = (
        "Filetype: Flipper SubGhz RAW File\n"
        "Version: 1\n"
        f"Frequency: {freq_hz}\n"
        f"Preset: {preset_map['ook650']}\n"
        "Protocol: RAW\n"
        f"RAW_Data: {raw_str}\n"
    )

    path = "/ext/bench/ook_link.sub"
    # Write the .sub file via RPC, then switch back to CLI to run tx_from_file.
    # _rpc_write_file leaves the driver in RPC mode; _ensure_cli sends the
    # stop_session message to return to the CLI prompt.  _flush_cli re-syncs
    # the CLI state (sends \r, waits for ">: ") to clear any residual data.
    fz._rpc_write_file(path, content.encode())
    fz._ensure_cli()
    fz._flush_cli()

    for i in range(repeat):
        if repeat > 1:
            print(f"\nTransmission {i+1}/{repeat} ...")
        resp = fz._cli_send(f"subghz tx_from_file {path} 1 0", timeout=15.0)
        import re as _re
        clean = _re.sub(r'\x1b\[[0-9;]*m', '', resp).strip()
        if "restricted" in clean.lower():
            print(f"  ERROR: Flipper blocked TX — sub-GHz transmission is region-locked.")
            print(f"  Fix: on the Flipper go to Settings → Sub-GHz → Bypass Region Lock")
            break
        print(f"  Sent.")
        if i < repeat - 1:
            time.sleep(1.0)


# ---------------------------------------------------------------------------
# RX — RTL-SDR demodulator
# ---------------------------------------------------------------------------

def receive(freq_hz: int, gain: float, duration_s: Optional[float],
            threshold_frac: float) -> None:
    """
    Listen on the RTL-SDR, demodulate OOK, decode UART bytes.

    Tunes IF_OFFSET Hz above the carrier, mixes down in software, and
    decimates by DECIMATE to a ~12 kHz channel.  This rejects out-of-band
    ISM interference before envelope detection, giving ~20 dB better SNR in
    congested 433 MHz bands.

    threshold_frac: fraction between noise floor (0.0) and signal peak (1.0).
                    Default 0.5 works well; raise to 0.7 in noisy environments.
    """
    from rf_bench.rtlsdr import RTLSDR, RTLSDRError

    fs_dec  = SAMPLE_RATE / DECIMATE      # decimated sample rate (12 kHz)
    spb     = fs_dec / BAUD               # samples per bit after decimation (10.0)
    block   = int(SAMPLE_RATE * 0.5)      # requested raw block (~500 ms)

    print(f"RTL-SDR listening on {freq_hz/1e6:.3f} MHz  gain={gain} dB")
    print(f"  IF offset: +{IF_OFFSET/1e3:.0f} kHz  decimation: {DECIMATE}x  "
          f"channel BW: {fs_dec/1e3:.0f} kHz")
    print(f"  {BAUD} baud  {spb:.0f} samples/bit  Ctrl-C to stop\n")

    ring         = None
    block_dec    = None                   # decimated block size (set on first block)
    sample_off   = 0                      # running sample offset for phase-continuous mixing
    running      = True

    import signal as _sig
    def _stop(_s, _f):
        nonlocal running
        running = False
    _sig.signal(_sig.SIGINT, _stop)

    # Phase step per raw sample for the IF mix-down.
    # RTL-SDR tunes to freq_hz + IF_OFFSET, so the carrier appears at -IF_OFFSET
    # in baseband.  Multiplying by exp(+j*2*pi*IF_OFFSET*t) upshifts it to 0 Hz.
    phase_step = +2.0 * np.pi * IF_OFFSET / SAMPLE_RATE

    with RTLSDR() as sdr:
        sdr.set_center_freq(freq_hz + IF_OFFSET)   # tune above carrier
        sdr.set_sample_rate(SAMPLE_RATE)
        sdr.set_gain(gain)

        start_t = time.time()
        for raw_iq in sdr.stream_iq(block_size=block):
            if not running:
                break
            if duration_s and (time.time() - start_t) > duration_s:
                break

            n = len(raw_iq)

            # Mix: shift the carrier from +IF_OFFSET down to 0 Hz
            mix = np.exp(1j * phase_step *
                         np.arange(sample_off, sample_off + n,
                                   dtype=np.float32)).astype(np.complex64)
            mixed = raw_iq * mix
            sample_off += n

            # Decimate: mean of every DECIMATE samples (boxcar LPF + downsample)
            n_out = n // DECIMATE
            if n_out == 0:
                continue
            dec = (mixed[:n_out * DECIMATE]
                   .reshape(n_out, DECIMATE)
                   .mean(axis=1)
                   .astype(np.complex64))

            # Initialise ring buffer from first actual decimated block size
            actual = len(dec)
            if ring is None:
                ring       = np.zeros(actual * 2, dtype=np.complex64)
                block_dec  = actual

            # Shift ring buffer and insert new decimated block
            ring[:block_dec] = ring[block_dec:]
            ring[block_dec:] = dec

            # OOK demodulation: AM envelope
            env = np.abs(ring).astype(np.float32)

            # Adaptive threshold between noise floor and signal level
            lo = float(np.percentile(env, 10))
            hi = float(np.percentile(env, 90))
            if hi - lo < lo * 0.1:
                continue
            thresh = lo + (hi - lo) * threshold_frac
            bits = (env > thresh).astype(np.int8)

            _decode_uart_stream(bits, spb, new_start=block_dec)

    print("\nDone.")


def _decode_uart_stream(bits: np.ndarray, spb: float, new_start: int = 0) -> None:
    """
    Find UART frames in a binary signal and print decoded bytes.

    Looks for start bits (1→0 falling edges) then samples 8 data bits and
    one stop bit at the centre of each bit period.

    new_start: only report messages whose sync word's start bit falls at or
               after this index.  When decoding a 2-block ring buffer, pass
               new_start=block so messages in the old half (already reported
               in the previous iteration) are not printed again.
    """
    edges = np.where(np.diff(bits.astype(np.int16)) == -1)[0]

    # List of (byte_value, start_bit_position) for each decoded byte
    decoded: list[tuple[int, int]] = []
    skip_before = 0

    for edge in edges:
        if edge < skip_before:
            continue

        start = edge
        mid0 = int(start + 0.5 * spb)
        if mid0 >= len(bits) or bits[mid0] != 0:
            continue

        byte_val = 0
        for bit_no in range(8):
            pos = int(start + (1.5 + bit_no) * spb)
            if pos >= len(bits):
                byte_val = None
                break
            if bits[pos]:
                byte_val |= (1 << bit_no)

        if byte_val is None:
            continue

        stop_pos = int(start + 9.5 * spb)
        if stop_pos >= len(bits) or bits[stop_pos] == 0:
            skip_before = int(start + spb)
            continue

        decoded.append((byte_val, start))
        skip_before = int(start + 10 * spb)

    if not decoded:
        return

    raw = bytes(v for v, _ in decoded)
    sync = bytes([0xAA, 0x55])

    search_from = 0
    while True:
        idx = raw.find(sync, search_from)
        if idx == -1:
            break

        # Only report this message if its sync word starts in the new half
        # of the ring buffer (avoids printing the same message twice when
        # it shifts from the new half into the old half next iteration).
        sync_ring_pos = decoded[idx][1]
        if sync_ring_pos < new_start:
            search_from = idx + 1
            continue

        payload = raw[idx + len(sync):]
        eot = payload.find(EOT)
        if eot != -1:
            payload = payload[:eot]

        if payload:
            text = payload.decode("ascii", errors="replace")
            print(f"RX: {text!r}")

        search_from = idx + 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    global BAUD, BIT_US  # allow --baud to override module-level constants
    ap = argparse.ArgumentParser(
        description="OOK ASCII link: Flipper Zero TX ↔ RTL-SDR RX",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ook_link.py tx "Hello"          # send from Flipper
  python ook_link.py rx                  # receive on RTL-SDR
  python ook_link.py tx "Hi" --repeat 5 # repeat for reliability
  python ook_link.py rx --gain 30        # lower gain if saturating
""")
    ap.add_argument("mode", choices=["tx", "rx"],
                    help="tx = transmit via Flipper, rx = receive via RTL-SDR")
    ap.add_argument("text", nargs="?", default="",
                    help="ASCII text to send (tx mode only)")

    ap.add_argument("--freq",      type=float, default=FREQ_HZ / 1e6, metavar="MHZ",
                    help=f"Frequency in MHz (default: {FREQ_HZ/1e6})")
    ap.add_argument("--baud",      type=int,   default=BAUD,
                    help=f"Baud rate (default: {BAUD})")
    ap.add_argument("--repeat",    type=int,   default=1,
                    help="Number of times to repeat transmission (default: 1)")
    ap.add_argument("--gain",      type=float, default=40,
                    help="RTL-SDR gain in dB (default: 40)")
    ap.add_argument("--duration",  type=float, default=None, metavar="SECS",
                    help="RX duration in seconds (default: until Ctrl-C)")
    ap.add_argument("--threshold", type=float, default=0.5, metavar="FRAC",
                    help="OOK detection threshold 0.0–1.0 (default: 0.5)")
    ap.add_argument("--serial",    default="/dev/ttyACM0",
                    help="Flipper serial port (default: /dev/ttyACM0)")

    args = ap.parse_args()

    freq_hz = int(args.freq * 1e6)

    if args.baud != BAUD:
        BAUD   = args.baud
        BIT_US = int(1_000_000 / BAUD)

    if args.mode == "tx":
        if not args.text:
            ap.error("tx mode requires a text argument")
        transmit(args.text, args.serial, freq_hz, args.repeat)

    elif args.mode == "rx":
        receive(freq_hz, args.gain, args.duration, args.threshold)


if __name__ == "__main__":
    main()
