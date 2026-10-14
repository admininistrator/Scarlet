/**
 * T-8.3 — "Chat tiep" tren `/s/:token` + `next` cua `/dang-nhap`.
 *
 *   1. `safeNext`: `//evil`, `https://evil`, `/\evil`, `javascript:`, ky tu dieu khien ⇒ bo (ve `/`)
 *   2. `next=/s/abc?fork=1` ⇒ giu
 *   3. co phien ⇒ dung MOT `POST` roi mo hoi thoai moi
 *   4. khong phien ⇒ `/dang-nhap?next=/s/<token>?fork=1`
 *   5. dang nhap tu link ⇒ ve trang share ⇒ tu fork MOT lan (StrictMode — B-260), go `fork=1`
 *   6. `403 PENDING_APPROVAL` ⇒ cau theo ma, khong ve dang nhap
 *
 * Bang route rut gon (Layout + ba duong): `/` that mount ca man chat va mot
 * chuc API khong lien quan.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, me: vi.fn(), login: vi.fn(), getShare: vi.fn(), forkShare: vi.fn() },
  };
});

import { Layout } from "../../app/Layout";
import { LoginRoute, safeNext } from "../../app/LoginRoute";
import { PATHS } from "../../app/paths";
import { ApiError, api, type ProfileOut, type PublicShare } from "../../lib/api";
import locale from "../../locales/vi.json";
import { ShareScreen } from "./ShareScreen";

const ME = {
  id: "22222222-2222-4222-8222-222222222222",
  email: "b@scarlet.test",
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "free",
} as unknown as ProfileOut;

const SHARE: PublicShare = {
  version: 1,
  title: "Báo cáo",
  shared_at: "2026-10-14T08:00:00+00:00",
  messages: [
    {
      role: "user",
      content: "Câu hỏi",
      model_display_name: null,
      created_at: "2026-10-14T08:00:00+00:00",
      attachments: [],
      artifacts: [],
    },
  ],
};

function renderAt(path: string, strict = false) {
  const router = createMemoryRouter(
    [
      {
        element: <Layout />,
        children: [
          { path: PATHS.home, element: <p>man chat</p> },
          { path: PATHS.login, element: <LoginRoute /> },
          { path: PATHS.share, element: <ShareScreen /> },
        ],
      },
    ],
    { initialEntries: [path] },
  );
  const tree = <RouterProvider router={router} />;
  render(strict ? <StrictMode>{tree}</StrictMode> : tree);
  return router;
}

const signedOut = () => vi.mocked(api.me).mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "chua dang nhap"));

beforeEach(() => {
  sessionStorage.clear();
  vi.mocked(api.me).mockReset();
  vi.mocked(api.login).mockReset();
  vi.mocked(api.forkShare).mockReset();
  vi.mocked(api.getShare).mockReset().mockResolvedValue(SHARE);
});

describe("T-8.3 — safeNext", () => {
  it.each(["//evil.example", "https://evil.example", "/\\evil.example", "javascript:alert(1)", "/\t/evil.example"])(
    "1. %j ⇒ bo qua, ve /",
    (next) => {
      expect(safeNext(next) ?? PATHS.home).toBe("/");
    },
  );

  it("2. /s/abc?fork=1 ⇒ giu", () => {
    expect(safeNext("/s/abc?fork=1")).toBe("/s/abc?fork=1");
  });
});

describe("T-8.3 — Chat tiep", () => {
  it("3. co phien ⇒ dung MOT POST roi mo hoi thoai moi", async () => {
    const user = userEvent.setup();
    vi.mocked(api.me).mockResolvedValue(ME);
    vi.mocked(api.forkShare).mockResolvedValue({ conversation_id: "conv-1" });
    const router = renderAt("/s/tok");

    await screen.findByRole("heading", { level: 1, name: "Báo cáo" });
    await waitFor(() => expect(api.me).toHaveBeenCalled());
    const [header] = screen.getAllByRole("button", { name: locale["publicShare.continue"] });
    await user.click(header);

    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
    expect(router.state.location.search).toBe("?c=conv-1");
    expect(api.forkShare).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.forkShare).mock.calls[0][0]).toBe("tok");
    expect(sessionStorage.length).toBe(0);
  });

  it("4. khong phien ⇒ /dang-nhap?next=/s/<token>?fork=1, khong POST", async () => {
    const user = userEvent.setup();
    signedOut();
    const router = renderAt("/s/tok");

    await screen.findByRole("heading", { level: 1, name: "Báo cáo" });
    await waitFor(() => expect(api.me).toHaveBeenCalled());
    await user.click(screen.getAllByRole("button", { name: locale["publicShare.continue"] })[1]);

    await waitFor(() => expect(router.state.location.pathname).toBe(PATHS.login));
    expect(new URLSearchParams(router.state.location.search).get("next")).toBe("/s/tok?fork=1");
    expect(api.forkShare).not.toHaveBeenCalled();
  });

  it("5. dang nhap tu link ⇒ ve share ⇒ tu fork MOT lan duoi StrictMode, go fork=1", async () => {
    const user = userEvent.setup();
    signedOut();
    vi.mocked(api.login).mockResolvedValue(ME);
    let resolveFork: (v: { conversation_id: string }) => void = () => {};
    vi.mocked(api.forkShare).mockReturnValue(new Promise((resolve) => (resolveFork = resolve)));
    const router = renderAt(`${PATHS.login}?next=${encodeURIComponent("/s/tok?fork=1")}`, true);

    await user.type(await screen.findByLabelText("Email"), "b@scarlet.test");
    await user.type(screen.getByLabelText("Mật khẩu"), "mat-khau-du-dai-123");
    vi.mocked(api.me).mockResolvedValue(ME);
    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    await waitFor(() => expect(api.forkShare).toHaveBeenCalled());
    expect(router.state.location.pathname).toBe("/s/tok");
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(await screen.findAllByRole("button", { name: locale["publicShare.copying"] })).toHaveLength(2);
    resolveFork({ conversation_id: "conv-2" });

    await waitFor(() => expect(router.state.location.search).toBe("?c=conv-2"));
    expect(api.forkShare).toHaveBeenCalledTimes(1);
  });

  it("6. 403 PENDING_APPROVAL ⇒ cau theo ma, o lai trang share", async () => {
    const user = userEvent.setup();
    vi.mocked(api.me).mockResolvedValue({ ...ME, status: "pending_approval" });
    vi.mocked(api.forkShare).mockRejectedValue(new ApiError(403, "PENDING_APPROVAL", "cho duyet"));
    const router = renderAt("/s/tok");

    await screen.findByRole("heading", { level: 1, name: "Báo cáo" });
    await waitFor(() => expect(api.me).toHaveBeenCalled());
    await user.click(screen.getAllByRole("button", { name: locale["publicShare.continue"] })[0]);

    expect(await screen.findByRole("alert")).toHaveTextContent(locale["publicShare.continuePendingApproval"]);
    expect(router.state.location.pathname).toBe("/s/tok");
    expect(api.forkShare).toHaveBeenCalledTimes(1);
    expect(sessionStorage.length).toBe(0);
  });
});
