import { useEffect } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { PATHS } from "../../app/paths";
import { t } from "../../lib/i18n";

/**
 * Mot khung cho moi man auth — T-S.16, ban T-HD8 (`AuthLayout`).
 *
 * KH tham chieu: §11.1, §11.6, UC-01 · tasks.md T-S.16, T-3.1b · NQ-108.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  COT NEO O DINH, KHONG CAN GIUA DOC                                    ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Ban ve: *"Cot neo o dinh, cach 96, khong can giua doc, nen di tu Dang nhap
 * sang Dang ky thi tieu de va o dau tien dung yen."* Can giua doc thi hai form
 * cao khac nhau se dat tieu de o hai do cao khac nhau, va moi lan chuyen man
 * ca cot nhay len nhay xuong.
 *
 * ≥ 640 px (`sm:`): the `surface-panel`, vien, `radius-xl`, dem 32 — ban ve tinh
 * long the 400 − 2 × 32 = 336 cho khung Turnstile, nhung vien 1 px moi ben
 * lam long con 334 (B-316, xem `TurnstileSlot`). Duoi 640 px: khong the, le 16,
 * chu Scarlet can trai va dinh cach 12 de tieu de nam cao, chua cho ban phim.
 *
 * Header cua ung dung KHONG ve tren man auth (NQ-131 d) — `Layout` tu an no;
 * chu Scarlet o day la loi ve trang chu duy nhat.
 */
export function AuthLayout({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  useKeyboardInset();
  return (
    <div className="flex min-h-dvh flex-col items-center bg-background px-gutter pt-3 pb-4 sm:px-gutter-lg sm:pt-auth-top sm:pb-12">
      <div className="flex w-full max-w-auth flex-col gap-6">
        <Link
          to={PATHS.home}
          className="inline-flex min-h-touch items-center self-start text-xl font-bold tracking-[-0.01em] text-foreground no-underline hover:text-foreground hover:no-underline sm:self-center"
        >
          {t("app.title")}
        </Link>
        <main className="sm:rounded-xl sm:border sm:border-border sm:bg-surface-panel sm:p-8 sm:shadow-sm">
          {children}
        </main>
        {footer}
      </div>
    </div>
  );
}

/** Lien ket phu duoi the — "Chua co tai khoan? Dang ky", "Quay lai dang nhap". */
export function AuthFooterLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="inline-flex min-h-touch items-center self-center text-base font-medium">
      {children}
    </Link>
  );
}

/**
 * Hang nut chinh. < 640 px: dinh mep tren ban phim ao. ≥ 640 px: nam yen
 * trong the.
 *
 * Ban ve K: *"Khi form ngan hon man hinh, no nam yen ngay duoi o cuoi. Khi ban
 * phim che nua duoi, no dinh len mep tren ban phim."* Nen trang, de chu cuon
 * phia duoi khong lo qua.
 */
export function AuthActions({ children }: { children: ReactNode }) {
  return (
    <div className="sticky bottom-(--keyboard-inset) z-10 bg-background py-3 sm:static sm:bg-transparent sm:p-0">
      {children}
    </div>
  );
}

/**
 * Do cao ban phim ao -> `--keyboard-inset` tren `<html>`.
 *
 * Android: `interactive-widget=resizes-content` (index.html, T-3.10) da co khung
 * nhin lai, nen o do gia tri nay la 0. iOS khong co, nen phai doc
 * `visualViewport`: phan khung nhin bo cuc bi ban phim che = `innerHeight −
 * vv.height − vv.offsetTop`.
 */
export function useKeyboardInset() {
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) {
      return undefined;
    }
    const root = document.documentElement;
    const update = () =>
      root.style.setProperty(
        "--keyboard-inset",
        `${Math.max(0, window.innerHeight - vv.height - vv.offsetTop)}px`,
      );
    update();
    vv.addEventListener("resize", update);
    vv.addEventListener("scroll", update);
    return () => {
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
      root.style.removeProperty("--keyboard-inset");
    };
  }, []);
}
