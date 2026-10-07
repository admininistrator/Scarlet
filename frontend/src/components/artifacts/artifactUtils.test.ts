/**
 * Logic thuan cua panel artifact — T-5.5 (DoD dong 1: bang duoi, ten tep) va
 * quy tac be rong 640–1279 cua ban T-HD6 (B-366).
 */

import { describe, expect, it } from "vitest";

import {
  DIFF_MAX_LINES,
  diffCounts,
  diffLines,
  downloadName,
  extensionFor,
  foldUnchanged,
  hasGapBefore,
  languageName,
  lineCount,
  mimeFor,
  resolvePanelLayout,
  type DiffLine,
} from "./artifactUtils";

describe("duoi tep va MIME — MOT bang", () => {
  it("1. kind co duoi co dinh; code theo language; khong biet / du lieu doc ⇒ .txt", () => {
    expect(extensionFor("html", "html")).toBe(".html");
    expect(extensionFor("react", "jsx")).toBe(".jsx");
    expect(extensionFor("react", "tsx")).toBe(".tsx");
    expect(extensionFor("svg", "svg")).toBe(".svg");
    expect(extensionFor("mermaid", "mermaid")).toBe(".mmd");
    expect(extensionFor("markdown", "md")).toBe(".md");
    expect(extensionFor("code", "python")).toBe(".py");
    expect(extensionFor("code", " TypeScript ")).toBe(".ts");
    expect(extensionFor("code", "brainfuck")).toBe(".txt");
    expect(extensionFor("code", null)).toBe(".txt");
    // `kind` / `language` la du lieu cua model: khoa cua Object.prototype khong duoc lot.
    expect(extensionFor("constructor", "__proto__")).toBe(".txt");
    expect(extensionFor("code", "toString")).toBe(".txt");

    expect(mimeFor("html")).toBe("text/html;charset=utf-8");
    expect(mimeFor("svg")).toBe("image/svg+xml;charset=utf-8");
    expect(mimeFor("markdown")).toBe("text/markdown;charset=utf-8");
    expect(mimeFor("code")).toBe("text/plain;charset=utf-8");
    expect(mimeFor("constructor")).toBe("text/plain;charset=utf-8");

    expect(languageName("python")).toBe("Python");
    expect(languageName("hasOwnProperty")).toBe("");
    expect(lineCount("a\nb\n")).toBe(2);
    expect(lineCount("")).toBe(0);
  });
});

/** Ten thiet bi danh rieng cua Windows — CA khi co duoi (`CON.txt` van la CON). */
const WINDOWS_RESERVED = /^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\.|$)/i;

describe("ten tep tai ve — MOT ham lam sach", () => {
  const art = (title: string, kind = "code", language: string | null = "python", version = 1) => ({
    title,
    kind,
    language,
    version,
  });

  it("2. ../../x, CON, a<U+202E>fdp.exe, tieu de rong, ky tu cam ⇒ da lam sach", () => {
    expect(downloadName(art("../../x", "html", "html"))).toBe("x-v1.html");
    expect(downloadName(art("CON", "code", "text", 2))).toBe("con-v2.txt");
    expect(downloadName(art("CON", "code", "text", 2))).not.toMatch(WINDOWS_RESERVED);
    expect(downloadName(art("nul.txt"))).not.toMatch(WINDOWS_RESERVED);

    const spoof = downloadName(art("a‮fdp.exe"));
    expect(spoof).toBe("a-fdp-exe-v1.py");
    expect(spoof).not.toMatch(/[‪-‮⁦-⁩‎‏]/);

    expect(downloadName(art("", "svg", null, 3))).toBe("artifact-v3.svg");
    expect(downloadName(art("   ", "markdown", "md"))).toBe("artifact-v1.md");
    expect(downloadName(art("\u0000\u001f\u007f", "html", "html"))).toBe("artifact-v1.html");

    const nasty = downloadName(art('a/b\\c:d*e?f"g<h>i|j\tk\nl'));
    expect(nasty).toBe("a-b-c-d-e-f-g-h-i-j-k-l-v1.py");
    expect(nasty).not.toMatch(/[/\\:*?"<>|\u0000-\u001f]/);

    expect(downloadName(art("Trang hiển thị mã 949133", "html", "html", 3))).toBe("trang-hien-thi-ma-949133-v3.html");
    expect(downloadName(art("Đường đi", "code", "python"))).toBe("duong-di-v1.py");
  });

  it("3. tieu de dai ⇒ cat 60 ky tu (khong de gach cuoi), hau to phien ban + duoi van con", () => {
    const name = downloadName(art(`${"a".repeat(59)} ${"b".repeat(200)}`));
    expect(name).toBe(`${"a".repeat(59)}-v1.py`);
    expect(downloadName(art("x".repeat(500)))).toBe(`${"x".repeat(60)}-v1.py`);
  });
});

describe("be rong panel theo cua so va neo (ban T-HD6 1k, B-366)", () => {
  const base = { gap: 16, min: 320, max: 560, chatMin: 375 };

  it("4. bang quy tac: day cot chat khi con cho, phu len khi het; da luu khong bi ghi de", () => {
    // 1440, neo tren: day, tran 560.
    expect(resolvePanelLayout({ ...base, viewport: 1440, sidebar: 0, stored: 380 })).toEqual({
      mode: "push",
      width: 380,
      low: 320,
      high: 560,
    });
    // 1024, neo trai, da keo 560 ⇒ 361, cot chat 375 (ban ve 1k).
    expect(resolvePanelLayout({ ...base, viewport: 1024, sidebar: 272, stored: 560 })).toEqual({
      mode: "push",
      width: 361,
      low: 320,
      high: 361,
    });
    // Nguong: neo tren day tu 711, neo hai ben tu 983.
    expect(resolvePanelLayout({ ...base, viewport: 711, sidebar: 0, stored: 380 }).mode).toBe("push");
    expect(resolvePanelLayout({ ...base, viewport: 710, sidebar: 0, stored: 380 }).mode).toBe("overlay");
    expect(resolvePanelLayout({ ...base, viewport: 983, sidebar: 272, stored: 380 }).mode).toBe("push");
    expect(resolvePanelLayout({ ...base, viewport: 982, sidebar: 272, stored: 380 }).mode).toBe("overlay");
    // Phu len: tran = min(560, man − sidebar − 32).
    expect(resolvePanelLayout({ ...base, viewport: 700, sidebar: 0, stored: 560 })).toEqual({
      mode: "overlay",
      width: 560,
      low: 320,
      high: 560,
    });
    expect(resolvePanelLayout({ ...base, viewport: 640, sidebar: 272, stored: 380 })).toEqual({
      mode: "overlay",
      width: 336,
      low: 320,
      high: 336,
    });
  });
});

describe("khac biet theo dong (T-5.9) — LCS tu viet", () => {
  const ops = (lines: DiffLine[] | null) => (lines ?? []).map((l) => `${l.op === "same" ? " " : l.op === "add" ? "+" : "-"}${l.text}`);

  it("5. rong ⇒ toan them (khong co 'dong rong' bi bo); nguoc lai ⇒ toan bo", () => {
    expect(ops(diffLines("", "a\nb\n"))).toEqual(["+a", "+b"]);
    expect(ops(diffLines("a\nb", ""))).toEqual(["-a", "-b"]);
    expect(diffLines("", "")).toEqual([]);
  });

  it("6. giong het ⇒ 0 dong doi; MOT `\\n` cuoi khong phai khac biet", () => {
    const lines = diffLines("x\ny\nz\n", "x\ny\nz") ?? [];
    expect(diffCounts(lines)).toEqual({ added: 0, removed: 0 });
    expect(lines).toHaveLength(3);
  });

  it("7. doi mot dong giua ⇒ -1 +1, moi dong khac giu nguyen", () => {
    expect(ops(diffLines("1\n2\n3\n4\n5", "1\n2\nTHREE\n4\n5"))).toEqual([" 1", " 2", "-3", "+THREE", " 4", " 5"]);
  });

  it("8. doi mot khoi (3 dong tu dau xuong cuoi) ⇒ +3 −3 — dung so cua `diff --minimal`", () => {
    const lines = diffLines("a\nb\nc\nd\ne\nf", "d\ne\nf\na\nb\nc");
    expect(diffCounts(lines ?? [])).toEqual({ added: 3, removed: 3 });
    expect(ops(lines).filter((l) => l.startsWith(" "))).toHaveLength(3);
  });

  it("9. vuot tran ⇒ `null`; dau / cuoi giong nhau khong tinh vao tran", () => {
    const many = (tag: string, n: number) => Array.from({ length: n }, (_, i) => `${tag}${i}`).join("\n");
    expect(diffLines(many("x", DIFF_MAX_LINES + 1), many("y", 3))).toBeNull();
    expect(diffLines(many("x", 3), many("y", DIFF_MAX_LINES + 1))).toBeNull();
    expect(diffLines(many("x", DIFF_MAX_LINES), many("y", DIFF_MAX_LINES))).not.toBeNull();
    // 10 000 dong, sua MOT dong ⇒ doan giua 1 × 1, khong cham tran.
    const long = many("l", 10_000);
    expect(diffCounts(diffLines(long, long.replace("l5000\n", "L5000\n")) ?? [])).toEqual({ added: 1, removed: 1 });
  });

  it("10. gap doan giong nhau dai, giu 3 dong quanh cho doi; so ho giua hai phien ban", () => {
    const before = Array.from({ length: 20 }, (_, i) => `r${i}`).join("\n");
    const blocks = foldUnchanged(diffLines(before, before.replace("r10", "R10")) ?? []);
    expect(blocks.map((b) => `${b.type}:${b.lines.length}`)).toEqual(["fold:7", "lines:8", "fold:6"]);
    expect(hasGapBefore([{ version: 1 }, { version: 4 }, { version: 5 }], 1)).toBe(true);
    expect(hasGapBefore([{ version: 1 }, { version: 4 }, { version: 5 }], 2)).toBe(false);
    expect(hasGapBefore([{ version: 1 }], 0)).toBe(false);
  });
});
