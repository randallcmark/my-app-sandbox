.PHONY: check lint migrate package-firefox-extension run test

PYTHON ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn
FIREFOX_EXTENSION_ZIP ?= dist/application-tracker-firefox.zip

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

check: lint test

migrate:
	.venv/bin/alembic upgrade head

create-admin:
	$(PYTHON) -m app.cli users create-admin --email "$$EMAIL"

package-firefox-extension:
	mkdir -p dist
	cd extensions/firefox && zip -r ../../$(FIREFOX_EXTENSION_ZIP) .

run:
	$(UVICORN) app.main:app --reload
