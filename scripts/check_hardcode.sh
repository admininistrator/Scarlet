#!/usr/bin/env bash
# Bốn lệnh kiểm rò rỉ hardcode/secret của KE-HOACH.md §19.4.
set -uo pipefail

status=0

check() {
  local name="$1"
  local output="$2"
  if [ -n "$output" ]; then
    echo "FAIL [$name]:"
    echo "$output"
    echo "  -> $(echo "$output" | wc -l) dong vi pham"
    status=1
  fi
}

# 1. API khong duoc goi model/tool truc tiep (§5.3)
out1=$(grep -rnE "litellm|openai|anthropic|AsyncClient\(" backend/app/api/ 2>/dev/null)
check "API goi model/tool truc tiep" "$out1"

# 2. Khong ten model literal ngoai config layer.
# Loai tru tests/ va app/config/ (cam bay T-0.9: khong loai se bao dong gia moi lan).
out2=$(grep -rnE "\"(deepseek|claude|gpt|gemini)-[a-z0-9.-]+\"" backend/app/ --include=*.py 2>/dev/null \
  | grep -v "app/config/" | grep -v "tests/")
check "Ten model literal ngoai config" "$out2"

# 3. Khong mau literal trong component React
out3=$(grep -rnE "#[0-9a-fA-F]{6}|rgb\(" frontend/src/components/ 2>/dev/null)
check "Mau literal trong component" "$out3"

# 4. Khong secret lot vao repo.
# Chi quet file git dang theo doi (B-41): .env bi gitignore nhung chua key that
# hop le, quet ca cay thu muc se bao dong gia tren moi may dev.
out4=$(git ls-files -z | xargs -0 grep -nE "sk-[a-zA-Z0-9]{20,}" 2>/dev/null)
check "Secret trong file git dang theo doi" "$out4"

if [ "$status" -ne 0 ]; then
  echo "check-hardcode: THAT BAI"
  exit 1
fi

echo "check-hardcode: OK"
