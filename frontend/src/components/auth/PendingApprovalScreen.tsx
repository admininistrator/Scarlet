import { Hourglass } from "lucide";
import { useNavigate } from "react-router";

import { useSession } from "../../app/Layout";
import { PATHS } from "../../app/paths";
import { t } from "../../lib/i18n";
import { AuthLayout } from "./AuthLayout";
import { AuthMessage, LogoutButton, MessageText, SecondaryLink } from "./AuthMessage";

/**
 * Man `/cho-duyet` — hang `pending_approval` cua §11.1. T-3.1b.
 *
 * KH tham chieu: §11.1, UC-01 · tasks.md T-3.1b, T-S.16 · NQ-131 c.
 *
 * Man hinh nay KHONG doi mot phien: nguoi vua bam lien ket xac thuc trong hop
 * thu chua dang nhap lan nao, va ho van phai doc duoc "gio thi cho admin
 * duyet". Do la ly do no khong re nhanh theo `status` — viec dua ai toi day
 * la cua `StatusGate` va `VerifyEmailScreen`.
 *
 * ── T-S.16: ban T-HD8 (6a, 6b) ────────────────────────────────────────────
 *
 * Ban ve in email cua phien (*"de nguoi dung biet minh dang cho bang tai khoan
 * nao"*) va mot nut phu "Dang xuat". Ca hai chi co nghia khi CO phien — ca
 * `StatusGate` dua mot `pending_approval` da dang nhap toi day. Tren duong
 * UC-01 (bam link verify -> tu sang day) khong co phien nao: khong dong email,
 * va nut phu la lien ket "Quay lai dang nhap" (NQ-131 c). Luc `/auth/me` con
 * dang hoi thi chua ve ca hai, de khong nhay tu nhanh nay sang nhanh kia.
 */
export function PendingApprovalScreen() {
  const session = useSession();
  const navigate = useNavigate();
  const email = session.user?.email ?? null;

  return (
    <AuthLayout>
      <AuthMessage
        icon={Hourglass}
        title={t("auth.choDuyetTieuDe")}
        body={
          <>
            <MessageText>{t("auth.choDuyet")}</MessageText>
            {email !== null && <MessageText strong>{email}</MessageText>}
          </>
        }
      >
        {!session.loading &&
          (email !== null ? (
            <LogoutButton
              label={t("auth.dangXuat")}
              onClick={() => void session.logout().then(() => navigate(PATHS.login))}
            />
          ) : (
            <SecondaryLink to={PATHS.login}>{t("auth.quayLaiDangNhap")}</SecondaryLink>
          ))}
      </AuthMessage>
    </AuthLayout>
  );
}
