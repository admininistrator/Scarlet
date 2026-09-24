"""Cài đặt cá nhân — BYOK CRUD (§18.4, §10.5) — T-2.14; `PUT /settings` — T-3.0,
nở thêm hồ sơ và mức suy luận đã nhớ — T-S.5.

KH tham chiếu: §10.5, §18.4, §9.2, §11.1, §19.1, §20, §23 `api/v1/settings.py`,
§24.2b·S4, S10, S14 · Cạm bẫy C20, C42 · CLAUDE.md A3 · tasks.md T-2.14, T-3.0,
T-S.5, B-206, NQ-79, NQ-116, NQ-118.

Ba endpoint của hàng "keys" trong bảng §18.4, cộng `PUT /settings` từ T-3.0.
`GET /settings` và `GET /settings/usage` **chưa** có task nào — không dựng sẵn.

┌──────────────────────────────────────────────────────────────────────────┐
│  `PUT /settings` CÓ, `GET /settings` KHÔNG — và đó là một quyết định      │
└──────────────────────────────────────────────────────────────────────────┘

§18.4 ghi `GET/PUT /settings` trên cùng một hàng, nhưng T-3.0 chỉ dựng vế
`PUT`. Lý do: vế `GET` đã có người trả lời rồi — **mọi** trường của
`PUT /settings` đi ra trong `GET /auth/me` (§18.1, NQ-81; S14 ghi hai endpoint
ấy trên cùng một hàng), và theme thì sống trong `localStorage` từ T-0.10. Một
`GET /settings` vì thế là endpoint thứ hai trả lời đúng một câu hỏi, tức chỗ
đầu tiên để hai câu trả lời lệch nhau.

┌──────────────────────────────────────────────────────────────────────────┐
│  CÁI GÌ LƯU Ở ĐÂU (T-S.5 Cạm bẫy ①)                                      │
└──────────────────────────────────────────────────────────────────────────┘

- `default_model` → `users.default_model` (NQ-79). **Không** dời sang
  `user_settings` — đó là một migration dữ liệu không ai yêu cầu.
- `display_name` → `users.display_name` (NQ-116), cột có từ Phụ lục A.
- `avatar_color`, `reasoning_prefs` → `user_settings.prefs_json`, khoá
  `avatar_color` và `reasoning` (S14; hình dạng ở `app/core/user_prefs.py`).

Hai bảng, **một** transaction: một lần bấm Lưu không được để tên mới đi cùng
mức suy luận cũ.

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
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from app.config import catalog
from app.config.catalog import Provider
from app.config.settings import settings
from app.core.crypto import DecryptionError, Sealed, mask_secret, seal, unseal
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.core.user_prefs import UserPrefs
from app.db.models import UserProviderKey
from app.db.repositories import ProviderKeyRepository, UserRepository, UserSettingsRepository
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


# ═══════════════ PUT /settings (§18.4, B-206, NQ-79) — T-3.0, T-S.5 ═════════

#: Tên màu avatar (§24.2b·S10, T-S.5 Việc 1): chữ thường, số, gạch nối. Chỉ
#: kiểm **hình dạng** — backend không biết bảng màu token của T-HD1-v2 (A3), nên
#: một tên hợp hình dạng mà FE không biết vẫn lưu được, và FE rơi về màu mặc
#: định. Hình dạng hẹp là để tên màu không bao giờ mang được một mã CSS nào.
_AVATAR_COLOR_PATTERN = r"^[a-z0-9-]{1,32}$"

#: Không ký tự điều khiển C0/DEL trong tên hiển thị. `\x00` là lý do cứng:
#: Postgres `TEXT` không nhận NUL, và thiếu luật này thì nó đi hết biên vào rồi
#: nổ thành `500` ở câu `UPDATE`. Xuống dòng, tab thì không có chỗ trong một tên
#: hiện trên một dòng sidebar.
_DISPLAY_NAME_PATTERN = r"^[^\x00-\x1f\x7f]*$"


def _blank_to_none(value: object) -> object:
    """`display_name`: cắt khoảng trắng hai đầu; rỗng ⇒ `None` (Cạm bẫy ② của T-S.5).

    Chạy **trước** trần độ dài, nên `"  An  "` đếm là 2 ký tự chứ không 6, và
    `"   "` thành `NULL` trong DB — FE hiện nguyên email (NQ-116). Lưu chuỗi
    rỗng là cho FE hai cách viết "chưa đặt tên".
    """
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


#: Ràng buộc đặt trên kiểu `str` **bên trong**, không trên `str | None`. Đo khi
#: viết task: `Field(max_length=…)` đặt ngoài cùng `BeforeValidator` thì
#: Pydantic áp `max_length` lên cả `None` do `_blank_to_none` trả về và nổ
#: `TypeError` (tức `500`) — đúng ca rỗng mà Cạm bẫy ② đòi phải đi được.
#: `avatar_color` đi cùng khuôn cho khỏi hai cách viết một loại ràng buộc.
_DisplayName = Annotated[
    str,
    StringConstraints(max_length=settings.DISPLAY_NAME_MAX_CHARS, pattern=_DISPLAY_NAME_PATTERN),
]
_AvatarColor = Annotated[str, StringConstraints(pattern=_AVATAR_COLOR_PATTERN)]


class SettingsIn(BaseModel):
    """Body của `PUT /settings` — **thay cả tài nguyên** (§18.4, S10).

    Trường vắng mặt đọc thành "không có": `default_model`/`display_name`/
    `avatar_color` về `null`, `reasoning_prefs` về `{}`. Đó là hành vi **có chủ
    ý**: S10 chốt `PUT` vẫn thay cả tài nguyên khi tài nguyên nở thêm trường,
    nên FE (T-S.11) luôn gửi **đủ** — không có luật "vắng mặt nghĩa là giữ
    nguyên" nào nhét vào `PUT`. Test `test_put_replaces_whole_resource` canh.

    `extra="forbid"` để một khoá gõ sai (`defaultModel`, `avatarColor`) thành
    `422` chứ không thành một lần ghi im lặng — mà với `PUT` thay cả tài nguyên
    thì còn tệ hơn: trường gõ sai bị bỏ qua, trường đúng tên thì bị xoá.
    """

    model_config = ConfigDict(extra="forbid")

    #: `null` = **bỏ chọn**, quay về bậc thang mặc định của §9.2.
    default_model: str | None = None
    #: `null`/rỗng/toàn khoảng trắng ⇒ `NULL` ⇒ FE hiện nguyên email (NQ-116).
    #: Trần đếm theo **ký tự** như `MESSAGE_MAX_CHARS` (Cạm bẫy ③), không bắt
    #: duy nhất (S10). FE không bao giờ render nó như HTML — việc của FE.
    display_name: Annotated[_DisplayName | None, BeforeValidator(_blank_to_none)] = None
    #: Tên màu, không mã màu (A3, NQ-116). `null` = màu mặc định của FE.
    avatar_color: _AvatarColor | None = None
    #: `{model_id: level_id}` — mức suy luận đã nhớ (§24.2b·S4). Kiểm **từng
    #: cặp** theo catalog lúc ghi, trong `_check_reasoning_prefs`.
    reasoning_prefs: dict[str, str] = Field(default_factory=dict)


class SettingsOut(BaseModel):
    """`200` của `PUT /settings` — trạng thái sau khi ghi.

    Trả lại giá trị thay vì `204`: FE vừa gửi và cần biết chắc server đã nhận
    đúng thứ ấy (kể cả `display_name` đã cắt khoảng trắng), chứ không phải suy
    ra từ một response rỗng. Cùng tên trường với `GET /auth/me`, để hai chỗ nói
    về cùng một thứ bằng cùng một cái tên.
    """

    model_config = ConfigDict(extra="forbid")

    default_model: str | None
    display_name: str | None
    avatar_color: str | None
    reasoning_prefs: dict[str, str]


def _check_reasoning_prefs(prefs: dict[str, str]) -> None:
    """Kiểm từng cặp `model → mức` theo catalog **lúc ghi** (T-S.5 Việc 1).

    Cùng hai luật với `default_model` và cùng một hàm với lúc đọc
    (`catalog.supports_reasoning`), nên một cặp ghi được hôm nay thì
    `/auth/me` trả lại nó — trừ khi catalog đổi ở giữa, lúc ấy đọc bỏ qua.

    Raises:
        ApiError 400 `MODEL_UNKNOWN`: model không có hoặc đã `enabled: false`.
        ApiError 400 `REASONING_UNSUPPORTED`: model không khai mức ấy — kể cả
            model không có khối `reasoning` nào.
    """
    for model_id, level in prefs.items():
        model = catalog.get_model(model_id)
        if model is None:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                ApiErrorCode.MODEL_UNKNOWN,
                f"model khong co trong catalog hoac da tat: {model_id}",
                details={"model_id": model_id},
            )
        if not catalog.supports_reasoning(model, level):
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                ApiErrorCode.REASONING_UNSUPPORTED,
                f"model {model_id} khong co muc suy luan {level}",
                details={"model_id": model_id, "level": level},
            )


@router.put(
    "",
    status_code=status.HTTP_200_OK,
    response_model=SettingsOut,
    responses={
        400: {
            "model": ErrorEnvelope,
            "description": "model khong co trong catalog hoac da tat (MODEL_UNKNOWN), "
            "hoac model khong co muc suy luan do (REASONING_UNSUPPORTED)",
        }
    },
)
async def put_settings(
    body: SettingsIn,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> SettingsOut:
    """Ghi cài đặt cá nhân của **chính mình** (§18.4, UC-05, §24.2b·S10).

    Không có tham số nào trỏ sang người khác: `user_id` đến từ dependency và đi
    thẳng vào `WHERE` của cả hai câu ghi (§20) — đường dẫn không có `{id}`, body
    không có `user_id`, và `UserRepository.set_profile` lẫn
    `UserSettingsRepository.put_prefs` không nhận một khoá nào khác để lọc.

    **Validate catalog lúc GHI, không lúc đọc** (Cạm bẫy ③ của T-3.0). Catalog
    là file sửa nóng (`POST /admin/catalog/reload`, §19.1), nên một model hợp
    lệ hôm nay có thể biến mất ngày mai. Chặn ở đây thì người dùng chọn xong là
    biết ngay; lúc đọc thì `/auth/me` trả nguyên văn `default_model` (FE rơi về
    `default: true`) và bỏ qua cặp suy luận hết hợp lệ (`user_prefs.read_prefs`).

    Kiểm **hết** trước khi mở transaction: một `400` không ghi gì cả, kể cả
    những trường hợp lệ đi cùng body ấy.

    Raises:
        ApiError 400 `MODEL_UNKNOWN`: `default_model` hoặc một khoá của
            `reasoning_prefs` không có trong catalog hoặc đã `enabled: false`.
        ApiError 400 `REASONING_UNSUPPORTED`: model không khai mức ấy.
        ApiError 401 `UNAUTHENTICATED`: tài khoản đã bị xoá giữa hai request.
    """
    if body.default_model is not None and catalog.get_model(body.default_model) is None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.MODEL_UNKNOWN,
            f"model khong co trong catalog hoac da tat: {body.default_model}",
            details={"model_id": body.default_model},
        )
    _check_reasoning_prefs(body.reasoning_prefs)
    prefs = UserPrefs(avatar_color=body.avatar_color, reasoning=body.reasoning_prefs)

    async with session_scope() as session:
        written = await UserRepository(session).set_profile(
            user_id, display_name=body.display_name, default_model=body.default_model
        )
        if not written:
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED,
                ApiErrorCode.UNAUTHENTICATED,
                "user khong con ton tai",
            )
        await UserSettingsRepository(session).put_prefs(user_id, prefs.to_json())
        await session.commit()

    return SettingsOut(
        default_model=body.default_model,
        display_name=body.display_name,
        avatar_color=prefs.avatar_color,
        reasoning_prefs=prefs.reasoning,
    )
