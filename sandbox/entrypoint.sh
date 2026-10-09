#!/bin/sh
# T-7.2 — NQ-147 (Q-P7-1): danh tính server ≠ danh tính code.
#
# Container khởi động root nhưng chỉ còn SETUID/SETGID (compose: `cap_drop: [ALL]`
# + `cap_add`, `no-new-privileges`). Server chạy root, KHÔNG bao giờ chạy code
# trong tiến trình của nó; mỗi lượt `exec` hạ code xuống uid 65534 bằng `setpriv`
# (T-7.3). Thư mục socket phải thuộc root 0755 để code không thay được tệp socket
# (T-7.1: cùng uid ⇒ code dựng listener giả). Volume cũ mang chủ khác ⇒ `chown`
# không có CAP_CHOWN thì hỏng ⇒ `set -e` dừng container (đóng, không mở).
set -eu

chown root:root /run/sandbox
chmod 0755 /run/sandbox

exec tini -- "$@"
