/**
 * Man chat v2 — T-S.10 (DoD dong 4, phan "DOM khong con ma hoi thoai"), va
 * ba loi hua cua §24.2b·S7/S9 chi do duoc o tang man hinh:
 *
 *   1. Mo `/` la man NHAP: loi chao, o nhap giua man, KHONG `POST` nao — ke ca
 *      trong `StrictMode` (Cam bay ①: effect chay hai lan).
 *   2. Khong con dai trang thai (ma hoi thoai · trang thai ket noi · `in/out`,
 *      NQ-115); chi con MOT thong bao khi stream dang noi lai.
 *   3. Loi chao go tung ky tu theo token `--duration-type` (T-HD5-v2 muc 1b).
 *
 * `useSession` (Outlet context cua `Layout`) duoc thay bang mot phien gia; moi
 * loi goi mang di qua `api` gia; `openStream` gia giu lai `onStatus`/`onEvent`
 * de test tu phat su kien §7.4.
 */

import { StrictMode } from "react";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionState } from "../../features/auth/useSessionState";
import type { ConnectionStatus, StreamEvent } from "../../lib/sse";

const session: { current: SessionState | null } = { current: null };

vi.mock("../../app/Layout", () => ({
  useSession: () => session.current,
}));

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listModels: vi.fn(),
      listConversations: vi.fn(),
      listProviderKeys: vi.fn(),
      getConversation: vi.fn(),
      createConversation: vi.fn(),
      sendMessage: vi.fn(),
    },
  };
});

const stream: {
  status: ((status: ConnectionStatus) => void) | null;
  emit: ((event: StreamEvent) => void) | null;
} = { status: null, emit: null };

vi.mock("../../lib/sse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/sse")>();
  return {
    ...actual,
    openStream: vi.fn(
      (params: { onStatus?: (s: ConnectionStatus) => void; onEvent: (e: StreamEvent) => void }) => {
        stream.status = params.onStatus ?? null;
        stream.emit = params.onEvent;
        return { close: vi.fn(), cursor: () => "" };
      },
    ),
  };
});

import { api, type ConversationDetail, type MessageOut, type ProfileOut } from "../../lib/api";
import { useChat } from "../../features/chat/useChat";
import { ChatScreen } from "./ChatScreen";

const CONVERSATION_ID = "0f9d3c2a-5b7e-4c1d-9a8f-6e5d4c3b2a19";

const PROFILE: ProfileOut = {
  id: "u1",
  email: "a@scarlet.example",
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "free",
  default_model: null,
  quota: null,
  message_max_chars: 24000,
  quota_warn_remaining_pct: 20,
};

function fakeSession(): SessionState {
  return {
    user: PROFILE,
    profile: PROFILE,
    profileReadAt: Date.now(),
    loading: false,
    locked: false,
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    changeDefaultModel: vi.fn(),
    refreshProfile: vi.fn(async () => {}),
  } as unknown as SessionState;
}

function message(overrides: Partial<MessageOut>): MessageOut {
  return {
    id: "m",
    parent_id: null,
    role: "user",
    status: "done",
    content: "",
    reasoning: null,
    model_id: null,
    finish_reason: null,
    error_code: null,
    created_at: "2026-09-25T00:00:00+00:00",
    sibling_index: 0,
    sibling_count: 1,
    feedback: null,
    ...overrides,
  } as MessageOut;
}

/** Hoi thoai co mot cau hoi va mot cau tra loi DANG chay — de stream mo ra. */
const CONVERSATION: ConversationDetail = {
  id: CONVERSATION_ID,
  title: null,
  default_model: null,
  system_prompt_override: null,
  active_leaf_id: "a1",
  pinned: false,
  created_at: "2026-09-25T00:00:00+00:00",
  updated_at: "2026-09-25T00:00:00+00:00",
  path: [
    message({ id: "u1", content: "Cau hoi dau tien" }),
    message({ id: "a1", parent_id: "u1", role: "assistant", status: "streaming", content: "Dang tra" }),
  ],
};

function renderScreen() {
  return render(
    <StrictMode>
      <MemoryRouter>
        <ChatScreen />
      </MemoryRouter>
    </StrictMode>,
  );
}

beforeEach(() => {
  session.current = fakeSession();
  stream.status = null;
  stream.emit = null;
  vi.mocked(api.listModels).mockResolvedValue([]);
  vi.mocked(api.listConversations).mockResolvedValue({ items: [], next_cursor: null });
  vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [], byok_providers: [] });
  vi.mocked(api.getConversation).mockReset().mockResolvedValue(CONVERSATION);
  vi.mocked(api.createConversation).mockReset();
  vi.mocked(api.sendMessage).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  document.documentElement.style.removeProperty("--duration-type");
});

describe("man nhap (§24.2b·S7)", () => {
  it("1. mo `/` ⇒ loi chao + o nhap giua man, va KHONG tao hoi thoai nao (StrictMode)", async () => {
    window.history.replaceState(null, "", "/");
    renderScreen();

    expect(await screen.findByRole("heading", { name: "Hôm nay bạn cần gì?" })).toBeInTheDocument();
    await act(async () => {});
    expect(screen.getByRole("textbox").closest("form")).toHaveAttribute("data-phase", "draft");
    expect(api.createConversation).not.toHaveBeenCalled();
    expect(api.getConversation).not.toHaveBeenCalled();
    expect(api.sendMessage).not.toHaveBeenCalled();
  });

  /**
   * `render` boc `act`, ma `act` xa het effect — tuc `open()` da chay truoc
   * dong `expect` dau tien, va mot ban bat dau o `draft` roi moi doi van xanh
   * o tang DOM (do duoc: kiem nguoc M12). Nen pha duoc ghi o CHINH lan render
   * DAU, truoc moi effect — dung khung hinh trinh duyet ve ra truoc tien.
   */
  it("2. F5 tren `?c=` ⇒ vao thang khung hoi thoai tu lan render DAU, khong loe man nhap", () => {
    window.history.replaceState(null, "", `/?c=${CONVERSATION_ID}`);
    const phases: string[] = [];
    renderHook(() => {
      const chat = useChat();
      phases.push(chat.phase);
      return chat;
    });

    expect(phases[0]).toBe("conversation");

    renderScreen();
    expect(screen.queryByRole("heading", { name: "Hôm nay bạn cần gì?" })).toBeNull();
    expect(screen.getByRole("textbox").closest("form")).toHaveAttribute("data-phase", "docked");
  });
});

describe("khong con dai trang thai (NQ-115)", () => {
  it("3. DOM khong con ma hoi thoai, trang thai ket noi hay `in/out`", async () => {
    window.history.replaceState(null, "", `/?c=${CONVERSATION_ID}`);
    renderScreen();
    await screen.findByText("Cau hoi dau tien");
    await waitFor(() => expect(stream.emit).not.toBeNull());

    act(() => {
      stream.status?.("dang-chay");
      stream.emit?.({ event: "usage", data: { in: 11, out: 22 } } as StreamEvent);
    });

    const text = document.body.textContent ?? "";
    expect(text).not.toContain(CONVERSATION_ID);
    expect(document.querySelector("main")?.innerHTML ?? "").not.toContain(CONVERSATION_ID);
    expect(document.querySelector("form")?.innerHTML ?? "").not.toContain(CONVERSATION_ID);
    expect(text).not.toMatch(/in=\d+/);
    expect(text).not.toMatch(/đang nhận chữ/i);
  });

  it("4. chi khi dang noi lai ⇒ MOT thong bao; noi lai duoc thi bien mat", async () => {
    window.history.replaceState(null, "", `/?c=${CONVERSATION_ID}`);
    renderScreen();
    await waitFor(() => expect(stream.status).not.toBeNull());

    act(() => stream.status?.("dang-mo"));
    expect(screen.queryByText("Mất kết nối, đang nối lại…")).toBeNull();

    act(() => stream.status?.("dang-noi-lai"));
    expect(screen.getByText("Mất kết nối, đang nối lại…").closest("[role=status]")).not.toBeNull();

    act(() => stream.status?.("dang-chay"));
    expect(screen.queryByText("Mất kết nối, đang nối lại…")).toBeNull();
  });
});

describe("loi chao go tung ky tu (T-HD5-v2 muc 1b)", () => {
  it("5. token `--duration-type` > 0 ⇒ go dan; trinh doc man hinh nghe cau DAY DU mot lan", async () => {
    vi.useFakeTimers();
    document.documentElement.style.setProperty("--duration-type", "45ms");
    window.history.replaceState(null, "", "/");
    renderScreen();

    const heading = screen.getByRole("heading", { name: "Hôm nay bạn cần gì?" });
    const typedPart = heading.querySelector(".motion-none");
    expect(typedPart?.textContent).toBe("");

    await act(async () => {
      vi.advanceTimersByTime(45 * 4);
    });
    expect(typedPart?.textContent).toBe("Hôm ");

    await act(async () => {
      vi.advanceTimersByTime(45 * 40);
    });
    expect(typedPart?.textContent).toBe("Hôm nay bạn cần gì?");
    // Chi mot ban cho trinh doc man hinh; hai ban kia `aria-hidden`.
    expect(heading.querySelectorAll("[aria-hidden]")).toHaveLength(2);
  });
});
