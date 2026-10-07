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
