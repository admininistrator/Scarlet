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

    # ═══ Đăng ký & bảo mật ═══
    REGISTRATION_MODE: Literal["open", "approval", "invite"] = "approval"
    TURNSTILE_SITE_KEY: str = ""
    TURNSTILE_SECRET: SecretStr = SecretStr("")
    EMAIL_TOKEN_TTL_MIN: int = Field(default=60, gt=0)
    ACCESS_TOKEN_TTL_MIN: int = Field(default=15, gt=0)
    REFRESH_TOKEN_TTL_DAYS: int = Field(default=30, gt=0)
    ARGON2_TIME_COST: int = Field(default=3, gt=0)
    ARGON2_MEMORY_KIB: int = Field(default=65536, gt=0)

    # ═══ Streaming (§7) ═══
    STREAM_TTL_S: int = Field(default=3600, gt=0)
    STREAM_HEARTBEAT_S: int = Field(default=15, gt=0)
    WORKER_HEARTBEAT_S: int = Field(default=15, gt=0)
    REAPER_STALE_S: int = Field(default=90, gt=0)
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

    # ═══ Context & vision (§9.6, §15.3) ═══
    CONTEXT_WINDOW_CAP: int = Field(default=128000, gt=0)
    RESERVE_TOKENS: int = Field(default=1000, ge=0)
    VISION_MAX_EDGE_PX: int = Field(default=1568, gt=0)
    VISION_MAX_BYTES: int = Field(default=3_500_000, gt=0)
    MAX_PDF_PAGES_VISION: int = Field(default=10, gt=0)
    RESEND_IMAGES_IN_HISTORY: bool = False

    # ═══ Web tools (§12) ═══
    TAVILY_API_KEY: SecretStr = SecretStr("")
    FETCHER_BASE_URL: HttpUrlStr = "http://fetcher:8080"
    MAX_FETCH_MB: int = Field(default=5, gt=0)
    MAX_REDIRECTS: int = Field(default=5, ge=0)
    JS_ESCALATE_MIN_CHARS: int = Field(default=200, ge=0)
    FETCH_TIMEOUT_S: int = Field(default=10, gt=0)
    PLAYWRIGHT_TIMEOUT_S: int = Field(default=20, gt=0)

    # ═══ Sandbox (§13) ═══
    SANDBOX_BASE_URL: HttpUrlStr = "http://sandbox:8090"
    SANDBOX_TIMEOUT_S: int = Field(default=30, gt=0)
    MAX_SKILL_OUTPUT_MB: int = Field(default=20, gt=0)

    # ═══ Upload (§15.2) ═══
    ALLOWED_UPLOAD_MIME: str = (
        "image/png,image/jpeg,image/webp,image/gif,application/pdf,"
        "text/plain,text/markdown,"
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
    def _warn_on_boot(self) -> Settings:
        if not self.TURNSTILE_SECRET.get_secret_value().strip():
            logger.warning(
                "TURNSTILE_SECRET rỗng — bỏ qua kiểm tra Turnstile khi đăng ký. "
                "Chỉ chấp nhận ở môi trường dev (KH Phụ lục B)."
            )
        return self

    @property
    def allowed_upload_mime(self) -> tuple[str, ...]:
        """``ALLOWED_UPLOAD_MIME`` đã tách thành tuple — allowlist của §15.2."""
        return tuple(part.strip() for part in self.ALLOWED_UPLOAD_MIME.split(",") if part.strip())


#: Instance dùng chung. Khởi tạo ngay lúc import để app fail-fast khi boot (L2).
settings = Settings()
