/**
 * O nhap — DoD dong 2 cua T-3.4, DoD dong 1 va 4 cua T-S.10, va cac cam bay
 * cua hai task.
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
 * T-S.10 nhan doi van de: mot lan soan thao mang HAI khoa (`SendKeys`), va o
 * man nhap cau dau di qua HAI route. `describe("man nhap — C22 hai chieu")`
 * do dung DoD dong 1: buoc 1 `201` ma buoc 2 `500` ⇒ bam lai **khong** co
 * `POST /conversations` thu hai, va `POST .../messages` mang **cung** khoa.
 *
 * ── Ba tang, ba cau hoi khac nhau ────────────────────────────────────────
 *
 * `describe("Composer")` render **mot minh** component va dem khoa o bien
 * `onSend`: *"chu so huu khoa co giu dung ba luat cua C22 khong"*.
 *
 * `describe("Composer qua useChat")` cam them `useChat` that va mot `api`
 * gia, roi doc tham so header cua loi goi: *"khoa ay co di nguyen ven toi
 * HTTP khong"* — va chi o tang nay moi co mot response de mock `500`.
 *
 * `describe("man nhap …")` la tang thu hai o man NHAP: hai route, hai khoa.
 */

import { StrictMode, type ReactNode } from "react";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listModels: vi.fn(),
      getConversation: vi.fn(),
      createConversation: vi.fn(),
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

import {
  ApiError,
  api,
  type ConversationDetail,
  type ConversationOut,
  type CreateMessageOut,
} from "../../lib/api";
import type { StreamEvent } from "../../lib/sse";
import { useChat, type SendKeys, type SendResult } from "../../features/chat/useChat";
import { Composer } from "./Composer";

const LIMIT = 24000;
const CONVERSATION_ID = "11111111-1111-4111-8111-111111111111";

/** Dang cua mot UUID v4 — de khang dinh khoa la khoa chu khong phai chuoi rong. */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Overrides = Partial<{
  running: boolean;
  enabled: boolean;
  maxChars: number | null;
  docked: boolean;
  modelPicker: ReactNode;
}>;

function composerElement(
  onSend: (content: string, keys: SendKeys) => Promise<SendResult>,
  overrides: Overrides,
  onStop: () => void,
) {
  return (
    <Composer
      running={overrides.running ?? false}
      enabled={overrides.enabled ?? true}
      maxChars={overrides.maxChars === undefined ? LIMIT : overrides.maxChars}
      docked={overrides.docked ?? true}
      onSend={onSend}
      onStop={onStop}
      modelPicker={overrides.modelPicker}
    />
  );
}

function renderComposer(
  onSend: (content: string, keys: SendKeys) => Promise<SendResult>,
  overrides: Overrides = {},
) {
  const onStop = vi.fn();
  const view = render(composerElement(onSend, overrides, onStop));
  return {
    onStop,
    rerender: (next: Overrides) => view.rerender(composerElement(onSend, { ...overrides, ...next }, onStop)),
    container: view.container,
  };
}

const textbox = () => screen.getByRole("textbox");
const sendButton = () => screen.getByRole("button", { name: "Gửi" });
const form = () => textbox().closest("form") as HTMLFormElement;

describe("Composer", () => {
  it("1. sinh CAP khoa khi o nhap chuyen tu rong sang co chu — hai UUID, khac nhau", async () => {
    const keys: SendKeys[] = [];
    renderComposer(async (_n, k) => {
      keys.push(k);
      return "da-gui";
    });

    await userEvent.type(textbox(), "xin chao");
    await userEvent.click(sendButton());

    expect(keys).toHaveLength(1);
    expect(keys[0].conversation).toMatch(UUID_PATTERN);
    expect(keys[0].message).toMatch(UUID_PATTERN);
    // Hai khoa, khong mot (Cam bay ④ cua T-S.10).
    expect(keys[0].conversation).not.toBe(keys[0].message);
  });

  /**
   * Ca am cua DoD, ve thu nhat. Mot ban sinh khoa moi o moi lan `gui()` se
   * DO o dong cuoi — va do la toan bo diem cua C22.
   */
  it("2. gui hong roi bam gui lai ⇒ CUNG mot cap Idempotency-Key", async () => {
    const keys: SendKeys[] = [];
    let result: SendResult = "hong";
    renderComposer(async (_n, k) => {
      keys.push(k);
      return result;
    });

    await userEvent.type(textbox(), "1+1 bang may?");
    await userEvent.click(sendButton());
    // Gui hong: chu PHAI con nguyen, neu khong thi khong con gi de bam lan hai.
    expect(textbox()).toHaveValue("1+1 bang may?");

    result = "da-gui";
    await userEvent.click(sendButton());

    expect(keys).toHaveLength(2);
    expect(keys[1]).toEqual(keys[0]);
  });

  /** Ca am cua DoD, ve thu hai. Mot ban khong bao gio doi khoa se DO o day. */
  it("3. gui thanh cong roi go cau moi ⇒ CA HAI khoa KHAC", async () => {
    const keys: SendKeys[] = [];
    renderComposer(async (_n, k) => {
      keys.push(k);
      return "da-gui";
    });

    await userEvent.type(textbox(), "cau mot");
    await userEvent.click(sendButton());
    expect(textbox()).toHaveValue("");

    await userEvent.type(textbox(), "cau hai");
    await userEvent.click(sendButton());

    expect(keys).toHaveLength(2);
    expect(keys[1].message).not.toBe(keys[0].message);
    expect(keys[1].conversation).not.toBe(keys[0].conversation);
  });

  it("4. xoa sach o nhap la bo lan soan thao ⇒ cau sau mang cap khoa khac", async () => {
    const keys: SendKeys[] = [];
    renderComposer(async (_n, k) => {
      keys.push(k);
      return "hong";
    });

    await userEvent.type(textbox(), "abc");
    await userEvent.click(sendButton());
    await userEvent.clear(textbox());
    await userEvent.type(textbox(), "xyz");
    await userEvent.click(sendButton());

    expect(keys[1].message).not.toBe(keys[0].message);
  });

  /* ── Duong thoat khoi 409 IN_PROGRESS — B-143, Cam bay ① ──────────────── */

  it("5. 409 IN_PROGRESS ⇒ hien duong thoat, va no gui bang cap khoa MOI", async () => {
    const keys: SendKeys[] = [];
    let result: SendResult = "ket-khoa";
    renderComposer(async (_n, k) => {
      keys.push(k);
      return result;
    });

    await userEvent.type(textbox(), "cau bi ket");
    await userEvent.click(sendButton());

    const retryButton = await screen.findByRole("button", { name: "Gửi lại bằng khoá mới" });
    result = "da-gui";
    await userEvent.click(retryButton);

    expect(keys).toHaveLength(2);
    expect(keys[1].message).not.toBe(keys[0].message);
    expect(keys[1].conversation).not.toBe(keys[0].conversation);
    expect(keys[1].message).toMatch(UUID_PATTERN);
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

  /* ── Tran ky tu: chi hien khi VUOT — NQ-115, DoD dong 4 cua T-S.10 ─────── */

  it("7. bo dem AN o dung `max`, HIEN o `max + 1` — va chi khi ay Gui moi khoa", async () => {
    renderComposer(async () => "da-gui", { maxChars: 5 });

    await userEvent.type(textbox(), "12345");
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText(/\/ 5/)).toBeNull();
    expect(textbox()).toHaveAttribute("aria-invalid", "false");
    expect(sendButton()).toBeEnabled();

    await userEvent.type(textbox(), "6");
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Quá giới hạn ký tự");
    expect(notice).toHaveTextContent("6 / 5");
    expect(textbox()).toHaveAttribute("aria-invalid", "true");
    expect(sendButton()).toBeDisabled();

    // Xoa mot ky tu: ve lai dung tran ⇒ dong bao bien mat, Gui mo lai.
    await userEvent.type(textbox(), "{Backspace}");
    expect(screen.queryByRole("status")).toBeNull();
    expect(sendButton()).toBeEnabled();
  });

  it("8. con so theo locale hien thi — tran lay tu prop, khong mot con so nao o FE", async () => {
    renderComposer(async () => "da-gui", { maxChars: LIMIT });

    await userEvent.click(textbox());
    await userEvent.paste("a".repeat(LIMIT + 1));

    expect(screen.getByRole("status")).toHaveTextContent("24.001 / 24.000");
  });

  it("9. `maxChars === null` la 'chua biet tran': khong bao, khong chan", async () => {
    const keys: SendKeys[] = [];
    renderComposer(
      async (_n, k) => {
        keys.push(k);
        return "da-gui";
      },
      { maxChars: null },
    );

    await userEvent.click(textbox());
    await userEvent.paste("x".repeat(LIMIT + 1));
    expect(screen.queryByRole("status")).toBeNull();
    expect(sendButton()).toBeEnabled();
    await userEvent.click(sendButton());
    expect(keys).toHaveLength(1);
  });

  it("9b. dong nhac phim tat da bo (NQ-115)", () => {
    renderComposer(async () => "da-gui");

    expect(screen.queryByText(/Enter để gửi/)).toBeNull();
    expect(screen.queryByText(/Shift\+Enter/)).toBeNull();
  });

  /* ── Phim: Enter gui · Shift+Enter xuong dong (chot o T-3.4) ─────────── */

  it("10. Enter gui; Shift+Enter xuong dong chu khong gui", async () => {
    const sendMock = vi.fn(async (_content: string, _keys: SendKeys) => "da-gui" as SendResult);
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
    const sendMock = vi.fn(async (_content: string, _keys: SendKeys) => "da-gui" as SendResult);
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

  /* ── Nut Gui ⇄ Dung (UC-02 dong 2, Cam bay ③; T-HD5-v2 muc 7) ─────────── */

  it("12. `running` ⇒ nut la Dung, goi `onStop`, va la CUNG phan tu voi nut Gui", async () => {
    const view = renderComposer(async () => "da-gui");
    const before = sendButton();

    view.rerender({ running: true });

    expect(screen.queryByRole("button", { name: "Gửi" })).toBeNull();
    const stop = screen.getByRole("button", { name: "Dừng" });
    // Mot phan tu, doi ten: icon bien hinh thay vi mot nut bi thay bang nut khac.
    expect(stop).toBe(before);
    expect(stop).toHaveAttribute("type", "button");
    await userEvent.click(stop);
    expect(view.onStop).toHaveBeenCalledTimes(1);
  });

  it("13. o nhap rong hoac chi co dau cach ⇒ khong gui duoc", async () => {
    const sendMock = vi.fn(async (_content: string, _keys: SendKeys) => "da-gui" as SendResult);
    renderComposer(sendMock);

    expect(sendButton()).toBeDisabled();
    await userEvent.type(textbox(), "   ");
    expect(sendButton()).toBeDisabled();
    await userEvent.type(textbox(), "{Enter}");
    expect(sendMock).not.toHaveBeenCalled();
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Nut cho va bo cuc v2 — §7b.2, ban T-HD2-v2 muc G
   ══════════════════════════════════════════════════════════════════════════ */

describe("Composer — nut cho va bo cuc (T-S.10)", () => {
  it("14. bon nut cho cua o nhap theo §7b.2: aria-disabled, dung data-planned, bam khong gui", async () => {
    const sendMock = vi.fn(async (_content: string, _keys: SendKeys) => "da-gui" as SendResult);
    renderComposer(sendMock);
    await userEvent.type(textbox(), "cau hoi");

    const pending = [
      ["Đính kèm ảnh hoặc tệp", "T-4.7"],
      ["Tìm web", "T-6.7"],
      ["Chọn skill", "T-7.9"],
      ["Nhập bằng giọng nói", "T-8.4"],
    ] as const;
    for (const [name, planned] of pending) {
      const button = screen.getByRole("button", { name });
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(button).toHaveAttribute("data-planned", planned);
      expect(button).toHaveAttribute("type", "button");
      await userEvent.click(button);
    }

    expect(sendMock).not.toHaveBeenCalled();
    // "Tim web" la cong tac (ban ve): chu hien ra, `aria-pressed`.
    expect(screen.getByRole("button", { name: "Tìm web" })).toHaveAttribute("aria-pressed", "false");
  });

  /**
   * NQ-115 — picker chiem cho bo dem cu: hang DUOI hop nhap, ben phai. Dem
   * thu tu trong DOM chu khong do toa do — jsdom khong dung layout.
   */
  it("15. cho Model Picker o hang duoi, SAU nut Gui, van trong form", () => {
    renderComposer(vi.fn(), { maxChars: null, modelPicker: <button type="button">picker-stub</button> });

    const picker = screen.getByRole("button", { name: "picker-stub" });
    expect(form()).toContainElement(picker);
    const following = Node.DOCUMENT_POSITION_FOLLOWING;
    expect(textbox().compareDocumentPosition(sendButton()) & following).toBeTruthy();
    expect(sendButton().compareDocumentPosition(picker) & following).toBeTruthy();
  });

  it("16. man nhap: form chiem hang 2–3 cua luoi (subgrid); trong hoi thoai: khung o day", () => {
    const view = renderComposer(vi.fn(), { docked: false });

    expect(form()).toHaveAttribute("data-phase", "draft");
    expect(form()).toHaveClass("row-start-2", "row-span-2", "grid-rows-subgrid");

    view.rerender({ docked: true });

    expect(form()).toHaveAttribute("data-phase", "docked");
    expect(form()).not.toHaveClass("row-start-2");
    // Khong con dai nen full-width co vien tren (ban v1).
    expect(form()).not.toHaveClass("border-t");
    expect(form()).not.toHaveClass("bg-background");
  });
});

/* ── FLIP: o nhap truot tu giua xuong day — T-HD5-v2 muc 1, DoD dong 4 ───── */

describe("Composer — o nhap truot xuong day (FLIP)", () => {
  /** Dinh khung theo pha: giua man 400, o day 700 — du de co mot quang truot. */
  function fakeLayout() {
    return vi
      .spyOn(HTMLFormElement.prototype, "getBoundingClientRect")
      .mockImplementation(function (this: HTMLFormElement) {
        const top = this.dataset.phase === "draft" ? 400 : 700;
        return { top, bottom: top + 150, left: 0, right: 736, width: 736, height: 150, x: 0, y: top } as DOMRect;
      });
  }

  function reduceMotion(reduce: boolean) {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: reduce && query === "(prefers-reduced-motion: reduce)",
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }));
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Ca doi chung: khong co no thi ca 18 xanh ca voi mot `useDock` khong bao
   * gio gan gi — jsdom khong chay animation, nen "khong truot" la trang thai
   * mac dinh cua moi ban hong.
   */
  it("17. doi chung — KHONG giam chuyen dong: khung duoc gan `data-dock=run` voi quang truot tu giua", () => {
    reduceMotion(false);
    fakeLayout();
    const view = renderComposer(vi.fn(), { docked: false });
    expect(form()).not.toHaveAttribute("data-dock");

    view.rerender({ docked: true });

    expect(form()).toHaveAttribute("data-dock", "run");
    // Tu vi tri cu (400) ve vi tri moi (700): bat dau o −300 px roi ve 0.
    expect(form().style.getPropertyValue("--dock-from")).toBe("-300px");
    expect(form()).toHaveClass("motion-dock");
  });

  it("18. `matchMedia` reduce ⇒ o nhap NHAY THANG xuong day, khong mot khung trung gian", () => {
    reduceMotion(true);
    fakeLayout();
    const view = renderComposer(vi.fn(), { docked: false });

    view.rerender({ docked: true });

    expect(form()).toHaveAttribute("data-phase", "docked");
    expect(form()).not.toHaveAttribute("data-dock");
    expect(form().style.getPropertyValue("--dock-from")).toBe("");
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

const CREATED_CONVERSATION: ConversationOut = {
  id: CONVERSATION_ID,
  title: null,
  default_model: null,
  system_prompt_override: null,
  active_leaf_id: null,
  pinned: false,
  created_at: "2026-09-22T00:00:00+00:00",
  updated_at: "2026-09-22T00:00:00+00:00",
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
      enabled={!chat.busy}
      maxChars={LIMIT}
      docked={chat.phase !== "draft"}
      onSend={chat.send}
      onStop={() => void chat.stop()}
    />
  );
}

/** Tham so thu ba cua `api.sendMessage` la `Idempotency-Key`. */
function sentKey(attempt: number): string {
  return vi.mocked(api.sendMessage).mock.calls[attempt][2];
}

/** Tham so thu hai cua `api.createConversation` la `Idempotency-Key`. */
function createdKey(attempt: number): string {
  return vi.mocked(api.createConversation).mock.calls[attempt][1];
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
    vi.mocked(api.sendMessage).mockReset();
    vi.mocked(api.createConversation).mockReset();
    render(<MinimalChat />);
    await waitFor(() => {
      expect(api.getConversation).toHaveBeenCalled();
    });
  });

  /**
   * DoD dong 2 cua T-3.4 do dung o day: `500` la mot response that di qua
   * `ApiError`, khong phai mot chuoi `"hong"` do test tu nghi ra.
   */
  it("19. mock 500 roi bam gui lai ⇒ header `Idempotency-Key` khong doi", async () => {
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
    // Hoi thoai da mo: khong bao gio tao them hoi thoai nao.
    expect(api.createConversation).not.toHaveBeenCalled();
  });

  it("20. `409 IN_PROGRESS` ⇒ duong thoat hien ra, va no doi khoa", async () => {
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
  it("21. `409 GENERATION_IN_PROGRESS` KHONG mo duong thoat", async () => {
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

/* ══════════════════════════════════════════════════════════════════════════
   Man nhap — hai buoc, hai khoa. DoD dong 1 cua T-S.10 (C22 hai chieu).
   ══════════════════════════════════════════════════════════════════════════ */

describe("man nhap — C22 hai chieu", () => {
  beforeEach(() => {
    streamEvents.emit = null;
    window.history.replaceState(null, "", "/");
    vi.mocked(api.listModels).mockResolvedValue([]);
    vi.mocked(api.getConversation).mockReset().mockResolvedValue(CONVERSATION);
    vi.mocked(api.sendMessage).mockReset();
    vi.mocked(api.createConversation).mockReset();
  });

  /**
   * Cam bay ① cua T-S.10: `StrictMode` chay effect HAI lan. Man nhap la man
   * khong goi API nao luc mount — mot effect "tao san hoi thoai" lot vao day
   * se DO o dong dau, va chi o day, vi app that cung chay trong `StrictMode`.
   */
  it("22. mo man nhap trong StrictMode ⇒ KHONG mot loi goi nao", async () => {
    render(
      <StrictMode>
        <MinimalChat />
      </StrictMode>,
    );
    await act(async () => {});

    expect(api.createConversation).not.toHaveBeenCalled();
    expect(api.getConversation).not.toHaveBeenCalled();
    expect(api.sendMessage).not.toHaveBeenCalled();
    expect(form()).toHaveAttribute("data-phase", "draft");
    expect(textbox()).toBeEnabled();
  });

  /**
   * DoD dong 1, chieu thu nhat: `POST /conversations` da `201`, `POST
   * .../messages` tra `500` → bam gui lai ⇒ KHONG co `POST /conversations`
   * thu hai, va `POST .../messages` mang CUNG khoa. Chieu thu hai: gui thanh
   * cong roi go cau moi ⇒ khoa KHAC.
   */
  it("23. buoc 1 `201`, buoc 2 `500` → gui lai ⇒ khong tao hoi thoai thu hai, CUNG khoa message; cau sau ⇒ khoa KHAC", async () => {
    vi.mocked(api.createConversation).mockResolvedValue(CREATED_CONVERSATION);
    vi.mocked(api.sendMessage)
      .mockRejectedValueOnce(new ApiError(500, "INTERNAL", "loi may chu"))
      .mockResolvedValueOnce(CREATED);
    render(<MinimalChat />);

    await userEvent.type(textbox(), "cau dau tien");
    await userEvent.click(sendButton());
    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledTimes(1);
    });
    // Buoc 2 hong: van o man nhap, chu con nguyen.
    expect(form()).toHaveAttribute("data-phase", "draft");
    expect(textbox()).toHaveValue("cau dau tien");

    await userEvent.click(sendButton());
    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledTimes(2);
    });

    expect(api.createConversation).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.sendMessage).mock.calls[1][0]).toBe(CONVERSATION_ID);
    expect(sentKey(1)).toBe(sentKey(0));
    // Hai khoa, hai route: khoa cua buoc 1 khong phai khoa cua buoc 2.
    expect(createdKey(0)).toMatch(UUID_PATTERN);
    expect(createdKey(0)).not.toBe(sentKey(0));
    // Cau dau la GOC cua cay.
    expect(vi.mocked(api.sendMessage).mock.calls[0][1].parent_id).toBeNull();

    // `202` ⇒ vao hoi thoai: o nhap xuong day, URL mang `?c=`.
    await waitFor(() => {
      expect(form()).toHaveAttribute("data-phase", "docked");
    });
    expect(new URLSearchParams(window.location.search).get("c")).toBe(CONVERSATION_ID);
    await waitFor(() => {
      expect(textbox()).toHaveValue("");
    });

    vi.mocked(api.sendMessage).mockResolvedValueOnce(CREATED);
    await finishGeneration();
    await userEvent.type(textbox(), "cau thu hai");
    await userEvent.click(sendButton());
    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledTimes(3);
    });

    expect(sentKey(2)).not.toBe(sentKey(0));
    expect(api.createConversation).toHaveBeenCalledTimes(1);
  });

  it("24. buoc 1 `500` → gui lai ⇒ `POST /conversations` lan hai mang CUNG khoa", async () => {
    vi.mocked(api.createConversation)
      .mockRejectedValueOnce(new ApiError(500, "INTERNAL", "loi may chu"))
      .mockResolvedValueOnce(CREATED_CONVERSATION);
    vi.mocked(api.sendMessage).mockResolvedValue(CREATED);
    render(<MinimalChat />);

    await userEvent.type(textbox(), "cau dau tien");
    await userEvent.click(sendButton());
    await waitFor(() => {
      expect(api.createConversation).toHaveBeenCalledTimes(1);
    });
    expect(api.sendMessage).not.toHaveBeenCalled();

    await userEvent.click(sendButton());
    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledTimes(1);
    });

    expect(api.createConversation).toHaveBeenCalledTimes(2);
    expect(createdKey(1)).toBe(createdKey(0));
  });

  /**
   * `loadConversation` don sach `inFlight` khi id hoi thoai DOI. O man nhap cay
   * co id `null`; neu no van `null` luc `start` va vai `delta` dau toi (tuc
   * truoc khi `GET` duong di ve), phan mo dau cua cau tra loi bien mat ngay
   * khi `GET` ve — dung trieu chung C3, do loi cua client.
   */
  it("25. chu stream toi TRUOC khi duong di ve KHONG bi mat khi cay chuyen tu nhap sang hoi thoai", async () => {
    let resolveDetail: (detail: ConversationDetail) => void = () => {};
    vi.mocked(api.createConversation).mockResolvedValue(CREATED_CONVERSATION);
    vi.mocked(api.sendMessage).mockResolvedValue(CREATED);
    vi.mocked(api.getConversation).mockReturnValue(
      new Promise((resolve) => {
        resolveDetail = resolve;
      }),
    );
    const { result } = renderHook(() => useChat());

    let sending: Promise<SendResult> = Promise.resolve("hong");
    act(() => {
      sending = result.current.send("cau dau", { conversation: "k-conv", message: "k-msg" });
    });
    await waitFor(() => expect(streamEvents.emit).not.toBeNull());
    act(() => {
      streamEvents.emit?.({
        event: "start",
        data: { message_id: CREATED.assistant_message_id, model_id: "m" },
      });
      streamEvents.emit?.({ event: "delta", data: { t: "Xin chao" } });
    });
    await act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));

    await act(async () => {
      resolveDetail({ ...CONVERSATION, active_leaf_id: CREATED.assistant_message_id });
      await sending;
    });

    expect(result.current.tree.conversationId).toBe(CONVERSATION_ID);
    expect(result.current.tree.inFlight[CREATED.assistant_message_id]?.content).toBe("Xin chao");
  });
});
