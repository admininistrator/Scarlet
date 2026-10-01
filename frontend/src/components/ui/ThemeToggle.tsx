import { Moon, Sun } from "lucide";
import { useCallback, useEffect, useState } from "react";
import { t } from "../../lib/i18n";
import { Icon } from "./Icon";

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
 * `initialTheme()` duoi day la ban chuan, doan script la ban rut gon khong
 * import duoc vi no phai chay truoc ca bundle.
 *
 * ── Vi sao moi phep doc deu boc `try/catch` hoac `?.` ────────────────────
 *
 * `localStorage` nem `SecurityError` o che do rieng tu (da co tu T-0.10), va
 * `window.matchMedia` KHONG ton tai trong jsdom. Ca hai deu la "moi truong
 * thieu mot thu", va ca hai deu phai roi ve `light` chu khong lam vo app.
 */

export type Theme = "light" | "dark";
/**
 * T-S.11 (ban T-HD9 B) — lua chon DA LUU: mot theme co dinh, hoac `system` =
 * theo he dieu hanh. `system` KHONG co gia tri nao trong `localStorage`: vang
 * khoa chinh la "chua ai chon", dung nhu doan script trong `index.html` doc.
 */
export type ThemePreference = Theme | "system";

const STORAGE_KEY = "scarlet-theme";
/**
 * T-3.12 — trang Cai dat co o chon theme THU HAI canh nut o header. Hai noi
 * giu hai `useState` thi bam mot ben xong ben kia noi sai ("Toi" trong luc
 * trang da toi). Moi lan DOI theme DANG HIEN phat su kien nay; moi
 * `useTheme()` dang song nghe no va theo. Khong doc `data-theme` — xem khoi
 * ngay tren.
 */
const THEME_EVENT = "scarlet:theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function storedTheme(): Theme | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved === "light" || saved === "dark" ? saved : null;
  } catch {
    // che do rieng tu co the chan localStorage — coi nhu chua ai bam gi
    return null;
  }
}

function systemTheme(): Theme {
  // `window.matchMedia` vang mat trong jsdom va trong vai WebView cu.
  return window.matchMedia?.(DARK_QUERY).matches ? "dark" : "light";
}

/** Lua chon da luu thang he dieu hanh; khong co ca hai thi sang. */
export function initialTheme(): Theme {
  return storedTheme() ?? systemTheme();
}

/** Lua chon da luu, `system` khi chua ai chon — tab Giao dien (T-S.11). */
export function storedPreference(): ThemePreference {
  return storedTheme() ?? "system";
}

export function resolveTheme(preference: ThemePreference): Theme {
  return preference === "system" ? systemTheme() : preference;
}

/**
 * Doi theme DANG HIEN, KHONG luu — "xem truoc" cua tab Giao dien (ban T-HD9:
 * *"Giao dien doi ngay khi chon de ban xem truoc. Bam Luu de giu lua chon"*).
 */
export function showTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  window.dispatchEvent(new CustomEvent<Theme>(THEME_EVENT, { detail: theme }));
}

/**
 * Nghe moi lan theme DANG HIEN doi (xem truoc, luu, nut header). Tra ham go.
 * Tab Giao dien dung no de biet nut header vua luu mot lua chon khac.
 */
export function onThemeChange(listener: () => void): () => void {
  window.addEventListener(THEME_EVENT, listener);
  return () => window.removeEventListener(THEME_EVENT, listener);
}

/** Luu lua chon roi hien no. `system` = XOA khoa, khong ghi chu "system". */
export function saveThemePreference(preference: ThemePreference): void {
  try {
    if (preference === "system") {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, preference);
    }
  } catch {
    // che do rieng tu co the chan localStorage — bo qua, khong lam vo app
  }
  showTheme(resolveTheme(preference));
}

/**
 * Theme DANG HIEN + ham doi-va-luu — nut header (T-0.10) va tab Giao dien.
 *
 * T-S.11: luc mount KHONG con ghi `localStorage` (truoc day effect ghi theme
 * ban dau vao khoa, tuc "theo he dieu hanh" bien thanh mot lua chon co dinh
 * ngay lan mo app dau tien). Chi `setTheme`/`saveThemePreference` ghi.
 */
export function useTheme(): [Theme, (next: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    const follow = (e: Event) => {
      const next = (e as CustomEvent<Theme>).detail;
      if (next === "light" || next === "dark") {
        setThemeState(next);
      }
    };
    window.addEventListener(THEME_EVENT, follow);
    return () => window.removeEventListener(THEME_EVENT, follow);
  }, []);

  useEffect(() => {
    // "Theo he thong" (ban T-HD9: *"Doi theo cai dat cua may"*) theo SONG khi
    // he dieu hanh doi, khong chi doc mot lan luc tai trang.
    const list = window.matchMedia?.(DARK_QUERY);
    if (list === undefined) {
      return;
    }
    const follow = () => {
      if (storedTheme() === null) {
        showTheme(systemTheme());
      }
    };
    list.addEventListener("change", follow);
    return () => list.removeEventListener("change", follow);
  }, []);

  const setTheme = useCallback((next: Theme) => saveThemePreference(next), []);

  return [theme, setTheme];
}

/**
 * T-S.12 (header v2, NQ-128 b) — nut icon 44 × 44 cua ban T-HD2-v2
 * (`ShellHeader`): icon va ten noi theme SE CHUYEN SANG — dang sang thi `moon`
 * + "Chuyen sang theme toi", dang toi thi `sun` + "Chuyen sang theme sang".
 * Doi qua lai bang lo xo `themeToggle` (settle) cua T-HD5-v2 muc 7.
 *
 * `MotionV2.tsx` cua T-HD5-v2 ve nguoc (`dark ? "moon" : "sun"`, icon = theme
 * DANG HIEN); ban T-HD2-v2 co ten truy cap di kem nen di theo no — B-306.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const dark = theme === "dark";

  return (
    <button
      type="button"
      aria-label={dark ? t("theme.switchToLight") : t("theme.switchToDark")}
      onClick={() => setTheme(dark ? "light" : "dark")}
      // T-S.19a — nut chi con trong dao (ban Khung chinh v3: tron, nen kinh, icon 18).
      className="motion-control grid size-touch shrink-0 place-items-center rounded-full text-foreground hover:bg-glass-hover"
    >
      <Icon icon={dark ? Sun : Moon} spring="themeToggle" size={18} />
    </button>
  );
}
