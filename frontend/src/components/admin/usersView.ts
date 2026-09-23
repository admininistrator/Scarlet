/**
 * Luat THUAN cua man "Nguoi dung" — T-3.12, §16.3, §10.4.
 *
 * KH tham chieu: §10.4, §16.3 · tasks.md T-2.16 (`UpdateUserRequest`), T-2.20,
 * T-3.12 (Cam bay ②) · NQ-51.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  `can_execute_skills` LA MOT TRUONG CUA BAN GHI DE, KHONG PHAI MOT COT ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `PATCH /admin/users/{id}` co hai truong (`tier_name`, `limit_override`), va
 * docstring `UpdateUserRequest` noi ro vi sao khong co truong thu ba: cong tac
 * "Chay skill" ghi vao `limit_override.can_execute_skills`. Nen moi thao tac
 * o day la "doc ban ghi de hien co → doi DUNG mot khoa → gui lai CA ban ghi
 * de": gui mot ban ghi de chi co khoa vua doi la xoa mat moi khoa khac.
 *
 * Bat/tat ve DUNG gia tri cua tier thi khoa bi GO khoi ban ghi de thay vi ghi
 * mot ban sao: mot `can_execute_skills: false` nam trong ban ghi de cua mot
 * tier cung `false` se lang le chan nguoi ay ngay admin bat skill cho CA tier.
 * Ban ghi de rong thi gui `null` ("quay ve dung han muc cua tier").
 */

import type { AdminUserOut, TierRow, UserStatus } from "../../lib/api";
import type { TextKey } from "../../lib/i18n";

/** Nam trang thai §11.1 → nhan (dung chung cho bang Nguoi dung va so audit). */
export const STATUS_LABEL: Record<UserStatus, TextKey> = {
  pending_email: "admin.status.pending_email",
  pending_approval: "admin.status.pending_approval",
  active: "admin.status.active",
  rejected: "admin.status.rejected",
  suspended: "admin.status.suspended",
};

export type LimitOverride = Record<string, unknown>;

/** Hai khoa tien cua ban ghi de ma dialog "Ghi de han muc" sua. */
export const LIMIT_KEYS = ["limit_5h_usd", "limit_7d_usd"] as const;
export type LimitKey = (typeof LIMIT_KEYS)[number];

export const SKILLS_KEY = "can_execute_skills";

export function tierOf(tiers: readonly TierRow[], name: string): TierRow | null {
  return tiers.find((tier) => tier.name === name) ?? null;
}

/** Quyen chay skill DANG CO HIEU LUC: ban ghi de thang tier (§10.4). */
export function effectiveSkills(user: AdminUserOut, tiers: readonly TierRow[]): boolean {
  const overridden = user.limit_override_json?.[SKILLS_KEY];
  if (typeof overridden === "boolean") {
    return overridden;
  }
  return tierOf(tiers, user.tier_name)?.can_execute_skills ?? false;
}

function orNull(override: LimitOverride): LimitOverride | null {
  return Object.keys(override).length === 0 ? null : override;
}

/**
 * Ban ghi de SAU khi bat/tat skill. `tierDefault === null` (khong biet tier)
 * thi luon ghi khoa — khong doan gia tri cua tier.
 */
export function overrideWithSkills(
  current: LimitOverride | null,
  next: boolean,
  tierDefault: boolean | null,
): LimitOverride | null {
  const copy = { ...(current ?? {}) };
  if (tierDefault !== null && next === tierDefault) {
    delete copy[SKILLS_KEY];
  } else {
    copy[SKILLS_KEY] = next;
  }
  return orNull(copy);
}

/**
 * Ban ghi de SAU khi luu dialog "Ghi de han muc". O trong ⇒ go khoa (dung han
 * muc tier). Gia tri giu nguyen CHUOI da go — khong parse, khong lam tron (ban
 * T-HD7: *"go '20' luu '20', server chuan hoa"*).
 */
export function overrideWithLimits(
  current: LimitOverride | null,
  values: Record<LimitKey, string>,
): LimitOverride | null {
  const copy = { ...(current ?? {}) };
  for (const key of LIMIT_KEYS) {
    const value = values[key].trim();
    if (value === "") {
      delete copy[key];
    } else {
      copy[key] = value;
    }
  }
  return orNull(copy);
}

/** Gia tri dang ghi de cua mot khoa tien, de dien san vao o nhap. */
export function overrideLimit(current: LimitOverride | null, key: LimitKey): string {
  const value = current?.[key];
  return value === undefined || value === null ? "" : String(value);
}

/**
 * Thay doi da luu luc `savedAt` con "cho hieu luc" khong. TTL la cua server
 * (`limits_cache_ttl_s`); chua biet TTL thi coi nhu con cho — noi "co the
 * chua chay" khi khong chac la an toan, noi "da chay" thi khong.
 */
export function isPending(savedAt: number, now: number, ttlSeconds: number | null): boolean {
  return ttlSeconds === null || now < savedAt + ttlSeconds * 1000;
}
