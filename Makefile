.DEFAULT_GOAL := help

ifeq ($(OS),Windows_NT)
SHELL := cmd.exe
.SHELLFLAGS := /D /C
SYSTEM_PYTHON ?= python
PYTHON ?= .venv\Scripts\python.exe
NPM ?= npm.cmd
else
SYSTEM_PYTHON ?= python3
PYTHON ?= .venv/bin/python
NPM ?= npm
endif

BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
FRONTEND_DIR := frontend
PYTHON_PATHS := src tests
COMPOSE := docker compose
VISION_PROFILE ?= cpu
VISION_REQUIREMENTS := requirements/vision-$(VISION_PROFILE).txt
VISION_IDENTITY_REQUIREMENTS := requirements/vision-identity.txt

.PHONY: help setup venv install install-backend install-frontend \
	dev dev-backend dev-frontend db-init \
	test lint format format-check frontend-build check \
	docker-config docker-build docker-up docker-start docker-stop docker-down \
	docker-restart docker-rebuild docker-ps docker-logs docker-logs-backend \
	docker-logs-frontend docker-health clean

help: ## Show available commands
	@$(SYSTEM_PYTHON) -c "import re; from pathlib import Path; text=Path('Makefile').read_text(encoding='utf-8'); [print(f'{m.group(1):22} {m.group(2)}') for m in re.finditer(r'^([a-zA-Z0-9_-]+):.*?## (.*)$$', text, re.M)]"

setup: venv install ## Create the virtual environment and install all dependencies

venv: ## Create .venv when it does not exist
ifeq ($(OS),Windows_NT)
	@if not exist ".venv\Scripts\python.exe" $(SYSTEM_PYTHON) -m venv .venv
else
	@test -x "$(PYTHON)" || $(SYSTEM_PYTHON) -m venv .venv
endif

install: install-backend install-frontend ## Install backend and frontend dependencies

install-backend: ## Install Python dependencies into .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r $(VISION_REQUIREMENTS)
	$(PYTHON) -m pip install --no-deps -r $(VISION_IDENTITY_REQUIREMENTS)

install-frontend: ## Install exact frontend dependencies from package-lock.json
	cd $(FRONTEND_DIR) && $(NPM) ci

dev: ## Explain how to start local development
	@echo Run "make dev-backend" and "make dev-frontend" in two terminals.

dev-backend: ## Start FastAPI with automatic reload
	$(PYTHON) -m uvicorn src.main:app --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

dev-frontend: ## Start the Vite development server
	cd $(FRONTEND_DIR) && $(NPM) run dev

db-init: ## Initialize or migrate data/app.db
	$(PYTHON) -c "from src.database import initialize_database; initialize_database(); print('Database ready.')"

test: ## Run the complete Python test suite
	$(PYTHON) -m pytest -q

lint: ## Run Ruff lint checks
	$(PYTHON) -m ruff check $(PYTHON_PATHS)

format: ## Format Python and apply safe Ruff fixes
	$(PYTHON) -m ruff format $(PYTHON_PATHS)
	$(PYTHON) -m ruff check --fix $(PYTHON_PATHS)

format-check: ## Verify Python formatting without changing files
	$(PYTHON) -m ruff format --check $(PYTHON_PATHS)

frontend-build: ## Type-check and build the production frontend
	cd $(FRONTEND_DIR) && $(NPM) run build

check: lint format-check test frontend-build ## Run all checks before publishing changes

docker-config: ## Validate and render the Compose configuration
	$(COMPOSE) config --quiet

docker-build: docker-config ## Build the CPU-only backend and frontend images
	$(COMPOSE) build

docker-up: docker-config ## Build and start the complete stack in the background
	$(COMPOSE) up --build --detach

docker-start: docker-config ## Start the stack without rebuilding images
	$(COMPOSE) up --detach

docker-stop: ## Stop containers without removing them
	$(COMPOSE) stop

docker-down: ## Stop and remove containers and the Compose network
	$(COMPOSE) down

docker-restart: ## Restart existing containers
	$(COMPOSE) restart

docker-rebuild: docker-config ## Rebuild images from scratch and restart the stack
	$(COMPOSE) build --no-cache
	$(COMPOSE) up --detach

docker-ps: ## Show service and health status
	$(COMPOSE) ps

docker-logs: ## Follow logs from all services
	$(COMPOSE) logs --follow --tail=200

docker-logs-backend: ## Follow backend logs
	$(COMPOSE) logs --follow --tail=200 backend

docker-logs-frontend: ## Follow frontend logs
	$(COMPOSE) logs --follow --tail=200 frontend

docker-health: ## Call the backend health endpoint from its container
	$(COMPOSE) exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read().decode())"

clean: ## Remove generated caches and frontend build output
ifeq ($(OS),Windows_NT)
	@for /d /r src %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
	@for /d /r tests %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
	@if exist .pytest_cache rmdir /s /q .pytest_cache
	@if exist .ruff_cache rmdir /s /q .ruff_cache
	@if exist frontend\dist rmdir /s /q frontend\dist
else
	find src tests -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache frontend/dist
endif
