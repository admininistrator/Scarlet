import { ApiError, MA_LOI } from "../../lib/api";
import { t } from "../../lib/i18n";

/**
 * Mot loi cua §18 -> mot cau nguoi dung doc duoc — T-3.1b.
 *
 * KH tham chieu: §18, §11.6 · tasks.md T-3.1b · CLAUDE.md A3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  VI SAO KHONG HIEN THANG `loi.message`                                 ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `core/errors.py` tra mot cau tieng Viet KHONG DAU (*"mat khau qua pho bien,
 * hay chon mat khau khac"*) vi no la chuoi cua log va cua API, khong phai
 * chuoi cua man hinh. Dat no len giao dien la de nguoi dung doc mot thu chua
 * bao gio duoc viet cho ho.
 *
 * Nen ranh gioi la: FE re nhanh theo `code`, roi tu viet cau cua no tu
 * `vi.json` — dung nua sau cua ly le da co trong `api.ts` (*"`code` chu khong
 * phai `message` la thu FE duoc phep phan nhanh"*, B-86). `loi.message` chi
 * con la duong lui cho nhung ma chua ai nghi toi.
 *
 * ── Ba man hinh, mot bang ─────────────────────────────────────────────────
 *
 * Dang ky, quen mat khau va dat lai mat khau deu co the tra `TURNSTILE_FAILED`,
 * `PASSWORD_TOO_*` va `RATE_LIMITED`. Ba ban chep cua cung mot chuoi `if` la
 * ba cho de mot man hinh im lang khi hai man kia da noi.
 */
const THEO_MA: Record<string, string> = {
  [MA_LOI.TURNSTILE_HONG]: "auth.turnstileTuChoi",
  [MA_LOI.MAT_KHAU_QUA_NGAN]: "auth.matKhauQuaNgan",
  [MA_LOI.MAT_KHAU_QUA_YEU]: "auth.matKhauQuaYeu",
  [MA_LOI.QUA_NHIEU_LAN]: "auth.quaNhieuLan",
  [MA_LOI.SAI_MAT_KHAU]: "auth.saiMatKhau",
  [MA_LOI.TAI_KHOAN_BI_KHOA]: "auth.taiKhoanBiKhoa",
};

export function authErrorText(loi: unknown): string {
  if (!(loi instanceof ApiError)) {
    return String(loi);
  }
  const khoa = THEO_MA[loi.code];
  // `as never` chi de noi voi `t()` rang chuoi nay la mot khoa that: bang tren
  // go kieu `Record<string, string>` nen TypeScript khong theo doi duoc tung
  // gia tri. Khoa sai se lo ra ngay o man hinh — `t()` tra lai chinh khoa.
  return khoa === undefined ? loi.message : t(khoa as never);
}
