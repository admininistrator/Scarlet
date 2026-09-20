#!/usr/bin/env bash
# Nam dong DoD cua T-2.12 do tren STACK THAT: model that, Postgres that, Redis
# that, qua Nginx.
#
# KH tham chieu: §10.2, §10.3, §9.5, A7, ADR-08, C16 · tasks.md T-2.12 DoD,
# B-32, B-67, B-78, B-94, B-156.
#
#     bash scripts/test_metering.sh
#
# ┌───────────────────────────────────────────────────────────────────────────┐
# │  VI SAO CAN SCRIPT NAY KHI DA CO pytest                                   │
# └───────────────────────────────────────────────────────────────────────────┘
#
# `tests/quota/test_meter.py` chay tren Postgres that nhung Redis GIA, va tren
# `usage` GIA. Ba thu duoi day chi do duoc o day:
#
#   * `usage` do provider THAT gui ve (DoD 1) — mot fixture chep tay khong
#     chung minh duoc rang chunk cuoi cua DeepSeek that su co `prompt_tokens`;
#   * `cost_usd` KHONG doi khi gia trong catalog doi (DoD 2, A7) — phep kiem
#     nay chi co nghia khi catalog that duoc sua va tien trinh that nap lai;
#   * ZSET quota trong Redis THAT (DoD 5) — ban gia cua conftest la mot ban
#     hien thuc thu hai, va no se xanh ca khi lenh ZADD that sai cu phap.
#
# Cung ho `scripts/test_ratelimit.sh` (T-2.9) va `test_idempotency.sh` (S5):
# do tren duong ma nguoi dung that di. Xem B-149.
#
# ┌───────────────────────────────────────────────────────────────────────────┐
# │  SCRIPT NAY TIEU TIEN THAT                                                │
# └───────────────────────────────────────────────────────────────────────────┘
#
# No goi `deepseek-flash` va `nr-gemini-flash` that. Moi lan chay ton co ~1e-4
# USD — de y thi thay, nhung khong the tranh: DoD doi `cost_usd > 0`, va mot
# model 0 USD khong chung minh duoc gi ve phep nhan tien.
#
# Du lieu test (user `dod-t212-*`, hoi thoai, message, usage_events, khoa
# quota) duoc DON SACH o cuoi, ke ca khi co dong nao FAIL.
set -uo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose -p scarlet --profile core --profile tools"
# `tr -d` khong phai thua: `.env` tren may dev nay luu CRLF (B-146).
BASE_URL="$(grep -E '^PUBLIC_BASE_URL=' .env | cut -d= -f2- | tr -d '\r')"
CATALOG="config/model_catalog.json"
MODEL_METERED="deepseek-flash"
MODEL_9ROUTER="nr-gemini-flash"
EMAIL="dod-t212-$(date +%s)@scarlet.example"

so_loi=0
ok() { echo "  OK   $*"; }
fail() {
  echo "  FAIL $*"
  so_loi=$((so_loi + 1))
}

psql_() { $COMPOSE exec -T postgres psql -U scarlet -d scarlet -tAq -c "$1" | tr -d '\r'; }
redis_() { $COMPOSE exec -T redis redis-cli "$@" | tr -d '\r'; }
# Mot cookie phien that (§11.2) cho user $1, tier $2 — T-3.1c.
#
# Nhanh danh tinh tam cua Phase 1 chet cung task ay, nen moi lenh `curl` duoi
# day phai mang cookie nay thay cho header danh tinh cu. Token duoc ky TRONG
# container `api`: chi o do moi co `JWT_SECRET` va `app/` — WSL host khong co
# ca hai.
#
# Doan Python di qua STDIN (heredoc nhay don) chu khong qua `python -c "..."`:
# no mang dau nhay va dau ngoac nhon, va mot lan bash noi suy nham vao giua se
# bao loi o mot dong khac han — dung cai bay ma chu thich cua `amid()` trong
# `test_idempotency.sh` da ghi lai mot lan.
phien_() { # $1=user_id  $2=tier_name
  $COMPOSE exec -T api python - "$1" "$2" <<'PY' | tr -d '\r'
import sys
import uuid

from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import UserRole, UserStatus

print(
    SESSION_COOKIE_NAME
    + "="
    + encode_access_token(
        user_id=uuid.UUID(sys.argv[1]),
        role=UserRole.USER,
        tier=sys.argv[2],
        status=UserStatus.ACTIVE,
        ttl_minutes=settings.ACCESS_TOKEN_TTL_MIN,
    )
)
PY
}


# Mot luot chat tron ven: POST roi cho message khep lai. In assistant_message_id.
chat() { # $1=conversation  $2=noi dung  $3=model_id
  local amid
  amid="$(curl -sk -X POST "$BASE_URL/api/v1/conversations/$1/messages" \
    -H "Cookie: $COOKIE" -H 'Content-Type: application/json' \
    -H "Idempotency-Key: $(cat /proc/sys/kernel/random/uuid)" \
    -d "{\"content\":\"$2\",\"model_id\":\"$3\"}" |
    sed -n 's/.*"assistant_message_id":"\([^"]*\)".*/\1/p')"
  [ -n "$amid" ] || return 1
  cho_khep "$amid"
  echo "$amid"
}

cho_khep() { # doi toi khi status roi khoi queued/streaming
  local i
  for i in $(seq 1 120); do
    case "$(psql_ "SELECT status FROM messages WHERE id='$1';")" in
      queued | streaming) sleep 1 ;;
      *) return 0 ;;
    esac
  done
  return 1
}

don_dep() {
  echo
  echo "== don du lieu DoD =="
  if [ -n "${USER_ID:-}" ]; then
    redis_ DEL "quota:5h:$USER_ID" "quota:weekly:$USER_ID" "rl:user:chat:$USER_ID" \
      "rl:streams:$USER_ID" "tier:limits:$USER_ID" >/dev/null
    psql_ "DELETE FROM usage_events WHERE user_id='$USER_ID';" >/dev/null
    psql_ "DELETE FROM users WHERE id='$USER_ID';" >/dev/null
    echo "  usage_events con lai: $(psql_ 'SELECT count(*) FROM usage_events;')"
    echo "  users con lai:        $(psql_ 'SELECT count(*) FROM users;')"
  fi
  if [ -f "$CATALOG.dod-backup" ]; then
    mv "$CATALOG.dod-backup" "$CATALOG"
    echo "  catalog: da tra ve nguyen trang"
  fi
}
trap don_dep EXIT

echo "== chuan bi =="
USER_ID="$(psql_ "INSERT INTO users (email, password_hash, status) VALUES ('$EMAIL','khong-phai-hash-that','active') RETURNING id;" | tr -d ' ')"
TIER="$(psql_ "SELECT tier_name FROM users WHERE id='$USER_ID';" | tr -d ' ')"
COOKIE="$(phien_ "$USER_ID" "$TIER")"
CONV="$(psql_ "INSERT INTO conversations (user_id) VALUES ('$USER_ID') RETURNING id;" | tr -d ' ')"
echo "  user=$USER_ID  conv=$CONV"
echo "  usage_events truoc khi bat dau: $(psql_ "SELECT count(*) FROM usage_events WHERE user_id='$USER_ID';")"

# ── DoD 1: mot luot chat -> dung 1 dong, cost_usd > 0, snapshot day du ──────
echo
echo "== DoD 1: mot luot chat -> dung 1 dong usage_events =="
AMID1="$(chat "$CONV" "1+1 bang may? Tra loi that ngan." "$MODEL_METERED")" || fail "khong chat duoc"
echo "  assistant_message_id = $AMID1"
psql_ "SELECT 'so dong: ' || count(*) FROM usage_events WHERE user_id='$USER_ID';"
$COMPOSE exec -T postgres psql -U scarlet -d scarlet -x -c \
  "SELECT model_id, provider, key_source, prompt_tokens, completion_tokens, cached_tokens,
          cost_usd, cost_confidence, upstream_model_reported, price_snapshot
     FROM usage_events WHERE user_id='$USER_ID';"

SO_DONG="$(psql_ "SELECT count(*) FROM usage_events WHERE user_id='$USER_ID';")"
[ "$SO_DONG" = "1" ] && ok "dung 1 dong" || fail "co $SO_DONG dong, cho doi 1"
COST1="$(psql_ "SELECT cost_usd FROM usage_events WHERE user_id='$USER_ID';")"
awk -v c="$COST1" 'BEGIN{exit !(c+0 > 0)}' && ok "cost_usd = $COST1 > 0" || fail "cost_usd = $COST1"
THIEU="$(psql_ "SELECT count(*) FROM usage_events, LATERAL (VALUES ('input_per_1m'),('output_per_1m'),
   ('cached_input_per_1m'),('cache_write_per_1m'),('pricing_mode'),('source'),('catalog_version'),('at')) AS k(n)
   WHERE user_id='$USER_ID' AND NOT price_snapshot ? k.n;")"
[ "$THIEU" = "0" ] && ok "price_snapshot co du 8 khoa" || fail "price_snapshot thieu $THIEU khoa"
CONF1="$(psql_ "SELECT cost_confidence FROM usage_events WHERE user_id='$USER_ID';")"
[ "$CONF1" = "exact" ] && ok "cost_confidence = exact (model metered, provider bao usage)" ||
  fail "cost_confidence = $CONF1, cho doi exact"

# ── DoD 5 (nua dau): ZSET Redis khop ngay sau luot dau ─────────────────────
echo
echo "  ZSET quota ngay sau luot dau:"
for W in "5h" "weekly"; do
  echo "    quota:$W:  $(redis_ ZRANGE "quota:$W:$USER_ID" 0 -1 WITHSCORES | tr '\n' ' ')"
  echo "    TTL:       $(redis_ TTL "quota:$W:$USER_ID") s"
done

# ── DoD 2: doi gia trong catalog -> dong cu KHONG doi (A7) ─────────────────
echo
echo "== DoD 2: doi gia trong catalog -> dong cu khong doi cost_usd (A7) =="
SNAP_TRUOC="$(psql_ "SELECT price_snapshot::text FROM usage_events WHERE message_id='$AMID1';")"
echo "  cost_usd truoc khi doi gia: $COST1"
cp "$CATALOG" "$CATALOG.dod-backup"
# Nhan gia input/output cua model metered len 10 lan, ngay trong file that.
python3 - "$CATALOG" "$MODEL_METERED" <<'PY'
import json, sys
path, model_id = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    cat = json.load(f)
for m in cat["models"]:
    if m["id"] == model_id:
        for block in (m["pricing"], m["pricing"].get("off_peak") or {}):
            for k in ("input_per_1m", "output_per_1m", "cached_input_per_1m"):
                if block.get(k) is not None:
                    block[k] = round(block[k] * 10, 6)
with open(path, "w", encoding="utf-8") as f:
    json.dump(cat, f, ensure_ascii=False, indent=2)
    f.write("\n")
print("  da nhan gia len 10 lan trong", path)
PY
# Worker nap catalog luc import (fail-fast L2) nen phai restart no, khong phai
# goi /admin/catalog/reload — cai do chi nap lai tien trinh `api`.
$COMPOSE restart worker >/dev/null 2>&1
sleep 6

COST1_SAU="$(psql_ "SELECT cost_usd FROM usage_events WHERE message_id='$AMID1';")"
SNAP_SAU="$(psql_ "SELECT price_snapshot::text FROM usage_events WHERE message_id='$AMID1';")"
[ "$COST1_SAU" = "$COST1" ] && ok "dong cu van $COST1_SAU (khong doi)" ||
  fail "dong cu doi tu $COST1 thanh $COST1_SAU"
[ "$SNAP_SAU" = "$SNAP_TRUOC" ] && ok "price_snapshot cua dong cu khong doi" ||
  fail "price_snapshot cua dong cu da doi"

# …va mot luot MOI phai thay gia moi, neu khong thi phep kiem tren xanh vi
# khong co gi doi ca, chu khong phai vi A7 duoc giu.
AMID2="$(chat "$CONV" "2+2 bang may? Tra loi that ngan." "$MODEL_METERED")" || fail "khong chat duoc luot 2"
GIA_MOI="$(psql_ "SELECT (price_snapshot->>'input_per_1m') FROM usage_events WHERE message_id='$AMID2';")"
GIA_CU="$(psql_ "SELECT (price_snapshot->>'input_per_1m') FROM usage_events WHERE message_id='$AMID1';")"
echo "  input_per_1m: dong cu=$GIA_CU  dong moi=$GIA_MOI"
awk -v a="$GIA_CU" -v b="$GIA_MOI" 'BEGIN{exit !(b+0 > a+0)}' &&
  ok "luot moi dung gia moi (chung to phep kiem tren co y nghia)" ||
  fail "luot moi van dung gia cu — catalog chua nap lai?"

mv "$CATALOG.dod-backup" "$CATALOG"
$COMPOSE restart worker >/dev/null 2>&1
sleep 6
echo "  catalog: da tra ve nguyen trang"

# ── DoD 3: model qua 9Router -> cost_confidence='low' ─────────────────────
echo
echo "== DoD 3: model qua 9Router -> cost_confidence='low' (§9.5, C16) =="
AMID3="$(chat "$CONV" "Chao ban." "$MODEL_9ROUTER")" || fail "khong chat duoc qua 9Router"
$COMPOSE exec -T postgres psql -U scarlet -d scarlet -x -c \
  "SELECT model_id, prompt_tokens, completion_tokens, cost_usd, cost_confidence,
          upstream_model_reported, price_snapshot->>'source' AS gia_tu_dau
     FROM usage_events WHERE message_id='$AMID3';"
CONF3="$(psql_ "SELECT cost_confidence FROM usage_events WHERE message_id='$AMID3';")"
[ "$CONF3" = "low" ] && ok "cost_confidence = low" || fail "cost_confidence = $CONF3"
UP3="$(psql_ "SELECT coalesce(upstream_model_reported,'<NULL>') FROM usage_events WHERE message_id='$AMID3';")"
[ "$UP3" = "<NULL>" ] && ok "upstream_model_reported = NULL (B-32: khong lay duoc)" ||
  fail "upstream_model_reported = $UP3"

# ── DoD 4: huy giua chung -> van co 1 dong, completion_tokens = phan da sinh ─
echo
echo "== DoD 4: huy giua chung -> van co 1 dong (B-94) =="
AMID4="$(curl -sk -X POST "$BASE_URL/api/v1/conversations/$CONV/messages" \
  -H "Cookie: $COOKIE" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(cat /proc/sys/kernel/random/uuid)" \
  -d "{\"content\":\"Ke mot cau chuyen that dai ve mua thu Ha Noi, cang dai cang tot.\",\"model_id\":\"$MODEL_METERED\"}" |
  sed -n 's/.*"assistant_message_id":"\([^"]*\)".*/\1/p')"
echo "  assistant_message_id = $AMID4 — cho 6 s roi bam Dung"
sleep 6
curl -sk -o /dev/null -X POST "$BASE_URL/api/v1/messages/$AMID4/cancel" -H "Cookie: $COOKIE"
cho_khep "$AMID4"

$COMPOSE exec -T postgres psql -U scarlet -d scarlet -x -c \
  "SELECT m.status, m.finish_reason, length(m.content) AS so_ky_tu_content,
          length(coalesce(m.reasoning,'')) AS so_ky_tu_reasoning,
          m.prompt_tokens AS msg_prompt, m.completion_tokens AS msg_completion,
          u.prompt_tokens AS so_prompt, u.completion_tokens AS so_completion,
          u.cost_usd, u.cost_confidence
     FROM messages m JOIN usage_events u ON u.message_id = m.id WHERE m.id='$AMID4';"

ST4="$(psql_ "SELECT status FROM messages WHERE id='$AMID4';")"
SO4="$(psql_ "SELECT count(*) FROM usage_events WHERE message_id='$AMID4';")"
OUT4="$(psql_ "SELECT completion_tokens FROM usage_events WHERE message_id='$AMID4';")"
MSGOUT4="$(psql_ "SELECT coalesce(completion_tokens::text,'<NULL>') FROM messages WHERE id='$AMID4';")"
CONF4="$(psql_ "SELECT cost_confidence FROM usage_events WHERE message_id='$AMID4';")"
[ "$ST4" = "cancelled" ] && ok "messages.status = cancelled" || fail "status = $ST4"
[ "$SO4" = "1" ] && ok "van co dung 1 dong usage_events" || fail "co $SO4 dong"
[ "$OUT4" -gt 0 ] && ok "usage_events.completion_tokens = $OUT4 (phan da sinh)" ||
  fail "completion_tokens = $OUT4"
[ "$MSGOUT4" = "<NULL>" ] && ok "messages.completion_tokens van NULL (NQ-26 khong doi)" ||
  fail "messages.completion_tokens = $MSGOUT4, cho doi NULL"
[ "$CONF4" = "low" ] && ok "cost_confidence = low (tiktoken tu dem)" || fail "cost_confidence = $CONF4"

# Doi chieu con so tiktoken voi chinh `content` + `reasoning` da luu.
echo "  doi chieu voi phep dem tiktoken tren chinh content da luu:"
CONTENT_B64="$(psql_ "SELECT encode(convert_to(content || coalesce(reasoning,''), 'UTF8'), 'base64') FROM messages WHERE id='$AMID4';" | tr -d '\n')"
$COMPOSE exec -T -e CB64="$CONTENT_B64" worker python -c "
import base64, os
from app.llm.tokens import count_text
raw = base64.b64decode(os.environ['CB64']).decode('utf-8')
print('    so token cua content+reasoning:', count_text(raw, model_id='$MODEL_METERED'))
print('    (usage_events.completion_tokens = $OUT4, chenh lech la khung message va tool_calls)')
"

# ── DoD 5: SUM(cost_usd) Postgres khop tong ZSET Redis (±0.000001) ─────────
echo
echo "== DoD 5: SUM(cost_usd) Postgres khop tong ZSET Redis =="
SUM_PG="$(psql_ "SELECT coalesce(sum(cost_usd),0) FROM usage_events WHERE user_id='$USER_ID';")"
SO_DONG_PG="$(psql_ "SELECT count(*) FROM usage_events WHERE user_id='$USER_ID';")"
echo "  Postgres: $SO_DONG_PG dong, SUM(cost_usd) = $SUM_PG"
for W in "5h" "weekly"; do
  MEMBERS="$(redis_ ZRANGE "quota:$W:$USER_ID" 0 -1)"
  SUM_RD="$(echo "$MEMBERS" | awk -F: 'NF{s+=$NF} END{printf "%.6f", s}')"
  SO_MEM="$(echo "$MEMBERS" | grep -c . || true)"
  TTL="$(redis_ TTL "quota:$W:$USER_ID")"
  echo "  Redis quota:$W: $SO_MEM member, tong = $SUM_RD, TTL = $TTL s"
  awk -v a="$SUM_PG" -v b="$SUM_RD" 'BEGIN{exit !((a-b) <= 0.000001 && (b-a) <= 0.000001)}' &&
    ok "quota:$W khop Postgres (lech <= 0.000001)" ||
    fail "quota:$W lech: Postgres=$SUM_PG Redis=$SUM_RD"
  [ "$SO_MEM" = "$SO_DONG_PG" ] &&
    ok "quota:$W co dung $SO_MEM member = so dong trong so cai" ||
    fail "quota:$W co $SO_MEM member nhung so cai co $SO_DONG_PG dong"
  [ "$TTL" -gt 0 ] && ok "quota:$W co TTL = $TTL s (B-156 nua b)" || fail "quota:$W TTL = $TTL"
done

echo
if [ "$so_loi" -eq 0 ]; then
  echo "TAT CA DONG DoD DEU XANH"
else
  echo "CO $so_loi DONG FAIL"
fi
exit "$so_loi"
