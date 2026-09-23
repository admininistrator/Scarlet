import type { ReactNode } from "react";
import { Navigate } from "react-router";

import { t } from "../lib/i18n";
import { useSession } from "./Layout";
import { PATHS } from "./paths";

/**
 * Cua vao `/admin` — T-3.1a, chuyen nguyen van hanh vi cua `App.tsx` (T-2.19).
 *
 * KH tham chieu: §16.3, §11.2 · tasks.md T-2.19, T-3.1a.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  CHUYEN HUONG LA PHEP LICH SU, KHONG PHAI PHAN QUYEN                   ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Cam bay cua T-2.19 viet nguyen van: *"an menu o FE khong phai phan quyen.
 * Kiem o server la bat buoc (T-2.16 da lam; task nay khong duoc dua vao FE)"*.
 *
 * Component nay day nguoi khong phai admin ra khoi `/admin` de ho khong ngoi
 * nhin mot man hinh toan loi 403. No KHONG dong lo nao: ai bo qua duoc no —
 * go URL truoc khi JS chay, sua state trong DevTools, goi `fetch` tu console
 * — deu gap `require_admin` o tang router cua backend. Do la ly do dong DoD
 * thu hai cua T-2.19 doi HAI phep do chu khong mot: mot cho trinh duyet
 * (chuyen huong) va mot cho `curl` (403 khi ep vao URL).
 *
 * ── Ba nhanh, khong hai ────────────────────────────────────────────────────
 *
 * `loading` phai la nhanh RIENG. Trong lan `GET /auth/me` dau tien, `/admin`
 * chua biet minh co duoc vao hay khong; roi thang xuong nhanh "khong phai
 * admin" se day mot admin that ra khoi trang trong mot phan giay moi lan ho
 * mo `/admin` — dung kieu nhap nhay ma nguoi dung doc thanh "bam nham".
 *
 * Chua dang nhap thi di dang nhap; dang nhap roi ma khong phai admin thi ve
 * man chat. Hai dich khac nhau cho hai tinh huong khac nhau: day mot nguoi
 * da dang nhap toi form dang nhap se moi ho go lai mat khau cho mot thu ma
 * mat khau khong giai quyet duoc.
 *
 * `replace` chu khong mot lan `push`: mot lan chuyen huong tu dong khong
 * duoc de lai dau chan trong lich su, neu khong thi nut Back se dua nguoi
 * dung nguoc ve `/admin` roi bi day ra lan nua — mot cai bay khong thoat
 * duoc bang Back.
 */
export function AdminOnly({ children }: { children: ReactNode }) {
  const session = useSession();

  if (session.loading) {
    return <p className="px-6 py-4 text-sm text-muted">{t("admin.dangTai")}</p>;
  }
  if (session.user === null) {
    return <Navigate to={PATHS.login} replace />;
  }
  if (session.user.role !== "admin") {
    return <Navigate to={PATHS.home} replace />;
  }
  return <>{children}</>;
}
