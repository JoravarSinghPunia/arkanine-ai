.DEFAULT_GOAL := help

.PHONY: help setup dev test lint bundle airgap-test

VENV := .venv
PY := $(VENV)/bin/python

# Test stack runs beside `make dev` on different ports and its own project.
TEST_ENV := COMPOSE_PROJECT_NAME=arkanine-test API_PORT=18000 FAKE_INFERENCE_PORT=18080

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup: ## Install dependencies
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

dev: ## Run the stack locally
	docker compose up --build --wait
	@echo "API: http://localhost:8000/health"

test: ## Run the test suite
	@$(TEST_ENV) docker compose up --build --wait || { $(TEST_ENV) docker compose down --volumes; exit 1; }; \
	ARKANINE_API_URL=http://localhost:18000 \
		ARKANINE_FAKE_INFERENCE_URL=http://localhost:18080 $(PY) -m pytest; \
	code=$$?; \
	$(TEST_ENV) docker compose down --volumes; \
	exit $$code

lint: ## Run linters and type checks
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m mypy

bundle: ## Build the signed offline bundle
	@$(call todo,$@)

airgap-test: ## Verify the stack runs with networking disabled
	@$(call todo,$@)

define todo
echo "make $(1): not implemented yet"; exit 1
endef
