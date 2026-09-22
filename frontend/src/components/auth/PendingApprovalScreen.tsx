import { Link } from "react-router";

import { PATHS } from "../../app/paths";
import { t } from "../../lib/i18n";

/**
 * Man `/cho-duyet` — hang `pending_approval` cua §11.1. T-3.1b.
 *
 * KH tham chieu: §11.1, UC-01 · tasks.md T-3.1b.
 *
 * Man hinh nay KHONG doi mot phien: nguoi vua bam lien ket xac thuc trong hop
 * thu chua dang nhap lan nao, va ho van phai doc duoc "gio thi cho admin
 * duyet". Do la ly do no khong goi `GET /auth/me` va khong re nhanh theo
 * `status` — viec dua ai toi day la cua `StatusGate` va `VerifyEmailScreen`.
 *
 * Cau chu noi ro gioi han thuc: cho duyet chan CHAT BANG KHOA HE THONG, chu
 * khong chan ca tai khoan (§11.1 cho `pending_approval` dung BYOK — "nguoi do
 * khong tieu tien cua ban, nen khong co ly do gi chan ho").
 */
export function PendingApprovalScreen() {
  return (
    <main className="mx-auto w-full max-w-md px-6 py-16 text-center">
      <h2 className="text-lg font-semibold">{t("choDuyet.tieuDe")}</h2>
      <p className="mt-2 text-sm text-muted">{t("choDuyet.moTa")}</p>
      <Link
        to={PATHS.login}
        className="mt-6 inline-flex min-h-touch items-center rounded-md border border-border px-3 text-sm hover:bg-accent hover:text-accent-foreground"
      >
        {t("choDuyet.veDangNhap")}
      </Link>
    </main>
  );
}
