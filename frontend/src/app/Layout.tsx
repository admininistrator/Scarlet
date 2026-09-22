import { Link, Outlet, useLocation, useNavigate, useOutletContext } from "react-router";

import { SidebarToggle } from "../components/sidebar/SidebarToggle";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { usePhien, type Phien } from "../features/auth/usePhien";
import { t } from "../lib/i18n";
import { PATHS } from "./paths";

/**
 * Layout shell — header + vung noi dung. T-3.1a.
 *
 * KH tham chieu: §16.3 · tasks.md T-3.1a, T-2.19.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  PHIEN DUOC HOI MOT LAN, O DAY                                         ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `usePhien()` goi `GET /auth/me` luc mount. Goi no trong tung man hinh se
 * cho N loi goi cho mot cau hoi, va te hon: hai man hinh co the doc hai cau
 * tra loi khac nhau trong cung mot lan xem. Nen no duoc hoi MOT lan o day
 * roi day xuong qua `Outlet context`, va cac route con lay lai bang
 * `useSession()`.
 *
 * Vi sao `useOutletContext` chu khong mot React Context tu dung: day dung la
 * co che React Router sinh ra cho quan he layout → route con, nen no khong
 * them mot khai niem nao vao dau nguoi doc file nay. Neu sau nay co thanh
 * phan nam SAU mot route con can phien (ung vien gan nhat: thanh quota cua
 * T-3.11), luc do hay dung mot Context that — va doi ca cum mot lan, chu
 * dung de hai duong cung song.
 */
export function useSession(): Phien {
  return useOutletContext<Phien>();
}

export function Layout() {
  const session = usePhien();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const isAdmin = session.nguoiDung?.role === "admin";
  /*
    T-3.3 / T-HD2 — nut bat/tat sidebar song o HEADER, khong trong sidebar
    ("sidebar dong = 0 px, khong co dai icon"). Nhung header nay boc ca
    `/admin` va sau man auth, va o do khong co sidebar nao de bat/tat — nen nut
    chi hien tren duong co sidebar. T-3.10: duoi 1024 px cung nut nay mo
    drawer thay vi day cot — xem `SidebarToggle`.
  */
  const coSidebar = pathname === PATHS.home;

  return (
    /*
      Khung cao DUNG man hinh (`h-dvh`, ban T-HD2 `AppShell.tsx`): header
      `shrink-0` dung yen o dinh, va thanh cuon nam O TRONG vung noi dung chu
      khong o `window`. Man chat tu chia tiep (sidebar · tin nhan · o nhap) va
      chi cot tin nhan cuon; cac man khac (`/admin`, man auth) cuon ca vung
      duoi header. `dvh` chu khong `vh`: tren iOS `vh` tinh ca thanh dia chi.
    */
    <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      {/*
        T-3.10 — header cao DUNG `--spacing-header` (56 px) o moi be rong, nhu
        ban T-HD2 ghi ("ca desktop lan mobile"): KHONG `flex-wrap`, vi xuong
        dong o 375 px la mot header 143 px an mat mot phan tu man chat (B-242).
        De vua 375 px: email chi hien tu `sm` tro len (nut Dang xuat van o
        do), va lề ngang theo token gutter cua T-HD2. Moi thu bam duoc cao
        `min-h-touch` (44 px).
      */}
      <header className="flex h-header shrink-0 items-center justify-between gap-2 border-b border-border px-gutter lg:px-gutter-lg">
        <div className="flex min-w-0 items-center gap-2 sm:gap-4">
          {coSidebar && <SidebarToggle />}
          <h1 className="text-lg font-semibold">
            <Link to={PATHS.home} className="inline-flex min-h-touch items-center">
              {t("app.title")}
            </Link>
          </h1>
          {/*
            An nut nay khi khong phai admin la mot phep lich su voi nguoi
            dung, KHONG phai phan quyen — cung cau ma `AdminOnly` va
            `AdminScreen` deu chep lai. Lop chan that la `require_admin` o
            tang router cua backend (T-2.16).
          */}
          {isAdmin && (
            <Link
              to={PATHS.admin}
              className="inline-flex min-h-touch items-center whitespace-nowrap rounded-md border border-border px-2 text-sm sm:px-3 hover:bg-accent hover:text-accent-foreground"
            >
              {t("admin.tieuDe")}
            </Link>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2 text-sm sm:gap-3">
          {session.nguoiDung === null ? (
            <Link
              to={PATHS.login}
              className="motion-press inline-flex min-h-touch items-center rounded-md border border-border px-3 hover:bg-accent hover:text-accent-foreground"
            >
              {t("auth.dangNhap")}
            </Link>
          ) : (
            <>
              <span className="hidden truncate text-muted sm:inline">
                {session.nguoiDung.email}
              </span>
              <button
                type="button"
                onClick={() => {
                  void session.dangXuat().then(() => navigate(PATHS.home));
                }}
                className="motion-press min-h-touch whitespace-nowrap rounded-md border border-border px-2 sm:px-3 hover:bg-accent hover:text-accent-foreground"
              >
                {t("auth.dangXuat")}
              </button>
            </>
          )}
          <ThemeToggle />
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <Outlet context={session} />
      </div>
    </div>
  );
}
