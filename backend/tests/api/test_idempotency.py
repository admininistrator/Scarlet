"""§11.4 — `Idempotency-Key`, bốn dòng DoD của T-2.8 và các ngả hỏng (ADR-15).

Bốn dòng DoD nằm ở các test có chữ `DoD` trong docstring. Dòng 1 (S5) được đo
hai lần, cố ý:

* ở đây, bằng `asyncio.gather` trên cùng một app — bắt đúng ca hai request
  **chồng lấn** trong một tiến trình;
* và bằng `scripts/test_idempotency.sh` trên stack thật qua Nginx, nơi hai
  tiến trình `curl` bắn song song và Redis là Redis thật. Output của nó nằm
  trong báo cáo, không ở đây.

Cùng lối đi với `test_messages.py` (`ASGITransport`, `DEBUG` bật tay,
`session_scope()` trỏ về kết nối của test, pool arq giả). Khác một điểm: phần
lớn test ở đây **tự dựng client không có `event_hooks`**, vì fixture `client`
chung cố ý gắn một key mới cho mỗi POST (xem `tests/api/conftest.py`) còn ở
đây key là thứ đang được kiểm.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.messages import TEN_ROUTE_TAO_MESSAGE
from app.config.settings import settings
from app.core.idempotency import (
    HEADER_IDEMPOTENCY,
    HEADER_REPLAY,
    IDEM_PREFIX,
    RECORD_IN_PROGRESS,
    STATE_DONE,
    build_key,
)
from app.db.models import Conversation, Message
from app.db.repositories import ConversationRepository
from app.main import app

#: Kiểu thật là `tests.api.conftest.FakeIdempotencyRedis`, nhưng `tests/` không
#: phải package nên không import được tên đó ở đây (xem docstring conftest).
#: `make lint` chỉ chạy mypy trên `app/`, nên bí danh này không giấu gì cả.
RedisGia = Any

DUONG_DAN = "/api/v1/conversations/{}/messages"
DUONG_DAN_HUY = "/api/v1/messages/{}/cancel"


class ArqGia:
    """Pool arq giả — xem `tests/api/test_messages.py` cho lý do phải có."""

    def __init__(self) -> None:
        self.da_day: list[tuple[str, tuple[Any, ...]]] = []
        self.no_ra = False

    async def enqueue_job(self, ten: str, *args: Any, **_: Any) -> object | None:
        if self.no_ra:
            raise ConnectionError("redis chet giua chung (gia lap)")
        self.da_day.append((ten, args))
        return object()


@pytest.fixture
def _debug_bat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", True)


@pytest.fixture
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def arq_gia(monkeypatch: pytest.MonkeyPatch) -> ArqGia:
    gia = ArqGia()

    async def _pool() -> ArqGia:
        return gia

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return gia


@pytest.fixture
def _cancel_redis(monkeypatch: pytest.MonkeyPatch, idempotency_redis: RedisGia) -> None:
    """`POST /messages/{id}/cancel` đặt cờ `cancel:{id}` qua `messages.get_redis`.

    Đó là một client Redis **khác** với client của `core/idempotency.py` (xem
    `core/redis.py`: producer và consumer cấu hình khác nhau), nên fixture
    autouse của conftest không chạm tới nó. Dùng lại đúng một object giả cho cả
    hai: hai không gian khoá (`cancel:` và `idem:`) không giẫm lên nhau, và mọi
    assert trong file này chỉ đọc khoá `idem:`.
    """
    monkeypatch.setattr("app.api.v1.messages.get_redis", lambda: idempotency_redis)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """KHÔNG `event_hooks` — ở đây `Idempotency-Key` là thứ đang được kiểm."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        yield http


async def _tao_hoi_thoai(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> Conversation:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        await session.commit()
        return conversation


async def _dem_message(
    session_factory: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> int:
    async with session_factory() as session:
        stmt = (
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        return int((await session.execute(stmt)).scalar_one())


def _headers(user_id: uuid.UUID, key: str | None = None) -> dict[str, str]:
    headers = {"X-User-Id": str(user_id)}
    if key is not None:
        headers[HEADER_IDEMPOTENCY] = key
    return headers


# ══════════════════ định dạng khoá — §11.4 dòng đầu tiên ═══════════════════


def test_khoa_dung_dinh_dang_cua_11_4() -> None:
    """`idem:{user_id}:{route}:{idempotency_key}`, không phải một biến thể."""
    user_id = uuid.uuid4()

    key = build_key(user_id, TEN_ROUTE_TAO_MESSAGE, "abc")

    assert key == f"{IDEM_PREFIX}{user_id}:{TEN_ROUTE_TAO_MESSAGE}:abc"


def test_hai_user_cung_key_client_la_hai_khoa() -> None:
    """`{user_id}` đứng đầu khoá vì đúng lý do này (§20: không rò sang nhau)."""
    assert build_key(uuid.uuid4(), TEN_ROUTE_TAO_MESSAGE, "abc") != build_key(
        uuid.uuid4(), TEN_ROUTE_TAO_MESSAGE, "abc"
    )


def test_hai_route_cung_key_client_la_hai_khoa() -> None:
    assert build_key(uuid.uuid4(), "create_message", "abc") != build_key(
        uuid.uuid4(), "cancel_message", "abc"
    )


# ════════════════ DoD dòng 1 (S5) — hai request SONG SONG ══════════════════


async def test_hai_request_song_song_cung_key_chi_tao_mot_message(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """DoD dòng 1 / S5: 2 request song song ⇒ 1 tạo mới, 1 là `409` hoặc bản
    phát lại; DB có **đúng 2** message (một cặp user+assistant của MỘT lượt).

    "Đúng 1 message" của dòng DoD là **một lượt gửi**; §7.2 ① ghi mỗi lượt là
    hai hàng (user + assistant `queued`), nên con số kiểm ở đây là 2. Không có
    idempotency thì nó là 4.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    headers = _headers(user_a, "mot-lan-soan-thao")
    duong_dan = DUONG_DAN.format(conversation.id)

    mot, hai = await asyncio.gather(
        client.post(duong_dan, headers=headers, json={"content": "a"}),
        client.post(duong_dan, headers=headers, json={"content": "a"}),
    )

    ma = sorted([mot.status_code, hai.status_code])
    assert ma in ([202, 202], [202, 409]), (mot.text, hai.text)
    if ma == [202, 202]:
        # Request thứ hai tới sau khi thứ nhất đã xong ⇒ bản phát lại.
        assert mot.json() == hai.json()
    else:
        thua = mot if mot.status_code == 409 else hai
        assert thua.json()["error"]["code"] == "IN_PROGRESS"

    assert await _dem_message(session_factory, conversation.id) == 2
    assert len(arq_gia.da_day) == 1


async def test_dang_chay_tra_409_in_progress(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    idempotency_redis: RedisGia,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """§11.4: `state == in_progress` ⇒ `409 {code:"IN_PROGRESS"}`.

    Dựng thẳng bản ghi `in_progress` trong Redis thay vì đua hai request:
    ca "chồng lấn thật" đã có test trên, còn ca này phải **xác định** để mã lỗi
    được khẳng định chứ không phải "một trong hai khả năng".
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    key = build_key(user_a, TEN_ROUTE_TAO_MESSAGE, "dang-chay")
    idempotency_redis.store[key] = RECORD_IN_PROGRESS

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers=_headers(user_a, "dang-chay"),
        json={"content": "a"},
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "IN_PROGRESS"
    assert await _dem_message(session_factory, conversation.id) == 0
    assert arq_gia.da_day == []


# ═══════ DoD dòng 2 — gửi lại sau khi xong: cùng response, không thêm dòng ══


async def test_gui_lai_sau_khi_xong_tra_cung_response(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """DoD dòng 2: cùng response, DB **không** thêm dòng, job **không** thêm.

    `202` chứ không `200` — phiên T-2.8 chốt vế "trả lại nguyên response đã
    lưu" của §11.4 (xem docstring `app/core/idempotency.py`), và
    `Idempotent-Replay: true` là thứ phân biệt hai lần gọi.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    headers = _headers(user_a, "khoa-xong-roi")
    duong_dan = DUONG_DAN.format(conversation.id)

    mot = await client.post(duong_dan, headers=headers, json={"content": "a"})
    hai = await client.post(duong_dan, headers=headers, json={"content": "a"})

    assert mot.status_code == 202
    assert hai.status_code == 202
    assert mot.json() == hai.json()
    assert mot.headers["content-type"] == hai.headers["content-type"]
    assert HEADER_REPLAY not in mot.headers
    assert hai.headers[HEADER_REPLAY] == "true"
    assert await _dem_message(session_factory, conversation.id) == 2
    assert len(arq_gia.da_day) == 1


async def test_body_khac_cung_key_van_tra_response_cu(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Khoá là `Idempotency-Key`, KHÔNG phải hash nội dung (ADR-15).

    ADR-15 loại thẳng "dedupe bằng hash nội dung" vì gửi cùng một câu hỏi hai
    lần **một cách cố ý** là hợp lệ. Mặt còn lại của cùng quyết định: dùng lại
    một key cho nội dung khác thì nhận lại response cũ — đó là lỗi của client,
    và C22 nói đúng cách sửa (đổi key sau mỗi lần gửi thành công).
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    headers = _headers(user_a, "key-bi-dung-lai")
    duong_dan = DUONG_DAN.format(conversation.id)

    mot = await client.post(duong_dan, headers=headers, json={"content": "cau hoi mot"})
    hai = await client.post(duong_dan, headers=headers, json={"content": "cau hoi HAI"})

    assert mot.json() == hai.json()
    assert await _dem_message(session_factory, conversation.id) == 2


async def test_key_khac_thi_tao_luot_moi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Chiều ngược lại của test trên: key mới ⇒ lượt mới, không bị chặn nhầm."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    duong_dan = DUONG_DAN.format(conversation.id)

    mot = await client.post(duong_dan, headers=_headers(user_a, "key-1"), json={"content": "a"})
    hai = await client.post(duong_dan, headers=_headers(user_a, "key-2"), json={"content": "b"})

    assert mot.status_code == hai.status_code == 202
    assert mot.json()["assistant_message_id"] != hai.json()["assistant_message_id"]
    assert await _dem_message(session_factory, conversation.id) == 4
    assert len(arq_gia.da_day) == 2


async def test_key_cua_user_khac_khong_dung_chung_duoc(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """§20 — `{user_id}` trong khoá không phải trang trí.

    Hai người dùng chọn trùng một chuỗi key (rất dễ xảy ra nếu FE sinh key theo
    nội dung hoặc theo số thứ tự) không được nhìn thấy response của nhau.
    """
    hoi_thoai_a = await _tao_hoi_thoai(session_factory, user_a)
    hoi_thoai_b = await _tao_hoi_thoai(session_factory, user_b)

    a = await client.post(
        DUONG_DAN.format(hoi_thoai_a.id), headers=_headers(user_a, "trung"), json={"content": "a"}
    )
    b = await client.post(
        DUONG_DAN.format(hoi_thoai_b.id), headers=_headers(user_b, "trung"), json={"content": "b"}
    )

    assert a.status_code == b.status_code == 202
    assert HEADER_REPLAY not in b.headers
    assert a.json()["assistant_message_id"] != b.json()["assistant_message_id"]


# ════════════ DoD dòng 3 — thiếu header ở `POST .../messages` ═══════════════


async def test_thieu_header_tra_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """DoD dòng 3 + A8: bắt buộc với `POST /conversations/{id}/messages`."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN.format(conversation.id), headers=_headers(user_a), json={"content": "a"}
    )

    assert resp.status_code == 400
    body = resp.json()["error"]
    assert body["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert body["details"]["header"] == HEADER_IDEMPOTENCY
    assert await _dem_message(session_factory, conversation.id) == 0
    assert arq_gia.da_day == []


async def test_header_rong_cung_la_thieu(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`Idempotency-Key: "   "` không phải một key.

    Nếu để lọt, mọi client gửi header rỗng sẽ dùng chung **một** khoá
    `idem:{uid}:create_message:` — tức người dùng tự khoá chính mình 24 giờ sau
    lượt chat đầu tiên.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers=_headers(user_a, "   "),
        json={"content": "a"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_endpoint_khac_khong_bat_buoc_header(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    _cancel_redis: None,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Nửa "tuỳ chọn với endpoint khác" — `POST /messages/{id}/cancel` không đòi.

    Bấm Dừng mà bị `400` vì thiếu một header là đúng thứ §7.5 không cho phép:
    lượt sinh vẫn chảy và người dùng vẫn trả tiền cho nó.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    tao = await client.post(
        DUONG_DAN.format(conversation.id),
        headers=_headers(user_a, "de-co-message"),
        json={"content": "a"},
    )
    amid = tao.json()["assistant_message_id"]

    resp = await client.post(DUONG_DAN_HUY.format(amid), headers=_headers(user_a))

    assert resp.status_code == 200, resp.text


async def test_endpoint_khac_van_ap_luat_khi_co_header(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    _cancel_redis: None,
    idempotency_redis: RedisGia,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Nửa còn lại của "tuỳ chọn": có gửi header thì luật §11.4 vẫn chạy."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    tao = await client.post(
        DUONG_DAN.format(conversation.id),
        headers=_headers(user_a, "de-co-message"),
        json={"content": "a"},
    )
    amid = tao.json()["assistant_message_id"]

    mot = await client.post(DUONG_DAN_HUY.format(amid), headers=_headers(user_a, "huy-mot-lan"))
    hai = await client.post(DUONG_DAN_HUY.format(amid), headers=_headers(user_a, "huy-mot-lan"))

    assert mot.status_code == 200
    assert hai.headers[HEADER_REPLAY] == "true"
    assert mot.json() == hai.json()
    assert build_key(user_a, "cancel_message", "huy-mot-lan") in idempotency_redis.store


# ═══════════════════════ DoD dòng 4 — TTL ≈ 86400 ═══════════════════════════


async def test_ttl_cua_khoa_bang_cau_hinh(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    idempotency_redis: RedisGia,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """DoD dòng 4: `TTL idem:...` ≈ 86400 — và TTL được đặt lại lúc ghi `done`.

    Con số đọc từ `settings.IDEMPOTENCY_TTL_S` chứ không gõ `86400` vào đây:
    A3 — đó là một *giới hạn*, và một test gõ số sẽ xanh cả khi `.env` đặt giá
    trị khác, tức đo một hệ thống không ai đang chạy.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    key = build_key(user_a, TEN_ROUTE_TAO_MESSAGE, "co-ttl")

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers=_headers(user_a, "co-ttl"),
        json={"content": "a"},
    )

    assert resp.status_code == 202
    assert idempotency_redis.ttl[key] == settings.IDEMPOTENCY_TTL_S == 86400
    ban_ghi = json.loads(idempotency_redis.store[key])
    assert ban_ghi["state"] == STATE_DONE
    assert ban_ghi["response"]["status"] == 202
    assert json.loads(ban_ghi["response"]["body"]) == resp.json()


# ═══════════════ lỗi thì NHẢ khoá, không lưu (xem docstring module) ═════════


async def test_loi_503_nha_khoa_de_gui_lai_duoc(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    idempotency_redis: RedisGia,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """C22: một `503 ENQUEUE_FAILED` **không** được khoá lần soạn thảo 24 giờ.

    FE chỉ đổi key sau khi gửi thành công, nên nếu response lỗi được lưu thành
    `done` thì người dùng nhận đúng câu 503 ấy mãi mãi — bấm Gửi bao nhiêu lần
    cũng vậy, và không có gì trong giao diện giải thích tại sao.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    duong_dan = DUONG_DAN.format(conversation.id)
    headers = _headers(user_a, "lan-dau-that-bai")
    key = build_key(user_a, TEN_ROUTE_TAO_MESSAGE, "lan-dau-that-bai")

    arq_gia.no_ra = True
    hong = await client.post(duong_dan, headers=headers, json={"content": "a"})

    assert hong.status_code == 503
    assert key not in idempotency_redis.store

    arq_gia.no_ra = False
    lai = await client.post(duong_dan, headers=headers, json={"content": "a"})

    assert lai.status_code == 202
    assert HEADER_REPLAY not in lai.headers
    assert await _dem_message(session_factory, conversation.id) == 2


async def test_body_sai_422_cung_nha_khoa(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    idempotency_redis: RedisGia,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Cùng luật cho `422`: gõ thiếu rồi gửi lại **không** phải bấm F5 trang."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    duong_dan = DUONG_DAN.format(conversation.id)
    headers = _headers(user_a, "body-sai")
    key = build_key(user_a, TEN_ROUTE_TAO_MESSAGE, "body-sai")

    hong = await client.post(duong_dan, headers=headers, json={"content": ""})

    assert hong.status_code == 422
    assert key not in idempotency_redis.store

    lai = await client.post(duong_dan, headers=headers, json={"content": "a"})

    assert lai.status_code == 202


async def test_redis_chet_tra_503_va_khong_ghi_gi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    idempotency_redis: RedisGia,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Không hỏi được Redis ⇒ `503`, KHÔNG cho qua.

    Cho qua nghĩa là gỡ đúng lớp chống trùng vào lúc hệ thống đang hỏng — tức
    lúc người dùng bấm Gửi lại nhiều nhất. Cùng lối `core/deps.py` (blacklist)
    và `core/ratelimit.py`.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    idempotency_redis.fail = True

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers=_headers(user_a, "redis-chet"),
        json={"content": "a"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert await _dem_message(session_factory, conversation.id) == 0
    assert arq_gia.da_day == []


async def test_ban_ghi_hong_thi_tra_409_chu_khong_tao_them(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    idempotency_redis: RedisGia,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """JSON hỏng trong Redis ⇒ `409`, hỏng về phía **không tính tiền hai lần**."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    key = build_key(user_a, TEN_ROUTE_TAO_MESSAGE, "ban-ghi-hong")
    idempotency_redis.store[key] = "{khong-phai-json"

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers=_headers(user_a, "ban-ghi-hong"),
        json={"content": "a"},
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "IN_PROGRESS"
    assert await _dem_message(session_factory, conversation.id) == 0


# ═════════════ middleware KHÔNG được đụng vào đường SSE (§7, C1) ═══════════


async def test_get_khong_di_qua_lop_gom_body(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    idempotency_redis: RedisGia,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`GET` mang cả header vẫn đi thẳng: không khoá, không bản ghi nào.

    §11.4 chỉ nói về POST, và quan trọng hơn: đường SSE của §7 là một `GET` có
    thể mở hàng giờ — gom thân response của nó là một rò rỉ bộ nhớ, và đệm nó
    là C1 quay lại.
    """
    await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.get("/api/v1/conversations", headers=_headers(user_a, "khoa-cho-get"))

    assert resp.status_code == 200
    assert idempotency_redis.store == {}
