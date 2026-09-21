/**
 * Sidebar hoi thoai — DoD dong 1 cua T-3.3.
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
 *   8. Ghim ⇒ `PATCH {pinned: true}` va hang do **len dau** (DoD dong 4)
 *   9. Doi ten ⇒ `PATCH {title}`; de trong ⇒ `PATCH {title: null}`
 *  10. An/hien nho qua `localStorage`, va `localStorage` nem thi van chay
 *      (Cam bay cua `ThemeToggle`, T-0.10)
 *  11. Chon mot hang DA CO trong danh sach ⇒ khong goi mang lan nua
 *  12. `sortConversations` giu dung thu tu cua server trong nhom khong ghim
 *
 * ── Vi sao mock `../../lib/api` chu khong mock `fetch` ────────────────────
 *
 * Ca 6 phai khang dinh **khong mot loi goi mang nao** xay ra khi go vao o
 * tim. Mot `fetch` gia van de lot ca "component goi `api.danhSachHoiThoai`
 * roi cache ket qua" — thu van la mot loi goi. Dem o tang `api` la dem dung
 * cai DoD noi toi.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const that = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...that,
    api: {
      ...that.api,
      danhSachHoiThoai: vi.fn(),
      suaHoiThoai: vi.fn(),
      xoaHoiThoai: vi.fn(),
    },
  };
});

import {
  api,
  type DanhSachHoiThoai,
  type HoiThoaiChiTiet,
  type HoiThoaiRa,
} from "../../lib/api";
import { Sidebar, sortConversations } from "./Sidebar";

const KHOA_LUU = "scarlet-sidebar";

function hoiThoai(sua: Partial<HoiThoaiRa> & Pick<HoiThoaiRa, "id">): HoiThoaiRa {
  return {
    title: null,
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: null,
    pinned: false,
    created_at: "2026-09-01T00:00:00+00:00",
    updated_at: "2026-09-01T00:00:00+00:00",
    ...sua,
  };
}

function trang(items: HoiThoaiRa[], nextCursor: string | null = null): DanhSachHoiThoai {
  return { items, next_cursor: nextCursor };
}

function chiTiet(item: HoiThoaiRa): HoiThoaiChiTiet {
  return { ...item, path: [] };
}

const goi = () => vi.mocked(api.danhSachHoiThoai);

function dungLen(props: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const onSelect = vi.fn();
  const onOpenConversationDeleted = vi.fn();
  render(
    <Sidebar
      openConversationId={null}
      onSelect={onSelect}
      onOpenConversationDeleted={onOpenConversationDeleted}
      {...props}
    />,
  );
  return { onSelect, onOpenConversationDeleted };
}

beforeEach(() => {
  localStorage.clear();
  goi().mockResolvedValue(trang([]));
});

describe("Sidebar — phan trang", () => {
  it("1. `next_cursor: null` thi KHONG co nut Tai them va khong goi trang ke", async () => {
    goi().mockResolvedValue(trang([hoiThoai({ id: "a", title: "Mot" })], null));

    dungLen();

    expect(await screen.findByText("Mot")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tải thêm" })).not.toBeInTheDocument();
    expect(goi()).toHaveBeenCalledTimes(1);
    expect(goi()).toHaveBeenCalledWith();
  });

  it("2. co con tro thi bam Tai them goi dung `updated_before` cua trang truoc", async () => {
    const conTro = "2026-09-02T03:04:05.678901+00:00";
    goi()
      .mockResolvedValueOnce(trang([hoiThoai({ id: "a", title: "Mot" })], conTro))
      .mockResolvedValueOnce(trang([hoiThoai({ id: "b", title: "Hai" })], null));

    dungLen();
    await screen.findByText("Mot");

    await userEvent.click(screen.getByRole("button", { name: "Tải thêm" }));

    expect(await screen.findByText("Hai")).toBeInTheDocument();
    expect(goi()).toHaveBeenNthCalledWith(2, conTro);
    expect(screen.queryByRole("button", { name: "Tải thêm" })).not.toBeInTheDocument();
  });

  it("3. hai trang tra ve cung mot hoi thoai thi no chi hien MOT lan", async () => {
    const trung = hoiThoai({ id: "a", title: "Trùng" });
    goi()
      .mockResolvedValueOnce(trang([trung, hoiThoai({ id: "b", title: "Hai" })], "cursor-1"))
      .mockResolvedValueOnce(trang([trung, hoiThoai({ id: "c", title: "Ba" })], null));

    dungLen();
    await screen.findByText("Trùng");

    await userEvent.click(screen.getByRole("button", { name: "Tải thêm" }));
    await screen.findByText("Ba");

    expect(screen.getAllByText("Trùng")).toHaveLength(1);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });
});

describe("Sidebar — xoa", () => {
  it("4. xoa xong thi hang bien mat NGAY, khong co lan `GET /conversations` thu hai", async () => {
    goi().mockResolvedValue(
      trang([hoiThoai({ id: "a", title: "Một" }), hoiThoai({ id: "b", title: "Hai" })]),
    );
    vi.mocked(api.xoaHoiThoai).mockResolvedValue(undefined);

    dungLen();
    await screen.findByText("Một");

    await userEvent.click(screen.getByRole("button", { name: "Xoá — Một" }));
    await userEvent.click(screen.getByRole("button", { name: "Xoá" }));

    await waitFor(() => {
      expect(screen.queryByText("Một")).not.toBeInTheDocument();
    });
    expect(api.xoaHoiThoai).toHaveBeenCalledWith("a");
    expect(screen.getByText("Hai")).toBeInTheDocument();
    expect(goi()).toHaveBeenCalledTimes(1);
  });

  it("5. xoa hoi thoai DANG MO thi man chat duoc bao", async () => {
    goi().mockResolvedValue(trang([hoiThoai({ id: "a", title: "Một" })]));
    vi.mocked(api.xoaHoiThoai).mockResolvedValue(undefined);

    const { onOpenConversationDeleted } = dungLen({ openConversationId: "a" });
    await screen.findByText("Một");

    await userEvent.click(screen.getByRole("button", { name: "Xoá — Một" }));
    await userEvent.click(screen.getByRole("button", { name: "Xoá" }));

    await waitFor(() => {
      expect(onOpenConversationDeleted).toHaveBeenCalledTimes(1);
    });
  });
});

describe("Sidebar — tim kiem cuc bo", () => {
  it("6. loc dung va KHONG goi mang mot lan nao", async () => {
    goi().mockResolvedValue(
      trang([
        hoiThoai({ id: "a", title: "Hạn mức Redis" }),
        hoiThoai({ id: "b", title: "Sửa nginx" }),
      ]),
    );

    dungLen();
    await screen.findByText("Hạn mức Redis");
    const truoc = goi().mock.calls.length;

    await userEvent.type(screen.getByLabelText("Tìm trong hội thoại đã tải"), "nginx");

    expect(screen.getByText("Sửa nginx")).toBeInTheDocument();
    expect(screen.queryByText("Hạn mức Redis")).not.toBeInTheDocument();
    expect(goi().mock.calls.length).toBe(truoc);
  });

  it("7. go KHONG DAU van tim ra tieu de co dau", async () => {
    goi().mockResolvedValue(trang([hoiThoai({ id: "a", title: "Hạn mức Redis" })]));

    dungLen();
    await screen.findByText("Hạn mức Redis");

    await userEvent.type(screen.getByLabelText("Tìm trong hội thoại đã tải"), "han muc");

    expect(screen.getByText("Hạn mức Redis")).toBeInTheDocument();
  });
});

describe("Sidebar — ghim va doi ten", () => {
  it("8. ghim goi `PATCH {pinned:true}` va day hang do len DAU", async () => {
    const cu = hoiThoai({ id: "a", title: "Cũ", updated_at: "2026-09-01T00:00:00+00:00" });
    const moi = hoiThoai({ id: "b", title: "Mới", updated_at: "2026-09-09T00:00:00+00:00" });
    goi().mockResolvedValue(trang([cu, moi]));
    vi.mocked(api.suaHoiThoai).mockResolvedValue(chiTiet({ ...cu, pinned: true }));

    dungLen();
    await screen.findByText("Cũ");
    // Truoc khi ghim: "Moi" dung dau vi `updated_at` moi hon.
    expect(within(screen.getAllByRole("listitem")[0]).getByText("Mới")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Ghim — Cũ" }));

    await waitFor(() => {
      expect(within(screen.getAllByRole("listitem")[0]).getByText("Cũ")).toBeInTheDocument();
    });
    expect(api.suaHoiThoai).toHaveBeenCalledWith("a", { pinned: true });
  });

  it("9. doi ten goi `PATCH {title}`; de trong goi `PATCH {title: null}`", async () => {
    const item = hoiThoai({ id: "a", title: "Cũ" });
    goi().mockResolvedValue(trang([item]));
    vi.mocked(api.suaHoiThoai).mockResolvedValue(chiTiet({ ...item, title: "Tên mới" }));

    dungLen();
    await screen.findByText("Cũ");

    await userEvent.click(screen.getByRole("button", { name: "Đổi tên — Cũ" }));
    await userEvent.clear(screen.getByLabelText("Tên mới"));
    await userEvent.type(screen.getByLabelText("Tên mới"), "Tên mới");
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));

    await waitFor(() => {
      expect(api.suaHoiThoai).toHaveBeenCalledWith("a", { title: "Tên mới" });
    });

    vi.mocked(api.suaHoiThoai).mockResolvedValue(chiTiet({ ...item, title: null }));
    await userEvent.click(screen.getByRole("button", { name: "Đổi tên — Tên mới" }));
    await userEvent.clear(screen.getByLabelText("Tên mới"));
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));

    await waitFor(() => {
      expect(api.suaHoiThoai).toHaveBeenLastCalledWith("a", { title: null });
    });
  });
});

describe("Sidebar — an/hien", () => {
  it("10a. bam an roi mount lai thi van an, va bam hien thi ghi lai vao localStorage", async () => {
    goi().mockResolvedValue(trang([hoiThoai({ id: "a", title: "Một" })]));

    const { unmount } = render(
      <Sidebar openConversationId={null} onSelect={vi.fn()} onOpenConversationDeleted={vi.fn()} />,
    );
    await screen.findByText("Một");

    await userEvent.click(screen.getByRole("button", { name: "Ẩn danh sách hội thoại" }));
    expect(screen.queryByText("Một")).not.toBeInTheDocument();
    expect(localStorage.getItem(KHOA_LUU)).toBe("closed");

    unmount();
    dungLen();

    expect(screen.queryByText("Một")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Mở danh sách hội thoại" }));
    expect(await screen.findByText("Một")).toBeInTheDocument();
    expect(localStorage.getItem(KHOA_LUU)).toBe("open");
  });

  it("10b. `localStorage` nem (che do rieng tu) thi sidebar van mo duoc, khong vo app", async () => {
    goi().mockResolvedValue(trang([hoiThoai({ id: "a", title: "Một" })]));
    const doc = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new DOMException("bi chan", "SecurityError");
      });
    const ghi = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("bi chan", "SecurityError");
    });

    dungLen();

    expect(await screen.findByText("Một")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ẩn danh sách hội thoại" }));
    expect(screen.queryByText("Một")).not.toBeInTheDocument();

    doc.mockRestore();
    ghi.mockRestore();
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
    goi().mockResolvedValue(
      trang([hoiThoai({ id: "a", title: "Một" }), hoiThoai({ id: "b", title: "Hai" })]),
    );

    const { rerender } = render(
      <Sidebar
        openConversationId="a"
        onSelect={vi.fn()}
        onOpenConversationDeleted={vi.fn()}
      />,
    );
    await screen.findByText("Hai");
    expect(goi()).toHaveBeenCalledTimes(1);

    rerender(
      <Sidebar
        openConversationId="b"
        onSelect={vi.fn()}
        onOpenConversationDeleted={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("Hai").closest("button")).toHaveAttribute("aria-current", "page");
    });
    expect(goi()).toHaveBeenCalledTimes(1);

    goi().mockResolvedValue(
      trang([hoiThoai({ id: "moi", title: "Vừa tạo" }), hoiThoai({ id: "a", title: "Một" })]),
    );
    rerender(
      <Sidebar
        openConversationId="moi"
        onSelect={vi.fn()}
        onOpenConversationDeleted={vi.fn()}
      />,
    );
    expect(await screen.findByText("Vừa tạo")).toBeInTheDocument();
    expect(goi()).toHaveBeenCalledTimes(2);
  });
});

describe("sortConversations", () => {
  it("12. ghim truoc, roi `updated_at` giam dan, roi `id` giam dan", () => {
    const xep = sortConversations([
      hoiThoai({ id: "a1", updated_at: "2026-09-01T00:00:00+00:00" }),
      hoiThoai({ id: "a2", updated_at: "2026-09-01T00:00:00+00:00" }),
      hoiThoai({ id: "b", updated_at: "2026-09-05T00:00:00+00:00" }),
      hoiThoai({ id: "c", updated_at: "2026-08-01T00:00:00+00:00", pinned: true }),
    ]);

    expect(xep.map((x) => x.id)).toEqual(["c", "b", "a2", "a1"]);
  });
});
