#!/usr/bin/env bash
# SAMPLE_MODE from a clean clone with an empty .env: install, run the demo, run tests.
set -euo pipefail
SRC="${1:-$(git rev-parse --show-toplevel)}"
TMP="$(mktemp -d)"
git clone -q "$SRC" "$TMP/repo" && cd "$TMP/repo"
: > .env
python3 -m venv .v && .v/bin/pip install -q -r requirements.txt
env -u NVIDIA_API_KEY -u SAMPLE_MODE .v/bin/python run.py --input input_examples/example_1.json > /tmp/clean_run.json
.v/bin/python -c "import json;d=json.load(open('/tmp/clean_run.json'));assert d['status']=='success',d['status'];print('clean run:',d['status'],d['output']['result']['analysis']['top_cause_label'])"
env -u NVIDIA_API_KEY -u SAMPLE_MODE .v/bin/python -m pytest -q
