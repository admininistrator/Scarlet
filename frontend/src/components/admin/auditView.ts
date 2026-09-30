/**
 * Doc mot dong so audit thanh chu — THUAN, khong React (T-3.12, B-191).
 *
 * KH tham chieu: §16.3 (*"ai, luc nao, lam gi, voi ai"*), §20 · tasks.md
 * T-2.16, T-2.20, T-3.12 (DoD dong 3), B-191 · ban T-HD7 muc 1f.
 *
 * Ban T-HD7 dat bon luat, ca bon o day:
 *
 *   1. **Khong UUID nao hien ra.** "Voi ai" la ten + email (B-191, backend
 *      JOIN); nguoi DA XOA khong con ten, chi con 8 ky tu dau cua id de tra log.
 *   2. **Nhan loai luon dung tren** (NGUOI DUNG / TIER / TAI KHOAN DA XOA) —
 *      khong bat nguoi doc doan loai qua hinh dang.
 *   3. **"Lam gi" = nhan hanh dong + dong `cu → moi` rieng**, khong ghep thanh
 *      cau co bien o giua. Gia tri cu rong hien "—".
 *   4. **Tac nhan khong con biet la ai** hien nghieng, khong gia lam nguoi. Ban
 *      ve goi no "He thong (tu dong)"; o day `actor_id = NULL` co HAI nghia
 *      (cron, hoac tai khoan da xoa — `ON DELETE SET NULL`), va man hinh khong
 *      duoc chon giup nghia nao — nhan noi ca hai.
 */

import type { AuditActionName, AuditEntry, UserStatus } from "../../lib/api";
import type { TextKey } from "../../lib/i18n";
import { shortId } from "./format";
import { LIMIT_KEYS, STATUS_LABEL, type LimitKey } from "./usersView";

/** Ten bang cua `target_type` — khop `TARGET_*` cua `db/models/audit_log.py`. */
const TARGET_USERS = "users";
const TARGET_TIERS = "tiers";
const TARGET_CATALOG = "catalog";

export const ACTION_LABEL: Record<AuditActionName, TextKey> = {
  "user.approve": "admin.auditAction.user.approve",
  "user.reject": "admin.auditAction.user.reject",
  "user.suspend": "admin.auditAction.user.suspend",
  "user.update": "admin.auditAction.user.update",
  "tier.update": "admin.auditAction.tier.update",
  "catalog.reload": "admin.auditAction.catalog.reload",
};

const FIELD_LABEL: Record<string, TextKey> = {
  status: "admin.field.status",
  tier_name: "admin.field.tier_name",
  limit_override_json: "admin.field.limit_override_json",
  limit_5h_usd: "admin.field.limit_5h_usd",
  limit_7d_usd: "admin.field.limit_7d_usd",
  can_execute_skills: "admin.field.can_execute_skills",
  can_use_web: "admin.field.can_use_web",
  web_searches_per_day: "admin.field.web_searches_per_day",
  max_upload_mb: "admin.field.max_upload_mb",
  max_attachments: "admin.field.max_attachments",
  allowed_model_tags: "admin.field.allowed_model_tags",
  models: "admin.field.models",
  version: "admin.field.version",
};

export type AuditActor = { kind: "person"; name: string; email: string | null } | { kind: "unknown" };

export type AuditTarget =
  | { kind: "user"; name: string; email: string | null }
  | { kind: "deletedUser"; shortId: string }
  | { kind: "tier"; name: string }
  | { kind: "catalog" }
  | { kind: "none" };

/**
 * Mot dong "cu → moi" (hoac mot su kien khong co "cu", vi du so model sau khi
 * tai lai catalog). `label` la khoa `vi.json` neu biet, con khong thi la ten
 * truong tho — mot truong moi o backend van hien duoc, chi chua co nhan dep.
 */
export interface AuditChange {
  label: { key: TextKey } | { raw: string };
  from?: AuditValue;
  to: AuditValue;
}

/** Gia tri da san sang de hien — `text` nguyen van, hoac mot khoa `vi.json`. */
export type AuditValue = { text: string } | { key: TextKey } | { empty: true };

export function describeActor(entry: AuditEntry): AuditActor {
  if (entry.actor_email === null) {
    return { kind: "unknown" };
  }
  return {
    kind: "person",
    name: entry.actor_display_name ?? entry.actor_email,
    email: entry.actor_display_name === null ? null : entry.actor_email,
  };
}

export function describeTarget(entry: AuditEntry): AuditTarget {
  switch (entry.target_type) {
    case TARGET_USERS:
      if (entry.target_email !== null) {
        return {
          kind: "user",
          name: entry.target_display_name ?? entry.target_email,
          email: entry.target_display_name === null ? null : entry.target_email,
        };
      }
      return { kind: "deletedUser", shortId: shortId(entry.target_id ?? "") };
    case TARGET_TIERS:
      return { kind: "tier", name: entry.target_id ?? "" };
    case TARGET_CATALOG:
      return { kind: "catalog" };
    default:
      return { kind: "none" };
  }
}

function isStatus(value: unknown): value is UserStatus {
  return typeof value === "string" && value in STATUS_LABEL;
}

function fieldLabel(field: string): AuditChange["label"] {
  const key = FIELD_LABEL[field];
  return key === undefined ? { raw: field } : { key };
}

/** Mot gia tri JSON cua `details` → chu. Khong lam tron, khong doi kieu tien. */
export function describeValue(value: unknown): AuditValue {
  if (value === null || value === undefined || value === "") {
    return { empty: true };
  }
  if (typeof value === "boolean") {
    return { key: value ? "admin.yes" : "admin.no" };
  }
  if (Array.isArray(value)) {
    return value.length === 0 ? { empty: true } : { text: value.map(String).join(", ") };
  }
  if (typeof value === "object") {
    // Ban ghi de han muc (`limit_override_json`): hien `khoa=gia_tri` tho — day
    // la man cua nguoi van hanh, va ten khoa chinh la thu ho tra trong §10.4.
    const parts = Object.entries(value as Record<string, unknown>).map(
      ([k, v]) => `${k}=${plain(v)}`,
    );
    return parts.length === 0 ? { empty: true } : { text: parts.join(", ") };
  }
  return { text: String(value) };
}

function plain(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (Array.isArray(value)) {
    return `[${value.map(String).join(", ")}]`;
  }
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

const WINDOW_LABEL: Record<LimitKey, TextKey> = {
  limit_5h_usd: "admin.limit.5h",
  limit_7d_usd: "admin.limit.7d",
};

const asRecord = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" ? (value as Record<string, unknown>) : {};

/**
 * Ban T-HD7-v2 muc 1g: hanh dong han muc mang nhan CUA SO no cham toi (5 gio /
 * 7 ngay) thanh the rieng canh nhan hanh dong. Sua tier: truong `limit_*` co
 * trong `changed`; ghi de: khoa `limit_*` cua ban ghi de khac nhau giua cu/moi.
 */
export function limitWindows(entry: AuditEntry): TextKey[] {
  if (entry.action !== "user.update" && entry.action !== "tier.update") {
    return [];
  }
  const changed = asRecord(entry.details?.changed);
  const override = asRecord(changed.limit_override_json);
  const hasOverride = "limit_override_json" in changed;
  return LIMIT_KEYS.filter(
    (field) =>
      field in changed ||
      (hasOverride && asRecord(override.from)[field] !== asRecord(override.to)[field]),
  ).map((field) => WINDOW_LABEL[field]);
}

/** Cac dong "cu → moi" cua mot dong so, theo dung hinh dang `details` cua tung hanh dong. */
export function describeChanges(entry: AuditEntry): AuditChange[] {
  const details = entry.details ?? {};
  switch (entry.action) {
    case "user.approve":
    case "user.reject":
    case "user.suspend": {
      const from = details.from;
      const to = details.to;
      return [
        {
          label: { key: "admin.field.status" },
          from: isStatus(from) ? { key: STATUS_LABEL[from] } : describeValue(from),
          to: isStatus(to) ? { key: STATUS_LABEL[to] } : describeValue(to),
        },
      ];
    }
    case "user.update":
    case "tier.update": {
      const changed = (details.changed ?? {}) as Record<string, { from?: unknown; to?: unknown }>;
      return Object.entries(changed).map(([field, change]) => ({
        label: fieldLabel(field),
        from: describeValue(change.from),
        to: describeValue(change.to),
      }));
    }
    case "catalog.reload":
      return Object.entries(details).map(([field, value]) => ({
        label: fieldLabel(field),
        to: describeValue(value),
      }));
    default:
      return [];
  }
}
