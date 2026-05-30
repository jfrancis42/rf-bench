#!/usr/bin/env python3
"""
Protocol Analyzer — Siglent SDS2000X Plus MSO Digital Channels

Captures SPI, I2C, UART, or raw digital bus transactions from MSO digital
channels and decodes them in Python.  Results are written to a JSON file,
a timing diagram PNG, and printed to the terminal.

Supported protocols:
  spi   — CLK, MOSI, MISO (optional), CS (optional)
  i2c   — SCL, SDA
  uart  — RX only, or TX + RX
  raw   — display and export digital channels without decoding

Usage:
  python protocol_analyzer.py --protocol spi
  python protocol_analyzer.py --protocol i2c --scl-ch 0 --sda-ch 1
  python protocol_analyzer.py --protocol uart --baud 9600
  python protocol_analyzer.py --protocol raw --digital-channels 0,1,2,3
  python protocol_analyzer.py --protocol spi --continuous
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

# ---------------------------------------------------------------------------
# Siglent shared drivers
# ---------------------------------------------------------------------------

from rf_bench.siglent import SDS2000X                                         # noqa: E402

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SCOPE_HOST      = "10.1.1.58"
DEFAULT_DURATION = 0.1    # seconds
POD_0_CHANNELS  = range(0, 8)
POD_1_CHANNELS  = range(8, 16)


# ---------------------------------------------------------------------------
# Threshold helpers
# ---------------------------------------------------------------------------

def _pod_for_channel(ch: int) -> int:
    """Return the pod number (1 or 2) for a given channel (0–15)."""
    return 1 if ch < 8 else 2


def _apply_threshold(scope: SDS2000X, threshold_str: str, threshold_v: float | None,
                     channels: list[int]) -> None:
    """Set thresholds for the pods used by the given channels."""
    pods_needed = set(_pod_for_channel(ch) for ch in channels)
    for pod in pods_needed:
        if threshold_v is not None:
            scope.set_digital_threshold(pod, threshold_v)
        elif threshold_str.lower() == "auto":
            scope.set_digital_threshold(pod, "LVCMOS33")
        else:
            scope.set_digital_threshold(pod, threshold_str.upper())


# ---------------------------------------------------------------------------
# Capture helper
# ---------------------------------------------------------------------------

def capture_channels(scope: SDS2000X, channels: list[int],
                     duration_s: float) -> tuple[dict[int, np.ndarray], float]:
    """
    Run a single acquisition and return digital traces for all requested channels.

    Returns:
        (traces, sample_rate_hz):
            traces         — dict channel → bool np.ndarray
            sample_rate_hz — sample rate in Hz
    """
    scope.stop()
    time.sleep(0.2)
    scope.run()
    time.sleep(duration_s + 0.3)
    scope.stop()
    time.sleep(0.2)

    traces, sr = scope.capture_all_digital(channels)
    scope.run()
    return traces, sr


# ---------------------------------------------------------------------------
# SPI decoder
# ---------------------------------------------------------------------------

def decode_spi(
    clk: np.ndarray,
    mosi: np.ndarray,
    miso: np.ndarray | None,
    cs: np.ndarray | None,
    sample_rate_hz: float,
    cpol: int = 0,
    cpha: int = 0,
    bits_per_word: int = 8,
    msb_first: bool = True,
) -> list[dict]:
    """
    Decode SPI transactions from raw digital channel arrays.

    Returns list of transaction dicts:
        {
          'cs_start_sample': int | None,
          'cs_end_sample':   int | None,
          'cs_start_s':      float | None,
          'cs_end_s':        float | None,
          'mosi_bytes':      list[int],
          'miso_bytes':      list[int],
        }
    """
    clk_int  = clk.astype(np.int8)
    clk_diff = np.diff(clk_int)

    # Determine which edge to sample on (CPOL+CPHA define the sampling edge)
    #   CPOL=0, CPHA=0 → sample on rising edge  (first/leading edge)
    #   CPOL=0, CPHA=1 → sample on falling edge (second/trailing edge)
    #   CPOL=1, CPHA=0 → sample on falling edge (first/leading edge)
    #   CPOL=1, CPHA=1 → sample on rising edge  (second/trailing edge)
    if cpol == cpha:
        sample_edge = 1    # rising
    else:
        sample_edge = -1   # falling

    active_edges = np.where(clk_diff == sample_edge)[0] + 1  # +1: diff is 1 behind

    if len(active_edges) == 0:
        return []

    # Build CS assertion intervals (CS active-low)
    if cs is not None:
        cs_int  = cs.astype(np.int8)
        cs_diff = np.diff(cs_int)
        cs_assert   = list(np.where(cs_diff == -1)[0] + 1)  # falling → assert
        cs_deassert = list(np.where(cs_diff == 1)[0] + 1)   # rising  → deassert

        # If CS is already low at start, treat sample 0 as an assert
        if cs[0] == 0 and (not cs_assert or cs_assert[0] > (cs_deassert[0] if cs_deassert else len(cs))):
            cs_assert.insert(0, 0)

        # Pair up assertions and deasssertions
        intervals: list[tuple[int, int]] = []
        for start in cs_assert:
            ends_after = [d for d in cs_deassert if d > start]
            end = ends_after[0] if ends_after else len(cs) - 1
            intervals.append((start, end))
    else:
        # No CS: treat the whole capture as one transaction
        intervals = [(0, len(clk) - 1)]

    transactions: list[dict] = []

    for cs_start, cs_end in intervals:
        # Collect clock edges within this CS window
        window_edges = active_edges[(active_edges >= cs_start) &
                                    (active_edges <= cs_end)]

        mosi_bits = []
        miso_bits = []

        for edge_idx in window_edges:
            if edge_idx < len(mosi):
                mosi_bits.append(int(mosi[edge_idx]))
            if miso is not None and edge_idx < len(miso):
                miso_bits.append(int(miso[edge_idx]))

        # Pack bits into bytes
        def _bits_to_bytes(bits: list[int]) -> list[int]:
            result = []
            for i in range(0, len(bits), bits_per_word):
                word_bits = bits[i:i + bits_per_word]
                if len(word_bits) < bits_per_word:
                    # Pad incomplete word with zeros
                    word_bits += [0] * (bits_per_word - len(word_bits))
                if not msb_first:
                    word_bits = word_bits[::-1]
                value = 0
                for b in word_bits:
                    value = (value << 1) | b
                result.append(value)
            return result

        mosi_bytes = _bits_to_bytes(mosi_bits)
        miso_bytes = _bits_to_bytes(miso_bits) if miso_bits else []

        transactions.append({
            'cs_start_sample': cs_start if cs is not None else None,
            'cs_end_sample':   cs_end   if cs is not None else None,
            'cs_start_s':      cs_start / sample_rate_hz if cs is not None else None,
            'cs_end_s':        cs_end   / sample_rate_hz if cs is not None else None,
            'mosi_bytes':      mosi_bytes,
            'miso_bytes':      miso_bytes,
        })

    return transactions


# ---------------------------------------------------------------------------
# I2C decoder
# ---------------------------------------------------------------------------

def decode_i2c(
    scl: np.ndarray,
    sda: np.ndarray,
    sample_rate_hz: float,
) -> list[dict]:
    """
    Decode I2C transactions from raw digital channel arrays.

    Returns list of transaction dicts:
        {
          'start_sample': int,
          'stop_sample':  int,
          'start_s':      float,
          'stop_s':       float,
          'addr':         int,    # 7-bit address
          'rw':           str,    # 'R' or 'W'
          'data':         list[int],
          'ack':          list[bool],  # True = ACK (SDA low), one per byte
        }
    """
    scl_int  = scl.astype(np.int8)
    sda_int  = sda.astype(np.int8)
    scl_diff = np.diff(scl_int)
    sda_diff = np.diff(sda_int)

    # START condition: SDA falls while SCL is high
    # Use index i: sda_diff[i] == -1 and scl[i+1] == 1
    n = min(len(scl_diff), len(sda_diff))
    start_samples = []
    stop_samples  = []

    for i in range(n):
        scl_high = (scl[i + 1] == 1)
        if sda_diff[i] == -1 and scl_high:
            start_samples.append(i + 1)
        elif sda_diff[i] == 1 and scl_high:
            stop_samples.append(i + 1)

    if not start_samples:
        return []

    scl_rising = np.where(scl_diff == 1)[0] + 1

    transactions = []

    for si, start in enumerate(start_samples):
        # Find the STOP that comes after this START
        stops_after = [s for s in stop_samples if s > start]
        # Also consider the next START as an implicit stop (repeated start)
        next_starts = [s for s in start_samples if s > start]

        end_boundary = min(
            stops_after[0] if stops_after else len(scl),
            next_starts[0] if next_starts else len(scl),
        )
        stop_sample = stops_after[0] if stops_after and stops_after[0] <= end_boundary else end_boundary

        # Collect SCL rising edges between START and STOP
        rising_in_window = scl_rising[(scl_rising > start) & (scl_rising < stop_sample)]

        if len(rising_in_window) < 8:
            continue  # Not enough clocks for even one address byte

        # Sample SDA at each SCL rising edge to get bits
        sda_bits = []
        for edge in rising_in_window:
            if edge < len(sda):
                sda_bits.append(int(sda[edge]))

        if len(sda_bits) < 9:
            continue  # Need at least 8 address bits + 1 ACK

        # Decode address byte (bits 0–6) and R/W bit (bit 7)
        addr_bits = sda_bits[0:7]
        rw_bit    = sda_bits[7]
        ack_bit   = sda_bits[8] if len(sda_bits) > 8 else 1

        addr = 0
        for b in addr_bits:
            addr = (addr << 1) | b
        rw_str = 'R' if rw_bit else 'W'
        ack_ok = (ack_bit == 0)  # ACK = SDA low

        # Decode data bytes (9 bits each: 8 data + 1 ACK)
        data_bytes = []
        ack_list   = [ack_ok]   # first ACK is the address ACK
        idx = 9  # start after address byte + its ACK

        while idx + 8 <= len(sda_bits):
            byte_bits = sda_bits[idx:idx + 8]
            byte_ack  = sda_bits[idx + 8] if idx + 8 < len(sda_bits) else 1
            value = 0
            for b in byte_bits:
                value = (value << 1) | b
            data_bytes.append(value)
            ack_list.append(byte_ack == 0)
            idx += 9

        transactions.append({
            'start_sample': start,
            'stop_sample':  stop_sample,
            'start_s':      start       / sample_rate_hz,
            'stop_s':       stop_sample / sample_rate_hz,
            'addr':         addr,
            'rw':           rw_str,
            'data':         data_bytes,
            'ack':          ack_list,
        })

    return transactions


# ---------------------------------------------------------------------------
# UART decoder
# ---------------------------------------------------------------------------

def decode_uart(
    rx: np.ndarray,
    tx: np.ndarray | None,
    sample_rate_hz: float,
    baud: int = 115200,
    data_bits: int = 8,
    parity: str = "none",
    stop_bits: int = 1,
) -> list[dict]:
    """
    Decode UART data from raw digital channel arrays.

    UART idle = logic HIGH.  Start bit = logic LOW.

    Returns list of byte dicts:
        {
          'channel':    'RX' | 'TX',
          'byte':       int,
          'sample_idx': int,
          'time_s':     float,
          'parity_ok':  bool,
        }
    """
    baud_samples = sample_rate_hz / baud
    half_baud    = baud_samples / 2.0

    def _decode_channel(signal: np.ndarray, channel_name: str) -> list[dict]:
        decoded = []
        sig_int  = signal.astype(np.int8)
        sig_diff = np.diff(sig_int)
        # Start bit: idle (1) → low (0) = falling edge
        start_edges = list(np.where(sig_diff == -1)[0] + 1)

        i = 0
        while i < len(start_edges):
            start_idx = start_edges[i]

            # Confirm: sample at mid-start-bit should be 0
            mid_start = start_idx + int(half_baud)
            if mid_start >= len(signal) or signal[mid_start] != 0:
                i += 1
                continue

            # Sample each data bit at center of its bit cell
            bits = []
            valid = True
            for bit_n in range(data_bits):
                sample_pos = int(start_idx + half_baud + (bit_n + 1) * baud_samples)
                if sample_pos >= len(signal):
                    valid = False
                    break
                bits.append(int(signal[sample_pos]))

            if not valid:
                i += 1
                continue

            # Parity bit (if enabled)
            parity_ok = True
            n_parity_bits = 0
            if parity != "none":
                n_parity_bits = 1
                par_pos = int(start_idx + half_baud + (data_bits + 1) * baud_samples)
                if par_pos < len(signal):
                    par_bit   = int(signal[par_pos])
                    ones      = sum(bits)
                    if parity == "even":
                        expected = ones % 2
                    else:  # odd
                        expected = (ones + 1) % 2
                    parity_ok = (par_bit == expected)

            # Stop bit
            stop_pos = int(start_idx + half_baud +
                           (data_bits + n_parity_bits + 1) * baud_samples)
            if stop_pos < len(signal) and signal[stop_pos] == 0:
                # Framing error — skip
                i += 1
                continue

            # LSB-first (standard UART): bits[0] is LSB
            value = 0
            for bit_idx, b in enumerate(bits):
                value |= (b << bit_idx)

            decoded.append({
                'channel':    channel_name,
                'byte':       value,
                'sample_idx': start_idx,
                'time_s':     start_idx / sample_rate_hz,
                'parity_ok':  parity_ok,
            })

            # Advance past this frame: skip past last stop bit
            total_bits = 1 + data_bits + n_parity_bits + stop_bits
            frame_end_idx = int(start_idx + total_bits * baud_samples)

            # Skip any start edges that fall within this frame
            while i < len(start_edges) and start_edges[i] < frame_end_idx:
                i += 1

        return decoded

    results = []
    results.extend(_decode_channel(rx, "RX"))
    if tx is not None:
        results.extend(_decode_channel(tx, "TX"))

    results.sort(key=lambda d: d['time_s'])
    return results


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _fmt_bytes_hex(data: list[int]) -> str:
    return " ".join(f"0x{b:02X}" for b in data)


def _fmt_bytes_ascii(data: list[int]) -> str:
    parts = []
    for b in data:
        if 32 <= b < 127:
            parts.append(chr(b))
        else:
            parts.append(f"\\x{b:02X}")
    return "".join(parts)


def _fmt_bytes(data: list[int], use_ascii: bool) -> str:
    if use_ascii:
        return _fmt_bytes_ascii(data)
    return _fmt_bytes_hex(data)


def print_spi_transactions(transactions: list[dict], use_ascii: bool) -> None:
    if not transactions:
        print("  [no transactions decoded]")
        return
    for t in transactions:
        ts_str = (f"t={t['cs_start_s']*1e6:.1f}µs"
                  if t['cs_start_s'] is not None else "")
        mosi_str = _fmt_bytes(t['mosi_bytes'], use_ascii) or "(empty)"
        miso_str = _fmt_bytes(t['miso_bytes'], use_ascii) if t['miso_bytes'] else "-"
        print(f"  [{ts_str}]  MOSI: {mosi_str}  →  MISO: {miso_str}")


def print_i2c_transactions(transactions: list[dict], use_ascii: bool) -> None:
    if not transactions:
        print("  [no transactions decoded]")
        return
    for t in transactions:
        ts_str   = f"t={t['start_s']*1e6:.1f}µs"
        rw_label = t['rw']
        addr_str = f"0x{t['addr']:02X}"
        data_str = _fmt_bytes(t['data'], use_ascii) or "(no data)"
        ack_str  = "ACK" if (t['ack'] and t['ack'][0]) else "NAK"
        print(f"  [{ts_str}]  {rw_label} {addr_str} [{ack_str}]  data: {data_str}")


def print_uart_results(decoded: list[dict], use_ascii: bool) -> None:
    if not decoded:
        print("  [no bytes decoded]")
        return
    # Group into RX and TX runs
    rx_bytes = [d for d in decoded if d['channel'] == 'RX']
    tx_bytes = [d for d in decoded if d['channel'] == 'TX']

    if rx_bytes:
        data = [d['byte'] for d in rx_bytes]
        parity_warn = " [parity errors]" if any(not d['parity_ok'] for d in rx_bytes) else ""
        print(f"  RX: \"{_fmt_bytes_ascii(data)}\"{parity_warn}")
        if not use_ascii:
            print(f"      {_fmt_bytes_hex(data)}")

    if tx_bytes:
        data = [d['byte'] for d in tx_bytes]
        parity_warn = " [parity errors]" if any(not d['parity_ok'] for d in tx_bytes) else ""
        print(f"  TX: \"{_fmt_bytes_ascii(data)}\"{parity_warn}")
        if not use_ascii:
            print(f"      {_fmt_bytes_hex(data)}")


# ---------------------------------------------------------------------------
# Timing diagram
# ---------------------------------------------------------------------------

CHANNEL_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf", "#aec7e8", "#ffbb78",
    "#98df8a", "#ff9896", "#c5b0d5", "#c49c94",
]


def generate_timing_diagram(
    traces: dict[int, np.ndarray],
    sample_rate_hz: float,
    channel_labels: dict[int, str],
    output_prefix: str,
    protocol: str,
    decoded_annotations: list[dict] | None = None,
) -> str:
    """
    Generate a logic-analyzer-style timing diagram PNG.

    Each channel occupies one row.  The x-axis is time in microseconds.
    Decoded byte values are annotated above the corresponding clock edges.
    """
    channels = sorted(traces.keys())
    n_ch     = len(channels)
    if n_ch == 0:
        return ""

    # Compute time axis in microseconds
    n_pts   = max(len(traces[ch]) for ch in channels)
    t_us    = np.arange(n_pts) / sample_rate_hz * 1e6

    fig_h = max(2.5, 0.9 * n_ch + 1.2)
    fig, ax = plt.subplots(figsize=(14, fig_h))

    ax.set_title(
        f"Protocol Analyzer — {protocol.upper()} Timing Diagram\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  "
        f"Sample rate: {sample_rate_hz/1e6:.1f} MHz",
        fontsize=10,
    )

    row_height = 0.8  # normalized height per channel
    y_gap      = 1.0  # spacing between rows

    for row_idx, ch in enumerate(channels):
        sig  = traces[ch].astype(float)
        t_ch = np.arange(len(sig)) / sample_rate_hz * 1e6
        y_base = (n_ch - 1 - row_idx) * y_gap

        # Plot the digital waveform as a step plot
        color = CHANNEL_COLORS[row_idx % len(CHANNEL_COLORS)]
        y_vals = y_base + sig * row_height
        ax.step(t_ch, y_vals, where='post', color=color, linewidth=1.0)
        ax.fill_between(t_ch, y_base, y_vals, step='post', color=color, alpha=0.18)

        # Channel label on left
        label = channel_labels.get(ch, f"D{ch}")
        ax.text(-t_us[-1] * 0.01, y_base + row_height * 0.5,
                label, ha='right', va='center', fontsize=8, fontweight='bold')

        # Grid lines at y_base
        ax.axhline(y_base, color='gray', linewidth=0.3, alpha=0.4)
        ax.axhline(y_base + row_height, color='gray', linewidth=0.3, alpha=0.4)

    ax.set_xlabel("Time (µs)", fontsize=9)
    ax.set_xlim(t_us[0], t_us[-1])
    ax.set_ylim(-0.3, n_ch * y_gap + 0.1)
    ax.set_yticks([])
    ax.grid(True, axis='x', alpha=0.3, linestyle='--')

    # Annotate decoded bytes (placed above the waveform area)
    if decoded_annotations:
        for ann in decoded_annotations:
            t_ann = ann.get('time_s', 0) * 1e6
            label = ann.get('label', '')
            if t_ann < t_us[-1]:
                ax.text(t_ann, n_ch * y_gap - 0.05, label,
                        ha='center', va='bottom', fontsize=6,
                        color='darkred', rotation=45)

    plt.tight_layout()
    path = f"{output_prefix}_timing.png"
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def save_protocol_json(protocol: str, decoded: list[dict],
                       sample_rate_hz: float, duration_s: float,
                       output_prefix: str) -> str:
    path = f"{output_prefix}_protocol.json"
    data = {
        "timestamp":       datetime.now().isoformat(),
        "protocol":        protocol,
        "sample_rate_hz":  sample_rate_hz,
        "duration_s":      duration_s,
        "transaction_count": len(decoded),
        "transactions":    decoded,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=lambda x: x.tolist() if hasattr(x, 'tolist') else x)
    return path


# ---------------------------------------------------------------------------
# Main capture + decode loop
# ---------------------------------------------------------------------------

def run_once(scope: SDS2000X, args: argparse.Namespace,
             capture_num: int) -> tuple[str, str]:
    """
    Perform one capture/decode cycle.

    Returns: (json_path, png_path)
    """
    protocol = args.protocol.lower()

    # Determine which channels to enable
    if protocol == "spi":
        channels = [args.clk_ch, args.mosi_ch]
        if args.miso_ch >= 0:
            channels.append(args.miso_ch)
        if args.cs_ch >= 0:
            channels.append(args.cs_ch)
        channel_labels = {
            args.clk_ch:  "CLK",
            args.mosi_ch: "MOSI",
        }
        if args.miso_ch >= 0:
            channel_labels[args.miso_ch] = "MISO"
        if args.cs_ch >= 0:
            channel_labels[args.cs_ch] = "CS"

    elif protocol == "i2c":
        channels = [args.scl_ch, args.sda_ch]
        channel_labels = {
            args.scl_ch: "SCL",
            args.sda_ch: "SDA",
        }

    elif protocol == "uart":
        channels = [args.rx_ch]
        channel_labels = {args.rx_ch: "RX"}
        if args.tx_ch >= 0:
            channels.append(args.tx_ch)
            channel_labels[args.tx_ch] = "TX"

    else:  # raw
        channels = [int(c.strip()) for c in args.digital_channels.split(",")]
        channel_labels = {ch: f"D{ch}" for ch in channels}

    channels = list(dict.fromkeys(channels))  # deduplicate, preserve order

    # Configure scope MSO
    scope.digital_enable()
    scope.enable_digital_channels(channels)

    threshold_v = args.threshold_v if hasattr(args, 'threshold_v') else None
    _apply_threshold(scope, args.threshold, threshold_v, channels)

    # Set labels on scope display
    for ch, lbl in channel_labels.items():
        scope.set_digital_label(ch, lbl)

    # Capture
    print(f"  Capturing {args.duration_s:.3f} s on channels {channels} ...",
          end=" ", flush=True)
    traces, sr = capture_channels(scope, channels, args.duration_s)
    print(f"done  ({sr/1e6:.1f} MHz sample rate, {len(next(iter(traces.values()))) if traces else 0} pts)")

    if not traces:
        print("  WARNING: no digital data returned — check MSO option and pod connection.")
        return "", ""

    # Decode
    decoded: list[dict] = []
    annotations: list[dict] = []

    use_ascii = getattr(args, 'ascii', False)

    if protocol == "spi":
        clk  = traces.get(args.clk_ch)
        mosi = traces.get(args.mosi_ch)
        miso = traces.get(args.miso_ch) if args.miso_ch >= 0 else None
        cs   = traces.get(args.cs_ch)   if args.cs_ch   >= 0 else None

        if clk is None or mosi is None:
            print("  ERROR: CLK or MOSI channel data missing.")
            return "", ""

        transactions = decode_spi(
            clk, mosi, miso, cs, sr,
            cpol=args.cpol, cpha=args.cpha,
            bits_per_word=args.bits_per_word,
            msb_first=not getattr(args, 'lsb_first', False),
        )
        decoded = transactions

        print(f"\n  SPI decoded {len(transactions)} transaction(s):")
        print_spi_transactions(transactions, use_ascii)

        # Build annotations for timing plot
        for t in transactions:
            if t['cs_start_s'] is not None:
                for i, b in enumerate(t['mosi_bytes']):
                    # Estimate byte time: evenly distributed within transaction
                    if len(t['mosi_bytes']) > 0:
                        t_byte = t['cs_start_s'] + i * (
                            (t['cs_end_s'] - t['cs_start_s']) / len(t['mosi_bytes']))
                        annotations.append({'time_s': t_byte, 'label': f"{b:02X}"})

    elif protocol == "i2c":
        scl = traces.get(args.scl_ch)
        sda = traces.get(args.sda_ch)

        if scl is None or sda is None:
            print("  ERROR: SCL or SDA channel data missing.")
            return "", ""

        transactions = decode_i2c(scl, sda, sr)
        decoded = transactions

        print(f"\n  I2C decoded {len(transactions)} transaction(s):")
        print_i2c_transactions(transactions, use_ascii)

        for t in transactions:
            annotations.append({
                'time_s': t['start_s'],
                'label': f"0x{t['addr']:02X}{t['rw']}",
            })

    elif protocol == "uart":
        rx = traces.get(args.rx_ch)
        tx = traces.get(args.tx_ch) if args.tx_ch >= 0 else None

        if rx is None:
            print("  ERROR: RX channel data missing.")
            return "", ""

        decoded_bytes = decode_uart(rx, tx, sr,
                                    baud=args.baud,
                                    data_bits=args.data_bits,
                                    parity=args.parity,
                                    stop_bits=args.stop_bits)
        decoded = decoded_bytes

        print(f"\n  UART decoded {len(decoded_bytes)} byte(s):")
        print_uart_results(decoded_bytes, use_ascii)

        for d in decoded_bytes:
            annotations.append({
                'time_s': d['time_s'],
                'label': f"{d['byte']:02X}",
            })

    else:  # raw
        print(f"\n  Raw digital capture: {len(traces)} channel(s)")
        for ch in sorted(traces.keys()):
            sig   = traces[ch]
            edges = int(np.sum(np.abs(np.diff(sig.astype(int)))))
            print(f"    D{ch}: {len(sig)} samples, {edges} edges")

    # Timestamped prefix
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    pfx = args.output if args.output else f"{protocol}_analyzer_{ts}"
    if capture_num > 1:
        pfx = f"{pfx}_{capture_num:04d}"

    # Save JSON
    json_path = save_protocol_json(protocol, decoded, sr, args.duration_s, pfx)

    # Save timing diagram
    try:
        png_path = generate_timing_diagram(
            traces, sr, channel_labels, pfx, protocol, annotations
        )
    except Exception as exc:
        print(f"  WARNING: timing diagram failed ({exc})")
        png_path = ""

    return json_path, png_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Protocol Analyzer — Siglent SDS2000X Plus MSO",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Protocols:
  spi   CLK, MOSI, MISO (optional), CS (optional)
  i2c   SCL, SDA
  uart  RX only, or TX+RX
  raw   No decoding — display and export digital channels

Threshold options:
  --threshold ttl|cmos|lvcmos33|lvcmos25   Standard preset (default: lvcmos33)
  --threshold-v VOLTS                       Custom voltage threshold (e.g. 1.65)

SPI CPOL/CPHA modes:
  Mode 0: --cpol 0 --cpha 0  (sample rising,  idle low)
  Mode 1: --cpol 0 --cpha 1  (sample falling, idle low)
  Mode 2: --cpol 1 --cpha 0  (sample falling, idle high)
  Mode 3: --cpol 1 --cpha 1  (sample rising,  idle high)

Examples:
  python protocol_analyzer.py --protocol spi
  python protocol_analyzer.py --protocol spi --cpol 1 --cpha 1 --bits-per-word 16
  python protocol_analyzer.py --protocol i2c --scl-ch 0 --sda-ch 1
  python protocol_analyzer.py --protocol uart --baud 9600 --parity even
  python protocol_analyzer.py --protocol uart --rx-ch 0 --tx-ch 1 --baud 115200
  python protocol_analyzer.py --protocol raw --digital-channels 0,1,4,7
  python protocol_analyzer.py --protocol spi --continuous
""",
    )

    parser.add_argument("--protocol", required=True, choices=["spi", "i2c", "uart", "raw"],
                        help="Protocol to decode")
    parser.add_argument("--scope-host", default=SCOPE_HOST, metavar="HOST",
                        help=f"Oscilloscope IP address (default: {SCOPE_HOST})")
    parser.add_argument("--duration-s", type=float, default=DEFAULT_DURATION, metavar="S",
                        help=f"Capture duration in seconds (default: {DEFAULT_DURATION})")
    parser.add_argument("--threshold", default="lvcmos33",
                        choices=["ttl", "cmos", "lvcmos33", "lvcmos25", "auto"],
                        help="Logic threshold preset (default: lvcmos33)")
    parser.add_argument("--threshold-v", type=float, default=None, metavar="VOLTS",
                        help="Custom threshold voltage in V (overrides --threshold)")
    parser.add_argument("--output", default=None, metavar="PREFIX",
                        help="Output filename prefix (default: timestamped)")
    parser.add_argument("--hex", dest="hex", action="store_true", default=True,
                        help="Display decoded bytes as hex (default)")
    parser.add_argument("--ascii", dest="ascii", action="store_true", default=False,
                        help="Display decoded bytes as ASCII where printable")
    parser.add_argument("--continuous", action="store_true",
                        help="Keep capturing until Ctrl+C")
    parser.add_argument("--digital-channels", default="0,1,2,3", metavar="LIST",
                        help="Channels for --protocol raw (comma-separated, default: 0,1,2,3)")

    # SPI options
    spi = parser.add_argument_group("SPI options")
    spi.add_argument("--clk-ch",  type=int, default=0, metavar="N",
                     help="CLK channel (default: 0)")
    spi.add_argument("--mosi-ch", type=int, default=1, metavar="N",
                     help="MOSI channel (default: 1)")
    spi.add_argument("--miso-ch", type=int, default=2, metavar="N",
                     help="MISO channel (default: 2; use -1 to disable)")
    spi.add_argument("--cs-ch",   type=int, default=3, metavar="N",
                     help="CS channel (default: 3; use -1 for no CS)")
    spi.add_argument("--cpol",    type=int, default=0, choices=[0, 1],
                     help="Clock polarity: 0=idle low, 1=idle high (default: 0)")
    spi.add_argument("--cpha",    type=int, default=0, choices=[0, 1],
                     help="Clock phase: 0=first edge, 1=second edge (default: 0)")
    spi.add_argument("--bits-per-word", type=int, default=8, metavar="N",
                     help="Bits per SPI word (default: 8)")
    spi.add_argument("--msb-first", dest="lsb_first", action="store_false", default=False,
                     help="MSB transmitted first (default)")
    spi.add_argument("--lsb-first", dest="lsb_first", action="store_true",
                     help="LSB transmitted first")

    # I2C options
    i2c = parser.add_argument_group("I2C options")
    i2c.add_argument("--scl-ch", type=int, default=0, metavar="N",
                     help="SCL channel (default: 0)")
    i2c.add_argument("--sda-ch", type=int, default=1, metavar="N",
                     help="SDA channel (default: 1)")

    # UART options
    uart = parser.add_argument_group("UART options")
    uart.add_argument("--rx-ch",     type=int, default=0, metavar="N",
                      help="RX channel (default: 0)")
    uart.add_argument("--tx-ch",     type=int, default=1, metavar="N",
                      help="TX channel (default: 1; use -1 for RX-only)")
    uart.add_argument("--baud",      type=int, default=115200,
                      help="UART baud rate (default: 115200)")
    uart.add_argument("--data-bits", type=int, default=8, metavar="N",
                      help="UART data bits (default: 8)")
    uart.add_argument("--parity",    default="none", choices=["none", "even", "odd"],
                      help="UART parity (default: none)")
    uart.add_argument("--stop-bits", type=int, default=1, choices=[1, 2],
                      help="UART stop bits (default: 1)")

    args = parser.parse_args()

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"{args.protocol}_analyzer_{ts}"

    scope = None
    try:
        print(f"Connecting to oscilloscope at {args.scope_host} ...")
        scope = SDS2000X(args.scope_host)
        idn   = scope.identify()
        print(f"Instrument: {idn}")

        if args.continuous:
            print("Continuous mode — press Ctrl+C to stop.\n")
            n = 0
            while True:
                n += 1
                print(f"[Capture #{n}]")
                json_path, png_path = run_once(scope, args, n)
                if json_path:
                    print(f"  JSON → {json_path}")
                if png_path:
                    print(f"  PNG  → {png_path}")
                print()
        else:
            print(f"\n[Capture]")
            json_path, png_path = run_once(scope, args, 1)
            if json_path:
                print(f"\nJSON → {json_path}")
            if png_path:
                print(f"PNG  → {png_path}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
    except ConnectionRefusedError:
        print(f"\nCannot connect to {args.scope_host}:5025")
        print("Verify the oscilloscope is powered on and SCPI/LAN is enabled.")
        sys.exit(1)
    except OSError as exc:
        print(f"\nNetwork error: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"\nUnexpected error: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        if scope is not None:
            try:
                scope.digital_disable()
                scope.run()
            except Exception:
                pass
            scope.close()


if __name__ == "__main__":
    main()
