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

# 5. Khong KHOA RIENG lot vao repo (B-76).
# Lenh 4 chi biet mau `sk-...` cua API key, khong bat duoc PEM: hai file mkcert
# `localhost+3*.pem` nam o GOC REPO tu T-0.8 toi T-1.6 ma khong lenh nao keu.
#
# Hai chi tiet cua mau, ca hai deu da lam do phep kiem nay khi viet sai:
#  - Doi DU vanh PEM (nam dau gach hai ben) chu khong chi ba chu "BEGIN PRIVATE
#    KEY": van ban MO TA cai bay nay — chinh dong B-76 trong docs/tasks.md —
#    viet ba chu do trong dau nhay, va mot canh bao gia moi lan chay la mot
#    lenh kiem se bi tat.
#  - `[A-Z ]*` chu khong phai `.*`: dang `.*` khop CHINH DONG NAY khi grep quet
#    file nay, tuc bao dong gia vinh vien khong lien quan gi toi khoa that.
out5=$(git ls-files -z | xargs -0 grep -lE -- "-----BEGIN [A-Z ]*PRIVATE KEY-----" 2>/dev/null)
check "Khoa rieng trong file git dang theo doi" "$out5"

if [ "$status" -ne 0 ]; then
  echo "check-hardcode: THAT BAI"
  exit 1
fi

echo "check-hardcode: OK"
