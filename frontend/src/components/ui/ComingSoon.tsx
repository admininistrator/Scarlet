import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Tooltip from "@radix-ui/react-tooltip";
import { useContext, type ReactNode } from "react";
import { t } from "../../lib/i18n";
import { MENU_ITEM_CLASS, MenuDismissContext, PENDING_MENU_ITEM_CLASS } from "./menu";

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
 * that khi T-6.7 gan. Muc menu cho — hinh dang thu tu, xem doan T-S.12 ben
 * duoi.
 *
 * T-S.11 — nut chu co them `leadingIcon` (icon TRUOC chu, cach 8 px): "Tai anh
 * len" o tab Tai khoan, ban T-HD9 (`SettingsAccount`). Van la nut chu: chu la
 * ten truy cap, icon `aria-hidden` (do `StaticIcon` khong `label`).
 *
 * T-S.12 — hinh dang thu tu `menuItem`: MUC CHO trong mot `DropdownMenu` cua
 * Radix (menu tai khoan; menu hang hoi thoai cua T-S.13 dung lai). Ban
 * T-HD2-v2 (`AccountMenu.tsx`, H6): *"pending → aria-disabled +
 * control-disabled + Tooltip, onSelect preventDefault. Khong dung prop
 * `disabled` cua Radix"* — muc `disabled` cua Radix bi mui ten BO QUA, tuc
 * nguoi dung ban phim khong bao gio toi duoc tooltip (cung Cam bay ④ cua
 * T-S.9, o dang menu). `preventDefault` trong `onSelect` giu menu mo va khong
 * lam gi ca — do la toan bo "hanh vi" cua no. Chi dung ben trong
 * `DropdownMenu.Content`.
 */

type Planned = `${"T" | "B"}-${string}`;

type ComingSoonProps =
  | {
      planned: Planned;
      label: string;
      icon?: undefined;
      toggle?: false;
      leadingIcon?: ReactNode;
      menuItem?: false;
    }
  | {
      planned: Planned;
      label: string;
      icon: ReactNode;
      toggle?: false;
      leadingIcon?: undefined;
      menuItem?: false;
    }
  | {
      planned: Planned;
      label: string;
      icon: ReactNode;
      toggle: true;
      leadingIcon?: undefined;
      menuItem?: false;
    }
  | {
      planned: Planned;
      label: string;
      icon: ReactNode;
      toggle?: false;
      leadingIcon?: undefined;
      menuItem: true;
    };

/**
 * Tooltip cua muc menu cho nam BEN CANH menu, khong de len muc khac (ban
 * T-HD2-v2 H6: tooltip ben trai menu, cach mep menu 6 px). Khoang cach do tu
 * mep MUC: 1 (vien menu) + 6 (dem `p-1.5`) + 6 = 13. Khong du cho ben trai
 * (menu tai khoan o mep trai man hinh) thi Radix tu lat sang phai.
 */
const MENU_TOOLTIP_OFFSET = 13;

const ICON_CLASS =
  "control-disabled inline-flex size-touch shrink-0 items-center justify-center rounded-md text-muted";
const TEXT_CLASS =
  "control-disabled min-h-touch rounded-md border border-border-strong bg-surface-panel px-4 text-base font-medium text-foreground";
const TOGGLE_CLASS =
  "control-disabled inline-flex min-h-touch shrink-0 items-center gap-1.5 rounded-full pr-3 pl-2.5 text-sm font-medium text-muted";

export function ComingSoon({ planned, label, icon, toggle, leadingIcon, menuItem }: ComingSoonProps) {
  const dismissMenu = useContext(MenuDismissContext);

  if (menuItem === true) {
    return (
      <Tooltip.Provider>
        <Tooltip.Root>
          <Tooltip.Trigger asChild>
            <DropdownMenu.Item
              aria-disabled="true"
              data-planned={planned}
              onSelect={(event) => event.preventDefault()}
              className={`${MENU_ITEM_CLASS} ${PENDING_MENU_ITEM_CLASS}`}
            >
              {icon}
              {label}
            </DropdownMenu.Item>
          </Tooltip.Trigger>
          <Tooltip.Portal>
            <Tooltip.Content
              side="left"
              sideOffset={MENU_TOOLTIP_OFFSET}
              // Esc toi tooltip (lop tren cung) truoc menu: dong LUON menu, mot
              // lan bam — xem `MenuDismissContext`. Menu go ⇒ tooltip go theo.
              onEscapeKeyDown={(event) => {
                if (dismissMenu !== null) {
                  event.preventDefault();
                  dismissMenu();
                }
              }}
              className="motion-popover z-50 rounded-md bg-surface-tooltip px-2.5 py-1.5 text-xs text-tooltip-foreground shadow-popover"
            >
              {t("common.comingSoon")}
            </Tooltip.Content>
          </Tooltip.Portal>
        </Tooltip.Root>
      </Tooltip.Provider>
    );
  }

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
