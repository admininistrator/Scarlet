import { t } from "../../lib/i18n";
import { useDrawerMode } from "../../lib/viewport";
import { PanelIcon } from "./icons";
import {
  SIDEBAR_TOGGLE_ID,
  setDrawerOpen,
  toggleSidebar,
  useDrawerOpen,
  useSidebarOpen,
} from "./sidebarOpen";

/**
 * Nut bat/tat sidebar o header — T-3.3 (T-HD2), tach ra file rieng o T-3.10.
 *
 * Mot nut, hai trang thai: tren 1024 px no bat/tat cot sidebar (nho qua F5),
 * duoi 1024 px no MO drawer. Drawer dong bang Esc, bang cham ra ngoai hoac
 * bang nut dong cua chinh no — nut nay nam SAU lop phu nen khong bam duoc luc
 * drawer dang mo, va `aria-expanded` van noi dung trang thai cho trinh doc.
 *
 * Tach khoi `app/Layout.tsx` de `Drawer.test.tsx` dung duoc DUNG nut that ma
 * khong phai dung ca phien dang nhap + router.
 */
export function SidebarToggle() {
  const drawerMode = useDrawerMode();
  const sidebarOpen = useSidebarOpen();
  const drawerOpen = useDrawerOpen();
  const expanded = drawerMode ? drawerOpen : sidebarOpen;

  return (
    <button
      id={SIDEBAR_TOGGLE_ID}
      type="button"
      onClick={() => (drawerMode ? setDrawerOpen(!drawerOpen) : toggleSidebar())}
      aria-expanded={expanded}
      aria-label={expanded ? t("header.closeSidebar") : t("header.openSidebar")}
      className="motion-press grid size-touch shrink-0 place-items-center rounded-md text-foreground hover:bg-surface-hover"
    >
      <PanelIcon />
    </button>
  );
}
