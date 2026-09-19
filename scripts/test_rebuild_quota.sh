#!/usr/bin/env bash
# Ba dong DoD cua T-2.13 do tren STACK THAT: Redis that (bi FLUSHDB that),
# Postgres that, model that, qua Nginx.
#
# KH tham chieu: §10.3, RR-7 · tasks.md T-2.13 DoD, B-155, B-156.
#
#     bash scripts/test_rebuild_quota.sh
#
# ┌───────────────────────────────────────────────────────────────────────────┐
# │  VI SAO CAN SCRIPT NAY KHI DA CO pytest                                   │
# └───────────────────────────────────────────────────────────────────────────┘
#
# `tests/quota/test_rebuild.py` chay tren Postgres that nhung Redis GIA. Ba
# thu duoi day chi do duoc o day:
#
#   * `redis-cli FLUSHDB` THAT (DoD 1) — ban gia trong `conftest.py` khong co
#     lenh do, va "xoa sach mot dict Python" khong chung minh duoc rang app
#     song sot qua mot Redis vua mat toan bo du lieu;
#   * thoi gian THAT cua 10k dong (DoD 3) — mot `ZADD` vao dict khong co vong
#     di-ve nao, nen phep chia lo se "nhanh" ca khi no khong ton tai;
#   * ke hoach thuc thi THAT cua Postgres (DoD 3 — "dung index
#     ix_usage_user_time"), thu chi `EXPLAIN ANALYZE` tren du lieu that noi.
#
# Cung ho `scripts/test_metering.sh` (T-2.12), `test_ratelimit.sh` (T-2.9) va
# `test_idempotency.sh` (S5): do tren duong ma nguoi dung that di. Xem B-149.
#
# ┌───────────────────────────────────────────────────────────────────────────┐
# │  SCRIPT NAY TIEU TIEN THAT — VA NO CHAY `FLUSHDB`                         │
# └───────────────────────────────────────────────────────────────────────────┘
#
# Hai luot chat that voi `deepseek-flash`, moi lan chay ton co ~2e-4 USD.
#
# `FLUSHDB` xoa SACH Redis cua stack dev: hang doi arq, stream dang chay,
# rate limit, blacklist, cache tier. Do dung la kich ban ma DoD dong 1 mo ta
# (`docker compose down -v` khi dev), nhung DUNG chay script nay tren mot
# stack dang co nguoi dung.
#
# Du lieu test (user `dod-t213-*`, hoi thoai, message, usage_events, khoa
# quota) duoc DON SACH o cuoi, ke ca khi co dong nao FAIL.
set -uo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose -p scarlet --profile core --profile tools"
# `tr -d` khong phai thua: `.env` tren may dev nay luu CRLF (B-146).
BASE_URL="$(grep -E '^PUBLIC_BASE_URL=' .env | cut -d= -f2- | tr -d '\r')"
MODEL="deepseek-flash"
EMAIL="dod-t213-$(date +%s)@scarlet.example"
#: DoD dong 3. 10 000 dong, rai deu trong 4 gio gan nhat de CA HAI cua so
#: cung mang du 10k — truong hop nang nhat, khong phai truong hop de.
SO_DONG_10K=10000

so_loi=0
ok() { echo "  OK   $*"; }
fail() {
  echo "  FAIL $*"
  so_loi=$((so_loi + 1))
}

psql_() { $COMPOSE exec -T postgres psql -U scarlet -d scarlet -tAq -c "$1" | tr -d '\r'; }
redis_() { $COMPOSE exec -T redis redis-cli "$@" | tr -d '\r'; }

chat() { # $1=conversation  $2=noi dung — in assistant_message_id
  local amid
  amid="$(curl -sk -X POST "$BASE_URL/api/v1/conversations/$1/messages" \
    -H "X-User-Id: $USER_ID" -H 'Content-Type: application/json' \
    -H "Idempotency-Key: $(cat /proc/sys/kernel/random/uuid)" \
    -d "{\"content\":\"$2\",\"model_id\":\"$MODEL\"}" |
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

zset_() { # $1=ten cua so — in "member score" tung dong, da sap xep
  redis_ ZRANGE "quota:$1:$USER_ID" 0 -1 WITHSCORES | paste - - | sort
}

members_() { # $1=ten cua so — chi ten member, da sap xep
  redis_ ZRANGE "quota:$1:$USER_ID" 0 -1 | sort
}

# Do lech score LON NHAT giua hai anh chup cua cung mot cua so, tinh bang giay.
#
# So score bang phep BANG thi sai, va sai theo mot cach co that: ban goc dung
# `now = time.time()` cua worker luc ghi so (`add_to_windows`), con ban dung
# lai dung `usage_events.created_at` — tuc `now()` cua Postgres, thoi diem
# BAT DAU transaction cua chinh cau INSERT do. Hai moc cach nhau vai mili
# giay. Tren mot cua so 5 gio thi khoang do khong doi mot dong nao, nhung
# `[ "$a" = "$b" ]` thi no doi.
lech_score() { # $1=file truoc  $2=file sau (dinh dang "member<TAB>score")
  awk 'NR==FNR {a[$1] = $2; next}
       ($1 in a) {d = a[$1] - $2; if (d < 0) d = -d; if (d > m) m = d}
       END {print m + 0}' "$1" "$2"
}

tong_zset() { # $1=ten cua so — tong tien trong ZSET, cong bang awk tren member
  redis_ ZRANGE "quota:$1:$USER_ID" 0 -1 |
    awk -F: '{s += $NF} END {printf "%.6f\n", s + 0}'
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
    echo "  khoa quota:* con lai: $(redis_ --scan --pattern 'quota:*' | grep -c . || true)"
  fi
}
#: Chỗ để bốn ảnh chụp ZSET (trước/sau × hai cửa sổ). File chứ không phải
#: biến: `cmp` nói được *dòng nào* khác, và `awk` của `lech_score` cần hai
#: luồng vào chứ không phải hai chuỗi.
TMP="$(mktemp -d)"
don_dep_tmp() {
  rm -rf "$TMP"
  don_dep
}
trap don_dep_tmp EXIT

echo "== chuan bi =="
USER_ID="$(psql_ "INSERT INTO users (email, password_hash, status) VALUES ('$EMAIL','khong-phai-hash-that','active') RETURNING id;" | tr -d ' ')"
CONV="$(psql_ "INSERT INTO conversations (user_id) VALUES ('$USER_ID') RETURNING id;" | tr -d ' ')"
echo "  user=$USER_ID  conv=$CONV"

# ── DoD 1: FLUSHDB -> goi API -> quota dung nhu truoc khi flush ────────────
echo
echo "== DoD 1: redis-cli FLUSHDB -> goi API -> quota KHONG ve 0 =="
AMID1="$(chat "$CONV" "1+1 bang may? Tra loi that ngan.")" || fail "khong chat duoc"
echo "  assistant_message_id = $AMID1"

for W in 5h weekly; do
  zset_ "$W" >"$TMP/truoc-$W"
  members_ "$W" >"$TMP/truoc-m-$W"
done
TRUOC_5H="$(cat "$TMP/truoc-5h")"
TONG_TRUOC="$(tong_zset 5h)"
TONG_PG="$(psql_ "SELECT coalesce(sum(cost_usd),0)::text FROM usage_events WHERE user_id='$USER_ID';")"
echo "  ZSET 5h TRUOC khi flush:"
echo "$TRUOC_5H" | sed 's/^/    /'
echo "  tong ZSET 5h = $TONG_TRUOC · SUM(cost_usd) Postgres = $TONG_PG"

echo "  --- redis-cli FLUSHDB ---"
redis_ FLUSHDB
SAU_FLUSH="$(redis_ --scan --pattern 'quota:*' | grep -c . || true)"
[ "$SAU_FLUSH" = "0" ] && ok "sau FLUSHDB: 0 khoa quota:* (Redis that su trang)" ||
  fail "sau FLUSHDB van con $SAU_FLUSH khoa quota:*"

# Goi API. `check_quota` chay DONG BO trong handler nay, truoc ca enqueue, nen
# ZSET da duoc nap lai ngay khi POST tra ve — truoc khi worker kip ghi dong so
# cua chinh luot nay.
AMID2="$(curl -sk -X POST "$BASE_URL/api/v1/conversations/$CONV/messages" \
  -H "X-User-Id: $USER_ID" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(cat /proc/sys/kernel/random/uuid)" \
  -d "{\"content\":\"2+2 bang may? Tra loi that ngan.\",\"model_id\":\"$MODEL\"}" |
  sed -n 's/.*"assistant_message_id":"\([^"]*\)".*/\1/p')"
for W in 5h weekly; do
  zset_ "$W" >"$TMP/sau-$W"
  members_ "$W" >"$TMP/sau-m-$W"
done
echo "  ZSET 5h SAU khi goi API:"
sed 's/^/    /' "$TMP/sau-5h"

for W in 5h weekly; do
  cmp -s "$TMP/truoc-m-$W" "$TMP/sau-m-$W" &&
    ok "cua so $W: tap member giong HET truoc khi flush (usage_id va so tien)" ||
    fail "cua so $W: tap member khac truoc khi flush"
  LECH="$(lech_score "$TMP/truoc-$W" "$TMP/sau-$W")"
  awk -v d="$LECH" 'BEGIN{exit !(d < 1.0)}' &&
    ok "cua so $W: score lech toi da $LECH s (created_at cua Postgres vs now() cua worker)" ||
    fail "cua so $W: score lech toi da $LECH s — qua mot giay, khong con la sai so ghi so"
done
TONG_SAU="$(tong_zset 5h)"
[ "$TONG_SAU" != "0.000000" ] && ok "tong ZSET 5h = $TONG_SAU (KHONG ve 0)" ||
  fail "tong ZSET 5h = 0 — quota da reset, dung cam bay cua T-2.13"
awk -v a="$TONG_SAU" -v b="$TONG_PG" 'BEGIN{exit !(a - b < 0.000001 && b - a < 0.000001)}' &&
  ok "tong ZSET ($TONG_SAU) khop SUM(cost_usd) Postgres ($TONG_PG) ±0.000001" ||
  fail "tong ZSET $TONG_SAU KHAC SUM(cost_usd) $TONG_PG"
echo "  TTL sau khi dung lai: 5h=$(redis_ TTL "quota:5h:$USER_ID") s · weekly=$(redis_ TTL "quota:weekly:$USER_ID") s"

[ -n "$AMID2" ] && cho_khep "$AMID2"

# ── DoD 3: 10k usage event -> rebuild < 2 s, di dung index ─────────────────
echo
echo "== DoD 3: rebuild cho $SO_DONG_10K usage event < 2 s =="
psql_ "INSERT INTO usage_events
         (user_id, model_id, provider, key_source, prompt_tokens, completion_tokens,
          cached_tokens, cost_usd, cost_confidence, price_snapshot, created_at)
       SELECT '$USER_ID', '$MODEL', 'deepseek', 'system', 10, 10, 0, 0.000001, 'exact',
              '{\"source\":\"catalog\"}'::jsonb,
              now() - make_interval(secs => (random() * 14400))
         FROM generate_series(1, $SO_DONG_10K);" >/dev/null
echo "  so dong usage_events cua user: $(psql_ "SELECT count(*) FROM usage_events WHERE user_id='$USER_ID';")"

echo "  --- ke hoach thuc thi cua chinh cau truy van rebuild doc ---"
$COMPOSE exec -T postgres psql -U scarlet -d scarlet -c \
  "EXPLAIN (ANALYZE, BUFFERS) SELECT id, cost_usd, created_at FROM usage_events
     WHERE user_id = '$USER_ID' AND created_at >= now() - interval '5 hours'
     ORDER BY created_at;" | sed 's/^/    /'

redis_ DEL "quota:5h:$USER_ID" "quota:weekly:$USER_ID" >/dev/null
echo "  --- dong ho dat quanh CHINH rebuild_quota, trong container api ---"
$COMPOSE exec -T api python - "$USER_ID" <<'PY'
import asyncio, sys, time, uuid
from app.core.redis import get_redis
from app.db.session import session_scope
from app.quota.rebuild import rebuild_quota

async def main() -> None:
    user_id = uuid.UUID(sys.argv[1])
    async with session_scope() as session:
        t0 = time.perf_counter()
        report = await rebuild_quota(session, get_redis(), user_id=user_id, now=time.time())
        giay = time.perf_counter() - t0
    print(f"    rebuild_quota: {giay:.3f} s cho {report.members} member")
    for w in report.windows:
        print(f"      {w.limit_type.value}: {w.members} member · {w.spent} USD")
    print("    KET QUA: " + ("DAT" if giay < 2.0 else "TRUOT") + " nguong 2 s")

asyncio.run(main())
PY

echo "  --- va dong ho quanh CA LENH CLI (co ca thoi gian khoi dong Python) ---"
/usr/bin/time -f "    tong wall-clock cua lenh CLI: %e s" \
  $COMPOSE exec -T api python -m app.cli rebuild-quota --all 2>&1 | tail -6

SO_MEMBER_5H="$(redis_ ZCARD "quota:5h:$USER_ID")"
SO_DONG_5H="$(psql_ "SELECT count(*) FROM usage_events WHERE user_id='$USER_ID' AND created_at >= now() - interval '5 hours';")"
[ "$SO_MEMBER_5H" = "$SO_DONG_5H" ] &&
  ok "so member cua so 5h ($SO_MEMBER_5H) = so dong so trong cua so ($SO_DONG_5H)" ||
  fail "so member $SO_MEMBER_5H KHAC so dong so $SO_DONG_5H"

echo
if [ "$so_loi" -eq 0 ]; then
  echo "== TAT CA DAT =="
else
  echo "== CO $so_loi DONG TRUOT =="
fi
exit "$so_loi"
