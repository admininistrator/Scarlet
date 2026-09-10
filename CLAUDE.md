# Scarlet — luật cho agent

Chatbot self-host, 15–20 người dùng. Đọc `docs/KE-HOACH.md` theo mục khi task yêu cầu.
Hàng đợi công việc ở `docs/tasks.md`. **Mỗi lần làm đúng một task.**

## Môi trường

- Repo **phải** nằm trong WSL filesystem (`/home/...`), **không** phải `/mnt/c/...` — chậm 10–20× nếu sai
- Backend chạy trong `.venv` riêng: `cd backend && source .venv/bin/activate`
- Tạo lần đầu: `python -m venv .venv && pip install -e ".[dev]"`
- **Không** cài package vào Python hệ thống. **Không** dùng conda. Kiểm bằng `which python`
- Frontend dùng `pnpm`, không `npm`/`yarn`
- Mọi service chạy qua `docker compose --profile core --profile tools`

## Mười luật kiến trúc

Chi tiết và lý do ở `docs/KE-HOACH.md` §0. Mâu thuẫn với luật nào → **dừng và hỏi**, không tự hoà giải.

```
A1  Generation KHÔNG chạy trong HTTP handler. Handler tạo record + enqueue job.
    Worker sinh chữ, ghi Redis Stream. API chỉ ĐỌC stream và phát SSE.   → §7
A2  Message là CÂY (parent_id). Không có query "tất cả message theo thời gian".
    Dựng context = đi từ active_leaf_id ngược lên gốc.                   → §8
A3  Không literal trong .py/.tsx: tên model, giá, giới hạn, URL provider,
    màu sắc. Chúng sống ở config/ hoặc bảng tiers/settings.              → §19
A4  Thiếu biến .env bắt buộc → app KHÔNG boot, in đúng tên biến thiếu.
    Không os.getenv("X", "default") cho bất cứ thứ gì quan trọng.        → §19.2
A5  Mọi URL do người dùng cung cấp đi qua app/tools/ssrf.py::validate_url().
    Không ngoại lệ, kể cả từng hop redirect.                             → §12
A6  Backend KHÔNG tự chạy code do LLM/skill sinh ra. Luôn gửi sang service
    sandbox.                                                             → §13
A7  Chi phí snapshot vào usage_events tại thời điểm gọi. Đổi giá trong
    catalog KHÔNG được làm đổi lịch sử.                                  → §10
A8  Mọi POST tạo tài nguyên đọc header Idempotency-Key. Bắt buộc với
    POST /conversations/{id}/messages.                                   → §11.4
A9  Backend chỉ nói MỘT protocol với model: OpenAI Chat Completions
    streaming. Khác biệt provider xử lý ở LiteLLM hoặc adapter.          → §9
A10 KHÔNG tự "đơn giản hoá" kiến trúc khi gặp khó. Thấy thừa → ghi
    Backlog trong tasks.md và HỎI.
```

## Không bao giờ

- Thêm `fetcher` hoặc `sandbox` vào Docker network `internal` — đó là lớp phòng thủ số 1 của §12.2 và ADR-09
- Dùng `sandbox="allow-scripts allow-same-origin"` cho iframe artifact — vô hiệu hoá toàn bộ cách ly (§14.3)
- Bỏ `proxy_buffering off` khỏi location SSE trong `nginx.conf` — streaming sẽ im lặng rồi trả một cục (C1)
- Dùng Redis Pub/Sub hoặc consumer group cho stream — mất khả năng resume, và hai tab thì một tab đói (ADR-01, C7)
- Đặt `ON DELETE CASCADE` trên `messages.parent_id` — xoá một message là mất cả nhánh (C12)
- Lọc `user_id` ở tầng Python sau khi đã SELECT — lọc **trong câu SQL**
- Import LangChain (ADR-04 đã loại)
- Sửa file trong `docs/` — trừ mục Backlog và Nhật ký quyết định của `tasks.md`
- Commit `.env`, thư mục `certs/`, hoặc bất cứ chuỗi nào khớp `sk-[A-Za-z0-9]{20,}`

## Quy trình mỗi task

1. Đọc mục "KH tham chiếu" của task **trước khi** viết dòng code đầu tiên
2. Chưa rõ hoặc thấy mâu thuẫn → **hỏi**, không đoán
3. Làm đúng phần "Việc cần làm", không làm thêm
4. Chạy **từng dòng** DoD, dán **output thật** vào báo cáo
5. Báo cáo 4 phần: đã làm gì · output DoD · lệch kế hoạch chỗ nào · cần ghi Backlog gì

Task đánh 🔒 làm **một mình, một commit riêng**. Gộp nó với task khác là lý do hợp lệ để bỏ cả phiên.

## Trước khi báo xong

```bash
make test && make lint && make check-hardcode && docker compose ps
```

Commit: `<loại>(T-<id>): <mô tả>` — ví dụ `feat(T-1.7): SSE consumer đọc theo cursor`
