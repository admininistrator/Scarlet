/**
 * Panel artifact — T-5.4 (DoD dong 1); khung ve lai theo ban T-HD6 o T-5.5
 * (nut ⑨, quy tac 640–1279, dao can giua cot chat — ca 4, 10–12).
 *
 * Dung BANG ROUTE THAT + `useSessionState` THAT, chi lop `api` bi thay (cung
 * khuon `AccountMenu.test.tsx`): nut o dao, panel o `ChatScreen`, tra tieu diem
 * qua `pendingFocus` cua dao — ba noi, mot luong.
 *
 * jsdom khong co layout (Cam bay ①): kep va be rong kiem bang `aria-valuenow`
 * va `style.width`; toa do that la viec cua DoD tren Chrome. jsdom cung khong
 * nap `theme.css`, nen ba token be rong duoc chep tu `theme.css?raw` vao `:root`
 * — so trong test la so cua token, khong phai so go tay.
 */

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
      listModels: vi.fn(),
      listConversations: vi.fn(),
      listProviderKeys: vi.fn(),
      listByokEndpoints: vi.fn(),
    },
  };
});

import { PATHS } from "../../app/paths";
import { routes } from "../../app/routes";
import { api, type ProfileOut } from "../../lib/api";
import { ISLAND_COMPACT_QUERY } from "../../lib/motion";
import themeCss from "../../styles/theme.css?raw";
import { ANCHOR_STORAGE_KEY, islandRightInset } from "../island/islandAnchor";
import { PANEL_WIDTH_STORAGE_KEY } from "./ArtifactPanel";

const PROFILE: ProfileOut = {
  id: "7c3e9a51-2b6d-4f08-8e1a-9d4c2b7f6a30",
  email: "an.nguyen@scarlet.test",
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "free",
  default_model: null,
  last_login_at: "2026-10-07T01:00:00Z",
  quota: null,
  message_max_chars: 24000,
  quota_warn_remaining_pct: 20,
  limits_cache_ttl_s: 60,
  stream_ttl_s: 3600,
  display_name_max_chars: 64,
  avatar_color: null,
  reasoning_prefs: {},
  max_upload_mb: 10,
  max_attachments: 5,
  allowed_upload_mime: ["image/png"],
  can_use_web: true,
  can_execute_skills: false,
  web_searches_per_day: 50,
  web_searches_used: 0,
};

const TOKENS = [
  "--spacing-panel-right",
  "--spacing-panel-min",
  "--spacing-panel-max",
  "--spacing-island-gap",
  "--spacing-sidebar",
  "--spacing-min",
] as const;

/** Token (rem) cua `theme.css` → px, voi co chu goc cua trinh duyet. */
function tokenPx(name: string): number {
  const match = new RegExp(`${name}:\\s*([\\d.]+)rem`).exec(themeCss);
  if (match === null) {
    throw new Error(`thieu ${name} trong theme.css`);
  }
  return Number.parseFloat(match[1]) * 16;
}

const DEFAULT = tokenPx("--spacing-panel-right");
const MIN = tokenPx("--spacing-panel-min");
const MAX = tokenPx("--spacing-panel-max");
/** `--spacing-panel-gap` la bi danh cua `--spacing-island-gap` (theme.css, khoi ARTIFACT). */
const GAP = tokenPx("--spacing-island-gap");
const SIDEBAR = GAP + tokenPx("--spacing-sidebar");
const CHAT_MIN = tokenPx("--spacing-min");

function renderChat() {
  vi.mocked(api.me).mockResolvedValue(PROFILE);
  const router = createMemoryRouter(routes, { initialEntries: [PATHS.home] });
  render(<RouterProvider router={router} />);
}

/** Be rong cua so cua jsdom (mac dinh 1024) — `resize` cho `useViewportWidth`. */
function viewport(width: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  window.dispatchEvent(new Event("resize"));
}

function island(): HTMLElement {
  return screen.getByRole("navigation", { name: "Điều hướng chính" });
}

/** Nut cua thanh mo (neo tren), du thanh dang hien hay `inert`. */
async function barToggle(): Promise<HTMLElement> {
  await screen.findByRole("navigation", { name: "Điều hướng chính" });
  const seeAll = within(island()).getByRole("button", { name: "Xem tất cả" });
  return within(seeAll.closest("[data-active]") as HTMLElement).getByRole("button", { name: "Panel artifact" });
}

/** Nut ⑨ (neo hai ben): nut panel NGOAI dao, o goc cot chat. */
async function corner(): Promise<HTMLElement> {
  await screen.findByRole("navigation", { name: "Điều hướng chính" });
  const outside = screen.getAllByRole("button", { name: "Panel artifact" }).filter((b) => !island().contains(b));
  expect(outside).toHaveLength(1);
  return outside[0];
}

function panel(): HTMLElement | null {
  return document.getElementById("artifact-panel");
}

function separator(): HTMLElement {
  return screen.getByRole("separator", { name: "Đổi bề rộng panel artifact" });
}

function compactScreen() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === ISLAND_COMPACT_QUERY,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

async function openPanel(user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> {
  const button = await barToggle();
  act(() => button.focus());
  await user.click(button);
  await waitFor(() => expect(panel()).not.toBeNull());
  return button;
}

beforeEach(() => {
  localStorage.clear();
  const root = document.documentElement;
  for (const name of TOKENS) {
    root.style.setProperty(name, `${tokenPx(name) / 16}rem`);
  }
  root.style.setProperty("--spacing-panel-gap", `${GAP / 16}rem`);
  root.style.fontSize = "16px";
  vi.mocked(api.listModels).mockResolvedValue([]);
  vi.mocked(api.listConversations).mockResolvedValue({ items: [], next_cursor: null, truncated: false });
  vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [], byok_providers: [] });
  vi.mocked(api.listByokEndpoints).mockResolvedValue({ endpoints: [], max_endpoints: 3 });
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("style");
  viewport(1024);
});

describe("panel artifact — dong / mo", () => {
  it("1. nut dao mo / dong panel: aria-expanded, aria-controls, trang thai trong; khong con nut cho T-5.4", async () => {
    const user = userEvent.setup();
    renderChat();
    const button = await barToggle();
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("aria-controls", "artifact-panel");
    expect(button).not.toHaveAttribute("aria-disabled");
    expect(document.querySelector('[data-planned="T-5.4"]')).toBeNull();
    expect(panel()).toBeNull();

    await openPanel(user);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(panel()).toBe(screen.getByRole("complementary", { name: "Panel artifact" }));
    expect(within(panel() as HTMLElement).getByText("Chưa mở artifact nào")).toBeInTheDocument();

    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(panel()).toBeNull();
  });

  it("2. Esc trong panel ⇒ dong, tieu diem ve nut mo — ke ca khi dao da thu (nut trong lop inert, B-323 ④)", async () => {
    const user = userEvent.setup();
    renderChat();
    await openPanel(user);
    const close = within(panel() as HTMLElement).getByRole("button", { name: "Đóng panel artifact" });
    // Con tro + tieu diem roi dao ⇒ dao thu ve vien thuoc; nut panel nay o lop `inert`.
    await user.hover(close);
    act(() => close.focus());
    await waitFor(() => expect(island()).toHaveAttribute("data-shape", "pill"));

    await user.keyboard("{Escape}");
    expect(panel()).toBeNull();
    const button = await barToggle();
    await waitFor(() => expect(button).toHaveFocus());
    expect(island()).toHaveAttribute("data-shape", "bar");
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("3. nut X trong panel ⇒ dong, tieu diem ve nut mo", async () => {
    const user = userEvent.setup();
    renderChat();
    await openPanel(user);
    await user.click(within(panel() as HTMLElement).getByRole("button", { name: "Đóng panel artifact" }));
    expect(panel()).toBeNull();
    await waitFor(async () => expect(await barToggle()).toHaveFocus());
  });

  it("4. neo hai ben: nut ⑨ o cot chat (NGOAI dao, chan sidebar khong con nut) mo / dong panel, Esc tra tieu diem ve chinh nut ay", async () => {
    localStorage.setItem(ANCHOR_STORAGE_KEY, "left");
    const user = userEvent.setup();
    renderChat();
    await waitFor(() => expect(island()).toHaveAttribute("data-shape", "side"));
    // Lop sidebar doc dang hien KHONG con nut (thanh mo an van giu nut cua no — jsdom khong thi hanh `inert`).
    const sideLayer = island().querySelector('[data-active="true"]') as HTMLElement;
    expect(sideLayer).toHaveAttribute("data-anchor", "left");
    expect(within(sideLayer).queryByRole("button", { name: "Panel artifact" })).toBeNull();
    const button = await corner();
    expect(button.closest(".island-glass")).not.toBeNull();
    expect(button).toHaveAttribute("aria-controls", "artifact-panel");

    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(panel()).toHaveAttribute("data-anchor", "left");
    act(() => within(panel() as HTMLElement).getByRole("button", { name: "Đóng panel artifact" }).focus());
    await user.keyboard("{Escape}");
    expect(panel()).toBeNull();
    await waitFor(() => expect(button).toHaveFocus());
    expect(island()).toHaveAttribute("data-shape", "side");
  });
});

describe("panel artifact — be rong", () => {
  it("5. tay nam: separator doc, aria-valuenow/min/max theo token; mui ten doi va kep trong [min, max]", async () => {
    const user = userEvent.setup();
    renderChat();
    await openPanel(user);
    const handle = separator();
    expect(handle).toHaveAttribute("aria-orientation", "vertical");
    expect(handle).toHaveAttribute("aria-valuenow", String(DEFAULT));
    expect(handle).toHaveAttribute("aria-valuemin", String(MIN));
    expect(handle).toHaveAttribute("aria-valuemax", String(MAX));
    expect(panel()?.style.width).toBe(`${DEFAULT}px`);

    act(() => handle.focus());
    await user.keyboard("{ArrowLeft}");
    const wider = Number(handle.getAttribute("aria-valuenow"));
    expect(wider).toBeGreaterThan(DEFAULT);
    await user.keyboard("{ArrowRight}");
    expect(handle).toHaveAttribute("aria-valuenow", String(DEFAULT));

    for (let i = 0; i < 40; i += 1) {
      await user.keyboard("{ArrowLeft}");
    }
    expect(handle).toHaveAttribute("aria-valuenow", String(MAX));
    for (let i = 0; i < 40; i += 1) {
      await user.keyboard("{ArrowRight}");
    }
    expect(handle).toHaveAttribute("aria-valuenow", String(MIN));
    expect(panel()?.style.width).toBe(`${MIN}px`);
  });

  it("6. keo bang su kien pointer ⇒ kep: 300 px sang trai ⇒ max, 300 px sang phai ⇒ min; tha tay moi ghi", async () => {
    const user = userEvent.setup();
    renderChat();
    await openPanel(user);
    const handle = separator();

    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 1000 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 900 });
    expect(handle).toHaveAttribute("aria-valuenow", String(DEFAULT + 100));
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 700 });
    expect(handle).toHaveAttribute("aria-valuenow", String(MAX));
    expect(localStorage.getItem(PANEL_WIDTH_STORAGE_KEY)).toBeNull();
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 700 });
    expect(localStorage.getItem(PANEL_WIDTH_STORAGE_KEY)).toBe(String(MAX));

    fireEvent.pointerDown(handle, { button: 0, pointerId: 2, clientX: 700 });
    fireEvent.pointerMove(handle, { pointerId: 2, clientX: 1000 });
    fireEvent.pointerUp(handle, { pointerId: 2, clientX: 1000 });
    expect(handle).toHaveAttribute("aria-valuenow", String(MIN));
    expect(panel()?.style.width).toBe(`${MIN}px`);

    // Di chuot khi KHONG giu: khong doi gi.
    fireEvent.pointerMove(handle, { pointerId: 3, clientX: 100 });
    expect(handle).toHaveAttribute("aria-valuenow", String(MIN));
  });

  it("7. be rong nho qua lan mount (dong roi mo lai); so da luu ngoai [min, max] bi kep", async () => {
    const user = userEvent.setup();
    renderChat();
    const button = await openPanel(user);
    act(() => separator().focus());
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    const kept = separator().getAttribute("aria-valuenow");
    expect(Number(kept)).toBeGreaterThan(DEFAULT);

    await user.click(button);
    expect(panel()).toBeNull();
    await user.click(button);
    expect(separator()).toHaveAttribute("aria-valuenow", kept);

    // Mount MOI (tai lai trang): so da luu ngoai khoang bi kep.
    localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, "99999");
    cleanup();
    renderChat();
    await openPanel(user);
    expect(separator()).toHaveAttribute("aria-valuenow", String(MAX));
  });

  it("8. localStorage nem ⇒ van mo duoc, be rong mac dinh, keo khong vo", async () => {
    localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(MAX));
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const user = userEvent.setup();
    renderChat();
    await openPanel(user);
    const handle = separator();
    expect(handle).toHaveAttribute("aria-valuenow", String(DEFAULT));
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 500 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 480 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 480 });
    expect(handle).toHaveAttribute("aria-valuenow", String(DEFAULT + 20));
  });
});

describe("panel artifact — < 640 px", () => {
  it("9. matchMedia < 640 px ⇒ dialog toan man hinh, khong tay nam; co nut dong; Esc dong va tra tieu diem ve nut", async () => {
    compactScreen();
    const user = userEvent.setup();
    renderChat();
    const button = await openPanel(user);

    // Ten = tieu de dau panel (ban T-HD6: "Artifact" khi chua mo artifact nao).
    const dialog = screen.getByRole("dialog", { name: "Artifact" });
    expect(dialog).toBe(panel());
    expect(dialog.className).toContain("inset-0");
    expect(screen.queryByRole("separator", { name: "Đổi bề rộng panel artifact" })).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Panel artifact" })).toBeNull();
    const close = within(dialog).getByRole("button", { name: "Đóng panel artifact" });
    expect(close.tabIndex).toBe(0);

    await user.keyboard("{Escape}");
    expect(panel()).toBeNull();
    await waitFor(() => expect(button).toHaveFocus());
    expect(button).toHaveAttribute("aria-expanded", "false");
  });
});

describe("panel artifact — khung T-HD6 (T-5.5)", () => {
  it("10. 1024 neo trai, da keo 560 ⇒ day cot chat, kep 361 (cot chat 375); localStorage van 560; rong lai ⇒ 560; neo phai ⇒ hop truoc sidebar", async () => {
    localStorage.setItem(ANCHOR_STORAGE_KEY, "left");
    localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(MAX));
    const user = userEvent.setup();
    renderChat();
    await user.click(await corner());
    const cap = 1024 - SIDEBAR - GAP - CHAT_MIN;
    expect(cap).toBe(361);
    const handle = separator();
    expect(handle).toHaveAttribute("aria-valuenow", String(cap));
    expect(handle).toHaveAttribute("aria-valuemax", String(cap));
    expect(panel()).toHaveAttribute("data-mode", "push");
    expect(localStorage.getItem(PANEL_WIDTH_STORAGE_KEY)).toBe(String(MAX));
    act(() => handle.focus());
    await user.keyboard("{ArrowLeft}");
    expect(handle).toHaveAttribute("aria-valuenow", String(cap));

    // Cua so rong lai ⇒ ve dung be rong da luu (kep KHONG ghi de localStorage).
    localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(MAX));
    cleanup();
    renderChat();
    act(() => viewport(1440));
    await user.click(await corner());
    expect(separator()).toHaveAttribute("aria-valuenow", String(MAX));

    localStorage.setItem(ANCHOR_STORAGE_KEY, "right");
    cleanup();
    renderChat();
    await user.click(await corner());
    expect(panel()).toHaveAttribute("data-anchor", "right");
    expect(panel()?.className).toContain(
      "data-[anchor=right]:right-[calc(var(--spacing-island-gap)_+_var(--spacing-sidebar)_+_var(--spacing-panel-gap))]",
    );
  });

  it("11. neo tren 700 px ⇒ hop de len cot chat (o dem 0), tran = min(max, man − 2 le); 1024 ⇒ o dem = panel + le", async () => {
    const user = userEvent.setup();
    act(() => viewport(700));
    renderChat();
    await openPanel(user);
    const spacer = panel()?.previousElementSibling as HTMLElement;
    expect(panel()).toHaveAttribute("data-mode", "overlay");
    expect(spacer.style.width).toBe("0px");
    expect(separator()).toHaveAttribute("aria-valuemax", String(Math.min(MAX, 700 - 2 * GAP)));

    act(() => viewport(1024));
    expect(panel()).toHaveAttribute("data-mode", "push");
    expect(spacer.style.width).toBe(`${DEFAULT + GAP}px`);
    expect(spacer).toHaveAttribute("data-panel", "open");
  });

  it("12. ban T-HD6 ⑦: neo tren mo panel ⇒ dao biet cot chat ngan di dung panel + le; dong ⇒ 0", async () => {
    const user = userEvent.setup();
    renderChat();
    const button = await openPanel(user);
    expect(islandRightInset()).toBe(DEFAULT + GAP);
    await user.click(button);
    expect(panel()).toBeNull();
    expect(islandRightInset()).toBe(0);
  });
});
