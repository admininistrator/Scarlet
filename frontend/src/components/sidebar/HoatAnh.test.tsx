/**
 * Hoat anh cua sidebar va `prefers-reduced-motion` — T-3.9, ban T-HD5.
 *
 * KH tham chieu: §19.1, §2.3 (P5) · tasks.md T-3.9 (DoD dong 2, 3).
 *
 * Cam bay ② cua task: *"`make audit` khong bat duoc `prefers-reduced-motion`
 * sai"* — ca `lighthouse` lan `axe` deu khong cham no. File nay la phep do
 * duy nhat, nen no kiem CA HAI nua cua loi hua:
 *
 *   1. Phia JS: `matchMedia` noi "giam" ⇒ khoi sidebar mang
 *      `data-motion="none"`, khong mang `motion-sidebar`, va dong la go khoi
 *      DOM NGAY — khong cho token nao.
 *   2. Phia CSS: `theme.css` co dung khoi `@media` voi DUNG chuoi truy van ma
 *      JS dung, va khoi ay TAT (`none`) va dua MOI token `--duration-*` ve 0 —
 *      khong "giam con mot mili-giay". jsdom khong tinh `@media`, nen phan nay
 *      doc thang van ban cua `theme.css`.
 *
 * Ca am cua DoD dong 3: xoa khoi `@media` khoi `theme.css` ⇒ ca "reduce" do.
 *
 * File nay nam trong `components/` nen DoD dong 1 (`grep` so ms / thuoc tinh
 * hoat anh) quet ca no: moi thoi luong o day DOC tu `theme.css`, khong go tay.
 */

import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      danhSachHoiThoai: vi.fn(),
      suaHoiThoai: vi.fn(),
      xoaHoiThoai: vi.fn(),
    },
  };
});

import themeCss from "../../styles/theme.css?raw";
import { api } from "../../lib/api";
import { t } from "../../lib/i18n";
import { REDUCED_MOTION_QUERY, readDurationMs } from "../../lib/motion";
import { Sidebar } from "./Sidebar";
import { resetSidebarOpenForTest, toggleSidebar } from "./sidebarOpen";

function stubMatchMedia(reduce: boolean): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === REDUCED_MOTION_QUERY ? reduce : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

/** Dung sidebar roi cho luot tai danh sach dau tien ve xong (tranh canh bao `act`). */
async function renderSidebar() {
  const result = render(
    <Sidebar
      openConversationId={null}
      onSelect={vi.fn()}
      onNewChat={vi.fn()}
      onOpenConversationDeleted={vi.fn()}
    />,
  );
  await screen.findByText(t("sidebar.empty"));
  return result;
}

function toggle(): void {
  act(() => {
    toggleSidebar();
  });
}

/** Than cua khoi `@media <query> { ... }` trong `theme.css`, dem ngoac cho dung. */
function mediaBlock(css: string, query: string): string | null {
  const start = css.indexOf(`@media ${query}`);
  if (start < 0) {
    return null;
  }
  let depth = 0;
  const open = css.indexOf("{", start);
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === "{") {
      depth += 1;
    } else if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        return css.slice(open + 1, i);
      }
    }
  }
  return null;
}

/**
 * Moi token thoi luong khai trong `@theme`, kem gia tri: `[ten, gia tri]`.
 * Bi danh (`var(--...)`) bi bo qua — chung di theo token goc.
 */
function durationTokens(css: string): [string, string][] {
  const theme = css.slice(css.indexOf("@theme"));
  return [...theme.matchAll(/(--duration-\w+):\s*([^;]+);/g)]
    .map((m): [string, string] => [m[1], m[2].trim()])
    .filter(([, value]) => !value.startsWith("var("))
    .filter(([name], i, all) => all.findIndex(([other]) => other === name) === i);
}

/**
 * Dat `--duration-normal` len `:root` bang DUNG gia tri cua `@theme` — jsdom
 * khong nap CSS, nen khong co dong nay thi token rong va sidebar go ngay vi
 * ly do sai (token rong) chu khong vi `matchMedia`.
 */
function applyNormalToken(): void {
  const found = durationTokens(themeCss).find(([name]) => name === "--duration-normal");
  expect(found, "theme.css thieu --duration-normal").toBeDefined();
  document.documentElement.style.setProperty("--duration-normal", found?.[1] ?? "");
}

beforeEach(() => {
  localStorage.clear();
  resetSidebarOpenForTest();
  vi.mocked(api.danhSachHoiThoai).mockResolvedValue({ items: [], next_cursor: null });
});

afterEach(() => {
  vi.useRealTimers();
  document.documentElement.style.removeProperty("--duration-normal");
});

describe("Sidebar — prefers-reduced-motion", () => {
  it("reduce ⇒ dat `data-motion=\"none\"`, bo `motion-sidebar`, dong la go ngay; theme.css TAT han", async () => {
    stubMatchMedia(true);
    // Token van mang gia tri that: phai la matchMedia, khong phai token rong,
    // lam no go ngay.
    applyNormalToken();
    expect(readDurationMs("--duration-normal")).toBeGreaterThan(0);

    const { container } = await renderSidebar();
    const region = container.firstElementChild as HTMLElement;

    expect(region).toHaveAttribute("data-motion", "none");
    expect(region).not.toHaveClass("motion-sidebar");

    toggle();
    expect(container).toBeEmptyDOMElement();

    // Nua CSS cua loi hua — xoa khoi @media thi dong nay do.
    const block = mediaBlock(themeCss, REDUCED_MOTION_QUERY);
    expect(block, `theme.css thieu @media ${REDUCED_MOTION_QUERY}`).not.toBeNull();
    const body = block ?? "";
    for (const property of ["animation", "transition"]) {
      expect(body).toMatch(new RegExp(`${property}\\s*:\\s*none\\s*!important`));
      // "Tat", khong phai "giam con mot nua": khong con thoi luong duong nao.
      expect(body).not.toMatch(new RegExp(`${property}-duration\\s*:\\s*[1-9]`));
    }
    // MOI token thoi luong ve 0 — ma JS doc token de hen gio cung khong cho.
    const tokens = durationTokens(themeCss);
    expect(tokens.length).toBeGreaterThan(0);
    for (const [name] of tokens) {
      expect(body, `${name} chua ve 0`).toMatch(new RegExp(`${name}\\s*:\\s*0(m?s)?\\s*;`));
    }
  });

  it("khong reduce ⇒ KHONG dat `data-motion`, co `motion-sidebar`, dong cho het token roi moi go", async () => {
    stubMatchMedia(false);
    applyNormalToken();
    const exitMs = readDurationMs("--duration-normal");
    expect(exitMs).toBeGreaterThan(0);

    const { container } = await renderSidebar();
    // Bat dong ho gia SAU luot tai dau, de `findByText` con chay bang dong ho that.
    vi.useFakeTimers();
    const region = container.firstElementChild as HTMLElement;

    expect(region).not.toHaveAttribute("data-motion");
    expect(region).toHaveClass("motion-sidebar");
    expect(region).toHaveAttribute("data-state", "open");

    toggle();
    // Van trong DOM de chieu rong thu ve 0, va khong bam Tab vao duoc.
    expect(region).toHaveAttribute("data-state", "closed");
    expect(region).toHaveAttribute("inert");
    expect(container).not.toBeEmptyDOMElement();

    // Mot tich truoc han: van con. Dung han: da go.
    act(() => {
      vi.advanceTimersByTime(exitMs - 1);
    });
    expect(container).not.toBeEmptyDOMElement();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(container).toBeEmptyDOMElement();
  });
});
