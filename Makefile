.PHONY: help
help:  ## Print this help menu
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup:  ## Set up the local development environment
	uv sync

.PHONY: lint
lint:  ## Run linters and the type checker
	uv run ruff check
	uv run ruff format --check
	uv run pyright

.PHONY: format
format:  ## Format the code
	uv run ruff check --fix
	uv run ruff format

.PHONY: test
test: lint  ## Run linters and the test suite
	uv run pytest

.PHONY: build
build:  ## Build the wheel and sdist into dist/
	uv build
