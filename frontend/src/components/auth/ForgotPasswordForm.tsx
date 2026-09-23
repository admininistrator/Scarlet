import { useState } from "react";
import { Link } from "react-router";

import { PATHS } from "../../app/paths";
import { api } from "../../lib/api";
import { t } from "../../lib/i18n";
import { Turnstile } from "./Turnstile";
import { authErrorText } from "./authErrors";
import { useTurnstile } from "./useTurnstile";

/**
 * Man `/quen-mat-khau` — §11.5, §11.6. T-3.1b.
 *
 * KH tham chieu: §11.5, §11.6 · tasks.md T-2.5, T-2.6, T-3.1b.
 *
 * Cung hinh dang `RegisterForm` va cung ly le §11.5: email co that va email
 * khong ton tai cho ra man hinh GIONG HET nhau, vi backend tra dung mot
 * `_FORGOT_PASSWORD_RESPONSE` cho ca hai. Khac dung mot thu — khong co o mat
 * khau — nen no la mot file rieng chu khong mot co `che_do` tren mot form
 * dung chung: hai form co hai truong khac nhau, hai cau khac nhau, hai duong
 * di tiep khac nhau, va thu duy nhat chung chia se (bon viec cua Turnstile)
 * da nam trong `useTurnstile`.
 *
 * Han muc 3/gio theo IP (§10.6, NQ-43) tinh ca luot bi captcha chan — nen
 * `RATE_LIMITED` phai co mot cau rieng, khong roi vao duong lui.
 */
export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const turnstile = useTurnstile();

  if (done) {
    return (
      <main className="mx-auto w-full max-w-sm px-6 py-12">
        <h2 className="text-lg font-semibold">{t("quenMatKhau.daGui.tieuDe")}</h2>
        <p className="mt-2 text-sm text-muted">{t("quenMatKhau.daGui.moTa")}</p>
        <Link
          to={PATHS.login}
          className="mt-6 inline-flex min-h-touch items-center rounded-md border border-border px-3 text-sm hover:bg-accent hover:text-accent-foreground"
        >
          {t("auth.dangNhap")}
        </Link>
      </main>
    );
  }

  async function submit() {
    if (turnstile.missingToken) {
      setError(t("auth.turnstileChua"));
      return;
    }
    setError(null);
    setSending(true);
    try {
      await api.forgotPassword(email, turnstile.token);
      setDone(true);
    } catch (e) {
      setError(authErrorText(e));
      turnstile.reset();
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-sm px-6 py-12">
      <h2 className="mb-2 text-lg font-semibold">{t("quenMatKhau.tieuDe")}</h2>
      <p className="mb-6 text-sm text-muted">{t("quenMatKhau.moTa")}</p>

      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
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
            className="min-h-touch rounded-sm border border-border bg-background px-2 text-foreground"
          />
        </label>

        <Turnstile onToken={turnstile.onToken} ref={turnstile.ref} className="my-1" />

        {error !== null && (
          <p role="alert" className="text-sm text-danger-text">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={sending}
          className="motion-press min-h-touch rounded-md border border-border px-3 text-sm hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
        >
          {sending ? t("auth.dangXuLy") : t("quenMatKhau.gui")}
        </button>
      </form>

      <Link to={PATHS.login} className="mt-6 inline-flex min-h-touch items-center text-sm text-muted underline">
        {t("auth.dangNhap")}
      </Link>
    </main>
  );
}
