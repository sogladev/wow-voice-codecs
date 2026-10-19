#!/usr/bin/env bash
# Serve the page locally.
#
# Byte ranges matter: without them the browser treats the audio as unseekable and the
# comparison cannot hold its position when you switch configuration. python3 -m
# http.server does not implement them, so this goes through tools/serve.py.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec python3 tools/serve.py "${1:-8788}"
