/**
 * `ThemeToggle` — B-199, mo rong o T-3.2.
 *
 * Mot test COMPONENT, khong phai mot test logic thuan: muc dich cua no la
 * chung minh ca chuoi `jsdom` + `@testing-library/react` + `jest-dom` chay
 * that. Mot bo chay test chi co test cua `lib/*.ts` se xanh ma khong ai biet
 * `render()` co hoat dong hay khong cho toi khi T-3.2 can toi no.
 *
 * Ca "localStorage bi chan" canh dung doan `try/catch` ma `ThemeToggle.tsx`
 * viet cho che do rieng tu — thu chay duoc tren may dev ma hong tren may
 * nguoi dung, tuc thu chi test moi bat duoc.
 *
 * ── Bon ca moi cua T-3.2 ──────────────────────────────────────────────────
 *
 * T-3.2 chuyen "mac dinh theo he dieu hanh" tu doan script trong `index.html`
 * vao chinh component. Trong jsdom KHONG co `index.html`, nen bon ca duoi day
 * do dung phan vua chuyen — va neu ai do go `initialTheme()` ve lai kieu doc
 * thuoc tinh `data-theme`, chung do het mot luot.
 *
 * `window.matchMedia` khong ton tai trong jsdom, nen moi ca phai tu dung no
 * len bang `vi.stubGlobal`. Ca cuoi cung KHONG dung — do chinh la phep do cho
 * `?.` trong `systemTheme()`.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "./ThemeToggle";

/** Dung `window.matchMedia` gia tra `matches` cho dung truy van theme toi. */
function fakeOsTheme(prefersDark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: prefersDark && query === "(prefers-color-scheme: dark)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

beforeEach(() => {
  document.documentElement.removeAttribute("data-theme");
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ThemeToggle", () => {
  it("mac dinh la sang, va nut moi sang che do toi", () => {
    fakeOsTheme(false);

    render(<ThemeToggle />);

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("bam mot lan thi doi sang toi va ghi localStorage", async () => {
    fakeOsTheme(false);
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(screen.getByRole("button"));

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("scarlet-theme")).toBe("dark");
  });

  it("bam hai lan thi ve cho cu", async () => {
    fakeOsTheme(false);
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("button"));

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("scarlet-theme")).toBe("light");
  });

  it("localStorage bi chan (che do rieng tu) thi van doi duoc giao dien", async () => {
    fakeOsTheme(false);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("bi chan", "SecurityError");
    });
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(screen.getByRole("button"));

    // Giao dien van doi — day la toan bo y nghia cua `try/catch` trong component.
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  // ── T-3.2: mac dinh lan dau doc `prefers-color-scheme` ───────────────────

  it("chua ai bam gi + he dieu hanh dang toi => toi", () => {
    fakeOsTheme(true);

    render(<ThemeToggle />);

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("chua ai bam gi + he dieu hanh dang sang => sang", () => {
    fakeOsTheme(false);

    render(<ThemeToggle />);

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("lua chon da luu THANG he dieu hanh", () => {
    localStorage.setItem("scarlet-theme", "light");
    fakeOsTheme(true);

    render(<ThemeToggle />);

    // Nguoi dung da tu chon sang; he dieu hanh toi khong duoc lat nguoc lai.
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("KHONG doc thuoc tinh `data-theme` co san — no khong phai mot nguon", () => {
    // Doan script FOUC cua `index.html` dat thuoc tinh nay. Component phai tu
    // tinh lai tu localStorage + he dieu hanh, nen mot thuoc tinh mau thuan
    // voi ca hai nguon do bi ghi de chu khong duoc tin.
    document.documentElement.setAttribute("data-theme", "dark");
    fakeOsTheme(false);

    render(<ThemeToggle />);

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("khong co `window.matchMedia` (jsdom tran, WebView cu) thi roi ve sang", () => {
    vi.stubGlobal("matchMedia", undefined);

    render(<ThemeToggle />);

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
