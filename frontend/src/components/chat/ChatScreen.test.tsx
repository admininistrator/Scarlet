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
import userEvent from "@testing-library/user-event";
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
      listByokEndpoints: vi.fn(),
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
  last_login_at: null,
  limits_cache_ttl_s: 60,
  stream_ttl_s: 3600,
  display_name_max_chars: 64,
  avatar_color: null,
  reasoning_prefs: {},
  max_upload_mb: 10,
  max_attachments: 5,
  allowed_upload_mime: ["image/png", "image/jpeg", "application/pdf", "text/plain"],
  can_use_web: true,
  can_execute_skills: false,
  web_searches_per_day: 50,
  web_searches_used: 0,
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
  vi.mocked(api.listConversations).mockResolvedValue({ items: [], next_cursor: null, truncated: false });
  vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [], byok_providers: [] });
  vi.mocked(api.getConversation).mockReset().mockResolvedValue(CONVERSATION);
  vi.mocked(api.createConversation).mockReset();
  vi.mocked(api.sendMessage).mockReset();
  vi.mocked(api.listByokEndpoints).mockReset().mockResolvedValue({ endpoints: [], max_endpoints: 5 });
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

    const text = "Mất kết nối, đang nối lại…";
    act(() => stream.status?.("dang-mo"));
    expect(screen.queryAllByText(text)).toHaveLength(0);

    /*
      T-S.19a — trang thai vao thang dao (ban Khung chinh v3): vien thuoc va
      thanh mo cung ve chu nay nhung `aria-hidden`; trinh doc man hinh nghe
      MOT `role=status`.
    */
    act(() => stream.status?.("dang-noi-lai"));
    const shown = screen.getAllByText(text);
    const announced = shown.filter((el) => el.closest("[role=status]") !== null);
    expect(announced).toHaveLength(1);
    for (const el of shown.filter((x) => !announced.includes(x))) {
      expect(el.closest('[aria-hidden="true"]')).not.toBeNull();
    }

    act(() => stream.status?.("dang-chay"));
    expect(screen.queryAllByText(text)).toHaveLength(0);
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

describe("model cua endpoint tu nhap (T-S.19c)", () => {
  it("6. chon o man nhap ⇒ KHONG `PUT /settings`; cau dau tao hoi thoai bang model ay; het quota van gui duoc", async () => {
    const endpointId = "e1d2c3b4-0000-4000-8000-000000000001";
    const own = `byok:${endpointId}/llama-3.3-70b-versatile`;
    vi.mocked(api.listModels).mockResolvedValue([
      {
        id: "deepseek-flash",
        display_name: "DeepSeek Flash",
        provider: "DeepSeek",
        provider_id: "deepseek",
        capabilities: [],
        context_window: 1,
        max_output: 1,
        default: true,
        badge: null,
        available: true,
        unavailable_reason: null,
        reasoning: null,
        pricing: null,
        pricing_mode: "unmetered",
        checked_at: null,
        stale_after_s: 30,
      },
    ]);
    vi.mocked(api.listByokEndpoints).mockResolvedValue({
      endpoints: [
        {
          id: endpointId,
          label: "Groq",
          base_url: "https://api.groq.com/openai/v1",
          masked_key: "gsk_...4321",
          models: ["llama-3.3-70b-versatile"],
          verified_at: null,
          created_at: "2026-10-01T00:00:00Z",
          usable: true,
          prompt_tokens: 0,
          completion_tokens: 0,
        },
      ],
      max_endpoints: 5,
    });
    const blocked = {
      ...PROFILE,
      quota: [
        {
          limit_type: "5h" as const,
          limit_usd: "0.5000",
          spent_usd: "0.5000",
          remaining_usd: "0.0000",
          remaining_pct: 0,
          retry_after: 3600,
        },
      ],
    };
    session.current = { ...fakeSession(), user: blocked, profile: blocked };
    vi.mocked(api.createConversation).mockResolvedValue(CONVERSATION);
    vi.mocked(api.sendMessage).mockRejectedValue(new Error("dung o day"));
    window.history.replaceState(null, "", "/");
    renderScreen();

    const send = await screen.findByRole("button", { name: "Gửi" });
    await userEvent.type(screen.getByRole("textbox", { name: "Nhập tin nhắn cho Scarlet" }), "Xin chao");
    // Model catalog + het quota 5 gio ⇒ nut Gui tat (T-3.11).
    expect(send).toBeDisabled();

    await userEvent.click(await screen.findByRole("button", { name: /^Chọn mô hình/ }));
    await userEvent.click(screen.getByRole("button", { name: /^More models/ }));
    await userEvent.click(await screen.findByRole("option", { name: /llama-3\.3-70b-versatile/ }));

    expect(session.current.changeDefaultModel).not.toHaveBeenCalled();
    await waitFor(() => expect(send).toBeEnabled());
    await userEvent.click(send);

    await waitFor(() => expect(api.sendMessage).toHaveBeenCalled());
    expect(vi.mocked(api.createConversation).mock.calls[0][0]).toEqual({ default_model: own });
    expect(vi.mocked(api.sendMessage).mock.calls[0][1]).toMatchObject({ model_id: own });
  });
});
