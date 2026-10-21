.PHONY: demo test eval compliance lint fmt

PY ?= python

demo:
	$(PY) -m membergraph.cli run "9月复购率环比下滑，给出一个30天挽回方案" --provider fake --out runs/demo

test:
	$(PY) -m pytest

eval:
	$(PY) evals/run.py --provider fake

compliance:
	$(PY) scripts/compliance_check.py .

lint:
	ruff check src tests evals

fmt:
	ruff format src tests evals
