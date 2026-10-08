/**
 * Cong tac "Tim web", chip tool, chip nguon — dau-cuoi o tang FE (T-6.7c).
 *
 * KH tham chieu: UC-08 dong 1, 3, 5 · §7.4 (`tool_call`, `tool_result`) ·
 * Q-P6-3, Q-P6-7 · B-87 · tasks.md T-6.7c.
 *
 * `ChatScreen` THAT tren `useSessionState`, `useChat`, `api` THAT (khuon
 * `ArtifactFlow.test.tsx`). Chi `fetch` (bo dinh tuyen gia) va `EventSource`
 * (jsdom khong co — ban gia PHAT duoc event) bi thay.
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionState } from "../../features/auth/useSessionState";

const holder: { current: SessionState | null } = { current: null };

vi.mock("../../app/Layout", () => ({
  useSession: () => holder.current,
}));

import type { ConversationDetail, MessageOut, ModelOut, ProfileOut, ToolSummary } from "../../lib/api";
import { useSessionState } from "../../features/auth/useSessionState";
import { ChatScreen } from "./ChatScreen";

const CONVERSATION_ID = "7d3e2c1b-0a9f-4e8d-8c7b-6a5f4e3d2c1b";
const USER_ID = "u1";
const ANSWER_ID = "a1";
const NEW_ANSWER = "a2";

function model(id: string, capabilities: string[]): ModelOut {
  return {
    id,
    display_name: id,
    provider: "Hang",
    provider_id: "hang",
    capabilities,
    context_window: 1000,
    max_output: 100,
    default: true,
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

const PROFILE: ProfileOut = {
  id: "5e4d3c2b-1a0f-4e9d-8c7b-6a5f4e3d2c1b",
  email: "binh@scarlet.test",
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "free",
  default_model: null,
  last_login_at: "2026-10-09T01:00:00Z",
  quota: null,
  message_max_chars: 24000,
  quota_warn_remaining_pct: 20,
  limits_cache_ttl_s: 60,
  stream_ttl_s: 3600,
  display_name_max_chars: 64,
  avatar_color: null,
  reasoning_prefs: {},
  max_upload_mb: 10,
  max_attachments: 5,
  allowed_upload_mime: ["text/plain"],
  can_use_web: true,
  web_searches_per_day: 50,
  web_searches_used: 0,
};

function message(p: Partial<MessageOut> & Pick<MessageOut, "id">): MessageOut {
  return {
    parent_id: null,
    role: "user",
    status: "completed",
    content: "",
    reasoning: null,
    model_id: null,
    finish_reason: null,
    error_code: null,
    created_at: "2026-10-09T08:00:00Z",
    sibling_index: 0,
    sibling_count: 1,
    feedback: null,
    reasoning_effort: null,
    artifacts: [],
    tools: [],
    ...p,
  };
}

function answer(p: Partial<MessageOut> = {}): MessageOut {
  return message({
    id: ANSWER_ID,
    parent_id: USER_ID,
    role: "assistant",
    content: "Giá vàng hôm nay là 120 triệu.",
    model_id: "claude-haiku",
    finish_reason: "stop",
    ...p,
  });
}

/** "Server": duong di, danh muc, profile — dat lai o `beforeEach`. */
const server = {
  path: [] as MessageOut[],
  models: [] as ModelOut[],
  profile: PROFILE,
};

function detail(): ConversationDetail {
  return {
    id: CONVERSATION_ID,
    title: "Hoi thu",
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: server.path[server.path.length - 1].id,
    pinned: false,
    created_at: "2026-10-09T08:00:00Z",
    updated_at: "2026-10-09T08:00:00Z",
    path: server.path,
  };
}

function reply(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

const ACCEPTED = {
  user_message_id: "u2",
  assistant_message_id: NEW_ANSWER,
  stream_url: `/api/v1/messages/${NEW_ANSWER}/stream`,
  branched: false,
  model_id: "claude-haiku",
  quota_warning: null,
};

const fakeFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const method = init?.method ?? "GET";
  const path = String(input).replace(/^\/api\/v1/, "").split("?")[0];
  switch (`${method} ${path}`) {
    case "GET /auth/me":
      return reply(200, server.profile);
    case "GET /models":
      return reply(200, server.models);
    case "GET /conversations":
      return reply(200, { items: [], next_cursor: null, truncated: false });
    case `GET /conversations/${CONVERSATION_ID}`:
      return reply(200, detail());
    case `POST /conversations/${CONVERSATION_ID}/messages`:
    case `POST /messages/${ANSWER_ID}/retry`:
    case `PATCH /messages/${USER_ID}`:
      return reply(202, ACCEPTED);
    default:
      return reply(404, { error: { code: "NOT_FOUND", message: `${method} ${path}`, details: null } });
  }
});

/** Body JSON cua lan goi `METHOD path` dau tien. */
function bodyOf(method: string, path: string): unknown {
  const call = fakeFetch.mock.calls.find(
    ([input, init]) => (init?.method ?? "GET") === method && String(input).endsWith(path),
  );
  expect(call).toBeDefined();
  return JSON.parse(String(call?.[1]?.body));
}

/** `EventSource` gia: ghi lai listener de test PHAT event nhu Nginx/SSE that. */
class FakeEventSource {
  static readonly CLOSED = 2;
  static all: FakeEventSource[] = [];
  readyState = 0;
  private listeners = new Map<string, ((ev: MessageEvent) => void)[]>();

  constructor(readonly url: string) {
    FakeEventSource.all.push(this);
  }

  addEventListener(kind: string, fn: (ev: MessageEvent) => void): void {
    this.listeners.set(kind, [...(this.listeners.get(kind) ?? []), fn]);
  }

  removeEventListener(): void {}

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }

  emit(kind: string, data: unknown, id: string): void {
    const ev = new MessageEvent(kind, { data: JSON.stringify(data), lastEventId: id });
    act(() => (this.listeners.get(kind) ?? []).forEach((fn) => fn(ev)));
  }
}

function Harness() {
  const session = useSessionState();
  holder.current = session;
  return session.loading ? null : <ChatScreen />;
}

function renderApp() {
  return render(
    <MemoryRouter>
      <Harness />
    </MemoryRouter>,
  );
}

const toggle = () => screen.getByRole("button", { name: "Tìm web" });
const answers = () => screen.getAllByRole("article", { name: "Scarlet trả lời" });

/** Man chat da mo xong hoi thoai VA danh muc model da ve (cong tac doc no). */
async function openChat(): Promise<void> {
  renderApp();
  await waitFor(() => expect(answers()).toHaveLength(1));
  await waitFor(() => expect(fakeFetch.mock.calls.some(([input]) => String(input).endsWith("/models"))).toBe(true));
}

/** Cau tra loi dang chay, stream mo, `start` da toi. */
async function streamingAnswer(): Promise<FakeEventSource> {
  server.path = [message({ id: USER_ID, content: "Giá vàng hôm nay?" }), answer({ status: "streaming", content: "" })];
  renderApp();
  await waitFor(() => expect(FakeEventSource.all).toHaveLength(1));
  const es = FakeEventSource.all[0];
  es.emit("start", { message_id: ANSWER_ID, model_id: "claude-haiku" }, "1-0");
  return es;
}

const SEARCH_CALL = { call_id: "c_1", name: "web_search", args: { query: "giá vàng" } };
const SEARCH_OK = {
  call_id: "c_1",
  name: "web_search",
  ok: true,
  result: {
    sources: [
      { url: "https://sjc.com.vn/gia-vang", title: "Giá vàng SJC" },
      { url: "javascript:alert(document.cookie)", title: "Bấm vào đây" },
      { url: "https://evil.example/x", title: "hoa-don‮fdp.exe" },
    ],
    reason: null,
  },
};

beforeEach(() => {
  holder.current = null;
  server.path = [message({ id: USER_ID, content: "Giá vàng hôm nay?" }), answer()];
  server.models = [model("claude-haiku", ["tools"])];
  server.profile = PROFILE;
  FakeEventSource.all = [];
  fakeFetch.mockClear();
  localStorage.clear();
  vi.stubGlobal("fetch", fakeFetch);
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  window.history.replaceState(null, "", `/?c=${CONVERSATION_ID}`);
});

describe("cong tac \"Tim web\" (Q-P6-3)", () => {
  it("1. bat / tat: `aria-pressed` false → true → false; khong `data-planned`", async () => {
    await openChat();

    expect(toggle()).toHaveAttribute("aria-pressed", "false");
    expect(toggle()).not.toHaveAttribute("data-planned");
    expect(toggle()).not.toHaveAttribute("aria-disabled");
    await userEvent.click(toggle());
    expect(toggle()).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(toggle());
    expect(toggle()).toHaveAttribute("aria-pressed", "false");
  });

  it("2. tat ⇒ gui mang `web_tools: false`", async () => {
    await openChat();

    await userEvent.type(screen.getByRole("textbox"), "Giá vàng?{Enter}");

    await waitFor(() =>
      expect(bodyOf("POST", `/conversations/${CONVERSATION_ID}/messages`)).toMatchObject({ web_tools: false }),
    );
  });

  it("3. bat ⇒ CA BA duong (gui, Thu lai, sua cau hoi) mang `web_tools: true`", async () => {
    await openChat();
    await userEvent.click(toggle());

    await userEvent.type(screen.getByRole("textbox"), "Giá vàng?{Enter}");
    await waitFor(() =>
      expect(bodyOf("POST", `/conversations/${CONVERSATION_ID}/messages`)).toMatchObject({ web_tools: true }),
    );

    await userEvent.click(within(answers()[0]).getByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(bodyOf("POST", `/messages/${ANSWER_ID}/retry`)).toMatchObject({ web_tools: true }));

    const question = screen.getByRole("article", { name: "Bạn" });
    await userEvent.click(within(question).getByRole("button", { name: "Sửa" }));
    await userEvent.click(screen.getByRole("button", { name: "Lưu" }));
    await waitFor(() =>
      expect(bodyOf("PATCH", `/messages/${USER_ID}`)).toEqual({ content: "Giá vàng hôm nay?", web_tools: true }),
    );
  });

  it("4. model khong `tools` ⇒ `aria-disabled` + tooltip ly do; bam khong bat; gui `web_tools: false`", async () => {
    server.models = [model("ol-qwen-small", [])];
    await openChat();
    await waitFor(() => expect(toggle()).toHaveAttribute("aria-disabled", "true"));

    act(() => toggle().focus());
    expect(await screen.findByRole("tooltip")).toHaveTextContent(/^Model này không dùng được tìm web$/);
    await userEvent.click(toggle());
    expect(toggle()).toHaveAttribute("aria-pressed", "false");

    await userEvent.type(screen.getByRole("textbox"), "Giá vàng?{Enter}");
    await waitFor(() =>
      expect(bodyOf("POST", `/conversations/${CONVERSATION_ID}/messages`)).toMatchObject({ web_tools: false }),
    );
  });

  it("5. `can_use_web: false` (T-6.8) ⇒ `aria-disabled` + tooltip ly do", async () => {
    server.profile = { ...PROFILE, can_use_web: false };
    await openChat();

    expect(toggle()).toHaveAttribute("aria-disabled", "true");
    act(() => toggle().focus());
    expect(await screen.findByRole("tooltip")).toHaveTextContent(/^Tài khoản của bạn chưa được bật tìm web$/);
  });
});

describe("chip tool + nguon tu stream (§7.4)", () => {
  it("6. `tool_call` ⇒ chip \"Đang tìm web…\" TREN chu tra loi", async () => {
    const es = await streamingAnswer();

    es.emit("tool_call", SEARCH_CALL, "1-1");

    const chip = within(answers()[0]).getByRole("status");
    expect(chip).toHaveTextContent(/^Đang tìm web…$/);
    expect(chip.querySelector(".motion-spin")).not.toBeNull();
  });

  it("7. `tool_result ok` ⇒ \"Đã tìm web\" + nguon (o chu cai, `href` https, mo tab moi)", async () => {
    const es = await streamingAnswer();
    es.emit("tool_call", SEARCH_CALL, "1-1");

    es.emit("tool_result", SEARCH_OK, "1-2");

    const bubble = answers()[0];
    expect(within(bubble).getByRole("status")).toHaveTextContent(/^Đã tìm web$/);
    const sources = within(bubble).getByRole("list", { name: "Nguồn" });
    const link = within(sources).getByRole("link", { name: "Giá vàng SJC" });
    expect(link).toHaveAttribute("href", "https://sjc.com.vn/gia-vang");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    // Q-P6-7: o chu cai, khong `<img>` nao tro ra ngoai (B-235).
    expect(link).toHaveTextContent(/^GGiá vàng SJC$/);
    expect(sources.querySelector("img")).toBeNull();
  });

  it("8. `ok: false` `reason: address` ⇒ chip loi \"Link trỏ vào địa chỉ nội bộ — đã từ chối\"; ma la ⇒ cau chung", async () => {
    const es = await streamingAnswer();
    es.emit("tool_call", { call_id: "c_1", name: "fetch_url", args: { url: "http://169.254.169.254/" } }, "1-1");
    expect(within(answers()[0]).getByRole("status")).toHaveTextContent(/^Đang đọc link…$/);

    es.emit("tool_result", { call_id: "c_1", name: "fetch_url", ok: false, result: { sources: [], reason: "address" } }, "1-2");
    es.emit("tool_call", { call_id: "c_2", name: "web_search", args: {} }, "1-3");
    es.emit("tool_result", { call_id: "c_2", name: "web_search", ok: false, result: { sources: [], reason: "constructor" } }, "1-4");

    const [blocked, odd] = within(answers()[0]).getAllByRole("status");
    expect(blocked).toHaveTextContent(/^Link trỏ vào địa chỉ nội bộ — đã từ chối$/);
    expect(blocked).toHaveClass("text-danger-text");
    expect(odd).toHaveTextContent(/^Công cụ gặp lỗi$/);
    expect(within(answers()[0]).queryByRole("list", { name: "Nguồn" })).toBeNull();
  });

  it("9. nguon `javascript:` ⇒ chip hien nhung KHONG la link", async () => {
    const es = await streamingAnswer();
    es.emit("tool_call", SEARCH_CALL, "1-1");
    es.emit("tool_result", SEARCH_OK, "1-2");

    const sources = within(answers()[0]).getByRole("list", { name: "Nguồn" });
    expect(within(sources).getByText("Bấm vào đây").closest("a")).toBeNull();
    for (const link of within(sources).getAllByRole("link")) {
      expect(link.getAttribute("href")).toMatch(/^https:\/\//);
    }
  });

  it("10. tieu de co `U+202E` ⇒ ky tu bi bo", async () => {
    const es = await streamingAnswer();
    es.emit("tool_call", SEARCH_CALL, "1-1");
    es.emit("tool_result", SEARCH_OK, "1-2");

    const link = within(answers()[0]).getByRole("link", { name: "hoa-donfdp.exe" });
    expect(link.textContent).not.toContain("‮");
    expect(link).toHaveAttribute("title", "hoa-donfdp.exe");
  });

  it("11. CUNG event phat lai (XRANGE) ⇒ khong nhan doi chip, chip da xong khong quay lai \"dang chay\"", async () => {
    const es = await streamingAnswer();
    es.emit("tool_call", SEARCH_CALL, "1-1");
    es.emit("tool_result", SEARCH_OK, "1-2");

    es.emit("start", { message_id: ANSWER_ID, model_id: "claude-haiku" }, "1-0");
    es.emit("tool_call", SEARCH_CALL, "1-1");
    es.emit("tool_result", SEARCH_OK, "1-2");
    es.emit("tool_call", SEARCH_CALL, "1-1");

    const chips = within(answers()[0]).getAllByRole("status");
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveTextContent(/^Đã tìm web$/);
    expect(within(answers()[0]).getAllByRole("link", { name: "Giá vàng SJC" })).toHaveLength(1);
  });
});

describe("chip tool + nguon tu DUONG DI (B-87, F5 sau `STREAM_TTL_S`)", () => {
  it("12. duong di co `tools` ⇒ chip + nguon hien, KHONG mo stream nao", async () => {
    const tools: ToolSummary[] = [
      { name: "web_search", ok: true, reason: null, sources: [{ url: "https://sjc.com.vn/gia-vang", title: "Giá vàng SJC" }] },
      { name: "fetch_url", ok: false, reason: "dns", sources: [] },
    ];
    server.path = [message({ id: USER_ID, content: "Giá vàng hôm nay?" }), answer({ tools })];

    await openChat();

    const bubble = answers()[0];
    const [searched, blocked] = within(bubble).getAllByRole("status");
    expect(searched).toHaveTextContent(/^Đã tìm web$/);
    expect(blocked).toHaveTextContent(/^Link trỏ vào địa chỉ nội bộ — đã từ chối$/);
    expect(within(bubble).getByRole("link", { name: "Giá vàng SJC" })).toHaveAttribute("href", "https://sjc.com.vn/gia-vang");
    expect(FakeEventSource.all).toHaveLength(0);
    expect(document.querySelectorAll('[data-planned^="T-6"]')).toHaveLength(0);
  });

  it("13. `done` ⇒ doc lai duong di co `tools` ⇒ van MOT chip, MOT nguon", async () => {
    const es = await streamingAnswer();
    es.emit("tool_call", SEARCH_CALL, "1-1");
    es.emit("tool_result", SEARCH_OK, "1-2");
    server.path = [
      message({ id: USER_ID, content: "Giá vàng hôm nay?" }),
      answer({
        tools: [{ name: "web_search", ok: true, reason: null, sources: [{ url: "https://sjc.com.vn/gia-vang", title: "Giá vàng SJC" }] }],
      }),
    ];

    es.emit("done", { finish_reason: "stop", usage: null }, "1-3");

    await waitFor(() => expect(within(answers()[0]).queryByRole("link", { name: "Bấm vào đây" })).toBeNull());
    await waitFor(() => expect(within(answers()[0]).queryByText("Bấm vào đây")).toBeNull());
    expect(within(answers()[0]).getAllByRole("status")).toHaveLength(1);
    expect(within(answers()[0]).getAllByRole("link", { name: "Giá vàng SJC" })).toHaveLength(1);
  });
});
