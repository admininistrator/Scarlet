/**
 * Sidebar hoi thoai — DoD dong 1 cua T-3.3, tren ban T-HD2.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOI CA O DAY LA MOT DONG DoD HOAC MOT CAM BAY CUA TASK                ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Khong co ca nao kiem "component co render khong". Danh sach:
 *
 *   1. `next_cursor: null` ⇒ **khong** goi trang ke (DoD dong 1)
 *   2. `next_cursor` co gia tri ⇒ goi dung `?updated_before=<con tro>`
 *   3. Hai trang noi nhau ⇒ **khong hoi thoai nao xuat hien hai lan** (DoD
 *      dong 3, va Cam bay ②)
 *   4. Xoa ⇒ **mat khoi danh sach ngay**, khong doi mot lan tai lai (DoD
 *      dong 1)
 *   5. Xoa hoi thoai DANG MO ⇒ man chat duoc bao (`onOpenConversationDeleted`)
 *   6. Tim kiem loc dung va **khong goi mang** (DoD dong 1)
 *   7. Tim kiem bo dau: go khong dau van tim ra tieu de co dau
 *   8. Ghim ⇒ `PATCH {pinned: true}` va hang do nhay sang nhom "Da ghim"
 *      (DoD dong 4)
 *   9. Doi ten ⇒ `PATCH {title}`; de trong ⇒ `PATCH {title: null}`
 *  10. An/hien nho qua `localStorage`, va `localStorage` nem thi van chay
 *      (Cam bay cua `ThemeToggle`, T-0.10)
 *  11. Doi hoi thoai dang mo: DA CO ⇒ khong goi mang · CHUA CO ⇒ goi lai
 *  12. `sortConversations` giu dung thu tu cua server trong nhom khong ghim
 *  13. Ban T-HD2: dong = **0 px, khong co dai icon**
 *
 * ── Vi sao mock `../../lib/api` chu khong mock `fetch` ────────────────────
 *
 * Ca 6 phai khang dinh **khong mot loi goi mang nao** xay ra khi go vao o
 * tim. Mot `fetch` gia van de lot ca "component goi `api.danhSachHoiThoai`
 * roi cache ket qua" — thu van la mot loi goi. Dem o tang `api` la dem dung
 * cai DoD noi toi. (Chuoi URL that duoc do rieng o `src/lib/api.test.ts`.)
 *
 * ── Nut bat/tat nam o HEADER, khong trong sidebar ────────────────────────
 *
 * Ban T-HD2 dat no o `app/Layout.tsx`, nen ca 10 goi thang `toggleSidebar()`
 * cua store thay vi bam mot nut — ca file nay render mot minh `Sidebar`.
 * Duong bam that duoc phu o `routes.test.tsx`.
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
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

import {
  api,
  type ConversationList,
  type ConversationDetail,
  type ConversationOut,
} from "../../lib/api";
import { Sidebar, sortConversations } from "./Sidebar";
import { resetSidebarOpenForTest, toggleSidebar } from "./sidebarOpen";

/**
 * `toggleSidebar()` la mot store NGOAI React, nen React khong biet no vua
 * bao moi nguoi nghe — thieu `act` thi cap nhat roi ra ngoai luot render cua
 * test va console day canh bao. Nut that o header (`Layout.tsx`) di qua mot
 * `onClick`, tuc da nam trong `act` san.
 */
function toggle(): void {
  act(() => {
    toggleSidebar();
  });
}

const STORAGE_KEY = "scarlet-sidebar";

function conversation(patch: Partial<ConversationOut> & Pick<ConversationOut, "id">): ConversationOut {
  return {
    title: null,
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: null,
    pinned: false,
    created_at: "2026-09-01T00:00:00+00:00",
    updated_at: "2026-09-01T00:00:00+00:00",
    ...patch,
  };
}

function page(items: ConversationOut[], nextCursor: string | null = null): ConversationList {
  return { items, next_cursor: nextCursor };
}

function detail(item: ConversationOut): ConversationDetail {
  return { ...item, path: [] };
}

const listMock = () => vi.mocked(api.listConversations);

function mount(props: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const onSelect = vi.fn();
  const onNewChat = vi.fn();
  const onOpenConversationDeleted = vi.fn();
  const view = render(
    <Sidebar
      openConversationId={null}
      onSelect={onSelect}
      onNewChat={onNewChat}
      onOpenConversationDeleted={onOpenConversationDeleted}
      {...props}
    />,
  );
  return { ...view, onSelect, onNewChat, onOpenConversationDeleted };
}

/** Mo menu "⋯" cua mot hang roi bam mot muc trong do. */
async function throughMenu(title: string, item: string) {
  await userEvent.click(screen.getByRole("button", { name: `Tuỳ chọn hội thoại — ${title}` }));
  await userEvent.click(screen.getByRole("menuitem", { name: item }));
}

/** Nhom "Đã ghim" / "Gần đây" — tra ve `<section>` chua tieu de nhom ay. */
function group(name: string): HTMLElement {
  return screen.getByRole("heading", { name: name }).closest("section") as HTMLElement;
}

beforeEach(() => {
  localStorage.clear();
  // Store song o tam module nen no song sot qua `cleanup()`.
  resetSidebarOpenForTest();
  listMock().mockResolvedValue(page([]));
});

describe("Sidebar — phan trang", () => {
  it("1. `next_cursor: null` thi KHONG co nut Tai them va khong goi trang ke", async () => {
    listMock().mockResolvedValue(page([conversation({ id: "a", title: "Mot" })], null));

    mount();

    expect(await screen.findByText("Mot")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tải thêm" })).not.toBeInTheDocument();
    expect(listMock()).toHaveBeenCalledTimes(1);
    expect(listMock()).toHaveBeenCalledWith();
  });

  it("2. co con tro thi bam Tai them goi dung `updated_before` cua trang truoc", async () => {
    const cursor = "2026-09-02T03:04:05.678901+00:00";
    listMock()
      .mockResolvedValueOnce(page([conversation({ id: "a", title: "Mot" })], cursor))
      .mockResolvedValueOnce(page([conversation({ id: "b", title: "Hai" })], null));

    mount();
    await screen.findByText("Mot");

    await userEvent.click(screen.getByRole("button", { name: "Tải thêm" }));

    expect(await screen.findByText("Hai")).toBeInTheDocument();
    expect(listMock()).toHaveBeenNthCalledWith(2, cursor);
    expect(screen.queryByRole("button", { name: "Tải thêm" })).not.toBeInTheDocument();
  });

  it("3. hai trang tra ve cung mot hoi thoai thi no chi hien MOT lan", async () => {
    const duplicate = conversation({ id: "a", title: "Trùng" });
    listMock()
      .mockResolvedValueOnce(page([duplicate, conversation({ id: "b", title: "Hai" })], "cursor-1"))
      .mockResolvedValueOnce(page([duplicate, conversation({ id: "c", title: "Ba" })], null));

    mount();
    await screen.findByText("Trùng");

    await userEvent.click(screen.getByRole("button", { name: "Tải thêm" }));
    await screen.findByText("Ba");

    expect(screen.getAllByText("Trùng")).toHaveLength(1);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });
});

describe("Sidebar — xoa", () => {
  it("4. xoa xong thi hang bien mat NGAY, khong co lan `GET /conversations` thu hai", async () => {
    listMock().mockResolvedValue(
      page([conversation({ id: "a", title: "Một" }), conversation({ id: "b", title: "Hai" })]),
    );
    vi.mocked(api.deleteConversation).mockResolvedValue(undefined);

    mount();
    await screen.findByText("Một");

    await throughMenu("Một", "Xoá");
    await userEvent.click(screen.getByRole("button", { name: "Xoá" }));

    await waitFor(() => {
      expect(screen.queryByText("Một")).not.toBeInTheDocument();
    });
    expect(api.deleteConversation).toHaveBeenCalledWith("a");
    expect(screen.getByText("Hai")).toBeInTheDocument();
    expect(listMock()).toHaveBeenCalledTimes(1);
  });

  it("5. xoa hoi thoai DANG MO thi man chat duoc bao", async () => {
    listMock().mockResolvedValue(page([conversation({ id: "a", title: "Một" })]));
    vi.mocked(api.deleteConversation).mockResolvedValue(undefined);

    const { onOpenConversationDeleted } = mount({ openConversationId: "a" });
    await screen.findByText("Một");

    await throughMenu("Một", "Xoá");
    await userEvent.click(screen.getByRole("button", { name: "Xoá" }));

    await waitFor(() => {
      expect(onOpenConversationDeleted).toHaveBeenCalledTimes(1);
    });
  });
});

describe("Sidebar — tim kiem cuc bo", () => {
  it("6. loc dung va KHONG goi mang mot lan nao", async () => {
    listMock().mockResolvedValue(
      page([
        conversation({ id: "a", title: "Hạn mức Redis" }),
        conversation({ id: "b", title: "Sửa nginx" }),
      ]),
    );

    mount();
    await screen.findByText("Hạn mức Redis");
    const before = listMock().mock.calls.length;

    await userEvent.type(screen.getByLabelText("Tìm hội thoại"), "nginx");

    expect(screen.getByText("Sửa nginx")).toBeInTheDocument();
    expect(screen.queryByText("Hạn mức Redis")).not.toBeInTheDocument();
    expect(listMock().mock.calls.length).toBe(before);
  });

  it("7. go KHONG DAU van tim ra tieu de co dau", async () => {
    listMock().mockResolvedValue(page([conversation({ id: "a", title: "Hạn mức Redis" })]));

    mount();
    await screen.findByText("Hạn mức Redis");

    await userEvent.type(screen.getByLabelText("Tìm hội thoại"), "han muc");

    expect(screen.getByText("Hạn mức Redis")).toBeInTheDocument();
  });
});

describe("Sidebar — ghim va doi ten", () => {
  it("8. ghim goi `PATCH {pinned:true}` va chuyen hang sang nhom “Đã ghim”", async () => {
    const old = conversation({ id: "a", title: "Cũ", updated_at: "2026-09-01T00:00:00+00:00" });
    const next = conversation({ id: "b", title: "Mới", updated_at: "2026-09-09T00:00:00+00:00" });
    listMock().mockResolvedValue(page([old, next]));
    vi.mocked(api.updateConversation).mockResolvedValue(detail({ ...old, pinned: true }));

    mount();
    await screen.findByText("Cũ");
    // Truoc khi ghim: chua co nhom "Da ghim", va "Moi" dung dau nhom "Gan day".
    expect(screen.queryByRole("heading", { name: "Đã ghim" })).not.toBeInTheDocument();
    expect(within(group("Gần đây")).getAllByRole("listitem")[0]).toHaveTextContent("Mới");

    await throughMenu("Cũ", "Ghim");

    await waitFor(() => {
      expect(within(group("Đã ghim")).getByText("Cũ")).toBeInTheDocument();
    });
    expect(within(group("Gần đây")).queryByText("Cũ")).not.toBeInTheDocument();
    expect(api.updateConversation).toHaveBeenCalledWith("a", { pinned: true });
    // Nhom "Da ghim" dung TRUOC nhom "Gan day" trong DOM.
    expect(group("Đã ghim").compareDocumentPosition(group("Gần đây"))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("9. doi ten goi `PATCH {title}`; de trong goi `PATCH {title: null}`", async () => {
    const item = conversation({ id: "a", title: "Cũ" });
    listMock().mockResolvedValue(page([item]));
    vi.mocked(api.updateConversation).mockResolvedValue(detail({ ...item, title: "Tên mới" }));

    mount();
    await screen.findByText("Cũ");

    await throughMenu("Cũ", "Đổi tên");
    await userEvent.clear(screen.getByLabelText("Tên mới"));
    await userEvent.type(screen.getByLabelText("Tên mới"), "Tên mới");
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));

    await waitFor(() => {
      expect(api.updateConversation).toHaveBeenCalledWith("a", { title: "Tên mới" });
    });

    vi.mocked(api.updateConversation).mockResolvedValue(detail({ ...item, title: null }));
    await throughMenu("Tên mới", "Đổi tên");
    await userEvent.clear(screen.getByLabelText("Tên mới"));
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));

    await waitFor(() => {
      expect(api.updateConversation).toHaveBeenLastCalledWith("a", { title: null });
    });
  });
});

describe("Sidebar — an/hien", () => {
  it("10a. an roi mount lai thi van an, va mo lai ghi duoc vao localStorage", async () => {
    listMock().mockResolvedValue(page([conversation({ id: "a", title: "Một" })]));

    const { unmount } = mount();
    await screen.findByText("Một");

    toggle();
    await waitFor(() => {
      expect(screen.queryByText("Một")).not.toBeInTheDocument();
    });
    expect(localStorage.getItem(STORAGE_KEY)).toBe("closed");

    unmount();
    resetSidebarOpenForTest();
    mount();

    expect(screen.queryByText("Một")).not.toBeInTheDocument();
    toggle();
    expect(await screen.findByText("Một")).toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEY)).toBe("open");
  });

  it("10b. `localStorage` nem (che do rieng tu) thi sidebar van chay, khong vo app", async () => {
    listMock().mockResolvedValue(page([conversation({ id: "a", title: "Một" })]));
    const readSpy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("bi chan", "SecurityError");
    });
    const writeSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("bi chan", "SecurityError");
    });

    resetSidebarOpenForTest();
    mount();

    expect(await screen.findByText("Một")).toBeInTheDocument();
    toggle();
    await waitFor(() => {
      expect(screen.queryByText("Một")).not.toBeInTheDocument();
    });

    readSpy.mockRestore();
    writeSpy.mockRestore();
  });
});

describe("Sidebar — chon hoi thoai", () => {
  /**
   * Hai khang dinh NGUOC CHIEU nhau, va thieu mot cai thi ca hai ban hien
   * thuc sai deu xanh:
   *
   *   - doi sang mot id DA CO ⇒ **khong** goi mang (bo guard "da co trong
   *     danh sach" thi moi lan bam mot hang la mot lan mat cac trang da tai)
   *   - doi sang mot id CHUA CO ⇒ **co** goi mang (day dung la duong "vua
   *     bam Hoi thoai moi"; bo no thi hoi thoai vua tao khong bao gio hien)
   *
   * `rerender` chu khong `render` lan hai: mot `render` thu hai la mot
   * component MOI, no mount va goi mang du guard co ton tai hay khong — tuc
   * mot phep do khong do gi ca. (Do duoc: ban dau ca nay viet bang `render`
   * va no van xanh khi guard bi go.)
   */
  it("11. doi hoi thoai dang mo: DA CO ⇒ khong goi mang · CHUA CO ⇒ goi lai", async () => {
    listMock().mockResolvedValue(
      page([conversation({ id: "a", title: "Một" }), conversation({ id: "b", title: "Hai" })]),
    );

    const { rerender } = mount({ openConversationId: "a" });
    await screen.findByText("Hai");
    expect(listMock()).toHaveBeenCalledTimes(1);

    rerender(
      <Sidebar
        openConversationId="b"
        onSelect={vi.fn()}
        onNewChat={vi.fn()}
        onOpenConversationDeleted={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("Hai").closest("button")).toHaveAttribute("aria-current", "page");
    });
    expect(listMock()).toHaveBeenCalledTimes(1);

    listMock().mockResolvedValue(
      page([conversation({ id: "moi", title: "Vừa tạo" }), conversation({ id: "a", title: "Một" })]),
    );
    rerender(
      <Sidebar
        openConversationId="moi"
        onSelect={vi.fn()}
        onNewChat={vi.fn()}
        onOpenConversationDeleted={vi.fn()}
      />,
    );
    expect(await screen.findByText("Vừa tạo")).toBeInTheDocument();
    expect(listMock()).toHaveBeenCalledTimes(2);
  });

  /**
   * T-S.10 (§24.2b·S7): "Hoi thoai moi" dua man chat ve man NHAP, va do la
   * khong mot loi goi API nao — ke ca `GET /conversations` cua sidebar. Ca
   * doi chieu o nua sau: hoi thoai vua ra doi tu man nhap (`createdConversationId`)
   * ⇒ nap lai DUNG MOT lan, du no doi cung luot voi `openConversationId`.
   */
  it("11b. ve man nhap (id → null) KHONG goi mang · hoi thoai vua tao ⇒ nap lai mot lan", async () => {
    listMock().mockResolvedValue(page([conversation({ id: "a", title: "Một" })]));
    const props = { onSelect: vi.fn(), onNewChat: vi.fn(), onOpenConversationDeleted: vi.fn() };

    const { rerender } = mount({ openConversationId: "a" });
    await screen.findByText("Một");
    expect(listMock()).toHaveBeenCalledTimes(1);

    rerender(<Sidebar openConversationId={null} {...props} />);
    await act(async () => {});
    expect(listMock()).toHaveBeenCalledTimes(1);

    listMock().mockResolvedValue(
      page([conversation({ id: "moi", title: "Vừa tạo" }), conversation({ id: "a", title: "Một" })]),
    );
    rerender(<Sidebar openConversationId="moi" createdConversationId="moi" {...props} />);
    expect(await screen.findByText("Vừa tạo")).toBeInTheDocument();
    expect(listMock()).toHaveBeenCalledTimes(2);

    // Doi hoi thoai qua lai sau do: khong nap lai vi "moi" da duoc xu ly.
    rerender(<Sidebar openConversationId="a" createdConversationId="moi" {...props} />);
    rerender(<Sidebar openConversationId="moi" createdConversationId="moi" {...props} />);
    await act(async () => {});
    expect(listMock()).toHaveBeenCalledTimes(2);
  });
});

describe("sortConversations", () => {
  it("12. ghim truoc, roi `updated_at` giam dan, roi `id` giam dan", () => {
    const sorted = sortConversations([
      conversation({ id: "a1", updated_at: "2026-09-01T00:00:00+00:00" }),
      conversation({ id: "a2", updated_at: "2026-09-01T00:00:00+00:00" }),
      conversation({ id: "b", updated_at: "2026-09-05T00:00:00+00:00" }),
      conversation({ id: "c", updated_at: "2026-08-01T00:00:00+00:00", pinned: true }),
    ]);

    expect(sorted.map((x) => x.id)).toEqual(["c", "b", "a2", "a1"]);
  });
});

describe("Sidebar — ban T-HD2", () => {
  /**
   * Bang so do cua T-HD2: *"An han, khong co dai icon. Dai icon se nhan doi
   * nut bat/tat cua header ma khong hien duoc tieu de hoi thoai."* Mot ban
   * hien thuc ve dai icon 48 px se lam ca 10a xanh (danh sach van an) nhung
   * lech ban ve — nen phai co mot ca noi thang ra rang khong con gi ca.
   */
  it("13. dong = 0 px: khong `<nav>`, khong nut nao con lai trong sidebar", async () => {
    listMock().mockResolvedValue(page([conversation({ id: "a", title: "Một" })]));

    const { container } = mount();
    await screen.findByText("Một");

    toggle();

    await waitFor(() => {
      expect(container.querySelector("nav")).toBeNull();
    });
    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(container).toBeEmptyDOMElement();
  });
});
