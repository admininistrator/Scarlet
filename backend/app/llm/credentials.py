"""Credential nào trả tiền cho một lượt sinh: system key hay BYOK (§10.5) — T-2.15.

KH tham chiếu: §10.5, §9.1, §9.2, §11.1 · CLAUDE.md A3, A7 · tasks.md T-2.15,
B-140, B-157 · NQ-58.

╔══════════════════════════════════════════════════════════════════════════╗
║  MỘT CÂU HỎI, MỘT HÀM, HAI NGƯỜI HỎI                                     ║
╚══════════════════════════════════════════════════════════════════════════╝

Câu hỏi là: *"người này có khoá dùng được cho provider của model đang gọi
không?"* — và **ba** chỗ cần đúng câu trả lời đó, không phải một:

1. `app/api/v1/messages.py::_mo_luot_sinh` — cửa chặn §10.2 chỉ được chạy cho
   lượt tiêu tiền của người vận hành (**B-157**: *"Request dùng BYOK vẫn bị
   trừ quota — §10.5 nói KHÔNG được"*).
2. cùng chỗ đó — phép kiểm §11.1 chính xác cho `pending_approval` (**B-140**:
   dependency chỉ biết "có khoá **nào đó**", nó không thấy `model_id` vì
   model nằm trong body).
3. `app/workers/generate.py` — chọn adapter (§9.1) và ghi `usage_events.
   key_source` (§10.5, A7).

Ba chỗ, một hàm: `_byok_key()` là lõi và hai hàm công khai chỉ là hai cách
nhìn nó. Hai bản sao của cùng một luật là hai chỗ để lệch nhau, và lệch ở đây
nghĩa là *một lượt sinh vừa được miễn quota vừa tiêu system key*.

**Khe đua đã biết trước, đã chọn, đã đo được giới hạn.** api hỏi lúc nhận
request; worker hỏi lại lúc nhặt job — giữa hai lúc ấy là thời gian job nằm
trong hàng đợi (`ARQ_POLL_DELAY_S`). Ai xoá khoá đúng trong khe đó thì lượt ấy
đi bằng system key mà đã được miễn cửa chặn — **một** lượt, và nó vẫn bị
`add_to_windows` ghi sổ ở bước ⑥.5 nên tiền không biến mất, chỉ là nó vượt
trần đúng một lượt. Chiều ngược lại (thêm khoá trong khe đó) chỉ làm người
dùng bị kiểm quota thừa một lần. Ngả thay thế — chốt quyết định vào một cột
`messages.key_source` — đòi một cột **không có** trong Phụ lục A, và vẫn không
bỏ được lần hỏi thứ hai của worker: worker phải đọc bảng khoá để **giải mã**
khoá, nên nếu khoá đã bị xoá thì cột kia chỉ nói dối to hơn.

╔══════════════════════════════════════════════════════════════════════════╗
║  "CÓ KHOÁ" KHÔNG ĐỦ — PHẢI LÀ KHOÁ **DÙNG ĐƯỢC**                        ║
╚══════════════════════════════════════════════════════════════════════════╝

Lõi trả `None` (⇒ system key) ở **bốn** ca, và cả bốn đều là cùng một câu:
lượt này sẽ đi bằng tiền của người vận hành, nên nó phải qua cửa quota.

* provider không có trong catalog — không thể xảy ra hôm nay
  (`_provider_must_exist` chặn lúc nạp), giữ vì nó là điều kiện tiên quyết
  của ba dòng dưới;
* `byok_supported: false` — người vận hành đã nói provider này không dùng
  khoá riêng; một hàng còn sót lại từ trước khi cờ bị tắt **không** được
  quyền lật lại quyết định đó;
* không có hàng nào — ca thường, và là ca **DoD dòng 3**: xoá khoá ⇒ lượt kế
  tiếp tự quay về system key, không cần ai dọn gì thêm;
* `DecryptionError` — `MASTER_ENCRYPTION_KEY` đã xoay, hoặc dump DB sang máy
  khác (`core/crypto.py`). Lùi về system key **và** ghi `WARNING`: ngả kia là
  ném một lỗi đỏ vào giữa một lượt chat cho một sự cố vận hành mà người dùng
  không gây ra và không sửa được. `GET /settings/keys` là chỗ nói với họ câu
  "hãy nhập lại khoá" (`usable: false`, T-2.14), và nó nói câu đó **trước**
  khi họ bấm Gửi.

Hệ quả có chủ ý của ca thứ tư: một `pending_approval` có khoá không giải mã
được sẽ nhận `403` chứ không phải một lượt chat miễn phí — hỏng về phía chặt
hơn, đúng chiều §11.1 chọn.

╔══════════════════════════════════════════════════════════════════════════╗
║  BẢN RÕ: `resolve_key_source` KHÔNG BAO GIỜ TRẢ NÓ RA                   ║
╚══════════════════════════════════════════════════════════════════════════╝

Tiến trình `api` cần **một bit** (có/không), tiến trình `worker` cần cả khoá.
Hai hàm công khai vì vậy có hai kiểu trả về khác nhau, và cái dành cho `api`
không có chỗ nào để bản rõ chui qua — nó trả về một `KeySource`.

Bản rõ vẫn tồn tại trong khung của lõi khi `api` gọi, và **phải** vậy: câu hỏi
"khoá này có dùng được không" chỉ trả lời được bằng cách giải mã thử. Đó đúng
là điều `GET /settings/keys` đã làm từ T-2.14 (`_is_readable`), cùng một lý lẽ và
cùng một cái giá: một phép AES-GCM cho mỗi lần hỏi.
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import catalog
from app.config.catalog import ModelEntry, Provider, ReasoningOption
from app.core.crypto import DecryptionError, Sealed, unseal
from app.db.models import KeySource
from app.db.repositories import ByokEndpointRepository, ProviderKeyRepository
from app.llm import byok_endpoints

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Credential:
    """Credential đã chốt cho một lượt sinh — đủ để dựng adapter và ghi sổ.

    `provider` và `api_key` cùng `None` hoặc cùng có giá trị: chúng là hai nửa
    của một câu trả lời (`ByokAdapter.for_provider` cần cả hai), và tách được
    chúng ra là mở đúng cái khe "có khoá nhưng không biết gửi đi đâu".
    """

    key_source: KeySource
    #: Bản ghi catalog của provider — chỉ có ở nhánh BYOK.
    provider: Provider | None
    #: Khoá **bản rõ** — chỉ có ở nhánh BYOK. Không log, không đi vào exception (C20).
    api_key: str | None
    #: Base URL của endpoint người dùng tự nhập (T-S.19b) — có thì `provider` là
    #: `None` và worker gọi qua client ghim IP (A5).
    base_url: str | None = None

    def model_name(self, model: ModelEntry, level: ReasoningOption | None = None) -> str:
        """Tên model gửi lên upstream — alias LiteLLM hay tên gốc của provider.

        Sống ở đây chứ không ở `workers/generate.py` vì nó là hệ quả trực tiếp
        của việc đã chọn credential nào: chọn BYOK là chọn bỏ qua LiteLLM, và
        bỏ qua LiteLLM là bỏ luôn bảng dịch alias của nó
        (`config/litellm.config.yaml`). Hai quyết định ấy phải nằm cạnh nhau,
        nếu không thì một ngày nào đó có người đổi một cái mà quên cái kia và
        provider trả `400 model not found` — xem `ModelEntry.provider_model`.

        **`level.alias` chỉ có nghĩa trên đường system** (§24.2b·S3b, T-S.6):
        nó là một `model_name` khác trong `litellm.config.yaml` — cách 9Router
        chọn mức bằng tên model — nên gửi nó thẳng tới provider là gửi một tên
        provider không biết. Đường BYOK vì vậy bỏ qua nó và gọi tên gốc.
        """
        if self.key_source is KeySource.SYSTEM:
            return level.alias if level is not None and level.alias else model.id
        if self.base_url is not None:
            # Tên người dùng nhập, nguyên văn — kể cả dấu `/` (OpenRouter…).
            return model.upstream_model
        return model.provider_model

    def reasoning_params(self, level: ReasoningOption | None) -> dict[str, Any]:
        """Tham số của một mức suy luận cho ĐƯỜNG này — trộn vào `extra` (§9.1).

        `byok_params` thay `params` trên đường BYOK khi catalog khai nó: LiteLLM
        không có mặt để dịch, nên provider có thể cần tên tham số khác (§24.2b·
        S3b). Vắng mặt ⇒ BYOK dùng chính `params` — T-S.2 đo `thinking` gốc
        chạy trên cả hai đường cho mọi model đang khai.

        Trả **bản sao sâu**: dict trong catalog là dữ liệu dùng chung của cả
        tiến trình, và một adapter nào đó trộn thêm khoá vào nó sẽ đổi tham số
        của mọi lượt sinh sau cho tới lần nạp catalog kế tiếp.
        """
        if level is None:
            return {}
        chosen = level.params
        if self.key_source is not KeySource.SYSTEM and level.byok_params is not None:
            chosen = level.byok_params
        return copy.deepcopy(chosen)


#: Lượt sinh đi bằng tiền của người vận hành. Một hằng dùng chung thay vì ba
#: lần dựng cùng một object: nó bất biến, và nó là câu trả lời mặc định của cả
#: bốn ca lùi ở docstring module.
class CredentialUnavailable(Exception):
    """Lượt sinh bằng endpoint tự nhập không lấy được khoá — xem `resolve_credential`."""


SYSTEM_CREDENTIAL = Credential(key_source=KeySource.SYSTEM, provider=None, api_key=None)


async def resolve_key_source(
    session: AsyncSession, *, user_id: uuid.UUID, model: ModelEntry
) -> KeySource:
    """Lượt này sẽ tiêu tiền của ai — dành cho tầng API (B-140, B-157).

    Trả về **chỉ** nguồn credential: bản rõ không có đường nào ra khỏi hàm
    này (xem docstring module).

    Model của endpoint tự nhập luôn là BYOK: không có đường system nào cho nó,
    và `resolve_model` đã tra endpoint theo `user_id` trước khi tới đây.
    """
    if byok_endpoints.endpoint_id_of(model) is not None:
        return KeySource.BYOK
    return (await _byok_key(session, user_id=user_id, model=model))[0]


async def resolve_credential(
    session: AsyncSession, *, user_id: uuid.UUID, model: ModelEntry
) -> Credential:
    """Credential đầy đủ cho một lượt sinh — dành cho worker (§9.1, §10.5).

    Cùng lõi với `resolve_key_source`, nên hai tiến trình không thể trả lời
    khác nhau về cùng một trạng thái DB (xem docstring module).

    Raises:
        CredentialUnavailable: model của endpoint tự nhập mà endpoint vừa bị
            xoá, hoặc khoá không giải mã được — không có system key nào để lùi về.
    """
    endpoint_id = byok_endpoints.endpoint_id_of(model)
    if endpoint_id is not None:
        row = await ByokEndpointRepository(session).get(user_id=user_id, endpoint_id=endpoint_id)
        if row is None:
            raise CredentialUnavailable("endpoint BYOK khong con ton tai")
        try:
            key = unseal(Sealed(cipher=row.key_cipher, nonce=row.key_nonce))
        except DecryptionError:
            raise CredentialUnavailable(
                "khoa cua endpoint BYOK khong giai ma duoc, hay xoa roi them lai"
            ) from None
        return Credential(
            key_source=KeySource.BYOK, provider=None, api_key=key, base_url=row.base_url
        )
    key_source, provider, api_key = await _byok_key(session, user_id=user_id, model=model)
    if key_source is KeySource.SYSTEM:
        return SYSTEM_CREDENTIAL
    return Credential(key_source=key_source, provider=provider, api_key=api_key)


# ─────────────────────────── phần trong của file ───────────────────────────


async def _byok_key(
    session: AsyncSession, *, user_id: uuid.UUID, model: ModelEntry
) -> tuple[KeySource, Provider | None, str | None]:
    """Lõi của cả hai hàm trên — bốn ca lùi ở docstring module.

    Trả về một tuple chứ không phải `Credential` để hai hàm công khai giữ được
    hai hình dạng khác nhau mà vẫn chỉ có **một** chỗ viết luật.
    """
    provider = catalog.get_catalog().providers.get(model.provider)
    if provider is None or not provider.byok_supported:  # pragma: no branch - xem docstring
        return KeySource.SYSTEM, None, None

    row = await ProviderKeyRepository(session).get(user_id=user_id, provider=model.provider)
    if row is None:
        return KeySource.SYSTEM, None, None

    try:
        plaintext = unseal(Sealed(cipher=row.key_cipher, nonce=row.key_nonce))
    except DecryptionError:
        # KHÔNG `logger.exception`: traceback của `cryptography` không nói
        # thêm gì mà `DecryptionError` chưa nói. Gọi tên `user_id` + provider
        # để người vận hành biết phải bảo ai nhập lại khoá.
        logger.warning(
            "khoa BYOK cua user %s cho provider '%s' khong giai ma duoc — "
            "luot sinh nay di bang system key va SE bi tru quota; "
            "nguoi dung can nhap lai khoa (GET /settings/keys tra usable=false)",
            user_id,
            model.provider,
        )
        return KeySource.SYSTEM, None, None

    return KeySource.BYOK, provider, plaintext
