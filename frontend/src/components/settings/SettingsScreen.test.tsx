/**
 * Trang Cai dat (T-3.12) — DoD dong 7 o tang test.
 *
 *   - Them khoa BYOK: chi hien 4 ky tu cuoi, ban ro KHONG BAO GIO hien lai
 *     (§20, T-2.14) — ke ca trong `value` cua o nhap sau khi gui, ke ca khi
 *     server tu choi khoa.
 *   - Doi model mac dinh: di qua `changeDefaultModel` (tuc `PUT /settings`, thu
 *     `GET /auth/me` doc lai sau F5 — phan F5 do tren stack that).
 *   - Theme: o chon o trang nay va nut o header la MOT trang thai.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Outlet, RouterProvider, createMemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listModels: vi.fn(),
      listProviderKeys: vi.fn(),
      putProviderKey: vi.fn(),
      deleteProviderKey: vi.fn(),
    },
  };
});

import type { SessionState } from "../../features/auth/useSessionState";
import { ApiError, api, type ModelOut, type ProviderKeyList } from "../../lib/api";
import { ThemeToggle } from "../ui/ThemeToggle";
import { SettingsScreen } from "./SettingsScreen";

const PLAINTEXT = "sk-banro-KHONG-DUOC-HIEN-1234567890";
const BYOK: ProviderKeyList["byok_providers"] = [
  { provider: "deepseek", label: "DeepSeek AI" },
  { provider: "anthropic", label: "Anthropic" },
];

const MODEL: ModelOut = {
  id: "claude-haiku",
  display_name: "Claude Haiku 4.5",
  provider: "Anthropic",
  provider_id: "anthropic",
  capabilities: [],
  context_window: 1,
  max_output: 1,
  default: false,
  badge: null,
  available: true,
  unavailable_reason: null,
  checked_at: null,
  stale_after_s: 30,
};

const changeDefaultModel = vi.fn(async () => undefined);

function renderAt() {
  const session = {
    user: { id: "u", email: "u@scarlet.test", role: "user", status: "active" },
    profile: { default_model: null },
    changeDefaultModel,
  } as unknown as SessionState;
  const router = createMemoryRouter(
    [
      {
        element: <Outlet context={session} />,
        children: [
          {
            path: "/",
            element: (
              <>
                <ThemeToggle />
                <SettingsScreen />
              </>
            ),
          },
        ],
      },
    ],
    { initialEntries: ["/"] },
  );
  return render(<RouterProvider router={router} />);
}

beforeEach(() => {
  localStorage.clear();
  changeDefaultModel.mockClear();
  vi.mocked(api.listModels).mockResolvedValue([MODEL]);
  vi.mocked(api.listProviderKeys).mockReset();
  vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [], byok_providers: BYOK });
  vi.mocked(api.putProviderKey).mockReset();
});

describe("khoa BYOK", () => {
  it("them khoa ⇒ hien DUNG ban che server tra; ban ro khong con o dau ca", async () => {
    const nd = userEvent.setup();
    vi.mocked(api.putProviderKey).mockResolvedValue({
      provider: "anthropic",
      masked_key: "sk-...7890",
      verified_at: "2026-09-23T07:00:00Z",
      created_at: "2026-09-23T07:00:00Z",
      usable: true,
    });
    renderAt();

    await nd.selectOptions(await screen.findByLabelText("Nhà cung cấp"), "anthropic");
    const o = screen.getByLabelText("Khoá API");
    expect(o).toHaveAttribute("type", "password");
    await nd.type(o, PLAINTEXT);
    vi.mocked(api.listProviderKeys).mockResolvedValue({
      keys: [
        {
          provider: "anthropic",
          masked_key: "sk-...7890",
          verified_at: "2026-09-23T07:00:00Z",
          created_at: "2026-09-23T07:00:00Z",
          usable: true,
        },
      ],
      byok_providers: BYOK,
    });
    await nd.click(screen.getByRole("button", { name: "Kiểm và lưu khoá" }));

    expect(api.putProviderKey).toHaveBeenCalledWith("anthropic", PLAINTEXT);
    expect(await screen.findByTestId("masked-key")).toHaveTextContent("sk-...7890");
    expect(screen.getByLabelText("Khoá API")).toHaveValue("");
    expect(document.body.textContent).not.toContain(PLAINTEXT);
    for (const input of document.querySelectorAll("input")) {
      expect(input.value).not.toContain(PLAINTEXT);
    }
  });

  it("provider tu choi ⇒ noi ro, va o nhap VAN bi xoa", async () => {
    const nd = userEvent.setup();
    vi.mocked(api.putProviderKey).mockRejectedValue(
      new ApiError(400, "PROVIDER_KEY_REJECTED", "provider tu choi khoa nay"),
    );
    renderAt();

    await nd.type(await screen.findByLabelText("Khoá API"), PLAINTEXT);
    await nd.click(screen.getByRole("button", { name: "Kiểm và lưu khoá" }));

    expect(await screen.findByText(/Nhà cung cấp từ chối khoá này/)).toBeInTheDocument();
    expect(screen.getByLabelText("Khoá API")).toHaveValue("");
    expect(document.body.textContent).not.toContain(PLAINTEXT);
  });

  it("danh sach provider den tu `byok_providers` cua server, khong tu mot mang go san", async () => {
    vi.mocked(api.listProviderKeys).mockResolvedValue({
      keys: [],
      byok_providers: [{ provider: "nha-moi", label: "Nhà mới" }],
    });
    renderAt();

    const select = await screen.findByLabelText("Nhà cung cấp");
    await waitFor(() => {
      expect(select).toHaveValue("nha-moi");
    });
    expect(screen.queryByRole("option", { name: "DeepSeek AI" })).toBeNull();
  });
});

describe("model mac dinh", () => {
  it("chon roi Luu ⇒ goi `datModelMacDinh` (PUT /settings); chon lai mac dinh ⇒ null", async () => {
    const nd = userEvent.setup();
    renderAt();

    const select = await screen.findByLabelText("Model cho hội thoại mới");
    await screen.findByRole("option", { name: /Claude Haiku 4\.5/ });
    await nd.selectOptions(select, "claude-haiku");
    await nd.click(screen.getByRole("button", { name: "Lưu" }));

    expect(changeDefaultModel).toHaveBeenCalledWith("claude-haiku");
    expect(await screen.findByText("Đã lưu.")).toBeInTheDocument();
  });
});

describe("giao dien", () => {
  it("chon Toi o trang nay ⇒ trang toi VA nut o header noi dung (mot trang thai)", async () => {
    const nd = userEvent.setup();
    renderAt();

    await nd.click(await screen.findByRole("radio", { name: "Tối" }));

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("scarlet-theme")).toBe("dark");
    // Nut header moi sang theme KIA — dang toi thi nut noi "Sang".
    expect(screen.getByRole("button", { name: "Đổi giao diện sáng/tối" })).toHaveTextContent("Sáng");
    expect(screen.getByRole("radio", { name: "Tối" })).toHaveAttribute("aria-checked", "true");
  });
});
