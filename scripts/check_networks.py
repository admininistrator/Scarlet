"""Lớp 1 của §12.2 trên cấu hình compose ĐÃ GỘP — T-6.5, thay grep ③ của
HUONG-DAN-AGENT §8.3 (B-49, B-117).

Grep trên `docker-compose.yml` trả rỗng khi đúng **và** khi sai mà thụt đầu dòng
lệch, và không thấy `docker-compose.override.yml`. Ở đây đọc
`docker compose config --format json` — thứ Docker thật sự chạy — và đòi đối
tượng phải TỒN TẠI: thiếu `fetcher` / `sandbox` là đỏ, không phải "xanh rỗng".

`env_file` đã được compose gộp vào `environment`, nên "không `env_file`" nghĩa
là `fetcher` / `sandbox` không có biến môi trường nào từ cấu hình (C27).
"""

from __future__ import annotations

import json
import subprocess
import sys

COMPOSE = ["docker", "compose", "--profile", "core", "--profile", "tools"]

# §12.2 + NQ-144 (Q-P6-2): service -> tập mạng phải có ĐÚNG.
EXPECTED = {
    "fetcher": {"egress"},
    "worker": {"internal", "egress"},
    "api": {"internal"},
    "sandbox": set(),
}
# ADR-09 + T-7.2: service vắng ở đây thì KHÔNG được có `network_mode`.
NETWORK_MODE = {"sandbox": "none"}


def main() -> int:
    raw = subprocess.run(
        [*COMPOSE, "config", "--format", "json"], check=True, capture_output=True, text=True
    ).stdout
    services = json.loads(raw)["services"]
    errors: list[str] = []
    for name, nets in EXPECTED.items():
        if name not in services:
            errors.append(f"{name}: khong co trong cau hinh da gop")
            continue
        svc = services[name]
        actual = set(svc.get("networks") or {})
        mode = NETWORK_MODE.get(name)
        if svc.get("network_mode") != mode or actual != nets:
            errors.append(
                f"{name}: mang {sorted(actual)} / network_mode "
                f"{svc.get('network_mode')!r}, phai la {sorted(nets)} / {mode!r}"
            )
    for name in ("fetcher", "sandbox"):
        for key in ("env_file", "environment", "ports"):
            if services.get(name, {}).get(key):
                errors.append(f"{name}: co `{key}` — lop 1 khong duoc thay secret / mo cong")
    for line in errors:
        print(f"check-networks: FAIL {line}")
    if not errors:
        print("check-networks: OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
