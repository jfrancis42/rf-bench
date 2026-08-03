#!/usr/bin/env bash
#
# talk-to-myself.sh — talk into the H-250 USB handset mic and hear
# yourself back through the handset earpiece, processed through the full
# IQ chain: mic → modulate → HF channel sim → demodulate → speaker.
#
# A live "what does my voice sound like coming off the ionosphere?" loop.
#
# Usage:
#   ./talk-to-myself.sh                  # USB mode, 'moderate' HF preset
#   ./talk-to-myself.sh -m fm            # FM mode instead
#   ./talk-to-myself.sh -p dx            # weak-DX preset
#   ./talk-to-myself.sh -m am -p rough   # AM, disturbed band
#   ./talk-to-myself.sh --ptt            # push-to-talk: audio only while
#                                        #   the handset button is held
#   ./talk-to-myself.sh --clean          # no HF effects, clean passthrough
#   ./talk-to-myself.sh --list           # list audio devices and exit
#
# The mic and speaker auto-resolve to the H-250 handset by trying several
# strategies in turn (see resolve_device below); if none find the handset,
# they fall back to the system default input/output devices. So it works
# whether the handset is exposed directly by PortAudio, only through
# PipeWire, or not present at all.

set -euo pipefail

# Defaults
MODE="usb"
PRESET="moderate"
CLEAN=0
PTT=0

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    grep '^#' "$0" | grep -v '^#!' | sed 's/^# \{0,1\}//'
    exit 0
}

# resolve_device KIND  (KIND is "input" or "output")
#
# Print a device token for modulate.py/demodulate.py's --device on stdout:
#   - a PortAudio device index (int), or
#   - "pipewire" (route through PipeWire, handset set as its default), or
#   - "" (empty) meaning: omit --device and use the system default.
# Diagnostics go to stderr. Always exits 0 so `set -e` never trips here.
#
# Strategy order (first that works wins):
#   1. A PortAudio device whose name matches the handset AND actually opens
#      for this direction. (Works when PipeWire hasn't grabbed the raw ALSA
#      device, so PortAudio still lists "H-250 Handset" directly.)
#   2. The handset's PipeWire node: make it the default source/sink, then
#      route via PortAudio's "pipewire" (or "default") device. (Works when
#      PipeWire owns the device exclusively — the common desktop case.)
#   3. Give up on the handset; print "" so the caller uses the default.
resolve_device() {
    python3 - "$1" <<'PYEOF'
import subprocess
import sys

KIND = sys.argv[1]                 # "input" or "output"
is_in = KIND == "input"
NAME_HINTS = ("h-250", "h250", "handset")


def log(msg):
    print("  [resolve %s] %s" % (KIND, msg), file=sys.stderr)


def emit(token):
    print(token)
    sys.exit(0)


try:
    import sounddevice as sd
except Exception as e:
    log("sounddevice unavailable (%s); using default" % type(e).__name__)
    emit("")

try:
    devs = sd.query_devices()
except Exception as e:
    log("cannot query devices (%s); using default" % type(e).__name__)
    emit("")


def can_open(dev):
    """True if an in/out stream on `dev` opens and starts for this KIND."""
    try:
        cls = sd.InputStream if is_in else sd.OutputStream
        s = cls(samplerate=48000, channels=1, device=dev, blocksize=512)
        s.start(); s.stop(); s.close()
        return True
    except Exception as e:
        log("%r did not open: %s" % (dev, type(e).__name__))
        return False


# --- Strategy 1: direct PortAudio device by name, if it opens. ---
for i, d in enumerate(devs):
    chans = d["max_input_channels"] if is_in else d["max_output_channels"]
    if chans >= 1 and any(h in d["name"].lower() for h in NAME_HINTS):
        log("trying direct PortAudio device #%d %r" % (i, d["name"]))
        if can_open(i):
            log("using PortAudio device #%d" % i)
            emit(str(i))


# --- Strategy 2: handset PipeWire node -> set default, route via pipewire. ---
def handset_pw_node():
    kind = "sources" if is_in else "sinks"
    try:
        out = subprocess.run(["pactl", "list", "short", kind],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception as e:
        log("pactl unavailable (%s)" % type(e).__name__)
        return None
    for line in out.splitlines():
        f = line.split("\t")
        # f[1] is the node name, e.g. alsa_input.usb-TEC_H-250_Handset-00...
        if len(f) >= 2 and "monitor" not in f[1].lower() \
                and any(h in f[1].lower() for h in ("h-250", "h_250", "handset")):
            return f[1]
    return None


node = handset_pw_node()
if node:
    setcmd = "set-default-source" if is_in else "set-default-sink"
    log("found handset PipeWire node %r; %s" % (node, setcmd))
    try:
        subprocess.run(["pactl", setcmd, node], check=True,
                       capture_output=True, timeout=5)
    except Exception as e:
        log("could not set default (%s)" % type(e).__name__)
    for cand in ("pipewire", "default"):
        if any(d["name"] == cand for d in devs) and can_open(cand):
            log("routing through %r" % cand)
            emit(cand)


# --- Strategy 3: fall back to the system default device. ---
log("handset not found; falling back to system default %s" % KIND)
emit("")
PYEOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        -m|--mode)    MODE="$2"; shift 2 ;;
        -p|--preset)  PRESET="$2"; shift 2 ;;
        --ptt)        PTT=1; shift ;;
        --clean)      CLEAN=1; shift ;;
        --list)       python3 "$DIR/modulate.py" --list-devices; exit 0 ;;
        -h|--help)    usage ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# Resolve the mic (input) and speaker (output) independently. Each prints a
# token: a device index, "pipewire", or "" (empty → use the default).
echo "Resolving handset audio devices…" >&2
MIC_DEVICE="$(resolve_device input)"
SPK_DEVICE="$(resolve_device output)"

# Turn each token into --device args (or nothing, to use the default).
MIC_ARGS=()
[ -n "$MIC_DEVICE" ] && MIC_ARGS=(--device "$MIC_DEVICE")
SPK_ARGS=()
[ -n "$SPK_DEVICE" ] && SPK_ARGS=(--device "$SPK_DEVICE")

MIC_DESC="${MIC_DEVICE:-<system default>}"
SPK_DESC="${SPK_DEVICE:-<system default>}"

# Build the HF channel stage. --clean swaps in passthrough (no effects).
if [ "$CLEAN" -eq 1 ]; then
    HF=(python3 "$DIR/hf-static.py" --passthrough)
else
    HF=(python3 "$DIR/hf-static.py" --preset "$PRESET")
fi

# Optional push-to-talk gating on the handset button.
PTT_ARGS=()
if [ "$PTT" -eq 1 ]; then
    PTT_ARGS=(--ptt)
fi

if [ "$PTT" -eq 1 ]; then
    echo "Push-to-talk: HOLD the handset button to talk, release to mute." >&2
else
    echo "Talk into the handset — you'll hear yourself back through it." >&2
fi
echo "Mic: $MIC_DESC   Speaker: $SPK_DESC" >&2
echo "Mode: ${MODE^^}   HF: $([ "$CLEAN" -eq 1 ] && echo passthrough || echo "$PRESET")   Ctrl-C to stop." >&2

# mic → modulate → HF channel → demodulate → speaker.
python3 "$DIR/modulate.py"   --mode "$MODE" --mic   "${MIC_ARGS[@]}" "${PTT_ARGS[@]}" --stdout \
  | "${HF[@]}" \
  | python3 "$DIR/demodulate.py" --mode "$MODE" --stdin "${SPK_ARGS[@]}" --speaker
