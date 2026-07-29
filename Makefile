.PHONY: bootstrap check test lint format typecheck dev infra-up infra-down trace-verify

UV_CACHE_DIR ?= .sentinel/uv-cache
VENV_BIN ?= .venv/bin

bootstrap:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv sync --all-packages --all-extras --locked
	npm ci

check: lint typecheck test

test:
	$(VENV_BIN)/pytest apps/api/tests
	npm run test

lint:
	$(VENV_BIN)/ruff check apps/api scripts
	$(VENV_BIN)/ruff format --check apps/api scripts
	npm run lint

format:
	$(VENV_BIN)/ruff check --fix apps/api scripts
	$(VENV_BIN)/ruff format apps/api scripts
	npm run format

typecheck:
	$(VENV_BIN)/mypy apps/api/src
	npm run typecheck

dev:
	docker compose up -d postgres temporal minio minio-init
	@echo "Run sentinel-api, sentinel-worker, and npm run dev:web in three terminals."

infra-up:
	docker compose up -d

infra-down:
	docker compose down

trace-verify:
	./scripts/export_codex_trace.py verify
