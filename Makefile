.PHONY: install dev up down logs test lint fmt typecheck migrate clean ollama-pull

# --- Setup ---
install:
	pip install -e ".[dev]"

ollama-pull:
	ollama pull llama3.1:8b

# --- Local services (Redis, MCP servers via Docker) ---
up:
	docker compose up -d redis

up-all:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# --- Run app locally (outside Docker, for fast reload) ---
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# --- MCP servers (run individually for local dev) ---
mcp-calendar:
	python -m app.mcp.servers.calendar_server

mcp-email:
	python -m app.mcp.servers.email_server

mcp-tasks:
	python -m app.mcp.servers.tasks_server

mcp-all:
	./scripts/run_local_mcp_servers.sh

# --- Dev data ---
seed:
	python3 scripts/seed_dev_data.py

# --- Quality ---
test:
	pytest -v --cov=app --cov-report=term-missing

lint:
	ruff check app tests

fmt:
	ruff format app tests

typecheck:
	mypy app

# --- DB ---
migrate:
	alembic upgrade head

migration:
	alembic revision --autogenerate -m "$(name)"

# --- Cleanup ---
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage