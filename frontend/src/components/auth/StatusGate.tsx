import type { ReactNode } from "react";
import { Navigate } from "react-router";

import { PATHS } from "../../app/paths";
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
 * ── `nguoiDung === null` ⇒ `/dang-nhap` (T-3.1c) ──────────────────────────
 *
 * T-3.1b co y KHONG chan nguoi chua dang nhap o day: nhanh danh tinh tam cua
 * Phase 1 (NQ-24/NQ-33) van song luc do va man chat van chay bang no, nen
 * chan o day la lam viec cua T-3.1c som mot commit bang mot component khac —
 * tuc ngay T-3.1c toi se co hai cho phai go thay vi mot.
 *
 * T-3.1c go nhanh ay. Ke tu day `nguoiDung === null` chi con mot nghia:
 * khong co phien nao, va man chat khong con duong nao goi API duoc. Man hinh
 * se dung yen cho mot nguoi khong the lam gi tren no, roi cho ho mot bang loi
 * `401` o lan bam dau tien; mot lan `<Navigate>` toi `/dang-nhap` la cau tra
 * loi trung thuc hon. Day cung la ly do ca test *"401 van ra man chat"* cua
 * T-3.1b doi chieu o ngay commit nay: no la phep do cua nhanh tam, khong phai
 * mot test hong.
 *
 * `replace` chu khong mot lan `push`, cung ly le `AdminOnly` da ghi: mot lan
 * chuyen huong tu dong de lai dau chan trong lich su la mot cai bay khong
 * thoat duoc bang Back.
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
  if (session.nguoiDung === null) {
    return <Navigate to={PATHS.login} replace />;
  }
  const dich = pathForStatus(session.nguoiDung.status);
  if (dich !== null) {
    return <Navigate to={dich} replace />;
  }
  return <>{children}</>;
}
