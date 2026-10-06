/**
 * Bon thanh phan bong bong DUNG SAN, CHUA MOUNT — T-S.15 "Viec" dong 4, §7b.2.
 *
 * Test render voi fixture: hinh dang (ban T-HD3-v2 3e) va cot `data-planned`
 * khong muc trong luc cho P4–P7. Mot nua file la Cam bay ② cua T-S.15: du
 * lieu that (tieu de trang web, ten tep, URL do model dua) phai qua bo loc
 * NGAY tu bay gio, khong phai ngay gan.
 *
 * KH tham chieu: §24.2b·S12, §20 (XSS) · tasks.md T-S.15, T-3.5, B-235.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  ArtifactCard,
  CARD_KIND,
  artifactLabel,
  SourceList,
  ToolChips,
  UserAttachments,
  plainText,
  sameOriginSrc,
  sourceHref,
} from "./BubbleExtras";

const RLO = "‮";

describe("bo loc dung chung (Cam bay ②)", () => {
  it("1 — `plainText` bo ky tu dieu khien + dao chieu, gop khoang trang", () => {
    expect(plainText(`  hoa-don${RLO}fdp.exe \n\t x\u0000`)).toBe("hoa-donfdp.exe x");
  });

  it("2 — `sourceHref`: chi `http(s)` tuyet doi", () => {
    expect(sourceHref("https://redis.io/docs")).toBe("https://redis.io/docs");
    expect(sourceHref("javascript:alert(1)")).toBeNull();
    expect(sourceHref("java\u0000script:alert(1)")).toBeNull();
    expect(sourceHref("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(sourceHref("mailto:a@b.c")).toBeNull();
    expect(sourceHref("/api/v1/khong-phai-nguon-web")).toBeNull();
  });

  it("3 — `sameOriginSrc`: chi URL tren chinh origin cua Scarlet", () => {
    expect(sameOriginSrc("/api/v1/favicons/redis.io.png")).toBe(`${window.location.origin}/api/v1/favicons/redis.io.png`);
    expect(sameOriginSrc("https://tracker.example/p.gif?d=hoi-thoai")).toBeNull();
    expect(sameOriginSrc("javascript:alert(1)")).toBeNull();
    expect(sameOriginSrc(undefined)).toBeNull();
  });
});

describe("chip trang thai cong cu (T-6.7, T-7.9)", () => {
  it("4 — dang chay: `role=status`, vong quay trong span `motion-spin` rieng, chu dung yen", () => {
    render(<ToolChips tools={[{ kind: "webSearch", running: true }]} />);
    const chip = screen.getByRole("status");

    expect(chip).toHaveTextContent("Đang tìm web…");
    expect(chip).toHaveAttribute("data-planned", "T-6.7");
    const spinner = chip.querySelector(".motion-spin");
    expect(spinner).not.toBeNull();
    expect(spinner).toHaveAttribute("aria-hidden", "true");
    expect(spinner?.textContent).toBe("");
  });

  it("5 — xong: chu 'Da…' mau muted, khong con vong quay; chay code mang `T-7.9`", () => {
    render(
      <ToolChips
        tools={[
          { kind: "webSearch", running: false },
          { kind: "codeRun", running: true },
        ]}
      />,
    );
    const [web, code] = screen.getAllByRole("status");

    expect(web).toHaveTextContent("Đã tìm web");
    expect(web).toHaveClass("text-muted");
    expect(web.querySelector(".motion-spin")).toBeNull();
    expect(code).toHaveTextContent("Đang chạy code…");
    expect(code).toHaveAttribute("data-planned", "T-7.9");
  });

  it("6 — khong co cong cu nao ⇒ khong ve gi", () => {
    const { container } = render(<ToolChips tools={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("chip nguon (T-6.7)", () => {
  it("7 — moi nguon la mot link tab moi `noopener noreferrer`, ten day du o `title` + `aria-label`", () => {
    render(
      <SourceList
        sources={[
          { url: "https://redis.io/docs/rate-limit", title: "redis.io" },
          { url: "https://github.com/redis/redis", title: "Tài liệu Redis: Rate limiting patterns với INCR và EXPIRE" },
        ]}
      />,
    );
    const list = screen.getByRole("list", { name: "Nguồn" });
    expect(list).toHaveAttribute("data-planned", "T-6.7");

    const links = within(list).getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[1]).toHaveAttribute("href", "https://github.com/redis/redis");
    expect(links[1]).toHaveAttribute("target", "_blank");
    expect(links[1]).toHaveAttribute("rel", "noopener noreferrer");
    expect(links[1]).toHaveAttribute("title", "Tài liệu Redis: Rate limiting patterns với INCR và EXPIRE");
    expect(links[1]).toHaveAccessibleName("Tài liệu Redis: Rate limiting patterns với INCR và EXPIRE");
    // Vung bam 44, chip ve 32 (ban ve 3h).
    expect(links[1]).toHaveClass("min-h-touch");
    expect(links[1].firstElementChild).toHaveClass("h-chip", "max-w-source-chip");
  });

  it("8 — URL `javascript:` / `data:` ⇒ chip van hien nhung KHONG la link", () => {
    const { container } = render(
      <SourceList
        sources={[
          { url: "javascript:alert(1)", title: "bay" },
          { url: "data:text/html,<script>alert(1)</script>", title: "bay hai" },
        ]}
      />,
    );

    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(container.querySelector("[href]")).toBeNull();
    expect(container.textContent).toContain("bay hai");
  });

  it("9 — tieu de chua HTML la CHU, khong thanh phan tu; ky tu dao chieu bi bo", () => {
    const { container } = render(
      <SourceList
        sources={[{ url: "https://x.example/", title: `<img src=x onerror=alert(1)>tin${RLO}gnp.exe` }]}
      />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>tingnp.exe");
    expect(container.textContent).not.toContain(RLO);
  });

  it("10 — favicon cung origin ⇒ `<img>` 16 px; loi tai ⇒ o chu cai du phong", () => {
    const { container } = render(
      <SourceList sources={[{ url: "https://redis.io/", title: "redis.io", faviconUrl: "/api/v1/favicons/redis.io" }]} />,
    );
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute("alt", "");
    expect(img).toHaveClass("size-favicon");

    fireEvent.error(img as HTMLImageElement);

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[aria-hidden='true']")?.textContent).toBe("R");
  });

  it("11 — favicon NGOAI origin ⇒ khong mot `<img>` nao (trinh duyet se tu GET ra ngoai)", () => {
    const { container } = render(
      <SourceList
        sources={[{ url: "https://github.com/", title: "github.com", faviconUrl: "https://github.com/favicon.ico" }]}
      />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[aria-hidden='true']")?.textContent).toBe("G");
  });
});

describe("the artifact (T-5.3)", () => {
  it("12 — tieu de, nhan phien ban `v3` tu SO cua may chu, nhan loai; khong con `data-planned`", () => {
    const { container } = render(
      <ArtifactCard
        artifact={{ kind: "code", title: "readQuota.ts — đọc hạn mức từ Redis", version: 3 }}
        onOpen={() => {}}
      />,
    );
    const card = container.firstElementChild as HTMLElement;

    expect(container.querySelector("[data-planned]")).toBeNull();
    expect(card).toHaveClass("max-w-artifact");
    expect(card).toHaveTextContent("readQuota.ts — đọc hạn mức từ Redis");
    expect(card).toHaveTextContent("v3");
    expect(card).toHaveTextContent("Code");
  });

  it("13 — nut 'Mo' la nut THAT (khong `aria-disabled`), ten truy cap mang tieu de, bam ⇒ `onOpen`", () => {
    const onOpen = vi.fn();
    render(<ArtifactCard artifact={{ kind: "html", title: "Bang gia", version: 1 }} onOpen={onOpen} />);
    const open = screen.getByRole("button", { name: "Mở Bang gia" });

    expect(open).toHaveTextContent(/^Mở$/);
    expect(open).not.toHaveAttribute("aria-disabled");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(open);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("16 — bang `kind`: bay gia tri cua DDL ⇒ bon loai cua the, MOT bang; chu la ⇒ Code", () => {
    const rows: [string, string][] = [
      ["html", "Trang HTML"],
      ["react", "Trang HTML"],
      ["svg", "Biểu đồ"],
      ["mermaid", "Biểu đồ"],
      ["markdown", "Tài liệu"],
      ["file", "Tài liệu"],
      ["code", "Code"],
      ["constructor", "Code"],
      ["la-hoan-toan", "Code"],
    ];
    for (const [kind, type] of rows) {
      const { container, unmount } = render(
        <ArtifactCard artifact={{ kind, title: "T", version: 1 }} onOpen={() => {}} />,
      );
      expect(container.querySelector(".text-xs.text-muted")).toHaveTextContent(type);
      unmount();
    }
    expect(Object.keys(CARD_KIND).sort()).toEqual(["code", "file", "html", "markdown", "mermaid", "react", "svg"]);
  });

  it("17 — tieu de do model dat co `U+202E` ⇒ ky tu bi bo (the va ten nut)", () => {
    render(<ArtifactCard artifact={{ kind: "code", title: `hoa-don${RLO}fdp.exe`, version: 1 }} onOpen={() => {}} />);

    expect(screen.getByText("hoa-donfdp.exe")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mở hoa-donfdp.exe" })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(RLO);
  });

  it("18 — tieu de rong ⇒ nhan suy ra 'ngon ngu · N dong'; chua co `content` ⇒ chi ngon ngu / loai", () => {
    expect(artifactLabel({ kind: "code", title: "", version: 1, language: "python", content: "a\nb\nc" })).toBe(
      "python · 3 dòng",
    );
    expect(artifactLabel({ kind: "html", title: "  ", version: 1, language: null, content: "<p>" })).toBe(
      "Trang HTML · 1 dòng",
    );
    expect(artifactLabel({ kind: "react", title: "", version: 2 })).toBe("Trang HTML");
    render(
      <ArtifactCard
        artifact={{ kind: "code", title: "", version: 1, language: "ts", content: "x\ny" }}
        onOpen={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Mở ts · 2 dòng" })).toBeInTheDocument();
  });
});

describe("anh / tep trong bong bong nguoi dung (T-4.7)", () => {
  it("14 — anh cung origin ⇒ thumbnail `alt` = ten tep; tep ⇒ chip ten + dung luong, KHONG nut xoa", () => {
    render(
      <UserAttachments
        items={[
          { id: "1", kind: "image", name: "dashboard.png", bytes: 1000, thumbnailUrl: "/api/v1/attachments/1/thumb" },
          { id: "2", kind: "file", name: "bao-cao-chi-phi-quy-3-2026.pdf", bytes: 2516582 },
        ]}
      />,
    );
    const list = screen.getByRole("list", { name: "Tệp đính kèm" });

    expect(list).not.toHaveAttribute("data-planned");
    expect(within(list).getByRole("img", { name: "dashboard.png" }).closest("li")).toHaveClass("size-thumb");
    expect(within(list).getByText("bao-cao-chi-phi-quy-3-2026.pdf")).toBeInTheDocument();
    expect(within(list).getByText("2,4 MB")).toBeInTheDocument();
    expect(within(list).queryAllByRole("button")).toHaveLength(0);
  });

  it("15 — thumbnail NGOAI origin ⇒ icon anh mang ten tep, khong `<img src>` nao; ten tep qua bo loc", () => {
    const { container } = render(
      <UserAttachments
        items={[
          { id: "1", kind: "image", name: `anh${RLO}gpj.exe`, bytes: 10, thumbnailUrl: "https://tracker.example/t.png" },
        ]}
      />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("img", { name: "anhgpj.exe" })).toBeInTheDocument();
  });
});
