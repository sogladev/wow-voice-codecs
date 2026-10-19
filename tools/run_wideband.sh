#!/usr/bin/env bash
# Wideband half of the preview: needs a real recording at >= 16 kHz (a phone
# handset recording will not do, it has no content above 4 kHz either).
#
#   ./record_sample.sh
#   ./run_wideband.sh corpus/mic_sample_48k.wav
#
# The sample is cut to the first 12 seconds to keep PESQ fast.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE/.."

SRC="${1:?usage: run_wideband.sh <recording.wav [>=16 kHz]>}"
NAME="$(basename "$SRC" .wav)"
mkdir -p out corpus

RATE="$(soxi -r "$SRC")"
if [ "$RATE" -lt 16000 ]; then
    echo "$SRC is $RATE Hz; wideband needs at least 16000 Hz" >&2
    exit 1
fi

# 12 s, mono, and the three reference rates the preview works with
sox "$SRC" -b 16 -e signed-integer -c 1 -t wav "corpus/${NAME}_trim.wav" trim 0 12 2>/dev/null
sox "corpus/${NAME}_trim.wav" -b 16 -r 48000 "corpus/${NAME}_ref48.wav" rate -v 48000 2>/dev/null
sox "corpus/${NAME}_ref48.wav" -b 16 -r 16000 "corpus/${NAME}_ref16.wav" rate -v 16000 2>/dev/null
sox "corpus/${NAME}_ref48.wav" -b 16 -r 8000  "corpus/${NAME}_ref8.wav"  rate -v 8000  2>/dev/null

# the ceiling for any 8 kHz pipeline: the reference band-limited to 4 kHz, upsampled
sox "corpus/${NAME}_ref8.wav" -b 16 -r 16000 "out/${NAME}_ceiling8k.wav" rate -v 16000 2>/dev/null

echo "== bandwidth the sample actually contains =="
for f in "corpus/${NAME}_ref48.wav"; do
    tools/build/wav_metrics band "$f" | sed 's/^/  /'
done

echo
echo "== running codecs =="
# today's codec, 8 kHz, 100 ms packets
tools/build/spirit_probe "corpus/${NAME}_ref8.wav" "out/${NAME}_ipmr8k.wav" "out/${NAME}_ipmr8k.csv" 0 2>&1 | sed 's/^/  ipmr /'

# Opus narrowband in 100 ms and 60 ms packets
python3 tools/opus_pipeline.py "corpus/${NAME}_ref8.wav" "out/${NAME}_opus8k_f5" --bitrate 9600  --frames-per-packet 5 | sed 's/^/  nb100ms /'
python3 tools/opus_pipeline.py "corpus/${NAME}_ref8.wav" "out/${NAME}_opus8k_f3" --bitrate 9600  --frames-per-packet 3 | sed 's/^/  nb60ms  /'

# Opus wideband 16 kHz
for br in 16000 24000 32000; do
    python3 tools/opus_pipeline.py "corpus/${NAME}_ref16.wav" "out/${NAME}_opus16k_${br}_f3" --bitrate "$br" --frames-per-packet 3 | sed 's/^/  wb /'
done

# Opus fullband 48 kHz
for br in 32000 48000 64000; do
    python3 tools/opus_pipeline.py "corpus/${NAME}_ref48.wav" "out/${NAME}_opus48k_${br}_f3" --bitrate "$br" --frames-per-packet 3 | sed 's/^/  fb /'
done

echo
echo "== PESQ =="
printf "%-28s %10s %10s %10s\n" "decode" "PESQ" "STOI" "wire kbit/s"
score() {  # file, reference, mode, label
    local f="$1" ref="$2" mode="$3" label="$4" rate
    if [ "$mode" = nb ]; then rate=8000; else rate=16000; fi
    local base; base="$(basename "$f" .wav)"
    sox "$f" -b 16 -r "$rate" "out/m8/${base}_${mode}.wav" rate -v "$rate" 2>/dev/null
    local r; r=$(python3 tools/score.py "$ref" "out/m8/${base}_${mode}.wav" --mode "$mode" 2>/dev/null || true)
    local p s w
    p=$(echo "$r" | grep -oP 'pesq_\w+,\K.*' || echo "-")
    s=$(echo "$r" | grep -oP '^stoi,\K.*' || echo "-")
    w=$(grep -oP 'bitrate_kbps_wire,\K.*' "${f%.wav}.csv" 2>/dev/null || echo "-")
    printf "%-28s %10s %10s %10s\n" "$label" "$p" "$s" "$w"
}
mkdir -p out/m8
score "out/${NAME}_ipmr8k.wav"          "corpus/${NAME}_ref8.wav"  nb "today ipmr 8k"
score "out/${NAME}_opus8k_f5.wav"       "corpus/${NAME}_ref8.wav"  nb "opus nb 9k6 100ms"
score "out/${NAME}_opus8k_f3.wav"       "corpus/${NAME}_ref8.wav"  nb "opus nb 9k6 60ms"
for br in 16000 24000 32000; do
    score "out/${NAME}_opus16k_${br}_f3.wav" "corpus/${NAME}_ref16.wav" wb "opus wb ${br} 60ms"
done
for br in 32000 48000 64000; do
    score "out/${NAME}_opus48k_${br}_f3.wav" "corpus/${NAME}_ref16.wav" wb "opus fb ${br} 60ms"
done

echo
echo "listening files are in out/; the *_ref16.wav is the wideband reference"
