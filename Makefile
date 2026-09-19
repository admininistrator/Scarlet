.PHONY: up down test test-resume bench lint fmt migrate check-hardcode eval logs

COMPOSE := docker compose --profile core --profile tools

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

# B-199 — HAI tang, mot lenh. Truoc no, `make test` chi chay pytest cua backend
# va 12 task cua §7 (Phase 3) deu gia dinh co mot cho de dat test FE ma khong
# cho nao ton tai.
#
# Vi sao FE chay TRONG container `web` chu khong tren host: WSL nay khong co
# `node` (`pnpm` tro nham sang shim Windows), va `node_modules` that nam trong
# image. `make test` VON DA doi stack chay san — `tests/conftest.py` cua backend
# noi Postgres that (NQ-17) — nen day khong phai mot hop dong moi.
test:
	cd backend && .venv/bin/pytest
	$(COMPOSE) exec -T web pnpm test

# T-1.11 / S3 — ngắt giữa lúc stream rồi nối lại, so byte-by-byte với
# `messages.content`. KHÁC `make test`: cần cả stack đang chạy (`make up`) và
# gọi model THẬT, nên nó tốn tiền và tính bằng phút — đó là lý do nó là một
# target riêng chứ không nằm trong `pytest`.
test-resume:
	backend/.venv/bin/python scripts/test_resume.py

# T-1.12 / S2 — TTFT p50/p95 theo từng model. CÙNG HỌ `test-resume`, không phải
# `test`: cần cả stack đang chạy (`make up`) và gọi model THẬT 2 lần cho mỗi
# lượt (một qua Scarlet, một thẳng LiteLLM làm baseline), nên nó tốn tiền và
# tính bằng chục phút. Mã thoát ≠ 0 nếu có model trượt ngưỡng p95 của §2.3.
bench:
	backend/.venv/bin/python scripts/bench_ttft.py

lint:
	cd backend && .venv/bin/ruff check .
	cd backend && .venv/bin/mypy app
	$(COMPOSE) exec -T web pnpm typecheck

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
