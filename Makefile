SHELL := /bin/bash
VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
NPM ?= npm

.PHONY: help setup setup-backend setup-frontend dev api build serve test test-backend test-frontend test-release check check-release predict evaluate docker-up docker-down

help:
	@printf '%s\n' 'make setup              Install Python + frontend dependencies' 'make dev                Local API :8000 and UI :5173' 'make build && make serve  Build UI and serve everything on :8000' 'make check              Tests, TypeScript, UI build, release hygiene' 'make predict IN=/private/tickets.jsonl OUT=/private/pred.jsonl' 'make evaluate IN=/private/tickets.jsonl OUT=/private/report.json' 'make docker-up          Build + run a loopback-only Docker demo' 'make docker-down        Stop containers; keep runtime data'

setup: setup-backend setup-frontend

setup-backend:
	python3 -m venv "$(VENV)"
	"$(PYTHON)" -m pip install -c constraints.txt -r backend/requirements-dev.txt

setup-frontend:
	cd frontend && $(NPM) ci --no-audit --no-fund

dev:
	"$(PYTHON)" scripts/with_env.py "$(PYTHON)" scripts/dev.py

api:
	"$(PYTHON)" scripts/with_env.py "$(PYTHON)" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload --reload-dir backend/app --no-access-log

build:
	cd frontend && $(NPM) run build

serve:
	FRONTEND_DIST="$$(pwd)/frontend/dist" "$(PYTHON)" scripts/with_env.py "$(PYTHON)" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log

test: test-backend test-frontend test-release

test-backend:
	APP_MODE=test ENABLE_GROQ=false PYTHONPATH=backend "$(PYTHON)" -m pytest -q backend/tests

test-release:
	"$(PYTHON)" -m pytest -q scripts/tests

test-frontend:
	cd frontend && $(NPM) test && $(NPM) run typecheck

check-release:
	python3 scripts/check_release.py

check: test build check-release

predict:
	@test -n "$(IN)" && test -n "$(OUT)" || (echo 'Usage: make predict IN=/private/tickets.jsonl OUT=/private/pred.jsonl' >&2; exit 2)
	PYTHONPATH=backend "$(PYTHON)" scripts/with_env.py "$(PYTHON)" -m app.cli predict --input "$(IN)" --output "$(OUT)"

evaluate:
	@test -n "$(IN)" && test -n "$(OUT)" || (echo 'Usage: make evaluate IN=/private/tickets.jsonl OUT=/private/report.json' >&2; exit 2)
	PYTHONPATH=backend "$(PYTHON)" scripts/with_env.py "$(PYTHON)" -m app.cli evaluate --input "$(IN)" --output "$(OUT)"

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
