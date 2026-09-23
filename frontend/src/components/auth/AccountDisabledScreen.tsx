import { Link } from "react-router";

import { PATHS } from "../../app/paths";
import { t } from "../../lib/i18n";

/**
 * Man giai thich cho `rejected` / `suspended` — hai hang cuoi cua §11.1.
 * T-3.1b.
 *
 * KH tham chieu: §11.1, §11.3 · tasks.md T-3.1b.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  VI SAO DAY LA MOT MAN HINH CHU KHONG MOT LAN DANG XUAT IM LANG        ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * "Viec can lam" cua T-3.1b ghi: *"`suspended` -> man giai thich. **Khong**
 * roi ve man chat"*. Truoc task nay, `useSessionState` bat moi loi cua `GET
 * /auth/me` thanh mot ket cuc duy nhat (`nguoiDung = null`) — mot lua chon
 * dung o T-2.19 va docstring cua no noi ro ly do: *"401 (chua dang nhap) va
 * 403 (tai khoan bi khoa) deu dan toi cung mot man hinh"*. Ke tu hom nay thi
 * KHONG con dan toi cung mot man hinh nua, va do la toan bo ly do `locked`
 * ra doi.
 *
 * He qua neu bo qua: admin bam Suspend giua mot phien (§11.3 thu hoi trong
 * 15 phut), tab dang mo tu nhien "dang xuat", nguoi dung go lai mat khau
 * dung va nhan `403` — mot vong lap khong co loi ra, va khong mot man hinh
 * nao noi ra chuyen gi da xay ra.
 *
 * Duong duy nhat ra khoi day di qua admin (§16.3): `rejected`/`suspended` la
 * hai trang thai CUOI cua §11.1, khong co canh nao tu no di ra.
 */
export function AccountDisabledScreen() {
  return (
    <main className="mx-auto w-full max-w-md px-6 py-16 text-center">
      <h2 className="text-lg font-semibold">{t("biKhoa.tieuDe")}</h2>
      <p className="mt-2 text-sm text-muted">{t("biKhoa.moTa")}</p>
      <Link
        to={PATHS.login}
        className="mt-6 inline-flex min-h-touch items-center rounded-md border border-border px-3 text-sm hover:bg-accent hover:text-accent-foreground"
      >
        {t("choDuyet.veDangNhap")}
      </Link>
    </main>
  );
}
