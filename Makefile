IMAGE = btc-predictor

.DEFAULT_GOAL := help

.PHONY: help build up up-d down logs test test-v lint validate install-local test-local lint-local

help: ## Show this help message
	@echo "BTC Predictor"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"} \
		/^[a-zA-Z0-9_-]+:.*##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Docker (default, no local Python needed)

build: ## Build all Docker images
	docker compose build

up: ## Start all services in the foreground
	docker compose up

up-d: ## Start all services in the background
	docker compose up -d

down: ## Stop all services
	docker compose down

logs: ## Follow api service logs
	docker compose logs -f api

test: ## Run the test suite in Docker (waits for postgres to be healthy)
	docker compose up -d --wait postgres
	docker compose run --rm api pytest

test-v: ## Run the test suite in Docker, verbose (waits for postgres to be healthy)
	docker compose up -d --wait postgres
	docker compose run --rm api pytest -v

lint: ## Lint shared/api-service/workers with ruff in Docker
	docker compose run --rm api ruff check shared api workers

validate: ## Run the full local quality gate: lockfile + lint + format + tests
	./scripts/validate.sh

##@ Local, no Docker, best-effort (requires Python 3.13 + Poetry active)

install-local: ## Install dependencies locally with Poetry
	poetry install

test-local: ## Run tests locally with Poetry
	poetry run pytest -v

lint-local: ## Lint locally with Poetry
	poetry run ruff check shared api-service workers
