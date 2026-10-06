/**
 * The artifact trong bong bong, dau-cuoi o tang FE — T-5.3 DoD dong 1.
 *
 * KH tham chieu: §7.3, §7.4 (`artifact` ⇒ mo panel phai), UC-10 dong 1, B-87,
 * B-363 · NQ-142 (Q-P5-7) · tasks.md T-5.3.
 *
 * `ChatScreen` THAT tren `useSessionState` THAT, `useChat` THAT, `api` THAT
 * (khuon `RetryFlow.test.tsx`). Chi hai thu cua trinh duyet bi thay: `fetch`
 * (bo dinh tuyen gia) va `EventSource` (jsdom khong co) — o day `EventSource`
 * gia PHAT duoc event, vi stream chinh la thu dang do.
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

import type { ArtifactOut, ConversationDetail, MessageOut, PathArtifact, ProfileOut } from "../../lib/api";
import { useSessionState } from "../../features/auth/useSessionState";
import themeCss from "../../styles/theme.css?raw";
import { ChatScreen } from "./ChatScreen";

const CONVERSATION_ID = "7d3e2c1b-0a9f-4e8d-8c7b-6a5f4e3d2c1b";
const ANSWER_ID = "a1";
const ARTIFACT_ID = "art-1";

/** Than khoi — dung `code.value` cua mdast, khong `\n` cuoi. */
const BLOCK = '<!doctype html>\n<h1 class="gia">Bảng giá</h1>\n<p>  hai dấu cách đầu dòng</p>';
const ANSWER_TEXT = `Đây là trang:\n\n\`\`\`html title="Bảng giá"\n${BLOCK}\n\`\`\`\n\nXong rồi.`;

const ARTIFACT: PathArtifact = {
  id: ARTIFACT_ID,
  kind: "html",
  language: "html",
  title: "Bảng giá",
  version: 1,
  content: BLOCK,
};

const PROFILE: ProfileOut = {
  id: "5e4d3c2b-1a0f-4e9d-8c7b-6a5f4e3d2c1b",
  email: "binh@scarlet.test",
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "free",
  default_model: null,
  last_login_at: "2026-10-07T01:00:00Z",
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
    created_at: "2026-10-07T08:00:00Z",
    sibling_index: 0,
    sibling_count: 1,
    feedback: null,
    reasoning_effort: null,
    artifacts: [],
    ...p,
  };
}

function answer(p: Partial<MessageOut> = {}): MessageOut {
  return message({ id: ANSWER_ID, parent_id: "u1", role: "assistant", content: ANSWER_TEXT, finish_reason: "stop", ...p });
}

/** Duong di cua "server" — dat lai o `beforeEach`, ca test doi giua chung. */
const server = { path: [] as MessageOut[] };

function detail(): ConversationDetail {
  return {
    id: CONVERSATION_ID,
    title: "Hoi thu",
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: server.path[server.path.length - 1].id,
    pinned: false,
    created_at: "2026-10-07T08:00:00Z",
    updated_at: "2026-10-07T08:00:00Z",
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

const fakeFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const method = init?.method ?? "GET";
  const path = String(input).replace(/^\/api\/v1/, "").split("?")[0];
  switch (`${method} ${path}`) {
    case "GET /auth/me":
      return reply(200, PROFILE);
    case "GET /models":
      return reply(200, []);
    case "GET /conversations":
      return reply(200, { items: [], next_cursor: null, truncated: false });
    case `GET /conversations/${CONVERSATION_ID}`:
      return reply(200, detail());
    case `GET /artifacts/${ARTIFACT_ID}`: {
      const out: ArtifactOut = {
        ...ARTIFACT,
        lineage_id: ARTIFACT_ID,
        message_id: ANSWER_ID,
        conversation_id: CONVERSATION_ID,
        created_at: "2026-10-07T08:00:01Z",
      };
      return reply(200, out);
    }
    default:
      return reply(404, { error: { code: "NOT_FOUND", message: `${method} ${path}`, details: null } });
  }
});

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

const ARTIFACT_EVENT = { artifact_id: ARTIFACT_ID, version: 1, kind: "html", title: "Bảng giá" };

function artifactGets() {
  return fakeFetch.mock.calls.filter(([input]) => String(input).endsWith(`/artifacts/${ARTIFACT_ID}`));
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

const panel = () => document.getElementById("artifact-panel");
const answers = () => screen.getAllByRole("article", { name: "Scarlet trả lời" });

beforeEach(() => {
  holder.current = null;
  server.path = [message({ id: "u1", content: "Tạo trang bảng giá" }), answer()];
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
  // jsdom khong nap `theme.css`: ba token be rong cua panel chep tu tep that (lo T-5.4).
  for (const name of ["--spacing-panel-right", "--spacing-panel-min", "--spacing-panel-max"]) {
    const value = new RegExp(`${name}:\\s*([^;]+);`).exec(themeCss)?.[1] ?? "";
    document.documentElement.style.setProperty(name, value);
  }
});

/** Message dang chay: stream mo, chu chay xong (con `running`), CHUA co event `artifact`. */
async function streamedAnswer(): Promise<FakeEventSource> {
  server.path = [message({ id: "u1", content: "Tạo trang bảng giá" }), answer({ status: "streaming", content: "" })];
  renderApp();
  await waitFor(() => expect(FakeEventSource.all).toHaveLength(1));
  const es = FakeEventSource.all[0];
  expect(es.url).toBe(`/api/v1/messages/${ANSWER_ID}/stream`);
  es.emit("start", { message_id: ANSWER_ID, model_id: "claude-haiku" }, "1-0");
  es.emit("delta", { t: ANSWER_TEXT }, "1-1");
  await waitFor(() => expect(answers()[0]).toHaveTextContent("Xong rồi."));
  return es;
}

describe("event `artifact` (UC-10 dong 1, §7.3)", () => {
  it("1. dang stream khoi hien nhu cu; event ⇒ the + panel mo voi artifact ay + DUNG mot `GET /artifacts/{id}`; khoi thanh the", async () => {
    const es = await streamedAnswer();
    expect(answers()[0].querySelectorAll("pre")).toHaveLength(1);
    expect(panel()).toBeNull();

    es.emit("artifact", ARTIFACT_EVENT, "1-2");

    const open = await within(answers()[0]).findByRole("button", { name: "Mở Bảng giá" });
    await waitFor(() => expect(answers()[0].querySelectorAll("pre")).toHaveLength(0));
    expect(open.closest("article")).toHaveTextContent("v1");
    await waitFor(() => expect(panel()).toHaveTextContent("<h1 class=\"gia\">Bảng giá</h1>"));
    expect(artifactGets()).toHaveLength(1);
  });

  it("2. CUNG event phat lai (XRANGE) ⇒ van mot the, khong request thu hai, panel da dong khong mo lai", async () => {
    const user = userEvent.setup();
    const es = await streamedAnswer();
    es.emit("artifact", ARTIFACT_EVENT, "1-2");
    await waitFor(() => expect(panel()).not.toBeNull());
    await user.click(screen.getByRole("button", { name: "Đóng panel artifact" }));
    expect(panel()).toBeNull();

    es.emit("artifact", ARTIFACT_EVENT, "1-2");
    es.emit("artifact", ARTIFACT_EVENT, "1-3");

    expect(within(answers()[0]).getAllByRole("button", { name: /^Mở / })).toHaveLength(1);
    expect(artifactGets()).toHaveLength(1);
    expect(panel()).toBeNull();
  });

  it("3. `done` ⇒ doc lai duong di co `artifacts[]` ⇒ van MOT the, khong `pre`", async () => {
    const es = await streamedAnswer();
    es.emit("artifact", ARTIFACT_EVENT, "1-2");
    await waitFor(() => expect(artifactGets()).toHaveLength(1));

    server.path = [message({ id: "u1", content: "Tạo trang bảng giá" }), answer({ artifacts: [ARTIFACT] })];
    es.emit("done", { finish_reason: "stop", usage: null }, "1-3");

    // Mot lan luc mo, mot lan sau `done` (luat 1 cua `useChat`).
    await waitFor(() =>
      expect(fakeFetch.mock.calls.filter(([i]) => String(i).endsWith(`/conversations/${CONVERSATION_ID}`))).toHaveLength(2),
    );
    expect(within(answers()[0]).getAllByRole("button", { name: /^Mở / })).toHaveLength(1);
    expect(answers()[0].querySelectorAll("pre")).toHaveLength(0);
    expect(artifactGets()).toHaveLength(1);
  });
});

describe("the dung tu duong di (B-87) va khop khoi (Q-P5-7)", () => {
  it("4. duong di co `artifacts[]` ⇒ the KHONG can stream, panel dong, khong `GET /artifacts`; 'Mo' ⇒ panel hien artifact", async () => {
    const user = userEvent.setup();
    server.path = [message({ id: "u1", content: "Tạo trang bảng giá" }), answer({ artifacts: [ARTIFACT] })];
    renderApp();

    const open = await screen.findByRole("button", { name: "Mở Bảng giá" });
    expect(answers()[0].querySelectorAll("pre")).toHaveLength(0);
    expect(FakeEventSource.all).toHaveLength(0);
    expect(panel()).toBeNull();
    expect(artifactGets()).toHaveLength(0);

    await user.click(open);
    expect(panel()).toHaveTextContent("Bảng giá");
    expect(panel()?.querySelector("pre")?.textContent).toBe(BLOCK);
  });

  it("5. the nam DUNG CHO khoi: giua 'Day la trang' va 'Xong roi'", async () => {
    server.path = [message({ id: "u1", content: "Tạo trang bảng giá" }), answer({ artifacts: [ARTIFACT] })];
    renderApp();

    const open = await screen.findByRole("button", { name: "Mở Bảng giá" });
    const before = within(answers()[0]).getByText("Đây là trang:");
    const after = within(answers()[0]).getByText("Xong rồi.");
    expect(before.compareDocumentPosition(open) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(after.compareDocumentPosition(open) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  });

  it("6. `content` khac khoi MOT byte (khoang trang cuoi) ⇒ giu `pre`; the xuong duoi chu, khong mat (B-363)", async () => {
    server.path = [
      message({ id: "u1", content: "Tạo trang bảng giá" }),
      answer({ artifacts: [{ ...ARTIFACT, content: `${BLOCK} ` }] }),
    ];
    renderApp();

    const open = await screen.findByRole("button", { name: "Mở Bảng giá" });
    expect(answers()[0].querySelectorAll("pre")).toHaveLength(1);
    const after = within(answers()[0]).getByText("Xong rồi.");
    expect(after.compareDocumentPosition(open) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("7. artifact cua message KHAC co cung noi dung ⇒ khoi cua message nay KHONG bi thay", async () => {
    server.path = [
      message({ id: "u1", content: "Tạo trang bảng giá" }),
      answer({ artifacts: [] }),
      message({ id: "u2", parent_id: ANSWER_ID, content: "Lưu lại giúp" }),
      message({
        id: "a2",
        parent_id: "u2",
        role: "assistant",
        content: "Đã lưu bản ở trên.",
        finish_reason: "stop",
        artifacts: [{ ...ARTIFACT, id: "art-2" }],
      }),
    ];
    renderApp();

    await screen.findByRole("button", { name: "Mở Bảng giá" });
    const [first, second] = answers();
    expect(first.querySelectorAll("pre")).toHaveLength(1);
    expect(within(first).queryByRole("button", { name: /^Mở / })).toBeNull();
    expect(within(second).getAllByRole("button", { name: /^Mở / })).toHaveLength(1);
  });

  it("9. B-363 ①: rao cot 0 trong `<div>` khong dong trong — mdast 0 khoi, Python 1 artifact ⇒ the van hien, duoi chu", async () => {
    server.path = [
      message({ id: "u1", content: "Lồng sai" }),
      answer({ content: `<div>\n\`\`\`html\n${BLOCK}\n\`\`\`\n</div>\n\nHết.`, artifacts: [ARTIFACT] }),
    ];
    renderApp();

    const open = await screen.findByRole("button", { name: "Mở Bảng giá" });
    expect(answers()[0].querySelectorAll("pre")).toHaveLength(0);
    const after = within(answers()[0]).getByText("Hết.");
    expect(after.compareDocumentPosition(open) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("8. hai khoi giong het, hai artifact ⇒ hai the, khong `pre` nao (moi artifact dat mot lan)", async () => {
    const twice = `Một:\n\n\`\`\`html\n${BLOCK}\n\`\`\`\n\nHai:\n\n\`\`\`html\n${BLOCK}\n\`\`\``;
    server.path = [
      message({ id: "u1", content: "Hai lần" }),
      answer({
        content: twice,
        artifacts: [
          { ...ARTIFACT, title: "" },
          { ...ARTIFACT, id: "art-2", title: "" },
        ],
      }),
    ];
    renderApp();

    await waitFor(() => expect(within(answers()[0]).getAllByRole("button", { name: /^Mở / })).toHaveLength(2));
    expect(answers()[0].querySelectorAll("pre")).toHaveLength(0);
    // Tieu de rong ⇒ nhan suy ra tu ngon ngu + so dong.
    expect(within(answers()[0]).getAllByRole("button", { name: "Mở html · 3 dòng" })).toHaveLength(2);
  });
});
