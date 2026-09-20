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
  const that = await importOriginal<typeof import("../lib/api")>();
  return {
    ...that,
    api: {
      ...that.api,
      toiLaAi: vi.fn(),
      danhSachModel: vi.fn(),
      quanTriDanhSachUser: vi.fn(),
      quanTriChiPhi: vi.fn(),
    },
  };
});

import { api, type ChiPhiRa, type NguoiDungRa } from "../lib/api";
import { PATHS } from "./paths";
import { routes } from "./routes";

const ADMIN: NguoiDungRa = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "admin@scarlet.test",
  display_name: null,
  status: "active",
  role: "admin",
  tier_name: "trusted",
};

const KHONG_TIEN = { cost_usd: "0", prompt_tokens: 0, completion_tokens: 0, events: 0 };
const CHI_PHI_RONG: ChiPhiRa = {
  since: "2026-09-13T00:00:00Z",
  until: "2026-09-20T00:00:00Z",
  key_source: "system",
  totals: { metered: KHONG_TIEN, unmetered: KHONG_TIEN },
  by_day: [],
  by_user: [],
  by_model: [],
  by_key_source: [],
};

function moTai(duong: string) {
  const router = createMemoryRouter(routes, { initialEntries: [duong] });
  return render(<RouterProvider router={router} />);
}

beforeEach(() => {
  vi.mocked(api.toiLaAi).mockResolvedValue(ADMIN);
  vi.mocked(api.danhSachModel).mockResolvedValue([]);
  vi.mocked(api.quanTriDanhSachUser).mockResolvedValue({ users: [] });
  vi.mocked(api.quanTriChiPhi).mockResolvedValue(CHI_PHI_RONG);
});

describe("bang route", () => {
  it("/abcxyz ra trang 404, KHONG ra man chat (B-187)", async () => {
    moTai("/abcxyz");

    expect(await screen.findByText("404")).toBeInTheDocument();
    expect(screen.getByText("Không tìm thấy trang")).toBeInTheDocument();
    // Nua quan trong cua B-187: truoc T-3.1a, dung duong nay hien man chat.
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
  });

  it("/dang-nhap ra form dang nhap", async () => {
    moTai(PATHS.login);

    expect(await screen.findByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Mật khẩu")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Đăng nhập" })).toBeInTheDocument();
  });

  it("/admin ra man quan tri", async () => {
    moTai(PATHS.admin);

    expect(await screen.findByRole("heading", { name: "Quản trị" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nạp lại catalog" })).toBeInTheDocument();
  });

  it("/ ra man chat", async () => {
    moTai(PATHS.home);

    expect(await screen.findByRole("button", { name: "Hội thoại mới" })).toBeInTheDocument();
  });

  it("trang 404 co duong ve / va di duoc bang router, khong nap lai trang", async () => {
    const nguoiDung = userEvent.setup();
    moTai("/abcxyz");

    await nguoiDung.click(await screen.findByRole("link", { name: "Về trang chủ" }));

    expect(await screen.findByRole("button", { name: "Hội thoại mới" })).toBeInTheDocument();
    expect(screen.queryByText("404")).toBeNull();
  });

  // T-3.1b thay nam trong sau cho trong nay bang man hinh that. `/cai-dat`
  // con lai mot minh — chu no la T-3.12.
  it.each([
    [PATHS.settings, "Cài đặt"],
    [PATHS.register, "Đăng ký"],
    [PATHS.forgotPassword, "Quên mật khẩu"],
    [PATHS.resetPassword, "Đặt lại mật khẩu"],
    [PATHS.verifyEmail, "Email chưa được xác thực"],
    [PATHS.pendingApproval, "Đang chờ quản trị duyệt"],
  ])("%s ra dung man hinh cua no, khong phai 404", async (duong, ten) => {
    moTai(duong);

    expect(await screen.findByRole("heading", { name: ten })).toBeInTheDocument();
    expect(screen.queryByText("404")).toBeNull();
  });

  it("chi con /cai-dat la trang tam — nam duong auth da co man hinh that", async () => {
    // Phep do cua *"T-3.1b chi phai dien"*: neu mot `element` bi bo quen thi
    // `PlaceholderPage` van ve mot man hinh co ten va moi khang dinh ben tren
    // van xanh. Cau "Man hinh nay chua duoc dung" la thu phan biet duoc.
    moTai(PATHS.register);
    expect(await screen.findByRole("heading", { name: "Đăng ký" })).toBeInTheDocument();
    expect(screen.queryByText("Màn hình này chưa được dựng.")).toBeNull();
  });

  it("nguoi khong phai admin bi day khoi /admin ve man chat", async () => {
    vi.mocked(api.toiLaAi).mockResolvedValue({ ...ADMIN, role: "user" });

    moTai(PATHS.admin);

    expect(await screen.findByRole("button", { name: "Hội thoại mới" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Quản trị" })).toBeNull();
  });

  it("nguoi chua dang nhap bi day khoi /admin toi /dang-nhap", async () => {
    vi.mocked(api.toiLaAi).mockRejectedValue(new Error("401"));

    moTai(PATHS.admin);

    expect(await screen.findByLabelText("Mật khẩu")).toBeInTheDocument();
  });
});
