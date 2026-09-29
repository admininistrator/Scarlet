import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { PATHS } from "../../app/paths";
import { ERROR_CODES, type ApiError } from "../../lib/api";
import { t } from "../../lib/i18n";
import { AuthField, AuthTitle, FormAlert, SubmitButton } from "./AuthForm";
import { AuthActions, AuthFooterLink, AuthLayout } from "./AuthLayout";
import { placeAuthError } from "./authErrors";

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
 *
 * ── T-S.16: ban T-HD8 (1a–1e) ─────────────────────────────────────────────
 *
 * *"Mot cau loi cho ca sai email lan sai mat khau"*, va **khong o nao bi to
 * do**: to mot o la noi o do sai, tuc noi ra email ay co ton tai. Sai thong
 * tin thi xoa mat khau va dua tieu diem ve o mat khau; bi khoa cung cho, cung
 * kieu; qua han muc la mau canh bao. Dang gui: hai o chi doc, nut khoa.
 */
export function LoginForm({
  onSend,
  error,
}: {
  onSend: (email: string, password: string) => Promise<boolean>;
  error: ApiError | null;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sending, setSending] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);
  /*
    Chi phan ung voi loi cua MOT lan gui trong chinh man nay: `error` song o
    `useSessionState` (Layout), nen quay lai `/dang-nhap` sau mot lan sai van
    thay loi cu — xoa o va keo tieu diem luc mo man la mot hanh vi khong ai
    yeu cau.
  */
  const awaitingRef = useRef(false);

  useEffect(() => {
    if (!awaitingRef.current || error === null) {
      return;
    }
    awaitingRef.current = false;
    if (error.code === ERROR_CODES.WRONG_PASSWORD) {
      setPassword("");
      passwordRef.current?.focus();
    }
  }, [error]);

  const alert = error === null ? null : placeAuthError(error);

  return (
    <AuthLayout footer={<AuthFooterLink to={PATHS.register}>{t("auth.chuaCoTaiKhoan")}</AuthFooterLink>}>
      <form
        aria-busy={sending}
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          awaitingRef.current = true;
          setSending(true);
          void onSend(email, password).finally(() => setSending(false));
        }}
      >
        <AuthTitle title={t("auth.dangNhap")} />

        {alert !== null && <FormAlert tone={alert.tone}>{alert.text}</FormAlert>}

        <AuthField
          id="login-email"
          label={t("auth.email")}
          type="email"
          autoComplete="email"
          value={email}
          onChange={setEmail}
          readOnly={sending}
        />
        <AuthField
          id="login-password"
          label={t("auth.matKhau")}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={setPassword}
          readOnly={sending}
          inputRef={passwordRef}
          after={
            <Link
              to={PATHS.forgotPassword}
              className="-mt-1.5 -mb-3 inline-flex min-h-touch items-center self-end text-sm font-medium"
            >
              {t("auth.quenMatKhau")}
            </Link>
          }
        />

        <AuthActions>
          <SubmitButton busy={sending} label={t("auth.dangNhap")} />
        </AuthActions>
      </form>
    </AuthLayout>
  );
}
