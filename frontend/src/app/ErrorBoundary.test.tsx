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
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, api: { ...actual.api, me: vi.fn(), listModels: vi.fn() } };
});

vi.mock("../components/chat/ChatScreen", () => ({
  ChatScreen: () => {
    throw new Error("man chat no tung");
  },
}));

import { api, type ProfileOut } from "../lib/api";
import { ErrorBoundary } from "./ErrorBoundary";
import { PATHS } from "./paths";
import { routes } from "./routes";

function Boom(): never {
  throw new Error("component nay luon nem");
}

/**
 * Mot phien THAT, `active` — dieu kien de `/` render toi `ChatScreen`.
 *
 * Toi T-3.1b, `me` o day tra `null` va ca 2 van chay: `StatusGate` cho
 * nguoi chua dang nhap vao thang man chat (nhanh danh tinh tam cua Phase 1).
 * T-3.1c chan duong do, nen mot `null` se dung lai o `/dang-nhap` va man
 * hinh "no tung" khong bao gio duoc render — tuc ca 2 se xanh vi mot ly do
 * khac han ly do no ra doi.
 */
const USER: ProfileOut = {
  id: "22222222-2222-4222-8222-222222222222",
  email: "nguoi-dung@scarlet.test",
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "free",
  // Ba truong cua `ProfileOut` — chi `GET /auth/me` tra chung (B-213, T-3.4).
  default_model: null,
  quota: null,
  message_max_chars: 24000,
  quota_warn_remaining_pct: 20,
  last_login_at: null,
  limits_cache_ttl_s: 60,
  stream_ttl_s: 3600,
  display_name_max_chars: 64,
  avatar_color: null,
  reasoning_prefs: {},
  max_upload_mb: 10,
  max_attachments: 5,
  allowed_upload_mime: ["image/png", "image/jpeg", "application/pdf", "text/plain"],
};

beforeEach(() => {
  // React ghi nguyen ca stack ra console moi lan mot boundary bat duoc loi.
  // Day la hanh vi dung cua React, nhung o day no lam ban output cua ca bo
  // test bang mot stack cua mot loi DUOC MONG DOI.
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(api.me).mockResolvedValue(USER);
  vi.mocked(api.listModels).mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("component nem loi luc render -> trang 500, khong phai man trang", () => {
    const { container } = render(
      <ErrorBoundary>
        <Boom />
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
