/**
 * Header v2 + khoi tai khoan + menu tai khoan — T-S.12 (DoD dong 1, dong 2).
 *
 * Dung BANG ROUTE THAT (`routes` + `createMemoryRouter`) va `useSessionState`
 * THAT, chi lop `api` bi thay — cung khuon `Settings.test.tsx`. Nho vay
 * "Dang xuat xoa phien roi ve `/dang-nhap`" do tren chinh phien cua `Layout`
 * va chinh URL cua router, khong tren mot ham gia.
 *
 *   - Header: khong con email, khong con nut Dang xuat; nut cho T-5.4 chi o
 *     man chat (NQ-128 c); "Quan tri" chu (desktop) / icon (mobile).
 *   - Khoi tai khoan: ten trong ⇒ NGUYEN email; ten la CHU, khong phai HTML;
 *     `truncate`; mau avatar; nhan tier (NQ-116).
 *   - Menu: dung thu tu bay `menuitem`, HAI `separator`; ba muc cho
 *     `aria-disabled` + `data-planned="B-264"`, bam khong lam gi.
 *   - Ban phim: Enter mo, mui ten di (ke ca qua muc cho), Esc dong va tra
 *     tieu diem ve khoi tai khoan.
 *   - Drawer: khoi nam trong drawer; chon mot muc thi drawer dong.
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
      listModels: vi.fn(),
      listConversations: vi.fn(),
      listProviderKeys: vi.fn(),
    },
  };
});

import { PATHS } from "../../app/paths";
import { routes } from "../../app/routes";
import { api, type ProfileOut } from "../../lib/api";
import { DRAWER_QUERY } from "../../lib/viewport";
import { defaultAvatarColor } from "../ui/avatar";

const USER_ID = "7c3e9a51-2b6d-4f08-8e1a-9d4c2b7f6a30";
const EMAIL = "an.nguyen@scarlet.test";

const PROFILE: ProfileOut = {
  id: USER_ID,
  email: EMAIL,
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "free",
  default_model: null,
  last_login_at: "2026-09-26T01:00:00Z",
  quota: null,
  message_max_chars: 24000,
  quota_warn_remaining_pct: 20,
  limits_cache_ttl_s: 60,
  stream_ttl_s: 3600,
  display_name_max_chars: 64,
  avatar_color: null,
  reasoning_prefs: {},
};

/** Thu tu cua S10 — `──` la mot `separator`. */
const MENU_ORDER = [
  "Cài đặt",
  "Mức sử dụng",
  "Ngôn ngữ",
  "Trợ giúp",
  "──",
  "Nâng cấp gói",
  "──",
  "Đăng xuất",
];

function renderAt(path: string, profile: Partial<ProfileOut> = {}) {
  vi.mocked(api.me).mockResolvedValue({ ...PROFILE, ...profile });
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

/** Nut mo menu = khoi tai khoan; ten truy cap la ten dang hien + tier. */
async function accountTrigger(name: string | RegExp = EMAIL): Promise<HTMLElement> {
  return screen.findByRole("button", { name: typeof name === "string" ? new RegExp(escapeRegExp(name)) : name });
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Mo menu bang chuot. DAT TIEU DIEM vao nut truoc khi bam — mot tat cua jsdom,
 * khong phai cua app: ca truoc go mot menu dang mo (tieu diem nam trong no),
 * jsdom de "vung dang focus" la chinh Document, va lan focus ke tiep jsdom ban
 * `blur` len `window` (buoc "focus update" cua HTML, Document → Window).
 * `Menu` cua Radix nghe `window.blur` (cua so mat tieu diem ⇒ dong menu) nen
 * menu vua mo tu dong ngay. Trinh duyet that chi ban `window.blur` khi CA cua
 * so mat tieu diem — do lai tren Chrome o DoD dong 3.
 */
async function openMenu(user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> {
  const trigger = await accountTrigger();
  act(() => trigger.focus());
  await user.click(trigger);
  return screen.findByRole("menu", { name: "Menu tài khoản" });
}

/** Header cua `Layout` — trang Cai dat co them `<header>` rieng cua no ben duoi. */
function appHeader(): HTMLElement {
  return screen.getAllByRole("banner")[0];
}

/** Doc noi dung menu theo DUNG thu tu DOM: ten muc, hoac `──` cho duong ke. */
function menuSequence(menu: HTMLElement): string[] {
  return Array.from(menu.querySelectorAll('[role="menuitem"], [role="separator"]')).map((el) =>
    el.getAttribute("role") === "separator" ? "──" : (el.textContent ?? "").trim(),
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(api.logout).mockReset().mockResolvedValue({ status: "ok" });
  vi.mocked(api.listModels).mockResolvedValue([]);
  vi.mocked(api.listConversations).mockResolvedValue({ items: [], next_cursor: null, truncated: false });
  vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [], byok_providers: [] });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("header v2 (NQ-115, NQ-128 b/c)", () => {
  it("1. man chat: khong email, khong nut Dang xuat; co nut cho T-5.4 aria-disabled", async () => {
    renderAt(PATHS.home);
    await accountTrigger();

    const header = appHeader();
    expect(within(header).queryByText(EMAIL)).toBeNull();
    expect(within(header).queryByRole("button", { name: "Đăng xuất" })).toBeNull();
    expect(within(header).queryByRole("link", { name: /Cài đặt/ })).toBeNull();

    const artifact = within(header).getByRole("button", { name: "Mở panel artifact" });
    expect(artifact).toHaveAttribute("aria-disabled", "true");
    expect(artifact).toHaveAttribute("data-planned", "T-5.4");
    expect(within(header).getByRole("button", { name: "Chuyển sang theme tối" })).toBeInTheDocument();
    // Nguoi dung thuong: khong co loi vao Quan tri.
    expect(within(header).queryByRole("link", { name: "Quản trị" })).toBeNull();
  });

  it("2. /cai-dat: header KHONG co nut cho T-5.4 hay nut sidebar; Dang xuat chi o tab Tai khoan", async () => {
    renderAt(PATHS.settingsAccount);
    const logout = await screen.findByRole("button", { name: "Đăng xuất" });

    const header = appHeader();
    expect(header).not.toContainElement(logout);
    expect(within(header).queryByRole("button", { name: "Mở panel artifact" })).toBeNull();
    expect(within(header).queryByRole("button", { name: "Mở thanh bên" })).toBeNull();
    expect(within(header).queryByRole("button", { name: "Đóng thanh bên" })).toBeNull();
    expect(within(header).queryByText(EMAIL)).toBeNull();
    // Khong sidebar ⇒ khong khoi tai khoan (Cam bay ①).
    expect(screen.queryByRole("button", { name: new RegExp(escapeRegExp(EMAIL)) })).toBeNull();
  });

  it("3. admin: desktop la CHU 'Quan tri'; mobile la icon cung ten truy cap", async () => {
    const { unmount } = renderAt(PATHS.home, { role: "admin" });
    const wide = await within(appHeader()).findByRole("link", { name: "Quản trị" });
    expect(wide).toHaveTextContent("Quản trị");
    expect(wide).toHaveAttribute("href", PATHS.admin);
    unmount();

    narrowScreen();
    renderAt(PATHS.home, { role: "admin" });
    const narrow = await within(appHeader()).findByRole("link", { name: "Quản trị" });
    expect(narrow.textContent).toBe("");
    expect(narrow.querySelector("svg")).not.toBeNull();
  });
});

describe("khoi tai khoan (NQ-116, Cam bay ②)", () => {
  it("4. ten trong ⇒ NGUYEN email, chu cai dau, nhan tier, mau hash(user id)", async () => {
    renderAt(PATHS.home);
    const trigger = await accountTrigger();

    expect(trigger).toHaveTextContent(EMAIL);
    expect(trigger).toHaveTextContent("Miễn phí");
    const avatar = trigger.querySelector('[aria-hidden="true"]');
    expect(avatar).toHaveTextContent("A");
    expect(avatar).toHaveClass(`bg-${defaultAvatarColor(USER_ID)}`);
  });

  it("5. ten do nguoi dung go: la CHU (khong HTML), cat bang truncate, mau da chon, tier la", async () => {
    const hostile = `<img src=x onerror="alert(1)">${"Nguyễn ".repeat(30)}`;
    renderAt(PATHS.home, { display_name: hostile, avatar_color: "avatar-3", tier_name: "pro" });
    const trigger = await accountTrigger(/Nguyễn/);

    expect(trigger.querySelector("img")).toBeNull();
    const name = within(trigger).getByText(hostile.trim());
    expect(name).toHaveClass("truncate");
    expect(name.parentElement).toHaveClass("min-w-0");
    expect(trigger).not.toHaveTextContent(EMAIL);
    expect(trigger.querySelector('[aria-hidden="true"]')).toHaveTextContent("<");
    expect(trigger.querySelector('[aria-hidden="true"]')).toHaveClass("bg-avatar-3");
    // Tier chua co nhan trong `vi.json` ⇒ nguyen ten goc.
    expect(trigger).toHaveTextContent("pro");
  });
});

describe("menu tai khoan (S10, §7b.2)", () => {
  it("6. dung thu tu bay menuitem, HAI separator; ba muc cho aria-disabled + B-264", async () => {
    const user = userEvent.setup();
    renderAt(PATHS.home);
    await openMenu(user);

    const menu = await screen.findByRole("menu", { name: "Menu tài khoản" });
    expect(menuSequence(menu)).toEqual(MENU_ORDER);
    expect(within(menu).getAllByRole("menuitem")).toHaveLength(6);
    expect(within(menu).getAllByRole("separator")).toHaveLength(2);

    const pending = within(menu)
      .getAllByRole("menuitem")
      .filter((item) => item.getAttribute("aria-disabled") === "true");
    expect(pending.map((item) => item.textContent)).toEqual(["Ngôn ngữ", "Trợ giúp", "Nâng cấp gói"]);
    for (const item of pending) {
      expect(item).toHaveAttribute("data-planned", "B-264");
      expect(item).toHaveClass("control-disabled");
      // `aria-disabled`, KHONG `disabled` cua Radix: Radix se dat `data-disabled`.
      expect(item).not.toHaveAttribute("data-disabled");
    }
    expect(within(menu).getByRole("menuitem", { name: "Cài đặt" })).toHaveAttribute("href", PATHS.settings);
    expect(within(menu).getByRole("menuitem", { name: "Mức sử dụng" })).toHaveAttribute(
      "href",
      PATHS.settingsUsage,
    );
  });

  it("7. bam muc cho: menu van mo, khong dieu huong, khong goi gi", async () => {
    const user = userEvent.setup();
    const { router } = renderAt(PATHS.home);
    await openMenu(user);
    for (const name of ["Ngôn ngữ", "Trợ giúp", "Nâng cấp gói"]) {
      await user.click(await screen.findByRole("menuitem", { name }));
      expect(screen.getByRole("menu", { name: "Menu tài khoản" })).toBeInTheDocument();
    }
    expect(router.state.location.pathname).toBe(PATHS.home);
    expect(api.logout).not.toHaveBeenCalled();
  });

  it("8. Cai dat → /cai-dat; Muc su dung → /cai-dat/muc-su-dung", async () => {
    const user = userEvent.setup();
    const { router } = renderAt(PATHS.home);
    await openMenu(user);
    await user.click(await screen.findByRole("menuitem", { name: "Mức sử dụng" }));
    await waitFor(() => expect(router.state.location.pathname).toBe(PATHS.settingsUsage));

    await act(() => router.navigate(PATHS.home));
    await openMenu(user);
    await user.click(await screen.findByRole("menuitem", { name: "Cài đặt" }));
    // ≥ 1024 px `/cai-dat` chuyen tiep sang tab Tai khoan (T-S.11).
    await waitFor(() => expect(router.state.location.pathname).toBe(PATHS.settingsAccount));
  });

  it("9. Dang xuat tu menu: goi `POST /auth/logout`, xoa phien, ve /dang-nhap", async () => {
    const user = userEvent.setup();
    const { router } = renderAt(PATHS.home);
    await openMenu(user);
    await user.click(await screen.findByRole("menuitem", { name: "Đăng xuất" }));

    await waitFor(() => expect(router.state.location.pathname).toBe(PATHS.login));
    expect(api.logout).toHaveBeenCalledTimes(1);
    // Phien da xoa: khong con khoi tai khoan, header khong con nut cho T-5.4.
    expect(screen.queryByRole("button", { name: new RegExp(escapeRegExp(EMAIL)) })).toBeNull();
    expect(screen.queryByRole("button", { name: "Mở panel artifact" })).toBeNull();
    expect(await screen.findByLabelText("Email")).toBeInTheDocument();
  });
});

describe("ban phim (DoD dong 2)", () => {
  it("10. Enter mo + tieu diem muc dau; mui ten di ca qua muc cho; Esc dong va tra tieu diem", async () => {
    const user = userEvent.setup();
    renderAt(PATHS.home);
    const trigger = await accountTrigger();

    act(() => trigger.focus());
    await user.keyboard("{Enter}");
    const menu = await screen.findByRole("menu", { name: "Menu tài khoản" });
    await waitFor(() => expect(within(menu).getByRole("menuitem", { name: "Cài đặt" })).toHaveFocus());
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{ArrowDown}");
    expect(within(menu).getByRole("menuitem", { name: "Mức sử dụng" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    const language = within(menu).getByRole("menuitem", { name: "Ngôn ngữ" });
    expect(language).toHaveFocus();
    // Muc cho toi duoc bang ban phim ⇒ tooltip "Sap co" mo (ly do cua aria-disabled).
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Sắp có");
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");
    expect(within(menu).getByRole("menuitem", { name: "Đăng xuất" })).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(within(menu).getByRole("menuitem", { name: "Nâng cấp gói" })).toHaveFocus();

    // Tieu diem dang o MUC CHO, tooltip dang mo (lop Radix tren cung): MOT lan
    // Esc van dong ca menu — `MenuDismissContext`.
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("11. Esc tu muc THUONG: dong menu, tieu diem ve khoi tai khoan; mo lai van duoc", async () => {
    const user = userEvent.setup();
    renderAt(PATHS.home);
    const trigger = await accountTrigger();

    act(() => trigger.focus());
    await user.keyboard("{ArrowDown}");
    const menu = await screen.findByRole("menu", { name: "Menu tài khoản" });
    await waitFor(() => expect(within(menu).getByRole("menuitem", { name: "Cài đặt" })).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    expect(trigger).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(await screen.findByRole("menu", { name: "Menu tài khoản" })).toBeInTheDocument();
  });
});

describe("drawer (< 1024 px)", () => {
  it("12. khoi tai khoan nam TRONG drawer; chon Cai dat thi drawer dong", async () => {
    narrowScreen();
    const user = userEvent.setup();
    const { router } = renderAt(PATHS.home);

    await user.click(await screen.findByRole("button", { name: "Mở thanh bên" }));
    const drawer = await screen.findByRole("dialog");
    const trigger = within(drawer).getByRole("button", { name: new RegExp(escapeRegExp(EMAIL)) });

    await user.click(trigger);
    const menu = await screen.findByRole("menu", { name: "Menu tài khoản" });
    expect(menuSequence(menu)).toEqual(MENU_ORDER);
    await user.click(within(menu).getByRole("menuitem", { name: "Cài đặt" }));
    await waitFor(() => expect(router.state.location.pathname).toBe(PATHS.settings));

    // Quay lai man chat: drawer KHONG tu bat lai (kho trang thai da ve `false`).
    await act(() => router.navigate(PATHS.home));
    await screen.findByRole("button", { name: "Mở thanh bên" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
