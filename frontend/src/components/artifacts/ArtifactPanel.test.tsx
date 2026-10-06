/**
 * Panel artifact — T-5.4 (DoD dong 1).
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

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
import { ANCHOR_STORAGE_KEY } from "../island/islandAnchor";
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
};

const TOKENS = ["--spacing-panel-right", "--spacing-panel-min", "--spacing-panel-max"] as const;

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

function renderChat() {
  vi.mocked(api.me).mockResolvedValue(PROFILE);
  const router = createMemoryRouter(routes, { initialEntries: [PATHS.home] });
  render(<RouterProvider router={router} />);
}

function island(): HTMLElement {
  return screen.getByRole("navigation", { name: "Điều hướng chính" });
}

/** jsdom khong thi hanh `inert`: nut cua lop DANG HIEN (thanh mo hoac sidebar doc). */
async function toggle(): Promise<HTMLElement> {
  await screen.findByRole("navigation", { name: "Điều hướng chính" });
  const buttons = within(island()).getAllByRole("button", { name: "Panel artifact" });
  const live = buttons.find((b) => b.closest('[data-active="true"]') !== null);
  return live ?? buttons[0];
}

/** Nut cua thanh mo (neo tren), du thanh dang hien hay `inert`. */
async function barToggle(): Promise<HTMLElement> {
  await screen.findByRole("navigation", { name: "Điều hướng chính" });
  const seeAll = within(island()).getByRole("button", { name: "Xem tất cả" });
  return within(seeAll.closest("[data-active]") as HTMLElement).getByRole("button", { name: "Panel artifact" });
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
  root.style.fontSize = "16px";
  vi.mocked(api.listModels).mockResolvedValue([]);
  vi.mocked(api.listConversations).mockResolvedValue({ items: [], next_cursor: null, truncated: false });
  vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [], byok_providers: [] });
  vi.mocked(api.listByokEndpoints).mockResolvedValue({ endpoints: [], max_endpoints: 3 });
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("style");
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

  it("4. neo hai ben: nut o chan sidebar doc mo / dong panel, Esc tra tieu diem ve chinh nut ay", async () => {
    localStorage.setItem(ANCHOR_STORAGE_KEY, "left");
    const user = userEvent.setup();
    renderChat();
    await waitFor(() => expect(island()).toHaveAttribute("data-shape", "side"));
    const sideButton = await toggle();
    expect(sideButton.closest('[data-active="true"]')).toHaveAttribute("data-anchor", "left");

    await user.click(sideButton);
    expect(sideButton).toHaveAttribute("aria-expanded", "true");
    act(() => within(panel() as HTMLElement).getByRole("button", { name: "Đóng panel artifact" }).focus());
    await user.keyboard("{Escape}");
    expect(panel()).toBeNull();
    await waitFor(() => expect(sideButton).toHaveFocus());
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

    await user.click(button);
    localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, "99999");
    await user.click(button);
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

    const dialog = screen.getByRole("dialog", { name: "Panel artifact" });
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
