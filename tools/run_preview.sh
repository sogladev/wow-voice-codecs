#!/usr/bin/env bash
# Voice codec preview: Spirit IPMR (the 3.3.5a client codec, built from the
# wowdecomp reference tree) against Opus at several rates and packet layouts.
#
#   ./run_preview.sh            # all corpus items, no loss
#   ./run_preview.sh loss       # corpus item 1 with 2% and 5% packet loss
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE/.."
mkdir -p out corpus

PROBE=tools/build/spirit_probe
METRICS=tools/build/wav_metrics
MODE="${1:-all}"

# --- IPMR, exactly as the client packetises: 1 x 100 ms frame per datagram ---
run_ipmr() {
    local item="$1" drop="${2:-0}"
    local tag="ipmr8k"
    [ "$drop" != "0" ] && tag="ipmr8k_loss${3}"
    $PROBE "corpus/${item}_ref8.wav" "out/${item}_${tag}.wav" "out/${item}_${tag}.csv" "$drop" \
        2> "out/${item}_${tag}.log"
    echo "  ${item} ${tag}: $(grep -E 'bitrate=|encode=' "out/${item}_${tag}.log" | tr '\n' ' ')"
}

# --- Opus: (input rate, bitrate, frames per packet) ---
run_opus() {
    local item="$1" rate="$2" bitrate="$3" fpp="$4" drop="${5:-0}" fec="${6:-0}"
    local khz
    khz="$(echo "$rate" | sed 's/000$//')"
    local src="corpus/${item}_ref${khz}"
    local tag="opus${khz}k_${bitrate}_f${fpp}"
    [ "$drop" != "0" ] && tag="${tag}_loss${drop}"
    local extra=()
    [ "$fec" != "0" ] && extra+=(--fec --expect-loss "$fec")
    python3 tools/opus_pipeline.py "$src.wav" "out/${item}_${tag}" \
        --bitrate "$bitrate" --frames-per-packet "$fpp" --drop-every "$drop" "${extra[@]}" \
        | sed 's/^/  /'
}

if [ "$MODE" = "loss" ]; then
    item=tts1
    # 2% loss = every 50th packet, 5% = every 20th
    run_ipmr "$item" 50 "2pct"
    run_ipmr "$item" 20 "5pct"
    run_opus "$item" 16000 24000 5 50 5
    run_opus "$item" 16000 24000 5 20 5
    exit 0
fi

for item in tts1 tts2 tts3; do
    echo "== $item =="
    run_ipmr "$item"
    run_opus "$item" 8000  6000   1
    run_opus "$item" 8000  12000  1
    run_opus "$item" 16000 16000  1
    run_opus "$item" 16000 24000  1
    run_opus "$item" 16000 24000  5
    run_opus "$item" 48000 32000  5
    run_opus "$item" 48000 48000  5
done
