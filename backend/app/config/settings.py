"""Cấu hình ứng dụng — nơi DUY NHẤT trong backend đọc biến môi trường.

KH tham chiếu: §19.2 (L2), §19.3 · Tiêu chí S1 · CLAUDE.md A3, A4.

Ba luật của file này:

1. Biến **bắt buộc** không có giá trị mặc định. Thiếu một biến → ``Settings()``
   raise ``ValidationError`` có chứa đúng tên biến, tiến trình thoát mã ≠ 0.
2. Biến **tuỳ chọn** có default ở đây và phải có mặt trong ``.env.example``.
   ``tests/test_settings_complete.py`` so hai tập hợp theo cả hai chiều.
3. App **không** tự đọc file ``.env``: docker compose nạp nó qua ``env_file``
   (KH Phụ lục C). Nhờ vậy biến môi trường là nguồn sự thật duy nhất và
   ``unset VAR`` đủ để tái hiện lỗi thiếu biến — không có file nào âm thầm
   vá lại giá trị.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

#: Độ dài tối thiểu của secret sinh bằng ``openssl rand -hex 32`` (§19.3).
MIN_SECRET_CHARS = 32

#: Trần độ dài của ``messages.feedback_reason`` — lý do kèm Like/Dislike
#: (§18.2, T-3.7a). A3 cấm một *giới hạn* nằm rải trong ``.py``, nên nó ở đây;
#: ``api/v1/messages.py`` đọc nó làm ``max_length`` của schema request.
#:
#: **Một hằng module chứ không một field của ``Settings``**, khác hẳn
#: ``MESSAGE_MAX_CHARS`` ngay bên dưới, và khác biệt ấy có lý do đo được: con
#: số này còn là một ``CHECK`` trên DDL (migration 0005). Một field ``.env``
#: sửa được lúc chạy thì nới nó lên mà không kèm migration sẽ biến một ``422``
#: gọn gàng thành một ``IntegrityError`` từ Postgres, tức ``500``.
#: ``MESSAGE_MAX_CHARS`` không có ràng buộc ấy — nó chỉ sống ở tầng schema — nên
#: nó được phép là một biến môi trường.
#:
#: **Vì sao 2000.** ``messages`` là bảng nóng nhất của app: mọi truy vấn đường
#: đi (§8.3) kéo cả hàng về, nên một trường tự do không trần là một hàng có thể
#: phình vô hạn trên đúng đường đi nóng nhất (Cạm bẫy ① của T-3.7a). 2000 ký tự
#: đủ cho vài đoạn văn giải thích "câu trả lời sai chỗ nào" và chặn đứng ngả
#: dán cả một file log vào ô lý do.
FEEDBACK_REASON_MAX_CHARS = 2000

#: Trần độ dài ``conversations.title``, tính bằng **ký tự** — một hợp đồng, hai
#: người ghi (T-S.7): người dùng qua ``POST``/``PATCH /conversations`` (schema của
#: ``api/v1/conversations.py``) và lượt đặt tên tự động (``workers/title.py``
#: cắt tiêu đề model trả về theo đúng con số này). Hai chỗ đọc một hằng, nên một
#: tiêu đề tự đặt không bao giờ dài hơn thứ người dùng được phép tự gõ lại.
#: Hằng module chứ không field ``.env``: cùng loại với trần trên — nó là hình
#: dạng của một trường API, không phải nút vặn vận hành. Cột là ``TEXT`` không
#: ``CHECK``. Giá trị 200 là con số hai schema ấy đã có từ T-1.2.
CONVERSATION_TITLE_MAX_CHARS = 200

_HTTP_URL = TypeAdapter(AnyHttpUrl)


def _http_url(value: str) -> str:
    """Kiểm dạng URL rồi trả lại chuỗi gốc, đã bỏ dấu ``/`` thừa ở cuối.

    Không dùng thẳng ``AnyHttpUrl`` làm kiểu của field vì pydantic chuẩn hoá
    ``https://localhost`` thành ``https://localhost/``; nối thêm đường dẫn sau
    đó sẽ ra ``https://localhost//api/v1``.
    """
    _HTTP_URL.validate_python(value)
    return value.rstrip("/")


HttpUrlStr = Annotated[str, AfterValidator(_http_url)]


def _unix_socket_url(value: str) -> str:
    """``unix://`` + đường dẫn tuyệt đối tới socket (T-7.2, Phụ lục C cách a).

    ``sandbox`` chạy ``network_mode: none`` (ADR-09) nên không URL HTTP nào tới
    được nó; nhận ``http://…`` là để worker boot rồi hỏng lúc gọi.
    """
    path = value.removeprefix("unix://")
    if path == value or not path.startswith("/"):
        raise ValueError("phải có dạng unix:///đường/dẫn/tuyệt/đối")
    return value


UnixSocketUrlStr = Annotated[str, AfterValidator(_unix_socket_url)]


class Settings(BaseSettings):
    """Toàn bộ biến môi trường của backend. Thứ tự nhóm bám theo KH Phụ lục B."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="forbid")

    # ═══ BẮT BUỘC — thiếu bất kỳ biến nào, app KHÔNG boot (S1) ═══
    DATABASE_URL: PostgresDsn
    REDIS_URL: RedisDsn
    JWT_SECRET: SecretStr
    MASTER_ENCRYPTION_KEY: SecretStr
    LITELLM_MASTER_KEY: SecretStr
    LITELLM_BASE_URL: HttpUrlStr
    PUBLIC_BASE_URL: HttpUrlStr
    ARTIFACTS_BASE_URL: HttpUrlStr

    MINIO_ENDPOINT: HttpUrlStr
    MINIO_ACCESS_KEY: SecretStr
    MINIO_SECRET_KEY: SecretStr
    MINIO_BUCKET: str = Field(min_length=1)
    # T-4.1 — region ghim cho `app/core/storage.py`. Phải khớp `MINIO_REGION`
    # của server MinIO (mặc định của nó là `us-east-1`). Không có biến này thì
    # SDK hỏi region qua mạng trước MỖI lần ký URL (Cạm bẫy ② của T-4.1).
    MINIO_REGION: str = Field(default="us-east-1", min_length=1)

    # ═══ Provider keys — CỐ Ý KHÔNG CÓ Ở ĐÂY (NQ-15, B-26, T-0.12) ═══
    # `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `NINEROUTER_*`, `OLLAMA_*`… sống
    # trong `.env.providers` và chỉ service `litellm` đọc. Backend không gọi
    # provider trực tiếp (A9: chỉ nói chuyện với LiteLLM), nên khai chúng ở đây
    # vừa là biến chết, vừa buộc mỗi provider mới phải sửa file `.py` này —
    # trái tiêu chí S15 ("thêm provider = 0 dòng code"). Thông tin cần cho
    # backend về provider (base_url, health_path) nằm trong `model_catalog.json`.

    # ═══ Email ═══
    SMTP_HOST: str = "mailpit"
    SMTP_PORT: int = Field(default=1025, gt=0, lt=65536)
    SMTP_USER: str = ""
    SMTP_PASSWORD: SecretStr = SecretStr("")
    SMTP_TLS: bool = False
    MAIL_FROM: str = "Scarlet <no-reply@scarlet.local>"
    #: Trần thời gian cho MỘT lần gọi `smtplib.SMTP(...)` (connect + login +
    #: send), chạy trong `asyncio.to_thread` (T-2.2, `core/mailer.py`). Là một
    #: *giới hạn* nên nó ở đây chứ không phải hằng trong `mailer.py` (A3, §19.2
    #: L4) — cùng họ với `FETCH_TIMEOUT_S`/`SANDBOX_TIMEOUT_S`.
    SMTP_TIMEOUT_S: int = Field(default=10, gt=0)

    # ═══ Đăng ký & bảo mật ═══
    REGISTRATION_MODE: Literal["open", "approval", "invite"] = "approval"
    #: Khoá CÔNG KHAI của widget — backend không dùng nó để kiểm gì cả; nó đi
    #: ra FE qua `VITE_TURNSTILE_SITE_KEY` mà `docker-compose.yml` ánh xạ từ
    #: chính biến này (một nguồn sự thật, xem `components/auth/Turnstile.tsx`).
    #: Vẫn khai ở đây vì `.env.example` là hợp đồng với người vận hành và
    #: `tests/test_settings_complete.py` so hai tập hợp theo cả hai chiều.
    TURNSTILE_SITE_KEY: str = ""
    TURNSTILE_SECRET: SecretStr = SecretStr("")
    #: Endpoint `siteverify` của Cloudflare. Ở đây chứ không phải một chuỗi
    #: trong `app/core/turnstile.py` vì A3/§19.2 L1 xếp "URL provider" vào danh
    #: sách literal bị cấm, và §19.1 xếp "endpoint hạ tầng" vào `.env` — cùng
    #: hàng với `LITELLM_BASE_URL`, `FETCHER_BASE_URL`, `SANDBOX_BASE_URL`.
    TURNSTILE_VERIFY_URL: HttpUrlStr = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    #: Trần thời gian cho MỘT lần gọi `siteverify`. Biến RIÊNG chứ không dùng
    #: lại `FETCH_TIMEOUT_S` (§12, đường fetch URL do người dùng gửi): hai chặng
    #: mạng khác nhau tới hai bên khác nhau, và gộp lại thì nới cái này sẽ nới
    #: luôn cái kia. Nằm ở đây chứ không phải một số trong `core/turnstile.py`
    #: vì đó là một *giới hạn* (A3, §19.2 L4) — cùng họ `SMTP_TIMEOUT_S`.
    TURNSTILE_TIMEOUT_S: int = Field(default=10, gt=0)
    EMAIL_TOKEN_TTL_MIN: int = Field(default=60, gt=0)
    ACCESS_TOKEN_TTL_MIN: int = Field(default=15, gt=0)
    REFRESH_TOKEN_TTL_DAYS: int = Field(default=30, gt=0)
    ARGON2_TIME_COST: int = Field(default=3, gt=0)
    #: DoD T-2.1 đòi thời gian hash 50–200 ms ("quá nhanh nghĩa là tham số quá
    #: yếu"). Mặc định cũ của argon2-cffi (65536 KiB = 64 MiB) đo được ~35 ms
    #: trên máy dev — dưới sàn. Đo lại 5 lần với `time_cost=3` cố định (chi
    #: tiết ở báo cáo T-2.1): 98304→~53 ms (sát sàn, rủi ro), 131072→~74 ms,
    #: **196608 (192 MiB)→~108–126 ms** — giữa khoảng, còn dư cả hai chiều nếu
    #: máy chạy thật nhanh/chậm hơn máy dev. Tăng bộ nhớ chứ không tăng
    #: `ARGON2_TIME_COST`: OWASP khuyến nghị ưu tiên bộ nhớ trước vì đó là thứ
    #: GPU/ASIC khó rẻ hoá song song nhất.
    ARGON2_MEMORY_KIB: int = Field(default=196608, gt=0)
    #: §11.6: "Độ dài tối thiểu 12 ký tự". Một *giới hạn* nên nó ở đây chứ
    #: không phải hằng trong `app/core/security.py` (A3, §19.2 L4).
    PASSWORD_MIN_LENGTH: int = Field(default=12, gt=0)
    #: Hạn mức theo IP cho route **gửi thư** chưa đăng nhập (§10.6 "quên mật
    #: khẩu: 3/giờ", §18.1 "`/auth/resend-verification` — Rate limit 3/giờ").
    #: Cửa sổ (3600 s) là quy đổi đơn vị của chính tên biến nên nó nằm trong
    #: `app/core/ratelimit.py`; con số 3 là một *giới hạn* nên nó ở đây (A3).
    RATE_LIMIT_EMAIL_IP_PER_HOUR: int = Field(default=3, gt=0)
    #: Hạn mức theo IP cho route `/auth/*` KHÔNG gửi thư (`logout`,
    #: `reset-password`). Con số lấy từ nhóm `auth` của §10.6 ("auth: 5/phút"),
    #: đổi trục đếm từ user sang IP vì những route này chạy khi chưa có user
    #: (B-131). Biến RIÊNG chứ không dùng lại biến trên: một bên bảo vệ hộp thư
    #: của người khác (đắt, đếm theo giờ), bên kia chỉ chặn gọi dồn dập (rẻ,
    #: đếm theo phút) — gộp lại thì siết cái này sẽ siết luôn cái kia.
    RATE_LIMIT_AUTH_IP_PER_MIN: int = Field(default=5, gt=0)
    #: Hạn mức **theo user** của nhóm route `chat` (§10.6 hàng 2: "chat:
    #: 20/phút"). Vừa là sức chứa của xô, vừa là tốc độ nạp lại: xô đầy 20
    #: token và nạp lại đúng 20 token mỗi phút, nên nó cho phép bùng phát 20
    #: lượt rồi hồi lại đều — đó là khác biệt giữa token bucket và cửa sổ cố
    #: định của lớp theo IP ngay trên. Cửa sổ (60 s) là quy đổi đơn vị của
    #: chính tên biến nên nó nằm trong `app/core/ratelimit.py`; con số 20 là
    #: một *giới hạn* nên nó ở đây (A3, §19.2 L4).
    #:
    #: Nhóm `auth` của cùng hàng đó đã có mặt ở `RATE_LIMIT_AUTH_IP_PER_MIN`
    #: (trục IP, NQ-43 — route `/auth/*` không có user để đếm theo).
    RATE_LIMIT_CHAT_PER_MIN: int = Field(default=20, gt=0)
    #: Nhóm `upload` của cùng hàng §10.6 (10/phút) — `POST /attachments`
    #: (T-4.2, B-148). Cùng token bucket với `chat`.
    RATE_LIMIT_UPLOAD_PER_MIN: int = Field(default=10, gt=0)
    #: Ngưỡng điểm zxcvbn (0–4, xem `app/core/security.py`) để coi một mật
    #: khẩu là "quá phổ biến" (§11.6 cho phép `zxcvbn` hoặc danh sách 10k
    #: top; chọn zxcvbn vì nó mang sẵn tập tần suất mật khẩu rò rỉ thật và
    #: chạy offline sau khi cài, không cần vendor một file danh sách mà repo
    #: này không có cách xác minh nguồn gốc). Đo được `password1234` → điểm 1,
    #: mật khẩu ngẫu nhiên dài → điểm 4; ngưỡng 2 chặn đúng hai điểm thấp nhất.
    PASSWORD_MIN_ZXCVBN_SCORE: int = Field(default=2, ge=0, le=4)

    # ═══ API (§18.2) ═══
    #: Số hội thoại tối đa một trang của `GET /conversations` — vừa là mặc định,
    #: vừa là trần cho `?limit=`. Ở đây chứ không phải một số trong
    #: `api/v1/conversations.py` vì `ConversationRepository.list_conversations`
    #: cố ý bắt caller truyền `limit` (A3, §19.2 L4): hạn mức là cấu hình.
    #: Một biến chứ không phải hai (mặc định + trần): chưa màn hình nào cần xin
    #: nhiều hơn một trang, và hai nút vặn cho một con số là hai chỗ để lệch.
    CONVERSATION_PAGE_SIZE: int = Field(default=30, gt=0)
    #: Trần của `GET /conversations?pinned=true` (§24.2b·S8, S14 — T-S.8): mục
    #: "Đã ghim" của sidebar nhận **mọi** hội thoại ghim trong một response,
    #: không con trỏ. Vượt trần ⇒ trả đúng ngần này hàng kèm `truncated: true`,
    #: không phải lỗi. Là một *giới hạn* ⇒ ở đây (A3, §19.2 L4). Biến **riêng**,
    #: không dùng `CONVERSATION_PAGE_SIZE`: ghim là tập người dùng tự chọn và
    #: phải hiện đủ, còn trang là lát cắt của một danh sách vô hạn — hai con số
    #: trả lời hai câu hỏi khác nhau.
    CONVERSATION_PINNED_MAX: int = Field(default=100, gt=0)
    #: Số dòng tối đa một trang của `GET /admin/audit-logs` (§16.3, T-2.20) —
    #: vừa là mặc định, vừa là trần cho `?limit=`, cùng lối
    #: `CONVERSATION_PAGE_SIZE` ngay trên. Một biến **riêng** chứ không dùng
    #: chung con số của sidebar: hai màn hình khác nhau về hình dạng (một danh
    #: sách tiêu đề ngắn, một bảng sổ nhiều cột) và về người xoay nút — người
    #: vận hành đang dò một sự cố muốn 200 dòng một trang, còn sidebar thì
    #: không. 50 là con số §16.3 không viết ra, nên nó là một *giới hạn* và
    #: thuộc về đây chứ không phải `api/v1/admin.py` (A3, §19.2 L4).
    AUDIT_LOG_PAGE_SIZE: int = Field(default=50, gt=0)
    #: Tuổi thọ kết quả healthcheck mà `GET /admin/system` dùng lại (T-3.12,
    #: B-192). Không có nó thì mỗi lần mở màn "Hệ thống" là năm lượt đi mạng,
    #: trong đó 9Router ~850 ms — một màn hình chẩn đoán biến thành máy phát
    #: request tới nhà cung cấp mỗi lần ai đó bấm F5. Màn hình ghi "Kiểm lúc …"
    #: theo mốc server trả về, nên con số cũ tới ngần này giây là con số người
    #: đọc NHÌN THẤY là cũ. Là một *giới hạn* ⇒ ở đây (A3, §19.2 L4).
    #: `GET /health/deep` **không** đọc nó: máy hỏi thì luôn đo tươi.
    ADMIN_HEALTH_CACHE_TTL_S: int = Field(default=10, gt=0)
    #: Trần độ dài cửa sổ của `GET /admin/usage`, tính bằng ngày (T-3.12,
    #: B-175). Số hàng của báo cáo tỉ lệ với số NGÀY trong cửa sổ, không bị R1
    #: chặn như `GET /admin/users`; một `since=2020-01-01` là vài nghìn hàng.
    #: Trần chứ không phân trang: báo cáo là TỔNG HỢP (`totals`, theo ngày/user/
    #: model), và một tổng không chia trang được. Màn "Chi phí" hỏi 7 và 30.
    ADMIN_USAGE_MAX_WINDOW_DAYS: int = Field(default=92, gt=0)
    #: Tuổi thọ bản ghi `idem:{user_id}:{route}:{key}` của §11.4 — dùng cho cả
    #: hai trạng thái (`in_progress` lúc `SET NX`, `done` lúc ghi response).
    #: Giá trị 86400 là con số §11.4/ADR-15 viết ra ("Redis `SET NX` TTL 24h").
    #: Là một *giới hạn* nên nó ở đây chứ không phải hằng trong
    #: `app/core/idempotency.py` (A3, §19.2 L4) — cùng họ `CANCEL_TTL_S`,
    #: `STREAM_TTL_S`.
    IDEMPOTENCY_TTL_S: int = Field(default=86400, gt=0)

    # ═══ Streaming (§7) ═══
    STREAM_TTL_S: int = Field(default=3600, gt=0)
    STREAM_HEARTBEAT_S: int = Field(default=15, gt=0)
    #: Nhịp worker ghi `messages.heartbeat_at` trong lúc sinh (§7.6). Kể từ
    #: T-1.10 nó mang **đúng một** nghĩa: nhịp healthcheck của container là
    #: `WORKER_HEALTHCHECK_S` ngay dưới (B-74, NQ-27).
    WORKER_HEARTBEAT_S: int = Field(default=15, gt=0)
    #: Tuổi tối đa của `heartbeat_at` trước khi reaper §7.6 coi lượt sinh là
    #: mồ côi. Quan hệ với biến trên là một *tỉ lệ*: `REAPER_STALE_S /
    #: WORKER_HEARTBEAT_S` = số nhịp được phép lỡ (mặc định 90/15 = 6).
    REAPER_STALE_S: int = Field(default=90, gt=0)
    #: Tuổi tối đa của một message còn `queued` trước khi reaper §7.6 coi là mồ
    #: côi (B-123). Đo trên `created_at`, **không** phải `heartbeat_at`: message
    #: `queued` chưa bao giờ có nhịp tim vì `mark_streaming` — chỗ đặt
    #: `heartbeat_at` — đúng là bước chưa chạy.
    #:
    #: Biến RIÊNG chứ không dùng lại `REAPER_STALE_S`: hai trạng thái trả lời
    #: hai câu hỏi khác nhau. `streaming` hỏi "worker còn sống không" (90 s là
    #: sáu nhịp tim bị lỡ); `queued` hỏi "còn ai sẽ nhận job này không", và câu
    #: đó bị chi phối bởi arq chứ không bởi nhịp tim.
    #:
    #: **Vì sao 1200 chứ không nhỏ hơn.** Sau SIGKILL, arq giữ khoá
    #: `arq:in-progress:` thêm `GENERATE_TIMEOUT_S + 10` giây (đo được 906 s ở
    #: B-72) rồi mới chọn lại job và từ chối bằng `max retries 1 exceeded` —
    #: trước mốc đó job **vẫn có thể chạy**, và dọn sớm là báo lỗi cho một câu
    #: hỏi sắp được trả lời. 1200 s cho ~290 s biên trên 910 s. Hạ xuống dưới
    #: `GENERATE_TIMEOUT_S` là đua với arq, và người thua là người dùng.
    #:
    #: Dọn sớm **không** gây sinh hai lần: `mark_streaming` đòi `status='queued'`
    #: nên một worker tới muộn sẽ nhận `False` và bỏ lượt (đúng lối B-72).
    REAPER_QUEUED_STALE_S: int = Field(default=1200, gt=0)
    #: Nhịp worker ghi khoá `arq:queue:health-check` — thứ mà `arq --check`
    #: (healthcheck của service `worker`) đọc. Mặc định của arq là **3600 s**:
    #: để nguyên thì worker chết lúc 00:01 mà 00:59 `docker compose ps` vẫn báo
    #: `healthy`, đúng dạng xanh giả của B-47/B-49/B-59.
    #:
    #: Biến RIÊNG chứ không dùng lại `WORKER_HEARTBEAT_S` (B-74, NQ-27): hai
    #: nhịp trả lời hai câu hỏi khác nhau cho hai người đọc khác nhau — một bên
    #: là reaper so `messages.heartbeat_at` trong SQL, bên kia là Docker đọc một
    #: khoá Redis có TTL = nhịp + 1 s. Dùng chung một biến thì nới nhịp ghi DB
    #: sẽ **đồng thời** nới cửa sổ phát hiện worker chết và siết tỉ lệ nhịp
    #: được phép lỡ ở trên — ba hệ quả từ một nút vặn, không ai nhận ra.
    WORKER_HEALTHCHECK_S: int = Field(default=15, gt=0)
    #: ─── Ba biến của vòng nối lại trong `app/workers/run.py` (B-196) ───
    #:
    #: Đo được ba lần khi rà P2: một lần Redis khởi động lại là đủ giết vòng
    #: lặp chính của arq (`ConnectionError (104, 'Connection reset by peer')`),
    #: mà **tiến trình không thoát** — `/proc/1/stat` vẫn `S`, `wchan` là
    #: `do_epoll_wait`, `RestartCount=0`. `restart: unless-stopped` của Docker
    #: chỉ nhìn mã thoát nên nó không bao giờ kích hoạt; job nằm mãi ở `queued`
    #: và màn chat của người dùng kẹt mà không một dòng lỗi nào ở đâu cả.
    #:
    #: Cả ba là *giới hạn vận hành* nên chúng ở đây chứ không phải ba số trong
    #: `run.py` (A3, §19.2 L4) — cùng họ `SMTP_TIMEOUT_S`, `ARQ_POLL_DELAY_S`.
    #:
    #: Khoảng chờ trước lần dựng lại ĐẦU TIÊN. Nhỏ, vì ca thường gặp nhất là
    #: `docker compose restart redis` — Redis quay lại sau vài giây.
    WORKER_RECONNECT_BACKOFF_S: float = Field(default=1.0, gt=0)
    #: Trần của khoảng chờ khi nhân đôi. Ca nó phục vụ là Redis chết **lâu**:
    #: không có trần thì sau một đêm khoảng chờ dài hơn cả sự cố, và worker
    #: ngủ tiếp trong khi Redis đã sống lại từ lâu.
    WORKER_RECONNECT_BACKOFF_MAX_S: float = Field(default=30.0, gt=0)
    #: Trần cho lượt đóng worker cũ trước khi dựng bản mới. Có trần vì
    #: `Worker.close()` của arq gọi `pool.delete(health_check_key)` và
    #: `on_shutdown` — cả hai đều đi qua Redis, tức **đúng thứ vừa chết**.
    #: Không kẹp thì vòng nối lại treo ngay ở bước dọn dẹp, và ta chỉ đổi một
    #: kiểu treo lấy một kiểu treo khác.
    WORKER_SHUTDOWN_TIMEOUT_S: float = Field(default=10.0, gt=0)
    #: Khoảng cách giữa hai lần worker hỏi Redis "có job mới không" (B-104).
    #:
    #: Mặc định của arq là **0.5 s**, và T-1.12 đo được đúng con số đó nằm
    #: chình ình trong TTFT của **mọi** model: chặng `202` → event `start` có
    #: p95 0.486–0.505 s và `max` 0.494–0.510 s ở cả bốn model — trần bằng
    #: đúng `poll_delay`, không phải đặc tính của model nào. Với
    #: `ol-qwen-small` (upstream 0.048 s) thì ~85% TTFT là chờ arq nhặt job.
    #:
    #: Là một *giới hạn vận hành* nên nó ở đây chứ không phải một số trong
    #: `WorkerSettings` (A3, §19.2 L4) — khác `REAPER_EVERY_N_SECONDS`, vốn là *độ
    #: phân giải* của một phép quét và chỉ nhận ước của 60.
    #:
    #: Giá trị 0.1 đổi ~0.2 s p50 TTFT cho mọi model, giá là worker quay vòng
    #: Redis nhiều hơn 5× khi rỗi — với 15–20 người dùng thì gần như miễn phí.
    #: **Hạ dưới 0.5 s KHÔNG phá lịch cron của §7.6**: arq 0.28 tự kẹp
    #: `cron_window_size = max(poll_delay, 0.5)` (`arq/worker.py`), nên reaper
    #: vẫn nổ đúng một lần mỗi tick `{0, 30}`.
    ARQ_POLL_DELAY_S: float = Field(default=0.1, gt=0)
    MAX_CONCURRENT_STREAMS: int = Field(default=3, gt=0)
    #: Tuổi thọ của cờ huỷ `cancel:{message_id}` (§7.5). Là một *giới hạn* nên
    #: nó ở đây chứ không phải một số trong `app/streaming/cancel.py` (A3,
    #: §19.2 L4) — cùng họ với `STREAM_TTL_S`. Giá trị 300 là con số §7.5 viết
    #: ra (`EX 300`); nó chỉ cần **lớn hơn** khoảng thời gian từ lúc bấm Dừng
    #: tới lúc worker đọc chunk tiếp theo, nên rộng rãi thế này là để phòng ca
    #: message còn `queued` và worker chưa nhận job.
    CANCEL_TTL_S: int = Field(default=300, gt=0)

    # ═══ Worker & hàng đợi (ADR-02, §5.2) ═══
    #: Trần thời gian của MỘT job `generate`. Phải **lớn hơn**
    #: `LLM_REQUEST_TIMEOUT_S`: hai timeout này lồng nhau, và cái trong phải nổ
    #: trước. Nếu arq cắt job khi model vẫn đang sinh thì tiền vẫn mất mà worker
    #: mất luôn quyền ghi `status`/`usage`/`XADD done` — message kẹt ở
    #: `streaming` cho tới khi reaper §7.6 dọn. Đây là một *giới hạn* nên nó ở
    #: đây chứ không phải hằng trong `app/workers/main.py` (A3, §19.2 L4).
    GENERATE_TIMEOUT_S: int = Field(default=900, gt=0)

    # ═══ Quota (§10) ═══
    QUOTA_WINDOW_SHORT_S: int = Field(default=18000, gt=0)
    QUOTA_WINDOW_LONG_S: int = Field(default=604800, gt=0)
    DAILY_ALERT_USD: Decimal = Field(default=Decimal("2.00"), ge=0)
    MONTHLY_BUDGET_USD: Decimal = Field(default=Decimal("30.00"), ge=0)
    #: TTL của cache hạn mức trong Redis (§10.4, T-2.10). 60 s là con số §10.4
    #: viết ra, và nó là **AC của UC-07**: admin đổi `limit_5h_usd` thì hiệu lực
    #: phải tới trong ngần ấy giây mà không restart gì. Đây là một *giới hạn*
    #: nên nó ở đây chứ không phải hằng trong `app/quota/tiers.py` (A3, L4).
    TIER_CACHE_TTL_S: int = Field(default=60, gt=0)
    #: Ngưỡng cảnh báo "sắp hết quota" (T-2.11). UC-07 dòng 1 viết ra con số
    #: này: *"Còn ≤ 20% quota → hiện thanh cảnh báo, không chặn"*. Nó là một
    #: **giới hạn** nên nó ở đây chứ không phải hằng trong
    #: `app/quota/estimator.py` (A3, §19.2 L4) — và nó là nút vặn đầu tiên
    #: người vận hành muốn xoay khi cả nhóm kêu bị cảnh báo quá sớm hoặc quá
    #: muộn. `le=100` vì "còn hơn 100% quota" không phải một trạng thái.
    QUOTA_WARN_REMAINING_PCT: int = Field(default=20, ge=0, le=100)

    # ═══ Provider layer (§9.1) ═══
    #: Timeout HTTP của chặng backend → LiteLLM. Phải ≥ `request_timeout` trong
    #: `config/litellm.config.yaml` (chặng LiteLLM → provider), nếu không
    #: backend cắt trước và LiteLLM vẫn sinh tiếp — vẫn tính tiền mà không ai
    #: đọc. Đây là một *giới hạn*, nên nó ở đây chứ không phải hằng trong
    #: `adapters/system.py` (A3).
    LLM_REQUEST_TIMEOUT_S: int = Field(default=600, gt=0)
    #: `temperature` gửi cho model. `LLMClient.stream()` (§9.1) đòi tham số này
    #: nên phải có một giá trị; để nó thành hằng trong `workers/generate.py` là
    #: chỗ cứng đúng loại A3 cấm. Mặc định **1.0** = giá trị mặc định của Chat
    #: Completions, tức backend không áp ý kiến riêng lên model — và là giá trị
    #: duy nhất mà các model reasoning không từ chối. Tuỳ chọn theo từng người
    #: dùng thuộc `user_settings` (§18.4, Phase 2), không phải biến này.
    LLM_TEMPERATURE: float = Field(default=1.0, ge=0.0, le=2.0)
    #: Trần thời gian cho MỘT lần gọi `GET {base_url}{verify_path}` để xác nhận
    #: một khoá BYOK còn sống trước khi lưu (§10.5, T-2.14,
    #: `app/llm/byok_verify.py`). Là một *giới hạn* nên nó ở đây chứ không phải
    #: một số trong module đó (A3, §19.2 L4) — cùng họ `TURNSTILE_TIMEOUT_S`,
    #: `SMTP_TIMEOUT_S`, `FETCH_TIMEOUT_S`.
    #:
    #: Biến RIÊNG chứ không dùng lại `LLM_REQUEST_TIMEOUT_S` (600 s): đó là trần
    #: của một lượt **sinh chữ** đi qua LiteLLM, thứ có quyền chảy mười phút.
    #: Người dùng ở đây đang ngồi nhìn một nút "Lưu khoá" quay, nên chặng này
    #: phải bỏ cuộc theo đơn vị giây. Gộp hai biến thì nới cái kia sẽ treo màn
    #: hình cài đặt.
    BYOK_VERIFY_TIMEOUT_S: int = Field(default=10, gt=0)
    #: Endpoint BYOK do người dùng tự nhập (T-S.19b, NQ-134 ②). Trần số endpoint
    #: mỗi người, số model mỗi endpoint, độ dài tên endpoint / tên model.
    BYOK_ENDPOINTS_MAX_PER_USER: int = Field(default=5, gt=0)
    BYOK_ENDPOINT_MODELS_MAX: int = Field(default=50, gt=0)
    BYOK_ENDPOINT_NAME_MAX_CHARS: int = Field(default=128, gt=0)
    #: Model tự nhập không có trong catalog nên không ai khai `context_window` /
    #: `max_output` cho nó — hai con số này đứng thay, cho ngân sách §9.6.
    BYOK_ENDPOINT_CONTEXT_WINDOW: int = Field(default=64000, gt=0)
    BYOK_ENDPOINT_MAX_OUTPUT: int = Field(default=4096, gt=0)
    #: Nhịp của lượt đo provider `host-dependent` chạy nền trong `api`
    #: (`app/core/provider_health.py`, T-S.4, NQ-113) — cũng là tuổi mà FE coi
    #: `checked_at` của `GET /models` là cũ (`stale_after_s`). Hai hằng số của
    #: T-3.6 trong `.py` chuyển về đây vì chúng là *giới hạn* (A3, §19.2 L4).
    #:
    #: 30 s: đủ thưa để 9Router (đo ~0.7–2.5 s mỗi lượt) không thành tải, đủ
    #: dày để bật 9Router lên rồi mở picker là thấy hàng sáng lại trong khoảng
    #: một nhịp. Mỗi tiến trình `api` đo riêng (Cạm bẫy ② T-S.4).
    PROVIDER_HEALTH_TTL_S: int = Field(default=30, gt=0)
    #: Trần cho MỘT lượt đo, và cũng là trần mà `api` chờ lượt đo đầu lúc khởi
    #: động. Rộng hơn `CHECK_TIMEOUT_S` (2 s) của `/health/deep` có chủ ý: một
    #: lần chạm trần ở đây xám một model đang chạy được suốt một nhịp trước mặt
    #: người dùng. Giá của trần rộng chỉ trả khi host **im lặng** — và từ T-S.4
    #: nó rơi vào tác vụ nền, không rơi vào request nào.
    PROVIDER_PROBE_TIMEOUT_S: float = Field(default=5.0, gt=0)

    # ═══ Context & vision (§9.6, §15.3) ═══
    #: Trần độ dài MỘT message người dùng gửi lên, tính bằng ký tự (B-205,
    #: NQ-78). Áp ở biên vào cho cả `POST /conversations/{id}/messages` lẫn
    #: `PATCH /messages/{id}`, và FE đọc lại con số này qua `GET /auth/me` —
    #: không ô nhập nào được tự đặt một trần riêng (A3, §19.2 L4).
    #:
    #: **Vì sao 24000.** Trước NQ-78, thứ chặn đầu tiên là `token_budget()` của
    #: §9.6, tức một lần dán quá dài chỉ nổ ở `llm/context.py` **giữa lượt
    #: sinh** — sau khi đã tạo hai hàng `messages` và đã tiêu một lượt
    #: `Idempotency-Key`. Để trần này thật sự là cửa **đầu tiên**, nó phải nằm
    #: dưới ngân sách token nhỏ nhất của catalog hôm nay: `ol-qwen-small` có
    #: `min(32768, CONTEXT_WINDOW_CAP) - 4096 - 1000 = 27672` token. 24000 ký
    #: tự nằm dưới con số đó **kể cả** ở tỷ lệ bi quan nhất 1 token/ký tự; đo
    #: thật trên văn bản Latin của dự án là ~3.1 ký tự/token (24001 ký tự →
    #: 7777 token), nên đây là một biên rộng chứ không phải một biên khít.
    #:
    #: Catalog sửa nóng được (§19.1), nên thêm một model có `context_window`
    #: nhỏ hơn ~28k token là lúc phải hạ con số này xuống theo — đó là lý do nó
    #: là một biến `.env` chứ không phải một hằng trong `api/v1/messages.py`.
    MESSAGE_MAX_CHARS: int = Field(default=24000, gt=0)
    #: Trần độ dài `users.display_name`, tính bằng **ký tự** như
    #: `MESSAGE_MAX_CHARS` (T-S.5 Cạm bẫy ③). Áp ở biên vào của `PUT /settings`;
    #: FE đọc lại chính con số này qua `GET /auth/me` (`display_name_max_chars`).
    #: Cột là `TEXT` không `CHECK`, nên nới con số này không cần migration.
    DISPLAY_NAME_MAX_CHARS: int = Field(default=64, gt=0)
    #: Trần đầu vào của lượt đặt tên hội thoại (§24.2b·S6, S14 — T-S.7): câu hỏi
    #: đầu dài hơn thì chỉ **ngần này ký tự đầu** vào prompt của `title_model`.
    #: Tiêu đề chỉ cần ý chính, và lượt này đi bằng tiền system mà không trừ
    #: quota ai — nên trần của nó phải nằm ở đây, không để một câu hỏi 24000 ký
    #: tự (`MESSAGE_MAX_CHARS`) biến lượt đặt tên thành lượt đắt nhất hội thoại.
    TITLE_INPUT_MAX_CHARS: int = Field(default=2000, gt=0)
    CONTEXT_WINDOW_CAP: int = Field(default=128000, gt=0)
    RESERVE_TOKENS: int = Field(default=1000, ge=0)
    VISION_MAX_EDGE_PX: int = Field(default=1568, gt=0)
    VISION_MAX_BYTES: int = Field(default=3_500_000, gt=0)
    MAX_PDF_PAGES_VISION: int = Field(default=10, gt=0)
    RESEND_IMAGES_IN_HISTORY: bool = False
    #: Token ước lượng cho MỘT ảnh được gửi (NQ-138 ④, T-4.4b) — cộng vào ngân
    #: sách §9.6 và dự toán §10.2. Một con số chứ không công thức: §15.3 không
    #: có công thức, mỗi provider tính một kiểu. Mặc định = số đo `claude-haiku`
    #: (ảnh cạnh dài 1568 sau T-4.3) làm tròn lên trăm. Ngoài Phụ lục B (B-348).
    VISION_TOKENS_PER_IMAGE: int = Field(default=1600, gt=0)
    #: Trần TỔNG chữ trích từ tệp của MỘT message (T-4.6a Cạm bẫy ②) — vượt ⇒
    #: `422` ở `POST …/messages`, trước khi có lượt sinh. Chữ tệp đi vòng qua
    #: `MESSAGE_MAX_CHARS`, nên tổng xấu nhất là hai trần cộng lại: 48000 ký tự
    #: ≈ 15k token (đo `o200k`, tiếng Việt ~3.2 ký tự/token) < 27672 của
    #: `ol-qwen-small`. Không còn an toàn ở tỷ lệ bi quan 1 token/ký tự như
    #: `MESSAGE_MAX_CHARS` — đã chọn có chủ ý (NQ-140). Ngoài Phụ lục B.
    ATTACHMENT_TEXT_MAX_CHARS: int = Field(default=24000, gt=0)
    #: Trần byte GIẢI NÉN của `word/document.xml` (T-4.6a, Cạm bẫy ⑥) — worker
    #: đọc tối đa trần + 1 byte rồi mới parse; vượt ⇒ `failed`. XML của DOCX
    #: nặng gấp nhiều lần chữ của nó, nên trần rộng hơn hẳn trần chữ.
    DOCX_XML_MAX_BYTES: int = Field(default=20 * 1024 * 1024, gt=0)

    # ═══ Artifacts (§14) ═══
    #: §14.1 hàng 2 — khối code KHÔNG tiêu đề thành artifact khi thân có ít nhất
    #: ngần này dòng (T-5.1). Khối có `title="…"` thì không cần ngưỡng. Ngoài
    #: Phụ lục B (B-360 ④).
    ARTIFACT_MIN_CODE_LINES: int = Field(default=20, gt=0)
    #: Trần tiêu đề artifact, tính bằng KÝ TỰ, sau khi bỏ ký tự điều khiển (T-5.1).
    ARTIFACT_TITLE_MAX_CHARS: int = Field(default=120, gt=0)

    # ═══ Web tools (§12) ═══
    #: Rỗng ⇒ app vẫn boot (tính năng tuỳ chọn, A4 chỉ áp cho biến bắt buộc);
    #: `web_search` trả `not_configured` mà không mở kết nối (T-6.1).
    TAVILY_API_KEY: SecretStr = SecretStr("")
    #: Endpoint Tavily — URL provider nên ở đây, không ở `tools/web_search.py`
    #: (A3, cùng lối `TURNSTILE_VERIFY_URL`). Ba biến dưới đọc LÚC GỌI.
    TAVILY_BASE_URL: HttpUrlStr = "https://api.tavily.com"
    #: Trần TỔNG cho một lượt tìm (cả kết nối lẫn đọc) — `float` để test đặt
    #: được trần dưới một giây. Biến riêng, không dùng lại `FETCH_TIMEOUT_S`.
    WEB_SEARCH_TIMEOUT_S: float = Field(default=10.0, gt=0)
    #: Số kết quả mặc định mỗi lượt; Tavily nhận tối đa 20.
    WEB_SEARCH_MAX_RESULTS: int = Field(default=5, gt=0, le=20)
    FETCHER_BASE_URL: HttpUrlStr = "http://fetcher:8080"
    MAX_FETCH_MB: int = Field(default=5, gt=0)
    MAX_REDIRECTS: int = Field(default=5, ge=0)
    JS_ESCALATE_MIN_CHARS: int = Field(default=200, ge=0)
    FETCH_TIMEOUT_S: int = Field(default=10, gt=0)
    PLAYWRIGHT_TIMEOUT_S: int = Field(default=20, gt=0)
    #: Vòng lặp tool của một lượt (T-6.7a, §13.5) — đọc LÚC GỌI. Hết vòng ⇒ lần
    #: gọi cuối KHÔNG gửi `tools`; estimator nhân `est_max` với `MAX_TOOL_ROUNDS
    #: + 1` (Q-P6-6). Lời gọi vượt `MAX_TOOL_CALLS_PER_TURN` (cả lượt) ⇒ `ok:
    #: false` cho model, không chạy.
    MAX_TOOL_ROUNDS: int = Field(default=3, ge=0)
    MAX_TOOL_CALLS_PER_TURN: int = Field(default=5, gt=0)
    #: Trần chữ MỘT kết quả tool lên dây, tính bằng KÝ TỰ. 24000 = trần
    #: `MESSAGE_MAX_CHARS`; đo T-6.7a: PEP 8 qua `fetcher` 40 971 ký tự ≈ 8 971
    #: token ⇒ cắt còn ~5.2k token. Cộng dồn trong lượt còn cắt mềm theo
    #: `token_budget()` (B-208 ⑤).
    TOOL_RESULT_MAX_CHARS: int = Field(default=24000, gt=0)

    # ═══ Sandbox (§13) ═══
    #: Socket trên volume chung `sandbox_socket` (`docker-compose.yml`, T-7.2).
    SANDBOX_BASE_URL: UnixSocketUrlStr = "unix:///run/sandbox/sandbox.sock"
    SANDBOX_TIMEOUT_S: int = Field(default=30, gt=0)
    MAX_SKILL_OUTPUT_MB: int = Field(default=20, gt=0)

    # ═══ Upload (§15.2) ═══
    ALLOWED_UPLOAD_MIME: str = (
        "image/png,image/jpeg,image/webp,image/gif,application/pdf,"
        # Không `text/markdown`: libmagic trả `text/plain` cho `.md` (NQ-138 ②).
        "text/plain,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    PRESIGN_TTL_S: int = Field(default=300, gt=0)

    # ═══ Vận hành ═══
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    DEBUG: bool = False
    RAW_RESPONSE_KEEP_DAYS: int = Field(default=30, ge=0)
    PURGE_AFTER_DAYS: int = Field(default=30, ge=0)

    @field_validator("JWT_SECRET", "MASTER_ENCRYPTION_KEY")
    @classmethod
    def _long_enough(cls, v: SecretStr, info: ValidationInfo) -> SecretStr:
        if len(v.get_secret_value()) < MIN_SECRET_CHARS:
            raise ValueError(f"{info.field_name} phải dài ≥ {MIN_SECRET_CHARS} ký tự")
        return v

    @field_validator("LITELLM_MASTER_KEY", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY")
    @classmethod
    def _not_blank(cls, v: SecretStr, info: ValidationInfo) -> SecretStr:
        # Biến bắt buộc để rỗng cũng là thiếu — chỉ khác ở chỗ khó thấy hơn.
        if not v.get_secret_value().strip():
            raise ValueError(f"{info.field_name} là biến bắt buộc, không được để rỗng")
        return v

    @model_validator(mode="after")
    def _reject_comment_values(self) -> Settings:
        """Giá trị bắt đầu bằng `#` là một chú thích bị nuốt — KHÔNG boot (A4).

        B-44/B-118: `KEY=<rỗng>   # ghi chú` trong `.env` cho ra giá trị là
        **nguyên câu ghi chú**, vì docker compose chỉ bóc `#` khi phía trước nó
        đã có giá trị. `tests/test_env_file_format.py` canh hai file `.env*` của
        repo này; lớp ở đây canh mọi đường còn lại — `environment:` gõ tay trong
        compose, một `export` trong shell, `.env` của máy khác.

        **Vì sao cần một lớp riêng dù đã có `_long_enough`/`_not_blank`.** Câu
        chú thích của `MASTER_ENCRYPTION_KEY` dài 37 ký tự, tức **qua** được
        ngưỡng `MIN_SECRET_CHARS = 32` — không có phép kiểm này thì T-2.14 sẽ
        mã hoá khoá BYOK của người dùng bằng một dòng ghi chú, và mọi thứ sẽ
        chạy đúng cho tới ngày ai đó sửa chú thích.

        **Vì sao `RuntimeError` chứ không `ValueError`.** pydantic bọc
        `ValueError` thành `ValidationError`, mà `ValidationError` in kèm
        `input_value=` — B-18 đã ghi lại đúng cái bẫy đó. `RuntimeError` đi
        thẳng ra ngoài, nên thông báo chỉ chứa **tên biến**, không chứa giá trị.

        Đánh đổi đã biết: một giá trị hợp lệ bắt đầu bằng `#` (mật khẩu chẳng
        hạn) sẽ bị từ chối. Không field nào hôm nay có hình dạng đó, và câu trả
        lời cho ca ấy là đổi giá trị — rẻ hơn nhiều so với một cấu hình rác chạy
        im lặng.
        """
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            if isinstance(value, str) and value.lstrip().startswith("#"):
                raise RuntimeError(
                    f"{name} đang mang giá trị là một CHÚ THÍCH, không phải giá trị thật "
                    f"(B-44/B-118). Trong `.env`, chú thích phải nằm ở dòng riêng phía "
                    f"trên phép gán — `{name}=` rồi khoảng trắng rồi `# …` cho ra giá trị "
                    f"là chính câu chú thích đó."
                )
        return self

    @model_validator(mode="after")
    def _warn_on_boot(self) -> Settings:
        if not self.TURNSTILE_SECRET.get_secret_value().strip():
            # "Bỏ qua âm thầm khi thiếu secret nghĩa là một ngày nào đó bạn
            # deploy production mà không có captcha và không biết" (Cạm bẫy
            # T-2.6). Dòng này là thứ DUY NHẤT nói ra điều đó, nên nó phải kêu
            # mỗi lần boot chứ không chỉ lần đầu — và phải nêu đủ CẢ HAI route
            # đang mất lớp bảo vệ (§11.6: đăng ký và quên mật khẩu).
            logger.warning(
                "TURNSTILE_SECRET rỗng — BỎ QUA kiểm tra Turnstile ở "
                "POST /auth/register và POST /auth/forgot-password. "
                "Chỉ chấp nhận ở môi trường dev (KH §11.6, Phụ lục B); "
                "RR-1 mất một trong bốn lớp chống đăng ký rác."
            )
        return self

    @property
    def allowed_upload_mime(self) -> tuple[str, ...]:
        """``ALLOWED_UPLOAD_MIME`` đã tách thành tuple — allowlist của §15.2."""
        return tuple(part.strip() for part in self.ALLOWED_UPLOAD_MIME.split(",") if part.strip())


#: Instance dùng chung. Khởi tạo ngay lúc import để app fail-fast khi boot (L2).
settings = Settings()
