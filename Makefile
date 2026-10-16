.PHONY: up down test test-resume bench audit lint fmt migrate check-hardcode eval logs sync-theme check-theme check-identifiers test-artifact-origin test-voice check-networks prod-up prod-down s8

COMPOSE := docker compose --profile core --profile tools
SANDBOX_TIMEOUT_S := $(shell sed -n 's/^SANDBOX_TIMEOUT_S=//p' .env)

# T-9.4a — PROD = base + overlay prod, KHONG override dev (Cam bay ①). Hai stack
# chung project scarlet va chung volume tren may nay: doi qua lai bang
# make prod-up / make prod-down up — KHONG BAO GIO down -v.
PROD_FILES := docker-compose.yml:docker-compose.prod.yml
PROD := COMPOSE_FILE=$(PROD_FILES) docker compose --profile core --profile tools

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

# down cua dev truoc: ollama (profile local-llm o prod) va container
# dev khac khong o lai chay lan voi ban prod. --build: code nam TRONG image.
prod-up:
	$(COMPOSE) down
	$(PROD) up -d --build --wait

prod-down:
	$(PROD) down

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
	$(COMPOSE) run --rm --no-deps -T fetcher python -m pytest -q -p no:cacheprovider
	$(COMPOSE) run --rm --no-deps -T -e TMPDIR=/work -e SANDBOX_TIMEOUT_S=$(SANDBOX_TIMEOUT_S) -v ./skills:/skills:ro sandbox python -m pytest -q -p no:cacheprovider

# T-6.5 — dong cuoi cua `test`: test cua `fetcher` chay TRONG image `fetcher`
# (khong co `app`, khong co `.env` — dung moi truong ma `ssrf.py` phai song duoc),
# mang gia o tang socket nen khong ra Internet.
# T-7.3 — test cua `sandbox` cung vay, trong image `sandbox` voi cap / tmpfs cua
# service. `TMPDIR=/work`: rootfs read-only, `pytest` can mot cho tao tep tam.
# T-7.4 — `SANDBOX_TIMEOUT_S` lay tu `.env` (sandbox khong doc `.env`, C27): ca
# `while True` cua `test_isolation.py` do dung tran `worker` gui.

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

# T-3.2 / S8 — Lighthouse Accessibility + @axe-core/cli tren bon duong cua P3.
# CUNG HO `bench`/`test-resume`, khong phai `test`: can ca stack dang chay
# (`make up`), vi no do mot trang that bang mot Chrome that. Ma thoat = so
# duong truot nguong.
#
# Vi sao `run --rm` chu khong `exec`: service `audit` o `profile: dev` va
# KHONG chay thuong truc — DoD cua T-3.2 doi `docker compose --profile core
# --profile tools ps` khong thay no. `--profile core` co mat de `depends_on:
# web` keo duoc `web` len; `-T` de dau ra khong bi pseudo-tty lam roi, giong
# `make test`.
#
#   make audit                     bon duong
#   make audit ROUTE=/dang-nhap    mot duong, dung luc sua loi
audit:
	docker compose --profile core --profile dev run --rm -T -e ROUTE="$(ROUTE)" audit

# T-5.6 / S12 — artifact o origin phu khong doc duoc gi cua origin chinh. CUNG
# ho `test-resume`: can stack dang chay (Nginx, api). Refresh token phat trong
# `api` roi noi THANG vao stdin cua script (khong qua argv / env); script tu
# logout o cuoi. Ma thoat = so dong truot. Xem `scripts/test_artifact_origin.mjs`.
test-artifact-origin:
	$(COMPOSE) exec -T api python - < scripts/artifact_origin_session.py \
	  | docker compose --profile core --profile dev run --rm -T --no-deps artifact-origin

# T-8.4 — mic + Doc to tren Chromium VA Firefox ESR that, qua Nginx (https).
# Cung image + netns voi `test-artifact-origin` (service `artifact-origin`),
# cung loi token qua stdin. Ma thoat = so dong hong. Xem `scripts/test_voice.mjs`.
test-voice:
	$(COMPOSE) exec -T api python - < scripts/voice_session.py \
	  | docker compose --profile core --profile dev run --rm -T --no-deps artifact-origin node scripts/test_voice.mjs

# T-9.4a / S8 (NQ-77) — Lighthouse mobile Performance + Accessibility QUA NGINX
# https, cung image + netns + loi token qua stdin voi `test-artifact-origin`.
# Chay duoc tren stack dev lan prod (doi chung). Ma thoat = so duong truot.
s8:
	$(COMPOSE) exec -T api python - < scripts/s8_session.py \
	  | docker compose --profile core --profile dev run --rm -T --no-deps artifact-origin node scripts/s8_lighthouse.mjs

lint: check-theme check-identifiers check-networks
	cd backend && .venv/bin/ruff check .
	cd backend && .venv/bin/mypy app
	$(COMPOSE) exec -T web pnpm typecheck

# B-249 — `design/theme.css` la NGUON (ban Claude Design giao, cong phan app
# them vao). `frontend/src/styles/theme.css` la BAN CHEP y nguyen, vi container
# `web` chi mount `frontend/`. Sua o `design/` roi `make sync-theme`; sua thang
# ban chep thi `make lint` do. Hai ban lech nhau la hong trong im lang (B-226).
THEME_SRC := design/theme.css
THEME_DST := frontend/src/styles/theme.css

sync-theme:
	cp $(THEME_SRC) $(THEME_DST)

check-theme:
	@cmp -s $(THEME_SRC) $(THEME_DST) || { echo "check-theme: $(THEME_DST) lech $(THEME_SRC) — sua o design/ roi chay 'make sync-theme'"; exit 1; }
	@echo "check-theme: OK"

# T-S.1 / NQ-109 — dinh danh tieng Viet khong dau (bien, ham, lop, prop, ten
# file) khong duoc quay lai `backend/`, `frontend/src/`, `scripts/`. Ten nao
# la hop dong (khoa JSON, co CLI, khoa config) thi vao `_ALLOWED` cua chinh
# script, kem ly do. Bang doi ten cu -> moi: `scripts/renames-T-S.1.tsv`.
check-identifiers:
	backend/.venv/bin/python scripts/check_identifiers.py

# T-6.5 / B-117 — lop 1 cua §12.2 doc tren cau hinh compose DA GOP: `fetcher`
# chi `egress`, khong env/cong; `worker` hai mang; `api` khong `egress`;
# T-7.2 — `sandbox` `network_mode: none`, khong mang, khong env/cong (ADR-09, C27).
# T-9.4a — ca cau hinh prod da gop (COMPOSE_FILE cua docker compose).
check-networks:
	backend/.venv/bin/python scripts/check_networks.py
	COMPOSE_FILE=$(PROD_FILES) backend/.venv/bin/python scripts/check_networks.py

fmt:
	cd backend && .venv/bin/ruff format .

migrate:
	cd backend && .venv/bin/alembic upgrade head

check-hardcode:
	bash scripts/check_hardcode.sh

eval:
	cd backend && .venv/bin/python ../evals/runner.py --model $(MODEL) $(ARGS)

logs:
	$(COMPOSE) logs -f
