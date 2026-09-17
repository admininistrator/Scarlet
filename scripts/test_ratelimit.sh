#!/usr/bin/env bash
# Bon dong DoD cua T-2.9 do tren STACK THAT, qua Nginx, voi Redis that (§10.6).
#
# KH tham chieu: §10.6 · tasks.md T-2.9 DoD, B-85, NQ-49.
#
#     bash scripts/test_ratelimit.sh                  # model mac dinh catalog
#     MODEL_ID=ol-qwen-small bash scripts/...         # model cuc bo => 0 USD
#
# ┌───────────────────────────────────────────────────────────────────────────┐
# │  VI SAO CAN SCRIPT NAY KHI DA CO pytest                                   │
# └───────────────────────────────────────────────────────────────────────────┘
#
# `tests/core/test_ratelimit.py` CO Y khong dich hai script Lua sang Python:
# mot ban dich la mot ban hien thuc THU HAI, va test chay tren ban dich se xanh
# ca khi ban Lua that da hong. Nen hai thu duoi day khong co phep kiem tu dong
# nao, va chi do duoc o day:
#
#   * phep tinh nap lai cua xo (DoD 1 — `Retry-After` la SO GIAY DUNG),
#   * tinh NGUYEN TU cua script giua nhieu KET NOI (DoD 2 — 50 request song
#     song, tong so qua duoc dung bang han muc).
#
# Cung li le voi `scripts/test_idempotency.sh` cua S5 va `test_resume.py` cua
# S3: do tren duong ma nguoi dung that di. Xem B-149.
#
# ┌───────────────────────────────────────────────────────────────────────────┐
# │  MOT LUU Y KHI DOC KET QUA                                                │
# └───────────────────────────────────────────────────────────────────────────┘
#
# Mot POST toi `.../messages` di qua HAI han muc, theo thu tu:
#
#   1. token bucket theo user (dependency)     -> 429 RATE_LIMITED
#   2. tran dong thoi MAX_CONCURRENT_STREAMS   -> 429 TOO_MANY_STREAMS
#
# Nen trong DoD 1 va 2, phan lon request "qua duoc xo" van tra 429 — nhung la
# TOO_MANY_STREAMS, tuc chung DA tieu mot token. Do la hanh vi dung: han muc
# dem LUOT THU, cung li le da ghi o lop theo IP ("mot lan do email that bai
# cung la mot lan do"). Vi vay moi phep dem duoi day phan loai theo MA LOI,
# khong phai theo ma HTTP.
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose --profile core --profile tools"
# `tr -d` khong phai thua: `.env` tren may dev nay luu CRLF (B-146).
BASE_URL="$(grep -E '^PUBLIC_BASE_URL=' .env | cut -d= -f2- | tr -d '\r')"
TRAN_CHAT="$(grep -E '^RATE_LIMIT_CHAT_PER_MIN=' .env | cut -d= -f2- | tr -d '\r')"
TRAN_GHE="$(grep -E '^MAX_CONCURRENT_STREAMS=' .env | cut -d= -f2- | tr -d '\r')"
MODEL_ID="${MODEL_ID:-}"
EMAIL="dod-t29-$(date +%s)@scarlet.example"

so_loi=0
ok() { echo "  OK   $*"; }
fail() {
  echo "  FAIL $*"
  so_loi=$((so_loi + 1))
}

psql_() { $COMPOSE exec -T postgres psql -U scarlet -d scarlet -tAq -c "$1"; }
redis_() { $COMPOSE exec -T redis redis-cli "$@" | tr -d '\r'; }

# Mot POST toi `.../messages`. In "<ma http>|<ma loi hoac ->|<retry-after>".
post() { # $1=conversation_id  $2=noi dung
  local body="{\"content\":\"$2\""
  if [ -n "$MODEL_ID" ]; then body="$body,\"model_id\":\"$MODEL_ID\""; fi
  body="$body}"

  local tmp head
  tmp="$(mktemp)"
  head="$(mktemp)"
  local ma
  ma="$(curl -sk -o "$tmp" -D "$head" -w '%{http_code}' \
    -X POST "$BASE_URL/api/v1/conversations/$1/messages" \
    -H "X-User-Id: $USER_ID" -H 'Content-Type: application/json' \
    -H "Idempotency-Key: $(cat /proc/sys/kernel/random/uuid)" -d "$body")"
  local code retry
  code="$(sed -n 's/.*"code":"\([^"]*\)".*/\1/p' "$tmp")"
  retry="$(grep -i '^retry-after:' "$head" | tr -d '\r' | cut -d' ' -f2- || true)"
  echo "$ma|${code:--}|${retry:--}|$(sed -n 's/.*"assistant_message_id":"\([^"]*\)".*/\1/p' "$tmp")"
  rm -f "$tmp" "$head"
}

xoa_xo() { redis_ DEL "rl:user:chat:$USER_ID" >/dev/null; }
xoa_ghe() { redis_ DEL "rl:streams:$USER_ID" >/dev/null; }

echo "== chuan bi =="
USER_ID="$(psql_ "INSERT INTO users (email, password_hash, status) VALUES ('$EMAIL','khong-phai-hash-that','active') RETURNING id;" | tr -d ' ')"
CONV="$(psql_ "INSERT INTO conversations (user_id) VALUES ('$USER_ID') RETURNING id;" | tr -d ' ')"
echo "  user=$USER_ID  conv=$CONV  model=${MODEL_ID:-<mac dinh catalog>}"
echo "  RATE_LIMIT_CHAT_PER_MIN=$TRAN_CHAT  MAX_CONCURRENT_STREAMS=$TRAN_GHE"

# ── DoD 1: 25 request trong 1 phut -> request 21 tra 429 + Retry-After dung ─
echo
echo "== DoD 1: $((TRAN_CHAT + 5)) request chat trong 1 phut =="
xoa_xo
xoa_ghe
dong_dau_bi_chan=0
retry_dau=""
for i in $(seq 1 $((TRAN_CHAT + 5))); do
  R="$(post "$CONV" "1+1 bang may?")"
  ma="$(echo "$R" | cut -d'|' -f1)"
  code="$(echo "$R" | cut -d'|' -f2)"
  retry="$(echo "$R" | cut -d'|' -f3)"
  if [ "$i" -le 3 ] || [ "$i" -ge $((TRAN_CHAT - 1)) ]; then
    echo "  #$i -> $ma $code retry-after=$retry"
  fi
  if [ "$code" = "RATE_LIMITED" ] && [ "$dong_dau_bi_chan" = "0" ]; then
    dong_dau_bi_chan="$i"
    retry_dau="$retry"
  fi
done

if [ "$dong_dau_bi_chan" = "$((TRAN_CHAT + 1))" ]; then
  ok "request dau tien bi RATE_LIMITED la #$dong_dau_bi_chan (= tran + 1)"
else
  fail "request dau tien bi RATE_LIMITED la #$dong_dau_bi_chan, cho doi #$((TRAN_CHAT + 1))"
fi
# Xo nap lai `TRAN_CHAT` token moi 60 s => 1 token moi 60/TRAN_CHAT giay.
CHO_DOI=$((60 / TRAN_CHAT))
if [ "$retry_dau" = "$CHO_DOI" ]; then
  ok "Retry-After = $retry_dau s = 60/$TRAN_CHAT (dung mot token)"
else
  fail "Retry-After = $retry_dau, cho doi $CHO_DOI"
fi
echo "  xo trong redis: $(redis_ HGETALL "rl:user:chat:$USER_ID" | tr '\n' ' ')"
echo "  TTL xo: $(redis_ TTL "rl:user:chat:$USER_ID")"

# ── DoD 2: 50 request SONG SONG -> dung `TRAN_CHAT` cai qua duoc xo ────────
echo
echo "== DoD 2: 50 request SONG SONG (chung minh Lua nguyen tu) =="
xoa_xo
xoa_ghe
THU_MUC="$(mktemp -d)"
for i in $(seq 1 50); do
  post "$CONV" "1+1 bang may?" >"$THU_MUC/$i" &
done
wait
qua_xo=0
bi_xo_chan=0
for i in $(seq 1 50); do
  code="$(cut -d'|' -f2 "$THU_MUC/$i")"
  if [ "$code" = "RATE_LIMITED" ]; then
    bi_xo_chan=$((bi_xo_chan + 1))
  else
    qua_xo=$((qua_xo + 1))
  fi
done
rm -rf "$THU_MUC"
echo "  qua duoc xo: $qua_xo    bi xo chan (RATE_LIMITED): $bi_xo_chan"
if [ "$qua_xo" = "$TRAN_CHAT" ]; then
  ok "dung $TRAN_CHAT request qua duoc — khong co race"
else
  fail "$qua_xo request qua duoc, cho doi dung $TRAN_CHAT"
fi

# ── DoD 3: mo 4 luot sinh cung luc -> cai thu 4 tra TOO_MANY_STREAMS ───────
echo
echo "== DoD 3: mo $((TRAN_GHE + 1)) luot sinh cung luc =="
xoa_xo
xoa_ghe
CAU_HOI_DAI="Liet ke 120 so nguyen to dau tien, moi so mot dong."
dang_chay=()
for i in $(seq 1 "$TRAN_GHE"); do
  R="$(post "$CONV" "$CAU_HOI_DAI")"
  echo "  #$i -> $(echo "$R" | cut -d'|' -f1) $(echo "$R" | cut -d'|' -f2)"
  if [ "$(echo "$R" | cut -d'|' -f1)" = "202" ]; then
    dang_chay+=("$(echo "$R" | cut -d'|' -f4)")
  fi
done
R4="$(post "$CONV" "$CAU_HOI_DAI")"
ma4="$(echo "$R4" | cut -d'|' -f1)"
code4="$(echo "$R4" | cut -d'|' -f2)"
retry4="$(echo "$R4" | cut -d'|' -f3)"
echo "  #$((TRAN_GHE + 1)) -> $ma4 $code4 retry-after=$retry4"
if [ "$ma4" = "429" ] && [ "$code4" = "TOO_MANY_STREAMS" ]; then
  ok "luot thu $((TRAN_GHE + 1)) tra 429 TOO_MANY_STREAMS"
else
  fail "luot thu $((TRAN_GHE + 1)) tra $ma4 $code4"
fi
if [ "$retry4" = "-" ]; then
  ok "khong kem Retry-After (khong ai biet model sinh xong luc nao)"
else
  fail "co Retry-After=$retry4 — mot con so bia"
fi
echo "  ghe dang ban: $(redis_ ZRANGE "rl:streams:$USER_ID" 0 -1 | tr '\n' ' ')"

# ── DoD 4: mot luot xong -> ghe duoc tra lai ───────────────────────────────
echo
echo "== DoD 4: doi mot luot khep lai roi mo lai cai thu $((TRAN_GHE + 1)) =="
for _ in $(seq 1 60); do
  con_sinh="$(psql_ "SELECT count(*) FROM messages WHERE conversation_id='$CONV' AND status IN ('queued','streaming');" | tr -d ' ')"
  if [ "$con_sinh" -lt "$TRAN_GHE" ]; then break; fi
  sleep 2
done
echo "  con dang sinh trong DB: $con_sinh / $TRAN_GHE"
xoa_xo # khong de token bucket lan vao phep do nay
R5="$(post "$CONV" "1+1 bang may?")"
ma5="$(echo "$R5" | cut -d'|' -f1)"
code5="$(echo "$R5" | cut -d'|' -f2)"
echo "  luot moi -> $ma5 $code5"
if [ "$ma5" = "202" ]; then
  ok "ghe da duoc tra lai sau khi mot luot khep"
else
  fail "van bi tu choi ($ma5 $code5) du chi con $con_sinh luot dang chay"
fi
echo "  ghe dang ban: $(redis_ ZRANGE "rl:streams:$USER_ID" 0 -1 | tr '\n' ' ')"

# ── don dep: khong de du lieu cua phep do o lai stack dev ──────────────────
echo
echo "== don dep =="
for mid in $(psql_ "SELECT id FROM messages WHERE conversation_id='$CONV' AND status IN ('queued','streaming');"); do
  curl -sk -o /dev/null -X POST "$BASE_URL/api/v1/messages/$(echo "$mid" | tr -d ' ')/cancel" \
    -H "X-User-Id: $USER_ID" || true
done
sleep 3
for mau in "rl:user:chat:$USER_ID" "rl:streams:$USER_ID"; do
  redis_ DEL "$mau" >/dev/null
done
for mau in "idem:$USER_ID:*" "cancel:*" "stream:*"; do
  redis_ --scan --pattern "$mau" | while read -r k; do
    if [ -n "$k" ]; then redis_ DEL "$k" >/dev/null; fi
  done
done
psql_ "UPDATE conversations SET active_leaf_id=NULL WHERE user_id='$USER_ID';" >/dev/null
psql_ "DELETE FROM messages WHERE conversation_id='$CONV';" >/dev/null
psql_ "DELETE FROM conversations WHERE user_id='$USER_ID';" >/dev/null
psql_ "DELETE FROM users WHERE id='$USER_ID';" >/dev/null
echo "  da xoa user/hoi thoai/message cua phep do, moi khoa rl:*/idem:*/stream:* cua no"

echo
if [ "$so_loi" -ne 0 ]; then
  echo "test_ratelimit: THAT BAI ($so_loi dong)"
  exit 1
fi
echo "test_ratelimit: OK"
