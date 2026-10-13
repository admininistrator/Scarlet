"""Loader skill (KH §13.2, spec agentskills.io) — T-7.5.

Đọc `skills/<name>/SKILL.md`, phân tích YAML frontmatter, ghi sổ `skills`.
Chạy một lần lúc `api` khởi động (`app/main.py::lifespan`); thêm/sửa skill ⇒
restart `api`.

**Một skill hỏng không gãy cả bộ** (Cạm bẫy ③, lối "lỗi là dữ liệu" của
T-6.1): frontmatter thiếu/hỏng, `name` sai luật hay lệch tên thư mục,
`description` rỗng hay quá 1024 ký tự ⇒ bỏ qua đúng skill đó + `WARNING`,
không `raise`. Skill đã có trong sổ mà lần này không nạp được ⇒ `enabled=false`
(`SkillRepository.disable_missing`) — user không thấy skill ma.

**Vượt trần ⇒ bỏ qua, không cắt.** Spec ghi trần như ràng buộc hợp lệ
(validator `skills-ref` báo lỗi), không như gợi ý cắt; cắt `description` để
tiết kiệm prompt là việc của tầng 1 (T-7.6, `SKILL_DESCRIPTION_MAX_CHARS`).

`requires_execution` = skill có thư mục `scripts/` (§13.2) — mức (b) cần
`run_code`; không có thì skill là hướng dẫn thuần, mức (a).

`default_enabled` (T-7.8b, NQ-148 ②) = `metadata.default_enabled` đúng **chuỗi**
`"true"` (spec: `metadata` là map chuỗi — Cạm bẫy ⑥). Thiếu khoá, `true` không
ngoặc (YAML bool), giá trị lạ ⇒ `false`: skill ngoài bộ dựng sẵn không đổi hành vi.

A3: thư mục gốc suy từ vị trí file như `CATALOG_PATH` (`/skills` trong
container, mount ở `docker-compose.yml`); không tên skill nào nằm trong `.py`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import SKILL_SPEC_DESCRIPTION_MAX_CHARS, SKILL_SPEC_NAME_MAX_CHARS
from app.db.repositories import SkillRepository

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
SKILL_FILE = "SKILL.md"
SCRIPTS_DIR = "scripts"
FRONTMATTER_FENCE = "---"
DEFAULT_ENABLED_KEY = "default_enabled"
DEFAULT_ENABLED_ON = "true"

#: Spec: chữ thường, số, gạch nối; không mở/đóng bằng gạch, không hai gạch liền.
_NAME_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


class SkillError(ValueError):
    """Một skill không hợp lệ — loader bắt, log, bỏ qua."""


@dataclass(frozen=True)
class SkillSpec:
    name: str
    display_name: str
    description: str
    path: str
    requires_execution: bool
    default_enabled: bool = False


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Khối YAML giữa hai dòng `---` ở đầu file. Thiếu/hỏng ⇒ `SkillError`."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        raise SkillError("thieu frontmatter")
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == FRONTMATTER_FENCE)
    except StopIteration:
        raise SkillError("frontmatter khong dong") from None
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise SkillError(f"YAML hong: {exc}") from None
    if not isinstance(data, dict):
        raise SkillError("frontmatter khong phai mapping")
    return data


def read_skill(directory: Path) -> SkillSpec:
    """Đọc + kiểm một thư mục skill theo spec. Không hợp lệ ⇒ `SkillError`."""
    try:
        meta = parse_frontmatter((directory / SKILL_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise SkillError(f"khong doc duoc {SKILL_FILE}: {exc}") from None

    name = meta.get("name")
    if not isinstance(name, str) or not name:
        raise SkillError("thieu name")
    if len(name) > SKILL_SPEC_NAME_MAX_CHARS or not _NAME_RE.fullmatch(name):
        raise SkillError(f"name sai luat spec: {name!r}")
    if name != directory.name:
        raise SkillError(f"name {name!r} lech thu muc {directory.name!r}")

    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        raise SkillError("thieu description")
    if len(description) > SKILL_SPEC_DESCRIPTION_MAX_CHARS:
        raise SkillError(f"description {len(description)} > {SKILL_SPEC_DESCRIPTION_MAX_CHARS}")

    metadata = meta.get("metadata", {})
    if not isinstance(metadata, dict):
        raise SkillError("metadata khong phai mapping")
    display_name = metadata.get("display_name")

    return SkillSpec(
        name=name,
        display_name=display_name if isinstance(display_name, str) and display_name else name,
        description=description.strip(),
        path=str(directory),
        requires_execution=(directory / SCRIPTS_DIR).is_dir(),
        default_enabled=metadata.get(DEFAULT_ENABLED_KEY) == DEFAULT_ENABLED_ON,
    )


def discover(root: Path) -> list[SkillSpec]:
    """Mọi skill hợp lệ dưới `root`; skill hỏng bị bỏ qua + `WARNING`."""
    if not root.is_dir():
        logger.warning("thu muc skill %s khong ton tai — 0 skill", root)
        return []
    found: list[SkillSpec] = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            found.append(read_skill(directory))
        except SkillError as exc:
            logger.warning("bo qua skill %s: %s", directory.name, exc)
    return found


async def sync_skills(session: AsyncSession, root: Path = SKILLS_DIR) -> list[SkillSpec]:
    """Ghi sổ `skills` theo đĩa: upsert skill hợp lệ, tắt skill không còn nạp được."""
    specs = discover(root)
    repo = SkillRepository(session)
    for spec in specs:
        await repo.upsert(
            name=spec.name,
            display_name=spec.display_name,
            description=spec.description,
            path=spec.path,
            requires_execution=spec.requires_execution,
            default_enabled=spec.default_enabled,
        )
    await repo.disable_missing([s.name for s in specs])
    logger.info("nap %d skill: %s", len(specs), ", ".join(s.name for s in specs))
    return specs
