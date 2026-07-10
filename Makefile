.PHONY: install dev cursor cursor-task test lint

VENV := ./venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip
AV   := $(VENV)/bin/ai-verify

install:
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install -e ".[dev]"

dev: install

cursor:
	$(AV) cursor --since 7d

cursor-task:
	$(AV) cursor task --latest

cursor-import:
	$(AV) cursor import --since 7d

test:
	$(VENV)/bin/pytest -q

lint:
	$(VENV)/bin/ruff check ai_verify/
	$(VENV)/bin/black --check ai_verify/
