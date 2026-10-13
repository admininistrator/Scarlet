/**
 * Panel chon skill — T-7.9, ban T-HD11.
 *
 * KH tham chieu: UC-09 dong 1, 3 · §18.3 · tasks.md T-7.5 (`PUT …/toggle`
 * nhan `{"enabled": bool}`), T-7.8 (`can_execute_skills`), T-7.8b (bon skill
 * dung san bat mac dinh).
 *
 * `api` THAT; chi `fetch` (bo dinh tuyen gia) bi thay.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Skill } from "../../lib/api";
import { SkillPicker } from "./SkillPicker";

const skill = (name: string, display: string, p: Partial<Skill> = {}): Skill => ({
  name,
  display_name: display,
  description: `Create ${display} files.`,
  requires_execution: true,
  enabled: true,
  ...p,
});

/** Response that cua user moi sau T-7.8b: bon skill dung san, deu can chay code, deu bat. */
const BUILT_IN = [skill("docx", "Word (.docx)"), skill("pdf", "PDF"), skill("pptx", "PowerPoint (.pptx)"), skill("xlsx", "Excel (.xlsx)")];

const server = { items: [] as Skill[], putStatus: 200, getStatus: 200 };

function reply(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, statusText: "", json: () => Promise.resolve(body) } as unknown as Response;
}

const fakeFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const method = init?.method ?? "GET";
  const path = String(input).replace(/^\/api\/v1/, "");
  if (method === "GET" && path === "/skills") {
    return server.getStatus === 200 ? reply(200, { items: server.items }) : reply(server.getStatus, {});
  }
  const toggle = /^\/skills\/([^/]+)\/toggle$/.exec(path);
  if (method === "PUT" && toggle !== null) {
    if (server.putStatus !== 200) {
      const code = server.putStatus === 404 ? "SKILL_NOT_FOUND" : "INTERNAL";
      return reply(server.putStatus, { error: { code, message: code, details: null } });
    }
    const { enabled } = JSON.parse(String(init?.body)) as { enabled: boolean };
    server.items = server.items.map((s) => (s.name === toggle[1] ? { ...s, enabled } : s));
    return reply(200, server.items.find((s) => s.name === toggle[1]));
  }
  return reply(404, { error: { code: "NOT_FOUND", message: path, details: null } });
});

const puts = () => fakeFetch.mock.calls.filter(([, init]) => init?.method === "PUT");

function Host({ canExecute }: { canExecute: boolean }) {
  const frame = useRef<HTMLDivElement>(null);
  return (
    <div ref={frame}>
      <SkillPicker anchorRef={frame} canExecuteSkills={canExecute} />
    </div>
  );
}

async function openPanel(canExecute = false) {
  const user = userEvent.setup();
  render(<Host canExecute={canExecute} />);
  // So tren nut ⚡ co NGAY khi o nhap mount, chua mo panel (ban ve 1a).
  const zap = await screen.findByRole("button", { name: /^Chọn skill \d+ đang bật$/ });
  await user.click(zap);
  const panel = await screen.findByRole("dialog", { name: "Skill" });
  await within(panel).findByRole("list", { name: "Danh sách skill" });
  return { user, zap, panel };
}

beforeEach(() => {
  server.items = BUILT_IN;
  server.putStatus = 200;
  server.getStatus = 200;
  fakeFetch.mockClear();
  vi.stubGlobal("fetch", fakeFetch);
});

describe("panel skill (T-7.9, ban T-HD11)", () => {
  it("1. liet skill tu `GET /skills`: bon skill dung san BAT voi user moi, nut ⚡ 'Chọn skill 4 đang bật'", async () => {
    const { zap, panel } = await openPanel(true);

    expect(zap).toHaveAccessibleName("Chọn skill 4 đang bật");
    const switches = within(panel).getAllByRole("switch");
    expect(switches.map((s) => s.getAttribute("aria-checked"))).toEqual(["true", "true", "true", "true"]);
    expect(within(panel).getByRole("switch", { name: "Word (.docx)" })).toBeInTheDocument();
    expect(panel).toHaveTextContent("4đang bật");
    // T-7.8b: doc tep khong can skill ⇒ panel khong goi y bat skill de doc tep.
    expect(panel).not.toHaveTextContent(/đọc tệp/i);
  });

  it("2. tat ⇒ `PUT /skills/docx/toggle {\"enabled\": false}` (dat, khong lat); num va so tren nut doi", async () => {
    const { user, zap, panel } = await openPanel(true);

    await user.click(within(panel).getByRole("switch", { name: "Word (.docx)" }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    const [input, init] = puts()[0];
    expect(String(input)).toBe("/api/v1/skills/docx/toggle");
    expect(JSON.parse(String(init?.body))).toEqual({ enabled: false });
    await waitFor(() => expect(within(panel).getByRole("switch", { name: "Word (.docx)" })).toHaveAttribute("aria-checked", "false"));
    expect(zap).toHaveAccessibleName("Chọn skill 3 đang bật");
  });

  it("3. PUT 500 ⇒ num ve cho cu + cau loi; PUT 404 SKILL_NOT_FOUND ⇒ cong tac khoa + 'vừa bị gỡ'", async () => {
    const { user, panel } = await openPanel(true);

    server.putStatus = 500;
    await user.click(within(panel).getByRole("switch", { name: "PDF" }));
    expect(await within(panel).findByText("Chưa lưu được. Hãy thử lại.")).toBeInTheDocument();
    expect(within(panel).getByRole("switch", { name: "PDF" })).toHaveAttribute("aria-checked", "true");

    server.putStatus = 404;
    await user.click(within(panel).getByRole("switch", { name: "Excel (.xlsx)" }));
    expect(await within(panel).findByText("Skill này vừa bị gỡ khỏi máy chủ.")).toBeInTheDocument();
    expect(within(panel).getByRole("switch", { name: "Excel (.xlsx)" })).toBeDisabled();
  });

  it("4. user KHONG `can_execute_skills` ⇒ skill can chay mang nhan 'Chưa được chạy code' + MOT dong giai thich; cong tac van bat duoc", async () => {
    server.items = [...BUILT_IN, skill("sql-review", "Rà soát SQL", { requires_execution: false, enabled: false })];
    const { user, panel } = await openPanel(false);

    expect(within(panel).getAllByText("Chưa được chạy code")).toHaveLength(4);
    const hints = within(panel).getAllByText(/skill chỉ dùng được phần hướng dẫn/);
    expect(hints).toHaveLength(1);
    const docx = within(panel).getByRole("switch", { name: "Word (.docx)" });
    expect(docx.getAttribute("aria-describedby")).toContain(hints[0].id);
    // Skill khong can chay code: khong nhan, khong noi toi dong giai thich.
    expect(within(panel).getByRole("switch", { name: "Rà soát SQL" }).getAttribute("aria-describedby")).not.toContain(hints[0].id);
    expect(docx).toBeEnabled();

    await user.click(docx);
    await waitFor(() => expect(puts()).toHaveLength(1));
  });

  it("5. user CO quyen ⇒ nhan 'Chạy code', khong dong canh bao", async () => {
    const { panel } = await openPanel(true);

    expect(within(panel).getAllByText("Chạy code")).toHaveLength(4);
    expect(within(panel).queryByText("Chưa được chạy code")).toBeNull();
    expect(within(panel).queryByText(/skill chỉ dùng được phần hướng dẫn/)).toBeNull();
  });

  it("6. `GET /skills` hong ⇒ nut ⚡ khong so; panel bao loi + Thử lại nap lai duoc", async () => {
    server.getStatus = 503;
    const user = userEvent.setup();
    render(<Host canExecute />);
    const zap = screen.getByRole("button", { name: "Chọn skill" });
    await waitFor(() => expect(fakeFetch).toHaveBeenCalled());

    await user.click(zap);
    const panel = await screen.findByRole("dialog", { name: "Skill" });
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Không nạp được danh sách skill.");

    server.getStatus = 200;
    await user.click(within(panel).getByRole("button", { name: "Thử lại" }));
    expect(await within(panel).findAllByRole("switch")).toHaveLength(4);
    expect(zap).toHaveAccessibleName("Chọn skill 4 đang bật");
  });

  it("7. < 640 px ⇒ sheet (dialog) co nut dong 44", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({ matches: true, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    );
    const { user, panel } = await openPanel(true);

    await user.click(within(panel).getByRole("button", { name: "Đóng danh sách skill" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
