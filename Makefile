PY ?= .venv/bin/python
.PHONY: setup data run api ui test eval-dev eval-test scan clean-check bridge docker
setup:            ## venv + deps
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
data:             ## demo snapshot + eval datasets (synthetic, seeded)
	$(PY) scripts/make_data.py && $(PY) eval/build_datasets.py
run:              ## one demo run (SAMPLE_MODE)
	SAMPLE_MODE=true $(PY) run.py --input input_examples/example_1.json
api:
	$(PY) run.py --serve
ui:
	$(PY) run.py --ui
test:
	$(PY) -m pytest -q
eval-dev:
	SAMPLE_MODE=true $(PY) eval/eval.py --split dev
eval-test:        ## frozen test split; run sparingly and log in eval/RESULTS_HISTORY.md
	$(PY) eval/eval.py --split test --freeze
scan:
	$(PY) scripts/secret_scan.py
clean-check:
	./scripts/clean_clone_check.sh
bridge:           ## rebuild the Meterless bridge bundle
	./meterless_bridge/build.sh
docker:
	docker compose up --build
