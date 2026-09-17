#!/usr/bin/env bash
# S5 — hai lan bam Gui trong 300 ms chi tao MOT message (§2.3, §11.4, T-2.8).
#
# KH tham chieu: §2.3 (S5), §11.4, ADR-15, C22 · tasks.md T-2.8 DoD.
#
#     bash scripts/test_idempotency.sh             # model mac dinh cua catalog
#     MODEL_ID=ol-qwen-small bash scripts/...      # model cuc bo => 0 USD
#
# ┌───────────────────────────────────────────────────────────────────────────┐
# │  VI SAO CAN SCRIPT NAY KHI DA CO pytest                                   │
# └───────────────────────────────────────────────────────────────────────────┘
#
# `tests/api/test_idempotency.py` chay hai request "song song" bang
# `asyncio.gather` TRONG MOT tien trinh, tren mot Redis GIA. Cai no khong chung
# minh duoc, va cung la cai S5 hoi:
#
#   * `SET NX` cua Redis THAT co nguyen tu giua hai KET NOI khac nhau khong,
#   * Nginx (§22.3) co gop / doi thu tu hai POST den gan nhau khong,
#   * va hai tien trinh `curl` that bam cung mot luc thi DB con dung 1 luot.
#
# Cung li le voi `scripts/test_resume.py` cua S3: do tren duong ma nguoi dung
# that di, khong phai tren mot ban sao trong bo nho.
#
# ┌───────────────────────────────────────────────────────────────────────────┐
# │  BON DONG DoD CUA T-2.8, THEO DUNG THU TU                                 │
# └───────────────────────────────────────────────────────────────────────────┘
#
#   1. 2 request SONG SONG cung key -> 1 tao moi, 1 tra 409 hoac cung
#      message_id; DB co DUNG 1 luot (= 2 hang: user + assistant, §7.2 ①)
#   2. Gui lai cung key sau khi xong -> cung response, DB khong them dong
#   3. Thieu header o POST .../messages -> 400
#   4. TTL cua khoa idem: ~ 86400
#
# `curl -k`: chung chi dev do mkcert cap va CA cua no nam tren Windows host,
# khong nam trong WSL — cung ly do da ghi o `scripts/test_resume.py`.
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose --profile core --profile tools"
# `tr -d` khong phai thua: `.env` tren may dev nay luu CRLF (khong nam trong
# `.gitattributes`), va mot `` dinh o duoi URL lam moi lenh curl tra ma 000
# — that bai im lang, khong phai loi HTTP nao ca.
BASE_URL="$(grep -E '^PUBLIC_BASE_URL=' .env | cut -d= -f2- | tr -d '')"
MODEL_ID="${MODEL_ID:-}"
EMAIL="dod-t28-$(date +%s)@scarlet.example"

so_loi=0

ok() { echo "  OK   $*"; }
fail() {
  echo "  FAIL $*"
  so_loi=$((so_loi + 1))
}

psql_() { $COMPOSE exec -T postgres psql -U scarlet -d scarlet -tAq -c "$1"; }
redis_() { $COMPOSE exec -T redis redis-cli "$@" | tr -d '\r'; }

# Mot POST toi `.../messages`. In "<ma http>|<body>" tren MOT dong.
post() { # $1=conversation_id  $2=idempotency key ("" = khong gui header)
  local body="{\"content\":\"1+1 bang may?\""
  if [ -n "$MODEL_ID" ]; then body="$body,\"model_id\":\"$MODEL_ID\""; fi
  body="$body}"

  # `if` chu khong `[ ... ] && ...`: duoi `set -e`, mot AND-list that bai o ve
  # trai la mot lenh tra ma khac 0 -> script CHET giua chung thay vi di tiep.
  local header=()
  if [ -n "$2" ]; then header=(-H "Idempotency-Key: $2"); fi

  # `mktemp` chu khong `/tmp/...$$`: hai loi goi song song o DoD 1 chay trong
  # hai subshell, ma `$$` trong subshell van la PID cua tien trinh CHA — hai
  # lan ghi se dam vao cung mot file.
  local tmp
  tmp="$(mktemp)"
  curl -sk -o "$tmp" -w '%{http_code}' \
    -X POST "$BASE_URL/api/v1/conversations/$1/messages" \
    -H "X-User-Id: $USER_ID" -H 'Content-Type: application/json' \
    "${header[@]}" -d "$body"
  echo "|$(cat "$tmp")"
  rm -f "$tmp"
}

# `sed` chu khong `python3 -c '...'`: doan python phai mang dau nhay KEP long
# trong dau nhay DON, long trong `$( )`, long trong dau nhay KEP — bash tu choi
# phan tich va bao loi o mot dong khac han, mat 10 phut de tim.
amid() { printf '%s' "$1" | sed -n 's/.*"assistant_message_id":"\([^"]*\)".*/\1/p'; }

dem_message() { psql_ "SELECT count(*) FROM messages WHERE conversation_id='$1';" | tr -d ' '; }

echo "== chuan bi =="
USER_ID="$(psql_ "INSERT INTO users (email, password_hash, status) VALUES ('$EMAIL','khong-phai-hash-that','active') RETURNING id;" | tr -d ' ')"
CONV_1="$(psql_ "INSERT INTO conversations (user_id) VALUES ('$USER_ID') RETURNING id;" | tr -d ' ')"
CONV_2="$(psql_ "INSERT INTO conversations (user_id) VALUES ('$USER_ID') RETURNING id;" | tr -d ' ')"
echo "  user=$USER_ID"
echo "  conv1=$CONV_1  conv2=$CONV_2  model=${MODEL_ID:-<mac dinh cua catalog>}"

# ── DoD 1: hai request SONG SONG cung mot key ──────────────────────────────
echo
echo "== DoD 1: hai POST song song, cung Idempotency-Key (S5) =="
KEY_1="$(cat /proc/sys/kernel/random/uuid)"
OUT_A="$(mktemp)"
OUT_B="$(mktemp)"
post "$CONV_1" "$KEY_1" >"$OUT_A" &
pid_a=$!
post "$CONV_1" "$KEY_1" >"$OUT_B" &
pid_b=$!
wait "$pid_a" "$pid_b" || true
A="$(cat "$OUT_A")"
B="$(cat "$OUT_B")"
rm -f "$OUT_A" "$OUT_B"

ma_a="${A%%|*}"
body_a="${A#*|}"
ma_b="${B%%|*}"
body_b="${B#*|}"
echo "  request A: $ma_a $body_a"
echo "  request B: $ma_b $body_b"

if [ "$ma_a" = "202" ] && [ "$ma_b" = "202" ]; then
  amid_a="$(amid "$body_a")"
  amid_b="$(amid "$body_b")"
  if [ "$amid_a" = "$amid_b" ]; then
    ok "hai 202 cung assistant_message_id ($amid_a)"
  else
    fail "hai 202 KHAC message_id: $amid_a vs $amid_b"
  fi
elif [ "$ma_a$ma_b" = "202409" ] || [ "$ma_a$ma_b" = "409202" ]; then
  ok "mot 202, mot 409 IN_PROGRESS"
else
  fail "cap ma HTTP khong hop le: $ma_a / $ma_b"
fi

so_hang="$(dem_message "$CONV_1")"
if [ "$so_hang" = "2" ]; then
  ok "DB co dung 1 luot = 2 hang (user + assistant)"
else
  fail "DB co $so_hang hang, cho doi 2"
fi

# ── DoD 2: gui lai cung key sau khi da xong ────────────────────────────────
echo
echo "== DoD 2: gui lai cung key sau khi xong =="
C="$(post "$CONV_1" "$KEY_1")"
ma_c="${C%%|*}"
body_c="${C#*|}"
echo "  request C: $ma_c $body_c"
if [ "$body_c" = "$body_a" ] || [ "$body_c" = "$body_b" ]; then
  ok "body y het lan truoc"
else
  fail "body khac lan truoc"
fi
if [ "$(dem_message "$CONV_1")" = "2" ]; then
  ok "DB khong them dong"
else
  fail "DB da them dong"
fi

header_replay="$(curl -sk -D - -o /dev/null \
  -X POST "$BASE_URL/api/v1/conversations/$CONV_1/messages" \
  -H "X-User-Id: $USER_ID" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $KEY_1" -d '{"content":"1+1 bang may?"}' |
  grep -i '^idempotent-replay:' | tr -d '\r' || true)"
if [ -n "$header_replay" ]; then
  ok "co header $header_replay"
else
  fail "thieu header Idempotent-Replay"
fi

# ── DoD 3: thieu header ────────────────────────────────────────────────────
echo
echo "== DoD 3: thieu Idempotency-Key o POST .../messages =="
D="$(post "$CONV_2" "")"
echo "  request D: ${D%%|*} ${D#*|}"
if [ "${D%%|*}" = "400" ]; then
  ok "tra 400"
else
  fail "tra ${D%%|*}, cho doi 400"
fi
if [ "$(dem_message "$CONV_2")" = "0" ]; then
  ok "khong ghi hang nao"
else
  fail "da ghi hang du bi tu choi"
fi

# ── DoD 4: TTL cua khoa ────────────────────────────────────────────────────
echo
echo "== DoD 4: TTL idem:... ~ 86400 =="
KHOA="idem:$USER_ID:create_message:$KEY_1"
TTL="$(redis_ TTL "$KHOA")"
echo "  $KHOA -> TTL $TTL"
if [ "$TTL" -gt 86000 ] && [ "$TTL" -le 86400 ]; then
  ok "TTL trong khoang mong doi"
else
  fail "TTL=$TTL, cho doi ~86400"
fi
echo "  ban ghi: $(redis_ GET "$KHOA" | head -c 220)"

# ── don dep: khong de du lieu cua phep do o lai stack dev ──────────────────
echo
echo "== don dep =="
redis_ --scan --pattern "idem:$USER_ID:*" | while read -r k; do
  if [ -n "$k" ]; then redis_ DEL "$k" >/dev/null; fi
done
psql_ "UPDATE conversations SET active_leaf_id=NULL WHERE user_id='$USER_ID';" >/dev/null
psql_ "DELETE FROM messages WHERE conversation_id IN ('$CONV_1','$CONV_2');" >/dev/null
psql_ "DELETE FROM conversations WHERE user_id='$USER_ID';" >/dev/null
psql_ "DELETE FROM users WHERE id='$USER_ID';" >/dev/null
echo "  da xoa user/hoi thoai/message cua phep do va moi khoa idem: cua no"

echo
if [ "$so_loi" -ne 0 ]; then
  echo "test_idempotency: THAT BAI ($so_loi dong)"
  exit 1
fi
echo "test_idempotency: OK"
