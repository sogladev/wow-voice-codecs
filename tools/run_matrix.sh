#!/usr/bin/env bash
# Run every codec configuration over every item in corpus/items/.
#
# Each item is a 16 kHz, 10 second clip: corpus/items/<item>_ref16.wav.
# Outputs land in out/<item>_<config>.wav plus a .csv with bitrate and timing.
#
#   ./tools/run_matrix.sh              # all items
#   ./tools/run_matrix.sh item1        # one item
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE/.."

PROBE=tools/build/spirit_probe
[ -x "$PROBE" ] || { echo "build the probe first: ./tools/build.sh" >&2; exit 1; }

items=("$@")
[ ${#items[@]} -eq 0 ] && items=(item1 item2 item3 item4)

mkdir -p out corpus/items

for item in "${items[@]}"; do
    ref16="corpus/items/${item}_ref16.wav"
    ref8="corpus/items/${item}_ref8.wav"
    if [ ! -f "$ref16" ]; then echo "skip $item: no $ref16" >&2; continue; fi

    echo "== $item =="
    sox "$ref16" -b 16 -e signed-integer -r 8000 "$ref8" rate -v 8000 2>/dev/null
    # the ceiling: the reference band-limited to 4 kHz and upsampled, no codec involved
    sox "$ref8" -b 16 -r 16000 "out/${item}_ceiling8k.wav" rate -v 16000 2>/dev/null

    # today's protocol: 8 kHz, one 100 ms frame per datagram
    $PROBE "$ref8" "out/${item}_ipmr.wav" "out/${item}_ipmr.csv" 0 2> "out/${item}_ipmr.log"
    $PROBE "$ref8" "out/${item}_ipmr_loss.wav" "out/${item}_ipmr_loss.csv" 20 2> "out/${item}_ipmr_loss.log"
    echo "  ipmr $(grep -oP 'bitrate=\K[0-9.]+' "out/${item}_ipmr.log") kbit/s"

    # Opus, 8 kHz (narrowband) in 100 ms and 60 ms packets
    python3 tools/opus_pipeline.py "$ref8" "out/${item}_nb96_100" --bitrate 9600 --frames-per-packet 5 >/dev/null
    python3 tools/opus_pipeline.py "$ref8" "out/${item}_nb96_60"  --bitrate 9600 --frames-per-packet 3 >/dev/null
    python3 tools/opus_pipeline.py "$ref8" "out/${item}_nb96_60_loss" --bitrate 9600 --frames-per-packet 3 \
        --drop-every 20 --fec --expect-loss 10 >/dev/null

    # Opus, 16 kHz (wideband)
    python3 tools/opus_pipeline.py "$ref16" "out/${item}_wb96_100" --bitrate 9600  --frames-per-packet 5 >/dev/null
    python3 tools/opus_pipeline.py "$ref16" "out/${item}_wb16_100" --bitrate 16000 --frames-per-packet 5 >/dev/null
    python3 tools/opus_pipeline.py "$ref16" "out/${item}_wb16_60"  --bitrate 16000 --frames-per-packet 3 >/dev/null
    python3 tools/opus_pipeline.py "$ref16" "out/${item}_wb24_60"  --bitrate 24000 --frames-per-packet 3 >/dev/null
    python3 tools/opus_pipeline.py "$ref16" "out/${item}_wb32_60"  --bitrate 32000 --frames-per-packet 3 >/dev/null
    python3 tools/opus_pipeline.py "$ref16" "out/${item}_wb16_60_loss" --bitrate 16000 --frames-per-packet 3 \
        --drop-every 20 --fec --expect-loss 10 >/dev/null
    echo "  opus done"
done

echo
echo "next: ./tools/build_site.py"
