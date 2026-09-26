import * as Tooltip from "@radix-ui/react-tooltip";
import type { ReactElement } from "react";

/**
 * Tooltip cua bong bong — ban T-HD3-v2 (`MessageBubble.tsx`, `Hint`), T-S.15.
 *
 * Thay cho `title` cua ban T-3.7: `title` khong mo bang ban phim va khong noi
 * duoc voi nut qua `aria-describedby`. Radix gan `aria-describedby` vao nut
 * luc tooltip mo — ban ve 3b: *"`aria-label` 'Thu lai', tooltip noi qua
 * `aria-describedby`"* — nen nguoi dung screen reader nghe CA ten nut lan cau
 * "Tao lai bang model dang chon" (Cam bay ① cua T-S.15).
 *
 * `Provider` rieng, cung cach `ComingSoon`: bong bong khong nam duoi mot
 * `Tooltip.Provider` chung nao. Lop tooltip giong het `ComingSoon` (chu 12,
 * nen `surface-tooltip`, `z-50`) — hai noi hai lop thi mot ngay nao do lech.
 */
export function Hint({
  label,
  side = "top",
  children,
}: {
  label: string;
  side?: "top" | "left";
  /** Mot phan tu nhan ref (nut) — `Tooltip.Trigger asChild`. */
  children: ReactElement;
}) {
  return (
    <Tooltip.Provider>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            side={side}
            sideOffset={8}
            className="motion-popover z-50 rounded-md bg-surface-tooltip px-2.5 py-1.5 text-xs text-tooltip-foreground shadow-popover"
          >
            {label}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
