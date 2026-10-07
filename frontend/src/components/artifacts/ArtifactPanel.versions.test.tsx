/**
 * Tab phien ban, so sanh, sua trong panel — T-5.9 (DoD dong 1).
 *
 * Render THANG `ArtifactPanel`, `api` THAT; chi `fetch` bi thay bang mot server
 * gia de dem request va doc header `Idempotency-Key` (lo `ArtifactFlow.test.tsx`).
 * `kind = code` ⇒ khong iframe (khung da co test rieng).
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ArtifactOut, ArtifactVersion, PathArtifact } from "../../lib/api";
import { ArtifactPanel } from "./ArtifactPanel";
import { DIFF_MAX_LINES } from "./artifactUtils";

const LINEAGE = "art-v1";

type Row = { id: string; version: number; origin: string; created_at: string; content: string };

/** Ba phien ban + mot so ho (v2 cua message da xoa). Server tra theo `created_at`, KHONG theo `version`. */
let rows: Row[];
let postReplies: (() => Response)[];
let created: Row[];
/** Giu `GET /artifacts/{id}` lai toi khi test mo (ca 11). */
let gate: Promise<void>;

function reply(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

const meta = (r: Row): ArtifactVersion => ({
  id: r.id,
  version: r.version,
  kind: "code",
  language: "python",
  title: "Bang gia",
  origin: r.origin,
  message_id: "m1",
  created_at: r.created_at,
});

const fakeFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const method = init?.method ?? "GET";
  const path = String(input).replace(/^\/api\/v1/, "");
  const versions = /^\/artifacts\/([^/]+)\/versions$/.exec(path);
  if (versions && method === "GET") {
    // Thu tu `created_at` — v4 (ban sua) tao TRUOC v3 o nhanh khac.
    const items = [...rows].sort((a, b) => a.created_at.localeCompare(b.created_at)).map(meta);
    return reply(200, { items });
  }
  if (versions && method === "POST") {
    const next = postReplies.shift();
    if (next) {
      return next();
    }
    const { content } = JSON.parse(String(init?.body)) as { content: string };
    const row: Row = {
      id: `art-new-${created.length + 1}`,
      version: Math.max(...rows.map((r) => r.version)) + 1,
      origin: "user",
      created_at: "2026-10-07T09:00:00Z",
      content,
    };
    created.push(row);
    rows.push(row);
    return reply(201, meta(row));
  }
  const one = /^\/artifacts\/([^/]+)$/.exec(path);
  const row = one && rows.find((r) => r.id === one[1]);
  if (row && method === "GET") {
    await gate;
    const out: ArtifactOut = {
      ...meta(row),
      lineage_id: LINEAGE,
      content: row.content,
      conversation_id: "c1",
    };
    return reply(200, out);
  }
  return reply(404, { error: { code: "NOT_FOUND", message: `${method} ${path}`, details: null } });
});

const calls = (method: string, suffix: string) =>
  fakeFetch.mock.calls.filter(([input, init]) => (init?.method ?? "GET") === method && String(input).endsWith(suffix));
const posts = () => calls("POST", "/versions");
const keyOf = (i: number) => (posts()[i][1]?.headers as Record<string, string>)["Idempotency-Key"];

beforeEach(() => {
  rows = [
    { id: "art-v1", version: 1, origin: "model", created_at: "2026-10-07T08:00:00Z", content: "a\nb\nc\n" },
    { id: "art-v4", version: 4, origin: "user", created_at: "2026-10-07T08:01:00Z", content: "a\nB\nc\n" },
    { id: "art-v3", version: 3, origin: "model", created_at: "2026-10-07T08:02:00Z", content: "a\nb\nc\nd\n" },
  ];
  postReplies = [];
  created = [];
  gate = Promise.resolve();
  fakeFetch.mockClear();
  vi.stubGlobal("fetch", fakeFetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Panel mo voi v3 (phien ban model vua viet lai, co `content` tu duong di). */
async function openAt(id = "art-v3") {
  const row = rows.find((r) => r.id === id) as Row;
  const opened: PathArtifact = {
    id: row.id,
    kind: "code",
    language: "python",
    title: "Bang gia",
    version: row.version,
    content: row.content,
  };
  render(<ArtifactPanel open artifact={opened} onClose={() => {}} />);
  await waitFor(() => expect(tabs()).toHaveLength(rows.length));
}

const panel = () => document.getElementById("artifact-panel") as HTMLElement;
const tabs = () => within(panel()).queryAllByRole("tab");
const tabText = () => tabs().map((tab) => tab.textContent);
const selectedTab = () => within(panel()).getByRole("tab", { selected: true });
const source = () => panel().querySelector("pre.code-lines")?.textContent;

describe("tab phien ban", () => {
  it("1. thu tu theo `version` du server tra theo `created_at`; so ho ⇒ dau '…' + cau giai thich; nhan 'bạn sửa' chi o origin user", async () => {
    await openAt();
    expect(tabText()).toEqual(["v1", "v3", "v4bạn sửa"]);
    expect(selectedTab()).toHaveTextContent("v3");
    const list = within(panel()).getByRole("tablist", { name: "Phiên bản" });
    // v1 → v3 ho mot so; v3 → v4 lien.
    expect(list.querySelectorAll('[aria-hidden="true"].w-5')).toHaveLength(1);
    expect(list).toHaveAccessibleDescription(/tin nhắn đã xoá/);
  });

  it("2. chon tab ⇒ noi dung doi; MOT `GET /artifacts/{id}` moi phien ban, ke ca khi bam lai / bam dup", async () => {
    const user = userEvent.setup();
    await openAt();
    expect(source()).toBe("a\nb\nc\nd");

    const v1 = tabs()[0];
    v1.click();
    v1.click(); // cung nhip: van mot request
    await waitFor(() => expect(source()).toBe("a\nb\nc"));
    expect(selectedTab()).toHaveTextContent("v1");

    await user.click(tabs()[2]);
    await waitFor(() => expect(source()).toBe("a\nB\nc"));
    await user.click(tabs()[0]);
    await user.click(tabs()[1]); // v3 = phien ban da mo, da co `content`
    await waitFor(() => expect(source()).toBe("a\nb\nc\nd"));
    await user.click(tabs()[0]);
    expect(source()).toBe("a\nb\nc");

    expect(calls("GET", "/artifacts/art-v1")).toHaveLength(1);
    expect(calls("GET", "/artifacts/art-v4")).toHaveLength(1);
    expect(calls("GET", "/artifacts/art-v3")).toHaveLength(0);
    expect(calls("GET", "/versions")).toHaveLength(1);
  });

  it("3. mui ten trai / phai, Home / End doi tab va tieu diem; o mep thi dung", async () => {
    const user = userEvent.setup();
    await openAt();
    selectedTab().focus();
    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(selectedTab()).toHaveTextContent("v4"));
    expect(document.activeElement).toBe(selectedTab());
    await user.keyboard("{ArrowRight}");
    expect(selectedTab()).toHaveTextContent("v4");
    await user.keyboard("{Home}");
    await waitFor(() => expect(selectedTab()).toHaveTextContent("v1"));
    await user.keyboard("{ArrowLeft}");
    expect(selectedTab()).toHaveTextContent("v1");
    await user.keyboard("{End}");
    await user.keyboard("{ArrowLeft}");
    await waitFor(() => expect(selectedTab()).toHaveTextContent("v3"));
    expect(tabs().filter((tab) => tab.tabIndex === 0)).toEqual([selectedTab()]);
  });
});

describe("tab va noi dung khong lech", () => {
  it("11. tab chua nap ⇒ tab cu VAN chon va noi dung cu hien toi khi `GET` ve; bam v1 roi v4 ⇒ chi v4 hien (do tren Chrome)", async () => {
    const user = userEvent.setup();
    await openAt();
    let open = () => {};
    gate = new Promise((resolve) => (open = resolve));
    await user.click(tabs()[0]);
    await user.click(tabs()[2]);
    expect(selectedTab()).toHaveTextContent("v3");
    expect(source()).toBe("a\nb\nc\nd");
    await act(async () => open());
    await waitFor(() => expect(selectedTab()).toHaveTextContent("v4"));
    expect(source()).toBe("a\nB\nc");
  });
});

describe("so sanh", () => {
  it("4. v3 ↔ v4 trong panel: +/− dung so, dong doi to nen, Xong ⇒ ve tab", async () => {
    const user = userEvent.setup();
    await openAt("art-v4");
    await user.click(within(panel()).getByRole("button", { name: /So sánh/ }));
    // Mac dinh: phien ban lien truoc ⇒ phien ban dang xem.
    expect(within(panel()).getByLabelText("Từ phiên bản")).toHaveValue("art-v3");
    expect(within(panel()).getByLabelText("Đến phiên bản")).toHaveValue("art-v4");
    await waitFor(() => expect(panel().querySelector('[data-diff="added"]')).toHaveTextContent("+1"));
    expect(panel().querySelector('[data-diff="removed"]')).toHaveTextContent("−2");
    expect([...panel().querySelectorAll("[data-op]")].map((el) => el.getAttribute("data-op"))).toEqual([
      "same",
      "del",
      "add",
      "same",
      "del",
    ]);

    fireEvent.change(within(panel()).getByLabelText("Từ phiên bản"), { target: { value: "art-v4" } });
    expect(within(panel()).getByText("Hai phiên bản giống hệt nhau.")).toBeInTheDocument();
    await user.click(within(panel()).getByRole("button", { name: "Xong" }));
    expect(selectedTab()).toHaveTextContent("v4");
  });

  it("5. vuot tran so dong ⇒ thong bao 'qua dai de so', khong bang khac biet", async () => {
    const user = userEvent.setup();
    const big = (tag: string) => Array.from({ length: DIFF_MAX_LINES + 1 }, (_, i) => `${tag}${i}`).join("\n");
    rows[0].content = big("x");
    rows[2].content = big("y");
    await openAt();
    await user.click(within(panel()).getByRole("button", { name: /So sánh/ }));
    await waitFor(() => expect(panel().querySelector('[data-diff="too-long"]')).not.toBeNull());
    expect(panel().querySelector('[data-diff="too-long"]')).toHaveTextContent("quá dài để so");
    expect(panel().querySelector("[data-op]")).toBeNull();
  });
});

describe("sua ⇒ phien ban moi", () => {
  const editor = () => within(panel()).getByRole("textbox", { name: "Nội dung artifact" });
  const saveButton = () => within(panel()).getByRole("button", { name: "Lưu thành phiên bản mới" });

  it("6. Luu ⇒ MOT `POST` co `Idempotency-Key`, than = ban sua; xong ⇒ tab moi duoc chon, 'bạn sửa', noi dung = ban sua, khong GET them", async () => {
    const user = userEvent.setup();
    await openAt();
    await user.click(within(panel()).getByRole("button", { name: "Sửa" }));
    expect(editor()).toHaveValue("a\nb\nc\nd\n");
    expect(panel()).toHaveTextContent("Bản sửa được gửi cho model ở câu hỏi kế tiếp.");
    expect(saveButton()).toBeDisabled(); // chua doi gi
    await user.type(editor(), "e");
    await user.click(saveButton());

    await waitFor(() => expect(selectedTab()).toHaveTextContent("v5bạn sửa"));
    expect(posts()).toHaveLength(1);
    expect(keyOf(0)).toMatch(/\S{8,}/);
    expect(JSON.parse(String(posts()[0][1]?.body))).toEqual({ content: "a\nb\nc\nd\ne" });
    expect(posts()[0][0]).toBe("/api/v1/artifacts/art-v3/versions");
    expect(tabText()).toEqual(["v1", "v3", "v4bạn sửa", "v5bạn sửa"]);
    expect(source()).toBe("a\nb\nc\nd\ne");
    expect(calls("GET", `/artifacts/${created[0].id}`)).toHaveLength(0);
  });

  it("7. loi ⇒ giu o sua + bao loi; Luu lai mang CUNG khoa; bam dup cung nhip ⇒ van mot POST", async () => {
    const user = userEvent.setup();
    postReplies = [() => reply(503, { error: { code: "UPSTREAM_ERROR", message: "tam hong", details: null } })];
    await openAt();
    await user.click(within(panel()).getByRole("button", { name: "Sửa" }));
    await user.type(editor(), "e");
    act(() => {
      saveButton().click();
      saveButton().click();
    });
    await waitFor(() => expect(within(panel()).getByRole("alert")).toHaveTextContent("UPSTREAM_ERROR"));
    expect(posts()).toHaveLength(1);
    expect(editor()).toHaveValue("a\nb\nc\nd\ne");

    await user.click(saveButton());
    await waitFor(() => expect(selectedTab()).toHaveTextContent("v5"));
    expect(posts()).toHaveLength(2);
    expect(keyOf(1)).toBe(keyOf(0));
  });

  it("8. sua noi dung roi Luu sau loi ⇒ khoa MOI (server khong bam than)", async () => {
    const user = userEvent.setup();
    postReplies = [() => reply(503, { error: { code: "UPSTREAM_ERROR", message: "tam hong", details: null } })];
    await openAt();
    await user.click(within(panel()).getByRole("button", { name: "Sửa" }));
    await user.type(editor(), "e");
    await user.click(saveButton());
    await waitFor(() => expect(within(panel()).getByRole("alert")).toBeInTheDocument());
    await user.type(editor(), "f");
    await user.click(saveButton());
    await waitFor(() => expect(selectedTab()).toHaveTextContent("v5"));
    expect(posts()).toHaveLength(2);
    expect(keyOf(1)).not.toBe(keyOf(0));
    expect(JSON.parse(String(posts()[1][1]?.body))).toEqual({ content: "a\nb\nc\nd\nef" });
  });

  it("9. Huy ⇒ 0 request, ve tab cu; mo Sua lan nua ⇒ o sua tu phien ban dang xem", async () => {
    const user = userEvent.setup();
    await openAt();
    const before = fakeFetch.mock.calls.length;
    await user.click(within(panel()).getByRole("button", { name: "Sửa" }));
    await user.type(editor(), "zzz");
    await user.click(within(panel()).getByRole("button", { name: "Huỷ" }));
    expect(fakeFetch.mock.calls.length).toBe(before);
    expect(selectedTab()).toHaveTextContent("v3");
    await user.click(within(panel()).getByRole("button", { name: "Sửa" }));
    expect(editor()).toHaveValue("a\nb\nc\nd\n");
  });

  it("10. `/versions` hong ⇒ van mot tab cua phien ban dang mo, noi dung hien", async () => {
    fakeFetch.mockImplementationOnce(async () => reply(500, { error: { code: "INTERNAL", message: "x", details: null } }));
    render(
      <ArtifactPanel
        open
        artifact={{ id: "art-v3", kind: "code", language: "python", title: "Bang gia", version: 3, content: "q\n" }}
        onClose={() => {}}
      />,
    );
    await waitFor(() => expect(calls("GET", "/versions")).toHaveLength(1));
    expect(tabText()).toEqual(["v3"]);
    expect(source()).toBe("q");
    expect(screen.queryByRole("button", { name: /So sánh/ })).toBeNull();
  });
});
