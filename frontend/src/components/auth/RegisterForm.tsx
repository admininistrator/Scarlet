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
 * Man `/dang-ky` — UC-01, §11.6. T-3.1b, dong B-185.
 *
 * KH tham chieu: §11.1, §11.5, §11.6, UC-01 · tasks.md T-2.6, T-3.1b, B-185.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  DAY LA CHO DAU TIEN `Turnstile.tsx` DUOC MOUNT                        ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * T-2.6 dung widget tu Phase 2 va docstring cua no ghi thang: *"CHUA CO MAN
 * HINH NAO DUNG NO, VA DO LA DUNG PHAM VI"*. B-185 la muc Backlog giu cho
 * ngay hom nay. He qua do duoc: truoc man hinh nay, cach duy nhat chay het
 * UC-01 tren stack that la tam doi `TURNSTILE_SECRET` sang khoa test "luon
 * dat" cua Cloudflare roi dang ky bang `curl`.
 *
 * ── MOT CAU TRA LOI CHO CA HAI NHANH (UC-01 dong 1) ───────────────────────
 *
 * Email da ton tai va email moi cho ra man hinh GIONG HET nhau, va no giong
 * het **vi khong co gi de khac**: backend tra dung mot `_REGISTER_RESPONSE`
 * cho ca hai (§11.5), nen o day khong co mot nhanh nao doc `message` ra de re
 * duong. Man hinh thanh cong duoi day duoc ve tu `vi.json`, khong tu response
 * — mot ngay nao do ai do doi cau chu cua backend cung khong lam lo ra email
 * nao da dang ky.
 *
 * T-S.16 (ban T-HD8 2e): man ay in lai email NGUOI DUNG VUA GO — thu ho da co
 * trong tay, nen khong lo gi — va noi "chung toi vua gui thu". Voi email da
 * co, backend hom nay KHONG gui thu nao; ban ve gia dinh mot thu "ban da co tai
 * khoan" (NQ-131 b, Backlog).
 *
 * ── `reset()` SAU MOI LOI ─────────────────────────────────────────────────
 *
 * Cloudflare tieu token ngay lan `siteverify` dau tien. Sau mot `422` vi mat
 * khau qua yeu, lan gui thu hai chac chan `400 TURNSTILE_FAILED` neu khong
 * xin token moi — xem `useTurnstile`.
 */
export function RegisterForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<PlacedAuthError | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const turnstile = useTurnstile();

  if (sentTo !== null) {
    return (
      <AuthLayout>
        <AuthMessage
          icon={Mail}
          title={t("auth.kiemTraHopThu")}
          body={
            <>
              <MessageText>{t("auth.daGuiThuToi")}</MessageText>
              <MessageText strong>{sentTo}</MessageText>
              <MessageText>{t("auth.moThuDeTiepTuc")}</MessageText>
            </>
          }
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
      await api.register(email, password, turnstile.token);
      setSentTo(email);
    } catch (e) {
      setError(placeAuthError(e));
      turnstile.reset();
    } finally {
      setSending(false);
    }
  }

  const errorAt = (slot: PlacedAuthError["slot"]) => (error?.slot === slot ? error.text : null);

  return (
    <AuthLayout footer={<AuthFooterLink to={PATHS.login}>{t("auth.daCoTaiKhoan")}</AuthFooterLink>}>
      <form
        aria-busy={sending}
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <AuthTitle title={t("auth.dangKy")} />

        {error !== null && error.slot === "form" && <FormAlert tone={error.tone}>{error.text}</FormAlert>}

        <AuthField
          id="register-email"
          label={t("auth.email")}
          type="email"
          autoComplete="email"
          value={email}
          onChange={setEmail}
          readOnly={sending}
        />
        <AuthField
          id="register-password"
          label={t("auth.matKhau")}
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={setPassword}
          readOnly={sending}
          hint={t("auth.matKhauGoiY")}
          error={errorAt("password")}
        />

        <TurnstileSlot turnstile={turnstile} error={errorAt("turnstile")} />

        <AuthActions>
          <SubmitButton busy={sending} label={t("auth.dangKy")} />
        </AuthActions>
      </form>
    </AuthLayout>
  );
}
