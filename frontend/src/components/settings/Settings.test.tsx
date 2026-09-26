/**
 * Trang Cai dat v2 (T-S.11) — DoD dong 1, dong 4 o tang test, va bon Cam bay.
 *
 * Dung BANG ROUTE THAT (`routes` + `createMemoryRouter`) va `useSessionState`
 * THAT: chi lop `api` bi thay. Nho vay cau "doi ten KHONG xoa `default_model`"
 * duoc khang dinh tren chinh BODY ma `api.updateSettings` nhan — tuc dung thu
 * di ra mang — chu khong tren mot ham gia cua `session`.
 *
 *   - Deep link `/cai-dat/muc-su-dung` mo dung tab.
 *   - Doi ten ⇒ body mang du `default_model` + `reasoning_prefs` + mau (Cam bay ①).
 *   - Thanh chay o lan mo dau, KHONG o lan hai, CHAY LAI khi `last_login_at`
 *     doi; `localStorage` nem loi ⇒ van render, khong chay (Cam bay ②).
 *   - Dong BYOK cua T-3.12: them khoa ⇒ 4 ky tu cuoi, ban ro khong bao gio
 *     hien lai (§20).
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      logout: vi.fn(),
      updateSettings: vi.fn(),
      listModels: vi.fn(),
      listProviderKeys: vi.fn(),
      putProviderKey: vi.fn(),
      deleteProviderKey: vi.fn(),
    },
  };
});

import { PATHS } from "../../app/paths";
import { routes } from "../../app/routes";
import {
  ApiError,
  api,
  type ModelOut,
  type ProfileOut,
  type ProviderKey,
  type ProviderKeyList,
  type QuotaWindow,
} from "../../lib/api";
import { DRAWER_QUERY } from "../../lib/viewport";
import { defaultAvatarColor } from "../ui/avatar";

const USER_ID = "5b0c1c9e-7d1a-4c52-9f0e-2a6b3c4d5e6f";

function quotaWindow(over: Partial<QuotaWindow> = {}): QuotaWindow {
  return {
    limit_type: "5h",
    limit_usd: "0.5000",
    spent_usd: "0.1800",
    remaining_usd: "0.3200",
    remaining_pct: 64,
    retry_after: null,
    ...over,
  };
}

const PROFILE: ProfileOut = {
  id: USER_ID,
  email: "an.nguyen@scarlet.test",
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "free",
  default_model: "claude-haiku",
  last_login_at: "2026-09-26T01:00:00Z",
  quota: [quotaWindow(), quotaWindow({ limit_type: "weekly", remaining_pct: 90 })],
  message_max_chars: 24000,
  quota_warn_remaining_pct: 20,
  limits_cache_ttl_s: 45,
  stream_ttl_s: 3600,
  display_name_max_chars: 64,
  avatar_color: null,
  reasoning_prefs: { "deepseek-flash": "high" },
};

function model(over: Partial<ModelOut>): ModelOut {
  return {
    id: "m",
    display_name: "M",
    provider: "P",
    provider_id: "p",
    capabilities: [],
    context_window: 1,
    max_output: 1,
    default: false,
    badge: null,
    available: true,
    unavailable_reason: null,
    reasoning: null,
    pricing: null,
    pricing_mode: "unmetered",
    checked_at: null,
    stale_after_s: 30,
    ...over,
  };
}

const MODELS: ModelOut[] = [
  model({ id: "deepseek-flash", display_name: "DeepSeek Flash", provider: "DeepSeek", default: true }),
  model({ id: "claude-haiku", display_name: "Claude Haiku 4.5", provider: "Anthropic" }),
  model({ id: "grok-4.6", display_name: "Grok 4.6", provider: "xAI", available: false }),
];

const PLAINTEXT = "sk-banro-KHONG-DUOC-HIEN-1234567890";
const BYOK: ProviderKeyList["byok_providers"] = [
  { provider: "deepseek", label: "DeepSeek" },
  { provider: "anthropic", label: "Anthropic" },
];
const STORED: ProviderKey = {
  provider: "anthropic",
  masked_key: "sk-...7890",
  verified_at: "2026-09-26T02:00:00Z",
  created_at: "2026-09-26T02:00:00Z",
  usable: true,
};

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(<RouterProvider router={router} />);
  return { ...view, router };
}

/** Man hep (< 1024 px): chi truy van drawer cua `viewport.ts` khop. */
function narrowScreen() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === DRAWER_QUERY,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  vi.mocked(api.me).mockResolvedValue(PROFILE);
  vi.mocked(api.logout).mockResolvedValue({ status: "ok" });
  vi.mocked(api.updateSettings).mockReset();
  vi.mocked(api.updateSettings).mockImplementation(async (body) => ({
    ...body,
    // Nhu server (T-S.5): cat hai dau, rong ⇒ `null`.
    display_name: body.display_name?.trim() || null,
  }));
  vi.mocked(api.listModels).mockResolvedValue(MODELS);
  vi.mocked(api.listProviderKeys).mockReset();
  vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [], byok_providers: BYOK });
  vi.mocked(api.putProviderKey).mockReset();
  vi.mocked(api.deleteProviderKey).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

/* ── Duong dan ─────────────────────────────────────────────────────────── */

describe("duong dan", () => {
  it("1. deep link /cai-dat/muc-su-dung mo DUNG tab Muc su dung", async () => {
    renderAt(PATHS.settingsUsage);

    expect(await screen.findByRole("heading", { name: "5 giờ" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mức sử dụng" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Tài khoản" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("region", { name: "Mức sử dụng" })).toBeInTheDocument();
  });

  it("2. man hep: /cai-dat la DANH SACH nam tab kem gia tri, khong chuyen huong", async () => {
    narrowScreen();
    localStorage.setItem("scarlet-theme", "dark");
    const { router } = renderAt(PATHS.settings);

    const nav = await screen.findByRole("navigation", { name: "Mục cài đặt" });
    await waitFor(() => {
      expect(within(nav).getByRole("link", { name: /Model/ })).toHaveTextContent("Claude Haiku 4.5");
    });
    expect([...nav.querySelectorAll("a")].map((a) => a.getAttribute("href"))).toEqual([
      PATHS.settingsAccount,
      PATHS.settingsAppearance,
      PATHS.settingsModel,
      PATHS.settingsApiKeys,
      PATHS.settingsUsage,
    ]);
    // Ten trong ⇒ email (NQ-116); theme da luu.
    expect(within(nav).getByRole("link", { name: /Tài khoản/ })).toHaveTextContent(PROFILE.email);
    expect(within(nav).getByRole("link", { name: /Giao diện/ })).toHaveTextContent("Tối");
    expect(router.state.location.pathname).toBe(PATHS.settings);
  });

  it("3. man hep: man con co nut quay lai /cai-dat", async () => {
    narrowScreen();
    const user = userEvent.setup();
    const { router } = renderAt(PATHS.settingsModel);

    await user.click(await screen.findByRole("link", { name: "Quay lại Cài đặt" }));

    expect(router.state.location.pathname).toBe(PATHS.settings);
    expect(await screen.findByRole("navigation", { name: "Mục cài đặt" })).toBeInTheDocument();
  });

  it("4. slug go sai ⇒ 404, khong phai mot tab rong", async () => {
    renderAt("/cai-dat/khong-co");

    expect(await screen.findByText("404")).toBeInTheDocument();
  });
});

/* ── Tab Tai khoan ─────────────────────────────────────────────────────── */

describe("tai khoan", () => {
  it("5. doi ten KHONG xoa default_model — body gui DU bon truong (Cam bay ①)", async () => {
    const user = userEvent.setup();
    renderAt(PATHS.settingsAccount);

    await user.type(await screen.findByLabelText("Tên hiển thị"), "Nguyễn Thị An");
    await user.click(screen.getByRole("button", { name: "Lưu" }));

    expect(api.updateSettings).toHaveBeenCalledTimes(1);
    expect(api.updateSettings).toHaveBeenCalledWith({
      default_model: "claude-haiku",
      display_name: "Nguyễn Thị An",
      // Mau khong cham ⇒ van "chua chon" — khong dong cung mau hash vao DB.
      avatar_color: null,
      reasoning_prefs: { "deepseek-flash": "high" },
    });
    expect(await screen.findByText("Đã lưu")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lưu" })).toBeDisabled();
  });

  it("6. xoa ten ⇒ `display_name: null`; placeholder va avatar la email", async () => {
    vi.mocked(api.me).mockResolvedValue({ ...PROFILE, display_name: "An", avatar_color: "avatar-2" });
    const user = userEvent.setup();
    renderAt(PATHS.settingsAccount);

    const input = await screen.findByLabelText("Tên hiển thị");
    expect(input).toHaveValue("An");
    await user.clear(input);

    expect(input).toHaveAttribute("placeholder", PROFILE.email);
    expect(screen.getByTestId("avatar-preview")).toHaveTextContent("A");
    await user.click(screen.getByRole("button", { name: "Lưu" }));

    expect(api.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ display_name: null, default_model: "claude-haiku", avatar_color: "avatar-2" }),
    );
  });

  it("7. chua chon mau ⇒ mau hash(user id); chon mau ⇒ gui TEN token", async () => {
    const user = userEvent.setup();
    renderAt(PATHS.settingsAccount);

    const fallback = defaultAvatarColor(USER_ID);
    expect(await screen.findByTestId("avatar-preview")).toHaveAttribute("data-color", fallback);
    const next = fallback === "avatar-5" ? "avatar-6" : "avatar-5";
    await user.click(screen.getByRole("radio", { name: next === "avatar-5" ? "Lam" : "Xám đá" }));
    expect(screen.getByTestId("avatar-preview")).toHaveAttribute("data-color", next);
    await user.click(screen.getByRole("button", { name: "Lưu" }));

    expect(api.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ avatar_color: next, default_model: "claude-haiku", display_name: null }),
    );
  });

  it("8. mau la trong `/auth/me` ⇒ roi ve mau mac dinh, khong vo", async () => {
    vi.mocked(api.me).mockResolvedValue({ ...PROFILE, avatar_color: "ruby-500" });
    renderAt(PATHS.settingsAccount);

    expect(await screen.findByTestId("avatar-preview")).toHaveAttribute(
      "data-color",
      defaultAvatarColor(USER_ID),
    );
  });

  it("9. tran ten tu `display_name_max_chars` (A3); khoang trang cuoi khong la 'doi'", async () => {
    vi.mocked(api.me).mockResolvedValue({ ...PROFILE, display_name: "An", display_name_max_chars: 12 });
    const user = userEvent.setup();
    renderAt(PATHS.settingsAccount);

    const input = await screen.findByLabelText("Tên hiển thị");
    expect(input).toHaveAttribute("maxLength", "12");
    expect(screen.getByText("12")).toBeInTheDocument();
    await user.type(input, "  ");

    expect(screen.getByRole("button", { name: "Lưu" })).toBeDisabled();
  });

  it("10. Tai anh len la nut cho B-265; tier co nhan / chua co nhan", async () => {
    renderAt(PATHS.settingsAccount);

    const upload = await screen.findByRole("button", { name: "Tải ảnh lên" });
    expect(upload).toHaveAttribute("aria-disabled", "true");
    expect(upload).toHaveAttribute("data-planned", "B-265");
    expect(screen.getAllByText("Miễn phí").length).toBeGreaterThan(0);
  });

  it("11. tier chua co nhan trong vi.json ⇒ hien nguyen ten (NQ-116)", async () => {
    vi.mocked(api.me).mockResolvedValue({ ...PROFILE, tier_name: "trusted" });
    renderAt(PATHS.settingsAccount);

    expect((await screen.findAllByText("trusted")).length).toBeGreaterThan(0);
  });

  it("12. Dang xuat ⇒ xoa phien roi ve /dang-nhap", async () => {
    const user = userEvent.setup();
    const { router } = renderAt(PATHS.settingsAccount);

    // Header hom nay con mot nut Dang xuat (T-S.12 go no) — bam nut CUA TAB.
    const tab = await screen.findByRole("region", { name: "Tài khoản" });
    await user.click(await within(tab).findByRole("button", { name: "Đăng xuất" }));

    expect(api.logout).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(PATHS.login);
    });
  });

  it("13. model mac dinh vua bi tat ⇒ noi ro, khong im lang", async () => {
    vi.mocked(api.updateSettings).mockRejectedValue(new ApiError(400, "MODEL_UNKNOWN", "x"));
    const user = userEvent.setup();
    renderAt(PATHS.settingsAccount);

    await user.type(await screen.findByLabelText("Tên hiển thị"), "An");
    await user.click(screen.getByRole("button", { name: "Lưu" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Model này không còn trong danh mục");
  });
});

/* ── Tab Muc su dung ───────────────────────────────────────────────────── */

const fills = () => screen.getAllByTestId("quota-fill");

describe("muc su dung", () => {
  it("14. thanh chay tu 0 o lan mo DAU, khong o lan HAI, chay LAI khi last_login_at doi", async () => {
    const first = renderAt(PATHS.settingsUsage);
    await screen.findByRole("heading", { name: "5 giờ" });
    expect(fills().map((el) => el.className.includes("motion-quota-fill"))).toEqual([true, true]);
    first.unmount();

    // F5 / mo tab moi trong CUNG lan dang nhap ⇒ khong chay.
    const second = renderAt(PATHS.settingsUsage);
    await screen.findByRole("heading", { name: "5 giờ" });
    expect(fills().every((el) => !el.className.includes("motion-quota-fill"))).toBe(true);
    expect(fills().every((el) => el.className.includes("motion-quota"))).toBe(true);
    second.unmount();

    // Dang nhap lai ⇒ `last_login_at` moi ⇒ chay lai.
    vi.mocked(api.me).mockResolvedValue({ ...PROFILE, last_login_at: "2026-09-27T08:00:00Z" });
    renderAt(PATHS.settingsUsage);
    await screen.findByRole("heading", { name: "5 giờ" });
    expect(fills().every((el) => el.className.includes("motion-quota-fill"))).toBe(true);
  });

  it("15. `localStorage` nem loi ⇒ van render, KHONG chay hoat anh", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("bi chan", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("bi chan", "SecurityError");
    });
    renderAt(PATHS.settingsUsage);

    expect(await screen.findByRole("heading", { name: "7 ngày" })).toBeInTheDocument();
    expect(fills()).toHaveLength(2);
    expect(fills().some((el) => el.className.includes("motion-quota-fill"))).toBe(false);
  });

  it("16. `last_login_at: null` ⇒ khong chay (khong phan biet duoc hai lan dang nhap)", async () => {
    // Khoa da nho mot lan dang nhap CU: `null` van khong duoc tinh la "khac".
    localStorage.setItem("scarlet-quota-fill", "2026-09-20T00:00:00Z");
    vi.mocked(api.me).mockResolvedValue({ ...PROFILE, last_login_at: null });
    renderAt(PATHS.settingsUsage);

    await screen.findByRole("heading", { name: "5 giờ" });
    expect(fills().some((el) => el.className.includes("motion-quota-fill"))).toBe(false);
  });

  it("17. nguong tu `/auth/me`: 21% ⇒ khong canh bao, 20% ⇒ 'sap het'; phan to = da dung", async () => {
    vi.mocked(api.me).mockResolvedValue({
      ...PROFILE,
      quota: [
        quotaWindow({ remaining_pct: 20 }),
        quotaWindow({ limit_type: "weekly", remaining_pct: 21 }),
      ],
    });
    renderAt(PATHS.settingsUsage);

    const five = await screen.findByRole("region", { name: "5 giờ" });
    const seven = screen.getByRole("region", { name: "7 ngày" });
    expect(within(five).getByText("Hạn mức sắp hết")).toBeInTheDocument();
    expect(within(seven).queryByText("Hạn mức sắp hết")).toBeNull();
    expect(five).toHaveAttribute("data-level", "warning");
    expect(seven).toHaveAttribute("data-level", "normal");
    expect(within(five).getByTestId("quota-fill")).toHaveStyle({ width: "80%" });
    // Mot con so moi cua so (ca 11 cu cua QuotaBar).
    expect(within(five).getAllByText("20%")).toHaveLength(1);
  });

  it("18. het ⇒ 'da dung het' + gio hoan lai; cua so chua het KHONG bia gio", async () => {
    vi.mocked(api.me).mockResolvedValue({
      ...PROFILE,
      quota: [
        quotaWindow({ remaining_pct: 0, retry_after: 3600 }),
        quotaWindow({ limit_type: "weekly", remaining_pct: 64 }),
      ],
    });
    renderAt(PATHS.settingsUsage);

    const five = await screen.findByRole("region", { name: "5 giờ" });
    expect(within(five).getByText("Đã dùng hết hạn mức")).toBeInTheDocument();
    expect(within(five).getByText("Hoàn lại lúc")).toBeInTheDocument();
    expect(five.querySelector("time")).not.toBeNull();
    // Cua so truot chua vuot tran khong co "luc hoan lai" nao — ca dong ay vang
    // mat, khong phai mot dong "chua xac dinh".
    const seven = screen.getByRole("region", { name: "7 ngày" });
    expect(within(seven).queryByText("Hoàn lại lúc")).toBeNull();
    expect(within(seven).queryByText(/Chưa xác định/)).toBeNull();
    expect(seven.querySelector("time")).toBeNull();
  });

  it("19. `quota: null` (Redis chop) ⇒ AN the, khong ve thanh rong; ghi chu van con", async () => {
    vi.mocked(api.me).mockResolvedValue({ ...PROFILE, quota: null });
    renderAt(PATHS.settingsUsage);

    expect(await screen.findByRole("link", { name: "Quản lý khoá API" })).toHaveAttribute(
      "href",
      PATHS.settingsApiKeys,
    );
    expect(screen.queryAllByTestId("quota-fill")).toHaveLength(0);
  });

  it("20. 'co hieu luc trong vong N giay' — N tu `limits_cache_ttl_s`, khong go tay", async () => {
    renderAt(PATHS.settingsUsage);

    expect(await screen.findByText(/Hạn mức do quản trị viên đặt/)).toHaveTextContent(
      /trong vòng 45 giây\./,
    );
  });
});

/* ── Tab Model ─────────────────────────────────────────────────────────── */

describe("model", () => {
  it("21. chon model ⇒ body DU truong, ten va mau giu nguyen; 'Theo mac dinh' ⇒ null", async () => {
    vi.mocked(api.me).mockResolvedValue({ ...PROFILE, display_name: "An", avatar_color: "avatar-7" });
    const user = userEvent.setup();
    renderAt(PATHS.settingsModel);

    expect(await screen.findByRole("radio", { name: /Claude Haiku 4\.5/ })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: /^DeepSeek Flash/ }));
    await user.click(screen.getByRole("button", { name: "Lưu" }));

    expect(api.updateSettings).toHaveBeenLastCalledWith({
      default_model: "deepseek-flash",
      display_name: "An",
      avatar_color: "avatar-7",
      reasoning_prefs: { "deepseek-flash": "high" },
    });
    await screen.findByText("Đã lưu");

    await user.click(screen.getByRole("radio", { name: /Theo mặc định của hệ thống/ }));
    await user.click(screen.getByRole("button", { name: "Lưu" }));
    expect(api.updateSettings).toHaveBeenLastCalledWith(
      expect.objectContaining({ default_model: null, display_name: "An" }),
    );
  });

  it("22. model khong dung duoc: hien xam, KHONG chon duoc", async () => {
    renderAt(PATHS.settingsModel);

    const off = await screen.findByRole("radio", { name: /Grok 4\.6/ });
    expect(off).toBeDisabled();
    expect(screen.getByText("Không dùng được")).toBeInTheDocument();
  });
});

/* ── Tab Giao dien ─────────────────────────────────────────────────────── */

describe("giao dien", () => {
  it("23. chon Toi = XEM TRUOC (chua ghi); Luu ⇒ ghi; nut header noi dung", async () => {
    const user = userEvent.setup();
    renderAt(PATHS.settingsAppearance);

    await user.click(await screen.findByRole("radio", { name: /Tối/ }));

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("scarlet-theme")).toBeNull();
    // Nut header moi sang theme KIA — dang toi thi ten nut la "sang" (T-S.12:
    // nut icon, ten truy cap mang loi moi).
    expect(screen.getByRole("button", { name: "Chuyển sang theme sáng" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Lưu" }));
    expect(localStorage.getItem("scarlet-theme")).toBe("dark");
    expect(await screen.findByText("Đã lưu")).toBeInTheDocument();
  });

  it("24. xem truoc roi ROI tab chua luu ⇒ trang ve theme da luu", async () => {
    localStorage.setItem("scarlet-theme", "light");
    const user = userEvent.setup();
    renderAt(PATHS.settingsAppearance);

    await user.click(await screen.findByRole("radio", { name: /Tối/ }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    await user.click(screen.getByRole("link", { name: "Mức sử dụng" }));

    await screen.findByRole("heading", { name: "5 giờ" });
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("scarlet-theme")).toBe("light");
  });

  it("25. 'Theo he thong' + Luu ⇒ XOA khoa (khong ghi chu 'system')", async () => {
    localStorage.setItem("scarlet-theme", "dark");
    const user = userEvent.setup();
    renderAt(PATHS.settingsAppearance);

    expect(await screen.findByRole("radio", { name: /Tối/ })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: /Theo hệ thống/ }));
    await user.click(screen.getByRole("button", { name: "Lưu" }));

    expect(localStorage.getItem("scarlet-theme")).toBeNull();
  });

  it("26. bam nut header khi dang o tab ⇒ tab theo lua chon vua luu", async () => {
    localStorage.setItem("scarlet-theme", "light");
    const user = userEvent.setup();
    renderAt(PATHS.settingsAppearance);

    expect(await screen.findByRole("radio", { name: /Sáng/ })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Chuyển sang theme tối" }));

    expect(localStorage.getItem("scarlet-theme")).toBe("dark");
    expect(screen.getByRole("radio", { name: /Tối/ })).toBeChecked();
    expect(screen.getByRole("button", { name: "Lưu" })).toBeDisabled();
  });
});

/* ── Tab Khoa API ──────────────────────────────────────────────────────── */

describe("khoa API", () => {
  it("27. them khoa ⇒ hien DUNG ban che; ban ro khong con o dau ca (§20)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.putProviderKey).mockResolvedValue(STORED);
    renderAt(PATHS.settingsApiKeys);

    // O nhap khong co `<label>` rieng: ten cua no la ten provider cua hang
    // (`aria-labelledby`, ban T-HD9 D).
    const field = await screen.findByLabelText("Anthropic");
    expect(field).toHaveAttribute("type", "password");
    await user.type(field, PLAINTEXT);
    vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [STORED], byok_providers: BYOK });
    const row = field.closest("div.flex-col") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Lưu khoá" }));

    expect(api.putProviderKey).toHaveBeenCalledWith("anthropic", PLAINTEXT);
    expect(await screen.findByTestId("masked-key")).toHaveTextContent("sk-...7890");
    expect(screen.getByText("Đã lưu")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(PLAINTEXT);
    for (const el of document.querySelectorAll("input")) {
      expect(el.value).not.toContain(PLAINTEXT);
    }
  });

  it("28. provider tu choi ⇒ noi ro, va o nhap VAN bi xoa", async () => {
    const user = userEvent.setup();
    vi.mocked(api.putProviderKey).mockRejectedValue(new ApiError(400, "PROVIDER_KEY_REJECTED", "x"));
    renderAt(PATHS.settingsApiKeys);

    const field = await screen.findByLabelText("DeepSeek");
    await user.type(field, PLAINTEXT);
    await user.click(within(field.closest("div.flex-col") as HTMLElement).getByRole("button", { name: "Lưu khoá" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Nhà cung cấp từ chối khoá này");
    expect(field).toHaveValue("");
    expect(document.body.textContent).not.toContain(PLAINTEXT);
  });

  it("29. danh sach hang den tu `byok_providers` cua server, khong tu mot mang go san", async () => {
    vi.mocked(api.listProviderKeys).mockResolvedValue({
      keys: [],
      byok_providers: [{ provider: "nha-moi", label: "Nhà mới" }],
    });
    renderAt(PATHS.settingsApiKeys);

    expect(await screen.findByLabelText("Nhà mới")).toBeInTheDocument();
    expect(screen.queryByText("DeepSeek")).toBeNull();
  });

  it("30. Xoa hoi lai trong dialog; Huy ⇒ khong goi; Xoa ⇒ DELETE", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [STORED], byok_providers: BYOK });
    vi.mocked(api.deleteProviderKey).mockResolvedValue(undefined);
    renderAt(PATHS.settingsApiKeys);

    await user.click(await screen.findByRole("button", { name: "Xoá" }));
    const dialog = await screen.findByRole("dialog", { name: "Xoá khoá API này?" });
    await user.click(within(dialog).getByRole("button", { name: "Huỷ" }));
    expect(api.deleteProviderKey).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Xoá" }));
    vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [], byok_providers: BYOK });
    await act(async () => {
      await user.click(
        within(await screen.findByRole("dialog")).getByRole("button", { name: "Xoá" }),
      );
    });

    expect(api.deleteProviderKey).toHaveBeenCalledWith("anthropic");
    await waitFor(() => {
      expect(screen.queryByTestId("masked-key")).toBeNull();
    });
  });
});
