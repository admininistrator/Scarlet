/**
 * Man `/admin` (T-3.12) — cac hanh vi ma DoD va Cam bay cua task goi ten.
 *
 *   - Nguoi dung: hai cot NQ-66 hien `0`/`0.000000` chu khong trong; bat skill
 *     gui ca ban ghi de; cau "trong vong N giay" dung N cua SERVER (45, khong
 *     phai 60 — mot so go tay trong `vi.json` se do o day).
 *   - He thong: ly do rong van noi duoc dieu gi do (B-193); `503` cua chinh API
 *     quan tri (Redis chet, C21) ⇒ roi ve `/health/deep` (B-190/Cam bay ①).
 *   - Nhat ky: "voi ai" bang chu, khong UUID (B-191).
 *   - Chi phi: tong la chuoi cua server, khong co phep cong nao.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Outlet, RouterProvider, createMemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      adminListUsers: vi.fn(),
      adminChangeStatus: vi.fn(),
      adminCosts: vi.fn(),
      adminUpdateUser: vi.fn(),
      adminListTiers: vi.fn(),
      adminSystem: vi.fn(),
      adminAuditLogs: vi.fn(),
      healthDeep: vi.fn(),
    },
  };
});

import type { SessionState } from "../../features/auth/useSessionState";
import {
  ApiError,
  api,
  type AdminUserListItem,
  type AuditEntry,
  type CostsOut,
  type SystemStatus,
  type TierList,
} from "../../lib/api";
import { AdminScreen } from "./AdminScreen";

const UUID = "4e1dd956-7a41-4c1e-9b1f-0c6a2b9f1d2e";
const ADMIN_ID = "11111111-1111-4111-8111-111111111111";

const SESSION = {
  user: {
    id: ADMIN_ID,
    email: "admin@scarlet.test",
    display_name: null,
    status: "active",
    role: "admin",
    tier_name: "trusted",
    default_model: null,
  },
  profile: null,
  profileReadAt: null,
  loading: false,
  locked: false,
  error: null,
} as unknown as SessionState;

const TIERS: TierList = {
  tiers: [
    {
      name: "free",
      limit_5h_usd: "0.5000",
      limit_7d_usd: "3.0000",
      can_execute_skills: false,
      can_use_web: false,
      web_searches_per_day: 0,
      max_upload_mb: 5,
      max_attachments: 3,
      allowed_model_tags: [],
      is_default: true,
    },
  ],
  // KHONG phai 60: cau tren man hinh phai doc tu day.
  limits_cache_ttl_s: 45,
};

function userRow(p: Partial<AdminUserListItem> = {}): AdminUserListItem {
  return {
    id: UUID,
    email: "moi@scarlet.test",
    display_name: null,
    status: "active",
    role: "user",
    tier_name: "free",
    limit_override_json: null,
    email_verified_at: null,
    approved_at: null,
    approved_by: null,
    last_login_at: null,
    created_at: "2026-09-22T01:02:03Z",
    conversation_count: 0,
    spend_7d_usd: "0.000000",
    ...p,
  };
}

function renderAt(path: string) {
  const router = createMemoryRouter(
    [{ element: <Outlet context={SESSION} />, children: [{ path: "/admin", element: <AdminScreen /> }] }],
    { initialEntries: [path] },
  );
  return render(<RouterProvider router={router} />);
}

beforeEach(() => {
  vi.mocked(api.adminListUsers).mockReset();
  vi.mocked(api.adminListUsers).mockImplementation(async (status) =>
    status === "pending_approval"
      ? { users: [userRow({ status: "pending_approval" })] }
      : { users: [userRow()] },
  );
  vi.mocked(api.adminListTiers).mockResolvedValue(TIERS);
  vi.mocked(api.adminUpdateUser).mockReset();
  vi.mocked(api.adminUpdateUser).mockResolvedValue(userRow());
  vi.mocked(api.adminChangeStatus).mockReset();
  vi.mocked(api.healthDeep).mockReset();
});

describe("Duyet nguoi dung", () => {
  it("nut dieu huong dem don cho duyet; bam Duyet goi dung endpoint roi DOC LAI danh sach", async () => {
    const nd = userEvent.setup();
    vi.mocked(api.adminChangeStatus).mockResolvedValue(userRow());
    renderAt("/admin");

    expect(await screen.findByRole("heading", { name: "Chờ duyệt" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Duyệt người dùng\s*1/ })).toBeInTheDocument();
    const before = vi.mocked(api.adminListUsers).mock.calls.length;

    await nd.click(screen.getByRole("button", { name: "Duyệt" }));

    expect(api.adminChangeStatus).toHaveBeenCalledWith(UUID, "approve");
    await waitFor(() => {
      expect(vi.mocked(api.adminListUsers).mock.calls.length).toBe(before + 1);
    });
  });
});

describe("Nguoi dung", () => {
  it("NQ-66: nguoi chua co hoi thoai hien 0 va 0.000000, khong o trong", async () => {
    renderAt("/admin?screen=users");

    const table = await screen.findByRole("region", { name: "Người dùng" });
    const row = within(table).getByRole("row", { name: /moi@scarlet\.test/ });
    expect(within(row).getByText("0.000000")).toBeInTheDocument();
    expect(within(row).getByText("0")).toBeInTheDocument();
    expect(table.textContent).not.toContain(UUID);
  });

  it("bat skill ⇒ PATCH ca ban ghi de; cau hieu luc dung TTL cua SERVER; hang mang nhan cho", async () => {
    const nd = userEvent.setup();
    renderAt("/admin?screen=users");

    await nd.click(await screen.findByRole("switch", { name: /Chạy skill — moi@scarlet\.test/ }));

    expect(api.adminUpdateUser).toHaveBeenCalledWith(UUID, {
      limit_override: { can_execute_skills: true },
    });
    const notice = await screen.findByText(/Có hiệu lực trong vòng/);
    expect(notice.textContent).toMatch(/Có hiệu lực trong vòng 45 giây\./);
    expect(screen.queryByText(/60 giây/)).toBeNull();
    expect(await screen.findByText("Chờ hiệu lực")).toBeInTheDocument();
    // Cam bay ②: khong bao gio noi "da ap dung".
    expect(document.body.textContent).not.toMatch(/đã áp dụng/i);
  });

  it("tat ve dung gia tri tier ⇒ go khoa, ban ghi de rong ⇒ null", async () => {
    const nd = userEvent.setup();
    vi.mocked(api.adminListUsers).mockResolvedValue({
      users: [userRow({ limit_override_json: { can_execute_skills: true } })],
    });
    renderAt("/admin?screen=users");

    await nd.click(await screen.findByRole("switch", { name: /Chạy skill/ }));

    expect(api.adminUpdateUser).toHaveBeenCalledWith(UUID, { limit_override: null });
  });

  it("KHONG ve cong tac `is_default` (Cam bay ③ / B-152)", async () => {
    renderAt("/admin?screen=users");

    await screen.findByRole("region", { name: "Hạn mức theo tier" });
    expect(screen.queryByText(/mặc định/i)).toBeNull();
  });
});

const SYSTEM: SystemStatus = {
  version: "0.9.4",
  queue_depth: null,
  streams_dang_chay: 2,
  health: {
    postgres: { ok: true, latency_ms: 4, error: null },
    redis: { ok: false, latency_ms: 2000, error: "" },
  },
  health_checked_at: "2026-09-23T07:32:10Z",
};

describe("He thong", () => {
  it("B-193: ly do rong van noi duoc dieu gi do; hang doi `null` KHONG hien 0", async () => {
    vi.mocked(api.adminSystem).mockResolvedValue(SYSTEM);
    renderAt("/admin?screen=system");

    expect(await screen.findByText(/Máy chủ không gửi lý do \(chuỗi rỗng\)/)).toBeInTheDocument();
    expect(screen.getByText("Không đo được")).toBeInTheDocument();
    expect(screen.getAllByText(/Kiểm lúc/).length).toBe(2);
  });

  it("Cam bay ① / B-190: API quan tri tra 503 ⇒ roi ve /health/deep va hien ly do cua redis", async () => {
    vi.mocked(api.adminSystem).mockRejectedValue(
      new ApiError(503, "SERVICE_UNAVAILABLE", "khong hoi duoc redis"),
    );
    vi.mocked(api.healthDeep).mockResolvedValue({
      status: "down",
      checks: { redis: { ok: false, latency_ms: 2001, error: "TimeoutError" } },
    });
    renderAt("/admin?screen=system");

    expect(await screen.findByText("TimeoutError")).toBeInTheDocument();
    expect(screen.getByText("API quản trị không trả lời")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("SERVICE_UNAVAILABLE");
  });

  it("loi 403 thi KHONG roi ve /health/deep — do la tu choi, khong phai su co", async () => {
    vi.mocked(api.adminSystem).mockRejectedValue(new ApiError(403, "ADMIN_REQUIRED", "x"));
    renderAt("/admin?screen=system");

    expect(await screen.findByRole("alert")).toHaveTextContent("ADMIN_REQUIRED");
    expect(api.healthDeep).not.toHaveBeenCalled();
  });
});

describe("Nhat ky", () => {
  const auditRow = (p: Partial<AuditEntry>): AuditEntry => ({
    id: 1,
    created_at: "2026-09-22T07:32:00Z",
    actor_id: ADMIN_ID,
    actor_email: "admin@scarlet.test",
    actor_display_name: null,
    action: "user.approve",
    target_type: "users",
    target_id: UUID,
    target_email: "moi@scarlet.test",
    target_display_name: null,
    details: { from: "pending_approval", to: "active" },
    ip: null,
    ...p,
  });

  it("DoD dong 3 / B-191: ai va voi ai bang chu, khong UUID; nguoi da xoa chi con 8 ky tu", async () => {
    vi.mocked(api.adminAuditLogs).mockResolvedValue({
      items: [auditRow({}), auditRow({ id: 2, target_email: null })],
      next_cursor: null,
    });
    renderAt("/admin?screen=audit");

    const table = await screen.findByRole("region", { name: "Nhật ký quản trị" });
    expect(within(table).getAllByText("admin@scarlet.test").length).toBe(2);
    expect(within(table).getByText("moi@scarlet.test")).toBeInTheDocument();
    expect(within(table).getByText("4e1dd956")).toBeInTheDocument();
    expect(within(table).getByText("Tài khoản đã xoá")).toBeInTheDocument();
    expect(table.textContent).not.toContain(UUID);
  });
});

describe("Chi phi", () => {
  it("tong la chuoi cua SERVER (khong cong hai cot); nhan 'Cao nhat' la chuoi goc", async () => {
    const zero = { cost_usd: "0", prompt_tokens: 0, completion_tokens: 0, events: 0 };
    const report: CostsOut = {
      since: "2026-09-16T00:00:00Z",
      until: "2026-09-23T00:00:00Z",
      key_source: "system",
      totals: {
        metered: { cost_usd: "0.3", prompt_tokens: 10, completion_tokens: 20, events: 2 },
        unmetered: { cost_usd: "0.2", prompt_tokens: 10, completion_tokens: 20, events: 1 },
      },
      by_day: [
        {
          key: "2026-09-22",
          label: null,
          metered: { cost_usd: "0.3", prompt_tokens: 10, completion_tokens: 20, events: 2 },
          unmetered: { cost_usd: "0.2", prompt_tokens: 10, completion_tokens: 20, events: 1 },
        },
      ],
      by_user: [],
      by_model: [],
      by_key_source: [{ key: "byok", label: null, metered: zero, unmetered: zero }],
    };
    vi.mocked(api.adminCosts).mockResolvedValue(report);
    renderAt("/admin?screen=cost");

    expect(await screen.findByText("Metered trong kỳ (USD)")).toBeInTheDocument();
    expect(screen.getAllByText("0.300000").length).toBeGreaterThan(0);
    expect(screen.getAllByText("0.200000").length).toBeGreaterThan(0);
    // 0.3 + 0.2 KHONG duoc xuat hien o bat cu dau.
    expect(screen.queryByText("0.500000")).toBeNull();
    // Mac dinh B-178: loc tien he thong, 7 ngay.
    expect(vi.mocked(api.adminCosts).mock.calls[0][0]).toBe("system");
    // Truc theo nguon KHONG bi loc — van ke dong BYOK.
    expect(screen.getByRole("region", { name: /Theo nguồn tiền/ })).toHaveTextContent("BYOK");
  });
});
