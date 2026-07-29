.PHONY: bootstrap check test lint format typecheck dev infra-up infra-down

UV_CACHE_DIR ?= .sentinel/uv-cache
VENV_BIN ?= .venv/bin

bootstrap:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv sync --all-packages --all-extras
	npm install

check: lint typecheck test

test:
	$(VENV_BIN)/pytest apps/api/tests
	npm run test

lint:
	$(VENV_BIN)/ruff check apps/api
	$(VENV_BIN)/ruff format --check apps/api
	npm run lint

format:
	$(VENV_BIN)/ruff check --fix apps/api
	$(VENV_BIN)/ruff format apps/api
	npm run format

typecheck:
	$(VENV_BIN)/mypy apps/api/src
	npm run typecheck

dev:
	docker compose up -d postgres temporal minio minio-init
	@echo "Run 'npm run dev:web' and 'uv run --package sentinel-api sentinel-api' in separate terminals."

infra-up:
	docker compose up -d

infra-down:
	docker compose down
