#!/usr/bin/env bash
# Record a 15 s wideband voice sample for the codec preview.
#
# Speak normally, about 30 cm from the microphone, the way you would talk on
# voice chat during a raid. Roughly this text is enough:
#
#   "Alright, pulling the pack now. Watch the healer, I am out of mana.
#    Move left around the corner, the patrol is coming back in ten seconds.
#    Nice work on that boss, let us reset and take the next pull slower."
#
# Usage: ./record_sample.sh [output.wav]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$HERE/../corpus/mic_sample_48k.wav}"
mkdir -p "$(dirname "$OUT")"

SRC="${MIC_SOURCE:-alsa_input.usb-Razer_Inc_Razer_Seiren_Mini_UC2119L03204002-00.mono-fallback}"

echo "recording 15 s from $SRC ... speak now"
ffmpeg -hide_banner -loglevel error -y \
    -f pulse -i "$SRC" \
    -t 15 -ac 1 -ar 48000 -c:a pcm_s16le "$OUT"
echo "wrote $OUT ($(soxi -r "$OUT") Hz, $(soxi -d "$OUT") s)"
echo
echo "next: ./tools/run_wideband.sh $OUT"
