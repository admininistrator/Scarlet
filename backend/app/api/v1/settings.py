"""Cài đặt cá nhân — BYOK CRUD (§18.4, §10.5) — T-2.14.

KH tham chiếu: §10.5, §18.4, §11.1, §20, §23 `api/v1/settings.py` · Cạm bẫy
C20, C42 · CLAUDE.md A3 · tasks.md T-2.14.

Ba endpoint của hàng "keys" trong bảng §18.4. Ba endpoint còn lại của mục đó
(`/settings`, `/settings/usage`) **chưa** có task nào — không dựng sẵn.

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

Router này nằm trong danh sách `_CO_DANH_TINH` của `api/v1/__init__.py`, tức
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
from app.db.repositories import ProviderKeyRepository
from app.db.session import session_scope
from app.llm.byok_verify import VerifyOutcome, VerifyUnavailable, verify_key

router = APIRouter(prefix="/settings", tags=["settings"])

#: Câu trả lời cho mọi kiểu "khoá này không dùng được". Một hằng chứ không ba
#: chuỗi rải rác: nó là câu **không được phép** chứa khoá (C20, DoD dòng 4), và
#: một câu thì soi được bằng mắt trong ba giây.
_LOI_KHOA_BI_TU_CHOI = "provider tu choi khoa nay, hay kiem tra lai roi nhap lai"


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


class ProviderKeyListOut(BaseModel):
    keys: list[ProviderKeyOut]


class ProviderKeyIn(BaseModel):
    """Body của `PUT /settings/keys/{provider}`.

    `min_length=1` chứ không một luật hình dạng nào: mỗi provider có định dạng
    khoá riêng, và chép luật ấy vào đây là đúng loại literal-của-provider mà
    A3 cấm. Phép kiểm thật là hỏi chính provider (§10.5).
    """

    key: str = Field(min_length=1)


def _tim_provider(provider: str) -> Provider:
    """Provider trong catalog, hoặc `404`/`400` — §9.2, §10.5.

    Raises:
        ApiError 404 `PROVIDER_UNKNOWN`: không có trong `providers`.
        ApiError 400 `BYOK_NOT_SUPPORTED`: có, nhưng `byok_supported: false`.
    """
    ban_ghi = catalog.get_catalog().providers.get(provider)
    if ban_ghi is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.PROVIDER_UNKNOWN,
            "provider khong co trong catalog",
            details={"provider": provider},
        )
    if not ban_ghi.byok_supported:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.BYOK_NOT_SUPPORTED,
            "provider nay khong dung duoc khoa API rieng",
            details={"provider": provider},
        )
    return ban_ghi


def _doc_duoc(hang: UserProviderKey) -> bool:
    """`MASTER_ENCRYPTION_KEY` hiện tại còn mở được hàng này không.

    Bản rõ **không** được gán vào biến nào: nó chỉ tồn tại trong khung của
    `unseal` rồi biến mất cùng câu lệnh — xem docstring module.
    """
    try:
        unseal(Sealed(cipher=hang.key_cipher, nonce=hang.key_nonce))
    except DecryptionError:
        return False
    return True


def _ra(hang: UserProviderKey) -> ProviderKeyOut:
    return ProviderKeyOut(
        provider=hang.provider,
        masked_key=hang.key_last4,
        verified_at=hang.verified_at,
        created_at=hang.created_at,
        usable=_doc_duoc(hang),
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
    """
    async with session_scope() as session:
        hang = await ProviderKeyRepository(session).list_for_user(user_id)
        return ProviderKeyListOut(keys=[_ra(h) for h in hang])


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
    ban_ghi = _tim_provider(provider)
    khoa = body.key.strip()

    try:
        ket_cuc = await verify_key(provider, ban_ghi, khoa)
    except VerifyUnavailable as loi:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.SERVICE_UNAVAILABLE,
            "khong hoi duoc provider de kiem khoa, hay thu lai",
            details={"provider": provider},
        ) from loi

    if ket_cuc is VerifyOutcome.REJECTED:
        # `details` KHÔNG mang `body.key`, và thông điệp cũng vậy — DoD dòng 4.
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.PROVIDER_KEY_REJECTED,
            _LOI_KHOA_BI_TU_CHOI,
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
    verified_at = datetime.now(UTC) if ket_cuc is VerifyOutcome.ALIVE else None

    async with session_scope() as session:
        hang = await ProviderKeyRepository(session).upsert(
            user_id=user_id,
            provider=provider,
            sealed=seal(khoa),
            masked=mask_secret(khoa),
            verified_at=verified_at,
        )
        await session.commit()
        return _ra(hang)


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

    **Không** gọi `_tim_provider`: một provider vừa bị gỡ khỏi catalog vẫn có
    thể còn để lại một hàng trong bảng này, và chặn ở đây nghĩa là hàng ấy
    không ai xoá được nữa. Xoá thì luôn được phép.

    Xoá lần thứ hai trả `404` chứ không `204`, cùng lối `delete_conversation`
    của `conversations.py`: "đã không còn gì để xoá" là một câu trả lời khác
    với "vừa xoá xong", và FE dựa vào đó để biết danh sách của nó đã cũ.
    """
    async with session_scope() as session:
        da_xoa = await ProviderKeyRepository(session).delete(user_id=user_id, provider=provider)
        if not da_xoa:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.PROVIDER_KEY_NOT_FOUND,
                "chua cau hinh khoa rieng cho provider nay",
                details={"provider": provider},
            )
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
