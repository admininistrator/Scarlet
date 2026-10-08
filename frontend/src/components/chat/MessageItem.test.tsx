/**
 * Bon trang thai cua bong bong — "Viec" dong 4 cua T-3.5, ban T-HD3 hinh 2a.
 *
 * Moi ca o day kiem mot dieu ma mot phep doc mat khong bat duoc: trang thai
 * nao duoc suy ra tu truong nao. Cu the la ca 2 — `status` con `streaming`
 * ma `content` trong Postgres van RONG la chuyen BINH THUONG giua luot sinh
 * (§7.2 ③), nen "chua co chu" phai doc tu `inFlight` chu khong tu `path`.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { MessageOut, ModelOut } from "../../lib/api";
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
    reasoning_effort: null,
    ...patch,
  };
}

function model(id: string, displayName: string): ModelOut {
  return {
    id,
    display_name: displayName,
    provider: "Hang",
    provider_id: null,
    capabilities: [],
    context_window: 1000,
    max_output: 100,
    default: false,
    badge: null,
    available: true,
    unavailable_reason: null,
    reasoning: null,
    pricing: null,
    pricing_mode: "unmetered",
    checked_at: null,
    stale_after_s: 30,
  };
}

/** Danh muc gia cho chip — ten hien thi KHAC han id de phep so co nghia. */
const MODELS: ModelOut[] = [
  model("ds-id", "DeepSeek Flash"),
  model("haiku-id", "Claude Haiku 4.5"),
  model("nr-grok", "Grok 4.6"),
];

function renderView(
  n: MessageOut,
  tree: TreeState = emptyTree(),
  running = false,
  busy = false,
  onRetry: (messageId: string) => void = vi.fn(),
) {
  return render(
    <MessageItem
      node={n}
      tree={tree}
      models={MODELS}
      running={running}
      busy={busy}
      onRetry={onRetry}
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

  it("3 — xong: hien chip model (ten hien thi) va khong con chu 'dang cho'", () => {
    const { container } = renderView(node({ status: "completed", content: "Xong roi.", model_id: "ds-id" }));
    expect(screen.queryByText("Đang chờ Scarlet trả lời")).toBeNull();
    expect(container.textContent).toContain("DeepSeek Flash");
  });

  it("4 — loi: hien ma loi nguyen van va MOT nut Thu lai, gui dung id message", async () => {
    const onRetry = vi.fn();
    renderView(node({ status: "failed", error_code: "CONTEXT_TOO_LARGE" }), emptyTree(), false, false, onRetry);
    expect(screen.getByText("CONTEXT_TOO_LARGE")).toBeInTheDocument();
    expect(screen.getByText("Không nhận được câu trả lời")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /thử lại/i })).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(onRetry).toHaveBeenCalledWith("m1");
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

/**
 * T-S.15 — chip "model · muc" (ban T-HD3-v2 3c) va khoi "Suy luan" (3d).
 *
 * Chip doc model va muc DA DUNG cua chinh message (`MessageOut`), khong doc
 * picker — nen bong bong nay khong nhan prop nao ve picker ca.
 */
describe("chip model · muc (ban T-HD3-v2 3c)", () => {
  function chip() {
    const list = screen.getAllByRole("list")[0];
    return within(list).getAllByRole("listitem")[0];
  }

  it("11 — ten hien thi cua catalog · nhan muc tieng Anh; hai manh la hai span, dau '·' aria-hidden", () => {
    renderView(node({ status: "completed", content: "x", model_id: "ds-id", reasoning_effort: "high" }));
    const spans = chip().querySelectorAll("span");
    expect([...spans].map((s) => s.textContent)).toEqual(["DeepSeek Flash", "·", "High"]);
    expect(spans[1]).toHaveAttribute("aria-hidden", "true");
    // Khong bao gio in id tho khi catalog co ten.
    expect(chip().textContent).not.toContain("ds-id");
  });

  it("12 — muc 'off' VAN hien 'Off' (model co hang muc, nguoi dung chon tat)", () => {
    renderView(node({ status: "completed", content: "x", model_id: "haiku-id", reasoning_effort: "off" }));
    expect(chip()).toHaveTextContent("Claude Haiku 4.5·Off");
  });

  it("13 — khong co muc ⇒ chi ten model, khong dau '·'", () => {
    renderView(node({ status: "completed", content: "x", model_id: "nr-grok", reasoning_effort: null }));
    expect(chip().textContent).toBe("Grok 4.6");
  });

  it("14 — model da bien mat khoi catalog ⇒ chip hien `model_id` tho, khong o trong", () => {
    renderView(node({ status: "completed", content: "x", model_id: "model-da-go", reasoning_effort: "low" }));
    expect(chip()).toHaveTextContent("model-da-go·Low");
  });

  it("15 — hai anh em cung cha: moi bong bong ve chip cua CHINH no (UC-04 dong 4)", () => {
    const { rerender } = renderView(
      node({ status: "completed", content: "x", model_id: "ds-id", reasoning_effort: "high", sibling_count: 2 }),
    );
    expect(chip()).toHaveTextContent("DeepSeek Flash·High");

    rerender(
      <MessageItem
        node={node({ status: "completed", content: "x", model_id: "nr-grok", sibling_index: 1, sibling_count: 2 })}
        tree={emptyTree()}
        models={MODELS}
        running={false}
        busy={false}
        onRetry={vi.fn()}
        onFeedback={vi.fn()}
        onEdit={vi.fn()}
        onSwitchBranch={vi.fn()}
      />,
    );
    expect(chip().textContent).toBe("Grok 4.6");
  });
});

describe("khoi Suy luan (ban T-HD3-v2 3d)", () => {
  it("16 — `reasoning` NULL ⇒ khong dung khoi (khong nut, khong khoi rong)", () => {
    renderView(node({ status: "completed", content: "x", reasoning: null }));
    expect(screen.queryByRole("button", { name: "Suy luận" })).toBeNull();
    expect(screen.queryByText("Suy luận")).toBeNull();
  });

  it("17 — `reasoning` chi co khoang trang ⇒ cung khong dung (dieu kien la `trim()`)", () => {
    renderView(node({ status: "completed", content: "x", reasoning: "  \n " }));
    expect(screen.queryByRole("button", { name: "Suy luận" })).toBeNull();
  });

  it("18 — co suy luan ⇒ nut `aria-expanded` gap san; bam mo ra dung chu, bam lai gap", async () => {
    renderView(node({ status: "completed", content: "x", reasoning: "buoc 1\nbuoc 2" }));
    const toggle = screen.getByRole("button", { name: "Suy luận" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/buoc 1/)).toBeNull();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/buoc 1/)).toBeInTheDocument();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
