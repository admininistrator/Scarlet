"""Blacklist access token — `bl:jti:{jti}` và `bl:user:{uid}` (§11.3) — T-2.4.

KH tham chiếu: §11.3, C21, §11.2 · CLAUDE.md A3 · tasks.md T-2.4.

§11.3 viết ra toàn bộ cơ chế trong sáu dòng:

    Logout        → SET bl:jti:{jti} 1 EX <thời gian còn lại của access token>
                    + đánh dấu refresh family revoked trong DB
    Đổi mật khẩu  → revoke TẤT CẢ refresh family của user
                    + SET bl:user:{uid} <now> EX 900
                      (middleware từ chối mọi access token có iat < giá trị này)
    Admin suspend → như đổi mật khẩu

Hai khoá, hai câu hỏi khác nhau, và đó là lý do không gộp được thành một:

- `bl:jti:` chặn **một** token cụ thể. Logout trên điện thoại không được đá
  người dùng ra khỏi máy tính để bàn — §11.2 nói phiên, không nói tài khoản.
- `bl:user:` chặn **mọi** token phát hành trước một mốc. Đổi mật khẩu thì
  ngược lại: đá sạch, kể cả những `jti` mà server chưa bao giờ nhìn thấy.
  Liệt kê từng `jti` là việc không làm được — server không lưu chúng ở đâu cả
  (đó chính là điều ADR-07 đánh đổi), nên câu trả lời phải là một *mốc thời
  gian* chứ không phải một danh sách.

**Vì sao cả hai khoá đều có TTL, và TTL bằng đúng cái gì.** Cạm bẫy của T-2.4:
"blacklist không có TTL sẽ phình vô hạn". `bl:jti:` sống đúng phần đời còn lại
của chính token nó chặn — sau `exp` thì `decode_access_token` đã tự từ chối,
một khoá còn nằm đó chỉ tốn chỗ. `bl:user:` sống `ACCESS_TOKEN_TTL_MIN * 60`
giây (§11.3 viết `EX 900`, và 900 = 15 phút = **đúng** trần tuổi của một access
token — nên đây là một phép suy ra từ cấu hình, không phải một con số gõ tay,
A3): token cuối cùng còn có thể vi phạm mốc là token phát hành ngay trước mốc,
và nó tự chết sau chừng ấy giây.

**Vì sao mốc lưu `time.time()` dạng thực chứ không phải số giây nguyên.**
`iat` của JWT là NumericDate, tức **giây nguyên** (`floor`). Nếu mốc cũng làm
tròn xuống, mọi token phát hành trong *cùng giây* với lần đổi mật khẩu sẽ có
`iat == mốc`, và phép so `iat < mốc` của §11.3 cho `False` — token của kẻ tấn
công sống sót qua đúng thứ vừa được dựng lên để giết nó. Giữ phần thập phân
đóng hẳn khe đó. Giá phải trả đi đúng chiều an toàn: một token phát hành
*sau* mốc nhưng trong cùng giây cũng bị chặn — người dùng đăng nhập lại một
lần, thay vì kẻ trộm giữ được phiên.

**Vì sao `mget` chứ không hai lần `exists`/`get`.** Phép kiểm này chạy trên
**mọi** request đã đăng nhập (`app/core/deps.py`). Hai lượt đi-về Redis cho mỗi
request là hai lần độ trễ mạng cho một câu hỏi duy nhất; `MGET` hỏi cả hai
khoá trong một lượt. Giá trị `None` đọc ra phân biệt được "không có khoá" với
mọi thứ khác, nên không mất thông tin gì so với `EXISTS`.

**Vì sao `revoke_all_sessions()` ở đây chứ không ở router**, dù nó kéo theo một
import từ `db/repositories/` vào `core/` (`core/access_token.py` đã có tiền lệ
nhập `db/models`): hai nửa của "đổi mật khẩu" trong §11.3 — revoke refresh
family (Postgres) và đặt mốc (Redis) — **không** được phép rời nhau. Làm nửa
đầu mà quên nửa sau thì access token cũ còn sống 15 phút (đúng C21, chỉ đổi
nguyên nhân); làm nửa sau mà quên nửa đầu thì refresh token cũ đổi ra một access
token mới tinh sau 15 phút và kẻ tấn công quay lại. Một hàm có tên là cách duy
nhất bắt T-2.5 (`reset-password`) và T-2.7 (admin suspend) không mỗi nơi nhớ
một nửa.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.config.settings import settings
from app.core.access_token import AccessTokenClaims
from app.db.repositories.refresh_tokens import RefreshTokenRepository

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

#: Tiền tố khoá của §11.3. Cùng luật với `cancel_key()` của `streaming/cancel.py`:
#: không ai được tự nối chuỗi, vì một tiền tố gõ sai là một blacklist không bao
#: giờ chặn gì — và nó **không** báo lỗi, nó chỉ im lặng cho qua.
BL_JTI_PREFIX = "bl:jti:"
BL_USER_PREFIX = "bl:user:"

#: §11.3 viết `SET bl:jti:{jti} 1`. Không ai đọc nội dung; câu hỏi duy nhất là
#: "khoá có tồn tại không". Vẫn ghi đúng `1` để `redis-cli GET` lúc debug cho ra
#: thứ người đọc kế hoạch đang chờ thấy (cùng lối `FLAG_VALUE` của §7.5).
BLOCKED_VALUE = "1"


def jti_key(jti: str) -> str:
    return f"{BL_JTI_PREFIX}{jti}"


def user_key(user_id: uuid.UUID | str) -> str:
    return f"{BL_USER_PREFIX}{user_id}"


def user_cutoff_ttl() -> int:
    """TTL của `bl:user:{uid}`, suy ra từ cấu hình chứ không gõ tay (A3).

    Xem docstring module: mốc chỉ cần sống đúng bằng trần tuổi của một access
    token. Nới `ACCESS_TOKEN_TTL_MIN` mà quên nới chỗ này sẽ mở lại đúng khe
    hở mà mốc dựng ra để bịt, nên hai con số phải là **một**.
    """
    return settings.ACCESS_TOKEN_TTL_MIN * 60


async def block_jti(redis: Redis, claims: AccessTokenClaims, *, now: datetime | None = None) -> int:
    """`SET bl:jti:{jti} 1 EX <thời gian còn lại>` — nửa Redis của logout.

    Trả về TTL đã đặt (giây) để chỗ gọi log được con số thật — DoD T-2.4 đo
    đúng nó bằng `redis-cli TTL`.

    `max(1, ...)`: Redis từ chối `EX 0` và `EX` âm. Về lý thì không tới được
    (token đã qua `exp` thì `decode_access_token` đã ném `TokenExpiredError`
    từ trước), nhưng `logout` cố ý **tha** token hết hạn (xem `api/v1/auth.py`)
    nên đường đó có thật. `ceil` chứ không `int`: cắt xuống là để khoá chết
    sớm hơn token nó chặn, đúng một giây — nhỏ, nhưng sai chiều.
    """
    cutoff = now or datetime.now(UTC)
    ttl_s = max(1, math.ceil((claims.expires_at - cutoff).total_seconds()))
    await redis.set(jti_key(claims.jti), BLOCKED_VALUE, ex=ttl_s)
    return ttl_s


async def set_user_cutoff(
    redis: Redis, user_id: uuid.UUID, *, now: datetime | None = None
) -> float:
    """`SET bl:user:{uid} <now> EX 900` — nửa Redis của "đổi mật khẩu" (§11.3).

    Trả về mốc đã ghi để chỗ gọi log/test đọc lại được đúng giá trị.
    """
    cutoff = (now or datetime.now(UTC)).timestamp()
    await redis.set(user_key(user_id), repr(cutoff), ex=user_cutoff_ttl())
    return cutoff


async def is_blocked(redis: Redis, claims: AccessTokenClaims) -> bool:
    """Token này có nằm trong blacklist nào không — phép kiểm của mọi request.

    Ngoại lệ của Redis **không** bị nuốt ở đây: chỗ gọi (`app/core/deps.py`)
    mới là nơi biết phải trả lời người dùng thế nào khi Redis chết.
    """
    jti_value, cutoff_value = await redis.mget([jti_key(claims.jti), user_key(claims.user_id)])

    if jti_value is not None:
        return True
    if cutoff_value is None:
        return False

    try:
        cutoff = float(cutoff_value)
    except (TypeError, ValueError):
        # Khoá đúng tên nhưng nội dung không đọc được (ai đó `SET` tay lúc
        # debug, hoặc một phiên bản trước ghi định dạng khác). Chặn, không tha:
        # khoá này chỉ tồn tại vì có người đã yêu cầu thu hồi.
        return True
    return claims.issued_at.timestamp() < cutoff


async def revoke_all_sessions(
    session: AsyncSession, redis: Redis, user_id: uuid.UUID, *, now: datetime | None = None
) -> float:
    """Nhánh "đổi mật khẩu" của §11.3: revoke **mọi** refresh family + đặt mốc.

    Hai nửa đi liền nhau, luôn luôn — xem docstring module. Trả về mốc đã ghi.

    **Không** `commit()`: hàm này chạy *trong* transaction của chỗ gọi, để một
    lần đổi mật khẩu thất bại không để lại một tài khoản đã bị thu hồi sạch
    phiên mà mật khẩu thì vẫn như cũ. Nửa Redis đứng sau nửa Postgres vì thứ
    tự ngược lại có một khe: mốc đã đặt mà `UPDATE` trượt ⇒ refresh token cũ
    vẫn sống và sẽ đổi ra access token mới sau 15 phút.
    """
    await RefreshTokenRepository(session).revoke_all_families(user_id)
    return await set_user_cutoff(redis, user_id, now=now)
