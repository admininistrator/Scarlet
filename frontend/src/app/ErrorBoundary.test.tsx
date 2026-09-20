/**
 * Error boundary — DoD dong 2 cua T-3.1a.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  THU DUOC DO O DAY LA "KHONG PHAI MAN TRANG"                           ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Mot ngoai le luc render khong bi bat lam React thao SACH cay va de lai mot
 * `<div id="root">` rong. Trieu chung tren trinh duyet la mot trang trang —
 * khong mot dong chu, khong mot dau hieu nao noi rang co loi — nen no doc y
 * het "mang cham" hoac "app chua tai xong".
 *
 * Hai ca, vi co HAI nguoi bat (xem `pages/ServerErrorPage.tsx`):
 *  - ca 1 do class `ErrorBoundary`, thu boc ngoai `RouterProvider`;
 *  - ca 2 do `errorElement` cua BANG ROUTE THAT, bang cach lam mot man hinh
 *    that (`ChatScreen`) nem ngay luc render.
 *
 * Ca 2 cham vao bang route cua san pham chu khong mot bang dung rieng cho
 * test: mot `errorElement` quen gan la mot loi khong bao gio lo dien cho toi
 * ngay co su co, va no phai do duoc tren chinh cau hinh se chay that.
 */

import { render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", async (importOriginal) => {
  const that = await importOriginal<typeof import("../lib/api")>();
  return { ...that, api: { ...that.api, toiLaAi: vi.fn(), danhSachModel: vi.fn() } };
});

vi.mock("../components/chat/ChatScreen", () => ({
  ChatScreen: () => {
    throw new Error("man chat no tung");
  },
}));

import { api } from "../lib/api";
import { ErrorBoundary } from "./ErrorBoundary";
import { PATHS } from "./paths";
import { routes } from "./routes";

function Bum(): never {
  throw new Error("component nay luon nem");
}

beforeEach(() => {
  // React ghi nguyen ca stack ra console moi lan mot boundary bat duoc loi.
  // Day la hanh vi dung cua React, nhung o day no lam ban output cua ca bo
  // test bang mot stack cua mot loi DUOC MONG DOI.
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(api.toiLaAi).mockResolvedValue(null as never);
  vi.mocked(api.danhSachModel).mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("component nem loi luc render -> trang 500, khong phai man trang", () => {
    const { container } = render(
      <ErrorBoundary>
        <Bum />
      </ErrorBoundary>,
    );

    expect(screen.getByText("500")).toBeInTheDocument();
    expect(screen.getByText("Giao diện gặp lỗi")).toBeInTheDocument();
    expect(screen.getByText("component nay luon nem")).toBeInTheDocument();
    expect(container).not.toBeEmptyDOMElement();
  });

  it("khong co loi thi tre con di qua nguyen ven", () => {
    render(
      <ErrorBoundary>
        <p>noi dung binh thuong</p>
      </ErrorBoundary>,
    );

    expect(screen.getByText("noi dung binh thuong")).toBeInTheDocument();
    expect(screen.queryByText("500")).toBeNull();
  });

  it("mot man hinh THAT nem loi -> `errorElement` cua bang route ra trang 500", async () => {
    const router = createMemoryRouter(routes, { initialEntries: [PATHS.home] });

    const { container } = render(<RouterProvider router={router} />);

    expect(await screen.findByText("500")).toBeInTheDocument();
    expect(screen.getByText("man chat no tung")).toBeInTheDocument();
    expect(container).not.toBeEmptyDOMElement();
  });

  it("nut tren trang 500 tai lai trang", async () => {
    const router = createMemoryRouter(routes, { initialEntries: [PATHS.home] });
    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("button", { name: "Tải lại trang" })).toBeInTheDocument();
  });
});
