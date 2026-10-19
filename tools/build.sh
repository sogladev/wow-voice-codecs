#!/usr/bin/env bash
# Build the offline IPMR probe.
#
# The Spirit IPMR codec itself is NOT part of this repository: it is the decompiled
# voice codec from the 3.3.5a client, which this project does not redistribute.
# Point DECOMP at a wowdecomp checkout; that tree is only read, never modified.
#
#   DECOMP=/path/to/wowdecomp ./tools/build.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DECOMP="${DECOMP:-$HOME/wd/client/wowdecomp}"
BUILD="$HERE/build"
mkdir -p "$BUILD"

if [ ! -d "$DECOMP/Engine/Source/ComSat/SPIRIT" ]; then
    echo "no decompiled client at $DECOMP" >&2
    echo "set DECOMP to a wowdecomp checkout containing Engine/Source/ComSat/SPIRIT" >&2
    exit 1
fi

SPIRIT_SRCS=$(ls "$DECOMP"/Engine/Source/ComSat/SPIRIT/*.cpp)

echo "reference tree: $DECOMP"
g++ -std=c++17 -O2 -msse2 -DIPMR_PLC -I"$DECOMP" \
    "$HERE/spirit_probe.cpp" $SPIRIT_SRCS \
    -o "$BUILD/spirit_probe"
g++ -std=c++17 -O2 "$HERE/wav_metrics.cpp" -o "$BUILD/wav_metrics"

echo "built: $BUILD/spirit_probe $BUILD/wav_metrics"
