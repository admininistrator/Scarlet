import { Link, Outlet, useNavigate, useOutletContext } from "react-router";

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

  const isAdmin = session.nguoiDung?.role === "admin";

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-semibold">
            <Link to={PATHS.home}>{t("app.title")}</Link>
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
              className="rounded-sm border border-border px-2 py-1 text-sm hover:bg-accent hover:text-accent-foreground"
            >
              {t("admin.tieuDe")}
            </Link>
          )}
        </div>

        <div className="flex items-center gap-3 text-sm">
          {session.nguoiDung === null ? (
            <Link
              to={PATHS.login}
              className="rounded-md border border-border px-3 py-1.5 hover:bg-accent hover:text-accent-foreground"
            >
              {t("auth.dangNhap")}
            </Link>
          ) : (
            <>
              <span className="text-muted">{session.nguoiDung.email}</span>
              <button
                type="button"
                onClick={() => {
                  void session.dangXuat().then(() => navigate(PATHS.home));
                }}
                className="rounded-md border border-border px-3 py-1.5 hover:bg-accent hover:text-accent-foreground"
              >
                {t("auth.dangXuat")}
              </button>
            </>
          )}
          <ThemeToggle />
        </div>
      </header>

      <Outlet context={session} />
    </div>
  );
}
