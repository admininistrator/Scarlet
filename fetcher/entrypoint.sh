#!/bin/sh
# B-382 / NQ-145 — lớp 1 của §12.2 cho cả cổng publish của host.
#
# Mạng `egress` giấu TÊN service, nhưng không giấu host: đo 2026-10-07/08,
# `host.docker.internal` (192.168.65.254) và gateway của bridge mở 4000
# (LiteLLM), 5432 (Postgres, dù publish 127.0.0.1), 20128 (9Router), 443. Ở đây
# netns của `fetcher` từ chối mọi kết nối RA tới dải riêng / loopback / link-local
# / CGNAT / multicast — kể cả khi lớp 2–4 vỡ, và kể cả request con của trình
# duyệt ở T-6.6. Chiều VÀO (`worker` gọi `/fetch`) đi qua ESTABLISHED. DNS của
# Docker là 127.0.0.11 (`lo`) — đo: vẫn resolve sau khi chặn.
#
# Chạy bằng root với NET_ADMIN (compose: `cap_drop: [ALL]` + bốn cap — SETPCAP
# để bỏ được bounding set), rồi `setpriv` bỏ hết cap kể cả bounding set (cộng
# `no-new-privileges`) trước khi chạy server: code đọc trang
# web không bao giờ cầm NET_ADMIN. Lỗi bất kỳ ⇒ `set -e` dừng container (đóng,
# không mở).
set -eu

for cmd in iptables ip6tables; do
  "$cmd" -F OUTPUT
  "$cmd" -A OUTPUT -o lo -j ACCEPT
  "$cmd" -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
done
for net in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 \
           172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
  iptables -A OUTPUT -d "$net" -j REJECT
done
for net in ::1/128 ::ffff:0:0/96 fc00::/7 fe80::/10 ff00::/8; do
  ip6tables -A OUTPUT -d "$net" -j REJECT
done

# T-6.6 — `tini` làm PID 1, đã ở uid 1000 không cap nào: tiến trình Chromium mồ
# côi (driver Playwright dừng khi khởi lại browser, `uvicorn --reload`) về PID 1,
# và uvicorn không dọn chúng ⇒ zombie (đo: 3 sau 50 lượt). Không dùng `init: true`
# của compose: `docker-init` là PID 1 ROOT giữ NET_ADMIN suốt đời container.
exec setpriv --reuid=fetcher --regid=fetcher --init-groups \
  --inh-caps=-all --bounding-set=-all -- tini -- "$@"
