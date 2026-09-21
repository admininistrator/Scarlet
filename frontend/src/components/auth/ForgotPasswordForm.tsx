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
 * `_PHAN_HOI_QUEN_MAT_KHAU` cho ca hai. Khac dung mot thu — khong co o mat
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
  const [dangGui, setDangGui] = useState(false);
  const [loi, setLoi] = useState<string | null>(null);
  const [xong, setXong] = useState(false);
  const turnstile = useTurnstile();

  if (xong) {
    return (
      <main className="mx-auto w-full max-w-sm px-6 py-12">
        <h2 className="text-lg font-semibold">{t("quenMatKhau.daGui.tieuDe")}</h2>
        <p className="mt-2 text-sm text-muted">{t("quenMatKhau.daGui.moTa")}</p>
        <Link
          to={PATHS.login}
          className="mt-6 inline-block rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
        >
          {t("auth.dangNhap")}
        </Link>
      </main>
    );
  }

  async function gui() {
    if (turnstile.thieuToken) {
      setLoi(t("auth.turnstileChua"));
      return;
    }
    setLoi(null);
    setDangGui(true);
    try {
      await api.quenMatKhau(email, turnstile.token);
      setXong(true);
    } catch (e) {
      setLoi(authErrorText(e));
      turnstile.reset();
    } finally {
      setDangGui(false);
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
          void gui();
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

        <Turnstile onToken={turnstile.onToken} ref={turnstile.ref} className="my-1" />

        {loi !== null && (
          <p role="alert" className="text-sm text-danger-emphasis">
            {loi}
          </p>
        )}

        <button
          type="submit"
          disabled={dangGui}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
        >
          {dangGui ? t("auth.dangXuLy") : t("quenMatKhau.gui")}
        </button>
      </form>

      <Link to={PATHS.login} className="mt-6 inline-block text-sm text-muted underline">
        {t("auth.dangNhap")}
      </Link>
    </main>
  );
}
