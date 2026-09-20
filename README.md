# Scarlet

Chatbot self-host cho 15–20 người dùng.

## Chạy

```bash
cp .env.example .env      # điền giá trị thật
docker compose --profile core --profile tools up -d
```

Backend phát triển trong `.venv` riêng:

```bash
cd backend && source .venv/bin/activate
```

Frontend dùng `pnpm`, không dùng `npm`/`yarn`.

## Vận hành

### Khởi động lại `api` hoặc `web` thì phải khởi động lại `nginx`

```bash
docker compose --profile core --profile tools up -d api      # hoặc web
docker compose --profile core --profile tools restart nginx  # BẮT BUỘC, ngay sau đó
```

Nginx phân giải tên upstream (`api`, `web`) **một lần lúc boot** rồi giữ IP
đó. Container khởi động lại thì đổi IP, nên mọi request sau đó nhận
`502 Bad Gateway` — và triệu chứng ấy đọc y hệt "API chết", dù `api` vẫn
`healthy` và `/health` vẫn 200 từ bên trong container.

Đo được ba lần: hai lần ở T-2.19, một lần ở T-3.1a. Đây là **B-189**; ngả sửa
bằng `resolver 127.0.0.11 valid=10s;` trong `nginx.conf` đã được cân nhắc và
**không chọn** (2026-09-20), vì nó cho Nginx khởi động được cả khi `api` chưa
lên — ngược đúng lý lẽ NQ-11 đã chọn cho `location /`.

### Thêm/xoá một package của frontend

`node_modules` **không** nằm trong bind-mount: `docker-compose.override.yml`
che nó bằng một volume ẩn danh, và bản thật nằm trong image `scarlet-web`.
Nên `pnpm add` một mình chỉ sống tới lần tạo lại container kế tiếp:

```bash
docker compose --profile core --profile tools exec -T web \
  pnpm add <goi> --store-dir /root/.local/share/pnpm/store
docker compose --profile core --profile tools build web
docker compose --profile core --profile tools up -d --force-recreate --renew-anon-volumes web
docker compose --profile core --profile tools restart nginx   # xem mục trên
```

`--store-dir` là bắt buộc: `/app` là bind-mount nên pnpm tự đổi sang một store
cục bộ (`/app/.pnpm-store`) và từ chối chạy với `ERR_PNPM_UNEXPECTED_STORE`.
`--renew-anon-volumes` là thứ làm image vừa build thật sự được dùng.

## Tài liệu

- `docs/KE-HOACH.md` — kế hoạch kỹ thuật đầy đủ
- `docs/tasks.md` — hàng đợi công việc
- `docs/HUONG-DAN-AGENT.md` — hướng dẫn giao việc cho agent
- `CLAUDE.md` — luật rút gọn cho agent
