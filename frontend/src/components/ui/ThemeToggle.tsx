import { useEffect, useState } from "react";
import { t } from "../../lib/i18n";

type Theme = "light" | "dark";

function readTheme(): Theme {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("scarlet-theme", theme);
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
      className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
    >
      {nextLabel}
    </button>
  );
}
