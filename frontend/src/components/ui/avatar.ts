import { DISPLAY_LOCALE, type TextKey } from "../../lib/i18n";

/**
 * Avatar tron mot chu cai — mau va chu cai dau. T-S.11 (tab Tai khoan), T-S.12
 * (khoi tai khoan o chan sidebar) doc CUNG file nay.
 *
 * KH tham chieu: §24.2b·S10 · NQ-116 · B-293 (chot 2026-09-26: nguoi dung chon
 * mau, hash cua user id lam mac dinh khi chua chon).
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  SERVER LUU TEN MAU, KHONG LUU MA MAU (A3)                             ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `avatar_color` la TEN token cua ban T-HD1-v2 (`avatar-1`…`avatar-8`), ma
 * mau o `theme.css` — sang va toi mot cap. Backend khong biet bang mau
 * (T-S.5 chi kiem `^[a-z0-9-]{1,32}$`), nen mot ten FE khong biet (bang mau
 * doi sau nay, sua tay trong `psql`) roi ve mau MAC DINH chu khong vo avatar.
 *
 * Mau mac dinh = hash on dinh cua user id mod 8 (chu thich khoi AVATAR trong
 * `theme.css`): theo id chu khong theo ten, de doi ten khong doi mau.
 */

export const AVATAR_COLORS = [
  "avatar-1",
  "avatar-2",
  "avatar-3",
  "avatar-4",
  "avatar-5",
  "avatar-6",
  "avatar-7",
  "avatar-8",
] as const;

export type AvatarColor = (typeof AVATAR_COLORS)[number];

/** Ten lop viet NGUYEN VAN — Tailwind chi sinh lop no thay trong ma nguon. */
const BACKGROUND: Record<AvatarColor, string> = {
  "avatar-1": "bg-avatar-1",
  "avatar-2": "bg-avatar-2",
  "avatar-3": "bg-avatar-3",
  "avatar-4": "bg-avatar-4",
  "avatar-5": "bg-avatar-5",
  "avatar-6": "bg-avatar-6",
  "avatar-7": "bg-avatar-7",
  "avatar-8": "bg-avatar-8",
};

/** Ten mau doc cho trinh doc man hinh (ban T-HD9: `aria-label` cua o chon). */
export const AVATAR_LABEL: Record<AvatarColor, TextKey> = {
  "avatar-1": "account.color.1",
  "avatar-2": "account.color.2",
  "avatar-3": "account.color.3",
  "avatar-4": "account.color.4",
  "avatar-5": "account.color.5",
  "avatar-6": "account.color.6",
  "avatar-7": "account.color.7",
  "avatar-8": "account.color.8",
};

export function isAvatarColor(name: string | null | undefined): name is AvatarColor {
  return (AVATAR_COLORS as readonly string[]).includes(name ?? "");
}

/** FNV-1a 32 bit tren tung don vi UTF-16 — on dinh giua cac trinh duyet. */
function stableHash(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** Mau khi nguoi dung CHUA chon — hash(user id) mod 8. */
export function defaultAvatarColor(userId: string): AvatarColor {
  return AVATAR_COLORS[stableHash(userId) % AVATAR_COLORS.length];
}

/** Mau da chon neu FE biet ten ay, khong thi mau mac dinh cua nguoi nay. */
export function avatarColorOf(saved: string | null, userId: string): AvatarColor {
  return isAvatarColor(saved) ? saved : defaultAvatarColor(userId);
}

export function avatarBackground(color: AvatarColor): string {
  return BACKGROUND[color];
}

/**
 * Chu cai dau cua ten dang HIEN (ten hien thi, trong thi email — NQ-116).
 * `Array.from` tach theo diem ma, nen mot emoji o dau ten khong bi cat doi.
 */
export function initialOf(shown: string): string {
  return (Array.from(shown.trim())[0] ?? "").toLocaleUpperCase(DISPLAY_LOCALE);
}
