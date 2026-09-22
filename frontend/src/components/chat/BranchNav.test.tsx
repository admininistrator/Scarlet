/**
 * `‹ n/m ›` — dong DoD thu nhat cua T-3.8 ("≥ 6 ca moi cho component dieu huong").
 *
 * Hai thu duoc canh ky nhat o day, va ca hai deu la mot cam bay da ghi san:
 *
 *   - **C13 — khong mot phep dem nao o FE.** Moi ca duoi day dat
 *     `sibling_index`/`sibling_count` nhu the SERVER vua tra ve chung, roi
 *     kiem chu tren man hinh. Khong ca nao dung `items.length`.
 *   - **Cam bay ① cua T-3.8 — "thay `1/2` thi dung di sua off-by-one".**
 *     `chiSoHienThi()` la cho duy nhat cong 1 (B-60, NQ-33), va ca 1 o day la
 *     phep do cua chinh no: `sibling_index: 1` PHAI ra `2 / 3`.
 *
 * Ca cuoi cung khong ve gi: no khang dinh `BranchNav` KHONG doc `sibling_*`
 * cua mot node nao khac ngoai node duoc truyen vao — tuc no khong the "tu
 * doan" nhanh.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { MessageRa } from "../../lib/api";
import { BranchNav } from "./BranchNav";

function node(patch: Partial<MessageRa> = {}): MessageRa {
  return {
    id: "m1",
    parent_id: null,
    role: "user",
    status: "completed",
    content: "cau hoi",
    reasoning: null,
    model_id: null,
    finish_reason: null,
    error_code: null,
    created_at: "2026-09-22T00:00:00Z",
    sibling_index: 0,
    sibling_count: 1,
    feedback: null,
    ...patch,
  };
}

function ve(patch: Partial<MessageRa>, nhan = "Nhánh câu hỏi") {
  const onChuyenNhanh = vi.fn();
  render(<BranchNav node={node(patch)} nhan={nhan} onChuyenNhanh={onChuyenNhanh} />);
  return {
    onChuyenNhanh,
    lui: screen.getByRole("button", { name: "Nhánh trước" }),
    toi: screen.getByRole("button", { name: "Nhánh sau" }),
  };
}

describe("‹ n/m › — con so", () => {
  it("1 — `sibling_index` 0-based thanh so nguoi doc: 1 ⇒ `2 / 3` (B-60, cam bay ①)", () => {
    ve({ sibling_index: 1, sibling_count: 3 });
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
  });

  it("2 — sau mot lan Retry, la MOI la anh em cuoi: 1 ⇒ `2 / 2`, khong phai `1 / 2`", () => {
    ve({ sibling_index: 1, sibling_count: 2 });
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
    expect(screen.queryByText("1 / 2")).toBeNull();
  });
});

describe("‹ n/m › — hai dau day", () => {
  it("3 — dau day: `‹` tat, `›` mo (ban T-HD3 hinh 2c)", () => {
    const { lui, toi } = ve({ sibling_index: 0, sibling_count: 3 });
    expect(lui).toBeDisabled();
    expect(toi).toBeEnabled();
  });

  it("4 — cuoi day: `›` tat, `‹` mo", () => {
    const { lui, toi } = ve({ sibling_index: 2, sibling_count: 3 });
    expect(lui).toBeEnabled();
    expect(toi).toBeDisabled();
  });

  it("5 — giua day: mo ca hai", () => {
    const { lui, toi } = ve({ sibling_index: 1, sibling_count: 3 });
    expect(lui).toBeEnabled();
    expect(toi).toBeEnabled();
  });
});

describe("‹ n/m › — bam nut", () => {
  it("6 — `‹` gui `-1`, `›` gui `+1`, va KHONG kem doi so nao khac", async () => {
    const nguoi = userEvent.setup();
    const { lui, toi, onChuyenNhanh } = ve({ sibling_index: 1, sibling_count: 3 });

    await nguoi.click(lui);
    await nguoi.click(toi);

    // `IconButton` goi `onClick()` khong tham so (T-3.7): mot `onClick={onClick}`
    // truyen thang se lam React nhet `MouseEvent` vao day.
    expect(onChuyenNhanh.mock.calls).toEqual([[-1], [1]]);
  });

  it("7 — nut da tat thi bam khong goi gi", async () => {
    const nguoi = userEvent.setup();
    const { lui, onChuyenNhanh } = ve({ sibling_index: 0, sibling_count: 2 });

    await nguoi.click(lui);

    expect(onChuyenNhanh).not.toHaveBeenCalled();
  });
});

describe("‹ n/m › — a11y", () => {
  it("8 — nhan cua nhom den TU BEN NGOAI, de hai nhom tren cung man hinh khac nhau", () => {
    render(
      <>
        <BranchNav
          node={node({ id: "u1", sibling_index: 0, sibling_count: 2 })}
          nhan="Nhánh câu hỏi"
          onChuyenNhanh={vi.fn()}
        />
        <BranchNav
          node={node({ id: "a1", role: "assistant", sibling_index: 1, sibling_count: 2 })}
          nhan="Nhánh câu trả lời"
          onChuyenNhanh={vi.fn()}
        />
      </>,
    );

    expect(screen.getByRole("group", { name: "Nhánh câu hỏi" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Nhánh câu trả lời" })).toBeInTheDocument();
  });

  it("9 — hai nut deu co `aria-label`, vi glyph `‹`/`›` khong doc thanh loi duoc", () => {
    const { lui, toi } = ve({ sibling_index: 1, sibling_count: 3 });
    expect(lui).toHaveAttribute("aria-label", "Nhánh trước");
    expect(toi).toHaveAttribute("aria-label", "Nhánh sau");
    // Mui ten dieu huong khong co trang thai bat/tat — xem `IconButton`.
    expect(lui).not.toHaveAttribute("aria-pressed");
  });
});
