import type { IconNode } from "lucide";
import { MorphIcon } from "morphicons/react";
import { SPRINGS, type SpringRole } from "../../lib/motion";

/**
 * Icon bien hinh — T-S.9, NQ-117.
 *
 * KH tham chieu: §24.2b·S10 · tasks.md T-S.9, T-3.9 · CLAUDE.md A3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOI `MorphIcon` DI QUA DAY — KHONG MOT CHO NAO IMPORT `morphicons`    ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Tu ban 1.4.2, `morphicons` mac dinh BO QUA cai dat giam chuyen dong cua he
 * dieu hanh (`reducedMotion="never"`) — trai T-3.9. Wrapper nay khoa
 * `reducedMotion="user"`: nguoi dung xin giam thi icon doi tuc thi, khong
 * mot khung hinh trung gian nao. Prop ay KHONG mo ra cho noi goi, de khong ai
 * vo tinh tat no. Cac task sau co dong DoD
 * `grep "from \"morphicons" frontend/src | grep -v components/ui/Icon.tsx` → rong.
 *
 * `icon` la DU LIEU cua goi `lucide` (`import { Menu } from "lucide"`), khong
 * phai component cua `lucide-react` — `morphicons` chi nhan du lieu.
 *
 * `spring` la VAI TRO chu khong phai con so: thong so song o `lib/motion.ts`
 * (ban T-HD5-v2). Bat buoc, vi thieu no thi thu vien roi ve lo xo mac dinh
 * cua chinh no — mot bo so khong ai trong ban ve chon.
 *
 * Khong `label` ⇒ `aria-hidden` (icon trang tri canh chu, hoac trong mot nut
 * da co `aria-label`); co `label` ⇒ `role="img"` + `<title>`.
 */

type IconProps = {
  icon: IconNode;
  spring: SpringRole;
  size?: number;
  strokeWidth?: number;
  className?: string;
  label?: string;
};

export function Icon({ icon, spring, size, strokeWidth, className, label }: IconProps) {
  return (
    <MorphIcon
      icon={icon}
      spring={SPRINGS[spring]}
      reducedMotion="user"
      size={size}
      strokeWidth={strokeWidth}
      className={className}
      label={label}
    />
  );
}

/**
 * Icon KHONG BAO GIO doi hinh — T-S.10 (nut cho, dong han muc, khay tep).
 *
 * Van la `MorphIcon` (S10: moi icon di qua `morphicons` + du lieu `lucide`),
 * nhung khong nhan `spring`: `icon` o day la mot hang so, nen khong co lo xo
 * nao chay de ma chon. Icon nao doi hinh theo trang thai thi dung `Icon` o
 * tren — va khi ay bat buoc khai vai tro lo xo.
 */
export function StaticIcon({ icon, size, strokeWidth, className, label }: Omit<IconProps, "spring">) {
  return (
    <MorphIcon
      icon={icon}
      reducedMotion="user"
      size={size}
      strokeWidth={strokeWidth}
      className={className}
      label={label}
    />
  );
}
