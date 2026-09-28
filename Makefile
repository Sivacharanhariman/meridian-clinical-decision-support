PYTHON ?= .venv/bin/python

.PHONY: setup backend frontend contracts check-contracts test build

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.lock
	cd frontend && npm ci

backend:
	$(PYTHON) -m uvicorn backend.app:app --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev -- --hostname 127.0.0.1 --port 3000

contracts:
	$(PYTHON) scripts/export_openapi.py
	cd frontend && npm run generate

check-contracts:
	$(PYTHON) scripts/export_openapi.py --check
	cd frontend && npm run generate:check

test:
	$(PYTHON) -m pytest
	cd frontend && npm run test

build:
	cd frontend && npm run typecheck && npm run build
