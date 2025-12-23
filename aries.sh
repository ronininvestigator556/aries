#!/usr/bin/env bash
set -e

if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python -m aries.cli "$@"
elif command -v python3 >/dev/null 2>&1; then
  exec python3 -m aries.cli "$@"
else
  echo "Python interpreter not found. Install Python 3.11-3.13 and/or activate the project's virtual environment." >&2
  exit 1
fi
