import { Mail } from "lucide";
import { useState } from "react";

import { PATHS } from "../../app/paths";
import { api } from "../../lib/api";
import { t } from "../../lib/i18n";
import { AuthField, AuthTitle, FormAlert, SubmitButton, TurnstileSlot } from "./AuthForm";
import { AuthActions, AuthFooterLink, AuthLayout } from "./AuthLayout";
import { AuthMessage, MessageNote, MessageText, SecondaryLink } from "./AuthMessage";
import { placeAuthError, type PlacedAuthError } from "./authErrors";
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
 *
 * T-S.16: ban T-HD8 (3a–3c) KHONG ve o Turnstile o man nay. §11.6 dat captcha
 * o dung form nay va `forgot-password` van kiem token, nen bo khung ay la mot
 * form dep ma backend tu choi bang `400` — khung GIU nguyen, cung vi tri nhu
 * man Dang ky (bao lai ban ve, Backlog).
 */
export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<PlacedAuthError | null>(null);
  const [done, setDone] = useState(false);
  const turnstile = useTurnstile();

  if (done) {
    return (
      <AuthLayout>
        <AuthMessage
          icon={Mail}
          title={t("auth.kiemTraHopThu")}
          body={<MessageText>{t("auth.daGuiThuDatLai")}</MessageText>}
        >
          <SecondaryLink to={PATHS.login}>{t("auth.quayLaiDangNhap")}</SecondaryLink>
          <MessageNote>{t("auth.khongThayThu")}</MessageNote>
        </AuthMessage>
      </AuthLayout>
    );
  }

  async function submit() {
    if (turnstile.missingToken) {
      setError({ slot: "turnstile", tone: "danger", text: t("auth.turnstileChua") });
      return;
    }
    setError(null);
    setSending(true);
    try {
      await api.forgotPassword(email, turnstile.token);
      setDone(true);
    } catch (e) {
      setError(placeAuthError(e));
      turnstile.reset();
    } finally {
      setSending(false);
    }
  }

  return (
    <AuthLayout footer={<AuthFooterLink to={PATHS.login}>{t("auth.quayLaiDangNhap")}</AuthFooterLink>}>
      <form
        aria-busy={sending}
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <AuthTitle title={t("auth.quenMatKhauTieuDe")} lead={t("auth.quenMatKhauMoTa")} />

        {error !== null && error.slot !== "turnstile" && (
          <FormAlert tone={error.tone}>{error.text}</FormAlert>
        )}

        <AuthField
          id="forgot-email"
          label={t("auth.email")}
          type="email"
          autoComplete="email"
          value={email}
          onChange={setEmail}
          readOnly={sending}
        />

        <TurnstileSlot turnstile={turnstile} error={error?.slot === "turnstile" ? error.text : null} />

        <AuthActions>
          <SubmitButton busy={sending} label={t("auth.guiThuDatLai")} />
        </AuthActions>
      </form>
    </AuthLayout>
  );
}
