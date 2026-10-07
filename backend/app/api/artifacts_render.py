"""Trang khung của origin phụ `artifacts.<domain>` (ADR-10, §14.3) — T-5.6.

Nginx chuyển **mọi** đường của origin phụ về đây (`location /` ⇒
`proxy_pass http://api:8000/artifacts-render/`, Phụ lục D). Trang không id,
không đọc DB, không đăng nhập: nội dung artifact tới sau bằng `postMessage` từ
trang cha đã xác thực (T-5.7) — ở đây không có gì để IDOR (B-182). Đường duy
nhất có nghĩa là `kind` (T-5.8): `/react`, `/mermaid` ⇒ trang có runtime của
kind ấy; đường khác ⇒ trang `html` không runtime.

**Vì sao router riêng ngoài `/api/v1`.** Origin chính chỉ chuyển `/api/` cho
`api`; `/artifacts-render/` ở đó rơi vào SPA — khung không tới được từ origin
chính, nên không thể vô tình chạy cùng gốc với cookie phiên. Nằm dưới
`/api/v1` thì `https://<domain>/api/v1/...` sẽ phục vụ khung ngay trên origin
chính, và các dependency xác thực của `app/api/v1/__init__.py` không áp cho nó.

CSP và `nosniff` do Nginx đặt (Phụ lục D), không phải ở đây: cùng một chỗ phủ
cả trang lỗi.

**Bắt tay `postMessage` (T-5.7, §14.3 đoạn cuối).** Script của khung gắn
listener rồi gửi `ready {watchdog}` cho `window.parent`; cha gửi `{type:
"render", kind, content}` **sau** `ready`; khung trả `rendered` hoặc `error
{message}`. Khung chỉ nhận message có `event.source === window.parent` **và**
`event.origin` == `PUBLIC_BASE_URL` — chèn vào trang lúc phục vụ (A3), không
literal. Thiếu kiểm `source` thì một tab khác cùng origin chính `window.open`
khung này rồi đẩy nội dung vào được (DoD T-5.7). Nội dung không bao giờ đi qua
URL: access log ghi URL (T-4.1 ⑥).

**Runtime + watchdog (T-5.8, §14.4, C31, C32).** `config/artifact_runtime.json`
đọc ở MỖI request (§19.1: sửa tệp, không restart): script CDN theo `kind` —
chỉ chèn của kind đang phục vụ (Babel 3.1 MB, Mermaid 3.6 MB) — và hai nhịp
watchdog, gửi cho cha trong `ready`. Cha `ping` mỗi nhịp, khung trả `alive`
(không `pong` — `check-identifiers` đỏ). Tệp hỏng / URL ngoài jsdelivr ⇒ 503 có
log cho MỌI kind: không có nhịp watchdog thì không khung nào được chạy.

Khung **dùng một lần**: phía cha đổi nội dung bằng iframe MỚI
(`ArtifactFrame.tsx`) — state và timer của script cũ chết cùng iframe cũ.
`html` viết bằng `document.open()`, thứ xoá mọi listener của `window` (HTML
spec) ⇒ listener `ping` gắn LẠI sau `document.close()` (B-370).
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path
from typing import Annotated, Self

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    PositiveInt,
    ValidationError,
    model_validator,
)

from app.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artifacts-render", include_in_schema=False)

RUNTIME_PATH = Path(__file__).resolve().parents[3] / "config" / "artifact_runtime.json"

#: Kind không có runtime: `document.write` nguyên văn (T-5.7).
DEFAULT_KIND = "html"

# Chỉ jsdelivr — origin DUY NHẤT `script-src` của origin phụ cho phép (Phụ lục
# D, `config/nginx/nginx.conf`); sửa một chỗ thì sửa cả hai. CSP cho CẢ
# jsdelivr nên đây không phải hàng rào (B-361): nó chặn tệp cấu hình trỏ ra
# chỗ CSP sẽ chặn (khung nửa vời) hoặc ghim lỏng. Phiên bản ĐỦ ba số
# (`@latest`, `@4`, `@^4.1.0` ⇒ trượt); mỗi đoạn đường không mở đầu bằng `.`
# (`/../` đưa URL ra khỏi gói đã ghim).
_PINNED_CDN_URL = re.compile(
    r"https://cdn\.jsdelivr\.net/npm/(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*"
    r"@\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?(?:/[A-Za-z0-9_-][A-Za-z0-9._-]*)+"
)
_KIND = re.compile(r"[a-z]+")


def _pinned_cdn_url(url: str) -> str:
    if not _PINNED_CDN_URL.fullmatch(url):
        raise ValueError(
            f"URL runtime phải là https://cdn.jsdelivr.net/npm/<gói>@<x.y.z>/…: {url!r}"
        )
    return url


def _kind(kind: str) -> str:
    if not _KIND.fullmatch(kind):
        raise ValueError(f"kind không hợp lệ: {kind!r}")
    return kind


class Watchdog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ping_interval_ms: PositiveInt
    timeout_ms: PositiveInt

    @model_validator(mode="after")
    def _timeout_after_ping(self) -> Self:
        if self.timeout_ms <= self.ping_interval_ms:
            raise ValueError("timeout_ms phải lớn hơn ping_interval_ms")
        return self


class ArtifactRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watchdog: Watchdog
    scripts: dict[
        Annotated[str, AfterValidator(_kind)], list[Annotated[str, AfterValidator(_pinned_cdn_url)]]
    ]


def load_runtime() -> ArtifactRuntime:
    """Đọc + kiểm `artifact_runtime.json` — không cache (§19.1)."""
    return ArtifactRuntime.model_validate(json.loads(RUNTIME_PATH.read_text(encoding="utf-8")))


# `__…__` thay lúc phục vụ. Tên các kiểu message ở MỘT chỗ phía khung
# (`MESSAGE`); phía cha là `ARTIFACT_MESSAGE` của `ArtifactFrame.tsx`.
_FRAME_HTML = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>artifact</title>
__RUNTIME_SCRIPTS__
</head>
<body>
<div id="root"></div>
<script>
(() => {
  const PARENT_ORIGIN = __PARENT_ORIGIN__;
  const KIND = __KIND__;
  const WATCHDOG = __WATCHDOG__;
  const MESSAGE = {
    ready: "ready", render: "render", rendered: "rendered", error: "error",
    ping: "ping", alive: "alive",
  };
  const parent = window.parent;
  const reply = (data) => parent.postMessage(data, PARENT_ORIGIN);
  const trusted = (event) => event.source === parent && event.origin === PARENT_ORIGIN;
  const describe = (e) => (e instanceof Error ? e.name + ": " + e.message : String(e));
  // Babel tu bien dich moi `text/babel` o DOMContentLoaded — tat: chi bien dich
  // khi `render` toi (co the TRUOC DOMContentLoaded), dung mot lan.
  if (window.Babel) window.Babel.disableScriptTags();

  // Loi doc duoc TRONG khung (C31: khong trang trang) + `error` ve cha.
  let failed = false;
  function fail(message) {
    failed = true;
    const box = document.createElement("pre");
    box.setAttribute("role", "alert");
    box.style.cssText = "margin:0;padding:12px;white-space:pre-wrap;font:13px/1.5 monospace";
    box.textContent = message;
    document.body.prepend(box);
    reply({ type: MESSAGE.error, message });
  }
  addEventListener("error", (event) => fail(event.message || describe(event.error)));
  addEventListener("unhandledrejection", (event) => fail(describe(event.reason)));

  function onPing(event) {
    if (!trusted(event) || !event.data || event.data.type !== MESSAGE.ping) return;
    reply({ type: MESSAGE.alive });
  }

  const RENDER = {
    html(content) {
      document.open();
      document.write(content);
      document.close();
      addEventListener("message", onPing); // document.open() da xoa no (B-370)
      reply({ type: MESSAGE.rendered });
    },
    react(content) {
      // `tsx` cung la `react` (KIND_BY_LANGUAGE): bo kieu TS + JSX, khong
      // preset `env` ⇒ `import` giu nguyen va nem dung loi cua C31.
      const { availablePresets } = window.Babel;
      const typescript = [availablePresets.typescript, { allExtensions: true, isTSX: true }];
      window.Babel.registerPreset("artifact", { presets: [typescript, availablePresets.react] });
      const script = document.createElement("script");
      script.type = "text/babel";
      script.setAttribute("data-presets", "artifact");
      script.textContent = content;
      document.body.append(script);
      window.Babel.transformScriptTags();
      if (failed) return;
      if (typeof App !== "function") {
        throw new Error("không thấy component App — artifact React là function App() "
          + "dùng React toàn cục, không import / export");
      }
      const root = ReactDOM.createRoot(document.getElementById("root"));
      ReactDOM.flushSync(() => root.render(React.createElement(App)));
      if (!failed) reply({ type: MESSAGE.rendered });
    },
    async mermaid(content) {
      window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
      try {
        const { svg } = await window.mermaid.render("artifact-mermaid", content);
        document.getElementById("root").innerHTML = svg;
      } catch (e) {
        document.getElementById("dartifact-mermaid")?.remove(); // hop tam Mermaid bo lai khi loi
        throw e;
      }
      reply({ type: MESSAGE.rendered });
    },
  };

  function onRender(event) {
    if (!trusted(event)) return;
    const data = event.data;
    if (!data || data.type !== MESSAGE.render) return;
    removeEventListener("message", onRender);
    if (data.kind !== KIND || !Object.hasOwn(RENDER, KIND) || typeof data.content !== "string") {
      fail("khung " + KIND + " không chạy được kind " + String(data.kind));
      return;
    }
    Promise.resolve()
      .then(() => RENDER[KIND](data.content))
      .catch((e) => fail(describe(e)));
  }
  addEventListener("message", onPing);
  addEventListener("message", onRender);
  reply({ type: MESSAGE.ready, watchdog: WATCHDOG });
})();
</script>
</body>
</html>
"""


def _script_value(value: object) -> str:
    # `<` thoát thành `<`: giá trị nằm trong <script>, không được đóng thẻ.
    return json.dumps(value).replace("<", "\\u003c")


@router.get("/{rest:path}", response_class=HTMLResponse)
def artifact_frame(rest: str) -> HTMLResponse:
    try:
        runtime = load_runtime()
    except (OSError, ValueError, ValidationError) as exc:
        logger.error("artifact_runtime.json bị từ chối, không phục vụ khung: %s", exc)
        return HTMLResponse("artifact runtime unavailable", status_code=503)
    kind = rest if rest in runtime.scripts else DEFAULT_KIND
    # `crossorigin`: lỗi ném từ script khác origin (React gọi handler) bị che
    # thành "Script error." (đo) — jsdelivr trả `Access-Control-Allow-Origin: *`.
    scripts = "\n".join(
        f'<script src="{html.escape(url)}" crossorigin="anonymous"></script>'
        for url in runtime.scripts.get(kind, [])
    )
    page = (
        _FRAME_HTML.replace("__RUNTIME_SCRIPTS__", scripts)
        .replace("__PARENT_ORIGIN__", _script_value(settings.PUBLIC_BASE_URL))
        .replace("__KIND__", _script_value(kind))
        .replace("__WATCHDOG__", _script_value(runtime.watchdog.model_dump()))
    )
    return HTMLResponse(page)
