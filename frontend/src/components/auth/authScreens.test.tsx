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
 * vitest chay TRONG container ay — nen `turnstileDaBat()` tra `true` ngay
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
  bat: true,
  token: "token-cloudflare-gia",
  nhanNut: "hoan tat o xac minh",
  reset: vi.fn(),
}));

vi.mock("./Turnstile", async () => {
  const { useImperativeHandle } = await vi.importActual<typeof import("react")>("react");
  return {
    turnstileDaBat: () => ts.bat,
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
      if (!ts.bat) {
        return null;
      }
      return (
        <button type="button" onClick={() => onToken(ts.token)}>
          {ts.nhanNut}
        </button>
      );
    },
  };
});

vi.mock("../../lib/api", async (importOriginal) => {
  const that = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...that,
    api: {
      ...that.api,
      toiLaAi: vi.fn(),
      danhSachModel: vi.fn(),
      danhSachHoiThoai: vi.fn(),
      dangKy: vi.fn(),
      xacThucEmail: vi.fn(),
      guiLaiXacThuc: vi.fn(),
      quenMatKhau: vi.fn(),
      datLaiMatKhau: vi.fn(),
    },
  };
});

import { PATHS } from "../../app/paths";
import { routes } from "../../app/routes";
import { ApiError, api, type HoSoRa, type TrangThaiUser } from "../../lib/api";

const NGUOI_DUNG: HoSoRa = {
  id: "33333333-3333-4333-8333-333333333333",
  email: "nguoi-moi@scarlet.test",
  display_name: null,
  status: "active",
  role: "user",
  tier_name: "free",
  // Ba truong cua `HoSoRa` — chi `GET /auth/me` tra chung (B-213, T-3.4).
  default_model: null,
  quota: null,
  message_max_chars: 24000,
};

const MAT_KHAU = "mot-mat-khau-du-manh-123";
const PHAN_HOI_CHONG_DO = { message: "cau co dinh cua §11.5" };

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
 * `conGan` bi cleanup cua lan chay thu nhat tat di con lan thu hai thi bi
 * `daGoi` chan truoc khi kip dung mot co moi. Bo test chi bat duoc no khi no
 * chay dung cai cay ma trinh duyet chay.
 */
function moTai(duong: string) {
  const router = createMemoryRouter(routes, { initialEntries: [duong] });
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
 */
function man() {
  return within(screen.getByRole("main"));
}

function loi(status: number, code: string): ApiError {
  return new ApiError(status, code, "thong diep cua backend, khong phai cua man hinh");
}

beforeEach(() => {
  ts.bat = true;
  vi.mocked(api.toiLaAi).mockRejectedValue(loi(401, "UNAUTHENTICATED"));
  vi.mocked(api.danhSachModel).mockResolvedValue([]);
  vi.mocked(api.danhSachHoiThoai).mockResolvedValue({ items: [], next_cursor: null });
});

// ───────────────────── /dang-ky — UC-01 dong 1, B-185 ───────────────────────

describe("/dang-ky", () => {
  async function dien(nguoiDung: ReturnType<typeof userEvent.setup>, email: string) {
    await nguoiDung.type(await screen.findByLabelText("Email"), email);
    await nguoiDung.type(screen.getByLabelText("Mật khẩu"), MAT_KHAU);
  }

  it("mount widget Turnstile va gui kem token cua no (B-185)", async () => {
    const nguoiDung = userEvent.setup();
    vi.mocked(api.dangKy).mockResolvedValue(PHAN_HOI_CHONG_DO);
    moTai(PATHS.register);

    await dien(nguoiDung, "a@scarlet.test");
    await nguoiDung.click(screen.getByRole("button", { name: ts.nhanNut }));
    await nguoiDung.click(screen.getByRole("button", { name: "Đăng ký" }));

    expect(api.dangKy).toHaveBeenCalledWith("a@scarlet.test", MAT_KHAU, ts.token);
  });

  it("chua hoan tat o xac minh thi KHONG goi API (§11.6)", async () => {
    const nguoiDung = userEvent.setup();
    moTai(PATHS.register);

    await dien(nguoiDung, "a@scarlet.test");
    await nguoiDung.click(screen.getByRole("button", { name: "Đăng ký" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Hãy hoàn tất ô xác minh");
    expect(api.dangKy).not.toHaveBeenCalled();
  });

  it("site key rong => widget tu an va van gui duoc voi token null (Cam bay ②)", async () => {
    const nguoiDung = userEvent.setup();
    ts.bat = false;
    vi.mocked(api.dangKy).mockResolvedValue(PHAN_HOI_CHONG_DO);
    moTai(PATHS.register);

    await dien(nguoiDung, "a@scarlet.test");
    await nguoiDung.click(screen.getByRole("button", { name: "Đăng ký" }));

    // Hien mot o xac minh chet la cach chac chan nhat de khoa nguoi dung ra
    // khoi trang dang ky tren may dev — xem docstring `Turnstile.tsx`.
    expect(screen.queryByRole("button", { name: ts.nhanNut })).toBeNull();
    expect(api.dangKy).toHaveBeenCalledWith("a@scarlet.test", MAT_KHAU, null);
  });

  it("email DA TON TAI cho ra man hinh giong het ca thanh cong (UC-01 dong 1)", async () => {
    const nguoiDung = userEvent.setup();
    // Backend tra dung mot `_PHAN_HOI_DANG_KY` cho ca hai nhanh — day la toan
    // bo co che chong do cua §11.5, va FE khong duoc them mot nhanh nao.
    vi.mocked(api.dangKy).mockResolvedValue(PHAN_HOI_CHONG_DO);
    moTai(PATHS.register);

    await dien(nguoiDung, "da-ton-tai@scarlet.test");
    await nguoiDung.click(screen.getByRole("button", { name: ts.nhanNut }));
    await nguoiDung.click(screen.getByRole("button", { name: "Đăng ký" }));

    expect(await screen.findByText("Kiểm tra hộp thư của bạn")).toBeInTheDocument();
    // Khong mot dau vet nao cua "email nay da co nguoi dung".
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("mat khau qua yeu ra cau cua vi.json, khong ra chuoi khong dau cua backend", async () => {
    const nguoiDung = userEvent.setup();
    vi.mocked(api.dangKy).mockRejectedValue(loi(422, "PASSWORD_TOO_WEAK"));
    moTai(PATHS.register);

    await dien(nguoiDung, "a@scarlet.test");
    await nguoiDung.click(screen.getByRole("button", { name: ts.nhanNut }));
    await nguoiDung.click(screen.getByRole("button", { name: "Đăng ký" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Mật khẩu này quá phổ biến. Chọn mật khẩu khác.",
    );
    // Van con o form de go lai — khong nhay sang man "da gui thu".
    expect(screen.getByLabelText("Mật khẩu")).toBeInTheDocument();
  });

  it("MOI response loi keo theo mot lan Turnstile.reset() (Cam bay T-2.6)", async () => {
    const nguoiDung = userEvent.setup();
    vi.mocked(api.dangKy).mockRejectedValue(loi(422, "PASSWORD_TOO_WEAK"));
    moTai(PATHS.register);

    await dien(nguoiDung, "a@scarlet.test");
    await nguoiDung.click(screen.getByRole("button", { name: ts.nhanNut }));
    await nguoiDung.click(screen.getByRole("button", { name: "Đăng ký" }));
    await screen.findByRole("alert");

    // Cloudflare tieu token ngay lan `siteverify` dau tien: khong xin lai thi
    // lan gui thu hai chac chan `400 TURNSTILE_FAILED`.
    expect(ts.reset).toHaveBeenCalledTimes(1);
    // Va token cu da bi vut di — bam Gui ngay bay gio bi chinh form chan lai.
    await nguoiDung.click(screen.getByRole("button", { name: "Đăng ký" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Hãy hoàn tất ô xác minh");
    expect(api.dangKy).toHaveBeenCalledTimes(1);
  });
});

// ─────────────────── /quen-mat-khau — §11.5 cung mot cau ────────────────────

describe("/quen-mat-khau", () => {
  it("email khong ton tai cho ra man hinh giong het email co that (§11.5)", async () => {
    const nguoiDung = userEvent.setup();
    vi.mocked(api.quenMatKhau).mockResolvedValue(PHAN_HOI_CHONG_DO);
    moTai(PATHS.forgotPassword);

    await nguoiDung.type(await screen.findByLabelText("Email"), "khong-ai@scarlet.test");
    await nguoiDung.click(screen.getByRole("button", { name: ts.nhanNut }));
    await nguoiDung.click(screen.getByRole("button", { name: "Gửi liên kết đặt lại" }));

    expect(await screen.findByText("Kiểm tra hộp thư của bạn")).toBeInTheDocument();
    expect(api.quenMatKhau).toHaveBeenCalledWith("khong-ai@scarlet.test", ts.token);
  });

  it("429 noi ra han muc chu khong im lang (§10.6)", async () => {
    const nguoiDung = userEvent.setup();
    vi.mocked(api.quenMatKhau).mockRejectedValue(loi(429, "RATE_LIMITED"));
    moTai(PATHS.forgotPassword);

    await nguoiDung.type(await screen.findByLabelText("Email"), "a@scarlet.test");
    await nguoiDung.click(screen.getByRole("button", { name: ts.nhanNut }));
    await nguoiDung.click(screen.getByRole("button", { name: "Gửi liên kết đặt lại" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Bạn đã thử quá nhiều lần. Đợi một lúc rồi thử lại.",
    );
  });
});

// ──────────────── /dat-lai-mat-khau?token= — §11.5, NQ-44 ───────────────────

describe("/dat-lai-mat-khau", () => {
  it("doc token tu query va KHONG tu dang nhap sau khi doi xong (NQ-44)", async () => {
    const nguoiDung = userEvent.setup();
    vi.mocked(api.datLaiMatKhau).mockResolvedValue({ status: "reset" });
    moTai(`${PATHS.resetPassword}?token=mot-token-that`);

    await nguoiDung.type(await screen.findByLabelText("Mật khẩu mới"), MAT_KHAU);
    await nguoiDung.click(screen.getByRole("button", { name: "Đặt mật khẩu mới" }));

    expect(api.datLaiMatKhau).toHaveBeenCalledWith("mot-token-that", MAT_KHAU);
    expect(await screen.findByText("Đã đặt lại mật khẩu")).toBeInTheDocument();
    // Khong roi ve man chat: duong di tiep duy nhat la mot lan dang nhap moi.
    expect(man().getByRole("link", { name: "Đăng nhập" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
  });

  it("TOKEN_INVALID doi ca man hinh, khong mot dong do duoi o nhap", async () => {
    const nguoiDung = userEvent.setup();
    vi.mocked(api.datLaiMatKhau).mockRejectedValue(loi(400, "TOKEN_INVALID"));
    moTai(`${PATHS.resetPassword}?token=het-han`);

    await nguoiDung.type(await screen.findByLabelText("Mật khẩu mới"), MAT_KHAU);
    await nguoiDung.click(screen.getByRole("button", { name: "Đặt mật khẩu mới" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.",
    );
    // Go lai mat khau khong sua duoc mot lien ket het han — o nhap bien mat.
    expect(screen.queryByLabelText("Mật khẩu mới")).toBeNull();
    expect(man().getByRole("link", { name: "Xin liên kết mới" })).toBeInTheDocument();
  });
});

// ──────────────── /verify-email?token= — UC-01 dong 4 va 5 ──────────────────

describe("/verify-email", () => {
  it("token het han ra nut GUI LAI, khong phai man loi (UC-01 dong 4)", async () => {
    vi.mocked(api.xacThucEmail).mockResolvedValue({ status: "expired" });
    moTai(`${PATHS.verifyEmail}?token=het-han`);

    expect(await screen.findByText("Liên kết đã hết hạn")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gửi lại email xác thực" })).toBeInTheDocument();
    // "Khong phai loi 500": khong mot `role="alert"` nao, khong trang 500.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("500")).toBeNull();
  });

  it("nut gui lai bi 429 phai NOI RA han muc (Cam bay ③)", async () => {
    const nguoiDung = userEvent.setup();
    vi.mocked(api.xacThucEmail).mockResolvedValue({ status: "expired" });
    vi.mocked(api.guiLaiXacThuc).mockRejectedValue(loi(429, "RATE_LIMITED"));
    moTai(`${PATHS.verifyEmail}?token=het-han`);

    await nguoiDung.type(await screen.findByLabelText("Email"), "a@scarlet.test");
    await nguoiDung.click(screen.getByRole("button", { name: "Gửi lại email xác thực" }));

    // *"Mot nut bam duoc ma khong co chuyen gi xay ra la cach chac chan nhat
    // de nguoi dung bam them bon lan."*
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Bạn đã xin gửi lại quá nhiều lần trong một giờ. Hãy đợi rồi thử lại.",
    );
  });

  it("lan bam DAU bao da xac thuc roi tu sang /cho-duyet (DoD dong 1)", async () => {
    vi.mocked(api.xacThucEmail).mockResolvedValue({ status: "verified" });
    moTai(`${PATHS.verifyEmail}?token=lan-dau`);

    expect(await screen.findByText("Email đã được xác thực")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Đang chờ quản trị duyệt" }, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("lan bam THU HAI ve thang /dang-nhap, khong phai loi (UC-01 dong 5)", async () => {
    vi.mocked(api.xacThucEmail).mockResolvedValue({ status: "already_verified" });
    moTai(`${PATHS.verifyEmail}?token=lan-hai`);

    expect(await screen.findByText(/đã được xác thực trước đó/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      await screen.findByLabelText("Mật khẩu", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("goi verify-email DUNG MOT LAN du StrictMode mount hai lan", async () => {
    // Neu khong co co `daGoi`, loi goi thu hai tra `already_verified` va nguoi
    // vua dang ky bi day toi `/dang-nhap` thay vi `/cho-duyet` — chi o ban dev.
    vi.mocked(api.xacThucEmail).mockResolvedValue({ status: "verified" });
    moTai(`${PATHS.verifyEmail}?token=chi-mot-lan`);

    await screen.findByText("Email đã được xác thực");

    expect(api.xacThucEmail).toHaveBeenCalledTimes(1);
  });
});

// ──────────── StatusGate — DoD dong 2 va "khong roi ve man chat" ────────────

describe("dieu huong theo status cua §11.1", () => {
  function moManChat(status: TrangThaiUser) {
    vi.mocked(api.toiLaAi).mockResolvedValue({ ...NGUOI_DUNG, status });
    moTai(PATHS.home);
  }

  it("pending_approval khong vao man chat ma sang /cho-duyet", async () => {
    moManChat("pending_approval");

    expect(
      await screen.findByRole("heading", { name: "Đang chờ quản trị duyệt" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
  });

  it("man /cho-duyet BIEN MAT sau khi duoc duyet (DoD dong 2)", async () => {
    moManChat("active");

    expect(await screen.findByRole("button", { name: "Hội thoại mới" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Đang chờ quản trị duyệt" })).toBeNull();
  });

  it("pending_email sang /verify-email chu khong vao man chat", async () => {
    moManChat("pending_email");

    expect(
      await screen.findByRole("heading", { name: "Email chưa được xác thực" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
  });

  it("403 ACCOUNT_DISABLED ra man giai thich, KHONG roi ve man chat (§11.1)", async () => {
    vi.mocked(api.toiLaAi).mockRejectedValue(loi(403, "ACCOUNT_DISABLED"));
    moTai(PATHS.home);

    expect(
      await screen.findByRole("heading", { name: "Tài khoản không dùng được" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
  });

  it("401 (chua dang nhap) sang /dang-nhap, KHONG ra man chat (T-3.1c)", async () => {
    // Ca nay TUNG khang dinh dieu nguoc lai, va no dung vao ngay T-3.1b:
    // nhanh danh tinh tam cua Phase 1 con song, man chat con chay bang no.
    // T-3.1c go nhanh ay, nen cau khang dinh phai lat cung mot commit — do la
    // dau hieu nhanh tam da chet, khong phai mot test hong. Xem `StatusGate`.
    moTai(PATHS.home);

    expect(await screen.findByLabelText("Mật khẩu")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hội thoại mới" })).toBeNull();
  });
});
