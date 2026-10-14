#!/usr/bin/env python3
"""Kiểm một tệp export JSON của Scarlet nạp lại được (T-8.6, §24.3 dòng P8).

    python3 scripts/check_export.py t.json [--path p.json]

`p.json` = thân `GET /api/v1/conversations/{id}` — đường đi dựng lại từ tệp phải
trùng đường đi API. Chỉ stdlib. Exit 0 + số đếm khi đạt; exit 1 + lý do khi hỏng.
Cùng hợp đồng mà import (B-13) sẽ đọc.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

FORMAT = "scarlet-conversation"
VERSION = 1


def check(export: dict[str, Any], api_path: list[str] | None) -> str:
    """Trả dòng tóm tắt; ném `ValueError` / `TypeError` (lý do) khi tệp hỏng."""
    if export.get("format") != FORMAT:
        raise ValueError(f"format = {export.get('format')!r}, can {FORMAT!r}")
    if export.get("version") != VERSION:
        raise ValueError(f"version = {export.get('version')!r}, can {VERSION}")
    messages = export.get("messages")
    if not isinstance(messages, list):
        raise TypeError("thieu mang messages")

    parents: dict[str, str | None] = {}
    for i, message in enumerate(messages):
        mid, parent = message.get("id"), message.get("parent_id")
        if mid in parents:
            raise ValueError(f"messages[{i}]: id {mid} trung")
        # Cha phải xuất hiện TRƯỚC con — nạp lại tuần tự không cần lượt hai.
        if parent is not None and parent not in parents:
            raise ValueError(f"messages[{i}] ({mid}): parent_id {parent} chua xuat hien truoc")
        parents[mid] = parent

    leaf = export.get("conversation", {}).get("active_leaf_id")
    path: list[str] = []
    if leaf is not None:
        if leaf not in parents:
            raise ValueError(f"active_leaf_id {leaf} khong co trong tep")
        node: str | None = leaf
        while node is not None:
            path.append(node)
            node = parents[node]
        path.reverse()

    if api_path is not None and path != api_path:
        raise ValueError(f"duong di dung lai ({len(path)}) khac duong di API ({len(api_path)})")

    with_children = {p for p in parents.values() if p is not None}
    roots = sum(p is None for p in parents.values())
    leaves = sum(m not in with_children for m in parents)
    return (
        f"OK scope={export.get('scope')} messages={len(messages)} roots={roots} "
        f"leaves={leaves} path={len(path)}" + (" path_khop_api" if api_path is not None else "")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export")
    parser.add_argument("--path", help="JSON cua GET /conversations/{id}")
    args = parser.parse_args()
    try:
        with open(args.export, encoding="utf-8") as fh:
            export = json.load(fh)
        api_path = None
        if args.path:
            with open(args.path, encoding="utf-8") as fh:
                api_path = [m["id"] for m in json.load(fh)["path"]]
        print(check(export, api_path))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"HONG: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
