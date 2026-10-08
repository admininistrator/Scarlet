# T-6.5 — service `fetcher` (§12). Context là `./fetcher`; `ssrf.py` tới từ
# context phụ `ssrf` (= `backend/app/tools`, khai ở `docker-compose.yml`) — MỘT
# nguồn với backend, không chép tay (B-208). Không dùng gốc repo làm context
# (B-364: kéo theo `node_modules`, `.venv`).
FROM python:3.12-slim

# B-382: `iptables` cho rào lớp 1 trong `entrypoint.sh`; `setpriv` (util-linux,
# có sẵn) bỏ quyền trước khi chạy server. T-6.6: `tini` làm PID 1 (chạy SAU
# `setpriv`) để dọn tiến trình Chromium mồ côi.
RUN apt-get update && apt-get install -y --no-install-recommends iptables tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 fetcher

WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# T-6.6 — CHỈ Chromium, bản "headless shell" (không Firefox / WebKit, không bản có
# giao diện): image `mcr.microsoft.com/playwright/python` đủ ba trình duyệt là
# 1014 MB nén (đo 2026-10-07). Cùng bản với client `playwright` ở requirements —
# lệnh `install` của chính gói ấy tải đúng bản trình duyệt nó được build cùng.
# `--with-deps` cài thư viện hệ thống bằng apt (cần root — chỉ lúc build).
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN playwright install --with-deps --only-shell chromium && rm -rf /var/lib/apt/lists/*

# Chỉ `ssrf.py`, không cả thư mục: `web_search.py` bên cạnh import `app.config`.
COPY --from=ssrf ssrf.py /opt/ssrf/ssrf.py
COPY server.py test_server.py ./
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

# Không có gói `app` trong image ⇒ `import app.config` là `ModuleNotFoundError`:
# `ssrf.py` mà import lại `Settings` thì `fetcher` không boot (đúng ý — A4 nghĩa
# là `fetcher` phải đòi `.env`, mà `.env` là thứ lớp 1 giấu đi).
ENV PYTHONPATH=/opt/ssrf \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Không `USER`: entrypoint cần root + NET_ADMIN để dựng rào, rồi tự hạ xuống
# `fetcher` (uid 1000) không còn cap nào — mọi lệnh (`CMD`, `compose run`) đi qua.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
