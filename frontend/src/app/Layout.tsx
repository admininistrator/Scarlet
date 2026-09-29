import { PanelRight, Shield } from "lucide";
import { Link, Outlet, useLocation, useOutletContext } from "react-router";

import { SidebarToggle } from "../components/sidebar/SidebarToggle";
import { ComingSoon } from "../components/ui/ComingSoon";
import { StaticIcon } from "../components/ui/Icon";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { useSessionState, type SessionState } from "../features/auth/useSessionState";
import { t } from "../lib/i18n";
import { useDrawerMode } from "../lib/viewport";
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
 * `useSessionState()` goi `GET /auth/me` luc mount. Goi no trong tung man hinh se
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
export function useSession(): SessionState {
  return useOutletContext<SessionState>();
}

/** Sau duong auth cua T-3.1b — ve bang `AuthLayout`, khong header (T-S.16). */
const AUTH_PATHS: ReadonlySet<string> = new Set([
  PATHS.login,
  PATHS.register,
  PATHS.forgotPassword,
  PATHS.resetPassword,
  PATHS.verifyEmail,
  PATHS.pendingApproval,
]);

export function Layout() {
  const session = useSessionState();
  const { pathname } = useLocation();
  const drawerMode = useDrawerMode();

  const isAdmin = session.user?.role === "admin";
  /*
    T-3.3 / T-HD2 — nut bat/tat sidebar song o HEADER, khong trong sidebar
    ("sidebar dong = 0 px, khong co dai icon"). Nhung header nay boc ca
    `/admin` va sau man auth, va o do khong co sidebar nao de bat/tat — nen nut
    chi hien tren duong co sidebar. T-3.10: duoi 1024 px cung nut nay mo
    drawer thay vi day cot — xem `SidebarToggle`.

    T-S.12 — nut cho "Mo panel artifact" (T-5.4) theo CUNG dieu kien, cong
    phien da dang nhap: panel artifact mo canh hoi thoai, con `/admin`,
    `/cai-dat` khong co hoi thoai nao (NQ-128 c).
  */
  const hasSidebar = pathname === PATHS.home;
  /*
    T-S.16 — ban T-HD8 ve sau man auth KHONG co header: chu Scarlet nam trong
    cot form va la loi ve trang chu duy nhat (NQ-131 d). Man "bi khoa" cung
    vay — no hien o bat ky duong nao `StatusGate`/`SignedInOnly` canh, nen
    hoi `session.locked` chu khong hoi duong. Nut sang/toi vi vay khong co o
    day; theme van theo lua chon da luu hoac theo he thong (index.html).
  */
  const bare = AUTH_PATHS.has(pathname) || session.locked;

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
        Moi thu bam duoc la o 44 × 44 (`size-touch`/`h-touch`).

        T-S.12 — header v2 (ban T-HD2-v2 `ShellHeader`, NQ-115, NQ-128 b): KHONG
        con email lan nut Dang xuat — hai loi ay doi xuong menu tai khoan o
        chan sidebar (`AccountMenu`), va o `/admin`, `/cai-dat` (khong sidebar)
        la tab Tai khoan cua Cai dat. Dung them lai chung vao day "cho tien"
        (Cam bay ① cua T-S.12). Con lai: nut sidebar · ten app | Quan tri ·
        sang/toi · nut cho panel artifact, nen `surface-panel`, le 8 (desktop)
        / 6 (mobile), nhom phai sat mep phai.
      */}
      {!bare && (
        <header className="flex h-header shrink-0 items-center gap-1 border-b border-border bg-surface-panel px-1.5 lg:gap-2 lg:px-2">
          {hasSidebar && <SidebarToggle />}
          <h1 className="text-lg font-semibold lg:tracking-[-0.01em]">
            <Link to={PATHS.home} className="inline-flex min-h-touch items-center text-foreground no-underline">
              {t("app.title")}
            </Link>
          </h1>

          <div className="ml-auto flex shrink-0 items-center gap-0.5 lg:gap-1">
            {/*
              An nut nay khi khong phai admin la mot phep lich su voi nguoi
              dung, KHONG phai phan quyen — cung cau ma `AdminOnly` va
              `AdminScreen` deu chep lai. Lop chan that la `require_admin` o
              tang router cua backend (T-2.16).

              Ban T-HD2-v2: desktop la chu "Quan tri" mau accent-text, mobile la
              icon `shield` (cung ten truy cap). Chon bang `useDrawerMode` chu
              khong bang hai phan tu an/hien bang CSS: mot link, mot ten.
            */}
            {isAdmin &&
              (drawerMode ? (
                <Link
                  to={PATHS.admin}
                  aria-label={t("admin.tieuDe")}
                  className="grid size-touch place-items-center rounded-md text-accent-text hover:bg-surface-hover"
                >
                  <StaticIcon icon={Shield} size={20} />
                </Link>
              ) : (
                <Link
                  to={PATHS.admin}
                  className="inline-flex h-touch items-center whitespace-nowrap rounded-md px-3 text-base font-medium text-accent-text no-underline hover:bg-surface-hover"
                >
                  {t("admin.tieuDe")}
                </Link>
              ))}
            {session.user === null && (
              <Link
                to={PATHS.login}
                className="motion-press inline-flex min-h-touch items-center rounded-md border border-border px-3 text-sm hover:bg-accent hover:text-accent-foreground"
              >
                {t("auth.dangNhap")}
              </Link>
            )}
            <ThemeToggle />
            {hasSidebar && session.user !== null && (
              <ComingSoon
                planned="T-5.4"
                label={t("header.artifactPanel")}
                icon={<StaticIcon icon={PanelRight} size={20} />}
              />
            )}
          </div>
        </header>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        <Outlet context={session} />
      </div>
    </div>
  );
}
