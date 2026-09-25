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
 * Ba hinh dang cua ban ve: co `icon` ⇒ nut icon vuong 44 px, `label` thanh
 * `aria-label`; khong `icon` ⇒ nut chu co vien, `label` la chu hien ra; co
 * `icon` VA `toggle` ⇒ cong tac vien thuoc icon + chu (T-S.10, "Tim web" o o
 * nhap — ban T-HD2-v2 muc G), `aria-pressed="false"` vi no se la mot cong tac
 * that khi T-6.7 gan. Muc menu cho (menu tai khoan, menu hang hoi thoai) can
 * `DropdownMenu` cua Radix — goi chua cai; task dung menu ay (T-S.12, T-S.13)
 * them hinh dang thu tu.
 *
 * T-S.11 — nut chu co them `leadingIcon` (icon TRUOC chu, cach 8 px): "Tai anh
 * len" o tab Tai khoan, ban T-HD9 (`SettingsAccount`). Van la nut chu: chu la
 * ten truy cap, icon `aria-hidden` (do `StaticIcon` khong `label`).
 */

type Planned = `${"T" | "B"}-${string}`;

type ComingSoonProps =
  | { planned: Planned; label: string; icon?: undefined; toggle?: false; leadingIcon?: ReactNode }
  | { planned: Planned; label: string; icon: ReactNode; toggle?: false; leadingIcon?: undefined }
  | { planned: Planned; label: string; icon: ReactNode; toggle: true; leadingIcon?: undefined };

const ICON_CLASS =
  "control-disabled inline-flex size-touch shrink-0 items-center justify-center rounded-md text-muted";
const TEXT_CLASS =
  "control-disabled min-h-touch rounded-md border border-border-strong bg-surface-panel px-4 text-base font-medium text-foreground";
const TOGGLE_CLASS =
  "control-disabled inline-flex min-h-touch shrink-0 items-center gap-1.5 rounded-full pr-3 pl-2.5 text-sm font-medium text-muted";

export function ComingSoon({ planned, label, icon, toggle, leadingIcon }: ComingSoonProps) {
  const iconOnly = icon !== undefined && toggle !== true;
  return (
    <Tooltip.Provider>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button
            type="button"
            aria-disabled="true"
            aria-label={iconOnly ? label : undefined}
            aria-pressed={toggle === true ? false : undefined}
            data-planned={planned}
            className={
              toggle === true
                ? TOGGLE_CLASS
                : iconOnly
                  ? ICON_CLASS
                  : leadingIcon === undefined
                    ? TEXT_CLASS
                    : `${TEXT_CLASS} inline-flex items-center gap-2`
            }
          >
            {toggle === true ? (
              <>
                {icon}
                {label}
              </>
            ) : iconOnly ? (
              icon
            ) : (
              <>
                {leadingIcon}
                {label}
              </>
            )}
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
