.DEFAULT_GOAL := help

.PHONY: help setup dev test lint bundle airgap-test

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup: ## Install dependencies
	@$(call todo,$@)

dev: ## Run the stack locally
	@$(call todo,$@)

test: ## Run the test suite
	@$(call todo,$@)

lint: ## Run linters and type checks
	@$(call todo,$@)

bundle: ## Build the signed offline bundle
	@$(call todo,$@)

airgap-test: ## Verify the stack runs with networking disabled
	@$(call todo,$@)

define todo
echo "make $(1): not implemented yet"; exit 1
endef
