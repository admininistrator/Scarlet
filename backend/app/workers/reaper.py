"""Cron `reaper` — dọn lượt sinh mà worker chết giữa chừng (§7.6, tiêu chí S4).

KH tham chiếu: §7.6, §7.4, §17.2, §17.4, ADR-02, C8 · CLAUDE.md A1, A3 · S4.

Nếu container `worker` bị giết trong lúc đang sinh, không ai chạy nốt bước ⑥→⑧
của §7.2: message nằm lại ở `status='streaming'` **vĩnh viễn**, và client đang
mở SSE chờ mãi — §7.4 cấm FE suy ra "đã xong" từ việc stream im lặng, nên im
lặng với nó nghĩa là *đang chờ*. Job này là đường thoát duy nhất cho ca đó.

**HAI tập, không phải một (B-123).** Worker chết ở hai chỗ khác nhau để lại
hai hình dạng khác nhau, và một câu UPDATE chỉ thấy được một:

    ① mất nhịp tim — chết *sau* `mark_streaming`
       status='streaming' AND heartbeat_at < now() - REAPER_STALE_S  → WORKER_LOST
    ② mồ côi hàng đợi — chết *trước* `mark_streaming`
       status='queued'    AND created_at   < now() - REAPER_QUEUED_STALE_S → JOB_LOST

Tập ② vô hình với câu của tập ①: message `queued` có `heartbeat_at = NULL`
(`mark_streaming` mới là chỗ đặt nó), mà `NULL < now() - interval` cho ra
`NULL` chứ không `true`. Hai ngưỡng RIÊNG vì hai câu hỏi khác nhau — xem
docstring `Settings.REAPER_QUEUED_STALE_S`.

**Hai bước cho mỗi tập, đúng thứ tự này, không đảo:**

    ① UPDATE messages SET status='failed', error_code=<mã> ... RETURNING id
    ② với mỗi id trả về: XADD stream:{id} type=error data={"code":"<mã>"}

Postgres **trước**, Redis **sau** — cùng luật 2 của `generate.py`: client nhận
`error` rồi tải lại trang sẽ đọc `messages.status` từ Postgres, và đảo thứ tự
là tạo một khe trong đó FE đã hiện nút Retry còn lịch sử vẫn nói "đang sinh".

**Vì sao `RETURNING` chứ không `SELECT` rồi `UPDATE`.** Hai câu lệnh là hai
lượt quét và một khe ở giữa: một worker khác có thể hồi sinh nhịp tim đúng lúc
đó, và mình sẽ `XADD error` cho một lượt sinh vẫn đang chảy. Một câu `UPDATE …
RETURNING` thì danh sách trả về **chính là** tập dòng đã đổi, không thể lệch.

**Vì sao nhịp 30 s không phải một biến `Settings`.** Nó không phải một *giới
hạn* vận hành (A3 liệt "tên model, giá, giới hạn, URL provider, màu sắc") mà
là *độ phân giải* của phép quét: giới hạn thật là `REAPER_STALE_S`, đã có biến
riêng và là thứ quyết định "bao lâu thì coi như chết". Thêm nữa, cron của arq
nhận một **tập giây trong phút**, nên chỉ các ước của 60 mới ra nhịp đều — một
biến môi trường nhận `REAPER_MOI_N_GIAY=7` sẽ tạo ra một lịch quét lệch mà
không ai báo. Cùng loại với `CANCEL_CHECK_EVERY_N_CHUNKS` của `generate.py`.

**Cửa sổ phát hiện thật, tính được từ ba con số** (và đây là chỗ S4 của
KE-HOACH §2.3 nói "query DB sau 120 s" chứ không phải 90 s):

    sớm nhất = REAPER_STALE_S − WORKER_HEARTBEAT_S = 90 − 15 = 75 s
    muộn nhất = REAPER_STALE_S + 30 = 120 s

vì nhịp tim cuối cùng trước lúc chết cách lúc chết từ 0 tới
`WORKER_HEARTBEAT_S` giây, rồi còn phải đợi tới tick cron kế tiếp.

**Không đụng tới khoá `arq:in-progress:` của job đã chết (B-72, NQ-28).** Ba
lý do, lý do đầu là lý do chặn: reaper chỉ có `message_id`, còn khoá kia đặt
tên theo `job_id` mà arq sinh ngẫu nhiên và **không** lưu ở đâu trong
`messages` (B-92 mới là chỗ ghim `_job_id`). Hai lý do còn lại ở NQ-28.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.config.settings import settings
from app.db.repositories import MessageRepository
from app.db.session import session_scope
from app.streaming.events import ErrorCode, ErrorEvent
from app.streaming.producer import StreamProducer

logger = logging.getLogger(__name__)

#: Tên cron trên dây. arq mặc định lấy `__qualname__`; ghim lại vì tên này
#: hiện trong log worker và là thứ người vận hành grep khi hỏi "reaper có chạy
#: không" — đổi tên hàm Python mà tên job đổi theo là một `grep` chết lặng.
REAPER_JOB_NAME = "reaper"

#: §7.6 viết thẳng "Cron arq mỗi 30 s". arq nhận **tập giây trong phút**, nên
#: 30 s là `{0, 30}`. Xem docstring module cho lý do đây không phải biến
#: `Settings`.
REAPER_EVERY_N_SECONDS = 30
REAPER_SECONDS_IN_MINUTE = frozenset(range(0, 60, REAPER_EVERY_N_SECONDS))

#: Chữ đi kèm event `error`. Chỉ cho người đọc log — §7.4 nói FE phân nhánh
#: theo `code`, không theo câu này; và §20 cấm nó mang nội dung message.
REASON_BY_CODE = {
    ErrorCode.WORKER_LOST: "worker dung giua chung, khong con nhip tim",
    ErrorCode.JOB_LOST: "khong worker nao nhan job nay, message ket o hang doi",
}


async def reaper(ctx: dict[str, Any]) -> None:
    """Một lượt quét. Không ném ra ngoài: cron chết là reaper im lặng biến mất.

    `max_tries=1` của cron arq nghĩa là một lần ném là một tick mất hẳn; và vì
    tick sau vẫn thấy cùng những dòng ấy (chúng vẫn `streaming`), thử lại
    không mua thêm gì. Đổi lại, mọi ngả thoát đều để lại một dòng log.
    """
    try:
        lost_heartbeat, orphaned_queued = await _sweep_postgres()
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("reaper: khong chay duoc cau UPDATE cua §7.6")
        return

    if not lost_heartbeat and not orphaned_queued:
        # Đường chạy thường ngày. `debug` chứ không `info`: 2880 dòng/ngày ở
        # mức `info` sẽ dìm chết log của `generate` trong chính file log ấy.
        logger.debug(
            "reaper: 0 message qua han (nguong %ds streaming / %ds queued)",
            settings.REAPER_STALE_S,
            settings.REAPER_QUEUED_STALE_S,
        )
        return

    # `warning` chứ không `info`: mỗi dòng ở đây là một câu trả lời người dùng
    # đã mất. Đây cũng là dòng giải thích cho "job biến mất" của B-72 — hàng
    # đợi arq bỏ quên job trong ~910 s sau SIGKILL mà không log gì, nên nếu
    # không có dòng này thì người đọc log không có mốc nào để nối hai sự kiện.
    #
    # Hai nhánh log RIÊNG, không cộng vào một con số: chúng nói hai chuyện khác
    # nhau với người vận hành. `streaming` quá hạn nghĩa là worker chết giữa
    # lúc sinh; `queued` quá hạn nghĩa là **không ai nhận job** — ca thứ hai
    # chỉ về hàng đợi hoặc về việc worker không chạy, không về model.
    for ids, threshold, code, description in (
        (lost_heartbeat, settings.REAPER_STALE_S, ErrorCode.WORKER_LOST, "streaming"),
        (orphaned_queued, settings.REAPER_QUEUED_STALE_S, ErrorCode.JOB_LOST, "queued"),
    ):
        if not ids:
            continue
        for mid in ids:
            await _notify_client(ctx["redis"], mid, code)
        logger.warning(
            "reaper: %d message ket o %s qua %ds -> failed/%s: %s",
            len(ids),
            description,
            threshold,
            code.value,
            ", ".join(str(mid) for mid in ids),
        )


async def _sweep_postgres() -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Bước ①. MỘT transaction cho cả hai nhánh, mốc thời gian do Postgres cấp.

    Cùng một session nên cùng một `now()` (= `transaction_timestamp()`): hai
    nhánh của một lượt quét phải được đo bằng cùng cái đồng hồ, đúng lý lẽ đã
    ghi ở `reap_stale_streaming`.
    """
    async with session_scope() as session:
        repo = MessageRepository(session)
        lost_heartbeat = await repo.reap_stale_streaming(
            stale_after_s=settings.REAPER_STALE_S,
            error_code=ErrorCode.WORKER_LOST.value,
        )
        orphaned_queued = await repo.reap_stale_queued(
            stale_after_s=settings.REAPER_QUEUED_STALE_S,
            error_code=ErrorCode.JOB_LOST.value,
        )
        await session.commit()
        return list(lost_heartbeat), list(orphaned_queued)


async def _notify_client(redis: Any, mid: uuid.UUID, code: ErrorCode) -> None:
    """Bước ②. Một message hỏng KHÔNG được làm hỏng những message còn lại.

    `EXPIRE` đi kèm `XADD` vì đây là ca duy nhất mà không ai khác đặt được TTL
    cho stream: `generate` đặt nó ở `_close_ledger`, mà `_close_ledger` chính là thứ đã
    không chạy (worker bị giết). Bỏ qua thì khoá `stream:{id}` sống **mãi** và
    `maxmemory-policy volatile-lru` không đụng tới được khoá không có TTL —
    đúng C8, chỉ khác là ở đây chỗ quên nằm ở một tiến trình đã chết.

    Với nhánh `queued` (B-123) thì `stream:{id}` thường **chưa tồn tại** —
    `generate` chưa chạy tới `XADD start` bao giờ. `XADD` tự tạo khoá, nên
    client nào đang mở SSE vẫn nhận được `error` thay vì chờ mãi, và `EXPIRE`
    giữ cho khoá vừa tạo đó không sống vĩnh viễn.
    """
    producer = StreamProducer(redis, mid, ttl_s=settings.STREAM_TTL_S)
    try:
        await producer.emit(ErrorEvent(code=code, message=REASON_BY_CODE[code]))
        await producer.expire()
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("reaper: %s da danh failed nhung khong XADD duoc error", mid)
