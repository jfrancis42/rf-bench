#!/usr/bin/env python3
"""
tci-sipphone — Register a SIP extension with FreePBX/Asterisk that streams
TCI radio audio.  Dial the extension from any phone on the PBX to hear
the radio receive audio.  Caller audio is sent to the radio TX path.

PTT: VOX-triggered — audio above --vox-threshold asserts TRX:N,true,tci.

Usage:
  tci-sipphone --tci-host HOST --sip-server HOST --sip-user EXT \\
               --sip-password PASS [options]
"""

import argparse
import hashlib
import random
import re
import select
import signal
import socket
import struct
import threading
import time
from typing import Optional

import numpy as np
import websocket


# ── G.711 µ-law codec (pure numpy, no audioop) ───────────────────────────────

def _build_ulaw_tables():
    """
    Build G.711 µ-law encode (65536-entry uint8) and decode (256-entry int16)
    lookup tables.  Called once at import time.
    """
    BIAS    = 132
    seg_end = [0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF, 0x3FFF, 0x7FFF]

    enc = np.zeros(65536, dtype=np.uint8)
    for raw in range(65536):
        s = raw if raw < 32768 else raw - 65536   # interpret as int16
        if s < 0:
            s, mask = BIAS - s, 0x7F
        else:
            s, mask = s + BIAS, 0xFF
        s   = min(s, 32767)
        exp = next((i for i, e in enumerate(seg_end) if s <= e), 7)
        enc[raw] = ((exp << 4) | ((s >> (exp + 3)) & 0xF)) ^ mask

    dec = np.zeros(256, dtype=np.int16)
    for i in range(256):
        u    = ~i & 0xFF
        sign = u & 0x80
        exp  = (u >> 4) & 7
        mant = u & 0xF
        t    = ((mant << 3) + BIAS) << exp
        dec[i] = np.int16(BIAS - t if sign else t - BIAS)

    return enc, dec


_ULAW_ENC, _ULAW_DEC = _build_ulaw_tables()


def _pcm_to_ulaw(f32: np.ndarray) -> bytes:
    """float32 mono [-1,1] → G.711 µ-law bytes."""
    s16 = (np.clip(f32, -1.0, 1.0) * 32767.0).astype(np.int16)
    return _ULAW_ENC[s16.view(np.uint16)].tobytes()


def _ulaw_to_pcm(data: bytes) -> np.ndarray:
    """G.711 µ-law bytes → float32 mono [-1,1]."""
    return _ULAW_DEC[np.frombuffer(data, dtype=np.uint8)].astype(np.float32) / 32768.0


# ── TCI binary frame helpers ─────────────────────────────────────────────────

_TCI_HDR_FMT   = "<IIIIIIII8x"
_TCI_HDR_LEN   = 40
_TCI_RX_AUDIO  = 1
_TCI_TX_AUDIO  = 2
_TCI_TX_CHRONO = 3
_FMT_INT16     = 0
_FMT_FLOAT32   = 3


def _decode_tci(data: bytes) -> Optional[tuple]:
    if len(data) < _TCI_HDR_LEN:
        return None
    trx, rate, fmt, _, _, length, stype, channels = \
        struct.unpack_from(_TCI_HDR_FMT, data, 0)
    payload = data[_TCI_HDR_LEN:]

    if stype == _TCI_RX_AUDIO:
        if fmt == _FMT_INT16:
            n = min(length, len(payload) // 2)
            s = np.frombuffer(payload[:n*2], dtype='<i2').astype(np.float32) / 32768.0
        elif fmt == _FMT_FLOAT32:
            n = min(length, len(payload) // 4)
            s = np.frombuffer(payload[:n*4], dtype='<f4').copy()
        else:
            return None
        if channels == 2 and len(s) >= 2:
            s = s.reshape(-1, 2).mean(axis=1).astype(np.float32)
        return ('rx', s)

    if stype == _TCI_TX_CHRONO:
        return ('chrono', trx, rate, length)
    return None


def _encode_tci_tx(trx: int, rate: int, samples: np.ndarray) -> bytes:
    s16 = (np.clip(samples, -1.0, 1.0) * 32767.0).astype('<i2')
    hdr = struct.pack(_TCI_HDR_FMT,
                      trx, rate, _FMT_INT16, 0, 0, len(s16), _TCI_TX_AUDIO, 1)
    return hdr + s16.tobytes()


# ── SIP helpers ───────────────────────────────────────────────────────────────

def _rnd(n: int = 8) -> str:
    return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=n))


def _md5_digest(user: str, realm: str, password: str,
                method: str, uri: str, nonce: str) -> str:
    ha1 = hashlib.md5(f'{user}:{realm}:{password}'.encode()).hexdigest()
    ha2 = hashlib.md5(f'{method}:{uri}'.encode()).hexdigest()
    return hashlib.md5(f'{ha1}:{nonce}:{ha2}'.encode()).hexdigest()


def _parse_sip(text: str) -> Optional[dict]:
    """Parse a raw SIP message into a dict."""
    lines = text.replace('\r\n', '\n').split('\n')
    if not lines or not lines[0].strip():
        return None
    first = lines[0].strip()
    msg: dict = {'headers': {}, 'body': ''}

    if first.startswith('SIP/2.0 '):
        parts = first.split(' ', 2)
        msg.update(type='response', status=int(parts[1]),
                   reason=parts[2] if len(parts) > 2 else '')
    elif ' SIP/2.0' in first:
        parts = first.split(' ', 2)
        msg.update(type='request', method=parts[0],
                   uri=parts[1] if len(parts) > 1 else '')
    else:
        return None

    body_idx = len(lines)
    for i, line in enumerate(lines[1:], 1):
        if not line.strip():
            body_idx = i + 1
            break
        if ':' in line:
            k, _, v = line.partition(':')
            k = k.strip().lower()
            if k not in msg['headers']:
                msg['headers'][k] = v.strip()

    msg['body'] = '\n'.join(lines[body_idx:]).strip()
    cseq = msg['headers'].get('cseq', '')
    parts = cseq.split()
    msg['cseq_num']    = parts[0] if parts else '1'
    msg['cseq_method'] = parts[1] if len(parts) > 1 else ''
    return msg


def _parse_sdp(sdp: str):
    """Return (remote_ip, remote_port, has_pcmu) from an SDP body."""
    ip, port, has_pcmu = None, None, False
    for line in sdp.replace('\r\n', '\n').split('\n'):
        line = line.strip()
        if line.startswith('c=IN IP4 '):
            ip = line[9:].strip()
        elif line.startswith('m=audio '):
            parts = line.split()
            if len(parts) >= 4:
                port      = int(parts[1])
                has_pcmu  = '0' in parts[3:]
    return ip, port, has_pcmu


def _parse_www_auth(hdr: str):
    """Extract (realm, nonce) from WWW-Authenticate header."""
    realm = re.search(r'realm="([^"]+)"', hdr)
    nonce = re.search(r'nonce="([^"]+)"', hdr)
    return (realm.group(1) if realm else ''), (nonce.group(1) if nonce else '')


# ── main class ────────────────────────────────────────────────────────────────

class TciSipPhone:
    # Jitter buffer constants (all in samples at 8 kHz)
    _JITTER_TARGET  = 480    # 60 ms pre-fill target depth
    _JITTER_MIN     = 80     # 10 ms: switch to comfort noise below this
    _JITTER_MAX     = 1_280  # 160 ms: shed toward target above this
    _COMFORT_LEVEL  = 0.003  # comfort noise amplitude ≈ -50 dBFS

    # AGC constants (applied per 20 ms frame)
    _AGC_TARGET  = 0.10   # target RMS ≈ -20 dBFS
    _AGC_MAX_GAIN = 12.0  # cap at +22 dB to avoid noise floor amplification
    _AGC_ATTACK  = 0.33   # α for level rising  (≈ 2 frame time constant)
    _AGC_RELEASE = 0.04   # α for level falling (≈ 25 frame time constant)

    def __init__(self, tci_host, tci_port, tci_trx,
                 sip_server, sip_user, sip_password, sip_port,
                 local_ip, rx_only, vox_threshold):

        # TCI
        self._tci_host = tci_host
        self._tci_port = tci_port
        self._tci_trx  = tci_trx
        self._ws:      Optional[websocket.WebSocket] = None
        self._ws_lock  = threading.Lock()

        # Audio ring buffers
        self._rx_lock = threading.Lock()
        self._tx_lock = threading.Lock()
        self._rx_buf  = np.zeros(0, dtype=np.float32)  # TCI → RTP
        self._tx_buf  = np.zeros(0, dtype=np.float32)  # RTP → TCI

        # SIP
        self._sip_server   = sip_server
        self._sip_port     = sip_port
        self._sip_user     = sip_user
        self._sip_password = sip_password
        self._local_ip     = local_ip or self._detect_local_ip(sip_server)
        self._sip_sock:    Optional[socket.socket] = None
        self._sip_lport    = 0

        # SIP registration state (persists across calls)
        self._reg_cseq    = 0
        self._from_tag    = _rnd()
        self._reg_call_id = _rnd(16) + '@' + self._local_ip
        self._realm       = ''
        self._nonce       = ''
        self._next_reg    = 0.0   # monotonic() trigger

        # Call state
        self._in_call   = False
        self._to_tag    = ''
        self._call_addr = None

        # RTP
        self._rtp_sock:   Optional[socket.socket] = None
        self._rtp_lport   = 0
        self._rtp_remote  = None   # (ip, port) set when call is active
        self._rtp_seq     = random.randint(0, 0xFFFF)
        self._rtp_ts      = random.randint(0, 0x7FFFFFFF)
        self._rtp_ssrc    = random.randint(0, 0xFFFFFFFF)

        # PTT / VOX
        self._rx_only       = rx_only
        self._vox_threshold = vox_threshold
        self._ptt_active    = False

        # Jitter buffer state (reset on each new call in _handle_invite)
        self._jitter_prefilled = False

        # AGC state (reset on each new call)
        self._agc_rms = self._AGC_TARGET

        # Clock drift correction: track buffer depth trend over a snapshot window.
        # If the buffer grows by N samples over M packets, we are consuming audio
        # slightly slower than TCI produces it; we trim next_t to compensate.
        self._drift_ts    = 0.0   # monotonic time of last snapshot
        self._drift_buf0  = 0     # buffer depth at last snapshot

        self._running = threading.Event()

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_local_ip(target: str) -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target, 80))
                return s.getsockname()[0]
        except Exception:
            return '127.0.0.1'

    def _reset_call_audio_state(self) -> None:
        """Clear audio buffers and reset per-call processing state."""
        with self._rx_lock:
            self._rx_buf = np.zeros(0, dtype=np.float32)
        self._jitter_prefilled = False
        self._agc_rms          = self._AGC_TARGET
        self._drift_ts         = 0.0
        self._drift_buf0       = 0

    # ── TCI ──────────────────────────────────────────────────────────────────

    def _tci_connect(self) -> None:
        url = f'ws://{self._tci_host}:{self._tci_port}'
        print(f'Connecting to TCI {url} ...')
        ws = websocket.WebSocket()
        ws.settimeout(10.0)
        ws.connect(url)
        self._ws = ws
        ws.settimeout(1.0)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                msg = ws.recv()
                if isinstance(msg, str) and 'ready' in msg.lower():
                    break
            except websocket.WebSocketTimeoutException:
                break
        for cmd in ['AUDIO_SAMPLERATE:8000', 'AUDIO_STREAM_SAMPLE_TYPE:int16',
                    'AUDIO_STREAM_CHANNELS:1', 'TX_STREAM_AUDIO_BUFFERING:150',
                    f'AUDIO_START:{self._tci_trx}']:
            ws.send(cmd + ';')
        ws.settimeout(0.5)
        print('TCI ready (8 kHz)')

    def _ws_send(self, data) -> None:
        with self._ws_lock:
            if self._ws:
                try:
                    if isinstance(data, (bytes, bytearray)):
                        self._ws.send_binary(data)
                    else:
                        self._ws.send(data)
                except Exception:
                    pass

    def _tci_receiver(self) -> None:
        ws = self._ws
        while self._running.is_set():
            try:
                frame = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                if self._running.is_set():
                    print('TCI connection lost.', flush=True)
                    self._running.clear()
                break

            if isinstance(frame, str):
                # Re-assert PTT with TCI audio source when CAT keys up
                for raw in frame.split(';'):
                    raw = raw.strip()
                    if ':' not in raw:
                        continue
                    cmd, _, args = raw.partition(':')
                    parts = args.split(',')
                    if (cmd.lower() == 'trx' and len(parts) >= 2
                            and parts[0] == str(self._tci_trx)
                            and parts[1].lower() == 'true'
                            and (len(parts) < 3 or parts[2].lower() != 'tci')):
                        self._ws_send(f'TRX:{self._tci_trx},true,tci;')
                continue

            if not isinstance(frame, bytes):
                continue
            result = _decode_tci(frame)
            if not result:
                continue

            if result[0] == 'rx':
                with self._rx_lock:
                    self._rx_buf = np.concatenate([self._rx_buf, result[1]])
                    # Hard cap at 4 s; blend toward cap to avoid a click.
                    # Rather than a hard slice, we let _rtp_sender's overflow
                    # handler deal with anything above _JITTER_MAX, so here we
                    # only guard against completely runaway growth (no active call).
                    if len(self._rx_buf) > 32_000:
                        self._rx_buf = self._rx_buf[-self._JITTER_TARGET:]

            elif result[0] == 'chrono':
                _, trx, rate, n = result
                if trx != self._tci_trx:
                    continue
                with self._tx_lock:
                    if len(self._tx_buf) >= n:
                        out, self._tx_buf = self._tx_buf[:n], self._tx_buf[n:]
                    else:
                        out = np.concatenate([
                            self._tx_buf,
                            np.zeros(n - len(self._tx_buf), dtype=np.float32),
                        ])
                        self._tx_buf = np.zeros(0, dtype=np.float32)
                self._ws_send(_encode_tci_tx(trx, rate, out))

    # ── SIP ──────────────────────────────────────────────────────────────────

    def _sip_send(self, msg: str, addr=None) -> None:
        if addr is None:
            addr = (self._sip_server, self._sip_port)
        try:
            self._sip_sock.sendto(msg.encode(), addr)
        except OSError:
            pass

    def _build_response(self, req: dict, status: int, reason: str,
                        body: str = '', with_tag: bool = True) -> str:
        hdrs = req['headers']
        to   = hdrs.get('to', '')
        if with_tag and ';tag=' not in to and self._to_tag:
            to += f';tag={self._to_tag}'

        lines = [
            f'SIP/2.0 {status} {reason}',
            f'Via: {hdrs.get("via", "")}',
            f'From: {hdrs.get("from", "")}',
            f'To: {to}',
            f'Call-ID: {hdrs.get("call-id", "")}',
            f'CSeq: {hdrs.get("cseq", "")}',
            f'Contact: <sip:{self._sip_user}@{self._local_ip}:{self._sip_lport}>',
            f'User-Agent: tci-sipphone/1.0',
            f'Allow: INVITE, ACK, BYE, CANCEL, OPTIONS',
        ]
        body_b = body.encode() if body else b''
        if body:
            lines.append('Content-Type: application/sdp')
        lines += [f'Content-Length: {len(body_b)}', '', body]
        return '\r\n'.join(lines)

    def _build_register(self, auth: str = '') -> str:
        uri = f'sip:{self._sip_server}'
        lines = [
            f'REGISTER {uri} SIP/2.0',
            f'Via: SIP/2.0/UDP {self._local_ip}:{self._sip_lport}'
            f';rport;branch=z9hG4bK{_rnd(12)}',
            f'From: <sip:{self._sip_user}@{self._sip_server}>;tag={self._from_tag}',
            f'To: <sip:{self._sip_user}@{self._sip_server}>',
            f'Call-ID: {self._reg_call_id}',
            f'CSeq: {self._reg_cseq} REGISTER',
            f'Contact: <sip:{self._sip_user}@{self._local_ip}:{self._sip_lport}>',
            f'Max-Forwards: 70',
            f'Expires: 60',
            f'User-Agent: tci-sipphone/1.0',
        ]
        if auth:
            lines.append(auth)
        lines += ['Content-Length: 0', '', '']
        return '\r\n'.join(lines)

    def _do_register(self, www_auth: str = '') -> None:
        self._reg_cseq += 1
        if www_auth:
            self._realm, self._nonce = _parse_www_auth(www_auth)
        auth = ''
        if self._realm and self._nonce:
            uri  = f'sip:{self._sip_server}'
            resp = _md5_digest(self._sip_user, self._realm, self._sip_password,
                               'REGISTER', uri, self._nonce)
            auth = (f'Authorization: Digest username="{self._sip_user}",'
                    f'realm="{self._realm}",nonce="{self._nonce}",'
                    f'uri="{uri}",response="{resp}",algorithm=MD5')
        self._sip_send(self._build_register(auth))

    def _make_sdp(self) -> str:
        return (f'v=0\r\n'
                f'o=tci-sipphone 1 1 IN IP4 {self._local_ip}\r\n'
                f's=TCI Radio\r\n'
                f'c=IN IP4 {self._local_ip}\r\n'
                f't=0 0\r\n'
                f'm=audio {self._rtp_lport} RTP/AVP 0\r\n'
                f'a=rtpmap:0 PCMU/8000\r\n'
                f'a=sendrecv\r\n')

    def _handle_invite(self, msg: dict, addr) -> None:
        if self._in_call:
            self._sip_send(self._build_response(msg, 486, 'Busy Here',
                                                with_tag=False), addr)
            return

        remote_ip, remote_port, has_pcmu = _parse_sdp(msg['body'])
        if not (has_pcmu and remote_ip and remote_port):
            self._sip_send(self._build_response(msg, 488, 'Not Acceptable Here',
                                                with_tag=False), addr)
            return

        self._to_tag    = _rnd()
        self._call_addr = addr
        self._sip_send(self._build_response(msg, 100, 'Trying', with_tag=False), addr)
        self._sip_send(self._build_response(msg, 200, 'OK', body=self._make_sdp()), addr)

        # Reset audio processing state before the call goes active so the
        # jitter buffer pre-fills cleanly and stale audio is discarded.
        self._reset_call_audio_state()

        self._rtp_remote = (remote_ip, remote_port)
        self._in_call    = True
        print(f'Call up → RTP to {remote_ip}:{remote_port}')

    def _handle_bye(self, msg: dict, addr) -> None:
        self._sip_send(self._build_response(msg, 200, 'OK'), addr)
        self._in_call    = False
        self._rtp_remote = None
        if self._ptt_active:
            self._ws_send(f'TRX:{self._tci_trx},false;')
            self._ptt_active = False
        print('Call ended.')

    def _sip_loop(self) -> None:
        while self._running.is_set():
            if time.monotonic() >= self._next_reg:
                self._do_register()
                self._next_reg = time.monotonic() + 50.0

            ready, _, _ = select.select([self._sip_sock], [], [], 0.5)
            if not ready:
                continue

            try:
                data, addr = self._sip_sock.recvfrom(65535)
            except OSError:
                continue
            msg = _parse_sip(data.decode('utf-8', errors='replace'))
            if msg is None:
                continue

            if msg['type'] == 'request':
                method = msg['method']
                if method == 'INVITE':
                    self._handle_invite(msg, addr)
                elif method == 'BYE':
                    self._handle_bye(msg, addr)
                elif method == 'ACK':
                    pass   # call fully confirmed
                elif method in ('OPTIONS', 'CANCEL'):
                    self._sip_send(self._build_response(msg, 200, 'OK'), addr)

            elif msg['type'] == 'response':
                if msg['cseq_method'] == 'REGISTER':
                    if msg['status'] in (401, 407):
                        www = (msg['headers'].get('www-authenticate')
                               or msg['headers'].get('proxy-authenticate', ''))
                        self._do_register(www)
                    elif msg['status'] == 200:
                        print(f'Registered: sip:{self._sip_user}@{self._sip_server}')

    # ── RTP ──────────────────────────────────────────────────────────────────

    def _rtp_sender(self) -> None:
        """Send 160-sample PCMU RTP packets every 20 ms while in a call.

        Audio quality improvements over a bare buffer-and-send loop:

        1. Jitter pre-fill: hold off sending until the buffer reaches
           _JITTER_TARGET samples (60 ms).  This absorbs WebSocket frame
           delivery jitter from TCI; without it the sender underruns on
           almost every packet when TCI delivers frames at > 20 ms intervals.

        2. Comfort noise: when the buffer genuinely underruns, send -50 dBFS
           white noise instead of silence.  Hard silence edges (0 → audio →
           0 → audio ...) cause click trains that the ear hears as buzz;
           comfort noise blends much more smoothly.

        3. Overflow shedding: when the buffer grows too deep, slowly shed
           toward the target depth by consuming extra samples.  Avoids the
           click from hard-slicing the buffer.

        4. Clock drift correction: every 5 seconds compare the current buffer
           depth to its level at the last snapshot.  If the SunSDR clock runs
           slightly faster than the system clock, the buffer grows; if slower,
           it shrinks.  Adjust the packet interval by a fraction of a sample
           per packet to correct the trend.

        5. AGC: track a smoothed RMS with asymmetric attack / release and
           apply a gain-limited scale so µ-law encoding always gets a
           well-levelled signal.
        """
        SAMPLES  = 160
        INTERVAL = 0.020   # 20 ms nominal

        # Drift snapshot interval (seconds).  Must be long enough to measure
        # a meaningful trend; 5 s gives ±1 sample/s resolution at 8 kHz.
        DRIFT_WINDOW = 5.0

        next_t = time.monotonic() + INTERVAL

        while self._running.is_set():
            # Pace to the 20 ms grid.  Reset the grid if we're not in a call
            # to avoid a burst of catch-up packets when the call starts.
            sleep_s = next_t - time.monotonic()
            if sleep_s > 0:
                time.sleep(sleep_s)
            next_t += INTERVAL

            if not self._in_call or not self._rtp_remote:
                next_t = time.monotonic() + INTERVAL
                # While idle, keep the buffer from growing unboundedly.
                with self._rx_lock:
                    if len(self._rx_buf) > self._JITTER_MAX:
                        self._rx_buf = self._rx_buf[-self._JITTER_TARGET:]
                continue

            # ── Jitter pre-fill ──────────────────────────────────────────
            with self._rx_lock:
                buf_len = len(self._rx_buf)

            if not self._jitter_prefilled:
                if buf_len < self._JITTER_TARGET:
                    # Not enough audio yet; reset the send grid and wait.
                    next_t = time.monotonic() + INTERVAL
                    continue
                self._jitter_prefilled = True
                self._drift_ts   = time.monotonic()
                self._drift_buf0 = buf_len
                print(f'Jitter buffer pre-filled ({buf_len} samples); starting RTP stream.')

            # ── Consume samples (or generate comfort noise) ──────────────
            with self._rx_lock:
                buf_len = len(self._rx_buf)

                if buf_len >= SAMPLES:
                    samples      = self._rx_buf[:SAMPLES].copy()
                    self._rx_buf = self._rx_buf[SAMPLES:]
                    underrun     = False
                else:
                    # True underrun: TCI stopped delivering audio (network
                    # hiccup, etc.).  Send comfort noise and reset pre-fill
                    # so we wait for the buffer to recover before resuming.
                    samples              = (np.random.randn(SAMPLES)
                                            * self._COMFORT_LEVEL).astype(np.float32)
                    self._rx_buf         = np.zeros(0, dtype=np.float32)
                    self._jitter_prefilled = False
                    underrun             = True

                # Overflow shedding: if the buffer has grown well past the
                # target, consume an extra packet's worth of silence so we
                # drain toward the target gradually.  This avoids needing a
                # hard slice (which would cause a click).
                if len(self._rx_buf) > self._JITTER_MAX:
                    excess = len(self._rx_buf) - self._JITTER_TARGET
                    shed   = min(excess // 2, SAMPLES)   # shed at most 1 extra packet
                    self._rx_buf = self._rx_buf[shed:]

            # ── Clock drift correction ────────────────────────────────────
            # After DRIFT_WINDOW seconds, compare current buffer depth to the
            # depth at the last snapshot.  A positive delta means TCI produces
            # audio faster than we send it → advance next_t to send slightly
            # faster.  The correction is spread across the next DRIFT_WINDOW
            # worth of packets so the adjustment is imperceptibly gradual.
            if not underrun:
                now = time.monotonic()
                if now - self._drift_ts >= DRIFT_WINDOW:
                    with self._rx_lock:
                        buf_now = len(self._rx_buf)
                    drift_samples    = buf_now - self._drift_buf0
                    packets_in_window = DRIFT_WINDOW / INTERVAL          # e.g. 250
                    # Advance (or retard) next_t by the equivalent time of the
                    # drift distributed over the next window's worth of packets.
                    # One sample at 8 kHz = 0.000125 s.
                    per_packet_adj   = (drift_samples / packets_in_window) / 8000.0
                    next_t          -= per_packet_adj * packets_in_window
                    self._drift_ts   = now
                    self._drift_buf0 = buf_now
                    if abs(drift_samples) > 8:   # only log if non-trivial
                        print(f'Drift correction: {drift_samples:+d} samples '
                              f'over {DRIFT_WINDOW:.0f} s '
                              f'({per_packet_adj*1e6:+.1f} µs/pkt)')

            # ── AGC ───────────────────────────────────────────────────────
            # Smooth envelope tracking: fast attack prevents clipping, slow
            # release avoids pumping on natural pauses in speech.
            rms = float(np.sqrt(np.mean(samples ** 2)))
            if rms > self._agc_rms:
                self._agc_rms += self._AGC_ATTACK  * (rms - self._agc_rms)
            else:
                self._agc_rms += self._AGC_RELEASE * (rms - self._agc_rms)

            if self._agc_rms > 1e-6:
                gain    = min(self._AGC_TARGET / self._agc_rms, self._AGC_MAX_GAIN)
                samples = np.clip(samples * gain, -1.0, 1.0)

            # ── Encode and send ───────────────────────────────────────────
            payload = _pcm_to_ulaw(samples)
            hdr = struct.pack('!BBHII',
                              0x80,                          # V=2,P=0,X=0,CC=0
                              0x00,                          # M=0, PT=0 (PCMU)
                              self._rtp_seq  & 0xFFFF,
                              self._rtp_ts   & 0xFFFFFFFF,
                              self._rtp_ssrc & 0xFFFFFFFF)
            self._rtp_seq += 1
            self._rtp_ts  += SAMPLES
            try:
                self._rtp_sock.sendto(hdr + payload, self._rtp_remote)
            except OSError:
                pass

    def _rtp_receiver(self) -> None:
        """Receive caller RTP; feed to TCI TX with VOX-gated PTT."""
        if self._rx_only:
            return

        VOX_ATTACK  = 5     # frames above threshold → PTT on
        VOX_RELEASE = 20    # frames below threshold → PTT off
        above = below = 0

        while self._running.is_set():
            try:
                ready, _, _ = select.select([self._rtp_sock], [], [], 0.1)
            except (ValueError, OSError):
                break
            if not ready or not self._in_call:
                continue
            try:
                pkt, _ = self._rtp_sock.recvfrom(2048)
            except OSError:
                continue
            if len(pkt) < 12 or (pkt[1] & 0x7F) != 0:
                continue   # not PCMU

            samples = _ulaw_to_pcm(pkt[12:])
            rms     = float(np.sqrt(np.mean(samples ** 2)))

            if rms > self._vox_threshold:
                above += 1
                below  = 0
                if above >= VOX_ATTACK and not self._ptt_active:
                    self._ptt_active = True
                    self._ws_send(f'TRX:{self._tci_trx},true,tci;')
            else:
                below += 1
                above  = 0
                if below >= VOX_RELEASE and self._ptt_active:
                    self._ptt_active = False
                    self._ws_send(f'TRX:{self._tci_trx},false;')

            if self._ptt_active:
                with self._tx_lock:
                    self._tx_buf = np.concatenate([self._tx_buf, samples])
                    if len(self._tx_buf) > 16_000:
                        self._tx_buf = self._tx_buf[-16_000:]

    # ── run / shutdown ────────────────────────────────────────────────────────

    def run(self) -> None:
        self._tci_connect()

        self._sip_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sip_sock.bind(('', 0))
        self._sip_lport = self._sip_sock.getsockname()[1]

        self._rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rtp_sock.bind(('', 0))
        self._rtp_lport = self._rtp_sock.getsockname()[1]

        print(f'Local IP      : {self._local_ip}')
        print(f'SIP local port: {self._sip_lport}')
        print(f'RTP local port: {self._rtp_lport}')

        self._running.set()
        for target, name in [
            (self._tci_receiver, 'tci-rx'),
            (self._sip_loop,     'sip'),
            (self._rtp_sender,   'rtp-tx'),
            (self._rtp_receiver, 'rtp-rx'),
        ]:
            threading.Thread(target=target, daemon=True, name=name).start()

        print('Running. Ctrl+C or SIGTERM to stop.')
        try:
            while self._running.is_set():
                time.sleep(0.25)
        except KeyboardInterrupt:
            pass
        self.shutdown()

    def shutdown(self) -> None:
        print('\nShutting down...')
        self._running.clear()
        if self._ptt_active:
            self._ws_send(f'TRX:{self._tci_trx},false;')
        with self._ws_lock:
            ws, self._ws = self._ws, None
        if ws:
            try:
                ws.send(f'AUDIO_STOP:{self._tci_trx};')
            except Exception:
                pass
            try:
                ws.close()
            except Exception:
                pass
        for s in (self._sip_sock, self._rtp_sock):
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        print('Done.')


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description='SIP softphone bridging TCI radio audio to FreePBX',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument('--tci-host',      required=True, metavar='HOST',
                    help='ExpertSDR3 TCI host IP/hostname')
    ap.add_argument('--tci-port',      type=int, default=50001, metavar='PORT',
                    help='TCI WebSocket port')
    ap.add_argument('--tci-trx',       type=int, default=0,     metavar='N',
                    help='TCI transceiver index (0-based)')
    ap.add_argument('--sip-server',    required=True, metavar='HOST',
                    help='FreePBX/Asterisk IP or hostname')
    ap.add_argument('--sip-user',      required=True, metavar='EXT',
                    help='SIP extension number to register as')
    ap.add_argument('--sip-password',  required=True, metavar='PASS',
                    help='SIP extension password')
    ap.add_argument('--sip-port',      type=int, default=5060,  metavar='PORT',
                    help='FreePBX SIP port')
    ap.add_argument('--local-ip',      default='',    metavar='IP',
                    help='Our IP address (auto-detected if omitted)')
    ap.add_argument('--rx-only',       action='store_true',
                    help="Don't send caller audio to radio TX")
    ap.add_argument('--vox-threshold', type=float, default=0.02, metavar='LEVEL',
                    help='VOX RMS trigger level (0.0–1.0)')
    args = ap.parse_args()

    phone = TciSipPhone(
        tci_host=args.tci_host, tci_port=args.tci_port, tci_trx=args.tci_trx,
        sip_server=args.sip_server, sip_user=args.sip_user,
        sip_password=args.sip_password, sip_port=args.sip_port,
        local_ip=args.local_ip or None,
        rx_only=args.rx_only,
        vox_threshold=args.vox_threshold,
    )
    signal.signal(signal.SIGTERM, lambda *_: phone._running.clear())
    phone.run()


if __name__ == '__main__':
    main()
