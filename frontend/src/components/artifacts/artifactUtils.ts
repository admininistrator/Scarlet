/**
 * Panel artifact — logic thuan, khong React (T-5.5, ban T-HD6 `artifactUtils.ts`).
 *
 * `kind` / `language` / `title` la DU LIEU do model sinh: tra bang bang
 * `Object.hasOwn` (lo `cardKind` cua T-5.3) — "constructor" khong duoc thanh
 * mot ham, "__proto__" khong duoc thanh mot object.
 */

const own = <T>(table: Readonly<Record<string, T>>, key: string): T | undefined =>
  Object.hasOwn(table, key) ? table[key] : undefined;

/** Ten ngon ngu de hien trong nhan suy ra ("Python · 42 dong"). Khong biet ⇒ `""` (roi ve nhan loai). */
const LANGUAGE_NAMES: Readonly<Record<string, string>> = {
  python: "Python", typescript: "TypeScript", ts: "TypeScript", tsx: "TSX", javascript: "JavaScript",
  js: "JavaScript", jsx: "JSX", html: "HTML", css: "CSS", json: "JSON", sql: "SQL", bash: "Bash",
  sh: "Shell", shell: "Shell", go: "Go", rust: "Rust", java: "Java", kotlin: "Kotlin", csharp: "C#",
  php: "PHP", ruby: "Ruby", yaml: "YAML", csv: "CSV", markdown: "Markdown", mermaid: "Mermaid", svg: "SVG",
};

/*
  MOT bang duoi tep (UC-10 dong 5): `kind` co duoi co dinh thang `language`;
  `code` (va moi `kind` la) theo `language`; khong biet ⇒ `.txt`.
*/
const KIND_EXT: Readonly<Record<string, string>> = {
  html: "html", react: "jsx", svg: "svg", mermaid: "mmd", markdown: "md",
};
const LANGUAGE_EXT: Readonly<Record<string, string>> = {
  python: "py", typescript: "ts", ts: "ts", tsx: "tsx", javascript: "js", js: "js", jsx: "jsx", html: "html",
  css: "css", json: "json", sql: "sql", bash: "sh", sh: "sh", shell: "sh", go: "go", rust: "rs", java: "java",
  kotlin: "kt", csharp: "cs", php: "php", ruby: "rb", yaml: "yml", csv: "csv", markdown: "md", text: "txt",
};
const KIND_MIME: Readonly<Record<string, string>> = {
  html: "text/html", svg: "image/svg+xml", markdown: "text/markdown",
};

const normalized = (language: string | null) => (language ?? "").trim().toLowerCase();

export const languageName = (language: string | null): string => own(LANGUAGE_NAMES, normalized(language)) ?? "";

/** Duoi tep kem dau cham. `react` co `language` tsx / typescript ⇒ `.tsx` (ban T-HD6). */
export function extensionFor(kind: string, language: string | null): string {
  const key = normalized(language);
  if (kind === "react" && (key === "tsx" || key === "typescript")) {
    return ".tsx";
  }
  return `.${own(KIND_EXT, kind) ?? own(LANGUAGE_EXT, key) ?? "txt"}`;
}

export const mimeFor = (kind: string): string => `${own(KIND_MIME, kind) ?? "text/plain"};charset=utf-8`;

/** So dong; MOT `\n` o cuoi khong tinh la dong moi. */
export function lineCount(content: string): number {
  return content === "" ? 0 : content.replace(/\n$/, "").split("\n").length;
}

/** Tran do dai phan ten, truoc `-v<so>` va duoi (ban T-HD6). */
const SLUG_MAX_CHARS = 60;

/**
 * Ten tep tai ve — MOT ham lam sach (ban T-HD6: "trang-hien-thi-ma-949133-v3.html").
 *
 * Danh sach TRANG chu khong danh sach den: chi `[a-z0-9-]` song sot, nen
 * `/ \ : * ? " < > |`, `..`, ky tu dieu khien va dao chieu (U+202E — "a‮fdp.exe"
 * hien thanh "aexe.pdf") deu mat ma khong can liet ke. Ten danh rieng cua
 * Windows (`CON`, `NUL`, `COM1`…, ca khi co duoi) khong the xay ra: ten luon
 * mang hau to `-v<so>`. Tieu de rong / chi con ky tu la ⇒ `artifact`.
 */
export function downloadName(a: { title: string; version: number; kind: string; language: string | null }): string {
  const slug = a.title
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[đĐ]/g, "d")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .slice(0, SLUG_MAX_CHARS)
    .replace(/^-+|-+$/g, "");
  return `${slug || "artifact"}-v${a.version}${extensionFor(a.kind, a.language)}`;
}

// ───────────────────── be rong panel theo cua so va neo (ban T-HD6 1k) ─────────────────────

export type PanelMode = "push" | "overlay";

/**
 * Quy tac 640–1279 (B-366). Moi so la so do / token, khong so cung:
 *   con cho cho gap + panel-min + cot chat ≥ chatMin ⇒ `push`: day cot chat,
 *       tran = min(max, cho con lai − chatMin) — cot chat khong hep hon 375;
 *   khong con ⇒ `overlay`: hop noi de len cot chat, le `gap` ca hai ben.
 * `stored` (localStorage) KHONG bi ghi de khi kep: man rong lai thi panel ve
 * dung be rong da keo. `low` / `high` la khoang cua tay nam (`aria-valuemin/max`).
 * < 640 px (dialog phu kin) khong qua day.
 */
export function resolvePanelLayout(p: {
  viewport: number;
  /** Cho sidebar doc chiem (neo hai ben: sidebar + le dao), neo tren 0. */
  sidebar: number;
  gap: number;
  stored: number;
  min: number;
  max: number;
  chatMin: number;
}): { mode: PanelMode; width: number; low: number; high: number } {
  const available = p.viewport - p.sidebar - p.gap;
  const fit = (low: number, high: number, mode: PanelMode) => ({
    mode,
    width: Math.max(low, Math.min(high, p.stored)),
    low,
    high,
  });
  if (available - p.min >= p.chatMin) {
    return fit(p.min, Math.min(p.max, available - p.chatMin), "push");
  }
  const room = available - p.gap;
  return fit(Math.min(p.min, room), Math.min(p.max, room), "overlay");
}

// ───────────────────── phien ban: so ho, khac biet theo dong (T-5.9, ban T-HD6) ─────────────────────

/** So phien ban danh theo DONG (Q-P5-2): phien ban cua message da xoa mem vang ⇒ "v1 v4". */
export const hasGapBefore = (versions: readonly { version: number }[], i: number): boolean =>
  i > 0 && versions[i].version - versions[i - 1].version > 1;

export type DiffOp = "same" | "add" | "del";
export interface DiffLine {
  op: DiffOp;
  text: string;
}
export type DiffBlock = { type: "lines"; lines: DiffLine[] } | { type: "fold"; id: number; lines: DiffLine[] };

/**
 * Tran so dong MOI BEN cua doan giua (sau khi cat dau / cuoi giong nhau).
 * ponytail: bang LCS O(n·m) thoi gian va bo nho (2000 × 2000 = 16 MB Uint32);
 * vuot ⇒ `null` ("qua dai de so"), khong treo luong chinh. Can so tep lon ⇒ Myers O(ND).
 */
export const DIFF_MAX_LINES = 2000;

/** Chuoi rong = 0 dong (khong phai mot dong rong); MOT `\n` cuoi khong tinh. */
const linesOf = (text: string): string[] => (text === "" ? [] : text.replace(/\n$/, "").split("\n"));

/**
 * Khac biet theo dong, LCS tu viet (khong phu thuoc moi). So dong them + bo
 * = n + m − 2·LCS — dung so cua `diff --minimal`. Cat phan dau / cuoi giong
 * nhau truoc, nen sua nho tren tep dai van nhanh va khong cham tran.
 */
export function diffLines(before: string, after: string): DiffLine[] | null {
  const a = linesOf(before);
  const b = linesOf(after);
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }
  const x = a.slice(start, endA);
  const y = b.slice(start, endB);
  const n = x.length;
  const m = y.length;
  if (n > DIFF_MAX_LINES || m > DIFF_MAX_LINES) {
    return null;
  }
  const w = m + 1;
  const dp = new Uint32Array((n + 1) * w);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i * w + j] = x[i] === y[j] ? dp[(i + 1) * w + j + 1] + 1 : Math.max(dp[(i + 1) * w + j], dp[i * w + j + 1]);
    }
  }
  const same = (text: string): DiffLine => ({ op: "same", text });
  const out = a.slice(0, start).map(same);
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      out.push(same(x[i]));
      i++;
      j++;
    } else if (dp[(i + 1) * w + j] >= dp[i * w + j + 1]) {
      out.push({ op: "del", text: x[i++] });
    } else {
      out.push({ op: "add", text: y[j++] });
    }
  }
  while (i < n) out.push({ op: "del", text: x[i++] });
  while (j < m) out.push({ op: "add", text: y[j++] });
  return out.concat(a.slice(endA).map(same));
}

export const diffCounts = (lines: readonly DiffLine[]) => ({
  added: lines.filter((l) => l.op === "add").length,
  removed: lines.filter((l) => l.op === "del").length,
});

/** Gap doan giong nhau dai, giu `context` dong quanh moi cho doi (ban T-HD6). */
export function foldUnchanged(lines: readonly DiffLine[], context = 3): DiffBlock[] {
  const blocks: DiffBlock[] = [];
  let run: DiffLine[] = [];
  let id = 0;
  const pushLines = (ls: DiffLine[]) => {
    if (ls.length === 0) return;
    const last = blocks[blocks.length - 1];
    if (last?.type === "lines") last.lines.push(...ls);
    else blocks.push({ type: "lines", lines: [...ls] });
  };
  const flush = (atStart: boolean, atEnd: boolean) => {
    const keepHead = atStart ? 0 : context;
    const keepTail = atEnd ? 0 : context;
    if (run.length > keepHead + keepTail + 1) {
      pushLines(run.slice(0, keepHead));
      blocks.push({ type: "fold", id: id++, lines: run.slice(keepHead, run.length - keepTail) });
      pushLines(run.slice(run.length - keepTail));
    } else {
      pushLines(run);
    }
    run = [];
  };
  let seenChange = false;
  for (const line of lines) {
    if (line.op === "same") {
      run.push(line);
      continue;
    }
    flush(!seenChange, false);
    seenChange = true;
    pushLines([line]);
  }
  flush(!seenChange, true);
  return blocks;
}
