import { ApiError, ERROR_CODES } from "../../lib/api";
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
const BY_CODE: Record<string, string> = {
  [ERROR_CODES.TURNSTILE_FAILED]: "auth.turnstileTuChoi",
  [ERROR_CODES.PASSWORD_TOO_SHORT]: "auth.matKhauQuaNgan",
  [ERROR_CODES.PASSWORD_TOO_WEAK]: "auth.matKhauQuaYeu",
  [ERROR_CODES.TOO_MANY_ATTEMPTS]: "auth.quaNhieuLan",
  [ERROR_CODES.WRONG_PASSWORD]: "auth.saiMatKhau",
  [ERROR_CODES.ACCOUNT_DISABLED]: "auth.taiKhoanBiKhoa",
};

export function authErrorText(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return String(error);
  }
  const key = BY_CODE[error.code];
  // `as never` chi de noi voi `t()` rang chuoi nay la mot khoa that: bang tren
  // go kieu `Record<string, string>` nen TypeScript khong theo doi duoc tung
  // gia tri. Khoa sai se lo ra ngay o man hinh — `t()` tra lai chinh khoa.
  return key === undefined ? error.message : t(key as never);
}

/**
 * Cau loi nam O DAU tren form — T-S.16, ban T-HD8 (2c, 1d).
 *
 * *"Loi mat khau thay dung cho dong goi y. Loi Turnstile nam duoi o xac
 * minh, khop chu 'phia tren'."* Con lai len hop canh bao dau form; han muc la
 * mau CANH BAO chu khong phai mau loi (*"cho la het"*, 1d).
 *
 * Cung mot bang cho ca ba form, cung ly le `BY_CODE`: ba ban chep cua mot
 * chuoi `if` la ba cho de mot man dat loi mot noi, hai man kia dat noi khac.
 */
export type AuthErrorSlot = "password" | "turnstile" | "form";

export interface PlacedAuthError {
  slot: AuthErrorSlot;
  tone: "danger" | "warning";
  text: string;
}

const SLOT_BY_CODE: Record<string, AuthErrorSlot> = {
  [ERROR_CODES.PASSWORD_TOO_SHORT]: "password",
  [ERROR_CODES.PASSWORD_TOO_WEAK]: "password",
  [ERROR_CODES.TURNSTILE_FAILED]: "turnstile",
};

export function placeAuthError(error: unknown): PlacedAuthError {
  const code = error instanceof ApiError ? error.code : null;
  return {
    slot: (code !== null ? SLOT_BY_CODE[code] : undefined) ?? "form",
    tone: code === ERROR_CODES.TOO_MANY_ATTEMPTS ? "warning" : "danger",
    text: authErrorText(error),
  };
}
