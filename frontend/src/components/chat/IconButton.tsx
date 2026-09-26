import type { IconNode } from "lucide";

import { StaticIcon } from "../ui/Icon";
import { Hint } from "./Hint";

/**
 * Nut vuong 44 x 44 mang mot icon Lucide — ban T-HD3 / T-HD3-v2 (`IconAction`),
 * dung o hai cho.
 *
 * Hai cho do la `BranchNav` (`‹ n/m ›`, T-1.14/T-3.8) va hang nut duoi cau
 * tra loi (`AnswerActions`, T-3.7). Ban thiet ke ve chung bang **mot**
 * component, va o day cung vay: 44 px la con so cua danh sach kiem T-HD3
 * ("moi nut trong artboard 375 px do duoc ≥ 44 px"), nen mot ban chep thu hai
 * la mot cho de no tut xuong 40 mà khong ai thay.
 *
 * `pressed` la trang thai BAT/TAT cua Thich va Khong thich. No di ra DOM bang
 * `aria-pressed`, tuc screen reader doc duoc "da bam" — mau nen khong noi
 * duoc dieu do. `undefined` (khong phai `false`) o nhung nut khong co trang
 * thai bat/tat, de React bo han thuoc tinh thay vi khai `aria-pressed="false"`
 * cho mot mui ten dieu huong.
 *
 * T-S.15 (ban T-HD3-v2): ky tu (`⧉ ↑ ↓ ↻ ‹ ›`) thanh icon net Lucide qua
 * `StaticIcon` (S10 — moi icon di qua `morphicons`); `title` thanh tooltip
 * Radix (`Hint`) — `hint` vang mat thi tooltip la chinh `label`, nhu ban ve.
 */
export function IconButton({
  label,
  icon,
  onClick,
  pressed,
  disabled,
  hint,
}: {
  label: string;
  /** Du lieu icon cua goi `lucide` (`import { Copy } from "lucide"`). */
  icon: IconNode;
  onClick: () => void;
  pressed?: boolean;
  disabled?: boolean;
  /** Chu cua tooltip, khi no can noi nhieu hon `label`. */
  hint?: string;
}) {
  return (
    <Hint label={hint ?? label}>
      <button
        type="button"
        // `() => onClick()` chu khong `onClick={onClick}`: React truyen
        // `MouseEvent` lam tham so dau, nen mot handler khai `() => void` van
        // NHAN mot doi so luc chay — va `onRetry(messageId)` o ben goi se doc
        // ca su kien ay thanh mot tham so. Mot lop bao ve mot dong.
        onClick={() => onClick()}
        disabled={disabled}
        aria-label={label}
        aria-pressed={pressed}
        className={
          pressed === true
            ? "motion-press grid size-touch place-items-center rounded-md border border-accent bg-accent-subtle text-accent-text"
            : "motion-press control-disabled grid size-touch place-items-center rounded-md border border-transparent text-muted hover:bg-surface-hover hover:text-foreground disabled:text-disabled-foreground"
        }
      >
        <StaticIcon icon={icon} size={18} className="motion-icon" />
      </button>
    </Hint>
  );
}
