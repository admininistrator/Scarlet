"""Khung lỗi DUY NHẤT của HTTP API — §18 (B-86, chốt ở NQ-25).

KH tham chiếu: §18, §20, §23 `core/errors.py` · CLAUDE.md A10 · B-86.

§18 mở đầu bằng một câu áp cho toàn bộ mặt API:

    { "error": { "code": "QUOTA_EXCEEDED", "message": "…", "details": {...} } }

Cho tới hết T-1.7 không endpoint nào làm việc đó — FastAPI trả
`{"detail": "..."}` và **mã HTTP là thứ duy nhất FE đọc được**. Điều đó đủ khi
người đọc là `curl`, và hỏng ở T-1.14: `sse.ts` phải phân biệt "chưa đăng
nhập" với "model đã tắt" với "hết quota" để hiện ba màn hình khác nhau, mà một
câu tiếng Việt thì không so sánh được. B-86 ghi lệch này lại và giao cho task
đầu tiên có nhiều mã lỗi — T-1.8; file này là phần trả nợ đó, làm **trước**
task và thành một commit riêng.

**Vì sao là exception handler toàn cục, không phải sửa từng chỗ raise.**
Phân nửa số lỗi của một app FastAPI không đi qua code của mình: body sai kiểu
(`RequestValidationError`), đường dẫn không tồn tại (404 của router), method
sai (405), một `Depends` ném `HTTPException`. Đổi hình dạng ở chỗ nào *mình*
raise thì ba nguồn kia vẫn trả dạng cũ, và FE lại phải biết hai dạng.

**Vì sao `ApiError` kế thừa `HTTPException` thay vì là một kiểu mới.**
Starlette đã bắt `HTTPException` ở đúng mọi chỗ cần bắt (dependency,
background task, route); kế thừa nó nghĩa là không có đường nào lọt. Cái nó
thêm vào là hai trường mà §18 đòi còn `HTTPException` không có: `code` và
`details`.

**Vì sao bảng mã này TÁCH khỏi `app/streaming/events.py::ErrorCode`.** Hai
bảng trả lời hai câu khác nhau: bảng kia là "lượt sinh chết vì cái gì" (đi
trên dây SSE và vào cột `messages.error_code`), bảng này là "request HTTP bị
từ chối vì cái gì". Gộp lại thì `UNAUTHENTICATED` phải nằm cạnh
`PERSIST_FAILED`, và mỗi bên kéo bên kia theo mỗi lần mở rộng. Chỗ hai bảng
nói cùng một chuyện — `MESSAGE_NOT_FOUND`, `MODEL_UNKNOWN` — **cố ý** dùng
đúng một chuỗi, để FE không phải học hai tên cho một nghĩa.

**§20 sống ở hai chỗ trong file này:** `message` của lỗi 500 là câu cố định
chứ không phải `str(exc)` (traceback là bản đồ nội thất của server); và
`details` của lỗi 422 chỉ mang `loc`/`msg`/`type`, **không** mang `input` —
`input` của `POST /conversations/{id}/messages` chính là câu người dùng vừa gõ.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class ApiErrorCode(StrEnum):
    """Giá trị của `error.code` — hợp đồng với FE, không phải chuỗi tự do.

    Thêm mã mới là thêm một dòng ở đây, **không** phải một chuỗi rời rạc nằm
    trong router: một mã chỉ có ích nếu FE tìm được nó bằng cách đọc một danh
    sách.
    """

    # ── khung HTTP: dùng khi một `HTTPException` trần đi qua handler ──
    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"

    # ── danh tính (§18.1) ──
    #: `POST /auth/login` sai email hoặc sai mật khẩu (T-2.3). Một mã cho cả
    #: hai lý do — cùng tinh thần chống dò của §11.5: nói rõ "email không tồn
    #: tại" là mời kẻ tấn công dò danh sách người dùng.
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    #: Access JWT còn đúng chữ ký nhưng đã qua `exp` (T-2.3, DoD: "phân biệt
    #: với token sai"). Token sai chữ ký/định dạng vẫn dùng `UNAUTHENTICATED`
    #: — FE xử lý cả hai như nhau (đẩy về đăng nhập), mã riêng này chỉ để log
    #: và để test phân biệt được hai đường.
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    #: Access JWT còn hạn và đúng chữ ký nhưng đã bị thu hồi (§11.3, T-2.4):
    #: `jti` nằm trong `bl:jti:`, hoặc `iat` cũ hơn mốc `bl:user:` do một lần
    #: đổi mật khẩu/suspend đặt xuống. Mã riêng cùng lý lẽ với `TOKEN_EXPIRED`:
    #: FE xử lý như nhau (đẩy về đăng nhập), nhưng "phiên này đã bị đóng" và
    #: "token hỏng" là hai sự kiện khác nhau trong log — và là hai đường mà
    #: test của C21 phải phân biệt được, nếu không một `UNAUTHENTICATED` do
    #: **thiếu** cookie sẽ đọc y hệt một lần chặn thành công.
    TOKEN_REVOKED = "TOKEN_REVOKED"

    # ── đăng ký (§11.6, T-2.1) ──
    #: `len(password) < settings.PASSWORD_MIN_LENGTH`.
    PASSWORD_TOO_SHORT = "PASSWORD_TOO_SHORT"
    #: Điểm zxcvbn dưới `settings.PASSWORD_MIN_ZXCVBN_SCORE` — mật khẩu nằm
    #: trong nhóm quá phổ biến/dễ đoán (Cạm bẫy T-2.1: không nói gì thêm về
    #: LÝ DO cụ thể ngoài "quá phổ biến", tránh dạy kẻ tấn công cách né).
    PASSWORD_TOO_WEAK = "PASSWORD_TOO_WEAK"

    #: Turnstile không qua (§11.6, RR-1, T-2.6): thiếu token, token giả, token
    #: đã tiêu, hoặc token của một site key khác. **Một** mã cho cả bốn, cùng
    #: lý lẽ với `INVALID_CREDENTIALS` ở trên và với `TOKEN_INVALID` của
    #: `reset-password`: việc FE phải làm giống hệt nhau ở mọi ca — gọi
    #: `turnstile.reset()` rồi bảo người dùng thử lại — nên hai mã cho một
    #: nghĩa là đúng thứ docstring của bảng này cấm. Lý do thật (`error-codes`
    #: của Cloudflare) đi vào **log**, không vào response.
    #:
    #: KHÔNG dùng cho "không hỏi được Cloudflare": đó là `SERVICE_UNAVAILABLE`
    #: (503) — xem `app/core/turnstile.py`, mục vì sao không cho qua.
    TURNSTILE_FAILED = "TURNSTILE_FAILED"

    # ── email token (§11.5, T-2.2) ──
    #: `POST /auth/verify-email` với một token chưa từng tồn tại (không khớp
    #: `token_hash` nào) hoặc đúng hash nhưng sai `purpose`. KHÔNG dùng cho
    #: token hết hạn (đó là `200 {"status":"expired"}`, xem DoD T-2.2) hay
    #: token đã dùng (đó là idempotent-success, cùng lý lẽ UC-01).
    TOKEN_INVALID = "TOKEN_INVALID"

    # ── máy trạng thái tài khoản (§11.1, UC-01, T-2.7) ──
    #: Trạng thái `pending_email` gọi một endpoint đòi email đã xác thực —
    #: UC-01 gọi đích danh mã này ("Chưa verify email → `403` với
    #: `code=EMAIL_NOT_VERIFIED`"). Không dùng `FORBIDDEN` trần: FE phải hiện
    #: đúng nút "gửi lại thư xác thực", một việc khác hẳn với mọi 403 khác.
    EMAIL_NOT_VERIFIED = "EMAIL_NOT_VERIFIED"
    #: Trạng thái `pending_approval` chat bằng **system key** (§11.1, UC-01).
    #: Mã riêng chứ không chung với `EMAIL_NOT_VERIFIED` vì việc FE phải làm
    #: khác hẳn: ở đây không có nút nào để bấm, chỉ một banner "đang chờ
    #: duyệt" — và KHÔNG trả mã này khi người đó đã cấu hình BYOK, vì lúc ấy
    #: họ chat được (§10.5: họ không tiêu tiền của mình).
    PENDING_APPROVAL = "PENDING_APPROVAL"
    #: Tài khoản `rejected` hoặc `suspended` (§11.1 — hai hàng cuối, mọi ô đều
    #: "—"). **Một** mã cho cả hai, đúng luật của bảng này: việc FE phải làm
    #: giống hệt nhau ở cả hai ca — đóng phiên, hiện màn "tài khoản không dùng
    #: được, liên hệ quản trị" — nên hai mã ở đây là hai tên cho một nghĩa.
    #: Trạng thái cụ thể đi trong `details.status` (cho log và cho admin), chỗ
    #: nó không mời FE mọc thêm một nhánh rẽ. Không rò gì cho người lạ: mã này
    #: chỉ đến sau khi người gọi đã chứng minh được danh tính (đúng mật khẩu ở
    #: `/auth/login`, hoặc một access token còn hạn ở mọi route khác).
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"

    # ── admin (§16.3, §18.5, §20, T-2.16) ──
    #: Danh tính hợp lệ nhưng `role != admin` (§16.3 — *"mọi endpoint
    #: `/api/v1/admin/*` kiểm lại quyền phía server, không tin FE"*). Mã riêng
    #: chứ không `FORBIDDEN` trần vì việc FE phải làm khác hẳn mọi 403 khác của
    #: bảng này: không có nút nào để bấm, không có thư nào để gửi lại — nó gỡ
    #: mục `/admin` khỏi menu và đưa người dùng về trang chính (T-2.19 DoD dòng
    #: 2). `403` chứ không `404`: che đường dẫn `/admin/*` không giấu được gì
    #: (§16.3 công bố chúng), và một `404` ở đây sẽ làm admin thật tưởng mình
    #: gõ nhầm URL.
    ADMIN_REQUIRED = "ADMIN_REQUIRED"
    #: `POST /admin/users/{id}/approve|reject|suspend` cho một tài khoản đang ở
    #: trạng thái mà §11.1 không có mũi tên nào đi từ đó tới đích — ví dụ duyệt
    #: một `pending_email` (họ phải bấm link xác thực trước, không ai bấm hộ
    #: được). `409` chứ không `400`: dữ liệu gửi lên hoàn toàn hợp lệ, thứ sai
    #: là **trạng thái hiện tại** của tài nguyên — và nó đổi được, nên FE có
    #: một hành động cụ thể (tải lại danh sách). `details` mang
    #: `{"status", "target_status", "allowed_from"}` để màn hình nói được câu
    #: đúng thay vì "thao tác không hợp lệ".
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    #: `id` trong đường dẫn `/admin/users/{id}` không có hàng nào (chưa từng
    #: tồn tại, hoặc đã xoá mềm). Mã riêng với `NOT_FOUND` trần cùng lý lẽ
    #: `PROVIDER_KEY_NOT_FOUND`: nó nghĩa là "danh sách đang hiện đã cũ", một
    #: việc cụ thể. **Không** phải một ca §20/IDOR — admin được phép hỏi về mọi
    #: tài khoản, nên ở đây `404` nói đúng sự thật chứ không che giấu gì.
    USER_NOT_FOUND = "USER_NOT_FOUND"

    #: `PATCH /admin/tiers/{name}` cho một tên không có trong bảng `tiers`
    #: (T-2.20, §10.4). Mã riêng chứ không dùng `NOT_FOUND` chung: màn hình
    #: §16.3 gọi endpoint này ngay cạnh `PATCH /admin/users/{id}`, và một mã
    #: chung sẽ bắt người đọc lỗi đoán xem thứ không tìm thấy là tài khoản hay
    #: hạn mức — cùng lý lẽ đã tách `USER_NOT_FOUND` khỏi `NOT_FOUND`.
    TIER_NOT_FOUND = "TIER_NOT_FOUND"

    # ── chat (§18.2) ──
    #: `Last-Event-ID` / `?cursor=` không phải một Redis Stream ID.
    CURSOR_INVALID = "CURSOR_INVALID"
    #: Message không tồn tại, đã xoá mềm, hoặc của người khác — §20 gộp ba ca.
    #: Cùng chuỗi với `streaming.events.ErrorCode.MESSAGE_NOT_FOUND`, cố ý.
    MESSAGE_NOT_FOUND = "MESSAGE_NOT_FOUND"
    #: Hội thoại không tồn tại, đã xoá mềm, hoặc của người khác (§20, cùng lối).
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    #: `parent_id` client gửi lên (C14) không nằm trong hội thoại này.
    PARENT_NOT_FOUND = "PARENT_NOT_FOUND"
    #: `model_id` không có trong catalog hoặc đã `enabled: false` (§9.2).
    #: Cùng chuỗi với `streaming.events.ErrorCode.MODEL_UNKNOWN`, cố ý.
    MODEL_UNKNOWN = "MODEL_UNKNOWN"
    #: Không request nào chỉ định model và model `default` cũng đã bị tắt.
    NO_MODEL_AVAILABLE = "NO_MODEL_AVAILABLE"
    #: Không đẩy được job vào hàng đợi (Redis hỏng) — §7.2 ① không hoàn tất.
    ENQUEUE_FAILED = "ENQUEUE_FAILED"
    #: Không đặt được cờ huỷ `cancel:{id}` của §7.5 (Redis hỏng). Mã riêng chứ
    #: không phải `SERVICE_UNAVAILABLE` trần, cùng lý lẽ với `ENQUEUE_FAILED`:
    #: FE cần phân biệt "nút Dừng chưa ăn, bấm lại đi" với một lỗi lập trình,
    #: và người dùng đang nhìn chữ vẫn chảy nên câu trả lời phải nói đúng việc.
    CANCEL_FAILED = "CANCEL_FAILED"
    #: Người này đã có `MAX_CONCURRENT_STREAMS` lượt sinh chưa khép
    #: (`queued`/`streaming`) và vừa xin mở thêm một lượt nữa — §10.6 hàng
    #: "Đồng thời", T-2.9, B-85. `429` chứ không `403`: request **sẽ** hợp lệ
    #: ngay khi một lượt đang chạy khép lại, nên FE có một hành động cụ thể để
    #: đề nghị (đợi, hoặc bấm Dừng ở một lượt khác).
    #:
    #: Mã RIÊNG chứ không dùng chung `RATE_LIMITED`, dù cả hai đều `429`: hai
    #: câu trả lời khác nhau cho người dùng. `RATE_LIMITED` là "bạn bấm quá
    #: nhanh, chờ N giây" và kèm `Retry-After` — một con số có thật. Mã này là
    #: "bạn đang có ba câu trả lời cùng chảy", và nó **không** kèm
    #: `Retry-After` vì không ai biết model sẽ sinh xong lúc nào; đoán một con
    #: số ở đây là nói dối bằng một header mà client sẽ tin.
    #: `details` mang `{"limit", "active"}` để FE nói được câu đúng.
    TOO_MANY_STREAMS = "TOO_MANY_STREAMS"

    # ── quota (§10.2, UC-07, S6, T-2.11) ──
    #: Dự toán trường hợp xấu nhất của lượt sinh này cộng với chi tiêu đã có
    #: vượt hạn mức của một trong hai cửa sổ trượt (§10.3). §18 dùng đúng mã
    #: này làm ví dụ cho khung lỗi chung, nên tên nó là hợp đồng chứ không phải
    #: một lựa chọn.
    #:
    #: `429` chứ không `402`/`403`, và mã RIÊNG chứ không dùng chung
    #: `RATE_LIMITED` dù cả hai đều `429`: ba câu trả lời khác nhau cho người
    #: dùng. `RATE_LIMITED` là "bạn bấm quá nhanh", `TOO_MANY_STREAMS` là "bạn
    #: đang có ba câu trả lời cùng chảy", còn mã này là "bạn đã tiêu hết tiền
    #: của kỳ này" — UC-07 đòi FE hiện **thời điểm chính xác** quota được hoàn
    #: lại, một màn hình không màn nào kia cần.
    #:
    #: `details` mang `{"limit_type", "retry_after", "limit_usd", "spent_usd",
    #: "estimate_usd"}`. `limit_type ∈ {"5h", "weekly"}` là chữ của UC-07.
    #: `retry_after` **có thể `null`**: khi một lượt sinh đơn lẻ đã vượt trần
    #: thì nhả hết cả cửa sổ cũng không đủ, và không có thời điểm nào để hẹn —
    #: cùng lý lẽ đã chốt cho `TOO_MANY_STREAMS`, đoán một con số ở đó là nói
    #: dối bằng một header client sẽ tin.
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"

    # ── idempotency (§11.4, ADR-15, T-2.8) ──
    #: POST vào một route bắt buộc `Idempotency-Key` mà thiếu header đó (A8
    #: gọi đích danh `POST /conversations/{id}/messages`). `400` chứ không
    #: `422`: đây là một header thiếu, không phải một giá trị sai kiểu, và
    #: DoD T-2.8 dòng 3 ghi thẳng con số này. `details.header` mang đúng tên
    #: header để FE không phải đoán từ câu tiếng Việt.
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    #: Một request **cùng** `Idempotency-Key` đang được xử lý (§11.4 gọi đích
    #: danh `409 {code:"IN_PROGRESS"}`). Không phải lỗi của người dùng: nó
    #: nghĩa là "cái bạn vừa bấm đang chạy rồi", nên FE chỉ cần đợi — khác hẳn
    #: `GENERATION_IN_PROGRESS` (409 của `retry`), thứ nói về một **message**
    #: chưa khép chứ không về một request trùng.
    IN_PROGRESS = "IN_PROGRESS"

    # ── BYOK (§10.5, §18.4, T-2.14) ──
    #: `provider` trong đường dẫn `/settings/keys/{provider}` không có trong
    #: `model_catalog.json::providers`. Mã riêng chứ không `NOT_FOUND` trần,
    #: cùng lý lẽ với `MODEL_UNKNOWN`: FE hiện danh sách provider lấy từ
    #: catalog, nên mã này nghĩa là "danh sách của bạn đã cũ, tải lại đi" —
    #: một việc cụ thể, khác hẳn mọi 404 khác.
    PROVIDER_UNKNOWN = "PROVIDER_UNKNOWN"
    #: Provider có thật nhưng `byok_supported: false` (§9.2) — ví dụ một
    #: gateway chạy nội bộ, nơi khoá riêng không có nghĩa gì. `400` chứ không
    #: `404`: đường dẫn đúng, thứ sai là điều người gọi muốn làm với nó.
    BYOK_NOT_SUPPORTED = "BYOK_NOT_SUPPORTED"
    #: Provider đã trả lời và câu trả lời là khoá này không dùng được (401/403
    #: ở `GET {base_url}{verify_path}`) — §10.5 "kiểm key sống trước khi lưu",
    #: DoD T-2.14 dòng 4. Thông điệp đi kèm **không bao giờ** chứa chuỗi khoá
    #: (C20). Không dùng cho "không hỏi được provider": đó là `503`
    #: `SERVICE_UNAVAILABLE`, xem `app/llm/byok_verify.py`.
    PROVIDER_KEY_REJECTED = "PROVIDER_KEY_REJECTED"
    #: `DELETE /settings/keys/{provider}` cho một provider mà người này chưa
    #: cấu hình khoá. Mã riêng với `PROVIDER_UNKNOWN`: ở đó FE phải tải lại
    #: catalog, ở đây nó chỉ cần bỏ một dòng khỏi danh sách đang hiện.
    PROVIDER_KEY_NOT_FOUND = "PROVIDER_KEY_NOT_FOUND"

    # ── nhánh (§8.2, T-1.13) ──
    #: Thao tác nhánh gọi nhầm `role`: `retry` chỉ chạy trên message
    #: `assistant`, `PATCH /messages/{id}` chỉ chạy trên message `user` (§18.2).
    #: `details` mang `{"role", "expected"}` để FE nói được câu đúng thay vì
    #: "yêu cầu không hợp lệ". Một mã cho cả hai chiều vì đây là **cùng** một
    #: chuyện — "thao tác này không áp dụng cho loại message kia" — và hai mã
    #: cho một nghĩa là đúng thứ docstring của bảng này cấm.
    MESSAGE_ROLE_MISMATCH = "MESSAGE_ROLE_MISMATCH"
    #: `retry` trên một message còn `queued`/`streaming`. 409 chứ không 400:
    #: request **sẽ** hợp lệ sau khi lượt đang chạy khép lại (hoặc sau khi bấm
    #: Dừng, §7.5), nên FE có một hành động cụ thể để đề nghị. Để nó đi qua sẽ
    #: mở hai lượt sinh cho cùng một `parent_id` và trả tiền hai lần.
    GENERATION_IN_PROGRESS = "GENERATION_IN_PROGRESS"
    #: `active_leaf_id` gửi lên `PATCH /conversations/{id}` không nằm trong hội
    #: thoại đó. Mã riêng chứ không dùng chung `PARENT_NOT_FOUND`: hai trường
    #: khác nhau của hai request khác nhau, và §20 vẫn được giữ — câu trả lời
    #: không nói message ấy có thật ở đâu khác hay không.
    LEAF_NOT_FOUND = "LEAF_NOT_FOUND"


#: `HTTPException` trần (của mình hoặc của Starlette) ánh xạ sang mã nào. Chỉ
#: là lưới đỡ: mọi chỗ raise trong `app/` nên dùng `ApiError` với một mã nói
#: đúng chuyện gì đã xảy ra. Bảng này tồn tại cho 404-không-có-route và 405
#: của Starlette, hai thứ không đi qua code của mình.
_THEO_STATUS: dict[int, ApiErrorCode] = {
    400: ApiErrorCode.BAD_REQUEST,
    401: ApiErrorCode.UNAUTHENTICATED,
    403: ApiErrorCode.FORBIDDEN,
    404: ApiErrorCode.NOT_FOUND,
    405: ApiErrorCode.METHOD_NOT_ALLOWED,
    409: ApiErrorCode.CONFLICT,
    422: ApiErrorCode.VALIDATION_ERROR,
    429: ApiErrorCode.RATE_LIMITED,
    503: ApiErrorCode.SERVICE_UNAVAILABLE,
}

#: Câu trả cho lỗi 500. Cố định, không nội suy `str(exc)` — xem docstring module.
LOI_500 = "loi noi bo, xem log cua server"


class ErrorBody(BaseModel):
    """Ba trường của §18. `details` luôn có mặt (rỗng thì `{}`).

    Luôn có mặt chứ không `null`: FE đọc thẳng `err.details` mà không phải hỏi
    trước nó có tồn tại không, và một trường khi có khi không là chỗ sinh ra
    đúng loại `undefined is not an object` mà không test nào bắt.
    """

    code: ApiErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    """Toàn bộ body của MỌI response lỗi. Không có dạng thứ hai."""

    error: ErrorBody


class ApiError(StarletteHTTPException):
    """`HTTPException` có mang theo `code` và `details` của §18.

    Dùng nó thay `HTTPException` ở mọi chỗ trong `app/api/` và `app/core/`:
    `HTTPException` trần vẫn ra đúng khung (handler bên dưới lo), nhưng mã của
    nó chỉ suy được từ status — tức `NOT_FOUND` cho cả "hội thoại không có"
    lẫn "message cha không thuộc hội thoại này", và FE mất đúng thứ B-86 nói.
    """

    def __init__(
        self,
        status_code: int,
        code: ApiErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.details = details or {}


def _tra_ve(status_code: int, body: ErrorBody, headers: Mapping[str, str] | None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: Exception) -> Response:
    """Mọi `HTTPException` — của mình, của Starlette (404 route, 405) — ra §18.

    `headers` giữ nguyên: 401 kèm `WWW-Authenticate` và 429 kèm `Retry-After`
    mất tác dụng nếu handler này nuốt chúng.
    """
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - Starlette bảo đảm kiểu
        raise exc
    if isinstance(exc, ApiError):
        code, details = exc.code, exc.details
    else:
        code = _THEO_STATUS.get(exc.status_code, ApiErrorCode.INTERNAL_ERROR)
        details = {}
    return _tra_ve(
        exc.status_code,
        ErrorBody(code=code, message=str(exc.detail), details=details),
        exc.headers,
    )


async def validation_exception_handler(request: Request, exc: Exception) -> Response:
    """Body/query/header sai kiểu → 422 `VALIDATION_ERROR`.

    `details.fields` chỉ giữ `loc`/`msg`/`type` của pydantic. Hai lý do, cả
    hai đều cần: (a) §20 — `input` mà pydantic trả về chính là nội dung người
    dùng vừa gõ, nó không có việc gì phải quay ngược ra khỏi server một lần
    nữa; (b) `ctx` của pydantic có thể chứa object Python (một `ValueError`
    chẳng hạn) và `JSONResponse` chết khi serialize nó — một lỗi 422 biến
    thành một lỗi 500.
    """
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - FastAPI bảo đảm kiểu
        raise exc
    fields = [
        {
            "loc": [str(phan) for phan in loi.get("loc", ())],
            "msg": loi.get("msg", ""),
            "type": loi.get("type", ""),
        }
        for loi in exc.errors()
    ]
    return _tra_ve(
        422,
        ErrorBody(
            code=ApiErrorCode.VALIDATION_ERROR,
            message="du lieu gui len khong hop le",
            details={"fields": fields},
        ),
        None,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """Ngoại lệ không ai bắt → 500 đúng khung, và **một dòng log có traceback**.

    Không có handler này thì Starlette trả `Internal Server Error` dạng chữ
    trơn: FE parse JSON thất bại rồi hiện "lỗi không rõ" — đúng lúc thứ nó cần
    hiện là một mã để bấm Retry.
    """
    logger.exception("loi khong bat duoc tai %s %s", request.method, request.url.path)
    return _tra_ve(500, ErrorBody(code=ApiErrorCode.INTERNAL_ERROR, message=LOI_500), None)


def register(app: FastAPI) -> None:
    """Gắn ba handler vào app. `main.py` gọi đúng một lần lúc dựng app."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
