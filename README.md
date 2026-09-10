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

## Tài liệu

- `docs/KE-HOACH.md` — kế hoạch kỹ thuật đầy đủ
- `docs/tasks.md` — hàng đợi công việc
- `docs/HUONG-DAN-AGENT.md` — hướng dẫn giao việc cho agent
- `CLAUDE.md` — luật rút gọn cho agent
