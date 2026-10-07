"""T-5.8 — trang khung theo `kind`, `config/artifact_runtime.json` đọc ở mỗi request.

Router riêng, không DB, không đăng nhập (`app/api/artifacts_render.py`) ⇒ dựng
một app FastAPI chỉ có router ấy. `RUNTIME_PATH` vá sang tệp tạm: sửa tệp giữa
hai request trong CÙNG tiến trình là đúng hình "sửa file, không restart" của
§19.1. Hành vi trong trình duyệt (Babel, Mermaid, watchdog) đo trên Chromium —
`make test-artifact-origin` và DoD Chrome của T-5.8.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import artifacts_render

REACT = [
    "https://cdn.jsdelivr.net/npm/react@18.3.1/umd/react.production.min.js",
    "https://cdn.jsdelivr.net/npm/@babel/standalone@7.29.9/babel.min.js",
]
MERMAID = ["https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"]


def _runtime(**over: Any) -> dict[str, Any]:
    return {
        "watchdog": {"ping_interval_ms": 1500, "timeout_ms": 4500},
        "scripts": {"react": list(REACT), "mermaid": list(MERMAID)},
    } | over


@pytest.fixture
def runtime_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "artifact_runtime.json"
    path.write_text(json.dumps(_runtime()), encoding="utf-8")
    monkeypatch.setattr(artifacts_render, "RUNTIME_PATH", path)
    return path


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(artifacts_render.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://artifacts.localhost"
    ) as http:
        yield http


def _script_srcs(page: str) -> list[str]:
    return re.findall(r'<script src="([^"]*)"', page)


def test_repo_runtime_file_is_valid() -> None:
    """Tệp thật của repo qua được đúng bộ kiểm mà request dùng."""
    runtime = artifacts_render.load_runtime()
    assert {"react", "mermaid"} <= runtime.scripts.keys()
    assert runtime.watchdog.timeout_ms > runtime.watchdog.ping_interval_ms


async def test_react_page_has_exactly_the_file_scripts(
    runtime_file: Path, client: AsyncClient
) -> None:
    page = await client.get("/artifacts-render/react")
    assert page.status_code == 200
    assert _script_srcs(page.text) == REACT
    assert page.text.count('crossorigin="anonymous"') == len(REACT)
    assert 'const KIND = "react";' in page.text
    assert 'const WATCHDOG = {"ping_interval_ms": 1500, "timeout_ms": 4500};' in page.text
    assert _script_srcs((await client.get("/artifacts-render/mermaid")).text) == MERMAID


@pytest.mark.parametrize(
    "path", ["/artifacts-render/html", "/artifacts-render/", "/artifacts-render/react/x"]
)
async def test_html_and_other_paths_have_no_runtime_script(
    runtime_file: Path, client: AsyncClient, path: str
) -> None:
    page = await client.get(path)
    assert page.status_code == 200
    assert _script_srcs(page.text) == []
    assert 'const KIND = "html";' in page.text
    # Watchdog có ở MỌI kind — html cũng chạy được `while (true)`.
    assert '"timeout_ms": 4500' in page.text


async def test_file_edit_is_seen_by_the_next_request(
    runtime_file: Path, client: AsyncClient
) -> None:
    assert _script_srcs((await client.get("/artifacts-render/react")).text) == REACT
    added = "https://cdn.jsdelivr.net/npm/lodash@4.17.21/lodash.min.js"
    runtime_file.write_text(
        json.dumps(
            _runtime(
                scripts={"react": [*REACT, added]},
                watchdog={"ping_interval_ms": 900, "timeout_ms": 2700},
            )
        ),
        encoding="utf-8",
    )
    page = (await client.get("/artifacts-render/react")).text
    assert _script_srcs(page) == [*REACT, added]
    assert '"ping_interval_ms": 900' in page
    # `mermaid` vừa bị gỡ khỏi tệp ⇒ đường ấy về trang html không runtime.
    assert _script_srcs((await client.get("/artifacts-render/mermaid")).text) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.tailwindcss.com/3.4.0",  # ngoài CSP (Cạm bẫy ②)
        "https://unpkg.com/react@18.3.1/umd/react.production.min.js",
        "http://cdn.jsdelivr.net/npm/react@18.3.1/umd/react.production.min.js",
        "https://cdn.jsdelivr.net.evil.test/npm/react@18.3.1/umd/react.production.min.js",
        "https://cdn.jsdelivr.net/npm/react@latest/umd/react.production.min.js",
        "https://cdn.jsdelivr.net/npm/react@18/umd/react.production.min.js",
        "https://cdn.jsdelivr.net/npm/react@^18.3.1/umd/react.production.min.js",
        "https://cdn.jsdelivr.net/npm/react/umd/react.production.min.js",
        "https://cdn.jsdelivr.net/npm/react@18.3.1/../evil/x.js",
        "https://cdn.jsdelivr.net/npm/react@18.3.1/umd/react.js?v=1",
        'https://cdn.jsdelivr.net/npm/react@18.3.1/a"><script>alert(1)</script>.js',
    ],
)
async def test_unpinned_or_foreign_url_refuses_every_kind(
    runtime_file: Path, client: AsyncClient, caplog: pytest.LogCaptureFixture, url: str
) -> None:
    runtime_file.write_text(
        json.dumps(_runtime(scripts={"react": [*REACT, url]})), encoding="utf-8"
    )
    with caplog.at_level(logging.ERROR, logger=artifacts_render.__name__):
        for kind in ("react", "html"):
            page = await client.get(f"/artifacts-render/{kind}")
            assert page.status_code == 503
            assert "<script" not in page.text
    assert "artifact_runtime.json" in caplog.text
    assert url in caplog.text


@pytest.mark.parametrize(
    "content",
    [
        "{ hỏng",
        json.dumps({"scripts": {"react": REACT}}),  # thiếu watchdog
        json.dumps(_runtime(watchdog={"ping_interval_ms": 2000, "timeout_ms": 2000})),
        json.dumps(_runtime(watchdog={"ping_interval_ms": 0, "timeout_ms": 6000})),
        json.dumps(_runtime(extra=1)),
        json.dumps(_runtime(scripts={"React!": REACT})),
    ],
    ids=["bad-json", "no-watchdog", "timeout-eq-ping", "ping-zero", "extra-key", "bad-kind"],
)
async def test_broken_file_refuses_with_log(
    runtime_file: Path, client: AsyncClient, caplog: pytest.LogCaptureFixture, content: str
) -> None:
    runtime_file.write_text(content, encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger=artifacts_render.__name__):
        assert (await client.get("/artifacts-render/react")).status_code == 503
    assert "artifact_runtime.json bị từ chối" in caplog.text


async def test_missing_file_refuses(runtime_file: Path, client: AsyncClient) -> None:
    runtime_file.unlink()
    assert (await client.get("/artifacts-render/html")).status_code == 503
