"""Cài đặt cá nhân — BYOK CRUD (§18.4, §10.5) — T-2.14; `PUT /settings` — T-3.0.

KH tham chiếu: §10.5, §18.4, §9.2, §11.1, §19.1, §20, §23 `api/v1/settings.py` ·
Cạm bẫy C20, C42 · CLAUDE.md A3 · tasks.md T-2.14, T-3.0, B-206, NQ-79.

Ba endpoint của hàng "keys" trong bảng §18.4, cộng `PUT /settings` từ T-3.0.
`GET /settings` và `GET /settings/usage` **chưa** có task nào — không dựng sẵn.

┌──────────────────────────────────────────────────────────────────────────┐
│  `PUT /settings` CÓ, `GET /settings` KHÔNG — và đó là một quyết định      │
└──────────────────────────────────────────────────────────────────────────┘

§18.4 ghi `GET/PUT /settings` trên cùng một hàng, nhưng T-3.0 chỉ dựng vế
`PUT`. Lý do: vế `GET` đã có người trả lời rồi. `default_model` — hôm nay là
**toàn bộ** nội dung của "cài đặt cá nhân" ở tầng server — đi ra trong
`GET /auth/me` (§18.1, NQ-81), và theme thì sống trong `localStorage` từ
T-0.10. Một `GET /settings` hôm nay vì thế là endpoint thứ hai trả lời đúng
một câu hỏi, tức chỗ đầu tiên để hai câu trả lời lệch nhau.

Tên endpoint giữ nguyên chữ của §18.4 để tuỳ chọn thứ hai ghép thẳng vào đây
mà không phải đổi đường dẫn — và đó cũng là lúc `GET /settings` có việc để làm.

┌──────────────────────────────────────────────────────────────────────────┐
│  BẢN RÕ SỐNG ĐÚNG MỘT LẦN, TRONG ĐÚNG MỘT HÀM                            │
└──────────────────────────────────────────────────────────────────────────┘

`put_provider_key` là chỗ **duy nhất** trong toàn backend mà một khoá BYOK tồn
tại ở dạng bản rõ, và nó rời khỏi hàm theo đúng ba đường, cả ba đều đã che:
`crypto.seal()` (thành bản mã), `crypto.mask_secret()` (thành `sk-...4f2a`),
và `byok_verify.verify_key()` (thành một header gửi đi, không vào log).

Vì vậy ở đây **không** có `logger` nào. Một module không có logger là một
module không thể log nhầm — rẻ hơn và chắc hơn mọi lời dặn "nhớ đừng log biến
này" (C20). Những gì đáng ghi lại (provider từ chối, catalog thiếu
`verify_path`) đã được `app/llm/byok_verify.py` ghi, ở chỗ không có bản rõ nào
trong tầm tay.

┌──────────────────────────────────────────────────────────────────────────┐
│  `GET` KHÔNG GIẢI MÃ ĐỂ HIỂN THỊ, NHƯNG CÓ GIẢI MÃ ĐỂ TRẢ LỜI `usable`   │
└──────────────────────────────────────────────────────────────────────────┘

Chuỗi che nằm sẵn trong `key_last4` (xem `db/models/user_provider_key.py`),
nên phần **hiển thị** không cần tới bản rõ. Nhưng DoD dòng 6 đòi một thứ khác:
*"đổi `MASTER_ENCRYPTION_KEY` → giải mã thất bại **có kiểm soát** (không phải
crash), báo user nhập lại"* — và trong phạm vi T-2.14 thì `GET /settings/keys`
là màn hình duy nhất có thể nói câu đó với người dùng (đường **dùng** khoá để
gọi model là T-2.15).

Vì vậy mỗi hàng đi qua một lần `unseal()` mà kết quả bị **vứt đi ngay**: thứ
duy nhất đi ra là `usable: bool`. Người vận hành xoay `MASTER_ENCRYPTION_KEY`
(hoặc khôi phục dump DB sang máy có `.env` khác) thì màn hình cài đặt hiện
"khoá không đọc được nữa, hãy nhập lại" thay vì một trang `500`.

Giá: một phép AES-GCM cho mỗi hàng mỗi lần mở màn cài đặt. Bảng này có tối đa
một hàng cho mỗi provider của catalog (UNIQUE `(user_id, provider)`), tức bốn
hàng ở cấu hình hôm nay.

┌──────────────────────────────────────────────────────────────────────────┐
│  TRẠNG THÁI TÀI KHOẢN: `require_app_access`, KHÔNG PHẢI `require_chat_*` │
└──────────────────────────────────────────────────────────────────────────┘

Router này nằm trong danh sách `_AUTHENTICATED` của `api/v1/__init__.py`, tức
cột "Xem UI" của §11.1. Điều đó là bắt buộc chứ không tiện tay:
`pending_approval` **phải** thêm được khoá riêng — bảng §11.1 cho họ chat bằng
BYOK, và cánh cửa đó chỉ mở khi có một hàng trong `user_provider_keys`. Chặn ở
đây bằng `require_chat_access` là khoá vòng: muốn có khoá thì phải đã có khoá.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.config import catalog
from app.config.catalog import Provider
from app.core.crypto import DecryptionError, Sealed, mask_secret, seal, unseal
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.db.models import UserProviderKey
from app.db.repositories import ProviderKeyRepository, UserRepository
from app.db.session import session_scope
from app.llm.byok_verify import VerifyOutcome, VerifyUnavailable, verify_key

router = APIRouter(prefix="/settings", tags=["settings"])

#: Câu trả lời cho mọi kiểu "khoá này không dùng được". Một hằng chứ không ba
#: chuỗi rải rác: nó là câu **không được phép** chứa khoá (C20, DoD dòng 4), và
#: một câu thì soi được bằng mắt trong ba giây.
_KEY_REJECTED_MSG = "provider tu choi khoa nay, hay kiem tra lai roi nhap lai"


class ProviderKeyOut(BaseModel):
    """Một khoá BYOK, dưới dạng UI được phép thấy (§10.5).

    KHÔNG có trường nào mang bản rõ, và không có trường nào mang bản mã: người
    dùng không làm gì được với `key_cipher`, còn một bản mã đi ra ngoài là một
    bản mã người ta mang đi thử phá ngoại tuyến.
    """

    model_config = ConfigDict(from_attributes=True)

    provider: str
    #: `sk-...4f2a` — §10.5. Đọc thẳng từ cột `key_last4`, xem model.
    masked_key: str
    #: `None` = đã lưu nhưng chưa kiểm được (C42) — FE hiện "chưa xác minh".
    verified_at: datetime | None
    created_at: datetime
    #: Giải mã được bằng `MASTER_ENCRYPTION_KEY` hiện tại hay không. `False` =
    #: bảo người dùng nhập lại — xem docstring module.
    usable: bool


class ByokProviderOut(BaseModel):
    """Một provider nhận khoá riêng — ô chọn của trang Cài đặt (T-3.12).

    `provider` là **khoá** catalog (thứ `PUT /settings/keys/{provider}` nhận),
    `label` là tên để hiện. Danh sách đến từ `byok_supported` trong catalog
    (§9.2), không từ một mảng gõ sẵn ở FE (A3): thêm một provider BYOK là sửa
    `model_catalog.json`, không phải sửa giao diện.
    """

    provider: str
    label: str


class ProviderKeyListOut(BaseModel):
    keys: list[ProviderKeyOut]
    #: Mọi provider `byok_supported` của catalog hiện tại, kể cả chưa có khoá.
    byok_providers: list[ByokProviderOut]


class ProviderKeyIn(BaseModel):
    """Body của `PUT /settings/keys/{provider}`.

    `min_length=1` chứ không một luật hình dạng nào: mỗi provider có định dạng
    khoá riêng, và chép luật ấy vào đây là đúng loại literal-của-provider mà
    A3 cấm. Phép kiểm thật là hỏi chính provider (§10.5).
    """

    key: str = Field(min_length=1)


def _find_provider(provider: str) -> Provider:
    """Provider trong catalog, hoặc `404`/`400` — §9.2, §10.5.

    Raises:
        ApiError 404 `PROVIDER_UNKNOWN`: không có trong `providers`.
        ApiError 400 `BYOK_NOT_SUPPORTED`: có, nhưng `byok_supported: false`.
    """
    record = catalog.get_catalog().providers.get(provider)
    if record is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.PROVIDER_UNKNOWN,
            "provider khong co trong catalog",
            details={"provider": provider},
        )
    if not record.byok_supported:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.BYOK_NOT_SUPPORTED,
            "provider nay khong dung duoc khoa API rieng",
            details={"provider": provider},
        )
    return record


def _is_readable(row: UserProviderKey) -> bool:
    """`MASTER_ENCRYPTION_KEY` hiện tại còn mở được hàng này không.

    Bản rõ **không** được gán vào biến nào: nó chỉ tồn tại trong khung của
    `unseal` rồi biến mất cùng câu lệnh — xem docstring module.
    """
    try:
        unseal(Sealed(cipher=row.key_cipher, nonce=row.key_nonce))
    except DecryptionError:
        return False
    return True


def _to_out(row: UserProviderKey) -> ProviderKeyOut:
    return ProviderKeyOut(
        provider=row.provider,
        masked_key=row.key_last4,
        verified_at=row.verified_at,
        created_at=row.created_at,
        usable=_is_readable(row),
    )


@router.get(
    "/keys",
    status_code=status.HTTP_200_OK,
    response_model=ProviderKeyListOut,
)
async def list_provider_keys(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> ProviderKeyListOut:
    """Khoá BYOK của chính mình — **chỉ** phần che (§10.5, DoD dòng 3).

    Không có tham số nào cho phép xem của người khác: `user_id` đến từ
    dependency và đi thẳng vào `WHERE` của câu SQL (§20).

    T-3.12 thêm `byok_providers` — xem `ByokProviderOut`.
    """
    cat = catalog.get_catalog()
    byok_providers = [
        ByokProviderOut(provider=key, label=p.label)
        for key, p in cat.providers.items()
        if p.byok_supported
    ]
    async with session_scope() as session:
        row = await ProviderKeyRepository(session).list_for_user(user_id)
        return ProviderKeyListOut(keys=[_to_out(h) for h in row], byok_providers=byok_providers)


@router.put(
    "/keys/{provider}",
    status_code=status.HTTP_200_OK,
    response_model=ProviderKeyOut,
    responses={
        400: {
            "model": ErrorEnvelope,
            "description": "khoa bi provider tu choi (PROVIDER_KEY_REJECTED) "
            "hoac provider khong ho tro BYOK (BYOK_NOT_SUPPORTED)",
        },
        404: {"model": ErrorEnvelope, "description": "provider la (PROVIDER_UNKNOWN)"},
        503: {
            "model": ErrorEnvelope,
            "description": "khong hoi duoc provider de kiem khoa (SERVICE_UNAVAILABLE)",
        },
    },
)
async def put_provider_key(
    body: ProviderKeyIn,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    provider: Annotated[str, Path()],
) -> ProviderKeyOut:
    """Thêm hoặc thay khoá BYOK cho một provider (§10.5).

    Thứ tự **kiểm trước, lưu sau** là chữ của §10.5 ("trước khi lưu") và là lý
    do endpoint này đắt hơn một câu `INSERT`: một khoá chết nằm trong DB sẽ nổ
    ở giữa một lượt sinh chữ, chỗ khó đọc nhất.

    `PUT` idempotent theo đúng nghĩa của method: gửi lại cùng một khoá cho
    cùng một provider thì kết quả giống hệt, chỉ `verified_at` mới hơn. Vì vậy
    nó **không** cần `Idempotency-Key` của §11.4 — luật đó chỉ áp cho `POST`
    (xem `core/idempotency.py`).
    """
    record = _find_provider(provider)
    key = body.key.strip()

    try:
        outcome = await verify_key(provider, record, key)
    except VerifyUnavailable as exc:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.SERVICE_UNAVAILABLE,
            "khong hoi duoc provider de kiem khoa, hay thu lai",
            details={"provider": provider},
        ) from exc

    if outcome is VerifyOutcome.REJECTED:
        # `details` KHÔNG mang `body.key`, và thông điệp cũng vậy — DoD dòng 4.
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.PROVIDER_KEY_REJECTED,
            _KEY_REJECTED_MSG,
            details={"provider": provider},
        )

    # C42: `SKIPPED` ⇒ `verified_at` để NULL, không phải `now()`. Một mốc thời
    # gian ở đây sẽ nói rằng khoá đã được xác minh, trong khi nó chưa từng.
    #
    # `datetime.now(UTC)` chứ không `func.now()` của Postgres (khác `created_at`
    # ngay cạnh): cột này ghi lại thời điểm **provider trả lời**, một sự kiện đã
    # xảy ra xong trước khi transaction dưới đây mở ra. `func.now()` là mốc mở
    # transaction, tức nó sẽ trả lời một câu hỏi khác — và với một lần verify
    # chậm thì hai câu trả lời lệch nhau bằng đúng độ trễ của provider.
    verified_at = datetime.now(UTC) if outcome is VerifyOutcome.ALIVE else None

    async with session_scope() as session:
        row = await ProviderKeyRepository(session).upsert(
            user_id=user_id,
            provider=provider,
            sealed=seal(key),
            masked=mask_secret(key),
            verified_at=verified_at,
        )
        await session.commit()
        return _to_out(row)


@router.delete(
    "/keys/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {
            "model": ErrorEnvelope,
            "description": "chua cau hinh khoa cho provider nay (PROVIDER_KEY_NOT_FOUND)",
        }
    },
)
async def delete_provider_key(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    provider: Annotated[str, Path()],
) -> Response:
    """Xoá **cứng** khoá BYOK của một provider (§10.5 — không soft-delete).

    **Không** gọi `_find_provider`: một provider vừa bị gỡ khỏi catalog vẫn có
    thể còn để lại một hàng trong bảng này, và chặn ở đây nghĩa là hàng ấy
    không ai xoá được nữa. Xoá thì luôn được phép.

    Xoá lần thứ hai trả `404` chứ không `204`, cùng lối `delete_conversation`
    của `conversations.py`: "đã không còn gì để xoá" là một câu trả lời khác
    với "vừa xoá xong", và FE dựa vào đó để biết danh sách của nó đã cũ.
    """
    async with session_scope() as session:
        deleted = await ProviderKeyRepository(session).delete(user_id=user_id, provider=provider)
        if not deleted:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.PROVIDER_KEY_NOT_FOUND,
                "chua cau hinh khoa rieng cho provider nay",
                details={"provider": provider},
            )
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ═══════════════════ PUT /settings (§18.4, B-206, NQ-79) — T-3.0 ════════════


class SettingsIn(BaseModel):
    """Body của `PUT /settings`. Đúng **một** trường, cố ý.

    NQ-79 chốt "tối thiểu": không dựng sẵn khung cho tuỳ chọn chưa tồn tại.
    Đó là cùng lý lẽ đã dùng để `quota/tiers.py` không có `invalidate()`
    (NQ-51) — một chỗ cắm không ai cắm vào là một chỗ không ai kiểm.

    `extra="forbid"` để một khoá gõ sai (`defaultModel`, `default_model_id`)
    thành `422` chứ không thành một lần ghi im lặng không có tác dụng gì.
    """

    model_config = ConfigDict(extra="forbid")

    #: `null` (hoặc vắng mặt) = **bỏ chọn**, quay về bậc thang mặc định của
    #: §9.2. Đó là một ý định có thật, nên nó phải gửi được — và vì `PUT` thay
    #: cả tài nguyên chứ không vá từng trường, vắng mặt đọc thành `null`. Hôm
    #: nay tài nguyên ấy có đúng một trường nên hai cách đọc trùng nhau; ngày
    #: có trường thứ hai thì `PATCH` mới là method phải thêm, không phải một
    #: luật "vắng mặt nghĩa là giữ nguyên" nhét vào `PUT`.
    default_model: str | None = None


class SettingsOut(BaseModel):
    """`200` của `PUT /settings` — trạng thái sau khi ghi.

    Trả lại giá trị thay vì `204`: FE vừa gửi một tên model và cần biết chắc
    server đã nhận đúng tên ấy, chứ không phải suy ra từ một response rỗng.
    Cùng hình dạng với trường `default_model` của `GET /auth/me`, để hai chỗ
    nói về cùng một thứ bằng cùng một cái tên.
    """

    model_config = ConfigDict(extra="forbid")

    default_model: str | None


@router.put(
    "",
    status_code=status.HTTP_200_OK,
    response_model=SettingsOut,
    responses={
        400: {
            "model": ErrorEnvelope,
            "description": "model khong co trong catalog hoac da tat (MODEL_UNKNOWN)",
        }
    },
)
async def put_settings(
    body: SettingsIn,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> SettingsOut:
    """Ghi cài đặt cá nhân của **chính mình** (§18.4, UC-05).

    Không có tham số nào trỏ sang người khác: `user_id` đến từ dependency và đi
    thẳng vào `WHERE` của câu `UPDATE` (§20) — đường dẫn không có `{id}`, body
    không có `user_id`, và `UserRepository.set_default_model` không nhận một
    khoá nào khác để lọc.

    **Validate catalog lúc GHI, không lúc đọc** (Cạm bẫy ③ của T-3.0). Catalog
    là file sửa nóng (`POST /admin/catalog/reload`, §19.1), nên một model hợp
    lệ hôm nay có thể biến mất ngày mai. Chặn ở đây thì người dùng chọn xong là
    biết ngay; chặn lúc đọc thì một dòng cấu hình admin vừa sửa sẽ ném lỗi vào
    mặt một người không làm gì cả. `GET /auth/me` vì vậy trả nguyên văn giá trị
    đã lưu và để FE rơi về `default: true` của catalog.

    `catalog.get_model` lọc luôn `enabled`, cùng lối `_pick_model` của
    `api/v1/messages.py`: chọn mặc định một model đang tắt là hẹn trước một
    `MODEL_UNKNOWN` cho mọi lượt chat sau đó.

    Raises:
        ApiError 400 `MODEL_UNKNOWN`: `default_model` không có trong catalog
            hoặc đã `enabled: false`.
        ApiError 401 `UNAUTHENTICATED`: tài khoản đã bị xoá giữa hai request.
    """
    if body.default_model is not None and catalog.get_model(body.default_model) is None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.MODEL_UNKNOWN,
            f"model khong co trong catalog hoac da tat: {body.default_model}",
            details={"model_id": body.default_model},
        )

    async with session_scope() as session:
        written = await UserRepository(session).set_default_model(user_id, body.default_model)
        if not written:
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED,
                ApiErrorCode.UNAUTHENTICATED,
                "user khong con ton tai",
            )
        await session.commit()

    return SettingsOut(default_model=body.default_model)
