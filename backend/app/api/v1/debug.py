"""`GET /api/v1/_debug/sse` — máy phát SSE để kiểm C1 và C2 (§18.6, §22.3).

Endpoint này **không** gọi model, **không** chạm Redis, **không** đụng DB. Nó
tồn tại để trả lời đúng một câu hỏi: *đường ống ``curl → Nginx → uvicorn`` có
đẩy từng mẩu ra ngay lúc sinh không, hay có ai đó đang gom lại thành một cục?*

- **C1** — nếu thiếu ``proxy_buffering off`` trong ``config/nginx/nginx.conf``,
  50 dòng dưới đây sẽ ra cùng lúc sau 10 giây thay vì rải đều 200 ms một dòng.
  Triệu chứng ở Phase 1 sẽ bị đọc nhầm thành "model chậm".
- **C2** — ``?gap_s=75`` bắt endpoint **im lặng** 75 giây trước dòng đầu tiên.
  Phải là im lặng, không phải "chạy lâu": ``proxy_read_timeout`` đo khoảng cách
  giữa hai lần đọc từ upstream, nên một stream 90 giây phát đều 200 ms/dòng đi
  qua ngưỡng 60 giây mà không hề chạm vào nó — đo kiểu đó luôn xanh và không
  chứng minh được gì. Đây cũng đúng hình dạng của tình huống thật ở Phase 1:
  model nghĩ lâu trước token đầu (TTFT), lúc đó backend im lặng thật sự.

Router này **chỉ được gắn vào app khi ``DEBUG=true``** (§18.6) — xem
``app/api/v1/__init__.py``. Với ``DEBUG=false`` đường dẫn không hề tồn tại,
FastAPI trả 404, và không có nhánh ``if`` nào trong handler để quên.

Định dạng event bám đúng §7.4 / Phụ lục F (``id`` + ``event`` + ``data`` là
JSON) để FE dùng chung một parser cho cả stream thật lẫn stream giả này.
Payload luôn đi qua ``json.dumps`` — C10.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/_debug", tags=["debug"])

#: Khoảng cách giữa hai dòng. §18.6 chốt "1 dòng mỗi 200 ms" — con số này là
#: *hợp đồng của phép đo*, không phải hạn mức vận hành, nên nó sống ở đây chứ
#: không phải trong ``Settings`` (§19.2 L4: số ma phải có tên).
TICK_INTERVAL_S = 0.2

#: Thời lượng mặc định. §18.6 chốt 10 giây.
DEFAULT_DURATION_S = 10

#: Trần của ``?seconds=`` và ``?gap_s=``. Bằng đúng ``proxy_read_timeout``
#: trong nginx.conf: xin dài hơn thế thì Nginx cắt, và kết quả đo sẽ nói dối.
MAX_DURATION_S = 3600

#: ``X-Accel-Buffering: no`` là lớp thứ hai của C1: kể cả khi ai đó lỡ tay xoá
#: ``proxy_buffering off`` khỏi nginx.conf, header này vẫn bảo Nginx đừng gom.
#: Hai lớp, vì mất streaming là loại lỗi im lặng.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


async def _phat_tick(duration_s: int, gap_s: int) -> AsyncIterator[str]:
    """Sinh ``duration_s / TICK_INTERVAL_S`` event ``delta`` rồi một event ``done``.

    Mỗi payload mang mốc thời gian đã trôi tính bằng ms, đo ngay lúc sinh. Nhờ
    vậy người đọc output của ``curl -N`` phân biệt được hai trường hợp mà mắt
    thường dễ nhầm: server sinh chậm (mốc cách nhau ~200 ms và chữ ra đều) và
    proxy gom lại (mốc cũng cách nhau ~200 ms nhưng chữ ra cùng một lúc).
    """
    loop = asyncio.get_running_loop()
    bat_dau = loop.time()
    so_tick = max(1, round(duration_s / TICK_INTERVAL_S))

    # Im lặng trước dòng đầu — đây là phần duy nhất chạm được vào C2. Không gửi
    # byte nào, kể cả comment SSE `: ping`: gửi là mất luôn phép đo.
    if gap_s:
        await asyncio.sleep(gap_s)

    for seq in range(so_tick):
        troi_ms = int((loop.time() - bat_dau) * 1000)
        payload = json.dumps({"t": f"tick {seq} +{troi_ms}ms"}, ensure_ascii=False)
        yield f"id: {seq}\nevent: delta\ndata: {payload}\n\n"
        await asyncio.sleep(TICK_INTERVAL_S)

    ket = json.dumps(
        {
            "finish_reason": "stop",
            "ticks": so_tick,
            "seconds": duration_s,
            "gap_s": gap_s,
            "elapsed_ms": int((loop.time() - bat_dau) * 1000),
        },
        ensure_ascii=False,
    )
    yield f"id: {so_tick}\nevent: done\ndata: {ket}\n\n"


@router.get("/sse")
async def debug_sse(
    seconds: int = Query(default=DEFAULT_DURATION_S, ge=1, le=MAX_DURATION_S),
    gap_s: int = Query(default=0, ge=0, le=MAX_DURATION_S),
) -> StreamingResponse:
    """Im lặng ``gap_s`` giây, rồi phát một dòng mỗi 200 ms trong ``seconds`` giây.

    - ``?seconds=10`` (mặc định) — phép đo C1: chữ ra từng dòng hay một cục.
    - ``?gap_s=75`` — phép đo C2: kết nối sống qua khoảng im lặng 75 giây.
    """
    return StreamingResponse(
        _phat_tick(seconds, gap_s),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
