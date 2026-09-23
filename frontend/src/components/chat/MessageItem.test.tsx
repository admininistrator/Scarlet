/**
 * Bon trang thai cua bong bong — "Viec" dong 4 cua T-3.5, ban T-HD3 hinh 2a.
 *
 * Moi ca o day kiem mot dieu ma mot phep doc mat khong bat duoc: trang thai
 * nao duoc suy ra tu truong nao. Cu the la ca 2 — `status` con `streaming`
 * ma `content` trong Postgres van RONG la chuyen BINH THUONG giua luot sinh
 * (§7.2 ③), nen "chua co chu" phai doc tu `inFlight` chu khong tu `path`.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { MessageOut } from "../../lib/api";
import { emptyTree, type TreeState } from "../../lib/tree";
import { MessageItem } from "./MessageItem";

function node(patch: Partial<MessageOut> = {}): MessageOut {
  return {
    id: "m1",
    parent_id: null,
    role: "assistant",
    status: "completed",
    content: "",
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

function renderView(n: MessageOut, tree: TreeState = emptyTree(), running = false, busy = false) {
  return render(
    <MessageItem
      node={n}
      tree={tree}
      notes={[]}
      running={running}
      busy={busy}
      selectedModel={null}
      onRetry={vi.fn()}
      onFeedback={vi.fn()}
      onEdit={vi.fn()}
      onSwitchBranch={vi.fn()}
    />,
  );
}

describe("bon trang thai", () => {
  it("1 — dang cho: noi ra rang dang cho, khong de bong bong rong (§7.4)", () => {
    renderView(node({ status: "queued" }), emptyTree(), true);
    expect(screen.getByText("Đang chờ Scarlet trả lời")).toBeInTheDocument();
  });

  it("2 — dang stream: chu doc tu `dangBay`, KHONG tu `path[i].content`", () => {
    const tree: TreeState = { ...emptyTree(), inFlight: { m1: { content: "Xin ch", reasoning: "" } } };
    const { container } = renderView(node({ status: "streaming", content: "" }), tree, true);
    expect(container.textContent).toContain("Xin ch");
    // Chip / dieu huong nhanh chua duoc dung — quy tac 2 cua ban T-HD3.
    expect(container.querySelector("ul")).toBeNull();
  });

  it("3 — xong: hien chip model va khong con chu 'dang cho'", () => {
    const { container } = renderView(
      node({ status: "completed", content: "Xong roi.", model_id: "mot-model-nao-do" }),
    );
    expect(screen.queryByText("Đang chờ Scarlet trả lời")).toBeNull();
    expect(container.textContent).toContain("mot-model-nao-do");
  });

  it("4 — loi: hien ma loi nguyen van va mot nut Thu lai", () => {
    renderView(node({ status: "failed", error_code: "CONTEXT_TOO_LARGE" }));
    expect(screen.getByText("CONTEXT_TOO_LARGE")).toBeInTheDocument();
    expect(screen.getByText("Không nhận được câu trả lời")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
  });

  it("5 — loi GIU lai phan chu da chay duoc (ban T-HD3)", () => {
    const tree: TreeState = { ...emptyTree(), inFlight: { m1: { content: "Da chay duoc", reasoning: "" } } };
    const { container } = renderView(node({ status: "failed", error_code: "ERR_PROVIDER_502" }), tree);
    expect(container.textContent).toContain("Da chay duoc");
    expect(container.textContent).toContain("ERR_PROVIDER_502");
  });

  it("6 — bong bong nguoi dung la chu tho, khong qua markdown", () => {
    const { container } = renderView(node({ role: "user", content: "hoi ve `code` va **dam**" }));
    expect(container.querySelector("strong")).toBeNull();
    expect(container.textContent).toContain("hoi ve `code` va **dam**");
  });

  it("7 — `‹ n/m ›` doc thang tu server, va tat nut o dau day (C13)", () => {
    renderView(node({ status: "completed", content: "x", sibling_index: 0, sibling_count: 3 }));
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nhánh trước" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Nhánh sau" })).toBeEnabled();
  });
});

/**
 * T-3.8 — sua cau hoi sinh anh em cua message USER (§8.2), nen bong bong nguoi
 * dung phai mang `‹ n/m ›` cua chinh no. Bo ba ca duoi day la phep do cua UC-04
 * dong 2: khong co chung thi mot nhanh vua tao ra khong co duong nao quay lai.
 */
describe("bong bong nguoi dung co nhanh", () => {
  it("8 — co anh em ⇒ hien `‹ n/m ›` duoi bong bong NGUOI DUNG", () => {
    renderView(node({ role: "user", content: "cau hoi cu", sibling_index: 0, sibling_count: 2 }));
    expect(screen.getByRole("group", { name: "Nhánh câu hỏi" })).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
  });

  it("9 — khong co anh em ⇒ khong hien, chi con nut Sua", () => {
    renderView(node({ role: "user", content: "cau hoi", sibling_count: 1 }));
    expect(screen.queryByRole("group", { name: "Nhánh câu hỏi" })).toBeNull();
    expect(screen.getByRole("button", { name: "Sửa" })).toBeInTheDocument();
  });

  it("10 — nut Luu TAT khi dang ban (B-232: `PATCH` ngoai vung phu §11.4)", async () => {
    const userRow = userEvent.setup();
    renderView(node({ role: "user", content: "cau hoi" }), emptyTree(), false, true);

    await userRow.click(screen.getByRole("button", { name: "Sửa" }));

    expect(screen.getByRole("button", { name: "Lưu" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Thôi" })).toBeEnabled();
  });
});
