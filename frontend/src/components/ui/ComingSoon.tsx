import * as Tooltip from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";
import { t } from "../../lib/i18n";

/**
 * Nut cho cua P4–P9 — T-S.9, ban T-HD1-v2 (muc 13 "Nut cho"), NQ-121.
 *
 * KH tham chieu: §24.2b·S12 · tasks.md §7b.2 (bang nut cho), T-S.9.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  TRONG NHU NUT THAT O TRANG THAI KHOA — VA KHONG LAM GI CA            ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * - **`aria-disabled="true"`, KHONG `disabled`.** Phan tu `disabled` khong
 *   nhan focus va khong phat su kien, nen tooltip "Sap co" se khong bao gio
 *   toi duoc nguoi dung ban phim (Cam bay ④ cua T-S.9). Con tro `not-allowed`
 *   va do mo `--disabled-opacity` den tu `theme.css` (luat `@layer base` +
 *   tien ich `control-disabled`), khong tu dat o day.
 * - **Khong nhan `onClick`** — kieu props khong co khoa ay, va component khong
 *   trai phan con lai xuong `<button>`, nen mot `onClick` lot qua bang cach ep
 *   kieu cung roi xuong dat. `type="button"` de nam trong mot `<form>` thi
 *   bam cung khong gui form.
 * - **`planned` bat buoc** ⇒ `data-planned`: ID task se gan nut nay (bang
 *   §7b.2). Agent cua phase sau `grep data-planned` ra dung cho.
 * - **Tooltip "Sap co" KHONG ghi phase hay ngay** (NQ-121 · 15a).
 *
 * Hai hinh dang cua ban ve: co `icon` ⇒ nut icon vuong 44 px, `label` thanh
 * `aria-label`; khong `icon` ⇒ nut chu co vien, `label` la chu hien ra. Muc
 * menu cho (menu tai khoan, menu hang hoi thoai) can `DropdownMenu` cua Radix
 * — goi chua cai; task dung menu ay (T-S.12, T-S.13) them hinh dang thu ba.
 */

type Planned = `${"T" | "B"}-${string}`;

type ComingSoonProps = {
  planned: Planned;
  label: string;
  icon?: ReactNode;
};

const ICON_CLASS =
  "control-disabled inline-flex size-touch items-center justify-center rounded-md text-muted";
const TEXT_CLASS =
  "control-disabled min-h-touch rounded-md border border-border-strong bg-surface-panel px-4 text-base font-medium text-foreground";

export function ComingSoon({ planned, label, icon }: ComingSoonProps) {
  const iconOnly = icon !== undefined;
  return (
    <Tooltip.Provider>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button
            type="button"
            aria-disabled="true"
            aria-label={iconOnly ? label : undefined}
            data-planned={planned}
            className={iconOnly ? ICON_CLASS : TEXT_CLASS}
          >
            {iconOnly ? icon : label}
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content className="motion-popover z-50 rounded-md bg-surface-tooltip px-2.5 py-1.5 text-xs text-tooltip-foreground shadow-popover">
            {t("common.comingSoon")}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
