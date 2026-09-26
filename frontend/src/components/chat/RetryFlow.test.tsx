/**
 * MOT nut Thu lai, dau-cuoi o tang FE — T-S.15 DoD dong 1.
 *
 * KH tham chieu: §24.2b·S4 ("mot nut Thu lai, khong hai"), §11.4, §18.2 ·
 * UC-02 dong 5, UC-04 dong 4 · tasks.md T-3.7 (khuon "chi `fetch` bi thay"),
 * T-S.14, T-S.15.
 *
 * `ChatScreen` THAT tren `useSessionState` THAT, `useChat` THAT, `api` THAT.
 * Chi hai thu cua trinh duyet bi thay: `fetch` (mot bo dinh tuyen gia tra loi
 * theo duong dan) va `EventSource` (jsdom khong co; stream khong phai thu dang
 * do). Nen body di ra o day la body ma nut Thu lai THAT su gui sau khi nguoi
 * dung doi model va muc tren picker THAT — mot spy o tang component khong
 * thay duoc lan `useChat.retry` doc nham picker.
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

import type { ConversationDetail, MessageOut, ModelOut, ProfileOut } from "../../lib/api";
import { useSessionState } from "../../features/auth/useSessionState";
import { ChatScreen } from "./ChatScreen";

const CONVERSATION_ID = "7d3e2c1b-0a9f-4e8d-8c7b-6a5f4e3d2c1b";
const ANSWER_ID = "a1";

function model(p: Partial<ModelOut> & Pick<ModelOut, "id" | "display_name">): ModelOut {
  return {
    provider: "Hang",
    provider_id: "hang",
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
    checked_at: "2026-09-26T07:00:00Z",
    stale_after_s: 30,
    ...p,
  };
}

const levels = (...ids: string[]) => ids.map((id) => ({ id }));

const MODELS: ModelOut[] = [
  model({
    id: "deepseek-flash",
    display_name: "DeepSeek Flash",
    default: true,
    reasoning: { default: "high", options: levels("off", "low", "high", "max") },
  }),
  model({ id: "ol-qwen-small", display_name: "Qwen2.5 0.5B (Ollama)" }),
];

const BASE_PROFILE: ProfileOut = {
  id: "5e4d3c2b-1a0f-4e9d-8c7b-6a5f4e3d2c1b",
  email: "binh@scarlet.test",
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "free",
  default_model: "ol-qwen-small",
  last_login_at: "2026-09-26T01:00:00Z",
  quota: null,
  message_max_chars: 24000,
  quota_warn_remaining_pct: 20,
  limits_cache_ttl_s: 60,
  stream_ttl_s: 3600,
  display_name_max_chars: 64,
  avatar_color: null,
  reasoning_prefs: {},
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
    created_at: "2026-09-26T08:00:00Z",
    sibling_index: 0,
    sibling_count: 1,
    feedback: null,
    reasoning_effort: null,
    ...p,
  };
}

/** Trang thai "server" cua bo dinh tuyen gia — dat lai o `beforeEach`. */
const server = {
  profile: BASE_PROFILE,
  conversationModel: null as string | null,
  answer: message({ id: ANSWER_ID }),
};

function detail(): ConversationDetail {
  return {
    id: CONVERSATION_ID,
    title: "Hoi thu",
    default_model: server.conversationModel,
    system_prompt_override: null,
    active_leaf_id: ANSWER_ID,
    pinned: false,
    created_at: "2026-09-26T08:00:00Z",
    updated_at: "2026-09-26T08:00:00Z",
    path: [message({ id: "u1", content: "Cau hoi dau" }), server.answer],
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

/** Bo dinh tuyen: `METHOD /duong-dan` (khong query) → response. */
const fakeFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const method = init?.method ?? "GET";
  const path = String(input).replace(/^\/api\/v1/, "").split("?")[0];
  const body: unknown = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
  switch (`${method} ${path}`) {
    case "GET /auth/me":
      return reply(200, server.profile);
    case "PUT /settings": {
      server.profile = { ...server.profile, ...(body as Partial<ProfileOut>) };
      return reply(200, body);
    }
    case "GET /models":
      return reply(200, MODELS);
    case "GET /conversations":
      return reply(200, { items: [], next_cursor: null, truncated: false });
    case "GET /settings/keys":
      return reply(200, { keys: [], byok_providers: [] });
    case `GET /conversations/${CONVERSATION_ID}`:
      return reply(200, detail());
    case `PATCH /conversations/${CONVERSATION_ID}`: {
      server.conversationModel = (body as { default_model: string }).default_model;
      return reply(200, detail());
    }
    case `POST /messages/${ANSWER_ID}/retry`:
      return reply(202, {
        assistant_message_id: "a2",
        stream_url: "/api/v1/messages/a2/stream",
        model_id: (body as { model_id?: string }).model_id ?? "ol-qwen-small",
        quota_warning: null,
      });
    default:
      return reply(404, { error: { code: "NOT_FOUND", message: `${method} ${path}`, details: null } });
  }
});

/** `EventSource` rong — jsdom khong co; file nay khong do stream. */
class SilentEventSource {
  static readonly CLOSED = 2;
  readyState = 0;
  addEventListener(): void {}
  removeEventListener(): void {}
  close(): void {
    this.readyState = SilentEventSource.CLOSED;
  }
}

function retryCalls() {
  return fakeFetch.mock.calls.filter(
    ([input, init]) => init?.method === "POST" && String(input).endsWith(`/messages/${ANSWER_ID}/retry`),
  );
}

function Harness() {
  const session = useSessionState();
  holder.current = session;
  return session.loading ? null : <ChatScreen />;
}

const trigger = () => screen.getByRole("button", { name: /^Chọn mô hình/ });
const effortRow = () => screen.getByRole("button", { name: /^Thinking Effort/ });

/** Doi model tren picker — cung duong `ReasoningFlow.test.tsx` (T-S.14). */
async function pickModel(name: string): Promise<void> {
  await userEvent.click(trigger());
  await userEvent.click(screen.getByRole("button", { name: /^More models/ }));
  await userEvent.click(within(await screen.findByRole("listbox")).getByText(name));
  await waitFor(() => expect(trigger()).toHaveTextContent(name));
}

async function pickEffort(label: string): Promise<void> {
  await userEvent.click(trigger());
  act(() => effortRow().focus()); // B-308 ①
  await userEvent.click(effortRow());
  await userEvent.click(await screen.findByRole("menuitemradio", { name: label }));
  await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
  await userEvent.keyboard("{Escape}");
}

beforeEach(() => {
  holder.current = null;
  server.profile = BASE_PROFILE;
  server.conversationModel = null;
  server.answer = message({
    id: ANSWER_ID,
    parent_id: "u1",
    role: "assistant",
    content: "Tra loi cua Qwen",
    model_id: "ol-qwen-small",
    finish_reason: "stop",
  });
  fakeFetch.mockClear();
  vi.stubGlobal("fetch", fakeFetch);
  vi.stubGlobal("EventSource", SilentEventSource);
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

function renderApp() {
  return render(
    <MemoryRouter>
      <Harness />
    </MemoryRouter>,
  );
}

describe("mot nut Thu lai gui model + muc cua picker (T-S.15 DoD dong 1)", () => {
  it("1. doi sang DeepSeek Flash · Max tren picker → Thu lai ⇒ `POST /messages/{id}/retry` mang DUNG `model_id` va `reasoning_effort` ay", async () => {
    renderApp();
    const answer = await screen.findByRole("article", { name: "Scarlet trả lời" });
    await waitFor(() => expect(trigger()).toHaveTextContent("Qwen2.5 0.5B (Ollama)"));
    // Chip ghi model DA sinh cau tra loi (ten hien thi), khong phai picker.
    expect(within(answer).getByText("Qwen2.5 0.5B (Ollama)")).toBeInTheDocument();
    // Khong con nut thu hai (UC-02 dong 5 nay la "doi tren picker roi bam Thu lai").
    expect(within(answer).getAllByRole("button", { name: /thử lại/i })).toHaveLength(1);
    expect(within(answer).queryByRole("button", { name: /đổi model/i })).toBeNull();

    await pickModel("DeepSeek Flash");
    await pickEffort("Max");
    await userEvent.click(within(answer).getByRole("button", { name: "Thử lại" }));

    await waitFor(() => expect(retryCalls()).toHaveLength(1));
    const [url, init] = retryCalls()[0];
    expect(String(url)).toBe(`/api/v1/messages/${ANSWER_ID}/retry`);
    expect(JSON.parse(String(init?.body))).toEqual({ model_id: "deepseek-flash", reasoning_effort: "max" });
    // B-231 / NQ-93: route bat buoc khoa §11.4.
    expect((init?.headers as Record<string, string>)["Idempotency-Key"]).toMatch(/\S/);
    // Chip cua cau tra loi cu KHONG doi theo picker.
    expect(within(answer).getByText("Qwen2.5 0.5B (Ollama)")).toBeInTheDocument();
  });

  it("2. bong bong LOI: nut Thu lai cua no gui cung body voi hang nut (ban ve 3a/4)", async () => {
    server.answer = message({
      id: ANSWER_ID,
      parent_id: "u1",
      role: "assistant",
      status: "failed",
      model_id: "ol-qwen-small",
      error_code: "ERR_PROVIDER_502",
    });
    server.profile = { ...BASE_PROFILE, default_model: "deepseek-flash", reasoning_prefs: { "deepseek-flash": "low" } };
    renderApp();
    const answer = await screen.findByRole("article", { name: "Scarlet trả lời" });
    await waitFor(() => expect(trigger()).toHaveTextContent("DeepSeek Flash"));

    await userEvent.click(within(answer).getByRole("button", { name: "Thử lại" }));

    await waitFor(() => expect(retryCalls()).toHaveLength(1));
    expect(JSON.parse(String(retryCalls()[0][1]?.body))).toEqual({
      model_id: "deepseek-flash",
      reasoning_effort: "low",
    });
  });

  it("3. picker dang o model KHONG co muc ⇒ body chi co `model_id` (mot `id` bat ky la `400`)", async () => {
    renderApp();
    const answer = await screen.findByRole("article", { name: "Scarlet trả lời" });
    await waitFor(() => expect(trigger()).toHaveTextContent("Qwen2.5 0.5B (Ollama)"));

    await userEvent.click(within(answer).getByRole("button", { name: "Thử lại" }));

    await waitFor(() => expect(retryCalls()).toHaveLength(1));
    expect(JSON.parse(String(retryCalls()[0][1]?.body))).toEqual({ model_id: "ol-qwen-small" });
  });
});
