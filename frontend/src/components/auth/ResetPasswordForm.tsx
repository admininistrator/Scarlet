import { CircleCheck, Link2Off } from "lucide";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { PATHS } from "../../app/paths";
import { ApiError, ERROR_CODES, api } from "../../lib/api";
import { t } from "../../lib/i18n";
import { AuthField, AuthTitle, FormAlert, SubmitButton } from "./AuthForm";
import { AuthActions, AuthLayout } from "./AuthLayout";
import { AuthMessage, MessageText, PrimaryLink } from "./AuthMessage";
import { placeAuthError, type PlacedAuthError } from "./authErrors";

/**
 * Man `/dat-lai-mat-khau?token=` — §11.5, NQ-44. T-3.1b.
 *
 * KH tham chieu: §11.3, §11.5, §11.6 · tasks.md T-2.5, T-3.1b · NQ-44.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  XONG ROI VAN PHAI DANG NHAP LAI, VA DO LA CHU Y                       ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `POST /auth/reset-password` **khong** dang nhap ai ca (NQ-44, B-130) va no
 * con xoa hai cookie phien dang co, vi doi mat khau la thu hoi MOI phien
 * (§11.3). Nen man hinh nay khong duoc tu dieu huong ve `/` nhu mot lan dang
 * nhap thanh cong: no noi ra rang moi phien cu da bi thu hoi, roi moi nguoi
 * dung dang nhap lai. Mot lan chuyen thang ve man chat o day se cho ra mot
 * man chat `401` o moi loi goi — dung trieu chung ma NQ-44 tranh.
 *
 * ── `TOKEN_INVALID` khong phai mot loi form ────────────────────────────────
 *
 * Ba kieu token hong (khong ton tai / da dung / het han) deu ra mot cau tra
 * loi o backend (`_RESET_TOKEN_MSG`), va ca ba deu co cung duong di tiep: xin
 * mot lien ket moi. Nen no duoc ve thanh mot man hinh co LOI THOAT, khong
 * phai mot dong do duoi o mat khau — go lai mat khau khong sua duoc mot lien
 * ket het han, va de nguoi dung go them lan nua la de ho tu tim ra dieu do.
 *
 * ── T-S.16: o "Nhap lai" (ban T-HD8 4b) ───────────────────────────────────
 *
 * *"Kiem ngay tren may khi roi o thu hai. Loi dai/ngan/pho bien van den tu may
 * chu."* Hai o khac nhau thi KHONG goi API — body gui di van la dung mot mat
 * khau nhu truoc, nen hop dong voi backend khong doi.
 */
export function ResetPasswordForm() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");

  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<PlacedAuthError | null>(null);
  const [tokenInvalid, setTokenInvalid] = useState(false);
  const [done, setDone] = useState(false);

  if (token === null || tokenInvalid) {
    return (
      <AuthLayout>
        <AuthMessage icon={Link2Off} title={t("auth.datMatKhauMoiTieuDe")}>
          <FormAlert tone="danger">
            {token === null ? t("datLai.thieuToken") : t("datLai.tokenHong")}
          </FormAlert>
          <PrimaryLink to={PATHS.forgotPassword}>{t("datLai.xinLienKetMoi")}</PrimaryLink>
        </AuthMessage>
      </AuthLayout>
    );
  }

  if (done) {
    return (
      <AuthLayout>
        <AuthMessage
          icon={CircleCheck}
          tone="success"
          title={t("auth.daDoiMatKhau")}
          body={<MessageText>{t("auth.phienCuDaThuHoi")}</MessageText>}
        >
          <PrimaryLink to={PATHS.login}>{t("auth.dangNhap")}</PrimaryLink>
        </AuthMessage>
      </AuthLayout>
    );
  }

  async function submit() {
    if (password !== again) {
      setMismatch(true);
      return;
    }
    setError(null);
    setSending(true);
    try {
      await api.resetPassword(token as string, password);
      setDone(true);
    } catch (e) {
      // Token hong -> doi ca man hinh; mat khau qua ngan/yeu -> thay dong goi
      // y duoi o, vi do la thu go lai duoc.
      if (e instanceof ApiError && e.code === ERROR_CODES.TOKEN_INVALID) {
        setTokenInvalid(true);
      } else {
        setError(placeAuthError(e));
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <AuthLayout>
      <form
        aria-busy={sending}
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <AuthTitle title={t("auth.datMatKhauMoiTieuDe")} />

        {error !== null && error.slot !== "password" && <FormAlert tone={error.tone}>{error.text}</FormAlert>}

        <AuthField
          id="reset-new"
          label={t("auth.matKhauMoi")}
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(v) => {
            setPassword(v);
            setMismatch(false);
          }}
          readOnly={sending}
          hint={t("auth.matKhauGoiY")}
          error={error?.slot === "password" ? error.text : null}
        />
        <AuthField
          id="reset-again"
          label={t("auth.nhapLaiMatKhau")}
          type="password"
          autoComplete="new-password"
          value={again}
          onChange={(v) => {
            setAgain(v);
            setMismatch(false);
          }}
          onBlur={() => setMismatch(again !== "" && again !== password)}
          readOnly={sending}
          error={mismatch ? t("auth.matKhauKhongKhop") : null}
        />

        <AuthActions>
          <SubmitButton busy={sending} label={t("auth.datMatKhau")} />
        </AuthActions>
      </form>
    </AuthLayout>
  );
}
