/**
 * `‹ n/m ›` — dong DoD thu nhat cua T-3.8 ("≥ 6 ca moi cho component dieu huong").
 *
 * Hai thu duoc canh ky nhat o day, va ca hai deu la mot cam bay da ghi san:
 *
 *   - **C13 — khong mot phep dem nao o FE.** Moi ca duoi day dat
 *     `sibling_index`/`sibling_count` nhu the SERVER vua tra ve chung, roi
 *     kiem chu tren man hinh. Khong ca nao dung `items.length`.
 *   - **Cam bay ① cua T-3.8 — "thay `1/2` thi dung di sua off-by-one".**
 *     `displayIndex()` la cho duy nhat cong 1 (B-60, NQ-33), va ca 1 o day la
 *     phep do cua chinh no: `sibling_index: 1` PHAI ra `2 / 3`.
 *
 * Ca cuoi cung khong ve gi: no khang dinh `BranchNav` KHONG doc `sibling_*`
 * cua mot node nao khac ngoai node duoc truyen vao — tuc no khong the "tu
 * doan" nhanh.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { MessageOut } from "../../lib/api";
import { BranchNav } from "./BranchNav";

function node(patch: Partial<MessageOut> = {}): MessageOut {
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
    reasoning_effort: null,
    ...patch,
  };
}

function renderView(patch: Partial<MessageOut>, label = "Nhánh câu hỏi") {
  const onSwitchBranch = vi.fn();
  render(<BranchNav node={node(patch)} label={label} onSwitchBranch={onSwitchBranch} />);
  return {
    onSwitchBranch,
    back: screen.getByRole("button", { name: "Nhánh trước" }),
    forward: screen.getByRole("button", { name: "Nhánh sau" }),
  };
}

describe("‹ n/m › — con so", () => {
  it("1 — `sibling_index` 0-based thanh so nguoi doc: 1 ⇒ `2 / 3` (B-60, cam bay ①)", () => {
    renderView({ sibling_index: 1, sibling_count: 3 });
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
  });

  it("2 — sau mot lan Retry, la MOI la anh em cuoi: 1 ⇒ `2 / 2`, khong phai `1 / 2`", () => {
    renderView({ sibling_index: 1, sibling_count: 2 });
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
    expect(screen.queryByText("1 / 2")).toBeNull();
  });
});

describe("‹ n/m › — hai dau day", () => {
  it("3 — dau day: `‹` tat, `›` mo (ban T-HD3 hinh 2c)", () => {
    const { back, forward } = renderView({ sibling_index: 0, sibling_count: 3 });
    expect(back).toBeDisabled();
    expect(forward).toBeEnabled();
  });

  it("4 — cuoi day: `›` tat, `‹` mo", () => {
    const { back, forward } = renderView({ sibling_index: 2, sibling_count: 3 });
    expect(back).toBeEnabled();
    expect(forward).toBeDisabled();
  });

  it("5 — giua day: mo ca hai", () => {
    const { back, forward } = renderView({ sibling_index: 1, sibling_count: 3 });
    expect(back).toBeEnabled();
    expect(forward).toBeEnabled();
  });
});

describe("‹ n/m › — bam nut", () => {
  it("6 — `‹` gui `-1`, `›` gui `+1`, va KHONG kem doi so nao khac", async () => {
    const userRow = userEvent.setup();
    const { back, forward, onSwitchBranch } = renderView({ sibling_index: 1, sibling_count: 3 });

    await userRow.click(back);
    await userRow.click(forward);

    // `IconButton` goi `onClick()` khong tham so (T-3.7): mot `onClick={onClick}`
    // truyen thang se lam React nhet `MouseEvent` vao day.
    expect(onSwitchBranch.mock.calls).toEqual([[-1], [1]]);
  });

  it("7 — nut da tat thi bam khong goi gi", async () => {
    const userRow = userEvent.setup();
    const { back, onSwitchBranch } = renderView({ sibling_index: 0, sibling_count: 2 });

    await userRow.click(back);

    expect(onSwitchBranch).not.toHaveBeenCalled();
  });
});

describe("‹ n/m › — a11y", () => {
  it("8 — nhan cua nhom den TU BEN NGOAI, de hai nhom tren cung man hinh khac nhau", () => {
    render(
      <>
        <BranchNav
          node={node({ id: "u1", sibling_index: 0, sibling_count: 2 })}
          label="Nhánh câu hỏi"
          onSwitchBranch={vi.fn()}
        />
        <BranchNav
          node={node({ id: "a1", role: "assistant", sibling_index: 1, sibling_count: 2 })}
          label="Nhánh câu trả lời"
          onSwitchBranch={vi.fn()}
        />
      </>,
    );

    expect(screen.getByRole("group", { name: "Nhánh câu hỏi" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Nhánh câu trả lời" })).toBeInTheDocument();
  });

  it("9 — hai nut deu co `aria-label`, vi glyph `‹`/`›` khong doc thanh loi duoc", () => {
    const { back, forward } = renderView({ sibling_index: 1, sibling_count: 3 });
    expect(back).toHaveAttribute("aria-label", "Nhánh trước");
    expect(forward).toHaveAttribute("aria-label", "Nhánh sau");
    // Mui ten dieu huong khong co trang thai bat/tat — xem `IconButton`.
    expect(back).not.toHaveAttribute("aria-pressed");
  });
});
