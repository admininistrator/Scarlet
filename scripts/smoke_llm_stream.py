#!/usr/bin/env python3
"""Stream một câu tiếng Việt CÓ DẤU qua đường chạy thật, kiểm C9.

KH tham chiếu: C9, §9.1, ADR-03 · DoD T-1.3 dòng 2.

Khác `tests/llm/test_parser.py` ở chỗ: test chạy trên fixture đã ghi, script
này gọi model **thật** qua `SystemAdapter` → LiteLLM → provider. Nó là phép
kiểm duy nhất đi hết cả ba mảnh của T-1.3 cùng lúc, và là chỗ duy nhất bắt
được lỗi nằm giữa SDK `openai` và `parser.py`.

Kiểm ba điều, mỗi điều một dòng OK/FAIL:

1. Nối mọi `delta` lại **không** chứa ký tự thay thế `U+FFFD` (C9), và có dấu
   tiếng Việt thật — không có dấu thì phép kiểm vô nghĩa.
2. Chunk cuối là `done` và mang `usage` với `prompt_tokens`/`completion_tokens`
   đều > 0 (C40 — thiếu là quota không bao giờ trừ).
3. Model khai `reasoning` trong catalog thì phải thật sự có chunk `reasoning`
   (B-33), model không khai thì phải không có.

Chạy (từ gốc repo, LiteLLM đã `up`):

    source scripts/llm_env.sh
    backend/.venv/bin/python scripts/smoke_llm_stream.py --all

Không có `--all`/`--model` thì chỉ chạy model `default` của catalog.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config.catalog import ModelEntry, get_catalog  # noqa: E402
from app.llm.adapters.system import SystemAdapter  # noqa: E402
from app.llm.client import Chunk  # noqa: E402

PROMPT = (
    "Hãy viết đúng ba câu tiếng Việt có dấu về mùa thu Hà Nội. "
    "Không dùng danh sách gạch đầu dòng."
)

REPLACEMENT_CHAR = "�"


def co_dau_tieng_viet(text: str) -> bool:
    """Có ít nhất một chữ cái Latin mang dấu phụ — tức là tiếng Việt có dấu."""
    return any(
        "LATIN" in unicodedata.name(ch, "") and len(unicodedata.decomposition(ch)) > 0
        for ch in text
    )


async def chay_mot_model(adapter: SystemAdapter, model: ModelEntry, max_tokens: int) -> bool:
    chunks: list[Chunk] = []
    stream = await adapter.stream(
        model=model.id,
        messages=[{"role": "user", "content": PROMPT}],
        tools=None,
        max_tokens=min(model.max_output, max_tokens),
        temperature=0.0,
        extra={},
    )
    async for chunk in stream:
        chunks.append(chunk)

    text = "".join(c.text or "" for c in chunks if c.kind == "delta")
    reasoning = "".join(c.text or "" for c in chunks if c.kind == "reasoning")
    done = chunks[-1] if chunks else None
    khai_reasoning = "reasoning" in model.capabilities

    ket_qua: list[tuple[str, bool, str]] = [
        (
            "C9: không có U+FFFD và có dấu tiếng Việt",
            bool(text) and REPLACEMENT_CHAR not in text and co_dau_tieng_viet(text),
            f"{len(text)} ký tự",
        ),
        (
            "C40: chunk cuối là done và mang usage > 0",
            done is not None
            and done.kind == "done"
            and done.usage is not None
            and done.usage.prompt_tokens > 0
            and done.usage.completion_tokens > 0,
            "" if done is None or done.usage is None else str(done.usage),
        ),
        (
            f"B-33: capabilities khai reasoning={khai_reasoning}",
            bool(reasoning) == khai_reasoning,
            f"{len(reasoning)} ký tự reasoning",
        ),
    ]

    print(f"\n=== {model.id} ({model.provider}) — {len(chunks)} chunk ===")
    for ten, dat, chi_tiet in ket_qua:
        print(f"  [{'OK  ' if dat else 'FAIL'}] {ten} — {chi_tiet}")
    print(f"  finish_reason={done.finish_reason if done else None}")
    print(f"  --- chữ model trả về ---\n  {text.strip()[:400]}")

    return all(dat for _, dat, _ in ket_qua)


async def main_async(model_ids: list[str], max_tokens: int) -> int:
    catalog = get_catalog()
    chon = [m for m in catalog.models if m.id in model_ids]
    adapter = SystemAdapter.from_settings()
    try:
        ket_qua = [await chay_mot_model(adapter, m, max_tokens) for m in chon]
    finally:
        await adapter.close()
    print(f"\n{sum(ket_qua)}/{len(ket_qua)} model đạt cả ba phép kiểm")
    return 0 if all(ket_qua) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", default=None)
    parser.add_argument("--all", action="store_true", help="mọi model enabled trong catalog")
    parser.add_argument("--max-tokens", type=int, default=600)
    args = parser.parse_args()

    catalog = get_catalog()
    bat = [m for m in catalog.models if m.enabled]
    if args.all:
        chon = [m.id for m in bat]
    elif args.model:
        chon = args.model
        khong_co = set(chon) - {m.id for m in bat}
        if khong_co:
            print(f"model không có trong catalog hoặc đang tắt: {sorted(khong_co)}", file=sys.stderr)
            return 2
    else:
        chon = [m.id for m in bat if m.default]

    return asyncio.run(main_async(chon, args.max_tokens))


if __name__ == "__main__":
    raise SystemExit(main())
