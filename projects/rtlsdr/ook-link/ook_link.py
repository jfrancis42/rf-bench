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

# Supported baud rates.  Halving the rate gains ~3 dB SNR / ~40 % more range.
# FSK modes (2fsk_dev238/476, gfsk, msk) support higher rates than OOK.
BAUD_RATES  = [110, 300, 600, 1200, 2400, 4800, 9600, 99975]

# Per-preset CC1101 configuration.  'mod' selects OOK vs FSK demodulation.
# 'default_baud' is the rate used when --baud is omitted.
PRESET_INFO = {
    'ook270':      dict(mod='ook', flipper='FuriHalSubGhzPresetOok270Async',     default_baud=600),
    'ook650':      dict(mod='ook', flipper='FuriHalSubGhzPresetOok650Async',     default_baud=1200),
    '2fsk_dev238': dict(mod='fsk', flipper='FuriHalSubGhzPreset2FSKDev238Async', default_baud=1200),
    '2fsk_dev476': dict(mod='fsk', flipper='FuriHalSubGhzPreset2FSKDev476Async', default_baud=2400),
    'gfsk':        dict(mod='fsk', flipper='FuriHalSubGhzPresetGFSK9_99KbAsync', default_baud=9600),
    'msk':         dict(mod='fsk', flipper='FuriHalSubGhzPresetMSK99_97KbAsync', default_baud=99975),
}
DEFAULT_PRESET = 'ook650'


def _decimate_for_baud(baud: int) -> int:
    """Decimation factor that keeps at least 10 samples/bit (max 100)."""
    return max(1, min(100, SAMPLE_RATE // (baud * 10)))

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

_TX_ONLY_PRESETS = {'ook270', 'ook650', '2fsk_dev238', '2fsk_dev476'}
_RX_ONLY_PRESETS = {'gfsk', 'msk'}   # crash Flipper in RAW TX mode on Momentum


def transmit(text: str, serial: str, freq_hz: int, repeat: int,
             callsign: str = "", preset: str = DEFAULT_PRESET) -> None:
    from rf_bench.flipper import FlipperZero, FlipperError

    if preset in _RX_ONLY_PRESETS:
        print(f"ERROR: preset '{preset}' is receive-only — the Flipper's RAW TX "
              f"mode is incompatible with GFSK/MSK register configuration on "
              f"Momentum firmware and will crash the Flipper.\n"
              f"Use --preset 2fsk_dev476 for high-speed FSK TX instead.",
              file=__import__('sys').stderr)
        raise SystemExit(1)

    if callsign:
        text = f"DE {callsign}: {text}"

    mod = PRESET_INFO[preset]['mod']
    timings = encode_message(text)
    total_us = sum(abs(t) for t in timings)
    n_bytes = len(text) + len(SYNC_BYTES) + 2 + 1

    print(f"Encoding {len(text)} chars ({n_bytes} bytes including sync/CRC/EOT)")
    print(f"  {len(timings)} timing edges  {total_us/1e6:.3f} s per transmission")
    print(f"  Baud: {BAUD}  Bit period: {BIT_US} µs  Freq: {freq_hz/1e6:.3f} MHz"
          f"  Preset: {preset} ({mod.upper()})")

    print(f"\nConnecting to Flipper @ {serial} ...")
    with FlipperZero(serial) as fz:
        print(f"  Firmware: {fz.firmware_fork}  ({fz.identify().get('firmware_version','?')})")
        if not fz.uses_carrier_commands:
            _transmit_via_cli(fz, text, freq_hz, repeat, preset=preset)
        else:
            for i in range(repeat):
                if repeat > 1:
                    print(f"\nTransmission {i+1}/{repeat} ...")
                fz.subghz_transmit_raw(freq_hz, timings, preset=preset, repeat=1)
                print("  Sent.")
                if i < repeat - 1:
                    time.sleep(1.0)


def _transmit_via_cli(fz, text: str, freq_hz: int, repeat: int,
                      preset: str = DEFAULT_PRESET) -> None:
    """Write .sub file via RPC storage then play via CLI tx_from_file (Momentum)."""
    timings = encode_message(text)

    raw_vals = [abs(int(t)) if i % 2 == 0 else -abs(int(t))
                for i, t in enumerate(timings)]
    raw_str = " ".join(str(v) for v in raw_vals)

    content = (
        "Filetype: Flipper SubGhz RAW File\n"
        "Version: 1\n"
        f"Frequency: {freq_hz}\n"
        f"Preset: {PRESET_INFO[preset]['flipper']}\n"
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
            threshold_frac: float, preset: str = DEFAULT_PRESET,
            debug: bool = False) -> None:
    """
    Listen on the RTL-SDR, demodulate OOK or FSK, and decode UART bytes.

    OOK path  — incoherent (abs-then-average) envelope detection.
    FSK path  — FM discriminator (instantaneous phase difference): positive =
                mark (logic 1), negative = space (logic 0).  Works for
                2-FSK, GFSK, and MSK presets.

    Both paths share the same streaming UART decoder; they differ only in how
    the binary bit array is computed from the IQ samples.
    """
    from rf_bench.rtlsdr import RTLSDR, RTLSDRError

    mod     = PRESET_INFO[preset]['mod']
    decimate = _decimate_for_baud(BAUD)
    fs_dec  = SAMPLE_RATE / decimate
    spb     = fs_dec / BAUD
    block   = int(SAMPLE_RATE * 0.5)

    print(f"RTL-SDR listening on {freq_hz/1e6:.3f} MHz  gain={gain} dB  "
          f"preset={preset} ({mod.upper()})")
    print(f"  IF offset: +{IF_OFFSET/1e3:.0f} kHz  decimation: {decimate}×  "
          f"channel BW: {fs_dec/1e3:.1f} kHz")
    print(f"  {BAUD} baud  {spb:.1f} samples/bit  Ctrl-C to stop\n")

    running    = True
    sample_off = 0
    phase_step = +2.0 * np.pi * IF_OFFSET / SAMPLE_RATE

    import signal as _sig
    def _stop(_s, _f):
        nonlocal running
        running = False
        _sig.signal(_sig.SIGINT, _sig.SIG_DFL)
    _sig.signal(_sig.SIGINT, _stop)

    # Streaming decoder state
    bits_buf:      np.ndarray    = np.zeros(0, dtype=np.int8)
    byte_fifo:     list[int]     = []
    decode_pos:    int           = 0
    carrier_active: bool         = False
    KEEP_CTX = int(spb * 12)         # one byte-period of lookback context
    MAX_BITS = int(fs_dec * 30)      # 30 s safety cap

    # FSK-only: running noise floor used for carrier detection.
    # Updated during silence; frozen when carrier is present.
    fsk_noise_floor: float = 0.0
    FSK_CARRIER_RATIO = 5.0   # mean_env must exceed noise_floor × this to count as carrier

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

            n_out = n // decimate
            if n_out == 0:
                continue

            # ── OOK path ─────────────────────────────────────────────────────
            if mod == 'ook':
                # Incoherent (abs-then-average) envelope: frequency-independent
                # so CC1101 VCO drift between reconnections doesn't attenuate the
                # carrier.  ISM signals at other frequencies are still suppressed
                # by partial phase cancellation against our strong carrier.
                env = (np.abs(mixed[:n_out * decimate])
                       .astype(np.float32)
                       .reshape(n_out, decimate)
                       .mean(axis=1))

                lo = float(np.percentile(env, 10))
                hi = float(np.percentile(env, 99))

                if hi - lo < lo * 0.4:
                    # Incoherent noise is nearly flat (hi/lo ≈ 1.2); a real OOK
                    # carrier gives hi/lo >> 5.  Reset state between messages.
                    bits_buf = np.zeros(0, dtype=np.int8)
                    decode_pos = 0; byte_fifo = []; carrier_active = False
                    if debug:
                        print(f"  [flat lo={lo:.4f} hi={hi:.4f}]", flush=True)
                    continue

                is_carrier = hi > lo * 5.0
                if is_carrier and not carrier_active:
                    bits_buf = np.zeros(0, dtype=np.int8)
                    decode_pos = 0; byte_fifo = []
                    if debug:
                        print(f"  [OOK carrier start]", flush=True)
                carrier_active = is_carrier

                thresh   = lo + (hi - lo) * threshold_frac
                bits_new = (env > thresh).astype(np.int8)

                if debug:
                    print(f"  [ook lo={lo:.4f} hi={hi:.4f} thresh={thresh:.4f} "
                          f"ones={100*bits_new.mean():.1f}% buf={len(bits_buf)}]",
                          flush=True)

            # ── FSK path ─────────────────────────────────────────────────────
            else:
                # FM discriminator: instantaneous phase difference between
                # adjacent samples gives instantaneous frequency.
                # positive = mark (f + Δf) = logic 1 (idle/stop)
                # negative = space (f − Δf) = logic 0 (start bit)
                n_in  = n_out * decimate
                # diff_phase[i] = angle(IQ[i+1] · IQ[i]*) ∈ (−π, +π] rad/sample
                diff_phase = np.angle(
                    mixed[1:n_in] * np.conj(mixed[:n_in-1])
                ).astype(np.float32)

                # Decimate the phase-diff signal (average gives mean frequency)
                n_dec = (n_in - 1) // decimate
                if n_dec == 0:
                    continue
                disc = (diff_phase[:n_dec * decimate]
                        .reshape(n_dec, decimate)
                        .mean(axis=1))              # rad/sample; + = mark, − = space

                # Carrier detection via mean envelope level.
                # FSK always has carrier on; distinguish signal from noise by level.
                mean_env = float(np.mean(np.abs(mixed[:n_in])))

                if fsk_noise_floor == 0.0:
                    fsk_noise_floor = mean_env          # first block: calibrate
                    if debug:
                        print(f"  [fsk calibrate noise_floor={fsk_noise_floor:.4f}]",
                              flush=True)
                    continue

                is_carrier = mean_env > fsk_noise_floor * FSK_CARRIER_RATIO

                if not is_carrier:
                    # Silence: update noise floor and reset decoder
                    fsk_noise_floor = fsk_noise_floor * 0.9 + mean_env * 0.1
                    bits_buf = np.zeros(0, dtype=np.int8)
                    decode_pos = 0; byte_fifo = []; carrier_active = False
                    if debug:
                        print(f"  [fsk quiet mean={mean_env:.4f} "
                              f"floor={fsk_noise_floor:.4f}]", flush=True)
                    continue

                if is_carrier and not carrier_active:
                    bits_buf = np.zeros(0, dtype=np.int8)
                    decode_pos = 0; byte_fifo = []
                    if debug:
                        print(f"  [FSK carrier start mean={mean_env:.4f} "
                              f"floor={fsk_noise_floor:.4f} "
                              f"ratio={mean_env/fsk_noise_floor:.1f}x]", flush=True)
                carrier_active = is_carrier

                # Adaptive threshold: midpoint of the 5th–95th percentile range.
                # UART data is mark-biased (~57% marks due to idle/stop bits),
                # so the median sits at the mark frequency, not the center.
                # (p5 + p95)/2 gives the center between space and mark frequencies,
                # which equals the VCO offset — correctly compensating for CC1101
                # VCO drift between reconnections regardless of data balance.
                fsk_thresh = (float(np.percentile(disc, 5)) +
                              float(np.percentile(disc, 95))) / 2.0
                bits_new = (disc > fsk_thresh).astype(np.int8)
                # n_dec may be one less than n_out — no problem, handled by streaming

                if debug:
                    print(f"  [fsk mean={mean_env:.4f} floor={fsk_noise_floor:.4f} "
                          f"ratio={mean_env/fsk_noise_floor:.1f}x "
                          f"ones={100*bits_new.mean():.1f}% buf={len(bits_buf)}]",
                          flush=True)

            # ── shared UART decoder ───────────────────────────────────────────
            bits_buf = np.concatenate([bits_buf, bits_new])

            if len(bits_buf) > MAX_BITS:
                excess     = len(bits_buf) - MAX_BITS
                bits_buf   = bits_buf[excess:]
                decode_pos = max(0, decode_pos - excess)

            new_bytes, decode_pos = _decode_uart_chunk(bits_buf, spb, decode_pos)
            if debug and new_bytes:
                print(f"  [bytes {len(new_bytes)}: "
                      f"{bytes(new_bytes[:16]).hex()}]", flush=True)
            byte_fifo.extend(new_bytes)
            byte_fifo = _drain_byte_fifo(byte_fifo)

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

    _preset_summary = "  ".join(
        f"{k}({v['mod'].upper()},{v['default_baud']}bd)"
        for k, v in PRESET_INFO.items()
    )

    ap = argparse.ArgumentParser(
        description="OOK/FSK ASCII link: Flipper Zero TX ↔ RTL-SDR RX",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Presets (name, modulation, default baud):
  {_preset_summary}

OOK baud rates and range (approximate, relative to ook650 at 1200 bd):
  110 bd → ~20 dB gain → ~10× range   300 bd → ~12 dB → ~4×
  600 bd →  ~6 dB gain →  ~2× range  1200 bd → baseline  2400 bd → −3 dB

FSK baud rates (guidance — TX and RX must match):
  2fsk_dev238: up to 2400 bd (deviation/baud ≥ 1)
  2fsk_dev476: up to 4800 bd
  gfsk:        4800–9600 bd (Gaussian-filtered, lowest adjacent-channel interference)
  msk:         99975 bd only (preset tuned for this rate; lower rates work but are wide)

Examples:
  python ook_link.py tx "Hello" --callsign N0GQ
  python ook_link.py rx
  python ook_link.py tx "Hi" --preset 2fsk_dev476 --baud 2400 --callsign N0GQ
  python ook_link.py rx --preset 2fsk_dev476 --baud 2400
  python ook_link.py tx "CQ" --preset gfsk --baud 9600 --callsign N0GQ
  python ook_link.py rx --preset gfsk --baud 9600
  python ook_link.py tx "Max" --preset msk  --callsign N0GQ
  python ook_link.py rx --preset msk
  python ook_link.py tx "Hi"  --preset ook270 --baud 300 --repeat 3 --callsign N0GQ
""")
    ap.add_argument("mode", choices=["tx", "rx"],
                    help="tx = transmit via Flipper, rx = receive via RTL-SDR")
    ap.add_argument("text", nargs="?", default="",
                    help="ASCII text to send (tx mode only)")

    ap.add_argument("--freq",    type=float, default=FREQ_HZ / 1e6, metavar="MHZ",
                    help=f"Frequency in MHz (default: {FREQ_HZ/1e6})")
    ap.add_argument("--preset",  default=DEFAULT_PRESET,
                    choices=list(PRESET_INFO),
                    help=f"CC1101 modulation preset (default: {DEFAULT_PRESET}). "
                         "OOK presets: ook270 (narrow, slow), ook650 (wide, default). "
                         "FSK presets: 2fsk_dev238, 2fsk_dev476 (default FSK), gfsk, msk.")
    ap.add_argument("--baud",    type=int,   default=None,
                    choices=BAUD_RATES,
                    help="Baud rate. Omit to use the preset's default. "
                         "Lower rates narrow noise bandwidth: halving gains ~3 dB SNR "
                         "(~40%% more range). TX and RX must match.")
    ap.add_argument("--repeat",    type=int,   default=1,
                    help="Number of transmissions (default: 1)")
    ap.add_argument("--gain",      type=float, default=40,
                    help="RTL-SDR gain in dB (default: 40)")
    ap.add_argument("--duration",  type=float, default=None, metavar="SECS",
                    help="RX duration in seconds (default: until Ctrl-C)")
    ap.add_argument("--threshold", type=float, default=0.5, metavar="FRAC",
                    help="OOK envelope threshold fraction 0–1 (default: 0.5, rx only)")
    ap.add_argument("--serial",    default="/dev/ttyACM0",
                    help="Flipper serial port (default: /dev/ttyACM0)")
    ap.add_argument("--callsign",  default="",
                    help="Callsign prepended as 'DE CALLSIGN: msg' for ham ID (tx only)")
    ap.add_argument("--debug",     action="store_true",
                    help="Print per-block signal diagnostics (rx only)")

    args = ap.parse_args()

    freq_hz = int(args.freq * 1e6)
    preset  = args.preset

    # Baud: use explicit --baud, else preset's default
    baud = args.baud if args.baud is not None else PRESET_INFO[preset]['default_baud']
    if baud != BAUD:
        BAUD   = baud
        BIT_US = int(1_000_000 / BAUD)

    if args.mode == "tx":
        if not args.text:
            ap.error("tx mode requires a text argument")
        transmit(args.text, args.serial, freq_hz, args.repeat,
                 args.callsign, preset=preset)

    elif args.mode == "rx":
        receive(freq_hz, args.gain, args.duration, args.threshold,
                preset=preset, debug=args.debug)


if __name__ == "__main__":
    main()
