import { PATHS, type Path } from "../../app/paths";
import type { UserStatus } from "../../lib/api";

/**
 * May trang thai §11.1 -> mot dia chi — T-3.1b.
 *
 * KH tham chieu: §11.1 · tasks.md T-3.1b · CLAUDE.md A3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOT BANG, HAI NGUOI HOI                                               ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `LoginRoute` hoi sau mot lan dang nhap thanh cong; `StatusGate` hoi moi lan
 * co ai mo mot man hinh cua ung dung. Hai ban chep cua bang nay se lech vao
 * dung ngay them mot trang thai thu sau — va trieu chung se la "dang nhap thi
 * vao dung cho, F5 mot cai thi ra cho khac".
 *
 * ── `null` nghia la "khong chuyen di dau ca" ──────────────────────────────
 *
 * `active` la trang thai duy nhat duoc o lai. Hai trang thai cuoi
 * (`rejected`, `suspended`) KHONG co mat o day va do la chu y: ca `POST
 * /auth/login` lan `GET /auth/me` deu tra `403 ACCOUNT_DISABLED` cho chung
 * (`STATUSES_CAN_LOGIN`, `STATUSES_CAN_VIEW_APP` cua `core/deps.py`), nen FE
 * khong bao gio cam trong tay mot `UserOut` mang hai gia tri ay. Man giai
 * thich cho ho di theo duong loi, khong duong dinh tuyen — xem
 * `AccountDisabledScreen`.
 */
export function pathForStatus(status: UserStatus): Path | null {
  switch (status) {
    case "pending_email":
      return PATHS.verifyEmail;
    case "pending_approval":
      return PATHS.pendingApproval;
    default:
      return null;
  }
}
