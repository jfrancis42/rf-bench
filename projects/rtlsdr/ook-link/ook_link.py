#!/usr/bin/env -S python3 -u
"""
OOK ASCII Link — Flipper Zero TX / RTL-SDR RX

Sends ASCII text from the Flipper Zero's CC1101 and decodes it on the RTL-SDR.
Uses OOK (On-Off Keying) with async UART framing: one start bit, eight data
bits (LSB first), one stop bit per byte.

Encoding:
  carrier ON  = logic 1 (idle / stop bit)
  carrier OFF = logic 0 (start bit / data 0)

Baud rates (--baud):
  110   — ~27 dB above noise floor; ~16× more range than 1200 baud
  300   — ~18 dB above noise floor; ~8× more range than 1200 baud
  600   — ~12 dB above noise floor; ~4× more range than 1200 baud
  1200  — default; bit period 833 µs
  2400  — shorter range, higher throughput; requires good signal

Frame format:
  [preamble]  20-bit carrier ON (AGC settle) + 32-bit alternating (clock sync)
              + 4-bit carrier ON idle
  [sync]      0xAA 0x55
  [payload]   ASCII bytes
  [CRC]       CRC-16/CCITT, 2 bytes big-endian — garbled frames silently dropped
  [EOT]       0x04

Usage:
  python ook_link.py tx "Hello World"               # send via Flipper on /dev/ttyACM0
  python ook_link.py rx                             # receive on RTL-SDR
  python ook_link.py tx "CQ" --callsign N0GQ       # prepend callsign for ham ID
  python ook_link.py tx "Hi" --baud 300 --repeat 3 # slower baud, more range
  python ook_link.py rx --baud 300                  # receive at matching baud rate
"""

import argparse
import sys
import time
from typing import Optional

import numpy as np

BAUD        = 1200
BIT_US      = int(1_000_000 / BAUD)   # 833 µs
FREQ_HZ     = 433_920_000             # 433.92 MHz — ISM/70 cm (CC1101 factory-calibrated here)
SAMPLE_RATE = 1_200_000               # RTL-SDR sample rate (240 kHz too low for R820T)
IF_OFFSET   = 200_000                 # Hz; tune SDR this far above carrier, mix down in SW
DECIMATE    = 100                     # 1.2 MS/s → 12 kS/s (20 dB noise bandwidth reduction)

SYNC_BYTES  = bytes([0xAA, 0x55])
EOT         = 0x04                    # end-of-transmission marker

# CRC-16/CCITT-FALSE (poly=0x1021, init=0xFFFF) — appended before EOT for FEC
_CRC_POLY   = 0x1021
_CRC_INIT   = 0xFFFF

def _crc16(data: bytes) -> int:
    crc = _CRC_INIT
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ _CRC_POLY) if (crc & 0x8000) else (crc << 1)
        crc &= 0xFFFF
    return crc

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


BAUD_RATES  = [110, 300, 600, 1200, 2400]   # supported baud rates for --baud


def encode_message(text: str) -> list[int]:
    """
    Encode an ASCII string as OOK pulse timings (in µs) suitable for the
    Flipper .sub RAW_Data field.

    Returns a list of integers where positive = carrier ON and negative = OFF.
    """
    pairs: list[tuple[bool, int]] = []

    # Idle high before preamble — lets the RTL-SDR AGC settle (~16ms at 1200 bd)
    pairs.append((True, BIT_US * 20))
    # 32-bit alternating 1/0 for clock synchronisation
    for i in range(32):
        pairs.append((bool(i % 2), BIT_US))
    # Brief idle before sync word
    pairs.append((True, BIT_US * 4))

    # Sync word + payload + CRC-16 (big-endian) + EOT
    payload = text.encode('ascii')
    crc = _crc16(payload)
    packet = list(SYNC_BYTES) + list(payload) + [crc >> 8, crc & 0xFF] + [EOT]
    for byte in packet:
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

def transmit(text: str, serial: str, freq_hz: int, repeat: int,
             callsign: str = "") -> None:
    from rf_bench.flipper import FlipperZero, FlipperError

    # Prepend callsign ID so the frame is self-identifying (required for ham operation)
    if callsign:
        text = f"DE {callsign}: {text}"

    timings = encode_message(text)
    total_us = sum(abs(t) for t in timings)
    n_bytes = len(text) + len(SYNC_BYTES) + 2 + 1  # +2 CRC +1 EOT

    print(f"Encoding {len(text)} chars ({n_bytes} bytes including sync/CRC/EOT)")
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

def _decode_uart_chunk(bits: np.ndarray, spb: float,
                       start_from: int) -> tuple[list[int], int]:
    """
    Decode UART bytes from bits[start_from:].

    Returns (byte_list, next_start_from).  next_start_from advances past each
    complete byte so the caller can trim bits_buf and avoid re-decoding.
    Stops at the first byte whose data or stop bit is beyond the buffer end,
    so the caller can append more data and retry.
    """
    edges       = np.where(np.diff(bits.astype(np.int16)) == -1)[0]
    decoded:    list[int] = []
    skip_before = start_from
    next_pos    = start_from

    for edge in edges:
        if edge < skip_before:
            continue

        start = edge
        mid0  = int(start + 0.5 * spb)
        if mid0 >= len(bits):
            continue                             # not enough data yet; wait
        if bits[mid0] != 0:
            skip_before = start + 1             # definitively not a start bit; advance past it
            next_pos    = skip_before
            continue

        byte_val = 0
        for bit_no in range(8):
            pos = int(start + (1.5 + bit_no) * spb)
            if pos >= len(bits):
                return decoded, next_pos    # data bit beyond buffer; wait
            if bits[pos]:
                byte_val |= (1 << bit_no)

        stop_pos = int(start + 9.5 * spb)
        if stop_pos >= len(bits):
            return decoded, next_pos        # stop bit not yet received; wait

        if bits[stop_pos] == 0:
            skip_before = int(start + spb)
            next_pos    = skip_before
            continue

        decoded.append(byte_val)
        skip_before = int(start + 10 * spb)
        next_pos    = skip_before

    return decoded, next_pos


_MAX_PAYLOAD = 512   # bytes between sync and EOT before we give up on a sync word

def _drain_byte_fifo(byte_fifo: list[int]) -> list[int]:
    """
    Print all complete sync+payload+CRC+EOT messages in byte_fifo.
    Returns the unconsumed tail (incomplete message or possible partial sync).
    CRC-16 is validated; mismatches are silently discarded.
    """
    raw  = bytes(byte_fifo)
    sync = SYNC_BYTES
    pos  = 0

    while True:
        idx = raw.find(sync, pos)
        if idx == -1:
            trim_to = max(pos, len(raw) - (len(sync) - 1))
            return list(raw[trim_to:])

        data_start = idx + len(sync)
        eot_idx = raw.find(EOT, data_start)

        if eot_idx == -1:
            # No EOT yet.  If too many bytes have accumulated after this sync
            # without an EOT, the sync was likely a false match or the message
            # was corrupted — skip it and look for a fresher sync word.
            if len(raw) - data_start > _MAX_PAYLOAD:
                pos = idx + 1
                continue
            return list(raw[idx:])

        frame = raw[data_start:eot_idx]   # payload + 2-byte CRC

        if len(frame) >= 2:
            crc_rx   = (frame[-2] << 8) | frame[-1]
            text_raw = frame[:-2]
            if _crc16(text_raw) == crc_rx:
                if text_raw:
                    print(f"RX: {text_raw.decode('ascii', errors='replace')!r}")
            # CRC mismatch → silently drop (garbled or noise false-match)
        # frame < 2 bytes → can't contain valid CRC → drop

        pos = eot_idx + 1


def receive(freq_hz: int, gain: float, duration_s: Optional[float],
            threshold_frac: float, debug: bool = False) -> None:
    """
    Listen on the RTL-SDR, demodulate OOK, decode UART bytes.

    Streaming decoder: each block's bits are appended to a running buffer;
    UART bytes are decoded incrementally from that buffer; complete messages
    are drained and printed.  No ring-buffer size limit — long messages and
    back-to-back transmissions both work without restarting the receiver.
    """
    from rf_bench.rtlsdr import RTLSDR, RTLSDRError

    fs_dec  = SAMPLE_RATE / DECIMATE
    spb     = fs_dec / BAUD            # 10.0
    block   = int(SAMPLE_RATE * 0.5)

    print(f"RTL-SDR listening on {freq_hz/1e6:.3f} MHz  gain={gain} dB")
    print(f"  IF offset: +{IF_OFFSET/1e3:.0f} kHz  decimation: {DECIMATE}x  "
          f"channel BW: {fs_dec/1e3:.0f} kHz")
    print(f"  {BAUD} baud  {spb:.0f} samples/bit  Ctrl-C to stop\n")

    running    = True
    sample_off = 0
    phase_step = +2.0 * np.pi * IF_OFFSET / SAMPLE_RATE

    import signal as _sig
    def _stop(_s, _f):
        nonlocal running
        running = False
        # Restore default handler so a second Ctrl-C force-kills the process
        # in case the graceful shutdown gets stuck on libusb cleanup.
        _sig.signal(_sig.SIGINT, _sig.SIG_DFL)
    _sig.signal(_sig.SIGINT, _stop)

    # Streaming decoder state
    bits_buf:  np.ndarray    = np.zeros(0, dtype=np.int8)
    byte_fifo: list[int]     = []
    decode_pos: int          = 0
    carrier_active: bool     = False   # True while hi indicates a carrier is present
    KEEP_CTX  = int(spb * 12)         # one full byte-period of context before decode_pos
    MAX_BITS  = int(fs_dec * 30)      # safety cap on bits_buf

    with RTLSDR() as sdr:
        sdr.set_center_freq(freq_hz + IF_OFFSET)
        sdr.set_sample_rate(SAMPLE_RATE)
        sdr.set_gain(gain)

        start_t = time.time()
        for raw_iq in sdr.stream_iq(block_size=block):
            if not running:
                break
            if duration_s and (time.time() - start_t) > duration_s:
                break

            n = len(raw_iq)

            # Mix: shift carrier from +IF_OFFSET down to 0 Hz
            mix = np.exp(1j * phase_step *
                         np.arange(sample_off, sample_off + n,
                                   dtype=np.float32)).astype(np.complex64)
            mixed = raw_iq * mix
            sample_off += n

            # Incoherent envelope: abs each sample first, then average groups.
            # Unlike complex mean (boxcar), this is frequency-independent — the
            # carrier amplitude is preserved regardless of how far the CC1101's
            # VCO drifts from DC after mixing.  Off-frequency ISM signals are still
            # suppressed because they rotate in phase and partially cancel when added
            # to a strong DC carrier during carrier-on periods.
            n_out = n // DECIMATE
            if n_out == 0:
                continue
            env = (np.abs(mixed[:n_out * DECIMATE])
                   .astype(np.float32)
                   .reshape(n_out, DECIMATE)
                   .mean(axis=1))

            lo  = float(np.percentile(env, 10))
            hi  = float(np.percentile(env, 99))

            if hi - lo < lo * 0.4:
                # Envelope variation is small → noise only, no OOK modulation.
                # (Incoherent decimation makes noise nearly flat: hi/lo ≈ 1.2,
                # so hi-lo ≈ 0.2×lo.  Carrier gives hi/lo >> 5 → hi-lo >> 0.4×lo.)
                bits_buf       = np.zeros(0, dtype=np.int8)
                decode_pos     = 0
                byte_fifo      = []
                carrier_active = False
                if debug:
                    print(f"  [flat  lo={lo:.4f} hi={hi:.4f}]", flush=True)
                continue

            # Carrier detection: hi must be substantially above the noise floor.
            # Incoherent noise gives hi/lo ≈ 1.2; carrier gives hi/lo >> 5.
            is_carrier = hi > lo * 5.0

            if is_carrier and not carrier_active:
                # Noise → carrier transition: stale noise bits in bits_buf would
                # delay finding the new message by many seconds (decode_pos only
                # advances ~1400 bits/block but bits_buf grows ~1000 bits/block
                # during silence). Flush the stale accumulation and start fresh.
                bits_buf   = np.zeros(0, dtype=np.int8)
                decode_pos = 0
                byte_fifo  = []
                if debug:
                    print(f"  [carrier start]", flush=True)

            carrier_active = is_carrier

            thresh   = lo + (hi - lo) * threshold_frac
            bits_new = (env > thresh).astype(np.int8)
            ones_pct = 100.0 * bits_new.mean()

            if debug:
                print(f"  [block lo={lo:.4f} hi={hi:.4f} thresh={thresh:.4f} "
                      f"ones={ones_pct:.1f}% buf={len(bits_buf)}]", flush=True)

            bits_buf = np.concatenate([bits_buf, bits_new])

            # Safety cap: prevent unbounded growth during sustained noise
            if len(bits_buf) > MAX_BITS:
                excess     = len(bits_buf) - MAX_BITS
                bits_buf   = bits_buf[excess:]
                decode_pos = max(0, decode_pos - excess)

            # Decode UART bytes from decode_pos onward; stop at incomplete bytes
            new_bytes, decode_pos = _decode_uart_chunk(bits_buf, spb, decode_pos)
            if debug and new_bytes:
                print(f"  [bytes {len(new_bytes)}: "
                      f"{bytes(new_bytes[:16]).hex()} ...]", flush=True)
            byte_fifo.extend(new_bytes)

            # Drain complete messages from byte_fifo
            byte_fifo = _drain_byte_fifo(byte_fifo)

            # Trim bits already decoded (keep one byte of context for edge detection)
            trim_n = max(0, decode_pos - KEEP_CTX)
            if trim_n > 0:
                bits_buf   = bits_buf[trim_n:]
                decode_pos -= trim_n

        sdr.stop_stream()

    print("\nDone.")


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
                    choices=BAUD_RATES,
                    help="Baud rate (default: 1200). Lower = narrower noise BW = more range: "
                         "halving the baud rate gains ~3 dB SNR (~40%% more distance). "
                         "110 baud is ~20 dB better than 1200.")
    ap.add_argument("--repeat",    type=int,   default=1,
                    help="Number of times to repeat transmission (default: 1)")
    ap.add_argument("--gain",      type=float, default=40,
                    help="RTL-SDR gain in dB (default: 40)")
    ap.add_argument("--duration",  type=float, default=None, metavar="SECS",
                    help="RX duration in seconds (default: until Ctrl-C)")
    ap.add_argument("--threshold", type=float, default=0.5, metavar="FRAC",
                    help="OOK detection threshold 0.0–1.0 (default: 0.5)")
    ap.add_argument("--serial",      default="/dev/ttyACM0",
                    help="Flipper serial port (default: /dev/ttyACM0)")
    ap.add_argument("--callsign",    default="",
                    help="Station callsign prepended to TX as 'DE CALLSIGN: message' (ham ID)")
    ap.add_argument("--debug",       action="store_true",
                    help="Print per-block signal levels and raw bytes (rx only)")

    args = ap.parse_args()

    freq_hz = int(args.freq * 1e6)

    if args.baud != BAUD:
        BAUD   = args.baud
        BIT_US = int(1_000_000 / BAUD)

    if args.mode == "tx":
        if not args.text:
            ap.error("tx mode requires a text argument")
        transmit(args.text, args.serial, freq_hz, args.repeat, args.callsign)

    elif args.mode == "rx":
        receive(freq_hz, args.gain, args.duration, args.threshold, args.debug)


if __name__ == "__main__":
    main()
