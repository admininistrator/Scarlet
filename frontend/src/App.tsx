import { ThemeToggle } from "./components/ui/ThemeToggle";
import { t } from "./lib/i18n";

export default function App() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <h1 className="text-lg font-semibold">{t("app.title")}</h1>
        <ThemeToggle />
      </header>
      <main className="px-6 py-8">
        <p className="text-muted">{t("app.tagline")}</p>
      </main>
    </div>
  );
}
