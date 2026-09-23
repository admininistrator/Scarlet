#!/usr/bin/env python3
"""T-S.1 / KE-HOACH §24.2b·S2 — canh định danh tiếng Việt không dấu.

`CLAUDE.md` cấm đặt tên biến/hàm/lớp/prop/file dạng tiếng Việt không dấu
(NQ-109). Script này quét `backend/`, `frontend/src/`, `scripts/` và in mỗi
phát hiện một dòng `file:dòng: tên`; mã thoát 1 nếu có ít nhất một phát hiện.

Cách nhận ra một định danh "tiếng Việt":

1. Tách định danh thành từ theo camelCase / snake_case (`dangTai` →
   `dang`, `tai`; `_set_session_cookie` → `passed`, `cookie`, `phien`).
2. Một từ là âm tiết tiếng Việt nếu nó ghép được từ một phụ âm đầu trong
   `_ONSETS` và một vần trong `_RHYMES` (đã bỏ dấu), dài ít nhất 3 chữ, và
   KHÔNG nằm trong `_ENGLISH` — những chữ vừa là âm tiết Việt vừa là từ tiếng
   Anh/thuật ngữ (`chat`, `long`, `then`, `get`…). Từ 2 chữ chỉ tính khi nằm
   trong `_SHORT` (`ly`, `cu`, `out`, `start`…): `to`, `do`, `so`, `no`, `id`
   trùng tiếng Anh quá nhiều để phân xử.
3. Định danh bị báo nếu có ít nhất một từ như thế và tên đầy đủ không nằm trong
   `_ALLOWED` (mỗi dòng ghi lý do).

Python được đọc bằng `ast` và chỉ xét chỗ ĐỊNH NGHĨA (def, class, tham số,
biến được gán, thuộc tính được gán, `import … as`) — chỗ dùng đã được bắt ở
chỗ định nghĩa. TS/TSX/JS được đọc bằng một bộ tách token bỏ qua chuỗi,
template literal (trừ phần `${…}`), comment, regex và chữ trong JSX, rồi xét
MỌI định danh. Khoá `vi.json` là đối số chuỗi của `t("…")` nên tự bị bỏ qua.
Tên file (phần trước dấu chấm đầu tiên) cũng được xét, báo ở dòng 1.

Dùng: `python scripts/check_identifiers.py [--words]`. `--words` in thêm bảng
tần suất các từ Việt đã khớp — để rà `_ENGLISH` khi có báo động giả.
"""

from __future__ import annotations

import ast
import bisect
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCOPES = ("backend/", "frontend/src/", "scripts/")
PY_SUFFIXES = {".py"}
TS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs"}

# ── Âm tiết tiếng Việt, đã bỏ dấu ──────────────────────────────────────────
_ONSETS = (
    "", "b", "c", "ch", "d", "g", "gh", "gi", "h", "k", "kh", "l", "m", "n",
    "ng", "ngh", "nh", "p", "ph", "qu", "r", "s", "t", "th", "tr", "v", "x",
)
_RHYMES = (
    "a", "ac", "ach", "ai", "am", "an", "ang", "anh", "ao", "ap", "at", "au", "ay",
    "e", "ec", "ech", "em", "en", "eng", "enh", "eo", "ep", "et", "eu",
    "i", "ia", "ich", "iec", "iem", "ien", "ieng", "iep", "iet", "ieu", "im", "in",
    "inh", "ip", "it", "iu",
    "o", "oa", "oac", "oach", "oai", "oan", "oang", "oanh", "oat", "oay", "oc",
    "oe", "oen", "oet", "oi", "om", "on", "ong", "op", "ot",
    "u", "ua", "uan", "uang", "uat", "uay", "uc", "ue", "ui", "um", "un", "ung",
    "uoc", "uoi", "uom", "uon", "uong", "uop", "uot", "uou", "up", "ut", "uu",
    "uy", "uya", "uyen", "uyet", "uynh", "uyt",
    "y", "yen", "yet", "yeu",
)

# Chữ vừa ghép được thành âm tiết Việt vừa là từ tiếng Anh mà code dùng thật
# (`get`, `setBan`, `toBeGreaterThan`, `trimStart`, `DOMException`,
# `STATUSES_CAN_LOGIN`, `CONTEXT_WINDOW_CAP`, `gap_s`, `cat = catalog…`,
# `LUA_TOKEN_BUCKET` — script Lua).
# Danh sách lập theo dữ liệu, không theo từ điển: những chữ như `ban`, `added`,
# `doc`, `mat`, `man` ở kho này gần như luôn là `bản`, `thêm`, `đọc`, `mật`,
# `màn` — cho chúng vào đây là để lọt `valid`, `DUONG_DAN`. `that` là ngoại
# lệ có chủ ý: tên test tiếng Anh dùng nó liên tục, và `thật` hầu như không
# đứng một mình (`_tao_user_that` vẫn bị bắt nhờ `tao`).
# Thêm vào khi có báo động giả.
_ENGLISH = frozenset(
    """
    the then than true try trim len sep dom non not
    get set put let run pop map min sum top tip pay sin
    can cap gap cat rep day dot bit hit hot cut net
    chat chip pin long lua via but trip that
    """.split()
)

# Âm tiết hai chữ đủ đặc trưng để tính (`lyDo`, `token_cu`, `ProfileOut`,
# `tu_cache`, `exists`). Không có `to`/`do`/`so`/`no`/`me`/`he`/`vi` (`vi.json`).
_SHORT = frozenset(
    """
    ba bi bo co cu da de di du ga gi ho ke la le lo ly ma mi mo ne nu ra ro se
    su ta tu va ve vo xe xo
    """.split()
)

_SYLLABLES = (
    frozenset(o + r for o in _ONSETS for r in _RHYMES if len(o + r) >= 3) - _ENGLISH
) | _SHORT

# ── Danh sách cho phép: `tên` hoặc `đường/dẫn::tên` → lý do ────────────────
# Chỉ những tên là HỢP ĐỒNG hoặc DỮ LIỆU ĐÃ LƯU (NQ-109, §24.2b·S2): đổi chúng
# là đổi API, đổi file kết quả, hoặc đổi giao diện dòng lệnh — không phải một
# lần đổi tên.
_ALLOWED: dict[str, str] = {
    "streams_dang_chay": "khoá JSON của `GET /admin/system` (NQ-70 ②) — tên trên dây, FE đọc đúng tên này",
    "backend/app/api/v1/admin.py::hanh_dong": (
        "placeholder của route `/users/{user_id}/{hanh_dong}` — là tên tham số path trong OpenAPI"
    ),
    "scripts/bench_ttft.py::luot": "trường của `Run` → khoá JSON trong `evals/results/*.json` (asdict); cờ `--luot`",
    "scripts/bench_ttft.py::hang_doi_context": "trường của `Run` → khoá JSON trong `evals/results/*.json`",
    "scripts/bench_ttft.py::tong": "trường của `Run` → khoá JSON trong `evals/results/*.json`",
    "scripts/bench_ttft.py::ly_do_hong": "trường của `Run` → khoá JSON trong `evals/results/*.json`",
    "scripts/bench_ttft.py::bo_qua": "dest của cờ `--bo-qua`",
    "scripts/bench_ttft.py::ghi_de": "dest của cờ `--ghi-de`",
    "scripts/audit.mjs::DUONG": "biến môi trường của `make audit DUONG=…` (Makefile)",
    "scripts/audit.mjs::cho_san_sang": "khoá của `config/audit.json`",
    "scripts/audit.mjs::so_lan_thu": "khoá của `config/audit.json`",
    "scripts/audit.mjs::nghi_giua_hai_lan_ms": "khoá của `config/audit.json`",
    "scripts/audit.mjs::timeout_moi_lenh_s": "khoá của `config/audit.json`",
    "frontend/src/components/chat/ChatScreen.tsx::dong": (
        "khoá của `NHAN_KET_NOI` = giá trị `\"dong\"` của union `ConnectionStatus` (chuỗi trạng thái)"
    ),
    "frontend/src/components/admin/adminLogic.test.ts::truong_moi": (
        "khoá giả lập trong `details.changed` của một dòng audit (dữ liệu trên dây); "
        "test so với chuỗi `\"truong_moi\"`"
    ),
}

_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def vietnamese_words(name: str) -> list[str]:
    """Các từ của `name` là âm tiết tiếng Việt không dấu."""
    return [w for w in (m.lower() for m in _WORD_RE.findall(name)) if w in _SYLLABLES]


# ── Python ─────────────────────────────────────────────────────────────────
def python_names(source: str) -> Iterator[tuple[int, str]]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield node.lineno, node.name
        elif isinstance(node, ast.arg):
            yield node.lineno, node.arg
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            yield node.lineno, node.attr
        elif isinstance(node, ast.ExceptHandler) and node.name:
            yield node.lineno, node.name
        elif isinstance(node, ast.alias) and node.asname:
            yield node.lineno, node.asname


# ── TS / TSX / JS ──────────────────────────────────────────────────────────
_IDENT_START = re.compile(r"[A-Za-z_$]")
_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
# Sau những token này, `/` mở một regex và `<` mở một phần tử JSX.
_EXPR_KEYWORDS = frozenset(
    "return typeof instanceof in of new delete void throw case do else yield await".split()
)


class _TsScanner:
    """Bộ tách token đủ dùng cho việc tìm định danh — KHÔNG phải parser.

    Bỏ qua: chuỗi `'…'`/`"…"`, template literal (nhưng quét phần `${…}`),
    comment, regex literal, và chữ nằm giữa các thẻ JSX (quét phần `{…}`).
    """

    def __init__(self, text: str, jsx: bool) -> None:
        self.s = text
        self.i = 0
        self.n = len(text)
        self.jsx = jsx
        self.prev = ""  # token có nghĩa gần nhất: định danh, số, hay dấu
        self.out: list[tuple[int, str]] = []  # (offset, định danh)
        self.comments: list[tuple[int, int]] = []  # (đầu, cuối) của comment

    def run(self) -> list[tuple[int, str]]:
        self.code(stop=None)
        return self.out

    def comment(self) -> bool:
        """Đang đứng ở đầu một comment thì nhảy qua nó và trả True."""
        s, start = self.s, self.i
        if s.startswith("//", start):
            j = s.find("\n", start)
            self.i = self.n if j < 0 else j
        elif s.startswith("/*", start):
            j = s.find("*/", start + 2)
            self.i = self.n if j < 0 else j + 2
        else:
            return False
        self.comments.append((start, self.i))
        return True

    def expr_start(self) -> bool:
        p = self.prev
        if p == "" or p in _EXPR_KEYWORDS:
            return True
        return not (_IDENT.fullmatch(p) or p[0].isdigit() or p in (")", "]", "}"))

    def code(self, stop: str | None) -> None:
        """Quét code tới khi gặp `}` khớp (stop="}") hoặc hết file."""
        depth = 0
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif self.comment():
                pass
            elif c in "'\"":
                self.string(c)
                self.prev = "str"
            elif c == "`":
                self.template()
                self.prev = "str"
            elif c == "/" and self.expr_start():
                self.regex()
                self.prev = "str"
            elif c == "<" and self.jsx and self.expr_start() and self.jsx_ahead():
                self.jsx_element()
                self.prev = "str"
            elif _IDENT_START.match(c):
                m = _IDENT.match(s, self.i)
                assert m
                word = m.group()
                # `a.b` — `b` vẫn là định danh (prop), nhưng không đổi `prev`
                # kiểu khác.
                self.out.append((self.i, word))
                self.prev = word
                self.i = m.end()
            elif c.isdigit():
                m = re.compile(r"[0-9][0-9A-Za-z_.]*").match(s, self.i)
                assert m
                self.prev = "0"
                self.i = m.end()
            elif c == "{":
                depth += 1
                self.prev = "{"
                self.i += 1
            elif c == "}":
                if depth == 0 and stop == "}":
                    self.i += 1
                    return
                depth -= 1
                self.prev = "}"
                self.i += 1
            else:
                # `=>` là một token: sau nó là biểu thức.
                if s.startswith("=>", self.i):
                    self.prev = "=>"
                    self.i += 2
                else:
                    self.prev = c
                    self.i += 1

    def string(self, q: str) -> None:
        s = self.s
        self.i += 1
        while self.i < self.n and s[self.i] != q:
            if s[self.i] == "\\":
                self.i += 1
            elif s[self.i] == "\n":
                break
            self.i += 1
        self.i += 1

    def template(self) -> None:
        s = self.s
        self.i += 1
        while self.i < self.n:
            c = s[self.i]
            if c == "\\":
                self.i += 2
            elif c == "`":
                self.i += 1
                return
            elif s.startswith("${", self.i):
                self.i += 2
                self.prev = "{"
                self.code(stop="}")
            else:
                self.i += 1

    def regex(self) -> None:
        s = self.s
        self.i += 1
        in_class = False
        while self.i < self.n:
            c = s[self.i]
            if c == "\\":
                self.i += 2
                continue
            if c == "\n":
                break
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                self.i += 1
                break
            self.i += 1
        m = re.compile(r"[a-z]*").match(s, self.i)
        assert m
        self.i = m.end()

    def jsx_ahead(self) -> bool:
        """`<` theo sau là tên thẻ hoặc `>` (fragment)."""
        j = self.i + 1
        return j < self.n and (self.s[j] == ">" or _IDENT_START.match(self.s[j]) is not None)

    def jsx_element(self) -> None:
        """Đang đứng ở `<` của một thẻ mở. Quét hết phần tử, kể cả thẻ đóng."""
        if self.jsx_tag() == "selfclose":
            return
        self.jsx_children()

    def jsx_tag(self) -> str:
        """Quét `<Name attr={…} attr2="…" {...spread}>`; trả "open"/"selfclose"."""
        s = self.s
        self.i += 1  # `<`
        while self.i < self.n:
            c = s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif self.comment():
                pass
            elif c == ">":
                self.i += 1
                return "open"
            elif s.startswith("/>", self.i):
                self.i += 2
                return "selfclose"
            elif c in "'\"":
                self.string(c)
            elif c == "{":
                self.i += 1
                self.prev = "{"
                self.code(stop="}")
            elif _IDENT_START.match(c):
                m = re.compile(r"[A-Za-z_$][A-Za-z0-9_$\-]*").match(s, self.i)
                assert m
                for part in re.finditer(r"[^-]+", m.group()):
                    self.out.append((self.i + part.start(), part.group()))
                self.i = m.end()
            else:
                self.i += 1  # `.`, `:`, `=`, `<` của generic…
        return "selfclose"

    def jsx_children(self) -> None:
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if s.startswith("</", self.i):
                j = s.find(">", self.i)
                # Tên thẻ đóng lặp lại tên thẻ mở — vẫn là định danh.
                for m in _IDENT.finditer(s, self.i + 2, self.n if j < 0 else j):
                    self.out.append((m.start(), m.group()))
                self.i = self.n if j < 0 else j + 1
                return
            if c == "<":
                self.jsx_element()
            elif c == "{":
                self.i += 1
                self.prev = "{"
                self.code(stop="}")
            else:
                self.i += 1  # chữ JSX — không phải định danh


def ts_names(source: str, jsx: bool) -> list[tuple[int, str]]:
    starts = [0] + [m.end() for m in re.finditer("\n", source)]
    return [
        (bisect.bisect_right(starts, pos), word) for pos, word in _TsScanner(source, jsx).run()
    ]


# ── Chạy ───────────────────────────────────────────────────────────────────
def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", *SCOPES],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = sorted({line for line in out.splitlines() if line})
    return [ROOT / f for f in files if (ROOT / f).is_file()]


def scan() -> Iterator[tuple[str, int, str]]:
    for path in tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        suffix = path.suffix
        if suffix not in PY_SUFFIXES | TS_SUFFIXES:
            continue
        stem = path.name.split(".", 1)[0]
        yield rel, 1, stem
        text = path.read_text(encoding="utf-8")
        if suffix in PY_SUFFIXES:
            names: Iterator[tuple[int, str]] | list[tuple[int, str]] = python_names(text)
        else:
            names = ts_names(text, jsx=suffix in {".tsx", ".jsx"})
        seen: set[tuple[int, str]] = set()
        for lineno, name in names:
            if (lineno, name) not in seen:
                seen.add((lineno, name))
                yield rel, lineno, name


def main(argv: list[str]) -> int:
    findings: list[tuple[str, int, str]] = []
    words: Counter[str] = Counter()
    for rel, lineno, name in scan():
        if name in _ALLOWED or f"{rel}::{name}" in _ALLOWED:
            continue
        hits = vietnamese_words(name)
        if hits:
            findings.append((rel, lineno, name))
            words.update(hits)
    for rel, lineno, name in sorted(findings):
        print(f"{rel}:{lineno}: {name}")
    if "--words" in argv:
        for word, count in words.most_common():
            print(f"{count:6d} {word}", file=sys.stderr)
    if findings:
        print(f"check-identifiers: {len(findings)} phat hien", file=sys.stderr)
        return 1
    print("check-identifiers: OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
