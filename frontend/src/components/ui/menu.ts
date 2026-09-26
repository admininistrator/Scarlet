/**
 * Menu tha xuong dung chung — T-S.12: lop cua mot MUC va mot DUONG KE, va
 * `MenuDismissContext` (ham dong menu cho muc cho).
 *
 * KH tham chieu: §24.2b·S10, S12 · ban T-HD2-v2 muc D, F′, H6 (`ShellSidebar`,
 * `AccountMenu.tsx`).
 *
 * Mot cho cho hai noi dung chung: muc thuong cua menu tai khoan va muc CHO
 * (`ComingSoon` hinh dang `menuItem`). Hai noi giu hai chuoi thi mot ngay nao
 * do muc cho cao 40 con muc thuong cao 44 — dung loai lech ma T-S.18 phai di
 * tim. Menu hang hoi thoai (T-S.13) doc cung file nay.
 *
 * Ban ve: muc cao 44 (`min-h-touch`), dem ngang 10, icon cach chu 12, chu 14;
 * muc dang chon nen `surface-hover` (Radix dat `data-highlighted` cho muc giu
 * tieu diem, ca khi re chuot). Duong ke 1 px mau `divider`, cach hai ben 4 va
 * tren duoi 6.
 */

import { createContext } from "react";

/**
 * Ham DONG menu dang chua muc — nguoi so huu menu (dang `open` co kiem soat)
 * cung cap; muc cho (`ComingSoon` `menuItem`) doc no.
 *
 * Vi sao can: tooltip "Sap co" cua muc cho la mot LOP rieng cua Radix
 * (`DismissableLayer`), va Esc chi toi lop TREN CUNG. Khong co ham nay thi
 * khi tieu diem dang o mot muc cho (tooltip mo — dung ban T-HD2-v2 H6), Esc
 * dau chi dong tooltip, menu van mo; phai Esc lan hai — trai DoD dong 2 cua
 * T-S.12 ("Esc dong va tra tieu diem ve khoi tai khoan"). `null` = khong ai
 * cung cap ⇒ tooltip xu ly Esc theo mac dinh cua Radix.
 */
export const MenuDismissContext = createContext<(() => void) | null>(null);

const MENU_ITEM_BASE =
  "motion-control flex min-h-touch items-center gap-3 rounded-md px-2.5 text-base outline-none data-highlighted:bg-surface-hover";

export const MENU_ITEM_CLASS = `${MENU_ITEM_BASE} text-foreground`;

/**
 * T-S.13 — muc NGUY HIEM ("Xoa" cua menu hang hoi thoai, ban T-HD2-v2 H6):
 * chu va icon (`currentColor`) mau `danger-text`. Mot hang rieng chu khong
 * noi them `text-danger-text` vao `MENU_ITEM_CLASS`: hai tien ich mau tren
 * cung phan tu thi cai thang la cai dung SAU trong CSS da bien dich, khong
 * phai cai viet sau trong `className`.
 */
export const MENU_ITEM_DANGER_CLASS = `${MENU_ITEM_BASE} text-danger-text`;

/**
 * Them cho muc CHO: mo `--disabled-opacity`, va khi toi bang ban phim thi hien
 * ro lai kem vong focus ke trong (ban T-HD2-v2 H6: *"nut cho hien ro lai, vong
 * focus du dam, tooltip mo"* — `control-disabled` lo phan do mo).
 */
export const PENDING_MENU_ITEM_CLASS =
  "control-disabled focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring";

export const MENU_SEPARATOR_CLASS = "mx-1 my-1.5 h-px bg-divider";
