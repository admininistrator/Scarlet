/**
 * Bang route — DoD dong 1 cua T-3.1a, va phep do dong B-187.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  VI SAO PHEP DO NAY KHONG THE LA MOT LENH `curl`                       ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Cam bay ① cua task, do duoc ngay 2026-09-20:
 * `curl -sk -o /dev/null -w '%{http_code}' https://localhost/abcxyz` tra
 * **200**, than la `index.html` — Vite tra trang goc cho MOI duong va Nginx
 * `location /` proxy thang. Ma HTTP o do do Nginx+Vite chu khong do router,
 * nen mot DoD viet bang `curl` se xanh KE CA khi B-187 con nguyen.
 *
 * Phep do that phai chay router. `createMemoryRouter` nap dung mang `routes`
 * ma `App.tsx` dung cho san pham (xem docstring `routes.tsx`), chi thay lop
 * lich su trinh duyet bang mot lich su trong bo nho.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      listModels: vi.fn(),
      adminListUsers: vi.fn(),
      adminCosts: vi.fn(),
      listProviderKeys: vi.fn(),
    },
  };
});

import { api, type CostsOut, type ProfileOut } from "../lib/api";
import { PATHS } from "./paths";
import { routes } from "./routes";

const ADMIN: ProfileOut = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "admin@scarlet.test",
  display_name: null,
  status: "active",
  role: "admin",
  tier_name: "trusted",
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
};

const ZERO_AMOUNT = { cost_usd: "0", prompt_tokens: 0, completion_tokens: 0, events: 0 };
const EMPTY_COSTS: CostsOut = {
  since: "2026-09-13T00:00:00Z",
  until: "2026-09-20T00:00:00Z",
  key_source: "system",
  totals: {
    metered: ZERO_AMOUNT,
    unmetered: ZERO_AMOUNT,
    by_purpose: {
      chat: { metered: ZERO_AMOUNT, unmetered: ZERO_AMOUNT },
      title: { metered: ZERO_AMOUNT, unmetered: ZERO_AMOUNT },
    },
    title_cost_usd: "0",
  },
  by_day: [],
  by_user: [],
  by_model: [],
  by_key_source: [],
};

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

beforeEach(() => {
  vi.mocked(api.me).mockResolvedValue(ADMIN);
  vi.mocked(api.listModels).mockResolvedValue([]);
  vi.mocked(api.adminListUsers).mockResolvedValue({ users: [] });
  vi.mocked(api.adminCosts).mockResolvedValue(EMPTY_COSTS);
  vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [], byok_providers: [] });
});

describe("bang route", () => {
  it("/abcxyz ra trang 404, KHONG ra man chat (B-187)", async () => {
    renderAt("/abcxyz");

    expect(await screen.findByText("404")).toBeInTheDocument();
    expect(screen.getByText("Không tìm thấy trang")).toBeInTheDocument();
    // Nua quan trong cua B-187: truoc T-3.1a, dung duong nay hien man chat.
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
  });

  it("/dang-nhap ra form dang nhap", async () => {
    renderAt(PATHS.login);

    expect(await screen.findByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Mật khẩu")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Đăng nhập" })).toBeInTheDocument();
  });

  it("/admin ra man quan tri", async () => {
    renderAt(PATHS.admin);

    // T-3.12 — sau muc dieu huong cua ban T-HD7; man mac dinh la "Duyet".
    const nav = await screen.findByRole("navigation", { name: "Mục quản trị" });
    expect(nav).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Chờ duyệt" })).toBeInTheDocument();
    for (const item of ["Duyệt người dùng", "Người dùng", "Chi phí", "Model", "Hệ thống", "Nhật ký"]) {
      expect(screen.getByRole("button", { name: item })).toBeInTheDocument();
    }
  });

  it("/ ra man chat", async () => {
    renderAt(PATHS.home);

    expect(await screen.findByRole("textbox", { name: "Nhập tin nhắn cho Scarlet" })).toBeInTheDocument();
  });

  it("trang 404 co duong ve / va di duoc bang router, khong nap lai trang", async () => {
    const user = userEvent.setup();
    renderAt("/abcxyz");

    await user.click(await screen.findByRole("link", { name: "Về trang chủ" }));

    expect(await screen.findByRole("textbox", { name: "Nhập tin nhắn cho Scarlet" })).toBeInTheDocument();
    expect(screen.queryByText("404")).toBeNull();
  });

  // T-3.1b thay nam trong sau cho trong nay bang man hinh that; T-3.12 thay
  // not `/cai-dat`.
  it.each([
    [PATHS.settings, "Cài đặt"],
    [PATHS.register, "Đăng ký"],
    [PATHS.forgotPassword, "Quên mật khẩu"],
    [PATHS.resetPassword, "Đặt mật khẩu mới"],
    [PATHS.verifyEmail, "Email chưa được xác thực"],
    [PATHS.pendingApproval, "Đang chờ duyệt"],
  ])("%s ra dung man hinh cua no, khong phai 404", async (path, name) => {
    renderAt(path);

    expect(await screen.findByRole("heading", { name: name })).toBeInTheDocument();
    expect(screen.queryByText("404")).toBeNull();
  });

  it("/cai-dat (>= 1024 px) chuyen sang tab Tai khoan; nam tab la nam lien ket (T-S.11)", async () => {
    // Truoc T-3.12 `/cai-dat` la `PlaceholderPage` — mot man co TEN nen ca
    // `it.each` ben tren van xanh. T-S.11: `/cai-dat` la mac dinh cua tab Tai
    // khoan (jsdom = desktop, `matchMedia` khong khop), va cot tab co du nam.
    renderAt(PATHS.settings);

    const nav = await screen.findByRole("navigation", { name: "Mục cài đặt" });
    expect(screen.getByRole("link", { name: "Tài khoản" })).toHaveAttribute("aria-current", "page");
    expect(
      [...nav.querySelectorAll("a")].map((a) => [a.textContent, a.getAttribute("href")]),
    ).toEqual([
      ["Tài khoản", PATHS.settingsAccount],
      ["Giao diện", PATHS.settingsAppearance],
      ["Model", PATHS.settingsModel],
      ["BYOK", PATHS.settingsByok],
      ["Mức sử dụng", PATHS.settingsUsage],
    ]);
  });

  it("chua dang nhap thi /cai-dat day toi /dang-nhap", async () => {
    vi.mocked(api.me).mockRejectedValue(new Error("401"));

    renderAt(PATHS.settings);

    expect(await screen.findByLabelText("Mật khẩu")).toBeInTheDocument();
  });

  it("B-216 (de mo): `pending_approval` VAO duoc /cai-dat, khong bi day ve /cho-duyet", async () => {
    vi.mocked(api.me).mockResolvedValue({ ...ADMIN, role: "user", status: "pending_approval" });

    renderAt(PATHS.settingsByok);

    expect(await screen.findByRole("heading", { name: "Cài đặt" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "BYOK" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("heading", { name: "Đang chờ duyệt" })).toBeNull();
  });

  it("nguoi khong phai admin bi day khoi /admin ve man chat", async () => {
    vi.mocked(api.me).mockResolvedValue({ ...ADMIN, role: "user" });

    renderAt(PATHS.admin);

    expect(await screen.findByRole("textbox", { name: "Nhập tin nhắn cho Scarlet" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Mục quản trị" })).toBeNull();
  });

  it("nguoi chua dang nhap bi day khoi /admin toi /dang-nhap", async () => {
    vi.mocked(api.me).mockRejectedValue(new Error("401"));

    renderAt(PATHS.admin);

    expect(await screen.findByLabelText("Mật khẩu")).toBeInTheDocument();
  });
});
