.DEFAULT_GOAL := help

.PHONY: help setup dev test lint bundle airgap-test

VENV := .venv
PY := $(VENV)/bin/python

# `make bundle` settings; see docs/bundle.md.
TIER ?= laptop
MODELS_DIR ?= models/weights
SIGNING_KEY ?= $(HOME)/.config/arkanine/release-signing-key
PLATFORM ?=

# Test stack runs beside `make dev` on different ports and its own project.
TEST_ENV := COMPOSE_PROJECT_NAME=arkanine-test API_PORT=18000 FAKE_INFERENCE_PORT=18080 \
	INFERENCE_API_KEY=test-inference-key

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup: ## Install dependencies
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

dev: ## Run the stack locally; BACKEND=ollama|llamacpp|vllm uses a real model server
	docker compose $(if $(BACKEND),--env-file backends/$(BACKEND).env) up --build --wait
	@echo "API: http://localhost:8000/health"

test: ## Run the test suite
	@$(TEST_ENV) docker compose up --build --wait || { $(TEST_ENV) docker compose down --volumes; exit 1; }; \
	ARKANINE_API_URL=http://localhost:18000 \
		ARKANINE_FAKE_INFERENCE_URL=http://localhost:18080 $(PY) -m pytest; \
	code=$$?; \
	$(TEST_ENV) docker compose down --volumes; \
	exit $$code

lint: ## Run linters and type checks
	$(PY) -m ruff check src tests testing bundle
	$(PY) -m ruff format --check src tests testing bundle
	$(PY) -m mypy

lint-fix: ## Automatically fix linting issues
	$(PY) -m ruff check --fix src tests testing bundle
	$(PY) -m ruff format src tests testing bundle

bundle: ## Build the signed offline bundle in dist/; TIER=laptop|gpu|test
	$(PY) bundle/build.py --tier $(TIER) --models-dir $(MODELS_DIR) \
		--signing-key $(SIGNING_KEY) --out dist $(if $(PLATFORM),--platform $(PLATFORM))

airgap-test: ## Verify the stack runs with networking disabled
	@$(call todo,$@)

define todo
echo "make $(1): not implemented yet"; exit 1
endef
