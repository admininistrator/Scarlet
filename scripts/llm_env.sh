#!/usr/bin/env bash
# Nạp `.env` vào môi trường rồi trỏ LITELLM_BASE_URL sang cổng LiteLLM đã
# publish ra host. Dùng bằng `source scripts/llm_env.sh` trước khi chạy
# `scripts/record_llm_fixtures.py` hoặc `scripts/smoke_llm_stream.py` từ WSL.
#
# Vì sao không `source .env` thẳng: `.env` đang có CRLF và có dòng
# `MAIL_FROM=Scarlet <no-reply@...>` — bash hiểu `<` là chuyển hướng đầu vào.
# Vì sao phải đổi base URL: `.env` ghi `http://litellm:4000/v1`, tên service
# chỉ phân giải được BÊN TRONG network `internal` (C17/C45). Script chạy ở
# host nên phải đi qua cổng `docker-compose.yml` publish.
#
# Đây KHÔNG phải đường mà app dùng: app đọc biến môi trường do compose nạp
# (§19.2 L3). File này chỉ phục vụ script chạy tay.

_scarlet_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

while IFS= read -r _line; do
  _line="${_line%$'\r'}"
  case "$_line" in
    ''|'#'*) continue ;;
  esac
  [[ "$_line" == *=* ]] || continue
  _name="${_line%%=*}"
  [[ "$_name" =~ ^[A-Z][A-Z0-9_]*$ ]] || continue
  _value="${_line#*=}"
  _value="$(printf '%s' "$_value" | sed 's/[[:space:]]\+#.*$//; s/[[:space:]]*$//')"
  export "$_name=$_value"
done < "$_scarlet_root/.env"

export LITELLM_BASE_URL="${SCARLET_LITELLM_HOST_URL:-http://localhost:4000/v1}"

unset _line _name _value _scarlet_root
