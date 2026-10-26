# Scarlet — Runbook AWS EC2

Cập nhật: 2026-10-02. Dành cho người vận hành server đã dựng theo cấu hình bên dưới.

Tra nhanh: [lệnh thường dùng](#3-lệnh-thường-dùng) · [cập nhật sau pull](#4-sau-khi-pull-trên-ec2-quy-trình-cập-nhật) · [SMTP](#6-gmail-smtp-và-email-xác-thực) · [rate limit](#7-gỡ-rate-limit-cho-đúng-đối-tượng) · [backup/restore](#8-backup-restore-và-khôi-phục-khi-cập-nhật-lỗi).

**Bằng chứng hiện có:** log người dùng cung cấp cho thấy PostgreSQL, Redis, MinIO tự build, LiteLLM, API, worker, frontend và Nginx đều healthy. API đã nạp Gmail SMTP cổng 587, STARTTLS, mật khẩu dài 16 ký tự và không có khoảng trắng. **Chưa xác nhận** thư đã tới hộp thư, lượt chat production thành công hoặc gia hạn chứng chỉ đã vượt qua dry-run. Người viết runbook chưa trực tiếp chạy lệnh trên AWS.

## 1. Môi trường và nơi chạy lệnh

| Mục | Giá trị / quy ước |
|---|---|
| GitHub | https://github.com/admininistrator/Scarlet |
| Nhánh deploy | `main` |
| Repo local WSL | `/home/dmin/scarlet` |
| Repo EC2 | `/home/ubuntu/scarlet` |
| User SSH | `ubuntu` |
| Hệ điều hành theo hướng dẫn | Ubuntu Server 24.04 LTS x86_64 |
| Instance đề xuất trong danh sách Free Tier | `m7i-flex.large`, 2 vCPU / 8 GiB RAM; chưa xác nhận lựa chọn thực tế |
| Lệnh Compose trên EC2 | `sudo scarlet-compose …` |
| Profile | `core`; Ollama tách sang `local-llm` |

Các lệnh bên dưới chạy **trên EC2**, trừ đoạn có nhãn **LOCAL WSL**. Chạy từng khối, đọc kết quả; nếu lệnh lỗi thì dừng ở bước đó.

Các giá trị `ELASTIC_IP`, `EMAIL_DA_DANG_KY`, `IP_TRONG_LOG` là chỗ cần thay. Domain trong ví dụ không phải domain đã xác nhận của server:

```bash
cd /home/ubuntu/scarlet
APP_DOMAIN='chat.example.com'
ARTIFACT_DOMAIN='artifacts.example.com'
```

### SSH — LOCAL WSL

```bash
chmod 600 ~/.ssh/scarlet-ec2.pem
ssh -o ConnectTimeout=10 -i ~/.ssh/scarlet-ec2.pem ubuntu@ELASTIC_IP
```

Nếu timeout: kiểm tra instance Running, status checks, IP đích hiện tại và rule SSH của **Security Group đang gắn với instance**. Lấy IP Internet hiện tại của local bằng:

```bash
curl -4 -sS https://checkip.amazonaws.com
```

Source của rule TCP 22 cần là IP này + `/32`. Subnet cần route `0.0.0.0/0 → Internet Gateway`. Nếu stop/start mà chưa gắn Elastic IP, public IP có thể đổi.

## 2. Cấu hình riêng của EC2

| File / thư mục | Vai trò | Khi cập nhật |
|---|---|---|
| `docker-compose.yml` | Compose gốc từ GitHub | Pull cập nhật; kiểm tra các thay đổi |
| `docker-compose.override.yml` | Dev: reload, bind-mount, Mailpit | Không nạp trên EC2 |
| `docker-compose.aws.yml` | Override production riêng trên EC2 | Giữ lại và đối chiếu khi Compose gốc đổi |
| `.env` | Secret, DB, SMTP, domain, Turnstile | Giữ secret cũ; bổ sung biến mới từ `.env.example` |
| `.env.providers` | Key/endpoint provider cho LiteLLM | Giữ key; bổ sung biến từ file mẫu khi cần |
| `deploy-config/` | Catalog, prompt, LiteLLM, Nginx dùng trên EC2 | **Không tự cập nhật theo `config/` khi pull** |
| `frontend/Dockerfile.aws` | Build frontend static bằng pnpm | Giữ file riêng; source frontend mới được đưa vào image khi build |
| `frontend/aws.nginx.conf` | Serve static và SPA fallback, cổng nội bộ 5173 | Giữ file riêng |
| `deploy-minio/Dockerfile` | Build MinIO + mc từ source | Giữ file và image tự build |
| `/usr/local/bin/scarlet-compose` | Wrapper chọn đúng project/file/env | Nằm ngoài repo; Git không cập nhật |
| `/etc/letsencrypt/` | Chứng chỉ HTTPS và cấu hình gia hạn | Nằm ngoài repo; backup riêng |
| `/var/www/certbot/` | Webroot HTTP-01 | Mount vào Nginx để gia hạn |

Để các file server không hiện như thay đổi source, thêm một lần trên EC2:

```bash
cd /home/ubuntu/scarlet
cat >> .git/info/exclude <<'EOF'
/deploy-config/
/deploy-minio/
/docker-compose.aws.yml
/frontend/Dockerfile.aws
/frontend/aws.nginx.conf
/backups/
/scarlet-local.dump
EOF
chmod 600 .env .env.providers
```

`exclude` chỉ ẩn file khỏi Git, không tạo backup. Secret và các file production phải được lưu riêng.

Wrapper cần có nội dung như sau. Chỉ tạo lại nếu bị thiếu hoặc sai:

```bash
sudo tee /usr/local/bin/scarlet-compose >/dev/null <<'EOF'
#!/bin/sh
exec /usr/bin/docker compose \
  --project-name scarlet \
  --project-directory /home/ubuntu/scarlet \
  --env-file /home/ubuntu/scarlet/.env \
  -f /home/ubuntu/scarlet/docker-compose.yml \
  -f /home/ubuntu/scarlet/docker-compose.aws.yml \
  --profile core \
  "$@"
EOF
sudo chmod 755 /usr/local/bin/scarlet-compose
```

Không dùng `docker compose up` trần trên EC2: nó có thể tự nạp override dev. `config --quiet` kiểm tra cấu hình mà không in secret; không chia sẻ toàn bộ đầu ra `config` hoặc `docker inspect`.

## 3. Lệnh thường dùng

```bash
# Kiểm tra cấu hình và trạng thái, kể cả migrate đã thoát
sudo scarlet-compose config --quiet
sudo scarlet-compose ps -a

# Log gần đây
sudo scarlet-compose logs --since=10m --tail=150 api worker nginx

# Theo dõi log; Ctrl+C chỉ dừng xem log
sudo scarlet-compose logs -f --tail=100 api worker

# Kiểm tra cấu hình Nginx đang chạy
sudo scarlet-compose exec -T nginx nginx -t

# Khởi động lại tiến trình, dùng khi chưa đổi code/env
sudo scarlet-compose restart api worker
sudo scarlet-compose restart nginx
```

**Sau khi restart hoặc tạo lại API/frontend, restart Nginx ngay sau đó.** Nginx hiện phân giải tên upstream lúc boot và có thể giữ IP container cũ gây 502.

```bash
# Kiểm tra HTTPS từ ngoài
curl -I "http://$APP_DOMAIN"
curl -I "https://$APP_DOMAIN"

# Health sâu trực tiếp trong API, vẫn đọc được body khi HTTP 503
sudo scarlet-compose exec -T api python - <<'PY'
import httpx
r = httpx.get("http://127.0.0.1:8000/api/v1/health/deep", timeout=15)
print("HTTP:", r.status_code)
print(r.text)
PY
```

`migrate` thoát mã 0 là bình thường. Health sâu có thể `degraded` do 9Router không có trên EC2; cần xem từng check. `healthy` chưa xác nhận SMTP, quyền gọi model hoặc streaming thực tế.

## 4. Sau khi pull trên EC2: quy trình cập nhật

**Pull chỉ đổi source. Code trong API/worker và frontend production nằm trong image: cần build và tạo lại container.** Quy trình đầy đủ có một khoảng bảo trì khi dừng ứng dụng.

### 4.1. Code phải có trên GitHub trước

**LOCAL WSL:** kiểm tra nhánh và diff, commit đúng những file muốn phát hành. Sau khi đã kiểm tra commit:

```bash
cd /home/dmin/scarlet
git status --short
git branch --show-current
git log -1 --oneline
# Phát hành HEAD hiện tại lên main, chỉ khi đây là commit muốn deploy:
git push origin HEAD:main
```

Nếu push bị từ chối vì không fast-forward, đối chiếu lịch sử và giải quyết trước; không force-push để bỏ qua lỗi. Không dùng `git add -A` khi workspace còn secret/tài khoản test hoặc việc khác đang làm.

### 4.2. Pull và xem những gì thay đổi — EC2

```bash
cd /home/ubuntu/scarlet
git branch --show-current
git status --short
```

Nhánh cần là `main`; working tree cần sạch sau khi loại các file server bằng mục 2. Nếu có sửa file tracked trên EC2, lưu/đối chiếu thay đổi trước, không reset hoặc stash mù.

Chạy các lệnh sau trong **cùng phiên SSH** để giữ biến commit cũ:

```bash
PREVIOUS_COMMIT=$(git rev-parse HEAD)
git fetch origin
git diff --stat HEAD..origin/main
git pull --ff-only origin main
git log -1 --oneline
git diff --name-status "$PREVIOUS_COMMIT" HEAD
```

Nếu pull lỗi, dừng. Nếu chỉ đổi tài liệu, không cần build/restart.

### 4.3. Đối chiếu cấu hình trước khi build

```bash
git diff "$PREVIOUS_COMMIT" HEAD -- \
  config .env.example .env.providers.example docker-compose.yml

# Exit code 1 của diff ở đây chỉ nghĩa là hai thư mục khác nhau
diff -ru config deploy-config
```

Đọc các khác biệt và cập nhật `deploy-config/` cho những thay đổi thực sự cần phát hành:

- Giữ domain/chứng chỉ/webroot trong `deploy-config/nginx/nginx.conf`.
- Giữ trạng thái bật/tắt model cho EC2 trong `model_catalog.json`; 9Router/Sub2API trỏ vào máy local không tự xuất hiện trên EC2.
- Đồng bộ prompt và các trường catalog/config mới mà code cần. Ví dụ sau khi đã xem diff: `cp -a config/prompts/. deploy-config/prompts/`.
- Đối chiếu `docker-compose.aws.yml` với Compose gốc nếu có service, mount hoặc command mới.
- Bổ sung biến bắt buộc mới vào `.env` / `.env.providers`; không chép đè hai file này bằng file mẫu.

**Không chạy `cp -a config/. deploy-config/` hàng loạt:** sẽ ghi đè cấu hình production bằng domain/catalog dev.

```bash
sudo scarlet-compose config --quiet
sudo scarlet-compose build api worker migrate web
```

Build lỗi thì dừng; container cũ vẫn có thể tiếp tục phục vụ. MinIO không cần build lại cho mỗi lần đổi code app.

Nếu bản phát hành đổi image PostgreSQL/Redis/LiteLLM, đọc yêu cầu nâng cấp trước rồi mới pull **service tương ứng**. Đặc biệt, đổi major PostgreSQL không thể xử lý bằng cách chỉ pull image và dùng volume cũ.

### 4.4. Bảo trì, backup, migrate, tạo lại container

Chọn lúc ít người dùng; đợi lượt chat đang chạy kết thúc. Dừng Nginx/API/worker để code cũ không ghi dữ liệu trong lúc migrate:

```bash
sudo scarlet-compose stop nginx api worker
```

Tạo backup database; khối con dừng ngay nếu dump lỗi:

```bash
bash <<'BASH'
set -euo pipefail
cd /home/ubuntu/scarlet
umask 077
mkdir -p backups
backup_file="backups/scarlet-before-update-$(date +%Y%m%d-%H%M%S).dump"
sudo scarlet-compose exec -T postgres \
  pg_dump -U scarlet -d scarlet -Fc > "$backup_file"
test -s "$backup_file"
sudo scarlet-compose exec -T postgres pg_restore --list < "$backup_file" >/dev/null
echo "Backup: $backup_file"
BASH
```

Nếu backup lỗi, chưa chạy migration. Backup dạng dump này chỉ chứa PostgreSQL; dữ liệu MinIO/Redis và secret phải backup riêng.

```bash
# Chạy migration từ image vừa build; lệnh cần kết thúc mã 0
sudo scarlet-compose run --rm migrate
```

Migration lỗi thì giữ ứng dụng dừng để xử lý; không bật code mới hoặc tự downgrade schema. Khi migration thành công:

Nếu đã đổi config/key của LiteLLM, tạo lại nó trước khi bật ứng dụng:

```bash
sudo scarlet-compose up -d --no-deps --force-recreate \
  --wait --wait-timeout 180 litellm
```

```bash
# Hạ tầng đang chạy; --no-deps tránh tạo lại nó trong cập nhật app
sudo scarlet-compose up -d --no-deps --force-recreate \
  --wait --wait-timeout 240 api worker web
```

Đợi API/worker/web healthy rồi tạo lại Nginx để nhận IP upstream mới:

```bash
sudo scarlet-compose up -d --no-deps --force-recreate \
  --wait --wait-timeout 120 nginx
sudo scarlet-compose exec -T nginx nginx -t
sudo scarlet-compose ps -a
sudo scarlet-compose logs --since=5m --tail=100 api worker nginx
```

Kiểm tra health sâu theo mục 3, mở domain, đăng nhập và gửi một câu hỏi để kiểm tra streaming. Nếu có thay đổi email, gửi một thư thử theo mục 6. Ghi lại commit đã deploy và đường dẫn backup.

### 4.5. Chọn thao tác theo thay đổi

| Thay đổi | Thao tác |
|---|---|
| Chỉ tài liệu | Pull; không restart |
| Backend / dependency / migration | Build `api worker migrate`; backup, migrate, tạo lại API/worker, restart Nginx |
| Frontend / pnpm lock | Build `web`, tạo lại web, restart Nginx |
| `.env`: SMTP/secret/backend | Tạo lại API/worker; restart không nạp env mới |
| `TURNSTILE_SITE_KEY` | Build lại web vì key nằm trong bundle; tạo lại web và API; restart Nginx |
| `TURNSTILE_SECRET` | Tạo lại API |
| `.env.providers` hoặc config LiteLLM | Tạo lại LiteLLM |
| `LITELLM_MASTER_KEY` | Tạo lại LiteLLM + API/worker để dùng cùng key |
| Catalog/prompt trong `deploy-config/` | Restart API/worker để cùng đọc cấu hình; restart Nginx sau API |
| File Nginx đã mount | `nginx -t`, rồi `nginx -s reload`; nếu upstream vừa đổi IP, restart Nginx |
| Đổi mount/port trong Compose AWS | Tạo lại service liên quan |

Không sinh lại `MASTER_ENCRYPTION_KEY` khi cập nhật: nó dùng để giải mã BYOK đã lưu. Đổi `POSTGRES_PASSWORD` trong env không đổi mật khẩu role của database đã tồn tại.

## 5. Lệnh cập nhật nhanh theo service

```bash
# Frontend sau khi pull
sudo scarlet-compose build web
sudo scarlet-compose up -d --no-deps --force-recreate \
  --wait --wait-timeout 180 web
sudo scarlet-compose restart nginx

# Đổi SMTP/backend env: không cần build
sudo scarlet-compose up -d --no-deps --force-recreate \
  --wait --wait-timeout 180 api worker
sudo scarlet-compose restart nginx

# Đổi provider key
sudo scarlet-compose up -d --no-deps --force-recreate \
  --wait --wait-timeout 180 litellm

# Nginx config, khi upstream không đổi
sudo scarlet-compose exec -T nginx nginx -t
sudo scarlet-compose exec -T nginx nginx -s reload
```

`restart` khởi động lại container hiện có. `up --force-recreate` tạo container từ image và env hiện tại. `build` tạo image mới từ source. Xem [Docker Compose up](https://docs.docker.com/reference/cli/docker/compose/up/).

## 6. Gmail SMTP và email xác thực

Sửa **file trên EC2**: `nano /home/ubuntu/scarlet/.env`. Ví dụ:

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=sender@gmail.com
SMTP_PASSWORD='MAT_KHAU_UNG_DUNG_KHONG_CO_KHOANG_TRANG'
SMTP_TLS=true
MAIL_FROM=Scarlet <sender@gmail.com>
SMTP_TIMEOUT_S=30
```

Dùng mật khẩu ứng dụng Google, tài khoản đã bật xác minh 2 bước. Mật khẩu đã chia sẻ trong ảnh cần thu hồi và thay mới. [Hướng dẫn Google](https://support.google.com/accounts/answer/185833?hl=vi). `mailpit:1025` giữ thư để test dev, không gửi tới hộp thư thật.

Sau khi sửa: tạo lại API/worker theo mục 5. Đổi file trong IDE local không đổi env trên EC2.

### 6.1. Kiểm tra cấu hình đã nạp, không in mật khẩu

```bash
sudo scarlet-compose exec -T api python - <<'PY'
from app.config.settings import settings as s
p = s.SMTP_PASSWORD.get_secret_value()
print("SMTP_HOST:", s.SMTP_HOST)
print("SMTP_PORT:", s.SMTP_PORT)
print("SMTP_USER:", s.SMTP_USER)
print("SMTP_TLS:", s.SMTP_TLS)
print("MAIL_FROM:", s.MAIL_FROM)
print("Password length:", len(p))
print("Password contains whitespace:", any(c.isspace() for c in p))
PY
```

### 6.2. Gửi một thư thử tới chính SMTP_USER

Lệnh này thực sự gửi email; không tạo token hoặc thay trạng thái tài khoản:

```bash
sudo scarlet-compose exec -T api python - <<'PY'
import smtplib
import ssl
from email.message import EmailMessage
from app.config.settings import settings as s
m = EmailMessage()
m["Subject"] = "[Scarlet] Kiem tra SMTP"
m["From"] = s.MAIL_FROM
m["To"] = s.SMTP_USER
m.set_content("Thu kiem tra gui email tu Scarlet tren EC2.")
try:
    print("1. Ket noi SMTP...", flush=True)
    with smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT, timeout=30) as smtp:
        print("2. STARTTLS...", flush=True)
        smtp.starttls(context=ssl.create_default_context())
        print("3. Dang nhap...", flush=True)
        smtp.login(s.SMTP_USER, s.SMTP_PASSWORD.get_secret_value())
        print("4. Gui thu...", flush=True)
        refused = smtp.send_message(m)
        print("Ket qua:", refused or "SMTP da chap nhan thu.")
except Exception as error:
    print("LOI:", type(error).__name__, str(error))
PY
```

`535 / SMTPAuthenticationError`: kiểm tra mật khẩu ứng dụng và user. Timeout: xem bước đang kẹt, kiểm tra DNS/outbound TCP 587. SMTP chấp nhận thư chưa đồng nghĩa thư đã vào Inbox; tìm tiêu đề trong All Mail/Spam.

### 6.3. Gửi lại xác thực cho tài khoản đã đăng ký

`register 200` không chứng minh đã gửi thư: đăng ký lại email đã tồn tại trả cùng response nhưng không gửi. SMTP lỗi khi đăng ký/gửi lại cũng có thể vẫn trả 200, kèm lỗi trong log. Restart container không tự gửi lại email cũ.

Thay `EMAIL_DA_DANG_KY` bằng **email tài khoản nhận thư**, có thể khác SMTP_USER:

```bash
sudo scarlet-compose exec -T postgres psql -U scarlet -d scarlet -c \
  "SELECT email, status, email_verified_at FROM users
   WHERE email = 'EMAIL_DA_DANG_KY' AND deleted_at IS NULL;"
```

| Trạng thái | Xử lý |
|---|---|
| `pending_email` | Gửi lại thư xác thực |
| `pending_approval` | Đã xác thực; cần admin duyệt |
| `active` | Đã hoạt động; không gửi lại xác thực |
| Không có hàng | Kiểm tra email hoặc đăng ký tài khoản mới |

```bash
sudo scarlet-compose exec -T api python - <<'PY'
import httpx
r = httpx.post(
    "http://127.0.0.1:8000/api/v1/auth/resend-verification",
    json={"email": "EMAIL_DA_DANG_KY"},
    timeout=60,
)
print("HTTP:", r.status_code)
print(r.text)
PY
sudo scarlet-compose logs --since=2m --tail=150 api
```

Tìm `POST /api/v1/auth/resend-verification` và lỗi `gui email xac thuc that bai`. Log chỉ có `GET /health` không cho biết đã có thao tác gửi email.

## 7. Gỡ rate limit cho đúng đối tượng

Lấy IP từ dòng `rl:ip:register:…` hoặc `rl:ip:resend-verification:…` trong log, không lấy IP EC2 hay container. Các route này có giới hạn riêng.

```bash
sudo scarlet-compose exec -T api \
  python -m app.cli reset-rate-limit ip register IP_TRONG_LOG

sudo scarlet-compose exec -T api \
  python -m app.cli reset-rate-limit ip resend-verification IP_TRONG_LOG

sudo scarlet-compose exec -T api \
  python -m app.cli reset-rate-limit ip forgot-password IP_TRONG_LOG
```

Lệnh xóa bộ đếm hiện tại, không tắt chính sách 3 lượt/giờ; không cần restart. Nếu gửi lại bằng lệnh nội bộ mục 6.3, IP ghi nhận có thể là `127.0.0.1` — vẫn dùng IP thực tế trong log.

## 8. Backup, restore và khôi phục khi cập nhật lỗi

Tạo dump bằng khối backup mục 4.4; dùng được khi ứng dụng đang chạy, nhưng bảo trì giúp tránh ghi thêm dữ liệu trong lúc chuẩn bị migration.

**LOCAL WSL**, tải một file backup đã tạo:

```bash
scp -i ~/.ssh/scarlet-ec2.pem \
  ubuntu@ELASTIC_IP:/home/ubuntu/scarlet/backups/TEN_FILE.dump ./
```

Giữ bản sao ngoài EC2 của secret, `deploy-config/`, Compose AWS, Dockerfile production, wrapper, cấu hình Certbot; backup/snapshot volume MinIO và Redis riêng. Giữ project name `scarlet` và các named volume `pgdata`, `redisdata`, `miniodata`.

**Restore thay dữ liệu database đích.** Chỉ dùng khi đã chọn đúng backup, có backup dữ liệu đích và đang trong bảo trì:

```bash
sudo scarlet-compose stop nginx api worker
sudo scarlet-compose exec -T postgres \
  pg_restore -U scarlet -d scarlet --clean --if-exists \
    --no-owner --exit-on-error < backups/TEN_FILE.dump
```

Restore thành công rồi dùng code tương thích với schema của backup. Nếu triển khai code mới hơn, chạy migration thích hợp trước khi bật lại ứng dụng. Không tự `alembic downgrade` hoặc quay code cũ khi chưa biết schema tương thích.

Build lỗi trước khi dừng: giữ container cũ và sửa build. Migration lỗi: giữ ứng dụng dừng, đọc lỗi. Container mới lỗi sau migration: kiểm tra log, secret/config và mức tương thích schema; backup là điểm khôi phục, không tự động rollback.

Không dùng `down -v`, `docker volume prune` hoặc xóa thư mục dữ liệu khi cập nhật. `restart` không cập nhật code mới.

## 9. HTTPS và gia hạn

Nginx cần mount cả `/etc/letsencrypt` và `/var/www/certbot`; HTTP port 80 có location `/.well-known/acme-challenge/` phục vụ webroot trước redirect.

```bash
sudo /snap/bin/certbot certificates
sudo /snap/bin/certbot reconfigure \
  --cert-name "$APP_DOMAIN" \
  --authenticator webroot \
  --webroot-path /var/www/certbot
```

Nếu chưa có hook reload sau gia hạn:

```bash
sudo mkdir -p /etc/letsencrypt/renewal-hooks/deploy
sudo tee /etc/letsencrypt/renewal-hooks/deploy/scarlet-nginx >/dev/null <<'EOF'
#!/bin/sh
/usr/local/bin/scarlet-compose exec -T nginx nginx -t &&
/usr/local/bin/scarlet-compose exec -T nginx nginx -s reload
EOF
sudo chmod 755 /etc/letsencrypt/renewal-hooks/deploy/scarlet-nginx

sudo /snap/bin/certbot renew --dry-run --run-deploy-hooks
systemctl list-timers --all | grep -i certbot
```

Chỉ đánh dấu gia hạn hoạt động sau khi dry-run thành công. [Tài liệu Certbot](https://eff-certbot.readthedocs.io/en/stable/using.html#modifying-the-renewal-configuration-of-existing-certificates).

## 10. MinIO: giữ image tự build đã chạy được

Server đã báo image `scarlet-minio:RELEASE.2025-10-15T17-29-55Z` healthy. Override phải dùng image này, không dùng `minio/minio:latest` đang pull lỗi.

Trong **block minio hiện có** của Compose AWS:

```yaml
  minio:
    image: scarlet-minio:RELEASE.2025-10-15T17-29-55Z
    build:
      context: ./deploy-minio
    pull_policy: never
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY}
    healthcheck:
      test:
        - CMD-SHELL
        - 'mc alias set health http://127.0.0.1:9000 "$$MINIO_ROOT_USER" "$$MINIO_ROOT_PASSWORD" >/dev/null && mc ready health'
      interval: 15s
      timeout: 5s
      retries: 5
```

File `deploy-minio/Dockerfile` cần chứa cả server và `mc`:

```dockerfile
FROM golang:1.24.8-bookworm AS build
ENV CGO_ENABLED=0
ENV GOBIN=/out
ENV GOMAXPROCS=2
ENV GOFLAGS=-p=2
RUN go install github.com/minio/minio@RELEASE.2025-10-15T17-29-55Z
RUN go install github.com/minio/mc@RELEASE.2025-08-13T08-35-41Z

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /out/mc /usr/local/bin/mc
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
```

Chỉ build lại khi mất image, dựng server mới hoặc chủ động đổi phiên bản:

```bash
sudo scarlet-compose build minio
sudo scarlet-compose up -d --no-deps --wait --wait-timeout 180 minio

# Tạo bucket một lần; có rồi thì giữ nguyên
sudo scarlet-compose exec -T minio sh -c \
  'mc alias set scarlet http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc mb --ignore-existing scarlet/scarlet'
```

Không chạy pull toàn bộ stack khi có image tự build này. Với lần dựng ban đầu, pull `postgres redis litellm`, build MinIO, rồi khởi động bốn service đó trước migration.

[Release MinIO đã dùng](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z) hướng dẫn build source. Các phiên bản trên ghi lại cấu hình đã triển khai, không cam kết là các bản mới nhất hoặc còn được upstream duy trì.

## 11. Tạo admin đầu tiên

Sau khi đăng ký và xác thực email, mở psql:

```bash
sudo scarlet-compose exec postgres psql -U scarlet -d scarlet
```

Thay email rồi chạy trong psql:

```sql
BEGIN;
UPDATE users
SET role = 'admin',
    status = 'active',
    email_verified_at = COALESCE(email_verified_at, now()),
    approved_at = COALESCE(approved_at, now())
WHERE email = 'EMAIL_ADMIN'
  AND deleted_at IS NULL
RETURNING id, email, role, status;
```

Đúng một tài khoản của mình: `COMMIT;`. Sai hoặc không có hàng: `ROLLBACK;`. Thoát bằng `\q`; đăng xuất/đăng nhập lại để nhận quyền mới. Sau khi có admin, duyệt người dùng qua giao diện.

## 12. Tóm tắt dựng server mới

1. EC2 Ubuntu 24.04 x86_64, public subnet; Security Group SSH 22 từ IP quản trị `/32`, HTTP 80 và HTTPS 443 từ Internet. Gắn Elastic IP.
2. Trỏ A record app và artifact vào Elastic IP. Dùng IP đã gắn để SSH; không coi IP từng xuất hiện trong log là Elastic IP đã xác nhận.
3. Cài Docker Engine, Compose plugin (cần ≥ 2.24.4 cho `!override`) và Certbot. Clone nhánh `main`.
4. Tạo secret bằng `openssl rand -hex 32` cho lần dựng database mới; `DATABASE_URL` và `POSTGRES_PASSWORD` phải khớp. Với restore database cũ, giữ master encryption key cũ. Điền domain, SMTP, Turnstile và provider key.
5. Tạo bộ file production mục 2. Frontend phải có Dockerfile copy source, `pnpm build`, rồi serve `dist` bằng Nginx; cổng nội bộ 5173 và SPA fallback. Turnstile Site Key truyền qua build args.
6. Copy `config/` sang `deploy-config/` **chỉ lần dựng mới**. Chỉnh domain/chứng chỉ/webroot của Nginx, giữ các thiết lập SSE `proxy_buffering off`, `proxy_cache off`, `proxy_read_timeout 3600s`, `chunked_transfer_encoding on` cùng `proxy_http_version 1.1` và `proxy_set_header Connection ''`; chỉ bật provider thực sự có trên EC2.
7. Compose AWS: publish Nginx 80/443, gỡ publish LiteLLM bằng `ports: !reset []`, mount `deploy-config` cho API/worker và config tương ứng cho LiteLLM/Nginx; Ollama `profiles: !override [local-llm]`. Tạo wrapper mục 2.
8. Lấy chứng chỉ cho app + artifact bằng `certbot certonly --standalone` khi chưa chạy Nginx. Sau khi app chạy, chuyển gia hạn webroot theo mục 9.
9. Build `api worker migrate web minio`; pull `postgres redis litellm`; `up -d --wait postgres redis minio litellm`; `run --rm migrate`; `up -d --wait --wait-timeout 240`. Tạo bucket mục 10.
10. Kiểm tra health, HTTPS, gửi email thử, xác thực/duyệt admin và thử chat streaming. Chỉ đánh dấu hoàn tất những mục có kết quả kiểm tra.

Cài Docker theo [hướng dẫn Ubuntu chính thức](https://docs.docker.com/engine/install/ubuntu/). Free Tier mới sử dụng credit; nhãn eligible không đồng nghĩa miễn phí vô hạn: xem [quy định EC2 Free Tier](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html).

## 13. Bảng tra lỗi

| Lỗi | Việc cần kiểm tra |
|---|---|
| SSH timeout | IP đích, instance/status checks, source IP rule 22, route Internet Gateway |
| 502 sau cập nhật | API/web healthy rồi restart Nginx để nhận upstream mới |
| 403 khi POST/login | `PUBLIC_BASE_URL` đúng origin HTTPS, không dấu `/` cuối |
| 429 đăng ký/gửi lại | Mục 7, gỡ đúng IP và đúng route |
| Register 200 nhưng không có thư | Email có tồn tại? Dùng resend, xem status và log mục 6 |
| Log chỉ GET /health | Chưa thấy yêu cầu gửi thư trong khoảng thời gian lấy log |
| SMTP 535 | User/mật khẩu ứng dụng, xác minh 2 bước |
| MinIO pull denied | Override dùng image tự build mục 10 |
| No such image PostgreSQL/Redis sau pull bị ngắt | Tải lại đúng service; đọc lỗi pull đầu tiên |
| Frontend vẫn giao diện cũ | Source đã có trên main? Build đúng Dockerfile.aws? Tạo lại web, restart Nginx, reload trình duyệt |
| Catalog/prompt vẫn cũ | File thực tế nằm trong deploy-config, không phải config vừa pull |
| Migrate lỗi | Dừng cập nhật, đọc log, kiểm tra backup và schema; không tự bật code mới |

## 14. Nhật ký deploy

Mỗi lần deploy ghi: thời gian, commit trước/sau, config/env đã đổi (chỉ tên biến), đường dẫn backup, kết quả migration, health, HTTPS, đăng nhập, SMTP khi liên quan và chat streaming. Không ghi key, mật khẩu hoặc token vào tài liệu.

Runbook được tạo local; việc push runbook và các thay đổi code tiếp theo là bước phát hành riêng. Xem thêm [README](README.md), [runbook thêm provider](docs/RUNBOOK-them-provider.md).
