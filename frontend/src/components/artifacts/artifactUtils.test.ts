/**
 * Logic thuan cua panel artifact — T-5.5 (DoD dong 1: bang duoi, ten tep) va
 * quy tac be rong 640–1279 cua ban T-HD6 (B-366).
 */

import { describe, expect, it } from "vitest";

import { downloadName, extensionFor, languageName, lineCount, mimeFor, resolvePanelLayout } from "./artifactUtils";

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
