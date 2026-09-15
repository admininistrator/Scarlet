.PHONY: up down test test-resume lint fmt migrate check-hardcode eval logs

COMPOSE := docker compose --profile core --profile tools

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

test:
	cd backend && .venv/bin/pytest

# T-1.11 / S3 — ngắt giữa lúc stream rồi nối lại, so byte-by-byte với
# `messages.content`. KHÁC `make test`: cần cả stack đang chạy (`make up`) và
# gọi model THẬT, nên nó tốn tiền và tính bằng phút — đó là lý do nó là một
# target riêng chứ không nằm trong `pytest`.
test-resume:
	backend/.venv/bin/python scripts/test_resume.py

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
