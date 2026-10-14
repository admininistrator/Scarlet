/**
 * T-8.2 — trang chia se cong khai `/s/:token` (ban T-HD12).
 *
 * Mount CA bang route that (`routes`, qua `Layout`) chu khong mount
 * `ShareScreen` tran: ca 1 phai chung minh route nam NGOAI cua dang nhap —
 * `Layout` van hoi `/auth/me`, `401` o do khong duoc day ai ve `/dang-nhap`.
 *
 *   1. nguoi la (`me` ⇒ 401) ⇒ trang hien, URL van `/s/tok`
 *   2. `404 SHARE_NOT_FOUND` ⇒ man "link khong ton tai", khong man loi chung
 *   3. `content` co `<img onerror>` / `<script>` ⇒ khong phan tu nao nhu the (NQ-95)
 *   4. artifact `html` ⇒ khoi ma tinh, 0 `iframe` (Q-P8-6)
 *   5. tai lieu ⇒ chip ten, khong `<a href>` (Q-P8-4); anh ⇒ `<img src=url>`
 *   6. `<meta name="robots">` co khi o route, mat khi roi (noindex lop 2)
 *   7. B-416 ③ — message khong chu, khong tep (`cancelled` rong) ⇒ khong bong bong
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, me: vi.fn(), getShare: vi.fn() },
  };
});

import { routes } from "../../app/routes";
import { ApiError, api, type PublicMessage, type PublicShare } from "../../lib/api";
import locale from "../../locales/vi.json";

function message(patch: Partial<PublicMessage>): PublicMessage {
  return {
    role: "assistant",
    content: "",
    model_display_name: null,
    created_at: "2026-10-13T12:00:00+00:00",
    attachments: [],
    artifacts: [],
    ...patch,
  };
}

function share(messages: PublicMessage[]): PublicShare {
  return { version: 1, title: "Báo cáo", shared_at: "2026-10-13T16:46:13+00:00", messages };
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

const robots = () => document.head.querySelector('meta[name="robots"]');

beforeEach(() => {
  vi.mocked(api.me).mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "chua dang nhap"));
  vi.mocked(api.getShare).mockReset();
});

describe("T-8.2 — /s/:token", () => {
  it("1. nguoi la (session.user === null) ⇒ trang hien, URL KHONG doi sang /dang-nhap", async () => {
    vi.mocked(api.getShare).mockResolvedValue(
      share([message({ role: "user", content: "Câu hỏi" }), message({ content: "Trả lời", model_display_name: "Claude Haiku 4.5" })]),
    );

    const router = renderAt("/s/tok");

    expect(await screen.findByRole("heading", { level: 1, name: "Báo cáo" })).toBeInTheDocument();
    expect(screen.getByText("Trả lời")).toBeInTheDocument();
    expect(screen.getByText("Claude Haiku 4.5")).toBeInTheDocument();
    await waitFor(() => expect(api.me).toHaveBeenCalled());
    expect(router.state.location.pathname).toBe("/s/tok");
    expect(api.getShare).toHaveBeenCalledWith("tok");
    // Chi doc: khong o nhap, khong hang nut cua man chat.
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
  });

  it("2. 404 SHARE_NOT_FOUND ⇒ man 'link khong ton tai', khong man loi chung", async () => {
    vi.mocked(api.getShare).mockRejectedValue(new ApiError(404, "SHARE_NOT_FOUND", "khong co"));

    renderAt("/s/khong-co");

    expect(await screen.findByRole("heading", { name: locale["publicShare.notFoundTitle"] })).toBeInTheDocument();
    expect(screen.queryByText(locale["publicShare.errorTitle"])).toBeNull();
    expect(screen.getByRole("link", { name: locale["publicShare.goHome"] })).toHaveAttribute("href", "/");
  });

  it("3. content co <img onerror> / <script> ⇒ khong phan tu nao nhu the trong DOM (NQ-95)", async () => {
    vi.mocked(api.getShare).mockResolvedValue(
      share([
        message({ role: "user", content: 'Xin chào <img src=x onerror="alert(1)"> <script>alert(2)</script>' }),
        message({ content: "Đáp <img src=x onerror=alert(3)><script>window.pwned=1</script> xong" }),
      ]),
    );

    renderAt("/s/tok");
    await screen.findByText(/Xin chào/);

    const main = screen.getByRole("main");
    expect(main.querySelector("script")).toBeNull();
    expect(main.querySelector("img")).toBeNull();
    expect(main.querySelector("[onerror]")).toBeNull();
  });

  it("4. artifact html ⇒ khoi ma tinh (pre cuon duoc bang phim), 0 iframe", async () => {
    const html = '<!doctype html><script>alert("x")</script><p>Trang</p>';
    vi.mocked(api.getShare).mockResolvedValue(
      share([message({ content: "Đây", artifacts: [{ kind: "html", title: "Trang demo", language: "html", content: html }] })]),
    );

    renderAt("/s/tok");

    const region = await screen.findByRole("region", { name: "Trang demo" });
    expect(region.tagName).toBe("PRE");
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region.textContent).toBe(html);
    expect(document.querySelectorAll("iframe")).toHaveLength(0);
    expect(screen.getByRole("main").querySelector("script")).toBeNull();
  });

  it("5. tai lieu ⇒ chip ten, khong <a href>; anh ⇒ <img src=url ky>", async () => {
    vi.mocked(api.getShare).mockResolvedValue(
      share([
        message({
          role: "user",
          content: "Xem hai tệp",
          attachments: [
            { kind: "document", name: "bao-cao.pdf", mime_type: "application/pdf" },
            { kind: "image", name: "anh.png", key: "share/tok/1.png", width: 64, height: 48, url: "/scarlet/share/tok/1.png?X-Amz=1" },
          ],
        }),
      ]),
    );

    renderAt("/s/tok");

    const chip = (await screen.findByText("bao-cao.pdf")).closest("li") as HTMLElement;
    expect(within(chip).getByText(locale["publicShare.fileNameOnly"])).toBeInTheDocument();
    expect(chip.querySelector("a")).toBeNull();
    expect(chip.closest("a")).toBeNull();
    expect(screen.getByRole("img", { name: "anh.png" })).toHaveAttribute("src", "/scarlet/share/tok/1.png?X-Amz=1");
  });

  it("6. <meta name=robots noindex> co khi o route, mat khi roi", async () => {
    vi.mocked(api.getShare).mockResolvedValue(share([message({ content: "Một" })]));

    const router = renderAt("/s/tok");
    await screen.findByText("Một");

    expect(robots()).toHaveAttribute("content", "noindex, nofollow");

    await router.navigate("/dang-nhap");

    await waitFor(() => expect(robots()).toBeNull());
  });

  it("7. B-416 ③ — message rong (khong chu, khong tep) ⇒ khong ve bong bong rong", async () => {
    vi.mocked(api.getShare).mockResolvedValue(
      share([message({ role: "user", content: "Hỏi" }), message({ content: "" }), message({ role: "user", content: "Hỏi lại" })]),
    );

    renderAt("/s/tok");
    await screen.findByText("Hỏi lại");

    expect(document.querySelectorAll("[data-share-message]")).toHaveLength(2);
    expect(document.querySelector('[data-share-message="assistant"]')).toBeNull();
  });
});
