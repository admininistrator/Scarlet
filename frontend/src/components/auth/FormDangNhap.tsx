import { useState } from "react";
import { MA_LOI, type ApiError } from "../../lib/api";
import { t } from "../../lib/i18n";

/**
 * Form dang nhap TOI THIEU cua T-2.19 — §11.2.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  VI SAO MOT TASK "ADMIN UI" LAI DE RA MOT FORM DANG NHAP               ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `require_admin` (app/core/deps.py) co y KHONG cho nhanh danh tinh tam cua
 * Phase 1 di qua: mot chuoi nguoi goi tu go ma duyet duoc tai khoan chinh la
 * lo hong B-34. Nghia la man `/admin` khong the chay bang danh tinh tam, va
 * khong co duong nao lay duoc cookie phien that neu FE khong co cho de go
 * email + mat khau. (T-3.1c da xoa han nhanh tam ay — B-128.)
 *
 * Nen o day khong phai "them tinh nang", ma la dieu kien de hai dong DoD dau
 * cua T-2.19 ton tai. Man dang nhap THAT — quen mat khau, dang ky, Turnstile,
 * xu ly `pending_email` — la viec cua Phase 3.
 *
 * Khong co Turnstile o day va do la dung hop dong: §11.6 dat captcha o
 * `register`/`forgot-password`, con `POST /auth/login` khong doc
 * `turnstile_token` (xem `api/v1/auth.py`). Chong do mat khau o duong nay la
 * viec cua rate limit §10.6, da co tu T-2.9.
 */
export function FormDangNhap({
  onGui,
  loi,
}: {
  onGui: (email: string, matKhau: string) => Promise<boolean>;
  loi: ApiError | null;
}) {
  const [email, setEmail] = useState("");
  const [matKhau, setMatKhau] = useState("");
  const [dangGui, setDangGui] = useState(false);

  return (
    <main className="mx-auto w-full max-w-sm px-6 py-12">
      <h2 className="mb-6 text-lg font-semibold">{t("auth.dangNhap")}</h2>

      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setDangGui(true);
          void onGui(email, matKhau).finally(() => setDangGui(false));
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">{t("auth.email")}</span>
          <input
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-sm border border-border bg-background px-2 py-1.5 text-foreground"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">{t("auth.matKhau")}</span>
          <input
            type="password"
            required
            autoComplete="current-password"
            value={matKhau}
            onChange={(e) => setMatKhau(e.target.value)}
            className="rounded-sm border border-border bg-background px-2 py-1.5 text-foreground"
          />
        </label>

        {loi !== null && (
          <p role="alert" className="text-sm text-danger-emphasis">
            {loi.code === MA_LOI.SAI_MAT_KHAU
              ? t("auth.saiMatKhau")
              : loi.code === MA_LOI.TAI_KHOAN_BI_KHOA
                ? t("auth.taiKhoanBiKhoa")
                : loi.message}
          </p>
        )}

        <button
          type="submit"
          disabled={dangGui}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
        >
          {t("auth.dangNhap")}
        </button>
      </form>
    </main>
  );
}
