#!/usr/bin/env python3
"""Ghi lại chunk THẬT của từng model qua LiteLLM thành fixture cho `tests/llm/`.

KH tham chiếu: §9.1, §9.2, §9.8 · DoD T-1.3 ("fixture chunk thật đã ghi lại").

Vì sao không viết fixture bằng tay: mỗi provider lệch chuẩn OpenAI một kiểu
khác nhau, và đúng những chỗ lệch đó mới là thứ `parser.py` phải chịu được —
`reasoning_content` của `deepseek-flash` (B-33), `caller` lạ trong `tool_calls`
của `claude-haiku`, tool call gói trọn một chunk của `nr-gemini-flash`. Fixture
tự nghĩ ra sẽ chỉ chứng minh parser hiểu được trí tưởng tượng của người viết.

Dùng `httpx` gọi thẳng chứ **không** dùng SDK `openai`: fixture phải là đúng
nội dung dòng `data:` mà provider gửi, chưa qua chuẩn hoá nào. Test tự lo phần
chứng minh SDK không làm mất gì (xem `test_parser.py`).

Chạy (từ gốc repo, LiteLLM đã `up`):

    source scripts/llm_env.sh
    backend/.venv/bin/python scripts/record_llm_fixtures.py

Danh sách model lấy từ `config/model_catalog.json` — thêm model mới vào catalog
là đủ, không sửa file này (S7, S15).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "config" / "model_catalog.json"
DEFAULT_OUT_DIR = REPO_ROOT / "backend" / "tests" / "llm" / "fixtures"

#: Câu hỏi tiếng Việt CÓ DẤU, và đủ dài để provider phải chia thành nhiều
#: chunk — đó là điều kiện để fixture kiểm được C9.
TEXT_PROMPT = (
    "Hãy viết một đoạn ngắn khoảng bốn câu bằng tiếng Việt có dấu, "
    "giới thiệu về phở Hà Nội. Không dùng danh sách gạch đầu dòng."
)

TOOLS_PROMPT = "Thời tiết ở Hà Nội hôm nay thế nào? Hãy dùng công cụ để tra."

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Lấy thời tiết hiện tại của một thành phố",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Tên thành phố"},
                    "unit": {"type": "string", "enum": ["c", "f"]},
                },
                "required": ["city"],
            },
        },
    }
]

#: `deepseek-flash` tiêu `max_tokens` cho reasoning TRƯỚC khi sinh content
#: (B-33): để 60 thì content rỗng mà `finish_reason` vẫn là `stop`. Đặt rộng
#: tay để fixture có cả khối reasoning lẫn khối content.
MAX_TOKENS = 600


def load_models() -> list[dict[str, Any]]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return [m for m in catalog["models"] if m.get("enabled", True)]


def record_case(
    client: httpx.Client,
    *,
    base_url: str,
    api_key: str,
    model_id: str,
    with_tools: bool,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "model": model_id,
        "messages": [{"role": "user", "content": TOOLS_PROMPT if with_tools else TEXT_PROMPT}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if with_tools:
        body["tools"] = TOOLS_SCHEMA
        body["tool_choice"] = "auto"

    chunks: list[dict[str, Any]] = []
    with client.stream(
        "POST",
        f"{base_url}/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as response:
        if response.status_code != 200:
            detail = response.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"{model_id}: HTTP {response.status_code} — {detail}")
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if payload == "[DONE]":
                break
            chunks.append(json.loads(payload))
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LITELLM_BASE_URL", ""),
        help="gốc API của LiteLLM, đã gồm /v1 (C43)",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help="chỉ ghi model này (lặp lại được); mặc định: mọi model enabled trong catalog",
    )
    args = parser.parse_args()

    api_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not args.base_url or not api_key:
        print(
            "thiếu --base-url hoặc LITELLM_MASTER_KEY — xem docstring đầu file",
            file=sys.stderr,
        )
        return 2

    models = load_models()
    if args.model:
        wanted = set(args.model)
        models = [m for m in models if m["id"] in wanted]
        if not models:
            print(f"không model nào khớp {sorted(wanted)}", file=sys.stderr)
            return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []

    with httpx.Client(timeout=300.0) as client:
        for model in models:
            cases = [("text", False)]
            if "tools" in model.get("capabilities", []):
                cases.append(("tools", True))
            for case_name, with_tools in cases:
                chunks = record_case(
                    client,
                    base_url=args.base_url.rstrip("/"),
                    api_key=api_key,
                    model_id=model["id"],
                    with_tools=with_tools,
                )
                path = args.out_dir / f"{model['id']}.{case_name}.jsonl"
                with path.open("w", encoding="utf-8", newline="\n") as fh:
                    for chunk in chunks:
                        fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                entries.append(
                    {
                        "file": path.name,
                        "model": model["id"],
                        "provider": model["provider"],
                        "case": case_name,
                        "prompt": TOOLS_PROMPT if with_tools else TEXT_PROMPT,
                        "chunks": len(chunks),
                    }
                )
                print(f"{path.name}: {len(chunks)} chunk")

    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    manifest_path = args.out_dir / "manifest.json"
    if args.model and manifest_path.exists():
        # B-248: ghi MỘT model thì GỘP vào manifest cũ, không thay cả file —
        # bản trước xoá sạch mục của mọi model khác (7 mục) mà không báo gì.
        # `recorded_at` ở đầu file là của lần ghi toàn bộ; mục ghi lẻ mang
        # mốc riêng để không ai đọc nhầm fixture cũ thành fixture mới.
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        fresh = {e["file"] for e in entries}
        kept = [e for e in manifest["entries"] if e["file"] not in fresh]
        for entry in entries:
            entry["recorded_at"] = now
        manifest["entries"] = sorted(kept + entries, key=lambda e: e["file"])
    else:
        manifest = {
            "recorded_at": now,
            "via": "LiteLLM (ADR-03) — khoá KHÔNG ghi vào đây",
            "max_tokens": MAX_TOKENS,
            "temperature": 0.0,
            "stream_options": {"include_usage": True},
            "entries": sorted(entries, key=lambda e: e["file"]),
        }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{manifest_path.name}: ghi {len(entries)} mục, tổng {len(manifest['entries'])} mục")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
