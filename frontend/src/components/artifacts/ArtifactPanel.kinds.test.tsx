/**
 * Panel artifact hien theo `kind` — T-5.5 (DoD dong 1).
 *
 * Render THANG `ArtifactPanel` (khong qua `ChatScreen`): duong mo panel da co ca
 * o `ArtifactPanel.test.tsx` / `ArtifactFlow.test.tsx`. jsdom khong chay script
 * trong iframe va khong nap anh: `MessageEvent` voi `source` tu dat (lo
 * `ArtifactFrame.test.tsx`), `load` cua `<img>` ban tay. `URL.createObjectURL`
 * CO trong vitest nhung la ham cua Node, nem voi `Blob` cua jsdom (T-4.7 ④)
 * ⇒ `vi.spyOn(…).mockImplementation`.
 */

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import type { PathArtifact } from "../../lib/api";
import { ARTIFACT_MESSAGE, ARTIFACT_SANDBOX } from "./ArtifactFrame";
import { ArtifactPanel } from "./ArtifactPanel";

const art = (over: Partial<PathArtifact>): PathArtifact => ({
  id: "a1",
  kind: "code",
  language: "python",
  title: "Tieu de",
  version: 1,
  content: "print(1)\n",
  ...over,
});

const SVG_OK = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><circle cx="20" cy="20" r="18" fill="red"/></svg>';
/**
 * Chuoi cua DoD Chrome: `onload` + `<script>` + `<image onerror>`, ca ba ghi
 * `window.top.__pwned`. Do tren Chromium 153: chen qua `innerHTML` thi `<script>`
 * khong chay va `onload` cua `<svg>` khong ban — chi `<image onerror>` ban; thieu
 * no thi kiem nguoc "SVG qua innerHTML" khong bao gio do tren Chrome.
 */
const SVG_EVIL =
  '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" onload="window.top.__pwned=1"><script>window.top.__pwned=2</script><image href="x" onerror="window.top.__pwned=3"/><rect width="40" height="40" fill="red"/></svg>';

let created: MockInstance<typeof URL.createObjectURL>;
let revoked: MockInstance<typeof URL.revokeObjectURL>;
const blobByUrl = new Map<string, Blob>();

beforeEach(() => {
  blobByUrl.clear();
  created = vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
    const url = `blob:test/${blobByUrl.size + 1}`;
    blobByUrl.set(url, blob as Blob);
    return url;
  });
  revoked = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

function show(artifact: PathArtifact | null) {
  const view = render(<ArtifactPanel open artifact={artifact} onClose={() => {}} />);
  return {
    swap: (next: PathArtifact | null, open = true) =>
      view.rerender(<ArtifactPanel open={open} artifact={next} onClose={() => {}} />),
  };
}

const panel = () => document.getElementById("artifact-panel") as HTMLElement;
const source = () => panel().querySelector("pre.code-lines");

function send(source: MessageEventSource | null, data: unknown) {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, source, origin: "null" }));
  });
}

describe("renderer theo kind", () => {
  it("1. html ⇒ khung sandbox; svg ⇒ img blob:; markdown ⇒ Markdown; code ⇒ ma co so dong + Prism; react / mermaid / kind la ⇒ Ma", () => {
    const { swap } = show(art({ kind: "html", language: "html", content: "<p>x</p>" }));
    const frame = panel().querySelector("iframe");
    expect(frame).toHaveAttribute("sandbox", ARTIFACT_SANDBOX);
    expect(frame).toHaveAttribute("title", "Xem trước artifact");
    expect(within(panel()).getByRole("radiogroup", { name: "Chế độ xem" })).toBeInTheDocument();
    expect(within(panel()).getByText("Trang HTML")).toBeInTheDocument();
    expect(source()).toBeNull();

    swap(art({ id: "a2", kind: "svg", language: "svg", content: SVG_OK }));
    expect(panel().querySelector("iframe")).toBeNull();
    expect(panel().querySelector("img")?.getAttribute("src")).toMatch(/^blob:/);
    expect(within(panel()).getByRole("radiogroup", { name: "Chế độ xem" })).toBeInTheDocument();

    swap(art({ id: "a3", kind: "markdown", language: "md", content: "# Muc A\n\nmot **dam**" }));
    expect(within(panel()).getByRole("heading", { name: "Muc A" })).toBeInTheDocument();
    expect(panel().querySelector("strong")).toHaveTextContent("dam");
    expect(source()).toBeNull();
    expect(within(panel()).queryByRole("radiogroup")).toBeNull();

    swap(art({ id: "a4", kind: "code", language: "python", content: "def f():\n    return 1\n" }));
    expect(source()?.querySelectorAll(".code-line")).toHaveLength(2);
    expect(source()?.querySelector(".tk-keyword")).toHaveTextContent("def");
    expect(within(panel()).queryByRole("radiogroup")).toBeNull();

    for (const kind of ["react", "mermaid", "constructor"]) {
      swap(art({ id: kind, kind, language: kind === "react" ? "jsx" : "mermaid", content: "graph TD; A-->B" }));
      expect(source()).toHaveTextContent("graph TD; A-->B");
      expect(panel().querySelector("iframe, img")).toBeNull();
      expect(within(panel()).queryByRole("radiogroup")).toBeNull();
    }
    expect(within(panel()).getByText("Code")).toBeInTheDocument();
  });

  it("2. Xem truoc / Ma: radio + mui ten; Ma ⇒ ma nguon trong khoi, khung bien mat", async () => {
    const user = userEvent.setup();
    show(art({ kind: "html", language: "html", content: "<h1>Bang gia</h1>" }));
    const preview = within(panel()).getByRole("radio", { name: "Xem trước" });
    expect(preview).toHaveAttribute("aria-checked", "true");
    await user.click(within(panel()).getByRole("radio", { name: "Mã" }));
    expect(panel().querySelector("iframe")).toBeNull();
    expect(source()?.textContent).toBe("<h1>Bang gia</h1>");
    expect(within(panel()).getByRole("radio", { name: "Mã" })).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(preview).toHaveAttribute("aria-checked", "true");
    expect(preview).toHaveFocus();
    expect(panel().querySelector("iframe")).not.toBeNull();
  });
});

describe("SVG khong bao gio vao DOM cua origin chinh (Q-P5-6)", () => {
  it("3. SVG co <script> va onload ⇒ chi img[src^=blob:], khong script / rect / onload / __pwned nao trong DOM", () => {
    show(art({ kind: "svg", language: "svg", title: "Logo", content: SVG_EVIL }));
    const images = panel().querySelectorAll("img");
    expect(images).toHaveLength(1);
    expect(images[0].getAttribute("src")).toMatch(/^blob:/);
    expect(images[0]).toHaveAttribute("alt", "Logo");
    expect(document.querySelector("script, [onload], [onerror], rect[fill=red]")).toBeNull();
    expect(document.body.innerHTML).not.toContain("__pwned");
    expect((window as { __pwned?: unknown }).__pwned).toBeUndefined();
    // Blob mang DUNG noi dung, kieu anh — `<img>` khong chay script cua no.
    const blob = blobByUrl.get(images[0].getAttribute("src") as string);
    expect(blob?.type).toBe("image/svg+xml;charset=utf-8");
  });

  it("4. dem createObjectURL = revokeObjectURL sau nap / doi / Ma / dong; nap xong thu hoi NGAY, mot lan", async () => {
    const user = userEvent.setup();
    const { swap } = show(art({ kind: "svg", language: "svg", content: SVG_OK }));
    expect(created).toHaveBeenCalledTimes(1);
    expect(revoked).toHaveBeenCalledTimes(0);
    fireEvent.load(panel().querySelector("img") as HTMLImageElement);
    expect(revoked).toHaveBeenCalledTimes(1);

    // Artifact khac: URL moi; URL cu da thu hoi luc nap ⇒ khong thu hoi lan hai.
    swap(art({ id: "a2", kind: "svg", language: "svg", content: SVG_EVIL }));
    expect(created).toHaveBeenCalledTimes(2);
    expect(revoked).toHaveBeenCalledTimes(1);
    // Chua nap ma doi sang Ma ⇒ thu hoi luc go.
    await user.click(within(panel()).getByRole("radio", { name: "Mã" }));
    expect(revoked).toHaveBeenCalledTimes(2);
    await user.click(within(panel()).getByRole("radio", { name: "Xem trước" }));
    expect(created).toHaveBeenCalledTimes(3);
    swap(art({ id: "a2", kind: "svg", language: "svg", content: SVG_EVIL }), false);
    expect(panel()).toBeNull();

    expect(revoked).toHaveBeenCalledTimes(created.mock.calls.length);
    expect(new Set(revoked.mock.calls.map(([url]) => url))).toEqual(new Set(created.mock.results.map((r) => r.value)));
  });
});

describe("markdown: ba lop NQ-95, img bi chan (B-235)", () => {
  it("5. <img src=x onerror=…> va ![](https://…) ⇒ khong img, khong onerror; chu thuong van hien", () => {
    show(
      art({
        kind: "markdown",
        language: "md",
        content: '<img src=x onerror="window.__pwned=1">\n\n![anh](https://example.test/a.png)\n\nchu thuong',
      }),
    );
    expect(panel().querySelector("img")).toBeNull();
    expect(document.body.innerHTML).not.toContain("onerror");
    expect(document.body.innerHTML).not.toContain("example.test");
    expect(within(panel()).getByText("chu thuong")).toBeInTheDocument();
  });
});

describe("Tai (UC-10 dong 5)", () => {
  it("6. html / svg / markdown / code ⇒ a.download theo MOT ham lam sach + Blob dung kieu va noi dung; thu hoi sau khi bam", async () => {
    const user = userEvent.setup();
    const clicks: { download: string; href: string }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push({ download: this.download, href: this.getAttribute("href") ?? "" });
    });
    const cases: [PathArtifact, string, string][] = [
      [art({ kind: "html", language: "html", title: "Trang hiển thị mã 949133", version: 3, content: "<p>949133</p>" }), "trang-hien-thi-ma-949133-v3.html", "text/html;charset=utf-8"],
      [art({ kind: "svg", language: "svg", title: "", content: SVG_OK }), "artifact-v1.svg", "image/svg+xml;charset=utf-8"],
      [art({ kind: "markdown", language: "md", title: "Ghi chú", version: 2, content: "# a" }), "ghi-chu-v2.md", "text/markdown;charset=utf-8"],
      [art({ kind: "code", language: "python", title: "../../etc/passwd", content: "print(1)" }), "etc-passwd-v1.py", "text/plain;charset=utf-8"],
    ];
    const { swap } = show(null);
    for (const [artifact, name, type] of cases) {
      swap({ ...artifact, id: name });
      const ext = name.slice(name.lastIndexOf("."));
      await user.click(within(panel()).getByRole("button", { name: `Tải về ${ext}` }));
      const last = clicks[clicks.length - 1];
      expect(last.download).toBe(name);
      const blob = blobByUrl.get(last.href);
      expect(blob?.type).toBe(type);
      expect(await blob?.text()).toBe(artifact.content);
    }
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
    const revokedUrls = revoked.mock.calls.map(([url]) => url);
    for (const { href } of clicks) {
      expect(revokedUrls).toContain(href);
    }
  });
});

describe("khung html: dang nap / loi / Chay lai (ban T-HD6 ⑥)", () => {
  it("7. dang nap ⇒ dai trang thai + khung an; rendered ⇒ het dai; error ⇒ thong bao nguyen van + Chay lai ⇒ iframe MOI", async () => {
    const user = userEvent.setup();
    show(art({ kind: "html", language: "html", content: "<p>x</p>" }));
    const first = panel().querySelector("iframe") as HTMLIFrameElement;
    expect(within(panel()).getByRole("status")).toHaveTextContent("Đang chạy artifact…");
    expect(first.className).toContain("invisible");
    expect(first.className).toContain("bg-surface-artifact");

    send(first.contentWindow, { type: ARTIFACT_MESSAGE.rendered });
    expect(within(panel()).queryByRole("status")).toBeNull();
    expect(first.className).not.toContain("invisible");

    send(first.contentWindow, { type: ARTIFACT_MESSAGE.error, message: "TypeError: x is <null>" });
    const alert = within(panel()).getByRole("alert");
    expect(alert).toHaveTextContent("Artifact báo lỗi");
    expect(alert.querySelector("pre")?.textContent).toBe("TypeError: x is <null>");

    await user.click(within(alert).getByRole("button", { name: "Chạy lại" }));
    const second = panel().querySelector("iframe");
    expect(second).not.toBe(first);
    expect(first.isConnected).toBe(false);
    expect(within(panel()).getByRole("status")).toHaveTextContent("Đang chạy artifact…");
    expect(within(panel()).queryByRole("alert")).toBeNull();
  });
});

describe("dau panel (ban T-HD6, B-367 ③)", () => {
  it("8. tieu de rong ⇒ nhan suy ra 'Python · 3 dòng'; tieu de co ky tu dao chieu ⇒ da loc; trong ⇒ 'Artifact'", () => {
    const { swap } = show(art({ title: "", content: "a\nb\nc\n" }));
    expect(within(panel()).getByRole("heading")).toHaveTextContent("Python · 3 dòng");
    expect(within(panel()).getByText("Code")).toBeInTheDocument();

    swap(art({ id: "b", title: "", kind: "svg", language: null, content: SVG_OK }));
    expect(within(panel()).getByRole("heading")).toHaveTextContent("Ảnh SVG · 1 dòng");

    swap(art({ id: "c", title: "Bảng‮ giá", kind: "html", language: "html" }));
    expect(within(panel()).getByRole("heading").textContent).toBe("Bảng giá");

    swap(null);
    expect(within(panel()).getByRole("heading")).toHaveTextContent("Artifact");
    expect(screen.getByText("Chưa mở artifact nào")).toBeInTheDocument();
  });
});
