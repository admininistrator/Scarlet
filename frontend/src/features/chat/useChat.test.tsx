/**
 * `Idempotency-Key` cua nut Thu lai — nua FE cua B-231 (NQ-93).
 *
 * Nua backend (route nay tu nay BAT BUOC header, thieu ⇒ `400`) do
 * `backend/tests/api/test_idempotency.py` canh. File nay canh thu ma **chi**
 * FE quyet dinh duoc, va no la thu lam cho lop kia co tac dung: hai lan bam
 * nhanh phai mang CUNG mot khoa. Sinh khoa moi o moi lan bam la dung cai bay
 * C22 ta — luc do Redis thay hai request khac nhau, va nguoi dung tra hai hoa
 * don cho mot lan bam nham.
 *
 * Ba dong luat duoc do rieng tung dong:
 *
 *   1. sinh o lan bam dau cho mot bo `(message, model, muc)` (T-S.15);
 *   2. GIU nguyen qua moi lan hong;
 *   3. BO khi va chi khi `202` ve — lan bam sau la mot anh em that (§8.2).
 *
 * T-S.15 them mot khoi: MOT nut Thu lai gui model + muc cua picker (§24.2b·S4).
 *
 * KH tham chieu: §11.4, §8.2, §24.2b·S4, C22, S5 · tasks.md B-231, T-3.7,
 * T-3.4, T-S.15.
 */

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChat, type ChatOptions } from "./useChat";
import { api, type ConversationDetail, type MessageOut, type ModelOut } from "../../lib/api";

vi.mock("../../lib/api", async (original) => {
  const actual = await original<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      getConversation: vi.fn(),
      retry: vi.fn(),
      sendFeedback: vi.fn(),
    },
  };
});

/*
  `openStream` mo mot `EventSource` that — thu khong ton tai trong jsdom. Thay
  no bang mot tay cam rong: file nay do chuoi request di ra, khong do stream.
*/
vi.mock("../../lib/sse", async (original) => {
  const actual = await original<typeof import("../../lib/sse")>();
  return { ...actual, openStream: () => ({ close: () => {}, cursor: () => "" }) };
});

const CONVERSATION = "conv-1";
const ANSWER_ID = "msg-assistant";
const PICKED_MODEL = "model-co-muc";
const PLAIN_MODEL = "model-khong-muc";

function model(id: string, reasoning: ModelOut["reasoning"]): ModelOut {
  return {
    id,
    display_name: id,
    provider: "Hang",
    provider_id: "hang",
    capabilities: [],
    context_window: 1000,
    max_output: 100,
    default: false,
    badge: null,
    available: true,
    unavailable_reason: null,
    reasoning,
    pricing: null,
    pricing_mode: "unmetered",
    checked_at: null,
    stale_after_s: 30,
  };
}

/** Danh muc gia: mot model co muc (mac dinh `high`), mot model khong co khoi `reasoning`. */
const MODELS: ModelOut[] = [
  model(PICKED_MODEL, { default: "high", options: [{ id: "low" }, { id: "high" }] }),
  model(PLAIN_MODEL, null),
];

function node(overrides: Partial<MessageOut> = {}): MessageOut {
  return {
    id: ANSWER_ID,
    parent_id: "msg-user",
    role: "assistant",
    status: "completed",
    content: "tra loi",
    reasoning: null,
    model_id: "model-cu",
    finish_reason: "stop",
    error_code: null,
    created_at: "2026-09-22T00:00:00Z",
    sibling_index: 0,
    sibling_count: 1,
    feedback: null,
    reasoning_effort: null,
    ...overrides,
  };
}

function detail(): ConversationDetail {
  return {
    id: CONVERSATION,
    title: null,
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: ANSWER_ID,
    pinned: false,
    created_at: "2026-09-22T00:00:00Z",
    updated_at: "2026-09-22T00:00:00Z",
    path: [node({ id: "msg-user", role: "user", parent_id: null }), node()],
  };
}

const getConversation = vi.mocked(api.getConversation);
const retry = vi.mocked(api.retry);
const sendFeedback = vi.mocked(api.sendFeedback);

/** Khoa cua lan goi `api.retry` thu `n` — tham so thu ba (B-231). */
function keyOfCall(n: number): string {
  return retry.mock.calls[n][2];
}

beforeEach(() => {
  getConversation.mockResolvedValue(detail());
  retry.mockResolvedValue({
    assistant_message_id: "msg-moi",
    stream_url: "/api/v1/messages/msg-moi/stream",
    model_id: "model-cu",
    quota_warning: null,
  });
});

/**
 * Treo lan goi `api.retry` KE TIEP lai cho toi khi goi `.nha()`.
 *
 * Mot object chu khong mot bien `let`: TypeScript khong theo duoc phep gan
 * xay ra trong mot callback, nen mot bien se bi thu hep ve `null` ngay dong
 * duoi. Thuoc tinh cua object thi khong.
 */
function holdOneCall(): { release: () => void } {
  const gate = { release: () => {} };
  retry.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        gate.release = () =>
          resolve({
            assistant_message_id: "msg-moi",
            stream_url: "/api/v1/messages/msg-moi/stream",
            model_id: "model-cu",
            quota_warning: null,
          });
      }),
  );
  return gate;
}

/** Mot hook da mo san mot hoi thoai — `retry` khong lam gi khi chua mo. */
async function hookWithOpenConversation() {
  const { result } = renderHook(() => useChat());
  await act(async () => {
    await result.current.openConversation(CONVERSATION);
  });
  return result;
}

/**
 * Nhu tren, nhung picker co that: `options` doi duoc giua chung bang
 * `rerender` — dung duong `ChatScreen` day model/muc moi xuong sau mot lan chon.
 */
async function hookWithPicker(initial: ChatOptions) {
  const hook = renderHook((options: ChatOptions) => useChat(options), { initialProps: initial });
  await act(async () => {
    await hook.result.current.openConversation(CONVERSATION);
  });
  return hook;
}

describe("khoa idempotency cua nut Thu lai (B-231)", () => {
  it("1 — moi lan goi deu MANG mot khoa (route nay bat buoc tu NQ-93)", async () => {
    const result = await hookWithOpenConversation();

    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });

    expect(retry).toHaveBeenCalledTimes(1);
    expect(keyOfCall(0)).toMatch(/\S/);
  });

  it("2 — hai lan bam CHONG LAN dung cung mot khoa (S5, C22)", async () => {
    const result = await hookWithOpenConversation();
    /*
      Ca that: nguoi dung bam hai lan truoc khi request dau tra ve. Khoa phai
      la mot — do la toan bo ly do §11.4 ton tai. Giu request dau treo bang
      mot promise chua resolve, dung nhu mang cham.

      Khong can `waitFor`: than mot `async function` chay DONG BO toi `await`
      dau tien, ma `await api.thuLai(...)` la dong ay — nen ca hai lan goi da
      toi noi truoc khi dong lenh ke tiep chay.
    */
    const held = holdOneCall();

    await act(async () => {
      void result.current.retry(ANSWER_ID);
      void result.current.retry(ANSWER_ID);
      held.release();
    });

    expect(retry).toHaveBeenCalledTimes(2);
    expect(keyOfCall(0)).toBe(keyOfCall(1));
  });

  it("3 — sau `202` thi khoa duoc BO: lan bam sau la mot anh em that (§8.2)", async () => {
    const result = await hookWithOpenConversation();

    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });
    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });

    expect(keyOfCall(0)).not.toBe(keyOfCall(1));
  });

  it("4 — HONG thi GIU khoa: bam lai van la cung mot y dinh (luat 2)", async () => {
    const result = await hookWithOpenConversation();
    retry.mockRejectedValueOnce(new Error("mang rot"));

    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });
    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });

    expect(keyOfCall(0)).toBe(keyOfCall(1));
  });

  it("5 — hong, DOI model tren picker roi bam lai ⇒ khoa MOI (mot y dinh moi)", async () => {
    const { result, rerender } = await hookWithPicker({ models: MODELS, accountDefaultModel: PICKED_MODEL });
    retry.mockRejectedValueOnce(new Error("mang rot"));

    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });
    rerender({ models: MODELS, accountDefaultModel: PLAIN_MODEL });
    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });

    // Cung mot khoa se lam lan goi thu hai nhan BAN PHAT LAI cua lan dau (§11.4),
    // tuc doi model tren picker roi bam Thu lai khong doi duoc model nao ca.
    expect(retry.mock.calls[1][1]).toEqual({ model_id: PLAIN_MODEL });
    expect(keyOfCall(0)).not.toBe(keyOfCall(1));
  });

  it("6 — hong, DOI MUC tren picker roi bam lai ⇒ khoa MOI", async () => {
    const { result, rerender } = await hookWithPicker({
      models: MODELS,
      accountDefaultModel: PICKED_MODEL,
      reasoningPrefs: { [PICKED_MODEL]: "low" },
    });
    retry.mockRejectedValueOnce(new Error("mang rot"));

    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });
    rerender({ models: MODELS, accountDefaultModel: PICKED_MODEL, reasoningPrefs: { [PICKED_MODEL]: "high" } });
    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });

    expect(retry.mock.calls[1][1]).toEqual({ model_id: PICKED_MODEL, reasoning_effort: "high" });
    expect(keyOfCall(0)).not.toBe(keyOfCall(1));
  });
});

describe("MOT nut Thu lai gui model + muc cua picker (T-S.15, §24.2b·S4)", () => {
  it("model co muc ⇒ body mang `model_id` VA `reasoning_effort` dang hien tren picker", async () => {
    const { result } = await hookWithPicker({
      models: MODELS,
      accountDefaultModel: PICKED_MODEL,
      reasoningPrefs: { [PICKED_MODEL]: "low" },
    });

    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });

    // Muc DA NHO (`low`), khong phai mac dinh catalog (`high`): cung muc `send` gui.
    expect(result.current.effectiveEffort).toBe("low");
    expect(retry.mock.calls[0][1]).toEqual({ model_id: PICKED_MODEL, reasoning_effort: "low" });
  });

  it("model KHONG co khoi `reasoning` ⇒ khong co truong `reasoning_effort` (mot `id` bat ky la `400`)", async () => {
    const { result } = await hookWithPicker({ models: MODELS, accountDefaultModel: PLAIN_MODEL });

    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });

    expect(retry.mock.calls[0][1]).toEqual({ model_id: PLAIN_MODEL });
  });

  it("chua biet model nao (`GET /models` chua ve) ⇒ body rong, backend giu model cu", async () => {
    const result = await hookWithOpenConversation();

    await act(async () => {
      await result.current.retry(ANSWER_ID);
    });

    expect(retry.mock.calls[0][1]).toEqual({});
  });
});

describe("danhGia doc lai duong di tu server (T-3.7)", () => {
  it("ghi xong thi `GET /conversations/{id}` chay lai — khong tu va vao state", async () => {
    const result = await hookWithOpenConversation();
    sendFeedback.mockResolvedValue({
      message_id: ANSWER_ID,
      feedback: "like",
      feedback_reason: null,
    });
    getConversation.mockClear();

    await act(async () => {
      await result.current.sendFeedback(ANSWER_ID, "like");
    });

    expect(sendFeedback).toHaveBeenCalledWith(ANSWER_ID, "like");
    expect(getConversation).toHaveBeenCalledWith(CONVERSATION);
  });
});
