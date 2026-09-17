"""Idempotency của §11.4 — chống double-click và chống retry tầng mạng (T-2.8).

KH tham chiếu: §11.4, §7.2 ①, ADR-15, C22, S5 · CLAUDE.md A8 · tasks.md T-2.8.

§11.4 viết ra đúng năm dòng giả mã, và cả file này là chúng:

    key = idem:{user_id}:{route}:{idempotency_key}
    SET key '{"state":"in_progress"}' NX EX 86400
      → NX thất bại: in_progress → 409 · done → trả lại response đã lưu
      → NX thành công: xử lý, rồi SET key '{"state":"done","response":{…}}'

╔══════════════════════════════════════════════════════════════════════════╗
║  MỘT LUẬT, HAI MẢNH — VÌ SAO KHÔNG PHẢI MỘT MIDDLEWARE DUY NHẤT          ║
╚══════════════════════════════════════════════════════════════════════════╝

Task gọi đây là "middleware", nhưng khoá của §11.4 mở đầu bằng `{user_id}` —
mà một lớp ASGI chạy **trước khi định tuyến**, tức trước khi cookie phiên được
giải mã và trước khi blacklist §11.3 được hỏi. Muốn tự biết `user_id`, nó phải
chép lại toàn bộ luật danh tính của `app/core/deps.py` lần thứ hai: hai chỗ
cùng biết một luật, và chỗ nào cũng có thể sai một mình. Đây đúng là lý lẽ
T-2.4 đã dùng khi §11.3 cũng gọi blacklist là "middleware" mà code đặt nó ở
`deps.py` — xem docstring ở đó.

Nên phép kiểm tách làm hai mảnh, mỗi mảnh làm đúng việc **chỉ nó làm được**:

* `require_idempotency(...)` — **dependency**. Nó có `user_id` (qua
  `Depends(get_current_user_id)`, dùng lại đúng một luật danh tính) và có tên
  route (FastAPI đặt `scope["route"]` xong trước khi dependency chạy). Nó làm
  `SET NX`, trả `409`, hoặc phát lại response cũ.
* `IdempotencyMiddleware` — **lớp ASGI thuần**. Nó là chỗ duy nhất nhìn thấy
  *response đã hoàn chỉnh* để ghi `state=done`. Một dependency không bao giờ
  cầm được response: FastAPI dựng nó **sau** khi mọi dependency đã kết thúc.

Cả hai sống trong file này, nên §11.4 vẫn ở **đúng một chỗ**: định dạng khoá,
hai trạng thái, TTL, danh sách route bắt buộc — đọc hết trong một màn hình.

**Gắn ở `include_router`, không rải vào từng route.** Cùng bài học với
`require_app_access` của T-2.7: POST thứ mười hai của `conversations.py` phải
được bảo vệ vì nó nằm trong router, không phải vì ai đó nhớ chép thêm một dòng.
Dependency tự bỏ qua mọi method khác `POST` (§11.4 chỉ nói về POST), nên gắn
cho cả router không làm `GET` nào trả giá.

┌──────────────────────────────────────────────────────────────────────────┐
│  VÌ SAO KHÔNG GẮN CHO `auth`                                             │
└──────────────────────────────────────────────────────────────────────────┘

`register`/`login`/`refresh` là POST **chưa có ai đăng nhập**, nên
`Depends(get_current_user_id)` ở đó sẽ ném `401` cho chính những request phải
đi qua. Khoá của §11.4 có `{user_id}` ở đầu ⇒ luật này chỉ áp được cho mặt API
đã xác thực. Ba router `stream`/`conversations`/`messages` — đúng những router
đã mang `require_app_access` — là toàn bộ vùng phủ hôm nay.

┌──────────────────────────────────────────────────────────────────────────┐
│  LỖI THÌ NHẢ KHOÁ, KHÔNG LƯU (quyết định của phiên T-2.8)                │
└──────────────────────────────────────────────────────────────────────────┘

Chỉ response `< 400` mới thành `state=done`; mọi response lỗi làm khoá bị
**xoá**. Lý do nằm ở C22: FE chỉ đổi `Idempotency-Key` **sau khi gửi thành
công**, nên nếu một `503 ENQUEUE_FAILED` (Redis chớp tắt) được lưu lại thì lần
soạn thảo ấy nhận đúng câu 503 đó trong **24 giờ** — người dùng không bao giờ
gửi được câu hỏi vừa gõ, và không có nút nào để thoát ra. Nhả khoá thì lần bấm
Gửi tiếp theo đi tiếp bình thường; cái giá là hai request lỗi **song song**
cùng key có thể cùng được thử lại, mà một request lỗi thì chưa tạo ra gì.

┌──────────────────────────────────────────────────────────────────────────┐
│  PHÁT LẠI GIỮ NGUYÊN STATUS GỐC (202), KÈM `Idempotent-Replay: true`     │
└──────────────────────────────────────────────────────────────────────────┘

§11.4 viết "trả lại nguyên response đã lưu, status 200" — hai vế tự mâu thuẫn,
vì response đã lưu của `POST .../messages` mang status `202` (§7.2 ①). DoD dòng
2 của T-2.8 cũng đòi "**cùng** response". Phiên T-2.8 chốt vế "nguyên response
đã lưu": phát lại đúng status, đúng body, đúng `Content-Type` — FE T-3.4 chỉ
cần một nhánh xử lý, và `stream_url` trong body cũ vẫn gọi được ngay. Vế "status
200" đổi lấy một header: `Idempotent-Replay: true` cho ai cần phân biệt.

**Định danh tiếng Anh** theo mục "Không bao giờ" của CLAUDE.md, cùng luật mà
T-2.7 đã áp cho code mới; phần code cũ là B-142, chờ người quyết.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, status
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config.settings import settings
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

#: Header client gửi lên (ADR-15: "client sinh UUID v4"). Backend **không**
#: kiểm nó có phải UUID hay không: §11.4 chỉ dùng nó làm một phần của khoá, và
#: một client hợp lệ nhưng sinh key theo cách khác (ULID, hash của lần soạn
#: thảo) không có lý do gì bị từ chối. Thứ duy nhất bị chặn là **rỗng**.
HEADER_IDEMPOTENCY = "Idempotency-Key"

#: Header đánh dấu một response là bản phát lại — xem docstring module.
HEADER_REPLAY = "Idempotent-Replay"

#: Tiền tố khoá của §11.4. Cùng luật với `RL_IP_PREFIX` (`core/ratelimit.py`)
#: và `cancel_key()` (`streaming/cancel.py`): không ai tự nối chuỗi, vì một
#: tiền tố gõ lệch là một phép chống trùng không bao giờ chặn ai — im lặng.
IDEM_PREFIX = "idem:"

#: §11.4 chỉ nói về POST. `PATCH /messages/{id}` cũng mở một lượt sinh tốn tiền
#: (§8.2) nhưng nó không nằm trong chữ của §11.4 — ghi Backlog, không tự mở rộng.
GUARDED_METHOD = "POST"

#: Hai trạng thái của §11.4, đúng chữ.
STATE_IN_PROGRESS = "in_progress"
STATE_DONE = "done"

#: Chỗ dependency báo cho middleware biết "request này đã thắng `SET NX`, và
#: đây là khoá phải ghi kết quả vào". Đi qua `request.state` (tức
#: `scope["state"]`) chứ không qua một biến module: một tiến trình `api` phục
#: vụ nhiều request đồng thời, và một biến module là chỗ hai người dùng ghi đè
#: khoá của nhau.
STATE_ATTR_KEY = "scarlet_idem_key"

#: Bản ghi lúc giành được khoá. `separators` để hai lần dump cùng nội dung ra
#: cùng chuỗi — bản ghi này bị so trong test.
RECORD_IN_PROGRESS = json.dumps({"state": STATE_IN_PROGRESS}, separators=(",", ":"))

#: Số lần thử `SET NX` trước khi bỏ cuộc. >1 vì đúng một ca: khoá hết hạn (hoặc
#: bị nhả vì lỗi) **giữa** `SET NX` và `GET`, nên `GET` trả `None` và không có
#: bản ghi nào để đọc. Lúc đó đường đúng là giành lại, không phải đoán.
CLAIM_ATTEMPTS = 2


def build_key(user_id: uuid.UUID, route_name: str, client_key: str) -> str:
    """`idem:{user_id}:{route}:{idempotency_key}` — đúng chữ §11.4.

    `route` là **tên route** của FastAPI (`create_message`), không phải đường
    dẫn: đường dẫn mang `{conversation_id}` nên hai hội thoại sẽ thành hai
    khoá, và khi ấy một `Idempotency-Key` bị FE dùng lại ở hội thoại khác sẽ
    lọt qua. Tên route cũng miễn nhiễm với việc đổi tiền tố `/api/v1` — thứ
    sống ở `api/v1/__init__.py` và không được chép sang file thứ hai.
    """
    return f"{IDEM_PREFIX}{user_id}:{route_name}:{client_key}"


class ReplayStoredResponse(Exception):
    """Ném từ dependency để trả lại response đã lưu (§11.4, `state == done`).

    Là một ngoại lệ chứ không phải một giá trị trả về vì dependency không có
    đường nào khác để **thay** response của handler: FastAPI gọi handler ngay
    sau khi dependency trả về bình thường. Không kế thừa `ApiError`: đây không
    phải lỗi — nó là một `202` thành công, chỉ là đã xảy ra từ lần trước.
    """

    def __init__(self, status_code: int, body: bytes, media_type: str | None) -> None:
        super().__init__(f"phat lai response da luu (status {status_code})")
        self.status_code = status_code
        self.body = body
        self.media_type = media_type


async def replay_exception_handler(request: Request, exc: Exception) -> Response:
    """`ReplayStoredResponse` → response cũ nguyên văn + `Idempotent-Replay`."""
    if not isinstance(exc, ReplayStoredResponse):  # pragma: no cover - register() giữ kiểu
        raise exc
    return Response(
        content=exc.body,
        status_code=exc.status_code,
        media_type=exc.media_type,
        headers={HEADER_REPLAY: "true"},
    )


def register(app: FastAPI) -> None:
    """Gắn handler phát lại. `main.py` gọi một lần lúc dựng app."""
    app.add_exception_handler(ReplayStoredResponse, replay_exception_handler)


def _route_name(request: Request) -> str:
    """Tên route FastAPI đã khớp. Rỗng nghĩa là không route nào khớp."""
    route = request.scope.get("route")
    name = getattr(route, "name", "")
    return name if isinstance(name, str) else ""


def _redis_unavailable(key: str) -> ApiError:
    """Không hỏi được Redis ⇒ `503`, KHÔNG cho qua.

    Cùng lý lẽ với blacklist (`core/deps.py`) và rate limit
    (`core/ratelimit.py`): cho qua là gỡ đúng lớp chống trùng vào lúc hệ thống
    đang hỏng — tức lúc người dùng bấm Gửi lại nhiều nhất. Redis vốn là phụ
    thuộc cứng của app (A1), nên "Redis chết mà API vẫn tạo message" không
    phải một trạng thái có thật để bảo vệ.
    """
    logger.exception("khong hoi duoc redis cho khoa idempotency %s", key)
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        ApiErrorCode.SERVICE_UNAVAILABLE,
        "khong kiem duoc idempotency key, hay thu lai",
    )


async def _claim_key(key: str) -> dict[str, Any] | None:
    """`SET NX EX` của §11.4. `None` = mình là chủ; ngược lại trả bản ghi cũ.

    Bản ghi đọc không ra (JSON hỏng, hoặc không phải object) được coi là
    `in_progress` — tức `409`. Hỏng về phía **không tạo thêm message**: một
    `409` thừa làm người dùng bấm lại, còn đoán nhầm theo chiều kia là tính
    tiền hai lần cho một câu hỏi.
    """
    redis = get_redis()
    for _ in range(CLAIM_ATTEMPTS):
        try:
            claimed = await redis.set(
                key, RECORD_IN_PROGRESS, nx=True, ex=settings.IDEMPOTENCY_TTL_S
            )
        except Exception as loi:
            raise _redis_unavailable(key) from loi
        if claimed:
            return None

        try:
            raw = await redis.get(key)
        except Exception as loi:
            raise _redis_unavailable(key) from loi
        if raw is None:
            # Khoá vừa hết hạn (hoặc vừa bị nhả vì lần trước lỗi) giữa SET và
            # GET. Không có gì để đọc ⇒ thử giành lại, đừng đoán.
            continue

        try:
            record = json.loads(raw)
        except ValueError:
            logger.warning("ban ghi idempotency hong, coi nhu dang chay: %s", key)
            return {"state": STATE_IN_PROGRESS}
        if not isinstance(record, dict):
            logger.warning("ban ghi idempotency sai kieu, coi nhu dang chay: %s", key)
            return {"state": STATE_IN_PROGRESS}
        return record

    logger.warning("khong gianh duoc khoa idempotency sau %d lan: %s", CLAIM_ATTEMPTS, key)
    return {"state": STATE_IN_PROGRESS}


def _replay_from(record: dict[str, Any]) -> ReplayStoredResponse:
    """Dựng `ReplayStoredResponse` từ một bản ghi `done` đã lưu."""
    stored = record.get("response")
    stored = stored if isinstance(stored, dict) else {}
    status_code = stored.get("status")
    body = stored.get("body")
    return ReplayStoredResponse(
        status_code=status_code if isinstance(status_code, int) else status.HTTP_200_OK,
        body=body.encode("utf-8") if isinstance(body, str) else b"",
        media_type=stored.get("media_type") or None,
    )


def require_idempotency(required_routes: frozenset[str]) -> Callable[..., Awaitable[None]]:
    """Dựng dependency §11.4 cho một nhóm router.

    Args:
        required_routes: **tên route** (không phải đường dẫn) mà
            `Idempotency-Key` là bắt buộc — A8 gọi đích danh
            `POST /conversations/{id}/messages`. Mọi POST khác: có header thì
            áp luật, không có thì đi tiếp ("tuỳ chọn với endpoint khác").

    Raise (trong dependency dựng ra):
        ApiError 400 `IDEMPOTENCY_KEY_REQUIRED`: route bắt buộc mà thiếu header.
        ApiError 409 `IN_PROGRESS`: một request cùng khoá còn đang chạy.
        ApiError 503 `SERVICE_UNAVAILABLE`: không hỏi được Redis.
        ReplayStoredResponse: khoá đã `done` — trả lại response cũ.
    """

    async def _check(
        request: Request,
        user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    ) -> None:
        if request.method != GUARDED_METHOD:
            return

        route_name = _route_name(request)
        client_key = (request.headers.get(HEADER_IDEMPOTENCY) or "").strip()
        if not client_key:
            if route_name in required_routes:
                raise ApiError(
                    status.HTTP_400_BAD_REQUEST,
                    ApiErrorCode.IDEMPOTENCY_KEY_REQUIRED,
                    f"thieu header {HEADER_IDEMPOTENCY}",
                    details={"header": HEADER_IDEMPOTENCY},
                )
            return

        key = build_key(user_id, route_name, client_key)
        record = await _claim_key(key)
        if record is None:
            # Mình là chủ khoá. Middleware đọc chỗ này để biết ghi kết quả vào đâu.
            setattr(request.state, STATE_ATTR_KEY, key)
            return

        if record.get("state") == STATE_DONE:
            logger.info("idempotency: phat lai response da luu cho %s", key)
            raise _replay_from(record)

        logger.info("idempotency: %s con dang chay, tra 409", key)
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ApiErrorCode.IN_PROGRESS,
            "mot request cung Idempotency-Key dang duoc xu ly",
        )

    return _check


async def store_result(key: str, status_code: int, body: bytes, media_type: str | None) -> None:
    """`SET key '{"state":"done","response":{…}}' EX 86400` — §11.4 vế cuối.

    `SET` trần chứ không `NX`: khoá đang giữ bản ghi `in_progress` của chính
    request này, và mục đích của lệnh là đè lên nó. TTL đặt lại từ đầu, nên 24
    giờ tính từ lúc **xong**, không phải từ lúc bắt đầu.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        # Không phải JSON/chữ (chưa endpoint nào như vậy). Không lưu được thì
        # nhả khoá, đừng để lại một bản ghi `in_progress` sống 24 giờ.
        logger.warning("response cua %s khong phai utf-8, khong luu duoc — nha khoa", key)
        await release_key(key)
        return

    record = {
        "state": STATE_DONE,
        "response": {"status": status_code, "body": text, "media_type": media_type},
    }
    try:
        await get_redis().set(
            key, json.dumps(record, separators=(",", ":")), ex=settings.IDEMPOTENCY_TTL_S
        )
    except Exception:
        # Response đã đi khỏi server rồi, không đổi được nữa. Ghi log rồi thôi:
        # hậu quả là lần gửi lại cùng key sẽ tạo message thứ hai — đúng hành vi
        # của thời chưa có file này, không tệ hơn.
        logger.exception("khong luu duoc ket qua idempotency cho %s", key)


async def release_key(key: str) -> None:
    """Xoá khoá — dùng cho mọi response lỗi. Xem docstring module."""
    try:
        await get_redis().delete(key)
    except Exception:
        logger.exception("khong nha duoc khoa idempotency %s", key)


def _has_idempotency_header(scope: Scope) -> bool:
    wanted = HEADER_IDEMPOTENCY.lower().encode("latin-1")
    return any(name == wanted for name, _ in scope["headers"])


def _content_type(message: Message) -> str | None:
    for name, value in message.get("headers", ()):
        if name.lower() == b"content-type":
            return str(value.decode("latin-1"))
    return None


class IdempotencyMiddleware:
    """Ghi `state=done` (hoặc nhả khoá) cho request đã thắng `SET NX`.

    **ASGI thuần, không `BaseHTTPMiddleware`** — cùng lý do đã ghi ở
    `core/origin.py`: `BaseHTTPMiddleware` bọc mọi response vào một
    `StreamingResponse` nội bộ, và đây là app có SSE (§7, A1).

    Lớp này **không** đụng tới request nào không phải `POST` có
    `Idempotency-Key`: chúng được forward thẳng `(scope, receive, send)`, không
    có hàm nào chèn vào giữa. Đường SSE (`GET /messages/{id}/stream`) vì vậy đi
    qua đây y như không có file này — quan trọng, vì gom thân response của một
    stream vô hạn là một rò rỉ bộ nhớ tính bằng giờ.

    Ngay cả với `POST` có header, thân response chỉ được gom khi dependency đã
    đặt khoá vào `request.state`: một `POST /auth/login` mang header thừa (hay
    một `403` của `core/origin.py` trả về trước cả router) không tốn byte nào.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != GUARDED_METHOD
            or not _has_idempotency_header(scope)
        ):
            await self.app(scope, receive, send)
            return

        # `Request.state` cũng `setdefault` đúng khoá này; đặt trước để cả hai
        # bên chắc chắn nhìn vào **một** dict.
        scope.setdefault("state", {})
        status_code: int | None = None
        media_type: str | None = None
        chunks: list[bytes] = []

        async def _send(message: Message) -> None:
            nonlocal status_code, media_type
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                media_type = _content_type(message)
            elif message["type"] == "http.response.body" and self._pending_key(scope) is not None:
                chunks.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except BaseException:
            # Ngoại lệ không ai bắt đi thẳng lên `ServerErrorMiddleware` (lớp
            # ngoài cùng) nên `_send` không thấy response nào. Nhả khoá ở đây,
            # nếu không một lỗi lập trình sẽ khoá lần soạn thảo đó 24 giờ.
            await self._release_if_any(scope)
            raise

        key = self._pending_key(scope)
        if key is None:
            return
        if status_code is not None and status_code < status.HTTP_400_BAD_REQUEST:
            await store_result(key, status_code, b"".join(chunks), media_type)
        else:
            await release_key(key)

    @staticmethod
    def _pending_key(scope: Scope) -> str | None:
        key = scope.get("state", {}).get(STATE_ATTR_KEY)
        return key if isinstance(key, str) else None

    async def _release_if_any(self, scope: Scope) -> None:
        key = self._pending_key(scope)
        if key is not None:
            await release_key(key)
