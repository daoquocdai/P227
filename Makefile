.DEFAULT_GOAL := help

ifeq ($(OS),Windows_NT)
SHELL := cmd.exe
.SHELLFLAGS := /C
PYTHON ?= .venv/Scripts/python.exe
NPM ?= npm.cmd
else
PYTHON ?= .venv/bin/python
NPM ?= npm
endif

BACKEND_HOST ?= 0.0.0.0
BACKEND_PORT ?= 8000
FRONTEND_DIR := frontend
PY_PATHS := src/main.py src/config.py src/database.py src/api src/models src/services tests/conftest.py tests/test_api tests/test_services mock_yolo.py

.PHONY: help install install-backend install-frontend \
	dev dev-backend dev-frontend mock \
	db-init \
	test lint format format-check build check \
	docker-up docker-down docker-logs clean

help: ## Hiển thị danh sách lệnh
	@$(PYTHON) -c "import re; from pathlib import Path; text=Path('Makefile').read_text(encoding='utf-8'); [print(f'{m.group(1):18} {m.group(2)}') for m in re.finditer(r'^([a-zA-Z0-9_-]+):.*?## (.*)$$', text, re.M)]"

install: install-backend install-frontend ## Cài dependencies backend và frontend

install-backend: ## Cài dependencies Python vào virtual environment
	$(PYTHON) -m pip install -r requirements.txt

install-frontend: ## Cài dependencies frontend theo package-lock.json
	cd $(FRONTEND_DIR) && $(NPM) ci

dev: ## Hướng dẫn chạy cả backend và frontend
	@echo Chay make dev-backend va make dev-frontend trong hai cua so CMD rieng.

dev-backend: ## Chạy FastAPI development server
	$(PYTHON) -m uvicorn src.main:app --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

dev-frontend: ## Chạy Vite development server
	cd $(FRONTEND_DIR) && $(NPM) run dev

mock: ## Gửi một sự kiện YOLO giả lập tới backend đang chạy
	$(PYTHON) mock_yolo.py

db-init: ## Khởi tạo data/app.db từ database/schema.sql
	$(PYTHON) -c "from src.database import initialize_database; print(initialize_database())"

test: ## Chạy toàn bộ backend tests
	$(PYTHON) -m pytest -q

lint: ## Kiểm tra Python bằng Ruff
	$(PYTHON) -m ruff check $(PY_PATHS)

format: ## Tự động format Python bằng Ruff
	$(PYTHON) -m ruff format $(PY_PATHS)
	$(PYTHON) -m ruff check --fix $(PY_PATHS)

format-check: ## Kiểm tra format mà không sửa file
	$(PYTHON) -m ruff format --check $(PY_PATHS)

build: ## Type-check và build frontend production
	cd $(FRONTEND_DIR) && $(NPM) run build

check: lint format-check test build ## Chạy toàn bộ kiểm tra trước khi commit/push

docker-up: ## Build và chạy Local Hub backend bằng Docker
	docker compose up --build -d

docker-down: ## Dừng Docker services
	docker compose down

docker-logs: ## Theo dõi log backend container
	docker compose logs -f backend

clean: ## Xóa cache/build artifacts sinh tự động trong workspace
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
