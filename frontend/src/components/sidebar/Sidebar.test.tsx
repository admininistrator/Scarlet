/**
 * Sidebar hoi thoai — DoD dong 1 cua T-3.3 (ban T-HD2), va DoD cua T-S.13
 * (ban T-HD2-v2: nhom theo ngay, muc ghim day du, tieu de chay, menu hang).
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOI CA O DAY LA MOT DONG DoD HOAC MOT CAM BAY CUA TASK                ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * T-3.3:
 *   1. `next_cursor: null` ⇒ **khong** goi trang ke (DoD dong 1)
 *   2. `next_cursor` co gia tri ⇒ goi dung `?updated_before=<con tro>`
 *   3. Hai trang noi nhau ⇒ **khong hoi thoai nao xuat hien hai lan**
 *   4. Xoa ⇒ **mat khoi danh sach ngay**, khong doi mot lan tai lai
 *   5. Xoa hoi thoai DANG MO ⇒ man chat duoc bao
 *   6. Tim kiem loc dung va **khong goi mang** (DoD dong 1; T-S.13 DoD dong 4)
 *   7. Tim kiem bo dau
 *   8. Ghim ⇒ `PATCH {pinned: true}` va hang nhay sang muc "Da ghim"
 *   9. Doi ten ⇒ `PATCH {title}`; de trong ⇒ `PATCH {title: null}`
 *  10. An/hien nho qua `localStorage`, va `localStorage` nem thi van chay
 *  11. Doi hoi thoai dang mo: DA CO ⇒ khong goi mang · CHUA CO ⇒ goi lai
 *  12. `sortConversations` giu dung thu tu cua server
 *  13. Ban T-HD2: dong = **0 px, khong co dai icon**
 *
 * T-S.13:
 *  14. DoD dong 1 — dong ho gia 23/9/2026, gio +07: Hom nay · Hom qua ·
 *      "21/9/2026"; `2026-09-22T17:30:00Z` ⇒ Hom nay
 *  15. Cam bay ① — qua nua dem, tab lay lai tieu diem ⇒ nhom tinh lai
 *  16. DoD dong 2 — ghim nhieu hon mot trang ⇒ muc Da ghim DU ngay lan nap
 *      dau, khong bam "Tai them"
 *  17. `truncated` ⇒ mot dong bao duoi Da ghim (NQ-129)
 *  18. `sidebar.pinScopeNote` bien khoi man hinh lan `vi.json`
 *  19. Cam bay ③ — bo ghim ⇒ doi muc NGAY, khong nap lai
 *  20. Menu hang: thu tu cua ban H6, hai muc cho `T-8.1`/`T-8.7`
 *  21. Esc tu muc cho ⇒ menu dong, tieu diem ve nut "⋯" (B-308 ②)
 *  22–27. Tieu de chay (`useTitleStreams`) — xem khoi `describe` cuoi file
 *
 * ── Vi sao mock `../../lib/api` chu khong mock `fetch` ────────────────────
 *
 * Ca 6 phai khang dinh **khong mot loi goi mang nao** xay ra khi go vao o
 * tim. Dem o tang `api` la dem dung cai DoD noi toi. (Chuoi URL that duoc do
 * rieng o `src/lib/api.test.ts`.) `openStream` cung bi thay: jsdom khong co
 * `EventSource`, va ca tieu de chay can tu tay phat tung event.
 *
 * ── Hai nguon ─────────────────────────────────────────────────────────────
 *
 * `serve()` tra nguon `?pinned=true` va cac trang `?pinned=false` RIENG, nen
 * moi ca noi ro hang nao den tu dau. Mot lan nap = HAI loi goi.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// `process` cua Node (vitest chay trong Node); tsconfig cua app khong khai @types/node.
declare const process: { env: Record<string, string | undefined> };

// DoD dong 1 cua T-S.13: "gio +07". Dat TRUOC moi phep tinh ngay; ca 14 kiem
// lai rang no co tac dung (khong thi ca ay xanh vo nghia duoi UTC).
const ORIGINAL_TZ = process.env.TZ;
process.env.TZ = "Asia/Ho_Chi_Minh";
afterAll(() => {
  if (ORIGINAL_TZ === undefined) {
    delete process.env.TZ;
  } else {
    process.env.TZ = ORIGINAL_TZ;
  }
});

interface FakeStream {
  url: string;
  onEvent: (event: TitleStreamEvent) => void;
  onFatal?: (reason: string) => void;
  close: ReturnType<typeof vi.fn>;
}
const streams = vi.hoisted(() => [] as FakeStream[]);

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

vi.mock("../../lib/sse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/sse")>();
  return {
    ...actual,
    openStream: vi.fn(
      (params: {
        url: string;
        onEvent: (event: TitleStreamEvent) => void;
        onFatal?: (reason: string) => void;
      }) => {
        const entry: FakeStream = {
          url: params.url,
          onEvent: params.onEvent,
          onFatal: params.onFatal,
          close: vi.fn(),
        };
        streams.push(entry);
        return { close: entry.close, cursor: () => "" };
      },
    ),
  };
});

import {
  api,
  type ConversationDetail,
  type ConversationList,
  type ConversationListQuery,
  type ConversationOut,
} from "../../lib/api";
import type { TitleStreamEvent } from "../../lib/sse";
import locale from "../../locales/vi.json";
import { Sidebar, sortConversations } from "./Sidebar";

const TTL_S = 3600;
const UNTITLED = "Hội thoại chưa đặt tên";

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
  return { items, next_cursor: nextCursor, truncated: false };
}

function detail(item: ConversationOut): ConversationDetail {
  return { ...item, path: [] };
}

/** Moc `updated_at` cach bay gio `secondsAgo` giay — dung cho cua so `STREAM_TTL_S`. */
function ago(secondsAgo: number): string {
  return new Date(Date.now() - secondsAgo * 1000).toISOString();
}

const listMock = () => vi.mocked(api.listConversations);

/**
 * Hai nguon: `?pinned=true` tra `pinned` (mot lan, khong trang); `?pinned=false`
 * tra lan luot tung trang trong `pages` — trang cuoi lap lai cho moi lan nap sau.
 */
function serve({
  pinned = [],
  pages = [page([])],
  truncated = false,
}: {
  pinned?: ConversationOut[];
  pages?: ConversationList[];
  truncated?: boolean;
}) {
  const rest = [...pages];
  listMock().mockImplementation(async (query: ConversationListQuery) => {
    if (query.pinned) {
      return { items: pinned, next_cursor: null, truncated };
    }
    return rest.length > 1 ? (rest.shift() as ConversationList) : rest[0];
  });
}

/** So lan nap LAI tu dau (moi lan = mot `?pinned=false` khong con tro). */
function firstPageLoads(): number {
  return listMock().mock.calls.filter(
    ([query]) => !query.pinned && (query.updatedBefore ?? null) === null,
  ).length;
}

function mount(props: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const onSelect = vi.fn();
  const onNewChat = vi.fn();
  const onOpenConversationDeleted = vi.fn();
  const base = {
    openConversationId: null,
    onSelect,
    onNewChat,
    onOpenConversationDeleted,
  };
  const view = render(<Sidebar {...base} {...props} />);
  const rerenderWith = (next: Partial<Parameters<typeof Sidebar>[0]>) =>
    view.rerender(<Sidebar {...base} {...next} />);
  return { ...view, rerenderWith, onSelect, onNewChat, onOpenConversationDeleted };
}

function rowMenuButton(title: string): HTMLElement {
  return screen.getByRole("button", { name: `Tuỳ chọn hội thoại — ${title}` });
}

/**
 * Mo menu "⋯" — dat tieu diem vao nut TRUOC khi bam (B-308 ①): jsdom phat
 * `blur` len `window` khi tieu diem cu la Document, va `Menu` cua Radix dong
 * ngay khi thay `blur` ay.
 */
async function openRowMenu(title: string): Promise<HTMLElement> {
  const trigger = rowMenuButton(title);
  act(() => trigger.focus());
  await userEvent.click(trigger);
  return screen.findByRole("menu", { name: `Tuỳ chọn hội thoại — ${title}` });
}

/** Mo menu "⋯" cua mot hang roi bam mot muc trong do. */
async function throughMenu(title: string, item: string) {
  const menu = await openRowMenu(title);
  await userEvent.click(within(menu).getByRole("menuitem", { name: item }));
}

/** Muc "Da ghim" / "Hom nay" / … — tra ve `<section>` chua tieu de muc ay. */
function group(name: string): HTMLElement {
  return screen.getByRole("heading", { name }).closest("section") as HTMLElement;
}

function headings(): string[] {
  return screen.getAllByRole("heading").map((h) => h.textContent ?? "");
}

beforeEach(() => {
  localStorage.clear();
  streams.length = 0;
  serve({});
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Sidebar — phan trang", () => {
  it("1. `next_cursor: null` thi KHONG co nut Tai them va khong goi trang ke", async () => {
    serve({ pages: [page([conversation({ id: "a", title: "Mot" })], null)] });

    mount();

    expect(await screen.findByText("Mot")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tải thêm" })).not.toBeInTheDocument();
    // Mot lan nap = hai nguon, khong hon.
    expect(listMock().mock.calls.map(([q]) => q)).toEqual([{ pinned: true }, { pinned: false }]);
  });

  it("2. co con tro thi bam Tai them goi dung `updated_before` cua trang truoc", async () => {
    const cursor = "2026-09-02T03:04:05.678901+00:00";
    serve({
      pages: [
        page([conversation({ id: "a", title: "Mot" })], cursor),
        page([conversation({ id: "b", title: "Hai" })], null),
      ],
    });

    mount();
    await screen.findByText("Mot");

    await userEvent.click(screen.getByRole("button", { name: "Tải thêm" }));

    expect(await screen.findByText("Hai")).toBeInTheDocument();
    expect(listMock()).toHaveBeenLastCalledWith({ pinned: false, updatedBefore: cursor });
    expect(screen.queryByRole("button", { name: "Tải thêm" })).not.toBeInTheDocument();
  });

  it("3. hai trang tra ve cung mot hoi thoai thi no chi hien MOT lan", async () => {
    const duplicate = conversation({ id: "a", title: "Trùng" });
    serve({
      pages: [
        page([duplicate, conversation({ id: "b", title: "Hai" })], "cursor-1"),
        page([duplicate, conversation({ id: "c", title: "Ba" })], null),
      ],
    });

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
    serve({ pages: [page([conversation({ id: "a", title: "Một" }), conversation({ id: "b", title: "Hai" })])] });
    vi.mocked(api.deleteConversation).mockResolvedValue(undefined);

    mount();
    await screen.findByText("Một");
    const calls = listMock().mock.calls.length;

    await throughMenu("Một", "Xoá");
    await userEvent.click(screen.getByRole("button", { name: "Xoá" }));

    await waitFor(() => {
      expect(screen.queryByText("Một")).not.toBeInTheDocument();
    });
    expect(api.deleteConversation).toHaveBeenCalledWith("a");
    expect(screen.getByText("Hai")).toBeInTheDocument();
    expect(listMock().mock.calls.length).toBe(calls);
  });

  it("5. xoa hoi thoai DANG MO thi man chat duoc bao", async () => {
    serve({ pages: [page([conversation({ id: "a", title: "Một" })])] });
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
  it("6. loc dung — ca muc ghim lan muc ngay — va KHONG goi mang mot lan nao", async () => {
    serve({
      pinned: [conversation({ id: "p", title: "Ghim nginx", pinned: true })],
      pages: [
        page([
          conversation({ id: "a", title: "Hạn mức Redis" }),
          conversation({ id: "b", title: "Sửa nginx" }),
        ]),
      ],
    });

    mount();
    await screen.findByText("Hạn mức Redis");
    const before = listMock().mock.calls.length;

    await userEvent.type(screen.getByLabelText("Tìm hội thoại"), "nginx");

    expect(screen.getByText("Sửa nginx")).toBeInTheDocument();
    expect(within(group("Đã ghim")).getByText("Ghim nginx")).toBeInTheDocument();
    expect(screen.queryByText("Hạn mức Redis")).not.toBeInTheDocument();
    expect(listMock().mock.calls.length).toBe(before);
    // Cau "chi tim trong phan da tai" van tren man hinh (T-3.3, NQ-129).
    expect(screen.getByText(locale["sidebar.searchScopeNote"])).toBeInTheDocument();
  });

  it("7. go KHONG DAU van tim ra tieu de co dau", async () => {
    serve({ pages: [page([conversation({ id: "a", title: "Hạn mức Redis" })])] });

    mount();
    await screen.findByText("Hạn mức Redis");

    await userEvent.type(screen.getByLabelText("Tìm hội thoại"), "han muc");

    expect(screen.getByText("Hạn mức Redis")).toBeInTheDocument();
  });
});

describe("Sidebar — ghim va doi ten", () => {
  it("8. ghim goi `PATCH {pinned:true}` va chuyen hang sang muc “Đã ghim”, dung dau", async () => {
    const old = conversation({ id: "a", title: "Cũ", updated_at: "2026-09-01T00:00:00+00:00" });
    const next = conversation({ id: "b", title: "Mới", updated_at: "2026-09-09T00:00:00+00:00" });
    serve({ pages: [page([next, old])] });
    vi.mocked(api.updateConversation).mockResolvedValue(detail({ ...old, pinned: true }));

    mount();
    await screen.findByText("Cũ");
    expect(screen.queryByRole("heading", { name: "Đã ghim" })).not.toBeInTheDocument();

    await throughMenu("Cũ", "Ghim");

    await waitFor(() => {
      expect(within(group("Đã ghim")).getByText("Cũ")).toBeInTheDocument();
    });
    // "Cũ" la hang duy nhat cua ngay 1/9 ⇒ muc ay bien mat cung no.
    expect(screen.queryByRole("heading", { name: "1/9/2026" })).not.toBeInTheDocument();
    expect(api.updateConversation).toHaveBeenCalledWith("a", { pinned: true });
    expect(headings()[0]).toBe("Đã ghim");
  });

  it("9. doi ten goi `PATCH {title}`; de trong goi `PATCH {title: null}`", async () => {
    const item = conversation({ id: "a", title: "Cũ" });
    serve({ pages: [page([item])] });
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

describe("Sidebar — chon hoi thoai", () => {
  /**
   * Hai khang dinh NGUOC CHIEU nhau: doi sang mot id DA CO ⇒ **khong** goi
   * mang; doi sang mot id CHUA CO ⇒ **co** goi mang. `rerender` chu khong
   * `render` lan hai (mot `render` moi la mot component moi, luon goi mang).
   */
  it("11. doi hoi thoai dang mo: DA CO ⇒ khong goi mang · CHUA CO ⇒ goi lai", async () => {
    serve({ pages: [page([conversation({ id: "a", title: "Một" }), conversation({ id: "b", title: "Hai" })])] });

    const { rerenderWith } = mount({ openConversationId: "a" });
    await screen.findByText("Hai");
    expect(firstPageLoads()).toBe(1);

    rerenderWith({ openConversationId: "b" });
    await waitFor(() => {
      expect(screen.getByText("Hai").closest("button")).toHaveAttribute("aria-current", "page");
    });
    expect(firstPageLoads()).toBe(1);

    serve({ pages: [page([conversation({ id: "moi", title: "Vừa tạo" }), conversation({ id: "a", title: "Một" })])] });
    rerenderWith({ openConversationId: "moi" });
    expect(await screen.findByText("Vừa tạo")).toBeInTheDocument();
    expect(firstPageLoads()).toBe(2);
  });

  it("11b. ve man nhap (id → null) KHONG goi mang · hoi thoai vua tao ⇒ nap lai mot lan", async () => {
    serve({ pages: [page([conversation({ id: "a", title: "Một" })])] });

    const { rerenderWith } = mount({ openConversationId: "a" });
    await screen.findByText("Một");
    expect(listMock()).toHaveBeenCalledTimes(2);

    rerenderWith({ openConversationId: null });
    await act(async () => {});
    expect(listMock()).toHaveBeenCalledTimes(2);

    serve({ pages: [page([conversation({ id: "moi", title: "Vừa tạo" }), conversation({ id: "a", title: "Một" })])] });
    rerenderWith({ openConversationId: "moi", createdConversationId: "moi" });
    expect(await screen.findByText("Vừa tạo")).toBeInTheDocument();
    expect(firstPageLoads()).toBe(2);

    // Doi hoi thoai qua lai sau do: khong nap lai vi "moi" da duoc xu ly.
    rerenderWith({ openConversationId: "a", createdConversationId: "moi" });
    rerenderWith({ openConversationId: "moi", createdConversationId: "moi" });
    await act(async () => {});
    expect(firstPageLoads()).toBe(2);
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

describe("T-S.13 — nhom theo ngay (ban T-HD2-v2)", () => {
  it("14. DoD dong 1: dong ho gia 23/9/2026 +07 ⇒ Hom nay · Hom qua · 21/9/2026; 22/9 17:30Z ⇒ Hom nay", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-23T10:00:00+07:00"));
    // Mui gio +07 CO tac dung — thieu dong nay ca duoi co the xanh vo nghia o UTC.
    expect(new Date("2026-09-22T17:30:00Z").getHours()).toBe(0);
    expect(new Date("2026-09-22T17:30:00Z").getDate()).toBe(23);

    serve({
      pages: [
        page([
          conversation({ id: "d23", title: "Ngày 23", updated_at: "2026-09-23T02:00:00+00:00" }),
          conversation({ id: "d23-early", title: "Nửa đêm +07", updated_at: "2026-09-22T17:30:00Z" }),
          conversation({ id: "d22", title: "Ngày 22", updated_at: "2026-09-22T09:00:00+00:00" }),
          conversation({ id: "d21", title: "Ngày 21", updated_at: "2026-09-21T09:00:00+00:00" }),
        ]),
      ],
    });

    mount();
    await screen.findByText("Ngày 23");

    expect(headings()).toEqual(["Hôm nay", "Hôm qua", "21/9/2026"]);
    expect(within(group("Hôm nay")).getByText("Ngày 23")).toBeInTheDocument();
    expect(within(group("Hôm nay")).getByText("Nửa đêm +07")).toBeInTheDocument();
    expect(within(group("Hôm qua")).getByText("Ngày 22")).toBeInTheDocument();
    expect(within(group("21/9/2026")).getByText("Ngày 21")).toBeInTheDocument();
  });

  it("15. Cam bay ①: qua nua dem, tab lay lai tieu diem ⇒ Hom nay thanh Hom qua", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-23T23:50:00+07:00"));
    serve({
      pages: [page([conversation({ id: "a", title: "Tối qua", updated_at: "2026-09-23T16:00:00+00:00" })])],
    });

    mount();
    await screen.findByText("Tối qua");
    expect(headings()).toEqual(["Hôm nay"]);

    // Qua nua dem ma KHONG co su kien nao: nhom chua doi (khong ai hoi dong ho).
    vi.setSystemTime(new Date("2026-09-24T00:10:00+07:00"));
    expect(headings()).toEqual(["Hôm nay"]);

    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(headings()).toEqual(["Hôm qua"]);

    // Duong thu hai: tab tu an sang hien (dien thoai mo lai trinh duyet).
    vi.setSystemTime(new Date("2026-09-25T08:00:00+07:00"));
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(headings()).toEqual(["23/9/2026"]);
  });
});

describe("T-S.13 — muc Da ghim day du", () => {
  it("16. DoD dong 2: ghim NHIEU HON mot trang ⇒ du ca 35 ngay lan nap dau, khong bam Tai them", async () => {
    const pinned = Array.from({ length: 35 }, (_, i) =>
      conversation({
        id: `p${String(i).padStart(2, "0")}`,
        title: `Ghim ${String(i).padStart(2, "0")}`,
        pinned: true,
        updated_at: `2026-08-${String(1 + (i % 28)).padStart(2, "0")}T00:00:00+00:00`,
      }),
    );
    const firstPage = Array.from({ length: 30 }, (_, i) =>
      conversation({ id: `r${String(i).padStart(2, "0")}`, title: `Thường ${i}` }),
    );
    serve({ pinned, pages: [page(firstPage, "cursor-trang-2")] });

    mount();
    await screen.findByText("Ghim 00");

    expect(within(group("Đã ghim")).getAllByRole("listitem")).toHaveLength(35);
    // "Tai them" CO (phan khong ghim con trang sau) nhung khong ai bam no.
    expect(screen.getByRole("button", { name: "Tải thêm" })).toBeInTheDocument();
    expect(listMock().mock.calls.map(([q]) => q)).toEqual([{ pinned: true }, { pinned: false }]);
  });

  it("17. `truncated: true` ⇒ mot dong bao duoi Da ghim; `false` ⇒ khong", async () => {
    const pinned = [conversation({ id: "p", title: "Ghim", pinned: true })];
    serve({ pinned, truncated: true });

    const { unmount } = mount();
    await screen.findByText("Ghim");
    expect(within(group("Đã ghim")).getByText(locale["sidebar.pinnedTruncated"])).toBeInTheDocument();
    unmount();

    serve({ pinned, truncated: false });
    mount();
    await screen.findByText("Ghim");
    expect(screen.queryByText(locale["sidebar.pinnedTruncated"])).not.toBeInTheDocument();
  });

  it("18. `sidebar.pinScopeNote` bien khoi man hinh va khoi vi.json", async () => {
    serve({ pinned: [conversation({ id: "p", title: "Ghim", pinned: true })] });

    mount();
    await screen.findByText("Ghim");

    // Mang mot phan tu: khoa CO dau cham, khong phai duong `sidebar` → `pinScopeNote`.
    expect(locale).not.toHaveProperty(["sidebar.pinScopeNote"]);
    expect(locale).not.toHaveProperty(["sidebar.recentGroup"]);
    expect(locale).toHaveProperty(["sidebar.searchScopeNote"]);
    expect(screen.queryByText(/Ghim nổi lên đầu/)).not.toBeInTheDocument();
  });

  it("19. Cam bay ③: bo ghim ⇒ hang doi muc NGAY, khong nap lai", async () => {
    // Giua ngay: `ago(60)` khong duoc vat qua nua dem sang "Hom qua".
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-23T12:00:00+07:00"));
    const pinnedItem = conversation({ id: "p", title: "Đang ghim", pinned: true });
    serve({
      pinned: [pinnedItem],
      pages: [page([conversation({ id: "b", title: "Thường", updated_at: ago(60) })])],
    });
    vi.mocked(api.updateConversation).mockResolvedValue(
      // `updated_at` co `onupdate`: chinh lan PATCH day hang len moc moi nhat.
      detail({ ...pinnedItem, pinned: false, updated_at: ago(0) }),
    );

    mount();
    await screen.findByText("Đang ghim");
    const calls = listMock().mock.calls.length;

    await throughMenu("Đang ghim", "Bỏ ghim");

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Đã ghim" })).not.toBeInTheDocument();
    });
    expect(within(group("Hôm nay")).getAllByRole("listitem")[0]).toHaveTextContent("Đang ghim");
    expect(api.updateConversation).toHaveBeenCalledWith("p", { pinned: false });
    expect(listMock().mock.calls.length).toBe(calls);
  });
});

describe("T-S.13 — menu hang (ban T-HD2-v2 H6)", () => {
  it("20. thu tu Doi ten · Ghim · Chia se · Xuat · ── · Xoa; hai muc cho `aria-disabled`, bam khong lam gi", async () => {
    serve({ pages: [page([conversation({ id: "a", title: "Một" })])] });

    mount();
    await screen.findByText("Một");
    const menu = await openRowMenu("Một");

    const entries = [...menu.querySelectorAll('[role="menuitem"], [role="separator"]')].map((el) =>
      el.getAttribute("role") === "separator" ? "──" : (el.textContent ?? ""),
    );
    expect(entries).toEqual(["Đổi tên", "Ghim", "Chia sẻ", "Xuất", "──", "Xoá"]);

    const share = within(menu).getByRole("menuitem", { name: "Chia sẻ" });
    const exportItem = within(menu).getByRole("menuitem", { name: "Xuất" });
    expect(share).toHaveAttribute("aria-disabled", "true");
    expect(share).toHaveAttribute("data-planned", "T-8.1");
    expect(exportItem).toHaveAttribute("aria-disabled", "true");
    expect(exportItem).toHaveAttribute("data-planned", "T-8.7");
    // Khong dung `disabled` cua Radix (mui ten se bo qua muc ay).
    expect(share).not.toHaveAttribute("data-disabled");

    await userEvent.click(share);
    await userEvent.click(exportItem);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(api.updateConversation).not.toHaveBeenCalled();
    expect(api.deleteConversation).not.toHaveBeenCalled();
  });

  it("21. Esc khi tieu diem o muc cho (tooltip mo) ⇒ menu dong NGAY, tieu diem ve nut ⋯ (B-308 ②)", async () => {
    serve({ pages: [page([conversation({ id: "a", title: "Một" })])] });
    const user = userEvent.setup();

    mount();
    await screen.findByText("Một");
    const trigger = rowMenuButton("Một");
    act(() => trigger.focus());

    await user.keyboard("{Enter}");
    const menu = await screen.findByRole("menu");
    await waitFor(() => expect(within(menu).getByRole("menuitem", { name: "Đổi tên" })).toHaveFocus());
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(within(menu).getByRole("menuitem", { name: "Chia sẻ" })).toHaveFocus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Sắp có");

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });
});

describe("T-S.13 — tieu de chay (useTitleStreams)", () => {
  function titleButton(name: string): HTMLElement {
    return screen.getByRole("button", { name });
  }
  function rowOf(button: HTMLElement): HTMLElement {
    return button.parentElement as HTMLElement;
  }
  function emit(index: number, event: TitleStreamEvent): void {
    act(() => {
      streams[index].onEvent(event);
    });
  }

  it("22. hang vua tao: nghe `…/title/stream`, thanh xam → chu chay → `done` (ban H3)", async () => {
    serve({
      pages: [
        page([
          conversation({ id: "moi", updated_at: ago(2) }),
          conversation({ id: "cu", title: "Cũ", updated_at: ago(600) }),
        ]),
      ],
    });

    mount({ openConversationId: "moi", streamTtlS: TTL_S });
    await waitFor(() => expect(streams).toHaveLength(1));
    expect(streams[0].url).toBe("/api/v1/conversations/moi/title/stream");

    // Khung 1: chua mot manh — thanh xam `motion-pulse`, hang `aria-busy`.
    const button = titleButton(UNTITLED);
    expect(button.querySelector(".motion-pulse")).not.toBeNull();
    expect(rowOf(button)).toHaveAttribute("aria-busy", "true");

    emit(0, { event: "start", data: { message_id: "q", model_id: "deepseek" } });
    emit(0, { event: "delta", data: { t: "Cách đọc hạn" } });

    // Khung 2: chu trong vo `.motion-title` (duoi mo), chu gan `.motion-none`.
    const shell = document.querySelector('.motion-title[data-state="streaming"]') as HTMLElement;
    expect(shell).toHaveTextContent("Cách đọc hạn");
    expect(shell.querySelector(".motion-none")).toHaveTextContent("Cách đọc hạn");
    expect(document.querySelector(".motion-pulse")).toBeNull();
    // Cam bay ②: chu nam trong nut `min-w-0 flex-1 truncate` — hang giu be rong.
    const chooser = shell.closest("button") as HTMLElement;
    expect(chooser).toHaveClass("min-w-0", "flex-1", "truncate");

    emit(0, { event: "delta", data: { t: " mức từ Redis" } });
    expect(shell).toHaveTextContent("Cách đọc hạn mức từ Redis");

    emit(0, { event: "done", data: { title: "Cách đọc hạn mức từ Redis" } });

    // Khung 3: vo `data-state="done"` (duoi co ve 0), het `aria-busy`, stream dong.
    const done = document.querySelector('.motion-title[data-state="done"]') as HTMLElement;
    expect(done).toHaveTextContent("Cách đọc hạn mức từ Redis");
    expect(rowOf(titleButton("Cách đọc hạn mức từ Redis"))).not.toHaveAttribute("aria-busy");
    expect(streams[0].close).toHaveBeenCalled();

    // Ten da vao DANH SACH (khong chi vao man hinh): tim kiem thay no.
    await userEvent.type(screen.getByLabelText("Tìm hội thoại"), "redis");
    expect(screen.getByText("Cách đọc hạn mức từ Redis")).toBeInTheDocument();
    expect(screen.queryByText("Cũ")).not.toBeInTheDocument();
  });

  it("23. `done` mang ten TRONG DB (nguoi dung doi giua chung) ⇒ THAY chu da chay (B-289)", async () => {
    serve({ pages: [page([conversation({ id: "moi", updated_at: ago(2) })])] });

    mount({ streamTtlS: TTL_S });
    await waitFor(() => expect(streams).toHaveLength(1));

    emit(0, { event: "start", data: { message_id: "q", model_id: "deepseek" } });
    emit(0, { event: "delta", data: { t: "Tên máy đặt" } });
    emit(0, { event: "done", data: { title: "Tên người dùng đặt" } });

    expect(screen.getByRole("button", { name: "Tên người dùng đặt" })).toBeInTheDocument();
    expect(screen.queryByText(/Tên máy đặt/)).not.toBeInTheDocument();
  });

  it("24. `error` (ca `JOB_LOST`) ⇒ “Hội thoại chưa đặt tên” mau muted; nap lai KHONG mo lai", async () => {
    serve({ pages: [page([conversation({ id: "moi", updated_at: ago(2) })])] });

    const { rerenderWith } = mount({ streamTtlS: TTL_S });
    await waitFor(() => expect(streams).toHaveLength(1));

    emit(0, { event: "error", data: { code: "JOB_LOST", message: "khong co luot dat ten nao" } });

    const button = titleButton(UNTITLED);
    expect(button.querySelector(".text-muted")).toHaveTextContent(UNTITLED);
    expect(rowOf(button)).not.toHaveAttribute("aria-busy");
    expect(streams[0].close).toHaveBeenCalled();

    // Mot lan nap lai tra dung hang `null` ay: khong mo lai chi de nghe lai `error`.
    serve({ pages: [page([conversation({ id: "khac", title: "Khác" }), conversation({ id: "moi", updated_at: ago(3) })])] });
    rerenderWith({ streamTtlS: TTL_S, openConversationId: "khac", createdConversationId: "khac" });
    await screen.findByText("Khác");
    expect(streams).toHaveLength(1);
  });

  it("25. het cua so `STREAM_TTL_S` ⇒ dong stream, hien “chua dat ten” (NQ-129, B-287)", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
    vi.setSystemTime(new Date("2026-09-23T10:00:00+07:00"));
    serve({ pages: [page([conversation({ id: "moi", updated_at: ago(TTL_S - 5) })])] });

    mount({ streamTtlS: TTL_S });
    await act(async () => {});
    await act(async () => {});
    expect(streams).toHaveLength(1);

    // Worker chet giua chung: da co mot manh, roi im (B-287).
    emit(0, { event: "start", data: { message_id: "q", model_id: "deepseek" } });
    emit(0, { event: "delta", data: { t: "Dở dang" } });

    act(() => {
      vi.advanceTimersByTime(4_000);
    });
    expect(streams[0].close).not.toHaveBeenCalled();
    expect(screen.getByText("Dở dang")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1_500);
    });
    expect(streams[0].close).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: UNTITLED })).toBeInTheDocument();
    expect(screen.queryByText("Dở dang")).not.toBeInTheDocument();
  });

  it("26. khong nghe: hang qua cua so, hang da co ten, hay chua biet `stream_ttl_s`", async () => {
    serve({
      pages: [
        page([
          conversation({ id: "cu", updated_at: ago(TTL_S + 60) }),
          conversation({ id: "co-ten", title: "Có tên", updated_at: ago(2) }),
          conversation({ id: "moi", updated_at: ago(2) }),
        ]),
      ],
    });

    const { rerenderWith } = mount();
    await screen.findByText("Có tên");
    await act(async () => {});
    // `stream_ttl_s` chua ve (`/auth/me` chua xong) ⇒ chua nghe ai.
    expect(streams).toHaveLength(0);

    rerenderWith({ streamTtlS: TTL_S });
    await waitFor(() => expect(streams).toHaveLength(1));
    // Chi hang "moi": hang cu qua cua so, hang co ten khong co gi de nghe.
    expect(streams[0].url).toBe("/api/v1/conversations/moi/title/stream");
    expect(screen.getAllByRole("button", { name: UNTITLED })).toHaveLength(2);
  });

  it("28. `start` lan hai (noi lai, server phat lai tu dau) ⇒ chu BAT DAU LAI, khong lap (§7.4, `sse.ts` diem 4)", async () => {
    serve({ pages: [page([conversation({ id: "moi", updated_at: ago(2) })])] });

    mount({ streamTtlS: TTL_S });
    await waitFor(() => expect(streams).toHaveLength(1));

    emit(0, { event: "start", data: { message_id: "q", model_id: "deepseek" } });
    emit(0, { event: "delta", data: { t: "Kế hoạch" } });
    emit(0, { event: "start", data: { message_id: "q", model_id: "deepseek" } });
    emit(0, { event: "delta", data: { t: "Kế hoạch" } });
    emit(0, { event: "delta", data: { t: " vận hành" } });

    const shell = document.querySelector('.motion-title[data-state="streaming"]') as HTMLElement;
    expect(shell.textContent).toBe("Kế hoạch vận hành");
  });

  it("27. doi ten tay giua luc dang chay ⇒ dong stream, ten cua nguoi dung thang", async () => {
    const fresh = conversation({ id: "moi", updated_at: ago(2) });
    serve({ pages: [page([fresh])] });
    vi.mocked(api.updateConversation).mockResolvedValue(detail({ ...fresh, title: "Tên tay" }));

    mount({ streamTtlS: TTL_S });
    await waitFor(() => expect(streams).toHaveLength(1));
    emit(0, { event: "delta", data: { t: "Tên máy" } });

    // Hang chua co ten trong danh sach: nut ⋯ mang ten "chua dat ten".
    await throughMenu(UNTITLED, "Đổi tên");
    fireEvent.change(screen.getByLabelText("Tên mới"), { target: { value: "Tên tay" } });
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));

    expect(await screen.findByRole("button", { name: "Tên tay" })).toBeInTheDocument();
    expect(streams[0].close).toHaveBeenCalled();
    expect(document.querySelector('.motion-title[data-state="streaming"]')).toBeNull();
  });
});
