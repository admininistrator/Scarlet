/**
 * Sau man hinh auth cua T-3.1b — DoD dong 2.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOI CA O DAY LA MOT DONG CUA UC-01 HOAC MOT CAM BAY CUA TASK          ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Khong co ca nao kiem "component co render khong". Danh sach:
 *
 *  1. UC-01 dong 1 — email da ton tai cho ra man hinh GIONG HET ca thanh cong
 *  2. Cam bay ② — `VITE_TURNSTILE_SITE_KEY` rong thi widget TU AN, va form
 *     van gui duoc voi `turnstile_token: null`
 *  3. Cam bay Turnstile cua T-2.6 — `reset()` sau MOI response loi; khong lam
 *     vay thi lan gui thu hai chac chan `400` va trieu chung doc thanh
 *     "captcha hong" chu khong phai "mat khau qua yeu"
 *  4. UC-01 dong 4 — link het han ra nut "gui lai", KHONG phai man loi
 *  5. Cam bay ③ — `resend-verification` bi `429` phai NOI RA han muc
 *  6. UC-01 dong 5 — link bam lan hai ve thang `/dang-nhap`, khong phai loi
 *  7. DoD dong 2 — `/cho-duyet` hien khi `pending_approval`, bien mat sau khi
 *     duoc duyet
 *  8. §11.1 — `suspended` ra man giai thich, KHONG roi ve man chat
 *  9. T-3.1c — chua dang nhap thi KHONG vao duoc man chat nua
 *
 * ── Vi sao `./Turnstile` bi thay bang mot ban gia ─────────────────────────
 *
 * `docker-compose.yml` bom `VITE_TURNSTILE_SITE_KEY` vao container `web`, va
 * vitest chay TRONG container ay — nen `turnstileEnabled()` tra `true` ngay
 * trong test, va widget that se di nap mot script tu challenges.cloudflare.com
 * ma jsdom khong bao gio tai. Mot bo test phu thuoc vao gia tri mot bien moi
 * truong (va vao mang) thi xanh hay do khong con noi gi ve ma nguon.
 *
 * Ban gia lam dung ba viec cua ban that ma cac form nay dua vao: co bat
 * khong, cap token khi nguoi dung hoan tat, va `reset()` qua `ref`. Nho vay
 * CA HAI nhanh cua Cam bay ② deu do duoc trong cung mot file.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

const ts = vi.hoisted(() => ({
  /** `false` mo phong `VITE_TURNSTILE_SITE_KEY` rong — Cam bay ②. */
  enabled: true,
  token: "token-cloudflare-gia",
  buttonLabel: "hoan tat o xac minh",
  reset: vi.fn(),
}));

vi.mock("./Turnstile", async () => {
  const { useImperativeHandle } = await vi.importActual<typeof import("react")>("react");
  return {
    turnstileEnabled: () => ts.enabled,
    Turnstile: ({
      onToken,
      ref,
    }: {
      onToken: (token: string | null) => void;
      ref?: React.Ref<{ reset: () => void }>;
    }) => {
      useImperativeHandle(
        ref,
        () => ({
          reset: () => {
            ts.reset();
            onToken(null);
          },
        }),
        [onToken],
      );
      if (!ts.enabled) {
        return null;
      }
      return (
        <button type="button" onClick={() => onToken(ts.token)}>
          {ts.buttonLabel}
        </button>
      );
    },
  };
});

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      login: vi.fn(),
      logout: vi.fn(),
      listModels: vi.fn(),
      listConversations: vi.fn(),
      register: vi.fn(),
      verifyEmail: vi.fn(),
      resendVerification: vi.fn(),
      forgotPassword: vi.fn(),
      resetPassword: vi.fn(),
    },
  };
});

import { PATHS } from "../../app/paths";
import { routes } from "../../app/routes";
import { ApiError, api, type ProfileOut, type UserStatus } from "../../lib/api";

const USER: ProfileOut = {
  id: "33333333-3333-4333-8333-333333333333",
  email: "nguoi-moi@scarlet.test",
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "free",
  // Ba truong cua `ProfileOut` — chi `GET /auth/me` tra chung (B-213, T-3.4).
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
  web_searches_per_day: 50,
  web_searches_used: 0,
};

const PASSWORD = "mot-mat-khau-du-manh-123";
const ANTI_ENUMERATION_REPLY = { message: "cau co dinh cua §11.5" };

/**
 * Nap dung mang `routes` cua san pham, trong `StrictMode` — cung ly le
 * `routes.test.tsx`, cong mot ly le rieng cua file nay.
 *
 * Sau man hinh nay doc `?token=` bang `useSearchParams` va dieu huong bang
 * `useNavigate`, nen chung khong ton tai ngoai mot router. Dung bang route
 * THAT chu khong mot bang rieng cho test: mot `element` gan nham o
 * `routes.tsx` la loi khong bao gio lo dien neu test tu dung lay canh minh.
 *
 * ── `StrictMode` o day KHONG phai mot lop trang tri ───────────────────────
 *
 * `main.tsx` boc app trong `<StrictMode>`; `render()` cua testing-library thi
 * khong. Khoang lech ay giau dung mot lop bug — effect chay hai lan — va no
 * da can that trong chinh task nay: `VerifyEmailScreen` tung dung MAI o "Dang
 * xac thuc email..." tren Chrome trong khi ca 20 ca o day van xanh, vi co
 * `mounted` bi cleanup cua lan chay thu nhat tat di con lan thu hai thi bi
 * `daGoi` chan truoc khi kip dung mot co moi. Bo test chi bat duoc no khi no
 * chay dung cai cay ma trinh duyet chay.
 */
function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(
    <StrictMode>
      <RouterProvider router={router} />
    </StrictMode>,
  );
}

/**
 * Vung noi dung, khong ke header.
 *
 * `Layout` co san mot lien ket "Đăng nhập" o header khi chua co phien, nen
 * mot `getByRole("link", { name: "Đăng nhập" })` khong pham vi se tim thay
 * hai phan tu va bao mot loi noi ve SO LUONG chu khong ve thu dang duoc kiem.
 * T-S.16 bo header khoi sau man auth, nhung chu Scarlet (ve trang chu) va lien
 * ket duoi the van nam ngoai `main` — pham vi van la dung pham vi.
 */
function view() {
  return within(screen.getByRole("main"));
}

function error(status: number, code: string): ApiError {
  return new ApiError(status, code, "thong diep cua backend, khong phai cua man hinh");
}

beforeEach(() => {
  ts.enabled = true;
  vi.mocked(api.me).mockRejectedValue(error(401, "UNAUTHENTICATED"));
  vi.mocked(api.listModels).mockResolvedValue([]);
  vi.mocked(api.listConversations).mockResolvedValue({ items: [], next_cursor: null, truncated: false });
});

// ───────────────────── /dang-ky — UC-01 dong 1, B-185 ───────────────────────

describe("/dang-ky", () => {
  async function fillIn(user: ReturnType<typeof userEvent.setup>, email: string) {
    await user.type(await screen.findByLabelText("Email"), email);
    await user.type(screen.getByLabelText("Mật khẩu"), PASSWORD);
  }

  it("mount widget Turnstile va gui kem token cua no (B-185)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.register).mockResolvedValue(ANTI_ENUMERATION_REPLY);
    renderAt(PATHS.register);

    await fillIn(user, "a@scarlet.test");
    await user.click(screen.getByRole("button", { name: ts.buttonLabel }));
    await user.click(screen.getByRole("button", { name: "Đăng ký" }));

    expect(api.register).toHaveBeenCalledWith("a@scarlet.test", PASSWORD, ts.token);
  });

  it("chua hoan tat o xac minh thi KHONG goi API (§11.6)", async () => {
    const user = userEvent.setup();
    renderAt(PATHS.register);

    await fillIn(user, "a@scarlet.test");
    await user.click(screen.getByRole("button", { name: "Đăng ký" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Hãy hoàn tất ô xác minh");
    expect(api.register).not.toHaveBeenCalled();
  });

  it("site key rong => widget tu an va van gui duoc voi token null (Cam bay ②)", async () => {
    const user = userEvent.setup();
    ts.enabled = false;
    vi.mocked(api.register).mockResolvedValue(ANTI_ENUMERATION_REPLY);
    renderAt(PATHS.register);

    await fillIn(user, "a@scarlet.test");
    await user.click(screen.getByRole("button", { name: "Đăng ký" }));

    // Hien mot o xac minh chet la cach chac chan nhat de khoa nguoi dung ra
    // khoi trang dang ky tren may dev — xem docstring `Turnstile.tsx`.
    expect(screen.queryByRole("button", { name: ts.buttonLabel })).toBeNull();
    expect(api.register).toHaveBeenCalledWith("a@scarlet.test", PASSWORD, null);
  });

  it("email DA TON TAI cho ra man hinh giong het ca thanh cong (UC-01 dong 1)", async () => {
    const user = userEvent.setup();
    // Backend tra dung mot `_REGISTER_RESPONSE` cho ca hai nhanh — day la toan
    // bo co che chong do cua §11.5, va FE khong duoc them mot nhanh nao.
    vi.mocked(api.register).mockResolvedValue(ANTI_ENUMERATION_REPLY);
    renderAt(PATHS.register);

    await fillIn(user, "da-ton-tai@scarlet.test");
    await user.click(screen.getByRole("button", { name: ts.buttonLabel }));
    await user.click(screen.getByRole("button", { name: "Đăng ký" }));

    expect(await screen.findByText("Kiểm tra hộp thư của bạn")).toBeInTheDocument();
    // Khong mot dau vet nao cua "email nay da co nguoi dung".
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("mat khau qua yeu ra cau cua vi.json, khong ra chuoi khong dau cua backend", async () => {
    const user = userEvent.setup();
    vi.mocked(api.register).mockRejectedValue(error(422, "PASSWORD_TOO_WEAK"));
    renderAt(PATHS.register);

    await fillIn(user, "a@scarlet.test");
    await user.click(screen.getByRole("button", { name: ts.buttonLabel }));
    await user.click(screen.getByRole("button", { name: "Đăng ký" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Mật khẩu này quá phổ biến. Chọn mật khẩu khác.",
    );
    // Van con o form de go lai — khong nhay sang man "da gui thu".
    expect(screen.getByLabelText("Mật khẩu")).toBeInTheDocument();
    // Ban T-HD8 2c: loi THAY dung cho dong goi y, duoi o mat khau — khong len
    // hop canh bao dau form.
    expect(screen.getByLabelText("Mật khẩu")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Mật khẩu")).toHaveAccessibleDescription(
      "Mật khẩu này quá phổ biến. Chọn mật khẩu khác.",
    );
    expect(screen.queryByText(/Dùng một mật khẩu dài/)).toBeNull();
  });

  it("MOI response loi keo theo mot lan Turnstile.reset() (Cam bay T-2.6)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.register).mockRejectedValue(error(422, "PASSWORD_TOO_WEAK"));
    renderAt(PATHS.register);

    await fillIn(user, "a@scarlet.test");
    await user.click(screen.getByRole("button", { name: ts.buttonLabel }));
    await user.click(screen.getByRole("button", { name: "Đăng ký" }));
    await screen.findByRole("alert");

    // Cloudflare tieu token ngay lan `siteverify` dau tien: khong xin lai thi
    // lan gui thu hai chac chan `400 TURNSTILE_FAILED`.
    expect(ts.reset).toHaveBeenCalledTimes(1);
    // Va token cu da bi vut di — bam Gui ngay bay gio bi chinh form chan lai.
    await user.click(screen.getByRole("button", { name: "Đăng ký" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Hãy hoàn tất ô xác minh");
    expect(api.register).toHaveBeenCalledTimes(1);
  });
});

// ──────────────────── /dang-nhap — ban T-HD8 1b, 1d ─────────────────────────

describe("/dang-nhap", () => {
  it("sai thong tin: MOT cau loi, khong o nao bi to, mat khau bi xoa va nhan tieu diem", async () => {
    const user = userEvent.setup();
    vi.mocked(api.login).mockRejectedValue(error(401, "INVALID_CREDENTIALS"));
    renderAt(PATHS.login);

    await user.type(await screen.findByLabelText("Email"), "a@scarlet.test");
    await user.type(screen.getByLabelText("Mật khẩu"), PASSWORD);
    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Email hoặc mật khẩu không đúng.");
    // To mot o la noi o do sai — tuc noi ra email ay co ton tai.
    expect(screen.getByLabelText("Email")).not.toHaveAttribute("aria-invalid");
    expect(screen.getByLabelText("Mật khẩu")).not.toHaveAttribute("aria-invalid");
    expect(screen.getByLabelText("Mật khẩu")).toHaveValue("");
    expect(screen.getByLabelText("Mật khẩu")).toHaveFocus();
    expect(screen.getByLabelText("Email")).toHaveValue("a@scarlet.test");
    // Ban T-HD8 A: man auth khong co header ung dung (NQ-131 d).
    expect(screen.queryByRole("banner")).toBeNull();
  });

  it("qua han muc la mau CANH BAO, khong phai mau loi, va mat khau giu nguyen", async () => {
    const user = userEvent.setup();
    vi.mocked(api.login).mockRejectedValue(error(429, "RATE_LIMITED"));
    renderAt(PATHS.login);

    await user.type(await screen.findByLabelText("Email"), "a@scarlet.test");
    await user.type(screen.getByLabelText("Mật khẩu"), PASSWORD);
    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Bạn đã thử quá nhiều lần. Đợi một lúc rồi thử lại.");
    expect(alert).toHaveAttribute("data-tone", "warning");
    expect(screen.getByLabelText("Mật khẩu")).toHaveValue(PASSWORD);
  });
});

// ─────────────────── /quen-mat-khau — §11.5 cung mot cau ────────────────────

describe("/quen-mat-khau", () => {
  it("email khong ton tai cho ra man hinh giong het email co that (§11.5)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.forgotPassword).mockResolvedValue(ANTI_ENUMERATION_REPLY);
    renderAt(PATHS.forgotPassword);

    await user.type(await screen.findByLabelText("Email"), "khong-ai@scarlet.test");
    await user.click(screen.getByRole("button", { name: ts.buttonLabel }));
    await user.click(screen.getByRole("button", { name: "Gửi thư đặt lại" }));

    expect(await screen.findByText("Kiểm tra hộp thư của bạn")).toBeInTheDocument();
    expect(api.forgotPassword).toHaveBeenCalledWith("khong-ai@scarlet.test", ts.token);
  });

  it("429 noi ra han muc chu khong im lang (§10.6)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.forgotPassword).mockRejectedValue(error(429, "RATE_LIMITED"));
    renderAt(PATHS.forgotPassword);

    await user.type(await screen.findByLabelText("Email"), "a@scarlet.test");
    await user.click(screen.getByRole("button", { name: ts.buttonLabel }));
    await user.click(screen.getByRole("button", { name: "Gửi thư đặt lại" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Bạn đã thử quá nhiều lần. Đợi một lúc rồi thử lại.",
    );
  });
});

// ──────────────── /dat-lai-mat-khau?token= — §11.5, NQ-44 ───────────────────

describe("/dat-lai-mat-khau", () => {
  it("doc token tu query va KHONG tu dang nhap sau khi doi xong (NQ-44)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.resetPassword).mockResolvedValue({ status: "reset" });
    renderAt(`${PATHS.resetPassword}?token=mot-token-that`);

    await user.type(await screen.findByLabelText("Mật khẩu mới"), PASSWORD);
    await user.type(screen.getByLabelText("Nhập lại mật khẩu mới"), PASSWORD);
    await user.click(screen.getByRole("button", { name: "Đặt mật khẩu" }));

    expect(api.resetPassword).toHaveBeenCalledWith("mot-token-that", PASSWORD);
    expect(await screen.findByText("Đã đổi mật khẩu")).toBeInTheDocument();
    // Khong roi ve man chat: duong di tiep duy nhat la mot lan dang nhap moi.
    expect(view().getByRole("link", { name: "Đăng nhập" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
  });

  it("TOKEN_INVALID doi ca man hinh, khong mot dong do duoi o nhap", async () => {
    const user = userEvent.setup();
    vi.mocked(api.resetPassword).mockRejectedValue(error(400, "TOKEN_INVALID"));
    renderAt(`${PATHS.resetPassword}?token=het-han`);

    await user.type(await screen.findByLabelText("Mật khẩu mới"), PASSWORD);
    await user.type(screen.getByLabelText("Nhập lại mật khẩu mới"), PASSWORD);
    await user.click(screen.getByRole("button", { name: "Đặt mật khẩu" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.",
    );
    // Go lai mat khau khong sua duoc mot lien ket het han — o nhap bien mat.
    expect(screen.queryByLabelText("Mật khẩu mới")).toBeNull();
    expect(view().getByRole("link", { name: "Xin liên kết mới" })).toBeInTheDocument();
  });

  it("hai o KHONG khop: bao ngay khi roi o thu hai va KHONG goi API (T-HD8 4b)", async () => {
    const user = userEvent.setup();
    renderAt(`${PATHS.resetPassword}?token=mot-token-that`);

    await user.type(await screen.findByLabelText("Mật khẩu mới"), PASSWORD);
    await user.type(screen.getByLabelText("Nhập lại mật khẩu mới"), `${PASSWORD}x`);
    await user.tab();

    expect(await screen.findByRole("alert")).toHaveTextContent("Hai mật khẩu không giống nhau.");
    expect(screen.getByLabelText("Nhập lại mật khẩu mới")).toHaveAttribute("aria-invalid", "true");
    // O thu nhat khong bi to: no khong sai gi ca.
    expect(screen.getByLabelText("Mật khẩu mới")).not.toHaveAttribute("aria-invalid");

    await user.click(screen.getByRole("button", { name: "Đặt mật khẩu" }));
    expect(api.resetPassword).not.toHaveBeenCalled();
  });
});

// ──────────────── /verify-email?token= — UC-01 dong 4 va 5 ──────────────────

describe("/verify-email", () => {
  it("token het han ra nut GUI LAI, khong phai man loi (UC-01 dong 4)", async () => {
    vi.mocked(api.verifyEmail).mockResolvedValue({ status: "expired" });
    renderAt(`${PATHS.verifyEmail}?token=het-han`);

    expect(await screen.findByText("Link xác thực đã hết hạn")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gửi lại thư" })).toBeInTheDocument();
    // "Khong phai loi 500": khong mot `role="alert"` nao, khong trang 500.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("500")).toBeNull();
  });

  it("nut gui lai bi 429 phai NOI RA han muc (Cam bay ③)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.verifyEmail).mockResolvedValue({ status: "expired" });
    vi.mocked(api.resendVerification).mockRejectedValue(error(429, "RATE_LIMITED"));
    renderAt(`${PATHS.verifyEmail}?token=het-han`);

    await user.type(await screen.findByLabelText("Email"), "a@scarlet.test");
    await user.click(screen.getByRole("button", { name: "Gửi lại thư" }));

    // *"Mot nut bam duoc ma khong co chuyen gi xay ra la cach chac chan nhat
    // de nguoi dung bam them bon lan."*
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Bạn đã gửi lại thư quá số lần cho phép trong một giờ.",
    );
    // Ban T-HD8 5f: nut TAT vi dieu kien, ly do nam ngay phia tren.
    expect(screen.getByRole("button", { name: "Gửi lại thư" })).toBeDisabled();
  });

  it("429 kem `retry_after` noi ra GIO thu lai, lay tu may chu (T-HD8 5f)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.verifyEmail).mockResolvedValue({ status: "expired" });
    vi.mocked(api.resendVerification).mockRejectedValue(
      new ApiError(429, "RATE_LIMITED", "goi qua nhieu lan", { retry_after: 600 }),
    );
    renderAt(`${PATHS.verifyEmail}?token=het-han`);

    await user.type(await screen.findByLabelText("Email"), "a@scarlet.test");
    await user.click(screen.getByRole("button", { name: "Gửi lại thư" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Thử lại được lúc");
    // Moc gio = bay gio + 600 s, khong phai con so "3" nao cua giao dien.
    const at = new Date(alert.querySelector("time")?.getAttribute("datetime") ?? "").getTime();
    expect(Math.abs(at - (Date.now() + 600_000))).toBeLessThan(5_000);
  });

  it("gui lai xong: dong trang thai xanh, nut VAN bam duoc (T-HD8 5e)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.verifyEmail).mockResolvedValue({ status: "expired" });
    vi.mocked(api.resendVerification).mockResolvedValue(ANTI_ENUMERATION_REPLY);
    renderAt(`${PATHS.verifyEmail}?token=het-han`);

    await user.type(await screen.findByLabelText("Email"), "a@scarlet.test");
    await user.click(screen.getByRole("button", { name: "Gửi lại thư" }));

    expect(await screen.findByText("Đã gửi thư mới. Kiểm tra hộp thư của bạn.")).toBeInTheDocument();
    expect(api.resendVerification).toHaveBeenCalledWith("a@scarlet.test");
    expect(screen.getByRole("button", { name: "Gửi lại thư" })).toBeEnabled();
  });

  it("lan bam DAU bao da xac thuc roi tu sang /cho-duyet (DoD dong 1)", async () => {
    vi.mocked(api.verifyEmail).mockResolvedValue({ status: "verified" });
    renderAt(`${PATHS.verifyEmail}?token=lan-dau`);

    expect(await screen.findByText("Đã xác thực email")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Đang chờ duyệt" }, { timeout: 3000 }),
    ).toBeInTheDocument();
    // Duong UC-01 KHONG co phien: khong co gi de dang xuat (NQ-131 c).
    expect(view().getByRole("link", { name: "Quay lại đăng nhập" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Đăng xuất" })).toBeNull();
  });

  it("lan bam THU HAI ve thang /dang-nhap, khong phai loi (UC-01 dong 5)", async () => {
    vi.mocked(api.verifyEmail).mockResolvedValue({ status: "already_verified" });
    renderAt(`${PATHS.verifyEmail}?token=lan-hai`);

    expect(await screen.findByText(/đã được xác thực trước đó/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      await screen.findByLabelText("Mật khẩu", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("goi verify-email DUNG MOT LAN du StrictMode mount hai lan", async () => {
    // Neu khong co co `daGoi`, loi goi thu hai tra `already_verified` va nguoi
    // vua dang ky bi day toi `/dang-nhap` thay vi `/cho-duyet` — chi o ban dev.
    vi.mocked(api.verifyEmail).mockResolvedValue({ status: "verified" });
    renderAt(`${PATHS.verifyEmail}?token=chi-mot-lan`);

    await screen.findByText("Đã xác thực email");

    expect(api.verifyEmail).toHaveBeenCalledTimes(1);
  });
});

// ──────────── StatusGate — DoD dong 2 va "khong roi ve man chat" ────────────

describe("dieu huong theo status cua §11.1", () => {
  function openChat(status: UserStatus) {
    vi.mocked(api.me).mockResolvedValue({ ...USER, status });
    renderAt(PATHS.home);
  }

  it("pending_approval khong vao man chat ma sang /cho-duyet", async () => {
    openChat("pending_approval");

    expect(await screen.findByRole("heading", { name: "Đang chờ duyệt" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
    // Co phien: hien email dang cho va nut Dang xuat (ban T-HD8 6a, NQ-131 c).
    expect(screen.getByText(USER.email)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Đăng xuất" })).toBeInTheDocument();
  });

  it("man /cho-duyet BIEN MAT sau khi duoc duyet (DoD dong 2)", async () => {
    openChat("active");

    expect(await screen.findByRole("textbox", { name: "Nhập tin nhắn cho Scarlet" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Đang chờ duyệt" })).toBeNull();
  });

  it("pending_email sang /verify-email chu khong vao man chat", async () => {
    openChat("pending_email");

    expect(
      await screen.findByRole("heading", { name: "Email chưa được xác thực" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
  });

  it("403 ACCOUNT_DISABLED ra man giai thich, KHONG roi ve man chat (§11.1)", async () => {
    vi.mocked(api.me).mockRejectedValue(error(403, "ACCOUNT_DISABLED"));
    renderAt(PATHS.home);

    expect(await screen.findByRole("heading", { name: "Không đăng nhập được" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
    // Con cookie phien (403, khong phai 401) nen nut phu la Dang xuat that.
    expect(screen.getByRole("button", { name: "Đăng xuất" })).toBeInTheDocument();
  });

  it("401 (chua dang nhap) sang /dang-nhap, KHONG ra man chat (T-3.1c)", async () => {
    // Ca nay TUNG khang dinh dieu nguoc lai, va no dung vao ngay T-3.1b:
    // nhanh danh tinh tam cua Phase 1 con song, man chat con chay bang no.
    // T-3.1c go nhanh ay, nen cau khang dinh phai lat cung mot commit — do la
    // dau hieu nhanh tam da chet, khong phai mot test hong. Xem `StatusGate`.
    renderAt(PATHS.home);

    expect(await screen.findByLabelText("Mật khẩu")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
  });
});
