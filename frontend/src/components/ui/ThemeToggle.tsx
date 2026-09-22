import { useEffect, useState } from "react";
import { t } from "../../lib/i18n";

/**
 * Nut chuyen sang/toi — T-0.10, sua o T-3.2.
 *
 * KH tham chieu: §19.1 · tasks.md T-0.10, T-3.2 · CLAUDE.md A3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  "MAC DINH THEO HE DIEU HANH" PHAI SONG TRONG COMPONENT                ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Truoc T-3.2, `readTheme()` doc thuoc tinh `data-theme` ma doan script trong
 * `index.html` da dat san. Doc nhu the thi component LUON dung — va luon dung
 * vi mot ly do khong thuoc ve no: doan script chay truoc. Go doan script di
 * (hay render component nay trong mot trang khong co no, vi du mot test) thi
 * "mac dinh theo he dieu hanh" bien mat khong mot tieng dong.
 *
 * Nay component tu tra loi cau hoi ay tu HAI nguon that su:
 *
 *     localStorage["scarlet-theme"]   lua chon nguoi dung da bam
 *     prefers-color-scheme            he dieu hanh, khi chua ai bam gi
 *
 * Doan script trong `index.html` VAN o lai va VAN doc dung hai nguon do. No
 * khong phai ban sao thua: no chay truoc khi React mount, tuc no la thu chan
 * mot nhay trang trang (FOUC) o lan tai dau tien. Hai cho, mot cong thuc —
 * `themeBanDau()` duoi day la ban chuan, doan script la ban rut gon khong
 * import duoc vi no phai chay truoc ca bundle.
 *
 * ── Vi sao moi phep doc deu boc `try/catch` hoac `?.` ────────────────────
 *
 * `localStorage` nem `SecurityError` o che do rieng tu (da co tu T-0.10), va
 * `window.matchMedia` KHONG ton tai trong jsdom. Ca hai deu la "moi truong
 * thieu mot thu", va ca hai deu phai roi ve `light` chu khong lam vo app.
 */

type Theme = "light" | "dark";

const KHOA_LUU = "scarlet-theme";
const TRUY_VAN_TOI = "(prefers-color-scheme: dark)";

function themeDaLuu(): Theme | null {
  try {
    const luu = localStorage.getItem(KHOA_LUU);
    return luu === "light" || luu === "dark" ? luu : null;
  } catch {
    // che do rieng tu co the chan localStorage — coi nhu chua ai bam gi
    return null;
  }
}

function themeHeDieuHanh(): Theme {
  // `window.matchMedia` vang mat trong jsdom va trong vai WebView cu.
  return window.matchMedia?.(TRUY_VAN_TOI).matches ? "dark" : "light";
}

/** Lua chon da luu thang he dieu hanh; khong co ca hai thi sang. */
export function themeBanDau(): Theme {
  return themeDaLuu() ?? themeHeDieuHanh();
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(themeBanDau);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(KHOA_LUU, theme);
    } catch {
      // che do rieng tu co the chan localStorage — bo qua, khong lam vo app
    }
  }, [theme]);

  const nextLabel = theme === "dark" ? t("theme.light") : t("theme.dark");

  return (
    <button
      type="button"
      aria-label={t("theme.toggleLabel")}
      onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
      className="motion-press rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground hover:bg-accent hover:text-accent-foreground"
    >
      {nextLabel}
    </button>
  );
}
