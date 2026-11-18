#!/usr/bin/env bash
# Create a virtual environment, install pinned packages, run the tests, then print the article's results.
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt
python -m pytest
python -m src.totals_demo
