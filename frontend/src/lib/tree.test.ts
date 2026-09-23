/**
 * `lib/tree.ts` — B-199.
 *
 * Bo test dau tien cua tang FE. Chon `tree.ts` lam chỗ mở hàng khong phai vi
 * no de: no la file FE duy nhat mang **luat nghiep vu** (§8.2, §8.3 — cay
 * message, dieu huong anh em, chu dang bay), tuc file duy nhat ma mot loi o
 * day doc ra thanh "chat sai" chu khong phai "chat xau".
 *
 * Ba cho duoc canh ky nhat, ca ba deu la cam bay da ghi san trong `tree.ts`:
 *
 *   - `startGeneration` XOA chu cu (C3 — F5 giua luc stream khong duoc nhan doi chu)
 *   - `displayIndex` la CHO DUY NHAT cong 1 (B-60, NQ-33)
 *   - `adjacentSiblingId` doc theo `sibling_index`, KHONG theo vi tri trong mang
 */

import { describe, expect, it } from "vitest";

import type { SiblingsOut, ConversationDetail, MessageOut } from "./api";
import {
  startGeneration,
  canStream,
  emptyTree,
  displayIndex,
  hasSiblings,
  canGoBack,
  canGoForward,
  adjacentSiblingId,
  isLast,
  loadConversation,
  appendDelta,
  content,
  appendReasoning,
  reasoningOf,
  findNode,
} from "./tree";

function message(overrides: Partial<MessageOut> & Pick<MessageOut, "id">): MessageOut {
  return {
    parent_id: null,
    role: "assistant",
    status: "completed",
    content: "",
    reasoning: null,
    model_id: "deepseek-flash",
    finish_reason: "stop",
    error_code: null,
    created_at: "2026-09-20T00:00:00Z",
    sibling_index: 0,
    sibling_count: 1,
    feedback: null,
    ...overrides,
  };
}

function conversation(path: MessageOut[], id = "conv-1"): ConversationDetail {
  return {
    id,
    title: null,
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: path.length > 0 ? path[path.length - 1].id : null,
    pinned: false,
    created_at: "2026-09-20T00:00:00Z",
    updated_at: "2026-09-20T00:00:00Z",
    path,
  } as ConversationDetail;
}

describe("chu dang bay", () => {
  it("noi delta vao cuoi, khong dung toi reasoning", () => {
    let tree = startGeneration(emptyTree(), "m1");
    tree = appendDelta(tree, "m1", "Xin ");
    tree = appendDelta(tree, "m1", "chao");

    expect(tree.inFlight["m1"]).toEqual({ content: "Xin chao", reasoning: "" });
  });

  it("reasoning di vao CHO KHAC content (§7.4, B-33)", () => {
    let tree = startGeneration(emptyTree(), "m1");
    tree = appendDelta(tree, "m1", "tra loi");
    tree = appendReasoning(tree, "m1", "suy nghi");

    expect(tree.inFlight["m1"].content).toBe("tra loi");
    expect(tree.inFlight["m1"].reasoning).toBe("suy nghi");
  });

  it("batDauSinh XOA chu cu — C3, F5 giua luc stream", () => {
    let tree = startGeneration(emptyTree(), "m1");
    tree = appendDelta(tree, "m1", "phan da chay tren man hinh");

    // Duong dung lai tu Postgres phat `start` roi phat LAI toan bo noi dung.
    tree = startGeneration(tree, "m1");
    tree = appendDelta(tree, "m1", "phan da chay tren man hinh");

    expect(tree.inFlight["m1"].content).toBe("phan da chay tren man hinh");
  });

  it("uu tien chu dang bay hon cot content cua Postgres", () => {
    const node = message({ id: "m1", content: "ban trong Postgres" });
    let tree = loadConversation(emptyTree(), conversation([node]));
    expect(content(tree, node)).toBe("ban trong Postgres");

    tree = appendDelta(startGeneration(tree, "m1"), "m1", "ban dang bay");
    expect(content(tree, node)).toBe("ban dang bay");
  });

  it("phanReasoning ve chuoi rong khi khong co ca hai nguon", () => {
    const node = message({ id: "m1", reasoning: null });
    const tree = loadConversation(emptyTree(), conversation([node]));

    expect(reasoningOf(tree, node)).toBe("");
  });
});

describe("napHoiThoai", () => {
  // Thu tu trong ba ca duoi la co y: chu dang bay phai duoc them SAU lan
  // `napHoiThoai` dau tien. `emptyTree()` co `conversationId: null`, nen lan nap
  // dau **luon** la mot lan doi hoi thoai — day la hanh vi dung, va viet test
  // theo thu tu nguoc lai chi do chinh minh.
  it("GIU chu dang bay khi lam tuoi CUNG mot hoi thoai", () => {
    let tree = loadConversation(emptyTree(), conversation([message({ id: "m1" })], "conv-1"));
    tree = appendDelta(startGeneration(tree, "m1"), "m1", "dang chay");

    // Day la ca that: `GET /conversations/{id}` chay ve giua luc stream.
    tree = loadConversation(tree, conversation([message({ id: "m1" })], "conv-1"));

    expect(tree.inFlight["m1"].content).toBe("dang chay");
  });

  it("DON sach chu dang bay khi doi hoi thoai", () => {
    let tree = loadConversation(emptyTree(), conversation([message({ id: "m1" })], "conv-1"));
    tree = appendDelta(startGeneration(tree, "m1"), "m1", "dang chay");

    tree = loadConversation(tree, conversation([message({ id: "m9" })], "conv-2"));

    expect(tree.inFlight).toEqual({});
  });

  it("lan nap DAU TIEN tu cay rong cung la mot lan doi hoi thoai", () => {
    let tree = appendDelta(startGeneration(emptyTree(), "m1"), "m1", "chu mo coi");

    tree = loadConversation(tree, conversation([message({ id: "m1" })], "conv-1"));

    expect(tree.inFlight).toEqual({});
  });
});

describe("canStream", () => {
  it.each([
    ["queued", true],
    ["streaming", true],
    ["completed", false],
    ["failed", false],
    ["cancelled", false],
  ])("la assistant o trang thai %s -> can stream = %s", (status, expected) => {
    const unknown = message({ id: "m1", role: "assistant", status: status as MessageOut["status"] });
    const tree = loadConversation(emptyTree(), conversation([unknown]));

    expect(canStream(tree) !== null).toBe(expected);
  });

  it("la cua NGUOI DUNG thi khong bao gio can stream", () => {
    const unknown = message({ id: "m1", role: "user", status: "queued" });
    const tree = loadConversation(emptyTree(), conversation([unknown]));

    expect(canStream(tree)).toBeNull();
  });

  it("cay rong -> null, khong nem", () => {
    expect(canStream(emptyTree())).toBeNull();
    expect(isLast(emptyTree())).toBeNull();
  });
});

describe("timNode", () => {
  it("tra ve null khi khong co, khong nem", () => {
    const tree = loadConversation(emptyTree(), conversation([message({ id: "m1" })]));

    expect(findNode(tree, "m1")?.id).toBe("m1");
    expect(findNode(tree, "khong-ton-tai")).toBeNull();
  });
});

describe("dieu huong anh em", () => {
  it("chiSoHienThi la CHO DUY NHAT cong 1 (B-60, NQ-33)", () => {
    expect(displayIndex(message({ id: "m", sibling_index: 0 }))).toBe(1);
    expect(displayIndex(message({ id: "m", sibling_index: 2 }))).toBe(3);
  });

  it.each([
    [0, 1, false, false, false],
    [0, 3, true, false, true],
    [1, 3, true, true, true],
    [2, 3, true, true, false],
  ])(
    "index %i / count %i -> coAnhEm=%s coTheLui=%s coTheToi=%s",
    (index, count, siblings, back, forward) => {
      const node = message({ id: "m", sibling_index: index, sibling_count: count });

      expect(hasSiblings(node)).toBe(siblings);
      expect(canGoBack(node)).toBe(back);
      expect(canGoForward(node)).toBe(forward);
    },
  );

  it("idAnhEmKe doc theo sibling_index, KHONG theo vi tri trong mang", () => {
    // `items` co tinh xao tron: neu ham doc theo vi tri mang thi no se tra ve
    // "m-c" cho huong +1, va khong co gi bao la sai.
    const siblings: SiblingsOut = {
      message_id: "m-b",
      parent_id: "cha",
      sibling_index: 1,
      sibling_count: 3,
      items: [
        message({ id: "m-c", sibling_index: 2, sibling_count: 3 }),
        message({ id: "m-a", sibling_index: 0, sibling_count: 3 }),
        message({ id: "m-b", sibling_index: 1, sibling_count: 3 }),
      ],
    };

    expect(adjacentSiblingId(siblings, -1)).toBe("m-a");
    expect(adjacentSiblingId(siblings, 1)).toBe("m-c");
  });

  it("tra null o hai dau thay vi vong lai", () => {
    const first: SiblingsOut = {
      message_id: "m-a",
      parent_id: null,
      sibling_index: 0,
      sibling_count: 2,
      items: [message({ id: "m-a", sibling_index: 0, sibling_count: 2 })],
    };
    const last: SiblingsOut = { ...first, message_id: "m-b", sibling_index: 1 };

    expect(adjacentSiblingId(first, -1)).toBeNull();
    expect(adjacentSiblingId(last, 1)).toBeNull();
  });

  it("tra null khi `items` thieu dung cai anh em duoc hoi", () => {
    // Ca nay la ly do docstring `adjacentSiblingId` viet "mot ngay nao do `items` bi
    // loc": ham phai chiu duoc chuyen do thay vi tra ve `undefined`.
    const siblings: SiblingsOut = {
      message_id: "m-a",
      parent_id: null,
      sibling_index: 0,
      sibling_count: 2,
      items: [message({ id: "m-a", sibling_index: 0, sibling_count: 2 })],
    };

    expect(adjacentSiblingId(siblings, 1)).toBeNull();
  });
});
