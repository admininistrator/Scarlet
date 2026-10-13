/**
 * Chip "Dang chay code…" + the tep cua skill — dau-cuoi o tang FE (T-7.9).
 *
 * KH tham chieu: UC-09 dong 3 · §7.4 (`tool_call`, `tool_result`, `artifact`)
 * · B-87, B-372, B-405 ④, B-406 ②④⑤ · tasks.md T-7.9.
 *
 * `ChatScreen` THAT tren `useSessionState`, `useChat`, `api` THAT (khuon
 * `ArtifactFlow.test.tsx`). Chi `fetch` (bo dinh tuyen gia) va `EventSource`
 * (ban gia PHAT duoc event) bi thay.
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
const FILE_ID = "art-file";
const DOWNLOAD_URL = "https://scarlet.test/files/u/abc?X-Amz-Signature=ky";

const FILE: PathArtifact = { id: FILE_ID, kind: "file", language: null, title: "bao-cao.docx", version: 1, content: null };
const FILE_EVENT = { artifact_id: FILE_ID, version: 1, kind: "file", title: "bao-cao.docx" };

const PROFILE: ProfileOut = {
  id: "5e4d3c2b-1a0f-4e9d-8c7b-6a5f4e3d2c1b",
  email: "binh@scarlet.test",
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "trusted",
  default_model: null,
  last_login_at: "2026-10-13T01:00:00Z",
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
  can_execute_skills: true,
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
    created_at: "2026-10-13T08:00:00Z",
    sibling_index: 0,
    sibling_count: 1,
    feedback: null,
    reasoning_effort: null,
    artifacts: [],
    tools: [],
    ...p,
  };
}

const question = () => message({ id: "u1", content: "Tạo file Word báo cáo" });
const answer = (p: Partial<MessageOut> = {}) =>
  message({ id: ANSWER_ID, parent_id: "u1", role: "assistant", content: "Đã tạo tệp.", finish_reason: "stop", ...p });

const server = { path: [] as MessageOut[], fileStatus: 200 };

function detail(): ConversationDetail {
  return {
    id: CONVERSATION_ID,
    title: "Hoi thu",
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: server.path[server.path.length - 1].id,
    pinned: false,
    created_at: "2026-10-13T08:00:00Z",
    updated_at: "2026-10-13T08:00:00Z",
    path: server.path,
  };
}

function reply(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, statusText: "", json: () => Promise.resolve(body) } as unknown as Response;
}

const fakeFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const method = init?.method ?? "GET";
  const path = String(input).replace(/^\/api\/v1/, "").split("?")[0];
  switch (`${method} ${path}`) {
    case "GET /auth/me":
      return reply(200, PROFILE);
    case "GET /models":
      return reply(200, []);
    case "GET /skills":
      return reply(200, { items: [] });
    case "GET /conversations":
      return reply(200, { items: [], next_cursor: null, truncated: false });
    case `GET /conversations/${CONVERSATION_ID}`:
      return reply(200, detail());
    case `GET /artifacts/${FILE_ID}`: {
      if (server.fileStatus !== 200) {
        return reply(server.fileStatus, { error: { code: "INTERNAL", message: "x", details: null } });
      }
      const out: ArtifactOut = {
        ...FILE,
        lineage_id: FILE_ID,
        download_url: DOWNLOAD_URL,
        message_id: ANSWER_ID,
        conversation_id: CONVERSATION_ID,
        created_at: "2026-10-13T08:00:01Z",
      };
      return reply(200, out);
    }
    default:
      return reply(404, { error: { code: "NOT_FOUND", message: `${method} ${path}`, details: null } });
  }
});

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

const panel = () => document.getElementById("artifact-panel");
const reply0 = () => screen.getAllByRole("article", { name: "Scarlet trả lời" })[0];
const chips = () => within(reply0()).queryAllByRole("status").filter((el) => el.className.includes("rounded-full"));
const fileGets = () => fakeFetch.mock.calls.filter(([input]) => String(input).endsWith(`/artifacts/${FILE_ID}`));

const CALL = { call_id: "c1", name: "run_code", args: { skill: "docx" } };
const OK = { call_id: "c1", name: "run_code", ok: true, result: { reason: null, sources: [] } };

beforeEach(() => {
  holder.current = null;
  server.path = [question(), answer()];
  server.fileStatus = 200;
  FakeEventSource.all = [];
  fakeFetch.mockClear();
  localStorage.clear();
  vi.stubGlobal("fetch", fakeFetch);
  vi.stubGlobal("EventSource", FakeEventSource);
  window.history.replaceState(null, "", `/?c=${CONVERSATION_ID}`);
  for (const name of ["--spacing-panel-right", "--spacing-panel-min", "--spacing-panel-max"]) {
    const value = new RegExp(`${name}:\\s*([^;]+);`).exec(themeCss)?.[1] ?? "";
    document.documentElement.style.setProperty(name, value);
  }
});

async function streaming(): Promise<FakeEventSource> {
  server.path = [question(), answer({ status: "streaming", content: "" })];
  render(
    <MemoryRouter>
      <Harness />
    </MemoryRouter>,
  );
  await waitFor(() => expect(FakeEventSource.all).toHaveLength(1));
  const es = FakeEventSource.all[0];
  es.emit("start", { message_id: ANSWER_ID, model_id: "claude-haiku" }, "1-0");
  // The artifact nam duoi CHU tra loi (B-363): luot that co chu truoc / sau tool.
  es.emit("delta", { t: "Mình tạo tệp cho bạn." }, "1-00");
  return es;
}

describe("chip chay code (T-7.9)", () => {
  it("1. `tool_call load_skill` ⇒ KHONG chip (B-405 ④); `tool_call run_code` ⇒ chip 'Đang chạy code…'", async () => {
    const es = await streaming();
    es.emit("tool_call", { call_id: "c0", name: "load_skill", args: { name: "docx" } }, "1-1");
    es.emit("tool_result", { call_id: "c0", name: "load_skill", ok: true, result: { reason: null, sources: [] } }, "1-2");
    expect(chips()).toHaveLength(0);

    es.emit("tool_call", CALL, "1-3");

    await waitFor(() => expect(chips()).toHaveLength(1));
    expect(chips()[0]).toHaveTextContent("Đang chạy code…");
    expect(chips()[0].querySelector(".motion-spin")).not.toBeNull();
    expect(chips()[0]).not.toHaveAttribute("data-planned");
  });

  it("2. `tool_result ok` + `artifact kind=file` ⇒ 'Đã chạy code' + the tep; panel mo man tep: khong xem truoc, nut Tai, KHONG Sua", async () => {
    const es = await streaming();
    es.emit("tool_call", CALL, "1-1");
    es.emit("tool_result", OK, "1-2");
    es.emit("artifact", FILE_EVENT, "1-3");

    await waitFor(() => expect(chips()[0]).toHaveTextContent("Đã chạy code"));
    expect(await within(reply0()).findByRole("button", { name: "Mở bao-cao.docx" })).toBeInTheDocument();
    await waitFor(() => expect(panel()).toHaveTextContent("Loại này không xem trước được"));
    const view = within(panel() as HTMLElement);
    // Nut o dau panel + nut chinh cua man tep (ban T-HD6).
    expect(view.getAllByRole("button", { name: /^Tải về\s*\.docx$/ })).toHaveLength(2);
    expect(view.queryByRole("button", { name: "Sửa" })).toBeNull();
    expect(panel()?.querySelector("iframe")).toBeNull();
  });

  it("3. Tai ⇒ `GET /artifacts/{id}` LUC BAM (URL ky moi, B-406 ②) roi mo `download_url`; GET hong ⇒ cau loi", async () => {
    const opened: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      opened.push(this.href);
    });
    const user = userEvent.setup();
    const es = await streaming();
    es.emit("artifact", FILE_EVENT, "1-1");
    await waitFor(() => expect(panel()).toHaveTextContent("Loại này không xem trước được"));
    const before = fileGets().length;

    await user.click(within(panel() as HTMLElement).getAllByRole("button", { name: /^Tải về\s*\.docx$/ })[1]);

    await waitFor(() => expect(opened).toEqual([DOWNLOAD_URL]));
    expect(fileGets()).toHaveLength(before + 1);

    server.fileStatus = 500;
    await user.click(within(panel() as HTMLElement).getAllByRole("button", { name: /^Tải về\s*\.docx$/ })[1]);
    expect(await within(panel() as HTMLElement).findByRole("alert")).toHaveTextContent("Chưa tải được. Hãy thử lại.");
    expect(opened).toHaveLength(1);
    click.mockRestore();
  });

  it("4. `ok=false` ⇒ chip loi cau theo `reason` (no_exec_permission, sandbox_unavailable, ma la)", async () => {
    const es = await streaming();
    const fail = (id: string, reason: string) => ({ call_id: id, name: "run_code", ok: false, result: { reason, sources: [] } });
    for (const [id, reason] of [["a", "no_exec_permission"], ["b", "sandbox_unavailable"], ["c", "internal"]]) {
      es.emit("tool_call", { ...CALL, call_id: id }, `1-${id}`);
      es.emit("tool_result", fail(id, reason), `2-${id}`);
    }

    await waitFor(() => expect(chips()).toHaveLength(3));
    expect(chips().map((c) => c.textContent)).toEqual([
      "Tài khoản chưa được chạy code",
      "Chưa chạy được code lúc này",
      "Công cụ gặp lỗi",
    ]);
    expect(chips()[0]).toHaveClass("text-danger-text");
  });

  it("5. `exit_nonzero` ma van co tep ⇒ CA chip loi LAN the tep cung luot (B-406 ⑤)", async () => {
    const es = await streaming();
    es.emit("tool_call", CALL, "1-1");
    es.emit("tool_result", { ...OK, ok: false, result: { reason: "exit_nonzero", sources: [] } }, "1-2");
    es.emit("artifact", FILE_EVENT, "1-3");

    await waitFor(() => expect(chips()[0]).toHaveTextContent("Code chạy lỗi"));
    expect(await within(reply0()).findByRole("button", { name: "Mở bao-cao.docx" })).toBeInTheDocument();
  });

  it("6. CUNG event phat lai (XRANGE) ⇒ van MOT chip, chip da xong khong quay lai 'Đang…', MOT the", async () => {
    const es = await streaming();
    es.emit("tool_call", CALL, "1-1");
    es.emit("tool_result", OK, "1-2");
    es.emit("artifact", FILE_EVENT, "1-3");
    await waitFor(() => expect(chips()[0]).toHaveTextContent("Đã chạy code"));

    es.emit("tool_call", CALL, "1-1");
    es.emit("tool_result", OK, "1-2");
    es.emit("artifact", FILE_EVENT, "1-3");

    expect(chips()).toHaveLength(1);
    expect(chips()[0]).toHaveTextContent("Đã chạy code");
    expect(within(reply0()).getAllByRole("button", { name: /^Mở / })).toHaveLength(1);
  });

  it("7. duong di co tom tat tool + artifact (B-87) ⇒ chip + the KHONG can stream; load_skill van an", async () => {
    server.path = [
      question(),
      answer({
        tools: [
          { name: "load_skill", ok: true, reason: null, sources: [] },
          { name: "run_code", ok: true, reason: null, sources: [] },
        ],
        artifacts: [FILE],
      }),
    ];
    render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    );

    expect(await within(await screen.findByRole("article", { name: "Scarlet trả lời" })).findByRole("button", { name: "Mở bao-cao.docx" })).toBeInTheDocument();
    expect(chips()).toHaveLength(1);
    expect(chips()[0]).toHaveTextContent("Đã chạy code");
    expect(FakeEventSource.all).toHaveLength(0);
    expect(document.querySelectorAll('[data-planned^="T-7"]')).toHaveLength(0);
  });
});
