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

from pathlib import Path

from arq import worker as arq_worker
from arq.worker import Worker, create_worker

import app.workers.main as worker_main
from app.config.settings import Settings, settings
from app.workers.main import (
    CRON_JOBS,
    FUNCTIONS,
    GENERATE_JOB_NAME,
    GENERATE_MAX_TRIES,
    WorkerSettings,
    redis_settings,
)
from app.workers.reaper import REAPER_JOB_NAME


def test_exactly_one_job_named_generate() -> None:
    """§7.2 bước ① viết `enqueue('generate', ...)` — tên đó là giao kèo."""
    assert [f.name for f in FUNCTIONS] == ["generate"]
    assert GENERATE_JOB_NAME == "generate"


def test_generate_never_retries() -> None:
    assert GENERATE_MAX_TRIES == 1


def test_redis_settings_from_env_not_arq_default() -> None:
    """Mặc định của arq là `localhost:6379`; trong compose host là `redis`."""
    conn = redis_settings()
    assert str(settings.REDIS_URL).startswith(f"redis://{conn.host}:{conn.port}")
    assert conn.host != "localhost"


def test_real_worker_gets_all_three_params() -> None:
    """Dựng `Worker` đúng đường mà lệnh `arq` đi, rồi đọc lại trên đối tượng."""
    worker: Worker = create_worker(WorkerSettings)

    generate = worker.functions["generate"]
    assert generate.max_tries == 1, "mất max_tries=1 -> arq quay về mặc định 5"
    assert generate.timeout_s == settings.GENERATE_TIMEOUT_S

    # `health_check_interval` và `redis_settings` chỉ có tác dụng nếu arq thật
    # sự nhận được chúng — xem lý do ở docstring module.
    assert worker.health_check_interval == settings.WORKER_HEALTHCHECK_S
    assert worker.redis_settings is not None
    assert worker.redis_settings.host == redis_settings().host

    # Cron của §7.6 cũng đi qua cùng cái phễu `get_kwargs`: gõ `cron_job` thay
    # vì `cron_jobs` thì arq bỏ qua lặng lẽ và reaper không bao giờ chạy.
    assert REAPER_JOB_NAME in worker.cron_jobs[0].name
    assert len(worker.cron_jobs) == len(CRON_JOBS)


def test_healthcheck_beat_separate_from_7_6_heartbeat() -> None:
    """B-74 → NQ-27: hai nhịp, hai biến, hai người đọc.

    `WORKER_HEARTBEAT_S` nay chỉ còn nghĩa "nhịp ghi `messages.heartbeat_at`"
    và là mẫu số của tỉ lệ `REAPER_STALE_S / WORKER_HEARTBEAT_S` (số nhịp được
    phép lỡ). `WORKER_HEALTHCHECK_S` là nhịp ghi khoá `arq:queue:health-check`
    mà `arq --check` đọc. Nối lại làm một thì vặn nhịp ghi DB sẽ đồng thời đổi
    cửa sổ phát hiện worker chết của Docker — đúng rủi ro B-74 nêu.
    """
    # Hai trường ĐỘC LẬP: vặn cái này không được kéo theo cái kia. Phép khẳng
    # định trên giá trị (`== settings.WORKER_HEALTHCHECK_S`) một mình là vô
    # dụng vì mặc định cả hai đều là 15 — nó xanh kể cả khi ai đó nối lại.
    assert Settings(WORKER_HEARTBEAT_S=99).WORKER_HEALTHCHECK_S == 15
    assert Settings(WORKER_HEALTHCHECK_S=99).WORKER_HEARTBEAT_S == 15
    assert WorkerSettings.health_check_interval == settings.WORKER_HEALTHCHECK_S

    # Và chỗ *dùng* phải gọi đúng tên. Đọc mã nguồn vì hai giá trị bằng nhau ở
    # mặc định nên không phép so sánh runtime nào phân biệt được — cùng lối với
    # `tests/api/test_messages.py::test_tang_api_khong_import_gi_cua_provider`.
    source = (Path(worker_main.__file__)).read_text(encoding="utf-8")
    assert "health_check_interval = settings.WORKER_HEALTHCHECK_S" in source
    assert "health_check_interval = settings.WORKER_HEARTBEAT_S" not in source

    # Tỉ lệ phải còn nghĩa: reaper đợi ít nhất hai nhịp trước khi kết luận chết.
    assert settings.REAPER_STALE_S >= 2 * settings.WORKER_HEARTBEAT_S


def test_poll_delay_from_settings_not_arq_default() -> None:
    """B-104 — nhịp poll của arq nằm chình ình trong TTFT của mọi model.

    T-1.12 đo chặng `202` → `start`: p95 0.486–0.505 s và `max` 0.494–0.510 s
    ở **cả bốn** model — trần bằng đúng `poll_delay` mặc định 0.5 s của arq,
    không phải đặc tính của model nào.

    Đây cũng đúng cái bẫy mà docstring module nói: `get_kwargs` lọc theo chữ ký
    của `Worker`, nên gõ `poll_delay_s` (tên thuộc tính *bên trong* Worker) thay
    vì `poll_delay` (tên tham số) sẽ bị **bỏ qua lặng lẽ** — worker vẫn chạy,
    chỉ là chạy ở 0.5 s, và phép đo TTFT sẽ không đổi một mili-giây nào.
    """
    worker: Worker = create_worker(WorkerSettings)
    assert worker.poll_delay_s == settings.ARQ_POLL_DELAY_S
    assert worker.poll_delay_s < 0.5, "không thấp hơn mặc định arq thì B-104 chưa được sửa"

    # Đọc mã nguồn vì nếu ai đó gõ nhầm tên thuộc tính thì phép so sánh ở trên
    # vẫn xanh khi `ARQ_POLL_DELAY_S` tình cờ bằng mặc định của arq.
    source = (Path(worker_main.__file__)).read_text(encoding="utf-8")
    assert "poll_delay = settings.ARQ_POLL_DELAY_S" in source


def test_lower_poll_delay_does_not_break_7_6_cron_schedule() -> None:
    """Ghim giả định của arq mà quyết định hạ `poll_delay` dựa vào.

    `REAPER_MOI_N_GIAY = 30` chỉ đúng nếu arq **kẹp** cửa sổ cron ở 0.5 s:
    `arq/worker.py` viết `cron_window_size = max(self.poll_delay_s, 0.5)`.
    Nếu một bản arq sau bỏ phép kẹp ấy đi thì cửa sổ co lại bằng
    `poll_delay` (0.1 s) và reaper có thể **lỡ hẳn** một tick mà không ai báo
    — đúng dạng hỏng im lặng của §7.6.

    Giá trị được đọc ra từ chính mã nguồn arq đang cài, không chép lại: test
    này phải đỏ khi nâng arq làm đổi hành vi, chứ không đỏ khi mình đổi số.
    """
    arq_source = Path(arq_worker.__file__).read_text(encoding="utf-8")
    assert "max(self.poll_delay_s, 0.5)" in arq_source, (
        "arq đã đổi cách tính cron_window_size — kiểm lại REAPER_MOI_N_GIAY "
        "trước khi giữ ARQ_POLL_DELAY_S dưới 0.5 s"
    )
    assert settings.ARQ_POLL_DELAY_S <= 0.5


def test_job_timeout_exceeds_model_layer_http_timeout() -> None:
    """Hai timeout lồng nhau: cái trong (HTTP) phải nổ trước cái ngoài (arq).

    Ngược lại thì arq huỷ job giữa lúc model đang sinh — tiền vẫn mất, mà
    worker mất luôn quyền ghi `status`/`usage`/`XADD done`.
    """
    assert settings.GENERATE_TIMEOUT_S > settings.LLM_REQUEST_TIMEOUT_S
