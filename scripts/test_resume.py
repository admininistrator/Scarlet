#!/usr/bin/env python3
"""S3 — ngắt giữa lúc stream, nối lại, so byte-by-byte với `messages.content`.

KH tham chiếu: §2.3 (S3), §7.2 ②, §7.3, §7.4, C3, C4, C9 · tasks.md T-1.11.

**Đây là tiêu chí nghiệm thu của toàn bộ Phase 1.** §3 đặt cả kiến trúc lên một
câu: *câu trả lời phải sống độc lập với kết nối HTTP*. Script này là chỗ duy
nhất chứng minh câu đó đúng trên hạ tầng thật — model thật, Redis thật, Nginx
thật — chứ không phải trên một `RedisGia` biết trước câu trả lời.

    make test-resume        # hoặc: backend/.venv/bin/python scripts/test_resume.py

┌──────────────────────────────────────────────────────────────────────────┐
│  MỘT LƯỢT ĐO                                                             │
└──────────────────────────────────────────────────────────────────────────┘

    POST /conversations/{id}/messages        → 202 + stream_url
    GET  stream_url                          → đọc tới delta thứ N
    ✂ NGẮT CỨNG (đóng socket, không đọc hết)
    ngủ 2 s
    GET  stream_url  +  Last-Event-ID: <id event CUỐI CÙNG đã nhận>
    đọc tới `done`
    A + B  ==  messages.content ?            (so theo BYTE)

Sáu lượt: lượt 1 ngắt đúng ở **delta thứ 50** (con số trong "Việc cần làm" của
T-1.11), lượt 2–5 ngắt ở điểm **ngẫu nhiên**, lượt 6 ngắt **hai lần** trong
cùng một stream. Hạt giống ngẫu nhiên in ra ở đầu và nhận lại được bằng
`--seed`, nếu không một lượt đỏ sẽ không tái hiện được.

┌──────────────────────────────────────────────────────────────────────────┐
│  BỐN QUYẾT ĐỊNH CỦA PHÉP ĐO — MỖI CÁI LÀ MỘT CÁCH TỰ LỪA MÌNH ĐÃ TRÁNH   │
└──────────────────────────────────────────────────────────────────────────┘

**1. Chỉ nối `delta`, và chỉ nối event ĐÃ TRỌN VẸN.** Một khung SSE kết thúc
bằng dòng trống; ngắt giữa chừng thì phần dở dang bị **vứt**, và
`Last-Event-ID` giữ nguyên ở event trọn vẹn cuối cùng — đúng việc mà
`EventSource` của trình duyệt làm. Đếm cả phần dở dang là tự cho mình điểm cho
những byte chưa bao giờ tới nơi, và khi đó C3 (lặp) sẽ không bao giờ hiện ra.
`reasoning` **không** được nối: nó đi vào `messages.reasoning`, không vào
`content`, và model mặc định `deepseek-flash` có khai cờ `reasoning` — nối
nhầm là mọi lượt đều đỏ vì một lý do sai.

**2. So sánh bằng `.encode("utf-8")`, không bằng `==` của `str`.** T-1.11 ghi
"byte-by-byte" và đó không phải cách nói cho oai: C9 là ca chữ tiếng Việt bị
cắt giữa hai byte của một ký tự. Hai chuỗi `str` bằng nhau thì bytes cũng bằng
nhau, nhưng đọc kết quả theo byte là cách duy nhất báo được *lệch ở byte thứ
mấy*.

**3. Mọi lượt có TRẦN THỜI GIAN và TRẦN KÝ TỰ.** Đây là bài học B-88 áp cho
một script: hai dòng DoD của T-1.11 bắt phải **phá** consumer, mà cả hai kiểu
phá đều có thể làm treo thay vì đỏ — `$` có thể nuốt luôn event `done` (không
ai đóng stream nữa), `[cursor` biến vòng đuổi kịp thành vòng lặp nóng phát lại
mãi. Treo là kiểu đỏ không tự khai báo. Ở đây treo thành `FAIL … TREO` kèm số
ký tự đã nhận, tức vẫn trả lời đúng câu hỏi "thiếu hay lặp".

**4. Đi qua Nginx (`PUBLIC_BASE_URL`), không gọi thẳng `api:8000`.** Đường mà
người dùng thật đi có C1 (`proxy_buffering off`) và C2 (`proxy_read_timeout`)
trên đó. Một phép đo bỏ qua Nginx sẽ xanh trong khi trình duyệt im lặng.

**TLS**: chứng chỉ dev do `mkcert` cấp và CA của nó nằm trên máy Windows
(T-H1), không nằm trong trust store của WSL — nên mặc định script **không**
kiểm chứng chỉ, đúng như mọi `curl -k` của các DoD trước. Có CA thì truyền
`--cacert`.

**Dữ liệu**: script tự tạo user + hội thoại của riêng nó rồi **xoá sạch** ở
cuối (`--khong-don-dep` để giữ lại mà soi). Đó là bài học B-81: DoD của T-1.6
để lại ba user trong database dev và chúng vẫn còn tới hôm nay.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

GOC_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC_REPO / "backend"))

# ──────────────────────────── hằng số của phép đo ───────────────────────────

#: Số lượt đo. DoD đòi in đúng `PASS 6/6`.
SO_LUOT = 6

#: Lượt 1 ngắt ở đây — con số ghi thẳng trong "Việc cần làm" của T-1.11.
#: Các lượt sau ngẫu nhiên trong `[KHOANG_NGAT_NGAU_NHIEN]`.
DELTA_NGAT_LUOT_DAU = 50
KHOANG_NGAT_NGAU_NHIEN = (15, 120)

#: §7.4: `EventSource` của trình duyệt đợi ~3 s trước khi tự nối lại. T-1.11
#: chốt 2 s — đủ dài để worker sinh thêm một mảng chữ trong lúc đứt (nếu không
#: thì C4 chẳng có gì để lộ ra), đủ ngắn để stream chưa hết `STREAM_TTL_S`.
CHO_TRUOC_KHI_NOI_S = 2.0

#: Trần cho MỘT lượt. Một lượt bình thường (~800 từ, `deepseek-flash`) đo được
#: dưới 60 s; trần này là cái phanh cho ca treo, không phải phép đo hiệu năng
#: (đó là T-1.12). Xem quyết định 3 ở đầu file.
TRAN_MOT_LUOT_S = 150.0

#: Trần ký tự nhận được trong một lượt. `[cursor` biến vòng ① thành vòng lặp
#: nóng phát lại bản ghi cuối, nên không có trần này thì script nuốt hết RAM
#: trước khi kịp in `FAIL`. Rộng gấp nhiều lần một câu trả lời 800 từ.
TRAN_KY_TU = 200_000

#: Đặt vào `messages.content` của model. Xin dài để có đủ chỗ mà ngắt: một câu
#: trả lời 20 chữ thì "ngắt ở delta thứ 50" không tồn tại.
PROMPT = (
    "Viết một bài văn tiếng Việt CÓ DẤU, dài ít nhất 800 từ, về vai trò của "
    "sông Hồng trong đời sống của người dân đồng bằng Bắc Bộ. Chia thành nhiều "
    "đoạn, có mở bài và kết bài. Không dùng danh sách gạch đầu dòng, không "
    "dùng bảng. Viết liền mạch thành văn xuôi."
)

#: `.env` của repo — nguồn của `PUBLIC_BASE_URL` và `DEV_DATABASE_URL` khi
#: chạy từ WSL host (compose nạp file này cho container, host thì không).
ENV_FILE = GOC_REPO / ".env"
BIEN_DB = "DEV_DATABASE_URL"

_DONG_GAN = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_CHU_THICH_CUOI_DONG = re.compile(r"\s+#.*$")


def nap_env() -> None:
    """Nạp `.env` vào `os.environ` — **không đè** biến đã export sẵn.

    Cùng việc mà `scripts/llm_env.sh` làm cho hai script LLM, viết lại bằng
    Python để `make test-resume` là **một** lệnh chứ không phải "nhớ source
    trước". Thô sơ có chủ ý: cắt ở dấu `=` đầu tiên và chỉ bỏ chú thích đứng
    sau khoảng trắng — đúng bài học B-44, nơi một chú thích cuối dòng sau giá
    trị rỗng biến thành chính giá trị đó.
    """
    if not ENV_FILE.is_file():
        return
    for dong in ENV_FILE.read_text(encoding="utf-8").splitlines():
        khop = _DONG_GAN.match(dong.strip().rstrip("\r"))
        if khop is None:
            continue
        ten, gia_tri = khop.group(1), _CHU_THICH_CUOI_DONG.sub("", khop.group(2)).strip()
        os.environ.setdefault(ten, gia_tri)


nap_env()

import asyncpg  # noqa: E402
import httpx  # noqa: E402

from app.config.catalog import get_catalog  # noqa: E402
from app.config.settings import settings  # noqa: E402


def dev_database_url() -> str:
    """URL Postgres nhìn từ HOST, trỏ vào database `scarlet` của dev.

    **Không** dùng `settings.DATABASE_URL`: nó ghi `postgres:5432`, một tên chỉ
    phân giải được bên trong network `internal` của compose (C17/C45), còn
    script này chạy ở WSL host. Cũng **không** dùng `TEST_DATABASE_URL`: nó trỏ
    vào `scarlet_test`, nơi `api` và `worker` không ghi một dòng nào — so
    byte-by-byte với một bảng rỗng là một phép đo luôn đỏ vì lý do sai.

    Thiếu biến thì **nổ ngay kèm tên biến** (A4), không lùi về một giá trị đoán.
    """
    url = os.environ.get(BIEN_DB)
    if not url:
        raise SystemExit(
            f"thiếu {BIEN_DB}. Đặt nó trong môi trường hoặc trong {ENV_FILE} "
            f"(mẫu ở .env.example), và bảo đảm `docker compose up -d postgres` "
            f"đã publish cổng 127.0.0.1:5432"
        )
    # asyncpg nhận DSN thuần, không hiểu phương ngữ `+asyncpg` của SQLAlchemy.
    return url.replace("postgresql+asyncpg://", "postgresql://")


# ═══════════════════════════ phân tích dòng SSE ════════════════════════════


@dataclass(slots=True)
class SuKien:
    """Một khung SSE **đã trọn vẹn** (đã thấy dòng trống kết thúc)."""

    id: str | None
    loai: str
    data: str


class BoDocSSE:
    """Gom byte thành event, đúng luật WHATWG ở phần mà script này cần.

    Chỉ phát ra event khi đã gặp dòng trống. Phần dở dang nằm lại trong `_dem`
    và **biến mất** khi socket đóng — đó chính là hành vi phải mô phỏng, xem
    quyết định 1 ở đầu file.
    """

    __slots__ = ("_dem", "_id", "_loai", "_data")

    def __init__(self) -> None:
        self._dem = ""
        self._reset()

    def _reset(self) -> None:
        self._id: str | None = None
        self._loai = "message"
        self._data: list[str] = []

    def nap(self, khuc: str) -> list[SuKien]:
        self._dem += khuc
        ra: list[SuKien] = []
        while "\n" in self._dem:
            dong, self._dem = self._dem.split("\n", 1)
            dong = dong.rstrip("\r")
            if dong == "":
                if self._data or self._loai != "message":
                    ra.append(SuKien(self._id, self._loai, "\n".join(self._data)))
                self._reset()
                continue
            if dong.startswith(":"):
                continue  # comment `: ping` — không phải event, không đụng id
            ten, _, gia_tri = dong.partition(":")
            gia_tri = gia_tri[1:] if gia_tri.startswith(" ") else gia_tri
            if ten == "id":
                self._id = gia_tri
            elif ten == "event":
                self._loai = gia_tri
            elif ten == "data":
                self._data.append(gia_tri)
        return ra


# ════════════════════════════ kết quả một lượt ═════════════════════════════


@dataclass(slots=True)
class KetQua:
    ten: str
    dat: bool
    ly_do: str
    so_lan_ngat: int
    nhan_duoc: int = 0
    trong_db: int = 0
    lech_byte: int | None = None
    giay: float = 0.0
    diem_ngat: list[int] = field(default_factory=list)


class NgatCung(Exception):  # noqa: N818 - tên theo nghiệp vụ, không phải lỗi
    """Đã đọc đủ số delta cần thiết — đóng socket ngay tại đây."""


class QuaHan(Exception):  # noqa: N818
    """Vượt `TRAN_MOT_LUOT_S` hoặc `TRAN_KY_TU` — treo cũng là đỏ."""


# ═════════════════════════════ máy đo một lượt ═════════════════════════════


class PhepDo:
    """Một vòng đo hoàn chỉnh: hỏi, ngắt, nối lại, so."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        pool: asyncpg.Pool,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        on_am: bool,
    ) -> None:
        self._http = http
        self._pool = pool
        self._cid = conversation_id
        self._uid = user_id
        self._on_am = on_am

    def _log(self, *phan: object) -> None:
        if self._on_am:
            return
        print("   ", *phan, flush=True)

    async def chay(self, ten: str, diem_ngat: list[int]) -> KetQua:
        bat_dau = time.monotonic()
        han = bat_dau + TRAN_MOT_LUOT_S
        try:
            amid, stream_url = await self._gui_cau_hoi()
            chu, so_lan = await self._doc_ca_stream(stream_url, diem_ngat, han)
        except QuaHan as loi:
            return KetQua(
                ten=ten,
                dat=False,
                ly_do=f"TREO — {loi}",
                so_lan_ngat=len(diem_ngat),
                giay=time.monotonic() - bat_dau,
                diem_ngat=diem_ngat,
            )
        except httpx.HTTPError as loi:
            return KetQua(
                ten=ten,
                dat=False,
                ly_do=f"LỖI HTTP — {type(loi).__name__}: {loi}",
                so_lan_ngat=len(diem_ngat),
                giay=time.monotonic() - bat_dau,
                diem_ngat=diem_ngat,
            )

        if so_lan < len(diem_ngat):
            # Một lượt không ngắt được lần nào là một lượt KHÔNG đo gì cả, và
            # nó sẽ xanh — đúng cái "test luôn xanh là test vô dụng" mà cạm bẫy
            # của T-1.11 nói tới. Câu trả lời ngắn hơn điểm ngắt ⇒ đỏ, kèm số
            # thật để người đọc biết phải nới `PROMPT` hay hạ điểm ngắt.
            return KetQua(
                ten=ten,
                dat=False,
                ly_do=(
                    f"CHUA NGAT DU — dinh {len(diem_ngat)} lan, ngat duoc {so_lan}: "
                    f"cau tra loi khong du delta (diem ngat {diem_ngat})"
                ),
                so_lan_ngat=so_lan,
                nhan_duoc=len(chu.encode("utf-8")),
                giay=time.monotonic() - bat_dau,
                diem_ngat=diem_ngat,
            )

        trong_db = await self._doc_content(amid)
        return self._so_sanh(ten, chu, trong_db, so_lan, diem_ngat, time.monotonic() - bat_dau)

    async def _gui_cau_hoi(self) -> tuple[uuid.UUID, str]:
        """§7.2 ① — `202` + `stream_url`, không một byte chữ nào ở đây."""
        res = await self._http.post(
            f"/api/v1/conversations/{self._cid}/messages",
            json={"content": PROMPT},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        res.raise_for_status()
        body = res.json()
        return uuid.UUID(body["assistant_message_id"]), body["stream_url"]

    async def _doc_ca_stream(
        self, stream_url: str, diem_ngat: list[int], han: float
    ) -> tuple[str, int]:
        """Đọc — ngắt — nối lại … cho tới `done`/`error`. Trả chữ đã nối và số lần ngắt."""
        phan: list[str] = []
        cursor: str | None = None
        so_delta = 0
        so_lan_ngat = 0

        for thu_tu, moc_ngat in enumerate([*diem_ngat, None]):
            if thu_tu > 0:
                self._log(f"ngắt ở delta #{so_delta}, cursor={cursor}, chờ {CHO_TRUOC_KHI_NOI_S}s")
                await asyncio.sleep(CHO_TRUOC_KHI_NOI_S)
            chu, cursor, so_delta, xong = await self._mot_ket_noi(
                stream_url, cursor, so_delta, moc_ngat, han, len("".join(phan))
            )
            phan.append(chu)
            if moc_ngat is not None:
                so_lan_ngat += 1
            if xong:
                break
        return "".join(phan), so_lan_ngat

    async def _mot_ket_noi(
        self,
        stream_url: str,
        cursor: str | None,
        so_delta: int,
        moc_ngat: int | None,
        han: float,
        da_co: int,
    ) -> tuple[str, str | None, int, bool]:
        """Một kết nối SSE. `moc_ngat=None` ⇒ đọc tới hết.

        Trả về `(chữ nhận được, Last-Event-ID, tổng số delta, đã thấy done/error)`.
        """
        headers = {"Last-Event-ID": cursor} if cursor is not None else {}
        bo_doc = BoDocSSE()
        chu: list[str] = []
        xong = False

        try:
            async with self._http.stream("GET", stream_url, headers=headers) as res:
                res.raise_for_status()
                async for khuc in res.aiter_text():
                    if time.monotonic() > han:
                        raise QuaHan(
                            f"quá {TRAN_MOT_LUOT_S:.0f}s, mới nhận "
                            f"{da_co + len(''.join(chu))} ký tự"
                        )
                    for su_kien in bo_doc.nap(khuc):
                        # Cursor tiến theo event ĐÃ TRỌN VẸN, kể cả event không
                        # mang chữ — đó là thứ trình duyệt gửi lại (§7.4).
                        if su_kien.id is not None:
                            cursor = su_kien.id
                        if su_kien.loai == "delta":
                            chu.append(json.loads(su_kien.data)["t"])
                            so_delta += 1
                        elif su_kien.loai in ("done", "error"):
                            xong = True
                            raise NgatCung
                        if da_co + len("".join(chu)) > TRAN_KY_TU:
                            raise QuaHan(f"nhận quá {TRAN_KY_TU} ký tự — gần như chắc chắn là LẶP")
                        if moc_ngat is not None and so_delta >= moc_ngat:
                            raise NgatCung
        except NgatCung:
            pass
        return "".join(chu), cursor, so_delta, xong

    async def _doc_content(self, message_id: uuid.UUID) -> str:
        """`messages.content` — nguồn sự thật (C5). Đọc SAU khi đã thấy `done`.

        Không có khe nào ở đây: `workers/generate.py` ghi Postgres **trước** rồi
        mới `XADD done`, nên thấy `done` nghĩa là hàng đã khép.
        """
        async with self._pool.acquire() as conn:
            noi_dung = await conn.fetchval("SELECT content FROM messages WHERE id = $1", message_id)
        return noi_dung or ""

    def _so_sanh(
        self,
        ten: str,
        nhan: str,
        trong_db: str,
        so_lan_ngat: int,
        diem_ngat: list[int],
        giay: float,
    ) -> KetQua:
        """So theo BYTE và nói rõ **thiếu** hay **lặp** — xem quyết định 2."""
        b_nhan, b_db = nhan.encode("utf-8"), trong_db.encode("utf-8")
        chung = min(len(b_nhan), len(b_db))
        lech = next((i for i in range(chung) if b_nhan[i] != b_db[i]), None)
        if lech is None and len(b_nhan) != len(b_db):
            lech = chung

        if b_nhan == b_db and b_db:
            ly_do = f"{len(b_db)} byte khớp"
            dat = True
        elif not b_db:
            ly_do = "messages.content RỖNG — lượt sinh không ghi được gì"
            dat = False
        else:
            hieu = len(b_nhan) - len(b_db)
            if hieu < 0:
                nhan_xet = f"THIẾU {-hieu} byte"
            elif hieu > 0:
                nhan_xet = f"LẶP {hieu} byte"
            else:
                nhan_xet = "KHÁC NỘI DUNG (cùng độ dài)"
            ly_do = f"{nhan_xet}, lệch từ byte #{lech}"
            dat = False

        return KetQua(
            ten=ten,
            dat=dat,
            ly_do=ly_do,
            so_lan_ngat=so_lan_ngat,
            nhan_duoc=len(b_nhan),
            trong_db=len(b_db),
            lech_byte=lech,
            giay=giay,
            diem_ngat=diem_ngat,
        )


# ═══════════════════════════ dựng và dọn dữ liệu ═══════════════════════════


async def tao_user(pool: asyncpg.Pool, dau_vet: str) -> uuid.UUID:
    """`users` chưa có model ORM (Phase 2, T-2.1) nên chèn bằng SQL thô.

    `tier_name` để trống ⇒ DEFAULT `'free'`, tier do migration 0001 seed.
    """
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING id",
            f"{dau_vet}@scarlet.test",
            "khong-phai-hash-that",
        )
    assert isinstance(user_id, uuid.UUID)
    return user_id


async def don_dep(pool: asyncpg.Pool, user_id: uuid.UUID) -> tuple[int, int]:
    """Xoá **cứng** mọi thứ script vừa tạo. Bài học B-81.

    Thứ tự bắt buộc: `conversations.active_leaf_id` trỏ vào `messages`, nên
    phải gỡ con trỏ trước rồi mới xoá message, rồi mới xoá hội thoại.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE conversations SET active_leaf_id = NULL WHERE user_id = $1", user_id
        )
        so_msg = await conn.fetchval(
            "WITH x AS (DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = $1) RETURNING 1) "
            "SELECT count(*) FROM x",
            user_id,
        )
        so_ht = await conn.fetchval(
            "WITH x AS (DELETE FROM conversations WHERE user_id = $1 RETURNING 1) "
            "SELECT count(*) FROM x",
            user_id,
        )
        await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    return int(so_msg or 0), int(so_ht or 0)


# ══════════════════════════════════ chạy ═══════════════════════════════════


def diem_ngat_cua_luot(i: int, rng: random.Random) -> list[int]:
    """Lượt 1: đúng delta thứ 50. Lượt 2–5: ngẫu nhiên. Lượt 6: ngắt HAI lần."""
    if i == 0:
        return [DELTA_NGAT_LUOT_DAU]
    if i == SO_LUOT - 1:
        mot = rng.randint(*KHOANG_NGAT_NGAU_NHIEN)
        return [mot, mot + rng.randint(*KHOANG_NGAT_NGAU_NHIEN)]
    return [rng.randint(*KHOANG_NGAT_NGAU_NHIEN)]


async def chay(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    model = args.model or _model_mac_dinh()
    dau_vet = f"t111-{uuid.uuid4().hex[:8]}"

    print(f"seed={args.seed}  model={model}  base={settings.PUBLIC_BASE_URL}  dau_vet={dau_vet}")

    pool = await asyncpg.create_pool(dev_database_url(), min_size=1, max_size=2)
    assert pool is not None
    user_id = await tao_user(pool, dau_vet)
    ket_qua: list[KetQua] = []

    try:
        async with httpx.AsyncClient(
            base_url=settings.PUBLIC_BASE_URL,
            headers={"X-User-Id": str(user_id)},
            verify=args.cacert or False,
            timeout=httpx.Timeout(TRAN_MOT_LUOT_S, read=TRAN_MOT_LUOT_S),
        ) as http:
            res = await http.post(
                "/api/v1/conversations",
                json={"title": f"S3 {dau_vet}", "default_model": model},
            )
            res.raise_for_status()
            conversation_id = uuid.UUID(res.json()["id"])

            do = PhepDo(http, pool, conversation_id, user_id, on_am=args.im_lang)
            for i in range(SO_LUOT):
                diem = diem_ngat_cua_luot(i, rng)
                ten = f"luot {i + 1}/{SO_LUOT} (ngat {len(diem)} lan tai {diem})"
                print(f"\n▶ {ten}", flush=True)
                kq = await do.chay(ten, diem)
                ket_qua.append(kq)
                print(
                    f"{'✓ PASS' if kq.dat else '✗ FAIL'}  {kq.ly_do}  "
                    f"(nhan {kq.nhan_duoc} byte / db {kq.trong_db} byte, {kq.giay:.1f}s)",
                    flush=True,
                )
    finally:
        if args.khong_don_dep:
            print(f"\n(giữ lại dữ liệu: user_id={user_id})")
        else:
            so_msg, so_ht = await don_dep(pool, user_id)
            print(f"\nđã dọn: {so_msg} message, {so_ht} hội thoại, 1 user")
        await pool.close()

    return in_tong_ket(ket_qua)


def _model_mac_dinh() -> str:
    mac_dinh = next((m for m in get_catalog().models if m.default and m.enabled), None)
    if mac_dinh is None:
        raise SystemExit("catalog không có model `default` nào đang bật (§9.2)")
    return mac_dinh.id


def in_tong_ket(ket_qua: list[KetQua]) -> int:
    dat = sum(1 for k in ket_qua if k.dat)
    print("\n" + "═" * 74)
    for k in ket_qua:
        dau = "PASS" if k.dat else "FAIL"
        print(f"  {dau}  {k.ten}: {k.ly_do}")
    print("═" * 74)
    # Dòng này là thứ DoD của T-1.11 đọc. `PASS 6/6` hay `FAIL 4/6`, một dòng.
    print(f"{'PASS' if dat == len(ket_qua) else 'FAIL'} {dat}/{len(ket_qua)}")
    return 0 if dat == len(ket_qua) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed", type=int, default=random.randrange(2**31), help="hạt giống điểm ngắt"
    )
    parser.add_argument("--model", default=None, help="mặc định: model `default` của catalog")
    parser.add_argument("--cacert", default=None, help="CA của mkcert; không có thì bỏ kiểm TLS")
    parser.add_argument("--khong-don-dep", action="store_true", help="giữ user/hội thoại lại")
    parser.add_argument("--im-lang", action="store_true", help="không in tiến trình từng lượt")
    return asyncio.run(chay(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
