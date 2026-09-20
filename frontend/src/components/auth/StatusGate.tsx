import type { ReactNode } from "react";
import { Navigate } from "react-router";

import { useSession } from "../../app/Layout";
import { t } from "../../lib/i18n";
import { AccountDisabledScreen } from "./AccountDisabledScreen";
import { pathForStatus } from "./statusRoute";

/**
 * Cua vao ung dung, canh theo `status` cua §11.1 — T-3.1b.
 *
 * KH tham chieu: §11.1, §18.1 · tasks.md T-3.1b, T-2.19, T-3.1c.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  "KHONG ROI VE MAN CHAT"                                               ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * "Viec can lam" cua T-3.1b: *"Dieu huong theo `status` cua `GET /auth/me`
 * dung may trang thai §11.1 [...] **Khong** roi ve man chat"*. Truoc task
 * nay, moi nguoi dang nhap deu roi vao `<ChatScreen/>` bat ke `status`, va
 * ba trang thai chua dung duoc chi lo dien khi ho bam Gui roi nhan `403`.
 *
 * ── BON NHANH, VA NHANH DAU LA CUA `AdminOnly` ────────────────────────────
 *
 * `dangTai` la nhanh RIENG, cung ly le `AdminOnly` da ghi: roi thang xuong
 * nhanh duoi se nhap nhay mot lan chuyen huong trong moi lan mo trang.
 *
 * ── VI SAO `nguoiDung === null` KHONG BI CHAN ─────────────────────────────
 *
 * Nhanh danh tinh tam cua Phase 1 (`scarlet_dev_user`, NQ-24/NQ-33) van song
 * cho toi T-3.1c, va man chat van chay bang no. Chan nguoi chua dang nhap o
 * day la lam viec cua T-3.1c som mot commit — va lam no bang mot component
 * khac, tuc ngay T-3.1c toi se co hai cho phai go thay vi mot.
 *
 * ── `biKhoa` khong phai mot `status` ──────────────────────────────────────
 *
 * `rejected`/`suspended` khong bao gio ve toi FE duoi dang mot `status`: ca
 * `/auth/login` lan `/auth/me` tra `403 ACCOUNT_DISABLED` cho chung
 * (`STATUSES_CAN_VIEW_APP`). Vi vay chung di theo mot duong rieng —
 * `usePhien` ghi lai ma loi ay — va o day chung duoc ve chu khong duoc chuyen
 * huong: khong co dia chi nao de chuyen toi, va mot lan day ve `/dang-nhap`
 * chi moi ho go lai mat khau dung de gap lai dung buc tuong ay.
 */
export function StatusGate({ children }: { children: ReactNode }) {
  const session = useSession();

  if (session.dangTai) {
    return <p className="px-6 py-4 text-sm text-muted">{t("admin.dangTai")}</p>;
  }
  if (session.biKhoa) {
    return <AccountDisabledScreen />;
  }
  if (session.nguoiDung !== null) {
    const dich = pathForStatus(session.nguoiDung.status);
    if (dich !== null) {
      return <Navigate to={dich} replace />;
    }
  }
  return <>{children}</>;
}
