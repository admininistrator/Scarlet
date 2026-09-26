/**
 * Muc suy luan dau-cuoi o tang FE — T-S.14 DoD dong 1 (phan "PUT dung body va
 * lan gui sau mang `reasoning_effort`") va Cam bay ②.
 *
 * KH tham chieu: §24.2b·S4, S10 (`PUT /settings` thay ca tai nguyen), S11 ·
 * tasks.md T-S.5 DoD dong 2, T-S.14.
 *
 * Dung `ChatScreen` THAT tren `useSessionState` THAT — chi `api` (va
 * `openStream`) bi thay. Mot test chi dung picker se khong thay duoc hai loi
 * dang so nhat: body `PUT` thieu truong (mat `default_model`), va lan gui
 * doc mot muc khac muc picker dang hien.
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionState } from "../auth/useSessionState";

const holder: { current: SessionState | null } = { current: null };

vi.mock("../../app/Layout", () => ({
  useSession: () => holder.current,
}));

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      updateSettings: vi.fn(),
      listModels: vi.fn(),
      listConversations: vi.fn(),
      listProviderKeys: vi.fn(),
      getConversation: vi.fn(),
      createConversation: vi.fn(),
      sendMessage: vi.fn(),
    },
  };
});

/*
  Stream gia KHEP ngay (`done`): lan gui thu hai can nut Gui, ma trong luc mot
  luot con chay o nhap chi co nut Dung.
*/
vi.mock("../../lib/sse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/sse")>();
  return {
    ...actual,
    openStream: vi.fn((params: { onEvent: (e: import("../../lib/sse").StreamEvent) => void }) => {
      queueMicrotask(() =>
        params.onEvent({ event: "done", data: { finish_reason: "stop", usage: null } }),
      );
      return { close: vi.fn(), cursor: () => "" };
    }),
  };
});

import { api, type ModelOut, type ProfileOut } from "../../lib/api";
import { ChatScreen } from "../../components/chat/ChatScreen";
import { useSessionState } from "../auth/useSessionState";

const CONVERSATION_ID = "3c1e9b7a-2d4f-4a8e-9b6c-5d7e8f9a0b1c";

function model(p: Partial<ModelOut> & Pick<ModelOut, "id">): ModelOut {
  return {
    display_name: p.id,
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
    provider: "DeepSeek",
    default: true,
    reasoning: { default: "high", options: levels("off", "low", "high", "max") },
  }),
  model({
    id: "claude-haiku",
    display_name: "Claude Haiku 4.5",
    provider: "Anthropic",
    reasoning: { default: "off", options: levels("off", "low", "high") },
  }),
  model({ id: "ol-qwen-small", display_name: "Qwen2.5 0.5B (Ollama)", provider: "Alibaba Qwen" }),
];

/**
 * DeepSeek dang nho `low` — KHAC mac dinh `high` cua catalog, de lan chon
 * `high` la mot thay doi that chu khong trung voi duong lui. Haiku nho `low`
 * de Cam bay ② co mot muc rieng de doi chieu.
 */
const PROFILE: ProfileOut = {
  id: "8a7b6c5d-4e3f-4a1b-9c8d-7e6f5a4b3c2d",
  email: "an.nguyen@scarlet.test",
  display_name: "An",
  status: "active",
  role: "user",
  tier_name: "free",
  default_model: null,
  last_login_at: "2026-09-26T01:00:00Z",
  quota: null,
  message_max_chars: 24000,
  quota_warn_remaining_pct: 20,
  limits_cache_ttl_s: 60,
  stream_ttl_s: 3600,
  display_name_max_chars: 64,
  avatar_color: "avatar-3",
  reasoning_prefs: { "deepseek-flash": "low", "claude-haiku": "low" },
};

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

const trigger = () => screen.getByRole("button", { name: /^Chọn mô hình/ });
const effortRow = () => screen.getByRole("button", { name: /^Thinking Effort/ });

async function send(text: string): Promise<void> {
  await userEvent.type(screen.getByRole("textbox"), text);
  await userEvent.click(await screen.findByRole("button", { name: "Gửi" }));
}

/** Body cua lan `sendMessage` thu `n` (dem tu 0). */
function sentBody(n: number) {
  return vi.mocked(api.sendMessage).mock.calls[n][1];
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
  window.history.replaceState(null, "", "/");
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  vi.mocked(api.me).mockReset().mockResolvedValue(PROFILE);
  vi.mocked(api.updateSettings)
    .mockReset()
    .mockImplementation(async (body) => ({ ...body }));
  vi.mocked(api.listModels).mockReset().mockResolvedValue(MODELS);
  vi.mocked(api.listConversations).mockResolvedValue({ items: [], next_cursor: null, truncated: false });
  vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [], byok_providers: [] });
  vi.mocked(api.createConversation).mockReset().mockResolvedValue({
    id: CONVERSATION_ID,
    title: null,
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: null,
    pinned: false,
    created_at: "2026-09-26T08:00:00Z",
    updated_at: "2026-09-26T08:00:00Z",
  });
  vi.mocked(api.sendMessage).mockReset().mockResolvedValue({
    user_message_id: "u1",
    assistant_message_id: "a1",
    stream_url: "/api/v1/messages/a1/stream",
    branched: false,
    quota_warning: null,
  });
  vi.mocked(api.getConversation).mockReset().mockResolvedValue({
    id: CONVERSATION_ID,
    title: null,
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: null,
    pinned: false,
    created_at: "2026-09-26T08:00:00Z",
    updated_at: "2026-09-26T08:00:00Z",
    path: [],
  });
});

describe("muc suy luan: picker → PUT /settings → lan gui (T-S.14 DoD dong 1)", () => {
  it("1. chon High cho DeepSeek ⇒ PUT DU bon truong, `reasoning_prefs` ghep dung mot khoa; lan gui SAU mang `reasoning_effort: \"high\"`", async () => {
    renderApp();
    await waitFor(() => expect(trigger()).toHaveTextContent("DeepSeek Flash"));

    // Truoc khi chon: lan gui mang muc DA NHO (`low`), khong phai mac dinh catalog.
    await send("cau mot");
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(1));
    expect(sentBody(0)).toMatchObject({ model_id: "deepseek-flash", reasoning_effort: "low" });

    await pickEffort("High");

    expect(api.updateSettings).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.updateSettings).mock.calls[0][0]).toEqual({
      default_model: null,
      display_name: "An",
      avatar_color: "avatar-3",
      reasoning_prefs: { "deepseek-flash": "high", "claude-haiku": "low" },
    });

    // Picker doc lai tu ho so vua ghi.
    await userEvent.click(trigger());
    expect(effortRow()).toHaveTextContent("High");
    await userEvent.keyboard("{Escape}");

    await send("cau hai");
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(2));
    expect(sentBody(1)).toMatchObject({ model_id: "deepseek-flash", reasoning_effort: "high" });
  });

  it("2. Cam bay ② — doi sang Claude Haiku ⇒ picker hien muc da nho CUA HAIKU (Low), va lan gui mang dung muc ay", async () => {
    renderApp();
    await waitFor(() => expect(trigger()).toHaveTextContent("DeepSeek Flash"));
    await pickEffort("Max");
    expect(vi.mocked(api.updateSettings).mock.calls[0][0].reasoning_prefs).toEqual({
      "deepseek-flash": "max",
      "claude-haiku": "low",
    });

    await userEvent.click(trigger());
    await userEvent.click(screen.getByRole("button", { name: /^More models/ }));
    await userEvent.click(within(await screen.findByRole("listbox")).getByText("Claude Haiku 4.5"));
    await waitFor(() => expect(trigger()).toHaveTextContent("Claude Haiku 4.5"));

    await userEvent.click(trigger());
    expect(effortRow()).toHaveTextContent("Low");
    expect(effortRow()).not.toHaveTextContent("Max");
    await userEvent.keyboard("{Escape}");

    await send("cau cua haiku");
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(1));
    expect(sentBody(0)).toMatchObject({ model_id: "claude-haiku", reasoning_effort: "low" });
  });

  it("3. model khong co `reasoning` ⇒ lan gui KHONG co truong `reasoning_effort` (mot `id` bat ky la `400`)", async () => {
    vi.mocked(api.me).mockResolvedValue({ ...PROFILE, default_model: "ol-qwen-small" });
    renderApp();
    await waitFor(() => expect(trigger()).toHaveTextContent("Qwen2.5 0.5B (Ollama)"));
    await send("cau cua qwen");
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(1));
    expect(sentBody(0)).toMatchObject({ model_id: "ol-qwen-small" });
    expect(sentBody(0)).not.toHaveProperty("reasoning_effort");
  });
});
