#!/usr/bin/env bash
# Serve the page locally. data.json is fetched, so opening index.html from disk
# will not work in most browsers.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
PORT="${1:-8788}"
echo "http://127.0.0.1:${PORT}/"
python3 -m http.server "$PORT"
