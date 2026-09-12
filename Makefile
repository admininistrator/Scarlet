.PHONY: up down test lint fmt migrate check-hardcode eval logs

COMPOSE := docker compose --profile core --profile tools

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

test:
	cd backend && .venv/bin/pytest

lint:
	cd backend && .venv/bin/ruff check .
	cd backend && .venv/bin/mypy app

fmt:
	cd backend && .venv/bin/ruff format .

migrate:
	cd backend && .venv/bin/alembic upgrade head

check-hardcode:
	bash scripts/check_hardcode.sh

eval:
	cd backend && .venv/bin/python ../evals/runner.py --model $(MODEL)

logs:
	$(COMPOSE) logs -f
