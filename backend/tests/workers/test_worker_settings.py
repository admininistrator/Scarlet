"""`WorkerSettings` phải nói đúng ba điều với arq — và nói bằng tên arq đọc.

Không có test nào ở đây kiểm nghiệp vụ: `generate` của T-1.5 mới là khung.
Thứ được kiểm là **cấu hình**, vì cả ba tham số của T-1.5 đều hỏng theo kiểu
im lặng:

- sai `name` → `api` enqueue vào một tên không ai đăng ký, job nằm mãi trong
  hàng đợi mà không có lỗi nào;
- mất `max_tries=1` → arq quay về mặc định **5**, và mỗi lần thử lại là một
  hoá đơn nữa cho cùng một câu hỏi (mục "Cạm bẫy" của T-1.5);
- gõ sai tên thuộc tính trong `WorkerSettings` → `arq.worker.get_kwargs` lọc
  theo chữ ký của `Worker` nên thuộc tính lạ bị **bỏ qua lặng lẽ**, worker vẫn
  chạy, chỉ là chạy bằng mặc định của arq.

Vì vậy ca cuối dựng `Worker` thật bằng chính `create_worker` mà lệnh `arq`
dùng, rồi đọc lại giá trị trên đối tượng đó — không đọc lại hằng của mình.
"""

from __future__ import annotations

from arq.worker import Worker, create_worker

from app.config.settings import settings
from app.workers.main import (
    FUNCTIONS,
    GENERATE_JOB_NAME,
    GENERATE_MAX_TRIES,
    WorkerSettings,
    redis_settings,
)


def test_dung_mot_job_ten_generate() -> None:
    """§7.2 bước ① viết `enqueue('generate', ...)` — tên đó là giao kèo."""
    assert [f.name for f in FUNCTIONS] == ["generate"]
    assert GENERATE_JOB_NAME == "generate"


def test_generate_khong_bao_gio_thu_lai() -> None:
    assert GENERATE_MAX_TRIES == 1


def test_redis_settings_doc_tu_env_chu_khong_phai_mac_dinh_arq() -> None:
    """Mặc định của arq là `localhost:6379`; trong compose host là `redis`."""
    conn = redis_settings()
    assert str(settings.REDIS_URL).startswith(f"redis://{conn.host}:{conn.port}")
    assert conn.host != "localhost"


def test_worker_that_nhan_du_ba_tham_so() -> None:
    """Dựng `Worker` đúng đường mà lệnh `arq` đi, rồi đọc lại trên đối tượng."""
    worker: Worker = create_worker(WorkerSettings)

    generate = worker.functions["generate"]
    assert generate.max_tries == 1, "mất max_tries=1 -> arq quay về mặc định 5"
    assert generate.timeout_s == settings.GENERATE_TIMEOUT_S

    # `health_check_interval` và `redis_settings` chỉ có tác dụng nếu arq thật
    # sự nhận được chúng — xem lý do ở docstring module.
    assert worker.health_check_interval == settings.WORKER_HEARTBEAT_S
    assert worker.redis_settings is not None
    assert worker.redis_settings.host == redis_settings().host


def test_job_timeout_lon_hon_timeout_http_cua_tang_model() -> None:
    """Hai timeout lồng nhau: cái trong (HTTP) phải nổ trước cái ngoài (arq).

    Ngược lại thì arq huỷ job giữa lúc model đang sinh — tiền vẫn mất, mà
    worker mất luôn quyền ghi `status`/`usage`/`XADD done`.
    """
    assert settings.GENERATE_TIMEOUT_S > settings.LLM_REQUEST_TIMEOUT_S
