/**
 * `ThemeToggle` — B-199.
 *
 * Mot test COMPONENT, khong phai mot test logic thuan: muc dich cua no la
 * chung minh ca chuoi `jsdom` + `@testing-library/react` + `jest-dom` chay
 * that. Mot bo chay test chi co test cua `lib/*.ts` se xanh ma khong ai biet
 * `render()` co hoat dong hay khong cho toi khi T-3.2 can toi no.
 *
 * Ca cuoi cung ("localStorage bi chan") canh dung doan `try/catch` ma
 * `ThemeToggle.tsx` viet cho che do rieng tu — thu chay duoc tren may dev ma
 * hong tren may nguoi dung, tuc thu chi test moi bat duoc.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "./ThemeToggle";

beforeEach(() => {
  document.documentElement.removeAttribute("data-theme");
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ThemeToggle", () => {
  it("mac dinh la sang, va nut moi sang che do toi", () => {
    render(<ThemeToggle />);

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("bam mot lan thi doi sang toi va ghi localStorage", async () => {
    const nguoiDung = userEvent.setup();
    render(<ThemeToggle />);

    await nguoiDung.click(screen.getByRole("button"));

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("scarlet-theme")).toBe("dark");
  });

  it("bam hai lan thi ve cho cu", async () => {
    const nguoiDung = userEvent.setup();
    render(<ThemeToggle />);

    await nguoiDung.click(screen.getByRole("button"));
    await nguoiDung.click(screen.getByRole("button"));

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("scarlet-theme")).toBe("light");
  });

  it("doc trang thai ban dau tu `data-theme` co san", () => {
    document.documentElement.setAttribute("data-theme", "dark");

    render(<ThemeToggle />);

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("localStorage bi chan (che do rieng tu) thi van doi duoc giao dien", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("bi chan", "SecurityError");
    });
    const nguoiDung = userEvent.setup();
    render(<ThemeToggle />);

    await nguoiDung.click(screen.getByRole("button"));

    // Giao dien van doi — day la toan bo y nghia cua `try/catch` trong component.
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });
});
