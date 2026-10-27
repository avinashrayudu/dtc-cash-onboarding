# dtc-cash-onboarding. Built by Avinash Rayudu.
PY ?= python3

.PHONY: install demo eval quick test data holdout train freeze-check onboard clean

install:
	$(PY) -m pip install -r requirements.txt

demo:
	@test -d data/raw || $(MAKE) data
	@test -d data/holdout/raw || $(MAKE) holdout
	@test -f models/frozen.json || $(MAKE) train
	$(PY) evals/run_evals.py

eval: demo

quick:
	$(PY) evals/run_evals.py --quick

test:
	$(PY) -m pytest -q tests

data:
	$(PY) data/generate_brands.py

holdout:
	$(PY) data/holdout/generate_holdout.py

train:
	$(PY) evals/train.py

freeze-check:
	-$(PY) evals/freeze.py --check

# make onboard BRAND=quillon-coffee UPLOAD=upload_1
onboard:
	$(PY) onboard/run.py data/raw/$(BRAND) $(UPLOAD)

clean:
	rm -rf out .pytest_cache
