/**
 * Sidebar dang drawer duoi 1024 px — T-3.10, ban T-HD2.
 *
 * KH tham chieu: §2.3 (S8) · tasks.md T-3.10 (DoD dong 3).
 *
 * DoD doi hai tinh chat, va file nay do dung hai tinh chat ay bang HANH VI,
 * khong bang ten class:
 *
 *   1. Mo drawer ⇒ noi dung phia sau KHONG cuon duoc. jsdom khong cuon gi ca,
 *      nen phep do la: mot cu `wheel`/`touchmove` roi vao mot vung cuon PHIA
 *      SAU drawer bi huy (`defaultPrevented`). Do la dung thu trinh duyet
 *      dung de quyet dinh co cuon hay khong. Ca doi chung: drawer dong ⇒
 *      cung cu `wheel` ay KHONG bi huy — khong co no thi mot phep kiem huy
 *      MOI su kien cung xanh.
 *   2. `Esc` ⇒ drawer dong VA tieu diem ve nut mo. Ca "Safari": mo drawer ma
 *      nut KHONG nhan tieu diem truoc (Safari khong focus `<button>` khi bam
 *      chuot) — tieu diem van phai ve nut, khong roi ve `<body>`.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listConversations: vi.fn(),
      updateConversation: vi.fn(),
      deleteConversation: vi.fn(),
    },
  };
});

import { api, type ConversationOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { DRAWER_QUERY } from "../../lib/viewport";
import { Sidebar } from "./Sidebar";
import { SidebarToggle } from "./SidebarToggle";
import { SIDEBAR_TOGGLE_ID, resetSidebarOpenForTest } from "./sidebarOpen";

function stubViewport(drawer: boolean): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === DRAWER_QUERY ? drawer : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

const CONVERSATION: ConversationOut = {
  id: "c-1",
  title: "Han muc quota",
  default_model: null,
  system_prompt_override: null,
  active_leaf_id: null,
  pinned: false,
  created_at: "2026-09-01T00:00:00+00:00",
  updated_at: "2026-09-01T00:00:00+00:00",
};

/**
 * Header (nut that) + sidebar + mot cot cuon duoc dong vai man chat — dung
 * thu tu cua `Layout` + `ChatScreen`.
 */
function renderShell(onSelect = vi.fn()) {
  render(
    <>
      <SidebarToggle />
      <Sidebar
        openConversationId={null}
        onSelect={onSelect}
        onNewChat={vi.fn()}
        onOpenConversationDeleted={vi.fn()}
      />
      <main data-testid="behind" style={{ overflowY: "auto", height: "100px" }}>
        <p>tin nhan</p>
      </main>
    </>,
  );
  return {
    toggle: document.getElementById(SIDEBAR_TOGGLE_ID) as HTMLButtonElement,
    behind: screen.getByTestId("behind"),
  };
}

/** Mot cu cuon len vung `target`; tra `true` neu trinh duyet se KHONG cuon. */
function scrollIsBlocked(target: Element): boolean {
  const wheel = new WheelEvent("wheel", { deltaY: 120, bubbles: true, cancelable: true });
  act(() => {
    target.dispatchEvent(wheel);
  });
  return wheel.defaultPrevented;
}

beforeEach(() => {
  localStorage.clear();
  resetSidebarOpenForTest();
  vi.mocked(api.listConversations).mockResolvedValue({ items: [CONVERSATION], next_cursor: null, truncated: false });
});

describe("Drawer duoi 1024 px", () => {
  it("bat dau DONG, ke ca khi desktop da nho 'mo' — va khong co cot nao day bo cuc", async () => {
    stubViewport(true);
    renderShell();
    // Sidebar van nap trang dau khi drawer dong (de mo ra la co ngay); cho no
    // ve xong de khong co cap nhat state nao roi ra ngoai `act`.
    await waitFor(() => expect(api.listConversations).toHaveBeenCalled());
    await act(async () => {});

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: t("sidebar.title") })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("header.openSidebar") })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("mo drawer ⇒ noi dung phia sau KHONG cuon duoc; dong ⇒ cuon lai duoc", async () => {
    stubViewport(true);
    const user = userEvent.setup();
    const { toggle, behind } = renderShell();

    expect(scrollIsBlocked(behind)).toBe(false);

    await user.click(toggle);
    const dialog = await screen.findByRole("dialog", { name: t("sidebar.title") });
    await screen.findByText("Han muc quota");
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    expect(scrollIsBlocked(behind)).toBe(true);
    const touch = new Event("touchmove", { bubbles: true, cancelable: true });
    act(() => {
      behind.dispatchEvent(touch);
    });
    expect(touch.defaultPrevented).toBe(true);
    // Noi dung phia sau cung bi an khoi cay truy cap, khong chi khoi chuot.
    expect(behind.closest('[aria-hidden="true"]')).not.toBeNull();
    expect(dialog).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(scrollIsBlocked(behind)).toBe(false);
  });

  it("Esc ⇒ dong va tieu diem ve nut mo", async () => {
    stubViewport(true);
    const user = userEvent.setup();
    const { toggle } = renderShell();

    await user.click(toggle);
    await screen.findByRole("dialog");
    // Tieu diem da vao TRONG drawer (bay tieu diem cua Radix).
    expect(screen.getByRole("dialog")).toContainElement(document.activeElement as HTMLElement);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("ca Safari: nut KHONG nhan tieu diem luc mo — Esc van tra tieu diem ve nut", async () => {
    stubViewport(true);
    const user = userEvent.setup();
    const { toggle } = renderShell();

    // `fireEvent.click` khong focus nut, dung nhu Safari bam chuot.
    fireEvent.click(toggle);
    await screen.findByRole("dialog");
    expect(document.activeElement).not.toBe(toggle);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(toggle);
  });

  it("cham ra ngoai (lop nen mo) ⇒ dong va tieu diem ve nut mo", async () => {
    stubViewport(true);
    const user = userEvent.setup();
    const { toggle } = renderShell();

    await user.click(toggle);
    await screen.findByRole("dialog");

    // Lop phu nam ngoai `Dialog.Content`; Radix dong khi mot cu cham tron
    // (`pointerdown` roi `click`) roi ra ngoai noi dung. `userEvent` tu choi
    // bam vi Radix dat `pointer-events: none` len `<body>` — chinh la dieu
    // ngan cu cham xuyen xuong man chat phia sau.
    const scrim = document.querySelector(".bg-scrim");
    expect(scrim).not.toBeNull();
    await act(async () => {
      // Radix gan bo nghe `pointerdown` sau mot nhip (`setTimeout(0)`) de
      // chinh cu bam MO khong dong lai drawer.
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    fireEvent.pointerDown(scrim as Element, { button: 0 });
    fireEvent.click(scrim as Element, { button: 0 });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(toggle);
  });

  /**
   * T-S.13 (B-307) — vo drawer v2, ban T-HD2-v2 F/F′: KHONG thanh tieu de 56 px;
   * chi mot nut X 44 × 44 trong vung dem, goc tren-phai. Drawer van co ten cho
   * trinh doc man hinh (`Dialog.Title` sr-only).
   */
  it("vo v2: khong thanh tieu de nhin thay, nut X trong drawer dong no va tra tieu diem ve nut mo", async () => {
    stubViewport(true);
    const user = userEvent.setup();
    const { toggle } = renderShell();

    await user.click(toggle);
    const dialog = await screen.findByRole("dialog", { name: t("sidebar.title") });
    expect(within(dialog).getByText(t("sidebar.title"))).toHaveClass("sr-only");

    const close = within(dialog).getByRole("button", { name: t("header.closeSidebar") });
    // Nut X nam TRONG `<nav>` (vung dem p-3), dung truoc "Hoi thoai moi".
    const nav = within(dialog).getByRole("navigation", { name: t("sidebar.title") });
    expect(nav.firstElementChild).toBe(close);
    expect(close).toHaveClass("self-end", "size-touch");

    await user.click(close);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(toggle);
  });

  it("chon mot hoi thoai trong drawer ⇒ mo no VA dong drawer", async () => {
    stubViewport(true);
    const onSelect = vi.fn();
    const user = userEvent.setup();
    const { toggle } = renderShell(onSelect);

    await user.click(toggle);
    await user.click(await screen.findByRole("button", { name: "Han muc quota" }));

    expect(onSelect).toHaveBeenCalledWith("c-1");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("Tu 1024 px tro len — van la cot, khong phai drawer", () => {
  it("khong co dialog, khong khoa cuon", async () => {
    stubViewport(false);
    const { behind } = renderShell();

    await screen.findByText("Han muc quota");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: t("sidebar.title") })).toBeInTheDocument();
    expect(scrollIsBlocked(behind)).toBe(false);
  });
});
