import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  ChevronsUpDown,
  CircleArrowUp,
  CircleHelp,
  Gauge,
  Languages,
  LogOut,
  Settings,
  type IconNode,
} from "lucide";
import { useCallback, useState } from "react";
import { Link, useNavigate } from "react-router";

import { PATHS } from "../../app/paths";
import type { UserOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { avatarBackground, avatarColorOf, initialOf } from "../ui/avatar";
import { ComingSoon } from "../ui/ComingSoon";
import { NudgeIcon, StaticIcon } from "../ui/Icon";
import { MENU_ITEM_CLASS, MENU_SEPARATOR_CLASS, MenuDismissContext } from "../ui/menu";
import { tierLabel } from "../ui/tierLabel";
import { setDrawerOpen } from "./sidebarOpen";

/**
 * Khoi tai khoan o chan sidebar + menu tai khoan — T-S.12, ban T-HD2-v2 muc D,
 * F, F′, I (`ShellSidebar`, `AccountMenu.tsx`) va T-HD5-v2 muc 6.
 *
 * KH tham chieu: §24.2b·S10, S12 · tasks.md T-S.12, §7b.2 · NQ-115, NQ-116,
 * NQ-117, NQ-128.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  BAY MUC, HAI DUONG KE, DUNG THU TU CUA S10                            ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 *   Cai dat · Muc su dung · Ngon ngu* · Tro giup* · ── · Nang cap goi* · ── · Dang xuat
 *
 * `*` = nut cho `B-264` (bang §7b.2): `ComingSoon` hinh dang `menuItem` —
 * `aria-disabled`, van toi duoc bang mui ten de tooltip "Sap co" mo.
 *
 * ── Khoi tai khoan (ban I) ────────────────────────────────────────────────
 *
 * Cao 72 = 8 + nut 56 + 8, cong duong ke 1 px phia tren; avatar 32, ten
 * 14/20, tier 12/16. Ten la `display_name`, TRONG thi NGUYEN email (NQ-116);
 * mau avatar la ten token nguoi dung chon, chua chon thi hash(user id)
 * (`avatar.ts`, NQ-127 a). Ten do nguoi dung go nen:
 *   - render nhu CHU (React tu thoat ky tu) — khong mot `dangerouslySetInnerHTML`;
 *   - cat bang `truncate` trong mot cot `min-w-0` — ten 200 ky tu khong day
 *     gian sidebar (Cam bay ② cua T-S.12).
 *
 * ── Menu (ban D, F′) ─────────────────────────────────────────────────────
 *
 * Mo LEN tu khoi (`side="top"`), cach 4 px, rong DUNG bang nut
 * (`--radix-dropdown-menu-trigger-width`): 240 o desktop, 304 trong drawer
 * 320 — mot hanh vi cho ca hai be rong. Duoi 1024 px van la popover chu KHONG
 * sheet: drawer da la mot lop modal, sheet se la lop thu hai che mat no (ghi
 * chu cua ban ve canh F′). Chuyen dong la `.motion-menu-up` cua T-HD5-v2 muc 6
 * (ban T-HD2-v2 con ghi `motion-popover` cu — B-305).
 *
 * `DropdownMenu` cua Radix lo ban phim + ARIA: Enter/Space/mui ten xuong mo
 * menu va dat tieu diem vao muc dau, mui ten di giua cac muc, Esc dong va TRA
 * tieu diem ve khoi tai khoan (DoD dong 2).
 *
 * ── Drawer ────────────────────────────────────────────────────────────────
 *
 * Chon Cai dat / Muc su dung / Dang xuat thi dong drawer: `/cai-dat` khong co
 * sidebar, nhung trang thai drawer la mot kho o cap module (`sidebarOpen.ts`),
 * de nguyen `true` thi quay lai `/` drawer tu bat ra. Truoc day `Sidebar` dong
 * drawer bang `onClickCapture` quanh chan sidebar — voi mot menu thi lan bam
 * MO menu cung bi bat, va su kien cua noi dung menu (portal) van noi bot qua
 * cay React toi do.
 */

interface AccountMenuProps {
  user: UserOut;
  /** `avatar_color` cua `/auth/me` — `null` khi chua chon HOAC chua hoi xong. */
  avatarColor: string | null;
  /** `useSessionState().logout` — xoa phien o FE ca khi loi goi mang hong. */
  onLogout: () => Promise<void>;
}

export function AccountMenu({ user, avatarColor, onLogout }: AccountMenuProps) {
  const navigate = useNavigate();
  const shown = user.display_name?.trim() || user.email;
  const color = avatarColorOf(avatarColor, user.id);
  /*
    `open` co kiem soat CHI de dua ham dong xuong muc cho: tooltip cua muc cho
    nhan Esc truoc menu, va phai dong ca menu trong cung lan bam
    (`MenuDismissContext`).
  */
  const [open, setOpen] = useState(false);
  const closeMenu = useCallback(() => setOpen(false), []);

  return (
    <div className="shrink-0 border-t border-border p-2">
      <DropdownMenu.Root open={open} onOpenChange={setOpen}>
        <DropdownMenu.Trigger className="motion-control flex min-h-14 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-foreground hover:bg-surface-hover data-[state=open]:bg-surface-hover">
          <span
            aria-hidden="true"
            className={`grid size-8 shrink-0 place-items-center rounded-full text-base font-semibold text-avatar-foreground ${avatarBackground(color)}`}
          >
            {initialOf(shown)}
          </span>
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-base leading-5 font-semibold">{shown}</span>
            <span className="text-xs leading-4 text-muted">{tierLabel(user.tier_name)}</span>
          </span>
          <StaticIcon icon={ChevronsUpDown} size={16} className="shrink-0 text-muted" />
        </DropdownMenu.Trigger>

        <DropdownMenu.Portal>
          <DropdownMenu.Content
            side="top"
            align="start"
            sideOffset={4}
            // Radix mac dinh gan ten menu = chu cua nut (`aria-labelledby`), tuc
            // "Nguyen Thi An Mien phi"; ban ve dat ten "Menu tai khoan".
            aria-labelledby={undefined}
            aria-label={t("account.menu")}
            className="motion-menu-up z-50 flex w-(--radix-dropdown-menu-trigger-width) flex-col rounded-lg border border-border bg-surface-panel p-1.5 shadow-popover"
          >
            <MenuDismissContext.Provider value={closeMenu}>
              <MenuLink icon={Settings} label={t("account.settings")} to={PATHS.settings} />
              <MenuLink icon={Gauge} label={t("account.usage")} to={PATHS.settingsUsage} />
              <ComingSoon
                menuItem
                planned="B-264"
                label={t("account.language")}
                icon={<NudgeIcon icon={Languages} size={18} />}
              />
              <ComingSoon
                menuItem
                planned="B-264"
                label={t("account.help")}
                icon={<NudgeIcon icon={CircleHelp} size={18} />}
              />
              <DropdownMenu.Separator className={MENU_SEPARATOR_CLASS} />
              <ComingSoon
                menuItem
                planned="B-264"
                label={t("account.upgrade")}
                icon={<NudgeIcon icon={CircleArrowUp} size={18} />}
              />
              <DropdownMenu.Separator className={MENU_SEPARATOR_CLASS} />
              <DropdownMenu.Item
                onSelect={() => {
                  setDrawerOpen(false);
                  void onLogout().then(() => navigate(PATHS.login));
                }}
                className={MENU_ITEM_CLASS}
              >
                <NudgeIcon icon={LogOut} size={18} />
                {t("account.logout")}
              </DropdownMenu.Item>
            </MenuDismissContext.Provider>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  );
}

/**
 * Muc dan toi mot trang — `<a href>` that (mo tab moi, sao chep link van
 * dung); Enter tren muc goi `click()` cua chinh the `a` (Radix).
 *
 * Dong drawer trong `onClick` cua `Link`, KHONG trong `onSelect`: `Link` goi
 * `preventDefault()` truoc khi dieu huong, va Radix bo qua `onSelect` cua
 * mot lan bam da bi `preventDefault`. Menu tu dong vi trang dich khong co
 * sidebar (route doi ⇒ go ca cay).
 */
function MenuLink({ icon, label, to }: { icon: IconNode; label: string; to: string }) {
  return (
    <DropdownMenu.Item asChild className={MENU_ITEM_CLASS}>
      <Link to={to} onClick={() => setDrawerOpen(false)} className="no-underline">
        <NudgeIcon icon={icon} size={18} />
        {label}
      </Link>
    </DropdownMenu.Item>
  );
}
