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

### Gỡ một hạn mức rate limit đang chặn (§10.6)

`register` / `resend-verification` / `forgot-password` là **3 lượt/giờ/IP**, nên
đăng ký hai tài khoản test trong một phiên là chạm trần. Gỡ bằng:

```bash
# khi không biết IP mà Nginx gắn cho mình — ngả dùng khi chạy DoD
docker compose --profile core --profile tools exec -T api   python -m app.cli reset-rate-limit ip register --all

# khi đã biết mình cần gỡ cho ai
docker compose --profile core --profile tools exec -T api   python -m app.cli reset-rate-limit ip register 172.18.0.1
docker compose --profile core --profile tools exec -T api   python -m app.cli reset-rate-limit user chat <user_id>
```

Trục `ip` nhận tên **route** (`register`, `resend-verification`,
`forgot-password`, `reset-password`, `logout`); trục `user` nhận tên **nhóm**
(`chat`) và một `user_id` dạng UUID. Một tên gõ sai dừng ở `argparse` với mã
thoát 2 chứ không chạy xong rồi in "0 khoa" — đây là **B-188**, và ngả cũ
(`redis-cli DEL rl:ip:register:<ip>`) không còn cần thiết.

Trần đồng thời (`rl:streams:{uuid}`, §10.6 hàng 3) **không** có ở đây: nó tự
nhả qua `nha_ghe_sinh` + đối chiếu Postgres.

## Tài liệu

- `docs/KE-HOACH.md` — kế hoạch kỹ thuật đầy đủ
- `docs/tasks.md` — hàng đợi công việc
- `docs/HUONG-DAN-AGENT.md` — hướng dẫn giao việc cho agent
- `CLAUDE.md` — luật rút gọn cho agent
