#!/bin/bash
# Play any audio file through the IQ modulation/demodulation chain.
# Usage: play-iq.sh [OPTIONS] <audio-file>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE=usb
DEVICE=""
COMPRESS=1.5
FILTER="--filter-low 300 --filter-high 3000"
HF_ARGS=""

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] <audio-file>

Options:
  -m, --mode MODE       Modulation: am, fm, usb, lsb (default: usb)
  -d, --device DEV      Output device: PortAudio index or name substring
                         (default: system default output device)
  -c, --compress DRIVE  Compression drive (default: 1.5, 0 to disable)
  -w, --wide            Wide audio (no bandpass filter)
  -p, --preset PRESET   HF channel preset: clear, moderate, rough, dx,
                         aurora, contest, summer-80m, geomagnetic-storm
  --clean               No HF effects (passthrough)
  --snr DB              Override SNR (lower = noisier)
  --qrn RATE            Override QRN crash rate per second
  -h, --help            Show this help

Examples:
  $(basename "$0") audiobook.mp3
  $(basename "$0") -m fm podcast.wav
  $(basename "$0") -m am -c 3.0 --preset rough music.flac
  $(basename "$0") --clean audiobook.mp3
  $(basename "$0") --preset dx --snr 3 voice.wav
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -m|--mode)     MODE="$2"; shift 2 ;;
        -d|--device)   DEVICE="$2"; shift 2 ;;
        -c|--compress) COMPRESS="$2"; shift 2 ;;
        -w|--wide)     FILTER="--no-filter"; shift ;;
        -p|--preset)   HF_ARGS="$HF_ARGS --preset $2"; shift 2 ;;
        --clean)       HF_ARGS="--passthrough"; shift ;;
        --snr)         HF_ARGS="$HF_ARGS --snr $2"; shift 2 ;;
        --qrn)         HF_ARGS="$HF_ARGS --qrn $2"; shift 2 ;;
        -h|--help)     usage ;;
        -*)            echo "Unknown option: $1" >&2; exit 1 ;;
        *)             INPUT="$1"; shift ;;
    esac
done

if [[ -z "${INPUT:-}" ]]; then
    echo "Error: no input file specified" >&2
    usage
fi

if [[ ! -f "$INPUT" ]]; then
    echo "Error: file not found: $INPUT" >&2
    exit 1
fi

COMPRESS_ARG=""
if [[ "$COMPRESS" != "0" ]]; then
    COMPRESS_ARG="--compress $COMPRESS"
fi

# Output device: only pass --device when the user asked for one; otherwise
# demodulate.py --speaker uses the system default output device.
DEVICE_ARGS=()
if [[ -n "$DEVICE" ]]; then
    DEVICE_ARGS=(--device "$DEVICE")
fi

python3 "$SCRIPT_DIR/modulate.py" \
    --mode "$MODE" \
    --input "$INPUT" \
    $FILTER \
    $COMPRESS_ARG \
    --stdout \
  | python3 "$SCRIPT_DIR/hf-static.py" \
    $HF_ARGS \
  | python3 "$SCRIPT_DIR/demodulate.py" \
    --mode "$MODE" \
    --stdin \
    "${DEVICE_ARGS[@]}" \
    --speaker
