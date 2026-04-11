.PHONY: check lint migrate run test

PYTHON ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

check: lint test

migrate:
	.venv/bin/alembic upgrade head

run:
	$(UVICORN) app.main:app --reload
