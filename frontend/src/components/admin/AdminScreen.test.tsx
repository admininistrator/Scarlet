/**
 * Man `/admin` (T-3.12) — cac hanh vi ma DoD va Cam bay cua task goi ten.
 *
 *   - Nguoi dung: hai cot NQ-66 hien `0`/`0.000000` chu khong trong; bat skill
 *     gui ca ban ghi de; cau "trong vong N giay" dung N cua SERVER (45, khong
 *     phai 60 — mot so go tay trong `vi.json` se do o day).
 *   - He thong: ly do rong van noi duoc dieu gi do (B-193); `503` cua chinh API
 *     quan tri (Redis chet, C21) ⇒ roi ve `/health/deep` (B-190/Cam bay ①).
 *   - Nhat ky: "voi ai" bang chu, khong UUID (B-191).
 *   - Chi phi: tong la chuoi cua server, khong co phep cong nao; khoan "Dat
 *     ten" la `title_cost_usd` cua server, tach khoi hai cot (T-S.17).
 *   - Model: hang + "qua <duong>" cho duong an; hong ghi TEN duong (T-S.17).
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
      adminModels: vi.fn(),
      adminUpdateModel: vi.fn(),
      healthDeep: vi.fn(),
    },
  };
});

import type { SessionState } from "../../features/auth/useSessionState";
import {
  ApiError,
  api,
  type AdminModelListOut,
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
    const nd = userEvent.setup();
    renderAt("/admin?screen=users");

    // Ban v2 muc 1c: bang tier la TAB thu hai cua man Nguoi dung.
    await nd.click(await screen.findByRole("tab", { name: "Hạn mức theo tier" }));
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
  const zero = { cost_usd: "0", prompt_tokens: 0, completion_tokens: 0, events: 0 };
  const amount = (cost_usd: string, events = 1) => ({ cost_usd, prompt_tokens: 10, completion_tokens: 20, events });
  // Tong hai cot GOM ca dat ten (0.32 = 0.3 chat + 0.02 dat ten) — dung nghia backend.
  const split = {
    metered: amount("0.32", 3),
    unmetered: amount("0.2"),
    by_purpose: {
      chat: { metered: amount("0.3", 2), unmetered: amount("0.2") },
      title: { metered: amount("0.02"), unmetered: zero },
    },
    title_cost_usd: "0.02",
  };
  const report: CostsOut = {
    since: "2026-09-16T00:00:00Z",
    until: "2026-09-23T00:00:00Z",
    key_source: "system",
    totals: split,
    by_day: [{ key: "2026-09-22", label: null, ...split }],
    by_user: [],
    by_model: [],
    by_key_source: [
      { key: "system", label: null, ...split },
      {
        key: "byok",
        label: null,
        metered: zero,
        unmetered: zero,
        by_purpose: { chat: { metered: zero, unmetered: zero }, title: { metered: zero, unmetered: zero } },
        title_cost_usd: "0",
      },
    ],
  };

  it("tong la chuoi cua SERVER (khong cong hai cot); nhan 'Cao nhat' la chuoi goc", async () => {
    vi.mocked(api.adminCosts).mockResolvedValue(report);
    renderAt("/admin?screen=cost");

    expect(await screen.findByText("Metered trong kỳ (USD)")).toBeInTheDocument();
    expect(screen.getAllByText("0.300000").length).toBeGreaterThan(0);
    expect(screen.getAllByText("0.200000").length).toBeGreaterThan(0);
    // 0.3 + 0.2 KHONG duoc xuat hien o bat cu dau.
    expect(screen.queryByText("0.500000")).toBeNull();
    // Mac dinh B-178: loc tien he thong, 7 ngay.
    expect(vi.mocked(api.adminCosts).mock.calls[0][0]).toBe("system");
    // Truc theo nguon KHONG bi loc — van ke dong khoa rieng.
    expect(screen.getByRole("region", { name: "Theo nguồn" })).toHaveTextContent("Khoá riêng");
  });

  it("T-S.17: 'Dat ten' la `title_cost_usd` cua server, KHONG nam trong the/cot Metered", async () => {
    vi.mocked(api.adminCosts).mockResolvedValue(report);
    renderAt("/admin?screen=cost");

    const card = (await screen.findAllByText("Đặt tên hội thoại"))[0].closest("div") as HTMLElement;
    expect(within(card).getByText("0.020000")).toBeInTheDocument();
    expect(card).toHaveTextContent("Không trừ vào hạn mức người dùng.");
    // Hai cot doc phan `chat`: 0.32 (tong gom dat ten) khong hien o dau ca.
    expect(screen.queryByText("0.320000")).toBeNull();
    // Hang khoa rieng: o dat ten la "—", khong phai 0 (luot dat ten luon la tien he thong).
    // T-S.19c: ca hai o tien kia cung "—" — luot BYOK chi dem token (NQ-134 ③).
    const bySource = screen.getByRole("region", { name: "Theo nguồn" });
    const byokRow = within(bySource).getByRole("row", { name: /Khoá riêng/ });
    expect(within(byokRow).getAllByText("—")).toHaveLength(3);
  });

  it("T-S.19c: bang Theo nguon them Token vao/ra; nguon 'Khoa rieng' chi con token + dong duong di", async () => {
    const nd = userEvent.setup();
    const tokens = (prompt: number, completion: number) => ({
      cost_usd: "0",
      prompt_tokens: prompt,
      completion_tokens: completion,
      events: 1,
    });
    const row = (key: string, label: string | null, prompt: number, completion: number) => ({
      key,
      label,
      metered: tokens(prompt, completion),
      unmetered: zero,
      by_purpose: { chat: { metered: tokens(prompt, completion), unmetered: zero }, title: { metered: zero, unmetered: zero } },
      title_cost_usd: "0",
    });
    const endpointModel = "byok:e1d2c3b4-0000-4000-8000-000000000001/meta-llama/llama-4-maverick";
    const gone = "byok:e1d2c3b4-0000-4000-8000-000000000002/qwen3-32b";
    vi.mocked(api.adminModels).mockResolvedValue({
      models: [
        {
          id: "claude-sonnet",
          display_name: "Claude Sonnet 4.5",
          provider: "Anthropic",
          route: { id: "anthropic", label: "Anthropic", user_visible: true, availability: "always" },
          health: { available: true, reason: null },
          enabled: true,
          vision: true,
          vision_override: null,
        },
      ],
      checked_at: null,
      stale_after_s: 30,
    });
    vi.mocked(api.adminCosts).mockImplementation(async (source) =>
      source === "byok"
        ? {
            ...report,
            key_source: "byok",
            totals: row("t", null, 1733647, 422097),
            by_user: [row(UUID, "an@scarlet.test", 1733647, 422097)],
            by_model: [
              row("claude-sonnet", null, 1284530, 312874),
              row(endpointModel, "openrouter.ai", 210118, 51402),
              row(gone, null, 5, 1),
            ],
          }
        : report,
    );
    renderAt("/admin?screen=cost");

    const bySource = await screen.findByRole("region", { name: "Theo nguồn" });
    expect(within(bySource).getByRole("columnheader", { name: "Token vào" })).toBeInTheDocument();
    expect(within(bySource).getByRole("columnheader", { name: "Lượt gọi" })).toBeInTheDocument();

    await nd.click(within(screen.getByRole("radiogroup", { name: "Nguồn tiền" })).getByRole("radio", { name: "Khoá riêng" }));

    expect(await screen.findByText("Token vào trong kỳ")).toBeInTheDocument();
    expect(screen.getAllByText("1.733.647").length).toBeGreaterThan(0);
    expect(screen.getAllByText("422.097").length).toBeGreaterThan(0);
    expect(screen.queryByText("Metered trong kỳ (USD)")).toBeNull();
    expect(screen.getByText("Không có trong nguồn này")).toBeInTheDocument();

    for (const name of ["Theo người dùng", "Theo model"]) {
      const region = screen.getByRole("region", { name });
      const headers = within(region).getAllByRole("columnheader").map((h) => h.textContent);
      expect(headers.slice(1)).toEqual(["Token vào", "Token ra"]);
    }
    const byModel = screen.getByRole("region", { name: "Theo model" });
    expect(within(byModel).getByRole("row", { name: /Claude Sonnet 4\.5/ })).toHaveTextContent(/Anthropic·Gọi thẳng/);
    expect(within(byModel).getByRole("row", { name: /meta-llama\/llama-4-maverick/ })).toHaveTextContent(
      /Endpoint tuỳ chỉnh·openrouter\.ai/,
    );
    // Endpoint da xoa: khong host, khong UUID tran.
    const goneRow = within(byModel).getByRole("row", { name: /qwen3-32b/ });
    expect(goneRow).toHaveTextContent(/Endpoint tuỳ chỉnh/);
    expect(goneRow.textContent).not.toContain("e1d2c3b4");
  });

  it("chon nguon 'Khoa rieng' ⇒ the dat ten noi 'Khong co trong nguon nay', khong in so 0", async () => {
    const nd = userEvent.setup();
    vi.mocked(api.adminCosts).mockResolvedValue(report);
    renderAt("/admin?screen=cost");

    const group = await screen.findByRole("radiogroup", { name: "Nguồn tiền" });
    await nd.click(within(group).getByRole("radio", { name: "Khoá riêng" }));

    expect(vi.mocked(api.adminCosts).mock.lastCall?.[0]).toBe("byok");
    expect(await screen.findByText("Không có trong nguồn này")).toBeInTheDocument();
  });
});

describe("Model", () => {
  const MODELS: AdminModelListOut = {
    models: [
      {
        id: "deepseek-flash",
        display_name: "DeepSeek Flash",
        provider: "DeepSeek",
        route: { id: "deepseek", label: "DeepSeek AI", user_visible: true, availability: "always" },
        health: { available: true, reason: null },
        enabled: true,
        vision: true,
        vision_override: null,
      },
      {
        id: "nr-gemini-flash",
        display_name: "Gemini Flash",
        provider: "Google AI",
        route: { id: "ninerouter", label: "9Router (local)", user_visible: false, availability: "host-dependent" },
        health: { available: false, reason: "9Router (local) đang không phản hồi." },
        enabled: true,
        vision: true,
        vision_override: null,
      },
    ],
    checked_at: "2026-09-30T07:32:10Z",
    stale_after_s: 30,
  };

  it("DoD dong 2: 'Google AI · qua 9Router (local)'; hong ghi TEN duong, hang goi thang khong co 'qua'", async () => {
    vi.mocked(api.adminModels).mockResolvedValue(MODELS);
    renderAt("/admin?screen=models");

    const table = await screen.findByRole("region", { name: "Model" });
    const gemini = within(table).getByRole("row", { name: /Gemini Flash/ });
    expect(gemini).toHaveTextContent("Google AI · qua 9Router (local)");
    expect(gemini).toHaveTextContent("Lỗi ở đường 9Router (local)");
    const deepseek = within(table).getByRole("row", { name: /DeepSeek Flash/ });
    expect(deepseek).toHaveTextContent("DeepSeek");
    expect(deepseek).not.toHaveTextContent("qua");
    expect(deepseek).toHaveTextContent("Hoạt động");
    // The duong di: ly do cua server nguyen van, loai "Trung gian" cho duong an.
    expect(screen.getByText("9Router (local) đang không phản hồi.")).toBeInTheDocument();
    expect(screen.getByText("Trung gian")).toBeInTheDocument();
  });

  it("T-4.5: o 'Doc anh' — Luon tat ⇒ PATCH vision=false, Theo catalog ⇒ null, roi nap lai", async () => {
    const user = userEvent.setup();
    vi.mocked(api.adminModels).mockResolvedValue(MODELS);
    vi.mocked(api.adminUpdateModel).mockResolvedValue(undefined);
    renderAt("/admin?screen=models");

    const table = await screen.findByRole("region", { name: "Model" });
    const select = within(table).getByRole("combobox", { name: "Đọc ảnh — DeepSeek Flash" });
    expect(select).toHaveValue("catalog");

    await user.selectOptions(select, "off");
    await user.selectOptions(select, "catalog");

    expect(vi.mocked(api.adminUpdateModel).mock.calls).toEqual([
      ["deepseek-flash", { vision: false }],
      ["deepseek-flash", { vision: null }],
    ]);
    await waitFor(() => expect(api.adminModels).toHaveBeenCalledTimes(3));
  });
});
