#!/bin/zsh
set -eu
project_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$project_root"
exec .venv/bin/python -m dualsensedriver source \
  --credentials .credentials/pair/source --bind 127.0.0.1 "$@"
