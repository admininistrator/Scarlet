/**
 * O nhap — DoD dong 2 cua T-3.4, va ca cac cam bay cua task.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  HAI KHANG DINH NGUOC CHIEU NHAU, VA VI SAO PHAI CO CA HAI             ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * DoD viet ro: *"go → gui hong (mock 500) → bam gui lai ⇒ **cung**
 * `Idempotency-Key`; gui thanh cong → go cau moi ⇒ khoa **khac**. Hai khang
 * dinh nguoc chieu nhau; thieu mot cai thi test xanh ca voi ban sinh khoa moi
 * moi lan goi."*
 *
 * Doc nguoc lai cung dung: chi co ve "khoa khac" thi mot ban **khong bao gio
 * doi khoa** cung xanh. Nen ca 2 va ca 3 phai di cung nhau, va chung duoc
 * viet canh nhau o day de khong ai xoa mot cai ma khong thay cai con lai.
 *
 * ── Hai tang, hai cau hoi khac nhau ──────────────────────────────────────
 *
 * `describe("Composer")` render **mot minh** component va dem khoa o bien
 * `onSend`. No tra loi: *"chu so huu khoa co giu dung ba luat cua C22
 * khong"*.
 *
 * `describe("Composer qua useChat")` cam them `useChat` that va mot
 * `api.sendMessage` gia, roi doc **tham so thu ba** cua loi goi ay. No tra
 * loi cau khac han: *"khoa ay co di nguyen ven toi header HTTP khong"* — va
 * do la cho DoD noi "mock 500", vi chi o tang nay moi co mot response de
 * mock. Mot trong hai tang khong du: tang tren khong chung minh gi ve HTTP,
 * tang duoi khong chung minh gi ve luc nao khoa duoc sinh.
 */

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listModels: vi.fn(),
      getConversation: vi.fn(),
      sendMessage: vi.fn(),
    },
  };
});

/**
 * jsdom khong co `EventSource`, nen `openStream` that se nem ngay dong dau.
 * Cai dang duoc do o day la khoa, khong phai stream — T-1.14 da do stream.
 *
 * Ban gia van giu lai `onEvent` cua lan mo gan nhat, vi mot thu can no:
 * sau mot `202` man hinh chuyen sang trang thai "dang chay" va nut Gui bien
 * thanh Dung (UC-02 dong 2). Muon go mot cau THU HAI thi luot sinh thu nhat
 * phai ket thuc, ma §7.4 noi ro chi `done`/`error` dong duoc mot luot —
 * khong mot bo dem thoi gian nao (Cam bay ③). Nen test phai phat `done`.
 */
const streamEvents: { emit: ((event: StreamEvent) => void) | null } = { emit: null };

vi.mock("../../lib/sse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/sse")>();
  return {
    ...actual,
    openStream: vi.fn((params: { onEvent: (event: StreamEvent) => void }) => {
      streamEvents.emit = params.onEvent;
      return { close: vi.fn(), cursor: () => "" };
    }),
  };
});

import { ApiError, api, type ConversationDetail, type CreateMessageOut } from "../../lib/api";
import type { StreamEvent } from "../../lib/sse";
import { useChat, type SendResult } from "../../features/chat/useChat";
import { Composer } from "./Composer";

const LIMIT = 24000;
const CONVERSATION_ID = "11111111-1111-4111-8111-111111111111";

/** Dang cua mot UUID v4 — de khang dinh khoa la khoa chu khong phai chuoi rong. */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function renderComposer(
  onSend: (content: string, key: string) => Promise<SendResult>,
  overrides: Partial<{ running: boolean; enabled: boolean; maxChars: number | null }> = {},
) {
  const onStop = vi.fn();
  render(
    <Composer
      running={overrides.running ?? false}
      enabled={overrides.enabled ?? true}
      maxChars={overrides.maxChars === undefined ? LIMIT : overrides.maxChars}
      onSend={onSend}
      onStop={onStop}
    />,
  );
  return { onStop };
}

const textbox = () => screen.getByRole("textbox");
const sendButton = () => screen.getByRole("button", { name: "Gửi" });

describe("Composer", () => {
  it("1. sinh khoa khi o nhap chuyen tu rong sang co chu, khong som hon", async () => {
    const key: string[] = [];
    renderComposer(async (_n, k) => {
      key.push(k);
      return "da-gui";
    });

    await userEvent.type(textbox(), "xin chao");
    await userEvent.click(sendButton());

    expect(key).toHaveLength(1);
    expect(key[0]).toMatch(UUID_PATTERN);
  });

  /**
   * Ca am cua DoD, ve thu nhat. Mot ban sinh khoa moi o moi lan `gui()` se
   * DO o dong cuoi — va do la toan bo diem cua C22.
   */
  it("2. gui hong roi bam gui lai ⇒ CUNG mot Idempotency-Key", async () => {
    const key: string[] = [];
    let result: SendResult = "hong";
    renderComposer(async (_n, k) => {
      key.push(k);
      return result;
    });

    await userEvent.type(textbox(), "1+1 bang may?");
    await userEvent.click(sendButton());
    // Gui hong: chu PHAI con nguyen, neu khong thi khong con gi de bam lan hai.
    expect(textbox()).toHaveValue("1+1 bang may?");

    result = "da-gui";
    await userEvent.click(sendButton());

    expect(key).toHaveLength(2);
    expect(key[1]).toBe(key[0]);
  });

  /** Ca am cua DoD, ve thu hai. Mot ban khong bao gio doi khoa se DO o day. */
  it("3. gui thanh cong roi go cau moi ⇒ khoa KHAC", async () => {
    const key: string[] = [];
    renderComposer(async (_n, k) => {
      key.push(k);
      return "da-gui";
    });

    await userEvent.type(textbox(), "cau mot");
    await userEvent.click(sendButton());
    expect(textbox()).toHaveValue("");

    await userEvent.type(textbox(), "cau hai");
    await userEvent.click(sendButton());

    expect(key).toHaveLength(2);
    expect(key[1]).not.toBe(key[0]);
  });

  it("4. xoa sach o nhap la bo lan soan thao ⇒ cau sau mang khoa khac", async () => {
    const key: string[] = [];
    renderComposer(async (_n, k) => {
      key.push(k);
      return "hong";
    });

    await userEvent.type(textbox(), "abc");
    await userEvent.click(sendButton());
    await userEvent.clear(textbox());
    await userEvent.type(textbox(), "xyz");
    await userEvent.click(sendButton());

    expect(key[1]).not.toBe(key[0]);
  });

  /* ── Duong thoat khoi 409 IN_PROGRESS — B-143, Cam bay ① ──────────────── */

  it("5. 409 IN_PROGRESS ⇒ hien duong thoat, va no gui bang khoa MOI", async () => {
    const key: string[] = [];
    let result: SendResult = "ket-khoa";
    renderComposer(async (_n, k) => {
      key.push(k);
      return result;
    });

    await userEvent.type(textbox(), "cau bi ket");
    await userEvent.click(sendButton());

    const retryButton = await screen.findByRole("button", { name: "Gửi lại bằng khoá mới" });
    result = "da-gui";
    await userEvent.click(retryButton);

    expect(key).toHaveLength(2);
    expect(key[1]).not.toBe(key[0]);
    expect(key[1]).toMatch(UUID_PATTERN);
    // Da thoat ra that: o nhap sach, bang canh bao bien mat.
    expect(textbox()).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Gửi lại bằng khoá mới" })).toBeNull();
  });

  it("6. mot loi THUONG (500) KHONG duoc hien duong thoat — C22 van cam doi khoa", async () => {
    renderComposer(async () => "hong");

    await userEvent.type(textbox(), "cau hong");
    await userEvent.click(sendButton());

    expect(screen.queryByRole("button", { name: "Gửi lại bằng khoá mới" })).toBeNull();
  });

  /* ── Dem ky tu — A3/L4, B-205/NQ-78 ──────────────────────────────────── */

  it("7. dem nguoc ve `message_max_chars` lay tu prop, khong mot con so nao o FE", async () => {
    renderComposer(async () => "da-gui", { maxChars: 10 });

    expect(screen.getByRole("status")).toHaveTextContent("0 / 10");
    await userEvent.type(textbox(), "abcde");
    expect(screen.getByRole("status")).toHaveTextContent("5 / 10");
  });

  it("8. go vuot tran ⇒ nut Gui `disabled` (DoD dong 5)", async () => {
    renderComposer(async () => "da-gui", { maxChars: 5 });

    await userEvent.type(textbox(), "12345");
    expect(sendButton()).toBeEnabled();

    await userEvent.type(textbox(), "6");
    expect(screen.getByRole("status")).toHaveTextContent("6 / 5");
    expect(sendButton()).toBeDisabled();
  });

  it("9. `tranKyTu === null` la 'chua biet tran', khong phai 'tran = 0'", async () => {
    const key: string[] = [];
    renderComposer(
      async (_n, k) => {
        key.push(k);
        return "da-gui";
      },
      { maxChars: null },
    );

    await userEvent.type(textbox(), "van go duoc");
    expect(screen.queryByRole("status")).toBeNull();
    expect(sendButton()).toBeEnabled();
    await userEvent.click(sendButton());
    expect(key).toHaveLength(1);
  });

  /* ── Phim: Enter gui · Shift+Enter xuong dong (chot o T-3.4) ─────────── */

  it("10. Enter gui; Shift+Enter xuong dong chu khong gui", async () => {
    const sendMock = vi.fn(async (_content: string, _key: string) => "da-gui" as SendResult);
    renderComposer(sendMock);

    await userEvent.type(textbox(), "dong mot{Shift>}{Enter}{/Shift}dong hai");
    expect(sendMock).not.toHaveBeenCalled();
    expect(textbox()).toHaveValue("dong mot\ndong hai");

    await userEvent.type(textbox(), "{Enter}");
    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(sendMock.mock.calls[0][0]).toBe("dong mot\ndong hai");
  });

  /**
   * Bo go tieng Viet (Telex/VNI) dung Enter de chot tu dang dung, va su kien
   * ay mang `isComposing = true`. Gui o day la gui nham nua cau.
   */
  it("11. Enter trong luc bo go dang dung tu (`isComposing`) KHONG gui", async () => {
    const sendMock = vi.fn(async (_content: string, _key: string) => "da-gui" as SendResult);
    renderComposer(sendMock);

    await userEvent.type(textbox(), "tieng viet");
    // `userEvent` khong dung duoc IME, nen ban phim di thang qua `fireEvent`.
    act(() => {
      textbox().dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true, isComposing: true }),
      );
    });

    expect(sendMock).not.toHaveBeenCalled();
  });

  /* ── Nut Gui ⇄ Dung (UC-02 dong 2, Cam bay ③) ────────────────────────── */

  it("12. `dangChay` ⇒ nut la Dung, va no goi `onDung`", async () => {
    const { onStop } = renderComposer(async () => "da-gui", { running: true });

    expect(screen.queryByRole("button", { name: "Gửi" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Dừng" }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("13. o nhap rong hoac chua mo hoi thoai ⇒ khong gui duoc", async () => {
    const sendMock = vi.fn(async (_content: string, _key: string) => "da-gui" as SendResult);
    renderComposer(sendMock);

    expect(sendButton()).toBeDisabled();
    // Chi co dau cach cung khong phai mot cau hoi.
    await userEvent.type(textbox(), "   ");
    expect(sendButton()).toBeDisabled();
    await userEvent.type(textbox(), "{Enter}");
    expect(sendMock).not.toHaveBeenCalled();
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Tang hai: khoa cua `Composer` di toi header HTTP nguyen ven hay khong.
   ══════════════════════════════════════════════════════════════════════════ */

const CONVERSATION: ConversationDetail = {
  id: CONVERSATION_ID,
  title: null,
  default_model: null,
  system_prompt_override: null,
  active_leaf_id: null,
  pinned: false,
  created_at: "2026-09-22T00:00:00+00:00",
  updated_at: "2026-09-22T00:00:00+00:00",
  path: [],
};

const CREATED: CreateMessageOut = {
  user_message_id: "22222222-2222-4222-8222-222222222222",
  assistant_message_id: "33333333-3333-4333-8333-333333333333",
  stream_url: "/api/v1/messages/33333333-3333-4333-8333-333333333333/stream",
  branched: false,
  quota_warning: null,
};

/** Dung `useChat` that, nhu `ChatScreen` dung no. */
function MinimalChat() {
  const chat = useChat();
  return (
    <Composer
      running={chat.running !== null}
      enabled={chat.tree.conversationId !== null && !chat.busy}
      maxChars={LIMIT}
      onSend={chat.send}
      onStop={() => void chat.stop()}
    />
  );
}

/** Tham so thu ba cua `api.sendMessage` la `Idempotency-Key`. */
function sentKey(attempt: number): string {
  return vi.mocked(api.sendMessage).mock.calls[attempt][2];
}

/** §7.4 — chi `done` dong duoc mot luot sinh, va man hinh doc dung no. */
async function finishGeneration(): Promise<void> {
  act(() => {
    streamEvents.emit?.({ event: "done", data: { finish_reason: "stop", usage: null } });
  });
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Gửi" })).toBeInTheDocument();
  });
}

describe("Composer qua useChat", () => {
  beforeEach(async () => {
    streamEvents.emit = null;
    window.history.replaceState(null, "", `/?c=${CONVERSATION_ID}`);
    vi.mocked(api.listModels).mockResolvedValue([]);
    vi.mocked(api.getConversation).mockResolvedValue(CONVERSATION);
    render(<MinimalChat />);
    // `useChat` mo hoi thoai cua `?c=` luc mount; truoc do `enabled` la false.
    await waitFor(() => {
      expect(screen.getByRole("textbox")).toBeEnabled();
    });
  });

  /**
   * DoD dong 2 do dung o day: `500` la mot response that di qua `ApiError`,
   * khong phai mot chuoi `"hong"` do test tu nghi ra.
   */
  it("14. mock 500 roi bam gui lai ⇒ header `Idempotency-Key` khong doi", async () => {
    vi.mocked(api.sendMessage)
      .mockRejectedValueOnce(new ApiError(500, "INTERNAL", "loi may chu"))
      .mockResolvedValueOnce(CREATED);

    await userEvent.type(textbox(), "cau hoi");
    await userEvent.click(sendButton());
    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledTimes(1);
    });

    await userEvent.click(sendButton());
    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledTimes(2);
    });

    expect(sentKey(1)).toBe(sentKey(0));
    expect(sentKey(0)).toMatch(UUID_PATTERN);
    // Lan hai la lan `202`: o nhap sach, khoa bi bo.
    await waitFor(() => {
      expect(textbox()).toHaveValue("");
    });

    vi.mocked(api.sendMessage).mockResolvedValueOnce(CREATED);
    await finishGeneration();
    await userEvent.type(textbox(), "cau hoi khac");
    await userEvent.click(sendButton());
    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledTimes(3);
    });
    expect(sentKey(2)).not.toBe(sentKey(0));
  });

  it("15. `409 IN_PROGRESS` ⇒ duong thoat hien ra, va no doi khoa", async () => {
    vi.mocked(api.sendMessage)
      .mockRejectedValueOnce(new ApiError(409, "IN_PROGRESS", "dang chay"))
      .mockResolvedValueOnce(CREATED);

    await userEvent.type(textbox(), "cau bi ket");
    await userEvent.click(sendButton());

    const retryButton = await screen.findByRole("button", { name: "Gửi lại bằng khoá mới" });
    await userEvent.click(retryButton);
    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledTimes(2);
    });

    expect(sentKey(1)).not.toBe(sentKey(0));
  });

  /**
   * `GENERATION_IN_PROGRESS` (409 cua `retry` — mot MESSAGE dang sinh) khong
   * phai `IN_PROGRESS` (409 cua §11.4 — mot KHOA dang bi giu). Gop hai ma nay
   * lai la mo duong thoat cho mot ca ma doi khoa khong sua duoc gi.
   */
  it("16. `409 GENERATION_IN_PROGRESS` KHONG mo duong thoat", async () => {
    vi.mocked(api.sendMessage).mockRejectedValueOnce(
      new ApiError(409, "GENERATION_IN_PROGRESS", "luot cu chua xong"),
    );

    await userEvent.type(textbox(), "cau hoi");
    await userEvent.click(sendButton());
    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledTimes(1);
    });

    expect(screen.queryByRole("button", { name: "Gửi lại bằng khoá mới" })).toBeNull();
  });
});

describe("Composer — thanh cong cu (B-242)", () => {
  /**
   * Nguoi dung chot "thanh cong cu duoi o nhap": picker nam TRONG form, SAU o
   * nhap va TRUOC nut Gui. Dem thu tu trong DOM chu khong do toa do — jsdom
   * khong dung layout.
   */
  it("17. picker nam trong khung soan thao, giua o nhap va nut Gui", () => {
    render(
      <Composer
        running={false}
        enabled
        maxChars={null}
        onSend={vi.fn()}
        onStop={vi.fn()}
        modelPicker={<button type="button">picker-stub</button>}
      />,
    );

    const textbox = screen.getByRole("textbox");
    const picker = screen.getByRole("button", { name: "picker-stub" });
    const send = screen.getByRole("button", { name: "Gửi" });
    const form = textbox.closest("form");

    expect(form).not.toBeNull();
    expect(form).toContainElement(picker);
    const following = Node.DOCUMENT_POSITION_FOLLOWING;
    expect(textbox.compareDocumentPosition(picker) & following).toBeTruthy();
    expect(picker.compareDocumentPosition(send) & following).toBeTruthy();
  });
});
