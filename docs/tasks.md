# SCARLET — HÀNG ĐỢI CÔNG VIỆC

> **File này trả lời: THỨ TỰ NÀO và XONG KHI NÀO.**
> *Cái gì* và *tại sao* nằm ở `docs/KE-HOACH.md`. *Giao việc thế nào* nằm ở `docs/HUONG-DAN-AGENT.md`.
>
> Version 1.0 · 2026-09-10 · Cập nhật mỗi commit.

---

## 0. Cách dùng file này

### 0.1 Giao thức cho agent — sáu luật

| # | Luật |
|---|---|
| **G1** | **Mỗi lần làm ĐÚNG MỘT task.** Xong, báo cáo, chờ nghiệm thu. Không tự nhảy sang task kế tiếp, kể cả khi thấy nó dễ |
| **G2** | **Đọc mục KH tham chiếu TRƯỚC khi viết dòng code đầu tiên.** Task chỉ ghi *làm gì*; kế hoạch ghi *tại sao thế và không phải cách kia* |
| **G3** | **DoD là hợp đồng, không phải gợi ý.** Chạy đúng lệnh trong DoD, dán output thật vào báo cáo. Không được viết "đã test kỹ" thay cho output |
| **G4** | **Task đánh dấu 🔒 KHÔNG ĐƯỢC GỘP làm một mình, một commit riêng.** Gộp nó với task khác là lý do hợp lệ để reject toàn bộ phiên làm việc |
| **G5** | **Gặp mâu thuẫn giữa task và kế hoạch → DỪNG và hỏi.** Không tự hoà giải, không tự "đơn giản hoá" (A10) |
| **G6** | **Ý tưởng nảy ra giữa chừng → ghi vào §Backlog, KHÔNG code ngay.** Kể cả khi chỉ mất 5 phút |

### 0.2 Ký hiệu trạng thái

| Ký hiệu | Nghĩa |
|---|---|
| ☐ | Chưa làm |
| 🔄 | Đang làm |
| 🚧 | BLOCKED — **phải ghi kèm: chặn bởi cái gì, cần ai quyết cái gì** |
| ✅ | Xong, DoD đã chạy và đạt |
| ⏭️ | Bỏ qua — **phải kèm số ADR hoặc dòng trong Nhật ký quyết định** |

### 0.3 Quy ước ID

- `T-<phase>.<số>` — task của agent. `T-0.4` = phase 0, task 4.
- `T-H<số>` — việc của NGƯỜI, agent không làm được.
- `🔒` — không được gộp với task khác.
- `⭐` — task quyết định chất lượng sản phẩm; sai ở đây thì các phase sau xây trên nền hỏng.

### 0.4 Báo cáo sau mỗi task — đúng bốn phần

```
1. Đã làm gì (3-5 dòng, không phải liệt kê file)
2. Output THẬT của từng lệnh DoD (dán nguyên văn, không tóm tắt)
3. Đã lệch khỏi kế hoạch chỗ nào và vì sao (nếu không lệch: "không lệch")
4. Phát hiện gì cần ghi Backlog hoặc cần người quyết
```

---

## 1. Vì sao có file này

Kế hoạch dài 2400 dòng không dùng làm hàng đợi công việc được: agent nạp hết vào context sẽ loãng và bỏ sót. Ngược lại, một danh sách task trần trụi không giải thích được *vì sao chọn kiến trúc này*, nên agent sẽ tự ý "đơn giản hoá" khi gặp khó — và chỗ nó đơn giản hoá gần như luôn là §7 (stream resume) hoặc §8 (cây message), tức là đúng hai chỗ đắt nhất để sửa lại.

Hai file, hai vai trò. **Đừng gộp, đừng chép nội dung của file kia sang.**

---

## 2. Tiến độ tổng quan

| Phase | Tên | Số task | Ước lượng | Trạng thái |
|---|---|---|---|---|
| **P0** | Nền móng | 12 | 22.5 h | ☐ |
| **P1** ⭐ | Chat lõi + resume | 14 | 39 h | ☐ |
| **P2** | Auth, quota, admin | 19 | 41 h | ☐ |
| **P3** | Giao diện | 12 | 34 h | ☐ |
| **P4** | Ảnh & vision | 7 | 15 h | ☐ |
| **P5** | Artifacts | 9 | 26 h | ☐ |
| **P6** | Web tools | 8 | 20 h | ☐ |
| **P7** | Skills & sandbox | 9 | 30 h | ☐ |
| **P8** | Share, voice, export, PWA | 8 | 20 h | ☐ |
| **P9** | Hoàn thiện | 7 | 16 h | ☐ |
| | **Tổng** | **105** | **263.5 h** | |

> ⚠️ **Chênh lệch với KE-HOACH §24.2 là có chủ ý.** Kế hoạch ước 180–250 h khi nhìn từ trên xuống. Sau khi bẻ nhỏ thành 104 task, con số thật là ~262 h. Đây là hiện tượng bình thường: ước lượng từ trên xuống luôn lạc quan. **Dùng con số trong bảng này, không dùng con số trong kế hoạch.** Ghi vào Nhật ký quyết định NQ-01.

### Mốc quan trọng

| Mốc | Sau task | Nghĩa là |
|---|---|---|
| **M1 — Đường mạng đã thông** | T-0.6 | Xác nhận Docker gọi được 9Router. Nếu hỏng thì cả ADR-03 phải viết lại — biết ngay từ giờ thứ 8 thay vì giờ thứ 80 |
| **M2 — Streaming không chết** | T-0.8 | `curl -N` thấy chữ chảy từng cái qua Nginx |
| **M3 — Bạn tự dùng được** ⭐ | T-1.14 | Chat được, F5 không mất chữ. Từ đây trở đi bạn dùng thật hằng ngày |
| **M4 — Mời người khác được** | T-2.19 | Auth + quota + duyệt đầy đủ. **Trước mốc này không đưa link cho ai** |
| **M5 — Dùng như sản phẩm** | T-3.12 | Giao diện xong |
| **M6 — Đủ tính năng** | T-8.8 | Toàn bộ phạm vi v1 |

---

## 3. Việc của NGƯỜI (T-H)

Agent không làm được những việc này. Mỗi việc ghi rõ **chặn task nào** — nếu bạn chưa làm, agent sẽ tắc ở đó.

| ID | Việc | Chặn | Ước lượng |
|---|---|---|---|
| **T-H1** | Cài `mkcert`, chạy `mkcert -install` và `mkcert localhost "*.localhost" 127.0.0.1`, đặt file vào `certs/` | T-0.8 | 15 ph |
| **T-H2** | Chạy 9Router trên Windows host. Xác nhận từ WSL: `curl http://<host-ip>:20128/v1/models` ra JSON. Cho agent biết: có cần API key không, tên model nào đang có | T-0.6 🔒 | 20 ph |
| **T-H3** | Lấy API key DeepSeek + Anthropic, điền vào `.env` | T-0.6 | 15 ph |
| **T-H4** | Đặt `.wslconfig` (`memory=8GB`, `swap=2GB`) và **clone repo vào `~/` của WSL**, không phải `/mnt/c/` | T-0.1 | 10 ph |
| **T-H5** | Tạo tài khoản Cloudflare Turnstile, lấy site key + secret | T-2.6 | 15 ph |
| **T-H6** | Chốt hạn mức USD cho tier `free` và `trusted` (mặc định đề xuất: 0.50 / 3.00 và 2.00 / 12.00) | T-2.10 | 10 ph |
| **T-H7** | Lấy Tavily API key | T-6.1 | 10 ph |
| **T-H8** ⚠️ | **SMTP thật** (Resend/Brevo/SendGrid). Cho tới khi có, `REGISTRATION_MODE=invite` và bạn verify tay | T-9.2, và **chặn việc mời người thật** | 30 ph |
| **T-H9** | Chọn skill nào đưa vào P7 (mặc định: `docx`, `xlsx`, `pptx`, `pdf` của Anthropic) | T-7.1 | 15 ph |
| **T-H10** | Mua/trỏ tên miền, cấu hình DNS cho `<domain>` **và** `artifacts.<domain>` | T-9.4 | 30 ph |
| **T-H11** | **Diễn tập khôi phục backup**: xoá volume, khôi phục từ dump, xác nhận đăng nhập được và hội thoại cũ nguyên vẹn | DoD của P9 | 1 h |
| **T-H12** | Duyệt user thật đầu tiên qua admin panel, quan sát trải nghiệm của họ | Sau M4 | 30 ph |

### T-H-DESIGN — Việc thiết kế giao diện bằng Claude Design ⭐

Bạn đã yêu cầu ghi rõ Claude Design vào bước nào. Đây là bảy bước, xen kẽ với task của agent:

| ID | Bước | Làm khi | Đầu ra bạn giao cho agent | Chặn |
|---|---|---|---|---|
| **T-HD1** | **Hệ thống thiết kế**: bảng màu xoay quanh Scarlet cho cả sáng và tối, thang chữ, radius, spacing, shadow | Sau T-3.1 | File `theme.css` với đầy đủ CSS variable, đã kiểm tương phản | T-3.2 |
| **T-HD2** | **Khung chính**: sidebar (mở/đóng), header, vùng chat, panel phải | Sau T-HD1 | Ảnh/mã 3 trạng thái: sidebar mở · sidebar đóng · mobile | T-3.3 |
| **T-HD3** | **Bong bóng tin nhắn + code block**: trạng thái đang gõ, đang stream, xong, lỗi; code block có nút Copy | Sau T-HD2 | Mã component | T-3.5 |
| **T-HD4** | **Model Picker**: hiện provider, badge capability, trạng thái xám khi không khả dụng | Sau T-HD2 | Mã component | T-3.6 |
| **T-HD5** | **Hoạt ảnh**: nút bấm, hover icon, mở/đóng sidebar, chữ xuất hiện khi stream | Sau T-HD3 | Bảng token thời lượng + easing, đặt trong `theme.css` | T-3.9 |
| **T-HD6** | **Panel artifact**: khung, tab phiên bản, nút tải, chế độ toàn màn hình trên mobile | Sau T-5.4 | Mã component | T-5.5 |
| **T-HD7** | **Admin panel**: bảng user, biểu đồ chi phí | Sau T-2.19 | Có thể để đơn giản, ưu tiên thấp | T-3.12 |

> **Quy tắc phân vai:** Claude Design ra **hình dạng và mã component**. Agent nối chúng vào state, API và test. Agent **không được tự đổi màu, spacing, hay bố cục** do bạn đã chốt — nếu thấy sai, báo lại chứ không sửa (§8 của HUONG-DAN-AGENT.md).

---

## 4. Phase 0 — Nền móng

**Mục tiêu:** `docker compose up` chạy, HTTPS local hoạt động, và **xác minh sớm hai thứ có thể làm hỏng cả kiến trúc**: đường mạng tới 9Router (M1) và streaming qua Nginx (M2).

**DoD của phase:** KE-HOACH §24.3, dòng P0.

---

### T-0.1 — Khởi tạo repo và cấu trúc thư mục
- **Trạng thái:** ✅ · **Phụ thuộc:** T-H4 · **Ước lượng:** 1h
- **KH:** §23
- **Việc:**
  - [x] Tạo cây thư mục đúng §23 (kể cả thư mục rỗng, đặt `.gitkeep`)
  - [x] `.gitattributes`: `*.sh text eol=lf`, `*.py text eol=lf` (C39)
  - [x] `.gitignore`: `.env`, `certs/`, `.venv/`, `node_modules/`, `__pycache__/`, `evals/results/`
  - [x] `README.md` ngắn: cách chạy, trỏ tới `docs/`
  - [x] Chép `META-LAP-KE-HOACH.md`, `KE-HOACH.md`, `tasks.md`, `HUONG-DAN-AGENT.md` vào `docs/`
- **Xong khi (DoD):**
  - [x] `pwd` bắt đầu bằng `/home/`, **không** phải `/mnt/c/` (C35)
  - [x] `git status` sạch sau khi tạo file `.env` thử → `.env` **không** xuất hiện
  - [x] `find . -type d -empty -not -path './.git/*'` trả về rỗng
- **Cạm bẫy:** C35 — repo ở `/mnt/c/` khiến mọi thứ sau này chậm 10–20× và bạn sẽ đổ lỗi nhầm cho Docker.

---

### T-0.2 — Backend skeleton + `.venv`
- **Trạng thái:** ✅ · **Phụ thuộc:** T-0.1 · **Ước lượng:** 2h
- **KH:** §23, `CLAUDE.md`
- **Việc:**
  - [x] `backend/pyproject.toml`: fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings, redis, arq, openai, argon2-cffi, python-magic, pillow, httpx, jinja2; group dev: pytest, pytest-asyncio, ruff, mypy
  - [x] `python -m venv .venv` **trong WSL**, `pip install -e ".[dev]"`
  - [x] `app/main.py`: FastAPI app, `GET /health` trả `{"status":"ok"}`
  - [x] `app/api/v1/__init__.py` với router tiền tố `/api/v1`
  - [x] `backend/Dockerfile` multi-stage, non-root user
- **Xong khi (DoD):**
  - [x] `cd backend && source .venv/bin/activate && python -c "import fastapi, arq, openai; print('ok')"` → in `ok`
  - [x] `uvicorn app.main:app` rồi `curl -s localhost:8000/health` → `{"status":"ok"}`
  - [x] `which python` trỏ vào `backend/.venv/bin/python`
  - [x] `docker build -t scarlet-api backend/` thành công
- **Cạm bẫy:** cài package vào Python hệ thống thay vì `.venv` — kiểm bằng `which python` chứ không tin cảm giác.

---

### T-0.3 — Settings fail-fast ⭐
- **Trạng thái:** ✅ · **Phụ thuộc:** T-0.2 · **Ước lượng:** 2h
- **KH:** §19.2 (L2), §19.3 · **Tiêu chí:** S1
- **Việc:**
  - [x] `app/config/settings.py`: lớp `Settings(BaseSettings)` đầy đủ biến ở Phụ lục B
  - [x] Biến bắt buộc **không có giá trị mặc định**; biến tuỳ chọn có default và có mặt trong `.env.example`
  - [x] Validator: `JWT_SECRET` và `MASTER_ENCRYPTION_KEY` ≥ 32 ký tự
  - [x] Cảnh báo lúc boot nếu `TURNSTILE_SECRET` rỗng
  - [x] `.env.example` chép nguyên Phụ lục B, có chú thích từng nhóm
  - [x] Đây là **nơi duy nhất** trong backend đọc `os.environ`
- **Xong khi (DoD):**
  - [x] `unset JWT_SECRET && python -c "from app.config.settings import settings"` → **raise**, thông điệp chứa đúng chuỗi `JWT_SECRET`
  - [x] `JWT_SECRET=short python -c "..."` → raise với thông điệp về độ dài
  - [x] `grep -rn "os.environ\|os.getenv" backend/app/ --include=*.py | grep -v "app/config/"` → **rỗng**
  - [x] Mọi biến trong `.env.example` đều xuất hiện trong `Settings`, và ngược lại (viết `tests/test_settings_complete.py` so hai tập hợp) — 61/61, lệch 0 cả hai chiều
- **Cạm bẫy:** cám dỗ đặt `os.getenv("X", "gia-tri-mac-dinh")` cho secret. Một default ngầm nghĩa là app chạy được với cấu hình sai và bạn phát hiện ở production.

---

### T-0.4 — Compose: postgres, redis, minio
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.1 · **Ước lượng:** 2h
- **KH:** §22.1, §22.2, Phụ lục C
- **Việc:**
  - [ ] `docker-compose.yml` với ba service + healthcheck đúng Phụ lục C
  - [ ] Redis: `--appendonly yes --maxmemory 512mb --maxmemory-policy volatile-lru` (C8)
  - [ ] Hai network: `internal` và `egress`
  - [ ] Volume có tên: `pgdata`, `redisdata`, `miniodata`
  - [ ] `docker-compose.override.yml` cho dev: mount code, mailpit, adminer
- **Xong khi (DoD):**
  - [ ] `docker compose --profile core up -d` → `docker compose ps` cho thấy cả ba `healthy`
  - [ ] `docker compose exec redis redis-cli config get appendonly` → `yes`
  - [ ] `docker compose down && docker compose up -d` → dữ liệu Postgres còn nguyên (volume gắn đúng)
  - [ ] `docker compose exec postgres psql -U scarlet -c "select 1"` chạy được
- **Cạm bẫy:** healthcheck của MinIO dùng `mc ready local` — dùng `curl` vào `/minio/health/live` cũng được, nhưng phải có healthcheck thật, không để `depends_on` trần (service "up" không có nghĩa là "sẵn sàng nhận kết nối").

---

### T-0.5 — Alembic + migration đầu tiên
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.4, T-0.3 · **Ước lượng:** 3h
- **KH:** §17, Phụ lục A, §22.2
- **Việc:**
  - [ ] `alembic init`, cấu hình async engine, đọc URL từ `settings`
  - [ ] `alembic/versions/0001_initial.py` chép đúng DDL Phụ lục A
  - [ ] Service `migrate` trong compose: chạy `alembic upgrade head` rồi thoát, `restart: "no"`
  - [ ] `api` và `worker` `depends_on: migrate: service_completed_successfully`
  - [ ] Seed hai tier `free`/`trusted`
- **Xong khi (DoD):**
  - [ ] `docker compose run --rm migrate` → exit 0
  - [ ] `psql -c "\dt"` liệt kê đủ 15 bảng ở §17.1
  - [ ] `psql -c "\d messages"` cho thấy `parent_id` **nullable** và có FK tự trỏ
  - [ ] `psql -c "\di"` có `ix_msg_streaming` là **partial index** (`WHERE status='streaming'`)
  - [ ] `alembic downgrade base && alembic upgrade head` chạy sạch hai chiều
- **Cạm bẫy:** `conversations.active_leaf_id` tham chiếu `messages`, mà `messages` tham chiếu `conversations` — vòng tròn. Phải tạo bảng trước, `ALTER TABLE ADD CONSTRAINT` sau, đúng thứ tự trong Phụ lục A.

---

### T-0.6 — LiteLLM + đường mạng tới 9Router 🔒⭐ **KHÔNG ĐƯỢC GỘP**
- **Trạng thái:** ☐ · **Phụ thuộc:** T-H2, T-H3, T-0.4 · **Ước lượng:** 2h
- **KH:** ADR-03, §9.5, C17, Phụ lục E · **Mốc:** M1
- **Rủi ro:** cao — nếu hướng này không chạy, ADR-03 phải viết lại và cả tầng provider đổi theo. **Đây là lý do task này đứng ở giờ thứ 8 chứ không phải giờ thứ 80.**
- **Việc:**
  - [ ] `config/litellm.config.yaml` theo Phụ lục E
  - [ ] Service `litellm` trong compose với `extra_hosts: ["host.docker.internal:host-gateway"]`
  - [ ] Ba entry model: DeepSeek, Anthropic, 9Router
  - [ ] `drop_params: true`, `num_retries: 2`, `request_timeout: 600`
- **Xong khi (DoD):**
  - [ ] `docker compose exec litellm curl -s http://host.docker.internal:20128/v1/models` → JSON có mảng model (**đây là M1**)
  - [ ] `curl -s http://localhost:4000/v1/models -H "Authorization: Bearer $LITELLM_MASTER_KEY"` → liệt kê cả ba
  - [ ] Gọi thử **từng** model một lượt non-streaming, cả ba trả về text
  - [ ] Gọi thử **streaming** DeepSeek qua LiteLLM bằng `curl -N` → chunk chảy ra từng cái
  - [ ] Tắt 9Router trên Windows → gọi model của nó trả lỗi **có mã**, và hai model kia **vẫn chạy**
- **Cạm bẫy:**
  - C17 — `localhost` trong container là chính container. Trên Docker Desktop/WSL2 phải `host.docker.internal` + `extra_hosts`. Nếu vẫn không được, kiểm tường lửa Windows có chặn cổng 20128 với WSL không.
  - 9Router có thể **fallback sang model khác** với model đã yêu cầu (§9.5). Trong task này chỉ cần ghi nhận hiện tượng vào báo cáo, chưa xử lý — xử lý ở T-2.12.

---

### T-0.7 — Model catalog + `GET /models` tối thiểu
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.6 · **Ước lượng:** 2h
- **KH:** §9.2, §9.3, ADR-12
- **Việc:**
  - [ ] `config/model_catalog.json` đúng schema §9.2, có 3 model thật đã kiểm ở T-0.6
  - [ ] `app/config/catalog.py`: nạp, validate bằng pydantic, cache trong bộ nhớ, hàm `reload()`
  - [ ] Validate: `provider` phải tồn tại trong `providers`; đúng **một** model có `default: true`; `pricing` bắt buộc khi `pricing_mode='metered'`
  - [ ] `GET /api/v1/models` trả danh sách đã lọc, **không** kèm `base_url` và `pricing`
- **Xong khi (DoD):**
  - [ ] `curl -s localhost:8000/api/v1/models | jq '.[0]'` có `id`, `display_name`, `capabilities`, **không** có `base_url` hay `pricing`
  - [ ] Sửa `display_name` trong file → `POST /api/v1/admin/catalog/reload` → `GET /models` phản ánh ngay, **không** restart container
  - [ ] Đặt `provider: "khong-ton-tai"` → app **không** boot, log in đúng tên model sai
  - [ ] Đặt hai model cùng `default: true` → validate raise
  - [ ] `base_url` có dấu `/` ở cuối → loader tự chuẩn hoá, không sinh URL `//v1//chat` (C43)
  - [ ] Provider thiếu `auth_style` → mặc định `bearer`; thiếu `verify_path` → BYOK lưu key mà không kiểm, có cảnh báo (C42, C44)
- **Cạm bẫy:** cám dỗ để `GET /models` đọc file mỗi lần gọi. Cache và reload tường minh — nếu không, mỗi lần mở Model Picker là một lần đọc đĩa.

---

### T-0.8 — Nginx + HTTPS + SSE 🔒⭐ **KHÔNG ĐƯỢC GỘP**
- **Trạng thái:** ☐ · **Phụ thuộc:** T-H1, T-0.2 · **Ước lượng:** 3h
- **KH:** §22.3, §22.4, Phụ lục D, C1, C2 · **Mốc:** M2
- **Rủi ro:** cao — nếu SSE bị buffer mà không phát hiện bây giờ, cả P1 sẽ được xây và test trên một đường ống bị hỏng, rồi bug lộ ra khi đã viết xong 40 giờ code.
- **Việc:**
  - [ ] `config/nginx/nginx.conf` theo Phụ lục D
  - [ ] Server block chính (`localhost`) + server block phụ (`artifacts.localhost`) với CSP
  - [ ] Location SSE: `proxy_buffering off`, `proxy_read_timeout 3600s`, `proxy_http_version 1.1`, `Connection ''`
  - [ ] `GET /api/v1/_debug/sse`: phát một dòng mỗi 200 ms trong 10 s, kèm header `X-Accel-Buffering: no`, chỉ bật khi `DEBUG=true`
  - [ ] `client_max_body_size 25m`
- **Xong khi (DoD):**
  - [ ] `curl -kN https://localhost/api/v1/_debug/sse` → **chữ ra từng dòng cách nhau ~200 ms**, KHÔNG phải một cục sau 10 giây (**đây là M2**)
  - [ ] `curl -kI https://localhost/` → `HTTP/2 200`, chứng chỉ hợp lệ (không cảnh báo trên trình duyệt sau khi `mkcert -install`)
  - [ ] `curl -kI https://artifacts.localhost/` → header `Content-Security-Policy` chứa `connect-src 'none'`
  - [ ] Endpoint giữ kết nối > 70 giây không bị cắt (test bằng biến thể `_debug/sse?seconds=90`)
  - [ ] `DEBUG=false` → `/_debug/sse` trả 404
- **Cạm bẫy:**
  - C1 — thiếu `proxy_buffering off` là lỗi hay gặp nhất khi đặt Nginx trước FastAPI. Triệu chứng dễ nhầm với "model chậm".
  - C2 — `proxy_read_timeout` mặc định 60 s sẽ cắt ngang câu trả lời dài. Phát hiện muộn vì test thường ngắn hơn 60 s.

---

### T-0.9 — Makefile, lint, pre-commit, check-hardcode
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.2 · **Ước lượng:** 1.5h
- **KH:** §19.4, §0
- **Việc:**
  - [ ] `Makefile`: `up`, `down`, `test`, `lint`, `fmt`, `migrate`, `check-hardcode`, `eval`, `logs`
  - [ ] `scripts/check_hardcode.sh` chép đúng bốn lệnh grep ở §19.4
  - [ ] `ruff` + `mypy` cấu hình trong `pyproject.toml`
  - [ ] `.pre-commit-config.yaml`: ruff, check-hardcode, chặn commit `.env`
- **Xong khi (DoD):**
  - [ ] `make check-hardcode` → exit 0 trên repo sạch
  - [ ] Thêm tạm `MODEL = "claude-sonnet-4-5"` vào `app/llm/client.py` → `make check-hardcode` **exit ≠ 0** và in đúng số dòng
  - [ ] Thêm tạm `import openai` vào `app/api/v1/health.py` → exit ≠ 0
  - [ ] `git commit` với file `.env` trong staging → pre-commit **chặn**
- **Cạm bẫy:** grep phải loại trừ `tests/` và `app/config/`, nếu không nó sẽ báo động giả mỗi lần và bạn sẽ tắt nó đi — một lệnh kiểm tra bị tắt còn tệ hơn không có.

---

### T-0.10 — Frontend skeleton + theme tokens
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.1 · **Ước lượng:** 2h
- **KH:** §23, ADR-16, §19.1
- **Việc:**
  - [ ] `pnpm create vite` React + TS; Tailwind v4
  - [ ] `src/styles/theme.css` với CSS variable cho màu/spacing/radius; **giá trị tạm**, T-HD1 sẽ thay
  - [ ] Chuyển sáng/tối bằng `data-theme` trên `<html>`, đọc `prefers-color-scheme` làm mặc định
  - [ ] `src/lib/api.ts`: wrapper fetch, base URL từ biến môi trường Vite
  - [ ] `src/locales/vi.json` + hàm `t()` tối thiểu
  - [ ] Service `web` trong compose, Nginx proxy `/` sang đó
- **Xong khi (DoD):**
  - [ ] `https://localhost/` hiện trang có chữ, không lỗi console
  - [ ] Đổi `--color-accent` trong `theme.css` → màu đổi sau khi lưu, **không** rebuild
  - [ ] Chuyển sáng/tối đổi nền và chữ, không có chỗ nào chữ trùng màu nền
  - [ ] `grep -rE "#[0-9a-fA-F]{6}" frontend/src/components/` → rỗng (§19.4)
- **Cạm bẫy:** Tailwind v4 bỏ `tailwind.config.js` cho phần theme, dùng `@theme` trong CSS. Làm theo tài liệu v4, đừng chép cấu hình v3.

---

### T-0.11 — `/health/deep`
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.6, T-0.5 · **Ước lượng:** 1h
- **KH:** §18.6, §21.2
- **Việc:**
  - [ ] Kiểm song song: Postgres (`SELECT 1`), Redis (`PING`), MinIO (list bucket), LiteLLM (`/health/liveliness`), 9Router (`/v1/models`)
  - [ ] Mỗi mục trả `{ok, latency_ms, error?}`; timeout riêng 2 s mỗi mục
  - [ ] 9Router hỏng → tổng thể `degraded`, **không** phải `down`
- **Xong khi (DoD):**
  - [ ] `curl -sk https://localhost/api/v1/health/deep | jq` → 5 mục, tất cả `ok: true`
  - [ ] `docker compose stop redis` → mục redis `ok: false`, HTTP status `503`, các mục khác vẫn báo cáo
  - [ ] Tắt 9Router → tổng thể `"status": "degraded"`, HTTP `200`
  - [ ] Tổng thời gian phản hồi < 3 s ngay cả khi một phụ thuộc treo
- **Cạm bẫy:** kiểm tuần tự sẽ khiến endpoint treo 10 s khi một service chết. Dùng `asyncio.gather` với timeout riêng từng mục.

### T-0.12 — Diễn tập thêm provider thứ tư ⭐
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.7 · **Ước lượng:** 1.5h
- **KH:** R22, §9.8, §9.9, §9.10 · **Tiêu chí:** S15
- **Việc:**
  - [ ] Chọn **một provider chưa có trong kế hoạch** làm bài kiểm tra. Rẻ nhất: dựng `ollama` hoặc `vllm` local với một model nhỏ; hoặc một tài khoản free tier (Groq, Mistral, OpenRouter) — miễn là **không** phải 9Router/DeepSeek/Anthropic
  - [ ] Đi đúng 6 bước §9.9, **bấm giờ**
  - [ ] Loader chuẩn hoá `base_url`: bỏ `/` cuối, yêu cầu đã bao gồm `/v1`, validate lúc boot (C43)
  - [ ] Hỗ trợ `auth_style` và `verify_path` trong schema catalog (C42, C44)
  - [ ] Viết `docs/RUNBOOK-them-provider.md`: 6 bước + 6 cạm bẫy §9.10, dạng checklist copy-paste
- **Xong khi (DoD):**
  - [ ] Provider thứ tư chat được, **thời gian thực tế ≤ 15 phút** (ghi con số vào báo cáo) — **S15**
  - [ ] `git diff --stat` của cả task này: **không có file `.py` hay `.tsx` nào** ngoài phần loader ở trên. Chỉ `config/*` và `.env.example`
  - [ ] Model mới vào catalog với `enabled: false`, chỉ bật sau khi gọi thử thành công
  - [ ] `SELECT prompt_tokens, completion_tokens FROM usage_events ORDER BY created_at DESC LIMIT 1` → **cả hai > 0** (C40) *(nếu T-2.12 chưa xong: kiểm bằng log worker)*
  - [ ] `base_url` có `/` cuối → vẫn chạy (C43)
  - [ ] Gỡ provider thứ tư khỏi catalog → app boot bình thường, 3 provider kia không ảnh hưởng
- **Cạm bẫy:**
  - Đây là **task diễn tập**, không phải task tính năng. Nếu mất 2 tiếng thay vì 15 phút, kết quả hữu ích là biết **chỗ nào đang cứng** và sửa ngay bây giờ — rẻ hơn nhiều so với phát hiện ở P6 khi đã có 40 chỗ phụ thuộc vào tầng provider.
  - Cám dỗ chọn một provider "gần giống DeepSeek" cho dễ. Chọn cái khác biệt nhất bạn tiếp cận được — bài kiểm tra dễ thì không kiểm tra gì cả.

---

## 5. Phase 1 — Chat lõi + resume ⭐

**Đây là phase quyết định cả dự án.** Mọi phase sau xây trên nó. KE-HOACH §3 giải thích vì sao nó đứng trước cả auth và giao diện.

**Luật riêng của phase này:** không task nào được gộp với task khác. Bốn task đánh 🔒 là bắt buộc; nhưng ngay cả các task còn lại cũng nên một commit một task, vì khi bug lộ ra ở T-1.11 bạn cần `git bisect` chạy được.

---

### T-1.1 — DB models + repository cho cây hội thoại
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.5 · **Ước lượng:** 3h
- **KH:** §8.2, §17.1, §17.2
- **Việc:**
  - [ ] `app/db/models/`: `Conversation`, `Message` khớp DDL (SQLAlchemy 2.0 style)
  - [ ] `app/db/repositories/conversations.py`, `messages.py`
  - [ ] Mọi hàm repo nhận `user_id` và **lọc trong câu SQL**, không lọc sau khi lấy về (§20)
  - [ ] Soft delete: mọi truy vấn mặc định `deleted_at IS NULL` (C12)
- **Xong khi (DoD):**
  - [ ] `pytest tests/db/test_repositories.py` xanh, ≥ 12 case
  - [ ] `repo.get_conversation(conv_id_cua_B, user_id=A)` → trả `None` (không phải raise, không phải trả về object)
  - [ ] Xoá mềm một message → truy vấn mặc định không thấy nó, nhưng con của nó **vẫn còn trong DB**
  - [ ] Chèn message với `parent_id` thuộc conversation khác → raise (kiểm tra ở tầng repo)
- **Cạm bẫy:** C12 — đừng đặt `ON DELETE CASCADE` trên `parent_id`. Xoá một message ở giữa sẽ xoá cả nhánh phía dưới.

---

### T-1.2 — Truy vấn đường đi + đếm anh em ⭐
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.1 · **Ước lượng:** 3h
- **KH:** §8.3, C11, C13
- **Việc:**
  - [ ] `get_path(leaf_id)` bằng recursive CTE đúng §8.3
  - [ ] `get_siblings(conversation_id, parent_id)` dùng `IS NOT DISTINCT FROM` (bắt buộc, xem §8.3)
  - [ ] Trả kèm `sibling_index` và `sibling_count` cho **mỗi** message trong đường đi
  - [ ] Lọc `deleted_at IS NULL` trong CTE
- **Xong khi (DoD):**
  - [ ] `pytest tests/db/test_tree.py` ≥ 15 case xanh
  - [ ] Dựng cây 3 nhánh × 4 tầng; `get_path(leaf_nhánh_2)` trả **đúng 4** message, không có message nào của nhánh 1 hoặc 3
  - [ ] Message gốc (`parent_id IS NULL`) có 3 anh em → `sibling_count == 3` (đây là case mà `parent_id = NULL` sẽ làm sai nếu viết `=` thay vì `IS NOT DISTINCT FROM`)
  - [ ] Cây 500 message: `get_path` chạy < 50 ms (đo bằng `EXPLAIN ANALYZE`)
- **Cạm bẫy:** C11 là bug tốn tiền nhất của cả dự án — nếu dựng context bằng `WHERE conversation_id=... ORDER BY created_at` thì mọi nhánh bị bỏ đều được gửi lên model và bạn trả tiền cho chúng ở **mọi** lượt sau.

---

### T-1.3 — LLM client + SystemAdapter
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.6, T-0.7 · **Ước lượng:** 3h
- **KH:** §9.1, ADR-03, ADR-04, A9
- **Việc:**
  - [ ] `app/llm/client.py`: protocol `LLMClient` đúng §9.1
  - [ ] `app/llm/adapters/system.py`: dùng SDK `openai` async, `base_url` = LiteLLM
  - [ ] `app/llm/parser.py`: chuẩn hoá chunk của OpenAI stream thành `Chunk(kind, text, tool_call, usage)`
  - [ ] Xử lý `reasoning_content` / `reasoning` nếu có → `kind='reasoning'`
  - [ ] **Không** import LangChain (ADR-04)
- **Xong khi (DoD):**
  - [ ] `pytest tests/llm/test_parser.py` xanh với fixture chunk thật đã ghi lại từ cả ba provider
  - [ ] Script thử: stream một câu tiếng Việt có dấu, nối các `delta` → chuỗi cuối **không** có `\ufffd` (C9)
  - [ ] Chunk có `usage` được bắt đúng ở cuối stream
  - [ ] `grep -rn "langchain" backend/` → rỗng
- **Cạm bẫy:** một số provider gửi `usage` trong chunk cuối, một số chỉ gửi khi bật `stream_options: {include_usage: true}`. Bật nó, và có đường lùi ước tính bằng tiktoken nếu vẫn không có.

---

### T-1.4 — Context builder + ngân sách token
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.2, T-1.3 · **Ước lượng:** 3h
- **KH:** §9.6, C15, C11
- **Việc:**
  - [ ] `app/llm/context.py`: `build(leaf_id, model_meta) -> list[dict]`
  - [ ] Đếm token bằng tiktoken (xấp xỉ với model non-OpenAI là chấp nhận được)
  - [ ] Cắt theo thứ tự §9.6; **cặp `tool_call`+`tool_result` là đơn vị nguyên tử**
  - [ ] System prompt từ `config/prompts/system.jinja`, cache 60 s
- **Xong khi (DoD):**
  - [ ] `pytest tests/llm/test_context.py` ≥ 10 case xanh
  - [ ] Cây 3 nhánh, build từ nhánh 2 → số message bằng độ dài đường đi, **không** phải tổng số message (C11)
  - [ ] Hội thoại 200 message với `context_window=8000` → kết quả ≤ 8000 − `max_output` − `RESERVE_TOKENS` token
  - [ ] Cắt ở giữa một cặp tool → test khẳng định **không** có `tool_result` nào mồ côi trong output
- **Cạm bẫy:** C15 — cắt lẻ một nửa cặp tool khiến provider trả `400 invalid request`, và thông điệp lỗi của họ thường không nói rõ nguyên nhân.

---

### T-1.5 — Worker arq + job `generate` (khung)
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.4, T-1.3 · **Ước lượng:** 2h
- **KH:** ADR-02, §5.2, §7.2
- **Việc:**
  - [ ] `app/workers/main.py`: `WorkerSettings`, kết nối Redis, đăng ký job
  - [ ] `app/workers/generate.py`: khung nhận `message_id`, chưa stream (T-1.6 làm)
  - [ ] Service `worker` trong compose
  - [ ] Job timeout `GENERATE_TIMEOUT_S`, `max_tries: 1` (**không** retry tự động — retry một generation đã tính tiền là tính tiền lần hai)
- **Xong khi (DoD):**
  - [ ] `docker compose up worker` → log báo đã kết nối Redis và đăng ký job
  - [ ] Enqueue thủ công từ `python -c` → worker log nhận được job trong < 1 s
  - [ ] Kill worker giữa job → job **không** tự chạy lại khi worker lên (kiểm bằng log)
- **Cạm bẫy:** mặc định của arq có retry. Với generation, retry = gọi model lần hai = trả tiền lần hai. Đặt `max_tries: 1` tường minh.

---

### T-1.6 — Stream producer (XADD) 🔒⭐ **KHÔNG ĐƯỢC GỘP**
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.4, T-1.5 · **Ước lượng:** 4h
- **KH:** §7.2, §7.4, ADR-01, C19, C8
- **Rủi ro:** cao — đây là một nửa của cơ chế resume.
- **Việc:**
  - [ ] `app/streaming/events.py`: dataclass cho 9 loại event ở §7.4
  - [ ] `app/streaming/producer.py`: `XADD stream:{message_id}` cho từng event, payload luôn `json.dumps` (C10)
  - [ ] `generate.py`: vòng lặp stream → XADD `delta`; ghi `heartbeat_at` mỗi `WORKER_HEARTBEAT_S`
  - [ ] `try/finally`: **mọi** đường thoát đều XADD `done` hoặc `error` (C19)
  - [ ] Khi xong: `UPDATE messages` content/status/usage, rồi `EXPIRE stream:{id} STREAM_TTL_S` (C8)
- **Xong khi (DoD):**
  - [ ] Chạy một generation, `redis-cli XLEN stream:{id}` > 10
  - [ ] `redis-cli XRANGE stream:{id} - +` → bản ghi cuối cùng có `type=done`
  - [ ] Ngắt mạng tới LiteLLM giữa chừng → bản ghi cuối là `type=error` **có mã lỗi**, không phải im lặng
  - [ ] Sau `done`: `redis-cli TTL stream:{id}` trả số dương (không phải `-1`)
  - [ ] Nối toàn bộ `delta` == `messages.content` trong Postgres, **so byte-by-byte**
  - [ ] Nội dung có emoji và xuống dòng → `XRANGE` parse lại được bằng `json.loads` (C10)
- **Cạm bẫy:**
  - C19 — thiếu `finally` khiến client treo vô hạn khi upstream đứt bất thường.
  - C8 — quên `EXPIRE` thì Redis đầy dần trong vài tuần và bạn sẽ không nghĩ tới nguyên nhân này.

---

### T-1.7 — Stream consumer (SSE) 🔒⭐ **KHÔNG ĐƯỢC GỘP**
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.6 · **Ước lượng:** 4h
- **KH:** §7.3, §7.4, C3, C4, C7
- **Rủi ro:** cao — nửa còn lại của resume. **§7.3 giải thích thứ tự XRANGE → XREAD; đọc kỹ trước khi viết.**
- **Việc:**
  - [ ] `GET /api/v1/messages/{id}/stream`: kiểm quyền sở hữu (trả 404 nếu không phải của mình)
  - [ ] `cursor` = `Last-Event-ID` header, hoặc `?cursor=`, mặc định `0`
  - [ ] **`XRANGE (cursor, +]` để đuổi kịp** (dấu `(` — loại trừ, không phải `[`)
  - [ ] **Rồi `XREAD BLOCK` từ ID cuối cùng vừa gửi**, không phải từ `$`
  - [ ] **Không** dùng consumer group (C7)
  - [ ] Mỗi event SSE có `id:` = Redis Stream ID
  - [ ] Heartbeat `: ping` mỗi `STREAM_HEARTBEAT_S` khi BLOCK hết hạn
  - [ ] Header `X-Accel-Buffering: no`
  - [ ] Stream đã hết TTL nhưng message `completed` → trả content đầy đủ từ Postgres rồi `done`
- **Xong khi (DoD):**
  - [ ] `curl -kN https://localhost/api/v1/messages/{id}/stream` → event chảy ra từng cái
  - [ ] Ngắt curl ở giữa, chạy lại với `-H "Last-Event-ID: <id-cuối>"` → nhận **tiếp** từ đó, không lặp bản ghi nào (C3)
  - [ ] Chạy lại với `cursor=0` → nhận **lại từ đầu**, đủ số bản ghi bằng `XLEN`
  - [ ] **Hai** `curl -N` song song cùng một message → **cả hai** nhận đủ mọi event (C7)
  - [ ] Message của user khác → `404`
  - [ ] Message `completed` từ 2 giờ trước (stream đã hết TTL) → vẫn trả content đầy đủ + `done`
  - [ ] Không có event mới trong 20 s → thấy dòng `: ping`, kết nối chưa đứt
- **Cạm bẫy:**
  - C4 — `XREAD` từ `$` là lỗi tinh vi nhất: chạy đúng khi test liên tục, chỉ sai khi có độ trễ giữa XRANGE và XREAD, tức là chỉ sai trên máy thật dưới tải.
  - C7 — consumer group giao mỗi bản ghi cho **một** consumer; mở hai tab thì một tab đói.

---

### T-1.8 — `POST /conversations/{id}/messages`
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.6, T-1.2 · **Ước lượng:** 2h
- **KH:** §7.2 bước ①, §18.2, A1
- **Việc:**
  - [ ] Tạo message user + message assistant `status='queued'` trong **một** transaction
  - [ ] Cập nhật `conversations.active_leaf_id`
  - [ ] Enqueue arq, trả **202** với `{user_message_id, assistant_message_id, stream_url}`
  - [ ] Nhận `parent_id` client đang thấy; khác `active_leaf_id` → vẫn nhận, trả cờ `branched: true` (C14)
  - [ ] `Idempotency-Key` đọc nhưng chưa xử lý (T-2.8 làm) — chỉ log
- **Xong khi (DoD):**
  - [ ] Endpoint trả về trong **< 200 ms** (đo bằng `curl -w "%{time_total}"`), tức là **không** đợi model
  - [ ] `grep -rnE "litellm|openai|AsyncOpenAI" backend/app/api/` → **rỗng** (§5.3, A1)
  - [ ] Gửi với `parent_id` cũ → response có `branched: true`, và cây có thêm nhánh
  - [ ] Lỗi giữa transaction → **không** có message mồ côi trong DB (test bằng cách ép enqueue thất bại)
- **Cạm bẫy:** cám dỗ "gọi model luôn cho nhanh, sau tách ra". Đó chính là kiến trúc §3.1 đã bác bỏ, và tách ra sau tốn 3–4×.

---

### T-1.9 — Huỷ generation
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.6 · **Ước lượng:** 2h
- **KH:** §7.5
- **Việc:**
  - [ ] `POST /messages/{id}/cancel` → `SET cancel:{id} 1 EX 300`
  - [ ] Worker kiểm `EXISTS` mỗi 8 chunk
  - [ ] Dừng → `finish_reason='cancelled'`, **vẫn lưu phần đã sinh**, **vẫn ghi usage** (§7.5)
  - [ ] XADD `done` với `finish_reason='cancelled'`
- **Xong khi (DoD):**
  - [ ] Bắt đầu stream dài, gọi cancel → chữ ngừng trong **≤ 500 ms** (đo bằng dấu thời gian của bản ghi cuối trong stream)
  - [ ] `messages.content` chứa **đúng** phần đã sinh, không rỗng, không đầy đủ
  - [ ] `usage_events` có **1** dòng cho message bị huỷ (khi T-2.12 xong; ở phase này kiểm bằng log)
  - [ ] Cancel một message đã `completed` → `200`, không có tác dụng phụ (idempotent)
- **Cạm bẫy:** không ghi usage cho phần đã huỷ = quota bị rò. Provider vẫn tính tiền phần họ đã sinh.

---

### T-1.10 — Reaper + heartbeat
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.6 · **Ước lượng:** 2h
- **KH:** §7.6 · **Tiêu chí:** S4
- **Việc:**
  - [ ] Cron arq mỗi 30 s, câu UPDATE đúng §7.6
  - [ ] Với mỗi message bị dọn: XADD `error` với `code=WORKER_LOST`
  - [ ] Dùng partial index `ix_msg_streaming`
- **Xong khi (DoD):**
  - [ ] Bắt đầu stream, `docker compose kill worker` → sau ≤ 90 s, `SELECT status FROM messages WHERE id=...` là `failed` (S4)
  - [ ] Client đang mở SSE nhận được event `error` với `code=WORKER_LOST`, **không** treo vô hạn
  - [ ] `EXPLAIN` câu UPDATE của reaper → dùng `ix_msg_streaming`, **không** seq scan
  - [ ] Reaper chạy khi không có message nào `streaming` → 0 dòng bị đổi, không lỗi
- **Cạm bẫy:** nếu quét toàn bảng `messages` mỗi 30 s, sau vài tháng nó thành truy vấn nặng nhất hệ thống. Partial index giải quyết triệt để.

---

### T-1.11 — `scripts/test_resume.py` 🔒⭐ **KHÔNG ĐƯỢC GỘP**
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.7 · **Ước lượng:** 3h
- **KH:** §2.3 (S3), §7.3 · **Tiêu chí:** S3
- **Rủi ro:** cao — **đây là tiêu chí nghiệm thu của toàn bộ P1.** Không có nó thì bug resume chỉ lộ ra khi bạn dùng thật, giữa lúc cần app nhất.
- **Việc:**
  - [ ] Gửi một prompt đủ dài (yêu cầu model viết ≥ 800 từ)
  - [ ] Mở SSE, đọc tới token thứ 50, **ngắt kết nối cứng**
  - [ ] Chờ 2 s, reconnect với `Last-Event-ID` của event cuối đã nhận
  - [ ] Đọc tới hết, nối `A + B`
  - [ ] So với `messages.content` trong Postgres **byte-by-byte**
  - [ ] Lặp lại 5 lần với điểm ngắt ngẫu nhiên; thêm một lần ngắt **hai** lần trong cùng một stream
- **Xong khi (DoD):**
  - [ ] `python scripts/test_resume.py` in `PASS 6/6`
  - [ ] Cố tình sửa consumer thành `XREAD` từ `$` → script in `FAIL` và báo **thiếu** bao nhiêu ký tự (chứng minh test thật sự bắt được lỗi)
  - [ ] Cố tình đổi `(cursor` thành `[cursor` → script in `FAIL` và báo **lặp** (chứng minh bắt được lỗi ngược lại)
  - [ ] Chạy trong CI/Makefile: `make test-resume`
- **Cạm bẫy:** một test luôn xanh là một test vô dụng. Hai DoD ở giữa tồn tại để chứng minh test này **có thể sai** — nếu nó vẫn xanh khi bạn phá code, hãy viết lại nó.

---

### T-1.12 — `scripts/bench_ttft.py`
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.7 · **Ước lượng:** 1.5h
- **KH:** §2.3 (S2), §21.2
- **Việc:**
  - [ ] 30 lượt cho mỗi model, đo từ lúc `POST` tới lúc nhận event `delta` đầu tiên
  - [ ] In p50/p95/max theo từng model
  - [ ] Ghi kết quả vào `evals/results/ttft-{date}.json`
- **Xong khi (DoD):**
  - [ ] `make bench` in bảng có p50 và p95 cho cả ba model
  - [ ] p95 ≤ 2.0 s với model qua 9Router, ≤ 4.0 s với DeepSeek/Anthropic (S2)
  - [ ] Nếu không đạt: báo cáo ghi rõ phần nào chậm (hàng đợi / dựng context / upstream) bằng cách đo từng chặng
- **Cạm bẫy:** đo từ lúc nhận event `start` là **sai** — user cảm nhận độ trễ từ lúc bấm nút. Đo từ trước `POST`.

---

### T-1.13 — Retry và sửa câu hỏi (tạo nhánh)
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.8, T-1.2 · **Ước lượng:** 3h
- **KH:** §8.2, UC-04, §18.2
- **Việc:**
  - [ ] `POST /messages/{id}/retry` → tạo message assistant **anh em** (cùng `parent_id`), cho phép đổi `model_id`
  - [ ] `PATCH /messages/{id}` với message `role='user'` → tạo **anh em**, nhánh cũ giữ nguyên
  - [ ] `PATCH /conversations/{id}` cho phép đổi `active_leaf_id` (chuyển nhánh)
  - [ ] `GET /messages/{id}/siblings`
- **Xong khi (DoD):**
  - [ ] `pytest tests/api/test_branching.py` ≥ 10 case xanh
  - [ ] Retry 2 lần → message gốc có `sibling_count == 3`, cả ba **đều còn** trong DB
  - [ ] Retry bằng model khác → nhánh mới có `model_id` mới, nhánh cũ **không đổi**
  - [ ] Sửa message user ở giữa → nhánh con cũ vẫn truy cập được qua `active_leaf_id` cũ
  - [ ] Chuyển nhánh rồi gửi tin nhắn mới → gắn đúng vào nhánh đang xem
- **Cạm bẫy:** cám dỗ "xoá nhánh cũ cho gọn". Cả điểm của cây là giữ lại — user hay quay về nhánh trước.

---

### T-1.14 — Frontend tối thiểu: `sse.ts` + `tree.ts` + màn chat thô
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.7, T-1.13, T-0.10 · **Ước lượng:** 4h
- **KH:** §7.4, Phụ lục F, §8 · **Mốc:** M3
- **Việc:**
  - [ ] `src/lib/sse.ts`: `EventSource`, xử lý 9 loại event, **không** tự đóng khi `error` (để trình duyệt reconnect)
  - [ ] Lắng `visibilitychange` → reconnect khi tab hiện lại (C6)
  - [ ] `src/lib/tree.ts`: state cây, con trỏ leaf, điều hướng anh em
  - [ ] Màn chat **thô, chưa cần đẹp**: ô nhập, danh sách message, nút Dừng, điều hướng `‹ n/m ›`
  - [ ] Nút gửi → Dừng trong lúc stream
- **Xong khi (DoD):**
  - [ ] Chat được trên trình duyệt, chữ chảy từng chữ
  - [ ] **F5 giữa lúc stream → chữ tiếp tục chảy** (thao tác tay, quay video lại làm bằng chứng) — **đây là M3**
  - [ ] Đóng tab, mở lại sau 30 s → thấy câu trả lời đầy đủ
  - [ ] DevTools → Network → throttle Offline 5 s rồi bật lại → tự reconnect, không mất chữ
  - [ ] Mở 2 tab cùng hội thoại → cả hai cùng chảy
  - [ ] Retry hiện `‹ 2/2 ›`, bấm chuyển đổi nội dung phía dưới
- **Cạm bẫy:**
  - C6 — trên iOS Safari, khoá màn hình làm đứt SSE **im lặng**: `EventSource` không báo lỗi, chỉ ngừng nhận. Phải dựa vào `visibilitychange`, không dựa vào sự kiện `error`.
  - Đừng làm đẹp ở task này. Giao diện là P3 và do bạn thiết kế (T-HD1…T-HD5). Làm đẹp bây giờ = làm hai lần.

---

## 6. Phase 2 — Auth, quota, admin

**Mục tiêu:** đủ an toàn để mời người thật vào (M4). **Trước khi hoàn thành phase này, không đưa link cho ai.**

---

### T-2.1 — Đăng ký + Argon2
- **Trạng thái:** ☐ · **Phụ thuộc:** T-0.5 · **Ước lượng:** 2h
- **KH:** §11.1, §11.6, UC-01
- **Việc:**
  - [ ] `app/core/security.py`: hash/verify Argon2id, tham số từ settings
  - [ ] `POST /auth/register`: tạo user `status='pending_email'`, tier mặc định
  - [ ] Mật khẩu ≥ 12 ký tự, đối chiếu danh sách 10k mật khẩu phổ biến
  - [ ] Email đã tồn tại → phản hồi **giống hệt** trường hợp thành công, không tạo user
- **Xong khi (DoD):**
  - [ ] Đăng ký hai lần cùng email → **hai response giống nhau từng byte**, DB có **một** user
  - [ ] Mật khẩu `password1234` → `422` với lý do "quá phổ biến"
  - [ ] `SELECT password_hash FROM users` bắt đầu bằng `$argon2id$`
  - [ ] Thời gian hash 50–200 ms (`pytest --durations`) — quá nhanh nghĩa là tham số quá yếu
- **Cạm bẫy:** trả lỗi "email đã tồn tại" là cho phép người lạ dò xem ai đã đăng ký.

---

### T-2.2 — Email token + Mailer + verify
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.1 · **Ước lượng:** 3h
- **KH:** §11.5, UC-01
- **Việc:**
  - [ ] `app/core/mailer.py`: protocol `Mailer` + `SMTPMailer`
  - [ ] Template Jinja2 (HTML + text) cho verify và reset
  - [ ] Token ngẫu nhiên, **lưu hash** trong `email_tokens`, TTL từ settings
  - [ ] `POST /auth/verify-email`, `POST /auth/resend-verification`
  - [ ] Verify xong → `status='pending_approval'`
- **Xong khi (DoD):**
  - [ ] Đăng ký → thư hiện ở Mailpit `http://localhost:8025` trong ≤ 5 s
  - [ ] Bấm link → status đổi `pending_approval`
  - [ ] Bấm **lại** cùng link → không lỗi, chuyển tới trang đăng nhập (UC-01, idempotent)
  - [ ] `SELECT token_hash FROM email_tokens` → không dòng nào chứa token bản rõ có trong URL
  - [ ] Token quá hạn → trang "gửi lại", HTTP 200, không phải 500
- **Cạm bẫy:** lưu token bản rõ trong DB nghĩa là ai đọc được DB thì chiếm được mọi tài khoản.

---

### T-2.3 — Login + JWT + refresh xoay vòng
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.1 · **Ước lượng:** 4h
- **KH:** §11.2, ADR-07
- **Việc:**
  - [ ] `POST /auth/login` → access JWT (15 ph) + set cookie refresh `HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth`
  - [ ] `POST /auth/refresh`: xoay vòng, đánh dấu `used_at`, sinh token mới cùng `family_id`
  - [ ] **Phát hiện tái sử dụng:** token đã `used_at` bị dùng lại → revoke cả family
  - [ ] `GET /auth/me`
  - [ ] Dependency `get_current_user` kiểm chữ ký, `exp`, blacklist (T-2.4)
- **Xong khi (DoD):**
  - [ ] `pytest tests/api/test_auth.py` ≥ 15 case xanh
  - [ ] Dùng refresh token 2 lần → lần 2 trả `401` **và** `SELECT revoked_at FROM refresh_tokens WHERE family_id=...` → tất cả đều khác NULL
  - [ ] Access token hết hạn → `401` với `code=TOKEN_EXPIRED` (phân biệt với token sai)
  - [ ] Cookie refresh có đủ `HttpOnly`, `Secure`, `SameSite` (kiểm bằng `curl -i`)
  - [ ] `document.cookie` trong DevTools **không** thấy refresh token
- **Cạm bẫy:** `SameSite=Strict` sẽ làm hỏng luồng bấm link verify từ email. Dùng `Lax`.

---

### T-2.4 — Blacklist khi logout / đổi mật khẩu
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.3 · **Ước lượng:** 2h
- **KH:** §11.3, C21
- **Việc:**
  - [ ] `POST /auth/logout` → `SET bl:jti:{jti}` với TTL = thời gian còn lại của token + revoke family
  - [ ] Đổi mật khẩu → revoke **mọi** family + `SET bl:user:{uid} <now>`; middleware từ chối token có `iat` cũ hơn
  - [ ] `get_current_user` kiểm cả hai loại blacklist
- **Xong khi (DoD):**
  - [ ] Lưu access token → logout → dùng lại token đó → **401** (C21)
  - [ ] Đổi mật khẩu → mọi token cũ trên **mọi** thiết bị đều 401
  - [ ] `redis-cli TTL bl:jti:{jti}` ≤ 900 (không phải `-1`)
  - [ ] Blacklist trống mà token hợp lệ → vẫn qua được (không chặn nhầm)
- **Cạm bẫy:** blacklist không có TTL sẽ phình vô hạn. TTL phải bằng đúng thời gian sống còn lại của token.

---

### T-2.5 — Quên mật khẩu / đặt lại
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.2, T-2.4 · **Ước lượng:** 2h
- **KH:** §11.5, §11.6
- **Việc:** `POST /auth/forgot-password` (luôn trả 200 dù email không tồn tại) · `POST /auth/reset-password` · đặt lại xong → revoke mọi session · rate limit 3/giờ theo IP
- **Xong khi (DoD):**
  - [ ] Email không tồn tại → response **giống hệt** email tồn tại, không có thư nào ở Mailpit
  - [ ] Đặt lại xong → session cũ ở tab khác trả 401 ở request tiếp theo
  - [ ] Token reset dùng 2 lần → lần 2 trả 400
  - [ ] Gọi 4 lần trong 1 giờ từ cùng IP → lần 4 trả `429`
- **Cạm bẫy:** không revoke session sau khi đổi mật khẩu = kẻ đã chiếm tài khoản vẫn ở trong đó sau khi nạn nhân đổi mật khẩu.

---

### T-2.6 — Turnstile
- **Trạng thái:** ☐ · **Phụ thuộc:** T-H5, T-2.1 · **Ước lượng:** 1h
- **KH:** §11.6, RR-1
- **Việc:** verify token với Cloudflare ở `register` và `forgot-password` · `TURNSTILE_SECRET` rỗng → bỏ qua + **log cảnh báo mỗi lần boot** · widget ở FE
- **Xong khi (DoD):**
  - [ ] Đăng ký không kèm token → `400`
  - [ ] Token giả → `400`
  - [ ] `TURNSTILE_SECRET=` rỗng → đăng ký được, và log boot chứa chuỗi `TURNSTILE`
- **Cạm bẫy:** bỏ qua âm thầm khi thiếu secret nghĩa là một ngày nào đó bạn deploy production mà không có captcha và không biết.

---

### T-2.7 — Máy trạng thái tài khoản + phân quyền
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.3 · **Ước lượng:** 2h
- **KH:** §11.1, UC-01
- **Việc:** dependency `require_status(...)` · bảng phân quyền §11.1 · `pending_approval` + BYOK **được** chat, dùng system key thì không
- **Xong khi (DoD):**
  - [ ] `pytest tests/api/test_account_states.py` phủ **cả 5 trạng thái × 4 hành động** = 20 case
  - [ ] `pending_email` gọi `POST .../messages` → `403 EMAIL_NOT_VERIFIED`
  - [ ] `pending_approval` không BYOK → `403 PENDING_APPROVAL`
  - [ ] `pending_approval` **có** BYOK → **200** (đây là case dễ bỏ sót nhất)
  - [ ] `suspended` → không đăng nhập được
- **Cạm bẫy:** viết `if user.is_active` ở rải rác trong code. Tập trung vào một dependency, nếu không mỗi endpoint sẽ có một luật khác nhau.

---

### T-2.8 — Idempotency middleware
- **Trạng thái:** ☐ · **Phụ thuộc:** T-1.8 · **Ước lượng:** 2.5h
- **KH:** §11.4, ADR-15, C22 · **Tiêu chí:** S5
- **Việc:** middleware theo §11.4 · `in_progress` → `409` · `done` → trả lại response cũ · bắt buộc với `POST .../messages`, tuỳ chọn với endpoint khác
- **Xong khi (DoD):**
  - [ ] `scripts/test_idempotency.sh`: gửi 2 request **song song** cùng key → 1 tạo mới, 1 trả `409` hoặc cùng `message_id`; DB có **đúng 1** message (S5)
  - [ ] Gửi lại cùng key sau khi xong → cùng response, DB **không** thêm dòng
  - [ ] Thiếu header ở `POST .../messages` → `400`
  - [ ] `redis-cli TTL idem:...` ≈ 86400
- **Cạm bẫy:** C22 — nếu FE sinh key mới mỗi lần bấm thì middleware vô dụng. Key phải gắn với **lần soạn thảo**, đổi sau khi gửi thành công. Ghi rõ vào task FE T-3.4.

---

### T-2.9 — Rate limit token bucket
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.3 · **Ước lượng:** 2.5h
- **KH:** §10.6
- **Việc:** Lua script atomic trong Redis · nhóm route: chat 20/ph, auth 5/ph, upload 10/ph · theo IP cho route chưa đăng nhập · giới hạn `MAX_CONCURRENT_STREAMS` · header `X-RateLimit-*` + `Retry-After`
- **Xong khi (DoD):**
  - [ ] Gửi 25 request chat trong 1 phút → request 21 trả `429` với `Retry-After` là **số giây đúng**
  - [ ] 50 request song song → tổng số vượt qua **đúng bằng** hạn mức (chứng minh Lua atomic, không có race)
  - [ ] Mở 4 stream cùng lúc → cái thứ 4 trả `429 TOO_MANY_STREAMS`
  - [ ] Stream kết thúc → slot được trả lại (kiểm bằng cách mở cái thứ 4 sau khi một cái xong)
- **Cạm bẫy:** làm `GET` rồi `SET` trong Python thay vì Lua = race condition. Dưới tải, hạn mức sẽ bị vượt và bug này rất khó tái hiện.

---

### T-2.10 — Tier + cache
- **Trạng thái:** ☐ · **Phụ thuộc:** T-H6, T-0.5 · **Ước lượng:** 1.5h
- **KH:** §10.4
- **Việc:** repo `tiers` · `limit_override_json` gộp đè lên tier · cache Redis TTL 60 s · seed theo T-H6
- **Xong khi (DoD):**
  - [ ] Đổi `limit_5h_usd` trong DB → có hiệu lực trong **≤ 60 s** không restart (UC-07)
  - [ ] `limit_override_json = {"limit_5h_usd": 5.0}` → user đó dùng 5.0, các user khác cùng tier không đổi
  - [ ] Xoá cache Redis → đọc lại từ DB, không lỗi
- **Cạm bẫy:** cache vĩnh viễn thì admin panel đổi hạn mức mà không thấy tác dụng, và bạn sẽ nghĩ tính năng hỏng.

---

### T-2.11 — Quota estimator (kiểm TRƯỚC)
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.10, T-1.4 · **Ước lượng:** 3h
- **KH:** §10.2, §10.3, ADR-08 · **Tiêu chí:** S6
- **Việc:** ước tính trường hợp xấu nhất theo §10.2 · đọc hai ZSET, dọn `ZREMRANGEBYSCORE` trước khi đọc · `429` kèm `limit_type` và `retry_after` tính đúng · chạy **trong api**, trước enqueue
- **Xong khi (DoD):**
  - [ ] Đặt `limit_5h_usd = 0.001` → gửi tin nhắn → `429`, và `SELECT count(*) FROM usage_events` **không tăng**; log LiteLLM **không** có request nào (S6 — **0 USD phát sinh**)
  - [ ] `retry_after` trả về khớp (±5 s) với thời điểm phần tử cũ nhất rơi khỏi cửa sổ
  - [ ] Response body có `limit_type` phân biệt `5h` và `weekly`
  - [ ] Còn 15% quota → request vẫn qua, response có cảnh báo
- **Cạm bẫy:** ước tính lạc quan (chỉ tính prompt token) khiến một câu hỏi sinh 8000 token vượt hạn mức hàng chục lần. Phải tính theo `max_output`.

---

### T-2.12 — Quota meter (ghi SAU) + xử lý 9Router
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.11, T-1.6 · **Ước lượng:** 3h
- **KH:** §10.2, §9.5, A7
- **Việc:** worker ghi `usage_events` với `price_snapshot` · `cost_confidence='low'` cho `pricing_mode != 'metered'` · ghi `upstream_model_reported` nếu 9Router trả header · ZADD hai cửa sổ · ghi cả khi `cancelled` và khi `failed` giữa chừng
- **Xong khi (DoD):**
  - [ ] Một lượt chat → **đúng 1** dòng `usage_events` với `cost_usd > 0` và `price_snapshot` đầy đủ
  - [ ] Đổi giá trong catalog → dòng cũ **không đổi** `cost_usd` (A7)
  - [ ] Model qua 9Router → `cost_confidence='low'`
  - [ ] Huỷ giữa chừng → vẫn có 1 dòng, `completion_tokens` bằng phần đã sinh
  - [ ] `SUM(cost_usd)` trong Postgres khớp tổng ZSET Redis (±0.000001)
- **Cạm bẫy:** C16 — trộn chung `metered` và `unmetered` vào một con số làm bảng chi phí vô nghĩa. Phải tách từ đây, không phải sửa ở tầng hiển thị.

---

### T-2.13 — `rebuild_quota` từ Postgres
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.12 · **Ước lượng:** 2h
- **KH:** §10.3, RR-7
- **Việc:** `rebuild_quota(user_id)` dựng lại ZSET từ `usage_events` · tự gọi khi phát hiện ZSET rỗng mà DB có dữ liệu trong cửa sổ · lệnh CLI `python -m app.cli rebuild-quota --all`
- **Xong khi (DoD):**
  - [ ] `redis-cli FLUSHDB` → gọi API → quota **đúng** như trước khi flush (không phải 0)
  - [ ] `pytest tests/quota/test_rebuild.py` xanh với dữ liệu nằm trong và ngoài cửa sổ
  - [ ] Rebuild cho 10k usage event chạy < 2 s (dùng index `ix_usage_user_time`)
- **Cạm bẫy:** không có hàm này thì mỗi lần `docker compose down -v` khi dev là quota của mọi người reset — và bạn sẽ không phát hiện cho tới khi ai đó lợi dụng.

---

### T-2.14 — BYOK: mã hoá và CRUD
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.3 · **Ước lượng:** 3h
- **KH:** §10.5, C20
- **Việc:** `app/core/crypto.py` AES-256-GCM, nonce riêng mỗi bản ghi · `PUT /settings/keys/{provider}` kiểm key sống trước khi lưu · `GET` chỉ trả `key_last4` · middleware redact log
- **Xong khi (DoD):**
  - [ ] Lưu key → `SELECT key_cipher FROM user_provider_keys` **không** chứa chuỗi bản rõ
  - [ ] Hai user lưu **cùng** một key → hai `key_cipher` **khác nhau** (chứng minh nonce riêng)
  - [ ] `GET /settings/keys` trả `sk-...4f2a`, không bao giờ trả đủ
  - [ ] Lưu key sai → `400` với thông điệp **không chứa** chuỗi key
  - [ ] `docker compose logs | grep -E "sk-[a-zA-Z0-9]{20,}"` → **rỗng** (C20)
  - [ ] Đổi `MASTER_ENCRYPTION_KEY` → giải mã thất bại **có kiểm soát** (không phải crash), báo user nhập lại
- **Cạm bẫy:** dùng chung một nonce cho mọi bản ghi phá vỡ hoàn toàn GCM. Sinh nonce ngẫu nhiên mỗi lần mã hoá.

---

### T-2.15 — Đường gọi BYOK
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.14, T-1.3 · **Ước lượng:** 2h
- **KH:** §9.1, §10.5
- **Việc:** `ByokAdapter` với `base_url` từ catalog + key giải mã · chọn adapter: có BYOK cho provider đó thì ưu tiên (hoặc theo cài đặt user) · `key_source='byok'` → **không** trừ quota nhưng vẫn rate limit
- **Xong khi (DoD):**
  - [ ] Cấu hình BYOK DeepSeek, hết quota system → **vẫn chat được** (UC-07)
  - [ ] Dòng `usage_events` có `key_source='byok'`, và ZSET quota **không tăng**
  - [ ] Xoá key BYOK → tự quay về system key (nếu còn quota)
  - [ ] Rate limit vẫn áp dụng với BYOK (gửi 25 request → 429)
- **Cạm bẫy:** hai code path streaming khác nhau cho hai adapter. Cả hai đều OpenAI-compatible nên phải dùng **chung** parser — nếu thấy mình copy code, dừng lại.

---

### T-2.16 — Admin API + audit log
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.7 · **Ước lượng:** 3h
- **KH:** §16.3, §18.5, §20
- **Việc:** `/admin/users` (lọc theo status), approve/reject/suspend, PATCH tier/override/`can_execute_skills` · `/admin/usage` tách `metered`/`unmetered` · `/admin/catalog/reload` · mọi hành động ghi `audit_logs` · dependency `require_admin`
- **Xong khi (DoD):**
  - [ ] User thường gọi `/admin/users` → `403`; `curl` không token → `401`
  - [ ] Duyệt một user → `status='active'`, có 1 dòng `audit_logs` với `actor_id` đúng
  - [ ] `/admin/usage` trả hai nhóm riêng biệt (C16)
  - [ ] `pytest tests/api/test_admin_authz.py` phủ **mọi** endpoint `/admin/*` với user thường
- **Cạm bẫy:** quên `require_admin` ở **một** endpoint là đủ. Viết test lặp qua danh sách route thay vì test từng cái bằng tay.

---

### T-2.17 — Cảnh báo chi tiêu
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.12, T-2.2 · **Ước lượng:** 1.5h
- **KH:** RR-1, §21.5
- **Việc:** cron hằng giờ tổng chi tiêu ngày · vượt `DAILY_ALERT_USD` → gửi mail cho admin, tối đa 1 lần/ngày · vượt `MONTHLY_BUDGET_USD` → mail khẩn + ghi log mức WARNING
- **Xong khi (DoD):**
  - [ ] Đặt `DAILY_ALERT_USD=0.0001` → chạy cron → có thư ở Mailpit
  - [ ] Chạy cron lần 2 cùng ngày → **không** gửi thư thứ hai
  - [ ] Thư ghi rõ user nào tiêu nhiều nhất và bao nhiêu
- **Cạm bẫy:** không chống lặp thì bạn nhận 24 thư mỗi ngày và sẽ lọc chúng vào thùng rác — cảnh báo bị bỏ qua là cảnh báo không tồn tại.

---

### T-2.18 — Bộ test IDOR
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.16 · **Ước lượng:** 1.5h
- **KH:** §20 · 🔒 **KHÔNG ĐƯỢC GỘP**
- **Việc:** fixture hai user A và B với dữ liệu đầy đủ · test A truy cập **mọi** tài nguyên của B: conversation, message, attachment, artifact, key, usage · khẳng định **404**, không phải 403
- **Xong khi (DoD):**
  - [ ] `pytest tests/security/test_idor.py` ≥ 20 case xanh
  - [ ] Mọi case trả `404` (403 xác nhận tài nguyên tồn tại → rò rỉ thông tin)
  - [ ] Cố tình bỏ điều kiện `user_id` trong **một** hàm repo → test **đỏ** (chứng minh test có tác dụng)
- **Cạm bẫy:** lọc `user_id` trong Python sau khi đã `SELECT` về là sai — dữ liệu đã rời khỏi DB, và một lần quên là rò rỉ. Lọc trong SQL (T-1.1).

---

### T-2.19 — Admin UI tối thiểu
- **Trạng thái:** ☐ · **Phụ thuộc:** T-2.16, T-0.10 · **Ước lượng:** 3h
- **KH:** §16.3 · **Mốc:** M4
- **Việc:** trang `/admin` chỉ hiện khi `role=admin` · bảng user chờ duyệt + nút Duyệt/Từ chối · bảng chi phí đơn giản · nút reload catalog · **chưa cần đẹp** (T-HD7 làm sau)
- **Xong khi (DoD):**
  - [ ] Đăng ký một tài khoản test → thấy trong danh sách chờ → bấm Duyệt → tài khoản đó chat được (**M4 — luồng đầu-cuối hoàn chỉnh**)
  - [ ] User thường vào `/admin` → chuyển hướng, và API vẫn trả 403 kể cả khi ép vào URL
  - [ ] Bảng chi phí hiện hai cột `metered` / `unmetered`
- **Cạm bẫy:** ẩn menu ở FE **không phải** phân quyền. Kiểm ở server là bắt buộc (T-2.16 đã làm; task này không được dựa vào FE).

---

## 7. Phase 3 — Giao diện *(dạng bảng — mở rộng bằng prompt §7.4 của META khi tới nơi)*

**Đặc thù phase này:** phần lớn công việc thiết kế là của **bạn** qua Claude Design (T-HD1…T-HD5, T-HD7). Agent nối component vào state/API và viết test. Agent **không tự đổi màu, spacing, bố cục**.

| ID | Task | Phụ thuộc | KH | Ước lượng |
|---|---|---|---|---|
| T-3.1 | Khung app: router, layout shell, error boundary, trang 404/500 | T-1.14 | §23 | 3h |
| T-3.2 | Áp `theme.css` do T-HD1 giao; chuyển sáng/tối; kiểm tương phản bằng axe-core | **T-HD1** | §19.1, P5 | 2h |
| T-3.3 | Sidebar: danh sách hội thoại, ẩn/hiện, ghim, xoá, đổi tên, tìm kiếm cục bộ | **T-HD2** | §18.2 | 4h |
| T-3.4 | Ô nhập: gửi, Dừng, đếm ký tự, **Idempotency-Key theo lần soạn thảo** (C22) | T-2.8 | §11.4 | 3h |
| T-3.5 | Bong bóng tin nhắn + markdown sanitize + code block có nút Copy | **T-HD3** | §20 | 4h |
| T-3.6 | Model Picker đọc `GET /models`, badge capability, xám khi `available: false` | **T-HD4**, T-0.7 | §9.3, UC-05 | 3h |
| T-3.7 | Nút dưới câu trả lời: Copy · Like · Dislike · Retry · Đổi model & retry | T-1.13 | UC-02 | 3h |
| T-3.8 | Điều hướng nhánh `‹ n/m ›` + sửa message user tạo nhánh | T-1.13 | §8.2, UC-04 | 3h |
| T-3.9 | Hoạt ảnh theo token của T-HD5; tôn trọng `prefers-reduced-motion` | **T-HD5** | P5 | 3h |
| T-3.10 | Responsive 375 px → desktop; sidebar thành drawer trên mobile | T-3.3 | S8 | 3h |
| T-3.11 | Thanh quota + cảnh báo còn ≤ 20% + màn hình hết quota có `retry_after` | T-2.11 | UC-07 | 2h |
| T-3.12 | Admin UI hoàn chỉnh theo T-HD7 + trang Cài đặt (BYOK, theme, model mặc định) | **T-HD7**, T-2.19 | §16.3 | 4h |

**DoD của phase:** KE-HOACH §24.3 dòng P3. Bổ sung hai DoD cứng:
- `npx lighthouse https://localhost --preset=mobile` → Accessibility ≥ 90, Performance ≥ 80 (S8)
- `npx @axe-core/cli https://localhost` → 0 lỗi mức `serious` hoặc `critical`

---

## 8. Phase 4 — Ảnh & Vision *(dạng bảng)*

| ID | Task | Phụ thuộc | KH | Ước lượng |
|---|---|---|---|---|
| T-4.1 | MinIO client, bucket, chính sách; presigned URL TTL ngắn | T-0.4 | §15.2 | 2h |
| T-4.2 | `POST /attachments`: kiểm magic bytes, size theo tier, allowlist MIME, **từ chối SVG** | T-4.1 | §15.2 | 3h |
| T-4.3 | Pipeline ảnh: `exif_transpose` → resize `VISION_MAX_EDGE_PX` → nén → base64 (C34) | T-4.2 | §15.3 | 2h |
| T-4.4 | Gắn ảnh vào context; `RESEND_IMAGES_IN_HISTORY=false` mặc định (C33) | T-4.3, T-1.4 | §15.3 | 2h |
| T-4.5 | Guard capability `vision`: FE nút mờ + icon cấm khi hover; BE trả 422 nếu bypass | T-3.6 | S9, UC-06 | 2h |
| T-4.6 | Worker trích text PDF/DOCX; PDF không có text layer → render trang → vision, giới hạn `MAX_PDF_PAGES_VISION` | T-4.2 | §15.3 | 3h |
| T-4.7 | FE: kéo-thả, dán clipboard, xem trước, xoá trước khi gửi | T-4.2 | UC-06 | 2h |

---

## 9. Phase 5 — Artifacts *(dạng bảng)*

| ID | Task | Phụ thuộc | KH | Ước lượng |
|---|---|---|---|---|
| T-5.1 | Tool `create_artifact` + parse code block dài thành artifact | T-1.6 | §14.1 | 3h |
| T-5.2 | CRUD artifact + phiên bản (`parent_artifact_id`, `version`) | T-5.1 | §14.2 | 2h |
| T-5.3 | Event SSE `artifact` + FE mở panel khi nhận | T-5.1 | §7.4 | 2h |
| T-5.4 | Panel phải: khung, đóng/mở, kéo rộng, toàn màn hình trên mobile | T-3.10 | UC-10 | 3h |
| T-5.5 | Hiển thị theo loại: markdown, code (highlight), mermaid, svg + nút Tải | **T-HD6**, T-5.4 | §14.1 | 4h |
| T-5.6 🔒 | Origin phụ `artifacts.localhost`: route render, CSP, iframe `sandbox` **không** `allow-same-origin` | T-0.8 | ADR-10, §14.3 | 4h |
| T-5.7 | Nạp nội dung qua `postMessage`, không qua URL | T-5.6 | §14.3 | 2h |
| T-5.8 | Runtime React/HTML: Babel standalone, `artifact_runtime.json`, watchdog treo (C31, C32) | T-5.7 | §14.4 | 4h |
| T-5.9 | Tab phiên bản `v1 v2 v3` + so sánh khác biệt đơn giản | T-5.2, T-5.5 | §14.2 | 2h |

**DoD then chốt của phase:** artifact HTML chứa `fetch('/api/v1/conversations')` → **không** lấy được dữ liệu (S12). Test tự động ở `tests/e2e/test_artifact_origin.spec.ts`.

---

## 10. Phase 6 — Web tools *(gạch đầu dòng — mở rộng khi tới nơi)*

- **T-6.1** Tavily client sau interface `SearchProvider`; hỏng → tool trả `error`, chat **không chết** *(KH §12.4)*
- **T-6.2** 🔒 `app/tools/ssrf.py::validate_url()` — bốn lớp §12.2, gồm IPv6 và `::ffff:` mapped
- **T-6.3** 🔒 Transport httpx tuỳ chỉnh: kết nối tới **IP đã kiểm**, đặt `Host` thủ công (chống DNS rebinding)
- **T-6.4** 🔒 `tests/tools/test_ssrf.py` ≥ 25 case: metadata endpoint, tên service Docker, loopback, redirect chain, rebinding *(S10)*
- **T-6.5** Service `fetcher` ở network `egress`, **không** join `internal`; trích text bằng trafilatura
- **T-6.6** Leo thang Playwright theo §12.3; context per-request, `mem_limit`, block ảnh/font *(C24)*
- **T-6.7** Đăng ký tool vào registry; công tắc "Tìm web" ở FE; chip nguồn có favicon
- **T-6.8** Đếm lượt search/ngày theo `tiers.web_searches_per_day`

---

## 11. Phase 7 — Skills & Sandbox *(gạch đầu dòng)*

- **T-7.1** 🔒 **Task thí nghiệm:** chứng minh worker gọi được `sandbox` qua **Unix socket** khi `network_mode: none`. *Nếu hướng này không chạy, DỪNG và viết lại ADR-09 trước khi làm tiếp* *(Phụ lục C, ghi chú cuối)*
- **T-7.2** Image sandbox: rootfs read-only, tmpfs `/work`, `cap_drop: ALL`, non-root, **không** `env_file` *(C27)*
- **T-7.3** Server sandbox: `POST /exec`, thư mục tạm riêng mỗi lần, dọn sạch sau khi xong
- **T-7.4** 🔒 `tests/sandbox/test_isolation.py`: không ra mạng được, `while True` bị kill, `os.environ` không thấy secret *(S11)*
- **T-7.5** Loader skill format Anthropic: đọc frontmatter, đăng ký vào bảng `skills`
- **T-7.6** Progressive disclosure ba tầng + tool `load_skill` *(C30)*
- **T-7.7** Tool `run_code` → sandbox; file sinh ra → MinIO → artifact *(C29)*
- **T-7.8** Quyền `can_execute_skills`; bị chặn thì model nhận `tool_result` báo lỗi rõ, không im lặng
- **T-7.9** FE: panel chọn skill, bật/tắt theo user, hiện trạng thái chạy code

---

## 12. Phase 8 — Share, voice, export, PWA *(gạch đầu dòng)*

- **T-8.1** `POST /conversations/{id}/share` → snapshot JSONB bất biến; ảnh copy sang prefix riêng *(ADR-14, §16.1)*
- **T-8.2** Trang công khai `/s/{token}`, `noindex`, không lộ email/model_id/chi phí
- **T-8.3** Fork: `POST /s/{token}/fork` sau khi đăng nhập → hội thoại mới của người fork
- **T-8.4** Voice input + TTS bằng Web Speech API; feature-detect, **Firefox thì ẩn nút** *(ADR-13, §16.2)*
- **T-8.5** **Export Markdown**: `GET /conversations/{id}/export?format=md` — đường đi hiện tại, có tiêu đề, thời gian, tên model hiển thị; code block giữ nguyên fence; artifact xuất kèm dạng phụ lục
- **T-8.6** **Export JSON**: `?format=json` — có `?full=true` để xuất **cả cây** kèm `parent_id`, đủ để nạp lại; streaming response, không dựng cả file trong RAM
- **T-8.7** FE: nút Export trong menu hội thoại, chọn định dạng, tải về với tên file có ngày
- **T-8.8** PWA: manifest, service worker, icon, cài được trên iOS/Android

---

## 13. Phase 9 — Hoàn thiện *(gạch đầu dòng)*

- **T-9.1** Bộ eval golden-set 12 case §21.3 + `make eval MODEL=...`; **model chưa qua eval không được `enabled: true`**
- **T-9.2** Chuyển Mailpit → SMTP thật *(chặn bởi T-H8)*; test gửi thư thật tới hộp thư ngoài
- **T-9.3** Backup: cron `pg_dump` + `mc mirror`, giữ 14/7 bản *(§22.7)*
- **T-9.4** Lên domain: Let's Encrypt, `artifacts.<domain>`, cập nhật `.env`, bật HSTS *(chặn bởi T-H10)*
- **T-9.5** Rà soát log: không secret, không nội dung message đầy đủ; middleware redact có test
- **T-9.6** Trang thông tin cho người dùng: dữ liệu gửi tới provider nào, admin đọc được gì *(§20)*
- **T-9.7** README + hướng dẫn vận hành: khởi động lại, xem log, thêm model, thêm user

---

## 14. Backlog

Ý tưởng nảy ra giữa chừng. **KHÔNG code ngay.** Muốn đưa lên roadmap phải viết ADR hoặc thêm vào một phase cụ thể.

| # | Ý tưởng | Nguồn |
|---|---|---|
| B-01 | Playwright tự đăng nhập vào trang bên thứ ba | Đã loại ở GĐ1, §2.2 |
| B-02 | Chuyển sandbox sang gVisor/Firecracker nếu mở đăng ký rộng hơn | ADR-09, RR-2 |
| B-03 | Chuyển model catalog vào DB, sửa qua admin panel | ADR-12 |
| B-04 | Prometheus + Grafana thay bảng thống kê tự viết | §21.2 |
| B-05 | MCP client | R21, §13.5 — interface đã sẵn sàng |
| B-06 | RAG: collection, upload tài liệu, `search_knowledge` tool | R21, §21.4 |
| B-07 | i18n thêm ngôn ngữ (hạ tầng `t()` đã có từ T-0.10) | §2.2 |
| B-08 | **Phân trang/giới hạn khi một user có hàng nghìn hội thoại** — hiện chưa có gì chặn | Điểm yếu #4 trong rà soát §7.5 |
| B-09 | Tìm kiếm toàn văn trong lịch sử hội thoại (Postgres FTS) | — |
| B-10 | Thư mục/nhãn cho hội thoại | — |
| B-11 | Prompt template dùng lại được | — |
| B-12 | Thống kê cá nhân cho user: model hay dùng, chi tiêu theo tháng | — |
| B-13 | Import hội thoại từ ChatGPT/Claude export | Đối xứng với T-8.5/T-8.6 |
| B-14 | So sánh hai model song song trong cùng một câu hỏi | — |
| B-15 | `.env.example` **không `source` được bằng shell**: `MAIL_FROM=Scarlet <no-reply@...>` bị shell hiểu là redirect. Docker compose đọc bình thường, nhưng dev chạy backend ngoài Docker cần `scripts/load-env.sh` hoặc direnv | T-0.3 — chép nguyên KH Phụ lục B nên không tự sửa |
| B-17 | KH §22.6 nhắc `CORS_ORIGINS` khi lên domain, nhưng biến này **không có trong Phụ lục B** | T-0.3 |
| B-18 | `ValidationError` in kèm giá trị bị từ chối (`input_value='short'`) — một secret yếu sẽ lọt vào log lúc app từ chối boot. Cân nhắc bọc `Settings()` để in bản tóm tắt đã che giá trị | T-0.3 |

---

## 15. DoD chung — áp dụng cho MỌI task

Không task nào được đánh ✅ nếu thiếu bất kỳ dòng nào dưới đây.

- [ ] `make test` xanh, **không** có test nào bị `skip` mà không có lý do ghi trong code
- [ ] `make lint` sạch (ruff + mypy)
- [ ] `make check-hardcode` exit 0
- [ ] `docker compose ps` — mọi service `healthy`
- [ ] Biến mới (nếu có) đã thêm vào **cả** `Settings` **và** `.env.example`
- [ ] Endpoint mới (nếu có) đã thêm vào KE-HOACH §18
- [ ] Không log secret, key, hay nội dung message đầy đủ
- [ ] Báo cáo có **output thật** của lệnh DoD, không phải mô tả
- [ ] Một task = một commit, thông điệp commit chứa ID task

---

## 16. Nhật ký quyết định

| # | Ngày | Quyết định | Lý do |
|---|---|---|---|
| **NQ-01** | 2026-09-10 | Ước lượng tổng đổi từ 180–250 h (KH §24.2) sang **262 h** | Sau khi bẻ nhỏ thành 104 task, con số từ dưới lên chính xác hơn. Ước lượng từ trên xuống luôn lạc quan. Dùng bảng §2 của file này |
| **NQ-02** | 2026-09-10 | **Export hội thoại JSON/Markdown vào v1** (T-8.5, T-8.6), gỡ khỏi Backlog | Q-12 đã được trả lời: có cần |
| **NQ-03** | 2026-09-10 | Q-01…Q-11 dùng mặc định đã ghi trong KH §26 | Người dùng chốt "còn lại làm như bạn đề xuất". **Nếu mặc định nào sai, sửa ở đây và ghi thành NQ mới** |
| **NQ-04** | 2026-09-10 | T-7.1 là **task thí nghiệm chặn cả P7** | Phụ lục C phát hiện `network_mode: none` khiến worker không gọi HTTP vào sandbox được. Hướng Unix socket chưa được chứng minh — phải thử trước khi xây phần còn lại |
| **NQ-05** | 2026-09-10 | Ba DoD "quan sát bằng mắt" ở KH §24.3 (P3) được thay bằng lighthouse + axe-core | Điểm yếu #3 trong rà soát §7.5: DoD không thể sai là DoD vô dụng |
| **NQ-07** | 2026-09-10 | Bổ sung **R22** (mở rộng provider có endpoint tuỳ chỉnh), **S15**, **§9.8–9.10** và **T-0.12** | Người dùng hỏi lại và phát hiện thiếu sót: kiến trúc chịu được nhưng không có yêu cầu nào ghi ra, và S7 chỉ đo "thêm **model**" chứ không đo "thêm **provider**". Khả năng không được đo là khả năng sẽ mất |
| **NQ-06** | 2026-09-10 | **Không cắt phạm vi** (đã đề nghị cắt 40%, bị từ chối) | Không có deadline. Đường lùi vẫn ghi ở §7.5 của báo cáo rà soát nếu sau này cần |
| **NQ-08** | 2026-09-10 | `POSTGRES_PASSWORD` **vào `.env.example`** (bổ sung so với KH Phụ lục B) nhưng **không** vào `Settings`; `tests/test_settings_complete.py` miễn trừ nó qua danh sách `COMPOSE_ONLY`. Gỡ B-16 khỏi Backlog | Phương án (a) người dùng chốt. `.env.example` là hợp đồng với **người vận hành**, không chỉ với backend: compose cần biến này (KH Phụ lục C) nên nó phải hiện diện ở đó, còn backend không có việc gì đọc mật khẩu Postgres ngoài `DATABASE_URL`. Danh sách miễn trừ có test riêng chống mục ruỗng: tên nào không còn trong `.env.example` phải bị gỡ |

---

*Hết `tasks.md` v1.0. Phase 3–9 chưa chi tiết là **có chủ ý** (META §4.4) — dùng prompt §7.4 để mở rộng khi tới nơi, dựa trên tốc độ thực tế đã đo được chứ không dùng lại con số hôm nay.*
