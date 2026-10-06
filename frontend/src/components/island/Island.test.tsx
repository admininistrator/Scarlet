/**
 * Dao dieu huong + hop tim hoi thoai — T-S.19a (ban Khung chinh v3).
 *
 * jsdom khong co layout (Cam bay ② cua T-S.19a): test kiem TRANG THAI —
 * `data-shape`, `data-anchor`, `aria-expanded`, neo da luu, `inert` — khong kiem
 * toa do. Toa do la viec cua DoD tren Chrome.
 *
 * Ca nao thay ca nao cua header / sidebar / drawer cu da bi go (1 ↔ 1):
 *
 *   Sidebar 10a (an roi mount lai van an)        → 1  neo luu localStorage, mount lai van giu
 *   Sidebar 10b (localStorage nem)               → 2
 *   Drawer "Esc ⇒ dong, tieu diem ve nut mo"     → 3
 *   Drawer "Safari: nut khong nhan tieu diem"    → 3  (tieu diem ve nut mo du truoc do o dau)
 *   Drawer "cham ra ngoai ⇒ dong"                → 4
 *   Drawer "chon hoi thoai ⇒ mo VA dong"         → 5
 *   Drawer "bat dau DONG"                        → 6
 *   Drawer "≥ 1024 px: khong dialog, khong khoa cuon" → 6
 *   Sidebar 13 (dong = 0 px, khong nut nao)      → 6  (lop an mang `inert`)
 *   Motion "reduce ⇒ go ngay"                    → 10
 *   Motion "khong reduce ⇒ co hoat anh"          → 10
 *   Drawer "mo ⇒ khoa cuon phia sau"             — MAT: dao khong modal, khong lop phu
 *   Drawer "vo v2: nut X trong drawer"           — MAT: dao khong co nut X
 *
 * NQ-136: neo hai ben LUON la sidebar doc (khong con vien thuoc doc) — ca 1b,
 * 8 va 2b.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return { ...actual, api: { ...actual.api, listConversations: vi.fn() } };
});

import type { SessionState } from "../../features/auth/useSessionState";
import { api, type ConversationListQuery, type ConversationOut, type UserOut } from "../../lib/api";
import { ISLAND_COMPACT_QUERY } from "../../lib/motion";
import { AppIsland } from "./AppIsland";
import { ConversationSearch, filterConversations, type SearchConversation } from "./ConversationSearch";
import { DynamicIsland, type RecentConversation } from "./DynamicIsland";
import { ANCHOR_STORAGE_KEY } from "./islandAnchor";
import { step } from "./useIslandPhysics";

const USER: UserOut = {
  id: "7c3e9a51-2b6d-4f08-8e1a-9d4c2b7f6a30",
  email: "an.nguyen@scarlet.test",
  display_name: "Nguyễn Thị An",
  status: "active",
  role: "user",
  tier_name: "free",
  default_model: null,
  last_login_at: null,
};

const RECENT: RecentConversation[] = [
  { id: "r1", title: "Tóm tắt biên bản họp tuần 38", pinned: false, untitled: false },
  { id: "r2", title: "Quy trình nghỉ phép", pinned: true, untitled: false },
];

function inRouter(element: ReactNode, path = "/") {
  const router = createMemoryRouter([{ path: "*", element }], { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

function renderIsland(patch: Partial<Parameters<typeof DynamicIsland>[0]> = {}) {
  const onSelect = vi.fn();
  const onNewChat = vi.fn();
  inRouter(
    <>
      <button type="button">Ngoài đảo</button>
      <DynamicIsland
        context="chat"
        recent={RECENT}
        activeId={null}
        isAdmin={false}
        user={USER}
        avatarColor={null}
        onLogout={async () => {}}
        reconnecting={false}
        artifactPanel={{ open: false, onToggle: () => {}, focusRequest: 0 }}
        onNewChat={onNewChat}
        onSelect={onSelect}
        onOpenSearch={() => {}}
        sidebar={<div>noi dung sidebar</div>}
        {...patch}
      />
    </>,
  );
  return { onSelect, onNewChat };
}

function nav(): HTMLElement {
  return screen.getByRole("navigation", { name: "Điều hướng chính" });
}

/** Nut mo dao cua hinh dang hien (vien thuoc ngang hoac doc). */
function trigger(): HTMLElement {
  const buttons = within(nav()).getAllByRole("button", { name: /Mở menu điều hướng/ });
  return buttons.find((b) => b.closest("[inert]") === null) as HTMLElement;
}

function grips(): HTMLElement[] {
  return within(nav()).queryAllByRole("button", { name: "Di chuyển thanh điều hướng" });
}

/** Man hep: chi `ISLAND_COMPACT_QUERY` khop. */
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

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("dao — neo", () => {
  it("1. mac dinh neo tren; ⋮⋮ + ← sang trai, luu localStorage, tieu diem sang ⋮⋮ cua sidebar doc; ↑ ve tren; mount lai van giu", async () => {
    const user = userEvent.setup();
    renderIsland();
    expect(nav()).toHaveAttribute("data-anchor", "top");
    expect(nav()).toHaveAttribute("data-shape", "pill");

    const [barGrip, sideGrip] = grips();
    act(() => barGrip.focus());
    await user.keyboard("{ArrowLeft}");
    expect(nav()).toHaveAttribute("data-anchor", "left");
    expect(localStorage.getItem(ANCHOR_STORAGE_KEY)).toBe("left");
    expect(sideGrip).toHaveFocus();

    await user.keyboard("{ArrowUp}");
    expect(nav()).toHaveAttribute("data-anchor", "top");
    expect(barGrip).toHaveFocus();

    await user.keyboard("{ArrowRight}");
    expect(localStorage.getItem(ANCHOR_STORAGE_KEY)).toBe("right");
  });

  it("1b. neo da luu ⇒ mount lai (F5) van o neo ay, va hai ben thi MO SAN sidebar (NQ-136)", () => {
    localStorage.setItem(ANCHOR_STORAGE_KEY, "left");
    renderIsland();
    expect(nav()).toHaveAttribute("data-anchor", "left");
    expect(nav()).toHaveAttribute("data-shape", "side");
    expect(screen.getByText("noi dung sidebar").closest("[data-active]")).toHaveAttribute("data-active", "true");
  });

  it("2. `localStorage` nem (che do rieng tu) ⇒ neo tren, doi neo van chay, khong vo app", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("bi chan", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("bi chan", "SecurityError");
    });
    const user = userEvent.setup();
    renderIsland();
    expect(nav()).toHaveAttribute("data-anchor", "top");

    act(() => grips()[0].focus());
    await user.keyboard("{ArrowRight}");
    expect(nav()).toHaveAttribute("data-anchor", "right");
  });
});

describe("dao — mo / thu", () => {
  it("3. Esc thu lai va tra tieu diem ve nut mo dao", async () => {
    const user = userEvent.setup();
    renderIsland();
    const opener = trigger();
    await user.click(opener);
    expect(nav()).toHaveAttribute("data-shape", "bar");
    expect(opener).toHaveAttribute("aria-expanded", "true");

    act(() => within(nav()).getByRole("button", { name: "Xem tất cả" }).focus());
    await user.keyboard("{Escape}");
    expect(nav()).toHaveAttribute("data-shape", "pill");
    expect(document.activeElement).toBe(opener);
    expect(opener).toHaveAttribute("aria-expanded", "false");
  });

  it("4. cham / bam ra ngoai dao ⇒ thu lai", async () => {
    const user = userEvent.setup();
    renderIsland();
    await user.click(trigger());
    expect(nav()).toHaveAttribute("data-shape", "bar");

    fireEvent.pointerDown(screen.getByRole("button", { name: "Ngoài đảo" }));
    expect(nav()).toHaveAttribute("data-shape", "pill");
  });

  it("5. chon mot hoi thoai gan day ⇒ mo no VA thu lai; Hoi thoai moi cung vay", async () => {
    const user = userEvent.setup();
    const { onSelect, onNewChat } = renderIsland();
    await user.click(trigger());
    await user.click(within(nav()).getByRole("button", { name: "Tóm tắt biên bản họp tuần 38" }));
    expect(onSelect).toHaveBeenCalledWith("r1");
    expect(nav()).toHaveAttribute("data-shape", "pill");

    await user.click(trigger());
    await user.click(within(nav()).getByRole("button", { name: "Hội thoại mới" }));
    expect(onNewChat).toHaveBeenCalledTimes(1);
    expect(nav()).toHaveAttribute("data-shape", "pill");
  });

  it("6. bat dau THU; lop khong hien mang `inert`; khong dialog, khong khoa cuon", () => {
    renderIsland();
    const layers = Array.from(nav().querySelectorAll("[data-active]"));
    expect(layers).toHaveLength(4);
    for (const layer of layers) {
      const on = layer.getAttribute("data-active") === "true";
      expect(layer.hasAttribute("inert")).toBe(!on);
    }
    expect(layers.filter((l) => l.getAttribute("data-active") === "true")).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.style.overflow).toBe("");
  });
});

describe("dao — man hep, keo", () => {
  it("7. < 640 px: chi neo tren (neo trai da luu duoc GIU), khong ⋮⋮, keo khong doi hinh", async () => {
    compactScreen();
    localStorage.setItem(ANCHOR_STORAGE_KEY, "left");
    renderIsland();
    expect(nav()).toHaveAttribute("data-anchor", "top");
    expect(grips()).toHaveLength(0);

    fireEvent.pointerDown(nav(), { button: 0, clientX: 180, clientY: 40 });
    fireEvent.pointerMove(window, { clientX: 20, clientY: 400 });
    fireEvent.pointerUp(window);
    expect(nav()).toHaveAttribute("data-dragging", "false");
    expect(localStorage.getItem(ANCHOR_STORAGE_KEY)).toBe("left");
  });

  it("8. ≥ 640 px: keo qua nguong ⇒ vien tron; tha ben trai ⇒ neo trai", async () => {
    renderIsland();
    // Khung hinh dau cua vat ly da chay (lo xo co diem xuat phat).
    await waitFor(() => expect(nav().style.transform).not.toBe(""));

    fireEvent.pointerDown(nav(), { button: 0, clientX: 512, clientY: 40 });
    fireEvent.pointerMove(window, { clientX: 300, clientY: 300 });
    expect(nav()).toHaveAttribute("data-dragging", "true");
    expect(nav()).toHaveAttribute("data-shape", "orb");

    fireEvent.pointerMove(window, { clientX: 20, clientY: 400 });
    fireEvent.pointerUp(window);
    expect(nav()).toHaveAttribute("data-dragging", "false");
    expect(nav()).toHaveAttribute("data-anchor", "left");
    expect(nav()).toHaveAttribute("data-shape", "side");
    expect(localStorage.getItem(ANCHOR_STORAGE_KEY)).toBe("left");
  });
});

describe("dao — neo hai ben (NQ-136)", () => {
  it("2b. sidebar LUON mo: roi chuot, Esc, cham ra ngoai deu KHONG thu; ⋮⋮ + ↑ ve tren thi thanh mo, tieu diem o ⋮⋮ cua thanh", async () => {
    localStorage.setItem(ANCHOR_STORAGE_KEY, "right");
    const user = userEvent.setup();
    renderIsland();
    expect(nav()).toHaveAttribute("data-shape", "side");

    fireEvent.pointerEnter(nav(), { pointerType: "mouse" });
    fireEvent.pointerLeave(nav(), { pointerType: "mouse" });
    fireEvent.pointerDown(screen.getByRole("button", { name: "Ngoài đảo" }));
    const [barGrip, sideGrip] = grips();
    act(() => sideGrip.focus());
    await user.keyboard("{Escape}");
    await new Promise((resolve) => setTimeout(resolve, 20)); // qua han --duration-island-linger (0 trong jsdom)
    expect(nav()).toHaveAttribute("data-shape", "side");
    expect(sideGrip).toHaveFocus();

    await user.keyboard("{ArrowUp}");
    expect(nav()).toHaveAttribute("data-anchor", "top");
    expect(nav()).toHaveAttribute("data-shape", "bar");
    expect(barGrip).toHaveFocus();
  });
});

describe("dao — muc cho", () => {
  it("9. Kien thuc (B-06) la nut cho aria-disabled; bam khong lam gi", async () => {
    const user = userEvent.setup();
    const { onSelect, onNewChat } = renderIsland();
    const knowledge = within(nav()).getByRole("button", { name: "Kiến thức" });
    expect(knowledge).toHaveAttribute("aria-disabled", "true");
    expect(knowledge).toHaveAttribute("data-planned", "B-06");

    await user.click(trigger());
    await user.click(knowledge);
    expect(onSelect).not.toHaveBeenCalled();
    expect(onNewChat).not.toHaveBeenCalled();
  });

  it("9b. ngoai man chat (NQ-128 c): khong co nut panel artifact", () => {
    renderIsland({ context: "settings", artifactPanel: undefined });
    expect(within(nav()).queryByRole("button", { name: "Panel artifact" })).toBeNull();
  });
});

describe("dao — giam chuyen dong", () => {
  const rect = (x: number) => ({ x, y: x, w: x, h: x, r: x });
  const springState = () => ({
    x: { x: 0, v: 0 },
    y: { x: 0, v: 0 },
    w: { x: 0, v: 0 },
    h: { x: 0, v: 0 },
    r: { x: 0, v: 0 },
  });

  it("10. lo xo `null` (reduce) ⇒ MOT buoc toi dich, khong khung trung gian; co lo xo ⇒ co khung trung gian", () => {
    const reduced = springState();
    step(reduced, rect(100), null, 1 / 60);
    expect(reduced.x.x).toBe(100);
    expect(reduced.x.v).toBe(0);

    const moving = springState();
    step(moving, rect(100), { stiffness: 260, damping: 22 }, 1 / 60);
    expect(moving.x.x).toBeGreaterThan(0);
    expect(moving.x.x).toBeLessThan(100);
  });
});

// ──────────────────────────────── hop tim ────────────────────────────────

const ITEMS: SearchConversation[] = [
  { id: "p1", title: "Quy trình nghỉ phép", pinned: true, group: "Đã ghim" },
  { id: "a", title: "Tóm tắt biên bản họp tuần 38", pinned: false, group: "Hôm nay" },
  { id: "b", title: "Hạn mức quota", pinned: false, group: "Hôm nay" },
  { id: "c", title: "Soạn email mời họp quý IV", pinned: false, group: "Hôm qua" },
];

function renderSearch(conversations: SearchConversation[] | null = ITEMS) {
  const onPick = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <ConversationSearch open onOpenChange={onOpenChange} conversations={conversations} error={null} onPick={onPick} />,
  );
  return { onPick, onOpenChange, input: screen.getByRole("combobox", { name: "Tìm hội thoại" }) };
}

describe("hop tim hoi thoai", () => {
  it("11. khong dau: 'hop' khop 'họp', to dam dung chu goc; giu nhom ngay", async () => {
    const user = userEvent.setup();
    const { input } = renderSearch();
    await user.type(input, "hop");

    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Tóm tắt biên bản họp tuần 38", "Soạn email mời họp quý IV"]);
    expect(options[0].querySelector("mark")).toHaveTextContent("họp");
    expect(screen.getAllByRole("group").map((g) => g.firstChild?.textContent)).toEqual(["Hôm nay", "Hôm qua"]);
    expect(filterConversations(ITEMS, "HAN MUC").flat.map((r) => r.id)).toEqual(["b"]);
  });

  it("12. ↑ ↓ doi muc (aria-activedescendant), Enter mo dung hoi thoai va dong hop", async () => {
    const user = userEvent.setup();
    const { input, onPick, onOpenChange } = renderSearch();
    act(() => input.focus());
    const selected = () => screen.getAllByRole("option").find((o) => o.getAttribute("aria-selected") === "true");

    expect(selected()).toHaveTextContent("Quy trình nghỉ phép");
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(selected()).toHaveTextContent("Hạn mức quota");
    expect(input).toHaveAttribute("aria-activedescendant", selected()?.id);
    await user.keyboard("{ArrowUp}");
    expect(selected()).toHaveTextContent("Tóm tắt biên bản họp tuần 38");

    await user.keyboard("{Enter}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onPick).toHaveBeenCalledWith("a");
  });

  it("13. khong khop ⇒ 'Khong tim thay'; dang nap (`null`) ⇒ chua bao rong", async () => {
    const user = userEvent.setup();
    const { input } = renderSearch();
    await user.type(input, "hợp đồng thuê văn phòng");
    expect(await screen.findByText("Không tìm thấy hội thoại nào")).toBeInTheDocument();
    expect(screen.queryAllByRole("option")).toHaveLength(0);
  });

  it("13b. dang nap ⇒ khong option, khong bao rong", () => {
    renderSearch(null);
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.queryByText("Không tìm thấy hội thoại nào")).toBeNull();
  });
});

// ─────────────────────── AppIsland: Ctrl K + moi trang ───────────────────────

function conversation(id: string, title: string, patch: Partial<ConversationOut> = {}): ConversationOut {
  return {
    id,
    title,
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: null,
    pinned: false,
    created_at: "2026-09-20T01:00:00Z",
    updated_at: "2026-09-20T01:00:00Z",
    ...patch,
  };
}

describe("AppIsland — Ctrl K", () => {
  const SESSION = {
    user: USER,
    profile: null,
    logout: vi.fn(async () => {}),
  } as unknown as SessionState;

  beforeEach(() => {
    vi.mocked(api.listConversations).mockImplementation(async (query: ConversationListQuery) => {
      if (query.pinned) {
        return { items: [conversation("p1", "Quy trình nghỉ phép", { pinned: true })], next_cursor: null, truncated: false };
      }
      if (query.updatedBefore === "c1") {
        return { items: [conversation("old", "Ghi chú cũ về hạn mức")], next_cursor: null, truncated: false };
      }
      return {
        items: [conversation("a", "Tóm tắt biên bản họp", { updated_at: "2026-09-21T01:00:00Z" })],
        next_cursor: "c1",
        truncated: false,
      };
    });
  });

  it("14. Ctrl K mo hop; hoi thoai o TRANG 2 cung tim ra; Enter sang /?c=<id>", async () => {
    const user = userEvent.setup();
    const router = inRouter(<AppIsland session={SESSION} context="settings" />, "/cai-dat/tai-khoan");
    await user.keyboard("{Control>}k{/Control}");

    const input = await screen.findByRole("combobox", { name: "Tìm hội thoại" });
    await user.type(input, "chu cu");
    await screen.findByRole("option", { name: /Ghi chú cũ/ });
    await user.keyboard("{Enter}");

    await waitFor(() => expect(router.state.location.search).toBe("?c=old"));
    expect(router.state.location.pathname).toBe("/");
    expect(api.listConversations).toHaveBeenCalledWith({ pinned: false, updatedBefore: "c1" });
  });

  it("15. Esc dong hop va tra tieu diem ve cho da mo", async () => {
    const user = userEvent.setup();
    inRouter(
      <>
        <button type="button">Ngoài đảo</button>
        <AppIsland session={SESSION} context="admin" />
      </>,
      "/admin",
    );
    const outside = screen.getByRole("button", { name: "Ngoài đảo" });
    act(() => outside.focus());
    await user.keyboard("{Control>}k{/Control}");
    await screen.findByRole("dialog");

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(outside).toHaveFocus();
  });
});
