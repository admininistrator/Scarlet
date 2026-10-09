# T-7.2 — service `sandbox` (§13.3, ADR-09). Context là `./sandbox` + `.dockerignore`,
# không gốc repo (B-364). Không có gói `app` của backend ⇒ `import app.config` là
# `ModuleNotFoundError`, và compose không cấp `.env` (C27).
FROM python:3.12-slim

# `tini` làm PID 1 gặt zombie (T-7.1: 5 zombie sau 5 lượt khi PID 1 là python).
# `setpriv` (util-linux) có sẵn — T-7.3 dùng nó hạ code xuống uid 65534 mỗi lượt.
# `/run/sandbox` thuộc root 0755: volume socket mới chép đúng quyền này (NQ-147).
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sandbox && chmod 0755 /run/sandbox

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# `--chmod`: Edit qua `\\wsl.localhost` làm mất bit thực thi của tệp nguồn.
COPY --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /work

# Không `USER`: server là root (chỉ SETUID/SETGID, compose), code là 65534 (Q-P7-1).
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# T-7.3 thay bằng server UDS (`server.py`) và đổi healthcheck sang `connect` socket.
CMD ["sleep", "infinity"]
