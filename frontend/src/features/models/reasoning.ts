/**
 * Muc suy luan (Thinking Effort) hieu luc cua mot model — T-S.14.
 *
 * KH tham chieu: §24.2b·S3b, S4, S11 · NQ-118 · tasks.md T-S.14 (Cam bay ②).
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MUC DA NHO CUA MODEL NAY ＞ `reasoning.default` CUA CATALOG           ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Day la hai tang duoi cua thu tu thang o S4 (body › da nho › catalog). Tang
 * tren cung — body — la chinh gia tri ham nay tra ve: FE gui DUNG muc dang
 * hien tren picker, nen thu nguoi dung thay va thu model nhan la mot.
 *
 * Mot ham thuan, mot cho, vi hai nguoi doc phai ra cung mot dap an: `useChat`
 * dat no vao `reasoning_effort` cua lan gui, `ModelPicker` in no ben phai hang
 * Thinking Effort. Hai phep tinh roi nhau la mot man hinh ghi "High" va mot
 * request gui "low".
 *
 * Cam bay ② — muc NHO THEO MODEL: `prefs` la `{model_id: level}` cua
 * `/auth/me`, va ham nay chi doc o cua CHINH model duoc hoi. Doi model thi
 * gia tri doi theo model moi; khong co "muc dang chon" nao song rieng de bi
 * mang sang.
 */

import type { ModelOut } from "../../lib/api";
import { t, type TextKey } from "../../lib/i18n";

/**
 * Bo tu vung CO DINH cua S3b → khoa `vi.json`. Nhan tieng Anh (NQ-118) song
 * trong `vi.json`, khong trong catalog va khong o day.
 */
const LEVEL_LABELS: Record<string, TextKey> = {
  off: "model.effortLevel.off",
  low: "model.effortLevel.low",
  medium: "model.effortLevel.medium",
  high: "model.effortLevel.high",
  xhigh: "model.effortLevel.xhigh",
  max: "model.effortLevel.max",
};

/**
 * Muc model se chay o lan gui ke tiep, hoac `null` khi model khong co khoi
 * `reasoning` (hoac chua biet model nao).
 *
 * Muc da nho ma khong con trong `options` (catalog vua bot mot muc) bi BO QUA
 * va roi ve mac dinh — `/auth/me` da loc mot lan theo catalog luc doc, nhung
 * catalog sua nong duoc giua hai lan doc (cung ly do Cam bay ① cua T-3.6).
 */
export function effectiveEffort(
  model: ModelOut | undefined,
  prefs: Readonly<Record<string, string>>,
): string | null {
  const reasoning = model?.reasoning ?? null;
  if (model === undefined || reasoning === null) {
    return null;
  }
  const remembered = prefs[model.id];
  if (remembered !== undefined && reasoning.options.some((o) => o.id === remembered)) {
    return remembered;
  }
  return reasoning.default;
}

/** Nhan hien thi cua mot muc. `id` la (ngoai bo tu vung) hien nguyen chuoi. */
export function effortLabel(level: string): string {
  const key = LEVEL_LABELS[level];
  return key === undefined ? level : t(key);
}
