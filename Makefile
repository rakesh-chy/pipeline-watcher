.PHONY: help install install-dev db-up db-down db-reset init seed demo serve check test lint format clean

help:
	@echo "Common targets:"
	@echo "  install      Install the package"
	@echo "  install-dev  Install with dev extras (pytest, ruff)"
	@echo "  db-up        Start Postgres via docker-compose"
	@echo "  db-down      Stop Postgres"
	@echo "  db-reset     Wipe + recreate the Postgres volume"
	@echo "  init         Create schema in Postgres"
	@echo "  seed         Register the demo pipelines"
	@echo "  demo         Run a full demo (seed + emit heartbeats + run checks)"
	@echo "  serve        Run the FastAPI status page on :8080"
	@echo "  check        Run the SLA evaluator once"
	@echo "  test         Run pytest"
	@echo "  lint         Run ruff"
	@echo "  format       Format with ruff"
	@echo "  clean        Remove caches"

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-reset:
	docker compose down -v && docker compose up -d postgres

init:
	watcher init

seed:
	watcher seed

demo:
	watcher demo

serve:
	watcher serve

check:
	watcher check

test:
	pytest -v

lint:
	ruff check src tests

format:
	ruff format src tests

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
